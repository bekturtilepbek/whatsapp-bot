"""Фото товара (FEATURES.md 4.3/4.4). Загрузка — Волна 3 (CRUD, 6.8),
здесь только чтение для отправки карточки."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProductImage


async def list_product_images(session: AsyncSession, product_id: uuid.UUID) -> list[ProductImage]:
    stmt = (
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
