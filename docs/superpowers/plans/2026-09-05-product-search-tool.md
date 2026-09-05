# pgvector-поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** первая настоящая тулза для цикла LLM↔tool-calls — поиск товара
по каталогу бота: точное совпадение по имени, при отсутствии — векторный
поиск через pgvector (cosine similarity).

**Architecture:** `libs/db` (схема + чистые запросы) → `libs/llm`
(генерация эмбеддинга через OpenAI) → `libs/tools` (сама тулза,
композирует оба слоя). `services/worker`/`services/api` не меняются —
цикл тулз и API включения уже готовы с прошлой итерации.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async, `pgvector` (новая
зависимость, `pgvector.sqlalchemy.Vector`), OpenAI `text-embedding-3-small`,
pytest + testcontainers (`pgvector/pgvector:pg17` — уже содержит бинарник
расширения).

**Spec:** [docs/superpowers/specs/2026-09-05-product-search-tool-design.md](../specs/2026-09-05-product-search-tool-design.md)

## Global Constraints

- Порядок поиска — **точное** регистронезависимое совпадение по имени
  первым (`LOWER(TRIM(name)) = LOWER(query.strip())`, НЕ `ILIKE`-подстрока),
  векторный поиск — только если точного нет (эталон V1, подтверждено
  пользователем — расхождение с буквальным текстом FEATURES.md сознательное).
- Векторный поиск: cosine similarity, порог **0.4**, `LIMIT 1` — ровно
  один товар или ничего, никогда список из нескольких.
- Модель эмбеддинга — `text-embedding-3-small`; входной текст —
  `f"Name: {name}; Description: {description or ''}"` (эталон V1,
  `central-admin/main.py`).
- `product_embeddings` — 1:1 с товаром (`product_id` PK+FK), без ANN-индекса
  (осознанно отложено).
- Контракт результата тулзы — JSON-массив 0 или 1 объекта
  `{name, description, price}`, `price` по умолчанию строка
  `"Не указана"` (не `null`, не `"-"` — это ДРУГОЙ контракт, чем у
  каталога 3.4). Пустой результат — строка `"[]"`.
- Имя тулзы — `search_products`; реестр (`libs/tools/src/tools/registry.py`)
  получает `register(tool)`, ключ всегда `tool.name` (закрывает находку
  прошлого финального ревью — расхождение ключа и `tool.name`).
- `libs/db` не импортирует `llm` и не вызывает OpenAI. `libs/llm` не
  импортирует `db` и не знает о Postgres. Только `libs/tools` зависит от
  обоих (ADR-002).
- `services/worker`/`services/api` — **не трогать** в этом плане.
- Ruff + mypy strict на весь новый код; Conventional Commits; ветка `dev`.
- Триггер пересчёта эмбеддинга при create/update товара — Волна 3 (CRUD),
  вне охвата этого плана; для живой проверки эмбеддинг тестового товара
  считается вручную одноразовым скриптом (не коммитится).

---

## Task 1: `libs/db` — схема `product_embeddings` + запросы

**Files:**
- Modify: `libs/db/pyproject.toml` (добавить `pgvector>=0.3`)
- Modify: `libs/db/src/db/models.py` (добавить `ProductEmbedding`)
- Create: `libs/db/migrations/versions/202609051004_product_embeddings.py`
- Create: `libs/db/src/db/product_embeddings.py`
- Modify: `libs/db/src/db/products.py` (добавить `find_product_by_exact_name`)
- Modify: `libs/db/tests/test_products.py` (добавить 3 теста)
- Modify: `libs/db/tests/test_migration.py` (добавить `"product_embeddings"`)
- Create: `libs/db/tests/test_product_embeddings.py`

