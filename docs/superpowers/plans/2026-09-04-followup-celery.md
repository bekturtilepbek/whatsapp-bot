# Follow-up напоминания через Celery (FEATURES.md 5.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот, ответивший клиенту, ставит Celery-задачу с `eta`; если клиент
молчит `reminder_delay_minutes` — задача перепроверяет условия и шлёт
`reminder_message`. Переживает рестарт любого сервиса (задача — в Redis,
не в памяти процесса).

**Architecture:** Новый сервис `services/celery` (первое появление в коде,
до этого — только в ARCHITECTURE.md §4) + новая общая библиотека
`libs/scheduling` (конфиг Celery-приложения + имя задачи, без реализации —
чтобы `services/worker` мог ставить задачу в очередь, не импортируя чужой
сервис). Отмена — не через `revoke` (ADR-003: "оптимизация, не гарантия"),
а через перепроверку при срабатывании: сравнение `messages.seq` на момент
постановки с текущим состоянием истории.

**Tech Stack:** Celery 5.4+ (`celery[redis]`, брокер и backend — тот же
Redis, что и Streams), SQLAlchemy 2.0 async (переиспользуется как есть,
Celery-таск — синхронная обёртка `asyncio.run(...)` вокруг async-тела).

**Spec:** [docs/superpowers/specs/2026-09-04-followup-celery-design.md](../specs/2026-09-04-followup-celery-design.md)

## Global Constraints

- Отмена таймера — НЕ `revoke`. Задача при срабатывании перепроверяет:
  бот включён и `reminder_enabled` всё ещё true, handoff не активен,
  клиент не написал ничего нового (`messages.seq > after_seq, role='user'`
  не существует для этого `contact_id`).
- `funnel_completed`-эквивалент из V1 НЕ переносится (букинг вне скоупа) —
  проверяем только handoff.
- Follow-up планируется только после НАСТОЯЩЕГО LLM-ответа (`_reply`,
  `_reply_with_vision`) — НЕ после медиа-заглушки (`_reply_with_media_fallback`,
  FEATURES 2.6).
- Celery-приложение — в `libs/scheduling` (не в `libs/core`, чтобы не тащить
  Celery в `services/api`; не в `services/celery`, чтобы `services/worker`
  мог ставить задачи без импорта чужого сервиса).
- `services/worker`/`services/celery` шлют в `wa:out` через общий
  `core.bus.publish`/`make_redis` — не дублировать per-service.
- Только Celery worker-процесс в этой итерации, без `beat` (нет
  периодических задач — follow-up ставится программно через
  `apply_async(eta=...)`).
- Сбой постановки задачи (Redis/Celery недоступен) не должен ронять уже
  успешно отправленный клиенту ответ — перехватывается локально, не
  пробрасывается в общий `except` пайплайна.
- Conventional Commits; каждый коммит заканчивается
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

## Task 1: `core.bus` — общий Redis-паблишер для worker и celery

**Files:**
- Modify: `libs/core/pyproject.toml`
- Create: `libs/core/src/core/bus.py`
- Modify: `services/worker/src/worker/bus.py`

**Interfaces:**
- Produces: `core.bus.make_redis() -> Redis`, `core.bus.publish(redis, stream, event) -> None`,
  `core.bus.IN_STREAM = "wa:in"`, `core.bus.OUT_STREAM = "wa:out"`.
- `worker.bus` реэкспортирует все четыре — существующие импорты
  (`from ..bus import IN_STREAM, OUT_STREAM, ensure_group, publish, read_group`
  в `consumer.py`) не меняются ни на строку.

- [ ] **Step 1: Добавить `redis` в зависимости `libs/core`**

В `libs/core/pyproject.toml`:

```toml
dependencies = [
    "pydantic>=2.9",
    "redis>=5.0",
]
```

- [ ] **Step 2: Создать `core.bus`**

Создать `libs/core/src/core/bus.py` (дословно то, что сегодня в
`services/worker/src/worker/bus.py`, но без `ensure_group`/`StreamEntry`/
`read_group` — та часть остаётся сервис-локальной, читает `wa:in` только worker):

```python
"""Redis Streams: подключение и публикация — общее между services/worker
(шлёт ответы) и services/celery (шлёт follow-up). Чтение wa:in (consumer
group) остаётся в services/worker/bus.py — только он consumer этого стрима.
"""

from __future__ import annotations

import json
import os
from typing import Any

from redis.asyncio import Redis

IN_STREAM = "wa:in"
OUT_STREAM = "wa:out"


def make_redis() -> Redis:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    # socket_keepalive снижает риск, но не гарантирует: тихо потерянное сетью
    # (напр. Docker Desktop/WSL2 NAT) TCP-соединение может всё равно оставить
    # чтение висеть без ответа. socket_timeout — вторая линия защиты.
    return Redis.from_url(
        url, decode_responses=True, socket_keepalive=True, socket_timeout=15
    )


async def publish(redis: Redis, stream: str, event: dict[str, Any]) -> None:
    await redis.xadd(stream, {"payload": json.dumps(event, ensure_ascii=False)})
```

