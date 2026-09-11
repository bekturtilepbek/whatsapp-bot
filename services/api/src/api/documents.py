"""Валидация загрузки документа бота (FEATURES.md 6.7).

Любой тип файла (эталон V1: send_document уже отправляет "любой тип",
см. libs/tools/src/tools/send_document.py) — проверяем только размер по
метаданным, до чтения тела в память. Ресайза/декодирования нет (в отличие
от фото товара, 6.8) — документ хранится как есть.
"""

from __future__ import annotations

import uuid

from fastapi import UploadFile

MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024


class DocumentValidationError(Exception):
    pass


def validate_document_upload(upload: UploadFile) -> None:
    if not upload.filename or not upload.filename.strip():
        raise DocumentValidationError("filename is required")
    if upload.size is not None and upload.size > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentValidationError(f"file too large: {upload.filename}")


def build_document_storage_key(bot_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"bots/{bot_id}/documents/{document_id}"