**Interfaces:**
- Produces: `db.models.ProductEmbedding` (`product_id: uuid.UUID` PK+FK
  `products.id` ON DELETE CASCADE, `embedding: list[float]` через
  `pgvector.sqlalchemy.Vector(1536)`); `db.products.find_product_by_exact_name(session: AsyncSession, bot_id: uuid.UUID, name: str) -> Product | None`;
  `db.product_embeddings.upsert_embedding(session: AsyncSession, product_id: uuid.UUID, embedding: list[float]) -> None`;
  `db.product_embeddings.find_product_by_embedding(session: AsyncSession, bot_id: uuid.UUID, query_embedding: list[float], *, threshold: float = 0.4) -> Product | None`
  — используются в Task 3.

- [ ] **Step 1: Добавить зависимость и установить**

`libs/db/pyproject.toml` — в `dependencies`, после `"alembic>=1.13",`:

```toml
    "pgvector>=0.3",
```

Run: `./.venv/Scripts/python.exe -m pip install -e libs/db`

- [ ] **Step 2: Написать тесты `find_product_by_exact_name` (падают — функции нет)**

Добавить в `libs/db/tests/test_products.py` импорт (заменить строку
`from db.products import list_products` на):

```python
from db.products import find_product_by_exact_name, list_products
```

Добавить в конец файла:

```python
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
```

**Важно:** используй уже существующую в этом файле фикстуру `session`
(function-scoped `AsyncSession`) и хелпер `_make_bot(session)` — не
создавай новых. Остальные тесты файла делают `session.add(...)` + `await
session.flush()` без явного `session.commit()` — следуй тому же стилю.

- [ ] **Step 3: Запустить тесты, убедиться что падают**

Run: `./.venv/Scripts/python.exe -m pytest libs/db/tests/test_products.py -v`
Expected: FAIL (`ImportError: cannot import name 'find_product_by_exact_name' from 'db.products'`)

- [ ] **Step 4: Реализовать `find_product_by_exact_name`**

`libs/db/src/db/products.py` — заменить импорт:

```python
from sqlalchemy import func, select
```

и добавить функцию в конец файла:

```python
async def find_product_by_exact_name(
    session: AsyncSession, bot_id: uuid.UUID, name: str
) -> Product | None:
    """Точное регистронезависимое совпадение (эталон V1,
    vectorProductSearch: LOWER(TRIM(name)) = LOWER($1)) — НЕ подстрока/ILIKE.
    Идёт первым, до векторного поиска (db.product_embeddings)."""
    stmt = select(Product).where(
        Product.bot_id == bot_id,
        func.lower(func.trim(Product.name)) == func.lower(name.strip()),
    )
    result = await session.execute(stmt)
    return result.scalars().first()
```

- [ ] **Step 5: Запустить тесты products.py, убедиться что проходят**

Run: `./.venv/Scripts/python.exe -m pytest libs/db/tests/test_products.py -v`
Expected: PASS (все тесты файла — старые из 3.4 и три новых)

- [ ] **Step 6: Написать тесты `product_embeddings.py` (падают — модуля нет)**

`libs/db/tests/test_product_embeddings.py`:

```python
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
```

- [ ] **Step 7: Запустить тесты, убедиться что падают**

Run: `./.venv/Scripts/python.exe -m pytest libs/db/tests/test_product_embeddings.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'db.product_embeddings'`)

- [ ] **Step 8: Добавить модель `ProductEmbedding`**

`libs/db/src/db/models.py` — добавить импорт (в блок импортов сверху,
рядом с другими из `sqlalchemy.dialects.postgresql`):

```python
from pgvector.sqlalchemy import Vector
```

Добавить класс в конец файла:

```python
class ProductEmbedding(Base):
    """Эмбеддинг товара для pgvector-поиска (FEATURES.md 4.1) — 1:1 с
    товаром (как BotSession.bot_id). Кто считает эмбеддинг и когда —
    Волна 3 (CRUD, create/update товара); здесь только хранение и чтение.
    """

    __tablename__ = "product_embeddings"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
```

- [ ] **Step 9: Написать миграцию**

`libs/db/migrations/versions/202609051004_product_embeddings.py`:

