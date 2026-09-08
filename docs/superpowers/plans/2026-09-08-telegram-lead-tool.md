# Лиды в Telegram-группу (FEATURES.md 4.7) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** вторая настоящая тулза платформы — `send_telegram_lead`: LLM собирает данные клиента и шлёт уведомление менеджерам в Telegram-группу бота, как это делал V1 (`sendToTelegramGroup`).

**Architecture:** `libs/integrations/src/integrations/telegram.py` — тонкий HTTP-клиент Telegram Bot API (новая зависимость `httpx`, инжектируемый `transport` для тестов без реальной сети). `libs/tools/src/tools/telegram_lead.py` — сама тулза (единственное место, знающее и про `integrations.telegram`, и про `db.contacts`). `libs/db/src/db/contacts.py` получает узкую `get_contact()`. Токен — платформенный env var (`TELEGRAM_BOT_TOKEN`), `chat_id` — per bot через `tool_bindings.config` (уже так задумано в комментарии `ToolBinding`).

**Tech Stack:** Python 3.12, `httpx` (async HTTP), SQLAlchemy 2.0 async, pytest + testcontainers.

**Spec:** `docs/superpowers/specs/2026-09-08-telegram-lead-tool-design.md`

## Global Constraints

- Набор полей лида — generic (по образцу V1 node-bot2): `client_name` (required), `phone_number` (НЕ required, fallback на `wa_id` контакта), `details` (required). Никакой per-bot-настраиваемой схемы полей в этой итерации.
- Токен — один платформенный env var `TELEGRAM_BOT_TOKEN` (ADR-007, только на серверах, никогда не в коде/тестах). `chat_id` — per bot, `tool_bindings.config["chat_id"]`.
- Тулза никогда не бросает исключение наружу из `execute()` — любой сбой (нет токена, нет chat_id, сетевая ошибка, ошибка Telegram API) возвращается как текст в `ToolExecutionResult.content`, эталон V1.
- `override_reply_text`/`media` не используются этой тулзой (не карточка клиенту — LLM сама формулирует, что сказать дальше).
- Не входит в эту итерацию: per-bot схема полей (задел на UI), нормализация номера (FEATURES.md 9.1 — отдельная фича, `wa_id` используется как есть), ретраи HTTP-вызова к Telegram.
- Любой внешний вызов — с явным таймаутом (CLAUDE.md, `REQUEST_TIMEOUT_SECONDS`), укладывающимся в общий бюджет тулзы (`TOOL_CALL_TIMEOUT_SECONDS=20с` в `worker/pipeline/tool_loop.py`).
- FEATURES.md 4.7 фиксирует найденное расхождение с архивом прямо в файле (по прецеденту 4.2/4.3/4.5/4.6): реальная сигнатура V1 без `notificationType`, статус — `V1-DRIFT` (набор полей лида разъехался между копиями архива), не просто `V1`.

---

## Task 1: `libs/integrations` — клиент Telegram Bot API

**Files:**
- Modify: `libs/integrations/pyproject.toml`
- Create: `libs/integrations/src/integrations/telegram.py`
- Create: `libs/integrations/tests/test_telegram.py`

**Interfaces:**
- Produces: `async send_message(chat_id: str, text: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None` — бросает `TelegramNotConfiguredError` (нет `TELEGRAM_BOT_TOKEN`) или `httpx.HTTPStatusError`/`RuntimeError` (сбой отправки); используется Task 3 (`telegram_lead.py`). `TelegramNotConfiguredError(Exception)` — экспортируется, ловится вызывающим.

- [ ] **Step 1: Добавить `httpx` в зависимости пакета**

В `libs/integrations/pyproject.toml` заменить:

```toml
dependencies = [
    "boto3>=1.34",
]
```

на:

```toml
dependencies = [
    "boto3>=1.34",
    "httpx>=0.27",
]
```

- [ ] **Step 2: Написать падающий тест**

Создать `libs/integrations/tests/test_telegram.py`:

