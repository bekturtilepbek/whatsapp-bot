"""Pydantic v2 схема ответа аудит-лога (FEATURES.md 6.19)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: UUID
    actor_user_id: UUID
    actor_email: str
    bot_id: UUID | None
    bot_name: str | None
    action: str
    payload: dict[str, Any] | None
    created_at: datetime
