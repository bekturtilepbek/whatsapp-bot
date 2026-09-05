"""Каталог товаров бота (FEATURES.md 3.4): чтение для контекста LLM.
CRUD — Волна 3 (6.8), здесь только то, что нужно 3.4.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product

DEFAULT_CATALOG_LIMIT = 200


async def list_products(
    session: AsyncSession, bot_id: uuid.UUID, *, limit: int = DEFAULT_CATALOG_LIMIT
) -> list[Product]:
    stmt = (
        select(Product)
        .where(Product.bot_id == bot_id)
        .order_by(Product.name)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_product_by_exact_name(
    session: AsyncSession, bot_id: uuid.UUID, name: str
) -> Product | None:
    """Точное регистронезависимое совпадение (эталон V1,
    vectorProductSearch: LOWER(TRIM(name)) = LOWER($1)) — НЕ подстрока/ILIKE.
    Идёт первым, до векторного поиска (db.product_embeddings)."""
    stmt = select(Product).where(
        Product.bot_id == bot_id,
        func.lower(func.trim(Product.name)) == func.lower(name.strip()),
    )
    result = await session.execute(stmt)
    return result.scalars().first()
