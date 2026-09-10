# Товары: CRUD без фото (Волна 3, четвёртый под-проект) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кабинет умеет создавать, редактировать, просматривать и удалять
товары (без фото — это отдельный следующий суб-проект), с автопересчётом
эмбеддинга для векторного поиска (4.1) при изменении имени/описания.

**Architecture:** Схема БД не меняется (`products`/`product_embeddings`/
`product_images` уже существуют). Новый слой записи в
`libs/db/src/db/products.py` (get/create/update/delete, тот же "None = не
трогать поле" принцип, что и `db.bots.update_bot`). Новый роутер
`services/api/src/api/routers/products.py`: синхронная попытка эмбеддинга
внутри HTTP-запроса при create всегда и при update только если
name/description реально изменились; при сбое — товар всё равно
сохраняется, ставится идемпотентная Celery-задача-подстраховка
(`recompute_product_embedding`). admin-web получает три новых страницы
(`/bots/[id]/products`, `/new`, `/[productId]/edit`) на общем клиентском
`ProductForm`.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 async (api, libs/db)
· Celery (services/celery, задача-подстраховка) · OpenAI
`text-embedding-3-small` (libs/llm) · Next.js 15 / TypeScript / React 19
(admin-web) · vitest + React Testing Library (admin-web тесты) · pytest +
testcontainers (api/db/celery тесты).

**Spec:** [docs/superpowers/specs/2026-09-10-product-crud-design.md](../specs/2026-09-10-product-crud-design.md)

## Global Constraints

- Обязательно только `name` (непустая строка после `.strip()`). Фото НЕ
  обязательно в этом суб-проекте — требование "название И фото обязательны"
  сдвинуто на второй суб-проект (загрузка фото), товар без единой
  фотографии — штатное, временное состояние, не баг.
- `price`/`sku`/`description` нельзя явно сбросить обратно в NULL через
  `PATCH` — тот же принятый паттерн, что и `image_prompt`/`pdf_prompt` в
  `bots.py` (`None` неотличим от "поле не передано"). Не чиним.
- SKU свободен, без проверки уникальности даже в рамках одного бота —
  возможно, поле вообще уйдёт из схемы позже (решение пользователя).
- `display_custom` — "всё или ничего" (уже реализовано в
  `libs/tools/src/tools/product_search.py`, не меняем логику чтения);
  запись просто сохраняет объект как есть, без валидации состава ключей.
- Эмбеддинг строится ТОЛЬКО из `name`+`description`
  (`llm.embeddings.product_embedding_input`) — `price`/`sku`/`display_custom`
  не меняют "смысл" товара, эмбеддинг от них не зависит.
- Эмбеддинг считается синхронно при `create` всегда; при `update` — только
  если `name` или `description` реально изменились (сравнение старого и
  нового значения). При сбое синхронной попытки — товар всё равно
  сохраняется, ошибка логируется, ставится идемпотентная Celery-задача
  `recompute_product_embedding(product_id)`.
- **Этот дизайн эмбеддинга помечен пользователем как вероятный кандидат на
  пересмотр** — см. memory `product-embedding-retry-design`. Не удивляться
  будущему запросу переделать именно этот кусок.
- Архивирование/мягкое удаление — вне скоупа: `DELETE` — обычный SQL
  DELETE, `ON DELETE CASCADE` на `product_embeddings.product_id` и
  `product_images.product_id` подчищает связанные строки автоматически.
- Все read/write/delete-операции по одному товару скоупятся ОДНОВРЕМЕННО
  по `bot_id` И `product_id` — товар чужого бота не должен быть виден даже
  как "существует, но 403", а просто не находится (404).
- `POST` на несуществующего бота должен возвращать 404, а не 500 от
  нарушенного FK — проверка существования бота ДО insert (тот же класс
  бага, что чинился в `prompt_versions`).
- Без Tailwind, обычный CSS (ADR-009), тот же стиль, что и на остальных
  экранах кабинета — `table`/`th`/`td`/`form input`/`textarea` стили уже
  есть в `globals.css`, новых стилей не требуется.
- Технический долг Волны 3 (QR-экран, настройки): dev-сервер Next.js в
  проде, отсутствие `.dockerignore` у admin-web — не трогаем.

---

### Task 1: `libs/db/src/db/products.py` — write-функции (get/create/update/delete)

**Files:**
- Modify: `libs/db/src/db/products.py`
- Test: `libs/db/tests/test_products.py`

**Interfaces:**
- Consumes: существующий `Product` (`libs/db/src/db/models.py`).
- Produces:
  - `db.products.get_product(session, bot_id, product_id) -> Product | None`
  - `db.products.create_product(session, bot_id, *, name, price=None, sku=None, description=None, display_custom=None) -> Product`
  - `db.products.update_product(session, bot_id, product_id, *, name=None, price=None, sku=None, description=None, display_custom=None) -> Product | None`
  - `db.products.delete_product(session, bot_id, product_id) -> bool`

- [ ] **Step 1: Написать падающий тест**

`libs/db/tests/test_products.py` — заменить блок импорта:

```python
from db.products import find_product_by_exact_name, list_products
```

на:

```python
from db.products import (
    create_product,
    delete_product,
    find_product_by_exact_name,
    get_product,
    list_products,
    update_product,
)
```

и добавить `from decimal import Decimal` уже есть в файле (используется
выше) — новых импортов модулей не требуется, кроме перечисленного выше.

В конец файла добавить:

```python
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
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest libs/db/tests/test_products.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_product'` (и
остальные новые функции). Если Docker недоступен — все тесты `SKIPPED`,
ожидаемо в этом окружении.

- [ ] **Step 3: Реализовать**

`libs/db/src/db/products.py` — заменить файл целиком:

```python
"""Каталог товаров бота: чтение для контекста LLM (FEATURES.md 3.4) и
CRUD (FEATURES.md 6.8, Волна 3, первая половина — без фото).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product

DEFAULT_CATALOG_LIMIT = 200


async def list_products(
    session: AsyncSession, bot_id: uuid.UUID, *, limit: int = DEFAULT_CATALOG_LIMIT
) -> list[Product]:
    stmt = (
        select(Product)
        .where(Product.bot_id == bot_id)
        .order_by(Product.name)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


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


async def get_product(
    session: AsyncSession, bot_id: uuid.UUID, product_id: uuid.UUID
) -> Product | None:
    """Скоуп по bot_id И product_id вместе — товар чужого бота не должен
    быть виден даже как "существует, но 403", а просто не находится (404)."""
    stmt = select(Product).where(Product.bot_id == bot_id, Product.id == product_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_product(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    name: str,
    price: Decimal | None = None,
    sku: str | None = None,
    description: str | None = None,
    display_custom: dict[str, Any] | None = None,
) -> Product:
    product = Product(
        bot_id=bot_id,
        name=name,
        price=price,
        sku=sku,
        description=description,
        display_custom=display_custom if display_custom is not None else {},
    )
    session.add(product)
    await session.flush()
    return product


async def update_product(
    session: AsyncSession,
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    name: str | None = None,
    price: Decimal | None = None,
    sku: str | None = None,
    description: str | None = None,
    display_custom: dict[str, Any] | None = None,
) -> Product | None:
    """Частичное обновление: None-параметр = не трогать это поле (тот же
    принцип, что и db.bots.update_bot) — значит explicit-сброс price/sku/
    description обратно в NULL этим путём недостижим, сознательно принятое
    ограничение (см. docs/superpowers/specs/2026-09-10-product-crud-design.md,
    "Явно отложено")."""
    product = await get_product(session, bot_id, product_id)
    if product is None:
        return None
    if name is not None:
        product.name = name
    if price is not None:
        product.price = price
    if sku is not None:
        product.sku = sku
    if description is not None:
        product.description = description
    if display_custom is not None:
        product.display_custom = display_custom
    await session.flush()
    return product


async def delete_product(session: AsyncSession, bot_id: uuid.UUID, product_id: uuid.UUID) -> bool:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        return False
    await session.delete(product)
    await session.flush()
    return True
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `pytest libs/db/tests/test_products.py -v`
Expected: PASS (все тесты, включая уже существовавшие `list_products`/`find_product_by_exact_name`)

- [ ] **Step 5: Коммит**

```bash
git add libs/db/src/db/products.py libs/db/tests/test_products.py
git commit -m "feat(db): add product write functions (get/create/update/delete)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Celery-задача `recompute_product_embedding` + инфраструктура зависимостей `services/celery`

**Files:**
- Modify: `libs/scheduling/src/scheduling/task_names.py`
- Create: `services/celery/src/tasks/products.py`
- Modify: `services/celery/src/tasks/__init__.py`
- Modify: `services/celery/pyproject.toml`
- Modify: `services/celery/Dockerfile`
- Modify: `compose/docker-compose.dev.yml` (блок `celery`)
- Test: `services/celery/tests/test_products.py`

**Interfaces:**
- Consumes: `db.models.Product`, `db.product_embeddings.upsert_embedding`,
  `llm.embeddings.generate_embedding`/`product_embedding_input`,
  `scheduling.celery_app.celery_app`.
- Produces: `scheduling.task_names.RECOMPUTE_PRODUCT_EMBEDDING = "tasks.products.recompute_embedding"`;
  Celery-задача `recompute_product_embedding(product_id: str) -> None`
  (регистрирована под этим именем); внутренняя `tasks.products._recompute_async(session_factory, product_id: str) -> None`
  — тестируемое async-тело, без `asyncio.run`.

**Важно (найдено исследованием):** `services/celery` сейчас НЕ ставит
`libs/llm` (ни в `pyproject.toml`, ни в `Dockerfile`) — до этой задачи
Celery-сервису LLM не требовался (только `followup` — текст из
`bots.settings`). Без этого шага задача упадёт с `ModuleNotFoundError` в
контейнере (в общем dev-venv на хосте она бы случайно заработала — Makefile
ставит все `libs/*` в один venv, — но это не то, что реально катится в
Docker-образ celery).

- [ ] **Step 1: Написать падающий тест**

`services/celery/tests/test_products.py` (новый файл):

```python
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
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest services/celery/tests/test_products.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tasks.products'`.
Если Docker недоступен — все тесты `SKIPPED`, ожидаемо.

- [ ] **Step 3: Реализовать**

`libs/scheduling/src/scheduling/task_names.py` — добавить строку в конец
файла:

```python
RECOMPUTE_PRODUCT_EMBEDDING = "tasks.products.recompute_embedding"
```

`services/celery/src/tasks/products.py` (новый файл):

```python
"""FEATURES.md 4.1/6.8: подстраховка на случай, если синхронная попытка
эмбеддинга в services/api (create/update товара) не удалась. Идемпотентна —
читает АКТУАЛЬНЫЕ name/description из БД на момент срабатывания (не то, что
было в HTTP-запросе, поставившем задачу — на случай что товар успели
отредактировать ещё раз), апсертит вектор.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from db.engine import make_engine, make_session_factory
from db.models import Product
from db.product_embeddings import upsert_embedding
from llm.embeddings import generate_embedding, product_embedding_input
from scheduling.celery_app import celery_app
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger("tasks.products")


async def _recompute_async(
    session_factory: async_sessionmaker[AsyncSession], product_id: str
) -> None:
    async with session_factory() as session:
        product = await session.get(Product, uuid.UUID(product_id))
        if product is None:
            logger.info("embedding recompute skipped: product deleted", product_id=product_id)
            return
        text = product_embedding_input(product.name, product.description)
        embedding = await generate_embedding(text)
        await upsert_embedding(session, product.id, embedding)
        await session.commit()
        logger.info("embedding recomputed", product_id=product_id)


async def _run(product_id: str) -> None:
    engine = make_engine()
    session_factory = make_session_factory(engine)
    try:
        await _recompute_async(session_factory, product_id)
    finally:
        await engine.dispose()


@celery_app.task(name=RECOMPUTE_PRODUCT_EMBEDDING)  # type: ignore[untyped-decorator]  # celery не публикует py.typed — декоратор неизбежно нетипизирован
def recompute_product_embedding(product_id: str) -> None:
    asyncio.run(_run(product_id))
```

`services/celery/src/tasks/__init__.py` — полностью:

```python
"""Точка входа Celery-воркера: `celery -A tasks worker`. Экспортирует
`celery` (конвенция — Celery -A ищет этот атрибут в пакете) из общего
libs/scheduling и импортирует модули задач, чтобы @celery_app.task
зарегистрировался при старте воркера.
"""

from __future__ import annotations

from scheduling.celery_app import celery_app as celery  # noqa: F401

from . import followup, products  # noqa: F401
```

`services/celery/pyproject.toml` — добавить `"llm"` в `dependencies`:

```toml
dependencies = [
    "core",
    "db",
    "llm",
    "scheduling",
    "structlog>=24.4",
]
```

`services/celery/Dockerfile` — добавить `-e /app/libs/llm` в строку
`RUN pip install`:

```dockerfile
RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/llm -e /app/libs/scheduling -e /app/services/celery
```

`compose/docker-compose.dev.yml` — блок `celery` (сейчас строки 85-99),
добавить `OPENAI_API_KEY` в `environment`:

```yaml
  celery:
    build:
      context: ..
      dockerfile: services/celery/Dockerfile
    environment:
      DATABASE_URL: postgres://platform:platform@postgres:5432/platform
      REDIS_URL: redis://redis:6379/0
      # Секреты — из .env на хосте (ADR-007), не хардкодим сюда.
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    volumes:
      - ../services/celery/src:/app/services/celery/src
      - ../libs:/app/libs
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `pytest services/celery/tests/test_products.py services/celery/tests/test_followup.py -v`
Expected: PASS (новый файл + регрессия follow-up — общий `tasks/__init__.py`
теперь импортирует два модуля задач вместо одного)

Run: `pip install -e libs/llm -e services/celery` (если venv уже
существует, но `llm` в нём ещё не связан с celery-пакетом — на практике
он уже стоит в общем venv через Makefile, этот шаг документирует
изменение для чистой установки)

- [ ] **Step 5: Коммит**

```bash
git add libs/scheduling/src/scheduling/task_names.py services/celery/src/tasks/products.py services/celery/src/tasks/__init__.py services/celery/pyproject.toml services/celery/Dockerfile compose/docker-compose.dev.yml services/celery/tests/test_products.py
git commit -m "feat(celery): add recompute_product_embedding fallback task

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: API — схемы, роутер `/bots/{bot_id}/products`, инфраструктура зависимостей `services/api`

**Files:**
- Create: `services/api/src/api/schemas/products.py`
- Create: `services/api/src/api/routers/products.py`
- Modify: `services/api/src/api/main.py`
- Modify: `services/api/pyproject.toml`
- Modify: `services/api/Dockerfile`
- Modify: `compose/docker-compose.dev.yml` (блок `api`)
- Test: `services/api/tests/test_products.py`

**Interfaces:**
- Consumes: `db.bots.get_bot`, `db.products.{list_products,get_product,create_product,update_product,delete_product}`
  (Task 1), `db.product_embeddings.upsert_embedding`,
  `llm.embeddings.{generate_embedding,product_embedding_input}`,
  `scheduling.celery_app.celery_app`, `scheduling.task_names.RECOMPUTE_PRODUCT_EMBEDDING`
  (Task 2), существующий `SessionDep` (`services/api/src/api/db.py`).
- Produces: роуты `GET/POST /bots/{bot_id}/products`,
  `GET/PATCH/DELETE /bots/{bot_id}/products/{product_id}`; схемы
  `ProductOut`/`ProductCreate`/`ProductPatch`
  (`services/api/src/api/schemas/products.py`).

**Важно (найдено исследованием):** `services/api` сейчас НЕ зависит от
`libs/scheduling` (ни в `pyproject.toml`, ни в `Dockerfile`) — до этой
задачи api никогда не ставил Celery-задачи (это всегда делал
`services/worker`). `libs/llm` уже стоит в `Dockerfile` api (используется
косвенно через `tools`), но не объявлен в `pyproject.toml` — заодно
исправляем. Без этого шага роутер упадёт на импорте `scheduling.celery_app`
в собранном Docker-образе api.

- [ ] **Step 1: Написать падающий тест**

Создать `services/api/tests/test_products.py`:

```python
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
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest services/api/tests/test_products.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routers.products'`.
Если Docker недоступен — все тесты `SKIPPED`, ожидаемо.

- [ ] **Step 3: Реализовать**

`services/api/src/api/schemas/products.py` (новый файл):

```python
"""Pydantic v2 схемы товара для api (FEATURES.md 6.8, CRUD без фото)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: Decimal | None
    sku: str | None
    description: str | None
    display_custom: dict[str, Any]
    created_at: datetime


class ProductCreate(BaseModel):
    name: str
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict[str, Any] | None = None


class ProductPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные
    (exclude_unset). None для price/sku/description неотличим от "поле не
    передано" на уровне db.products.update_product — тот же принятый
    паттерн, что и BotPatch.image_prompt/pdf_prompt."""

    name: str | None = None
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict[str, Any] | None = None
```

`services/api/src/api/routers/products.py` (новый файл):

```python
"""GET/POST/PATCH/DELETE /bots/{bot_id}/products (FEATURES.md 6.8, Волна 3,
первая половина — CRUD без фото). Обязательно только name; price/sku/
description опциональны, display_custom — "всё или ничего" (см.
db.product_search._resolve_display_config, не меняется).

Эмбеддинг (FEATURES.md 4.1) строится только из name+description
(llm.embeddings.product_embedding_input) — синхронная попытка в этом же
HTTP-запросе (generate_embedding уже со своим ретраем); если и она не
удалась — товар всё равно сохраняется, ставится идемпотентная Celery-
задача-подстраховка (services/celery/src/tasks/products.py). См.
docs/superpowers/specs/2026-09-10-product-crud-design.md — этот дизайн
пользователь пометил как вероятного кандидата на пересмотр.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from db.bots import get_bot
from db.models import Product
from db.product_embeddings import upsert_embedding
from db.products import create_product, delete_product, get_product, list_products, update_product
from fastapi import APIRouter, HTTPException
from llm.embeddings import generate_embedding, product_embedding_input
from scheduling.celery_app import celery_app
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionDep
from ..schemas.products import ProductCreate, ProductOut, ProductPatch

router = APIRouter(prefix="/bots", tags=["products"])
logger = structlog.get_logger("api.products")

PRODUCT_EMBEDDING_SCHEDULE_TIMEOUT_SECONDS = 5.0


async def _recompute_embedding(session: AsyncSession, product: Product) -> None:
    """Синхронная попытка (с уже встроенным в generate_embedding ретраем);
    при сбое — не роняем запрос, ставим Celery-подстраховку."""
    text = product_embedding_input(product.name, product.description)
    try:
        embedding = await generate_embedding(text)
    except Exception:
        logger.warning(
            "embedding generation failed, scheduling retry",
            product_id=str(product.id),
            exc_info=True,
        )
        await _schedule_embedding_retry(product.id)
        return
    await upsert_embedding(session, product.id, embedding)
    await session.commit()


async def _schedule_embedding_retry(product_id: uuid.UUID) -> None:
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                celery_app.send_task,
                RECOMPUTE_PRODUCT_EMBEDDING,
                args=[str(product_id)],
            ),
            timeout=PRODUCT_EMBEDDING_SCHEDULE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "failed to schedule embedding recompute", product_id=str(product_id), exc_info=True
        )


@router.get("/{bot_id}/products", response_model=list[ProductOut])
async def list_products_route(bot_id: uuid.UUID, session: SessionDep) -> list[ProductOut]:
    products = await list_products(session, bot_id)
    return [ProductOut.model_validate(p) for p in products]


@router.post("/{bot_id}/products", response_model=ProductOut, status_code=201)
async def create_product_route(
    bot_id: uuid.UUID, body: ProductCreate, session: SessionDep
) -> ProductOut:
    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name must not be empty")

    product = await create_product(
        session,
        bot_id,
        name=name,
        price=body.price,
        sku=body.sku,
        description=body.description,
        display_custom=body.display_custom,
    )
    await session.commit()
    await _recompute_embedding(session, product)
    return ProductOut.model_validate(product)


@router.get("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def get_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep
) -> ProductOut:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return ProductOut.model_validate(product)


@router.patch("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def patch_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, patch: ProductPatch, session: SessionDep
) -> ProductOut:
    data = patch.model_dump(exclude_unset=True)
    if "name" in data and not (data["name"] or "").strip():
        raise HTTPException(status_code=422, detail="name must not be empty")

    before = await get_product(session, bot_id, product_id)
    if before is None:
        raise HTTPException(status_code=404, detail="product not found")
    old_name, old_description = before.name, before.description

    new_name = data["name"].strip() if "name" in data else None
    product = await update_product(
        session,
        bot_id,
        product_id,
        name=new_name,
        price=data.get("price"),
        sku=data.get("sku"),
        description=data.get("description"),
        display_custom=data.get("display_custom"),
    )
    assert product is not None  # проверено выше через before
    await session.commit()

    if product.name != old_name or product.description != old_description:
        await _recompute_embedding(session, product)

    return ProductOut.model_validate(product)


@router.delete("/{bot_id}/products/{product_id}", status_code=204)
async def delete_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep
) -> None:
    deleted = await delete_product(session, bot_id, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="product not found")
    await session.commit()
```

`services/api/src/api/main.py` — заменить:

```python
from .routers import bots
```

на:

```python
from .routers import bots, products
```

и добавить строку сразу после `app.include_router(bots.router)`:

```python
app.include_router(products.router)
```

`services/api/pyproject.toml` — заменить блок `dependencies`:

```toml
dependencies = [
    "core",
    "db",
    "integrations",
    "llm",
    "scheduling",
    "tools",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "redis>=5.0",
]
```

`services/api/Dockerfile` — добавить `-e /app/libs/scheduling`:

```dockerfile
RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/integrations -e /app/libs/llm -e /app/libs/scheduling -e /app/libs/tools -e /app/services/api
```

`compose/docker-compose.dev.yml` — блок `api` (сейчас строки 101-125),
добавить `OPENAI_API_KEY` в `environment`:

```yaml
  api:
    build:
      context: ..
      dockerfile: services/api/Dockerfile
    environment:
      DATABASE_URL: postgres://platform:platform@postgres:5432/platform
      REDIS_URL: redis://redis:6379/0
      GATEWAY_URL: http://gateway:8080
      ADMIN_WEB_ORIGIN: http://localhost:3000
      # Секреты — из .env на хосте (ADR-007), не хардкодим сюда.
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    ports:
      - "8000:8000"
    volumes:
      - ../services/api/src:/app/services/api/src
      - ../libs:/app/libs
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      gateway:
        condition: service_started
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      timeout: 5s
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `pip install -e libs/scheduling -e services/api` (venv уже видит
`scheduling`/`llm` через Makefile-установку, но если `services/api` ставился
раньше без них в редакции этого шага — переустановить egg-info)

Run: `pytest services/api/tests/test_products.py services/api/tests/test_bots.py -v`
Expected: PASS (новый файл + регрессия — `main.py` теперь подключает два
роутера)

- [ ] **Step 5: Коммит**

```bash
git add services/api/src/api/schemas/products.py services/api/src/api/routers/products.py services/api/src/api/main.py services/api/pyproject.toml services/api/Dockerfile compose/docker-compose.dev.yml services/api/tests/test_products.py
git commit -m "feat(api): CRUD /bots/{bot_id}/products with embedding recompute

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `lib/api.ts` — тип `Product` и функции fetch/create/update/delete

**Files:**
- Modify: `services/admin-web/lib/api.ts`
- Test: `services/admin-web/lib/api.test.ts`

**Interfaces:**
- Consumes: существующий `normalizeBaseUrl` (внутренний).
- Produces:
  - `interface Product { id: string; name: string; price: string | null; sku: string | null; description: string | null; display_custom: Record<string, boolean>; created_at: string }`
  - `interface ProductInput { name: string; price?: number | null; sku?: string | null; description?: string | null; display_custom?: Record<string, boolean> }`
  - `fetchProducts(baseUrl: string, botId: string): Promise<Product[]>`
  - `fetchProduct(baseUrl: string, botId: string, productId: string): Promise<Product | null>`
  - `createProduct(baseUrl: string, botId: string, input: ProductInput): Promise<Product>`
  - `updateProduct(baseUrl: string, botId: string, productId: string, input: ProductInput): Promise<Product>`
  - `deleteProduct(baseUrl: string, botId: string, productId: string): Promise<void>`

**Примечание:** бэкенд сериализует `Decimal` (Pydantic v2) как JSON-строку
(`"5000.00"`, не число) — `Product.price` типизирован `string | null`, а не
`number | null`. При отправке (`ProductInput.price`) это, наоборот,
`number | null` — FastAPI/Pydantic сам коэрсит JSON-число во входной
`Decimal`, отправлять строку не нужно.

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/lib/api.test.ts` — заменить первую строку импорта:

```ts
import { fetchBot, fetchBots, fetchPromptVersions, logoutBot, patchBotPrompt, qrImageUrl } from "@/lib/api";
```

на:

```ts
import {
  createProduct,
  deleteProduct,
  fetchBot,
  fetchBots,
  fetchProduct,
  fetchProducts,
  fetchPromptVersions,
  logoutBot,
  patchBotPrompt,
  qrImageUrl,
  updateProduct,
} from "@/lib/api";
```

В конец файла добавить:

```ts
describe("fetchProducts", () => {
  it("returns the parsed product list", async () => {
    const products = [
      {
        id: "p1",
        name: "Товар",
        price: "100.00",
        sku: null,
        description: null,
        display_custom: {},
        created_at: "2026-09-10T10:00:00Z",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => products });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchProducts("http://api", "1");

    expect(result).toEqual(products);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products", { cache: "no-store" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(fetchProducts("http://api", "1")).rejects.toThrow();
  });
});

describe("fetchProduct", () => {
  it("returns null on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const result = await fetchProduct("http://api", "1", "p1");
    expect(result).toBeNull();
  });

  it("returns the product when found", async () => {
    const product = {
      id: "p1",
      name: "Товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      created_at: "2026-09-10T10:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => product }));
    const result = await fetchProduct("http://api", "1", "p1");
    expect(result).toEqual(product);
  });
});

