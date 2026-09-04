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
    system_prompt: str
    image_prompt: str | None
    timezone: str
    settings: dict[str, Any]
    created_at: datetime


class BotPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные (exclude_unset)."""

    enabled: bool | None = None
    system_prompt: str | None = None
    image_prompt: str | None = None
    settings: dict[str, Any] | None = None
