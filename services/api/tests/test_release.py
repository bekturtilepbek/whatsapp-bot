"""POST /bots/{id}/chats/{chatId}/release — ручной возврат чата боту (5.3)
и запись события released_manual (5.7).

testcontainers-postgres (события, FK на bots/users) + fakeredis (handoff-ключ).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from api.redis_client import get_redis
from core.redis_keys import handoff_key
from db.contacts import match_or_create_contact
from db.engine import make_engine, make_session_factory
from db.models import Bot, HandoffEvent, User
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import FAKE_OWNER_USER, override_owner_auth

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"
CHAT_ID = "996700000050@s.whatsapp.net"


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
    return make_session_factory(make_engine(database_url))


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeRedis]]:
    override_owner_auth()
    # actor_user_id — FK на users: подложенный override-пользователь должен
    # существовать в БД. Один раз на модуль-БД (email уникален).
    async with session_factory() as session:
        exists = await session.get(User, FAKE_OWNER_USER.id)
        if exists is None:
            session.add(
                User(
                    id=FAKE_OWNER_USER.id,
                    email=FAKE_OWNER_USER.email,
                    password_hash="unused",
                    role="superadmin",
                )
            )
            await session.commit()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    redis = FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: redis
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, redis
    app.dependency_overrides.clear()
    await redis.aclose()


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def _events(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID
) -> list[HandoffEvent]:
    async with session_factory() as session:
        result = await session.execute(select(HandoffEvent).where(HandoffEvent.bot_id == bot_id))
        return list(result.scalars().all())


async def test_release_deletes_active_handoff_key(
    client: tuple[httpx.AsyncClient, FakeRedis],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    c, redis = client
    bot_id = await _make_bot(session_factory)
    await redis.set(handoff_key(str(bot_id), CHAT_ID), "1", ex=720)

    response = await c.post(f"/bots/{bot_id}/chats/{CHAT_ID}/release")

    assert response.status_code == 200
    assert not await redis.exists(handoff_key(str(bot_id), CHAT_ID))


async def test_release_records_manual_release_event_with_actor_and_contact(
    client: tuple[httpx.AsyncClient, FakeRedis],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    c, redis = client
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        contact = await match_or_create_contact(
            session, bot_id, wa_id="996700000050", lid=None, name="Айгуль"
        )
        await session.commit()
        contact_id = contact.id
    await redis.set(handoff_key(str(bot_id), CHAT_ID), "1", ex=720)

    await c.post(f"/bots/{bot_id}/chats/{CHAT_ID}/release")

    events = await _events(session_factory, bot_id)
    assert [e.kind for e in events] == ["released_manual"]
    assert events[0].chat_id == CHAT_ID
    assert events[0].contact_id == contact_id
    assert events[0].actor_user_id == FAKE_OWNER_USER.id


async def test_release_on_no_active_handoff_is_a_noop_and_records_nothing(
    client: tuple[httpx.AsyncClient, FakeRedis],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    c, _redis = client
    bot_id = await _make_bot(session_factory)

    response = await c.post(f"/bots/{bot_id}/chats/{CHAT_ID}/release")

    assert response.status_code == 200  # не падает, даже если ключа не было
    assert await _events(session_factory, bot_id) == []


async def test_repeated_release_records_a_single_event(
    client: tuple[httpx.AsyncClient, FakeRedis],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    c, redis = client
    bot_id = await _make_bot(session_factory)
    await redis.set(handoff_key(str(bot_id), CHAT_ID), "1", ex=720)

    await c.post(f"/bots/{bot_id}/chats/{CHAT_ID}/release")
    await c.post(f"/bots/{bot_id}/chats/{CHAT_ID}/release")

    assert len(await _events(session_factory, bot_id)) == 1