```python
"""Клиент Telegram Bot API (FEATURES.md 4.7) — реальная сеть никогда не
используется, httpx.MockTransport подменяет транспорт целиком.
"""

from __future__ import annotations

import json

import httpx
import pytest
from integrations.telegram import TelegramNotConfiguredError, send_message


def _mock_transport(status_code: int, response_json: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_json)

    return httpx.MockTransport(handler)


async def test_send_message_posts_chat_id_and_text_to_telegram_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    await send_message("12345", "Новая заявка", transport=httpx.MockTransport(handler))

    assert captured["url"] == "https://api.telegram.org/bottest-token/sendMessage"
    assert captured["body"] == {
        "chat_id": "12345",
        "text": "Новая заявка",
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }


async def test_send_message_raises_when_token_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(TelegramNotConfiguredError):
        await send_message("12345", "текст")


async def test_send_message_raises_on_http_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    transport = _mock_transport(401, {"ok": False, "description": "Unauthorized"})

    with pytest.raises(httpx.HTTPStatusError):
        await send_message("12345", "текст", transport=transport)


async def test_send_message_raises_when_telegram_reports_not_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    transport = _mock_transport(200, {"ok": False, "description": "chat not found"})

    with pytest.raises(RuntimeError, match="chat not found"):
        await send_message("12345", "текст", transport=transport)
```

- [ ] **Step 3: Прогнать — RED**

Run: `cd libs/integrations && ../../.venv/Scripts/python.exe -m pytest tests/test_telegram.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.telegram'`.

- [ ] **Step 4: Реализовать клиент**

Создать `libs/integrations/src/integrations/telegram.py`:

```python
"""Клиент Telegram Bot API (FEATURES.md 4.7) — тонкая обёртка над
sendMessage. Токен — платформенный (ADR-007, .env только на серверах),
chat_id — per bot, передаётся вызывающим
(tool_bindings.config, см. libs/tools/telegram_lead.py).
"""

from __future__ import annotations

import os

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10.0


class TelegramNotConfiguredError(Exception):
    """TELEGRAM_BOT_TOKEN не задан в окружении — платформа не настроена
    на отправку уведомлений в Telegram вообще (не путать с тем, что у
    конкретного бота нет chat_id — это отдельная, per-bot ошибка,
    обрабатывается в tools/telegram_lead.py)."""


async def send_message(
    chat_id: str, text: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Бросает исключение при сбое (нет токена, сетевая ошибка, ошибка
    Telegram API) — вызывающий (тулза) решает, как это представить LLM.

    transport — только для тестов (httpx.MockTransport), в проде всегда
    None (реальный транспорт httpx)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN не задан")

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload.get('description')}")
```

- [ ] **Step 5: Прогнать — GREEN**

Run: `cd libs/integrations && ../../.venv/Scripts/python.exe -m pytest tests/test_telegram.py -v`
Expected: PASS (4 теста).

- [ ] **Step 6: Установить обновлённый пакет и прогнать полный пакет `libs/integrations`**

Run (из корня репозитория, чтобы подтянуть новую зависимость `httpx` в уже установленный editable-пакет):
`.venv/Scripts/pip.exe install -e libs/integrations`
Run: `cd libs/integrations && ../../.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (все тесты пакета, включая уже существующие storage-тесты).

- [ ] **Step 7: Commit**

```bash
git add libs/integrations/pyproject.toml libs/integrations/src/integrations/telegram.py libs/integrations/tests/test_telegram.py
git commit -m "feat(integrations): Telegram Bot API client (FEATURES.md 4.7)"
```

---

## Task 2: `libs/db` — `get_contact`

**Files:**
- Modify: `libs/db/src/db/contacts.py`
- Modify: `libs/db/tests/test_contacts.py`

**Interfaces:**
- Produces: `async get_contact(session: AsyncSession, contact_id: uuid.UUID) -> Contact | None` — используется Task 3 (`telegram_lead.py`).

- [ ] **Step 1: Написать падающий тест**

Добавить в `libs/db/tests/test_contacts.py`, в импорт добавить `get_contact`:

```python
from db.contacts import get_contact, match_or_create_contact
```

Добавить в конец файла:

```python


