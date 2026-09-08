# Отправка файлов и видео (FEATURES.md 4.8/4.9) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** третья настоящая тулза платформы — `send_document`: LLM просит отправить клиенту файл или видео по точному имени из списка, известного боту; тулза находит его в БД, файл/видео уходит клиенту (видео — нативным video-сообщением, остальное — документом).

**Architecture:** новая таблица `documents` (`libs/db`) + два узких события `outbound.document`/`outbound.video` (тот же принцип, что `outbound.image` из 4.3/4.4) + `SessionManager.sendDocument()`/`sendVideo()` в gateway + `MediaToSend` получает необязательное поле `filename` + `_send_cards()` в worker учится диспетчеризовать по `mime_type` вместо единственной image-ветки + `documents_context()` (аналог `catalog_context`) в system prompt.

**Tech Stack:** Python 3.12, TypeScript (Baileys), SQLAlchemy 2.0 async, Alembic, pytest + testcontainers, vitest.

**Spec:** `docs/superpowers/specs/2026-09-08-document-video-sending-design.md`

## Global Constraints

- Одна тулза `send_document(file_name)` на оба случая (файл/видео) — LLM не выбирает тип, тулза сама смотрит `mime_type` найденного `Document` и решает способ отправки: `video/*` → `outbound.video`, всё остальное → `outbound.document`.
- Список файлов — в system prompt (`documents_context`, симметрично каталогу товаров 3.4) — платформенное дополнение сверх V1 (там список знал только владелец бота).
- Поиск файла — точное совпадение имени (`==`, НЕ `LOWER(TRIM())` как у товаров — имена файлов регистрозависимы), `UNIQUE(bot_id, filename)` на уровне БД.
- Override-паттерн без изменения контракта тулз — `override_reply_text` подавляет ответ LLM целиком, эталон V1 (`isFileSent` в архиве работает идентично находке товара).
- `outbound.document` несёт обязательный `filename` (Baileys требует `fileName` для показа документа клиенту), `outbound.video` — не несёт (не нужен видео-сообщению).
- Не входит в эту итерацию: загрузка файлов ботом (Wave 3, 6.7 — заполнение `documents` только вручную через SQL на этой итерации), ретраи с backoff (тот же техдолг, что у `outbound.image`), ограничение размера исходящего файла (тот же открытый пункт, что у 4.3/4.4).
- Любой внешний вызов — с явным таймаутом (CLAUDE.md), тот же паттерн, что уже есть у `outbound.image` (`storageGet`/`sendImage` таймауты в `OutboundConsumer`).

---

## Task 1: Контракт событий — `outbound.document` + `outbound.video`

**Files:**
- Modify: `docs/contracts/events.schema.json`
- Modify: `libs/core/src/core/events.py`
- Modify: `services/gateway/src/contracts/events.ts`
- Create: `docs/contracts/examples/outbound.document.json`
- Create: `docs/contracts/examples/outbound.video.json`

**Interfaces:**
- Produces: Pydantic `OutboundDocument`/`OutboundVideo` (`libs/core/src/core/events.py`); zod `OutboundDocument`/`OutboundVideo` (`services/gateway/src/contracts/events.ts`). Оба входят в объединение `Event` в обоих местах. Используются Task 4 (gateway) и Task 6 (worker).

Тесты — уже существующие data-driven файлы (`libs/core/tests/test_events_contract.py`,
`services/gateway/src/contracts/events.test.ts`) подхватывают любой файл в
`docs/contracts/examples/*.json` автоматически — новых тестов писать не нужно.

- [ ] **Step 1: Добавить фикстуры (RED — типов ещё нет ни в схеме, ни в моделях)**

Создать `docs/contracts/examples/outbound.document.json`:

```json
{
  "type": "outbound.document",
  "bot_id": "00000000-0000-0000-0000-000000000001",
  "chat_id": "996700000000@s.whatsapp.net",
  "storage_key": "bots/00000000-0000-0000-0000-000000000001/documents/price-list.pdf",
  "mime_type": "application/pdf",
  "filename": "price-list.pdf",
  "client_msg_id": "9f3e9c1a4b2d4e119f0a1234567890ab"
}
```

Создать `docs/contracts/examples/outbound.video.json`:

```json
{
  "type": "outbound.video",
  "bot_id": "00000000-0000-0000-0000-000000000001",
  "chat_id": "996700000000@s.whatsapp.net",
  "storage_key": "bots/00000000-0000-0000-0000-000000000001/documents/tour.mp4",
  "mime_type": "video/mp4",
  "client_msg_id": "af3e9c1a4b2d4e119f0a1234567890ab"
}
```

- [ ] **Step 2: Убедиться, что оба контрактных теста падают**

Run: `cd libs/core && ../../.venv/Scripts/python.exe -m pytest tests/test_events_contract.py -v`
Expected: FAIL — лишние типы в примерах, которых нет в схеме.

Run: `cd services/gateway && npx vitest run src/contracts/events.test.ts`
Expected: FAIL по той же причине.

- [ ] **Step 3: Добавить `outboundDocument`/`outboundVideo` в JSON Schema**

В `docs/contracts/events.schema.json` — новые определения в `definitions`
(вставить после блока `"outboundImage"`, перед `"outboundTyping"`):

```json
    "outboundDocument": {
      "type": "object",
      "description": "Исходящий файл в wa:out (FEATURES.md 4.8).",
      "additionalProperties": false,
      "properties": {
        "type": { "const": "outbound.document" },
        "bot_id": { "type": "string", "format": "uuid" },
        "chat_id": { "type": "string", "minLength": 1 },
        "storage_key": { "type": "string", "minLength": 1 },
        "mime_type": { "type": "string", "minLength": 1 },
        "filename": { "type": "string", "minLength": 1 },
        "client_msg_id": { "type": "string", "minLength": 1 }
      },
      "required": ["type", "bot_id", "chat_id", "storage_key", "mime_type", "filename", "client_msg_id"]
    },
    "outboundVideo": {
      "type": "object",
      "description": "Исходящее видео в wa:out (FEATURES.md 4.9).",
      "additionalProperties": false,
      "properties": {
        "type": { "const": "outbound.video" },
        "bot_id": { "type": "string", "format": "uuid" },
        "chat_id": { "type": "string", "minLength": 1 },
        "storage_key": { "type": "string", "minLength": 1 },
        "mime_type": { "type": "string", "minLength": 1 },
        "client_msg_id": { "type": "string", "minLength": 1 }
      },
      "required": ["type", "bot_id", "chat_id", "storage_key", "mime_type", "client_msg_id"]
    },
```

И добавить обе ссылки в `oneOf` (после `outboundImage`, перед `outboundTyping`):

```json
  "oneOf": [
    { "$ref": "#/definitions/inboundText" },
    { "$ref": "#/definitions/outboundText" },
    { "$ref": "#/definitions/outboundImage" },
    { "$ref": "#/definitions/outboundDocument" },
    { "$ref": "#/definitions/outboundVideo" },
    { "$ref": "#/definitions/outboundTyping" },
    { "$ref": "#/definitions/sessionStatus" }
  ]
```

- [ ] **Step 4: Добавить Pydantic-модели**

В `libs/core/src/core/events.py` — новые классы (после `OutboundImage`,
перед `OutboundTyping`):

```python
class OutboundDocument(BaseModel):
    """Исходящий файл в wa:out (FEATURES.md 4.8)."""

    type: Literal["outbound.document"] = "outbound.document"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class OutboundVideo(BaseModel):
    """Исходящее видео в wa:out (FEATURES.md 4.9)."""

    type: Literal["outbound.video"] = "outbound.video"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)
```

И расширить объединение:

```python
Event = (
    InboundText
    | OutboundText
    | OutboundImage
    | OutboundDocument
    | OutboundVideo
    | OutboundTyping
    | SessionStatus
)
```

