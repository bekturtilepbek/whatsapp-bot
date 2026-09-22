"""list_bots: unfiltered vs filtered by user access (FEATURES.md 6.18).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.bot_access import grant_bot_access
from db.bots import create_bot, list_bots, update_bot
from db.engine import make_engine, make_session_factory
from db.models import Bot, User
from sqlalchemy import delete
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


async def test_list_bots_without_user_id_returns_all(session: AsyncSession) -> None:
    bot_a = Bot(name="a")
    bot_b = Bot(name="b")
    session.add_all([bot_a, bot_b])
    await session.flush()
    names = {b.name for b in await list_bots(session)}
    assert {"a", "b"} <= names


async def test_list_bots_with_user_id_filters_to_granted(session: AsyncSession) -> None:
    bot_a = Bot(name="granted")
    bot_b = Bot(name="not-granted")
    user = User(email="client@example.com", password_hash="hash")
    session.add_all([bot_a, bot_b, user])
    await session.flush()
    await grant_bot_access(session, user.id, bot_a.id)

    result = await list_bots(session, user_id=user.id)
    assert [b.name for b in result] == ["granted"]


async def test_create_bot_sets_name_and_defaults(session: AsyncSession) -> None:
    bot = await create_bot(session, name="Новый бот")
    assert bot.name == "Новый бот"
    assert bot.enabled is True
    assert bot.system_prompt == ""
    assert bot.timezone == "Asia/Bishkek"
    assert bot.settings == {}


async def test_create_bot_duplicate_name_is_allowed(session: AsyncSession) -> None:
    await create_bot(session, name="dup")
    second = await create_bot(session, name="dup")
    assert second.name == "dup"


async def test_create_bot_with_responsible_user(session: AsyncSession) -> None:
    prompter = User(email="prompter1@example.com", password_hash="hash", role="prompter")
    session.add(prompter)
    await session.flush()

    bot = await create_bot(session, name="with responsible", responsible_user_id=prompter.id)
    assert bot.responsible_user_id == prompter.id


async def test_deleting_responsible_user_sets_null_on_bot(session: AsyncSession) -> None:
    """FK ondelete=SET NULL — увольнение/удаление сотрудника не должно
    сносить бота, только обнулять ссылку (FEATURES.md 6.18)."""
    prompter = User(email="prompter2@example.com", password_hash="hash", role="prompter")
    session.add(prompter)
    await session.flush()
    bot = await create_bot(session, name="orphaned", responsible_user_id=prompter.id)
    await session.commit()

    await session.execute(delete(User).where(User.id == prompter.id))
    await session.commit()

    await session.refresh(bot)
    assert bot.responsible_user_id is None


async def test_update_bot_responsible_user_id_unset_does_not_touch(session: AsyncSession) -> None:
    prompter = User(email="prompter3@example.com", password_hash="hash", role="prompter")
    session.add(prompter)
    await session.flush()
    bot = await create_bot(session, name="stable", responsible_user_id=prompter.id)
    await session.commit()

    updated = await update_bot(session, bot.id, name="renamed")
    assert updated is not None
    assert updated.responsible_user_id == prompter.id


async def test_update_bot_responsible_user_id_explicit_none_clears_it(
    session: AsyncSession,
) -> None:
    prompter = User(email="prompter4@example.com", password_hash="hash", role="prompter")
    session.add(prompter)
    await session.flush()
    bot = await create_bot(session, name="to be cleared", responsible_user_id=prompter.id)
    await session.commit()

    updated = await update_bot(session, bot.id, responsible_user_id=None)
    assert updated is not None
    assert updated.responsible_user_id is None


async def test_update_bot_responsible_user_id_reassigns(session: AsyncSession) -> None:
    old_prompter = User(email="prompter5@example.com", password_hash="hash", role="prompter")
    new_prompter = User(email="prompter6@example.com", password_hash="hash", role="prompter")
    session.add_all([old_prompter, new_prompter])
    await session.flush()
    bot = await create_bot(session, name="reassign", responsible_user_id=old_prompter.id)
    await session.commit()

    updated = await update_bot(session, bot.id, responsible_user_id=new_prompter.id)
    assert updated is not None
    assert updated.responsible_user_id == new_prompter.id
