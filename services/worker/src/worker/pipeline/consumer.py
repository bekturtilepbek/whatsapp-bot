"""Реальный пайплайн диалога — заменяет временный echo (Блок 1).

Этот шаг (2 из STAGE1_CORE Блок 2): дедуп → фильтры → contact → запись
входящего → enabled. Батчинг/лок/LLM/ответ/медиа-заглушка — следующие шаги
того же блока, дописываются в этот же модуль.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from core.events import Event
from db.bots import get_bot
from db.contacts import match_or_create_contact
from db.messages import insert_incoming
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..bus import IN_STREAM, ensure_group, read_group
from .dedup import is_duplicate
from .filters import is_ignored_chat
from .media import incoming_content

GROUP = "worker"

logger = structlog.get_logger("worker.pipeline")

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def _to_datetime(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC)


async def _process_entry(
    payload: dict[str, Any],
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    try:
        event = _event_adapter.validate_python(payload)
    except ValidationError:
        logger.warning("invalid event on wa:in, skipping", payload=payload)
        return

    if event.type != "inbound.text":
        return  # session.status и т.п. — не пайплайн диалога

    if event.from_me:
        # Публикуется gateway'ем для будущего handoff (Блок 3, детект ответа
        # менеджера). Пока не обрабатываем — иначе бот отвечал бы сам себе.
        return

    if await is_duplicate(redis, str(event.bot_id), event.wa_msg_id):
        logger.info("duplicate wa_msg_id, skipping", wa_msg_id=event.wa_msg_id)
        return

    if is_ignored_chat(event.chat_id):
        return

    async with session_factory() as session:
        contact = await match_or_create_contact(
            session, event.bot_id, wa_id=event.sender_wa_id, lid=event.sender_lid
        )
        content = incoming_content(event.text, event.media_type)
        await insert_incoming(
            session,
            event.bot_id,
            contact.id,
            content,
            event.wa_msg_id,
            _to_datetime(event.ts),
        )
        bot = await get_bot(session, event.bot_id)
        await session.commit()

    if bot is None:
        logger.error("bot not found for inbound event", bot_id=str(event.bot_id))
        return
    if not bot.enabled:
        return  # молчим, но история уже записана выше

    # Батчинг/лок/LLM/ответ/usage_events — Шаги 3 и 5 этого блока.


async def run_pipeline_consumer(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    consumer_name: str,
) -> None:
    """Останавливается через отмену задачи (asyncio.CancelledError) — как echo.py."""
    await ensure_group(redis, IN_STREAM, GROUP)
    while True:
        async for entry in read_group(redis, IN_STREAM, GROUP, consumer_name):
            try:
                if entry.payload is not None:
                    await _process_entry(entry.payload, redis, session_factory)
            finally:
                await redis.xack(IN_STREAM, GROUP, entry.entry_id)
