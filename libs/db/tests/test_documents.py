"""Файлы бота (FEATURES.md 4.8/4.9): list_documents — сортировка по
filename, скоуп per bot; find_document_by_filename — точное совпадение
с учётом регистра (имена файлов, не разговорные названия). Требует
Docker (testcontainers). Без него — skip, не fail.
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
from db.documents import find_document_by_filename, list_documents
from db.engine import make_engine, make_session_factory
from db.models import Bot, Document
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


async def test_list_documents_empty_by_default(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await list_documents(session, bot_id) == []


async def test_list_documents_ordered_by_filename(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add_all(
        [
            Document(
                bot_id=bot_id, filename="c-price.pdf", storage_key="k1", mime_type="application/pdf"
            ),
            Document(
                bot_id=bot_id, filename="a-contract.docx", storage_key="k2",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            Document(
                bot_id=bot_id, filename="b-catalog.pdf", storage_key="k3",
                mime_type="application/pdf",
            ),
        ]
    )
    await session.flush()

    documents = await list_documents(session, bot_id)
    assert [d.filename for d in documents] == ["a-contract.docx", "b-catalog.pdf", "c-price.pdf"]


async def test_list_documents_limit_caps_the_number_of_rows(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add_all(
        [
            Document(
                bot_id=bot_id, filename=f"file-{i}.pdf", storage_key=f"k{i}",
                mime_type="application/pdf",
            )
            for i in range(3)
        ]
    )
    await session.flush()

    documents = await list_documents(session, bot_id, limit=2)
    assert len(documents) == 2


async def test_list_documents_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    session.add_all(
        [
            Document(bot_id=bot_a, filename="a.pdf", storage_key="ka", mime_type="application/pdf"),
            Document(bot_id=bot_b, filename="b.pdf", storage_key="kb", mime_type="application/pdf"),
        ]
    )
    await session.flush()

    documents_a = await list_documents(session, bot_a)
    assert [d.filename for d in documents_a] == ["a.pdf"]


async def test_find_document_by_filename_exact_match(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add(
        Document(
            bot_id=bot_id, filename="price-list.pdf", storage_key="k1", mime_type="application/pdf"
        )
    )
    await session.flush()

    found = await find_document_by_filename(session, bot_id, "price-list.pdf")
    assert found is not None
    assert found.storage_key == "k1"


async def test_find_document_by_filename_is_case_sensitive(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add(
        Document(
            bot_id=bot_id, filename="Price-List.pdf", storage_key="k1", mime_type="application/pdf"
        )
    )
    await session.flush()

    assert await find_document_by_filename(session, bot_id, "price-list.pdf") is None
    assert await find_document_by_filename(session, bot_id, "Price-List.pdf") is not None


async def test_find_document_by_filename_returns_none_when_not_found(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    assert await find_document_by_filename(session, bot_id, "нет-такого.pdf") is None


async def test_find_document_by_filename_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    session.add(
        Document(bot_id=bot_a, filename="only-a.pdf", storage_key="ka", mime_type="application/pdf")
    )
    await session.flush()

    assert await find_document_by_filename(session, bot_a, "only-a.pdf") is not None
    assert await find_document_by_filename(session, bot_b, "only-a.pdf") is None
