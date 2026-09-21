"""Медиа товара — фото и видео (FEATURES.md 4.3/4.4/4.9/6.8) — чтение и запись."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProductMedia


async def list_product_media(session: AsyncSession, product_id: uuid.UUID) -> list[ProductMedia]:
    stmt = (
        select(ProductMedia)
        .where(ProductMedia.product_id == product_id)
        .order_by(ProductMedia.position)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_product_media_item(
    session: AsyncSession, product_id: uuid.UUID, media_id: uuid.UUID
) -> ProductMedia | None:
    """Скоуп по product_id И media_id вместе — чужой элемент не находится
    (тот же принцип, что db.products.get_product). Вызывающий (api-роутер)
    сам уже проверил, что product_id принадлежит нужному bot_id, до этого
    вызова — здесь второй уровень скоупа поверх первого."""
    stmt = select(ProductMedia).where(
        ProductMedia.product_id == product_id, ProductMedia.id == media_id
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_product_media_item(
    session: AsyncSession,
    product_id: uuid.UUID,
    *,
    id: uuid.UUID,
    storage_key: str,
    mime_type: str,
    position: int,
) -> ProductMedia:
    """id передаётся явно (не полагаемся на server_default) — storage_key
    строится из media_id ДО вставки строки (см. api.product_media), а
    Storage.put() должен успеть до commit, значит id нужен заранее."""
    media = ProductMedia(
        id=id,
        product_id=product_id,
        storage_key=storage_key,
        mime_type=mime_type,
        position=position,
    )
    session.add(media)
    await session.flush()
    return media


async def delete_product_media_item(
    session: AsyncSession, product_id: uuid.UUID, media_id: uuid.UUID
) -> bool:
    media = await get_product_media_item(session, product_id, media_id)
    if media is None:
        return False
    await session.delete(media)
    await session.flush()
    return True


async def next_position(session: AsyncSession, product_id: uuid.UUID) -> int:
    """max(position) + 1, не count() — удаление создаёт дыры в позициях,
    переиспользовать их нельзя (UniqueConstraint(product_id, position) не
    единственная причина: две функции, использующие переиспользованную
    позицию, легко перезаписали бы друг друга по смыслу порядка)."""
    stmt = select(func.coalesce(func.max(ProductMedia.position), -1) + 1).where(
        ProductMedia.product_id == product_id
    )
    result = await session.execute(stmt)
    return result.scalar_one()
