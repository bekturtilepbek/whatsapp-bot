"""api.video.compress_video — сжатие видео при загрузке (FEATURES.md 4.9
ревизия): клиент грузит видео как есть — ужимаем по высоте, как фото
товара ужимаются до 1280px (product_media.py), только для видео.

Тесты, которым нужен настоящий ffmpeg (генерация синтетического исходника
через lavfi + само сжатие), помечены индивидуально — на машине
разработчика на момент написания ffmpeg не установлен вообще, но это тот
же принцип, что и docker_available() у тестов с testcontainers: где
ffmpeg есть (например, в собранном api-образе), тесты реально прогоняются.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest
from api.video import VIDEO_MAX_HEIGHT, VideoCompressionError, compress_video, ffmpeg_available

_NEEDS_FFMPEG = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg недоступен в этом окружении"
)


def _synthetic_video_bytes(*, height: int, duration: float = 1.0) -> bytes:
    """Генерирует валидный маленький mp4 через ffmpeg lavfi — без бинарной
    фикстуры в репозитории, работает везде, где есть сам ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size=640x{height}:rate=5",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=1000:duration={duration}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-f",
            "mp4",
            "-movflags",
            "frag_keyframe+empty_moov",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


def _video_height(data: bytes) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=height",
            "-of",
            "csv=p=0",
            "pipe:0",
        ],
        input=data,
        capture_output=True,
        check=True,
    )
    return int(result.stdout.strip())


@_NEEDS_FFMPEG
async def test_compresses_a_real_video_without_raising() -> None:
    raw = _synthetic_video_bytes(height=480)
    compressed = await compress_video(raw)
    assert len(compressed) > 0
    assert compressed[4:8] == b"ftyp"  # валидный mp4-контейнер


@_NEEDS_FFMPEG
async def test_downscales_video_taller_than_the_cap() -> None:
    raw = _synthetic_video_bytes(height=1080)
    compressed = await compress_video(raw)
    assert _video_height(compressed) <= VIDEO_MAX_HEIGHT


@_NEEDS_FFMPEG
async def test_does_not_upscale_video_shorter_than_the_cap() -> None:
    raw = _synthetic_video_bytes(height=240)
    compressed = await compress_video(raw)
    assert _video_height(compressed) == 240


@_NEEDS_FFMPEG
async def test_invalid_video_bytes_raise_compression_error() -> None:
    with pytest.raises(VideoCompressionError):
        await compress_video(b"this is not a real video file")


async def test_missing_ffmpeg_binary_raises_compression_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.video as video_module

    monkeypatch.setattr(video_module.shutil, "which", lambda _: None)
    with pytest.raises(VideoCompressionError):
        await compress_video(b"irrelevant, never reaches ffmpeg")


async def test_timeout_kills_the_process_and_raises_compression_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.video as video_module

    killed = False

    class _FakeProcess:
        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(10)  # дольше подменённого ниже таймаута
            return b"", b""

        def kill(self) -> None:
            nonlocal killed
            killed = True

        async def wait(self) -> None:
            return None

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return _FakeProcess()

    monkeypatch.setattr(video_module.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(video_module, "VIDEO_COMPRESS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        video_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    with pytest.raises(VideoCompressionError):
        await compress_video(b"irrelevant")
    assert killed
