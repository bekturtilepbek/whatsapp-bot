# Чёрный список номеров (FEATURES.md 1.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сообщение от номера в чёрном списке бота полностью игнорируется —
без ответа, без записи в историю — ровно как игнорируются групповые чаты
сегодня. Номер добавляется/удаляется через API, без raw SQL.

**Architecture:** Одна новая таблица `blocked_contacts` (bot_id, phone) —
имя и состав колонок уже зафиксированы в `docs/ARCHITECTURE.md` §5. Матчинг —
по «сырому» `wa_id` (те же цифры без `+`, что уже используются для
`contacts.wa_id`/дедупа/handoff), НЕ по нормализованному телефону — 9.1
(нормализация) не готова и не нужна здесь как зависимость. Проверка — новый
ранний фильтр в `_process_entry`, симметричный уже существующему
`is_ignored_chat` (группы): полный молчаливый `return`, без записи в БД,
применяется только к сообщениям от клиента (`from_me=false`) — сообщения
менеджера (`from_me=true`, включая ручной ответ заблокированному клиенту)
не затрагиваются.

**Эталон поведения (V1, архив `webhook_wb.zip`, `whatsapp.js`/`server.js`,
все 3 копии бота идентичны — см. [[stage1-core-progress]] за деталями)**:
- Таблица `ignored_numbers(bot_id, phone)` — сюда переносится семантика,
  имя таблицы уже другое (`blocked_contacts`, из ARCHITECTURE.md).
- Матчинг: `phoneNumber = contact.id.user` (сырой JID-user, без `+`) —
  `Set.has(phoneNumber)`. Никакой нормализации на момент сравнения.
- Проверка — до создания контакта/записи истории, `return` сразу.
- Из `from_me`-хендлера (отдельный обработчик в V1) проверка НЕ вызывается
  вообще — заблокированный номер не мешает менеджеру писать вручную.
- Админ-панель (`central-admin/main.py`): при добавлении номера чистит его
  `re.sub(r'\D', '', phone)` (только цифры) перед вставкой — тот же формат,
  что и хранимый `phone`.
- V1 дополнительно дёргал HTTP `reload-ignored` на боте (in-memory кэш) —
  этот шаг НЕ переносим: у нас нет in-memory кэша, каждое сообщение и так
  идёт в БД (тот же паттерн, что уже `get_bot` на каждое событие).

**Tech Stack:** SQLAlchemy + Alembic (миграция), FastAPI (api-эндпоинты).
Изменений в gateway (TS) нет — фильтр целиком в worker (business logic,
ADR-002).

## Global Constraints

- `blocked_contacts.phone` хранит те же «сырые» цифры, что и `contacts.wa_id`
  (никакого `+`, никакой нормализации) — совпадает с V1.
- Проверка блокировки — ТОЛЬКО для `from_me=false`; ветка `from_me=true`
  (`_handle_manager_message`) не трогается.
- Блокировка — полный silent drop: без записи в `contacts`/`messages`, без
  ответа. Симметрично `is_ignored_chat`.
- Никаких изменений в `services/gateway` (TS) — фильтр не транспортный.
- Пагинация списка — явно Волна 3 (FEATURES.md 6.9), здесь — только
  add/remove/list без страниц.
- Conventional Commits; каждый коммит заканчивается
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

## Task 1: `blocked_contacts` — таблица, модель, DB-функции

**Files:**
- Modify: `libs/db/src/db/models.py`
- Create: `libs/db/migrations/versions/202609041002_blocked_contacts.py`
- Create: `libs/db/src/db/blocked_contacts.py`
- Create: `libs/db/tests/test_blocked_contacts.py`
- Modify: `libs/db/tests/test_migration.py`

**Interfaces:**
- Produces: `BlockedContact` ORM-модель; `is_blocked(session, bot_id, phone) -> bool`,
  `add_blocked_number(session, bot_id, phone) -> None`,
  `remove_blocked_number(session, bot_id, phone) -> None`,
  `list_blocked_numbers(session, bot_id) -> list[str]` в `db.blocked_contacts`.

- [ ] **Step 1: Обновить падающий тест на состав таблиц**

