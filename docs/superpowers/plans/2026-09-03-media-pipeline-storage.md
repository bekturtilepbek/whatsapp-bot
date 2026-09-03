# Медиа-пайплайн: лимит размера (1.9) + Storage-интерфейс (2.7) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gateway скачивает входящее медиа с лимитом размера (до сети), кладёт
байты в Storage-абстракцию (fs в dev, S3-совместимую в prod) и передаёт ссылку
worker'у через событие `wa:in`; worker сохраняет ссылку в истории. Ответ
клиенту остаётся существующим fallback-текстом — обработка содержимого
(vision/STT/PDF) не входит в этот план.

**Architecture:** Три независимых слоя, каждый тестируется отдельно: (1)
контракт событий получает три nullable-поля, (2) по одному Storage-интерфейсу
на язык (gateway пишет через TS-реализацию, worker будет читать через
Python-реализацию), (3) gateway проверяет `fileLength` против per-bot лимита
до вызова Baileys-скачивания, любой сбой на пути — событие без
`storage_key`, деградация к уже существующему media-fallback у worker.

**Tech Stack:** TypeScript/Baileys/`@aws-sdk/client-s3` (gateway), Python/
boto3/SQLAlchemy/Alembic (worker + libs), общий docker-volume в dev.

**Spec:** [docs/superpowers/specs/2026-09-03-media-pipeline-storage-design.md](../specs/2026-09-03-media-pipeline-storage-design.md)

## Global Constraints

- Любой внешний вызов — с таймаутом (CLAUDE.md): скачивание с CDN WhatsApp и
  загрузка в storage оба оборачиваются `withTimeout` (`services/gateway/src/utils/timeout.ts`).
- Лимиты — per-bot настройка в `bots.settings`, не константа в коде (CLAUDE.md).
  Ключ: `media_max_size_bytes`, дефолт `16 * 1024 * 1024`.
- Настройки бота мержатся, не перезаписываются — эта работа только читает
  `bots.settings`, ничего в него не пишет, конвенция не затрагивается.
- Любой сбой на пути скачивание→загрузка не блокирует приём сообщения:
  событие публикуется без `storage_key/mime_type/size_bytes`, worker
  откатывается на существующий `_reply_with_media_fallback` (FEATURES 2.6) —
  этот путь НЕ меняется в этом плане.
- Ключ объекта в storage: `bots/{bot_id}/media/{wa_msg_id}` (без расширения).
- `messages.media_ref` — один JSONB-столбец `{"storage_key", "mime_type", "size_bytes"}`,
  не три отдельные колонки.
- Dev storage-driver — `fs` на общем docker-volume (gateway + worker), без
  MinIO-контейнера (тесный диск разработчика). Prod — `s3` (DO Spaces).
- Conventional Commits; каждый коммит заканчивается `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

## Task 1: Контракт событий — storage_key/mime_type/size_bytes

**Files:**
- Modify: `docs/contracts/events.schema.json`
- Modify: `services/gateway/src/contracts/events.ts`
- Modify: `libs/core/src/core/events.py`
- Create: `docs/contracts/examples/inbound.text.media.json`
- Test: `libs/core/tests/test_events_contract.py` (существующий, параметризован по файлам в `examples/` — новый файл покрывается автоматически)
- Test: `services/gateway/src/contracts/events.test.ts` (существующий, аналогично)

**Interfaces:**
- Produces: `InboundText` (Python, `core.events`) и `InboundText` (TS, `contracts/events.ts`)
  получают опциональные поля `storage_key: str | None`, `mime_type: str | None`,
  `size_bytes: int | None` (Python) / `storage_key?: string | null`,
  `mime_type?: string | null`, `size_bytes?: number | null` (TS).

- [ ] **Step 1: Добавить поля в JSON Schema**

В `docs/contracts/events.schema.json`, в `definitions.inboundText.properties`,
сразу после `"media_type"`:

```json
        "media_type": { "type": ["string", "null"] },
        "storage_key": { "type": ["string", "null"] },
        "mime_type": { "type": ["string", "null"] },
        "size_bytes": { "type": ["integer", "null"] },
        "ts": { "type": "integer", "description": "unix ms" }
```

(замените существующий блок `"media_type"... "ts"...` на этот — `required` не трогаем)

- [ ] **Step 2: Добавить пример с заполненными медиа-полями**

Создать `docs/contracts/examples/inbound.text.media.json`:

```json
{
  "type": "inbound.text",
  "bot_id": "00000000-0000-0000-0000-000000000001",
  "wa_msg_id": "3EB0C767D26A1D7",
  "chat_id": "996700000000@s.whatsapp.net",
  "sender_wa_id": "996700000000",
  "sender_lid": null,
  "from_me": false,
  "text": "",
  "quoted_text": null,
  "media_type": "image",
  "storage_key": "bots/00000000-0000-0000-0000-000000000001/media/3EB0C767D26A1D7",
  "mime_type": "image/jpeg",
  "size_bytes": 245760,
  "ts": 1756800000000
}
```

- [ ] **Step 3: Прогнать существующие тесты контракта — ожидаем FAIL**

Run: `pytest libs/core/tests/test_events_contract.py -v` и
`cd services/gateway && npx vitest run src/contracts/events.test.ts`

Expected: FAIL — новый пример не проходит валидацию (Pydantic/zod ещё не
знают о новых полях; JSON Schema их уже содержит с Step 1, так что
`test_example_matches_json_schema`/"matches JSON Schema" пройдёт, а
`test_example_matches_pydantic_model`/"matches zod Event union" — упадёт).

- [ ] **Step 4: Обновить Pydantic-модель**

В `libs/core/src/core/events.py`, класс `InboundText`, после `media_type: str | None = None`:

```python
    media_type: str | None = None
    storage_key: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    ts: int
```

- [ ] **Step 5: Обновить zod-схему**

В `services/gateway/src/contracts/events.ts`, `InboundText`, после `media_type`:

```typescript
    media_type: z.string().nullable().optional(),
    storage_key: z.string().nullable().optional(),
    mime_type: z.string().nullable().optional(),
    size_bytes: z.number().int().nullable().optional(),
    ts: z.number().int(),
```

- [ ] **Step 6: Прогнать тесты снова — ожидаем PASS**

Run: `pytest libs/core/tests/test_events_contract.py -v` и
`cd services/gateway && npx vitest run src/contracts/events.test.ts`

Expected: PASS (все примеры, включая новый).

- [ ] **Step 7: Commit**

```bash
git add docs/contracts/events.schema.json docs/contracts/examples/inbound.text.media.json \
        services/gateway/src/contracts/events.ts libs/core/src/core/events.py
git commit -m "feat(contracts): add storage_key/mime_type/size_bytes to inbound.text

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: messages.media_ref — миграция, модель, запись из worker

