"""recompute_product_embedding (FEATURES.md 4.1/6.8) — подстраховка на
случай сбоя синхронной попытки эмбеддинга в services/api. Идемпотентна:
читает АКТУАЛЬНЫЕ name/description на момент срабатывания (не то, что было
при постановке задачи — товар могли отредактировать ещё раз).

Тестируем async-тело напрямую (DI session_factory, как send_reminder в
test_followup.py) — реальный прогон через Celery-воркер: живой прогон,
docker compose (см. план, Task 8).

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
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
from db.models import Bot, Product
from db.product_embeddings import find_product_by_embedding
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
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
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


FAKE_EMBEDDING = [0.2] * 1536


async def test_recomputes_embedding_from_current_db_values(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tasks.products as products_module

    async def fake_generate_embedding(text: str, **kwargs: object) -> list[float]:
        assert "Актуальное имя" in text
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", fake_generate_embedding)

    async with session_factory() as session:
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        product = Product(bot_id=bot.id, name="Актуальное имя")
        session.add(product)
        await session.commit()
        product_id = product.id
        bot_id = bot.id

    await products_module._recompute_async(session_factory, str(product_id))

    async with session_factory() as session:
        found = await find_product_by_embedding(session, bot_id, FAKE_EMBEDDING, threshold=0.0)
        assert found is not None
        assert found.id == product_id


async def test_no_op_when_product_was_deleted(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tasks.products as products_module

    async def failing_generate_embedding(text: str, **kwargs: object) -> list[float]:
        raise AssertionError("не должен вызываться для удалённого товара")

    monkeypatch.setattr(products_module, "generate_embedding", failing_generate_embedding)

    # Не должно упасть — товара с таким id никогда не было.
    await products_module._recompute_async(session_factory, str(uuid.uuid4()))