- [ ] **Step 5: Добавить zod-схемы**

В `services/gateway/src/contracts/events.ts` — новые схемы (после
`OutboundImage`, перед `OutboundTyping`):

```typescript
export const OutboundDocument = z
  .object({
    type: z.literal("outbound.document"),
    bot_id: z.string().uuid(),
    chat_id: z.string().min(1),
    storage_key: z.string().min(1),
    mime_type: z.string().min(1),
    filename: z.string().min(1),
    client_msg_id: z.string().min(1),
  })
  .strict();
export type OutboundDocument = z.infer<typeof OutboundDocument>;

export const OutboundVideo = z
  .object({
    type: z.literal("outbound.video"),
    bot_id: z.string().uuid(),
    chat_id: z.string().min(1),
    storage_key: z.string().min(1),
    mime_type: z.string().min(1),
    client_msg_id: z.string().min(1),
  })
  .strict();
export type OutboundVideo = z.infer<typeof OutboundVideo>;
```

И расширить объединение:

```typescript
export const Event = z.discriminatedUnion("type", [
  InboundText,
  OutboundText,
  OutboundImage,
  OutboundDocument,
  OutboundVideo,
  OutboundTyping,
  SessionStatus,
]);
export type Event = z.infer<typeof Event>;
```

- [ ] **Step 6: Прогнать оба контрактных теста снова — GREEN**

Run: `cd libs/core && ../../.venv/Scripts/python.exe -m pytest tests/test_events_contract.py -v`
Expected: PASS (все параметризованные варианты).

Run: `cd services/gateway && npx vitest run src/contracts/events.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/contracts/events.schema.json docs/contracts/examples/outbound.document.json docs/contracts/examples/outbound.video.json libs/core/src/core/events.py services/gateway/src/contracts/events.ts
git commit -m "feat(contracts): add outbound.document and outbound.video event types"
```

---

## Task 2: `libs/db` — таблица `documents`

**Files:**
- Modify: `libs/db/src/db/models.py`
- Create: `libs/db/migrations/versions/202609080001_documents.py`
- Create: `libs/db/src/db/documents.py`
- Create: `libs/db/tests/test_documents.py`
- Modify: `libs/db/tests/test_migration.py`

**Interfaces:**
- Produces: `Document` модель (`id, bot_id, filename, storage_key, mime_type, created_at`). `list_documents(session, bot_id) -> list[Document]` и `find_document_by_filename(session, bot_id, filename) -> Document | None` (`libs/db/src/db/documents.py`) — используются Task 5 (`SendDocumentTool`) и Task 6 (`_reply()`'s system prompt).

- [ ] **Step 1: Написать падающие тесты**

Создать `libs/db/tests/test_documents.py`:

```python
"""Файлы бота (FEATURES.md 4.8/4.9): list_documents — сортировка по
filename, скоуп per bot; find_document_by_filename — точное совпадение
с учётом регистра (имена файлов, не разговорные названия). Требует
Docker (testcontainers). Без него — skip, не fail.
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
from db.documents import find_document_by_filename, list_documents
from db.engine import make_engine, make_session_factory
from db.models import Bot, Document
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


async def test_list_documents_empty_by_default(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    assert await list_documents(session, bot_id) == []


async def test_list_documents_ordered_by_filename(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add_all(
        [
            Document(
                bot_id=bot_id, filename="c-price.pdf", storage_key="k1", mime_type="application/pdf"
            ),
            Document(
                bot_id=bot_id, filename="a-contract.docx", storage_key="k2",
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            Document(
                bot_id=bot_id, filename="b-catalog.pdf", storage_key="k3", mime_type="application/pdf"
            ),
        ]
    )
    await session.flush()

    documents = await list_documents(session, bot_id)
    assert [d.filename for d in documents] == ["a-contract.docx", "b-catalog.pdf", "c-price.pdf"]


async def test_list_documents_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    session.add_all(
        [
            Document(bot_id=bot_a, filename="a.pdf", storage_key="ka", mime_type="application/pdf"),
            Document(bot_id=bot_b, filename="b.pdf", storage_key="kb", mime_type="application/pdf"),
        ]
    )
    await session.flush()

    documents_a = await list_documents(session, bot_a)
    assert [d.filename for d in documents_a] == ["a.pdf"]


async def test_find_document_by_filename_exact_match(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add(
        Document(
            bot_id=bot_id, filename="price-list.pdf", storage_key="k1", mime_type="application/pdf"
        )
    )
    await session.flush()

    found = await find_document_by_filename(session, bot_id, "price-list.pdf")
    assert found is not None
    assert found.storage_key == "k1"


async def test_find_document_by_filename_is_case_sensitive(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    session.add(
        Document(
            bot_id=bot_id, filename="Price-List.pdf", storage_key="k1", mime_type="application/pdf"
        )
    )
    await session.flush()

    assert await find_document_by_filename(session, bot_id, "price-list.pdf") is None
    assert await find_document_by_filename(session, bot_id, "Price-List.pdf") is not None


async def test_find_document_by_filename_returns_none_when_not_found(
    session: AsyncSession,
) -> None:
    bot_id = await _make_bot(session)
    assert await find_document_by_filename(session, bot_id, "нет-такого.pdf") is None


async def test_find_document_by_filename_scoped_per_bot(session: AsyncSession) -> None:
    bot_a = await _make_bot(session)
    bot_b = await _make_bot(session)
    session.add(
        Document(bot_id=bot_a, filename="only-a.pdf", storage_key="ka", mime_type="application/pdf")
    )
    await session.flush()

    assert await find_document_by_filename(session, bot_a, "only-a.pdf") is not None
    assert await find_document_by_filename(session, bot_b, "only-a.pdf") is None
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd libs/db && ../../.venv/Scripts/python.exe -m pytest tests/test_documents.py -v`
Expected: FAIL — `ImportError: cannot import name 'Document'`.

- [ ] **Step 3: Добавить модель `Document`**

В `libs/db/src/db/models.py`, в самый конец файла, после `ProductImage`:

```python


class Document(Base):
    """Файл бота (FEATURES.md 4.8/4.9) — любой тип; video/* отправляется
    нативным video-сообщением, остальное — документом (решает тулза по
    mime_type, см. libs/tools/send_document.py). Загрузка (заполнение
    этой таблицы) — Волна 3 (6.7), здесь только хранение и чтение."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("bot_id", "filename", name="uq_documents_bot_filename"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Создать миграцию**

Создать `libs/db/migrations/versions/202609080001_documents.py`:

```python
"""documents

Revision ID: 202609080001
Revises: 202609051005
Create Date: 2026-09-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609080001"
down_revision: str | None = "202609051005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bot_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("bot_id", "filename", name="uq_documents_bot_filename"),
    )


def downgrade() -> None:
    op.drop_table("documents")
```

- [ ] **Step 5: Создать `documents.py`**

Создать `libs/db/src/db/documents.py`:

```python
"""Файлы бота (FEATURES.md 4.8/4.9). Загрузка — Волна 3 (CRUD, 6.7),
здесь только чтение: список для system prompt и точный поиск для тулзы.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Document


async def list_documents(session: AsyncSession, bot_id: uuid.UUID) -> list[Document]:
    stmt = select(Document).where(Document.bot_id == bot_id).order_by(Document.filename)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_document_by_filename(
    session: AsyncSession, bot_id: uuid.UUID, filename: str
) -> Document | None:
    """Точное совпадение с учётом регистра — имена файлов, в отличие от
    разговорных названий товаров (4.1/4.2), не нормализуются: LLM видит
    точное имя в documents_context и должна передать его как есть."""
    stmt = select(Document).where(Document.bot_id == bot_id, Document.filename == filename)
    result = await session.execute(stmt)
    return result.scalars().first()
```

- [ ] **Step 6: Прогнать — GREEN**

Run: `cd libs/db && ../../.venv/Scripts/python.exe -m pytest tests/test_documents.py -v`
Expected: PASS (7 тестов).

- [ ] **Step 7: Обновить `test_migration.py`**

В `libs/db/tests/test_migration.py`, заменить:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products", "product_embeddings",
            "product_images",
        } <= tables
```

на:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products", "product_embeddings",
            "product_images", "documents",
        } <= tables
