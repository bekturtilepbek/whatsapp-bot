"""Чёрный список номеров (FEATURES.md 1.5). Матчинг — по "сырому" wa_id
(см. BlockedContact в models.py) — эталон поведения: V1 ignored_numbers.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BlockedContact


async def is_blocked(session: AsyncSession, bot_id: uuid.UUID, phone: str) -> bool:
    stmt = select(BlockedContact.id).where(
        BlockedContact.bot_id == bot_id, BlockedContact.phone == phone
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_blocked_number(session: AsyncSession, bot_id: uuid.UUID, phone: str) -> None:
    """Идемпотентно: повторное добавление того же номера — не ошибка."""
    stmt = (
        insert(BlockedContact)
        .values(bot_id=bot_id, phone=phone)
        .on_conflict_do_nothing(constraint="uq_blocked_contacts_bot_phone")
    )
    await session.execute(stmt)
    await session.flush()


async def remove_blocked_number(session: AsyncSession, bot_id: uuid.UUID, phone: str) -> None:
    """Идемпотентно: удаление отсутствующего номера — не ошибка (0 строк)."""
    stmt = delete(BlockedContact).where(
        BlockedContact.bot_id == bot_id, BlockedContact.phone == phone
    )
    await session.execute(stmt)
    await session.flush()


async def list_blocked_numbers(session: AsyncSession, bot_id: uuid.UUID) -> list[str]:
    stmt = (
        select(BlockedContact.phone)
        .where(BlockedContact.bot_id == bot_id)
        .order_by(BlockedContact.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
