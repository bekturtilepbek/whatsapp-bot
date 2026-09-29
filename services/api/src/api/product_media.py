"""Валидация и подготовка медиа товара к загрузке (FEATURES.md 4.4/6.8).

Фото и видео в одной галерее — эталон V1 (node-bot3/whatsapp.js): товару
можно было прикрепить видео вперемешку с фото, реальный MIME определялся
по магическим байтам при отправке. Здесь — сознательно другой подход:
явный allow-list по заявленному content_type, не разбор содержимого файла.

Два уровня проверки: validate_media_uploads — дешёвая, по метаданным
(количество/тип/размер), до чтения тела файлов; process_media_upload —
ветвится по типу: фото — Pillow decode+resize (заодно и валидация: битый
файл здесь становится MediaValidationError, не мусором в Storage) до
PHOTO_RESIZE_MAX_DIMENSION по длинной стороне; видео — переиспользует
compress_video() (api.video, тот же путь, что и у 4.9 для документов),
720p cap, всегда перекодируется в video/mp4.
"""

from __future__ import annotations

import asyncio
import io
import uuid

from fastapi import UploadFile
from PIL import Image

from .video import VideoCompressionError, compress_video

ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
# Только mp4 на входе, сознательно уже, чем весь список V1 (video/webm,
# video/quicktime) — compress_video() сам прогоняет любой контейнер через
# ffmpeg, но легче начать с одного проверенного случая, чем заявлять
# поддержку форматов, которые никто не тестировал.
ALLOWED_VIDEO_MIME_TYPES = frozenset({"video/mp4"})
MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
# Тот же лимит, что и у документов (services/api/src/api/documents.py,
# MAX_DOCUMENT_SIZE_BYTES) — видео тяжелее фото, 10 МБ фото-лимита мало.
MAX_VIDEO_SIZE_BYTES = 20 * 1024 * 1024
MAX_MEDIA_PER_PRODUCT = 10
PHOTO_RESIZE_MAX_DIMENSION = 1280

_PIL_FORMAT_BY_MIME = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class MediaValidationError(Exception):
    pass


def validate_media_uploads(uploads: list[UploadFile], *, max_count: int) -> None:
    if not uploads:
        raise MediaValidationError("Нужно хотя бы одно фото или видео")
    if len(uploads) > max_count:
        raise MediaValidationError(f"Не больше {max_count} медиа у товара")
    for upload in uploads:
        if upload.content_type in ALLOWED_IMAGE_MIME_TYPES:
            if upload.size is not None and upload.size > MAX_PHOTO_SIZE_BYTES:
                raise MediaValidationError(f"Фото слишком большое: {upload.filename}")
        elif upload.content_type in ALLOWED_VIDEO_MIME_TYPES:
            if upload.size is not None and upload.size > MAX_VIDEO_SIZE_BYTES:
                raise MediaValidationError(f"Видео слишком большое: {upload.filename}")
        else:
            raise MediaValidationError(
                f"Этот тип файла не подходит: {upload.content_type} "
                "(нужно фото JPEG/PNG/WebP или видео MP4)"
            )


async def process_media_upload(upload: UploadFile) -> tuple[bytes, str]:
    raw = await upload.read()
    mime_type = upload.content_type or "application/octet-stream"
    if mime_type in ALLOWED_VIDEO_MIME_TYPES:
        try:
            data = await compress_video(raw)
        except VideoCompressionError as exc:
            raise MediaValidationError(
                f"Видео повреждено или не читается: {upload.filename}"
            ) from exc
        return data, "video/mp4"  # compress_video всегда перекодирует в mp4

    save_format = _PIL_FORMAT_BY_MIME.get(mime_type, "JPEG")
    try:
        data = await asyncio.to_thread(_decode_resize_encode, raw, save_format)
    except Exception as exc:
        raise MediaValidationError(f"Фото повреждено или не читается: {upload.filename}") from exc
    return data, mime_type


def _decode_resize_encode(raw: bytes, save_format: str) -> bytes:
    # Явная аннотация базовым Image.Image — convert() ниже возвращает именно
    # его, а не более узкий ImageFile, который выводит mypy из Image.open().
    image: Image.Image = Image.open(io.BytesIO(raw))
    image.load()  # Image.open ленив — decode форсируется тут, битые байты всплывают здесь
    if image.width > PHOTO_RESIZE_MAX_DIMENSION or image.height > PHOTO_RESIZE_MAX_DIMENSION:
        image.thumbnail((PHOTO_RESIZE_MAX_DIMENSION, PHOTO_RESIZE_MAX_DIMENSION))
    if save_format == "JPEG" and image.mode in ("RGBA", "P"):
        # JPEG не поддерживает альфа-канал/палитру — конвертируем, иначе
        # save() падает на PNG/GIF, ошибочно помеченных как image/jpeg.
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format=save_format)
    return buf.getvalue()


def build_media_storage_key(bot_id: uuid.UUID, product_id: uuid.UUID, media_id: uuid.UUID) -> str:
    return f"bots/{bot_id}/products/{product_id}/{media_id}"
