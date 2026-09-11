"""Pydantic v2 схемы бота для api."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    phone: str | None
    linked_at: datetime | None
    system_prompt: str
    image_prompt: str | None
    pdf_prompt: str | None
    timezone: str
    settings: dict[str, Any]
    created_at: datetime


class BotCreate(BaseModel):
    name: str


class BotPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные (exclude_unset)."""

    name: str | None = None
    enabled: bool | None = None
    system_prompt: str | None = None
    image_prompt: str | None = None
    pdf_prompt: str | None = None
    settings: dict[str, Any] | None = None