**Files:**
- Create: `libs/db/migrations/versions/202609031001_messages_media_ref.py`
- Modify: `libs/db/src/db/models.py`
- Modify: `libs/db/src/db/messages.py`
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Test: `libs/db/tests/test_messages.py`
- Test: `services/worker/tests/pipeline/test_media_fallback.py`

**Interfaces:**
- Consumes: `InboundText.storage_key/mime_type/size_bytes` (Task 1)
- Produces: `insert_incoming(session, bot_id, contact_id, content, wa_msg_id, ts, media_ref: dict[str, Any] | None = None) -> None`
  — новый keyword-параметр, обратная совместимость сохранена (default `None`).

- [ ] **Step 1: Написать падающий тест миграции/модели**

В `libs/db/tests/test_messages.py`, добавить в конец файла:

```python
async def test_insert_incoming_persists_media_ref(session: AsyncSession) -> None:
    bot_id, contact_id = await _make_contact(session)
    media_ref = {"storage_key": "bots/x/media/wamsg-1", "mime_type": "image/jpeg", "size_bytes": 123}
    await insert_incoming(
        session, bot_id, contact_id, "[фото]", "wamsg-media-1", datetime.now(UTC), media_ref=media_ref
    )

    history = await fetch_recent_history(session, contact_id)
    assert history[0].media_ref == media_ref


async def test_insert_incoming_without_media_ref_leaves_it_null(session: AsyncSession) -> None:
    bot_id, contact_id = await _make_contact(session)
    await insert_incoming(session, bot_id, contact_id, "привет", "wamsg-text-1", datetime.now(UTC))

    history = await fetch_recent_history(session, contact_id)
    assert history[0].media_ref is None
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest libs/db/tests/test_messages.py -v`

Expected: FAIL — `insert_incoming() got an unexpected keyword argument 'media_ref'`
(или `AttributeError: 'Message' object has no attribute 'media_ref'`, если Docker
недоступен — тест целиком skip, тогда см. Step 6 про live-прогон).

- [ ] **Step 3: Добавить колонку в модель**

В `libs/db/src/db/models.py`, класс `Message`, после `wa_msg_id`:

```python
    wa_msg_id: Mapped[str | None] = mapped_column(String, nullable=True)
    media_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(
```

(удалить старую строку `ts: Mapped[datetime]...`, заменить на блок выше — `Any` и `JSONB` уже импортированы в файле)

- [ ] **Step 4: Создать миграцию Alembic**

Создать `libs/db/migrations/versions/202609031001_messages_media_ref.py`:

```python
"""messages.media_ref

Revision ID: 202609031001
Revises: 202609021001
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609031001"
down_revision: str | None = "202609021001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("media_ref", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "media_ref")
```

- [ ] **Step 5: Добавить параметр в insert_incoming**

В `libs/db/src/db/messages.py`, добавить `from typing import Any` в импорты, изменить сигнатуру и values:

```python
async def insert_incoming(
    session: AsyncSession,
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    content: str,
    wa_msg_id: str,
    ts: datetime,
    media_ref: dict[str, Any] | None = None,
) -> None:
    """Идемпотентно: редоставка entry консюмер-группой не должна падать
    на UNIQUE(bot_id, wa_msg_id) — тихо игнорируем повтор.
    """
    stmt = (
        insert(Message)
        .values(
            bot_id=bot_id,
            contact_id=contact_id,
            role="user",
            content=content,
            wa_msg_id=wa_msg_id,
            ts=ts,
            media_ref=media_ref,
        )
        .on_conflict_do_nothing(constraint="uq_messages_bot_wa_msg_id")
    )
    await session.execute(stmt)
    await session.flush()
```

- [ ] **Step 6: Прогнать — ожидаем PASS**

Run: `pytest libs/db/tests/test_messages.py -v` (нужен Docker; см.
[[windows-docker-gotchas]] — при проблемах с диском чистить только
build cache, не volumes других проектов)

Expected: PASS

- [ ] **Step 7: Прокинуть storage-поля события в insert_incoming внутри worker**

В `services/worker/src/worker/pipeline/consumer.py`, заменить блок вызова
`insert_incoming` (строки ~100–108):

```python
        content = incoming_content(event.text, event.media_type)
        media_ref = (
            {
                "storage_key": event.storage_key,
                "mime_type": event.mime_type,
                "size_bytes": event.size_bytes,
            }
            if event.storage_key is not None
            else None
        )
        await insert_incoming(
            session,
            event.bot_id,
            contact.id,
            content,
            event.wa_msg_id,
            _to_datetime(event.ts),
            media_ref=media_ref,
        )
```

- [ ] **Step 8: Написать падающий тест на worker-пайплайн**

В `services/worker/tests/pipeline/test_media_fallback.py`, добавить helper и тест
в конец файла:

```python
def _inbound_image_payload_with_storage(bot_id: uuid.UUID) -> dict[str, object]:
    payload = _inbound_image_payload(bot_id)
    payload.update(
        {
            "wa_msg_id": "wamsg-photo-stored-1",
            "storage_key": f"bots/{bot_id}/media/wamsg-photo-stored-1",
            "mime_type": "image/jpeg",
            "size_bytes": 245760,
        }
    )
    return payload


async def test_media_message_with_storage_key_persists_media_ref(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для медиа-сообщения")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_image_payload_with_storage(bot_id), redis, session_factory)

        async with session_factory() as session:
            messages = (
                (
                    await session.execute(
                        select(Message).where(Message.bot_id == bot_id).order_by(Message.ts)
                    )
                )
                .scalars()
                .all()
            )
            assert messages[0].media_ref == {
                "storage_key": f"bots/{bot_id}/media/wamsg-photo-stored-1",
                "mime_type": "image/jpeg",
                "size_bytes": 245760,
            }
    finally:
        await redis.aclose()
```

- [ ] **Step 9: Прогнать — ожидаем FAIL, затем PASS после Step 7**

Run: `pytest services/worker/tests/pipeline/test_media_fallback.py -v`

Expected: с кодом до Step 7 — FAIL (`media_ref` не пишется/не существует);
после Step 7 — PASS. Также прогнать
`pytest services/worker/tests/pipeline/test_media_fallback.py::test_media_message_gets_fallback_reply_without_llm -v`
— регрессия на существующее поведение (медиа без storage_key) не должна сломаться.

- [ ] **Step 10: Commit**