- [ ] **Step 3: Переписать `worker/bus.py` на реэкспорт**

Заменить `services/worker/src/worker/bus.py` целиком:

```python
"""Redis Streams: consumer-group чтение wa:in — специфично для worker
(единственный consumer этого стрима). make_redis/publish/IN_STREAM/OUT_STREAM
теперь в core.bus (общие для worker и celery) — реэкспортируются здесь,
чтобы существующие импорты в consumer.py не менялись.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from core.bus import IN_STREAM, OUT_STREAM, make_redis, publish  # noqa: F401
from redis.asyncio import Redis


async def ensure_group(redis: Redis, stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(stream, group, id="$", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


@dataclass(frozen=True)
class StreamEntry:
    entry_id: str
    # None — записи не распарсить (нет поля "payload" или битый JSON). Такую
    # запись всё равно нужно ACK'нуть вызывающим кодом, иначе она зависнет
    # в pending list навсегда.
    payload: dict[str, Any] | None


async def read_group(
    redis: Redis,
    stream: str,
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 5000,
) -> AsyncIterator[StreamEntry]:
    """Один проход XREADGROUP; отдаёт записи как есть. Не ACK'ает сама."""
    # decode_responses=True в make_redis() -> ключи/значения полей всегда str;
    # библиотечный тип ответа шире (bytes-вариант), сужаем явным cast.
    reply = cast(
        "list[tuple[str, list[tuple[str, dict[str, str]]]]] | None",
        await redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        ),
    )
    if not reply:
        return
    for _stream_name, entries in reply:
        for entry_id, fields in entries:
            raw = fields.get("payload")
            payload: dict[str, Any] | None
            if raw is None:
                payload = None
            else:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = None
            yield StreamEntry(entry_id=entry_id, payload=payload)
```

Заметь: `json` теперь нужен и здесь (для `read_group`) — добавить
`import json` в начало файла вместе с остальными импортами.

- [ ] **Step 4: Переустановить `core` и прогнать существующие тесты worker'а**

Run: `pip install -e libs/core` (пересобрать editable-install после
изменения зависимостей), затем `pytest services/worker -v`

Expected: PASS, весь набор без регрессий (существующие импорты из
`worker.bus` продолжают работать через реэкспорт).

- [ ] **Step 5: Commit**

