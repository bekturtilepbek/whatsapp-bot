# Инфраструктура тулзов + реестр per bot (FEATURES.md 4.13) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** построить цикл LLM↔tool-calls (OpenAI function calling) и реестр
`tool_bindings` per bot, встроить его в основной текстовый путь ответа
worker'а — без единой настоящей тулзы (реестр пуст, первая тулза — 4.1
pgvector-поиск, следующая итерация).

**Architecture:** три новых/расширенных пакета по ADR-002: `libs/llm`
получает `complete_with_tools()` (механика одного вызова OpenAI с
`tools=[...]`), новый `libs/tools` даёт интерфейс `Tool`/`ToolContext` и
пустой реестр, `services/worker` получает `pipeline/tool_loop.py`
(бизнес-оркестрация цикла: раунды, исполнение тулз, таймауты, форс
финального текста) и подключает его в `_reply()` вместо прямого
`complete()`. Таблица `tool_bindings` (БД) + `/bots/{id}/tools` (API) —
по прецеденту `blocked_contacts`/`image_prompt`.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 async + Alembic, Pydantic v2,
FastAPI, openai SDK (`AsyncOpenAI`), pytest + testcontainers + fakeredis.

**Spec:** [docs/superpowers/specs/2026-09-05-tool-calling-infra-design.md](../specs/2026-09-05-tool-calling-infra-design.md)

## Global Constraints

- `MAX_TOOL_ROUNDS = 5` (обычных раундов `tool_choice="auto"`), затем при
  необходимости ровно один дополнительный вызов с `force_text=True`
  (`tool_choice="none"`) — максимум 6 вызовов LLM на одно сообщение клиента.
- `TOOL_CALL_TIMEOUT_SECONDS = 20.0` — таймаут одного вызова тулзы
  (`asyncio.wait_for` вокруг `executor(...)`), тот же порядок величины, что
  `STORAGE_READ_TIMEOUT_SECONDS` в `consumer.py`.
- История в БД (`messages`) — только финальный текст ответа. Промежуточные
  tool-calls/результаты НЕ пишутся отдельными строками — эфемерны в рамках
  одного вызова `run_tool_loop`.
- `_reply_with_vision`/`_reply_with_pdf` НЕ меняются в этой итерации —
  однопроходная архитектура image_prompt/pdf_prompt сохраняется как есть.
- При пустом списке тулз у бота (сейчас — у всех) поведение `_reply()`
  побитово не меняется: тот же единственный вызов `complete()`, та же форма
  запроса к OpenAI.
- Тулза = модуль/класс в `libs/tools`, включается записью в `tool_bindings`
  (CLAUDE.md); ничего per-bot в коде — конфиг тулзы живёт в
  `tool_bindings.config` (JSONB).
- Миграции только через Alembic; ruff + mypy strict на весь новый код;
  Conventional Commits; ветка `dev` уже текущая.
- На машине разработки нет `OPENAI_API_KEY` — живая проверка ограничена
  тем, что не требует реального OpenAI (см. Task 7).

---

## Task 1: `libs/tools` — интерфейс тулзы и пустой реестр

**Files:**
- Create: `libs/tools/pyproject.toml`
- Create: `libs/tools/src/tools/__init__.py`
- Create: `libs/tools/src/tools/base.py`
- Create: `libs/tools/src/tools/registry.py`
- Test: `libs/tools/tests/test_registry.py`
- Modify: `Makefile:16` (install), `Makefile:25` (lint)
- Modify: `pyproject.toml` (`[tool.mypy]` `mypy_path`)

**Interfaces:**
- Produces: `tools.base.Tool` (Protocol: `name: str`, `description: str`,
  `parameters_schema: dict[str, Any]`, `async def execute(self, arguments:
  dict[str, Any], ctx: ToolContext) -> str`), `tools.base.ToolContext`
  (frozen dataclass: `bot: Bot`, `contact_id: uuid.UUID`, `session_factory:
  async_sessionmaker[AsyncSession]`, `redis: Redis`, `storage: Storage`,
  `config: dict[str, Any]`), `tools.registry.get_tool(name: str) -> Tool |
  None`, `tools.registry.all_tool_names() -> list[str]`,
  `tools.registry._REGISTRY: dict[str, Tool]` (пустой словарь — читается и
  монки-патчится тестами Task 5/6, заполняется реальными тулзами в
  следующих итерациях).

- [ ] **Step 1: Создать пакет `libs/tools`**

`libs/tools/pyproject.toml`:

```toml
[project]
name = "tools"
version = "0.1.0"
description = "Интерфейс и реестр тулз бота (FEATURES.md 4.13) — реализации отдельных тулз добавляются по мере Волны 2"
requires-python = ">=3.12"
dependencies = [
    "db",
    "integrations",
    "redis>=5.0",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

`libs/tools/src/tools/__init__.py` — пустой файл.

- [ ] **Step 2: Написать тесты реестра (заведомо падают — модуля ещё нет)**

`libs/tools/tests/test_registry.py`:

```python
"""Реестр тулз (FEATURES.md 4.13): get_tool/all_tool_names. Пуст в
продакшн-коде на этой итерации — тесты monkeypatch'ят _REGISTRY напрямую,
не полагаясь ни на одну настоящую тулзу.
"""

from __future__ import annotations

import pytest
from tools import registry


class _DummyTool:
    name = "dummy"
    description = "тестовая тулза"
    parameters_schema: dict[str, object] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, object], ctx: object) -> str:
        return "ok"


def test_get_tool_returns_none_for_unregistered_name() -> None:
    assert registry.get_tool("does_not_exist") is None


def test_all_tool_names_empty_by_default() -> None:
    """Реестр пуст в этой итерации (инфраструктура без тулз) — первая
    настоящая тулза (следующая итерация, 4.1) обновит этот тест."""
    assert registry.all_tool_names() == []


def test_get_tool_and_all_tool_names_reflect_registered_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = _DummyTool()
    monkeypatch.setitem(registry._REGISTRY, "dummy", dummy)

    assert registry.get_tool("dummy") is dummy
    assert registry.all_tool_names() == ["dummy"]
```

- [ ] **Step 3: Запустить тесты, убедиться что падают на импорте**

Run: `pytest libs/tools/tests/test_registry.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'tools'`) — пакет ещё
не установлен и `base.py`/`registry.py` не существуют.

- [ ] **Step 4: Реализовать `base.py` и `registry.py`**

`libs/tools/src/tools/base.py`:

```python
"""Интерфейс тулзы бота (FEATURES.md 4.13). Реализация конкретной тулзы —
модуль/класс в этом пакете, регистрируется в registry.py; какому боту она
доступна и с каким config — решает tool_bindings (libs/db), не код тулзы.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from db.models import Bot
from integrations.storage import Storage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class ToolContext:
    """Всё, что нужно тулзе для одного вызова — собирается в
    services/worker/pipeline/consumer.py на каждый tool-call."""

    bot: Bot
    contact_id: uuid.UUID
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: Storage
    config: dict[str, Any]  # tool_bindings.config для этого бота и этой тулзы


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]  # JSON schema тела function для OpenAI

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> str: ...
```

`libs/tools/src/tools/registry.py`:

```python
"""Реестр доступных тулз (FEATURES.md 4.13). Пуст в этой итерации —
инфраструктура без единой настоящей тулзы; заполняется в следующих
итерациях Волны 2 (первая — 4.1, pgvector-поиск товара).