describe("createProduct", () => {
  it("POSTs the input and returns the created product", async () => {
    const created = {
      id: "p1",
      name: "Товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      created_at: "2026-09-10T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => created });
    vi.stubGlobal("fetch", fetchMock);

    const result = await createProduct("http://api", "1", { name: "Товар" });

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Товар" }),
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    await expect(createProduct("http://api", "1", { name: "x" })).rejects.toThrow();
  });
});

describe("updateProduct", () => {
  it("PATCHes the input and returns the updated product", async () => {
    const updated = {
      id: "p1",
      name: "Новое имя",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      created_at: "2026-09-10T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => updated });
    vi.stubGlobal("fetch", fetchMock);

    const result = await updateProduct("http://api", "1", "p1", { name: "Новое имя" });

    expect(result).toEqual(updated);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products/p1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Новое имя" }),
    });
  });
});

describe("deleteProduct", () => {
  it("DELETEs the product", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await deleteProduct("http://api", "1", "p1");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products/p1", { method: "DELETE" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await expect(deleteProduct("http://api", "1", "p1")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- lib/api.test.ts`
Expected: FAIL — `"@/lib/api" does not provide an export named 'fetchProducts'`

- [ ] **Step 3: Реализовать**

`services/admin-web/lib/api.ts` — добавить в конец файла:

```ts
// Decimal (Pydantic v2) сериализуется бэкендом как JSON-строка ("5000.00"),
// не число — см. services/api/src/api/schemas/products.py.
export interface Product {
  id: string;
  name: string;
  price: string | null;
  sku: string | null;
  description: string | null;
  display_custom: Record<string, boolean>;
  created_at: string;
}

export interface ProductInput {
  name: string;
  price?: number | null;
  sku?: string | null;
  description?: string | null;
  display_custom?: Record<string, boolean>;
}

export async function fetchProducts(baseUrl: string, botId: string): Promise<Product[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${botId}/products failed: ${res.status}`);
  }
  return (await res.json()) as Product[];
}

