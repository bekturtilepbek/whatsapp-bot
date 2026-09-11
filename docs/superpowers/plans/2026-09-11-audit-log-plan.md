# Аудит-лог действий Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Записывать в новую таблицу `audit_log` каждую успешную мутацию
в 19 существующих HTTP-роутах `api` (кто/что/когда) и дать владельцу
платформы экран для просмотра лога в кабинете.

**Architecture:** Один общий ASGI-middleware (`services/api/src/api/audit.py`)
перехватывает все `POST`/`PATCH`/`DELETE`/`PUT`-запросы, сверяет
`(method, route.path)` со статическим реестром `ACTION_REGISTRY`, пишет
запись в `audit_log` через свою отдельную DB-сессию — ни один файл в
`services/api/src/api/routers/` не меняется. Owner-only `GET /audit-log`
+ экран `/audit-log` в admin-web читают эту таблицу.

**Tech Stack:** FastAPI (middleware `@app.middleware("http")`), SQLAlchemy
2.0 async + Alembic (новая таблица), Next.js 15 App Router (новый экран).

**Spec:** `docs/superpowers/specs/2026-09-11-audit-log-design.md`

## Global Constraints

- **Payload — три уровня fallback, именно в этом порядке**: (1) тело
  ОТВЕТА, если `Content-Type` начинается с `application/json` и тело
  непустое; (2) тело ЗАПРОСА (закэшированное `await request.body()` ДО
  `call_next`), если ответ пуст, запрос не в `MULTIPART_ROUTES`,
  `Content-Type` запроса — `application/json`, тело непустое; (3)
  `dict(request.path_params)` (UUID → `str`).
- **`MULTIPART_ROUTES`** — ровно 3 маршрута: `("POST", "/bots/{bot_id}/products")`,
  `("POST", "/bots/{bot_id}/products/{product_id}/photos")`,
  `("POST", "/bots/{bot_id}/documents")`. Для них тело запроса не читается
  вообще (экономия памяти — файлы/фото).
- **Ошибка записи в аудит-лог никогда не должна ронять исходный запрос**
  — весь блок «декодировать actor → определить payload → записать в БД»
  обёрнут в `try/except Exception` с `logger.warning(..., exc_info=True)`
  (`structlog`, тот же паттерн, что уже есть в `services/api/src/api/main.py`
  для `_bootstrap_platform_owner`), исходный `response` возвращается как
  есть в любом случае.
- **Аудит только успешных мутаций**: `response.status_code` не в диапазоне
  200-299 → ничего не пишем. Роут не в `ACTION_REGISTRY` → ничего не
  пишем (не баг, документированное поведение — новый роут регистрируется
  одной строкой в реестре, без этого он молча не аудируется).
- **Своя сессия, не сессия роута**: middleware вне графа FastAPI DI —
  пишет через `app.state.audit_session_factory` (если не `None` — тесты
  подставляют туда testcontainers-фабрику) либо, в продакшене, через
  `db.get_session_factory()` (реальный `DATABASE_URL`). Использовать
  `getattr(request.app.state, "audit_session_factory", None)`, НЕ прямое
  обращение через точку — в проде атрибут никогда явно не выставляется
  (`State` кидает `AttributeError` на незаданный атрибут, не `None`).
- `/auth/login`, `/auth/me` — вне `ACTION_REGISTRY`, не аудируются
  (аутентификация — другая тема, не «поменял конфиг»).

---

### Task 1: Схема `audit_log` + CRUD-модуль в libs/db

**Files:**
- Modify: `libs/db/src/db/models.py` — добавить класс `AuditLog` в конец файла.
- Create: `libs/db/migrations/versions/202609111001_audit_log.py`
- Create: `libs/db/src/db/audit_log.py`
- Test: `libs/db/tests/test_audit_log.py`

**Interfaces:**
- Produces: `AuditLog` (ORM-модель, `libs/db/src/db/models.py`);
  `create_entry(session, *, actor_user_id: uuid.UUID, bot_id: uuid.UUID | None, action: str, payload: dict[str, Any] | None) -> AuditLog`;
  `AuditLogEntry` (dataclass: `id, actor_user_id, actor_email, bot_id, bot_name, action, payload, created_at`);
  `list_entries(session, *, bot_id: uuid.UUID | None = None, actor_user_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0) -> list[AuditLogEntry]`
  — обе функции в `libs/db/src/db/audit_log.py`. Task 2/4 зависят от этих
  точных имён и сигнатур.

- [ ] **Step 1: Добавить модель `AuditLog` в `libs/db/src/db/models.py`**

В самый конец файла (после класса `BotAccess`):