```bash
git add libs/db/migrations/versions/202609031001_messages_media_ref.py \
        libs/db/src/db/models.py libs/db/src/db/messages.py \
        libs/db/tests/test_messages.py \
        services/worker/src/worker/pipeline/consumer.py \
        services/worker/tests/pipeline/test_media_fallback.py
git commit -m "feat(db,worker): persist messages.media_ref from inbound event

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Gateway Storage-абстракция (TS)

**Files:**
- Create: `services/gateway/src/storage/types.ts`
- Create: `services/gateway/src/storage/filesystem.ts`
- Create: `services/gateway/src/storage/filesystem.test.ts`
- Create: `services/gateway/src/storage/s3.ts`
- Create: `services/gateway/src/storage/s3.test.ts`
- Create: `services/gateway/src/storage/index.ts`
- Create: `services/gateway/src/storage/index.test.ts`
- Modify: `services/gateway/package.json` (через `npm install`)

**Interfaces:**
- Produces: `interface Storage { put(key: string, bytes: Buffer, mimeType: string): Promise<void> }`,
  `class FilesystemStorage implements Storage`, `class S3Storage implements Storage`,
  `function createStorage(env?: NodeJS.ProcessEnv): Storage`.

- [ ] **Step 1: Установить `@aws-sdk/client-s3`**

Run:
```bash
cd services/gateway && npm install @aws-sdk/client-s3
```

- [ ] **Step 2: Написать интерфейс Storage**

Создать `services/gateway/src/storage/types.ts`:

```typescript
// Storage-абстракция (FEATURES.md 2.7): gateway пишет медиа сюда, worker
// читает по тому же ключу (см. libs/integrations/src/integrations/storage
// на Python-стороне). Ключ объекта: bots/{bot_id}/media/{wa_msg_id}.
export interface Storage {
  put(key: string, bytes: Buffer, mimeType: string): Promise<void>;
}
```

- [ ] **Step 3: Написать падающий тест FilesystemStorage**

Создать `services/gateway/src/storage/filesystem.test.ts`:

```typescript
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { FilesystemStorage } from "./filesystem.js";

describe("FilesystemStorage", () => {
  let root: string;

  beforeEach(async () => {
    root = await mkdtemp(join(tmpdir(), "storage-test-"));
  });

  afterEach(async () => {
    await rm(root, { recursive: true, force: true });
  });

  it("writes bytes to a nested key, creating directories as needed", async () => {
    const storage = new FilesystemStorage(root);
    await storage.put("bots/bot-1/media/msg-1", Buffer.from("hello"), "text/plain");

    const written = await readFile(join(root, "bots", "bot-1", "media", "msg-1"));
    expect(written.toString()).toBe("hello");
  });
});
```

- [ ] **Step 4: Прогнать — ожидаем FAIL**

Run: `cd services/gateway && npx vitest run src/storage/filesystem.test.ts`

Expected: FAIL — `Cannot find module './filesystem.js'`

- [ ] **Step 5: Реализовать FilesystemStorage**

Создать `services/gateway/src/storage/filesystem.ts`:

```typescript
// Storage поверх локальной ФС — общий docker-volume с worker в dev
// (см. compose/docker-compose.dev.yml). mimeType не нужен для fs, поэтому
// не принимается — сигнатура остаётся присваиваемой к Storage.
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import type { Storage } from "./types.js";

export class FilesystemStorage implements Storage {
  constructor(private readonly root: string) {}

  async put(key: string, bytes: Buffer): Promise<void> {
    const path = join(this.root, key);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, bytes);
  }
}
```

- [ ] **Step 6: Прогнать — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/storage/filesystem.test.ts`

Expected: PASS

- [ ] **Step 7: Написать падающий тест S3Storage**

Создать `services/gateway/src/storage/s3.test.ts`:

```typescript
import type { S3Client } from "@aws-sdk/client-s3";
import { describe, expect, it, vi } from "vitest";
import { S3Storage } from "./s3.js";

function makeFakeClient() {
  return { send: vi.fn(async () => ({})) } as unknown as S3Client;
}

describe("S3Storage", () => {
  it("sends a PutObjectCommand with bucket, key, body and content-type", async () => {
    const client = makeFakeClient();
    const storage = new S3Storage(client, "my-bucket");

    await storage.put("bots/bot-1/media/msg-1", Buffer.from("hello"), "image/jpeg");

    expect(client.send).toHaveBeenCalledTimes(1);
    const command = (client.send as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(command.input).toMatchObject({
      Bucket: "my-bucket",
      Key: "bots/bot-1/media/msg-1",
      ContentType: "image/jpeg",
    });
    expect(Buffer.from(command.input.Body)).toEqual(Buffer.from("hello"));
  });
});
```

- [ ] **Step 8: Прогнать — ожидаем FAIL**

Run: `cd services/gateway && npx vitest run src/storage/s3.test.ts`

Expected: FAIL — `Cannot find module './s3.js'`

- [ ] **Step 9: Реализовать S3Storage**

Создать `services/gateway/src/storage/s3.ts`:

```typescript
// Storage поверх S3-совместимого хранилища (DO Spaces в проде). Таймаут на
// сам вызов — на стороне caller'а (media/download.ts, withTimeout), не здесь.
import { PutObjectCommand, type S3Client } from "@aws-sdk/client-s3";
import type { Storage } from "./types.js";

export class S3Storage implements Storage {
  constructor(
    private readonly client: S3Client,
    private readonly bucket: string,
  ) {}

  async put(key: string, bytes: Buffer, mimeType: string): Promise<void> {
    await this.client.send(
      new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: bytes, ContentType: mimeType }),
    );
  }
}
```

- [ ] **Step 10: Прогнать — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/storage/s3.test.ts`

Expected: PASS

- [ ] **Step 11: Написать падающий тест фабрики createStorage**

Создать `services/gateway/src/storage/index.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { createStorage } from "./index.js";
import { FilesystemStorage } from "./filesystem.js";
import { S3Storage } from "./s3.js";

describe("createStorage", () => {
  it("defaults to FilesystemStorage when STORAGE_DRIVER is unset", () => {
    const storage = createStorage({} as NodeJS.ProcessEnv);
    expect(storage).toBeInstanceOf(FilesystemStorage);
  });

  it("returns S3Storage when STORAGE_DRIVER=s3 with a bucket", () => {
    const storage = createStorage({
      STORAGE_DRIVER: "s3",
      S3_BUCKET: "my-bucket",
      S3_ENDPOINT: "https://example.com",
      S3_REGION: "us-east-1",
      S3_ACCESS_KEY: "key",
      S3_SECRET_KEY: "secret",
    } as unknown as NodeJS.ProcessEnv);
    expect(storage).toBeInstanceOf(S3Storage);
  });

  it("throws when STORAGE_DRIVER=s3 without S3_BUCKET", () => {
    expect(() => createStorage({ STORAGE_DRIVER: "s3" } as NodeJS.ProcessEnv)).toThrow(
      /S3_BUCKET/,
    );
  });
});
```

- [ ] **Step 12: Прогнать — ожидаем FAIL**

Run: `cd services/gateway && npx vitest run src/storage/index.test.ts`

Expected: FAIL — `Cannot find module './index.js'`

- [ ] **Step 13: Реализовать фабрику**

Создать `services/gateway/src/storage/index.ts`:

```typescript
// Выбор реализации Storage по STORAGE_DRIVER=fs|s3 (default fs) — одинаковый
// паттерн на Python-стороне (libs/integrations/src/integrations/storage).
import { S3Client } from "@aws-sdk/client-s3";
import { FilesystemStorage } from "./filesystem.js";
import { S3Storage } from "./s3.js";
import type { Storage } from "./types.js";

