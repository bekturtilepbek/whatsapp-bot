"""Аудит-лог действий (FEATURES.md 6.19). Пишется ASGI-middleware
(services/api/src/api/audit.py) через собственную сессию — не роутами
напрямую.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, Bot, User


async def create_entry(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    bot_id: uuid.UUID | None,
    action: str,
    payload: dict[str, Any] | None,
) -> AuditLog:
    entry = AuditLog(actor_user_id=actor_user_id, bot_id=bot_id, action=action, payload=payload)
    session.add(entry)
    await session.flush()
    return entry


@dataclass
class AuditLogEntry:
    id: uuid.UUID
    actor_user_id: uuid.UUID
    actor_email: str
    bot_id: uuid.UUID | None
    bot_name: str | None
    action: str
    payload: dict[str, Any] | None
    created_at: datetime


async def list_entries(
    session: AsyncSession,
    *,
    bot_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLogEntry]:
    """JOIN на users/bots за один запрос — экран не должен слать
    отдельный запрос на email/имя бота на каждую строку (тот же принцип,
    что list_bots подмешивает phone/linked_at, а не N+1)."""
    stmt = (
        select(AuditLog, User.email, Bot.name)
        .join(User, User.id == AuditLog.actor_user_id)
        .outerjoin(Bot, Bot.id == AuditLog.bot_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if bot_id is not None:
        stmt = stmt.where(AuditLog.bot_id == bot_id)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)

    result = await session.execute(stmt)
    return [
        AuditLogEntry(
            id=entry.id,
            actor_user_id=entry.actor_user_id,
            actor_email=actor_email,
            bot_id=entry.bot_id,
            bot_name=bot_name,
            action=entry.action,
            payload=entry.payload,
            created_at=entry.created_at,
        )
        for entry, actor_email, bot_name in result.all()
    ]
