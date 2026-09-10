"""GET/POST/PATCH/DELETE /bots/{bot_id}/products (FEATURES.md 6.8). POST —
multipart/form-data, обязательно хотя бы одно фото. Обязательно только name;
price/sku/description опциональны, display_custom — "всё или ничего" (см.
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
import json
import uuid
from decimal import Decimal
from typing import Any

import structlog
from db.bots import get_bot
from db.models import Product
from db.product_embeddings import upsert_embedding
from db.product_images import create_product_image
from db.products import (
    DEFAULT_CATALOG_LIMIT,
    create_product,
    delete_product,
    get_product,
    list_products,
    update_product,
)
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from llm.embeddings import generate_embedding, product_embedding_input
from scheduling.celery_app import celery_app
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionDep
from ..product_photos import (
    MAX_PHOTOS_PER_PRODUCT,
    PhotoValidationError,
    build_photo_storage_key,
    read_and_resize_photo,
    validate_photo_uploads,
)
from ..schemas.products import ProductOut, ProductPatch
from ..storage import StorageDep

router = APIRouter(prefix="/bots", tags=["products"])
logger = structlog.get_logger("api.products")

PRODUCT_EMBEDDING_SCHEDULE_TIMEOUT_SECONDS = 5.0

# Дефолт этого роута == db.products.DEFAULT_CATALOG_LIMIT (=200) — сознательно,
# чтобы не повторить в меньшем масштабе тот же баг, который правит вся эта
# пагинация (найдено финальным ревью 6.8, 2026-09-10: список товаров молча
# обрезался на 200 без признака "есть ещё"). Roль этого роута — дать явным
# ?limit=/?offset= возможность листать каталог; у самого дефолта нет причин
# быть меньше, чем было раньше для любого вызывающего, который limit не
# передаёт (сейчас это только admin-web, но роут публичный — см. FEATURES.md
# 9.8). admin-web передаёт свой limit явно (PRODUCTS_PAGE_SIZE=100 в
# app/bots/[id]/products/page.tsx), так что для него это не регрессия.
# PRODUCTS_LIST_MAX_LIMIT — верхняя граница на ?limit=, чтобы клиент не мог
# одним запросом запросить весь каталог разом.
PRODUCTS_LIST_DEFAULT_LIMIT = DEFAULT_CATALOG_LIMIT
PRODUCTS_LIST_MAX_LIMIT = 500


def _parse_display_custom(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="display_custom must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="display_custom must be a JSON object")
    return parsed


async def _recompute_embedding(session: AsyncSession, product: Product) -> None:
    """Синхронная попытка (с уже встроенным в generate_embedding ретраем);
    при сбое — не роняем запрос, ставим Celery-подстраховку. upsert_embedding
    и commit — тоже часть этой попытки: сбой записи (БД недоступна,
    несовпадение размерности вектора, конфликт транзакции) должен уйти в тот
    же fallback, а не 500-ить уже сохранённый товар."""
    text = product_embedding_input(product.name, product.description)
    try:
        embedding = await generate_embedding(text)
        await upsert_embedding(session, product.id, embedding)
        await session.commit()
    except Exception:
        logger.warning(
            "embedding generation failed, scheduling retry",
            product_id=str(product.id),
            exc_info=True,
        )
        await _schedule_embedding_retry(product.id)


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
async def list_products_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(PRODUCTS_LIST_DEFAULT_LIMIT, ge=1, le=PRODUCTS_LIST_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[ProductOut]:
    products = await list_products(session, bot_id, limit=limit, offset=offset, with_images=True)
    return [ProductOut.model_validate(p) for p in products]


@router.post("/{bot_id}/products", response_model=ProductOut, status_code=201)
async def create_product_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    name: str = Form(...),
    price: Decimal | None = Form(None),  # noqa: B008
    sku: str | None = Form(None),
    description: str | None = Form(None),
    display_custom: str | None = Form(None),
    photos: list[UploadFile] = File(...),  # noqa: B008
) -> ProductOut:
    try:
        validate_photo_uploads(photos, max_count=MAX_PHOTOS_PER_PRODUCT)
    except PhotoValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    name_stripped = name.strip()
    if not name_stripped:
        raise HTTPException(status_code=422, detail="name must not be empty")

    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")

    display_custom_parsed = _parse_display_custom(display_custom)

    product = await create_product(
        session,
        bot_id,
        name=name_stripped,
        price=price,
        sku=sku,
        description=description,
        display_custom=display_custom_parsed,
    )
    await session.flush()  # нужен product.id для ключей Storage ниже

    try:
        for position, upload in enumerate(photos):
            data, mime_type = await read_and_resize_photo(upload)
            photo_id = uuid.uuid4()
            key = build_photo_storage_key(bot_id, product.id, photo_id)
            await storage.put(key, data, mime_type)
            await create_product_image(
                session,
                product.id,
                id=photo_id,
                storage_key=key,
                mime_type=mime_type,
                position=position,
            )
    except PhotoValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="failed to store product photo") from exc

    await session.commit()

    created_product = await get_product(session, bot_id, product.id, with_images=True)
    assert created_product is not None  # только что закоммитили
    await _recompute_embedding(session, created_product)
    return ProductOut.model_validate(created_product)


@router.get("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def get_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep
) -> ProductOut:
    product = await get_product(session, bot_id, product_id, with_images=True)
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

    product = await get_product(session, bot_id, product_id, with_images=True)
    assert product is not None  # только что успешно обновили выше

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
