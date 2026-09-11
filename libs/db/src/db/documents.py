"""Файлы бота (FEATURES.md 4.8/4.9, 6.7): список для system prompt, точный
поиск для тулзы send_document, CRUD для кабинета (create/delete)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Document


async def list_documents(
    session: AsyncSession, bot_id: uuid.UUID, *, limit: int = 200
) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.bot_id == bot_id)
        .order_by(Document.filename)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_document_by_filename(
    session: AsyncSession, bot_id: uuid.UUID, filename: str
) -> Document | None:
    """Точное совпадение с учётом регистра — имена файлов, в отличие от
    разговорных названий товаров (4.1/4.2), не нормализуются: LLM видит
    точное имя в documents_context и должна передать его как есть."""
    stmt = select(Document).where(Document.bot_id == bot_id, Document.filename == filename)
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_document(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    id: uuid.UUID,
    filename: str,
    storage_key: str,
    mime_type: str,
) -> Document:
    """id передаётся явно вызывающим кодом (генерируется ДО этого вызова,
    т.к. storage_key уже должен включать его — Storage.put() пишется раньше
    этой функции, тот же порядок, что и у create_product_image), а не
    полагается на server_default гена БД — иначе storage_key и
    Document.id разъедутся."""
    document = Document(
        id=id, bot_id=bot_id, filename=filename, storage_key=storage_key, mime_type=mime_type
    )
    session.add(document)
    await session.flush()
    return document


async def delete_document(session: AsyncSession, bot_id: uuid.UUID, document_id: uuid.UUID) -> bool:
    """True — строка была и удалена. Storage-объект НЕ чистится (тот же
    осознанно принятый паттерн, что и product_images — orphan-объект в
    Storage дешевле, чем городить delete() в Storage-протоколе ради этого).
    Тот же паттерн select-затем-delete, что и db.products.delete_product —
    не bulk DELETE + rowcount (Result.rowcount не типизирован в базовом
    Result[Any], который возвращает session.execute)."""
    stmt = select(Document).where(Document.bot_id == bot_id, Document.id == document_id)
    result = await session.execute(stmt)
    document = result.scalars().first()
    if document is None:
        return False
    await session.delete(document)
    await session.flush()
    return True