```bash
git add libs/core/pyproject.toml libs/core/src/core/bus.py services/worker/src/worker/bus.py
git commit -m "refactor(core): extract shared Redis publish helper to core.bus

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `libs/scheduling` — конфиг Celery-приложения и имя задачи

**Files:**
- Create: `libs/scheduling/pyproject.toml`
- Create: `libs/scheduling/src/scheduling/__init__.py`
- Create: `libs/scheduling/src/scheduling/celery_app.py`
- Create: `libs/scheduling/src/scheduling/task_names.py`
- Create: `libs/scheduling/tests/test_celery_app.py`

**Interfaces:**
- Produces: `scheduling.celery_app.celery_app` (инстанс `celery.Celery`),
  `scheduling.task_names.FOLLOW_UP_REMINDER = "tasks.followup.send_reminder"`.

- [ ] **Step 1: Создать пакет**

Создать `libs/scheduling/pyproject.toml`:

```toml
[project]
name = "scheduling"
version = "0.1.0"
description = "Celery-приложение (конфиг) и имена задач — общее между services/worker (постановка) и services/celery (исполнение)"
requires-python = ">=3.12"
dependencies = [
    "celery[redis]>=5.4",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Создать `libs/scheduling/src/scheduling/__init__.py`:

```python
"""Конфиг Celery-приложения и общие имена задач (FEATURES.md 5.5)."""
```

- [ ] **Step 2: Написать падающие тесты**

Создать `libs/scheduling/tests/test_celery_app.py`:

```python
"""Конфигурация Celery-приложения и имя follow-up задачи."""

from __future__ import annotations

from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER


def test_celery_app_uses_redis_for_broker_and_backend() -> None:
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.conf.result_backend.startswith("redis://")


def test_celery_app_uses_json_serialization() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]


def test_follow_up_task_name_is_stable() -> None:
    # Строка захардкожена в тесте намеренно — меняется редко и осознанно;
    # оба потребителя (worker, celery) должны совпадать именно на ней.
    assert FOLLOW_UP_REMINDER == "tasks.followup.send_reminder"
```

- [ ] **Step 3: Прогнать — ожидаем FAIL**

Run: `pip install -e libs/scheduling && pytest libs/scheduling -v`

Expected: FAIL — `scheduling.celery_app`/`scheduling.task_names` не существуют.

- [ ] **Step 4: Реализовать**

Создать `libs/scheduling/src/scheduling/celery_app.py`:

```python
"""Celery-приложение: общий брокер/backend (Redis) для services/worker
(постановка задач) и services/celery (исполнение). Сами задачи регистрирует
services/celery — здесь только конфиг, чтобы не тащить celery со всеми
зависимостями в services/api, которому это не нужно (ADR-003).
"""

from __future__ import annotations

import os

from celery import Celery


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


celery_app = Celery("platform", broker=_redis_url(), backend=_redis_url())
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)
```

Создать `libs/scheduling/src/scheduling/task_names.py`:

```python
"""Имена Celery-задач, общие между постановкой (services/worker) и
регистрацией (services/celery) — держим в одном месте, чтобы строка не
разъехалась между двумя сторонами (тот же принцип, что и
libs/core/redis_keys.py для имён Redis-ключей).
"""

from __future__ import annotations

FOLLOW_UP_REMINDER = "tasks.followup.send_reminder"
```

- [ ] **Step 5: Прогнать — ожидаем PASS**

Run: `pytest libs/scheduling -v`

Expected: PASS (3 теста)

- [ ] **Step 6: Commit**

```bash
git add libs/scheduling
git commit -m "feat(scheduling): Celery app config and shared task names

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `insert_outgoing` возвращает `seq`

**Files:**
- Modify: `libs/db/src/db/messages.py`
- Modify: `libs/db/tests/test_messages.py`
- Modify: `services/worker/src/worker/pipeline/consumer.py` (только 2 из 4 call sites)

**Interfaces:**
- Produces: `insert_outgoing(session, bot_id, contact_id, content) -> int`
  (было `-> None`). Возвращает `seq` только что вставленной строки.

- [ ] **Step 1: Написать падающий тест**

В `libs/db/tests/test_messages.py`, добавить в конец файла:

```python
async def test_insert_outgoing_returns_the_new_row_seq(session: AsyncSession) -> None:
    bot_id, contact_id = await _make_contact(session)
    seq = await insert_outgoing(session, bot_id, contact_id, "ответ")

    history = await fetch_recent_history(session, contact_id)
    assert history[0].seq == seq
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest "libs/db/tests/test_messages.py::test_insert_outgoing_returns_the_new_row_seq" -v`

Expected: FAIL — `insert_outgoing` возвращает `None`, `None == seq` (int) не совпадает.

- [ ] **Step 3: Реализовать**

В `libs/db/src/db/messages.py`, изменить `insert_outgoing`:

```python
async def insert_outgoing(
    session: AsyncSession,
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    content: str,
) -> int:
    """Ответ ассистента — wa_msg_id нет, UNIQUE(bot_id, wa_msg_id) на NULL не срабатывает.

    ts выставляем на Python-стороне (как и insert_incoming), а не полагаемся
    на server_default=func.now(): внутри одной транзакции now() в Postgres
    заморожен на момент её начала, поэтому ts ответа мог оказаться РАНЬШЕ
    ts входящего сообщения той же транзакции — история сортировалась не по
    реальному порядку записи.

    Возвращает seq вставленной строки — нужен вызывающему коду для
    постановки follow-up-задачи (FEATURES.md 5.5): "было ли что-то новее
    этого сообщения к моменту срабатывания задачи".
    """
    message = Message(
        bot_id=bot_id,
        contact_id=contact_id,
        role="assistant",
        content=content,
        ts=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    return message.seq
```

- [ ] **Step 4: Прогнать — ожидаем PASS**

Run: `pytest libs/db/tests/test_messages.py -v`

Expected: PASS, весь файл (флеш присваивает `seq` через `IDENTITY` —
объект `message.seq` доступен сразу после `flush()`, до `commit()`).

- [ ] **Step 5: Обновить 2 из 4 вызовов в consumer.py**

В `services/worker/src/worker/pipeline/consumer.py`, изменить ТОЛЬКО
строки внутри `_reply` (было `await insert_outgoing(session, event.bot_id, contact_id, result.text)`,
строка ~247) и `_reply_with_vision` (аналогичная строка ~313) — присвоить
возврат переменной:

```python
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, result.text)
```

Строки в `_handle_manager_message` (~195) и `_reply_with_media_fallback`
(~334) НЕ трогать — возврат там не нужен (follow-up не планируется для
этих веток).

- [ ] **Step 6: Прогнать весь worker-пакет — регрессия**

Run: `pytest services/worker -v`

Expected: PASS, без регрессий (переменная `outgoing_seq` пока нигде не
используется дальше — это нормально для этого шага, использование
появится в Task 5; если линтер ругнётся на "assigned but never used" —
это ожидаемо ровно до Task 5, коммитить в Task 3 всё равно можно, т.к.
переменная используется в той же функции — просто присвоение без чтения
внутри ЭТОЙ задачи; следующая задача добавит чтение).

- [ ] **Step 7: Commit**

```bash
git add libs/db/src/db/messages.py libs/db/tests/test_messages.py services/worker/src/worker/pipeline/consumer.py
git commit -m "feat(db): insert_outgoing returns the inserted row's seq

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `services/celery` — задача `send_reminder`

**Files:**
- Create: `services/celery/pyproject.toml`
- Create: `services/celery/Dockerfile`
- Create: `services/celery/src/tasks/__init__.py`
- Create: `services/celery/src/tasks/followup.py`
- Create: `services/celery/tests/test_followup.py`

**Interfaces:**
- Consumes: `scheduling.celery_app.celery_app`, `scheduling.task_names.FOLLOW_UP_REMINDER`
  (Task 2); `core.bus.make_redis/publish/OUT_STREAM` (Task 1); `db.bots.get_bot`,
  `db.messages.insert_outgoing`, `db.models.Message` (существующие).
- Produces: `tasks.followup._send_reminder_async(redis, session_factory, bot_id, contact_id, chat_id, after_seq) -> None`
  (тестируемое async-тело, DI по образцу `_process_entry`) и
  `tasks.followup.send_reminder(bot_id, contact_id, chat_id, after_seq) -> None`
  (синхронная Celery-задача — `asyncio.run` вокруг тела + свой redis/engine).

- [ ] **Step 1: Создать пакет**

Создать `services/celery/pyproject.toml`:

```toml
[project]
name = "celery-worker"
version = "0.1.0"
description = "Celery worker: отложенные задачи (follow-up; кампании/бэкапы — позже волнами)"
requires-python = ">=3.12"
dependencies = [
    "core",
    "db",
    "scheduling",
    "structlog>=24.4",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Написать падающие тесты**

Создать `services/celery/tests/test_followup.py` (шапка — testcontainers,
как во всех Python DB-тестах этой сессии):

```python
"""send_reminder / _send_reminder_async: перепроверка условий при
срабатывании (FEATURES.md 5.5) — бот включён и настроен слать
напоминания, handoff не активен, клиент не ответил с момента постановки.

Тестируем async-тело напрямую (DI redis/session_factory, как _process_entry
в worker) — реальный прогон через Celery-воркер: живой прогон, docker
compose (см. план, Task 6).
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.messages import insert_incoming, insert_outgoing
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
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


CHAT_ID = "996700000000@s.whatsapp.net"


async def _make_bot_and_contact(
    session_factory: async_sessionmaker[AsyncSession], **settings: object
) -> tuple[uuid.UUID, uuid.UUID]:
    from db.contacts import match_or_create_contact

    async with session_factory() as session:
        bot = Bot(name="test-bot", settings={"reminder_enabled": True, **settings})
        session.add(bot)
        await session.flush()
        contact = await match_or_create_contact(session, bot.id, wa_id="996700000000", lid=None)
        await session.commit()
        return bot.id, contact.id


async def test_sends_reminder_and_records_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(
        session_factory, reminder_message="Напоминаем о себе!"
    )
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "исходный ответ бота")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )

        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert "Напоминаем о себе!" in out_entries[1][1]["payload"]

        async with session_factory() as session:
            messages = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.contact_id == contact_id)
                        .order_by(Message.seq)
                    )
                )
                .scalars()
                .all()
            )
            assert [m.content for m in messages] == [
                "исходный ответ бота",
                "Напоминаем о себе!",
            ]
    finally:
        await redis.aclose()


async def test_uses_default_message_when_not_configured(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import DEFAULT_REMINDER_MESSAGE, _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)  # без reminder_message
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        out_entries = await redis.xrange("wa:out")
        assert DEFAULT_REMINDER_MESSAGE in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_skips_when_customer_already_replied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ бота")
        await session.commit()
    async with session_factory() as session:
        await insert_incoming(
            session, bot_id, contact_id, "клиент ответил", "wamsg-1", datetime.now(UTC)
        )
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_skips_when_reminder_disabled_since_scheduling(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory, reminder_enabled=False)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_skips_when_handoff_active(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from core.redis_keys import handoff_key
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await redis.set(handoff_key(str(bot_id), CHAT_ID), "1", ex=600)
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_skips_when_bot_disabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        from db.bots import update_bot

        await update_bot(session, bot_id, enabled=False)
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()
```

- [ ] **Step 3: Прогнать — ожидаем FAIL**

Run: `pytest services/celery/tests/test_followup.py -v`

Expected: FAIL — `tasks.followup` не существует (`ModuleNotFoundError`).

- [ ] **Step 4: Реализовать**

Создать `services/celery/src/tasks/followup.py`:

```python
"""FEATURES.md 5.5: напоминание молчащему клиенту. Celery-задача с eta —
не таймер в памяти (см. "грабли" CLAUDE.md). При срабатывании
перепроверяет актуальность условия (revoke — оптимизация, не гарантия,
ADR-003): бот всё ещё включён и настроен слать напоминания, handoff не
активен, клиент ничего не написал с момента постановки задачи.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from core.bus import OUT_STREAM, make_redis, publish
from core.events import OutboundText, OutboundTyping
from core.redis_keys import handoff_key
from db.bots import get_bot
from db.engine import make_engine, make_session_factory
from db.messages import insert_outgoing
from db.models import Message
from redis.asyncio import Redis
from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DEFAULT_REMINDER_MESSAGE = (
    "Здравствуйте! Подскажите, удалось ли ознакомиться с информацией? "
    "Если есть вопросы — я на связи!"
)

logger = structlog.get_logger("tasks.followup")


async def _send_reminder_async(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    bot_id: str,
    contact_id: str,
    chat_id: str,
    after_seq: int,
) -> None:
    async with session_factory() as session:
        bot = await get_bot(session, uuid.UUID(bot_id))
        if bot is None or not bot.enabled:
            logger.info("follow-up skipped: bot missing or disabled", bot_id=bot_id)
            return
        if not bot.settings.get("reminder_enabled", False):
            logger.info(
                "follow-up skipped: reminders disabled since scheduling", bot_id=bot_id
            )
            return
        if await redis.exists(handoff_key(bot_id, chat_id)):
            logger.info("follow-up skipped: handoff active", bot_id=bot_id, chat_id=chat_id)
            return

        newer = await session.execute(
            select(Message.id)
            .where(
                Message.contact_id == uuid.UUID(contact_id),
                Message.role == "user",
                Message.seq > after_seq,
            )
            .limit(1)
        )
        if newer.scalar_one_or_none() is not None:
            logger.info(
                "follow-up skipped: customer already replied", bot_id=bot_id, chat_id=chat_id
            )
            return

        text = bot.settings.get("reminder_message", DEFAULT_REMINDER_MESSAGE)
        typing_event = OutboundTyping(
            bot_id=bot.id, chat_id=chat_id, client_msg_id=uuid.uuid4().hex
        )
        text_event = OutboundText(
            bot_id=bot.id, chat_id=chat_id, text=text, client_msg_id=uuid.uuid4().hex
        )
        await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))
        await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))
        await insert_outgoing(session, bot.id, uuid.UUID(contact_id), text)
        await session.commit()
        logger.info("follow-up reminder sent", bot_id=bot_id, chat_id=chat_id)


