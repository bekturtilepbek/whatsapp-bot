"""Pydantic v2 схема истории версий промпта для api."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str | None
    author: str
    created_at: datetime
