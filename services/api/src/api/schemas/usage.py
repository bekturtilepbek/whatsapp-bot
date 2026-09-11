"""Pydantic v2 схема ответа расходов OpenAI (FEATURES.md 6.15)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class UsageSummaryOut(BaseModel):
    bot_id: UUID
    bot_name: str
    tokens_in: int
    tokens_out: int
    cost: Decimal