Какие тулзы ВКЛЮЧЕНЫ конкретному боту — решает не этот файл, а таблица
tool_bindings (libs/db/src/db/tool_bindings.py); этот реестр — что вообще
существует в коде.
"""

from __future__ import annotations

from .base import Tool

_REGISTRY: dict[str, Tool] = {}


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tool_names() -> list[str]:
    return list(_REGISTRY)
```

- [ ] **Step 5: Установить пакет и прогнать тесты**

Run:
```bash
pip install -e libs/tools
pytest libs/tools/tests/test_registry.py -v
```
Expected: PASS (3 теста)

- [ ] **Step 6: Подключить `libs/tools` к install/lint/mypy_path**

`Makefile:16` — добавить `-e libs/tools` в строку `pip install`:

```makefile
	pip install -e libs/core -e libs/db -e libs/llm -e libs/integrations -e libs/scheduling -e libs/tools -e services/worker -e services/celery -e services/api -r requirements-dev.txt
```

`Makefile:25` — добавить `libs/tools/src` в список mypy (рядом с
core/db/integrations/scheduling):

```makefile
	ruff check . && mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src libs/tools/src services/worker/src services/celery/src
```

`pyproject.toml` `[tool.mypy] mypy_path` — добавить `libs/tools/src` в
двоеточие-разделённый список (после `libs/scheduling/src`):

```toml
mypy_path = "libs/core/src:libs/db/src:libs/llm/src:libs/integrations/src:libs/scheduling/src:libs/tools/src:services/worker/src:services/api/src:services/celery/src"
```

- [ ] **Step 7: Прогнать ruff + mypy на новый пакет**

Run: `ruff check libs/tools && mypy libs/tools/src`
Expected: без ошибок

- [ ] **Step 8: Commit**

```bash
git add libs/tools Makefile pyproject.toml
git commit -m "feat(tools): tool interface and empty registry (FEATURES.md 4.13)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `libs/db` — таблица `tool_bindings` + запросы

**Files:**
- Modify: `libs/db/src/db/models.py` (добавить класс `ToolBinding` после `BlockedContact`)
- Create: `libs/db/src/db/tool_bindings.py`
- Create: `libs/db/migrations/versions/202609051002_tool_bindings.py`
- Modify: `libs/db/tests/test_migration.py` (добавить `"tool_bindings"` в ожидаемый набор таблиц)
- Test: `libs/db/tests/test_tool_bindings.py`

**Interfaces:**
- Produces: `db.models.ToolBinding` (SQLAlchemy-модель: `id: uuid.UUID`,
  `bot_id: uuid.UUID`, `tool_name: str`, `config: dict[str, Any]`,
  `created_at: datetime`), `db.tool_bindings.list_enabled(session:
  AsyncSession, bot_id: uuid.UUID) -> list[ToolBinding]`,
  `db.tool_bindings.enable(session: AsyncSession, bot_id: uuid.UUID,
  tool_name: str, config: dict[str, Any]) -> None` (upsert — повторный
  вызов с тем же `tool_name` обновляет `config`, не дублирует строку),
  `db.tool_bindings.disable(session: AsyncSession, bot_id: uuid.UUID,
  tool_name: str) -> None` (идемпотентно).

- [ ] **Step 1: Написать тесты БД (падают — модуля/таблицы ещё нет)**

`libs/db/tests/test_tool_bindings.py`:

```python
"""tool_bindings: list_enabled/enable/disable (FEATURES.md 4.13,
инфраструктура). Требует Docker (testcontainers). Без него — skip, не fail.
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
from db.models import Bot
from db.tool_bindings import disable, enable, list_enabled
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