export async function fetchProduct(
  baseUrl: string,
  botId: string,
  productId: string,
): Promise<Product | null> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products/${productId}`, { cache: "no-store" });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GET /bots/${botId}/products/${productId} failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}

export async function createProduct(
  baseUrl: string,
  botId: string,
  input: ProductInput,
): Promise<Product> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/products failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}

export async function updateProduct(
  baseUrl: string,
  botId: string,
  productId: string,
  input: ProductInput,
): Promise<Product> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products/${productId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${botId}/products/${productId} failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}

export async function deleteProduct(
  baseUrl: string,
  botId: string,
  productId: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products/${productId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`DELETE /bots/${botId}/products/${productId} failed: ${res.status}`);
  }
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- lib/api.test.ts`
Expected: PASS

Run: `npx tsc --noEmit`
Expected: без ошибок

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/lib/api.ts services/admin-web/lib/api.test.ts
git commit -m "feat(admin-web): Product type and fetch/create/update/delete helpers

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `ProductForm` — создание и редактирование одним компонентом

**Files:**
- Create: `services/admin-web/components/ProductForm.tsx`
- Test: `services/admin-web/components/ProductForm.test.tsx`

**Interfaces:**
- Consumes: `Product`, `ProductInput`, `createProduct`, `updateProduct` из `@/lib/api` (Task 4).
- Produces: `ProductForm({ botId: string; apiBaseUrl: string; product?: Product })` — client component; без `product` — режим создания, с `product` — режим редактирования.

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/ProductForm.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProductForm } from "@/components/ProductForm";
import * as api from "@/lib/api";
import type { Product } from "@/lib/api";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createProduct: vi.fn(),
    updateProduct: vi.fn(),
  };
});