```

- [ ] **Step 8: Прогнать полный пакет `libs/db`**

Run: `cd libs/db && ../../.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (все тесты пакета).

- [ ] **Step 9: Commit**

```bash
git add libs/db/src/db/models.py libs/db/src/db/documents.py libs/db/migrations/versions/202609080001_documents.py libs/db/tests/test_documents.py libs/db/tests/test_migration.py
git commit -m "feat(db): add documents table and list/find queries"
```

---

## Task 3: `libs/llm` — `documents_context.py`

**Files:**
- Create: `libs/llm/src/llm/documents_context.py`
- Create: `libs/llm/tests/test_documents_context.py`

**Interfaces:**
- Produces: `documents_context(documents: Sequence[DocumentInfo]) -> str`, `DocumentInfo(filename: str)` — используются Task 6 (`consumer.py::_reply()`).

- [ ] **Step 1: Написать падающий тест**

Создать `libs/llm/tests/test_documents_context.py`:

```python
"""documents_context — список файлов бота для system prompt (FEATURES.md
4.8/4.9), платформенное дополнение сверх V1 (симметрично catalog_context,
FEATURES.md 3.4)."""

from __future__ import annotations

from llm.documents_context import DocumentInfo, documents_context


def test_empty_documents_list_returns_empty_message() -> None:
    assert documents_context([]) == "Файлов пока нет."


def test_lists_filenames_with_header() -> None:
    result = documents_context(
        [DocumentInfo(filename="price-list.pdf"), DocumentInfo(filename="dogovor.docx")]
    )
    assert "ДОСТУПНЫЕ ФАЙЛЫ" in result
    assert "- price-list.pdf" in result
    assert "- dogovor.docx" in result
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd libs/llm && ../../.venv/Scripts/python.exe -m pytest tests/test_documents_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.documents_context'`.

- [ ] **Step 3: Реализовать**

Создать `libs/llm/src/llm/documents_context.py`:

```python
"""Список файлов бота, подмешиваемый в system prompt (FEATURES.md
4.8/4.9) — платформенное дополнение сверх V1 (там список файлов знал
только владелец бота, зашивая имена в промпт вручную; здесь LLM видит
актуальный список программно, тем же принципом, что каталог товаров 3.4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_DOCUMENTS_HEADER = "ДОСТУПНЫЕ ФАЙЛЫ (используй send_document с ТОЧНЫМ именем):"
_EMPTY_DOCUMENTS_MESSAGE = "Файлов пока нет."


@dataclass(frozen=True)
class DocumentInfo:
    filename: str


def documents_context(documents: Sequence[DocumentInfo]) -> str:
    if not documents:
        return _EMPTY_DOCUMENTS_MESSAGE
    lines = [f"- {d.filename}" for d in documents]
    return _DOCUMENTS_HEADER + "\n" + "\n".join(lines)
```

- [ ] **Step 4: Прогнать — GREEN**

Run: `cd libs/llm && ../../.venv/Scripts/python.exe -m pytest tests/test_documents_context.py -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Прогнать полный пакет `libs/llm`**

Run: `cd libs/llm && ../../.venv/Scripts/python.exe -m pytest -v`
Expected: PASS (регрессии нет).

- [ ] **Step 6: Commit**

```bash
git add libs/llm/src/llm/documents_context.py libs/llm/tests/test_documents_context.py
git commit -m "feat(llm): documents context for system prompt (FEATURES.md 4.8/4.9)"
```

---

## Task 4: `services/gateway` — `sendDocument`/`sendVideo` + `OutboundConsumer`

**Files:**
- Modify: `services/gateway/src/session/manager.ts`
- Modify: `services/gateway/src/session/manager.test.ts`
- Modify: `services/gateway/src/outbound/consumer.ts`
- Modify: `services/gateway/src/outbound/consumer.test.ts`

**Interfaces:**
- Consumes: `OutboundDocument`/`OutboundVideo` zod-типы (Task 1).
- Produces: `SessionManager.sendDocument(botId, chatId, document, mimeType, filename, clientMsgId)`, `SessionManager.sendVideo(botId, chatId, video, mimeType, clientMsgId)`.

- [ ] **Step 1: Написать падающие тесты `sendDocument`/`sendVideo`**

В `services/gateway/src/session/manager.test.ts`, внутри
`describe("SessionManager.sendText / sendTyping", ...)`, после теста
`"sendImage passes clientMsgId..."`, добавить:

```typescript
  it("sendDocument passes clientMsgId as Baileys messageId with document+mimetype+fileName", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    const document = Buffer.from("fake-pdf-bytes");
    await sessions.sendDocument(
      "bot-1", "996700000000@s.whatsapp.net", document, "application/pdf", "price-list.pdf", "doc-msg-1",
    );

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { document, mimetype: "application/pdf", fileName: "price-list.pdf" },
      { messageId: "doc-msg-1" },
    );
  });

  it("sendVideo passes clientMsgId as Baileys messageId with video+mimetype", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    const video = Buffer.from("fake-mp4-bytes");
    await sessions.sendVideo("bot-1", "996700000000@s.whatsapp.net", video, "video/mp4", "video-msg-1");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { video, mimetype: "video/mp4" },
      { messageId: "video-msg-1" },
    );
  });
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd services/gateway && npx vitest run src/session/manager.test.ts`
Expected: FAIL — `sessions.sendDocument is not a function`.

- [ ] **Step 3: Реализовать методы**

В `services/gateway/src/session/manager.ts` добавить сразу после
`sendImage` (перед `async stopAll()`):

```typescript
  /** Аналогично sendImage — messageId=clientMsgId, плюс fileName: Baileys
   * (и сам WhatsApp) требует его, иначе клиент не увидит имя файла. */
  async sendDocument(
    botId: string,
    chatId: string,
    document: Buffer,
    mimeType: string,
    filename: string,
    clientMsgId: string,
  ): Promise<void> {
    await this.activeSocket(botId).sendMessage(
      chatId,
      { document, mimetype: mimeType, fileName: filename },
      { messageId: clientMsgId },
    );
  }

  /** Аналогично sendImage — нативное video-сообщение (плеер в чате),
   * fileName не нужен. */
  async sendVideo(
    botId: string,
    chatId: string,
    video: Buffer,
    mimeType: string,
    clientMsgId: string,
  ): Promise<void> {
    await this.activeSocket(botId).sendMessage(
      chatId,
      { video, mimetype: mimeType },
      { messageId: clientMsgId },
    );
  }
```

- [ ] **Step 4: Прогнать — GREEN**

Run: `cd services/gateway && npx vitest run src/session/manager.test.ts`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Заменить `consumer.test.ts` — добавить тесты `outbound.document`/`outbound.video`**

Заменить содержимое `services/gateway/src/outbound/consumer.test.ts`
целиком:

```typescript
import { describe, expect, it, vi } from "vitest";
import type { Redis } from "ioredis";
import { OutboundConsumer } from "./consumer.js";
import type { SessionManager } from "../session/manager.js";
import type { TransportLogger } from "../logger.js";
import type { Storage } from "../storage/types.js";

const BOT_ID = "00000000-0000-0000-0000-000000000001";