export type { Storage } from "./types.js";

const DEFAULT_FS_ROOT = "/data/media";

export function createStorage(env: NodeJS.ProcessEnv = process.env): Storage {
  const driver = env.STORAGE_DRIVER ?? "fs";
  if (driver === "s3") {
    const bucket = env.S3_BUCKET;
    if (!bucket) throw new Error("S3_BUCKET is required when STORAGE_DRIVER=s3");
    const client = new S3Client({
      endpoint: env.S3_ENDPOINT,
      region: env.S3_REGION ?? "us-east-1",
      credentials: {
        accessKeyId: env.S3_ACCESS_KEY ?? "",
        secretAccessKey: env.S3_SECRET_KEY ?? "",
      },
    });
    return new S3Storage(client, bucket);
  }
  return new FilesystemStorage(env.STORAGE_FS_ROOT ?? DEFAULT_FS_ROOT);
}
```

- [ ] **Step 14: Прогнать все тесты storage — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/storage`

Expected: PASS

- [ ] **Step 15: Lint**

Run: `cd services/gateway && npm run lint`

Expected: без ошибок (при unused-var на `mimeType` в FilesystemStorage.put —
параметр там не объявлен вовсе, см. Step 5, ошибки быть не должно)

- [ ] **Step 16: Commit**

```bash
git add services/gateway/package.json services/gateway/package-lock.json services/gateway/src/storage
git commit -m "feat(gateway): Storage abstraction — filesystem and S3 drivers

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Python Storage-абстракция (libs/integrations)

**Files:**
- Create: `libs/integrations/pyproject.toml`
- Create: `libs/integrations/src/integrations/__init__.py`
- Create: `libs/integrations/src/integrations/storage/__init__.py`
- Create: `libs/integrations/src/integrations/storage/filesystem.py`
- Create: `libs/integrations/src/integrations/storage/s3.py`
- Create: `libs/integrations/tests/test_storage_filesystem.py`
- Create: `libs/integrations/tests/test_storage_s3.py`
- Modify: `Makefile` (install/test/lint targets)
- Modify: `pyproject.toml` (root — mypy_path, boto3 override)
- Modify: `services/worker/Dockerfile`

**Interfaces:**
- Produces: `class FilesystemStorage` / `class S3Storage`, оба с
  `async def get(self, key: str) -> bytes`; `def create_storage(env: dict[str, str] | None = None) -> Storage`.
  Ничего из этого пока не вызывается из пайплайна worker'а (используется
  начиная со следующей итерации Волны 1 — vision/STT/PDF).

- [ ] **Step 1: Создать пакет — pyproject.toml**

Создать `libs/integrations/pyproject.toml`:

```toml
[project]
name = "integrations"
version = "0.1.0"
description = "Внешние интеграции: Storage (S3-совместимое/fs), позже Sheets/Telegram/STT (см. ARCHITECTURE.md §4)"
requires-python = ">=3.12"
dependencies = [
    "boto3>=1.34",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Создать пустой корневой `__init__.py`**

Создать `libs/integrations/src/integrations/__init__.py`:

```python
"""Внешние интеграции платформы (Storage, позже Sheets/Telegram/STT)."""
```

- [ ] **Step 3: Написать Storage-протокол**

Создать `libs/integrations/src/integrations/storage/__init__.py`:

```python
"""Storage-абстракция (FEATURES.md 2.7): gateway пишет (TS-сторона,
services/gateway/src/storage), worker читает через этот пакет. Реализация
выбирается STORAGE_DRIVER=fs|s3, одинаково на обеих сторонах.
"""

from __future__ import annotations

import os
from typing import Protocol


class Storage(Protocol):
    async def get(self, key: str) -> bytes: ...


_DEFAULT_FS_ROOT = "/data/media"


def create_storage(env: dict[str, str] | None = None) -> Storage:
    env = env if env is not None else dict(os.environ)
    driver = env.get("STORAGE_DRIVER", "fs")
    if driver == "s3":
        from .s3 import S3Storage

        bucket = env.get("S3_BUCKET")
        if not bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_DRIVER=s3")
        return S3Storage(
            bucket=bucket,
            endpoint_url=env.get("S3_ENDPOINT"),
            region_name=env.get("S3_REGION", "us-east-1"),
            aws_access_key_id=env.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=env.get("S3_SECRET_KEY", ""),
        )
    from .filesystem import FilesystemStorage

    return FilesystemStorage(env.get("STORAGE_FS_ROOT", _DEFAULT_FS_ROOT))
```

- [ ] **Step 4: Написать падающий тест FilesystemStorage**

Создать `libs/integrations/tests/test_storage_filesystem.py`:

```python
"""FilesystemStorage — чтение с общего docker-volume (dev-driver)."""

from __future__ import annotations

from pathlib import Path

from integrations.storage.filesystem import FilesystemStorage


async def test_get_reads_bytes_written_at_nested_key(tmp_path: Path) -> None:
    nested = tmp_path / "bots" / "bot-1" / "media"
    nested.mkdir(parents=True)
    (nested / "msg-1").write_bytes(b"hello")

    storage = FilesystemStorage(str(tmp_path))
    result = await storage.get("bots/bot-1/media/msg-1")

    assert result == b"hello"
```

- [ ] **Step 5: Прогнать — ожидаем FAIL**

Run: `pip install -e libs/integrations && pytest libs/integrations/tests/test_storage_filesystem.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.storage.filesystem'`

- [ ] **Step 6: Реализовать FilesystemStorage**

Создать `libs/integrations/src/integrations/storage/filesystem.py`:

```python
"""Storage поверх локальной ФС — общий docker-volume с gateway в dev
(см. compose/docker-compose.dev.yml, STORAGE_FS_ROOT)."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FilesystemStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    async def get(self, key: str) -> bytes:
        path = self._root / key
        return await asyncio.to_thread(path.read_bytes)
```

- [ ] **Step 7: Прогнать — ожидаем PASS**

Run: `pytest libs/integrations/tests/test_storage_filesystem.py -v`

Expected: PASS

- [ ] **Step 8: Написать падающий тест S3Storage**

Создать `libs/integrations/tests/test_storage_s3.py`:

```python
"""S3Storage — read-путь worker'а из S3-совместимого хранилища (prod-driver)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from integrations.storage.s3 import S3Storage


async def test_get_reads_object_body_via_injected_client() -> None:
    client = MagicMock()
    client.get_object.return_value = {"Body": BytesIO(b"hello")}
    storage = S3Storage(bucket="my-bucket", client=client)

    result = await storage.get("bots/bot-1/media/msg-1")

    assert result == b"hello"
    client.get_object.assert_called_once_with(Bucket="my-bucket", Key="bots/bot-1/media/msg-1")
```

- [ ] **Step 9: Прогнать — ожидаем FAIL**

Run: `pytest libs/integrations/tests/test_storage_s3.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.storage.s3'`

- [ ] **Step 10: Реализовать S3Storage**

Создать `libs/integrations/src/integrations/storage/s3.py`:

```python
"""Storage поверх S3-совместимого хранилища (DO Spaces в проде).

client — опциональная DI-точка для тестов (см. tests/test_storage_s3.py);
в реальной работе создаётся сам через boto3.client(...).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = Any


class S3Storage:
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region_name: str = "us-east-1",
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
        client: S3Client | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            # "любой внешний вызов — с таймаутом" (CLAUDE.md)
            config=Config(connect_timeout=10, read_timeout=20),
        )

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()  # type: ignore[no-any-return]
```

Примечание: пакет `mypy_boto3_s3` не устанавливается (нет в зависимостях) —
`TYPE_CHECKING`-ветка недостижима в рантайме, нужна только чтобы mypy strict
не ругался на `Any` без явного `type: ignore` в аннотации параметра; сам
mypy-прогон покрыт overrides в Step 12.

- [ ] **Step 11: Прогнать — ожидаем PASS**

Run: `pytest libs/integrations/tests/test_storage_s3.py -v`

Expected: PASS

- [ ] **Step 12: Разрешить mypy/ruff резолвить новый пакет**

В корневом `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
mypy_path = "libs/core/src:libs/db/src:libs/llm/src:libs/integrations/src:services/worker/src:services/api/src"
namespace_packages = true
explicit_package_bases = true

[[tool.mypy.overrides]]
module = "boto3.*"
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "botocore.*"
ignore_missing_imports = true
```

(добавить `libs/integrations/src` в существующий `mypy_path`; добавить два
новых `[[tool.mypy.overrides]]` блока — у boto3/botocore нет типов в проекте,
подключать `boto3-stubs` ради одного маленького модуля избыточно)

- [ ] **Step 13: Завести пакет в Makefile**

В `Makefile`, цель `install` — добавить `-e libs/integrations`:

```makefile
install:
	python -m venv .venv || true
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	pip install -e libs/core -e libs/db -e libs/integrations -e services/worker -r requirements-dev.txt
	cd services/gateway && npm install
```

Цель `lint` — добавить `libs/integrations/src` в mypy-прогон:

```makefile
lint:
	. .venv/Scripts/activate 2>/dev/null || . .venv/bin/activate; \
	ruff check . && mypy libs/core/src libs/db/src libs/integrations/src services/worker/src
	cd services/gateway && npm run lint
```

- [ ] **Step 14: Установить пакет и прогнать lint локально**

Run:
```bash
pip install -e libs/integrations
ruff check libs/integrations
mypy libs/integrations/src
```

Expected: без ошибок (если mypy ругается на `mypy_boto3_s3` — убедиться, что
`TYPE_CHECKING`-импорт написан как в Step 10 дословно: mypy не проверяет
недостижимость на рантайме, а статически резолвит тип через overrides).

- [ ] **Step 15: Добавить пакет в Dockerfile worker'а**

В `services/worker/Dockerfile`, добавить `-e /app/libs/integrations` в pip install:

```dockerfile
RUN pip install --no-cache-dir -e /app/libs/core -e /app/libs/db -e /app/libs/llm -e /app/libs/integrations -e /app/services/worker
```

- [ ] **Step 16: Commit**

```bash
git add libs/integrations Makefile pyproject.toml services/worker/Dockerfile
git commit -m "feat(integrations): Storage abstraction — filesystem and S3 drivers (Python read-side)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: Gateway — лимит размера медиа per bot

**Files:**
- Modify: `services/gateway/src/db/bots.ts`
- Create: `services/gateway/src/db/bots.test.ts`

**Interfaces:**
- Produces: `getBotMediaMaxSizeBytes(pool: Pool, botId: string): Promise<number>`,
  `DEFAULT_MEDIA_MAX_SIZE_BYTES` (экспортируемая константа, `16 * 1024 * 1024`).

- [ ] **Step 1: Написать падающий тест**

Создать `services/gateway/src/db/bots.test.ts`:

```typescript
import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_MEDIA_MAX_SIZE_BYTES, getBotMediaMaxSizeBytes } from "./bots.js";

