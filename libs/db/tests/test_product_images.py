"""Фото товара (FEATURES.md 4.3/4.4): list_product_images — порядок по
position, скоуп per product, пусто по умолчанию. Требует Docker
(testcontainers). Без него — skip, не fail.
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
from db.models import Bot, Product, ProductImage
from db.product_images import (
    create_product_image,
    delete_product_image,
    get_product_image,
    list_product_images,
    next_position,
)
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


async def _make_product(session: AsyncSession) -> uuid.UUID:
    bot = Bot(name="test-bot")
    session.add(bot)
    await session.flush()
    product = Product(bot_id=bot.id, name="Кроссовки Nike Air")
    session.add(product)
    await session.flush()
    return product.id


async def test_list_product_images_empty_by_default(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await list_product_images(session, product_id) == []


async def test_list_product_images_ordered_by_position(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    session.add_all(
        [
            ProductImage(
                product_id=product_id, storage_key="img-2", mime_type="image/jpeg", position=2
            ),
            ProductImage(
                product_id=product_id, storage_key="img-0", mime_type="image/jpeg", position=0
            ),
            ProductImage(
                product_id=product_id, storage_key="img-1", mime_type="image/jpeg", position=1
            ),
        ]
    )
    await session.flush()

    images = await list_product_images(session, product_id)
    assert [i.storage_key for i in images] == ["img-0", "img-1", "img-2"]


async def test_list_product_images_scoped_per_product(session: AsyncSession) -> None:
    product_a = await _make_product(session)
    product_b = await _make_product(session)
    session.add_all(
        [
            ProductImage(
                product_id=product_a, storage_key="img-a", mime_type="image/jpeg", position=0
            ),
            ProductImage(
                product_id=product_b, storage_key="img-b", mime_type="image/jpeg", position=0
            ),
        ]
    )
    await session.flush()

    images_a = await list_product_images(session, product_a)
    assert [i.storage_key for i in images_a] == ["img-a"]


async def test_next_position_is_zero_when_no_images(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await next_position(session, product_id) == 0


async def test_next_position_is_max_plus_one(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    session.add_all(
        [
            ProductImage(
                product_id=product_id, storage_key="img-0", mime_type="image/jpeg", position=0
            ),
            ProductImage(
                product_id=product_id, storage_key="img-2", mime_type="image/jpeg", position=2
            ),
        ]
    )
    await session.flush()

    # Позиция 1 пропущена (например, удалили) — следующая всё равно 3,
    # не переиспользует дыру: next_position = max(position) + 1.
    assert await next_position(session, product_id) == 3


async def test_create_product_image_uses_given_id(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    photo_id = uuid.uuid4()

    image = await create_product_image(
        session, product_id, id=photo_id, storage_key="k", mime_type="image/jpeg", position=0
    )

    assert image.id == photo_id
    assert image.storage_key == "k"


async def test_get_product_image_returns_none_when_missing(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await get_product_image(session, product_id, uuid.uuid4()) is None


async def test_get_product_image_scoped_per_product(session: AsyncSession) -> None:
    product_a = await _make_product(session)
    product_b = await _make_product(session)
    image = await create_product_image(
        session, product_a, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    assert await get_product_image(session, product_a, image.id) is not None
    assert await get_product_image(session, product_b, image.id) is None


async def test_delete_product_image_removes_row(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    image = await create_product_image(
        session, product_id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    deleted = await delete_product_image(session, product_id, image.id)
    assert deleted is True
    assert await get_product_image(session, product_id, image.id) is None


async def test_delete_product_image_returns_false_when_missing(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await delete_product_image(session, product_id, uuid.uuid4()) is False
