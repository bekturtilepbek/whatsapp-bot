"""users: create/lookup/activate/password (FEATURES.md 6.18).

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
from db.engine import make_engine, make_session_factory
from db.users import (
    create_user,
    get_user,
    get_user_by_email,
    list_users,
    set_user_active,
    set_user_password,
    set_user_role,
)
from sqlalchemy.exc import IntegrityError
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


async def test_create_then_get_by_email(session: AsyncSession) -> None:
    user = await create_user(session, email="owner@example.com", password_hash="hash")
    fetched = await get_user_by_email(session, "owner@example.com")
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.role == "client"
    assert fetched.is_active is True


async def test_create_platform_owner(session: AsyncSession) -> None:
    user = await create_user(
        session, email="owner2@example.com", password_hash="hash", role="superadmin"
    )
    assert user.role == "superadmin"


async def test_get_by_email_unknown_returns_none(session: AsyncSession) -> None:
    assert await get_user_by_email(session, "nobody@example.com") is None


async def test_get_user_by_id(session: AsyncSession) -> None:
    user = await create_user(session, email="a@example.com", password_hash="hash")
    fetched = await get_user(session, user.id)
    assert fetched is not None
    assert fetched.email == "a@example.com"


async def test_get_user_unknown_id_returns_none(session: AsyncSession) -> None:
    assert await get_user(session, uuid.uuid4()) is None


async def test_duplicate_email_raises(session: AsyncSession) -> None:
    await create_user(session, email="dup@example.com", password_hash="hash")
    with pytest.raises(IntegrityError):
        await create_user(session, email="dup@example.com", password_hash="hash2")


async def test_list_users_returns_all(session: AsyncSession) -> None:
    await create_user(session, email="b1@example.com", password_hash="hash")
    await create_user(session, email="b2@example.com", password_hash="hash")
    emails = {u.email for u in await list_users(session)}
    assert {"b1@example.com", "b2@example.com"} <= emails


async def test_set_user_active_false_then_true(session: AsyncSession) -> None:
    user = await create_user(session, email="c@example.com", password_hash="hash")
    updated = await set_user_active(session, user.id, False)
    assert updated is not None
    assert updated.is_active is False
    updated = await set_user_active(session, user.id, True)
    assert updated is not None
    assert updated.is_active is True


async def test_set_user_active_unknown_returns_none(session: AsyncSession) -> None:
    assert await set_user_active(session, uuid.uuid4(), False) is None


async def test_set_user_password(session: AsyncSession) -> None:
    user = await create_user(session, email="d@example.com", password_hash="old")
    updated = await set_user_password(session, user.id, "new-hash")
    assert updated is not None
    assert updated.password_hash == "new-hash"


async def test_set_user_role(session: AsyncSession) -> None:
    user = await create_user(session, email="e@example.com", password_hash="hash")
    assert user.role == "client"
    updated = await set_user_role(session, user.id, "prompter")
    assert updated is not None
    assert updated.role == "prompter"


async def test_set_user_role_unknown_returns_none(session: AsyncSession) -> None:
    assert await set_user_role(session, uuid.uuid4(), "admin") is None