function makeMocks() {
  const dedupeStore = new Set<string>();
  const redis = {
    set: vi.fn(async (...args: unknown[]) => {
      const key = args[0] as string;
      if (dedupeStore.has(key)) return null;
      dedupeStore.add(key);
      return "OK";
    }),
    xack: vi.fn(async () => 1),
  } as unknown as Redis;

  const sessions = {
    sendText: vi.fn(async () => undefined),
    sendTyping: vi.fn(async () => undefined),
    sendImage: vi.fn(async () => undefined),
    sendDocument: vi.fn(async () => undefined),
    sendVideo: vi.fn(async () => undefined),
  } as unknown as SessionManager;

  const logger = {
    level: "info",
    child: () => logger,
    trace: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  } as TransportLogger;

  const storage = {
    get: vi.fn(async () => Buffer.from("fake-image-bytes")),
  } as unknown as Storage;

  return { redis, sessions, logger, storage };
}

function payloadFields(payload: unknown): string[] {
  return ["payload", JSON.stringify(payload)];
}

describe("OutboundConsumer idempotency and routing", () => {
  it("sends outbound.text once and reserves the dedupe key", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "Здравствуйте",
      client_msg_id: "msg-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendText).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      "Здравствуйте",
      "msg-1",
    );
    expect(redis.set).toHaveBeenCalledWith("wa:sent:msg-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("skips send on a retried (duplicate) client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "дубль от ретрая",
      client_msg_id: "msg-dup",
    };
    const entry = (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry;

    await entry.call(consumer, "1-0", payloadFields(event));
    await entry.call(consumer, "2-0", payloadFields(event));

    expect(sessions.sendText).toHaveBeenCalledTimes(1);
    expect(redis.xack).toHaveBeenCalledTimes(2); // оба entry подтверждены
  });

  it("routes outbound.typing to sendTyping", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.typing",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      client_msg_id: "typing-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(sessions.sendTyping).toHaveBeenCalledWith(BOT_ID, "996700000000@s.whatsapp.net");
    expect(sessions.sendText).not.toHaveBeenCalled();
  });

  it("acks a malformed payload instead of throwing", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);

    await expect(
      (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }).processEntry(
        "1-0",
        ["payload", "{not valid json"],
      ),
    ).resolves.toBeUndefined();

    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    expect(sessions.sendText).not.toHaveBeenCalled();
  });

  it("acks even when the send itself fails", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    (sessions.sendText as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("send failed"));
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.text",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      text: "не доставится",
      client_msg_id: "msg-fail",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("reads bytes from storage and sends outbound.image via sendImage", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.image",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/products/img-1.jpg",
      mime_type: "image/jpeg",
      client_msg_id: "img-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(storage.get).toHaveBeenCalledWith("bots/bot-1/products/img-1.jpg");
    expect(sessions.sendImage).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      Buffer.from("fake-image-bytes"),
      "image/jpeg",
      "img-1",
    );
    expect(redis.set).toHaveBeenCalledWith("wa:sent:img-1", "1", "EX", 3600, "NX");
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("bounds a hanging storage.get with the send timeout instead of hanging forever", async () => {
    vi.useFakeTimers();
    try {
      const { redis, sessions, logger, storage } = makeMocks();
      // storage.get никогда не резолвится — имитация зависшего S3/диска
      (storage.get as ReturnType<typeof vi.fn>).mockReturnValueOnce(new Promise(() => {}));
      const consumer = new OutboundConsumer(redis, sessions, logger, storage);
      const event = {
        type: "outbound.image",
        bot_id: BOT_ID,
        chat_id: "996700000000@s.whatsapp.net",
        storage_key: "bots/bot-1/products/img-hang.jpg",
        mime_type: "image/jpeg",
        client_msg_id: "img-hang",
      };

      const entryPromise = (
        consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> }
      ).processEntry("1-0", payloadFields(event));

      // Продвигаем таймеры на SEND_TIMEOUT_MS (20с) без реального ожидания —
      // withTimeout должен отклонить raceующий storage.get, не дожидаясь sendImage.
      await vi.advanceTimersByTimeAsync(20_000);
      await entryPromise;

      expect(sessions.sendImage).not.toHaveBeenCalled();
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          err: expect.objectContaining({ message: "storageGet timed out after 20000ms" }),
        }),
        "failed to send outbound event",
      );
      // ACK всё равно происходит — зависший storage не должен вешать очередь остальным ботам
      expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
    } finally {
      vi.useRealTimers();
    }
  });

  it("skips a duplicate outbound.image client_msg_id but still ACKs", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.image",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/products/img-1.jpg",
      mime_type: "image/jpeg",
      client_msg_id: "img-dup",
    };
    const entry = (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry;

    await entry.call(consumer, "1-0", payloadFields(event));
    await entry.call(consumer, "2-0", payloadFields(event));

    expect(sessions.sendImage).toHaveBeenCalledTimes(1);
  });

  it("reads bytes from storage and sends outbound.document via sendDocument with filename", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.document",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/documents/price-list.pdf",
      mime_type: "application/pdf",
      filename: "price-list.pdf",
      client_msg_id: "doc-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(storage.get).toHaveBeenCalledWith("bots/bot-1/documents/price-list.pdf");
    expect(sessions.sendDocument).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      Buffer.from("fake-image-bytes"),
      "application/pdf",
      "price-list.pdf",
      "doc-1",
    );
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });

  it("reads bytes from storage and sends outbound.video via sendVideo", async () => {
    const { redis, sessions, logger, storage } = makeMocks();
    const consumer = new OutboundConsumer(redis, sessions, logger, storage);
    const event = {
      type: "outbound.video",
      bot_id: BOT_ID,
      chat_id: "996700000000@s.whatsapp.net",
      storage_key: "bots/bot-1/documents/tour.mp4",
      mime_type: "video/mp4",
      client_msg_id: "video-1",
    };

    await (consumer as unknown as { processEntry: (id: string, f: string[]) => Promise<void> })
      .processEntry("1-0", payloadFields(event));

    expect(storage.get).toHaveBeenCalledWith("bots/bot-1/documents/tour.mp4");
    expect(sessions.sendVideo).toHaveBeenCalledWith(
      BOT_ID,
      "996700000000@s.whatsapp.net",
      Buffer.from("fake-image-bytes"),
      "video/mp4",
      "video-1",
    );
    expect(redis.xack).toHaveBeenCalledWith("wa:out", "gateway", "1-0");
  });
});
```

- [ ] **Step 6: Прогнать — RED**

Run: `cd services/gateway && npx vitest run src/outbound/consumer.test.ts`
Expected: FAIL — новые типы не обрабатываются `handleOutbound`.

- [ ] **Step 7: Реализовать в `consumer.ts`**

Заменить содержимое `services/gateway/src/outbound/consumer.ts` целиком:

```typescript
// Consumer group на wa:out: outbound.text / outbound.typing / outbound.image /
// outbound.document / outbound.video -> отправка через Baileys. Идемпотентность
// по client_msg_id (SET NX EX 3600) ДО отправки — ретрай worker'а не должен
// породить дубль сообщения клиенту (CLAUDE.md, "Исходящие идемпотентны").
// Ошибка отправки — лог + ACK, без ретраев (ретраи с backoff — Волна 1, вне
// скоупа Блока 1).
import type { Redis } from "ioredis";

import { Event } from "../contracts/events.js";
import type { SessionManager } from "../session/manager.js";
import type { TransportLogger } from "../logger.js";
import type { Storage } from "../storage/types.js";
import { withTimeout } from "../utils/timeout.js";

const OUT_STREAM = "wa:out";
const GROUP = "gateway";
const IDEMPOTENCY_TTL_SECONDS = 3600;
const BLOCK_MS = 5000;
const BATCH_SIZE = 10;
const SEND_TIMEOUT_MS = 20_000;

type StreamEntry = [id: string, fields: string[]];
type XReadGroupReply = [stream: string, entries: StreamEntry[]][] | null;

function fieldsToPayload(fields: string[]): string | undefined {
  const idx = fields.indexOf("payload");
  return idx >= 0 ? fields[idx + 1] : undefined;
}