function makeFakePool(settings: Record<string, unknown>): Pool {
  return { query: vi.fn(async () => ({ rows: [{ settings }] })) } as unknown as Pool;
}

describe("getBotMediaMaxSizeBytes", () => {
  it("returns the configured value when settings.media_max_size_bytes is set", async () => {
    const pool = makeFakePool({ media_max_size_bytes: 5_000_000 });
    expect(await getBotMediaMaxSizeBytes(pool, "bot-1")).toBe(5_000_000);
  });

  it("returns the default when the setting is absent", async () => {
    const pool = makeFakePool({});
    expect(await getBotMediaMaxSizeBytes(pool, "bot-1")).toBe(DEFAULT_MEDIA_MAX_SIZE_BYTES);
  });

  it("returns the default when the value is not a positive number", async () => {
    const pool = makeFakePool({ media_max_size_bytes: -1 });
    expect(await getBotMediaMaxSizeBytes(pool, "bot-1")).toBe(DEFAULT_MEDIA_MAX_SIZE_BYTES);
  });
});
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `cd services/gateway && npx vitest run src/db/bots.test.ts`

Expected: FAIL — `getBotMediaMaxSizeBytes` не экспортируется

- [ ] **Step 3: Реализовать**

В `services/gateway/src/db/bots.ts`, добавить в конец файла:

```typescript
export const DEFAULT_MEDIA_MAX_SIZE_BYTES = 16 * 1024 * 1024;

export async function getBotMediaMaxSizeBytes(pool: Pool, botId: string): Promise<number> {
  const { rows } = await pool.query<{ settings: { media_max_size_bytes?: unknown } }>(
    "SELECT settings FROM bots WHERE id = $1",
    [botId],
  );
  const value = rows[0]?.settings?.media_max_size_bytes;
  return typeof value === "number" && value > 0 ? value : DEFAULT_MEDIA_MAX_SIZE_BYTES;
}
```

