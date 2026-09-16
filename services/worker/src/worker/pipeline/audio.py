"""Перекодирование голосового в mp3 перед STT (FEATURES.md 2.2) — WhatsApp
отдаёт голосовые в OGG/Opus, Whisper (`llm.client.transcribe_audio`) их
официально не поддерживает; тот же приём, что в V1 (ffmpeg -> mp3 -> STT).

Второе появление ffmpeg в проекте (первое — сжатие видео при загрузке,
`services/api/src/api/video.py`, FEATURES.md 4.9 ревизия) — отдельный
модуль, не общий пакет: разные сервисы (свои Docker-образы), разные
задачи (конвертация формата, не ресайз/сжатие).

Сбой (битый файл, ffmpeg не установлен, таймаут) — AudioConversionError,
вызывающий (consumer.py) деградирует в тот же fallback, что и на любой
другой сбой vision/pdf-путей.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

AUDIO_CONVERT_TIMEOUT_SECONDS = 30.0


class AudioConversionError(Exception):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


async def convert_to_mp3(raw: bytes) -> bytes:
    """Перекодирует произвольный аудио-контейнер (OGG/Opus от WhatsApp и
    т.п.) в mp3 — формат, который точно принимает Whisper."""
    if not ffmpeg_available():
        raise AudioConversionError("ffmpeg is not installed")

    with tempfile.TemporaryDirectory() as tmp_dir:
        src = Path(tmp_dir) / "input"
        dst = Path(tmp_dir) / "output.mp3"
        src.write_bytes(raw)

        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            str(dst),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=AUDIO_CONVERT_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AudioConversionError("ffmpeg timed out") from exc

        if process.returncode != 0 or not dst.exists():
            raise AudioConversionError(stderr.decode(errors="replace"))

        return dst.read_bytes()
