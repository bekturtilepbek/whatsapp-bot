"""Handoff (STAGE1_CORE Блок 3): менеджер отвечает вручную -> бот молчит.

Требует Docker (testcontainers-postgres); Redis — fakeredis, как весь блок.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from core.redis_keys import handoff_key, wa_sent_key
from db.engine import make_engine, make_session_factory
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker недоступен в этом окружении"
)


@pytest.fixture(scope="module")
def database_url() -> AsyncIterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="psycopg2") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        yield url


@pytest.fixture
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


CHAT_ID = "996700000000@s.whatsapp.net"


class _NullStorage:
    """Заглушка для тестов, которые не доходят до vision-ветки — она никогда
    не должна вызываться, поэтому падает явно, а не тихо возвращает мусор.
    """

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], **settings_overrides: object
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02, **settings_overrides},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _now_ms() -> int:
    # Реальный "сейчас", не устаревшая фиксированная константа: insert_outgoing
    # (Блок 2 фикс) пишет ts = datetime.now(UTC), а insert_incoming — ts из
    # события. Смешивать в одном тесте на порядок старую фиксированную дату
    # с "сейчас" — ломает ORDER BY ts независимо от реального порядка вызовов.
    return int(datetime.now(UTC).timestamp() * 1000)


def _from_me_payload(
    bot_id: uuid.UUID, wa_msg_id: str, text: str, ts: int | None = None
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": CHAT_ID,
        "sender_wa_id": "996700000000",
        "from_me": True,
        "text": text,
        "ts": ts if ts is not None else _now_ms(),
    }


def _customer_payload(
    bot_id: uuid.UUID, wa_msg_id: str, text: str, ts: int | None = None
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": CHAT_ID,
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": text,
        "ts": ts if ts is not None else _now_ms(),
    }


async def _messages(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID
) -> list[Message]:
    async with session_factory() as session:
        result = await session.execute(
            select(Message).where(Message.bot_id == bot_id).order_by(Message.seq)
        )
        return list(result.scalars().all())


async def test_manager_reply_sets_handoff_and_logs_with_prefix(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        payload = _from_me_payload(bot_id, "wamsg-manager-1", "Да, привезём завтра")
        await _process_entry(payload, redis, session_factory, _NullStorage())

        assert await redis.exists(handoff_key(str(bot_id), CHAT_ID))
        messages = await _messages(session_factory, bot_id)
        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].content == "[Ответ менеджера] Да, привезём завтра"
    finally:
        await redis.aclose()


async def test_customer_message_during_handoff_is_logged_but_not_replied(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться, пока активен handoff")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        manager_payload = _from_me_payload(bot_id, "wamsg-manager-2", "Уже занимаюсь")
        await _process_entry(manager_payload, redis, session_factory, _NullStorage())
        customer_payload = _customer_payload(bot_id, "wamsg-customer-1", "А когда доставка?")
        await _process_entry(customer_payload, redis, session_factory, _NullStorage())

        assert await redis.xlen("wa:out") == 0  # бот не ответил
        messages = await _messages(session_factory, bot_id)
        assert [m.role for m in messages] == ["assistant", "user"]
        assert messages[1].content == "А когда доставка?"
    finally:
        await redis.aclose()


async def test_own_echo_is_fully_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        # Эмулируем то, что уже сделал gateway при реальной отправке (Блок 1/3):
        # SET wa:sent:{client_msg_id} ДО отправки, а сам wa_msg_id = client_msg_id.
        await redis.set(wa_sent_key("own-msg-id-1"), "1")

        await _process_entry(
            _from_me_payload(bot_id, "own-msg-id-1", "Да, доставка есть."),
            redis,
            session_factory,
            _NullStorage(),
        )

        assert not await redis.exists(handoff_key(str(bot_id), CHAT_ID))
        assert await _messages(session_factory, bot_id) == []
    finally:
        await redis.aclose()


async def test_second_manager_message_extends_ttl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, auto_release_minutes=12)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _from_me_payload(bot_id, "wamsg-manager-3", "первое"),
            redis,
            session_factory,
            _NullStorage(),
        )
        key = handoff_key(str(bot_id), CHAT_ID)
        first_ttl = await redis.ttl(key)
        assert first_ttl > 700  # ~12 минут

        # Искусственно укорачиваем, чтобы отличить "продлилось" от "было и осталось"
        await redis.expire(key, 5)
        assert await redis.ttl(key) <= 5

        await _process_entry(
            _from_me_payload(bot_id, "wamsg-manager-4", "второе"),
            redis,
            session_factory,
            _NullStorage(),
        )
        assert await redis.ttl(key) > 700  # снова продлилось до полного окна
    finally:
        await redis.aclose()


async def test_media_manager_message_gets_placeholder_with_prefix(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    payload = _from_me_payload(bot_id, "wamsg-manager-5", "")
    payload["media_type"] = "image"
    try:
        await _process_entry(payload, redis, session_factory, _NullStorage())

        messages = await _messages(session_factory, bot_id)
        assert messages[0].content == "[Ответ менеджера] [фото]"
    finally:
        await redis.aclose()
