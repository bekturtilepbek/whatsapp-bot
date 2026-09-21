"""Сжатие видео при загрузке (FEATURES.md 4.9 ревизия) — тот же смысл, что
и ресайз фото товара (product_media.py::process_media_upload): клиент
грузит тяжёлый файл как есть, отправка клиентам платформы раздувает
трафик/место. Первое появление ffmpeg в проекте (голосовая транскрипция,
2.2, была отложена пользователем и не реализована).

Сбой (битый файл, ffmpeg не установлен, таймаут) — VideoCompressionError,
НЕ молчаливое сохранение необработанного оригинала: вызывающий (роутер)
отклоняет загрузку, а не тихо теряет сжатие (подтверждено пользователем).
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

VIDEO_COMPRESS_TIMEOUT_SECONDS = 60.0
# Кап по высоте, как у фото товара (PHOTO_RESIZE_MAX_DIMENSION=1280) — своё
# число, не то же самое: видео тяжелее фото при той же высоте, 720p —
# разумный компромисс "смотрибельно, но не раздувает трафик".
VIDEO_MAX_HEIGHT = 720


class VideoCompressionError(Exception):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


async def compress_video(raw: bytes) -> bytes:
    """Перекодирует видео через ffmpeg: кап по высоте VIDEO_MAX_HEIGHT
    (сохраняя пропорции; если исходник уже ниже — не увеличиваем), H.264 +
    AAC, контейнер mp4."""
    if not ffmpeg_available():
        raise VideoCompressionError("ffmpeg is not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "input"
        dst = Path(tmp_dir) / "output.mp4"
        src.write_bytes(raw)

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"scale=-2:'min({VIDEO_MAX_HEIGHT},ih)'",
            "-c:v",
            "libx264",
            "-crf",
            "28",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(dst),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=VIDEO_COMPRESS_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise VideoCompressionError("ffmpeg timed out") from exc

        if process.returncode != 0 or not dst.exists():
            raise VideoCompressionError(stderr.decode(errors="replace"))

        return dst.read_bytes()
