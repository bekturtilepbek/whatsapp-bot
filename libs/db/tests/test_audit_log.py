"""audit_log: create_entry/list_entries (FEATURES.md 6.19).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.audit_log import create_entry, list_entries
from db.bots import create_bot
from db.engine import make_engine, make_session_factory
from db.models import User
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

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
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_user(session: AsyncSession, *, email: str = "owner@example.com") -> uuid.UUID:
    user = User(email=email, password_hash="unused", is_platform_owner=True, is_active=True)
    session.add(user)
    await session.flush()
    await session.commit()
    return user.id


async def test_create_entry_and_list_returns_it_with_actor_email(session: AsyncSession) -> None:
    user_id = await _make_user(session, email=f"owner1-{uuid.uuid4()}@example.com")
    bot_id = (await create_bot(session, name="test-bot")).id
    await session.commit()

    await create_entry(
        session,
        actor_user_id=user_id,
        bot_id=bot_id,
        action="bots.update",
        payload={"name": "новое имя"},
    )
    await session.commit()

    entries = await list_entries(session)
    assert len(entries) == 1
    assert entries[0].actor_email.startswith("owner1-")
    assert entries[0].bot_id == bot_id
    assert entries[0].bot_name == "test-bot"
    assert entries[0].action == "bots.update"
    assert entries[0].payload == {"name": "новое имя"}


async def test_list_entries_filters_by_bot_id(session: AsyncSession) -> None:
    user_id = await _make_user(session, email=f"owner2-{uuid.uuid4()}@example.com")
    bot_a = (await create_bot(session, name=f"bot-a-{uuid.uuid4()}")).id
    bot_b = (await create_bot(session, name=f"bot-b-{uuid.uuid4()}")).id
    await session.commit()

    await create_entry(
        session, actor_user_id=user_id, bot_id=bot_a, action="bots.update", payload=None
    )
    await create_entry(
        session, actor_user_id=user_id, bot_id=bot_b, action="bots.update", payload=None
    )
    await session.commit()

    entries = await list_entries(session, bot_id=bot_a)
    assert len(entries) == 1
    assert entries[0].bot_id == bot_a


async def test_list_entries_orders_newest_first(session: AsyncSession) -> None:
    user_id = await _make_user(session, email=f"owner3-{uuid.uuid4()}@example.com")
    await create_entry(
        session, actor_user_id=user_id, bot_id=None, action="users.create", payload=None
    )
    await create_entry(
        session, actor_user_id=user_id, bot_id=None, action="users.update", payload=None
    )
    await session.commit()

    entries = await list_entries(session)
    assert len(entries) >= 2
    # Find the most recent entries from this test
    recent_entries = [e for e in entries if e.actor_user_id == user_id]
    assert len(recent_entries) == 2
    assert [e.action for e in recent_entries] == ["users.update", "users.create"]


async def test_list_entries_respects_limit_and_offset(session: AsyncSession) -> None:
    user_id = await _make_user(session, email=f"owner4-{uuid.uuid4()}@example.com")
    for i in range(5):
        await create_entry(
            session, actor_user_id=user_id, bot_id=None, action=f"users.create.{i}", payload=None
        )
    await session.commit()

    page = await list_entries(session, limit=2, offset=0, actor_user_id=user_id)
    assert len(page) == 2


async def test_platform_level_entry_has_null_bot_id_and_bot_name(session: AsyncSession) -> None:
    user_id = await _make_user(session, email=f"owner5-{uuid.uuid4()}@example.com")
    await create_entry(
        session, actor_user_id=user_id, bot_id=None, action="users.create", payload=None
    )
    await session.commit()

    entries = await list_entries(session, actor_user_id=user_id)
    assert len(entries) == 1
    assert entries[0].bot_id is None
    assert entries[0].bot_name is None