async def test_list_enabled_empty_by_default(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await list_enabled(session, bot_id) == []


async def test_enable_then_list_enabled_returns_it(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await enable(session, bot_id, "search", {"limit": 3})
    bindings = await list_enabled(session, bot_id)
    assert len(bindings) == 1
    assert bindings[0].tool_name == "search"
    assert bindings[0].config == {"limit": 3}


async def test_enable_is_upsert_and_updates_config(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await enable(session, bot_id, "search", {"limit": 3})
    await enable(session, bot_id, "search", {"limit": 10})

    bindings = await list_enabled(session, bot_id)
    assert len(bindings) == 1  # не дублируется
    assert bindings[0].config == {"limit": 10}


async def test_disable_removes_binding(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await enable(session, bot_id, "search", {})
    await disable(session, bot_id, "search")
    assert await list_enabled(session, bot_id) == []


async def test_disable_unknown_is_not_an_error(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await disable(session, bot_id, "does_not_exist")  # не должно упасть


async def test_bindings_are_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await enable(session, bot_a, "search", {})
    assert len(await list_enabled(session, bot_a)) == 1
    assert await list_enabled(session, bot_b) == []
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `pytest libs/db/tests/test_tool_bindings.py -v`
Expected: FAIL (`ImportError: cannot import name 'disable' from 'db.tool_bindings'`
или `ModuleNotFoundError`, т.к. `db/tool_bindings.py` ещё не существует)

- [ ] **Step 3: Добавить модель `ToolBinding` в `models.py`**

`libs/db/src/db/models.py` — добавить класс после `BlockedContact` (конец файла):

```python
class ToolBinding(Base):
    """Тулзы, включённые конкретному боту (FEATURES.md 4.13). Сама тулза —
    код в libs/tools; эта таблица решает, что боту доступно и с каким
    config (например chat_id для telegram-лидов).
    """

    __tablename__ = "tool_bindings"
    __table_args__ = (
        UniqueConstraint("bot_id", "tool_name", name="uq_tool_bindings_bot_tool_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Написать `libs/db/src/db/tool_bindings.py`**

```python
"""Реестр тулз, включённых конкретному боту (FEATURES.md 4.13). Сама
тулза как код живёт в libs/tools — эта таблица только решает, что боту
доступно и с каким config.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ToolBinding


async def list_enabled(session: AsyncSession, bot_id: uuid.UUID) -> list[ToolBinding]:
    stmt = (
        select(ToolBinding)
        .where(ToolBinding.bot_id == bot_id)
        .order_by(ToolBinding.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def enable(
    session: AsyncSession, bot_id: uuid.UUID, tool_name: str, config: dict[str, Any]
) -> None:
    """Идемпотентно: повторное включение той же тулзы обновляет config,
    а не создаёт вторую строку (UNIQUE(bot_id, tool_name))."""
    stmt = (
        insert(ToolBinding)
        .values(bot_id=bot_id, tool_name=tool_name, config=config)
        .on_conflict_do_update(
            constraint="uq_tool_bindings_bot_tool_name",
            set_={"config": config},
        )
    )
    await session.execute(stmt)
    await session.flush()


async def disable(session: AsyncSession, bot_id: uuid.UUID, tool_name: str) -> None:
    """Идемпотентно: выключение отсутствующей тулзы — не ошибка (0 строк)."""
    stmt = delete(ToolBinding).where(
        ToolBinding.bot_id == bot_id, ToolBinding.tool_name == tool_name
    )
    await session.execute(stmt)
    await session.flush()
```

- [ ] **Step 5: Написать Alembic-миграцию**

`libs/db/migrations/versions/202609051002_tool_bindings.py`:

```python
"""tool_bindings

Revision ID: 202609051002
Revises: 202609051001
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609051002"
down_revision: str | None = "202609051001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_bindings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("bot_id", "tool_name", name="uq_tool_bindings_bot_tool_name"),
    )


def downgrade() -> None:
    op.drop_table("tool_bindings")
```

- [ ] **Step 6: Добавить `"tool_bindings"` в ожидаемые таблицы `test_migration.py`**

`libs/db/tests/test_migration.py:60-63` — изменить:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings",
        } <= tables
```

- [ ] **Step 7: Прогнать тесты, убедиться что проходят**

Run: `pytest libs/db/tests/test_tool_bindings.py libs/db/tests/test_migration.py -v`
Expected: PASS (миграция применяется, `test_migration.py` видит новую таблицу, все 6 тестов `test_tool_bindings.py` зелёные)

- [ ] **Step 8: ruff + mypy**

Run: `ruff check libs/db && mypy libs/db/src`
Expected: без ошибок

- [ ] **Step 9: Commit**

```bash
git add libs/db/src/db/models.py libs/db/src/db/tool_bindings.py libs/db/migrations/versions/202609051002_tool_bindings.py libs/db/tests/test_tool_bindings.py libs/db/tests/test_migration.py
git commit -m "feat(db): tool_bindings table and query helpers (FEATURES.md 4.13)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `libs/llm` — `complete_with_tools()`

**Files:**
- Modify: `libs/llm/src/llm/client.py`
- Modify: `libs/llm/tests/test_client.py`

**Interfaces:**
- Produces: `llm.client.ToolSpec` (frozen dataclass: `name: str`,
  `description: str`, `parameters_schema: dict[str, Any]`),
  `llm.client.ToolCall` (frozen dataclass: `id: str`, `name: str`,
  `arguments_json: str` — сырой JSON-текст аргументов от OpenAI, НЕ
  распарсенный: разбор и обработка ошибки парсинга — забота вызывающего,
  см. Task 4), `llm.client.AssistantToolCallsTurn` (frozen dataclass:
  `tool_calls: list[ToolCall]`), `llm.client.ToolResultTurn` (frozen
  dataclass: `tool_call_id: str`, `name: str`, `content: str`),
  `llm.client.ToolExchangeTurn` (`= AssistantToolCallsTurn |
  ToolResultTurn`), `llm.client.LLMResult.tool_calls: list[ToolCall] |
  None = None` (новое поле, `None` — как раньше, когда тулз не было),
  `async def complete_with_tools(system_prompt: str, history:
  list[HistoryMessage], tools: list[ToolSpec], exchange:
  Sequence[ToolExchangeTurn] = (), *, force_text: bool = False, client:
  AsyncOpenAI | None = None, timeout_seconds: float =
  REQUEST_TIMEOUT_SECONDS) -> LLMResult`.
- Consumes: ничего нового (расширяет существующий `_call_and_extract`,
  `complete`/`complete_with_image` не меняют сигнатуру и поведение).

- [ ] **Step 1: Расширить тестовые фейки и написать новые тесты (падают)**

`libs/llm/tests/test_client.py` — добавить в блок импортов (после
существующего `from llm.client import HistoryMessage, complete,
complete_with_image`):

```python
from llm.client import (
    AssistantToolCallsTurn,
    HistoryMessage,
    ToolCall,
    ToolResultTurn,
    ToolSpec,
    complete,
    complete_with_image,
    complete_with_tools,
)
```

Изменить `_FakeMessage` (добавить поле с дефолтом — существующие вызовы
`_FakeMessage(content=...)` не ломаются):

```python
@dataclass
class _FakeMessage:
    content: str | None
    tool_calls: list[object] | None = None
```

Добавить рядом с `_FakeMessage`/`_FakeChoice` два новых фейка:

```python
@dataclass
class _FakeFunctionCall:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunctionCall
```

Добавить в конец файла новые тесты:

```python
async def test_complete_with_tools_sends_function_specs_and_auto_choice() -> None:
    client = _client_with_response("ok", 1, 1)
    spec = ToolSpec(
        name="search", description="ищет товар", parameters_schema={"type": "object", "properties": {}}
    )
    await complete_with_tools("SYS", [], [spec], client=client)  # type: ignore[arg-type]

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "ищет товар",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert kwargs["tool_choice"] == "auto"


async def test_complete_with_tools_force_text_sets_tool_choice_none() -> None:
    client = _client_with_response("ok", 1, 1)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    await complete_with_tools("SYS", [], [spec], force_text=True, client=client)  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["tool_choice"] == "none"


async def test_complete_with_tools_parses_tool_calls_from_response() -> None:
    response = _FakeResponse(
        choices=[
            _FakeChoice(
                message=_FakeMessage(
                    content=None,
                    tool_calls=[
                        _FakeToolCall(
                            id="call_1",
                            function=_FakeFunctionCall(name="search", arguments='{"q": "кроссовки"}'),
                        )
                    ],
                )
            )
        ],
        usage=_FakeUsage(prompt_tokens=10, completion_tokens=5),
    )
    client = _FakeClient(_FakeCompletions(response=response))
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    result = await complete_with_tools("SYS", [], [spec], client=client)  # type: ignore[arg-type]

    assert result.text == ""
    assert result.tool_calls == [ToolCall(id="call_1", name="search", arguments_json='{"q": "кроссовки"}')]


async def test_complete_with_tools_no_tool_calls_returns_plain_text() -> None:
    client = _client_with_response("обычный ответ", 5, 5)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    result = await complete_with_tools("SYS", [], [spec], client=client)  # type: ignore[arg-type]
    assert result.text == "обычный ответ"
    assert result.tool_calls is None


async def test_complete_with_tools_exchange_becomes_assistant_and_tool_messages() -> None:
    client = _client_with_response("финальный ответ", 1, 1)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    exchange = [
        AssistantToolCallsTurn([ToolCall(id="call_1", name="search", arguments_json='{"q": "x"}')]),
        ToolResultTurn(tool_call_id="call_1", name="search", content="ничего не найдено"),
    ]
    await complete_with_tools("SYS", [], [spec], exchange, client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q": "x"}'}}
        ],
    }
    assert sent[2] == {"role": "tool", "tool_call_id": "call_1", "content": "ничего не найдено"}


async def test_complete_without_tools_does_not_send_tools_key() -> None:
    """Регрессия: у ботов без единой включённой тулзы (все сейчас) форма
    запроса к OpenAI не должна меняться вообще."""
    client = _client_with_response("ok", 1, 1)
    await complete("SYS", [], client=client)  # type: ignore[arg-type]
    assert "tools" not in client.chat.completions.last_call_kwargs
    assert "tool_choice" not in client.chat.completions.last_call_kwargs
```

- [ ] **Step 2: Запустить тесты, убедиться что новые падают**

Run: `pytest libs/llm/tests/test_client.py -v`
Expected: старые тесты (retries, complete, complete_with_image) — PASS;
новые (`test_complete_with_tools_*`, `test_complete_without_tools_does_not_send_tools_key`)
— FAIL (`ImportError: cannot import name 'ToolSpec'`)

- [ ] **Step 3: Реализовать `complete_with_tools()` в `client.py`**

`libs/llm/src/llm/client.py` — добавить в блок импортов (после `import os`):

```python
from collections.abc import Sequence
from typing import Any
```

(`json` не нужен в этом файле — парсинг `arguments_json` в аргументы
тулзы делает `tool_loop.py`, Task 4, не `client.py`.)

Заменить сигнатуру и тело `_call_and_extract` (строки 63-94) на:

```python
async def _call_and_extract(
    active_client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, object]],
    timeout_seconds: float,
    *,
    tools: list[dict[str, object]] | None = None,
    tool_choice: str | None = None,
) -> LLMResult:
    """Ретрай — только на временные сбои SDK (см. _RETRYABLE_EXCEPTIONS),
    экспоненциальный backoff (1с, 2с) между попытками. Таймаут на каждую
    попытку — тот же timeout_seconds, не суммируется отдельно.

    tools/tool_choice — опциональны: complete()/complete_with_image() их не
    передают, форма запроса для них не меняется (регрессия — см.
    test_complete_without_tools_does_not_send_tools_key).
    """
    response = None
    kwargs: dict[str, object] = {"model": model, "messages": messages, "timeout": timeout_seconds}
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            response = await active_client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
            break
        except _RETRYABLE_EXCEPTIONS:
            if attempt == RETRY_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    # цикл либо break (успех), либо raise на последней попытке — эта ветка недостижима
    assert response is not None  # pragma: no cover

    choice = response.choices[0]
    text = choice.message.content or ""
    raw_tool_calls = getattr(choice.message, "tool_calls", None)
    tool_calls: list[ToolCall] | None = None
    if raw_tool_calls:
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments_json=tc.function.arguments or "")
            for tc in raw_tool_calls
        ]

    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    return LLMResult(
        text=text, tokens_in=tokens_in, tokens_out=tokens_out, model=model, tool_calls=tool_calls
    )
