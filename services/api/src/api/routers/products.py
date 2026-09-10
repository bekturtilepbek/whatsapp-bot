"""GET/POST/PATCH/DELETE /bots/{bot_id}/products (FEATURES.md 6.8, Волна 3,
первая половина — CRUD без фото). Обязательно только name; price/sku/
description опциональны, display_custom — "всё или ничего" (см.
db.product_search._resolve_display_config, не меняется).

Эмбеддинг (FEATURES.md 4.1) строится только из name+description
(llm.embeddings.product_embedding_input) — синхронная попытка в этом же
HTTP-запросе (generate_embedding уже со своим ретраем); если и она не
удалась — товар всё равно сохраняется, ставится идемпотентная Celery-
задача-подстраховка (services/celery/src/tasks/products.py). См.
docs/superpowers/specs/2026-09-10-product-crud-design.md — этот дизайн
пользователь пометил как вероятного кандидата на пересмотр.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from db.bots import get_bot
from db.models import Product
from db.product_embeddings import upsert_embedding
from db.products import create_product, delete_product, get_product, list_products, update_product
from fastapi import APIRouter, HTTPException
from llm.embeddings import generate_embedding, product_embedding_input
from scheduling.celery_app import celery_app
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionDep
from ..schemas.products import ProductCreate, ProductOut, ProductPatch

router = APIRouter(prefix="/bots", tags=["products"])
logger = structlog.get_logger("api.products")

PRODUCT_EMBEDDING_SCHEDULE_TIMEOUT_SECONDS = 5.0


async def _recompute_embedding(session: AsyncSession, product: Product) -> None:
    """Синхронная попытка (с уже встроенным в generate_embedding ретраем);
    при сбое — не роняем запрос, ставим Celery-подстраховку."""
    text = product_embedding_input(product.name, product.description)
    try:
        embedding = await generate_embedding(text)
    except Exception:
        logger.warning(
            "embedding generation failed, scheduling retry",
            product_id=str(product.id),
            exc_info=True,
        )
        await _schedule_embedding_retry(product.id)
        return
    await upsert_embedding(session, product.id, embedding)
    await session.commit()


async def _schedule_embedding_retry(product_id: uuid.UUID) -> None:
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                celery_app.send_task,
                RECOMPUTE_PRODUCT_EMBEDDING,
                args=[str(product_id)],
            ),
            timeout=PRODUCT_EMBEDDING_SCHEDULE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "failed to schedule embedding recompute", product_id=str(product_id), exc_info=True
        )


@router.get("/{bot_id}/products", response_model=list[ProductOut])
async def list_products_route(bot_id: uuid.UUID, session: SessionDep) -> list[ProductOut]:
    products = await list_products(session, bot_id)
    return [ProductOut.model_validate(p) for p in products]


@router.post("/{bot_id}/products", response_model=ProductOut, status_code=201)
async def create_product_route(
    bot_id: uuid.UUID, body: ProductCreate, session: SessionDep
) -> ProductOut:
    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")

    product = await create_product(
        session,
        bot_id,
        name=name,
        price=body.price,
        sku=body.sku,
        description=body.description,
        display_custom=body.display_custom,
    )
    await session.commit()
    await _recompute_embedding(session, product)
    return ProductOut.model_validate(product)


@router.get("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def get_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep
) -> ProductOut:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return ProductOut.model_validate(product)


@router.patch("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def patch_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, patch: ProductPatch, session: SessionDep
) -> ProductOut:
    data = patch.model_dump(exclude_unset=True)
    if "name" in data and not (data["name"] or "").strip():
        raise HTTPException(status_code=422, detail="name must not be empty")

    before = await get_product(session, bot_id, product_id)
    if before is None:
        raise HTTPException(status_code=404, detail="product not found")
    old_name, old_description = before.name, before.description

    new_name = data["name"].strip() if "name" in data else None
    product = await update_product(
        session,
        bot_id,
        product_id,
        name=new_name,
        price=data.get("price"),
        sku=data.get("sku"),
        description=data.get("description"),
        display_custom=data.get("display_custom"),
    )
    assert product is not None  # проверено выше через before
    await session.commit()

    if product.name != old_name or product.description != old_description:
        await _recompute_embedding(session, product)

    return ProductOut.model_validate(product)


@router.delete("/{bot_id}/products/{product_id}", status_code=204)
async def delete_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep
) -> None:
    deleted = await delete_product(session, bot_id, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="product not found")
    await session.commit()
