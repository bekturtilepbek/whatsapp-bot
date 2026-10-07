"""FEATURES.md 6.13: саммари диалога и температура клиента. Celery-задача с
eta (ставит worker после сообщения клиента, "диалог затих") — не вызов LLM в
запросе API, как делал V1 при открытии списка клиентов. При срабатывании
перепроверяет актуальность: revoke — оптимизация, не гарантия (ADR-003).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable

import structlog
from core.bus import make_redis
from core.redis_keys import summary_lock_key
from db.blocked_contacts import is_blocked
from db.bots import get_bot
from db.contacts import get_contact, set_contact_analysis
from db.engine import make_engine, make_session_factory
from db.messages import fetch_last_messages, has_newer_user_message
from db.usage import record_usage
from llm.pricing import compute_cost
from llm.summary import AnalysisOutcome, SummaryMessage, analyze_conversation
from redis.asyncio import Redis
from scheduling.celery_app import celery_app
from scheduling.task_names import CONTACT_SUMMARY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger("tasks.summary")

# V1: до 20 последних сообщений. Меньше двух — оценивать нечего (одно
# приветствие), токены не тратим.
HISTORY_LIMIT = 20
MIN_MESSAGES = 2
# С запасом больше visibility_timeout брокера (см. scheduling/celery_app.py).
LOCK_TTL_SECONDS = 172800

AnalyzeFn = Callable[[list[SummaryMessage]], Awaitable[AnalysisOutcome]]


async def _refresh_summary_async(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: str,
    contact_id: str,
    after_seq: int,
    *,
    analyze: AnalyzeFn = analyze_conversation,
) -> None:
    bot_uuid = uuid.UUID(bot_id)
    contact_uuid = uuid.UUID(contact_id)

    # Чтение — отдельной короткой сессией: вызов LLM может идти минуту с
    # ретраями, держать на это открытую транзакцию незачем.
    async with session_factory() as session:
        bot = await get_bot(session, bot_uuid)
        if bot is None or not bot.enabled:
            logger.info("summary skipped: bot missing or disabled", bot_id=bot_id)
            return
        contact = await get_contact(session, contact_uuid)
        if contact is None:
            logger.info("summary skipped: contact no longer exists", bot_id=bot_id)
            return
        if contact.wa_id and await is_blocked(session, bot_uuid, contact.wa_id):
            logger.info("summary skipped: contact is blocked", bot_id=bot_id)
            return
        if await has_newer_user_message(session, contact_uuid, after_seq):
            logger.info("summary skipped: client wrote again, newer task exists", bot_id=bot_id)
            return
        rows = await fetch_last_messages(session, contact_uuid, HISTORY_LIMIT)
        messages = [SummaryMessage(role=m.role, content=m.content) for m in rows]
    if len(messages) < MIN_MESSAGES:
        logger.info("summary skipped: dialog too short", bot_id=bot_id)
        return

    # Атомарная пометка ДО вызова модели (повторная доставка не жжёт токены).
    lock_key = summary_lock_key(contact_id, after_seq)
    if not await redis.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS):
        logger.info("summary skipped: already processed (duplicate delivery)", bot_id=bot_id)
        return

    try:
        outcome = await analyze(messages)
    except Exception:
        # Сеть/OpenAI: прежние значения не трогаем, пометку снимаем — повторная
        # доставка (или следующее сообщение клиента) попробует снова.
        await redis.delete(lock_key)
        logger.warning("summary failed", bot_id=bot_id, contact_id=contact_id, exc_info=True)
        return

    async with session_factory() as session:
        # Токены потрачены в любом случае — расход пишем и при нечитаемом ответе.
        cost = compute_cost(outcome.model, outcome.tokens_in, outcome.tokens_out)
        await record_usage(
            session, bot_uuid, outcome.model, outcome.tokens_in, outcome.tokens_out, cost
        )
        if outcome.analysis is not None:
            await set_contact_analysis(
                session, contact_uuid, outcome.analysis.summary, outcome.analysis.temperature
            )
        await session.commit()
    if outcome.analysis is None:
        logger.warning("summary: unusable model answer", bot_id=bot_id, contact_id=contact_id)
    else:
        logger.info(
            "summary updated",
            bot_id=bot_id,
            contact_id=contact_id,
            temperature=outcome.analysis.temperature,
        )


async def _run(bot_id: str, contact_id: str, after_seq: int) -> None:
    redis = make_redis()
    engine = make_engine()
    session_factory = make_session_factory(engine)
    try:
        await _refresh_summary_async(redis, session_factory, bot_id, contact_id, after_seq)
    finally:
        await redis.aclose()
        await engine.dispose()


@celery_app.task(name=CONTACT_SUMMARY)  # type: ignore[untyped-decorator]  # celery не публикует py.typed — декоратор неизбежно нетипизирован
def refresh_contact_summary(bot_id: str, contact_id: str, after_seq: int) -> None:
    asyncio.run(_run(bot_id, contact_id, after_seq))