const existingProduct: Product = {
  id: "p1",
  name: "Старое имя",
  price: "100.00",
  sku: "SKU-1",
  description: "Старое описание",
  display_custom: {},
  created_at: "2026-09-10T10:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("renders an empty form in create mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  expect(screen.getByLabelText(/название/i)).toHaveValue("");
});

it("renders existing values in edit mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByLabelText(/название/i)).toHaveValue("Старое имя");
  expect(screen.getByLabelText(/цена/i)).toHaveValue(100);
  expect(screen.getByLabelText(/артикул/i)).toHaveValue("SKU-1");
  expect(screen.getByLabelText(/описание/i)).toHaveValue("Старое описание");
});

it("rejects an empty name without calling the api", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(api.createProduct).not.toHaveBeenCalled();
});

it("creates a product with trimmed optional fields", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Новый товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith("http://api", "1", {
      name: "Новый товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
    });
  });
  expect(pushMock).toHaveBeenCalledWith("/bots/1/products");
});

it("updates an existing product", async () => {
  vi.mocked(api.updateProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);

  fireEvent.change(screen.getByLabelText(/цена/i), { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.updateProduct).toHaveBeenCalledWith("http://api", "1", "p1", {
      name: "Старое имя",
      price: 200,
      sku: "SKU-1",
      description: "Старое описание",
      display_custom: {},
    });
  });
});

