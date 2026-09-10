"""GET/POST/PATCH/DELETE /bots/{bot_id}/products (FEATURES.md 6.8, CRUD без
фото) + автопересчёт эмбеддинга при create/update. generate_embedding и
celery_app подменяются моками — реальный OpenAI/Celery в юнит-тестах не
участвуют (живой прогон — docker compose, см. план, Task 8).

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from api.routers import products as products_module
from db.engine import make_engine, make_session_factory
from db.models import Bot
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
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


class _FakeCeleryApp:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_task(self, name: str, args: list[object]) -> None:
        self.calls.append({"name": name, "args": args})


@pytest.fixture
def fake_celery(monkeypatch: pytest.MonkeyPatch) -> _FakeCeleryApp:
    fake = _FakeCeleryApp()
    monkeypatch.setattr(products_module, "celery_app", fake)
    return fake


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="product-test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


FAKE_EMBEDDING = [0.1] * 1536


async def _fake_generate_embedding(text: str, **kwargs: object) -> list[float]:
    return FAKE_EMBEDDING


async def _failing_generate_embedding(text: str, **kwargs: object) -> list[float]:
    raise RuntimeError("openai недоступен")


async def test_create_product_requires_name(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/products", json={"name": "   "})
    assert response.status_code == 422


async def test_create_product_for_unknown_bot_returns_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(f"/bots/{uuid.uuid4()}/products", json={"name": "Товар"})
    assert response.status_code == 404


async def test_create_computes_embedding_and_returns_product(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products",
        json={"name": "Кроссовки", "description": "Беговые", "price": 5000},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Кроссовки"
    assert body["price"] == "5000"

    async with session_factory() as session:
        from db.product_embeddings import find_product_by_embedding

        found = await find_product_by_embedding(session, bot_id, FAKE_EMBEDDING, threshold=0.0)
        assert found is not None
        assert found.id == uuid.UUID(body["id"])


async def test_create_list_get_flow(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)

    created = await client.post(f"/bots/{bot_id}/products", json={"name": "Товар"})
    product_id = created.json()["id"]

    listing = await client.get(f"/bots/{bot_id}/products")
    assert listing.status_code == 200
    assert [p["id"] for p in listing.json()] == [product_id]

    fetched = await client.get(f"/bots/{bot_id}/products/{product_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == product_id


async def test_list_products_respects_limit_and_offset(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    for name in ("Апельсины", "Бананы", "Вишня"):
        await client.post(f"/bots/{bot_id}/products", json={"name": name})

    first_page = await client.get(f"/bots/{bot_id}/products", params={"limit": 2})
    assert first_page.status_code == 200
    assert [p["name"] for p in first_page.json()] == ["Апельсины", "Бананы"]

    second_page = await client.get(
        f"/bots/{bot_id}/products", params={"limit": 2, "offset": 2}
    )
    assert [p["name"] for p in second_page.json()] == ["Вишня"]


async def test_list_products_limit_out_of_range_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    assert (
        await client.get(f"/bots/{bot_id}/products", params={"limit": 0})
    ).status_code == 422
    assert (
        await client.get(f"/bots/{bot_id}/products", params={"limit": 501})
    ).status_code == 422


def test_default_list_limit_matches_prior_http_behavior() -> None:
    """Регрессия на находку code review (2026-09-10): роут раньше молча
    считал limit=DEFAULT_CATALOG_LIMIT=200 для любого вызова без ?limit=
    (db.products.list_products), пагинация не должна была урезать этот
    дефолт для внешних вызывающих (сейчас только admin-web, но роут
    публичный) — admin-web передаёт свой limit явно и здесь не участвует."""
    assert products_module.PRODUCTS_LIST_DEFAULT_LIMIT == 200


async def test_get_patch_delete_unknown_product_returns_404(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    missing_id = uuid.uuid4()

    assert (await client.get(f"/bots/{bot_id}/products/{missing_id}")).status_code == 404
    assert (
        await client.patch(f"/bots/{bot_id}/products/{missing_id}", json={"name": "x"})
    ).status_code == 404
    assert (await client.delete(f"/bots/{bot_id}/products/{missing_id}")).status_code == 404


async def test_patch_price_only_does_not_recompute_embedding(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def counting_generate_embedding(text: str, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", counting_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products", json={"name": "Товар", "description": "Описание"}
    )
    product_id = created.json()["id"]
    assert calls == 1  # создание всегда считает эмбеддинг

    response = await client.patch(f"/bots/{bot_id}/products/{product_id}", json={"price": 999})
    assert response.status_code == 200
    assert calls == 1  # цена — не name/description, пересчёта не было


async def test_patch_description_recomputes_embedding(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def counting_generate_embedding(text: str, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", counting_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products", json={"name": "Товар", "description": "Старое"}
    )
    product_id = created.json()["id"]
    assert calls == 1

    response = await client.patch(
        f"/bots/{bot_id}/products/{product_id}", json={"description": "Новое"}
    )
    assert response.status_code == 200
    assert calls == 2


async def test_patch_description_same_value_does_not_recompute_embedding(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def counting_generate_embedding(text: str, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", counting_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products", json={"name": "Товар", "description": "Без изменений"}
    )
    product_id = created.json()["id"]
    assert calls == 1

    # description присутствует в теле PATCH, но равен уже сохранённому значению —
    # это не "изменение", пересчёта быть не должно (отличает "поле передано" от
    # "значение изменилось").
    response = await client.patch(
        f"/bots/{bot_id}/products/{product_id}", json={"description": "Без изменений"}
    )
    assert response.status_code == 200
    assert calls == 1


async def test_create_falls_back_to_celery_when_embedding_fails(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_celery: _FakeCeleryApp,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _failing_generate_embedding)
    bot_id = await _make_bot(session_factory)

    response = await client.post(f"/bots/{bot_id}/products", json={"name": "Товар"})

    # Товар всё равно создаётся, несмотря на сбой эмбеддинга.
    assert response.status_code == 201
    product_id = response.json()["id"]

    assert len(fake_celery.calls) == 1
    assert fake_celery.calls[0]["name"] == RECOMPUTE_PRODUCT_EMBEDDING
    assert fake_celery.calls[0]["args"] == [product_id]


async def test_delete_product_removes_it(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(f"/bots/{bot_id}/products", json={"name": "Товар"})
    product_id = created.json()["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product_id}")
    assert response.status_code == 204

    assert (await client.get(f"/bots/{bot_id}/products/{product_id}")).status_code == 404
