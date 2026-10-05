"""GET /bots/{id}/overview — агрегаты для "Обзора" бота (FEATURES.md 6.23).

Данные кладём в БД напрямую с явными ts/created_at, чтобы не зависеть от
часов: окно — скользящее (сейчас минус период), граница проверяется явно.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from db.engine import make_engine, make_session_factory
from db.models import Bot, Contact, HandoffEvent, Message
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_non_owner_auth, override_owner_auth

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
    return make_session_factory(make_engine(database_url))


@pytest.fixture(autouse=True)
async def _clean_handoff_events(session_factory: async_sessionmaker[AsyncSession]) -> None:
    # handoff_tracked_since — минимум по всей таблице: без очистки события
    # соседних тестов модуля подмешивались бы в него.
    async with session_factory() as session:
        await session.execute(text("TRUNCATE handoff_events"))
        await session.commit()


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


def _ago(**kwargs: float) -> datetime:
    return datetime.now(UTC) - timedelta(**kwargs)


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="overview-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def _make_contact(
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: uuid.UUID,
    n: int,
    created_at: datetime,
) -> uuid.UUID:
    async with session_factory() as session:
        contact = Contact(bot_id=bot_id, wa_id=f"99670000{n:04d}", created_at=created_at)
        session.add(contact)
        await session.flush()
        await session.commit()
        return contact.id


async def _add_message(
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    role: str,
    ts: datetime,
) -> None:
    async with session_factory() as session:
        session.add(
            Message(
                bot_id=bot_id,
                contact_id=contact_id,
                role=role,
                content="x",
                wa_msg_id=uuid.uuid4().hex if role == "user" else None,
                ts=ts,
            )
        )
        await session.commit()


async def _add_handoff(
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    created_at: datetime,
    kind: str = "started",
) -> None:
    async with session_factory() as session:
        session.add(
            HandoffEvent(
                bot_id=bot_id,
                chat_id="996700000000@s.whatsapp.net",
                contact_id=contact_id,
                kind=kind,
                created_at=created_at,
            )
        )
        await session.commit()


async def test_counts_messages_and_clients_inside_window_only(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    fresh = await _make_contact(session_factory, bot_id, 1, _ago(days=2))
    old = await _make_contact(session_factory, bot_id, 2, _ago(days=20))
    await _add_message(session_factory, bot_id, fresh, "user", _ago(days=1))
    await _add_message(session_factory, bot_id, fresh, "user", _ago(hours=5))
    await _add_message(session_factory, bot_id, fresh, "assistant", _ago(hours=5))
    await _add_message(session_factory, bot_id, old, "user", _ago(days=3))  # старый клиент, активен
    await _add_message(session_factory, bot_id, old, "user", _ago(days=9))  # вне окна 7d

    body = (await client.get(f"/bots/{bot_id}/overview?period=7d")).json()

    assert body["period"] == "7d"
    assert body["messages_in"] == 3
    assert body["messages_out"] == 1
    assert body["clients_active"] == 2
    assert body["clients_new"] == 1  # old создан 20 дней назад


async def test_default_period_is_7d(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/overview")
    assert response.status_code == 200
    assert response.json()["period"] == "7d"


async def test_does_not_count_other_bots(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    other_id = await _make_bot(session_factory)
    other_contact = await _make_contact(session_factory, other_id, 3, _ago(days=1))
    await _add_message(session_factory, other_id, other_contact, "user", _ago(hours=1))

    body = (await client.get(f"/bots/{bot_id}/overview")).json()

    assert body["messages_in"] == 0
    assert body["clients_active"] == 0
    assert body["clients_new"] == 0


async def test_resolved_without_human_pct_and_handoffs(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    contacts = [await _make_contact(session_factory, bot_id, n, _ago(days=3)) for n in range(4)]
    for cid in contacts:
        await _add_message(session_factory, bot_id, cid, "user", _ago(days=1))
    # Эпизод у одного из четырёх клиентов; второе событие "released_manual" не считается.
    await _add_handoff(session_factory, bot_id, contacts[0], _ago(days=1))
    await _add_handoff(session_factory, bot_id, contacts[0], _ago(hours=20), "released_manual")
    # Отслеживание началось раньше начала окна 7d.
    other_bot = await _make_bot(session_factory)
    other_contact = await _make_contact(session_factory, other_bot, 9, _ago(days=30))
    await _add_handoff(session_factory, other_bot, other_contact, _ago(days=10))

    body = (await client.get(f"/bots/{bot_id}/overview?period=7d")).json()

    assert body["handoffs"] == 1
    assert body["clients_active"] == 4
    assert body["resolved_without_human_pct"] == 75
    assert body["handoff_tracked_since"] is not None


async def test_pct_is_null_when_window_starts_before_tracking(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    cid = await _make_contact(session_factory, bot_id, 1, _ago(days=3))
    await _add_message(session_factory, bot_id, cid, "user", _ago(hours=2))
    await _add_handoff(session_factory, bot_id, cid, _ago(days=2))  # трекинг начался 2 дня назад

    week = (await client.get(f"/bots/{bot_id}/overview?period=7d")).json()
    day = (await client.get(f"/bots/{bot_id}/overview?period=24h")).json()

    assert week["resolved_without_human_pct"] is None  # окно 7d начинается раньше трекинга
    assert week["handoffs"] == 1  # сами счётчики отдаём как есть
    assert day["resolved_without_human_pct"] is not None  # окно 24h целиком после начала


async def test_pct_is_null_when_no_handoff_events_exist_anywhere(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    cid = await _make_contact(session_factory, bot_id, 1, _ago(days=3))
    await _add_message(session_factory, bot_id, cid, "user", _ago(hours=2))

    body = (await client.get(f"/bots/{bot_id}/overview?period=24h")).json()

    assert body["handoff_tracked_since"] is None
    assert body["resolved_without_human_pct"] is None


async def test_pct_is_null_when_no_active_clients(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    other = await _make_bot(session_factory)
    cid = await _make_contact(session_factory, other, 5, _ago(days=40))
    await _add_handoff(session_factory, other, cid, _ago(days=35))  # трекинг давно идёт

    body = (await client.get(f"/bots/{bot_id}/overview?period=7d")).json()

    assert body["clients_active"] == 0
    assert body["resolved_without_human_pct"] is None


async def test_previous_window_is_the_adjacent_one(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    cid = await _make_contact(session_factory, bot_id, 1, _ago(days=40))
    await _add_message(session_factory, bot_id, cid, "user", _ago(days=2))  # текущее окно 7d
    await _add_message(session_factory, bot_id, cid, "user", _ago(days=9))  # предыдущее 7–14d
    await _add_message(session_factory, bot_id, cid, "user", _ago(days=10))  # предыдущее
    await _add_message(session_factory, bot_id, cid, "user", _ago(days=20))  # вне обоих

    body = (await client.get(f"/bots/{bot_id}/overview?period=7d")).json()

    assert body["messages_in"] == 1
    assert body["previous"]["messages_in"] == 2
    assert body["previous"]["clients_active"] == 1


async def test_invalid_period_is_rejected(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/overview?period=1y")
    assert response.status_code == 422


async def test_client_without_access_gets_403(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    override_non_owner_auth()  # client без bot_access на этого бота

    response = await client.get(f"/bots/{bot_id}/overview")

    assert response.status_code == 403
