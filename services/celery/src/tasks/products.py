"""FEATURES.md 4.1/6.8: подстраховка на случай, если синхронная попытка
эмбеддинга в services/api (create/update товара) не удалась. Идемпотентна —
читает АКТУАЛЬНЫЕ name/description из БД на момент срабатывания (не то, что
было в HTTP-запросе, поставившем задачу — на случай что товар успели
отредактировать ещё раз), апсертит вектор.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from db.engine import make_engine, make_session_factory
from db.models import Product
from db.product_embeddings import upsert_embedding
from llm.embeddings import generate_embedding, product_embedding_input
from scheduling.celery_app import celery_app
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger("tasks.products")


async def _recompute_async(
    session_factory: async_sessionmaker[AsyncSession], product_id: str
) -> None:
    async with session_factory() as session:
        product = await session.get(Product, uuid.UUID(product_id))
        if product is None:
            logger.info("embedding recompute skipped: product deleted", product_id=product_id)
            return
        text = product_embedding_input(product.name, product.description)
        embedding = await generate_embedding(text)
        await upsert_embedding(session, product.id, embedding)
        await session.commit()
        logger.info("embedding recomputed", product_id=product_id)


async def _run(product_id: str) -> None:
    engine = make_engine()
    session_factory = make_session_factory(engine)
    try:
        await _recompute_async(session_factory, product_id)
    finally:
        await engine.dispose()


@celery_app.task(name=RECOMPUTE_PRODUCT_EMBEDDING)  # type: ignore[untyped-decorator]  # celery не публикует py.typed — декоратор неизбежно нетипизирован
def recompute_product_embedding(product_id: str) -> None:
    asyncio.run(_run(product_id))