async def _run(bot_id: str, contact_id: str, chat_id: str, after_seq: int) -> None:
    redis = make_redis()
    engine = make_engine()
    session_factory = make_session_factory(engine)
    try:
        await _send_reminder_async(
            redis, session_factory, bot_id, contact_id, chat_id, after_seq
        )
    finally:
        await redis.aclose()
        await engine.dispose()


@celery_app.task(name=FOLLOW_UP_REMINDER)
def send_reminder(bot_id: str, contact_id: str, chat_id: str, after_seq: int) -> None:
    asyncio.run(_run(bot_id, contact_id, chat_id, after_seq))
```

Создать `services/celery/src/tasks/__init__.py`:

```python
"""Точка входа Celery-воркера: `celery -A tasks worker`. Экспортирует
`celery` (конвенция — Celery -A ищет этот атрибут в пакете) из общего
libs/scheduling и импортирует модули задач, чтобы @celery_app.task
зарегистрировался при старте воркера.
"""

from __future__ import annotations

from scheduling.celery_app import celery_app as celery  # noqa: F401

from . import followup  # noqa: F401
```

- [ ] **Step 5: Прогнать — ожидаем PASS**

Run: `pip install -e services/celery && pytest services/celery -v`

Expected: PASS (6 тестов)

- [ ] **Step 6: Commit**

```bash
git add services/celery/pyproject.toml services/celery/src services/celery/tests
git commit -m "feat(celery): follow-up reminder task with re-check on fire

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Постановка задачи из worker'а

