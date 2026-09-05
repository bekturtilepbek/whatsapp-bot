"""ProductSearchTool (FEATURES.md 4.1/4.2/4.3/4.4): точное совпадение
сначала, векторный поиск — только если точного нет; при находке —
также override_reply_text+media (карточка товара). Требует Docker
(testcontainers) — реальный Postgres, генерация эмбеддинга подменена
фейком (не настоящий OpenAI).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.models import Bot, Product, ProductEmbedding, ProductImage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import product_search as product_search_module
from tools.base import ToolContext
from tools.product_search import ProductSearchTool

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"

DIMENSION = 1536


def _unit_vector(index: int) -> list[float]:
    vec = [0.0] * DIMENSION
    vec[index] = 1.0
    return vec


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


async def test_exact_name_match_is_returned_without_calling_embeddings(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Product(
                bot_id=bot.id, name="Кроссовки Nike Air",
                price=Decimal("5000.00"), description="Беговые",
            )
        )
        await session.commit()

    async def fail_generate_embedding(*args: object, **kwargs: object) -> list[float]:
        raise AssertionError("эмбеддинг не должен вызываться при точном совпадении")

    monkeypatch.setattr(product_search_module, "generate_embedding", fail_generate_embedding)

    result = await ProductSearchTool().execute(
        {"query": "Кроссовки Nike Air"}, _make_ctx(bot, session_factory)
    )
    assert json.loads(result.content) == [
        {"name": "Кроссовки Nike Air", "description": "Беговые", "price": "5000.00"}
    ]


async def test_exact_match_is_case_and_whitespace_insensitive(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(Product(bot_id=bot.id, name="Кроссовки Nike Air"))
        await session.commit()

    async def fail_generate_embedding(*args: object, **kwargs: object) -> list[float]:
        raise AssertionError("не должен вызываться")

    monkeypatch.setattr(product_search_module, "generate_embedding", fail_generate_embedding)

    result = await ProductSearchTool().execute(
        {"query": "  кроссовки nike air  "}, _make_ctx(bot, session_factory)
    )
    assert json.loads(result.content)[0]["name"] == "Кроссовки Nike Air"


async def test_falls_back_to_vector_search_when_no_exact_match(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        product = Product(bot_id=bot.id, name="Кеды Adidas", description="Городские")
        session.add(product)
        await session.flush()
        session.add(ProductEmbedding(product_id=product.id, embedding=_unit_vector(0)))
        await session.commit()

    async def fake_generate_embedding(text: str, **kwargs: object) -> list[float]:
        assert text == "обувь для города"
        return _unit_vector(0)

    monkeypatch.setattr(product_search_module, "generate_embedding", fake_generate_embedding)

    result = await ProductSearchTool().execute(
        {"query": "обувь для города"}, _make_ctx(bot, session_factory)
    )
    assert json.loads(result.content)[0]["name"] == "Кеды Adidas"


async def test_returns_empty_list_when_nothing_found(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)

    async def fake_generate_embedding(text: str, **kwargs: object) -> list[float]:
        return _unit_vector(5)

    monkeypatch.setattr(product_search_module, "generate_embedding", fake_generate_embedding)

    result = await ProductSearchTool().execute(
        {"query": "нет такого"}, _make_ctx(bot, session_factory)
    )
    assert result.content == "[]"
    assert result.override_reply_text is None
    assert result.media == ()


async def test_missing_price_defaults_to_not_specified_text(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(Product(bot_id=bot.id, name="Товар без цены"))
        await session.commit()

    async def fail_generate_embedding(*args: object, **kwargs: object) -> list[float]:
        raise AssertionError("не должен вызываться")

    monkeypatch.setattr(product_search_module, "generate_embedding", fail_generate_embedding)

    result = await ProductSearchTool().execute(
        {"query": "Товар без цены"}, _make_ctx(bot, session_factory)
    )
    assert json.loads(result.content)[0]["price"] == "Не указана"


async def test_found_product_with_images_returns_override_reply_text_and_media(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        product = Product(
            bot_id=bot.id, name="Кроссовки Nike Air",
            price=Decimal("5000.00"), description="Беговые",
        )
        session.add(product)
        await session.flush()
        session.add_all(
            [
                ProductImage(
                    product_id=product.id, storage_key="img-0", mime_type="image/jpeg", position=0
                ),
                ProductImage(
                    product_id=product.id, storage_key="img-1", mime_type="image/png", position=1
                ),
            ]
        )
        await session.commit()

    result = await ProductSearchTool().execute(
        {"query": "Кроссовки Nike Air"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "*Кроссовки Nike Air*\nБеговые\nЦена: 5000.00"
    assert [(m.storage_key, m.mime_type) for m in result.media] == [
        ("img-0", "image/jpeg"),
        ("img-1", "image/png"),
    ]


async def test_found_product_without_images_returns_override_reply_text_without_media(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(Product(bot_id=bot.id, name="Товар без фото"))
        await session.commit()

    result = await ProductSearchTool().execute(
        {"query": "Товар без фото"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "*Товар без фото*\nЦена: Не указана"
    assert result.media == ()