export class OutboundConsumer {
  private running = false;
  private loopPromise: Promise<void> | null = null;
  private readonly consumerName = `gateway-${process.pid}`;

  constructor(
    private readonly redis: Redis,
    private readonly sessions: SessionManager,
    private readonly logger: TransportLogger,
    private readonly storage: Storage,
  ) {}

  async start(): Promise<void> {
    await this.ensureGroup();
    this.running = true;
    this.loopPromise = this.loop();
  }

  async stop(): Promise<void> {
    this.running = false;
    await this.loopPromise;
  }

  private async ensureGroup(): Promise<void> {
    try {
      await this.redis.xgroup("CREATE", OUT_STREAM, GROUP, "$", "MKSTREAM");
    } catch (err) {
      if (!(err instanceof Error) || !err.message.includes("BUSYGROUP")) throw err;
      // группа уже существует — нормальный случай при рестарте
    }
  }

  private async loop(): Promise<void> {
    while (this.running) {
      let reply: XReadGroupReply;
      try {
        reply = (await this.redis.xreadgroup(
          "GROUP",
          GROUP,
          this.consumerName,
          "COUNT",
          BATCH_SIZE,
          "BLOCK",
          BLOCK_MS,
          "STREAMS",
          OUT_STREAM,
          ">",
        )) as XReadGroupReply;
      } catch (err) {
        this.logger.error({ err }, "xreadgroup failed on wa:out, retrying");
        continue;
      }
      if (!reply) continue; // BLOCK timeout, ничего не пришло

      for (const [, entries] of reply) {
        for (const [id, fields] of entries) {
          await this.processEntry(id, fields);
        }
      }
    }
  }

  private async processEntry(id: string, fields: string[]): Promise<void> {
    const raw = fieldsToPayload(fields);
    try {
      if (!raw) throw new Error("entry has no 'payload' field");
      const event = Event.parse(JSON.parse(raw));
      if (
        event.type === "outbound.text" ||
        event.type === "outbound.typing" ||
        event.type === "outbound.image" ||
        event.type === "outbound.document" ||
        event.type === "outbound.video"
      ) {
        // Цепочка === (не .includes() на массиве типов) — TS естественно
        // сужает event до нужного Extract-объединения по литералам, без
        // явного as-каста, который потребовался бы при проверке через
        // includes() на readonly-массиве строк.
        await this.handleOutbound(event);
      } else {
        this.logger.warn({ id, type: event.type }, "unexpected event type on wa:out, skipping");
      }
    } catch (err) {
      this.logger.error({ err, id, raw }, "failed to process wa:out entry, acking anyway");
    } finally {
      await this.redis.xack(OUT_STREAM, GROUP, id);
    }
  }

  private async handleOutbound(
    event: Extract<
      Event,
      { type: "outbound.text" | "outbound.typing" | "outbound.image" | "outbound.document" | "outbound.video" }
    >,
  ): Promise<void> {
    // Формат ключа задокументирован и переиспользуется в libs/core/src/core/redis_keys.py
    // (worker, api) — Блок 3 detect'ит по нему свой echo для handoff. Меняешь тут — меняй и там.
    const dedupeKey = `wa:sent:${event.client_msg_id}`;
    const reserved = await this.redis.set(dedupeKey, "1", "EX", IDEMPOTENCY_TTL_SECONDS, "NX");
    if (reserved !== "OK") {
      this.logger.info({ clientMsgId: event.client_msg_id }, "duplicate client_msg_id, skipping send");
      return;
    }

    try {
      if (event.type === "outbound.text") {
        await withTimeout(
          this.sessions.sendText(event.bot_id, event.chat_id, event.text, event.client_msg_id),
          SEND_TIMEOUT_MS,
          "sendText",
        );
      } else if (event.type === "outbound.typing") {
        await withTimeout(
          this.sessions.sendTyping(event.bot_id, event.chat_id),
          SEND_TIMEOUT_MS,
          "sendTyping",
        );
      } else if (event.type === "outbound.image") {
        const image = await withTimeout(
          this.storage.get(event.storage_key),
          SEND_TIMEOUT_MS,
          "storageGet",
        );
        await withTimeout(
          this.sessions.sendImage(event.bot_id, event.chat_id, image, event.mime_type, event.client_msg_id),
          SEND_TIMEOUT_MS,
          "sendImage",
        );
      } else if (event.type === "outbound.document") {
        const document = await withTimeout(
          this.storage.get(event.storage_key),
          SEND_TIMEOUT_MS,
          "storageGet",
        );
        await withTimeout(
          this.sessions.sendDocument(
            event.bot_id, event.chat_id, document, event.mime_type, event.filename, event.client_msg_id,
          ),
          SEND_TIMEOUT_MS,
          "sendDocument",
        );
      } else {
        const video = await withTimeout(
          this.storage.get(event.storage_key),
          SEND_TIMEOUT_MS,
          "storageGet",
        );
        await withTimeout(
          this.sessions.sendVideo(event.bot_id, event.chat_id, video, event.mime_type, event.client_msg_id),
          SEND_TIMEOUT_MS,
          "sendVideo",
        );
      }
    } catch (err) {
      this.logger.error(
        { err, botId: event.bot_id, chatId: event.chat_id, clientMsgId: event.client_msg_id },
        "failed to send outbound event",
      );
    }
  }
}
```

- [ ] **Step 8: Прогнать — GREEN**

Run: `cd services/gateway && npx vitest run src/outbound/consumer.test.ts src/session/manager.test.ts`
Expected: PASS (9 тестов consumer + 8 тестов session manager).

- [ ] **Step 9: Прогнать полный пакет gateway + типы**

Run: `cd services/gateway && npx vitest run`
Run: `cd services/gateway && npx tsc --noEmit`
Expected: всё зелёное/чисто.

- [ ] **Step 10: Commit**

```bash
git add services/gateway/src/session/manager.ts services/gateway/src/session/manager.test.ts services/gateway/src/outbound/consumer.ts services/gateway/src/outbound/consumer.test.ts
git commit -m "feat(gateway): send outbound.document and outbound.video"
```

---

## Task 5: `libs/tools` — `MediaToSend.filename` + `SendDocumentTool`

**Files:**
- Modify: `libs/tools/src/tools/base.py`
- Create: `libs/tools/src/tools/send_document.py`
- Modify: `libs/tools/src/tools/registry.py`
- Create: `libs/tools/tests/test_send_document.py`
- Modify: `libs/tools/tests/test_registry.py`

**Interfaces:**
- Consumes: `find_document_by_filename` (Task 2, `db.documents`).
- Produces: `MediaToSend.filename: str | None = None` (новое необязательное поле); `SendDocumentTool` — зарегистрирована под `send_document`. Используется Task 6 (`_send_cards()` читает `item.filename`).

- [ ] **Step 1: Написать падающий тест реестра**

В `libs/tools/tests/test_registry.py` добавить в конец файла:

```python


def test_all_tool_names_includes_send_document() -> None:
    """Третья настоящая тулза (FEATURES.md 4.8/4.9)."""
    assert "send_document" in registry.all_tool_names()
