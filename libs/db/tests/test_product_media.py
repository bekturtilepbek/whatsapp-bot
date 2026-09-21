"""Медиа товара (FEATURES.md 4.3/4.4): list_product_media — порядок по
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
from db.models import Bot, Product, ProductMedia
from db.product_media import (
    create_product_media_item,
    delete_product_media_item,
    get_product_media_item,
    list_product_media,
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


async def test_list_product_media_empty_by_default(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await list_product_media(session, product_id) == []


async def test_list_product_media_ordered_by_position(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    session.add_all(
        [
            ProductMedia(
                product_id=product_id, storage_key="img-2", mime_type="image/jpeg", position=2
            ),
            ProductMedia(
                product_id=product_id, storage_key="img-0", mime_type="image/jpeg", position=0
            ),
            ProductMedia(
                product_id=product_id, storage_key="video-1", mime_type="video/mp4", position=1
            ),
        ]
    )
    await session.flush()

    media = await list_product_media(session, product_id)
    assert [m.storage_key for m in media] == ["img-0", "video-1", "img-2"]


async def test_list_product_media_scoped_per_product(session: AsyncSession) -> None:
    product_a = await _make_product(session)
    product_b = await _make_product(session)
    session.add_all(
        [
            ProductMedia(
                product_id=product_a, storage_key="img-a", mime_type="image/jpeg", position=0
            ),
            ProductMedia(
                product_id=product_b, storage_key="img-b", mime_type="image/jpeg", position=0
            ),
        ]
    )
    await session.flush()

    media_a = await list_product_media(session, product_a)
    assert [m.storage_key for m in media_a] == ["img-a"]


async def test_next_position_is_zero_when_no_media(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await next_position(session, product_id) == 0


async def test_next_position_is_max_plus_one(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    session.add_all(
        [
            ProductMedia(
                product_id=product_id, storage_key="img-0", mime_type="image/jpeg", position=0
            ),
            ProductMedia(
                product_id=product_id, storage_key="img-2", mime_type="image/jpeg", position=2
            ),
        ]
    )
    await session.flush()

    # Позиция 1 пропущена (например, удалили) — следующая всё равно 3,
    # не переиспользует дыру: next_position = max(position) + 1.
    assert await next_position(session, product_id) == 3


async def test_create_product_media_item_uses_given_id(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    media_id = uuid.uuid4()

    media = await create_product_media_item(
        session, product_id, id=media_id, storage_key="k", mime_type="video/mp4", position=0
    )

    assert media.id == media_id
    assert media.storage_key == "k"
    assert media.mime_type == "video/mp4"


async def test_get_product_media_item_returns_none_when_missing(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await get_product_media_item(session, product_id, uuid.uuid4()) is None


async def test_get_product_media_item_scoped_per_product(session: AsyncSession) -> None:
    product_a = await _make_product(session)
    product_b = await _make_product(session)
    media = await create_product_media_item(
        session, product_a, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    assert await get_product_media_item(session, product_a, media.id) is not None
    assert await get_product_media_item(session, product_b, media.id) is None


async def test_delete_product_media_item_removes_row(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    media = await create_product_media_item(
        session, product_id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    deleted = await delete_product_media_item(session, product_id, media.id)
    assert deleted is True
    assert await get_product_media_item(session, product_id, media.id) is None


async def test_delete_product_media_item_returns_false_when_missing(
    session: AsyncSession,
) -> None:
    product_id = await _make_product(session)
    assert await delete_product_media_item(session, product_id, uuid.uuid4()) is False
