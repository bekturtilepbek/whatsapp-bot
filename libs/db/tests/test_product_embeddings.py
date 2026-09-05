"""Эмбеддинги товаров (FEATURES.md 4.1): upsert_embedding (идемпотентно),
find_product_by_embedding (порог similarity, скоуп per bot, LIMIT 1).
Векторы — настоящие числовые (не заглушки): единичные орты 1536-мерного
пространства дают управляемую похожесть (одинаковый орт -> similarity 1.0,
разные орты -> ортогональны, similarity 0.0). Требует Docker
(testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.models import Bot, Product
from db.product_embeddings import find_product_by_embedding, upsert_embedding
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"

DIMENSION = 1536


def _unit_vector(index: int) -> list[float]:
    vec = [0.0] * DIMENSION
    vec[index] = 1.0
    return vec


def _mixed_vector(index_a: int, index_b: int) -> list[float]:
    """Равная смесь двух ортов, нормированная — cosine similarity с
    _unit_vector(index_a) ≈ 0.707 (меньше 1.0, но всё ещё выше порога 0.4)."""
    vec = [0.0] * DIMENSION
    norm = math.sqrt(2)
    vec[index_a] = 1 / norm
    vec[index_b] = 1 / norm
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


async def _make_product(session: AsyncSession, bot_id: uuid.UUID, name: str) -> uuid.UUID:
    product = Product(bot_id=bot_id, name=name)
    session.add(product)
    await session.flush()
    return product.id


async def test_upsert_then_find_with_identical_vector_matches(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product_id = await _make_product(session, bot_id, "Товар А")
    await upsert_embedding(session, product_id, _unit_vector(0))

    found = await find_product_by_embedding(session, bot_id, _unit_vector(0))
    assert found is not None
    assert found.id == product_id


async def test_orthogonal_vector_does_not_match_below_threshold(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product_id = await _make_product(session, bot_id, "Товар А")
    await upsert_embedding(session, product_id, _unit_vector(0))

    found = await find_product_by_embedding(session, bot_id, _unit_vector(1))
    assert found is None


async def test_upsert_is_idempotent_and_updates_the_vector(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product_id = await _make_product(session, bot_id, "Товар А")
    await upsert_embedding(session, product_id, _unit_vector(0))
    await upsert_embedding(session, product_id, _unit_vector(1))  # перезаписываем

    assert await find_product_by_embedding(session, bot_id, _unit_vector(0)) is None
    found = await find_product_by_embedding(session, bot_id, _unit_vector(1))
    assert found is not None
    assert found.id == product_id


async def test_find_is_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    product_a = await _make_product(session, bot_a, "Товар A")
    await upsert_embedding(session, product_a, _unit_vector(0))

    assert await find_product_by_embedding(session, bot_a, _unit_vector(0)) is not None
    assert await find_product_by_embedding(session, bot_b, _unit_vector(0)) is None


async def test_limit_one_returns_the_closest_match(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    close_product_id = await _make_product(session, bot_id, "Похожий")
    await upsert_embedding(session, close_product_id, _mixed_vector(0, 1))  # similarity ~0.707
    exact_product_id = await _make_product(session, bot_id, "Точный")
    await upsert_embedding(session, exact_product_id, _unit_vector(0))  # similarity 1.0

    found = await find_product_by_embedding(session, bot_id, _unit_vector(0))
    assert found is not None
    assert found.id == exact_product_id