```

- [ ] **Step 2: Написать падающие тесты тулзы**

Создать `libs/tools/tests/test_send_document.py`:

```python
"""SendDocumentTool (FEATURES.md 4.8/4.9): точное совпадение имени файла,
override-паттерн (эталон V1 — isFileSent подавляет ответ LLM целиком, как
у карточки товара), video/* -> media без явной обработки (диспетчеризация
по mime_type — забота consumer.py::_send_cards, не тулзы). Требует Docker
(testcontainers) — реальный Postgres.
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
from db.models import Bot, Document
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools.base import ToolContext
from tools.send_document import SendDocumentTool

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


def _make_ctx(bot: Bot, session_factory: async_sessionmaker[AsyncSession]) -> ToolContext:
    return ToolContext(
        bot=bot,
        contact_id=uuid.uuid4(),
        session_factory=session_factory,
        redis=None,  # type: ignore[arg-type]  # эта тулза не использует redis
        storage=None,  # type: ignore[arg-type]  # эта тулза не использует storage
        config={},
    )


async def test_found_document_returns_override_and_media_with_filename(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot.id, filename="price-list.pdf",
                storage_key="bots/x/documents/price-list.pdf", mime_type="application/pdf",
            )
        )
        await session.commit()

    result = await SendDocumentTool().execute(
        {"file_name": "price-list.pdf"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "Файл price-list.pdf отправлен."
    assert len(result.media) == 1
    assert result.media[0].storage_key == "bots/x/documents/price-list.pdf"
    assert result.media[0].mime_type == "application/pdf"
    assert result.media[0].filename == "price-list.pdf"
    assert result.content == "Файл price-list.pdf успешно отправлен."


async def test_found_video_returns_override_and_media(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot.id, filename="tour.mp4",
                storage_key="bots/x/documents/tour.mp4", mime_type="video/mp4",
            )
        )
        await session.commit()

    result = await SendDocumentTool().execute(
        {"file_name": "tour.mp4"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "Файл tour.mp4 отправлен."
    assert result.media[0].mime_type == "video/mp4"
    assert result.media[0].filename == "tour.mp4"


async def test_document_not_found_returns_error_without_override(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)

    result = await SendDocumentTool().execute(
        {"file_name": "нет-такого.pdf"}, _make_ctx(bot, session_factory)
    )

    assert result.content == 'Файл "нет-такого.pdf" не найден.'
    assert result.override_reply_text is None
    assert result.media == ()


async def test_empty_file_name_returns_error_without_querying_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)

    result = await SendDocumentTool().execute(
        {"file_name": "  "}, _make_ctx(bot, session_factory)
    )

    assert result.content == "Не указано имя файла."
    assert result.override_reply_text is None
    assert result.media == ()


async def test_document_lookup_is_scoped_per_bot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_a = await _make_bot(session_factory)
    bot_b = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot_a, filename="only-a.pdf",
                storage_key="k", mime_type="application/pdf",
            )
        )
        await session.commit()

    result = await SendDocumentTool().execute(
        {"file_name": "only-a.pdf"}, _make_ctx(bot_b, session_factory)
    )

    assert result.override_reply_text is None
```

- [ ] **Step 3: Прогнать — RED**

Run: `cd libs/tools && ../../.venv/Scripts/python.exe -m pytest tests/test_send_document.py tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.send_document'`.

- [ ] **Step 4: Добавить поле `filename` в `MediaToSend`**

В `libs/tools/src/tools/base.py` заменить:

```python
@dataclass(frozen=True)
class MediaToSend:
    storage_key: str
    mime_type: str
```

на:

```python
@dataclass(frozen=True)
class MediaToSend:
    storage_key: str
    mime_type: str
    filename: str | None = None  # только для outbound.document (Baileys требует fileName)
```

(Дефолт `None` — существующая `ProductSearchTool` продолжает работать
без изменений: она никогда не передаёт `filename`, а `_send_cards`
диспетчеризует её медиа по `mime_type` в ветку `outbound.image`, где
`filename` не используется.)

- [ ] **Step 5: Реализовать тулзу**

Создать `libs/tools/src/tools/send_document.py`:

```python
"""Отправка файла или видео клиенту (FEATURES.md 4.8/4.9) — эталон V1
(sendDocument), но файл ищется в БД по имени, не на диске (платформа
мультитенантная, файлы — в Storage). Одна тулза на оба случая — LLM не
думает заранее, файл это или видео, тулза сама смотрит mime_type; какое
outbound-событие публиковать (outbound.video/outbound.document) решает
consumer.py::_send_cards по mime_type каждого MediaToSend, не эта тулза.
"""

from __future__ import annotations

from typing import Any, ClassVar

from db.documents import find_document_by_filename

from .base import MediaToSend, ToolContext, ToolExecutionResult

_NOT_FOUND_ERROR = 'Файл "{filename}" не найден.'


class SendDocumentTool:
    name = "send_document"
    description = "Отправляет клиенту файл или видео по точному имени из списка доступных файлов."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "file_name": {
                "type": "string",
                "description": "Точное имя файла из списка доступных файлов",
            }
        },
        "required": ["file_name"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        filename = str(arguments.get("file_name", ""))
        if not filename.strip():
            return ToolExecutionResult(content="Не указано имя файла.")

        async with ctx.session_factory() as session:
            document = await find_document_by_filename(session, ctx.bot.id, filename)

        if document is None:
            return ToolExecutionResult(content=_NOT_FOUND_ERROR.format(filename=filename))

        media = MediaToSend(
            storage_key=document.storage_key,
            mime_type=document.mime_type,
            filename=document.filename,
        )
        return ToolExecutionResult(
            content=f"Файл {filename} успешно отправлен.",
            override_reply_text=f"Файл {filename} отправлен.",
            media=(media,),
        )
```

- [ ] **Step 6: Зарегистрировать тулзу**

В `libs/tools/src/tools/registry.py` заменить:

```python
from .base import Tool
from .product_search import ProductSearchTool
from .telegram_lead import TelegramLeadTool

_REGISTRY: dict[str, Tool] = {}
```

на:

```python
from .base import Tool
from .product_search import ProductSearchTool
from .send_document import SendDocumentTool
from .telegram_lead import TelegramLeadTool

_REGISTRY: dict[str, Tool] = {}
```

И заменить:

```python
register(ProductSearchTool())
register(TelegramLeadTool())
```

на:

```python
register(ProductSearchTool())
register(TelegramLeadTool())
register(SendDocumentTool())
```

- [ ] **Step 7: Прогнать — GREEN**

Run: `cd libs/tools && ../../.venv/Scripts/python.exe -m pytest tests/test_send_document.py tests/test_registry.py -v`
Expected: PASS (5 тестов тулзы + 7 тестов реестра).

- [ ] **Step 8: Прогнать mypy strict и ruff, полный пакет `libs/tools`**

Run (из корня репозитория): `.venv/Scripts/python.exe -m mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src libs/tools/src services/worker/src services/celery/src`
Expected: без новых ошибок (только преdexisting `libs/core/src/core/bus.py:23`).
Run: `.venv/Scripts/python.exe -m ruff check .`
Expected: чисто.
Run: `cd libs/tools && ../../.venv/Scripts/python.exe -m pytest -v`
Expected: PASS, весь пакет.

- [ ] **Step 9: Commit**

```bash
git add libs/tools/src/tools/base.py libs/tools/src/tools/send_document.py libs/tools/src/tools/registry.py libs/tools/tests/test_send_document.py libs/tools/tests/test_registry.py
git commit -m "feat(tools): send_document tool for files and video (FEATURES.md 4.8/4.9)"
```

---

## Task 6: `services/worker` — контекст файлов + диспетчеризация по `mime_type`

**Files:**
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Modify: `services/worker/tests/pipeline/test_reply_tools.py`
- Create: `services/worker/tests/pipeline/test_documents_context.py`

**Interfaces:**
- Consumes: `list_documents` (Task 2), `documents_context`/`DocumentInfo` (Task 3), `OutboundDocument`/`OutboundVideo` (Task 1), `MediaToSend.filename` (Task 5).

- [ ] **Step 1: Написать падающий тест — документы в system prompt**

Создать `services/worker/tests/pipeline/test_documents_context.py`
(зеркально `test_catalog.py`):

```python
"""Список файлов в system prompt (FEATURES.md 4.8/4.9) — реальный
сценарий через _process_entry, как test_catalog.py: мок только на
границе LLM (consumer_module.complete), всё остальное — реальный
Postgres/fakeredis.
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
from db.models import Bot, Document
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
        "wa_msg_id": "livecheck-docs-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Пришлите прайс",
        "ts": 1756800000000,
    }


