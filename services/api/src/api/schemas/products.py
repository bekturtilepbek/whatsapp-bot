"""Pydantic v2 схемы товара для api (FEATURES.md 6.8, CRUD без фото)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: Decimal | None
    sku: str | None
    description: str | None
    display_custom: dict[str, Any]
    created_at: datetime


class ProductCreate(BaseModel):
    name: str
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict[str, Any] | None = None


class ProductPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные
    (exclude_unset). None для price/sku/description неотличим от "поле не
    передано" на уровне db.products.update_product — тот же принятый
    паттерн, что и BotPatch.image_prompt/pdf_prompt."""

    name: str | None = None
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict[str, Any] | None = None