```python
class AuditLog(Base):
    """Кто и когда поменял промпт/настройки/товар и т.п. (FEATURES.md 6.19).
    Пишется ASGI-middleware (services/api/src/api/audit.py), не роутами
    напрямую — эта модель только хранит запись."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_bot_id", "bot_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

Все использованные имена (`Index`, `ForeignKey`, `String`, `JSONB`,
`DateTime`, `func`, `text`, `Mapped`, `mapped_column`, `UUID`, `Any`,
`datetime`, `uuid`) уже импортированы в начале файла — новых импортов
не требуется.

- [ ] **Step 2: Написать миграцию**

`libs/db/migrations/versions/202609111001_audit_log.py` — `down_revision`
берём из текущего HEAD миграций (на момент написания это
`"202609110001"`, файл `202609110001_users_and_bot_access.py`; **если к
моменту выполнения этой задачи появилась более новая миграция — взять
её revision id вместо этого**, проверить командой
`ls -t libs/db/migrations/versions/*.py | head -1`):

```python
"""audit_log

Revision ID: 202609111001
Revises: 202609110001
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609111001"
down_revision: str | None = "202609110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_bot_id", "audit_log", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_bot_id", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
```

- [ ] **Step 3: Написать `libs/db/src/db/audit_log.py`**

```python
"""Аудит-лог действий (FEATURES.md 6.19). Пишется ASGI-middleware
(services/api/src/api/audit.py) через собственную сессию — не роутами
напрямую.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog, Bot, User


async def create_entry(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    bot_id: uuid.UUID | None,
    action: str,
    payload: dict[str, Any] | None,
) -> AuditLog:
    entry = AuditLog(actor_user_id=actor_user_id, bot_id=bot_id, action=action, payload=payload)
    session.add(entry)
    await session.flush()
    return entry


@dataclass
class AuditLogEntry:
    id: uuid.UUID
    actor_user_id: uuid.UUID
    actor_email: str
    bot_id: uuid.UUID | None
    bot_name: str | None
    action: str
    payload: dict[str, Any] | None
    created_at: datetime


async def list_entries(
    session: AsyncSession,
    *,
    bot_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLogEntry]:
    """JOIN на users/bots за один запрос — экран не должен слать
    отдельный запрос на email/имя бота на каждую строку (тот же принцип,
    что list_bots подмешивает phone/linked_at, а не N+1)."""
    stmt = (
        select(AuditLog, User.email, Bot.name)
        .join(User, User.id == AuditLog.actor_user_id)
        .outerjoin(Bot, Bot.id == AuditLog.bot_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if bot_id is not None:
        stmt = stmt.where(AuditLog.bot_id == bot_id)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)

    result = await session.execute(stmt)
    return [
        AuditLogEntry(
            id=entry.id,
            actor_user_id=entry.actor_user_id,
            actor_email=actor_email,
            bot_id=entry.bot_id,
            bot_name=bot_name,
            action=entry.action,
            payload=entry.payload,
            created_at=entry.created_at,
        )
        for entry, actor_email, bot_name in result.all()
    ]
```

- [ ] **Step 4: Написать тест `libs/db/tests/test_audit_log.py`**

Точный boilerplate testcontainers-фикстур — скопировать 1:1 из
`libs/db/tests/test_bot_access.py` (`_docker_available`, `pytestmark`,
`database_url` fixture, `session` fixture) — они идентичны байт-в-байт
во всех тестах `libs/db/tests/`, отдельного общего conftest.py в этой
директории нет (в отличие от `services/worker/tests/pipeline/`, не
трогать эту директорию в рамках этой задачи — не в скоупе).

```python
"""audit_log: create_entry/list_entries (FEATURES.md 6.19).

Требует Docker (testcontainers). Без него — skip, не fail.
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
from db.audit_log import create_entry, list_entries
from db.bots import create_bot
from db.engine import make_engine, make_session_factory
from db.models import User
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


async def _make_user(session: AsyncSession, *, email: str = "owner@example.com") -> uuid.UUID:
    user = User(email=email, password_hash="unused", is_platform_owner=True, is_active=True)
    session.add(user)
    await session.flush()
    await session.commit()
    return user.id


async def test_create_entry_and_list_returns_it_with_actor_email(session: AsyncSession) -> None:
    user_id = await _make_user(session)
    bot_id = (await create_bot(session, name="test-bot")).id
    await session.commit()

    await create_entry(
        session,
        actor_user_id=user_id,
        bot_id=bot_id,
        action="bots.update",
        payload={"name": "новое имя"},
    )
    await session.commit()

    entries = await list_entries(session)
    assert len(entries) == 1
    assert entries[0].actor_email == "owner@example.com"
    assert entries[0].bot_id == bot_id
    assert entries[0].bot_name == "test-bot"
    assert entries[0].action == "bots.update"
    assert entries[0].payload == {"name": "новое имя"}


async def test_list_entries_filters_by_bot_id(session: AsyncSession) -> None:
    user_id = await _make_user(session)
    bot_a = (await create_bot(session, name="bot-a")).id
    bot_b = (await create_bot(session, name="bot-b")).id
    await session.commit()

    await create_entry(session, actor_user_id=user_id, bot_id=bot_a, action="bots.update", payload=None)
    await create_entry(session, actor_user_id=user_id, bot_id=bot_b, action="bots.update", payload=None)
    await session.commit()

    entries = await list_entries(session, bot_id=bot_a)
    assert len(entries) == 1
    assert entries[0].bot_id == bot_a


async def test_list_entries_orders_newest_first(session: AsyncSession) -> None:
    user_id = await _make_user(session)
    await create_entry(session, actor_user_id=user_id, bot_id=None, action="users.create", payload=None)
    await create_entry(session, actor_user_id=user_id, bot_id=None, action="users.update", payload=None)
    await session.commit()

    entries = await list_entries(session)
    assert [e.action for e in entries] == ["users.update", "users.create"]


async def test_list_entries_respects_limit_and_offset(session: AsyncSession) -> None:
    user_id = await _make_user(session)
    for i in range(5):
        await create_entry(
            session, actor_user_id=user_id, bot_id=None, action=f"users.create.{i}", payload=None
        )
    await session.commit()

    page = await list_entries(session, limit=2, offset=2)
    assert len(page) == 2


async def test_platform_level_entry_has_null_bot_id_and_bot_name(session: AsyncSession) -> None:
    user_id = await _make_user(session)
    await create_entry(session, actor_user_id=user_id, bot_id=None, action="users.create", payload=None)
    await session.commit()

    entries = await list_entries(session)
    assert entries[0].bot_id is None
    assert entries[0].bot_name is None
```

- [ ] **Step 5: Прогнать тест**

Run: `cd libs/db && ../../.venv/Scripts/python.exe -m pytest tests/test_audit_log.py -v`
Expected: 5 passed (Docker должен быть доступен и поднят — если нет,
пропущено с skip, тоже приемлемый результат для этого шага, но
предпочтительно проверить с реальным Docker перед коммитом).

- [ ] **Step 6: Прогнать mypy и ruff на изменённые файлы**

Run (из корня репозитория): `.venv/Scripts/python.exe -m mypy libs/db/src` и `.venv/Scripts/python.exe -m ruff check libs/db/src libs/db/tests`
Expected: чисто, без новых ошибок.

- [ ] **Step 7: Commit**

```bash
git add libs/db/src/db/models.py libs/db/migrations/versions/202609111001_audit_log.py libs/db/src/db/audit_log.py libs/db/tests/test_audit_log.py
git commit -m "feat(db): add audit_log table and CRUD module (FEATURES.md 6.19)"
```

---

### Task 2: Middleware — перехват мутаций + запись в аудит-лог

**Files:**
- Modify: `services/api/src/api/db.py` — переименовать `_get_session_factory` → `get_session_factory` (убрать подчёркивание), обновить единственный внутренний вызов в `get_session()`.
- Create: `services/api/src/api/audit.py`
- Modify: `services/api/src/api/main.py` — зарегистрировать middleware.
- Test: `services/api/tests/test_audit_log.py` (новый файл — часть write-пути; Task 4 допишет в этот же файл тесты read-эндпоинта).

**Interfaces:**
- Consumes: `create_entry` из Task 1 (`libs.db.audit_log`); `decode_access_token` из `services/api/src/api/security.py` (уже существует, сигнатура `(token: str) -> uuid.UUID`, бросает `jwt.InvalidTokenError`).
- Produces: `audit_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response` (`services/api/src/api/audit.py`) — зарегистрирован в `main.py`; `ACTION_REGISTRY: dict[tuple[str, str], str]`, `MULTIPART_ROUTES: frozenset[tuple[str, str]]` (оба в `audit.py`, Task 4/будущие роуты читают `ACTION_REGISTRY` как справочник, не импортируют программно); контракт `app.state.audit_session_factory: async_sessionmaker[AsyncSession] | None` — Task 3 использует этот же атрибут в тестовых фикстурах.

- [ ] **Step 1: Переименовать `_get_session_factory` в `services/api/src/api/db.py`**

Текущее содержимое (`services/api/src/api/db.py:17-24`):

```python
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _get_session_factory()() as session:
        yield session
```

Заменить на (убрано ведущее подчёркивание у функции — используется из
`audit.py`, другого модуля того же пакета, тянуть приватное имя явным
импортом — плохой знак; сам модульный кэш `_session_factory` остаётся
приватным, это деталь реализации):

```python
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
```

- [ ] **Step 2: Написать `services/api/src/api/audit.py`**

```python
"""ASGI-middleware, пишущий аудит-лог (FEATURES.md 6.19) на каждую
успешную мутацию — без единой правки в routers/*.py.

Реестр ACTION_REGISTRY — единственное расширяемое место: новый
мутирующий роут в будущем добавляется сюда одной строкой; без записи в
реестре роут просто не аудируется, тихо (документированное поведение,
не баг). Три-уровневый fallback payload'а и все технические ограничения
см. docs/superpowers/specs/2026-09-11-audit-log-design.md.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
import structlog
from db.audit_log import create_entry
from fastapi import Request
from starlette.responses import Response

from .db import get_session_factory
from .security import decode_access_token

logger = structlog.get_logger("api.audit")

AUDIT_METHODS = frozenset({"POST", "PATCH", "DELETE", "PUT"})

ACTION_REGISTRY: dict[tuple[str, str], str] = {
    ("POST", "/bots"): "bots.create",
    ("PATCH", "/bots/{bot_id}"): "bots.update",
    ("POST", "/bots/{bot_id}/logout"): "bots.logout",
    ("POST", "/bots/{bot_id}/chats/{chat_id}/release"): "bots.release_chat",
    ("POST", "/bots/{bot_id}/blocked-numbers"): "blocked_numbers.create",
    ("DELETE", "/bots/{bot_id}/blocked-numbers/{phone}"): "blocked_numbers.delete",
    ("POST", "/bots/{bot_id}/tools"): "tools.create",
    ("DELETE", "/bots/{bot_id}/tools/{tool_name}"): "tools.delete",
    ("POST", "/bots/{bot_id}/documents"): "documents.create",
    ("DELETE", "/bots/{bot_id}/documents/{document_id}"): "documents.delete",
    ("POST", "/bots/{bot_id}/products"): "products.create",
    ("PATCH", "/bots/{bot_id}/products/{product_id}"): "products.update",
    ("DELETE", "/bots/{bot_id}/products/{product_id}"): "products.delete",
    ("POST", "/bots/{bot_id}/products/{product_id}/photos"): "product_photos.create",
    ("DELETE", "/bots/{bot_id}/products/{product_id}/photos/{photo_id}"): "product_photos.delete",
    ("POST", "/users"): "users.create",
    ("PATCH", "/users/{user_id}"): "users.update",
    ("POST", "/users/{user_id}/bot-access"): "bot_access.grant",
    ("DELETE", "/users/{user_id}/bot-access/{bot_id}"): "bot_access.revoke",
}

# Тело запроса НЕ читается вообще для этих роутов (multipart — файлы/фото,
# бессмысленно и дорого буферить в память ради аудит-лога). Payload для
# них всегда берётся из ответа (все три возвращают JSON-объект).
MULTIPART_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/bots/{bot_id}/products"),
        ("POST", "/bots/{bot_id}/products/{product_id}/photos"),
        ("POST", "/bots/{bot_id}/documents"),
    }
)


def _json_safe_path_params(path_params: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) for k, v in path_params.items()}


async def audit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method not in AUDIT_METHODS:
        return await call_next(request)

    is_multipart = request.headers.get("content-type", "").startswith("multipart/")
    request_body: bytes | None = None
    if not is_multipart:
        # Кэшируется Starlette'ом — роут ниже читает те же байты повторно,
        # парсинг Pydantic-моделью не ломается.
        request_body = await request.body()

    response = await call_next(request)

    if not (200 <= response.status_code < 300):
        return response

    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path is None:
        return response

    action = ACTION_REGISTRY.get((request.method, route_path))
    if action is None:
        return response

    # Response — StreamingResponse (BaseHTTPMiddleware) — тело читается
    # один раз через body_iterator, дальше нужно вернуть НОВЫЙ Response с
    # теми же байтами, иначе клиент получит пустой ответ.
    response_body = b""
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        response_body += chunk
    rebuilt_response = Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )

    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return rebuilt_response
        actor_user_id = decode_access_token(auth_header.removeprefix("Bearer "))

        bot_id_raw = request.path_params.get("bot_id")
        bot_id = uuid.UUID(bot_id_raw) if bot_id_raw else None

        payload: dict[str, Any] | None = None
        response_content_type = response.headers.get("content-type", "")
        if response_content_type.startswith("application/json") and response_body:
            payload = json.loads(response_body)
        elif (
            (request.method, route_path) not in MULTIPART_ROUTES
            and request_body
            and request.headers.get("content-type", "").startswith("application/json")
        ):
            payload = json.loads(request_body)
        else:
            path_params = dict(request.path_params)
            if path_params:
                payload = _json_safe_path_params(path_params)

        session_factory = getattr(request.app.state, "audit_session_factory", None)
        if session_factory is None:
            session_factory = get_session_factory()

        async with session_factory() as session:
            await create_entry(
                session,
                actor_user_id=actor_user_id,
                bot_id=bot_id,
                action=action,
                payload=payload,
            )
            await session.commit()
    except (jwt.InvalidTokenError, Exception):
        logger.warning("audit_log_write_failed", action=action, exc_info=True)

    return rebuilt_response
```

- [ ] **Step 3: Зарегистрировать middleware в `services/api/src/api/main.py`**

Добавить импорт и вызов сразу после создания `app`:

```python
from .audit import audit_middleware
```

(добавить к существующему блоку импортов из `.routers`/`.security`)

```python
app = FastAPI(title="platform-api", lifespan=lifespan)

app.middleware("http")(audit_middleware)
```

(строка `app.middleware("http")(audit_middleware)` — сразу после
`app = FastAPI(...)`, до `app.include_router(...)`).

- [ ] **Step 4: Написать `services/api/tests/test_audit_log.py`**

Копирует boilerplate testcontainers/`client`-фикстуры из
`services/api/tests/test_bots.py` (`_docker_available`, `database_url`,
`session_factory`, `override_owner_auth` из `tests.auth_helpers`) —
ОДНО отличие от всех остальных 8 файлов с таким же `client`
(перечислены в Task 3): эта фикстура ЕДИНСТВЕННАЯ, которой обязательно
с самого начала нужен `app.state.audit_session_factory`, потому что
тесты этого файла ПРОВЕРЯЮТ содержимое аудит-лога.

```python
"""ASGI-middleware аудит-лога (FEATURES.md 6.19): что должно/не должно
попадать в audit_log при мутирующих запросах. GET /audit-log — см.
Task 4 этого же файла.

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
from db.audit_log import list_entries
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


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.state.audit_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None


async def _make_bot(session_factory: async_sessionmaker[AsyncSession], *, name: str = "test-bot") -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name=name, enabled=True, system_prompt="", timezone="Asia/Bishkek", settings={})
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_successful_patch_creates_audit_entry_with_response_payload(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "Новое имя"})
    assert response.status_code == 200

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    assert len(entries) == 1
    assert entries[0].action == "bots.update"
    assert entries[0].payload is not None
    assert entries[0].payload["name"] == "Новое имя"


async def test_successful_delete_creates_audit_entry_with_path_params_payload(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    response = await client.delete(f"/bots/{bot_id}/blocked-numbers/996700000000")
    assert response.status_code == 204

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    delete_entries = [e for e in entries if e.action == "blocked_numbers.delete"]
    assert len(delete_entries) == 1
    assert delete_entries[0].payload == {"bot_id": str(bot_id), "phone": "996700000000"}


async def test_failed_request_does_not_create_audit_entry(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "   "})
    assert response.status_code == 422

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    assert entries == []


async def test_unregistered_route_does_not_create_audit_entry(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _make_bot(session_factory)
    response = await client.get("/bots")
    assert response.status_code == 200

    async with session_factory() as session:
        entries = await list_entries(session)
    assert entries == []


async def test_grant_bot_access_records_bot_id_from_request_body(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Единственный роут, где payload берётся из тела ЗАПРОСА (уровень 2
    fallback) — ответ 204, bot_id только в теле {"bot_id": ...}."""
    from db.users import create_user

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        user = await create_user(session, email="client@example.com", password_hash="unused")
        await session.commit()
        user_id = user.id

    response = await client.post(f"/users/{user_id}/bot-access", json={"bot_id": str(bot_id)})
    assert response.status_code == 204

    async with session_factory() as session:
        entries = await list_entries(session)
    grant_entries = [e for e in entries if e.action == "bot_access.grant"]
    assert len(grant_entries) == 1
    assert grant_entries[0].payload == {"bot_id": str(bot_id)}


async def test_multipart_document_upload_records_response_payload_not_request_body(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    files = {"file": ("price.pdf", b"%PDF-1.4 fake content", "application/pdf")}
    response = await client.post(f"/bots/{bot_id}/documents", files=files)
    assert response.status_code == 201

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    create_entries = [e for e in entries if e.action == "documents.create"]
    assert len(create_entries) == 1
    assert create_entries[0].payload is not None
    assert create_entries[0].payload["filename"] == "price.pdf"
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd services/api && ../../.venv/Scripts/python.exe -m pytest tests/test_audit_log.py -v`
Expected: 6 passed.

- [ ] **Step 6: Прогнать ПОЛНЫЙ существующий набор тестов `services/api`**

Это критическая проверка — middleware теперь оборачивает КАЖДЫЙ запрос
в приложении, включая все существующие тесты. Ожидается, что все они
по-прежнему проходят (middleware для них молча не пишет аудит-запись —
`app.state.audit_session_factory` не выставлен, `get_session_factory()`
упадёт на отсутствующем `DATABASE_URL`, ошибка проглочена try/except).

Run: `cd services/api && ../../.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -60`
Expected: все тесты, что проходили ДО этой задачи, проходят и сейчас
(число пройденных тестов не уменьшилось; новые 6 добавились). Если
что-то упало — это находка, а не повод менять чужой тест без понимания
причины: разобраться, почему именно, прежде чем трогать что-либо за
пределами `audit.py`/`main.py`/`db.py`.

- [ ] **Step 7: Прогнать mypy и ruff**

Run: `.venv/Scripts/python.exe -m mypy services/api/src` и `.venv/Scripts/python.exe -m ruff check services/api/src services/api/tests`
Expected: чисто. Один нюанс, который может потребовать `# type: ignore` —
уже проставлен в коде выше на `response.body_iterator` (атрибут есть у
`StreamingResponse`, но не у базового `Response`, а `call_next`
типизирован как возвращающий `Response`).

- [ ] **Step 8: Commit**

```bash
git add services/api/src/api/db.py services/api/src/api/audit.py services/api/src/api/main.py services/api/tests/test_audit_log.py
git commit -m "feat(api): audit-log middleware writes on every successful mutation (FEATURES.md 6.19)"
```

---

### Task 3: Подключить `audit_session_factory` в 8 существующих тестовых фикстурах

**Почему отдельная задача:** без этого 8 существующих Docker-gated
тестовых файлов молча идут через try/except-fallback (не ошибка, но и
не показательно — их мутирующие запросы НЕ будут по-настоящему
аудироваться в тестовом прогоне, только в проде). Подключение делает
поведение консистентным везде и снижает риск, что реальный баг в
middleware останется незамеченным, потому что 90% тестов его не
упражняют по-настоящему. Механическая, однотипная правка — один
диспатч на все 8 файлов сразу (SDD: batch same-shape work).

**Files:**
- Modify: `services/api/tests/test_auth.py`
- Modify: `services/api/tests/test_blocked_contacts.py`
- Modify: `services/api/tests/test_bots.py`
- Modify: `services/api/tests/test_documents_router.py`
- Modify: `services/api/tests/test_products.py`
- Modify: `services/api/tests/test_prompt_versions.py`
- Modify: `services/api/tests/test_tool_bindings.py`
- Modify: `services/api/tests/test_users_router.py`

(`test_gateway_proxy.py` и `test_release.py` НЕ трогать — их `client`
fixture использует `_unused_session`, заглушку без реального
testcontainers `session_factory` в области видимости; middleware для
них по-прежнему уходит в try/except-fallback, это ожидаемо и корректно.)

**Interfaces:**
- Consumes: контракт `app.state.audit_session_factory` из Task 2 —
  ничего нового не производит, чисто потребляющая задача.

Во ВСЕХ 8 файлах — одна и та же правка. Пример на `test_bots.py`
(строки `services/api/tests/test_bots.py:65-79`, уже показаны в общем
контексте выше в этом плане при исследовании — текущий вид):

```python
@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

Меняется на (добавлены ровно 2 строки — установка ПОСЛЕ
`app.dependency_overrides[get_session] = override_get_session` и сброс
ПОСЛЕ `app.dependency_overrides.clear()`):

```python
@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.state.audit_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None
```

- [ ] **Step 1: Применить эту же правку во всех 8 файлах**

Найти в каждом файле его собственную `client`-фикстуру (имя переменной
сессии может отличаться — где-то `session_factory` в параметре
фикстуры, всегда есть строка `app.dependency_overrides[get_session] = override_get_session`
и позже `app.dependency_overrides.clear()`) и вставить ровно те же две
строки в тех же двух местах: `app.state.audit_session_factory = session_factory`
сразу после установки `dependency_overrides[get_session]`,
`app.state.audit_session_factory = None` сразу после
`app.dependency_overrides.clear()`.

- [ ] **Step 2: Прогнать полный набор тестов `services/api`**

Run: `cd services/api && ../../.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -60`
Expected: все тесты проходят (то же количество passed, что и в конце
Task 2 — эта задача ничего не добавляет и не убирает тестов, только
делает существующие честнее).

- [ ] **Step 3: Прогнать ruff**

Run: `.venv/Scripts/python.exe -m ruff check services/api/tests`
Expected: чисто.

- [ ] **Step 4: Commit**

```bash
git add services/api/tests/test_auth.py services/api/tests/test_blocked_contacts.py services/api/tests/test_bots.py services/api/tests/test_documents_router.py services/api/tests/test_products.py services/api/tests/test_prompt_versions.py services/api/tests/test_tool_bindings.py services/api/tests/test_users_router.py
git commit -m "test(api): wire audit_session_factory into existing test client fixtures"
```

---

### Task 4: `GET /audit-log` — owner-only ручка чтения

**Files:**
- Create: `services/api/src/api/schemas/audit_log.py`
- Create: `services/api/src/api/routers/audit_log.py`
- Modify: `services/api/src/api/main.py` — зарегистрировать новый роутер.
- Test: `services/api/tests/test_audit_log.py` (тот же файл, что Task 2 — дописать тесты в конец).

**Interfaces:**
- Consumes: `list_entries`, `AuditLogEntry` из Task 1 (`libs.db.audit_log`); `PlatformOwner` из `services/api/src/api/security.py` (уже существует).
- Produces: `AuditLogOut` (`services/api/src/api/schemas/audit_log.py`); ничего, что зависит от последующих задач.

- [ ] **Step 1: Написать `services/api/src/api/schemas/audit_log.py`**

```python
"""Pydantic v2 схема ответа аудит-лога (FEATURES.md 6.19)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: UUID
    actor_user_id: UUID
    actor_email: str
    bot_id: UUID | None
    bot_name: str | None
    action: str
    payload: dict[str, Any] | None
    created_at: datetime
```

- [ ] **Step 2: Написать `services/api/src/api/routers/audit_log.py`**

```python
"""GET /audit-log (FEATURES.md 6.19) — owner-only, записи пишет
ASGI-middleware (services/api/src/api/audit.py), не этот роутер.
"""

from __future__ import annotations

import uuid

from db.audit_log import list_entries
from fastapi import APIRouter, Query

from ..db import SessionDep
from ..schemas.audit_log import AuditLogOut
from ..security import PlatformOwner

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

AUDIT_LOG_DEFAULT_LIMIT = 50
AUDIT_LOG_MAX_LIMIT = 200


@router.get("", response_model=list[AuditLogOut])
async def list_audit_log(
    session: SessionDep,
    _owner: PlatformOwner,
    bot_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    limit: int = Query(AUDIT_LOG_DEFAULT_LIMIT, ge=1, le=AUDIT_LOG_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[AuditLogOut]:
    entries = await list_entries(
        session, bot_id=bot_id, actor_user_id=actor_user_id, limit=limit, offset=offset
    )
    return [
        AuditLogOut(
            id=e.id,
            actor_user_id=e.actor_user_id,
            actor_email=e.actor_email,
            bot_id=e.bot_id,
            bot_name=e.bot_name,
            action=e.action,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in entries
    ]
```

- [ ] **Step 3: Зарегистрировать роутер в `services/api/src/api/main.py`**

```python
from .routers import audit_log, auth, bots, documents, products, users
```

(заменить существующую строку `from .routers import auth, bots, documents, products, users`)

```python
app.include_router(audit_log.router)
app.include_router(auth.router)
app.include_router(bots.router)
app.include_router(documents.router)
app.include_router(products.router)
app.include_router(users.router)
```

(добавить `app.include_router(audit_log.router)` в существующий блок
`include_router`-вызовов — порядок среди роутеров не важен).

- [ ] **Step 4: Дописать тесты в `services/api/tests/test_audit_log.py`**

Добавить в конец файла (использует ту же `client`/`session_factory`
фикстуру, что уже есть в файле после Task 2):

```python
async def test_get_audit_log_returns_entries_newest_first(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"name": "Раз"})
    await client.patch(f"/bots/{bot_id}", json={"name": "Два"})

    response = await client.get("/audit-log")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["payload"]["name"] == "Два"
    assert body[1]["payload"]["name"] == "Раз"
    assert body[0]["actor_email"]


async def test_get_audit_log_filters_by_bot_id(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_a = await _make_bot(session_factory, name="bot-a")
    bot_b = await _make_bot(session_factory, name="bot-b")
    await client.patch(f"/bots/{bot_a}", json={"name": "A изменён"})
    await client.patch(f"/bots/{bot_b}", json={"name": "B изменён"})

    response = await client.get(f"/audit-log?bot_id={bot_a}")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["bot_id"] == str(bot_a)


async def test_get_audit_log_respects_limit(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    for i in range(3):
        await client.patch(f"/bots/{bot_id}", json={"name": f"Имя {i}"})

    response = await client.get("/audit-log?limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_audit_log_non_owner_returns_403(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from api.security import get_current_user
    from datetime import datetime
    from db.models import User

    client_user = User(
        id=uuid.uuid4(),
        email="client@example.com",
        password_hash="unused",
        is_platform_owner=False,
        is_active=True,
        created_at=datetime.now(),
    )
    app.dependency_overrides[get_current_user] = lambda: client_user

    response = await client.get("/audit-log")
    assert response.status_code == 403
```

- [ ] **Step 5: Прогнать тесты**

Run: `cd services/api && ../../.venv/Scripts/python.exe -m pytest tests/test_audit_log.py -v`
Expected: 10 passed (6 из Task 2 + 4 новых).

- [ ] **Step 6: Прогнать полный набор + mypy + ruff**

Run: `cd services/api && ../../.venv/Scripts/python.exe -m pytest -v 2>&1 | tail -40` затем из корня
`.venv/Scripts/python.exe -m mypy services/api/src` и `.venv/Scripts/python.exe -m ruff check services/api/src services/api/tests`
Expected: всё чисто, ничего не сломано.

- [ ] **Step 7: Commit**

```bash
git add services/api/src/api/schemas/audit_log.py services/api/src/api/routers/audit_log.py services/api/src/api/main.py services/api/tests/test_audit_log.py
git commit -m "feat(api): GET /audit-log read endpoint, owner-only (FEATURES.md 6.19)"
```

---

### Task 5: Экран `/audit-log` в admin-web

**Files:**
- Modify: `services/admin-web/lib/api.ts` — добавить `AuditLogEntry` тип и `fetchAuditLog`.
- Create: `services/admin-web/components/AuditLogTable.tsx`
- Test: `services/admin-web/components/AuditLogTable.test.tsx`
- Create: `services/admin-web/app/audit-log/page.tsx`
- Modify: `services/admin-web/components/AppHeader.tsx` — добавить ссылку.

**Interfaces:**
- Consumes: `GET /audit-log` из Task 4 (query-параметры `bot_id`, `limit`, `offset`); `fetchBots`, `Bot`, `apiFetch`/`normalizeBaseUrl` (уже существуют в `lib/api.ts`); `currentUserIsOwner` (`lib/currentUser.ts`, уже существует).
- Produces: ничего, что нужно последующим задачам — последняя задача плана.

- [ ] **Step 1: Добавить в `services/admin-web/lib/api.ts`**

Вставить после блока «Пользователи кабинета» (после `patchUser`, перед
концом файла — рядом с однотипными `fetch*`-функциями):

```typescript
// Аудит-лог (FEATURES.md 6.19, только для владельца платформы).

export interface AuditLogEntry {
  id: string;
  actor_user_id: string;
  actor_email: string;
  bot_id: string | null;
  bot_name: string | null;
  action: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface FetchAuditLogOptions {
  botId?: string;
  limit?: number;
  offset?: number;
}

export async function fetchAuditLog(
  baseUrl: string,
  options?: FetchAuditLogOptions,
): Promise<AuditLogEntry[]> {
  const base = normalizeBaseUrl(baseUrl);
  const query = new URLSearchParams();
  if (options?.botId) {
    query.set("bot_id", options.botId);
  }
  if (options?.limit !== undefined) {
    query.set("limit", String(options.limit));
  }
  if (options?.offset !== undefined) {
    query.set("offset", String(options.offset));
  }
  const qs = query.toString();
  const res = await apiFetch(`${base}/audit-log${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /audit-log failed: ${res.status}`);
  }
  return (await res.json()) as AuditLogEntry[];
}
```

- [ ] **Step 2: Написать тест `services/admin-web/lib/api.test.ts`-стиля проверку не требуется отдельно** — существующий `lib/api.test.ts` тестирует другие функции по образцу; для `fetchAuditLog` тестовое покрытие идёт через компонент (Step 4 ниже), отдельный юнит-тест на голую функцию fetch не добавляется — тот же выбор, что уже сделан для остальных `fetch*`-функций в этом файле (ни одна из них не тестируется изолированно, только через компоненты, которые их вызывают).

- [ ] **Step 3: Написать `services/admin-web/components/AuditLogTable.tsx`**

```tsx
"use client";

import { useState } from "react";
import { fetchAuditLog, type AuditLogEntry, type Bot } from "@/lib/api";

interface AuditLogTableProps {
  apiBaseUrl: string;
  entries: AuditLogEntry[];
  bots: Bot[];
  /** Совпадает с лимитом, которым страница делала первый fetchAuditLog —
   * тот же приём, что в BlockedNumbersTable/ProductsTable: пришло МЕНЬШЕ
   * pageSize — дальше грузить нечего. */
  pageSize: number;
}

