"""Запросы к bots для worker-пайплайна."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Bot


async def get_bot(session: AsyncSession, bot_id: uuid.UUID) -> Bot | None:
    return await session.get(Bot, bot_id)
