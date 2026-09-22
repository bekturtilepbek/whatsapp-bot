"""GET /usage (FEATURES.md 6.15): владелец платформы видит сумму
токенов/стоимости по боту за период.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from db.engine import make_engine, make_session_factory
from db.models import Bot
from db.usage import record_usage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_admin_auth, override_non_owner_auth, override_owner_auth

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
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], *, name: str = "test-bot"
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name=name, enabled=True, system_prompt="", timezone="Asia/Bishkek", settings={})
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_get_usage_returns_summary_per_bot(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await record_usage(session, bot_id, "gpt-4o-mini", 100, 20, Decimal("0.01"))
        await record_usage(session, bot_id, "gpt-4o-mini", 200, 30, Decimal("0.02"))
        await session.commit()

    response = await client.get("/usage")
    assert response.status_code == 200
    body = [row for row in response.json() if row["bot_id"] == str(bot_id)]
    assert len(body) == 1
    assert body[0]["tokens_in"] == 300
    assert body[0]["tokens_out"] == 50
    assert body[0]["cost"] == "0.030000"


async def test_get_usage_excludes_bot_with_no_usage(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory, name="idle-bot-for-usage-test")

    response = await client.get("/usage")
    assert response.status_code == 200
    assert all(row["bot_id"] != str(bot_id) for row in response.json())


async def test_get_usage_period_all_ignores_time_window(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory, name="all-time-bot")
    async with session_factory() as session:
        await record_usage(session, bot_id, "gpt-4o-mini", 10, 5, Decimal("0.001"))
        await session.commit()

    response = await client.get("/usage?period=all")
    assert response.status_code == 200
    body = [row for row in response.json() if row["bot_id"] == str(bot_id)]
    assert len(body) == 1


async def test_get_usage_invalid_period_returns_422(client: httpx.AsyncClient) -> None:
    response = await client.get("/usage?period=bogus")
    assert response.status_code == 422


async def test_get_usage_non_owner_returns_403(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    override_non_owner_auth()
    response = await client.get("/usage")
    assert response.status_code == 403


async def test_get_usage_admin_gets_200(client: httpx.AsyncClient) -> None:
    """Ролевой пересмотр 2026-09-22: /usage — PlatformWide (superadmin И
    admin), в отличие от /users (только superadmin)."""
    override_admin_auth()
    response = await client.get("/usage")
    assert response.status_code == 200
