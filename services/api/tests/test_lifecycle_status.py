"""bots.lifecycle_status — служебный статус клиента-бота (FEATURES.md 6.22).

Видят и меняют только superadmin/admin (PlatformWide); prompter/client
получают в BotOut null и менять не могут. На работу пайплайна не влияет.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.audit import ACTION_REGISTRY
from api.db import get_session
from api.main import app
from api.security import get_current_user
from db.bot_access import grant_bot_access
from db.engine import make_engine, make_session_factory
from db.models import Bot, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_admin_auth, override_owner_auth

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


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="lifecycle-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def _act_as(
    session_factory: async_sessionmaker[AsyncSession], role: str, bot_id: uuid.UUID
) -> None:
    """Реальный пользователь с грантом на бота (client/prompter проходят
    BotAccessUser только через bot_access)."""
    user = User(
        id=uuid.uuid4(),
        email=f"{role}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=datetime.now(),
    )
    async with session_factory() as session:
        session.add(user)
        await grant_bot_access(session, user.id, bot_id)
        await session.commit()
    app.dependency_overrides[get_current_user] = lambda: user


async def test_new_bot_defaults_to_in_development(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = await client.post("/bots", json={"name": "Новый"})

    assert created.status_code == 201
    assert created.json()["lifecycle_status"] == "in_development"


async def test_admin_can_change_status(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    override_admin_auth()

    response = await client.patch(
        f"/bots/{bot_id}/lifecycle-status", json={"lifecycle_status": "frozen"}
    )

    assert response.status_code == 200
    assert response.json()["lifecycle_status"] == "frozen"
    assert (await client.get(f"/bots/{bot_id}")).json()["lifecycle_status"] == "frozen"


@pytest.mark.parametrize("role", ["prompter", "client"])
async def test_non_platform_roles_cannot_change_status(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    role: str,
) -> None:
    bot_id = await _make_bot(session_factory)
    await _act_as(session_factory, role, bot_id)

    response = await client.patch(
        f"/bots/{bot_id}/lifecycle-status", json={"lifecycle_status": "active"}
    )

    assert response.status_code == 403


async def test_unknown_status_is_rejected(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)

    response = await client.patch(
        f"/bots/{bot_id}/lifecycle-status", json={"lifecycle_status": "dead"}
    )

    assert response.status_code == 422


async def test_unknown_bot_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.patch(
        f"/bots/{uuid.uuid4()}/lifecycle-status", json={"lifecycle_status": "active"}
    )
    assert response.status_code == 404


@pytest.mark.parametrize("role", ["prompter", "client"])
async def test_status_is_hidden_from_non_platform_roles(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    role: str,
) -> None:
    bot_id = await _make_bot(session_factory)
    await _act_as(session_factory, role, bot_id)

    single = await client.get(f"/bots/{bot_id}")
    listing = await client.get("/bots")

    assert single.json()["lifecycle_status"] is None
    assert all(b["lifecycle_status"] is None for b in listing.json())


async def test_status_is_visible_in_list_for_platform_roles(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)

    listing = (await client.get("/bots")).json()

    row = next(b for b in listing if b["id"] == str(bot_id))
    assert row["lifecycle_status"] == "in_development"


async def test_status_change_is_audited() -> None:
    assert ACTION_REGISTRY[("PATCH", "/bots/{bot_id}/lifecycle-status")] == (
        "bots.update_lifecycle_status"
    )


def _alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), *args],
        check=True,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
    )


async def test_migration_marks_linked_bots_active_and_others_in_development(
    database_url: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Backfill реальной миграции: откатываем её, создаём "старых" ботов
    (колонки ещё нет), накатываем снова — бот с привязанным номером active,
    остальные in_development."""
    _alembic(database_url, "downgrade", "202610051001")
    linked_id, unlinked_id = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        await session.execute(
            text("INSERT INTO bots (id, name) VALUES (:a, 'linked'), (:b, 'unlinked')"),
            {"a": linked_id, "b": unlinked_id},
        )
        await session.execute(
            text("INSERT INTO bot_sessions (bot_id, phone) VALUES (:a, '996700000001')"),
            {"a": linked_id},
        )
        await session.commit()

    _alembic(database_url, "upgrade", "head")

    async with session_factory() as session:
        rows = dict(
            (
                await session.execute(
                    text("SELECT id::text, lifecycle_status FROM bots WHERE id IN (:a, :b)"),
                    {"a": linked_id, "b": unlinked_id},
                )
            ).all()
        )
    assert rows[str(linked_id)] == "active"
    assert rows[str(unlinked_id)] == "in_development"
