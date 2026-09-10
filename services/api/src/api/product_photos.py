"""Валидация и подготовка фото товара к загрузке (FEATURES.md 6.8).

Два уровня проверки: validate_photo_uploads — дешёвая, по метаданным
(количество/тип/размер), до чтения тела файлов; read_and_resize_photo —
раскодирование Pillow (заодно и валидация: битый файл здесь становится
PhotoValidationError, не мусором в Storage) + ресайз до
PHOTO_RESIZE_MAX_DIMENSION по длинной стороне, формат не меняется.
"""

from __future__ import annotations

import asyncio
import io
import uuid

from fastapi import UploadFile
from PIL import Image

ALLOWED_PHOTO_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
MAX_PHOTOS_PER_PRODUCT = 10
PHOTO_RESIZE_MAX_DIMENSION = 1280

_PIL_FORMAT_BY_MIME = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class PhotoValidationError(Exception):
    pass


def validate_photo_uploads(uploads: list[UploadFile], *, max_count: int) -> None:
    if not uploads:
        raise PhotoValidationError("at least one photo is required")
    if len(uploads) > max_count:
        raise PhotoValidationError(f"at most {max_count} photos allowed")
    for upload in uploads:
        if upload.content_type not in ALLOWED_PHOTO_MIME_TYPES:
            raise PhotoValidationError(f"unsupported photo type: {upload.content_type}")
        if upload.size is not None and upload.size > MAX_PHOTO_SIZE_BYTES:
            raise PhotoValidationError(f"photo too large: {upload.filename}")


async def read_and_resize_photo(upload: UploadFile) -> tuple[bytes, str]:
    raw = await upload.read()
    mime_type = upload.content_type or "application/octet-stream"
    save_format = _PIL_FORMAT_BY_MIME.get(mime_type, "JPEG")
    try:
        data = await asyncio.to_thread(_decode_resize_encode, raw, save_format)
    except Exception as exc:
        raise PhotoValidationError(f"invalid image file: {upload.filename}") from exc
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


def build_photo_storage_key(bot_id: uuid.UUID, product_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return f"bots/{bot_id}/products/{product_id}/{photo_id}"