it("sends display_custom only when the override checkbox is on", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByLabelText(/переопределить вывод/i));
  fireEvent.click(screen.getByLabelText(/показывать цену/i));
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith(
      "http://api",
      "1",
      expect.objectContaining({
        display_custom: { show_name: true, show_description: true, show_price: false },
      }),
    );
  });
});

it("shows an error when saving fails", async () => {
  vi.mocked(api.createProduct).mockRejectedValue(new Error("save failed"));
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/ProductForm.test.tsx`
Expected: FAIL — `Cannot find module '@/components/ProductForm'`

- [ ] **Step 3: Реализовать**

`services/admin-web/components/ProductForm.tsx`:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createProduct, updateProduct, type Product, type ProductInput } from "@/lib/api";

interface ProductFormProps {
  botId: string;
  apiBaseUrl: string;
  /** Если задан — режим редактирования, иначе — создание нового товара. */
  product?: Product;
}

interface FormState {
  name: string;
  price: string;
  sku: string;
  description: string;
  displayOverride: boolean;
  showName: boolean;
  showDescription: boolean;
  showPrice: boolean;
}

function initialState(product: Product | undefined): FormState {
  const hasOverride = !!product && Object.keys(product.display_custom).length > 0;
  return {
    name: product?.name ?? "",
    price: product?.price ?? "",
    sku: product?.sku ?? "",
    description: product?.description ?? "",
    displayOverride: hasOverride,
    showName: product?.display_custom.show_name ?? true,
    showDescription: product?.display_custom.show_description ?? true,
    showPrice: product?.display_custom.show_price ?? true,
  };
}

function toInput(state: FormState): ProductInput {
  return {
    name: state.name.trim(),
    price: state.price.trim() === "" ? null : Number(state.price),
    sku: state.sku.trim() === "" ? null : state.sku.trim(),
    description: state.description.trim() === "" ? null : state.description.trim(),
    display_custom: state.displayOverride
      ? {
          show_name: state.showName,
          show_description: state.showDescription,
          show_price: state.showPrice,
        }
      : {},
  };
}

export function ProductForm({ botId, apiBaseUrl, product }: ProductFormProps) {
  const router = useRouter();
  const [state, setState] = useState<FormState>(() => initialState(product));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state.name.trim() === "") {
      setError("Название обязательно");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const input = toInput(state);
      if (product) {
        await updateProduct(apiBaseUrl, botId, product.id, input);
      } else {
        await createProduct(apiBaseUrl, botId, input);
      }
      router.push(`/bots/${botId}/products`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    // noValidate — та же причина, что и в BotSettingsForm: нативная
    // HTML5-валидация (required/min) тихо блокирует submit ДО нашей проверки.
    <form noValidate onSubmit={(e) => void handleSubmit(e)}>
      <label>
        Название
        <input
          type="text"
          value={state.name}
          onChange={(e) => setState({ ...state, name: e.target.value })}
        />
      </label>
      <label>
        Цена
        <input
          type="number"
          min={0}
          step={0.01}
          value={state.price}
          onChange={(e) => setState({ ...state, price: e.target.value })}
        />
      </label>
      <label>
        Артикул (SKU)
        <input
          type="text"
          value={state.sku}
          onChange={(e) => setState({ ...state, sku: e.target.value })}
        />
      </label>
      <label>
        Описание
        <textarea
          rows={4}
          value={state.description}
          onChange={(e) => setState({ ...state, description: e.target.value })}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={state.displayOverride}
          onChange={(e) => setState({ ...state, displayOverride: e.target.checked })}
        />
        Переопределить вывод для этого товара
      </label>
      {state.displayOverride && (
        <fieldset>
          <label>
            <input
              type="checkbox"
              checked={state.showName}
              onChange={(e) => setState({ ...state, showName: e.target.checked })}
            />
            Показывать название
          </label>
          <label>
            <input
              type="checkbox"
              checked={state.showDescription}
              onChange={(e) => setState({ ...state, showDescription: e.target.checked })}
            />
            Показывать описание
          </label>
          <label>
            <input
              type="checkbox"
              checked={state.showPrice}
              onChange={(e) => setState({ ...state, showPrice: e.target.checked })}
            />
            Показывать цену
          </label>
        </fieldset>
      )}
      <button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </button>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
    </form>
  );
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/ProductForm.test.tsx`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/ProductForm.tsx services/admin-web/components/ProductForm.test.tsx
git commit -m "feat(admin-web): ProductForm for create and edit

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `ProductsTable` — список с редактированием и удалением

**Files:**
- Create: `services/admin-web/components/ProductsTable.tsx`
- Test: `services/admin-web/components/ProductsTable.test.tsx`

**Interfaces:**
- Consumes: `Product`, `deleteProduct` из `@/lib/api` (Task 4).
- Produces: `ProductsTable({ botId: string; apiBaseUrl: string; products: Product[] })` — client component.

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/ProductsTable.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProductsTable } from "@/components/ProductsTable";
import * as api from "@/lib/api";
import type { Product } from "@/lib/api";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: refreshMock }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    deleteProduct: vi.fn(),
  };
});