В `libs/db/tests/test_migration.py`, найти строку
`assert {"bots", "bot_sessions", "contacts", "messages", "usage_events"} <= tables`
и добавить `"blocked_contacts"`:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts",
        } <= tables
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest libs/db/tests/test_migration.py -v` (нужен Docker)

Expected: FAIL — таблицы `blocked_contacts` ещё нет.

- [ ] **Step 3: Добавить модель**

В `libs/db/src/db/models.py`, в конец файла (после класса `UsageEvent`):

```python
class BlockedContact(Base):
    """Чёрный список номеров (FEATURES.md 1.5). Матчинг — по тому же
    "сырому" wa_id (без "+"), что и Contact.wa_id/дедуп/handoff, НЕ по
    нормализованному телефону (эталон — V1, ignored_numbers).
    """

    __tablename__ = "blocked_contacts"
    __table_args__ = (
        UniqueConstraint("bot_id", "phone", name="uq_blocked_contacts_bot_phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

(все нужные импорты — `String`, `UniqueConstraint`, `ForeignKey`, `UUID`,
`DateTime`, `func`, `text` — уже есть в шапке файла, новых не требуется)

- [ ] **Step 4: Создать миграцию**

Создать `libs/db/migrations/versions/202609041002_blocked_contacts.py`:

```python
"""blocked_contacts

Revision ID: 202609041002
Revises: 202609041001
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609041002"
down_revision: str | None = "202609041001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blocked_contacts",
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
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("bot_id", "phone", name="uq_blocked_contacts_bot_phone"),
    )


def downgrade() -> None:
    op.drop_table("blocked_contacts")
```

- [ ] **Step 5: Прогнать — ожидаем PASS**

Run: `pytest libs/db/tests/test_migration.py -v`

Expected: PASS

- [ ] **Step 6: Написать падающие тесты для DB-функций**

Создать `libs/db/tests/test_blocked_contacts.py` (шапка — дословно как в
`libs/db/tests/test_contacts.py`: docker-gate, `database_url`, `session`
fixtures):

```python
"""Чёрный список: is_blocked/add/remove/list (FEATURES.md 1.5).

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
from db.blocked_contacts import (
    add_blocked_number,
    is_blocked,
    list_blocked_numbers,
    remove_blocked_number,
)
from db.engine import make_engine, make_session_factory
from db.models import Bot
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


async def test_is_blocked_false_when_no_row(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await is_blocked(session, bot_id, "996700000000") is False


async def test_add_then_is_blocked_true(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await add_blocked_number(session, bot_id, "996700000000")
    assert await is_blocked(session, bot_id, "996700000000") is True


async def test_add_is_idempotent_on_conflict(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await add_blocked_number(session, bot_id, "996700000000")
    await add_blocked_number(session, bot_id, "996700000000")  # не должно упасть
    assert await list_blocked_numbers(session, bot_id) == ["996700000000"]


async def test_remove_then_is_blocked_false(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    await add_blocked_number(session, bot_id, "996700000000")
    await remove_blocked_number(session, bot_id, "996700000000")
    assert await is_blocked(session, bot_id, "996700000000") is False


async def test_block_is_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await add_blocked_number(session, bot_a, "996700000000")
    assert await is_blocked(session, bot_a, "996700000000") is True
    assert await is_blocked(session, bot_b, "996700000000") is False


async def test_list_blocked_numbers_returns_only_this_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    await add_blocked_number(session, bot_a, "996700000001")
    await add_blocked_number(session, bot_b, "996700000002")
    assert await list_blocked_numbers(session, bot_a) == ["996700000001"]
```

- [ ] **Step 7: Прогнать — ожидаем FAIL**

Run: `pytest libs/db/tests/test_blocked_contacts.py -v`

Expected: FAIL — `db.blocked_contacts` не существует (`ImportError`).

- [ ] **Step 8: Реализовать**

Создать `libs/db/src/db/blocked_contacts.py`:

```python
"""Чёрный список номеров (FEATURES.md 1.5). Матчинг — по "сырому" wa_id
(см. BlockedContact в models.py) — эталон поведения: V1 ignored_numbers.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BlockedContact


async def is_blocked(session: AsyncSession, bot_id: uuid.UUID, phone: str) -> bool:
    stmt = select(BlockedContact.id).where(
        BlockedContact.bot_id == bot_id, BlockedContact.phone == phone
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def add_blocked_number(session: AsyncSession, bot_id: uuid.UUID, phone: str) -> None:
    """Идемпотентно: повторное добавление того же номера — не ошибка."""
    stmt = (
        insert(BlockedContact)
        .values(bot_id=bot_id, phone=phone)
        .on_conflict_do_nothing(constraint="uq_blocked_contacts_bot_phone")
    )
    await session.execute(stmt)
    await session.flush()


async def remove_blocked_number(session: AsyncSession, bot_id: uuid.UUID, phone: str) -> None:
    """Идемпотентно: удаление отсутствующего номера — не ошибка (0 строк)."""
    stmt = delete(BlockedContact).where(
        BlockedContact.bot_id == bot_id, BlockedContact.phone == phone
    )
    await session.execute(stmt)
    await session.flush()


async def list_blocked_numbers(session: AsyncSession, bot_id: uuid.UUID) -> list[str]:
    stmt = (
        select(BlockedContact.phone)
        .where(BlockedContact.bot_id == bot_id)
        .order_by(BlockedContact.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

- [ ] **Step 9: Прогнать — ожидаем PASS**

Run: `pytest libs/db/tests/test_blocked_contacts.py -v`

Expected: PASS (6 тестов)

- [ ] **Step 10: Commit**

```bash
git add libs/db/src/db/models.py \
        libs/db/migrations/versions/202609041002_blocked_contacts.py \
        libs/db/src/db/blocked_contacts.py \
        libs/db/tests/test_blocked_contacts.py \
        libs/db/tests/test_migration.py
git commit -m "feat(db): add blocked_contacts table and CRUD helpers

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Фильтр в пайплайне worker'а

**Files:**
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Create: `services/worker/tests/pipeline/test_blocked_contacts.py`

**Interfaces:**
- Consumes: `db.blocked_contacts.is_blocked` (Task 1).
- Не меняет ни одну существующую сигнатуру — чисто добавочная проверка
  внутри уже существующего `async with session_factory() as session:` блока.

- [ ] **Step 1: Написать падающие тесты**

Создать `services/worker/tests/pipeline/test_blocked_contacts.py` (шапка —
дословно как в `services/worker/tests/pipeline/test_media_fallback.py`:
docker-gate, `database_url`, `session_factory` fixtures, `_NullStorage`):

```python
"""Чёрный список (FEATURES.md 1.5): сообщение от заблокированного номера
полностью игнорируется — без ответа, без записи в историю. Менеджер
(from_me) не блокируется.
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
from db.blocked_contacts import add_blocked_number
from db.engine import make_engine, make_session_factory
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
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
        raise NotImplementedError("этот тест не должен читать из Storage")


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(bot_id: uuid.UUID, *, from_me: bool = False, wa_msg_id: str = "wamsg-1") -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": from_me,
        "text": "Здравствуйте!",
        "ts": 1756800000000,
    }


async def test_message_from_blocked_number_is_fully_ignored(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для заблокированного номера")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000000")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        assert await redis.xlen("wa:out") == 0  # ни ответа, ни typing
        async with session_factory() as session:
            messages = (
                (await session.execute(select(Message).where(Message.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert messages == []  # история не пишется вообще
    finally:
        await redis.aclose()


async def test_message_from_non_blocked_number_is_unaffected(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm.client import LLMResult

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996799999999")  # другой номер
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert await redis.xlen("wa:out") == 2  # typing + text — обычный ответ
    finally:
        await redis.aclose()


async def test_manager_message_from_blocked_number_is_not_blocked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000000")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_payload(bot_id, from_me=True, wa_msg_id="wamsg-manager-1"),
            redis,
            session_factory,
            _NullStorage(),
        )
        async with session_factory() as session:
            messages = (
                (await session.execute(select(Message).where(Message.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(messages) == 1  # ручное сообщение менеджера записалось как обычно
            assert messages[0].role == "assistant"
    finally:
        await redis.aclose()
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest services/worker/tests/pipeline/test_blocked_contacts.py -v`

Expected: FAIL — первый тест падает (сообщение НЕ игнорируется, обычный
ответ уходит) — фильтра ещё нет.

- [ ] **Step 3: Реализовать**

В `services/worker/src/worker/pipeline/consumer.py`:

1. Добавить импорт:

```python
from db.blocked_contacts import is_blocked
```

2. В `_process_entry`, изменить блок с `match_or_create_contact` — добавить
   проверку первой строкой внутри уже существующего `async with
   session_factory() as session:`:

```python
    async with session_factory() as session:
        if await is_blocked(session, event.bot_id, event.sender_wa_id):
            logger.info(
                "blocked contact, ignoring", bot_id=str(event.bot_id), phone=event.sender_wa_id
            )
            return
        contact = await match_or_create_contact(
            session, event.bot_id, wa_id=event.sender_wa_id, lid=event.sender_lid
        )
```

(остальное тело блока — без изменений; `return` внутри `async with` просто
закрывает сессию, ничего не закоммичено — записи не было)

3. Обновить докстринг модуля (начало файла) — добавить чёрный список в
   описание порядка: заменить `дедуп → фильтры → from_me?` на
   `дедуп → фильтры (группы) → from_me? handoff-ветка : чёрный список →
   contact → ...`.

- [ ] **Step 4: Прогнать новые тесты — ожидаем PASS**

Run: `pytest services/worker/tests/pipeline/test_blocked_contacts.py -v`

Expected: PASS (3 теста)

- [ ] **Step 5: Прогнать весь worker-пакет — регрессия**

Run: `pytest services/worker -v`

Expected: PASS, без регрессий (проверка `is_blocked` для незаблокированного
номера — один лишний быстрый SELECT на индексированную таблицу, не меняет
поведение остальных тестов).

- [ ] **Step 6: Commit**

```bash
git add services/worker/src/worker/pipeline/consumer.py \
        services/worker/tests/pipeline/test_blocked_contacts.py
git commit -m "feat(worker): ignore messages from blocked contacts

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Управление списком через API

Без этого шага чёрный список нечем заполнить без raw SQL — тот же довод,
что и для `image_prompt` в прошлой итерации. Пагинация — явно Волна 3
(6.9), здесь только list/add/remove.

**Files:**
- Create: `services/api/src/api/schemas/blocked_contacts.py`
- Modify: `services/api/src/api/routers/bots.py`
- Create: `services/api/tests/test_blocked_contacts.py`

**Interfaces:**
- Produces: `GET /bots/{bot_id}/blocked-numbers` → `list[BlockedNumberOut]`,
  `POST /bots/{bot_id}/blocked-numbers` (body `{"phone": str}`) → `BlockedNumberOut`,
  `DELETE /bots/{bot_id}/blocked-numbers/{phone}` → `204`.

- [ ] **Step 1: Написать падающие тесты**

Создать `services/api/tests/test_blocked_contacts.py` — шапка дословно как
в `services/api/tests/test_bots.py` (`client`, `session_factory` fixtures,
`_make_bot` helper):

```python
"""GET/POST/DELETE /bots/{id}/blocked-numbers (FEATURES.md 1.5)."""

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
    response = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert response.status_code == 200
    assert response.json() == []


async def test_post_adds_number_stripping_non_digits(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/blocked-numbers", json={"phone": "+996 700-00-00-00"}
    )
    assert response.status_code == 201
    assert response.json()["phone"] == "996700000000"

    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert [item["phone"] for item in listing.json()] == ["996700000000"]


async def test_post_is_idempotent(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    response = await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    assert response.status_code == 201  # не ошибка при повторе
    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert len(listing.json()) == 1


async def test_delete_removes_number(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    response = await client.delete(f"/bots/{bot_id}/blocked-numbers/996700000000")
    assert response.status_code == 204

    listing = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert listing.json() == []


async def test_delete_unknown_number_is_still_204(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.delete(f"/bots/{bot_id}/blocked-numbers/000000000000")
    assert response.status_code == 204


async def test_list_scoped_to_bot(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_a = await _make_bot(session_factory)
    bot_b = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_a}/blocked-numbers", json={"phone": "996700000001"})
    await client.post(f"/bots/{bot_b}/blocked-numbers", json={"phone": "996700000002"})

    listing = await client.get(f"/bots/{bot_a}/blocked-numbers")
    assert [item["phone"] for item in listing.json()] == ["996700000001"]
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest services/api/tests/test_blocked_contacts.py -v`

Expected: FAIL — маршрутов `/bots/{id}/blocked-numbers` не существует (404).

- [ ] **Step 3: Схема**

Создать `services/api/src/api/schemas/blocked_contacts.py`:

```python
"""Pydantic v2 схемы чёрного списка номеров (FEATURES.md 1.5)."""

from __future__ import annotations

from pydantic import BaseModel


class BlockedNumberIn(BaseModel):
    phone: str


class BlockedNumberOut(BaseModel):
    phone: str
```

- [ ] **Step 4: Роуты**

В `services/api/src/api/routers/bots.py`:

1. Добавить импорты:

```python
import re

from db.blocked_contacts import add_blocked_number, list_blocked_numbers, remove_blocked_number

from ..schemas.blocked_contacts import BlockedNumberIn, BlockedNumberOut
```

2. Добавить в конец файла (после `release_chat`):

```python
def _strip_non_digits(phone: str) -> str:
    """Тот же формат хранения, что и Contact.wa_id — без "+"/пробелов/скобок
    (эталон V1: re.sub(r'\\D', '', phone) в central-admin).
    """
    return re.sub(r"\D", "", phone)


@router.get("/{bot_id}/blocked-numbers", response_model=list[BlockedNumberOut])
async def list_blocked(bot_id: uuid.UUID, session: SessionDep) -> list[BlockedNumberOut]:
    phones = await list_blocked_numbers(session, bot_id)
    return [BlockedNumberOut(phone=p) for p in phones]


@router.post(
    "/{bot_id}/blocked-numbers", response_model=BlockedNumberOut, status_code=201
)
async def add_blocked(
    bot_id: uuid.UUID, body: BlockedNumberIn, session: SessionDep
) -> BlockedNumberOut:
    phone = _strip_non_digits(body.phone)
    await add_blocked_number(session, bot_id, phone)
    await session.commit()
    return BlockedNumberOut(phone=phone)


@router.delete("/{bot_id}/blocked-numbers/{phone}", status_code=204)
async def delete_blocked(bot_id: uuid.UUID, phone: str, session: SessionDep) -> None:
    await remove_blocked_number(session, bot_id, phone)
    await session.commit()
```

(`SessionDep`, `uuid`, `router` — уже импортированы/определены в файле;
свериться перед вставкой, что имена совпадают с текущим состоянием файла)

- [ ] **Step 5: Прогнать — ожидаем PASS**

Run: `pytest services/api/tests/test_blocked_contacts.py -v`

Expected: PASS (6 тестов)

- [ ] **Step 6: Полный прогон Python-пакета — регрессия**

Run: `pytest -q` (из корня, полный набор)

Expected: PASS, без регрессий.

- [ ] **Step 7: Lint + типы**

Run: `ruff check .` и `mypy libs/core/src libs/db/src libs/integrations/src services/worker/src`

Expected: чисто. (`services/api/src` не входит в текущий `make lint`
охват — прогнать отдельно `mypy services/api/src` для собственной
уверенности, но не блокирующе, если найдутся pre-existing gaps вне этой
задачи)

- [ ] **Step 8: Commit**

```bash
git add services/api/src/api/schemas/blocked_contacts.py \
        services/api/src/api/routers/bots.py \
        services/api/tests/test_blocked_contacts.py
git commit -m "feat(api): manage blocked_contacts via GET/POST/DELETE

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Живой прогон (docker compose)

По [[live-verification-preference]].

**Files:** нет (верификация)

- [ ] **Step 1: Поднять dev-стек, прогнать миграции**

`docker compose -f compose/docker-compose.dev.yml up --build -d`, затем
`docker compose -f compose/docker-compose.dev.yml exec worker sh -c "cd /app/libs/db && alembic upgrade head"`.

- [ ] **Step 2: Создать тестового бота, добавить номер в ЧС через API**

`curl -X POST http://localhost:8000/bots/<id>/blocked-numbers -d '{"phone":"996700000000"}'`
(порт/хост — свериться с `compose/docker-compose.dev.yml`, `api` слушает
`8000`).

- [ ] **Step 3: XADD событие от этого номера в `wa:in`, свериться**

`wa:out` пуст, `messages`/`contacts` для этого бота пусты — сообщение
полностью проигнорировано.

- [ ] **Step 4: XADD событие с `from_me: true` от того же номера**

Свериться, что оно обрабатывается как обычно (handoff включается) —
чёрный список не блокирует менеджера.

- [ ] **Step 5: Обновить память проекта**

Обновить [[stage1-core-progress]]: 1.5 закрыт. Следующий пункт по
согласованному порядку Волны 1 — LLM-ретраи (в списке после 2.2–2.3,
которая отложена) либо возобновление 2.2–2.3, если пользователь принесёт
ElevenLabs-версию — уточнить у пользователя.