**Files:**
- Modify: `services/worker/pyproject.toml`
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Modify: `services/worker/tests/pipeline/test_reply_smoke.py`
- Create: `services/worker/tests/pipeline/test_followup_scheduling.py`

**Interfaces:**
- Consumes: `scheduling.celery_app.celery_app`, `scheduling.task_names.FOLLOW_UP_REMINDER` (Task 2).
- Produces: `_schedule_follow_up(bot, chat_id, contact_id, after_seq) -> None` в `consumer.py`.

- [ ] **Step 1: Добавить `scheduling` в зависимости worker'а**

В `services/worker/pyproject.toml`:

```toml
dependencies = [
    "core",
    "db",
    "llm",
    "integrations",
    "scheduling",
    "redis>=5.0",
    "structlog>=24.4",
    "aiohttp>=3.10",
]
```

(имя editable-пакета `integrations` уже установлено в Dockerfile/локально —
добавление в `dependencies` здесь только документирует состав, не меняет
установку; `scheduling` — новое, нужно и в `dependencies`, и в
`pip install -e` — см. Task 6)

- [ ] **Step 2: Написать падающие тесты**

Создать `services/worker/tests/pipeline/test_followup_scheduling.py`
(шапка — testcontainers, как везде в этом пакете):

```python
"""Постановка follow-up-задачи после настоящего LLM-ответа (FEATURES.md
5.5) — НЕ после медиа-заглушки. Сбой постановки не должен портить уже
отправленный клиенту ответ.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
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


class _FakeCeleryApp:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._error = error

    def send_task(self, name: str, args: list[object], eta: datetime) -> None:
        if self._error is not None:
            raise self._error
        self.calls.append({"name": name, "args": args, "eta": eta})


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], **settings: object
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02, **settings},
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
        "text": "Здравствуйте, у вас есть доставка?",
        "ts": 1756800000000,
    }


async def test_reminder_scheduled_after_llm_reply_when_enabled(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)

    bot_id = await _make_bot(
        session_factory, reminder_enabled=True, reminder_delay_minutes=45
    )
    redis = FakeRedis(decode_responses=True)
    try:
        before = datetime.now(UTC)
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        assert len(fake_celery.calls) == 1
        call = fake_celery.calls[0]
        assert call["name"] == "tasks.followup.send_reminder"
        bot_id_arg, contact_id_arg, chat_id_arg, after_seq_arg = call["args"]  # type: ignore[misc]
        assert bot_id_arg == str(bot_id)
        assert chat_id_arg == "996700000000@s.whatsapp.net"
        assert isinstance(after_seq_arg, int)
        eta = call["eta"]
        assert isinstance(eta, datetime)
        expected = before + timedelta(minutes=45)
        assert abs((eta - expected).total_seconds()) < 5
    finally:
        await redis.aclose()


async def test_reminder_not_scheduled_when_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)

    bot_id = await _make_bot(session_factory)  # reminder_enabled отсутствует
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert fake_celery.calls == []
    finally:
        await redis.aclose()


async def test_scheduling_failure_does_not_break_the_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    monkeypatch.setattr(
        consumer_module, "celery_app", _FakeCeleryApp(error=RuntimeError("redis down"))
    )

    bot_id = await _make_bot(session_factory, reminder_enabled=True)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2  # ответ клиенту всё равно ушёл
        assert "Да, есть." in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest services/worker/tests/pipeline/test_followup_scheduling.py -v`

