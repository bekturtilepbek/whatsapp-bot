"""Запросы к bots — используется worker-пайплайном и api."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Bot
from .prompt_versions import record_version_if_changed


async def get_bot(session: AsyncSession, bot_id: uuid.UUID) -> Bot | None:
    """Без eager-load .session — горячий путь (worker/celery на каждое
    сообщение/follow-up), им не нужны Bot.phone/Bot.linked_at. Не добавлять
    сюда options=selectinload(Bot.session): это тянет bot_sessions.auth_state
    (Signal-ключи Baileys, большой и растущий JSONB) на каждый вызов —
    см. get_bot_with_session ниже для admin-роутов, которым он нужен.
    """
    return await session.get(Bot, bot_id)


async def get_bot_with_session(session: AsyncSession, bot_id: uuid.UUID) -> Bot | None:
    """Как get_bot, но с eager-loaded .session — для admin-роутов, которым
    нужны Bot.phone/Bot.linked_at (см. models.py). НЕ использовать в
    горячем пути (worker/celery) — тянет весь bot_sessions.auth_state
    (Signal-ключи Baileys), там он не нужен и дорог.
    select() вместо session.get() — иначе eager-load молча пропускается,
    если Bot уже в identity map текущей сессии (session.get() не
    применяет options в этом случае)."""
    result = await session.execute(
        select(Bot).options(selectinload(Bot.session)).where(Bot.id == bot_id)
    )
    return result.scalars().first()


async def list_bots(session: AsyncSession) -> Sequence[Bot]:
    result = await session.execute(
        select(Bot).options(selectinload(Bot.session)).order_by(Bot.created_at)
    )
    return result.scalars().all()


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

    Промпты (system_prompt/image_prompt/pdf_prompt), если переданы,
    дополнительно версионируются в prompt_versions (FEATURES.md 3.7/3.8) —
    см. record_version_if_changed. NULL остаётся сигналом "не трогать это
    поле" (как и раньше) — версия для kind пишется только когда вызывающий
    передал непустое значение, то же условие, что решает, попадёт ли поле
    в UPDATE bots.
    """
    current = await get_bot(session, bot_id)
    if current is None:
        return None

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

    if system_prompt is not None:
        await record_version_if_changed(
            session, bot_id, "main", system_prompt, baseline=current.system_prompt
        )
    if image_prompt is not None:
        await record_version_if_changed(
            session, bot_id, "image", image_prompt, baseline=current.image_prompt
        )
    if pdf_prompt is not None:
        await record_version_if_changed(
            session, bot_id, "pdf", pdf_prompt, baseline=current.pdf_prompt
        )

    if values:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(**values))
        await session.flush()
        # Bulk UPDATE (Core) не обновляет уже загруженный в identity map
        # объект сам по себе — без expire get_bot_with_session() ниже мог бы
        # вернуть объект с полями до PATCH, если бот уже был загружен в этой сессии.
        session.expire_all()

    return await get_bot_with_session(session, bot_id)
