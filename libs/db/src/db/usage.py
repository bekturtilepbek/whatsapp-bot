"""Учёт токенов и стоимости вызовов LLM (FEATURES.md 3.9/6.15).

cost — локальная ОЦЕНКА по объявленным ценам OpenAI (libs/llm/pricing.py),
не биллинговые данные — V1 ходил в реальный OpenAI usage API с отдельным
admin-ключом, здесь сознательное упрощение (см. pricing.py docstring).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Bot, UsageEvent


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


@dataclass
class UsageSummary:
    bot_id: uuid.UUID
    bot_name: str
    tokens_in: int
    tokens_out: int
    cost: Decimal


async def list_usage_by_bot(
    session: AsyncSession, *, since: datetime | None = None
) -> list[UsageSummary]:
    """Сумма токенов/стоимости по боту за период — сортировка по убыванию
    стоимости (сначала самые дорогие). INNER JOIN на usage_events — бот без
    единого вызова за период просто не попадает в отчёт, показывать
    "$0.00" для него не несёт пользы для основного сценария (кто больше
    всех тратит)."""
    stmt = (
        select(
            Bot.id,
            Bot.name,
            func.sum(UsageEvent.tokens_in),
            func.sum(UsageEvent.tokens_out),
            func.sum(UsageEvent.cost),
        )
        .join(UsageEvent, UsageEvent.bot_id == Bot.id)
        .group_by(Bot.id, Bot.name)
    )
    if since is not None:
        stmt = stmt.where(UsageEvent.ts >= since)
    stmt = stmt.order_by(func.sum(UsageEvent.cost).desc())

    result = await session.execute(stmt)
    return [
        UsageSummary(
            bot_id=bot_id,
            bot_name=bot_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
        )
        for bot_id, bot_name, tokens_in, tokens_out, cost in result.all()
    ]
