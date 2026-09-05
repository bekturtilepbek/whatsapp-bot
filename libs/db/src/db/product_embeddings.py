"""Эмбеддинги товаров для векторного поиска (FEATURES.md 4.1). Кто и
когда их считает — Волна 3 (CRUD, create/update товара); здесь только
хранение (upsert_embedding) и чтение (find_product_by_embedding).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, ProductEmbedding

DEFAULT_SIMILARITY_THRESHOLD = 0.4


async def upsert_embedding(
    session: AsyncSession, product_id: uuid.UUID, embedding: list[float]
) -> None:
    """Идемпотентно: product_id — PK, повторный вызов обновляет вектор,
    не дублирует строку."""
    stmt = (
        insert(ProductEmbedding)
        .values(product_id=product_id, embedding=embedding)
        .on_conflict_do_update(
            index_elements=["product_id"],
            set_={"embedding": embedding},
        )
    )
    await session.execute(stmt)
    await session.flush()


async def find_product_by_embedding(
    session: AsyncSession,
    bot_id: uuid.UUID,
    query_embedding: list[float],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Product | None:
    """Эталон V1 (vectorProductSearch): cosine similarity > threshold,
    ORDER BY similarity DESC, LIMIT 1 — ровно один товар, не список."""
    similarity = 1 - ProductEmbedding.embedding.cosine_distance(query_embedding)
    stmt = (
        select(Product)
        .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(Product.bot_id == bot_id, similarity > threshold)
        .order_by(similarity.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()