Expected: FAIL — `consumer_module.celery_app` не существует (`AttributeError`
при `monkeypatch.setattr`), задача никогда не ставится.

- [ ] **Step 3: Реализовать**

В `services/worker/src/worker/pipeline/consumer.py`:

1. Обновить импорт `datetime`:

```python
from datetime import UTC, datetime, timedelta
```

2. Добавить импорты Celery-конфига:

```python
from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER
```

3. Добавить константу рядом с остальными:

```python
DEFAULT_REMINDER_DELAY_MINUTES = 60.0
FOLLOW_UP_SCHEDULE_TIMEOUT_SECONDS = 5.0
```

4. Добавить функцию (после `_send_reply`, перед `_reply`):

```python
async def _schedule_follow_up(
    bot: Bot,
    chat_id: str,
    contact_id: uuid.UUID,
    after_seq: int,
) -> None:
    """FEATURES.md 5.5: ставит Celery-задачу с eta, не таймер в памяти (см.
    "грабли" CLAUDE.md). Сбой постановки (Redis/Celery недоступен) — не
    должен маскировать уже успешно отправленный клиенту ответ: перехватываем
    здесь, не пробрасываем в общий except _process_entry.
    """
    if not bot.settings.get("reminder_enabled", False):
        return

    delay_value = bot.settings.get("reminder_delay_minutes", DEFAULT_REMINDER_DELAY_MINUTES)
    try:
        delay_minutes = float(delay_value)
    except (TypeError, ValueError):
        delay_minutes = DEFAULT_REMINDER_DELAY_MINUTES

    eta = datetime.now(UTC) + timedelta(minutes=delay_minutes)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                celery_app.send_task,
                FOLLOW_UP_REMINDER,
                args=[str(bot.id), str(contact_id), chat_id, after_seq],
                eta=eta,
            ),
            timeout=FOLLOW_UP_SCHEDULE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "failed to schedule follow-up reminder",
            bot_id=str(bot.id),
            chat_id=chat_id,
            exc_info=True,
        )
```

