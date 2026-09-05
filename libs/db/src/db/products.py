"""Каталог товаров бота (FEATURES.md 3.4): чтение для контекста LLM.
CRUD — Волна 3 (6.8), здесь только то, что нужно 3.4.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
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
