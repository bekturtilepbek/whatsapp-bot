"""Каталог товаров (FEATURES.md 3.4): list_products — ORDER BY name, LIMIT,
скоуп per bot. Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

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
from db.models import Bot, Product
from db.products import find_product_by_exact_name, list_products
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


async def test_list_products_empty_by_default(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await list_products(session, bot_id) == []


async def test_list_products_returns_created_product_with_all_fields(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    session.add(
        Product(
            bot_id=bot_id,
            name="Кроссовки Nike Air",
            price=Decimal("5000.00"),
            sku="NK-001",
            description="Беговые, размеры 38-45",
            display_custom={"show_sku": True},
        )
    )
    await session.flush()

    products = await list_products(session, bot_id)
    assert len(products) == 1
    assert products[0].name == "Кроссовки Nike Air"
    assert products[0].price == Decimal("5000.00")
    assert products[0].sku == "NK-001"
    assert products[0].description == "Беговые, размеры 38-45"
    assert products[0].display_custom == {"show_sku": True}


async def test_list_products_allows_null_price_sku_description(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    session.add(Product(bot_id=bot_id, name="Товар без деталей"))
    await session.flush()

    products = await list_products(session, bot_id)
    assert len(products) == 1
    assert products[0].price is None
    assert products[0].sku is None
    assert products[0].description is None
    assert products[0].display_custom == {}


async def test_list_products_ordered_by_name(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add_all(
        [
            Product(bot_id=bot_id, name="Яблоки"),
            Product(bot_id=bot_id, name="Апельсины"),
            Product(bot_id=bot_id, name="Бананы"),
        ]
    )
    await session.flush()

    products = await list_products(session, bot_id)
    assert [p.name for p in products] == ["Апельсины", "Бананы", "Яблоки"]


async def test_list_products_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    session.add_all(
        [
            Product(bot_id=bot_a, name="Товар A"),
            Product(bot_id=bot_b, name="Товар B"),
        ]
    )
    await session.flush()

    products_a = await list_products(session, bot_a)
    assert [p.name for p in products_a] == ["Товар A"]


async def test_list_products_limit_caps_the_number_of_rows(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add_all([Product(bot_id=bot_id, name=f"Товар {i}") for i in range(5)])
    await session.flush()

    products = await list_products(session, bot_id, limit=2)
    assert len(products) == 2


async def test_find_product_by_exact_name_matches_case_and_whitespace_insensitively(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    session.add(Product(bot_id=bot_id, name="Кроссовки Nike Air"))
    await session.flush()

    found = await find_product_by_exact_name(session, bot_id, "  кроссовки NIKE air  ")
    assert found is not None
    assert found.name == "Кроссовки Nike Air"


async def test_find_product_by_exact_name_returns_none_when_not_found(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    assert await find_product_by_exact_name(session, bot_id, "Нет такого") is None


async def test_find_product_by_exact_name_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    session.add(Product(bot_id=bot_a, name="Только у А"))
    await session.flush()

    assert await find_product_by_exact_name(session, bot_a, "Только у А") is not None
    assert await find_product_by_exact_name(session, bot_b, "Только у А") is None