const products: Product[] = [
  {
    id: "p1",
    name: "Кроссовки",
    price: "5000.00",
    sku: "NK-001",
    description: null,
    display_custom: {},
    created_at: "2026-09-10T10:00:00Z",
  },
  {
    id: "p2",
    name: "Без цены",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    created_at: "2026-09-10T10:00:00Z",
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each product's name, price and sku", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} />);
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
  expect(screen.getByText("5000.00")).toBeInTheDocument();
  expect(screen.getByText("NK-001")).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2); // цена и sku "Без цены"
});

it("does nothing when the delete confirmation is declined", async () => {
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  expect(api.deleteProduct).not.toHaveBeenCalled();
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
});

it("deletes the product and removes its row after confirmation", async () => {
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
  vi.mocked(api.deleteProduct).mockResolvedValue(undefined);
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(api.deleteProduct).toHaveBeenCalledWith("http://api", "1", "p1");
  });
  await waitFor(() => {
    expect(screen.queryByText("Кроссовки")).not.toBeInTheDocument();
  });
  expect(refreshMock).toHaveBeenCalled();
});

it("shows an error and keeps the row when deletion fails", async () => {
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
  vi.mocked(api.deleteProduct).mockRejectedValue(new Error("delete failed"));
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} />);

  fireEvent.click(screen.getAllByRole("button", { name: /удалить/i })[0]);

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/delete failed/i);
  });
  expect(screen.getByText("Кроссовки")).toBeInTheDocument();
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/ProductsTable.test.tsx`
Expected: FAIL — `Cannot find module '@/components/ProductsTable'`

- [ ] **Step 3: Реализовать**

`services/admin-web/components/ProductsTable.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { deleteProduct, type Product } from "@/lib/api";

