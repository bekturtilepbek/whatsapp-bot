"""Рабочий график (FEATURES.md 1.6): вне графика сообщение записывается в
историю, но бот не отвечает — ни ответа, ни "прочитано", ни "печатает", ни
реакции (тот же принцип "принимаем и логируем", что у паузы 1.7 и чёрного
списка 1.5; в V1 сообщение вне графика терялось совсем). Менеджер (from_me)
работает круглосуточно.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("testcontainers.postgres")
from core.redis_keys import handoff_key
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)

CHAT_ID = "996700000077@s.whatsapp.net"


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError


def _closed_now_settings() -> dict[str, object]:
    # Окно в 1 час, которое точно НЕ содержит текущий час Бишкека.
    hour = datetime.now(ZoneInfo("Asia/Bishkek")).hour
    return {
        "batch_timeout_seconds": 0.02,
        "schedule_enabled": True,
        "work_start_hour": (hour + 2) % 24,
        "work_end_hour": (hour + 3) % 24,
    }


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="schedule-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings=_closed_now_settings(),
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _payload(bot_id: uuid.UUID, *, from_me: bool = False, media: bool = False) -> dict[str, object]:
    p: dict[str, object] = {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": uuid.uuid4().hex,
        "chat_id": CHAT_ID,
        "sender_wa_id": "996700000077",
        "from_me": from_me,
        "text": "" if media else "Вы работаете?",
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }
    if media:
        p["media_type"] = "image"
    return p


async def _messages(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID
) -> list[Message]:
    async with session_factory() as session:
        result = await session.execute(select(Message).where(Message.bot_id == bot_id))
        return list(result.scalars().all())


@pytest.mark.parametrize("media", [False, True])
async def test_outside_schedule_message_is_recorded_but_bot_stays_silent(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    media: bool,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться вне рабочего графика")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_payload(bot_id, media=media), redis, session_factory, _NullStorage())
        # ни ответа, ни seen, ни typing, ни реакции на фото
        assert await redis.xlen("wa:out") == 0
        assert len(await _messages(session_factory, bot_id)) == 1
    finally:
        await redis.aclose()


async def test_manager_reply_is_handled_outside_schedule(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_payload(bot_id, from_me=True), redis, session_factory, _NullStorage())
        assert await redis.exists(handoff_key(str(bot_id), CHAT_ID))
    finally:
        await redis.aclose()