- [ ] **Step 4: Прогнать — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/db/bots.test.ts`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/gateway/src/db/bots.ts services/gateway/src/db/bots.test.ts
git commit -m "feat(gateway): per-bot media size limit lookup

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Gateway — скачивание медиа и подключение в пайплайн

**Files:**
- Create: `services/gateway/src/media/download.ts`
- Create: `services/gateway/src/media/download.test.ts`
- Modify: `services/gateway/src/session/manager.ts`
- Modify: `services/gateway/src/session/manager.test.ts`
- Modify: `services/gateway/src/main.ts`

**Interfaces:**
- Consumes: `Storage.put` (Task 3), `getBotMediaMaxSizeBytes` (Task 5), `withTimeout` (existing)
- Produces: `extractMediaFileInfo(msg: WAMessage): { mimeType: string; fileLength: number } | null`,
  `attachMedia(pool, storage, logger, botId, waMsgId, msg): Promise<{ storage_key: string; mime_type: string; size_bytes: number } | null>`

- [ ] **Step 1: Написать падающий тест extractMediaFileInfo**

Создать `services/gateway/src/media/download.test.ts`:

```typescript
import type { WAMessage } from "@whiskeysockets/baileys";
import { describe, expect, it, vi } from "vitest";
import { extractMediaFileInfo } from "./download.js";

function imageMessage(overrides: Record<string, unknown> = {}): WAMessage {
  return {
    key: { remoteJid: "996700000000@s.whatsapp.net", id: "MSG1", fromMe: false },
    message: { imageMessage: { mimetype: "image/jpeg", fileLength: 245760, ...overrides } },
  } as unknown as WAMessage;
}

describe("extractMediaFileInfo", () => {
  it("reads mimetype and fileLength from an image message", () => {
    expect(extractMediaFileInfo(imageMessage())).toEqual({
      mimeType: "image/jpeg",
      fileLength: 245760,
    });
  });

  it("returns null when fileLength is missing (can't verify limit — skip safely)", () => {
    expect(extractMediaFileInfo(imageMessage({ fileLength: undefined }))).toBeNull();
  });

  it("returns null when there is no media content", () => {
    const msg = {
      key: { remoteJid: "x", id: "MSG1", fromMe: false },
      message: { conversation: "text only" },
    } as unknown as WAMessage;
    expect(extractMediaFileInfo(msg)).toBeNull();
  });
});
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `cd services/gateway && npx vitest run src/media/download.test.ts`

Expected: FAIL — `Cannot find module './download.js'`

- [ ] **Step 3: Реализовать extractMediaFileInfo + заготовку attachMedia**

Создать `services/gateway/src/media/download.ts`:

```typescript
// 1.9 + 2.7: лимит размера ДО скачивания (грабля: причина OOM прошлой
// версии), скачивание+расшифровка через Baileys, загрузка в Storage. Любой
// сбой на этом пути НЕ блокирует приём сообщения: событие уходит без
// storage_key, worker откатывается на существующий media-fallback (2.6).
import { downloadMediaMessage, getContentType, toNumber, type WAMessage } from "@whiskeysockets/baileys";
import type { Pool } from "pg";

import { getBotMediaMaxSizeBytes } from "../db/bots.js";
import type { TransportLogger } from "../logger.js";
import type { Storage } from "../storage/types.js";
import { withTimeout } from "../utils/timeout.js";

const DOWNLOAD_TIMEOUT_MS = 20_000;
const UPLOAD_TIMEOUT_MS = 20_000;

export interface MediaAttachment {
  storage_key: string;
  mime_type: string;
  size_bytes: number;
}

interface MediaFileInfo {
  mimeType: string;
  fileLength: number;
}

/** Чистая функция — достаёт mimetype/fileLength из протобаф-сообщения, без сети. */
export function extractMediaFileInfo(msg: WAMessage): MediaFileInfo | null {
  const contentType = getContentType(msg.message);
  if (!contentType || !msg.message) return null;
  const content = msg.message as unknown as Record<string, unknown>;
  const body = content[contentType] as { mimetype?: string; fileLength?: number } | undefined;
  if (!body?.mimetype) return null;
  const fileLength = toNumber(body.fileLength);
  if (!fileLength) return null; // неизвестный размер — не можем проверить лимит, пропускаем безопасно
  return { mimeType: body.mimetype, fileLength };
}

export async function attachMedia(
  pool: Pool,
  storage: Storage,
  logger: TransportLogger,
  botId: string,
  waMsgId: string,
  msg: WAMessage,
): Promise<MediaAttachment | null> {
  const info = extractMediaFileInfo(msg);
  if (!info) {
    logger.warn({ botId, waMsgId }, "media_skipped: no file info in message");
    return null;
  }

  const maxBytes = await getBotMediaMaxSizeBytes(pool, botId);
  if (info.fileLength > maxBytes) {
    logger.warn({ botId, waMsgId, fileLength: info.fileLength, maxBytes }, "media_skipped: too_large");
    return null;
  }

  let bytes: Buffer;
  try {
    bytes = await withTimeout(
      downloadMediaMessage(msg, "buffer", {}, { logger }),
      DOWNLOAD_TIMEOUT_MS,
      "media download",
    );
  } catch (err) {
    logger.warn({ err, botId, waMsgId }, "media_skipped: download_failed");
    return null;
  }

  const key = `bots/${botId}/media/${waMsgId}`;
  try {
    await withTimeout(storage.put(key, bytes, info.mimeType), UPLOAD_TIMEOUT_MS, "storage put");
  } catch (err) {
    logger.warn({ err, botId, waMsgId }, "media_skipped: upload_failed");
    return null;
  }

  return { storage_key: key, mime_type: info.mimeType, size_bytes: bytes.length };
}
```

- [ ] **Step 4: Прогнать extractMediaFileInfo — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/media/download.test.ts`

Expected: PASS (3 теста extractMediaFileInfo)

- [ ] **Step 5: Написать падающие тесты attachMedia (лимит, скачивание, сбои)**

Сначала поправить самый верх `services/gateway/src/media/download.test.ts` —
`vi.mock` хостится vitest'ом перед всеми импортами модуля (тот же паттерн,
что в `session/manager.test.ts`), поэтому мок и его импорт идут ДО импорта
`extractMediaFileInfo`/`attachMedia`, а не рядом с новыми тестами внизу:

```typescript
import type { WAMessage } from "@whiskeysockets/baileys";
import { describe, expect, it, vi } from "vitest";

vi.mock("@whiskeysockets/baileys", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@whiskeysockets/baileys")>();
  return { ...actual, downloadMediaMessage: vi.fn() };
});

const { downloadMediaMessage } = await import("@whiskeysockets/baileys");
import { attachMedia, extractMediaFileInfo } from "./download.js";
import type { Storage } from "../storage/types.js";
```

(это заменяет исходные два импорта из Step 1 — `WAMessage` и
`extractMediaFileInfo` теперь идут через этот блок)

Затем добавить в конец файла:

```typescript
function makeFakePool(maxBytes?: number) {
  const settings = maxBytes ? { media_max_size_bytes: maxBytes } : {};
  return { query: vi.fn(async () => ({ rows: [{ settings }] })) } as unknown as import("pg").Pool;
}

function makeFakeStorage(): Storage {
  return { put: vi.fn(async () => undefined) };
}