```

Добавить новые dataclass'ы рядом с `LLMResult` (после неё):

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str  # сырой JSON от OpenAI — разбор на стороне вызывающего


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True)
class AssistantToolCallsTurn:
    tool_calls: list[ToolCall]


@dataclass(frozen=True)
class ToolResultTurn:
    tool_call_id: str
    name: str
    content: str


ToolExchangeTurn = AssistantToolCallsTurn | ToolResultTurn
```

Обновить `LLMResult` (добавить поле в конец):

```python
@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    tool_calls: list[ToolCall] | None = None
```

Добавить хелперы и `complete_with_tools()` в конец файла:

```python
def _tool_specs_to_openai(tools: list[ToolSpec]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
            },
        }
        for t in tools
    ]


def _exchange_to_messages(exchange: Sequence[ToolExchangeTurn]) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for turn in exchange:
        if isinstance(turn, AssistantToolCallsTurn):
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments_json},
                        }
                        for call in turn.tool_calls
                    ],
                }
            )
        else:
            messages.append(
                {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content}
            )
    return messages


async def complete_with_tools(
    system_prompt: str,
    history: list[HistoryMessage],
    tools: list[ToolSpec],
    exchange: Sequence[ToolExchangeTurn] = (),
    *,
    force_text: bool = False,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """Один вызов LLM с доступными тулзами (FEATURES.md 4.13, инфраструктура).
    Цикл по нескольким раундам — НЕ здесь, а в
    services/worker/pipeline/tool_loop.py (ADR-002: этот пакет — только
    механика вызова OpenAI, оркестрация цикла — бизнес-логика worker).

    exchange — уже случившиеся в ТЕКУЩЕМ раунде реплики (assistant с
    tool_calls + результаты тулз), эфемерны в рамках одного вызова
    run_tool_loop — не путать с history (постоянная история из БД).

    force_text=True форсирует tool_choice="none" — модель обязана ответить
    текстом по уже собранным в exchange результатам, а не запросить ещё
    одну тулзу (используется, когда исчерпан лимит раундов цикла).
    """
    model = current_model()
    messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages += _exchange_to_messages(exchange)
    active_client = client or _default_client()
    return await _call_and_extract(
        active_client,
        model,
        messages,
        timeout_seconds,
        tools=_tool_specs_to_openai(tools),
        tool_choice="none" if force_text else "auto",
    )
```

- [ ] **Step 4: Запустить тесты, убедиться что все проходят**

Run: `pytest libs/llm/tests/test_client.py -v`
Expected: PASS (все тесты — старые и новые)

- [ ] **Step 5: ruff + mypy**

Run: `ruff check libs/llm && mypy libs/llm/src`
Expected: без ошибок

- [ ] **Step 6: Commit**

```bash
git add libs/llm/src/llm/client.py libs/llm/tests/test_client.py
git commit -m "feat(llm): tool-calling support in LLM client (FEATURES.md 4.13)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `services/worker` — цикл `run_tool_loop`

**Files:**
- Create: `services/worker/src/worker/pipeline/tool_loop.py`
- Test: `services/worker/tests/pipeline/test_tool_loop.py`

**Interfaces:**
- Consumes: `llm.client.{HistoryMessage, LLMResult, ToolCall, ToolSpec,
  AssistantToolCallsTurn, ToolResultTurn, ToolExchangeTurn, complete,
  complete_with_tools}` (Task 3).
- Produces: `worker.pipeline.tool_loop.ToolLoopResult` (frozen dataclass:
  `text: str`, `tokens_in: int`, `tokens_out: int`, `model: str`),
  `worker.pipeline.tool_loop.ToolExecutor` (`= Callable[[str, dict[str,
  Any]], Awaitable[str]]`), `worker.pipeline.tool_loop.MAX_TOOL_ROUNDS = 5`,
  `worker.pipeline.tool_loop.TOOL_CALL_TIMEOUT_SECONDS = 20.0`, `async def
  run_tool_loop(system_prompt: str, history: list[HistoryMessage], tools:
  list[ToolSpec], executor: ToolExecutor, *, max_rounds: int =
  MAX_TOOL_ROUNDS, complete_fn=..., complete_with_tools_fn=...) ->
  ToolLoopResult` — используется в Task 5 (`_reply()`).

- [ ] **Step 1: Написать тесты цикла (падают — модуля ещё нет)**

`services/worker/tests/pipeline/test_tool_loop.py`:

```python
"""run_tool_loop: цикл LLM↔tool-calls (FEATURES.md 4.13, инфраструктура).
complete_fn/complete_with_tools_fn/executor — все фейковые, сценарии
прогоняются полностью синхронно предсказуемым скриптом, без реального
OpenAI-вызова.
"""

from __future__ import annotations

from llm.client import (
    AssistantToolCallsTurn,
    HistoryMessage,
    LLMResult,
    ToolCall,
    ToolResultTurn,
    ToolSpec,
)
from worker.pipeline.tool_loop import ToolLoopResult, run_tool_loop

_SPEC = ToolSpec(name="search", description="ищет товар", parameters_schema={"type": "object"})


async def _unused_executor(name: str, arguments: dict[str, object]) -> str:
    raise AssertionError("не должен вызываться в этом сценарии")


