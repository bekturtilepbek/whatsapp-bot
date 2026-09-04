"""GET/POST/DELETE /bots/{id}/tools (FEATURES.md 4.13, инфраструктура)."""

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
from db.engine import make_engine, make_session_factory
from db.models import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import registry as tools_registry

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
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_list_is_empty_by_default(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/tools")
    assert response.status_code == 200
    assert response.json() == []


async def test_post_unknown_tool_name_is_rejected(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/tools", json={"tool_name": "does_not_exist"})
    assert response.status_code == 400

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == []


async def test_post_known_tool_name_enables_it_with_config(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(tools_registry._REGISTRY, "search", object())
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/tools", json={"tool_name": "search", "config": {"limit": 3}}
    )
    assert response.status_code == 201
    assert response.json() == {"tool_name": "search", "config": {"limit": 3}}

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == [{"tool_name": "search", "config": {"limit": 3}}]


async def test_post_is_idempotent_and_updates_config(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(tools_registry._REGISTRY, "search", object())
    bot_id = await _make_bot(session_factory)

    await client.post(f"/bots/{bot_id}/tools", json={"tool_name": "search", "config": {"limit": 3}})
    response = await client.post(
        f"/bots/{bot_id}/tools", json={"tool_name": "search", "config": {"limit": 5}}
    )
    assert response.status_code == 201

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == [{"tool_name": "search", "config": {"limit": 5}}]


async def test_delete_removes_tool(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(tools_registry._REGISTRY, "search", object())
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/tools", json={"tool_name": "search"})

    response = await client.delete(f"/bots/{bot_id}/tools/search")
    assert response.status_code == 204

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == []


async def test_delete_unknown_tool_is_still_204(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.delete(f"/bots/{bot_id}/tools/does_not_exist")
    assert response.status_code == 204
