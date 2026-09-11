"""usage: record_usage/list_usage_by_bot (FEATURES.md 3.9/6.15).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.bots import create_bot
from db.engine import make_engine, make_session_factory
from db.usage import UsageSummary, list_usage_by_bot, record_usage
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


def _for_bots(summaries: list[UsageSummary], *bot_ids: object) -> list[UsageSummary]:
    """`database_url` — module-scoped (один Postgres-контейнер на весь
    файл) — без фильтрации по своим bot_id каждый тест видел бы боты,
    созданные ДРУГИМИ тестами этого же файла."""
    return [s for s in summaries if s.bot_id in bot_ids]


async def test_list_usage_by_bot_sums_across_multiple_events(session: AsyncSession) -> None:
    bot = await create_bot(session, name="bot-a")
    await session.commit()

    await record_usage(session, bot.id, "gpt-4o-mini", 100, 20, Decimal("0.01"))
    await record_usage(session, bot.id, "gpt-4o-mini", 200, 30, Decimal("0.02"))
    await session.commit()

    summaries = _for_bots(await list_usage_by_bot(session), bot.id)
    assert len(summaries) == 1
    assert summaries[0].bot_id == bot.id
    assert summaries[0].bot_name == "bot-a"
    assert summaries[0].tokens_in == 300
    assert summaries[0].tokens_out == 50
    assert summaries[0].cost == Decimal("0.03")


async def test_list_usage_by_bot_excludes_bots_with_no_usage(session: AsyncSession) -> None:
    bot_with_usage = await create_bot(session, name="bot-with-usage")
    bot_without_usage = await create_bot(session, name="bot-without-usage")
    await session.commit()

    await record_usage(session, bot_with_usage.id, "gpt-4o-mini", 100, 20, Decimal("0.01"))
    await session.commit()

    summaries = _for_bots(
        await list_usage_by_bot(session), bot_with_usage.id, bot_without_usage.id
    )
    assert [s.bot_name for s in summaries] == ["bot-with-usage"]


async def test_list_usage_by_bot_orders_by_cost_descending(session: AsyncSession) -> None:
    cheap_bot = await create_bot(session, name="cheap-bot")
    expensive_bot = await create_bot(session, name="expensive-bot")
    await session.commit()

    await record_usage(session, cheap_bot.id, "gpt-4o-mini", 100, 20, Decimal("0.01"))
    await record_usage(session, expensive_bot.id, "gpt-4o", 100, 20, Decimal("1.00"))
    await session.commit()

    summaries = _for_bots(await list_usage_by_bot(session), cheap_bot.id, expensive_bot.id)
    assert [s.bot_name for s in summaries] == ["expensive-bot", "cheap-bot"]


async def test_list_usage_by_bot_filters_by_since(session: AsyncSession) -> None:
    bot = await create_bot(session, name="since-filter-bot")
    await session.commit()

    await record_usage(session, bot.id, "gpt-4o-mini", 100, 20, Decimal("0.01"))
    await session.commit()

    future_cutoff = datetime.now(UTC) + timedelta(days=1)
    summaries = _for_bots(await list_usage_by_bot(session, since=future_cutoff), bot.id)
    assert summaries == []

    past_cutoff = datetime.now(UTC) - timedelta(days=1)
    summaries = _for_bots(await list_usage_by_bot(session, since=past_cutoff), bot.id)
    assert len(summaries) == 1


async def test_list_usage_by_bot_returns_empty_list_when_no_usage_at_all(
    session: AsyncSession,
) -> None:
    bot = await create_bot(session, name="idle-bot")
    await session.commit()

    summaries = _for_bots(await list_usage_by_bot(session), bot.id)
    assert summaries == []