async def test_empty_tools_calls_complete_fn_directly() -> None:
    async def complete_fn(system_prompt: str, history: list[HistoryMessage]) -> LLMResult:
        return LLMResult(text="прямой ответ", tokens_in=10, tokens_out=2, model="gpt-4o-mini")

    async def fail_complete_with_tools(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("не должен вызываться, когда tools пуст")

    result = await run_tool_loop(
        "SYS", [], [], _unused_executor,
        complete_fn=complete_fn, complete_with_tools_fn=fail_complete_with_tools,
    )
    assert result == ToolLoopResult(text="прямой ответ", tokens_in=10, tokens_out=2, model="gpt-4o-mini")


async def test_single_round_returns_text_when_no_tool_calls_requested() -> None:
    async def complete_with_tools_fn(*args: object, **kwargs: object) -> LLMResult:
        return LLMResult(text="готовый ответ", tokens_in=20, tokens_out=8, model="gpt-4o-mini")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], _unused_executor, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "готовый ответ"
    assert result.tokens_in == 20
    assert result.tokens_out == 8


async def test_two_round_scenario_executes_tool_then_returns_final_text() -> None:
    calls: list[dict[str, object]] = []

    async def complete_with_tools_fn(
        system_prompt: str,
        history: list[HistoryMessage],
        tools: list[ToolSpec],
        exchange: object,
        *,
        force_text: bool = False,
    ) -> LLMResult:
        calls.append({"exchange_len": len(list(exchange)), "force_text": force_text})
        if len(calls) == 1:
            return LLMResult(
                text="", tokens_in=15, tokens_out=5, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json='{"q": "кроссовки"}')],
            )
        return LLMResult(text="Нашёл кроссовки Nike.", tokens_in=25, tokens_out=10, model="gpt-4o-mini")

    async def executor(name: str, arguments: dict[str, object]) -> str:
        assert name == "search"
        assert arguments == {"q": "кроссовки"}
        return "Nike Air, 5000 сом"

    result = await run_tool_loop("SYS", [], [_SPEC], executor, complete_with_tools_fn=complete_with_tools_fn)

    assert result.text == "Нашёл кроссовки Nike."
    assert result.tokens_in == 15 + 25
    assert result.tokens_out == 5 + 10
    assert calls[0]["exchange_len"] == 0
    assert calls[1]["exchange_len"] == 2  # assistant-tool-calls + tool-result


async def test_invalid_json_arguments_returns_error_turn_without_calling_executor() -> None:
    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="m",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="не json")],
            )
        tool_turn = exchange_list[1]
        assert isinstance(tool_turn, ToolResultTurn)
        assert "JSON" in tool_turn.content
        return LLMResult(text="понял, уточню", tokens_in=1, tokens_out=1, model="m")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], _unused_executor, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "понял, уточню"


async def test_executor_exception_returns_error_turn_and_loop_continues() -> None:
    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="m",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        tool_turn = exchange_list[1]
        assert isinstance(tool_turn, ToolResultTurn)
        assert "Ошибка" in tool_turn.content
        return LLMResult(text="извините, не получилось", tokens_in=1, tokens_out=1, model="m")

    async def executor(name: str, arguments: dict[str, object]) -> str:
        raise RuntimeError("тулза упала")

    result = await run_tool_loop("SYS", [], [_SPEC], executor, complete_with_tools_fn=complete_with_tools_fn)
    assert result.text == "извините, не получилось"


async def test_max_rounds_exhausted_forces_final_text_call() -> None:
    call_count = 0

    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        nonlocal call_count
        call_count += 1
        if force_text:
            return LLMResult(
                text="итоговый ответ по тому, что успел узнать", tokens_in=1, tokens_out=1, model="m"
            )
        return LLMResult(
            text="", tokens_in=1, tokens_out=1, model="m",
            tool_calls=[ToolCall(id=f"call_{call_count}", name="search", arguments_json="{}")],
        )

    async def executor(name: str, arguments: dict[str, object]) -> str:
        return "результат"

    result = await run_tool_loop(
        "SYS", [], [_SPEC], executor, max_rounds=2, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "итоговый ответ по тому, что успел узнать"
    assert call_count == 3  # 2 обычных раунда + 1 форсированный текстовый
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `pytest services/worker/tests/pipeline/test_tool_loop.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'worker.pipeline.tool_loop'`)

- [ ] **Step 3: Реализовать `tool_loop.py`**

`services/worker/src/worker/pipeline/tool_loop.py`:

```python
"""Цикл LLM↔tool-calls (FEATURES.md 4.13, инфраструктура). Оркестрация —
здесь (ADR-002: worker = бизнес-логика); механика одного вызова OpenAI —
libs/llm. См. docs/superpowers/specs/2026-09-05-tool-calling-infra-design.md

При пустом списке тулз — один вызов complete_fn(), форма запроса и
поведение идентичны тому, что было до этой фичи: это гарантирует, что
подключение цикла в _reply() (Task 5) при пустом реестре тулз у всех
ботов сейчас — ноль изменений в живом поведении.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from llm.client import (
    AssistantToolCallsTurn,
    HistoryMessage,
    LLMResult,
    ToolCall,
    ToolExchangeTurn,
    ToolResultTurn,
    ToolSpec,
)
from llm.client import complete as _default_complete
from llm.client import complete_with_tools as _default_complete_with_tools

logger = structlog.get_logger("worker.pipeline.tool_loop")

MAX_TOOL_ROUNDS = 5
TOOL_CALL_TIMEOUT_SECONDS = 20.0

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]
_CompleteFn = Callable[[str, list[HistoryMessage]], Awaitable[LLMResult]]
_CompleteWithToolsFn = Callable[..., Awaitable[LLMResult]]


@dataclass(frozen=True)
class ToolLoopResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


async def run_tool_loop(
    system_prompt: str,
    history: list[HistoryMessage],
    tools: list[ToolSpec],
    executor: ToolExecutor,
    *,
    max_rounds: int = MAX_TOOL_ROUNDS,
    complete_fn: _CompleteFn = _default_complete,
    complete_with_tools_fn: _CompleteWithToolsFn = _default_complete_with_tools,
) -> ToolLoopResult:
    if not tools:
        result = await complete_fn(system_prompt, history)
        return ToolLoopResult(
            text=result.text, tokens_in=result.tokens_in, tokens_out=result.tokens_out, model=result.model
        )

    exchange: list[ToolExchangeTurn] = []
    tokens_in_total = 0
    tokens_out_total = 0
    model_name = ""

    for _ in range(max_rounds):
        result = await complete_with_tools_fn(system_prompt, history, tools, exchange)
        tokens_in_total += result.tokens_in
        tokens_out_total += result.tokens_out
        model_name = result.model

        if not result.tool_calls:
            return ToolLoopResult(
                text=result.text, tokens_in=tokens_in_total, tokens_out=tokens_out_total, model=model_name
            )

        exchange.append(AssistantToolCallsTurn(result.tool_calls))
        for call in result.tool_calls:
            output = await _run_one_tool(call, executor)
            exchange.append(ToolResultTurn(call.id, call.name, output))

    logger.warning("tool loop reached max_rounds, forcing final text answer", max_rounds=max_rounds)
    result = await complete_with_tools_fn(system_prompt, history, tools, exchange, force_text=True)
    tokens_in_total += result.tokens_in
    tokens_out_total += result.tokens_out
    return ToolLoopResult(
        text=result.text, tokens_in=tokens_in_total, tokens_out=tokens_out_total, model=result.model
    )


async def _run_one_tool(call: ToolCall, executor: ToolExecutor) -> str:
    try:
        arguments: dict[str, Any] = json.loads(call.arguments_json) if call.arguments_json else {}
    except json.JSONDecodeError:
        logger.warning("tool call arguments are not valid json", tool_name=call.name)
        return "Ошибка: не удалось разобрать аргументы как JSON. Повтори вызов с корректным JSON."

    try:
        return await asyncio.wait_for(executor(call.name, arguments), timeout=TOOL_CALL_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("tool execution failed", tool_name=call.name, exc_info=True)
        return "Ошибка при вызове инструмента. Продолжай без этого результата или попробуй иначе."
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `pytest services/worker/tests/pipeline/test_tool_loop.py -v`
Expected: PASS (6 тестов)

- [ ] **Step 5: ruff + mypy**

Run: `ruff check services/worker && mypy services/worker/src`
Expected: без ошибок

- [ ] **Step 6: Commit**

```bash
git add services/worker/src/worker/pipeline/tool_loop.py services/worker/tests/pipeline/test_tool_loop.py
git commit -m "feat(worker): tool-calling loop (FEATURES.md 4.13)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `services/worker` — подключить цикл в `_reply()`

