"""Файлы бота (FEATURES.md 4.8/4.9). Загрузка — Волна 3 (CRUD, 6.7),
здесь только чтение: список для system prompt и точный поиск для тулзы.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Document


async def list_documents(session: AsyncSession, bot_id: uuid.UUID) -> list[Document]:
    stmt = select(Document).where(Document.bot_id == bot_id).order_by(Document.filename)
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
