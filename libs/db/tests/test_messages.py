"""История: окно/лимит/порядок, идемпотентная запись входящего.

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
from db.contacts import match_or_create_contact
from db.engine import make_engine, make_session_factory
from db.messages import fetch_recent_history, insert_incoming, insert_outgoing
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


async def _make_contact(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    bot = Bot(name="test-bot")
    session.add(bot)
    await session.flush()
    contact = await match_or_create_contact(session, bot.id, wa_id=str(uuid.uuid4()), lid=None)
    return bot.id, contact.id


async def test_insert_incoming_is_idempotent_on_duplicate_wa_msg_id(
    session: AsyncSession,
) -> None:
    bot_id, contact_id = await _make_contact(session)
    now = datetime.now(UTC)
    await insert_incoming(session, bot_id, contact_id, "привет", "wamsg-dup", now)
    await insert_incoming(session, bot_id, contact_id, "привет ещё раз", "wamsg-dup", now)

    history = await fetch_recent_history(session, contact_id)
    assert len(history) == 1
    assert history[0].content == "привет"  # второй insert проигнорирован


async def test_fetch_recent_history_respects_limit_and_order(session: AsyncSession) -> None:
    bot_id, contact_id = await _make_contact(session)
    base = datetime.now(UTC) - timedelta(minutes=10)
    for i in range(5):
        await insert_incoming(
            session, bot_id, contact_id, f"msg-{i}", f"wamsg-{i}", base + timedelta(seconds=i)
        )

    history = await fetch_recent_history(session, contact_id, limit=3)
    assert [m.content for m in history] == ["msg-2", "msg-3", "msg-4"]  # последние 3, по порядку


async def test_fetch_recent_history_excludes_messages_outside_window(
    session: AsyncSession,
) -> None:
    bot_id, contact_id = await _make_contact(session)
    old_ts = datetime.now(UTC) - timedelta(hours=48)
    await insert_incoming(session, bot_id, contact_id, "старое", "wamsg-old", old_ts)
    await insert_incoming(session, bot_id, contact_id, "свежее", "wamsg-new", datetime.now(UTC))

    history = await fetch_recent_history(session, contact_id, window_hours=24)
    assert [m.content for m in history] == ["свежее"]


async def test_history_includes_both_user_and_assistant_messages_in_order(
    session: AsyncSession,
) -> None:
    bot_id, contact_id = await _make_contact(session)
    await insert_incoming(session, bot_id, contact_id, "вопрос", "wamsg-q", datetime.now(UTC))
    await insert_outgoing(session, bot_id, contact_id, "ответ")

    history = await fetch_recent_history(session, contact_id)
    assert [(m.role, m.content) for m in history] == [("user", "вопрос"), ("assistant", "ответ")]