**Files:**
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Modify: `services/worker/pyproject.toml` (добавить зависимость `tools`)
- Test: `services/worker/tests/pipeline/test_reply_tools.py`

**Interfaces:**
- Consumes: `tools.base.ToolContext`, `tools.registry.get_tool` (Task 1);
  `db.tool_bindings.list_enabled`, `db.models.ToolBinding` (Task 2);
  `llm.client.{ToolSpec, complete, complete_with_tools}` (Task 3);
  `worker.pipeline.tool_loop.{run_tool_loop, ToolExecutor}` (Task 4).
- Produces: `_reply()` получает новый параметр `storage: Storage` (был
  доступен в `_process_entry`, но не передавался); новые приватные хелперы
  `_tool_specs_for_bindings(bindings: list[ToolBinding]) -> list[ToolSpec]`,
  `_make_tool_executor(bot, contact_id, session_factory, redis, storage,
  bindings) -> ToolExecutor` в `consumer.py`.

- [ ] **Step 1: Добавить зависимость `tools` в pyproject worker**

`services/worker/pyproject.toml` — добавить `"tools",` в `dependencies`
(после `"integrations",`):

```toml
dependencies = [
    "core",
    "db",
    "llm",
    "integrations",
    "tools",
    "scheduling",
    "redis>=5.0",
    "structlog>=24.4",
    "aiohttp>=3.10",
    "pypdf>=5.0",
]
```

Run: `pip install -e services/worker`

- [ ] **Step 2: Написать тесты подключения (падают — `_reply` ещё не принимает storage/тулзы)**

`services/worker/tests/pipeline/test_reply_tools.py`:

```python
"""_reply(): включённые в tool_bindings тулзы попадают в run_tool_loop;
тулза, которой нет в реестре libs/tools, молча пропускается (FEATURES.md
4.13, инфраструктура — реального дозвона до LLM здесь нет, run_tool_loop
патчится тестовыми фейками, как и complete/complete_with_image в
test_reply_smoke.py).
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
from db.models import Bot
from db.tool_bindings import enable as enable_tool_binding
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult, ToolCall
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import registry as tools_registry
from tools.base import ToolContext
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

REPO_ROOT = Path(__file__).resolve().parents[4]
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


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не читает из Storage")


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot", enabled=True, system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek", settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Привет",
        "ts": 1756800000000,
    }


async def test_no_bindings_uses_complete_fn_fast_path(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ни одной строки в tool_bindings — как сейчас у всех ботов: быстрый
    путь run_tool_loop (просто complete()), поведение не меняется."""

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="ответ без тулз", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert "ответ без тулз" in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_binding_for_tool_missing_from_registry_is_silently_skipped(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """tool_bindings ссылается на имя, которого нет в реестре libs/tools
    (рассинхрон БД/деплоя кода) — не должно ронять диалог и не должно
    доходить до complete_with_tools (итоговых тулз для LLM — ноль)."""

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_complete_with_tools(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("не должен вызываться — тулза не найдена в реестре")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fail_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "phantom_tool", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert "ok" in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_registered_tool_is_offered_and_can_be_invoked_end_to_end(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Реестр временно содержит фейковую тулзу (monkeypatch, не продакшн-код)
    — доказывает, что вся цепочка tool_bindings -> реестр -> ToolContext ->
    executor реально работает, без реального OpenAI-вызова."""

    class _FakeSearchTool:
        name = "search"
        description = "тестовая тулза"
        parameters_schema: dict[str, object] = {"type": "object", "properties": {}}

        async def execute(self, arguments: dict[str, object], ctx: ToolContext) -> str:
            assert ctx.config == {"limit": 3}
            assert ctx.contact_id is not None
            return "найдено: тестовый товар"

    monkeypatch.setitem(tools_registry._REGISTRY, "search", _FakeSearchTool())

    captured_tool_specs: list[object] = []

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        captured_tool_specs.append(tools)
        if not list(exchange):
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        return LLMResult(text="Вот тестовый товар.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "search", {"limit": 3})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert "Вот тестовый товар." in out_entries[1][1]["payload"]
        assert len(captured_tool_specs[0]) == 1
        assert captured_tool_specs[0][0].name == "search"
    finally:
        await redis.aclose()
```

- [ ] **Step 3: Запустить тесты, убедиться что падают**

Run: `pytest services/worker/tests/pipeline/test_reply_tools.py -v`
Expected: `test_no_bindings_uses_complete_fn_fast_path` — PASS уже сейчас
(старая `_reply` и так просто зовёт `complete()`, тест лишь фиксирует это
поведение как регрессионную границу перед рефакторингом). Две другие FAIL:
`consumer.py` ещё не импортирует `complete_with_tools`, поэтому
`monkeypatch.setattr(consumer_module, "complete_with_tools", ...)` в
`test_binding_for_tool_missing_from_registry_is_silently_skipped` и
`test_registered_tool_is_offered_and_can_be_invoked_end_to_end` падает с
`AttributeError` (по умолчанию `setattr` требует существующий атрибут).

- [ ] **Step 4: Обновить `consumer.py`**

Импорты `services/worker/src/worker/pipeline/consumer.py:29-51` — заменить
блок целиком на:

