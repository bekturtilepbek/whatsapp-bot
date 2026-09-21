"""GET/POST/DELETE /bots/{bot_id}/documents (FEATURES.md 6.7). Загрузка —
multipart/form-data, один файл за раз. Любой тип, лимит по размеру
(MAX_DOCUMENT_SIZE_BYTES) — см. ../documents.py. Дубликат имени файла в
рамках бота (uq_documents_bot_filename) — явная проверка до вставки, 409,
не try/except на IntegrityError (тот же паттерн, что и users.py после
фикс-раунда 6.18)."""

from __future__ import annotations

import uuid

from db.bots import get_bot
from db.documents import (
    create_document,
    delete_document,
    find_document_by_filename,
    list_documents,
)
from fastapi import APIRouter, File, HTTPException, UploadFile

from ..db import SessionDep
from ..documents import (
    DocumentValidationError,
    build_document_storage_key,
    validate_document_upload,
)
from ..schemas.documents import DocumentOut
from ..security import BotAccessUser
from ..storage import StorageDep
from ..video import VideoCompressionError, compress_video

router = APIRouter(prefix="/bots", tags=["documents"])


@router.get("/{bot_id}/documents", response_model=list[DocumentOut])
async def list_documents_route(
    bot_id: uuid.UUID, session: SessionDep, user: BotAccessUser
) -> list[DocumentOut]:
    documents = await list_documents(session, bot_id)
    return [DocumentOut.model_validate(d) for d in documents]


@router.post("/{bot_id}/documents", response_model=DocumentOut, status_code=201)
async def create_document_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    user: BotAccessUser,
    file: UploadFile = File(...),  # noqa: B008
) -> DocumentOut:
    try:
        validate_document_upload(file)
    except DocumentValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")

    assert file.filename is not None  # проверено validate_document_upload
    if await find_document_by_filename(session, bot_id, file.filename) is not None:
        raise HTTPException(status_code=409, detail="a document with this filename already exists")

    document_id = uuid.uuid4()
    key = build_document_storage_key(bot_id, document_id)
    mime_type = file.content_type or "application/octet-stream"
    data = await file.read()
    if mime_type.startswith("video/"):
        # FEATURES.md 4.9 ревизия: видео грузится как есть, в отличие от
        # фото товара (product_media.py), которое ужимается всегда —
        # отклоняем загрузку, а не сохраняем необработанный оригинал молча.
        try:
            data = await compress_video(data)
        except VideoCompressionError as exc:
            raise HTTPException(status_code=422, detail=f"video compression failed: {exc}") from exc
        mime_type = "video/mp4"  # compress_video всегда перекодирует в mp4
    try:
        await storage.put(key, data, mime_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="failed to store document") from exc

    document = await create_document(
        session,
        bot_id,
        id=document_id,
        filename=file.filename,
        storage_key=key,
        mime_type=mime_type,
    )
    await session.commit()
    return DocumentOut.model_validate(document)


@router.delete("/{bot_id}/documents/{document_id}", status_code=204)
async def delete_document_route(
    bot_id: uuid.UUID, document_id: uuid.UUID, session: SessionDep, user: BotAccessUser
) -> None:
    deleted = await delete_document(session, bot_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="document not found")
    await session.commit()
