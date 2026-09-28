"""api.documents.validate_document_upload — чистые юнит-тесты, без Docker
(FEATURES.md 6.7, санитизация имени файла — закрытие техдолга, замеченного
на финальных ревью Волн 1-2: control-символы в filename летят как есть в
documents_context -> system prompt бота, потенциальный prompt injection,
влияющий на ВСЕХ клиентов бота, не только загрузившего файл)."""

from __future__ import annotations

import io

from api.documents import (
    MAX_DOCUMENT_SIZE_BYTES,
    DocumentValidationError,
    validate_document_upload,
)
from fastapi import UploadFile


def _upload(filename: str | None, size: int | None = 100) -> UploadFile:
    return UploadFile(file=io.BytesIO(b""), filename=filename, size=size)


def test_valid_filename_passes() -> None:
    validate_document_upload(_upload("price-list.pdf"))


def test_missing_filename_raises() -> None:
    try:
        validate_document_upload(_upload(None))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_blank_filename_raises() -> None:
    try:
        validate_document_upload(_upload("   "))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_empty_file_raises() -> None:
    # Регрессия 2026-09-28: 0-байтный файл принимался — бот отправил бы клиенту пустышку.
    try:
        validate_document_upload(_upload("empty.txt", size=0))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_too_large_raises() -> None:
    try:
        validate_document_upload(_upload("big.pdf", size=MAX_DOCUMENT_SIZE_BYTES + 1))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_at_size_limit_passes() -> None:
    validate_document_upload(_upload("exact.pdf", size=MAX_DOCUMENT_SIZE_BYTES))


def test_filename_with_newline_raises() -> None:
    try:
        validate_document_upload(_upload("price.pdf\nDROP EVERYTHING"))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_filename_with_carriage_return_raises() -> None:
    try:
        validate_document_upload(_upload("price.pdf\rinjected"))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_filename_with_tab_raises() -> None:
    try:
        validate_document_upload(_upload("price\t.pdf"))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_filename_with_null_byte_raises() -> None:
    try:
        validate_document_upload(_upload("price\x00.pdf"))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_filename_with_del_raises() -> None:
    try:
        validate_document_upload(_upload("price\x7f.pdf"))
    except DocumentValidationError:
        pass
    else:
        raise AssertionError("expected DocumentValidationError")


def test_filename_with_spaces_and_cyrillic_passes() -> None:
    validate_document_upload(_upload("Прайс лист 2026.pdf"))