```python
import structlog
from core.events import Event, InboundText, OutboundText, OutboundTyping
from db.blocked_contacts import is_blocked
from db.bots import get_bot
from db.contacts import match_or_create_contact
from db.messages import fetch_recent_history, insert_incoming, insert_outgoing
from db.models import Bot, ToolBinding
from db.tool_bindings import list_enabled as list_enabled_tool_bindings
from db.usage import record_usage
from integrations.storage import Storage
from llm.client import HistoryMessage, ToolSpec, complete, complete_with_image, complete_with_tools
from llm.pricing import compute_cost
from llm.time_context import time_context
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tools.base import ToolContext
from tools.registry import get_tool

from ..bus import IN_STREAM, OUT_STREAM, ensure_group, publish, read_group
from . import batching, handoff, lock
from .dedup import is_duplicate
from .filters import is_ignored_chat
from .media import incoming_content
from .pdf_extract import extract_pdf_text
from .tool_loop import ToolExecutor, run_tool_loop
```

Строку вызова `_reply` внутри `_process_entry`
(`services/worker/src/worker/pipeline/consumer.py:181-182`, ветка `else`)
— изменить:

```python
        else:
            await _reply(event, bot, contact.id, redis, session_factory, storage)
```

Модульный докстринг (строка 10) — уточнить шаг перед "typing":

```
батчинг (debounce) → лок диалога → фото с настроенным image_prompt? ... :
... : прочее медиа? заглушка без LLM :
история → тулзы бота (LLM↔tool-calls, FEATURES.md 4.13; реестр пуст — как
раньше, просто complete()) → typing → ответ → запись ответа →
usage_events (LLM-ветки, включая vision и PDF).
```

Функцию `_reply` (строки 281-308) — заменить целиком:

```python
async def _reply(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    async with session_factory() as session:
        history_rows = await fetch_recent_history(session, contact_id)
        bindings = await list_enabled_tool_bindings(session, bot.id)

    history = [HistoryMessage(role=m.role, content=m.content) for m in history_rows]
    system_prompt = f"{bot.system_prompt}\n\n{time_context(bot.timezone)}"

    tool_specs = _tool_specs_for_bindings(bindings)
    executor = _make_tool_executor(bot, contact_id, session_factory, redis, storage, bindings)

    loop_result = await run_tool_loop(
        system_prompt,
        history,
        tool_specs,
        executor,
        complete_fn=complete,
        complete_with_tools_fn=complete_with_tools,
    )
    if not loop_result.text.strip():
        logger.warning("LLM returned empty text, not sending", bot_id=str(event.bot_id))
        return

    await _send_reply(event, redis, loop_result.text)

    cost = compute_cost(loop_result.model, loop_result.tokens_in, loop_result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, loop_result.text)
        await record_usage(
            session, event.bot_id, loop_result.model, loop_result.tokens_in, loop_result.tokens_out, cost
        )
        await session.commit()
    await _schedule_follow_up(bot, event.chat_id, contact_id, outgoing_seq)


def _tool_specs_for_bindings(bindings: list[ToolBinding]) -> list[ToolSpec]:
    """Тулзы, включённые боту (tool_bindings), но отсутствующие в реестре
    libs/tools — молча пропускаются: рассинхрон между БД и деплоем кода не
    должен ронять диалог (FEATURES.md 4.13)."""
    specs: list[ToolSpec] = []
    for binding in bindings:
        tool = get_tool(binding.tool_name)
        if tool is None:
            continue
        specs.append(
            ToolSpec(name=tool.name, description=tool.description, parameters_schema=tool.parameters_schema)
        )
    return specs


def _make_tool_executor(
    bot: Bot,
    contact_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    storage: Storage,
    bindings: list[ToolBinding],
) -> ToolExecutor:
    config_by_name = {binding.tool_name: binding.config for binding in bindings}

    async def executor(name: str, arguments: dict[str, Any]) -> str:
        tool = get_tool(name)
        if tool is None:
            raise LookupError(f"tool not in registry: {name}")
        ctx = ToolContext(
            bot=bot,
            contact_id=contact_id,
            session_factory=session_factory,
            redis=redis,
            storage=storage,
            config=config_by_name.get(name, {}),
        )
        return await tool.execute(arguments, ctx)

    return executor
```

- [ ] **Step 5: Запустить новые и существующие тесты worker**

Run: `pytest services/worker/tests -v`
Expected: PASS — все прежние тесты (`test_reply_smoke.py`, `test_vision.py`,
`test_pdf.py`, `test_handoff.py`, `test_blocked_contacts.py`,
`test_media_fallback.py`, `test_followup_scheduling.py` и т.д.) остаются
зелёными (монки-патч `consumer_module.complete` по-прежнему перехватывает
вызов через быстрый путь `run_tool_loop`); новый `test_reply_tools.py` —
3/3 PASS.

- [ ] **Step 6: ruff + mypy**

Run: `ruff check services/worker && mypy services/worker/src`
Expected: без ошибок

- [ ] **Step 7: Commit**