function formatTimestamp(iso: string): string {
  // Чистая строковая операция, не new Date() — иначе разное форматирование
  // на SSR и на клиенте даёт hydration-mismatch (тот же урок, что в
  // PromptEditor.tsx).
  return iso.slice(0, 16).replace("T", " ");
}

export function AuditLogTable({ apiBaseUrl, entries, bots, pageSize }: AuditLogTableProps) {
  const [rows, setRows] = useState(entries);
  const [botFilter, setBotFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(entries.length === pageSize);
  const [error, setError] = useState<string | null>(null);

  const handleFilterChange = async (nextBotId: string) => {
    setBotFilter(nextBotId);
    setError(null);
    setLoading(true);
    try {
      const next = await fetchAuditLog(apiBaseUrl, {
        botId: nextBotId || undefined,
        limit: pageSize,
      });
      setRows(next);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить лог");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadMore = async () => {
    setError(null);
    setLoading(true);
    try {
      const next = await fetchAuditLog(apiBaseUrl, {
        botId: botFilter || undefined,
        limit: pageSize,
        offset: rows.length,
      });
      setRows((current) => [...current, ...next]);
      setHasMore(next.length === pageSize);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить ещё");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <label>
        Бот
        <select
          value={botFilter}
          onChange={(e) => void handleFilterChange(e.target.value)}
          aria-label="Фильтр по боту"
        >
          <option value="">Все боты</option>
          {bots.map((bot) => (
            <option key={bot.id} value={bot.id}>
              {bot.name}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <table>
        <thead>
          <tr>
            <th>Время</th>
            <th>Кто</th>
            <th>Бот</th>
            <th>Действие</th>
            <th>Payload</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((entry) => (
            <tr key={entry.id}>
              <td>{formatTimestamp(entry.created_at)}</td>
              <td>{entry.actor_email}</td>
              <td>{entry.bot_name ?? "—"}</td>
              <td>
                <code>{entry.action}</code>
              </td>
              <td>
                {entry.payload && (
                  <details>
                    <summary>показать</summary>
                    <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
                  </details>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {hasMore && (
        <button onClick={() => void handleLoadMore()} disabled={loading}>
          {loading ? "Загружаем…" : "Показать ещё"}
        </button>
      )}
    </>
  );
}
```

- [ ] **Step 4: Написать тест `services/admin-web/components/AuditLogTable.test.tsx`**

```tsx
import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/lib/test-utils";
import { AuditLogTable } from "@/components/AuditLogTable";
import * as api from "@/lib/api";
import type { AuditLogEntry, Bot } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchAuditLog: vi.fn(),
  };
});

const bots: Bot[] = [
  {
    id: "bot-1",
    name: "Bot One",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "",
    image_prompt: null,
    pdf_prompt: null,
  },
];

const entries: AuditLogEntry[] = [
  {
    id: "e1",
    actor_user_id: "u1",
    actor_email: "owner@example.com",
    bot_id: "bot-1",
    bot_name: "Bot One",
    action: "bots.update",
    payload: { name: "Новое имя" },
    created_at: "2026-09-11T10:00:00Z",
  },
];

afterEach(() => {
  vi.clearAllMocks();
});

it("renders each entry's actor, bot and action", () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);
  expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  expect(screen.getByText("Bot One")).toBeInTheDocument();
  expect(screen.getByText("bots.update")).toBeInTheDocument();
});

it("shows the payload when the details element is expanded", () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);
  expect(screen.getByText(/новое имя/i)).toBeInTheDocument();
});

it("refetches with the selected bot filter", async () => {
  vi.mocked(api.fetchAuditLog).mockResolvedValue([]);
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);

  fireEvent.change(screen.getByLabelText("Фильтр по боту"), { target: { value: "bot-1" } });

  await waitFor(() => {
    expect(api.fetchAuditLog).toHaveBeenCalledWith("http://api", {
      botId: "bot-1",
      limit: 50,
    });
  });
});

it('hides "Показать ещё" when the first page is smaller than pageSize', () => {
  render(<AuditLogTable apiBaseUrl="http://api" entries={entries} bots={bots} pageSize={50} />);
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it('shows "Показать ещё", loads and appends the next page, then hides once exhausted', async () => {
  const fullPage: AuditLogEntry[] = [entries[0], { ...entries[0], id: "e2" }];
  vi.mocked(api.fetchAuditLog).mockResolvedValue([{ ...entries[0], id: "e3" }]);
  render(<AuditLogTable apiBaseUrl="http://api" entries={fullPage} bots={bots} pageSize={2} />);
  expect(screen.getByRole("button", { name: /показать ещё/i })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(api.fetchAuditLog).toHaveBeenCalledWith("http://api", { botId: undefined, limit: 2, offset: 2 });
  });
  expect(screen.queryByRole("button", { name: /показать ещё/i })).not.toBeInTheDocument();
});

it("shows an error when loading more fails", async () => {
  vi.mocked(api.fetchAuditLog).mockRejectedValue(new Error("load failed"));
  const fullPage: AuditLogEntry[] = [entries[0], { ...entries[0], id: "e2" }];
  render(<AuditLogTable apiBaseUrl="http://api" entries={fullPage} bots={bots} pageSize={2} />);

  fireEvent.click(screen.getByRole("button", { name: /показать ещё/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/load failed/i);
  });
});
```

- [ ] **Step 5: Прогнать тесты компонента**

Run: `cd services/admin-web && npx vitest run components/AuditLogTable.test.tsx`
Expected: 6 passed.

- [ ] **Step 6: Написать `services/admin-web/app/audit-log/page.tsx`**

```tsx
import { redirect } from "next/navigation";
import { AuditLogTable } from "@/components/AuditLogTable";
import { fetchAuditLog, fetchBots } from "@/lib/api";
import { currentUserIsOwner } from "@/lib/currentUser";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

const AUDIT_LOG_PAGE_SIZE = 50;

export default async function AuditLogPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const [entries, bots] = await Promise.all([
    fetchAuditLog(API_INTERNAL_URL, { limit: AUDIT_LOG_PAGE_SIZE }),
    fetchBots(API_INTERNAL_URL),
  ]);

  return (
    <main>
      <h1>Аудит-лог</h1>
      <AuditLogTable
        apiBaseUrl={API_PROXY_PATH}
        entries={entries}
        bots={bots}
        pageSize={AUDIT_LOG_PAGE_SIZE}
      />
    </main>
  );
}
```

- [ ] **Step 7: Добавить ссылку в `services/admin-web/components/AppHeader.tsx`**

Текущее содержимое:

```tsx
import Link from "next/link";
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";

export async function AppHeader() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <header>
      <span>{user.email}</span>
      {user.is_platform_owner && <Link href="/users">Пользователи</Link>}
      <form action={logout}>
        <button type="submit">Выйти</button>
      </form>
    </header>
  );
}
```

Заменить на:

```tsx
import Link from "next/link";
import { logout } from "@/app/login/actions";
import { fetchCurrentUser } from "@/lib/currentUser";

