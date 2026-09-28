"""GET/POST/PATCH/DELETE /bots/{bot_id}/products (FEATURES.md 6.8). POST —
multipart/form-data, обязательно хотя бы один медиа-элемент (фото или видео,
FEATURES.md 4.4 ревизия). Обязательно только name; price/sku/description
опциональны, display_custom — "всё или ничего" (см.
db.product_search._resolve_display_config, не меняется).

Эмбеддинг (FEATURES.md 4.1) строится только из name+description
(llm.embeddings.product_embedding_input) — строго синхронно в этом же
HTTP-запросе, ДО commit (generate_embedding уже со своим ретраем ×3).
Строгое V1-поведение (пересмотр 2026-09-16, см. память
product-embedding-retry-design — первая версия этого дизайна сохраняла
товар всё равно и ставила Celery-подстраховку в фоне, пользователь явно
попросил вернуться к V1): если эмбеддинг не удалось посчитать — операция
(создание ИЛИ патч, если он меняет name/description) отклоняется целиком,
ничего не коммитится. Известный принятый компромисс: уже загруженные в
Storage фото при отклонении создания не удаляются (у Storage пока нет
метода delete() ни в одном бэкенде) — редкий и дешёвый по цене мусор.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import structlog
from db.bots import get_bot
from db.models import Product
from db.product_embeddings import upsert_embedding
from db.product_media import (
    create_product_media_item,
    delete_product_media_item,
    get_product_media_item,
    list_product_media,
    next_position,
)
from db.products import (
    DEFAULT_CATALOG_LIMIT,
    create_product,
    delete_product,
    get_product,
    list_products,
    update_product,
)
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from llm.embeddings import generate_embedding, product_embedding_input
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionDep
from ..product_media import (
    MAX_MEDIA_PER_PRODUCT,
    MediaValidationError,
    build_media_storage_key,
    process_media_upload,
    validate_media_uploads,
)
from ..schemas.products import PRICE_UPPER_BOUND, ProductMediaOut, ProductOut, ProductPatch
from ..security import BotAccessUser
from ..storage import StorageDep

router = APIRouter(prefix="/bots", tags=["products"])
logger = structlog.get_logger("api.products")

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


async def _compute_and_store_embedding(session: AsyncSession, product: Product) -> None:
    """Строгое V1-поведение: сбой здесь должен провалить ВЕСЬ вызывающий
    запрос (create/patch) — исключение сознательно не перехватывается тут,
    вызывающий код ловит его сам, делает rollback и возвращает 502.
    upsert_embedding — часть той же попытки, но ещё не commit (коммитит
    вызывающий код одной транзакцией вместе с товаром/фото)."""
    text = product_embedding_input(product.name, product.description)
    embedding = await generate_embedding(text)
    await upsert_embedding(session, product.id, embedding)


@router.get("/{bot_id}/products", response_model=list[ProductOut])
async def list_products_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    user: BotAccessUser,
    limit: int = Query(PRODUCTS_LIST_DEFAULT_LIMIT, ge=1, le=PRODUCTS_LIST_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[ProductOut]:
    products = await list_products(session, bot_id, limit=limit, offset=offset, with_media=True)
    return [ProductOut.model_validate(p) for p in products]


@router.post("/{bot_id}/products", response_model=ProductOut, status_code=201)
async def create_product_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    user: BotAccessUser,
    name: str = Form(...),
    price: Decimal | None = Form(None, ge=0, lt=float(PRICE_UPPER_BOUND)),  # noqa: B008
    sku: str | None = Form(None),
    description: str | None = Form(None),
    display_custom: str | None = Form(None),
    media: list[UploadFile] = File(...),  # noqa: B008
) -> ProductOut:
    try:
        validate_media_uploads(media, max_count=MAX_MEDIA_PER_PRODUCT)
    except MediaValidationError as exc:
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
        for position, upload in enumerate(media):
            data, mime_type = await process_media_upload(upload)
            media_id = uuid.uuid4()
            key = build_media_storage_key(bot_id, product.id, media_id)
            await storage.put(key, data, mime_type)
            await create_product_media_item(
                session,
                product.id,
                id=media_id,
                storage_key=key,
                mime_type=mime_type,
                position=position,
            )
    except MediaValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="failed to store product media") from exc

    try:
        await _compute_and_store_embedding(session, product)
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="failed to generate product embedding") from exc

    await session.commit()

    created_product = await get_product(session, bot_id, product.id, with_media=True)
    assert created_product is not None  # только что закоммитили
    return ProductOut.model_validate(created_product)


@router.get("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def get_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep, user: BotAccessUser
) -> ProductOut:
    product = await get_product(session, bot_id, product_id, with_media=True)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return ProductOut.model_validate(product)


@router.patch("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def patch_product_route(
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    patch: ProductPatch,
    session: SessionDep,
    user: BotAccessUser,
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

    if product.name != old_name or product.description != old_description:
        try:
            await _compute_and_store_embedding(session, product)
        except Exception as exc:
            # rollback откатывает и update_product() выше — сбой эмбеддинга
            # отклоняет ВЕСЬ патч целиком, включая несвязанные поля вроде
            # price в том же запросе (строгое V1-поведение).
            await session.rollback()
            raise HTTPException(
                status_code=502, detail="failed to generate product embedding"
            ) from exc

    await session.commit()

    product = await get_product(session, bot_id, product_id, with_media=True)
    assert product is not None  # только что успешно обновили выше
    return ProductOut.model_validate(product)


@router.delete("/{bot_id}/products/{product_id}", status_code=204)
async def delete_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep, user: BotAccessUser
) -> None:
    deleted = await delete_product(session, bot_id, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="product not found")
    await session.commit()


@router.post(
    "/{bot_id}/products/{product_id}/media",
    response_model=list[ProductMediaOut],
    status_code=201,
)
async def add_product_media_route(
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    user: BotAccessUser,
    media: list[UploadFile] = File(...),  # noqa: B008
) -> list[ProductMediaOut]:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    existing_count = len(await list_product_media(session, product_id))
    remaining_slots = MAX_MEDIA_PER_PRODUCT - existing_count
    try:
        validate_media_uploads(media, max_count=max(remaining_slots, 0))
    except MediaValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    created: list[Any] = []
    try:
        for upload in media:
            data, mime_type = await process_media_upload(upload)
            position = await next_position(session, product_id)
            media_id = uuid.uuid4()
            key = build_media_storage_key(bot_id, product_id, media_id)
            await storage.put(key, data, mime_type)
            item = await create_product_media_item(
                session,
                product_id,
                id=media_id,
                storage_key=key,
                mime_type=mime_type,
                position=position,
            )
            created.append(item)
    except MediaValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="failed to store product media") from exc

    await session.commit()
    return [ProductMediaOut.model_validate(item) for item in created]


@router.delete("/{bot_id}/products/{product_id}/media/{media_id}", status_code=204)
async def delete_product_media_route(
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    media_id: uuid.UUID,
    session: SessionDep,
    user: BotAccessUser,
) -> None:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    remaining = await list_product_media(session, product_id)
    if len(remaining) <= 1:
        if not any(item.id == media_id for item in remaining):
            raise HTTPException(status_code=404, detail="media item not found")
        raise HTTPException(
            status_code=422, detail="cannot delete the last media item of a product"
        )

    deleted = await delete_product_media_item(session, product_id, media_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="media item not found")
    await session.commit()


@router.get("/{bot_id}/products/{product_id}/media/{media_id}")
async def get_product_media_route(
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    media_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    user: BotAccessUser,
) -> Response:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    item = await get_product_media_item(session, product_id, media_id)
    if item is None:
        raise HTTPException(status_code=404, detail="media item not found")
    try:
        data = await storage.get(item.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="failed to read media") from exc
    # Медиа по media_id неизменяемо: перезаписи/апдейта в Storage нет, только
    # create/delete всего объекта — можно кэшировать бессрочно (финальное
    # ревью 6.8, 2026-09-10: список товаров иначе рефетчит те же байты на
    # каждый рендер миниатюры).
    return Response(
        content=data,
        media_type=item.mime_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
