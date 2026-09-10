"""Гранты доступа клиентов к ботам (FEATURES.md 6.18)."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BotAccess


async def grant_bot_access(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    """Идемпотентно: повторная выдача того же гранта — не ошибка."""
    stmt = (
        insert(BotAccess)
        .values(user_id=user_id, bot_id=bot_id)
        .on_conflict_do_nothing(constraint="uq_bot_access_user_bot")
    )
    await session.execute(stmt)
    await session.flush()


async def revoke_bot_access(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    """Идемпотентно: отзыв отсутствующего гранта — не ошибка (0 строк)."""
    stmt = delete(BotAccess).where(BotAccess.user_id == user_id, BotAccess.bot_id == bot_id)
    await session.execute(stmt)
    await session.flush()


async def has_bot_access(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> bool:
    stmt = select(BotAccess.id).where(BotAccess.user_id == user_id, BotAccess.bot_id == bot_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def list_bot_ids_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = (
        select(BotAccess.bot_id)
        .where(BotAccess.user_id == user_id)
        .order_by(BotAccess.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
