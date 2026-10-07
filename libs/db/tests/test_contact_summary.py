"""Хранение саммари и температуры контакта (FEATURES.md 6.13).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.contacts import get_contact, match_or_create_contact, set_contact_analysis
from db.engine import make_engine, make_session_factory
from db.messages import fetch_last_messages, insert_incoming, insert_outgoing, latest_message_seq
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


async def _bot_and_contact(session: AsyncSession, n: int) -> tuple[uuid.UUID, uuid.UUID]:
    bot = Bot(name="summary-bot")
    session.add(bot)
    await session.flush()
    contact = await match_or_create_contact(session, bot.id, wa_id=f"99670011{n:04d}", lid=None)
    await session.commit()
    return bot.id, contact.id


async def test_new_contact_has_no_analysis_yet(session: AsyncSession) -> None:
    _bot_id, contact_id = await _bot_and_contact(session, 1)

    contact = await get_contact(session, contact_id)

    assert contact is not None
    assert contact.temperature is None
    assert contact.summary is None
    assert contact.summary_updated_at is None


async def test_set_contact_analysis_stores_values_and_timestamp(session: AsyncSession) -> None:
    _bot_id, contact_id = await _bot_and_contact(session, 2)

    await set_contact_analysis(session, contact_id, "Клиент выбирает шкаф.", "warm")
    await session.commit()

    contact = await get_contact(session, contact_id)
    assert contact is not None
    assert contact.summary == "Клиент выбирает шкаф."
    assert contact.temperature == "warm"
    assert contact.summary_updated_at is not None
    assert datetime.now(UTC) - contact.summary_updated_at < timedelta(minutes=1)


async def test_latest_message_seq_is_none_without_messages_and_max_otherwise(
    session: AsyncSession,
) -> None:
    bot_id, contact_id = await _bot_and_contact(session, 3)
    assert await latest_message_seq(session, contact_id) is None

    await insert_incoming(session, bot_id, contact_id, "привет", "ls-1", datetime.now(UTC))
    last = await insert_outgoing(session, bot_id, contact_id, "здравствуйте")
    await session.commit()

    assert await latest_message_seq(session, contact_id) == last


async def test_fetch_last_messages_returns_last_n_in_chronological_order_without_time_window(
    session: AsyncSession,
) -> None:
    bot_id, contact_id = await _bot_and_contact(session, 4)
    old = datetime.now(UTC) - timedelta(days=30)  # вне 24ч-окна истории бота — здесь не важно
    for i in range(5):
        await insert_incoming(session, bot_id, contact_id, f"m{i}", f"lm-{i}", old)
    await session.commit()

    messages = await fetch_last_messages(session, contact_id, limit=3)

    assert [m.content for m in messages] == ["m2", "m3", "m4"]