```bash
git add services/worker/src/worker/pipeline/consumer.py services/worker/pyproject.toml services/worker/tests/pipeline/test_reply_tools.py
git commit -m "feat(worker): wire tool loop into text reply pipeline (FEATURES.md 4.13)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: `services/api` — `/bots/{id}/tools`

**Files:**
- Modify: `services/api/pyproject.toml` (добавить `integrations`, `tools`)
- Create: `services/api/src/api/schemas/tool_bindings.py`
- Modify: `services/api/src/api/routers/bots.py`
- Test: `services/api/tests/test_tool_bindings.py`

**Interfaces:**
- Consumes: `db.tool_bindings.{list_enabled, enable, disable}` (Task 2),
  `tools.registry.all_tool_names` (Task 1).
- Produces: `api.schemas.tool_bindings.{ToolBindingIn, ToolBindingOut}`;
  роуты `GET/POST /bots/{id}/tools`, `DELETE /bots/{id}/tools/{tool_name}`.

- [ ] **Step 1: Добавить зависимости в pyproject api**

`services/api/pyproject.toml`:

```toml
dependencies = [
    "core",
    "db",
    "integrations",
    "tools",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "redis>=5.0",
]
```

Run: `pip install -e services/api`

- [ ] **Step 2: Написать тесты (падают — роутов ещё нет)**

`services/api/tests/test_tool_bindings.py`:

```python
"""GET/POST/DELETE /bots/{id}/tools (FEATURES.md 4.13, инфраструктура)."""

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
from db.engine import make_engine, make_session_factory
from db.models import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import registry as tools_registry

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
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_list_is_empty_by_default(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/tools")
    assert response.status_code == 200
    assert response.json() == []


async def test_post_unknown_tool_name_is_rejected(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/tools", json={"tool_name": "does_not_exist"})
    assert response.status_code == 400

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == []


async def test_post_known_tool_name_enables_it_with_config(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(tools_registry._REGISTRY, "search", object())
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/tools", json={"tool_name": "search", "config": {"limit": 3}}
    )
    assert response.status_code == 201
    assert response.json() == {"tool_name": "search", "config": {"limit": 3}}

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == [{"tool_name": "search", "config": {"limit": 3}}]


async def test_post_is_idempotent_and_updates_config(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(tools_registry._REGISTRY, "search", object())
    bot_id = await _make_bot(session_factory)

    await client.post(f"/bots/{bot_id}/tools", json={"tool_name": "search", "config": {"limit": 3}})
    response = await client.post(
        f"/bots/{bot_id}/tools", json={"tool_name": "search", "config": {"limit": 5}}
    )
    assert response.status_code == 201

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == [{"tool_name": "search", "config": {"limit": 5}}]


async def test_delete_removes_tool(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(tools_registry._REGISTRY, "search", object())
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/tools", json={"tool_name": "search"})

    response = await client.delete(f"/bots/{bot_id}/tools/search")
    assert response.status_code == 204

    listing = await client.get(f"/bots/{bot_id}/tools")
    assert listing.json() == []


async def test_delete_unknown_tool_is_still_204(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.delete(f"/bots/{bot_id}/tools/does_not_exist")
    assert response.status_code == 204
```

- [ ] **Step 3: Запустить тесты, убедиться что падают**

Run: `pytest services/api/tests/test_tool_bindings.py -v`
Expected: FAIL (`404 Not Found` — роутов ещё нет)

- [ ] **Step 4: Написать схемы**

`services/api/src/api/schemas/tool_bindings.py`:

```python
"""Pydantic v2 схемы реестра тулз бота (FEATURES.md 4.13)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolBindingIn(BaseModel):
    tool_name: str
    config: dict[str, Any] = Field(default_factory=dict)


class ToolBindingOut(BaseModel):
    tool_name: str
    config: dict[str, Any]
```

- [ ] **Step 5: Добавить роуты в `bots.py`**

`services/api/src/api/routers/bots.py` — добавить импорты (после
существующего `from db.blocked_contacts import ...`):

```python
from db.tool_bindings import disable as disable_tool
from db.tool_bindings import enable as enable_tool
from db.tool_bindings import list_enabled as list_enabled_tools
from tools.registry import all_tool_names
```

и (после `from ..schemas.blocked_contacts import ...`):

```python
from ..schemas.tool_bindings import ToolBindingIn, ToolBindingOut
```

Добавить в конец файла:

```python
@router.get("/{bot_id}/tools", response_model=list[ToolBindingOut])
async def list_tools(bot_id: uuid.UUID, session: SessionDep) -> list[ToolBindingOut]:
    bindings = await list_enabled_tools(session, bot_id)
    return [ToolBindingOut(tool_name=b.tool_name, config=b.config) for b in bindings]


@router.post("/{bot_id}/tools", response_model=ToolBindingOut, status_code=201)
async def add_tool(bot_id: uuid.UUID, body: ToolBindingIn, session: SessionDep) -> ToolBindingOut:
    if body.tool_name not in all_tool_names():
        raise HTTPException(status_code=400, detail=f"unknown tool: {body.tool_name}")
    await enable_tool(session, bot_id, body.tool_name, body.config)
    await session.commit()
    return ToolBindingOut(tool_name=body.tool_name, config=body.config)


@router.delete("/{bot_id}/tools/{tool_name}", status_code=204)
async def delete_tool(bot_id: uuid.UUID, tool_name: str, session: SessionDep) -> None:
    await disable_tool(session, bot_id, tool_name)
    await session.commit()
```

- [ ] **Step 6: Запустить тесты**

Run: `pytest services/api/tests -v`
Expected: PASS — все прежние тесты (`test_bots.py`, `test_blocked_contacts.py`,
`test_gateway_proxy.py`, `test_release.py`) зелёные; новый
`test_tool_bindings.py` — 6/6 PASS.

- [ ] **Step 7: ruff + mypy**

Run: `ruff check services/api && mypy services/api/src`
Expected: без ошибок

- [ ] **Step 8: Commit**

```bash
git add services/api/pyproject.toml services/api/src/api/schemas/tool_bindings.py services/api/src/api/routers/bots.py services/api/tests/test_tool_bindings.py
git commit -m "feat(api): tool_bindings CRUD endpoints (FEATURES.md 4.13)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Живой прогон

Без кода/коммита — только проверка. Ограничение среды: `OPENAI_API_KEY`
не настроен на машине разработки (как в Волне 1), поэтому реальный
tool-calling через настоящий OpenAI недостижим — проверяется то, что
достижимо без него.

- [ ] **Step 1: Полный тестовый прогон**

Run: `pytest`
Expected: весь набор (`libs/*`, `services/worker`, `services/api`,
`services/celery`) зелёный, без regressions в ранее сданных фичах Волны 1.

- [ ] **Step 2: Поднять стек**

Run: `make dev` (в отдельном терминале/фоне), дождаться готовности контейнеров.

- [ ] **Step 3: Применить миграцию и проверить таблицу**

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres psql -U postgres -d platform -c "\d tool_bindings"
```
Expected: колонки `id, bot_id, tool_name, config, created_at`, constraint
`uq_tool_bindings_bot_tool_name`.

- [ ] **Step 4: Проверить worker/api healthy**

```bash
docker compose -f compose/docker-compose.dev.yml ps
```
Expected: `worker`, `api`, `gateway`, `postgres`, `redis` — все `healthy`/`running`.

- [ ] **Step 5: Обычный текстовый диалог отвечает как раньше**

Через реальный тестовый номер (если линкован в этой среде) или напрямую
через `XADD wa:in` с `inbound.text` для существующего тестового бота (тот
же приём, что использовался в Волне 1 для vision/PDF/ретраев) — убедиться,
что сообщение доходит до `_reply()`, деградация на отсутствующий
`OPENAI_API_KEY` та же, что и раньше (лог ошибки LLM, лок снимается, без
краша).

- [ ] **Step 6: Проверить API-эндпоинт живым `curl`**

```bash
curl -s -X POST http://localhost:8000/bots/<bot_id>/tools \
  -H "Content-Type: application/json" \
  -d '{"tool_name": "does_not_exist"}'
```
Expected: `400`, `{"detail": "unknown tool: does_not_exist"}` — реестр
пуст в этой итерации, это ожидаемый и единственно возможный на данном шаге
результат (см. спеку, раздел "Границы этой итерации").

```bash
curl -s http://localhost:8000/bots/<bot_id>/tools
```
Expected: `[]`.

- [ ] **Step 7: Обновить память проекта**

Дописать в `stage1-core-progress.md` (или завести отдельную заметку про
Волну 2) факт сдачи инфраструктуры тулз + 4.13, со ссылкой на спеку/план,
и что дальше — 4.1 pgvector-поиск (первая настоящая тулза).

---

## Самопроверка плана (writing-plans skill)

- **Покрытие спеки**: §2 (`complete_with_tools`) → Task 3; §3
  (`run_tool_loop`, встраивание в `_reply`) → Task 4+5; §4 (`libs/tools`)
  → Task 1; §5 (БД) → Task 2; §6 (API) → Task 6; §7 (тесты) → распределены
  по задачам 1-6; §"Границы итерации" → явно проверено в Task 7 Step 6.
- **Плейсхолдеры**: не найдено — каждый шаг содержит готовый код или
  точную команду.
- **Согласованность типов**: `ToolCall.arguments_json` (не `arguments:
  dict`, как в черновике спеки в чате — уточнено при планировании: разбор
  JSON и обработка ошибки парсинга — ответственность `tool_loop.py`, не
  `client.py`, см. Interfaces Task 3) используется одинаково в Task 3/4/5.
  `run_tool_loop` делает ровно `max_rounds` обычных раундов + один
  `force_text`-раунд при исчерпании — соответствует тексту спеки п.3.4 и
  тесту `test_max_rounds_exhausted_forces_final_text_call`.
