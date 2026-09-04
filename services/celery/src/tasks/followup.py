"""FEATURES.md 5.5: напоминание молчащему клиенту. Celery-задача с eta —
не таймер в памяти (см. "грабли" CLAUDE.md). При срабатывании
перепроверяет актуальность условия (revoke — оптимизация, не гарантия,
ADR-003): бот всё ещё включён и настроен слать напоминания, handoff не
активен, клиент ничего не написал с момента постановки задачи.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from core.bus import OUT_STREAM, make_redis, publish
from core.events import OutboundText, OutboundTyping
from core.redis_keys import handoff_key
from db.bots import get_bot
from db.engine import make_engine, make_session_factory
from db.messages import insert_outgoing
from db.models import Message
from redis.asyncio import Redis
from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEFAULT_REMINDER_MESSAGE = (
    "Здравствуйте! Подскажите, удалось ли ознакомиться с информацией? "
    "Если есть вопросы — я на связи!"
)

logger = structlog.get_logger("tasks.followup")


async def _send_reminder_async(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: str,
    contact_id: str,
    chat_id: str,
    after_seq: int,
) -> None:
    async with session_factory() as session:
        bot = await get_bot(session, uuid.UUID(bot_id))
        if bot is None or not bot.enabled:
            logger.info("follow-up skipped: bot missing or disabled", bot_id=bot_id)
            return
        if not bot.settings.get("reminder_enabled", False):
            logger.info(
                "follow-up skipped: reminders disabled since scheduling", bot_id=bot_id
            )
            return
        if await redis.exists(handoff_key(bot_id, chat_id)):
            logger.info("follow-up skipped: handoff active", bot_id=bot_id, chat_id=chat_id)
            return

        newer = await session.execute(
            select(Message.id)
            .where(
                Message.contact_id == uuid.UUID(contact_id),
                Message.role == "user",
                Message.seq > after_seq,
            )
            .limit(1)
        )
        if newer.scalar_one_or_none() is not None:
            logger.info(
                "follow-up skipped: customer already replied", bot_id=bot_id, chat_id=chat_id
            )
            return

        text = bot.settings.get("reminder_message", DEFAULT_REMINDER_MESSAGE)
        typing_event = OutboundTyping(
            bot_id=bot.id, chat_id=chat_id, client_msg_id=uuid.uuid4().hex
        )
        text_event = OutboundText(
            bot_id=bot.id, chat_id=chat_id, text=text, client_msg_id=uuid.uuid4().hex
        )
        await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))
        await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))
        await insert_outgoing(session, bot.id, uuid.UUID(contact_id), text)
        await session.commit()
        logger.info("follow-up reminder sent", bot_id=bot_id, chat_id=chat_id)


async def _run(bot_id: str, contact_id: str, chat_id: str, after_seq: int) -> None:
    redis = make_redis()
    engine = make_engine()
    session_factory = make_session_factory(engine)
    try:
        await _send_reminder_async(
            redis, session_factory, bot_id, contact_id, chat_id, after_seq
        )
    finally:
        await redis.aclose()
        await engine.dispose()


@celery_app.task(name=FOLLOW_UP_REMINDER)
def send_reminder(bot_id: str, contact_id: str, chat_id: str, after_seq: int) -> None:
    asyncio.run(_run(bot_id, contact_id, chat_id, after_seq))
