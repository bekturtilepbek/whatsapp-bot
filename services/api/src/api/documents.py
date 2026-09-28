"""Валидация загрузки документа бота (FEATURES.md 6.7).

Любой тип файла (эталон V1: send_document уже отправляет "любой тип",
см. libs/tools/src/tools/send_document.py) — проверяем только размер по
метаданным, до чтения тела в память. Ресайза/декодирования нет (в отличие
от фото товара, 6.8) — документ хранится как есть.

Имя файла отдельно санитизируется на запись (не на чтение) — оно летит
как есть в documents_context -> системный промпт бота
(libs/llm/src/llm/documents_context.py), построчно. Управляющий символ
(перенос строки прежде всего) в имени — реальный prompt injection в
промпт, который видят ВСЕ клиенты этого бота, не только загрузивший файл.
Отклоняем загрузку (422), не обрезаем/заменяем символы молча — тот же
принцип, что и у пустого имени бота/товара в этом проекте.
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
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in upload.filename):
        raise DocumentValidationError("filename must not contain control characters")
    # Пустой файл бот отправил бы клиенту как 0-байтную пустышку (2026-09-28).
    if upload.size == 0:
        raise DocumentValidationError(f"file is empty: {upload.filename}")
    if upload.size is not None and upload.size > MAX_DOCUMENT_SIZE_BYTES:
        raise DocumentValidationError(f"file too large: {upload.filename}")


def build_document_storage_key(bot_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"bots/{bot_id}/documents/{document_id}"