async def test_get_contact_returns_contact_by_id(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    created = await match_or_create_contact(session, bot_id, wa_id="996700000099", lid=None)

    found = await get_contact(session, created.id)

    assert found is not None
    assert found.id == created.id
    assert found.wa_id == "996700000099"


async def test_get_contact_returns_none_for_unknown_id(session: AsyncSession) -> None:
    assert await get_contact(session, uuid.uuid4()) is None
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd libs/db && ../../.venv/Scripts/python.exe -m pytest tests/test_contacts.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_contact'`.

- [ ] **Step 3: Реализовать `get_contact`**

В `libs/db/src/db/contacts.py` добавить в конец файла:

```python


async def get_contact(session: AsyncSession, contact_id: uuid.UUID) -> Contact | None:
    return await session.get(Contact, contact_id)
```

- [ ] **Step 4: Прогнать — GREEN**

Run: `cd libs/db && ../../.venv/Scripts/python.exe -m pytest tests/test_contacts.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Commit**

```bash
git add libs/db/src/db/contacts.py libs/db/tests/test_contacts.py
git commit -m "feat(db): add get_contact lookup by id"
```

---

## Task 3: `libs/tools` — тулза `send_telegram_lead`

**Files:**
- Create: `libs/tools/src/tools/telegram_lead.py`
- Modify: `libs/tools/src/tools/registry.py`
- Create: `libs/tools/tests/test_telegram_lead.py`
- Modify: `libs/tools/tests/test_registry.py`
- Modify: `docs/FEATURES.md`

**Interfaces:**
- Consumes: `send_message`/`TelegramNotConfiguredError` (Task 1, `integrations.telegram`), `get_contact` (Task 2, `db.contacts`).
- Produces: `TelegramLeadTool` — зарегистрирована в реестре под именем `send_telegram_lead`.

- [ ] **Step 1: Написать падающий тест реестра**

В `libs/tools/tests/test_registry.py` добавить в конец файла:

```python


def test_all_tool_names_includes_send_telegram_lead() -> None:
    """Вторая настоящая тулза (FEATURES.md 4.7)."""
    assert "send_telegram_lead" in registry.all_tool_names()
```

- [ ] **Step 2: Написать падающие тесты тулзы**

Создать `libs/tools/tests/test_telegram_lead.py`:

```python
"""TelegramLeadTool (FEATURES.md 4.7): generic-набор полей лида,
никогда не бросает исключение из execute() — любой сбой уходит текстом
в content (эталон V1, sendToTelegramGroup). Требует Docker
(testcontainers) для подгрузки контакта — реальная отправка в Telegram
подменена фейком (не настоящая сеть).
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
from db.contacts import match_or_create_contact
from db.engine import make_engine, make_session_factory
from db.models import Bot
from integrations.telegram import TelegramNotConfiguredError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import telegram_lead as telegram_lead_module
from tools.base import ToolContext
from tools.telegram_lead import TelegramLeadTool

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


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> Bot:
    async with session_factory() as session:
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot


async def _make_contact(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID, wa_id: str
) -> uuid.UUID:
    async with session_factory() as session:
        contact = await match_or_create_contact(session, bot_id, wa_id=wa_id, lid=None)
        await session.commit()
        return contact.id


def _make_ctx(
    bot: Bot,
    contact_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    config: dict[str, object],
) -> ToolContext:
    return ToolContext(
        bot=bot,
        contact_id=contact_id,
        session_factory=session_factory,
        redis=None,  # type: ignore[arg-type]  # эта тулза не использует redis
        storage=None,  # type: ignore[arg-type]  # эта тулза не использует storage
        config=config,
    )


async def test_missing_chat_id_returns_error_without_calling_telegram(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_send_message(*args: object, **kwargs: object) -> None:
        raise AssertionError("не должен вызываться без chat_id")

    monkeypatch.setattr(telegram_lead_module, "send_message", fail_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000010")

    result = await TelegramLeadTool().execute(
        {"client_name": "Аяна", "details": "Интересует 2-комнатная"},
        _make_ctx(bot, contact_id, session_factory, config={}),
    )

    assert result.content == telegram_lead_module._MISSING_CHAT_ID_ERROR


async def test_successful_send_returns_confirmation_and_uses_contact_wa_id(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_send_message(chat_id: str, text: str) -> None:
        captured["chat_id"] = chat_id
        captured["text"] = text

    monkeypatch.setattr(telegram_lead_module, "send_message", fake_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000011")

    result = await TelegramLeadTool().execute(
        {"client_name": "Бекзат", "details": "Спрашивал про рассрочку"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-1001234567890"}),
    )

    assert captured["chat_id"] == "-1001234567890"
    assert "Бекзат" in str(captured["text"])
    assert "Спрашивал про рассрочку" in str(captured["text"])
    # Клиент не назвал отдельный номер -> используется wa_id контакта.
    assert "996700000011" in str(captured["text"])
    assert result.content == "Заявка отправлена менеджерам."
    assert result.override_reply_text is None
    assert result.media == ()


async def test_explicit_phone_number_overrides_contact_wa_id(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_send_message(chat_id: str, text: str) -> None:
        captured["text"] = text

    monkeypatch.setattr(telegram_lead_module, "send_message", fake_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000012")

    await TelegramLeadTool().execute(
        {"client_name": "Данияр", "phone_number": "996555000000", "details": "Хочет каталог"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-100999"}),
    )

    assert "996555000000" in str(captured["text"])
    assert "996700000012" not in str(captured["text"])


async def test_telegram_not_configured_returns_error_text(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_send_message(*args: object, **kwargs: object) -> None:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN не задан")

    monkeypatch.setattr(telegram_lead_module, "send_message", fail_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000013")

    result = await TelegramLeadTool().execute(
        {"client_name": "Клиент", "details": "Детали"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-100999"}),
    )

    assert result.content == telegram_lead_module._NOT_CONFIGURED_ERROR


async def test_network_failure_returns_error_text_without_raising(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_send_message(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Telegram API error: chat not found")

    monkeypatch.setattr(telegram_lead_module, "send_message", fail_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000014")

    result = await TelegramLeadTool().execute(
        {"client_name": "Клиент", "details": "Детали"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-100999"}),
    )

    assert result.content == "Не удалось отправить заявку в Telegram."
```

- [ ] **Step 3: Прогнать — RED**

Run: `cd libs/tools && ../../.venv/Scripts/python.exe -m pytest tests/test_telegram_lead.py tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.telegram_lead'`.

- [ ] **Step 4: Реализовать тулзу**

Создать `libs/tools/src/tools/telegram_lead.py`:

```python
"""Лид в Telegram-группу (FEATURES.md 4.7) — эталон V1 (sendToTelegramGroup),
generic-набор полей (не привязан к нише клиента, см.
docs/superpowers/specs/2026-09-08-telegram-lead-tool-design.md). chat_id —
per bot (tool_bindings.config), токен — платформенный (integrations.telegram).
"""

from __future__ import annotations

from typing import Any, ClassVar

from db.contacts import get_contact
from integrations.telegram import TelegramNotConfiguredError, send_message

from .base import ToolContext, ToolExecutionResult

_MISSING_CHAT_ID_ERROR = "Лиды в Telegram не настроены для этого бота (нет chat_id)."
_NOT_CONFIGURED_ERROR = "Лиды в Telegram не настроены на платформе (нет TELEGRAM_BOT_TOKEN)."
_SEND_FAILED_ERROR = "Не удалось отправить заявку в Telegram."
_SUCCESS_MESSAGE = "Заявка отправлена менеджерам."


def _format_lead_message(client_name: str, phone: str, details: str, wa_link: str | None) -> str:
    """Эталон V1 (sendToTelegramGroup) — нейтральный текст, не привязанный
    к нише клиента (в архиве было под конкретный бизнес каждой копии).
    wa_link — None только если у контакта почему-то нет wa_id (LID-only,
    редкий переходный случай FEATURES.md 9.2) — тогда строку ссылки не
    добавляем вовсе, а не рендерим невалидный Markdown-URL."""
    parts = [
        "*Новая заявка*",
        "",
        f"*Клиент:* {client_name}",
        f"*Телефон:* `{phone}`",
        f"*Детали:* {details}",
    ]
    if wa_link:
        parts += ["", f"[Написать в WhatsApp]({wa_link})"]
    return "\n".join(parts)


class TelegramLeadTool:
    name = "send_telegram_lead"
    description = "Отправляет заявку клиента менеджерам в Telegram-группу."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "Имя клиента"},
            "phone_number": {
                "type": "string",
                "description": (
                    "Номер телефона клиента, если он назвал ДРУГОЙ номер, не тот, "
                    "с которого пишет в WhatsApp. Если не называл — не заполнять."
                ),
            },
            "details": {
                "type": "string",
                "description": "Что интересует клиента, контекст диалога",
            },
        },
        "required": ["client_name", "details"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        chat_id = ctx.config.get("chat_id")
        if not chat_id:
            return ToolExecutionResult(content=_MISSING_CHAT_ID_ERROR)

        async with ctx.session_factory() as session:
            contact = await get_contact(session, ctx.contact_id)

        wa_id = contact.wa_id if contact is not None else None
        phone = str(arguments.get("phone_number") or wa_id or "не указан")
        client_name = str(arguments.get("client_name", ""))
        details = str(arguments.get("details", ""))
        wa_link = f"https://wa.me/{wa_id}" if wa_id else None

        message = _format_lead_message(client_name, phone, details, wa_link)

        try:
            await send_message(str(chat_id), message)
        except TelegramNotConfiguredError:
            return ToolExecutionResult(content=_NOT_CONFIGURED_ERROR)
        except Exception:
            return ToolExecutionResult(content=_SEND_FAILED_ERROR)

        return ToolExecutionResult(content=_SUCCESS_MESSAGE)
```

- [ ] **Step 5: Зарегистрировать тулзу**

В `libs/tools/src/tools/registry.py` заменить:

```python
from .base import Tool
from .product_search import ProductSearchTool

_REGISTRY: dict[str, Tool] = {}
```

на:

```python
from .base import Tool
from .product_search import ProductSearchTool
from .telegram_lead import TelegramLeadTool

_REGISTRY: dict[str, Tool] = {}
```

И заменить последнюю строку файла:

```python
register(ProductSearchTool())
```

на:

```python
register(ProductSearchTool())
register(TelegramLeadTool())
```

- [ ] **Step 6: Прогнать — GREEN**

Run: `cd libs/tools && ../../.venv/Scripts/python.exe -m pytest tests/test_telegram_lead.py tests/test_registry.py -v`
Expected: PASS (6 тестов тулзы + 6 тестов реестра, включая новый).

- [ ] **Step 7: Прогнать mypy strict и ruff**

Run (из корня репозитория): `.venv/Scripts/python.exe -m mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src libs/tools/src services/worker/src services/celery/src`
Expected: без новых ошибок (единственная преdexisting — `libs/core/src/core/bus.py:23`, не связана с этой веткой).
Run: `.venv/Scripts/python.exe -m ruff check .`
Expected: чисто.

- [ ] **Step 8: Обновить FEATURES.md 4.7**

В `docs/FEATURES.md` заменить строку:

```
| 4.7 | Лиды в Telegram-группу | V1 | `sendToTelegramGroup(data, userId, notificationType)` — единая функция под разные типы |
```

на:

```
| 4.7 | Лиды в Telegram-группу | V1-DRIFT | Реально: `sendToTelegramGroup(data, userId)` — без третьего параметра, его не было ни в одной копии архива. Набор полей лида и текст сообщения жёстко зашиты под нишу клиента и разъехались между копиями (недвижимость — 6 полей, стройка — 3) — у нас generic-стандарт (имя/телефон/свободный текст), см. docs/superpowers/specs/2026-09-08-telegram-lead-tool-design.md |
```

- [ ] **Step 9: Прогнать полный пакет `libs/tools` и весь репозиторий**

Run: `cd libs/tools && ../../.venv/Scripts/python.exe -m pytest -v`
Run (из корня репозитория): `.venv/Scripts/python.exe -m pytest -q`
Expected: всё зелёное, без регрессий.

- [ ] **Step 10: Commit**

```bash
git add libs/tools/src/tools/telegram_lead.py libs/tools/src/tools/registry.py libs/tools/tests/test_telegram_lead.py libs/tools/tests/test_registry.py docs/FEATURES.md
git commit -m "feat(tools): telegram lead notification tool (FEATURES.md 4.7)"
```

---

## Task 4: Живой прогон

**Files:** нет изменений кода — только проверка на реальном стенде.

- [ ] **Step 1: Пересобрать образы, задействующие `libs/integrations`/`libs/tools`**

Run: `docker compose -f compose/docker-compose.dev.yml build worker api`
Expected: успешная сборка — `httpx` подтягивается автоматически через
`pip install -e /app/libs/integrations` (пакет `integrations` уже в
списке `-e` обоих Dockerfile, в Dockerfile ничего менять не пришлось).

- [ ] **Step 2: Поднять стенд, зарегистрировать тулзу через API**

```bash
docker compose -f compose/docker-compose.dev.yml up -d
```

Создать тестового бота (как в прошлых live-прогонах), включить тулзу:
`POST /bots/{id}/tools {"tool_name": "send_telegram_lead", "config": {"chat_id": "<тестовый chat_id>"}}` → должен вернуть 201 (реестр знает тулзу — не 400, как было бы при рассинхроне).

- [ ] **Step 3: Проверить путь без реального Telegram-токена**

Без `TELEGRAM_BOT_TOKEN` в `.env` (как и с `OPENAI_API_KEY` в прошлых
итерациях, ключа на машине разработки нет) — прямой вызов
`send_message()` внутри контейнера worker должен упасть с
`TelegramNotConfiguredError`, тулза — вернуть `_NOT_CONFIGURED_ERROR`, не
уронить пайплайн. Проверить логами worker при реальном сообщении,
провоцирующем вызов тулзы (потребует `OPENAI_API_KEY` для самого
диалога — тот же открытый пункт, что и во всех прошлых итерациях: без
ключа деградация ожидаема ДО вызова тулзы, специфический для этой фичи
путь без ключа не проверить, как и раньше).

- [ ] **Step 4: Обновить память проекта**

Обновить/создать памятку в
`C:\Users\user\.claude\projects\C--Work-Projects-whatsapp-bot\memory\`
(например `wave2-telegram-lead-progress.md`) с итогом итерации: что
сдано, найденное расхождение V1-DRIFT, что осталось в Волне 2 (4.8/4.9),
и добавить строку в `MEMORY.md`.

## Самопроверка плана (для исполнителя перед стартом)

- **Покрытие спеки**: клиент Telegram (Task 1) → `get_contact` (Task 2)
  → тулза + регистрация + FEATURES.md (Task 3) → живой прогон (Task 4).
  Все разделы спеки `2026-09-08-telegram-lead-tool-design.md` покрыты,
  включая «Границы этой итерации» (per-bot схема полей, нормализация
  номера, ретраи — ничего из списка не реализуется).
- **Плейсхолдеров нет**: каждый шаг содержит полный код.
- **Согласованность типов**: `send_message(chat_id: str, text: str, *, transport=None)`
  определена один раз в Task 1 и используется с той же сигнатурой (без
  `transport` — тулза его не передаёт, реальный транспорт в проде) в
  Task 3. `get_contact(session, contact_id) -> Contact | None` определена
  один раз в Task 2, используется в Task 3 с теми же именами.
  `_NOT_CONFIGURED_ERROR`/`_SEND_FAILED_ERROR`/`_MISSING_CHAT_ID_ERROR`/`_SUCCESS_MESSAGE`
  определены один раз в Task 3's `telegram_lead.py` и используются с теми
  же именами в его же тестах (та же задача — согласованность в
  пределах задачи, не между задачами).
