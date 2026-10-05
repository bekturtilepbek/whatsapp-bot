"""Агрегаты для "Обзора" бота за период (FEATURES.md 6.23)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from .handoff_events import KIND_STARTED
from .models import Contact, HandoffEvent, Message


@dataclass
class WindowCounts:
    clients_active: int
    clients_new: int
    messages_in: int
    messages_out: int
    handoffs: int
    resolved_without_human_pct: int | None


async def handoff_tracked_since(session: AsyncSession) -> datetime | None:
    """Самое раннее событие передачи по всей БД — с него события 5.7 пишутся
    вообще. До этого момента "без человека" посчитать нельзя: передач не
    фиксировали, а не их не было."""
    result = await session.execute(select(func.min(HandoffEvent.created_at)))
    return result.scalar_one_or_none()


async def window_counts(
    session: AsyncSession,
    bot_id: uuid.UUID,
    start: datetime,
    end: datetime | None,
    tracked_since: datetime | None,
) -> WindowCounts:
    """Окно [start, end); end=None — без верхней границы (текущий период)."""

    def in_window(column: InstrumentedAttribute[datetime]) -> list[ColumnElement[bool]]:
        conditions = [column >= start]
        if end is not None:
            conditions.append(column < end)
        return conditions

    async def scalar(stmt: Select[tuple[int]]) -> int:
        return int((await session.execute(stmt)).scalar_one())

    messages_in = await scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.bot_id == bot_id, Message.role == "user", *in_window(Message.ts))
    )
    messages_out = await scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.bot_id == bot_id, Message.role == "assistant", *in_window(Message.ts))
    )
    active_contacts = (
        select(Message.contact_id)
        .where(Message.bot_id == bot_id, Message.role == "user", *in_window(Message.ts))
        .distinct()
        .subquery()
    )
    clients_active = await scalar(select(func.count()).select_from(active_contacts))
    clients_new = await scalar(
        select(func.count())
        .select_from(Contact)
        .where(Contact.bot_id == bot_id, *in_window(Contact.created_at))
    )
    started = and_(
        HandoffEvent.bot_id == bot_id,
        HandoffEvent.kind == KIND_STARTED,
        *in_window(HandoffEvent.created_at),
    )
    handoffs = await scalar(select(func.count()).select_from(HandoffEvent).where(started))

    pct: int | None = None
    if clients_active > 0 and tracked_since is not None and start >= tracked_since:
        with_human = await scalar(
            select(func.count()).select_from(
                select(HandoffEvent.contact_id)
                .where(started, HandoffEvent.contact_id.in_(select(active_contacts.c.contact_id)))
                .distinct()
                .subquery()
            )
        )
        pct = int((clients_active - with_human) * 100 / clients_active + 0.5)

    return WindowCounts(
        clients_active=clients_active,
        clients_new=clients_new,
        messages_in=messages_in,
        messages_out=messages_out,
        handoffs=handoffs,
        resolved_without_human_pct=pct,
    )
