"""api.product_media: валидация метаданных загрузки (тип/размер/количество)
и обработка (Pillow decode+resize для фото — decode здесь же служит
валидацией, битый файл -> MediaValidationError, не мусор в Storage;
compress_video для видео, FEATURES.md 4.4 ревизия). Без Docker/ffmpeg — эти
тесты юнит-уровня, video-обработка мокает compress_video напрямую.
"""

from __future__ import annotations

import io
import uuid
from typing import BinaryIO

import pytest
from api import product_media as product_media_module
from api.product_media import (
    MAX_MEDIA_PER_PRODUCT,
    MAX_PHOTO_SIZE_BYTES,
    MAX_VIDEO_SIZE_BYTES,
    PHOTO_RESIZE_MAX_DIMENSION,
    MediaValidationError,
    build_media_storage_key,
    process_media_upload,
    validate_media_uploads,
)
from api.video import VideoCompressionError
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


def test_validate_media_uploads_rejects_empty_list() -> None:
    with pytest.raises(MediaValidationError):
        validate_media_uploads([], max_count=MAX_MEDIA_PER_PRODUCT)


def test_validate_media_uploads_rejects_more_than_max_count() -> None:
    uploads = [_make_upload(b"x", content_type="image/jpeg") for _ in range(3)]
    with pytest.raises(MediaValidationError):
        validate_media_uploads(uploads, max_count=2)


def test_validate_media_uploads_rejects_unsupported_mime_type() -> None:
    upload = _make_upload(b"not an image", content_type="text/plain")
    with pytest.raises(MediaValidationError):
        validate_media_uploads([upload], max_count=MAX_MEDIA_PER_PRODUCT)


def test_validate_media_uploads_rejects_oversized_photo() -> None:
    upload = _make_upload(b"x" * (MAX_PHOTO_SIZE_BYTES + 1), content_type="image/jpeg")
    with pytest.raises(MediaValidationError):
        validate_media_uploads([upload], max_count=MAX_MEDIA_PER_PRODUCT)


def test_validate_media_uploads_accepts_a_valid_photo() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(), content_type="image/jpeg")
    validate_media_uploads([upload], max_count=MAX_MEDIA_PER_PRODUCT)  # не бросает


def test_validate_media_uploads_accepts_a_valid_video() -> None:
    upload = _make_upload(
        b"x" * 1000, content_type="video/mp4", filename="clip.mp4"
    )
    validate_media_uploads([upload], max_count=MAX_MEDIA_PER_PRODUCT)  # не бросает


def test_validate_media_uploads_rejects_oversized_video() -> None:
    upload = _make_upload(
        b"x" * (MAX_VIDEO_SIZE_BYTES + 1), content_type="video/mp4", filename="clip.mp4"
    )
    with pytest.raises(MediaValidationError):
        validate_media_uploads([upload], max_count=MAX_MEDIA_PER_PRODUCT)


def test_validate_media_uploads_rejects_unsupported_video_container() -> None:
    # FEATURES.md 4.4 ревизия: сознательно только video/mp4 на входе, не
    # весь список V1 (video/webm/video/quicktime).
    upload = _make_upload(b"x" * 1000, content_type="video/webm", filename="clip.webm")
    with pytest.raises(MediaValidationError):
        validate_media_uploads([upload], max_count=MAX_MEDIA_PER_PRODUCT)


async def test_process_media_upload_returns_bytes_and_mime_type_for_photo() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(), content_type="image/jpeg")

    data, mime_type = await process_media_upload(upload)

    assert mime_type == "image/jpeg"
    assert Image.open(io.BytesIO(data)).format == "JPEG"


async def test_process_media_upload_shrinks_large_images() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(size=(2000, 1000)), content_type="image/jpeg")

    data, _ = await process_media_upload(upload)

    resized = Image.open(io.BytesIO(data))
    assert resized.width <= PHOTO_RESIZE_MAX_DIMENSION
    assert resized.height <= PHOTO_RESIZE_MAX_DIMENSION


async def test_process_media_upload_keeps_small_images_unchanged_in_size() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(size=(20, 20)), content_type="image/jpeg")

    data, _ = await process_media_upload(upload)

    resized = Image.open(io.BytesIO(data))
    assert resized.size == (20, 20)


async def test_process_media_upload_rejects_corrupt_photo() -> None:
    upload = _make_upload(b"this is not a real image file", content_type="image/jpeg")

    with pytest.raises(MediaValidationError):
        await process_media_upload(upload)


async def test_process_media_upload_compresses_video_and_forces_mp4_mime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_compress_video(raw: bytes) -> bytes:
        return b"compressed:" + raw

    monkeypatch.setattr(product_media_module, "compress_video", fake_compress_video)
    upload = _make_upload(b"raw video bytes", content_type="video/mp4", filename="clip.mp4")

    data, mime_type = await process_media_upload(upload)

    assert data == b"compressed:raw video bytes"
    assert mime_type == "video/mp4"


async def test_process_media_upload_rejects_video_compression_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_compress_video(raw: bytes) -> bytes:
        raise VideoCompressionError("ffmpeg exploded")

    monkeypatch.setattr(product_media_module, "compress_video", failing_compress_video)
    upload = _make_upload(b"raw video bytes", content_type="video/mp4", filename="clip.mp4")

    with pytest.raises(MediaValidationError):
        await process_media_upload(upload)


def test_build_media_storage_key_format() -> None:
    bot_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    product_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    media_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    key = build_media_storage_key(bot_id, product_id, media_id)

    assert key == (
        "bots/11111111-1111-1111-1111-111111111111/"
        "products/22222222-2222-2222-2222-222222222222/"
        "33333333-3333-3333-3333-333333333333"
    )