interface ProductsTableProps {
  botId: string;
  apiBaseUrl: string;
  products: Product[];
}

export function ProductsTable({ botId, apiBaseUrl, products }: ProductsTableProps) {
  const router = useRouter();
  const [rows, setRows] = useState(products);
  const [error, setError] = useState<string | null>(null);

  const handleDelete = async (productId: string) => {
    if (!confirm("Удалить товар?")) {
      return;
    }
    setError(null);
    try {
      await deleteProduct(apiBaseUrl, botId, productId);
      setRows((current) => current.filter((p) => p.id !== productId));
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить");
    }
  };

  return (
    <>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>Название</th>
            <th>Цена</th>
            <th>SKU</th>
            <th />
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((product) => (
            <tr key={product.id}>
              <td>{product.name}</td>
              <td>{product.price ?? "—"}</td>
              <td>{product.sku ?? "—"}</td>
              <td>
                <Link href={`/bots/${botId}/products/${product.id}/edit`}>Редактировать</Link>
              </td>
              <td>
                <button onClick={() => void handleDelete(product.id)}>Удалить</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/ProductsTable.test.tsx`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/ProductsTable.tsx services/admin-web/components/ProductsTable.test.tsx
git commit -m "feat(admin-web): ProductsTable with edit link and delete

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Страницы `/bots/[id]/products`, `/new`, `/[productId]/edit` + ссылка с карточки бота

**Files:**
- Create: `services/admin-web/app/bots/[id]/products/page.tsx`
- Create: `services/admin-web/app/bots/[id]/products/new/page.tsx`
- Create: `services/admin-web/app/bots/[id]/products/[productId]/edit/page.tsx`
- Modify: `services/admin-web/app/bots/[id]/page.tsx`

**Interfaces:**
- Consumes: `fetchBot`, `fetchProducts`, `fetchProduct` из `@/lib/api` (Task 4), `ProductsTable` из `@/components/ProductsTable` (Task 6), `ProductForm` из `@/components/ProductForm` (Task 5), `API_INTERNAL_URL`/`API_PUBLIC_URL` из `@/lib/env`.
- Produces: три новых маршрута; ссылка «Товары →» с `/bots/[id]`.

- [ ] **Step 1: Реализовать**

`services/admin-web/app/bots/[id]/products/page.tsx` (новый файл):

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductsTable } from "@/components/ProductsTable";
import { fetchBot, fetchProducts } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

export default async function BotProductsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const products = await fetchProducts(API_INTERNAL_URL, id);

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — товары</h1>
      <p>
        <Link href={`/bots/${id}/products/new`}>Добавить товар</Link>
      </p>
      <ProductsTable botId={id} apiBaseUrl={API_PUBLIC_URL} products={products} />
    </main>
  );
}
```

`services/admin-web/app/bots/[id]/products/new/page.tsx` (новый файл):

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

export default async function NewProductPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <p>
        <Link href={`/bots/${id}/products`}>← Назад к товарам</Link>
      </p>
      <h1>{bot.name} — новый товар</h1>
      <ProductForm botId={id} apiBaseUrl={API_PUBLIC_URL} />
    </main>
  );
}
```

`services/admin-web/app/bots/[id]/products/[productId]/edit/page.tsx`
(новый файл):

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductForm } from "@/components/ProductForm";
import { fetchBot, fetchProduct } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

export default async function EditProductPage({
  params,
}: {
  params: Promise<{ id: string; productId: string }>;
}) {
  const { id, productId } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }
  const product = await fetchProduct(API_INTERNAL_URL, id, productId);
  if (!product) {
    notFound();
  }

  return (
    <main>
      <p>
        <Link href={`/bots/${id}/products`}>← Назад к товарам</Link>
      </p>
      <h1>{bot.name} — редактировать товар</h1>
      <ProductForm botId={id} apiBaseUrl={API_PUBLIC_URL} product={product} />
    </main>
  );
}
```

`services/admin-web/app/bots/[id]/page.tsx` — полностью:

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { QrPanel } from "@/components/QrPanel";
import { fetchBot } from "@/lib/api";
import { API_INTERNAL_URL, API_PUBLIC_URL } from "@/lib/env";

export default async function BotPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <h1>{bot.name}</h1>
      <p>
        <Link href={`/bots/${bot.id}/prompts`}>Промпты и история →</Link>
      </p>
      <p>
        <Link href={`/bots/${bot.id}/settings`}>Настройки →</Link>
      </p>
      <p>
        <Link href={`/bots/${bot.id}/products`}>Товары →</Link>
      </p>
      <QrPanel initialBot={bot} apiBaseUrl={API_PUBLIC_URL} />
    </main>
  );
}
```

- [ ] **Step 2: Запустить и убедиться, что проходит**

Run: `npm run build`
Expected: `Compiled successfully` — среди роутов появляются
`/bots/[id]/products`, `/bots/[id]/products/new`,
`/bots/[id]/products/[productId]/edit`

Run: `npm test`
Expected: PASS (все файлы — новых регрессий в `QrPanel.test.tsx`/`BotsTable.test.tsx`
не ожидается, `Bot` не менялся)

- [ ] **Step 3: Коммит**

```bash
git add "services/admin-web/app/bots/[id]/products" "services/admin-web/app/bots/[id]/page.tsx"
git commit -m "feat(admin-web): products pages wired to bot detail

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Живая проверка (docker compose)

