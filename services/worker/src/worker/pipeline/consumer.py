"""Реальный пайплайн диалога — заменяет временный echo (Блок 1).

Порядок (STAGE1_CORE Блок 2, шаг 2): дедуп → фильтры → contact → запись
входящего → enabled → батчинг (debounce) → лок диалога → история → LLM →
typing → ответ → запись ответа → usage_events. Медиа-заглушка — Шаг 6,
подключается отдельной веткой перед вызовом LLM.

Любая ошибка на отрезке батчинг..запись (Redis/LLM/БД) — лог, лок
снимается, ACK без ответа; ретраи — Волна 1 (STAGE1_CORE).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from core.events import Event, InboundText, OutboundText, OutboundTyping
from db.bots import get_bot
from db.contacts import match_or_create_contact
from db.messages import fetch_recent_history, insert_incoming, insert_outgoing
from db.models import Bot
from db.usage import record_usage
from llm.client import HistoryMessage, complete
from llm.pricing import compute_cost
from llm.time_context import time_context
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..bus import IN_STREAM, OUT_STREAM, ensure_group, publish, read_group
from . import batching, lock
from .dedup import is_duplicate
from .filters import is_ignored_chat
from .media import incoming_content

GROUP = "worker"

logger = structlog.get_logger("worker.pipeline")

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)

DEFAULT_BATCH_TIMEOUT_SECONDS = 1.0


def _to_datetime(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC)


def _batch_timeout_seconds(bot: Bot) -> float:
    value = bot.settings.get("batch_timeout_seconds", DEFAULT_BATCH_TIMEOUT_SECONDS)
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_BATCH_TIMEOUT_SECONDS


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

    bot_id_str = str(event.bot_id)
    became_leader = await batching.register_arrival(
        redis, bot_id_str, event.chat_id, _batch_timeout_seconds(bot)
    )
    if not became_leader:
        return  # не лидер батча — сообщение уже в истории, дальше ведёт лидер

    await batching.wait_for_quiet(redis, bot_id_str, event.chat_id)

    if not await lock.acquire(redis, bot_id_str, event.chat_id):
        logger.info("dialog already locked, backing off", bot_id=bot_id_str, chat_id=event.chat_id)
        return

    try:
        await _reply(event, bot, contact.id, redis, session_factory)
    except Exception:
        # "Любой внешний вызов — с таймаутом" не спасает от сбоя самого
        # вызова (LLM/Redis/БД) — здесь лог и тихий отказ, без ретрая
        # (Волна 1) и без падения консюмера на одном плохом сообщении.
        logger.exception("reply pipeline failed", bot_id=bot_id_str, chat_id=event.chat_id)
    finally:
        await lock.release(redis, bot_id_str, event.chat_id)


async def _reply(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        history_rows = await fetch_recent_history(session, contact_id)

    history = [HistoryMessage(role=m.role, content=m.content) for m in history_rows]
    system_prompt = f"{bot.system_prompt}\n\n{time_context(bot.timezone)}"

    result = await complete(system_prompt, history)
    if not result.text.strip():
        logger.warning("LLM returned empty text, not sending", bot_id=str(event.bot_id))
        return

    typing_event = OutboundTyping(
        bot_id=event.bot_id, chat_id=event.chat_id, client_msg_id=str(uuid.uuid4())
    )
    text_event = OutboundText(
        bot_id=event.bot_id,
        chat_id=event.chat_id,
        text=result.text,
        client_msg_id=str(uuid.uuid4()),
    )
    await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))
    await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()


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
