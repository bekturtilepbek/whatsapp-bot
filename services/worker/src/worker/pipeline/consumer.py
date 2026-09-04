"""Реальный пайплайн диалога — заменяет временный echo (Блок 1).

Порядок (STAGE1_CORE Блок 2+3, Волна 1 п.1.5+2.1): дедуп → фильтры (группы) →
from_me? handoff-ветка : чёрный список → contact → запись входящего →
enabled → handoff активен? молчим : батчинг
(debounce) → лок диалога → фото с настроенным image_prompt? vision-ответ (один
вызов LLM, image_prompt как system prompt, ответ уходит клиенту напрямую) :
прочее медиа? заглушка без LLM : история → LLM → typing → ответ → запись
ответа → usage_events (LLM-ветки, включая vision).

Любая ошибка на отрезке батчинг..запись (Redis/LLM/БД) — лог, лок
снимается, ACK без ответа; ретраи — Волна 1 (STAGE1_CORE). Исключение:
сбой именно vision-вызова (storage/LLM/таймаут) не проваливается наружу —
_reply_with_vision сама деградирует в _reply_with_media_fallback, чтобы
клиент не остался без ответа из-за временной недоступности OpenAI vision
или хранилища.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from core.events import Event, InboundText, OutboundText, OutboundTyping
from db.blocked_contacts import is_blocked
from db.bots import get_bot
from db.contacts import match_or_create_contact
from db.messages import fetch_recent_history, insert_incoming, insert_outgoing
from db.models import Bot
from db.usage import record_usage
from integrations.storage import Storage
from llm.client import HistoryMessage, complete, complete_with_image
from llm.pricing import compute_cost
from llm.time_context import time_context
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..bus import IN_STREAM, OUT_STREAM, ensure_group, publish, read_group
from . import batching, handoff, lock
from .dedup import is_duplicate
from .filters import is_ignored_chat
from .media import incoming_content

GROUP = "worker"

logger = structlog.get_logger("worker.pipeline")

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)

DEFAULT_BATCH_TIMEOUT_SECONDS = 1.0
DEFAULT_MEDIA_FALLBACK_TEXT = "Пока я умею отвечать только на текстовые сообщения"
DEFAULT_AUTO_RELEASE_MINUTES = 12
STORAGE_READ_TIMEOUT_SECONDS = 20.0


def _to_datetime(ts_ms: int) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC)


def _batch_timeout_seconds(bot: Bot) -> float:
    value = bot.settings.get("batch_timeout_seconds", DEFAULT_BATCH_TIMEOUT_SECONDS)
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_BATCH_TIMEOUT_SECONDS


def _handoff_ttl_seconds(bot: Bot) -> int:
    value = bot.settings.get("auto_release_minutes", DEFAULT_AUTO_RELEASE_MINUTES)
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        minutes = DEFAULT_AUTO_RELEASE_MINUTES
    return int(minutes * 60)


async def _process_entry(
    payload: dict[str, Any],
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    try:
        event = _event_adapter.validate_python(payload)
    except ValidationError:
        logger.warning("invalid event on wa:in, skipping", payload=payload)
        return

    if event.type != "inbound.text":
        return  # session.status и т.п. — не пайплайн диалога

    if await is_duplicate(redis, str(event.bot_id), event.wa_msg_id):
        logger.info("duplicate wa_msg_id, skipping", wa_msg_id=event.wa_msg_id)
        return

    if is_ignored_chat(event.chat_id):
        return

    if event.from_me:
        await _handle_manager_message(event, redis, session_factory)
        return

    async with session_factory() as session:
        if await is_blocked(session, event.bot_id, event.sender_wa_id):
            logger.info(
                "blocked contact, ignoring", bot_id=str(event.bot_id), phone=event.sender_wa_id
            )
            return
        contact = await match_or_create_contact(
            session, event.bot_id, wa_id=event.sender_wa_id, lid=event.sender_lid
        )
        content = incoming_content(event.text, event.media_type)
        media_ref = (
            {
                "storage_key": event.storage_key,
                "mime_type": event.mime_type,
                "size_bytes": event.size_bytes,
            }
            if event.storage_key is not None
            else None
        )
        await insert_incoming(
            session,
            event.bot_id,
            contact.id,
            content,
            event.wa_msg_id,
            _to_datetime(event.ts),
            media_ref=media_ref,
        )
        bot = await get_bot(session, event.bot_id)
        await session.commit()

    if bot is None:
        logger.error("bot not found for inbound event", bot_id=str(event.bot_id))
        return
    if not bot.enabled:
        return  # молчим, но история уже записана выше

    bot_id_str = str(event.bot_id)
    if await handoff.is_active(redis, bot_id_str, event.chat_id):
        return  # менеджер ведёт чат вручную — история уже записана выше

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
        if event.media_type == "image" and event.storage_key is not None and bot.image_prompt:
            await _reply_with_vision(event, bot, contact.id, redis, session_factory, storage)
        elif event.media_type is not None:
            await _reply_with_media_fallback(event, bot, contact.id, redis, session_factory)
        else:
            await _reply(event, bot, contact.id, redis, session_factory)
    except Exception:
        # "Любой внешний вызов — с таймаутом" не спасает от сбоя самого
        # вызова (LLM/Redis/БД) — здесь лог и тихий отказ, без ретрая
        # (Волна 1) и без падения консюмера на одном плохом сообщении.
        logger.exception("reply pipeline failed", bot_id=bot_id_str, chat_id=event.chat_id)
    finally:
        await lock.release(redis, bot_id_str, event.chat_id)


async def _handle_manager_message(
    event: InboundText,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """from_me=true: либо наш собственный echo (мы это отправили), либо
    менеджер ответил вручную с телефона — тогда включаем handoff и пишем
    его сообщение в историю ролью assistant с префиксом (STAGE1_CORE Блок 3).
    """
    if await handoff.is_own_echo(redis, event.wa_msg_id):
        return  # это отправил сам бот — не наш случай, ничего не делаем

    bot_id_str = str(event.bot_id)
    content = handoff.MANAGER_REPLY_PREFIX + incoming_content(event.text, event.media_type)

    async with session_factory() as session:
        contact = await match_or_create_contact(
            session, event.bot_id, wa_id=event.sender_wa_id, lid=event.sender_lid
        )
        await insert_outgoing(session, event.bot_id, contact.id, content)
        bot = await get_bot(session, event.bot_id)
        await session.commit()

    if bot is None:
        logger.error("bot not found for manager message", bot_id=bot_id_str)
        return

    await handoff.mark_manager_reply(redis, bot_id_str, event.chat_id, _handoff_ttl_seconds(bot))


async def _send_reply(event: InboundText, redis: Redis, text: str) -> None:
    """typing + text — РАЗНЫЕ client_msg_id: идемпотентность gateway (Блок 1)
    ключуется по client_msg_id для обоих типов событий одинаково — общий id
    заставил бы её принять отправку текста за дубль отправки typing.

    .hex (32 hex-символа без дефисов), не str(uuid4()) с дефисами: gateway
    (Блок 3) отправляет outbound.text с messageId=client_msg_id — это
    становится РЕАЛЬНЫМ WhatsApp message ID, а не просто внутренней меткой.
    """
    typing_event = OutboundTyping(
        bot_id=event.bot_id, chat_id=event.chat_id, client_msg_id=uuid.uuid4().hex
    )
    text_event = OutboundText(
        bot_id=event.bot_id, chat_id=event.chat_id, text=text, client_msg_id=uuid.uuid4().hex
    )
    await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))
    await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))


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

    await _send_reply(event, redis, result.text)

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()


async def _reply_with_vision(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    """FEATURES.md 2.1: один вызов LLM на фото — image_prompt бота как system
    prompt, ответ модели уходит клиенту напрямую (без второго прохода).

    Любой сбой на этом пути (чтение из storage, таймаут, сам вызов LLM,
    пустой ответ) — НЕ бросаем наружу: тихо деградируем в
    _reply_with_media_fallback, чтобы клиент гарантированно получил хоть
    какой-то ответ, а не тишину (в отличие от сбоя обычного _reply, который
    в _process_entry просто логируется без всякого ответа — здесь так
    нельзя, у нас уже есть рабочий fallback ровно для медиа-сообщений).
    """
    try:
        async with session_factory() as session:
            history_rows = await fetch_recent_history(session, contact_id)
        # Последняя строка — плейсхолдер текущего фото ("[фото]"), уже
        # вставленный insert_incoming выше по _process_entry; текущий ход
        # собирается заново из самих байтов картинки, а не из плейсхолдера.
        history = [
            HistoryMessage(role=m.role, content=m.content) for m in history_rows[:-1]
        ]

        assert event.storage_key is not None  # гарантировано веткой в _process_entry
        image_bytes = await asyncio.wait_for(
            storage.get(event.storage_key), timeout=STORAGE_READ_TIMEOUT_SECONDS
        )

        assert bot.image_prompt is not None  # гарантировано веткой в _process_entry
        system_prompt = f"{bot.image_prompt}\n\n{time_context(bot.timezone)}"
        mime_type = event.mime_type or "image/jpeg"
        result = await complete_with_image(
            system_prompt, history, event.text, image_bytes, mime_type
        )
        if not result.text.strip():
            logger.warning(
                "vision LLM returned empty text, falling back", bot_id=str(event.bot_id)
            )
            await _reply_with_media_fallback(event, bot, contact_id, redis, session_factory)
            return
    except Exception:
        logger.warning(
            "vision reply failed, falling back to media placeholder",
            bot_id=str(event.bot_id),
            chat_id=event.chat_id,
            exc_info=True,
        )
        await _reply_with_media_fallback(event, bot, contact_id, redis, session_factory)
        return

    await _send_reply(event, redis, result.text)

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()


async def _reply_with_media_fallback(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FEATURES.md 2.6: медиа вне текстового пайплайна — фиксированный ответ,
    без LLM и без usage_events (вызова LLM не было — нечего учитывать).
    """
    text = bot.settings.get("media_fallback_text", DEFAULT_MEDIA_FALLBACK_TEXT)
    await _send_reply(event, redis, text)

    async with session_factory() as session:
        await insert_outgoing(session, event.bot_id, contact_id, text)
        await session.commit()


async def run_pipeline_consumer(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    consumer_name: str,
    storage: Storage,
) -> None:
    """Останавливается через отмену задачи (asyncio.CancelledError) — как echo.py.

    XREADGROUP сам по себе не защищён try/except внутри read_group — если
    соединение тихо потеряно сетью (redis-py упадёт TimeoutError/ConnectionError
    по socket_timeout из bus.make_redis), исключение вылетит прямо из
    async for. Без перехвата здесь оно пробросилось бы наружу и убило бы
    всю задачу консюмера навсегда (никто её больше не await'ит и не
    перезапускает) — а не просто одно сообщение.
    """
    await ensure_group(redis, IN_STREAM, GROUP)
    while True:
        try:
            async for entry in read_group(redis, IN_STREAM, GROUP, consumer_name):
                try:
                    if entry.payload is not None:
                        await _process_entry(entry.payload, redis, session_factory, storage)
                finally:
                    await redis.xack(IN_STREAM, GROUP, entry.entry_id)
        except Exception:
            logger.exception("wa:in read loop failed, retrying")
            await asyncio.sleep(1)