async def test_documents_appear_in_system_prompt_sent_to_llm(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot_id, filename="price-list.pdf", storage_key="k", mime_type="application/pdf"
            )
        )
        await session.commit()

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="Сейчас пришлю.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert len(captured_system_prompts) == 1
        assert "ДОСТУПНЫЕ ФАЙЛЫ" in captured_system_prompts[0]
        assert "- price-list.pdf" in captured_system_prompts[0]
    finally:
        await redis.aclose()


async def test_empty_documents_sends_the_empty_documents_message(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_id = await _make_bot(session_factory)  # ни одного файла

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert "Файлов пока нет." in captured_system_prompts[0]
    finally:
        await redis.aclose()
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_documents_context.py -v`
Expected: FAIL — `documents_context`/`list_documents` ещё не подключены
в `_reply()`, в system_prompt их нет.

- [ ] **Step 3: Подключить документы в `_reply()`**

В `services/worker/src/worker/pipeline/consumer.py`:

1. Добавить в блок импортов (после `from db.products import list_products`):

```python
from db.documents import list_documents
```

2. Заменить строку:

```python
from llm.catalog_context import ProductInfo, catalog_context
```

на:

```python
from llm.catalog_context import ProductInfo, catalog_context
from llm.documents_context import DocumentInfo, documents_context
```

3. В `_reply()` заменить:

```python
    async with session_factory() as session:
        history_rows = await fetch_recent_history(session, contact_id)
        bindings = await list_enabled_tool_bindings(session, bot.id)
        products = await list_products(session, bot.id, limit=PRODUCT_CATALOG_LIMIT)

    history = [HistoryMessage(role=m.role, content=m.content) for m in history_rows]
    catalog = catalog_context(
        [
            ProductInfo(
                name=p.name,
                price=str(p.price) if p.price is not None else None,
                description=p.description,
            )
            for p in products
        ]
    )
    # Порядок — как в V1 (agentInstructions + catalogContext + timeContext):
    # только основной текстовый путь, vision/PDF (image_prompt/pdf_prompt)
    # каталог не получают — эталон V1 (analyzeImage/analyzePdf) тоже.
    system_prompt = f"{bot.system_prompt}\n\n{catalog}\n\n{time_context(bot.timezone)}"
```

на:

```python
    async with session_factory() as session:
        history_rows = await fetch_recent_history(session, contact_id)
        bindings = await list_enabled_tool_bindings(session, bot.id)
        products = await list_products(session, bot.id, limit=PRODUCT_CATALOG_LIMIT)
        documents = await list_documents(session, bot.id)

    history = [HistoryMessage(role=m.role, content=m.content) for m in history_rows]
    catalog = catalog_context(
        [
            ProductInfo(
                name=p.name,
                price=str(p.price) if p.price is not None else None,
                description=p.description,
            )
            for p in products
        ]
    )
    docs_ctx = documents_context([DocumentInfo(filename=d.filename) for d in documents])
    # Порядок — как в V1 (agentInstructions + catalogContext + timeContext):
    # только основной текстовый путь, vision/PDF (image_prompt/pdf_prompt)
    # каталог/файлы не получают — эталон V1 (analyzeImage/analyzePdf) тоже.
    system_prompt = f"{bot.system_prompt}\n\n{catalog}\n\n{docs_ctx}\n\n{time_context(bot.timezone)}"
```

- [ ] **Step 4: Прогнать — GREEN**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_documents_context.py tests/pipeline/test_catalog.py -v`
Expected: PASS (2 новых теста + 3 существующих каталога — регрессии нет).

- [ ] **Step 5: Написать падающие тесты диспетчеризации по `mime_type` в `_send_cards`**

Добавить в конец `services/worker/tests/pipeline/test_reply_tools.py`:

```python


async def test_document_media_dispatches_to_outbound_document_with_filename(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.8: media с не-image/не-video mime_type уходит как
    outbound.document с filename (Baileys требует его для показа имени
    файла клиенту)."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeDocumentTool:
        name = "send_document"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content="Файл price-list.pdf успешно отправлен.",
                override_reply_text="Файл price-list.pdf отправлен.",
                media=[
                    MediaToSend(
                        storage_key="bots/x/documents/price-list.pdf",
                        mime_type="application/pdf",
                        filename="price-list.pdf",
                    )
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", _FakeDocumentTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="send_document", arguments_json="{}")],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, document, text
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.document"
        assert payloads[1]["storage_key"] == "bots/x/documents/price-list.pdf"
        assert payloads[1]["filename"] == "price-list.pdf"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "Файл price-list.pdf отправлен."
    finally:
        await redis.aclose()


async def test_video_media_dispatches_to_outbound_video(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.9: media с video/* mime_type уходит как outbound.video
    (нативный плеер), не outbound.document."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeVideoTool:
        name = "send_document"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content="Файл tour.mp4 успешно отправлен.",
                override_reply_text="Файл tour.mp4 отправлен.",
                media=[
                    MediaToSend(
                        storage_key="bots/x/documents/tour.mp4",
                        mime_type="video/mp4",
                        filename="tour.mp4",
                    )
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", _FakeVideoTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="send_document", arguments_json="{}")],
            )
        return LLMResult(text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[1]["type"] == "outbound.video"
        assert payloads[1]["storage_key"] == "bots/x/documents/tour.mp4"
        assert "filename" not in payloads[1]
    finally:
        await redis.aclose()
```

Эти тесты используют уже импортированные в файле `ClassVar`, `MediaToSend`,
`ToolContext`, `ToolExecutionResult`, `json`, `tools_registry`, `consumer_module`,
`LLMResult`, `ToolCall`, `FakeRedis`, `_make_bot`, `enable_tool_binding`,
`_inbound_payload`, `_NullStorage`, `_process_entry` (все уже есть в файле из
Task 6 предыдущего плана 4.3/4.4 — `from tools.base import MediaToSend,
ToolContext, ToolExecutionResult` уже стоит в блоке импортов) — новых
импортов для этого шага не требуется.

- [ ] **Step 6: Прогнать — RED**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_reply_tools.py -v`
Expected: FAIL — `_send_cards` шлёт всё как `outbound.image` независимо от `mime_type`.

- [ ] **Step 7: Реализовать диспетчеризацию в `_send_cards`**

В `services/worker/src/worker/pipeline/consumer.py`:

1. Заменить строку импорта:

```python
from core.events import Event, InboundText, OutboundImage, OutboundText, OutboundTyping
```

на:

```python
from core.events import (
    Event,
    InboundText,
    OutboundDocument,
    OutboundImage,
    OutboundText,
    OutboundTyping,
    OutboundVideo,
)
```

2. Заменить тело `_send_cards` (текущие строки 277-299, цикл по `reply.media`):

```python
    sent_media = False
    for reply in replies:
        for item in reply.media:
            if sent_media:
                await asyncio.sleep(
                    random.uniform(PHOTO_JITTER_MIN_SECONDS, PHOTO_JITTER_MAX_SECONDS)
                )
            image_event = OutboundImage(
                bot_id=event.bot_id,
                chat_id=event.chat_id,
                storage_key=item.storage_key,
                mime_type=item.mime_type,
                client_msg_id=uuid.uuid4().hex,
            )
            await publish(redis, OUT_STREAM, image_event.model_dump(mode="json"))
            sent_media = True
        text_event = OutboundText(
            bot_id=event.bot_id,
            chat_id=event.chat_id,
            text=reply.text,
            client_msg_id=uuid.uuid4().hex,
        )
        await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))
