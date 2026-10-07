"""GET /bots/{id}/chats — вкладка "Активные чаты" (5.3, ручной возврат).

Комбинирует testcontainers-postgres (найти имя контакта по chat_id) и
fakeredis (SCAN по активным handoff-ключам) — тот же паттерн, что и
test_bots.py/test_release.py по отдельности.
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
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_owner_auth

REPO_ROOT = Path(__file__).resolve().parents[3]
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


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeRedis]]:
    override_owner_auth()

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


async def test_returns_empty_list_when_nothing_is_active(
    client: tuple[httpx.AsyncClient, FakeRedis], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    c, _redis = client
    bot_id = await _make_bot(session_factory)
    response = await c.get(f"/bots/{bot_id}/chats")
    assert response.status_code == 200
    assert response.json() == []


async def test_lists_active_chat_with_ttl_and_matched_contact_name(
    client: tuple[httpx.AsyncClient, FakeRedis], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    c, redis = client
    bot_id = await _make_bot(session_factory)
    chat_id = "996700000040@s.whatsapp.net"
    async with session_factory() as session:
        await match_or_create_contact(
            session, bot_id, wa_id="996700000040", lid=None, name="Айгуль"
        )
        await session.commit()
    await redis.set(handoff_key(str(bot_id), chat_id), "1", ex=600)

    response = await c.get(f"/bots/{bot_id}/chats")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["chat_id"] == chat_id
    assert body[0]["contact_name"] == "Айгуль"
    assert 0 < body[0]["auto_release_in_seconds"] <= 600


async def test_lists_active_chat_without_a_matching_contact(
    client: tuple[httpx.AsyncClient, FakeRedis], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    c, redis = client
    bot_id = await _make_bot(session_factory)
    chat_id = "996700000041@s.whatsapp.net"
    await redis.set(handoff_key(str(bot_id), chat_id), "1", ex=600)

    response = await c.get(f"/bots/{bot_id}/chats")

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "chat_id": chat_id,
            "contact_name": None,
            "contact_phone": None,
            "temperature": None,
            "summary": None,
            "auto_release_in_seconds": body[0]["auto_release_in_seconds"],
        }
    ]


async def test_does_not_leak_another_bots_active_chats(
    client: tuple[httpx.AsyncClient, FakeRedis], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    c, redis = client
    bot_a = await _make_bot(session_factory)
    bot_b = await _make_bot(session_factory)
    await redis.set(handoff_key(str(bot_a), "996700000042@s.whatsapp.net"), "1", ex=600)
    await redis.set(handoff_key(str(bot_b), "996700000043@s.whatsapp.net"), "1", ex=600)

    response = await c.get(f"/bots/{bot_a}/chats")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["chat_id"] == "996700000042@s.whatsapp.net"


async def test_active_chat_shows_temperature_and_summary_of_matched_contact(
    client: tuple[httpx.AsyncClient, FakeRedis], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from db.contacts import set_contact_analysis

    c, redis = client
    bot_id = await _make_bot(session_factory)
    chat_id = "996700000044@s.whatsapp.net"
    async with session_factory() as session:
        contact = await match_or_create_contact(
            session, bot_id, wa_id="996700000044", lid=None, name="Бакыт"
        )
        await set_contact_analysis(
            session, contact.id, "Выбирает шкаф, спрашивает доставку.", "hot"
        )
        await session.commit()
    await redis.set(handoff_key(str(bot_id), chat_id), "1", ex=600)

    body = (await c.get(f"/bots/{bot_id}/chats")).json()

    assert body[0]["temperature"] == "hot"
    assert body[0]["summary"] == "Выбирает шкаф, спрашивает доставку."


async def test_active_chat_of_not_yet_assessed_contact_has_empty_analysis(
    client: tuple[httpx.AsyncClient, FakeRedis], session_factory: async_sessionmaker[AsyncSession]
) -> None:
    c, redis = client
    bot_id = await _make_bot(session_factory)
    chat_id = "996700000045@s.whatsapp.net"
    async with session_factory() as session:
        await match_or_create_contact(session, bot_id, wa_id="996700000045", lid=None, name="Нур")
        await session.commit()
    await redis.set(handoff_key(str(bot_id), chat_id), "1", ex=600)

    body = (await c.get(f"/bots/{bot_id}/chats")).json()

    assert body[0]["temperature"] is None
    assert body[0]["summary"] is None