```python
"""product_embeddings

Revision ID: 202609051004
Revises: 202609051003
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "202609051004"
down_revision: str | None = "202609051003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "product_embeddings",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(1536), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("product_embeddings")
    # Расширение не откатываем — может использоваться другими объектами схемы.
```

- [ ] **Step 10: Реализовать `product_embeddings.py`**

`libs/db/src/db/product_embeddings.py`:

```python
"""Эмбеддинги товаров для векторного поиска (FEATURES.md 4.1). Кто и
когда их считает — Волна 3 (CRUD, create/update товара); здесь только
хранение (upsert_embedding) и чтение (find_product_by_embedding).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, ProductEmbedding

DEFAULT_SIMILARITY_THRESHOLD = 0.4


async def upsert_embedding(
    session: AsyncSession, product_id: uuid.UUID, embedding: list[float]
) -> None:
    """Идемпотентно: product_id — PK, повторный вызов обновляет вектор,
    не дублирует строку."""
    stmt = (
        insert(ProductEmbedding)
        .values(product_id=product_id, embedding=embedding)
        .on_conflict_do_update(
            index_elements=["product_id"],
            set_={"embedding": embedding},
        )
    )
    await session.execute(stmt)
    await session.flush()


async def find_product_by_embedding(
    session: AsyncSession,
    bot_id: uuid.UUID,
    query_embedding: list[float],
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> Product | None:
    """Эталон V1 (vectorProductSearch): cosine similarity > threshold,
    ORDER BY similarity DESC, LIMIT 1 — ровно один товар, не список."""
    similarity = 1 - ProductEmbedding.embedding.cosine_distance(query_embedding)
    stmt = (
        select(Product)
        .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .where(Product.bot_id == bot_id, similarity > threshold)
        .order_by(similarity.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()
```

- [ ] **Step 11: Добавить `"product_embeddings"` в ожидаемые таблицы `test_migration.py`**

`libs/db/tests/test_migration.py` — заменить:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products",
        } <= tables
```

на:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products", "product_embeddings",
        } <= tables
```

- [ ] **Step 12: Запустить весь `libs/db`, убедиться что всё проходит**

Run: `./.venv/Scripts/python.exe -m pytest libs/db -v`
Expected: PASS (все тесты пакета, включая новые)

- [ ] **Step 13: ruff + mypy**

Run: `./.venv/Scripts/python.exe -m ruff check libs/db && ./.venv/Scripts/python.exe -m mypy libs/db/src`
Expected: без ошибок

- [ ] **Step 14: Commit**

