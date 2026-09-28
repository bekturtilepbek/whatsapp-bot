"""GET/POST/DELETE /bots/{id}/blocked-numbers (FEATURES.md 1.5)."""

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
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.state.audit_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None


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
    response = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert response.status_code == 200
    assert response.json() == []


async def test_post_adds_number_stripping_non_digits(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/blocked-numbers", json={"phone": "+996 700-00-00-00"}
    )
    assert response.status_code == 201
    assert response.json()["phone"] == "996700000000"

    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert [item["phone"] for item in listing.json()] == ["996700000000"]


@pytest.mark.parametrize("phone", ["abc", "", "   ", "<script>", "1", "123456", "9" * 16])
async def test_post_rejects_what_is_not_a_phone_number(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession], phone: str
) -> None:
    """Регрессия 2026-09-28: "abc" после очистки от не-цифр превращался в ""
    и сохранялся — пустая строка в списке, которую нельзя удалить (DELETE
    /blocked-numbers/ с пустым сегментом — 405). Номер WhatsApp — это wa_id
    с кодом страны: 7–15 цифр (E.164)."""
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": phone})
    assert response.status_code == 422

    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert listing.json() == []


async def test_post_is_idempotent(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    response = await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    assert response.status_code == 201  # не ошибка при повторе
    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert len(listing.json()) == 1


async def test_delete_removes_number(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    response = await client.delete(f"/bots/{bot_id}/blocked-numbers/996700000000")
    assert response.status_code == 204

    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert listing.json() == []


async def test_delete_unknown_number_is_still_204(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.delete(f"/bots/{bot_id}/blocked-numbers/000000000000")
    assert response.status_code == 204


async def test_list_scoped_to_bot(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_a = await _make_bot(session_factory)
    bot_b = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_a}/blocked-numbers", json={"phone": "996700000001"})
    await client.post(f"/bots/{bot_b}/blocked-numbers", json={"phone": "996700000002"})

    listing = await client.get(f"/bots/{bot_a}/blocked-numbers")
    assert [item["phone"] for item in listing.json()] == ["996700000001"]


async def test_list_respects_limit_and_offset(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    # created_at.desc() — последний добавленный первым, поэтому проверяем
    # страницы в обратном порядке добавления.
    for phone in ("996700000001", "996700000002", "996700000003"):
        await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": phone})

    first_page = await client.get(f"/bots/{bot_id}/blocked-numbers", params={"limit": 2})
    assert [item["phone"] for item in first_page.json()] == [
        "996700000003",
        "996700000002",
    ]

    second_page = await client.get(
        f"/bots/{bot_id}/blocked-numbers", params={"limit": 2, "offset": 2}
    )
    assert [item["phone"] for item in second_page.json()] == ["996700000001"]


async def test_list_limit_out_of_range_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    assert (
        await client.get(f"/bots/{bot_id}/blocked-numbers", params={"limit": 0})
    ).status_code == 422
    assert (
        await client.get(f"/bots/{bot_id}/blocked-numbers", params={"limit": 101})
    ).status_code == 422
