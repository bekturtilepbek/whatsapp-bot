"""Запросы к bots — используется worker-пайплайном и api."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import cast, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Bot


async def get_bot(session: AsyncSession, bot_id: uuid.UUID) -> Bot | None:
    return await session.get(Bot, bot_id)


async def update_bot(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    enabled: bool | None = None,
    system_prompt: str | None = None,
    image_prompt: str | None = None,
    pdf_prompt: str | None = None,
    settings_patch: dict[str, Any] | None = None,
) -> Bot | None:
    """Частичное обновление: None-параметр = не трогать это поле.

    settings мержится через Postgres JSONB `||` (shallow merge на стороне
    БД), а не Python-side read-modify-write — атомарно, без гонки двух
    параллельных PATCH на разные ключи settings. Правило CLAUDE.md:
    "настройки бота мержатся, не перезаписываются".
    """
    values: dict[str, Any] = {}
    if enabled is not None:
        values["enabled"] = enabled
    if system_prompt is not None:
        values["system_prompt"] = system_prompt
    if image_prompt is not None:
        values["image_prompt"] = image_prompt
    if pdf_prompt is not None:
        values["pdf_prompt"] = pdf_prompt
    if settings_patch is not None:
        values["settings"] = Bot.settings.op("||")(cast(settings_patch, JSONB))

    if values:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(**values))
        await session.flush()
        # Bulk UPDATE (Core) не обновляет уже загруженный в identity map
        # объект сам по себе — без expire get_bot() ниже мог бы вернуть
        # объект с полями до PATCH, если бот уже был загружен в этой сессии.
        session.expire_all()

    return await get_bot(session, bot_id)
