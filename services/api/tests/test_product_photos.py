"""api.product_photos: валидация метаданных загрузки (тип/размер/количество)
и раскодирование+ресайз (Pillow) — decode здесь же служит валидацией
(битый файл -> PhotoValidationError, не мусор в Storage). Без Docker — эти
тесты юнит-уровня, testcontainers не нужен.
"""

from __future__ import annotations

import io
import uuid
from typing import BinaryIO

import pytest
from api.product_photos import (
    MAX_PHOTO_SIZE_BYTES,
    MAX_PHOTOS_PER_PRODUCT,
    PHOTO_RESIZE_MAX_DIMENSION,
    PhotoValidationError,
    build_photo_storage_key,
    read_and_resize_photo,
    validate_photo_uploads,
)
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers


def _make_upload(data: bytes, *, content_type: str, filename: str = "photo.jpg") -> UploadFile:
    file: BinaryIO = io.BytesIO(data)
    # headers передаётся конструктору, не присваивается после — Starlette's
    # Headers иммутабелен (нет поддержки headers[...] = ...).
    headers = Headers({"content-type": content_type})
    return UploadFile(file=file, filename=filename, size=len(data), headers=headers)


def _tiny_jpeg_bytes(*, size: tuple[int, int] = (20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color="red").save(buf, format="JPEG")
    return buf.getvalue()


def test_validate_photo_uploads_rejects_empty_list() -> None:
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads([], max_count=MAX_PHOTOS_PER_PRODUCT)


def test_validate_photo_uploads_rejects_more_than_max_count() -> None:
    uploads = [_make_upload(b"x", content_type="image/jpeg") for _ in range(3)]
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads(uploads, max_count=2)


def test_validate_photo_uploads_rejects_unsupported_mime_type() -> None:
    upload = _make_upload(b"not an image", content_type="text/plain")
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads([upload], max_count=MAX_PHOTOS_PER_PRODUCT)


def test_validate_photo_uploads_rejects_oversized_file() -> None:
    upload = _make_upload(b"x" * (MAX_PHOTO_SIZE_BYTES + 1), content_type="image/jpeg")
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads([upload], max_count=MAX_PHOTOS_PER_PRODUCT)


def test_validate_photo_uploads_accepts_a_valid_photo() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(), content_type="image/jpeg")
    validate_photo_uploads([upload], max_count=MAX_PHOTOS_PER_PRODUCT)  # не бросает


async def test_read_and_resize_photo_returns_bytes_and_mime_type() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(), content_type="image/jpeg")

    data, mime_type = await read_and_resize_photo(upload)

    assert mime_type == "image/jpeg"
    assert Image.open(io.BytesIO(data)).format == "JPEG"


async def test_read_and_resize_photo_shrinks_large_images() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(size=(2000, 1000)), content_type="image/jpeg")

    data, _ = await read_and_resize_photo(upload)

    resized = Image.open(io.BytesIO(data))
    assert resized.width <= PHOTO_RESIZE_MAX_DIMENSION
    assert resized.height <= PHOTO_RESIZE_MAX_DIMENSION


async def test_read_and_resize_photo_keeps_small_images_unchanged_in_size() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(size=(20, 20)), content_type="image/jpeg")

    data, _ = await read_and_resize_photo(upload)

    resized = Image.open(io.BytesIO(data))
    assert resized.size == (20, 20)


async def test_read_and_resize_photo_rejects_corrupt_file() -> None:
    upload = _make_upload(b"this is not a real image file", content_type="image/jpeg")

    with pytest.raises(PhotoValidationError):
        await read_and_resize_photo(upload)


def test_build_photo_storage_key_format() -> None:
    bot_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    product_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    photo_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    key = build_photo_storage_key(bot_id, product_id, photo_id)

    assert key == (
        "bots/11111111-1111-1111-1111-111111111111/"
        "products/22222222-2222-2222-2222-222222222222/"
        "33333333-3333-3333-3333-333333333333"
    )
