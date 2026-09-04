"""tool_bindings: list_enabled/enable/disable (FEATURES.md 4.13,
инфраструктура). Требует Docker (testcontainers). Без него — skip, не fail.
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
from db.models import Bot
from db.tool_bindings import disable, enable, list_enabled
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


async def test_list_enabled_empty_by_default(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await list_enabled(session, bot_id) == []


async def test_enable_then_list_enabled_returns_it(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await enable(session, bot_id, "search", {"limit": 3})
    bindings = await list_enabled(session, bot_id)
    assert len(bindings) == 1
    assert bindings[0].tool_name == "search"
    assert bindings[0].config == {"limit": 3}


async def test_enable_is_upsert_and_updates_config(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await enable(session, bot_id, "search", {"limit": 3})
    await enable(session, bot_id, "search", {"limit": 10})

    bindings = await list_enabled(session, bot_id)
    assert len(bindings) == 1  # не дублируется
    assert bindings[0].config == {"limit": 10}


async def test_disable_removes_binding(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await enable(session, bot_id, "search", {})
    await disable(session, bot_id, "search")
    assert await list_enabled(session, bot_id) == []


async def test_disable_unknown_is_not_an_error(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await disable(session, bot_id, "does_not_exist")  # не должно упасть


async def test_bindings_are_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await enable(session, bot_a, "search", {})
    assert len(await list_enabled(session, bot_a)) == 1
    assert await list_enabled(session, bot_b) == []