function makeFakeLogger(): TransportLoggerLike {
  const logger = {
    level: "info",
    child: () => logger,
    trace: vi.fn(),
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  return logger;
}
type TransportLoggerLike = ReturnType<typeof makeFakeLogger>;

describe("attachMedia", () => {
  it("skips download when fileLength exceeds the bot's limit", async () => {
    const pool = makeFakePool(1_000);
    const storage = makeFakeStorage();
    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
    expect(storage.put).not.toHaveBeenCalled();
    expect(downloadMediaMessage).not.toHaveBeenCalled();
  });

  it("downloads and uploads when within the limit, returning attachment fields", async () => {
    vi.mocked(downloadMediaMessage).mockResolvedValue(Buffer.from("bytes"));
    const pool = makeFakePool(10_000_000);
    const storage = makeFakeStorage();

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toEqual({
      storage_key: "bots/bot-1/media/MSG1",
      mime_type: "image/jpeg",
      size_bytes: 5,
    });
    expect(storage.put).toHaveBeenCalledWith("bots/bot-1/media/MSG1", Buffer.from("bytes"), "image/jpeg");
  });

  it("returns null when the CDN download fails, without throwing", async () => {
    vi.mocked(downloadMediaMessage).mockRejectedValue(new Error("network down"));
    const pool = makeFakePool(10_000_000);
    const storage = makeFakeStorage();

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
    expect(storage.put).not.toHaveBeenCalled();
  });

  it("returns null when the storage upload fails, without throwing", async () => {
    vi.mocked(downloadMediaMessage).mockResolvedValue(Buffer.from("bytes"));
    const pool = makeFakePool(10_000_000);
    const storage = { put: vi.fn(async () => { throw new Error("s3 down"); }) };

    const result = await attachMedia(pool, storage, makeFakeLogger(), "bot-1", "MSG1", imageMessage());

    expect(result).toBeNull();
  });
});
```

- [ ] **Step 6: Прогнать — ожидаем FAIL**

Run: `cd services/gateway && npx vitest run src/media/download.test.ts`

Expected: FAIL до этого шага код уже реализован в Step 3 — ожидаем, что новые
4 теста тоже пройдут сразу (реализация уже покрывает эти случаи). Если
падает — сверить моки `downloadMediaMessage`/`storage.put` дословно с
сигнатурами из Step 3.

- [ ] **Step 7: Прогнать все тесты media — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/media/download.test.ts`

Expected: PASS (7 тестов)

- [ ] **Step 8: Подключить storage в конструктор SessionManager**

В `services/gateway/src/session/manager.ts`:
- добавить импорт: `import type { Storage } from "../storage/types.js";` и
  `import { attachMedia } from "../media/download.js";`
- изменить конструктор:

```typescript
  constructor(
    private readonly pool: Pool,
    private readonly redis: Redis,
    private readonly logger: TransportLogger,
    private readonly storage: Storage,
  ) {}
```

- изменить `onMessagesUpsert`:

```typescript
  private async onMessagesUpsert(
    botId: string,
    upsert: { messages: WAMessage[]; type: MessageUpsertType },
  ): Promise<void> {
    if (upsert.type !== "notify") return;

    for (const msg of upsert.messages) {
      const event = normalizeInboundMessage(botId, msg);
      if (!event) continue;

      let outgoingEvent = event;
      if (event.media_type) {
        const attachment = await attachMedia(this.pool, this.storage, this.logger, botId, event.wa_msg_id, msg);
        if (attachment) {
          outgoingEvent = { ...event, ...attachment };
        }
      }

      try {
        await publishEvent(this.redis, IN_STREAM, outgoingEvent);
      } catch (err) {
        this.logger.error({ err, botId, waMsgId: event.wa_msg_id }, "failed to publish inbound.text");
      }
    }
  }
```

- [ ] **Step 9: Обновить существующие вызовы `new SessionManager(...)` в тестах**

В `services/gateway/src/session/manager.test.ts`, добавить helper рядом с
остальными (`makeFakePool`/`makeFakeRedis`/`makeFakeLogger`):

```typescript
function makeFakeStorage(): import("../storage/types.js").Storage {
  return { put: vi.fn(async () => undefined) };
}
```

И добавить `makeFakeStorage()` четвёртым аргументом в оба существующих
вызова `new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger())`
(строки 65 и 78) → `new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage())`.

- [ ] **Step 10: Прогнать существующие тесты SessionManager — ожидаем PASS**

Run: `cd services/gateway && npx vitest run src/session/manager.test.ts`

Expected: PASS (без регрессий)

- [ ] **Step 11: Подключить в main.ts**

В `services/gateway/src/main.ts`:

```typescript
import { closeRedis, getRedis } from "./bus/redis.js";
import { botExists, listLinkedBotIds } from "./db/bots.js";
import { closePool, getPool } from "./db/pool.js";
import { OutboundConsumer } from "./outbound/consumer.js";
import { SessionManager } from "./session/manager.js";
import { createStorage } from "./storage/index.js";

const app = Fastify({ logger: { name: "gateway" } });
const pool = getPool();
const redis = getRedis();
const storage = createStorage();
const sessions = new SessionManager(pool, redis, app.log, storage);
```

- [ ] **Step 12: Полный прогон gateway-тестов**

Run: `cd services/gateway && npm test`

Expected: PASS, без регрессий во всём пакете

- [ ] **Step 13: Lint + typecheck**

Run: `cd services/gateway && npm run lint && npx tsc --noEmit`

Expected: без ошибок

- [ ] **Step 14: Commit**

```bash
git add services/gateway/src/media services/gateway/src/session/manager.ts \
        services/gateway/src/session/manager.test.ts services/gateway/src/main.ts
git commit -m "feat(gateway): download+limit+upload inbound media, attach to wa:in event

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Docker Compose / env — dev fs-driver, prod s3-driver

**Files:**
- Modify: `compose/docker-compose.dev.yml`
- Modify: `compose/docker-compose.prod.yml`
- Modify: `.env.example`

**Interfaces:**
- Нет кода — только конфигурация окружения, потребляемая `createStorage()` /
  `create_storage()` из Task 3/4.

- [ ] **Step 1: Dev — общий volume и STORAGE_DRIVER=fs**

В `compose/docker-compose.dev.yml`, добавить в сервис `gateway`:

```yaml
  gateway:
    build:
      context: ../services/gateway
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgres://platform:platform@postgres:5432/platform
      REDIS_URL: redis://redis:6379/0
      GATEWAY_PORT: "8080"
      STORAGE_DRIVER: fs
      STORAGE_FS_ROOT: /data/media
    ports:
      - "8080:8080"
    volumes:
      - ../services/gateway/src:/app/src
      - media-data:/data/media
```

В сервис `worker`:

```yaml
  worker:
    build:
      context: ..
      dockerfile: services/worker/Dockerfile
    environment:
      DATABASE_URL: postgres://platform:platform@postgres:5432/platform
      REDIS_URL: redis://redis:6379/0
      WORKER_HEALTH_PORT: "8081"
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4o-mini}
      STORAGE_DRIVER: fs
      STORAGE_FS_ROOT: /data/media
    volumes:
      - ../services/worker/src:/app/services/worker/src
      - ../libs:/app/libs
      - media-data:/data/media
