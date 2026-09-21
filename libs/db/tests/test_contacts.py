"""Матчинг контакта wa_id<->lid: не создаёт дубль, дозаполняет второй идентификатор.

Требует Docker (testcontainers). Без него — skip, не fail (см. test_migration.py).
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
from db.contacts import count_contacts, find_by_identifier, get_contact, match_or_create_contact
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


async def test_creates_new_contact_by_wa_id(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    contact = await match_or_create_contact(session, bot_id, wa_id="996700000001", lid=None)
    assert contact.wa_id == "996700000001"
    assert contact.lid is None


async def test_second_message_same_wa_id_reuses_contact(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    first = await match_or_create_contact(session, bot_id, wa_id="996700000002", lid=None)
    second = await match_or_create_contact(session, bot_id, wa_id="996700000002", lid=None)
    assert first.id == second.id


async def test_lid_appearing_later_backfills_same_row_not_a_duplicate(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    first = await match_or_create_contact(session, bot_id, wa_id="996700000003", lid=None)
    # тот же человек, теперь событие пришло с lid впервые
    second = await match_or_create_contact(session, bot_id, wa_id="996700000003", lid="111222333")
    assert first.id == second.id
    assert second.lid == "111222333"


async def test_matching_by_lid_alone_finds_existing_contact(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    created = await match_or_create_contact(
        session, bot_id, wa_id="996700000004", lid="444555666"
    )
    found = await match_or_create_contact(session, bot_id, wa_id=None, lid="444555666")
    assert found.id == created.id


async def test_different_bots_do_not_share_contacts(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    a = await match_or_create_contact(session, bot_a, wa_id="996700000005", lid=None)
    b = await match_or_create_contact(session, bot_b, wa_id="996700000005", lid=None)
    assert a.id != b.id


async def test_get_contact_returns_contact_by_id(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    created = await match_or_create_contact(session, bot_id, wa_id="996700000099", lid=None)

    found = await get_contact(session, created.id)

    assert found is not None
    assert found.id == created.id
    assert found.wa_id == "996700000099"


async def test_get_contact_returns_none_for_unknown_id(session: AsyncSession) -> None:
    assert await get_contact(session, uuid.uuid4()) is None


async def test_count_contacts_scoped_to_one_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await match_or_create_contact(session, bot_a, wa_id="996700000010", lid=None)
    await match_or_create_contact(session, bot_a, wa_id="996700000011", lid=None)
    await match_or_create_contact(session, bot_b, wa_id="996700000010", lid=None)

    assert await count_contacts(session, bot_a) == 2
    assert await count_contacts(session, bot_b) == 1


async def test_count_contacts_is_zero_for_bot_with_none(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await count_contacts(session, bot_id) == 0


async def test_find_by_identifier_matches_by_wa_id(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    created = await match_or_create_contact(
        session, bot_id, wa_id="996700000020", lid=None, name="Клиент"
    )

    found = await find_by_identifier(session, bot_id, "996700000020")

    assert found is not None
    assert found.id == created.id
    assert found.name == "Клиент"


async def test_find_by_identifier_matches_by_lid(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    created = await match_or_create_contact(
        session, bot_id, wa_id="996700000021", lid="777888999"
    )

    found = await find_by_identifier(session, bot_id, "777888999")

    assert found is not None
    assert found.id == created.id


async def test_find_by_identifier_returns_none_when_unmatched(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await find_by_identifier(session, bot_id, "no-such-identifier") is None
