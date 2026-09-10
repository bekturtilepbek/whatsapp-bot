"""bot_access: grant/revoke/check (FEATURES.md 6.18).

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
from db.bot_access import grant_bot_access, has_bot_access, list_bot_ids_for_user, revoke_bot_access
from db.engine import make_engine, make_session_factory
from db.models import Bot, User
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


async def _make_user(session: AsyncSession) -> User:
    user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash="hash")
    session.add(user)
    await session.flush()
    return user


async def _make_bot(session: AsyncSession) -> Bot:
    bot = Bot(name="test-bot")
    session.add(bot)
    await session.flush()
    return bot


async def test_has_access_false_by_default(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    assert await has_bot_access(session, user.id, bot.id) is False


async def test_grant_then_has_access_true(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await grant_bot_access(session, user.id, bot.id)
    assert await has_bot_access(session, user.id, bot.id) is True


async def test_grant_is_idempotent_on_conflict(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await grant_bot_access(session, user.id, bot.id)
    await grant_bot_access(session, user.id, bot.id)  # не должно упасть
    assert await list_bot_ids_for_user(session, user.id) == [bot.id]


async def test_revoke_then_has_access_false(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await grant_bot_access(session, user.id, bot.id)
    await revoke_bot_access(session, user.id, bot.id)
    assert await has_bot_access(session, user.id, bot.id) is False


async def test_revoke_unknown_grant_is_a_noop(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await revoke_bot_access(session, user.id, bot.id)  # не должно упасть


async def test_list_bot_ids_for_user_scoped_per_user(session: AsyncSession) -> None:
    user_a, user_b = await _make_user(session), await _make_user(session)
    bot = await _make_bot(session)
    await grant_bot_access(session, user_a.id, bot.id)
    assert await list_bot_ids_for_user(session, user_a.id) == [bot.id]
    assert await list_bot_ids_for_user(session, user_b.id) == []