```

на:

```python
    sent_media = False
    for reply in replies:
        for item in reply.media:
            if sent_media:
                await asyncio.sleep(
                    random.uniform(PHOTO_JITTER_MIN_SECONDS, PHOTO_JITTER_MAX_SECONDS)
                )
            media_event: OutboundImage | OutboundVideo | OutboundDocument
            if item.mime_type.startswith("video/"):
                media_event = OutboundVideo(
                    bot_id=event.bot_id,
                    chat_id=event.chat_id,
                    storage_key=item.storage_key,
                    mime_type=item.mime_type,
                    client_msg_id=uuid.uuid4().hex,
                )
            elif item.mime_type.startswith("image/"):
                media_event = OutboundImage(
                    bot_id=event.bot_id,
                    chat_id=event.chat_id,
                    storage_key=item.storage_key,
                    mime_type=item.mime_type,
                    client_msg_id=uuid.uuid4().hex,
                )
            else:
                media_event = OutboundDocument(
                    bot_id=event.bot_id,
                    chat_id=event.chat_id,
                    storage_key=item.storage_key,
                    mime_type=item.mime_type,
                    filename=item.filename or "file",
                    client_msg_id=uuid.uuid4().hex,
                )
            await publish(redis, OUT_STREAM, media_event.model_dump(mode="json"))
            sent_media = True
        text_event = OutboundText(
            bot_id=event.bot_id,
            chat_id=event.chat_id,
            text=reply.text,
            client_msg_id=uuid.uuid4().hex,
        )
        await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))
```

Также обновить докстринг `_send_cards` (сейчас говорит только про
«карточки товара» — расширить формулировку):

```python
async def _send_cards(
    event: InboundText, redis: Redis, replies: Sequence[OverrideReply]
) -> None:
    """FEATURES.md 4.3/4.4/4.8/4.9: карточки товара и файлы/видео —
    typing один раз, затем для каждой карточки её медиа (диспетчеризация
    по mime_type: image/* -> outbound.image, video/* -> outbound.video,
    остальное -> outbound.document) и текст, по порядку. Джиттер
    1000-1500 мс перед КАЖДЫМ медиа, кроме самого первого в этом ходе
    (включая между карточками/файлами) — эталон V1, анти-бан дисциплина.
    client_msg_id — новый .hex на КАЖДОЕ исходящее событие, как и в
    _send_reply."""
```

- [ ] **Step 8: Прогнать — GREEN**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_reply_tools.py -v`
Expected: PASS (все тесты файла, включая 2 новых и регрессионные из
4.3/4.4/4.7).

- [ ] **Step 9: Полный прогон `services/worker`, mypy, ruff, весь репозиторий**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest -v`
Run (из корня репозитория): `.venv/Scripts/python.exe -m mypy libs/core/src libs/db/src libs/integrations/src libs/scheduling/src libs/tools/src services/worker/src services/celery/src`
Run: `.venv/Scripts/python.exe -m ruff check .`
Run (из корня репозитория): `.venv/Scripts/python.exe -m pytest -q`
Expected: всё зелёное/чисто, без регрессий.

- [ ] **Step 10: Commit**

```bash
git add services/worker/src/worker/pipeline/consumer.py services/worker/tests/pipeline/test_reply_tools.py services/worker/tests/pipeline/test_documents_context.py
git commit -m "feat(worker): send files/video via mime-type dispatch, documents in system prompt"
```

---

## Task 7: Живой прогон

**Files:** нет изменений кода — только проверка на реальном стенде.

- [ ] **Step 1: Проверить свободное место на диске**

Run: `df -h` (или `Get-PSDrive C` в PowerShell) — при менее ~3 ГБ
свободного сначала `docker builder prune -f`, не трогая volumes других
проектов (см. память проекта, находка про тесный диск на машине
разработки).

- [ ] **Step 2: Пересобрать образы, задействующие изменённые пакеты**

Run: `docker compose -f compose/docker-compose.dev.yml build gateway worker api`
Expected: успешная сборка — новых pip/npm-зависимостей эта итерация не
добавляет (только код), сборка быстрая за счёт кэша слоёв.

- [ ] **Step 3: Поднять стенд, накатить миграцию**

```bash
docker compose -f compose/docker-compose.dev.yml up -d
```

Run (Windows/Git Bash — `MSYS_NO_PATHCONV=1` обязателен для `-w`,
задокументированная ловушка):

```bash
MSYS_NO_PATHCONV=1 docker compose -f compose/docker-compose.dev.yml exec -w /app/libs/db worker python -m alembic upgrade head
```

Убедиться, что таблица `documents` появилась (`docker compose ... exec
postgres psql -U platform -d platform -c '\d documents'`).

- [ ] **Step 4: Зарегистрировать тулзу через API**

Создать тестового бота (как в прошлых живых прогонах), выполнить:
`POST /bots/{id}/tools {"tool_name": "send_document", "config": {}}` →
должен вернуть 201 (реестр знает тулзу).

- [ ] **Step 5: Проверить тулзу против реального Postgres**

Вставить тестовую строку в `documents` вручную через SQL (`storage_key`
указывает на реальный файл, положенный в shared media volume — тот же
приём, что уже применялся для `product_images`/inbound-медиа в прошлых
итерациях), вызвать `SendDocumentTool().execute()` напрямую внутри
контейнера `worker` (как это делалось для `ProductSearchTool`/
`TelegramLeadTool` в прошлых живых прогонах) — убедиться, что
`override_reply_text`/`media` формируются корректно для документа
(`mime_type` не video/image) и для видео (`mime_type` video/*)
раздельно.

Опубликовать вручную `outbound.document` и `outbound.video` события в
`wa:out` через redis-cli/скрипт (тот же приём, что для `outbound.image`
в прошлой итерации) — убедиться, что gateway корректно читает байты
через `Storage.get()` и пытается `sendDocument`/`sendVideo` (упадёт на
«no session running for bot» — ожидаемо, нет привязанного номера, тот
же разрыв, что и во всех прошлых итерациях).

- [ ] **Step 6: Очистить тестовые данные, остановить стенд**

Удалить тестового бота (каскадно уберёт `documents`/`tool_bindings`),
`docker compose down`.

- [ ] **Step 7: Обновить память проекта**

Создать памятку `wave2-document-video-progress.md` в
`C:\Users\user\.claude\projects\C--Work-Projects-whatsapp-bot\memory\`
— что сдано, найденные в архиве расхождения (в т.ч. `isFileSent`
подтверждение override-паттерна), закрытие Волны 2 целиком (это
последняя итерация волны — если так, обновить также
`docs/FEATURES.md`'s раздел "Скоуп и порядок работ" пометкой, что Волна
2 завершена, и `MEMORY.md`.

## Самопроверка плана (для исполнителя перед стартом)

- **Покрытие спеки**: контракт (Task 1) → БД (Task 2) → system-prompt
  контекст (Task 3) → gateway (Task 4) → тулза (Task 5) → диспетчеризация
  worker'а + подключение контекста (Task 6) → живой прогон (Task 7). Все
  разделы спеки `2026-09-08-document-video-sending-design.md` покрыты,
  включая «Границы этой итерации».
- **Плейсхолдеров нет**: каждый шаг содержит полный код.
- **Согласованность типов**: `MediaToSend(storage_key, mime_type, filename=None)`
  определена один раз в Task 5 и используется с теми же именами полей в
  Task 6 (`_send_cards`, `item.filename`). `OutboundDocument(bot_id, chat_id,
  storage_key, mime_type, filename, client_msg_id)` и
  `OutboundVideo(bot_id, chat_id, storage_key, mime_type, client_msg_id)`
  определены один раз в Task 1 и используются с теми же именами в Task 4
  (TS) и Task 6 (`_send_cards`). `list_documents`/`find_document_by_filename`
  определены один раз в Task 2, используются в Task 5 и Task 6 с теми же
  сигнатурами. `documents_context`/`DocumentInfo` определены один раз в
  Task 3, используются в Task 6 с теми же именами.
