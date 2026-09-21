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
from db.product_media import create_product_media_item
from db.products import (
    create_product,
    delete_product,
    find_product_by_exact_name,
    get_product,
    list_products,
    update_product,
)
from sqlalchemy.exc import InvalidRequestError
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


async def test_list_products_offset_skips_leading_rows(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    # Имена по алфавиту: Апельсины, Бананы, Вишня — сортировка list_products
    # по name (см. ORDER BY name), offset считается по этому же порядку.
    session.add_all(
        [
            Product(bot_id=bot_id, name="Апельсины"),
            Product(bot_id=bot_id, name="Бананы"),
            Product(bot_id=bot_id, name="Вишня"),
        ]
    )
    await session.flush()

    products = await list_products(session, bot_id, limit=2, offset=1)
    assert [p.name for p in products] == ["Бананы", "Вишня"]


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


async def test_get_product_returns_none_when_missing(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await get_product(session, bot_id, uuid.uuid4()) is None


async def test_get_product_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    product = await create_product(session, bot_a, name="Только у А")

    assert await get_product(session, bot_a, product.id) is not None
    assert await get_product(session, bot_b, product.id) is None


async def test_create_product_requires_only_name(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Новый товар")

    assert product.name == "Новый товар"
    assert product.price is None
    assert product.sku is None
    assert product.description is None
    assert product.display_custom == {}


async def test_create_product_with_all_fields(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(
        session,
        bot_id,
        name="Кроссовки",
        price=Decimal("5000.00"),
        sku="NK-001",
        description="Беговые",
        display_custom={"show_price": False},
    )

    assert product.price == Decimal("5000.00")
    assert product.sku == "NK-001"
    assert product.description == "Беговые"
    assert product.display_custom == {"show_price": False}


async def test_update_product_changes_only_passed_fields(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(
        session, bot_id, name="Исходное имя", price=Decimal("100.00"), sku="SKU-1"
    )

    updated = await update_product(session, bot_id, product.id, price=Decimal("200.00"))

    assert updated is not None
    assert updated.name == "Исходное имя"  # не тронуто
    assert updated.price == Decimal("200.00")
    assert updated.sku == "SKU-1"  # не тронуто


async def test_update_product_returns_none_when_missing(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    result = await update_product(session, bot_id, uuid.uuid4(), name="x")
    assert result is None


async def test_update_product_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    product = await create_product(session, bot_a, name="Товар А")

    result = await update_product(session, bot_b, product.id, name="Чужое имя")
    assert result is None

    unchanged = await get_product(session, bot_a, product.id)
    assert unchanged is not None
    assert unchanged.name == "Товар А"


async def test_delete_product_removes_row(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="На удаление")

    deleted = await delete_product(session, bot_id, product.id)
    assert deleted is True
    assert await get_product(session, bot_id, product.id) is None


async def test_delete_product_returns_false_when_missing(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await delete_product(session, bot_id, uuid.uuid4()) is False


async def test_delete_product_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    product = await create_product(session, bot_a, name="Товар А")

    deleted = await delete_product(session, bot_b, product.id)
    assert deleted is False
    assert await get_product(session, bot_a, product.id) is not None


async def test_delete_product_with_media_does_not_raise(session: AsyncSession) -> None:
    # Регрессия финального ревью Волны 3 (2026-09-10): без passive_deletes=True
    # на Product.media SQLAlchemy перед DELETE родителя сам грузит коллекцию
    # и шлёт UPDATE product_media SET product_id=NULL — падает на NOT NULL
    # constraint, а ON DELETE CASCADE в БД до этого не доходит.
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар с фото")
    await create_product_media_item(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    deleted = await delete_product(session, bot_id, product.id)
    assert deleted is True
    assert await get_product(session, bot_id, product.id) is None


async def test_get_product_without_with_media_does_not_load_media(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар")
    await create_product_media_item(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    fetched = await get_product(session, bot_id, product.id)
    assert fetched is not None
    with pytest.raises(InvalidRequestError):  # lazy="raise" — доступ без with_media кидает это
        _ = fetched.media


async def test_get_product_with_media_loads_media(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар")
    await create_product_media_item(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    fetched = await get_product(session, bot_id, product.id, with_media=True)
    assert fetched is not None
    assert len(fetched.media) == 1
    assert fetched.media[0].storage_key == "k"


async def test_list_products_with_media_loads_media_for_every_row(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар")
    await create_product_media_item(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    products = await list_products(session, bot_id, with_media=True)
    assert len(products) == 1
    assert len(products[0].media) == 1
