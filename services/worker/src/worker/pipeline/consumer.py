"""Реальный пайплайн диалога — заменяет временный echo (Блок 1).

Порядок (STAGE1_CORE Блок 2+3, Волна 1 п.1.5+2.1+2.4): дедуп → фильтры (группы) →
from_me? handoff-ветка : чёрный список → contact → запись входящего →
enabled → handoff активен? молчим : батчинг
(debounce) → лок диалога (продлевается в фоне на время ветки ниже —
lock.keep_alive, иначе ретраи LLM/цикл тулз могут пережить TTL лока) →
фото с настроенным image_prompt? vision-ответ (один
вызов LLM, image_prompt как system prompt, ответ уходит клиенту напрямую) :
PDF с настроенным pdf_prompt? PDF-ответ (текст извлекается ДО LLM, обычный
complete(), pdf_prompt как system prompt) : прочее медиа? заглушка без LLM :
история → каталог товаров в system prompt (FEATURES.md 3.4, только
текстовый путь — vision/PDF его не получают, как в V1) → тулзы бота
(LLM↔tool-calls, FEATURES.md 4.13; реестр пуст — как раньше, просто
complete()) → typing → ответ → запись ответа →
usage_events (LLM-ветки, включая vision и PDF).

Любая ошибка на отрезке батчинг..запись (Redis/LLM/БД) — лог, лок
снимается, ACK без ответа; ретраи — Волна 1 (STAGE1_CORE). Исключение:
сбой именно vision- или PDF-вызова (storage/извлечение текста/LLM/таймаут)
не проваливается наружу — _reply_with_vision/_reply_with_pdf сами
деградируют в _reply_with_media_fallback, чтобы клиент не остался без
ответа из-за временной недоступности OpenAI/хранилища.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from core.events import (
    Event,
    InboundText,
    OutboundDocument,
    OutboundImage,
    OutboundReaction,
    OutboundText,
    OutboundTyping,
    OutboundVideo,
)
from core.media import DEFAULT_MEDIA_FALLBACK_TEXT
from db.blocked_contacts import is_blocked
from db.bots import get_bot
from db.contacts import match_or_create_contact
from db.documents import list_documents
from db.messages import fetch_recent_history, insert_incoming, insert_outgoing
from db.models import Bot
from db.products import list_products
from db.tool_bindings import list_enabled as list_enabled_tool_bindings
from db.usage import record_usage
from integrations.storage import Storage
from llm.catalog_context import ProductInfo, catalog_context
from llm.client import HistoryMessage, complete, complete_with_image, complete_with_tools
from llm.documents_context import DocumentInfo, documents_context
from llm.pdf_extract import extract_pdf_text
from llm.pricing import compute_cost
from llm.time_context import time_context
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tools.executor import build_tool_executor, tool_specs_for_bindings
from tools.tool_loop import OverrideReply, run_tool_loop

from ..bus import IN_STREAM, OUT_STREAM, ensure_group, publish, read_group
from . import batching, handoff, lock
from .dedup import is_duplicate
from .filters import is_ignored_chat
from .media import incoming_content, quote_prefix

GROUP = "worker"

logger = structlog.get_logger("worker.pipeline")

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)

DEFAULT_BATCH_TIMEOUT_SECONDS = 1.0
DEFAULT_AUTO_RELEASE_MINUTES = 12
# FEATURES.md 9.10 — авто-реакция на входящее медиа, быстрый фидбек клиенту,
# пока готовится полноценный ответ. Без tool loop (сознательно, подтверждено
# пользователем) — деревянно простой shim в пайплайне, не через LLM.
DEFAULT_MEDIA_REACTION_ENABLED = True
DEFAULT_MEDIA_REACTION_EMOJI = "👍"
# Эталон V1 (FEATURES.md 4.3) — джиттер между отправляемыми медиа,
# анти-бан дисциплина (CLAUDE.md §7): не пачка фото залпом.
PHOTO_JITTER_MIN_SECONDS = 1.0
PHOTO_JITTER_MAX_SECONDS = 1.5
STORAGE_READ_TIMEOUT_SECONDS = 20.0
DEFAULT_REMINDER_DELAY_MINUTES = 60.0
FOLLOW_UP_SCHEDULE_TIMEOUT_SECONDS = 5.0
# Эталон V1 (analyzePdf): обрезка текста документа перед отправкой в LLM.
PDF_TEXT_MAX_CHARS = 15000
# Мультитенантная платформа на одной БД — бот с огромным каталогом не
# должен сажать токены/стоимость всем остальным (V1 такого лимита не
# имел — сознательное отличие, FEATURES.md 3.4).
PRODUCT_CATALOG_LIMIT = 200
# Тот же принцип, что PRODUCT_CATALOG_LIMIT — see Fix 1 of the 4.8/4.9
# retroactive review: list_documents() ран без лимита на каждый ответ,
# безвредно пока таблицу заполняют вручную, но Волна 3 (6.7, загрузка
# через UI) сделает это реальной проблемой.
DOCUMENTS_LIMIT = 200


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


def _media_reaction_enabled(bot: Bot) -> bool:
    return bool(bot.settings.get("media_reaction_enabled", DEFAULT_MEDIA_REACTION_ENABLED))


def _media_reaction_emoji(bot: Bot) -> str:
    value = bot.settings.get("media_reaction_emoji", DEFAULT_MEDIA_REACTION_EMOJI)
    return value if isinstance(value, str) and value else DEFAULT_MEDIA_REACTION_EMOJI


async def _react_to_media(event: InboundText, bot: Bot, redis: Redis) -> None:
    """FEATURES.md 9.10 — быстрый фидбек на фото/файл/видео клиента, ДО
    батчинга/лока/ответа: реакция не трогает общее состояние диалога, ждать
    очередь незачем. Живьём проверено на реальном номере (2026-09-12)."""
    reaction_event = OutboundReaction(
        bot_id=event.bot_id,
        chat_id=event.chat_id,
        reply_to_wa_msg_id=event.wa_msg_id,
        emoji=_media_reaction_emoji(bot),
        client_msg_id=uuid.uuid4().hex,
    )
    try:
        await publish(redis, OUT_STREAM, reaction_event.model_dump(mode="json"))
    except Exception:
        # Реакция — необязательный штрих, не должна ронять основной ответ.
        logger.warning(
            "failed to publish media reaction, continuing without it",
            bot_id=str(event.bot_id),
            wa_msg_id=event.wa_msg_id,
            exc_info=True,
        )


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
        content = quote_prefix(event.quoted_text, event.quoted_media_type) + incoming_content(
            event.text, event.media_type
        )
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

    if event.media_type is not None and _media_reaction_enabled(bot):
        await _react_to_media(event, bot, redis)

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
        async with lock.keep_alive(redis, bot_id_str, event.chat_id):
            if event.media_type == "image" and event.storage_key is not None and bot.image_prompt:
                await _reply_with_vision(event, bot, contact.id, redis, session_factory, storage)
            elif (
                event.media_type == "document"
                and event.mime_type == "application/pdf"
                and event.storage_key is not None
                and bot.pdf_prompt
            ):
                await _reply_with_pdf(event, bot, contact.id, redis, session_factory, storage)
            elif event.media_type is not None:
                await _reply_with_media_fallback(event, bot, contact.id, redis, session_factory)
            else:
                await _reply(event, bot, contact.id, redis, session_factory, storage)
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


async def _send_media_replies(
    event: InboundText, redis: Redis, replies: Sequence[OverrideReply]
) -> None:
    """FEATURES.md 4.3/4.4/4.8/4.9: карточки товара и файлы/видео —
    typing один раз, затем для каждой карточки её медиа (диспетчеризация
    по mime_type: image/* -> outbound.image, video/* -> outbound.video,
    остальное -> outbound.document) и текст, по порядку. Джиттер
    1000-1500 мс перед КАЖДЫМ медиа, кроме самого первого в этом ходе
    (включая между карточками/файлами) — эталон V1, анти-бан дисциплина.
    client_msg_id — новый .hex на КАЖДОЕ исходящее событие, как и в
    _send_reply."""
    typing_event = OutboundTyping(
        bot_id=event.bot_id, chat_id=event.chat_id, client_msg_id=uuid.uuid4().hex
    )
    await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))

    sent_media = False
    for reply in replies:
        for item in reply.media:
            if sent_media:
                await asyncio.sleep(
                    random.uniform(PHOTO_JITTER_MIN_SECONDS, PHOTO_JITTER_MAX_SECONDS)
                )
            # MIME-типы регистронезависимы (RFC 2045); Document.mime_type и
            # ProductImage-эквивалент — не ограниченные CHECK'ом String,
            # заполняются вручную SQL. Регистр нормализуем только для
            # диспетчеризации — оригинальное написание item.mime_type
            # уходит на wire как есть (см. mime_type= ниже).
            mime_type = item.mime_type.lower()
            media_event: OutboundImage | OutboundVideo | OutboundDocument
            if mime_type.startswith("video/"):
                media_event = OutboundVideo(
                    bot_id=event.bot_id,
                    chat_id=event.chat_id,
                    storage_key=item.storage_key,
                    mime_type=item.mime_type,
                    client_msg_id=uuid.uuid4().hex,
                )
            elif mime_type.startswith("image/"):
                media_event = OutboundImage(
                    bot_id=event.bot_id,
                    chat_id=event.chat_id,
                    storage_key=item.storage_key,
                    mime_type=item.mime_type,
                    client_msg_id=uuid.uuid4().hex,
                )
            else:
                if not item.filename:
                    # Сегодня недостижимо через реальные тулзы
                    # (SendDocumentTool всегда ставит filename;
                    # ProductSearchTool — только image/*) — лог на случай,
                    # если будущая тулза вернёт немедийный файл без имени.
                    logger.warning(
                        "media reply missing filename, using fallback",
                        bot_id=str(event.bot_id),
                        mime_type=item.mime_type,
                    )
                media_event = OutboundDocument(
                    bot_id=event.bot_id,
                    chat_id=event.chat_id,
                    storage_key=item.storage_key,
                    mime_type=item.mime_type,
                    filename=item.filename or "file",
                    client_msg_id=uuid.uuid4().hex,
                )
            await publish(redis, OUT_STREAM, media_event.model_dump(mode="json"))
            sent_media = True
        text_event = OutboundText(
            bot_id=event.bot_id,
            chat_id=event.chat_id,
            text=reply.text,
            client_msg_id=uuid.uuid4().hex,
        )
        await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))


async def _schedule_follow_up(
    bot: Bot,
    chat_id: str,
    contact_id: uuid.UUID,
    after_seq: int,
) -> None:
    """FEATURES.md 5.5: ставит Celery-задачу с eta, не таймер в памяти (см.
    "грабли" CLAUDE.md). Сбой постановки (Redis/Celery недоступен) — не
    должен маскировать уже успешно отправленный клиенту ответ: перехватываем
    здесь, не пробрасываем в общий except _process_entry.
    """
    if not bot.settings.get("reminder_enabled", False):
        return

    delay_value = bot.settings.get("reminder_delay_minutes", DEFAULT_REMINDER_DELAY_MINUTES)
    try:
        delay_minutes = float(delay_value)
    except (TypeError, ValueError):
        delay_minutes = DEFAULT_REMINDER_DELAY_MINUTES

    eta = datetime.now(UTC) + timedelta(minutes=delay_minutes)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                celery_app.send_task,
                FOLLOW_UP_REMINDER,
                args=[str(bot.id), str(contact_id), chat_id, after_seq],
                eta=eta,
            ),
            timeout=FOLLOW_UP_SCHEDULE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "failed to schedule follow-up reminder",
            bot_id=str(bot.id),
            chat_id=chat_id,
            exc_info=True,
        )


async def _reply(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    async with session_factory() as session:
        history_rows = await fetch_recent_history(session, contact_id)
        bindings = await list_enabled_tool_bindings(session, bot.id)
        products = await list_products(session, bot.id, limit=PRODUCT_CATALOG_LIMIT)
        # documents_context инструктирует LLM звать send_document — грузить
        # список файлов и показывать эту инструкцию боту, которому тулза не
        # привязана, бессмысленно и вводит модель в заблуждение (находка
        # финального ревью, Fix 6).
        bound_tool_names = {binding.tool_name for binding in bindings}
        documents = (
            await list_documents(session, bot.id, limit=DOCUMENTS_LIMIT)
            if "send_document" in bound_tool_names
            else []
        )

    history = [HistoryMessage(role=m.role, content=m.content) for m in history_rows]
    catalog = catalog_context(
        [
            ProductInfo(
                name=p.name,
                price=str(p.price) if p.price is not None else None,
                description=p.description,
            )
            for p in products
        ]
    )
    docs_ctx = (
        documents_context([DocumentInfo(filename=d.filename) for d in documents])
        if "send_document" in bound_tool_names
        else ""
    )
    # Порядок — как в V1 (agentInstructions + catalogContext + timeContext):
    # только основной текстовый путь, vision/PDF (image_prompt/pdf_prompt)
    # каталог/файлы не получают — эталон V1 (analyzeImage/analyzePdf) тоже.
    time_ctx = time_context(bot.timezone)
    # Пустые секции (docs_ctx == "" без send_document) пропускаются целиком,
    # а не вставляются как пустая строка — иначе в промпте остаются лишние
    # пустые строки подряд.
    sections = [bot.system_prompt, catalog, docs_ctx, time_ctx]
    system_prompt = "\n\n".join(section for section in sections if section)

    tool_specs = tool_specs_for_bindings(bindings)
    executor = build_tool_executor(bot, contact_id, session_factory, redis, storage, bindings)

    loop_result = await run_tool_loop(
        system_prompt,
        history,
        tool_specs,
        executor,
        complete_fn=complete,
        complete_with_tools_fn=complete_with_tools,
    )
    if loop_result.override_replies:
        # FEATURES.md 4.3/4.4: тулза(ы) нашли товар(ы) — клиенту уходят
        # ТОЛЬКО карточки, собственный текст LLM в этом ходе отбрасывается
        # (подтверждено пользователем, эталон V1). Несколько товаров в
        # одном ходе — несколько карточек по очереди, ни одна не теряется
        # (находка финального ревью — прежнее "последний выигрывает"
        # молча теряло более ранние товары).
        reply_text = "\n\n".join(reply.text for reply in loop_result.override_replies)
        await _send_media_replies(event, redis, loop_result.override_replies)
    else:
        if not loop_result.text.strip():
            logger.warning("LLM returned empty text, not sending", bot_id=str(event.bot_id))
            return
        reply_text = loop_result.text
        await _send_reply(event, redis, reply_text)

    cost = compute_cost(loop_result.model, loop_result.tokens_in, loop_result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, reply_text)
        await record_usage(
            session,
            event.bot_id,
            loop_result.model,
            loop_result.tokens_in,
            loop_result.tokens_out,
            cost,
        )
        await session.commit()
    await _schedule_follow_up(bot, event.chat_id, contact_id, outgoing_seq)


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
        caption = quote_prefix(event.quoted_text, event.quoted_media_type) + event.text
        result = await complete_with_image(
            system_prompt, history, caption, image_bytes, mime_type
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
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()
    await _schedule_follow_up(bot, event.chat_id, contact_id, outgoing_seq)


async def _reply_with_pdf(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    """FEATURES.md 2.4: текст PDF извлекается ДО вызова LLM — в отличие от
    vision, мультимодальный вызов не нужен, используем обычный complete()
    (документ уже стал обычным текстом). pdf_prompt бота — system prompt,
    ответ модели уходит клиенту напрямую (та же однопроходная архитектура,
    что и у vision, сознательно отличается от V1: там был второй LLM-проход
    поверх результата analyzePdf).

    Любой сбой на этом пути (storage, извлечение текста, сам вызов LLM,
    пустой ответ) — НЕ бросаем наружу: тихо деградируем в
    _reply_with_media_fallback, тот же принцип, что и у _reply_with_vision.
    """
    try:
        async with session_factory() as session:
            history_rows = await fetch_recent_history(session, contact_id)
        # Последняя строка — плейсхолдер текущего документа ("[документ]"),
        # уже вставленный insert_incoming выше по _process_entry; текущий
        # ход собирается заново из извлечённого текста, а не из плейсхолдера.
        history = [
            HistoryMessage(role=m.role, content=m.content) for m in history_rows[:-1]
        ]

        assert event.storage_key is not None  # гарантировано веткой в _process_entry
        pdf_bytes = await asyncio.wait_for(
            storage.get(event.storage_key), timeout=STORAGE_READ_TIMEOUT_SECONDS
        )
        pdf_text = extract_pdf_text(pdf_bytes)[:PDF_TEXT_MAX_CHARS]

        assert bot.pdf_prompt is not None  # гарантировано веткой в _process_entry
        system_prompt = f"{bot.pdf_prompt}\n\n{time_context(bot.timezone)}"
        current_turn = f"Текст документа:\n{pdf_text}"
        quoted_and_text = quote_prefix(event.quoted_text, event.quoted_media_type) + event.text
        if quoted_and_text:
            current_turn = f"{quoted_and_text}\n\n{current_turn}"
        history.append(HistoryMessage(role="user", content=current_turn))

        result = await complete(system_prompt, history)
        if not result.text.strip():
            logger.warning(
                "pdf LLM returned empty text, falling back", bot_id=str(event.bot_id)
            )
            await _reply_with_media_fallback(event, bot, contact_id, redis, session_factory)
            return
    except Exception:
        logger.warning(
            "pdf reply failed, falling back to media placeholder",
            bot_id=str(event.bot_id),
            chat_id=event.chat_id,
            exc_info=True,
        )
        await _reply_with_media_fallback(event, bot, contact_id, redis, session_factory)
        return

    await _send_reply(event, redis, result.text)

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()
    await _schedule_follow_up(bot, event.chat_id, contact_id, outgoing_seq)


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
    # `or DEFAULT` — не просто .get(key, default): явная пустая строка в
    # settings (например, сохранённая через форму настроек в admin-web)
    # не должна давать text="" — OutboundText требует min_length=1, падать
    # с ValidationError на реальном сообщении нельзя (найдено code review
    # настроек бота, 2026-09-09). Тот же паттерн уже используется для
    # reminder_message в services/celery/src/tasks/followup.py.
    text = bot.settings.get("media_fallback_text") or DEFAULT_MEDIA_FALLBACK_TEXT
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
