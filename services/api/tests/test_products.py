"""GET/POST/PATCH/DELETE /bots/{bot_id}/products (FEATURES.md 6.8, CRUD +
обязательное фото) + расчёт эмбеддинга при create/update. Строгое
V1-поведение (пересмотр 2026-09-16, см. память product-embedding-retry-
design): если generate_embedding() не удался — товар не создаётся/патч не
применяется вообще, никакой Celery-подстраховки в фоне больше нет.
generate_embedding подменяется моком — реальный OpenAI в юнит-тестах не
участвует (живой прогон — docker compose).

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from PIL import Image

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from api.routers import products as products_module
from api.storage import get_storage
from db.engine import make_engine, make_session_factory
from db.models import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_owner_auth

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


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.objects[key] = (data, mime_type)


@pytest.fixture
def fake_storage() -> _FakeStorage:
    return _FakeStorage()


def _tiny_jpeg_bytes(*, size: tuple[int, int] = (20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color="red").save(buf, format="JPEG")
    return buf.getvalue()


def _media_file(name: str = "photo.jpg") -> tuple[str, tuple[str, bytes, str]]:
    return ("media", (name, _tiny_jpeg_bytes(), "image/jpeg"))


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_storage] = lambda: fake_storage
    app.state.audit_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None


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
    response = await client.post(
        f"/bots/{bot_id}/products", data={"name": "   "}, files=[_media_file()]
    )
    assert response.status_code == 422


async def test_create_product_for_unknown_bot_returns_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/bots/{uuid.uuid4()}/products", data={"name": "Товар"}, files=[_media_file()]
    )
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
        data={"name": "Кроссовки", "description": "Беговые", "price": "5000"},
        files=[_media_file()],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Кроссовки"
    assert body["price"] == "5000"
    assert len(body["media"]) == 1

    async with session_factory() as session:
        from db.product_embeddings import find_product_by_embedding

        found = await find_product_by_embedding(session, bot_id, FAKE_EMBEDDING, threshold=0.0)
        assert found is not None
        assert found.id == uuid.UUID(body["id"])


async def test_create_product_with_valid_display_custom_object(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "display_custom": '{"show_price": false}'},
        files=[_media_file()],
    )

    assert response.status_code == 201
    assert response.json()["display_custom"] == {"show_price": False}


async def test_create_product_with_invalid_json_display_custom_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "display_custom": "not json"},
        files=[_media_file()],
    )

    assert response.status_code == 422


async def test_create_product_with_non_object_display_custom_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "display_custom": "[1,2,3]"},
        files=[_media_file()],
    )

    assert response.status_code == 422


async def test_create_list_get_flow(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)

    created = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_media_file()]
    )
    product_id = created.json()["id"]

    listing = await client.get(f"/bots/{bot_id}/products")
    assert listing.status_code == 200
    assert [p["id"] for p in listing.json()] == [product_id]
    assert len(listing.json()[0]["media"]) == 1

    fetched = await client.get(f"/bots/{bot_id}/products/{product_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == product_id
    assert len(fetched.json()["media"]) == 1


async def test_list_products_respects_limit_and_offset(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    for name in ("Апельсины", "Бананы", "Вишня"):
        await client.post(f"/bots/{bot_id}/products", data={"name": name}, files=[_media_file()])

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
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Описание"},
        files=[_media_file()],
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
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Старое"},
        files=[_media_file()],
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
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Без изменений"},
        files=[_media_file()],
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


async def test_create_rejects_product_when_embedding_fails(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строгое V1-поведение (пересмотр 2026-09-16): сбой генерации
    эмбеддинга отклоняет всё создание товара целиком — ни строки products,
    ни загруженных фото не остаётся. Никакой Celery-подстраховки в фоне
    больше нет."""
    monkeypatch.setattr(products_module, "generate_embedding", _failing_generate_embedding)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_media_file()]
    )

    assert response.status_code == 502
    listed = await client.get(f"/bots/{bot_id}/products")
    assert listed.json() == []


