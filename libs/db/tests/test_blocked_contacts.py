"""Чёрный список: is_blocked/add/remove/list (FEATURES.md 1.5).

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
from db.blocked_contacts import (
    add_blocked_number,
    is_blocked,
    list_blocked_numbers,
    remove_blocked_number,
)
from db.engine import make_engine, make_session_factory
from db.models import Bot
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


async def _make_bot(session: AsyncSession) -> uuid.UUID:
    bot = Bot(name="test-bot")
    session.add(bot)
    await session.flush()
    return bot.id


async def test_is_blocked_false_when_no_row(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await is_blocked(session, bot_id, "996700000000") is False


async def test_add_then_is_blocked_true(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await add_blocked_number(session, bot_id, "996700000000")
    assert await is_blocked(session, bot_id, "996700000000") is True


async def test_add_is_idempotent_on_conflict(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await add_blocked_number(session, bot_id, "996700000000")
    await add_blocked_number(session, bot_id, "996700000000")  # не должно упасть
    assert await list_blocked_numbers(session, bot_id) == ["996700000000"]


async def test_remove_then_is_blocked_false(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await add_blocked_number(session, bot_id, "996700000000")
    await remove_blocked_number(session, bot_id, "996700000000")
    assert await is_blocked(session, bot_id, "996700000000") is False


async def test_block_is_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await add_blocked_number(session, bot_a, "996700000000")
    assert await is_blocked(session, bot_a, "996700000000") is True
    assert await is_blocked(session, bot_b, "996700000000") is False


async def test_list_blocked_numbers_returns_only_this_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await add_blocked_number(session, bot_a, "996700000001")
    await add_blocked_number(session, bot_b, "996700000002")
    assert await list_blocked_numbers(session, bot_a) == ["996700000001"]