```

И в конце файла, секцию `volumes`:

```yaml
volumes:
  postgres-data:
  media-data:
```

- [ ] **Step 2: Prod — S3-driver**

В `compose/docker-compose.prod.yml`, добавить в сервис `gateway`:

```yaml
  gateway:
    build:
      context: ../services/gateway
      dockerfile: Dockerfile.prod
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://redis:6379/0
      GATEWAY_PORT: "8080"
      STORAGE_DRIVER: s3
      S3_ENDPOINT: ${S3_ENDPOINT:?S3_ENDPOINT не задан в .env}
      S3_BUCKET: ${S3_BUCKET:?S3_BUCKET не задан в .env}
      S3_REGION: ${S3_REGION:-fra1}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY:?S3_ACCESS_KEY не задан в .env}
      S3_SECRET_KEY: ${S3_SECRET_KEY:?S3_SECRET_KEY не задан в .env}
```

В сервис `worker`:

```yaml
  worker:
    build:
      context: ..
      dockerfile: services/worker/Dockerfile
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://redis:6379/0
      WORKER_HEALTH_PORT: "8081"
      OPENAI_API_KEY: ${OPENAI_API_KEY:?OPENAI_API_KEY не задан в .env}
      OPENAI_MODEL: ${OPENAI_MODEL:-gpt-4o-mini}
      STORAGE_DRIVER: s3
      S3_ENDPOINT: ${S3_ENDPOINT:?S3_ENDPOINT не задан в .env}
      S3_BUCKET: ${S3_BUCKET:?S3_BUCKET не задан в .env}
      S3_REGION: ${S3_REGION:-fra1}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY:?S3_ACCESS_KEY не задан в .env}
      S3_SECRET_KEY: ${S3_SECRET_KEY:?S3_SECRET_KEY не задан в .env}
```

- [ ] **Step 3: Задокументировать переменные в .env.example**

В `.env.example`, после `OPENAI_MODEL=gpt-4o-mini`:

```
STORAGE_DRIVER=fs
STORAGE_FS_ROOT=/data/media

# Только для docker-compose.prod.yml при STORAGE_DRIVER=s3 (DO Spaces или
# другое S3-совместимое хранилище):
S3_ENDPOINT=
S3_BUCKET=
S3_REGION=fra1
S3_ACCESS_KEY=
S3_SECRET_KEY=
```

- [ ] **Step 4: Валидация конфигов**

Run: `docker compose -f compose/docker-compose.dev.yml config --quiet` и
`docker compose -f compose/docker-compose.prod.yml config --quiet`

Expected: без ошибок парсинга YAML (prod-файл может ругаться на
незаполненные `:?`-переменные — это ожидаемо вне сервера, синтаксис главное
проверить: `docker compose -f compose/docker-compose.prod.yml config --quiet 2>&1 | grep -v "variable is not set"`
не должен показывать ничего кроме этих warning'ов)

- [ ] **Step 5: Commit**

```bash
git add compose/docker-compose.dev.yml compose/docker-compose.prod.yml .env.example
git commit -m "feat(deploy): wire STORAGE_DRIVER — fs volume in dev, S3 env in prod

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Живой прогон (docker compose)

Ручной шаг — по [[live-verification-preference]], не только зелёные тесты.

**Files:** нет (верификация, не код)

- [ ] **Step 1: Поднять dev-стек**

Run: `make dev` (или `docker compose -f compose/docker-compose.dev.yml up --build`)

Перед тяжёлой сборкой — проверить свободное место (`Get-PSDrive C` из
PowerShell), см. [[windows-docker-gotchas]].

- [ ] **Step 2: Прогнать миграции**

Run: `docker compose -f compose/docker-compose.dev.yml exec worker alembic -c /app/libs/db/alembic.ini upgrade head`

(запускать из директории `/app/libs/db` внутри контейнера, а не с абсолютным
путём в `-c`, если Git Bash на хосте искажает путь — см. [[windows-docker-gotchas]];
сам `exec` идёт с хоста, это не затронуто)

- [ ] **Step 3: Создать тестового бота и прогнать медиа-сообщение**

Через `docker compose exec postgres psql` создать тестового бота (или
переиспользовать уже существующего тестового бота из Блоков 1–3), затем
собрать и отправить в `wa:in` событие с медиа напрямую через `redis-cli`:

```bash
docker compose -f compose/docker-compose.dev.yml exec redis redis-cli XADD wa:in '*' payload \
  '{"type":"inbound.text","bot_id":"<BOT_ID>","wa_msg_id":"live-test-1","chat_id":"996700000000@s.whatsapp.net","sender_wa_id":"996700000000","from_me":false,"text":"","media_type":"image","storage_key":"bots/<BOT_ID>/media/live-test-1","mime_type":"image/jpeg","size_bytes":123,"ts":1756900000000}'
```

(это проверяет worker-часть — запись `media_ref`; для полной проверки
gateway-части нужен реальный тестовый номер с реальным фото — если он
поднят, отправить фото боту напрямую в WhatsApp и пропустить XADD выше)

- [ ] **Step 4: Свериться с БД**

Run: `docker compose -f compose/docker-compose.dev.yml exec postgres psql -U platform -d platform -c "SELECT wa_msg_id, media_ref FROM messages WHERE wa_msg_id = 'live-test-1';"`

Expected: строка с заполненным `media_ref` JSON (`{"storage_key": "...", "mime_type": "image/jpeg", "size_bytes": 123}`)

- [ ] **Step 5: Если тестировался реальный номер — свериться с файлом на диске**

Run: `docker compose -f compose/docker-compose.dev.yml exec gateway ls -la /data/media/bots/<BOT_ID>/media/`

Expected: файл с именем `wa_msg_id` реального фото присутствует, размер > 0

- [ ] **Step 6: Проверить деградацию — медиа больше лимита**

Через `psql`, выставить тестовому боту маленький лимит:
`UPDATE bots SET settings = settings || '{"media_max_size_bytes": 100}'::jsonb WHERE id = '<BOT_ID>';`
Отправить фото ещё раз (или другой `wa_msg_id`) — в логах gateway
(`docker compose logs gateway`) должна появиться строка `media_skipped: too_large`,
а в БД `messages.media_ref` для этого сообщения — `NULL`, ответ клиенту —
как раньше, `media_fallback_text`.

- [ ] **Step 7: Обновить память проекта**

После успешного прогона — обновить [[stage1-core-progress]]: этот пункт
Волны 1 закрыт, следующий — 2.1 (vision-анализ), уже может читать
`Storage.get()` из `libs/integrations`.
