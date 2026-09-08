"""SendDocumentTool (FEATURES.md 4.8/4.9): точное совпадение имени файла,
override-паттерн (эталон V1 — isFileSent подавляет ответ LLM целиком, как
у карточки товара), video/* -> media без явной обработки (диспетчеризация
по mime_type — забота consumer.py::_send_cards, не тулзы). Требует Docker
(testcontainers) — реальный Postgres.
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
from db.models import Bot, Document
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools.base import ToolContext
from tools.send_document import SendDocumentTool

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
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> Bot:
    async with session_factory() as session:
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot


def _make_ctx(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> ToolContext:
    return ToolContext(
        bot=bot,
        contact_id=uuid.uuid4(),
        session_factory=session_factory,
        redis=None,  # type: ignore[arg-type]  # эта тулза не использует redis
        storage=None,  # type: ignore[arg-type]  # эта тулза не использует storage
        config={},
    )


async def test_found_document_returns_override_and_media_with_filename(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot.id, filename="price-list.pdf",
                storage_key="bots/x/documents/price-list.pdf", mime_type="application/pdf",
            )
        )
        await session.commit()

    result = await SendDocumentTool().execute(
        {"file_name": "price-list.pdf"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "Отправляю файл price-list.pdf."
    assert len(result.media) == 1
    assert result.media[0].storage_key == "bots/x/documents/price-list.pdf"
    assert result.media[0].mime_type == "application/pdf"
    assert result.media[0].filename == "price-list.pdf"
    assert result.content == "Файл price-list.pdf поставлен в очередь на отправку."


async def test_found_video_returns_override_and_media(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot.id, filename="tour.mp4",
                storage_key="bots/x/documents/tour.mp4", mime_type="video/mp4",
            )
        )
        await session.commit()

    result = await SendDocumentTool().execute(
        {"file_name": "tour.mp4"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "Отправляю файл tour.mp4."
    assert result.media[0].mime_type == "video/mp4"
    assert result.media[0].filename == "tour.mp4"


async def test_document_not_found_returns_error_without_override(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)

    result = await SendDocumentTool().execute(
        {"file_name": "нет-такого.pdf"}, _make_ctx(bot, session_factory)
    )

    assert result.content == 'Файл "нет-такого.pdf" не найден.'
    assert result.override_reply_text is None
    assert result.media == ()


async def test_empty_file_name_returns_error_without_querying_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)

    result = await SendDocumentTool().execute(
        {"file_name": "  "}, _make_ctx(bot, session_factory)
    )

    assert result.content == "Не указано имя файла."
    assert result.override_reply_text is None
    assert result.media == ()


async def test_document_lookup_is_scoped_per_bot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_a = await _make_bot(session_factory)
    bot_b = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot_a.id, filename="only-a.pdf",
                storage_key="k", mime_type="application/pdf",
            )
        )
        await session.commit()

    result = await SendDocumentTool().execute(
        {"file_name": "only-a.pdf"}, _make_ctx(bot_b, session_factory)
    )

    assert result.override_reply_text is None
