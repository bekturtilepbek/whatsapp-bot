"""Каталог товаров бота: чтение для контекста LLM (FEATURES.md 3.4) и
CRUD (FEATURES.md 6.8, Волна 3, первая половина — без фото).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product

DEFAULT_CATALOG_LIMIT = 200


async def list_products(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    limit: int = DEFAULT_CATALOG_LIMIT,
    offset: int = 0,
) -> list[Product]:
    stmt = (
        select(Product)
        .where(Product.bot_id == bot_id)
        .order_by(Product.name)
        .limit(limit)
        .offset(offset)
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


async def get_product(
    session: AsyncSession, bot_id: uuid.UUID, product_id: uuid.UUID
) -> Product | None:
    """Скоуп по bot_id И product_id вместе — товар чужого бота не должен
    быть виден даже как "существует, но 403", а просто не находится (404)."""
    stmt = select(Product).where(Product.bot_id == bot_id, Product.id == product_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_product(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    name: str,
    price: Decimal | None = None,
    sku: str | None = None,
    description: str | None = None,
    display_custom: dict[str, Any] | None = None,
) -> Product:
    product = Product(
        bot_id=bot_id,
        name=name,
        price=price,
        sku=sku,
        description=description,
        display_custom=display_custom if display_custom is not None else {},
    )
    session.add(product)
    await session.flush()
    return product


async def update_product(
    session: AsyncSession,
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    name: str | None = None,
    price: Decimal | None = None,
    sku: str | None = None,
    description: str | None = None,
    display_custom: dict[str, Any] | None = None,
) -> Product | None:
    """Частичное обновление: None-параметр = не трогать это поле (тот же
    принцип, что и db.bots.update_bot) — значит explicit-сброс price/sku/
    description обратно в NULL этим путём недостижим, сознательно принятое
    ограничение (см. docs/superpowers/specs/2026-09-10-product-crud-design.md,
    "Явно отложено")."""
    product = await get_product(session, bot_id, product_id)
    if product is None:
        return None
    if name is not None:
        product.name = name
    if price is not None:
        product.price = price
    if sku is not None:
        product.sku = sku
    if description is not None:
        product.description = description
    if display_custom is not None:
        product.display_custom = display_custom
    await session.flush()
    return product


async def delete_product(session: AsyncSession, bot_id: uuid.UUID, product_id: uuid.UUID) -> bool:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        return False
    await session.delete(product)
    await session.flush()
    return True