async def test_patch_rejects_update_when_embedding_fails(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строгое V1-поведение: сбой пересчёта эмбеддинга (из-за смены
    description) отклоняет ВЕСЬ патч целиком — даже несвязанное поле price
    в том же запросе не применяется."""
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Старое", "price": "100"},
        files=[_media_file()],
    )
    product_id = created.json()["id"]

    monkeypatch.setattr(products_module, "generate_embedding", _failing_generate_embedding)
    response = await client.patch(
        f"/bots/{bot_id}/products/{product_id}",
        json={"description": "Новое", "price": 999},
    )

    assert response.status_code == 502
    unchanged = await client.get(f"/bots/{bot_id}/products/{product_id}")
    assert unchanged.json()["description"] == "Старое"
    assert unchanged.json()["price"] == "100.00"


async def test_delete_product_removes_it(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_media_file()]
    )
    product_id = created.json()["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product_id}")
    assert response.status_code == 204

    assert (await client.get(f"/bots/{bot_id}/products/{product_id}")).status_code == 404


async def test_create_product_without_media_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"})
    assert response.status_code == 422


async def test_create_product_rejects_unsupported_mime_type(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар"},
        files=[("media", ("file.txt", b"not an image", "text/plain"))],
    )
    assert response.status_code == 422


async def test_create_product_rejects_corrupt_image(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар"},
        files=[("media", ("photo.jpg", b"garbage bytes, not a real jpeg", "image/jpeg"))],
    )
    assert response.status_code == 422


async def test_create_product_rejects_more_than_max_media(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # products_module импортировал MAX_MEDIA_PER_PRODUCT через
    # "from ..product_media import MAX_MEDIA_PER_PRODUCT" — это отдельное
    # имя в его собственном namespace, патчить нужно именно его; патч
    # "api.product_media.MAX_MEDIA_PER_PRODUCT" на уже импортированную
    # константу в products_module никак не повлияет.
    monkeypatch.setattr(products_module, "MAX_MEDIA_PER_PRODUCT", 2)
    bot_id = await _make_bot(session_factory)
    files = [_media_file(f"photo{i}.jpg") for i in range(3)]
    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"}, files=files)
    assert response.status_code == 422


async def test_create_product_stores_multiple_media_items_in_order(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    files = [_media_file("a.jpg"), _media_file("b.jpg")]

    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"}, files=files)

    assert response.status_code == 201
    media = response.json()["media"]
    assert len(media) == 2
    assert [p["position"] for p in media] == [0, 1]


async def test_create_product_rolls_back_when_storage_fails(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_put(key: str, data: bytes, mime_type: str) -> None:
        raise RuntimeError("storage недоступен")

    # fake_storage — тот же экземпляр, что фикстура client уже подключила
    # через dependency_overrides; патчим один метод, не подменяем всю
    # зависимость — проще и не завязано на порядок teardown между тестами.
    monkeypatch.setattr(fake_storage, "put", failing_put)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_media_file()]
    )
    assert response.status_code == 502

    listing = await client.get(f"/bots/{bot_id}/products")
    assert listing.json() == []


async def _create_product_with_media(
    client: httpx.AsyncClient, bot_id: uuid.UUID, *, count: int = 1
) -> dict[str, object]:
    files = [_media_file(f"p{i}.jpg") for i in range(count)]
    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"}, files=files)
    assert response.status_code == 201
    return response.json()


async def test_add_product_media_appends_with_next_position(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id)

    response = await client.post(
        f"/bots/{bot_id}/products/{product['id']}/media", files=[_media_file("new.jpg")]
    )

    assert response.status_code == 201
    added = response.json()
    assert len(added) == 1
    assert added[0]["position"] == 1  # первое фото товара уже заняло 0


async def test_add_product_media_rejects_exceeding_max_total(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    # Тот же нюанс, что в test_create_product_rejects_more_than_max_media —
    # патчить нужно имя в namespace products_module, не в product_media.
    monkeypatch.setattr(products_module, "MAX_MEDIA_PER_PRODUCT", 2)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id, count=2)

    response = await client.post(
        f"/bots/{bot_id}/products/{product['id']}/media", files=[_media_file("one_too_many.jpg")]
    )

    assert response.status_code == 422


async def test_add_product_media_for_unknown_product_returns_404(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products/{uuid.uuid4()}/media", files=[_media_file()]
    )
    assert response.status_code == 404


async def test_delete_product_media_removes_it_when_not_the_last_one(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id, count=2)
    media_id = product["media"][0]["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product['id']}/media/{media_id}")
    assert response.status_code == 204

    fetched = await client.get(f"/bots/{bot_id}/products/{product['id']}")
    assert len(fetched.json()["media"]) == 1


async def test_delete_last_product_media_returns_422(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id, count=1)
    media_id = product["media"][0]["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product['id']}/media/{media_id}")
    assert response.status_code == 422

    fetched = await client.get(f"/bots/{bot_id}/products/{product['id']}")
    assert len(fetched.json()["media"]) == 1


async def test_delete_product_media_unknown_id_returns_404(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id, count=1)

    response = await client.delete(
        f"/bots/{bot_id}/products/{product['id']}/media/{uuid.uuid4()}"
    )
    assert response.status_code == 404


async def test_get_product_media_returns_bytes_with_content_type(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id, count=1)
    media_id = product["media"][0]["id"]

    response = await client.get(f"/bots/{bot_id}/products/{product['id']}/media/{media_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0


async def test_get_product_media_unknown_id_returns_404(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_media(client, bot_id, count=1)

    response = await client.get(
        f"/bots/{bot_id}/products/{product['id']}/media/{uuid.uuid4()}"
    )
    assert response.status_code == 404
