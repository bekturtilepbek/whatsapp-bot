"""Фото товара (FEATURES.md 4.3/4.4/6.8) — чтение и запись."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
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


async def get_product_image(
    session: AsyncSession, product_id: uuid.UUID, photo_id: uuid.UUID
) -> ProductImage | None:
    """Скоуп по product_id И photo_id вместе — чужое фото не находится
    (тот же принцип, что db.products.get_product). Вызывающий (api-роутер)
    сам уже проверил, что product_id принадлежит нужному bot_id, до этого
    вызова — здесь второй уровень скоупа поверх первого."""
    stmt = select(ProductImage).where(
        ProductImage.product_id == product_id, ProductImage.id == photo_id
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_product_image(
    session: AsyncSession,
    product_id: uuid.UUID,
    *,
    id: uuid.UUID,
    storage_key: str,
    mime_type: str,
    position: int,
) -> ProductImage:
    """id передаётся явно (не полагаемся на server_default) — storage_key
    строится из photo_id ДО вставки строки (см. api.product_photos), а
    Storage.put() должен успеть до commit, значит id нужен заранее."""
    image = ProductImage(
        id=id,
        product_id=product_id,
        storage_key=storage_key,
        mime_type=mime_type,
        position=position,
    )
    session.add(image)
    await session.flush()
    return image


async def delete_product_image(
    session: AsyncSession, product_id: uuid.UUID, photo_id: uuid.UUID
) -> bool:
    image = await get_product_image(session, product_id, photo_id)
    if image is None:
        return False
    await session.delete(image)
    await session.flush()
    return True


async def next_position(session: AsyncSession, product_id: uuid.UUID) -> int:
    """max(position) + 1, не count() — удаление создаёт дыры в позициях,
    переиспользовать их нельзя (UniqueConstraint(product_id, position) не
    единственная причина: две функции, использующие переиспользованную
    позицию, легко перезаписали бы друг друга по смыслу порядка)."""
    stmt = select(func.coalesce(func.max(ProductImage.position), -1) + 1).where(
        ProductImage.product_id == product_id
    )
    result = await session.execute(stmt)
    return result.scalar_one()