export async function AppHeader() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <header>
      <span>{user.email}</span>
      {user.is_platform_owner && <Link href="/users">Пользователи</Link>}
      {user.is_platform_owner && <Link href="/audit-log">Аудит-лог</Link>}
      <form action={logout}>
        <button type="submit">Выйти</button>
      </form>
    </header>
  );
}
```

- [ ] **Step 8: Прогнать полный набор тестов admin-web**

Run: `cd services/admin-web && npx vitest run`
Expected: все тесты проходят (число passed выросло минимум на 6).

- [ ] **Step 9: Прогнать tsc и eslint**

Run: `cd services/admin-web && npx tsc --noEmit` и `npm run lint`
Expected: чисто, без новых ошибок/варнингов сверх уже существующих двух
`no-img-element`-варнингов в `ProductForm.tsx`/`ProductsTable.tsx`
(предсуществующие, не эта задача).

- [ ] **Step 10: Commit**

```bash
git add services/admin-web/lib/api.ts services/admin-web/components/AuditLogTable.tsx services/admin-web/components/AuditLogTable.test.tsx services/admin-web/app/audit-log/page.tsx services/admin-web/components/AppHeader.tsx
git commit -m "feat(admin-web): audit log screen, owner-only (FEATURES.md 6.19)"
```

---

### Task 6: Живая проверка на docker compose (финал)

Не отдельный код — последний шаг перед финальным ревью всей ветки.
Выполнить вручную (или через дальнейший контроллер SDD) после того, как
все 5 задач выше слиты в ветку суб-проекта:

- [ ] Поднять/пересобрать стек: `docker compose -f compose/docker-compose.dev.yml up -d --build`, прогнать миграции (`alembic upgrade head` внутри контейнера `api`).
- [ ] Залогиниться владельцем платформы через реальный UI.
- [ ] Выполнить несколько реальных мутаций через кабинет: переименовать бота (6.3), добавить номер в чёрный список, создать пользователя-клиента.
- [ ] Открыть `/audit-log`, убедиться, что все три действия появились с правильными `actor_email`/`action`/`payload`.
- [ ] SQL-запрос к `audit_log` напрямую (`docker compose exec postgres psql ...`) для перекрёстной проверки — что в БД лежит ровно то, что показывает экран.
- [ ] Убедиться в логах `api`-контейнера, что нет ни одного `audit_log_write_failed` warning на эти три успешных действия (если есть — расследовать до финального ревью, не после).
