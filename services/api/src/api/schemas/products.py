"""Pydantic v2 схемы товара для api (FEATURES.md 6.8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# products.price — Numeric(12, 2): максимум 9 999 999 999.99. Больше — БД
# падала "numeric field overflow" (500) уже на commit, после платного
# эмбеддинга; отрицательная цена уходила клиенту в карточке (2026-09-28).
PRICE_UPPER_BOUND = Decimal(10) ** 10


class ProductMediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    # Нужен фронту, чтобы решить, рендерить <img> или <video> (FEATURES.md
    # 4.4 ревизия — раньше поле было строго фото, mime_type не отдавался).
    mime_type: str


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: Decimal | None
    sku: str | None
    description: str | None
    display_custom: dict[str, Any]
    media: list[ProductMediaOut]
    created_at: datetime


class ProductPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные
    (exclude_unset). None для price/sku/description неотличим от "поле не
    передано" на уровне db.products.update_product — тот же принятый
    паттерн, что и BotPatch.image_prompt/pdf_prompt."""

    name: str | None = None
    price: Decimal | None = Field(None, ge=0, lt=PRICE_UPPER_BOUND)
    sku: str | None = None
    description: str | None = None
    display_custom: dict[str, Any] | None = None