**Files:** нет изменений кода — сквозная проверка собранного стека, включая
цепочку api → celery-подстраховка при реальном сбое эмбеддинга нет смысла
эмулировать (нужен настоящий сбой OpenAI) — здесь проверяется штатный путь;
Celery-фолбэк уже покрыт юнит-тестом Task 3/Task 2.

- [ ] **Step 1: Поднять стек**

Убедиться, что в `.env` на хосте задан `OPENAI_API_KEY` (нужен реальный
ключ — сихронная попытка эмбеддинга в этой живой проверке идёт по-настоящему).

```bash
make dev
```

Дождаться, пока все сервисы станут healthy — включая `api` и `celery`
(это первая проверка, что новые зависимости `scheduling`/`llm` в их
образах действительно ставятся и сервисы не падают на старте).

- [ ] **Step 2: Создать товар**

Открыть `http://localhost:3000/bots` — выбрать существующего бота
(например, оставшегося от прошлых итераций) → «Открыть» → «Товары →».
Список пуст. Нажать «Добавить товар», заполнить название и описание,
сохранить — должен вернуться редирект на список, новый товар виден в нём.

- [ ] **Step 3: Проверить, что эмбеддинг реально посчитан**

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "select count(*) from product_embeddings;"
```

Ожидается `1` (или больше, если товаров создано несколько).

- [ ] **Step 4: Проверить, что смена цены НЕ трогает эмбеддинг**

Отредактировать товар — поменять только цену, сохранить. Убедиться (по
логам `api`, `docker compose -f compose/docker-compose.dev.yml logs api`),
что запроса к OpenAI Embeddings для этого сохранения не было (можно
проверить косвенно — время в `product_embeddings` не обновилось):

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "select p.name, p.price, pe.product_id is not null as has_embedding from products p left join product_embeddings pe on pe.product_id = p.id;"
```

- [ ] **Step 5: Проверить, что смена описания эмбеддинг обновляет**

Отредактировать тот же товар — поменять описание, сохранить. Повторный
`select` (Step 3) — количество строк `product_embeddings` не выросло
(апсерт, не дубль), но значение вектора изменилось (не проверяется
напрямую руками, достаточно убедиться, что сохранение прошло без ошибки —
детальная корректность уже покрыта юнит-тестом Task 3).

- [ ] **Step 6: Удалить товар**

Нажать «Удалить» в списке, подтвердить — товар пропал из списка. Проверить
каскад:

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "select count(*) from products; select count(*) from product_embeddings;"
```

Оба счётчика должны уменьшиться синхронно (ON DELETE CASCADE).

- [ ] **Step 7: Остановить стек**

```bash
make dev-down
```

Если что-то из Шагов 1-6 не совпало с ожиданием — не коммитить как готово,
вернуться к соответствующей задаче.