5. В `_reply`, заменить блок записи ответа (после `_send_reply`) —
   добавить вызов `_schedule_follow_up` после сохранения `outgoing_seq`
   (переменная уже введена в Task 3, здесь она наконец используется):

```python
    await _send_reply(event, redis, result.text)

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()
    await _schedule_follow_up(bot, event.chat_id, contact_id, outgoing_seq)
```

6. То же самое — в `_reply_with_vision`, в её финальном блоке (после
   `_send_reply`):

```python
    await _send_reply(event, redis, result.text)

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()
    await _schedule_follow_up(bot, event.chat_id, contact_id, outgoing_seq)
```

- [ ] **Step 4: Прогнать новые тесты — ожидаем PASS**

Run: `pytest services/worker/tests/pipeline/test_followup_scheduling.py -v`

Expected: PASS (3 теста)

- [ ] **Step 5: Прогнать весь worker-пакет — регрессия**

Run: `pytest services/worker -v`

Expected: PASS, весь пакет без регрессий (существующие тесты не задают
`reminder_enabled` в `settings`, значит `_schedule_follow_up` у них рано
возвращается — `celery_app.send_task` реально не дёргается, никакого
сетевого вызова в тестах, где это не проверяется явно).

- [ ] **Step 6: Commit**

```bash
git add services/worker/pyproject.toml services/worker/src/worker/pipeline/consumer.py \
        services/worker/tests/pipeline/test_followup_scheduling.py
git commit -m "feat(worker): schedule follow-up reminder after real LLM replies

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Docker/Makefile/конфиг — сборка нового сервиса

**Files:**
- Create: `services/celery/Dockerfile`
- Modify: `compose/docker-compose.dev.yml`
- Modify: `Makefile`
- Modify: `pyproject.toml` (корень — `mypy_path`, новые overrides не нужны)
- Modify: `services/worker/Dockerfile`

**Interfaces:** нет — только конфигурация окружения.

- [ ] **Step 1: Dockerfile для celery**

Создать `services/celery/Dockerfile`:

```dockerfile
# Контекст сборки — корень репозитория (нужен доступ к libs/*)
FROM python:3.12-slim

WORKDIR /app

COPY libs /app/libs
COPY services/celery /app/services/celery

RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/scheduling -e /app/services/celery

CMD ["celery", "-A", "tasks", "worker", "--loglevel=info"]
```

- [ ] **Step 2: Добавить `scheduling` в Dockerfile worker'а**

В `services/worker/Dockerfile`, добавить `-e /app/libs/scheduling` в pip install:

```dockerfile
RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/llm -e /app/libs/integrations -e /app/libs/scheduling -e /app/services/worker
```

- [ ] **Step 3: Новый сервис в dev-compose**

В `compose/docker-compose.dev.yml`, добавить в конец секции `services`
(после `worker`, перед `api`):

```yaml
  celery:
    build:
      context: ..
      dockerfile: services/celery/Dockerfile
    environment:
      DATABASE_URL: postgres://platform:platform@postgres:5432/platform
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ../services/celery/src:/app/services/celery/src
      - ../libs:/app/libs
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
```

(без `healthcheck` — нет HTTP-эндпоинта; никто не ждёт готовности `celery`
через `depends_on: condition: service_healthy` — задачи копятся в
Redis-очереди, пока воркер не поднимется, устойчивость к рестартам ради
этого и делается)

- [ ] **Step 4: Makefile и mypy_path**

В `Makefile`, цель `install`:

```makefile
install:
	python -m venv .venv || true
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	pip install -e libs/core -e libs/db -e libs/integrations -e libs/scheduling -e services/worker -e services/celery -r requirements-dev.txt
	cd services/gateway && npm install
