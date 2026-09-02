"""Учёт токенов и стоимости вызовов LLM."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from .models import UsageEvent


async def record_usage(
    session: AsyncSession,
    bot_id: uuid.UUID,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost: Decimal,
) -> None:
    session.add(
        UsageEvent(
            bot_id=bot_id, model=model, tokens_in=tokens_in, tokens_out=tokens_out, cost=cost
        )
    )
    await session.flush()
