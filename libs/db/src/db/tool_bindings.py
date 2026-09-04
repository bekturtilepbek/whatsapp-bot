"""Реестр тулз, включённых конкретному боту (FEATURES.md 4.13). Сама
тулза как код живёт в libs/tools — эта таблица только решает, что боту
доступно и с каким config.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ToolBinding


async def list_enabled(session: AsyncSession, bot_id: uuid.UUID) -> list[ToolBinding]:
    stmt = (
        select(ToolBinding)
        .where(ToolBinding.bot_id == bot_id)
        .order_by(ToolBinding.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def enable(
    session: AsyncSession, bot_id: uuid.UUID, tool_name: str, config: dict[str, Any]
) -> None:
    """Идемпотентно: повторное включение той же тулзы обновляет config,
    а не создаёт вторую строку (UNIQUE(bot_id, tool_name))."""
    stmt = (
        insert(ToolBinding)
        .values(bot_id=bot_id, tool_name=tool_name, config=config)
        .on_conflict_do_update(
            constraint="uq_tool_bindings_bot_tool_name",
            set_={"config": config},
        )
    )
    await session.execute(stmt)
    await session.flush()


async def disable(session: AsyncSession, bot_id: uuid.UUID, tool_name: str) -> None:
    """Идемпотентно: выключение отсутствующей тулзы — не ошибка (0 строк)."""
    stmt = delete(ToolBinding).where(
        ToolBinding.bot_id == bot_id, ToolBinding.tool_name == tool_name
    )
    await session.execute(stmt)
    await session.flush()
