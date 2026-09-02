"""Пайплайн Шага 2: дедуп -> фильтры -> contact -> запись входящего -> enabled.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
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
            env={"DATABASE_URL": url},
        )
        yield url


@pytest.fixture
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], enabled: bool = True
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="test-bot", enabled=enabled)
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(bot_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "привет",
        "ts": 1756800000000,
    }
    payload.update(overrides)
    return payload


async def _count_messages(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        result = await session.execute(select(Message))
        return len(result.scalars().all())


async def test_enabled_bot_writes_incoming_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory)
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory) == 1


async def test_disabled_bot_still_writes_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FEATURES.md: enabled=false -> молчим, но историю пишем."""
    bot_id = await _make_bot(session_factory, enabled=False)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory)
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory) == 1


async def test_duplicate_wa_msg_id_is_not_written_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory)
        await _process_entry(_inbound_payload(bot_id), redis, session_factory)
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory) == 1


async def test_from_me_event_is_not_written(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id, from_me=True), redis, session_factory)
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory) == 0


async def test_group_chat_event_is_not_written(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(
            _inbound_payload(bot_id, chat_id="120363000000000000@g.us"), redis, session_factory
        )
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory) == 0


async def test_session_status_event_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    payload = {"type": "session.status", "bot_id": str(bot_id), "status": "open", "ts": 1}
    try:
        await _process_entry(payload, redis, session_factory)
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory) == 0
