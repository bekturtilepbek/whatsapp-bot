"""worker.pipeline.audio.convert_to_mp3 — перекодирование голосового перед
STT (FEATURES.md 2.2). Тесты на реальное кодирование скипаются без ffmpeg
в окружении (тот же принцип, что и ffmpeg_available() у api/video.py) —
синтетический OGG-исходник генерируется через ffmpeg lavfi, без бинарной
фикстуры в репозитории.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest
from worker.pipeline.audio import AudioConversionError, convert_to_mp3, ffmpeg_available

_NEEDS_FFMPEG = pytest.mark.skipif(
    not ffmpeg_available(), reason="ffmpeg недоступен в этом окружении"
)


def _synthetic_ogg_bytes(*, duration: float = 1.0) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-c:a",
            "libopus",
            "-f",
            "ogg",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout


@_NEEDS_FFMPEG
async def test_converts_real_ogg_to_mp3_without_raising() -> None:
    raw = _synthetic_ogg_bytes()
    mp3 = await convert_to_mp3(raw)
    assert len(mp3) > 0
    assert mp3[:3] == b"ID3" or mp3[:2] == b"\xff\xfb"  # валидный mp3-заголовок


@_NEEDS_FFMPEG
async def test_invalid_audio_bytes_raise_conversion_error() -> None:
    with pytest.raises(AudioConversionError):
        await convert_to_mp3(b"this is not a real audio file")


async def test_missing_ffmpeg_binary_raises_conversion_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker.pipeline.audio as audio_module

    monkeypatch.setattr(audio_module.shutil, "which", lambda _: None)
    with pytest.raises(AudioConversionError):
        await convert_to_mp3(b"irrelevant, never reaches ffmpeg")


async def test_timeout_kills_the_process_and_raises_conversion_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker.pipeline.audio as audio_module

    killed = False

    class _FakeProcess:
        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return b"", b""

        def kill(self) -> None:
            nonlocal killed
            killed = True

        async def wait(self) -> None:
            return None

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> _FakeProcess:
        return _FakeProcess()

    monkeypatch.setattr(audio_module.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(audio_module, "AUDIO_CONVERT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        audio_module.asyncio, "create_subprocess_exec", fake_create_subprocess_exec
    )

    with pytest.raises(AudioConversionError):
        await convert_to_mp3(b"irrelevant")
    assert killed