```bash
git add libs/db/pyproject.toml libs/db/src/db/models.py libs/db/src/db/products.py libs/db/src/db/product_embeddings.py libs/db/migrations/versions/202609051004_product_embeddings.py libs/db/tests/test_products.py libs/db/tests/test_product_embeddings.py libs/db/tests/test_migration.py
git commit -m "feat(db): product_embeddings table and vector/exact-match queries (FEATURES.md 4.1/4.2)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `libs/llm` — генерация эмбеддинга товара

**Files:**
- Create: `libs/llm/src/llm/embeddings.py`
- Create: `libs/llm/tests/test_embeddings.py`

**Interfaces:**
- Consumes: `llm.client.{REQUEST_TIMEOUT_SECONDS, RETRY_MAX_ATTEMPTS, RETRY_BASE_DELAY_SECONDS, _RETRYABLE_EXCEPTIONS, _default_client}` (уже существуют, не меняются).
- Produces: `llm.embeddings.EMBEDDING_MODEL = "text-embedding-3-small"`;
  `llm.embeddings.product_embedding_input(name: str, description: str | None) -> str`;
  `llm.embeddings.generate_embedding(text: str, *, client: AsyncOpenAI | None = None, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> list[float]`
  — `generate_embedding` используется в Task 3.

- [ ] **Step 1: Написать тесты (падают — модуля нет)**

`libs/llm/tests/test_embeddings.py`:

```python
"""Генерация эмбеддинга товара (FEATURES.md 4.1). Реального сетевого
вызова нет — client инжектится как duck-typed фейк формы
openai.AsyncOpenAI (.embeddings.create), тот же приём, что test_client.py
для .chat.completions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx2
import openai
import pytest
from llm.embeddings import generate_embedding, product_embedding_input


@dataclass
class _FakeEmbeddingData:
    embedding: list[float]


@dataclass
class _FakeEmbeddingResponse:
    data: list[_FakeEmbeddingData]


class _FakeEmbeddingsEndpoint:
    def __init__(
        self, response: _FakeEmbeddingResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.last_call_kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> _FakeEmbeddingResponse:
        self.last_call_kwargs = kwargs
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeClient:
    def __init__(self, embeddings: _FakeEmbeddingsEndpoint) -> None:
        self.embeddings = embeddings


def _client_with_vector(vector: list[float]) -> _FakeClient:
    response = _FakeEmbeddingResponse(data=[_FakeEmbeddingData(embedding=vector)])
    return _FakeClient(_FakeEmbeddingsEndpoint(response=response))


class _FlakyEmbeddingsEndpoint:
    """Возвращает элементы `outcomes` по очереди на каждый вызов `create()` —
    исключение бросается, ответ возвращается (тот же приём, что
    _FlakyCompletions в test_client.py)."""

    def __init__(self, outcomes: list[Exception | _FakeEmbeddingResponse]) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def create(self, **kwargs: object) -> _FakeEmbeddingResponse:
        outcome = self._outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class _RecordingSleep:
    calls: list[float] = field(default_factory=list)

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


def _fake_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


def _rate_limit_error() -> openai.RateLimitError:
    request = _fake_request()
    return openai.RateLimitError(
        "rate limited", response=httpx2.Response(429, request=request), body=None
    )


def _auth_error() -> openai.AuthenticationError:
    request = _fake_request()
    return openai.AuthenticationError(
        "invalid api key", response=httpx2.Response(401, request=request), body=None
    )


def test_product_embedding_input_combines_name_and_description() -> None:
    result = product_embedding_input("Кроссовки Nike Air", "Беговые")
    assert result == "Name: Кроссовки Nike Air; Description: Беговые"


def test_product_embedding_input_handles_missing_description() -> None:
    result = product_embedding_input("Товар без описания", None)
    assert result == "Name: Товар без описания; Description: "


async def test_generate_embedding_returns_the_vector() -> None:
    client = _client_with_vector([0.1, 0.2, 0.3])
    result = await generate_embedding("Name: X; Description: Y", client=client)  # type: ignore[arg-type]
    assert result == [0.1, 0.2, 0.3]


async def test_generate_embedding_sends_the_configured_model_and_input_text() -> None:
    client = _client_with_vector([0.1])
    await generate_embedding("some text", client=client)  # type: ignore[arg-type]
    assert client.embeddings.last_call_kwargs["model"] == "text-embedding-3-small"
    assert client.embeddings.last_call_kwargs["input"] == "some text"


async def test_generate_embedding_passes_timeout_through_to_sdk() -> None:
    client = _client_with_vector([0.1])
    await generate_embedding("text", client=client, timeout_seconds=12.5)  # type: ignore[arg-type]
    assert client.embeddings.last_call_kwargs["timeout"] == 12.5


async def test_retries_on_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    response = _FakeEmbeddingResponse(data=[_FakeEmbeddingData(embedding=[0.5])])
    endpoint = _FlakyEmbeddingsEndpoint([_rate_limit_error(), _rate_limit_error(), response])
    client = _FakeClient(endpoint)  # type: ignore[arg-type]

    result = await generate_embedding("text", client=client)  # type: ignore[arg-type]

    assert result == [0.5]
    assert endpoint.call_count == 3
    assert sleep.calls == [1.0, 2.0]


async def test_gives_up_after_max_attempts_and_raises_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _RecordingSleep())
    endpoint = _FlakyEmbeddingsEndpoint(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()]
    )
    client = _FakeClient(endpoint)  # type: ignore[arg-type]

    with pytest.raises(openai.RateLimitError):
        await generate_embedding("text", client=client)  # type: ignore[arg-type]

    assert endpoint.call_count == 3


async def test_does_not_retry_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    endpoint = _FlakyEmbeddingsEndpoint([_auth_error()])
    client = _FakeClient(endpoint)  # type: ignore[arg-type]

    with pytest.raises(openai.AuthenticationError):
        await generate_embedding("text", client=client)  # type: ignore[arg-type]

    assert endpoint.call_count == 1
    assert sleep.calls == []
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `./.venv/Scripts/python.exe -m pytest libs/llm/tests/test_embeddings.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'llm.embeddings'`)

- [ ] **Step 3: Реализовать `embeddings.py`**

`libs/llm/src/llm/embeddings.py`:

```python
"""Эмбеддинг товара для векторного поиска (FEATURES.md 4.1). Эталон V1
(add_product/update_product, central-admin/main.py): text-embedding-3-small,
комбинированный текст "Name: {name}; Description: {description}".
"""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from .client import (
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_ATTEMPTS,
    REQUEST_TIMEOUT_SECONDS,
    _RETRYABLE_EXCEPTIONS,
    _default_client,
)

EMBEDDING_MODEL = "text-embedding-3-small"


def product_embedding_input(name: str, description: str | None) -> str:
    return f"Name: {name}; Description: {description or ''}"


async def generate_embedding(
    text: str,
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> list[float]:
    """Тот же ретрай-принцип, что и _call_and_extract в client.py (3
    попытки, backoff 1с/2с, те же retryable-исключения) — отдельный
    небольшой цикл, не общий рефакторинг: не трогаем уже протестированный
    текстовый путь ради этой фичи.
    """
    active_client = client or _default_client()
    response = None
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            response = await active_client.embeddings.create(
                model=EMBEDDING_MODEL, input=text, timeout=timeout_seconds
            )
            break
        except _RETRYABLE_EXCEPTIONS:
            if attempt == RETRY_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    assert response is not None  # pragma: no cover
    return response.data[0].embedding
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `./.venv/Scripts/python.exe -m pytest libs/llm/tests/test_embeddings.py -v`
Expected: PASS (все тесты)

- [ ] **Step 5: Запустить весь `libs/llm` (регрессия существующего клиента)**

Run: `./.venv/Scripts/python.exe -m pytest libs/llm -v`
Expected: PASS (старые тесты `test_client.py`/`test_pricing.py`/`test_time_context.py`/`test_catalog_context.py` не задеты)

- [ ] **Step 6: ruff + mypy**

Run: `./.venv/Scripts/python.exe -m ruff check libs/llm && ./.venv/Scripts/python.exe -m mypy libs/llm/src`
Expected: без ошибок

- [ ] **Step 7: Commit**

```bash
git add libs/llm/src/llm/embeddings.py libs/llm/tests/test_embeddings.py
git commit -m "feat(llm): product embedding generation (FEATURES.md 4.1)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `libs/tools` — `ProductSearchTool` + фикс реестра

**Files:**
- Modify: `libs/tools/pyproject.toml` (добавить `llm`)
- Create: `libs/tools/src/tools/product_search.py`
- Modify: `libs/tools/src/tools/registry.py` (добавить `register()`, зарегистрировать тулзу)
- Modify: `libs/tools/tests/test_registry.py`
- Create: `libs/tools/tests/test_product_search.py`

**Interfaces:**
- Consumes: `db.products.find_product_by_exact_name`, `db.product_embeddings.find_product_by_embedding` (Task 1); `llm.embeddings.generate_embedding` (Task 2); `tools.base.{Tool, ToolContext}` (существуют, не меняются).
- Produces: `tools.product_search.ProductSearchTool` (реализует `Tool`,
  `name = "search_products"`); `tools.registry.register(tool: Tool) -> None`.
  Ничего из этого не используется в более поздних задачах этого плана —
  Task 4 только проверяет живьём.

- [ ] **Step 1: Добавить зависимость и установить**

`libs/tools/pyproject.toml` — в `dependencies`, после `"integrations",`:

```toml
    "llm",
```

Run: `./.venv/Scripts/python.exe -m pip install -e libs/tools`

- [ ] **Step 2: Написать тесты `ProductSearchTool` (падают — модуля нет)**

`libs/tools/tests/test_product_search.py`:

```python
"""ProductSearchTool (FEATURES.md 4.1/4.2): точное совпадение сначала,
векторный поиск — только если точного нет; контракт результата — JSON-
массив 0/1 записи {name, description, price} (эталон V1:
formatProductForTool). Требует Docker (testcontainers) — реальный
Postgres, генерация эмбеддинга подменена фейком (не настоящий OpenAI).
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
from db.models import Bot, Product, ProductEmbedding
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
    assert json.loads(result) == [
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
    assert json.loads(result)[0]["name"] == "Кроссовки Nike Air"


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
    assert json.loads(result)[0]["name"] == "Кеды Adidas"


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
    assert result == "[]"


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
    assert json.loads(result)[0]["price"] == "Не указана"
```

- [ ] **Step 3: Запустить тесты, убедиться что падают**

Run: `./.venv/Scripts/python.exe -m pytest libs/tools/tests/test_product_search.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'tools.product_search'`)

- [ ] **Step 4: Реализовать `ProductSearchTool`**

`libs/tools/src/tools/product_search.py`:

```python
"""Поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2). Точное
совпадение по имени сначала (эталон V1: node-bot3/whatsapp.js
vectorProductSearch), векторный поиск — только если точного нет.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from db.product_embeddings import find_product_by_embedding
from db.products import find_product_by_exact_name
from llm.embeddings import generate_embedding

from .base import ToolContext

_NOT_SPECIFIED_PRICE = "Не указана"


class ProductSearchTool:
    name = "search_products"
    description = "Ищет товар в каталоге бота по названию или похожему описанию."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Название или описание товара, которое ищет клиент",
            }
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        query = str(arguments.get("query", ""))
        async with ctx.session_factory() as session:
            product = await find_product_by_exact_name(session, ctx.bot.id, query)
            if product is None:
                embedding = await generate_embedding(query)
                product = await find_product_by_embedding(session, ctx.bot.id, embedding)

        if product is None:
            return "[]"

        price = str(product.price) if product.price is not None else _NOT_SPECIFIED_PRICE
        return json.dumps(
            [{"name": product.name, "description": product.description or "", "price": price}],
            ensure_ascii=False,
        )
```

- [ ] **Step 5: Запустить тесты тулзы, убедиться что проходят**

Run: `./.venv/Scripts/python.exe -m pytest libs/tools/tests/test_product_search.py -v`
Expected: PASS (все 5 тестов)

- [ ] **Step 6: Обновить реестр — `register()` + регистрация тулзы**

`libs/tools/src/tools/registry.py` — заменить файл целиком:

```python
"""Реестр доступных тулз (FEATURES.md 4.13). Первая настоящая тулза —
поиск товара (FEATURES.md 4.1/4.2).
"""

from __future__ import annotations

from .base import Tool
from .product_search import ProductSearchTool

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Ключ реестра — ВСЕГДА tool.name, никогда отдельная строка —
    расхождение между ними было находкой финального ревью инфраструктуры
    тулз (2026-09-05): если тулза зарегистрирована под другим ключом, чем
    её собственное имя, get_tool(tool.name) вернёт None и тулза станет
    недоступной, даже если включена через tool_bindings."""
    _REGISTRY[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tool_names() -> list[str]:
    return list(_REGISTRY)


register(ProductSearchTool())
```

- [ ] **Step 7: Обновить тесты реестра**

`libs/tools/tests/test_registry.py` — заменить целиком (реестр теперь
содержит `search_products` на уровне модуля с момента импорта, поэтому
тесты на добавление `"dummy"` проверяют `in`, а не точное равенство
списку из одного элемента — старая версия проверяла пустой реестр, этот
файл его больше не застаёт):

```python
"""Реестр тулз (FEATURES.md 4.13): get_tool/all_tool_names/register.
Первая настоящая тулза — search_products (FEATURES.md 4.1/4.2).
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from tools import registry
from tools.product_search import ProductSearchTool


class _DummyTool:
    name = "dummy"
    description = "тестовая тулза"
    parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, object], ctx: object) -> str:
        return "ok"


def test_get_tool_returns_none_for_unregistered_name() -> None:
    assert registry.get_tool("does_not_exist") is None


def test_all_tool_names_includes_search_products() -> None:
    """Первая настоящая тулза (FEATURES.md 4.1) — реестр больше не пуст."""
    assert "search_products" in registry.all_tool_names()


def test_production_registry_resolves_search_products_to_the_real_tool() -> None:
    tool = registry.get_tool("search_products")
    assert isinstance(tool, ProductSearchTool)
    assert tool.name == "search_products"


def test_register_stores_under_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # Подменяем сам объект словаря на его копию, чтобы не мутировать
    # реальный продакшн-реестр (уже содержит search_products) — monkeypatch
    # откатывает подмену после теста, без ручной очистки.
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    dummy = _DummyTool()
    registry.register(dummy)

    assert registry.get_tool("dummy") is dummy
    assert "dummy" in registry.all_tool_names()


def test_get_tool_and_all_tool_names_reflect_registered_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = _DummyTool()
    monkeypatch.setitem(registry._REGISTRY, "dummy", dummy)

    assert registry.get_tool("dummy") is dummy
    assert "dummy" in registry.all_tool_names()
```

- [ ] **Step 8: Запустить тесты реестра, убедиться что проходят**

Run: `./.venv/Scripts/python.exe -m pytest libs/tools -v`
Expected: PASS (все тесты пакета — `test_registry.py` и `test_product_search.py`)

- [ ] **Step 9: ruff + mypy**

Run: `./.venv/Scripts/python.exe -m ruff check libs/tools && ./.venv/Scripts/python.exe -m mypy libs/tools/src`
Expected: без ошибок

- [ ] **Step 10: Commit**

```bash
git add libs/tools/pyproject.toml libs/tools/src/tools/product_search.py libs/tools/src/tools/registry.py libs/tools/tests/test_registry.py libs/tools/tests/test_product_search.py
git commit -m "feat(tools): product search tool, first real registry entry (FEATURES.md 4.1/4.2)

Also adds registry.register() to keep the registry key equal to
tool.name always — a divergence risk flagged by the tool-calling
infra's final review.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Живой прогон

Без кода/коммита — только проверка. Ограничение среды (как во всех
предыдущих итерациях): `OPENAI_API_KEY` не настроен на машине разработки
— реальный вызов эмбеддинга через настоящий OpenAI недостижим.

- [ ] **Step 1: Полный тестовый прогон**

Run: `./.venv/Scripts/python.exe -m pytest -q`
Expected: весь набор зелёный, без регрессий в ранее сданных фичах.

- [ ] **Step 2: Поднять стек**

```bash
cp .env.example .env
docker compose -f compose/docker-compose.dev.yml up --build
```
(в фоне/отдельном терминале), дождаться healthy у всех контейнеров.

- [ ] **Step 3: Применить миграцию и проверить схему**

```bash
docker compose -f compose/docker-compose.dev.yml exec worker sh -c "cd /app && python -m alembic -c libs/db/alembic.ini upgrade head"
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "\d product_embeddings"
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```
Expected: колонки `product_id` (PK+FK), `embedding vector(1536)`; расширение `vector` в списке.

- [ ] **Step 4: Завести тестового бота, товар и включить тулзу**

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "INSERT INTO bots (name, enabled, system_prompt, timezone) VALUES ('search-check-bot', true, 'Ты — вежливый ассистент магазина.', 'Asia/Bishkek') RETURNING id;"
```

Записать выведенный `id` как `BOT_ID`, затем:

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "INSERT INTO products (bot_id, name, price, description) VALUES ('<BOT_ID>', 'Кроссовки Nike Air', 5000.00, 'Беговые, размеры 38-45');"
curl -s -X POST http://localhost:8000/bots/<BOT_ID>/tools -H "Content-Type: application/json" -d '{"tool_name": "search_products"}'
```
Expected: `curl` → `201`, `{"tool_name": "search_products", "config": {}}` —
подтверждает, что реестр больше не пуст (в отличие от прошлой итерации,
где любой `POST` на неизвестное имя давал 400).

- [ ] **Step 5: Отправить сообщение, проверить лог worker**

```bash
TS=$(date +%s%3N)
docker compose -f compose/docker-compose.dev.yml exec redis redis-cli XADD wa:in '*' payload "{\"type\":\"inbound.text\",\"bot_id\":\"<BOT_ID>\",\"wa_msg_id\":\"search-check-1\",\"chat_id\":\"996700000003@s.whatsapp.net\",\"sender_wa_id\":\"996700000003\",\"from_me\":false,\"text\":\"Что у вас есть?\",\"ts\":$TS}"
docker compose -f compose/docker-compose.dev.yml logs worker --tail 30
```
Expected: traceback падает на отсутствующий `OPENAI_API_KEY` **внутри
цикла тулз** (`run_tool_loop` → `complete_with_tools_fn`, НЕ быстрый путь
`complete_fn` как в предыдущих итерациях) — само по себе подтверждает,
что тулза была предложена модели (список тулз для этого бота не пуст).
`wa:out` пуст, зависших `lock:*` нет (та же деградация, что и раньше).

- [ ] **Step 6: Остановить стек**

```bash
docker compose -f compose/docker-compose.dev.yml down
rm -f .env
```

- [ ] **Step 7: Обновить память проекта**

Дописать в `wave2-tools-infra-progress.md` (или создать `wave2-product-search-progress.md`)
факт сдачи 4.1/4.2, зафиксированное расхождение с FEATURES.md
(точное совпадение первым, не ILIKE-fallback после вектора), находку
про `register()`, и что дальше — 4.3–4.6 (карточки товара).

---

## Самопроверка плана (writing-plans skill)

- **Покрытие спеки**: разделение по пакетам (db/llm/tools) → задачи 1-3;
  контракт результата тулзы, точный порядок поиска, порог 0.4, имя
  `search_products`, фикс реестра — все явно в Task 3; живая проверка
  включения тулзы через уже существующий API — Task 4 Step 4 явно
  проверяет, что реестр был пуст ДО этого плана (400 в прошлой итерации)
  и не пуст ПОСЛЕ (201 в этой).
- **Плейсхолдеры**: не найдено — каждый шаг содержит готовый код или
  точную команду.
- **Согласованность типов**: `find_product_by_exact_name`/
  `find_product_by_embedding`/`upsert_embedding`/`generate_embedding`
  используются в Task 3 с теми же именами и сигнатурами, что определены
  в Task 1/2. `ProductSearchTool.execute()` вызывает `generate_embedding(query)`
  без `client=`/`timeout_seconds=` — используются дефолты, определённые
  в Task 2 (`client=None` → `_default_client()`, `timeout_seconds=REQUEST_TIMEOUT_SECONDS`) —
  согласовано с тем, как `_reply()` уже вызывает `complete()`/
  `complete_with_tools()` без явного `client=` в консьюмере.