```

Цель `lint`:

```makefile
lint:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	ruff check . && mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src services/worker/src services/celery/src
	cd services/gateway && npm run lint
```

В корневом `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "libs/core/src:libs/db/src:libs/llm/src:libs/integrations/src:libs/scheduling/src:services/worker/src:services/api/src:services/celery/src"
namespace_packages = true
explicit_package_bases = true
```

И добавить `"services/celery"` в `testpaths`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["libs", "services/worker", "services/api", "services/celery"]
norecursedirs = [".venv", "node_modules"]
```

- [ ] **Step 5: Установить всё локально и прогнать полный набор + линт**

Run:
```bash
pip install -e libs/core -e libs/db -e libs/llm -e libs/integrations -e libs/scheduling -e services/worker -e services/celery -e services/api
pytest -q
ruff check .
mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src services/worker/src services/celery/src
```

Expected: все тесты зелёные, ruff и mypy без ошибок.

- [ ] **Step 6: Commit**

```bash
git add services/celery/Dockerfile services/worker/Dockerfile compose/docker-compose.dev.yml Makefile pyproject.toml
git commit -m "feat(deploy): wire services/celery into dev compose and tooling

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Живой прогон (docker compose)

По [[live-verification-preference]] — это первый прогон НОВОГО СЕРВИСА,
особенно важно проверить живьём, не только тестами.

**Files:** нет (верификация)

- [ ] **Step 1: Поднять dev-стек**

Проверить свободное место (`Get-PSDrive C`), затем
`docker compose -f compose/docker-compose.dev.yml up --build -d`. Убедиться,
что контейнер `celery` стартовал и не падает в рестарт-луп
(`docker compose -f compose/docker-compose.dev.yml ps` — `celery` без
healthcheck, но должен быть `Up`, не `Restarting`).

- [ ] **Step 2: Прогнать миграции** (если есть новые — для этой фичи их
нет, но стоит свериться, что `alembic upgrade head` в контейнере `worker`
проходит чисто на всякий случай)

- [ ] **Step 3: Создать тестового бота с включёнными напоминаниями**

Через `psql`, короткая задержка для живой проверки (не ждать 60 минут):

```sql
INSERT INTO bots (name, enabled, system_prompt, timezone, settings)
VALUES (
  'followup-test-bot', true, 'Ты ассистент.', 'Asia/Bishkek',
  '{"batch_timeout_seconds": 0.1, "reminder_enabled": true, "reminder_delay_minutes": 0.1, "reminder_message": "Напоминаем о себе!"}'::jsonb
)
RETURNING id;
```

(`0.1` минуты = 6 секунд — достаточно, чтобы не ждать долго, но заметно
дольше, чем занимает сам прогон пайплайна)

- [ ] **Step 4: Отправить сообщение, дождаться постановки задачи**

`XADD` в `wa:in` обычное текстовое сообщение от этого бота (без
`OPENAI_API_KEY` реальный LLM-ответ не придёт — см. ограничение из
предыдущих итераций этой сессии; альтернативы: (a) временно замокать
`complete` нельзя в живом контейнере — значит для ПОЛНОЙ живой проверки
нужен реальный `OPENAI_API_KEY` в `.env`; (b) без ключа — проверить только
то, что доходит до попытки ответа и логируется ошибка LLM, без постановки
задачи (т.к. `_schedule_follow_up` вызывается только после успешного
ответа) — это ожидаемое и уже задокументированное для этой машины
ограничение, не блокер).

Если ключ есть — после успешного ответа проверить логи `celery`:
`docker compose -f compose/docker-compose.dev.yml logs celery --tail 30` —
должна появиться запись о полученной задаче; через ~6 секунд — о её
исполнении (`follow-up reminder sent` или `follow-up skipped: ...`).

- [ ] **Step 5: Проверить деградацию — клиент ответил до срабатывания**

Сразу после шага 4 (пока 6-секундное окно не истекло) отправить ещё одно
сообщение от того же клиента. Дождаться срабатывания задачи (лог
`celery`) — должно быть `follow-up skipped: customer already replied`, в
`wa:out`/`messages` не должно появиться напоминания.

- [ ] **Step 6: Свериться с БД**

`docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "SELECT role, content, seq FROM messages ORDER BY seq;"`
— напоминание (если сработало) видно как обычная строка `role=assistant`.

- [ ] **Step 7: Обновить память проекта**

Обновить [[stage1-core-progress]]: 5.5 закрыт, `services/celery` — первый
живой прогон. Отметить, что реализовано без `celery beat` (нет
периодических задач в скоупе Волны 1) — следующая задача, которой
понадобится `beat`, добавляет его отдельным шагом в compose.
