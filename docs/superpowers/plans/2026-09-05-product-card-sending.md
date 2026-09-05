# Отправка карточки товара — фото + текст (FEATURES.md 4.3/4.4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** когда тулза `search_products` находит товар, клиенту уходит не текст LLM, а реальная карточка — фото товара (одно или несколько) + структурированный текст, точно как в архиве V1.

**Architecture:** новый узкий тип события `outbound.image` в контракте; `services/gateway` учится читать байты из `Storage` и слать изображение через Baileys; `Tool.execute()` возвращает структурированный `ToolExecutionResult` (текст для LLM + опциональные "отправь это клиенту вместо ответа LLM" текст/медиа) вместо голой строки; `services/worker`'s `tool_loop.py` прокидывает это наверх, а `consumer.py::_reply()` решает, что реально публиковать в `wa:out`. `ToolContext` не меняется — тулза не публикует события сама (ADR-002).

**Tech Stack:** TypeScript (gateway, Baileys, zod), Python 3.12 (worker, tools, db — SQLAlchemy 2.0 async, Alembic), Redis Streams, Postgres.

**Spec:** `docs/superpowers/specs/2026-09-05-product-card-sending-design.md`

## Global Constraints

- 4.3 и 4.4 реализуются вместе, одним кодом (эталон V1 — один и тот же цикл для 1 или N фото).
- **Не добавлять в этой итерации**: ретраи с backoff при отправке (отдельный, уже задокументированный технический долг `services/gateway`), ресайз изображений (некуда встраивать без upload-пайплайна, Wave 3).
- Если товар найден — клиенту уходит ТОЛЬКО карточка (фото+текст), собственный текстовый ответ LLM в этом ходе **не отправляется** (жёстко, без переключателя; переключатель — заметка на будущее, не эта итерация).
- Новый тип события — узкий `outbound.image`, НЕ общий `outbound.media` (узкие миграции/типы сейчас, объединение позже, если понадобится).
- `ToolContext` не меняется — тулзы не публикуют события сами, только возвращают данные.
- Изображения НЕ отражаются в `messages.media_ref` в этой итерации (только текст карточки идёт в историю).
- Session-lifetime: DB-сессия не держится открытой во время сетевого вызова OpenAI (урок 4.1/4.2) — поиск фото товара делается СРАЗУ после его нахождения, в той же сессии/ветке (exact-match или vector), не в отдельном третьем открытии после `generate_embedding`.
- Любой tool-executor с сетевым вызовом внутри `execute()` укладывается в `TOOL_CALL_TIMEOUT_SECONDS=20с` (`worker/pipeline/tool_loop.py`) — уже соблюдено существующим `EMBEDDING_TIMEOUT_SECONDS=5.0`, этой итерации новых сетевых вызовов не добавляет.

---

## Task 1: Контракт событий — `outbound.image`

**Files:**
- Modify: `docs/contracts/events.schema.json`
- Modify: `libs/core/src/core/events.py`
- Modify: `services/gateway/src/contracts/events.ts`
- Create: `docs/contracts/examples/outbound.image.json`

**Interfaces:**
- Produces: Pydantic `OutboundImage` (`libs/core/src/core/events.py`) — поля `type: Literal["outbound.image"]`, `bot_id: UUID`, `chat_id: str`, `storage_key: str`, `mime_type: str`, `client_msg_id: str`. Zod `OutboundImage` (`services/gateway/src/contracts/events.ts`) — зеркально. Оба входят в объединение `Event`.

Тесты на эту задачу — уже существующие data-driven файлы
(`libs/core/tests/test_events_contract.py`, `services/gateway/src/contracts/events.test.ts`):
они автоматически подхватывают любой файл в `docs/contracts/examples/*.json`
и сверяют его и с JSON Schema, и с моделью своего языка — новых тестов
писать не нужно, только фикстуру и сами схема/модели.

- [ ] **Step 1: Добавить фикстуру `outbound.image` (RED — типа ещё нет ни в схеме, ни в моделях)**

Создать `docs/contracts/examples/outbound.image.json`:

```json
{
  "type": "outbound.image",
  "bot_id": "00000000-0000-0000-0000-000000000001",
  "chat_id": "996700000000@s.whatsapp.net",
  "storage_key": "bots/00000000-0000-0000-0000-000000000001/products/img-1.jpg",
  "mime_type": "image/jpeg",
  "client_msg_id": "8f3e9c1a4b2d4e119f0a1234567890ab"
}
```

- [ ] **Step 2: Убедиться, что оба контрактных теста падают**

Run: `cd libs/core && python -m pytest tests/test_events_contract.py -v`
Expected: FAIL — `test_examples_cover_all_schema_variants` (лишний тип в
примерах, которого нет в схеме) и `test_example_matches_json_schema[outbound.image]`
(ни один вариант `oneOf` не подходит).

Run: `cd services/gateway && npx vitest run src/contracts/events.test.ts`
Expected: FAIL по той же причине на TS-стороне.

- [ ] **Step 3: Добавить `outboundImage` в JSON Schema**

В `docs/contracts/events.schema.json` — новое определение в `definitions`
(вставить после блока `"outboundText"`, перед `"outboundTyping"`):

```json
    "outboundImage": {
      "type": "object",
      "description": "Исходящее изображение в wa:out (FEATURES.md 4.3/4.4 — карточка товара).",
      "additionalProperties": false,
      "properties": {
        "type": { "const": "outbound.image" },
        "bot_id": { "type": "string", "format": "uuid" },
        "chat_id": { "type": "string", "minLength": 1 },
        "storage_key": { "type": "string", "minLength": 1 },
        "mime_type": { "type": "string", "minLength": 1 },
        "client_msg_id": { "type": "string", "minLength": 1 }
      },
      "required": ["type", "bot_id", "chat_id", "storage_key", "mime_type", "client_msg_id"]
    },
```

И добавить ссылку на него в `oneOf` (после `outboundText`, перед `outboundTyping`):

```json
  "oneOf": [
    { "$ref": "#/definitions/inboundText" },
    { "$ref": "#/definitions/outboundText" },
    { "$ref": "#/definitions/outboundImage" },
    { "$ref": "#/definitions/outboundTyping" },
    { "$ref": "#/definitions/sessionStatus" }
  ]
```

- [ ] **Step 4: Добавить Pydantic-модель `OutboundImage`**

В `libs/core/src/core/events.py` — новый класс (после `OutboundText`,
перед `OutboundTyping`):

```python
class OutboundImage(BaseModel):
    """Исходящее изображение в wa:out (FEATURES.md 4.3/4.4 — карточка товара)."""

    type: Literal["outbound.image"] = "outbound.image"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)
```

И расширить объединение:

```python
Event = InboundText | OutboundText | OutboundImage | OutboundTyping | SessionStatus
```

- [ ] **Step 5: Добавить zod-схему `OutboundImage`**

В `services/gateway/src/contracts/events.ts` — новая схема (после
`OutboundText`, перед `OutboundTyping`):

```typescript
export const OutboundImage = z
  .object({
    type: z.literal("outbound.image"),
    bot_id: z.string().uuid(),
    chat_id: z.string().min(1),
    storage_key: z.string().min(1),
    mime_type: z.string().min(1),
    client_msg_id: z.string().min(1),
  })
  .strict();
export type OutboundImage = z.infer<typeof OutboundImage>;
```

И расширить объединение:

```typescript
export const Event = z.discriminatedUnion("type", [
  InboundText,
  OutboundText,
  OutboundImage,
  OutboundTyping,
  SessionStatus,
]);
export type Event = z.infer<typeof Event>;
```

- [ ] **Step 6: Прогнать оба контрактных теста снова — GREEN**

Run: `cd libs/core && python -m pytest tests/test_events_contract.py -v`
Expected: PASS (все параметризованные варианты, включая `outbound.image`).

Run: `cd services/gateway && npx vitest run src/contracts/events.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/contracts/events.schema.json docs/contracts/examples/outbound.image.json libs/core/src/core/events.py services/gateway/src/contracts/events.ts
git commit -m "feat(contracts): add outbound.image event type"
```

---

## Task 2: `Storage.get()` в gateway (fs + s3)

**Files:**
- Modify: `services/gateway/src/storage/types.ts`
- Modify: `services/gateway/src/storage/filesystem.ts`
- Modify: `services/gateway/src/storage/filesystem.test.ts`
- Modify: `services/gateway/src/storage/s3.ts`
- Modify: `services/gateway/src/storage/s3.test.ts`

**Interfaces:**
- Consumes: ничего нового.
- Produces: `Storage.get(key: string): Promise<Buffer>` — используется Task 3 (`OutboundConsumer`).

- [ ] **Step 1: Дополнить интерфейс `Storage`**

В `services/gateway/src/storage/types.ts`:

```typescript
// Storage-абстракция (FEATURES.md 2.7): gateway пишет медиа сюда, worker
// читает по тому же ключу (см. libs/integrations/src/integrations/storage
// на Python-стороне). Ключ объекта: bots/{bot_id}/media/{wa_msg_id}.
export interface Storage {
  put(key: string, bytes: Buffer, mimeType: string): Promise<void>;
  get(key: string): Promise<Buffer>;
}
```

- [ ] **Step 2: Написать падающие тесты для `FilesystemStorage.get()`**

Добавить в `services/gateway/src/storage/filesystem.test.ts` (внутри
существующего `describe("FilesystemStorage", ...)`, после уже
существующих тестов):

```typescript
  it("reads back bytes written by put", async () => {
    const storage = new FilesystemStorage(root);
    await storage.put("bots/bot-1/media/msg-1", Buffer.from("hello"), "text/plain");

    const bytes = await storage.get("bots/bot-1/media/msg-1");
    expect(bytes.toString()).toBe("hello");
  });

  it("throws when the key attempts path traversal via nested dots", async () => {
    const storage = new FilesystemStorage(root);
    const key = "bots/x/media/../../../../../etc/cron.d/evil";

    await expect(storage.get(key)).rejects.toThrow();
  });
```

- [ ] **Step 3: Прогнать — RED (метода `get` ещё нет)**

Run: `cd services/gateway && npx vitest run src/storage/filesystem.test.ts`
Expected: FAIL — `storage.get is not a function`.

- [ ] **Step 4: Реализовать `FilesystemStorage.get()`**

Заменить содержимое `services/gateway/src/storage/filesystem.ts` целиком
(защита от path traversal вынесена в общий приватный метод — тот же текст
ошибки, что и раньше, `put()`-тесты не затрагиваются):

```typescript
// Storage поверх локальной ФС — общий docker-volume с worker в dev
// (см. compose/docker-compose.dev.yml). mimeType не нужен для fs, поэтому
// не принимается — сигнатура остаётся присваиваемой к Storage.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join, resolve, sep } from "node:path";
import type { Storage } from "./types.js";

export class FilesystemStorage implements Storage {
  constructor(private readonly root: string) {}

  private resolveWithinRoot(key: string): string {
    const resolvedRoot = resolve(this.root);
    const resolvedPath = resolve(join(this.root, key));
    if (resolvedPath !== resolvedRoot && !resolvedPath.startsWith(resolvedRoot + sep)) {
      throw new Error(`storage key resolves outside root: ${key}`);
    }
    return resolvedPath;
  }

  async put(key: string, bytes: Buffer): Promise<void> {
    const resolvedPath = this.resolveWithinRoot(key);
    await mkdir(dirname(resolvedPath), { recursive: true });
    await writeFile(resolvedPath, bytes);
  }

  async get(key: string): Promise<Buffer> {
    const resolvedPath = this.resolveWithinRoot(key);
    return readFile(resolvedPath);
  }
}
```

- [ ] **Step 5: Прогнать — GREEN**

Run: `cd services/gateway && npx vitest run src/storage/filesystem.test.ts`
Expected: PASS (все тесты, старые и новые).

- [ ] **Step 6: Написать падающие тесты для `S3Storage.get()`**

Добавить в `services/gateway/src/storage/s3.test.ts` (после существующего
теста, импорт `GetObjectCommand` не нужен — тест мокает только `send`):

```typescript
  it("reads bytes back via GetObjectCommand", async () => {
    const client = {
      send: vi.fn(async () => ({
        Body: { transformToByteArray: async () => new Uint8Array(Buffer.from("hello")) },
      })),
    } as unknown as S3Client;
    const storage = new S3Storage(client, "my-bucket");

    const bytes = await storage.get("bots/bot-1/media/msg-1");

    expect(bytes).toEqual(Buffer.from("hello"));
    const command = (client.send as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(command.input).toMatchObject({ Bucket: "my-bucket", Key: "bots/bot-1/media/msg-1" });
  });

  it("throws when the S3 response has no body", async () => {
    const client = { send: vi.fn(async () => ({ Body: undefined })) } as unknown as S3Client;
    const storage = new S3Storage(client, "my-bucket");

    await expect(storage.get("missing-key")).rejects.toThrow();
  });
```

- [ ] **Step 7: Прогнать — RED**

Run: `cd services/gateway && npx vitest run src/storage/s3.test.ts`
Expected: FAIL — `storage.get is not a function`.

- [ ] **Step 8: Реализовать `S3Storage.get()`**

Заменить содержимое `services/gateway/src/storage/s3.ts` целиком:

```typescript
// Storage поверх S3-совместимого хранилища (DO Spaces в проде). Таймаут на
// сам вызов — на стороне caller'а (media/download.ts, withTimeout), не здесь.
import { GetObjectCommand, PutObjectCommand, type S3Client } from "@aws-sdk/client-s3";
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

  async get(key: string): Promise<Buffer> {
    const response = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }));
    if (!response.Body) throw new Error(`no body in S3 response for key: ${key}`);
    const bytes = await response.Body.transformToByteArray();
    return Buffer.from(bytes);
  }
}
```

- [ ] **Step 9: Прогнать — GREEN**

Run: `cd services/gateway && npx vitest run src/storage/s3.test.ts`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add services/gateway/src/storage
git commit -m "feat(gateway): add Storage.get() for filesystem and s3 backends"
```

---

## Task 3: `SessionManager.sendImage()` + `OutboundConsumer` обрабатывает `outbound.image`

**Files:**
- Modify: `services/gateway/src/session/manager.ts`
- Modify: `services/gateway/src/session/manager.test.ts`
- Modify: `services/gateway/src/outbound/consumer.ts`
- Modify: `services/gateway/src/outbound/consumer.test.ts`
- Modify: `services/gateway/src/main.ts`

**Interfaces:**
- Consumes: `Storage.get(key): Promise<Buffer>` (Task 2), `OutboundImage` zod-тип (Task 1).
- Produces: `SessionManager.sendImage(botId, chatId, image, mimeType, clientMsgId): Promise<void>`; `OutboundConsumer` конструктор — 4 параметра (`redis, sessions, logger, storage`).

- [ ] **Step 1: Написать падающий тест для `sendImage`**

Добавить в `services/gateway/src/session/manager.test.ts`, внутри
`describe("SessionManager.sendText / sendTyping", ...)`, после теста
`"sendTyping sends a composing presence update"`:

```typescript
  it("sendImage passes clientMsgId as Baileys messageId with image+mimetype", async () => {
    const sessions = new SessionManager(makeFakePool(), makeFakeRedis(), makeFakeLogger(), makeFakeStorage());
    await sessions.startSession("bot-1");

    const image = Buffer.from("fake-jpeg-bytes");
    await sessions.sendImage("bot-1", "996700000000@s.whatsapp.net", image, "image/jpeg", "img-msg-1");

    expect(sendMessageMock).toHaveBeenCalledWith(
      "996700000000@s.whatsapp.net",
      { image, mimetype: "image/jpeg" },
      { messageId: "img-msg-1" },
    );
  });
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd services/gateway && npx vitest run src/session/manager.test.ts`
Expected: FAIL — `sessions.sendImage is not a function`.

- [ ] **Step 3: Реализовать `SessionManager.sendImage()`**

В `services/gateway/src/session/manager.ts` добавить метод сразу после
`sendTyping` (строка 137, перед `async stopAll()`):

```typescript
  /** Аналогично sendText — messageId=clientMsgId для той же связки с
   * идемпотентностью/handoff-echo-детектом (wa:sent:{client_msg_id}). */
  async sendImage(
    botId: string,
    chatId: string,
    image: Buffer,
    mimeType: string,
    clientMsgId: string,
  ): Promise<void> {
    await this.activeSocket(botId).sendMessage(
      chatId,
      { image, mimetype: mimeType },
      { messageId: clientMsgId },
    );
  }
```

- [ ] **Step 4: Прогнать — GREEN**

Run: `cd services/gateway && npx vitest run src/session/manager.test.ts`
Expected: PASS (все тесты файла).

- [ ] **Step 5: Обновить `consumer.test.ts` — добавить `storage` в моки и вызовы, написать падающие тесты для `outbound.image`**

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
});
```

- [ ] **Step 6: Прогнать — RED**

Run: `cd services/gateway && npx vitest run src/outbound/consumer.test.ts`
Expected: FAIL — тип TS не совпадает (конструктор ожидает 3 аргумента, тест передаёт 4) и/или `outbound.image` не обрабатывается.

- [ ] **Step 7: Реализовать в `consumer.ts` — конструктор + ветка `outbound.image`**

Заменить содержимое `services/gateway/src/outbound/consumer.ts` целиком:

```typescript
// Consumer group на wa:out: outbound.text / outbound.typing / outbound.image ->
// отправка через Baileys. Идемпотентность по client_msg_id (SET NX EX 3600) ДО
// отправки — ретрай worker'а не должен породить дубль сообщения клиенту
// (CLAUDE.md, "Исходящие идемпотентны"). Ошибка отправки — лог + ACK, без
// ретраев (ретраи с backoff — Волна 1, вне скоупа Блока 1).
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
        event.type === "outbound.image"
      ) {
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
    event: Extract<Event, { type: "outbound.text" | "outbound.typing" | "outbound.image" }>,
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
      } else {
        const image = await this.storage.get(event.storage_key);
        await withTimeout(
          this.sessions.sendImage(event.bot_id, event.chat_id, image, event.mime_type, event.client_msg_id),
          SEND_TIMEOUT_MS,
          "sendImage",
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

Run: `cd services/gateway && npx vitest run src/outbound/consumer.test.ts`
Expected: PASS (все 7 тестов).

- [ ] **Step 9: Прокинуть `storage` в `main.ts`**

В `services/gateway/src/main.ts`, строка 18, заменить:

```typescript
const outbound = new OutboundConsumer(redis, sessions, app.log);
```

на:

```typescript
const outbound = new OutboundConsumer(redis, sessions, app.log, storage);
```

- [ ] **Step 10: Прогнать полный пакет тестов gateway**

Run: `cd services/gateway && npx vitest run`
Expected: PASS (все файлы), плюс `npx tsc --noEmit` без ошибок типов.

- [ ] **Step 11: Commit**

```bash
git add services/gateway/src/session/manager.ts services/gateway/src/session/manager.test.ts services/gateway/src/outbound/consumer.ts services/gateway/src/outbound/consumer.test.ts services/gateway/src/main.ts
git commit -m "feat(gateway): send outbound.image via SessionManager.sendImage"
```

---

## Task 4: `libs/db` — таблица `product_images`

**Files:**
- Modify: `libs/db/src/db/models.py`
- Create: `libs/db/migrations/versions/202609051005_product_images.py`
- Create: `libs/db/src/db/product_images.py`
- Create: `libs/db/tests/test_product_images.py`
- Modify: `libs/db/tests/test_migration.py`

**Interfaces:**
- Produces: `ProductImage` модель (`libs/db/src/db/models.py`) — `id, product_id, storage_key, mime_type, position, created_at`. `list_product_images(session, product_id) -> list[ProductImage]` (`libs/db/src/db/product_images.py`) — используется Task 5 (`ProductSearchTool`).

- [ ] **Step 1: Написать падающие тесты `list_product_images`**

Создать `libs/db/tests/test_product_images.py`:

```python
"""Фото товара (FEATURES.md 4.3/4.4): list_product_images — порядок по
position, скоуп per product, пусто по умолчанию. Требует Docker
(testcontainers). Без него — skip, не fail.
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
from db.models import Bot, Product, ProductImage
from db.product_images import list_product_images
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


async def _make_product(session: AsyncSession) -> uuid.UUID:
    bot = Bot(name="test-bot")
    session.add(bot)
    await session.flush()
    product = Product(bot_id=bot.id, name="Кроссовки Nike Air")
    session.add(product)
    await session.flush()
    return product.id


async def test_list_product_images_empty_by_default(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await list_product_images(session, product_id) == []


async def test_list_product_images_ordered_by_position(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    session.add_all(
        [
            ProductImage(product_id=product_id, storage_key="img-2", mime_type="image/jpeg", position=2),
            ProductImage(product_id=product_id, storage_key="img-0", mime_type="image/jpeg", position=0),
            ProductImage(product_id=product_id, storage_key="img-1", mime_type="image/jpeg", position=1),
        ]
    )
    await session.flush()

    images = await list_product_images(session, product_id)
    assert [i.storage_key for i in images] == ["img-0", "img-1", "img-2"]


async def test_list_product_images_scoped_per_product(session: AsyncSession) -> None:
    product_a = await _make_product(session)
    product_b = await _make_product(session)
    session.add_all(
        [
            ProductImage(product_id=product_a, storage_key="img-a", mime_type="image/jpeg", position=0),
            ProductImage(product_id=product_b, storage_key="img-b", mime_type="image/jpeg", position=0),
        ]
    )
    await session.flush()

    images_a = await list_product_images(session, product_a)
    assert [i.storage_key for i in images_a] == ["img-a"]
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd libs/db && python -m pytest tests/test_product_images.py -v`
Expected: FAIL — `ImportError: cannot import name 'ProductImage'` (модели и
модуля запроса ещё нет).

- [ ] **Step 3: Добавить модель `ProductImage`**

В `libs/db/src/db/models.py`, в самый конец файла, после `ProductEmbedding`:

```python


class ProductImage(Base):
    """Фото товара, одно или несколько, порядок — position (FEATURES.md
    4.3/4.4). Загрузка (значит, и заполнение этой таблицы) — Волна 3
    (6.8), здесь только хранение и чтение."""

    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("product_id", "position", name="uq_product_images_product_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 4: Создать миграцию**

Создать `libs/db/migrations/versions/202609051005_product_images.py`:

```python
"""product_images

Revision ID: 202609051005
Revises: 202609051004
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609051005"
down_revision: str | None = "202609051004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_images",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("product_id", "position", name="uq_product_images_product_position"),
    )


def downgrade() -> None:
    op.drop_table("product_images")
```

- [ ] **Step 5: Создать `product_images.py`**

Создать `libs/db/src/db/product_images.py`:

```python
"""Фото товара (FEATURES.md 4.3/4.4). Загрузка — Волна 3 (CRUD, 6.8),
здесь только чтение для отправки карточки."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProductImage


async def list_product_images(session: AsyncSession, product_id: uuid.UUID) -> list[ProductImage]:
    stmt = (
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

- [ ] **Step 6: Прогнать — GREEN**

Run: `cd libs/db && python -m pytest tests/test_product_images.py -v`
Expected: PASS (3 теста; либо реально запускаются с Docker, либо skip,
если Docker недоступен в среде выполнения).

- [ ] **Step 7: Обновить `test_migration.py` — добавить `product_images` в ожидаемые таблицы**

В `libs/db/tests/test_migration.py`, строки 60-63, заменить:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products", "product_embeddings",
        } <= tables
```

на:

```python
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products", "product_embeddings",
            "product_images",
        } <= tables
```

- [ ] **Step 8: Прогнать полный пакет `libs/db`**

Run: `cd libs/db && python -m pytest -v`
Expected: PASS (все тесты пакета, включая `test_migration.py`).

- [ ] **Step 9: Commit**

```bash
git add libs/db/src/db/models.py libs/db/src/db/product_images.py libs/db/migrations/versions/202609051005_product_images.py libs/db/tests/test_product_images.py libs/db/tests/test_migration.py
git commit -m "feat(db): add product_images table and list_product_images query"
```

---

## Task 5: `libs/tools` — структурированный результат тулзы + карточка в `ProductSearchTool`

**Files:**
- Modify: `libs/tools/src/tools/base.py`
- Modify: `libs/tools/src/tools/product_search.py`
- Modify: `libs/tools/tests/test_product_search.py`
- Modify: `libs/tools/tests/test_registry.py`

**Interfaces:**
- Consumes: `list_product_images(session, product_id)` (Task 4).
- Produces: `Tool` Protocol с `parameters_schema` как `@property` и
  `execute(...) -> ToolExecutionResult`; `ToolExecutionResult(content, override_reply_text=None, media=())`;
  `MediaToSend(storage_key, mime_type)` — все три из `tools.base`, используются Task 6 (`tool_loop.py`, `consumer.py`).

- [ ] **Step 1: Обновить `test_registry.py` — `_DummyTool.execute()` возвращает `ToolExecutionResult`**

Заменить содержимое `libs/tools/tests/test_registry.py` целиком:

```python
"""Реестр тулз (FEATURES.md 4.13): get_tool/all_tool_names/register.
Первая настоящая тулза — search_products (FEATURES.md 4.1/4.2).
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from tools import registry
from tools.base import ToolExecutionResult
from tools.product_search import ProductSearchTool


class _DummyTool:
    name = "dummy"
    description = "тестовая тулза"
    parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, object], ctx: object) -> ToolExecutionResult:
        return ToolExecutionResult(content="ok")


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

- [ ] **Step 2: Обновить `test_product_search.py` — существующие тесты читают `.content`, добавить тесты карточки**

Заменить содержимое `libs/tools/tests/test_product_search.py` целиком:

```python
"""ProductSearchTool (FEATURES.md 4.1/4.2/4.3/4.4): точное совпадение
сначала, векторный поиск — только если точного нет; при находке — также
override_reply_text+media (карточка товара). Требует Docker
(testcontainers) — реальный Postgres, генерация эмбеддинга подменена
фейком (не настоящий OpenAI).
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
from db.models import Bot, Product, ProductEmbedding, ProductImage
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
    assert json.loads(result.content) == [
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
    assert json.loads(result.content)[0]["name"] == "Кроссовки Nike Air"


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
    assert json.loads(result.content)[0]["name"] == "Кеды Adidas"


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
    assert result.content == "[]"
    assert result.override_reply_text is None
    assert result.media == ()


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
    assert json.loads(result.content)[0]["price"] == "Не указана"


async def test_found_product_with_images_returns_override_reply_text_and_media(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        product = Product(
            bot_id=bot.id, name="Кроссовки Nike Air",
            price=Decimal("5000.00"), description="Беговые",
        )
        session.add(product)
        await session.flush()
        session.add_all(
            [
                ProductImage(
                    product_id=product.id, storage_key="img-0", mime_type="image/jpeg", position=0
                ),
                ProductImage(
                    product_id=product.id, storage_key="img-1", mime_type="image/png", position=1
                ),
            ]
        )
        await session.commit()

    result = await ProductSearchTool().execute(
        {"query": "Кроссовки Nike Air"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "*Кроссовки Nike Air*\nБеговые\nЦена: 5000.00"
    assert [(m.storage_key, m.mime_type) for m in result.media] == [
        ("img-0", "image/jpeg"),
        ("img-1", "image/png"),
    ]


async def test_found_product_without_images_returns_override_reply_text_without_media(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(Product(bot_id=bot.id, name="Товар без фото"))
        await session.commit()

    result = await ProductSearchTool().execute(
        {"query": "Товар без фото"}, _make_ctx(bot, session_factory)
    )

    assert result.override_reply_text == "*Товар без фото*\nЦена: Не указана"
    assert result.media == ()
```

- [ ] **Step 3: Прогнать — RED**

Run: `cd libs/tools && python -m pytest tests/test_product_search.py tests/test_registry.py -v`
Expected: FAIL — `result.content`/`result.override_reply_text` не
существуют (тулза всё ещё возвращает голую строку), `ProductImage` не
импортируется в тулзе.

- [ ] **Step 4: Исправить `tools/base.py` — Protocol + `ToolExecutionResult`/`MediaToSend`**

Заменить содержимое `libs/tools/src/tools/base.py` целиком:

```python
"""Интерфейс тулзы бота (FEATURES.md 4.13). Тулза возвращает
ToolExecutionResult, а не голую строку (FEATURES.md 4.3/4.4) — так тулза
может сообщить "отправь клиенту вот это фото+текст ВМЕСТО ответа LLM", не
проходя эту возможность через отдельный API. Кто реально публикует
событие в wa:out — services/worker/pipeline/consumer.py::_reply() (у него
уже есть chat_id/redis/OUT_STREAM); ToolContext НЕ меняется — тулза не
публикует события сама (ADR-002, worker — оркестрация).

parameters_schema объявлен как read-only property (не обычный атрибут) —
это принимает и ClassVar-объявление в реализациях (естественная идиома
для неизменяемого dict), и обычный instance-атрибут, снимая
несовместимость с mypy strict, найденную финальным ревью 4.1/4.2.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from db.models import Bot
from integrations.storage import Storage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class ToolContext:
    bot: Bot
    contact_id: uuid.UUID
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: Storage
    config: dict[str, Any]


@dataclass(frozen=True)
class MediaToSend:
    storage_key: str
    mime_type: str


@dataclass(frozen=True)
class ToolExecutionResult:
    content: str  # как раньше — уходит в LLM как результат tool call
    # Если задано — уходит клиенту ВМЕСТО ответа LLM (FEATURES.md 4.3/4.4);
    # None — поведение как раньше (LLM отвечает своим текстом).
    override_reply_text: str | None = None
    media: Sequence[MediaToSend] = ()  # фото, отправляются раньше override_reply_text


class Tool(Protocol):
    name: str
    description: str

    @property
    def parameters_schema(self) -> dict[str, Any]: ...

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult: ...
```

- [ ] **Step 5: Обновить `product_search.py`**

Заменить содержимое `libs/tools/src/tools/product_search.py` целиком:

```python
"""Поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2); при
находке дополнительно собирает карточку (FEATURES.md 4.3/4.4 — эталон V1,
vectorProductSearch + formatProductText). Точное совпадение по имени
сначала, векторный поиск — только если точного нет.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from db.product_embeddings import find_product_by_embedding
from db.product_images import list_product_images
from db.products import find_product_by_exact_name
from llm.embeddings import generate_embedding

from .base import MediaToSend, ToolContext, ToolExecutionResult

_NOT_SPECIFIED_PRICE = "Не указана"
EMBEDDING_TIMEOUT_SECONDS = 5.0


def _format_card_text(name: str, description: str | None, price: str) -> str:
    """Эталон V1 (formatProductText) при дефолтных глобальных настройках
    вывода (show_name/show_description/show_price всегда true) — сами
    переключатели ещё не реализованы (FEATURES.md 4.5/4.6, следующая
    итерация); когда появятся — эта функция получит параметр displayCfg."""
    parts = [f"*{name}*"]
    if description:
        parts.append(description)
    parts.append(f"Цена: {price}")
    return "\n".join(parts)


class ProductSearchTool:
    name = "search_products"
    description = "Ищет товар в каталоге бота по названию или похожему описанию."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Название или описание товара, которое ищет клиент"}
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        query = str(arguments.get("query", ""))
        if not query.strip():
            return ToolExecutionResult(content="[]")

        # Фото ищем СРАЗУ после нахождения товара, в ТОЙ ЖЕ сессии/ветке —
        # не в отдельном третьем открытии после generate_embedding (урок
        # 4.1/4.2: сессия не должна держаться открытой во время сетевого
        # вызова OpenAI).
        async with ctx.session_factory() as session:
            product = await find_product_by_exact_name(session, ctx.bot.id, query)
            images = await list_product_images(session, product.id) if product is not None else []

        if product is None:
            embedding = await generate_embedding(query, timeout_seconds=EMBEDDING_TIMEOUT_SECONDS)
            async with ctx.session_factory() as session:
                product = await find_product_by_embedding(session, ctx.bot.id, embedding)
                images = await list_product_images(session, product.id) if product is not None else []

        if product is None:
            return ToolExecutionResult(content="[]")

        price = str(product.price) if product.price is not None else _NOT_SPECIFIED_PRICE
        content = json.dumps(
            [{"name": product.name, "description": product.description or "", "price": price}],
            ensure_ascii=False,
        )
        return ToolExecutionResult(
            content=content,
            override_reply_text=_format_card_text(product.name, product.description, price),
            # tuple(), не список: пустой список != () при сравнении (Python
            # не считает [] и () равными), а дефолт ToolExecutionResult.media
            # — именно (). tuple() на пустом images даёт (), совпадает с
            # дефолтом и с ожиданием теста "без фото".
            media=tuple(MediaToSend(storage_key=i.storage_key, mime_type=i.mime_type) for i in images),
        )
```

- [ ] **Step 6: Прогнать — GREEN**

Run: `cd libs/tools && python -m pytest tests/test_product_search.py tests/test_registry.py -v`
Expected: PASS (7 тестов поиска + 5 тестов реестра).

- [ ] **Step 7: Прогнать mypy strict на `libs/tools`**

Run: `cd libs/tools && mypy --strict src`
Expected: 0 ошибок (в частности — `ClassVar[dict]`-объявление
`parameters_schema` в `ProductSearchTool` больше не конфликтует с
Protocol, `# noqa: RUF012` больше не нужен и в коде отсутствует).

- [ ] **Step 8: Commit**

```bash
git add libs/tools/src/tools/base.py libs/tools/src/tools/product_search.py libs/tools/tests/test_product_search.py libs/tools/tests/test_registry.py
git commit -m "feat(tools): ProductSearchTool sends product card (photos + text)"
```

---

## Task 6: `services/worker` — прокидка `ToolExecutionResult` и реальная отправка карточки

**Files:**
- Modify: `services/worker/src/worker/pipeline/tool_loop.py`
- Modify: `services/worker/tests/pipeline/test_tool_loop.py`
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Modify: `services/worker/tests/pipeline/test_reply_tools.py`

**Interfaces:**
- Consumes: `ToolExecutionResult`, `MediaToSend` (Task 5, `tools.base`); `OutboundImage` (Task 1, `core.events`).
- Produces: `ToolLoopResult` с полями `override_reply_text: str | None`, `media: Sequence[MediaToSend]`.

- [ ] **Step 1: Обновить `test_tool_loop.py` — фейковые executor'ы возвращают `ToolExecutionResult`**

Заменить содержимое `services/worker/tests/pipeline/test_tool_loop.py`
целиком:

```python
"""run_tool_loop: цикл LLM↔tool-calls (FEATURES.md 4.13, инфраструктура;
FEATURES.md 4.3/4.4 — прокидка override_reply_text/media от тулзы к
вызывающему). complete_fn/complete_with_tools_fn/executor — все фейковые,
сценарии прогоняются полностью синхронно предсказуемым скриптом, без
реального OpenAI-вызова.
"""

from __future__ import annotations

from llm.client import (
    HistoryMessage,
    LLMResult,
    ToolCall,
    ToolResultTurn,
    ToolSpec,
)
from tools.base import MediaToSend, ToolExecutionResult
from worker.pipeline.tool_loop import ToolLoopResult, run_tool_loop

_SPEC = ToolSpec(name="search", description="ищет товар", parameters_schema={"type": "object"})


async def _unused_executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
    raise AssertionError("не должен вызываться в этом сценарии")


async def test_empty_tools_calls_complete_fn_directly() -> None:
    async def complete_fn(system_prompt: str, history: list[HistoryMessage]) -> LLMResult:
        return LLMResult(text="прямой ответ", tokens_in=10, tokens_out=2, model="gpt-4o-mini")

    async def fail_complete_with_tools(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("не должен вызываться, когда tools пуст")

    result = await run_tool_loop(
        "SYS",
        [],
        [],
        _unused_executor,
        complete_fn=complete_fn,
        complete_with_tools_fn=fail_complete_with_tools,
    )
    assert result == ToolLoopResult(
        text="прямой ответ", tokens_in=10, tokens_out=2, model="gpt-4o-mini"
    )


async def test_single_round_returns_text_when_no_tool_calls_requested() -> None:
    async def complete_with_tools_fn(*args: object, **kwargs: object) -> LLMResult:
        return LLMResult(text="готовый ответ", tokens_in=20, tokens_out=8, model="gpt-4o-mini")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], _unused_executor, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "готовый ответ"
    assert result.tokens_in == 20
    assert result.tokens_out == 8
    assert result.override_reply_text is None
    assert result.media == ()


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
                text="",
                tokens_in=15,
                tokens_out=5,
                model="gpt-4o-mini",
                tool_calls=[
                    ToolCall(
                        id="call_1", name="search", arguments_json='{"q": "кроссовки"}'
                    )
                ],
            )
        return LLMResult(
            text="Нашёл кроссовки Nike.",
            tokens_in=25,
            tokens_out=10,
            model="gpt-4o-mini",
        )

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        assert name == "search"
        assert arguments == {"q": "кроссовки"}
        return ToolExecutionResult(content="Nike Air, 5000 сом")

    result = await run_tool_loop(
        "SYS",
        [],
        [_SPEC],
        executor,
        complete_with_tools_fn=complete_with_tools_fn,
    )

    assert result.text == "Нашёл кроссовки Nike."
    assert result.tokens_in == 15 + 25
    assert result.tokens_out == 5 + 10
    assert calls[0]["exchange_len"] == 0
    assert calls[1]["exchange_len"] == 2  # assistant-tool-calls + tool-result


async def test_tool_result_with_override_reply_text_propagates_to_loop_result() -> None:
    """FEATURES.md 4.3/4.4: если тулза вернула override_reply_text/media —
    ToolLoopResult их несёт наверх (последний найденный товар в ходе
    актуален — тест с одним вызовом тулзы этого не проверяет отдельно,
    "последний выигрывает" покрыт следующим тестом)."""

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
        return LLMResult(text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="m")

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        return ToolExecutionResult(
            content='[{"name": "Nike Air"}]',
            override_reply_text="*Nike Air*\nЦена: 5000",
            media=[MediaToSend(storage_key="img-1", mime_type="image/jpeg")],
        )

    result = await run_tool_loop(
        "SYS", [], [_SPEC], executor, complete_with_tools_fn=complete_with_tools_fn
    )

    assert result.text == "текст LLM, будет отброшен"
    assert result.override_reply_text == "*Nike Air*\nЦена: 5000"
    assert [(m.storage_key, m.mime_type) for m in result.media] == [("img-1", "image/jpeg")]


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

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        raise RuntimeError("тулза упала")

    result = await run_tool_loop(
        "SYS",
        [],
        [_SPEC],
        executor,
        complete_with_tools_fn=complete_with_tools_fn,
    )
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
                text="итоговый ответ по тому, что успел узнать",
                tokens_in=1,
                tokens_out=1,
                model="m",
            )
        return LLMResult(
            text="", tokens_in=1, tokens_out=1, model="m",
            tool_calls=[ToolCall(id=f"call_{call_count}", name="search", arguments_json="{}")],
        )

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        return ToolExecutionResult(content="результат")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], executor, max_rounds=2, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "итоговый ответ по тому, что успел узнать"
    assert call_count == 3  # 2 обычных раунда + 1 форсированный текстовый
```

- [ ] **Step 2: Прогнать — RED**

Run: `cd services/worker && python -m pytest tests/pipeline/test_tool_loop.py -v`
Expected: FAIL — `ImportError` (`ToolExecutionResult`/`MediaToSend` не
существуют в `tools.base` со стороны импорта теста... на самом деле уже
существуют после Task 5; здесь падение — `AttributeError`/`AssertionError`
на `result.override_reply_text`/`result.media`, которых у `ToolLoopResult`
ещё нет).

- [ ] **Step 3: Обновить `tool_loop.py`**

Заменить содержимое `services/worker/src/worker/pipeline/tool_loop.py`
целиком:

```python
"""Цикл LLM↔tool-calls (FEATURES.md 4.13, инфраструктура; FEATURES.md
4.3/4.4 — прокидка override_reply_text/media от тулзы наверх). Оркестрация
— здесь (ADR-002: worker = бизнес-логика); механика одного вызова OpenAI —
libs/llm. См. docs/superpowers/specs/2026-09-05-tool-calling-infra-design.md
и docs/superpowers/specs/2026-09-05-product-card-sending-design.md

При пустом списке тулз — один вызов complete_fn(), форма запроса и
поведение идентичны тому, что было до этой фичи: это гарантирует, что
подключение цикла в _reply() (Task 5) при пустом реестре тулз у всех
ботов сейчас — ноль изменений в живом поведении.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
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
from tools.base import MediaToSend, ToolExecutionResult

logger = structlog.get_logger("worker.pipeline.tool_loop")

MAX_TOOL_ROUNDS = 5
TOOL_CALL_TIMEOUT_SECONDS = 20.0

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[ToolExecutionResult]]
_CompleteFn = Callable[[str, list[HistoryMessage]], Awaitable[LLMResult]]
_CompleteWithToolsFn = Callable[..., Awaitable[LLMResult]]


@dataclass(frozen=True)
class ToolLoopResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    # Если задано — тулза решила, что клиенту нужно отправить не текст
    # LLM, а карточку (FEATURES.md 4.3/4.4). "Последний выигрывает" —
    # если тулз в ходе несколько, актуален только последний найденный товар.
    override_reply_text: str | None = None
    media: Sequence[MediaToSend] = ()


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
            text=result.text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            model=result.model,
        )

    exchange: list[ToolExchangeTurn] = []
    tokens_in_total = 0
    tokens_out_total = 0
    model_name = ""
    override_reply_text: str | None = None
    media: Sequence[MediaToSend] = ()

    for _ in range(max_rounds):
        result = await complete_with_tools_fn(system_prompt, history, tools, exchange)
        tokens_in_total += result.tokens_in
        tokens_out_total += result.tokens_out
        model_name = result.model

        if not result.tool_calls:
            return ToolLoopResult(
                text=result.text,
                tokens_in=tokens_in_total,
                tokens_out=tokens_out_total,
                model=model_name,
                override_reply_text=override_reply_text,
                media=media,
            )

        exchange.append(AssistantToolCallsTurn(result.tool_calls))
        for call in result.tool_calls:
            tool_result = await _run_one_tool(call, executor)
            exchange.append(ToolResultTurn(call.id, call.name, tool_result.content))
            if tool_result.override_reply_text is not None:
                override_reply_text = tool_result.override_reply_text
                media = tool_result.media

    logger.warning("tool loop reached max_rounds, forcing final text answer", max_rounds=max_rounds)
    result = await complete_with_tools_fn(system_prompt, history, tools, exchange, force_text=True)
    tokens_in_total += result.tokens_in
    tokens_out_total += result.tokens_out
    return ToolLoopResult(
        text=result.text,
        tokens_in=tokens_in_total,
        tokens_out=tokens_out_total,
        model=result.model,
        override_reply_text=override_reply_text,
        media=media,
    )


async def _run_one_tool(call: ToolCall, executor: ToolExecutor) -> ToolExecutionResult:
    try:
        arguments: dict[str, Any] = json.loads(call.arguments_json) if call.arguments_json else {}
    except json.JSONDecodeError:
        logger.warning("tool call arguments are not valid json", tool_name=call.name)
        return ToolExecutionResult(
            content="Ошибка: не удалось разобрать аргументы как JSON. Повтори вызов с корректным JSON."
        )

    try:
        return await asyncio.wait_for(
            executor(call.name, arguments), timeout=TOOL_CALL_TIMEOUT_SECONDS
        )
    except Exception:
        logger.warning("tool execution failed", tool_name=call.name, exc_info=True)
        return ToolExecutionResult(
            content="Ошибка при вызове инструмента. Продолжай без этого результата или попробуй иначе."
        )
```

- [ ] **Step 4: Прогнать — GREEN**

Run: `cd services/worker && python -m pytest tests/pipeline/test_tool_loop.py -v`
Expected: PASS (8 тестов).

- [ ] **Step 5: Обновить `test_reply_tools.py` — фейковая тулза возвращает `ToolExecutionResult`, добавить сквозной тест карточки**

В `services/worker/tests/pipeline/test_reply_tools.py`:

1. Добавить в импорты (после `from tools.base import ToolContext`):

```python
import json

from tools.base import MediaToSend, ToolExecutionResult
```

2. В `test_registered_tool_is_offered_and_can_be_invoked_end_to_end` заменить
   тело `_FakeSearchTool.execute`:

```python
        async def execute(self, arguments: dict[str, object], ctx: ToolContext) -> ToolExecutionResult:
            captured_contexts.append(ctx)
            return ToolExecutionResult(content="найдено: тестовый товар")
```

(остальное тело функции и теста не меняется — `tool_results[0].content`
по-прежнему сравнивается со строкой, потому что `ToolResultTurn.content`
берётся из `ToolExecutionResult.content`, как и раньше).

3. Добавить новый тест в конец файла:

```python


async def test_tool_override_reply_sends_media_and_override_text_instead_of_llm_text(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.3/4.4: если тулза вернула override_reply_text —
    клиенту уходит typing + карточка (фото + текст карточки), а не текст
    LLM."""

    class _FakeCardTool:
        name = "search"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(self, arguments: dict[str, object], ctx: ToolContext) -> ToolExecutionResult:
            return ToolExecutionResult(
                content='[{"name": "Nike Air"}]',
                override_reply_text="*Nike Air*\nЦена: 5000",
                media=[MediaToSend(storage_key="bots/x/products/img-1.jpg", mime_type="image/jpeg")],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "search", _FakeCardTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        return LLMResult(
            text="этот текст LLM не должен уйти клиенту",
            tokens_in=1, tokens_out=1, model="gpt-4o-mini",
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "search", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, outbound.image, outbound.text — три события, текст LLM среди них нет
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.image"
        assert payloads[1]["storage_key"] == "bots/x/products/img-1.jpg"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "*Nike Air*\nЦена: 5000"
        assert not any("этот текст LLM" in p.get("text", "") for p in payloads)
    finally:
        await redis.aclose()
```

- [ ] **Step 6: Прогнать — RED**

Run: `cd services/worker && python -m pytest tests/pipeline/test_reply_tools.py -v`
Expected: FAIL — `_reply()` ещё не знает про `override_reply_text`, всегда
отправляет `loop_result.text` (тест ожидает 3 события, получит 2 —
typing+text с текстом LLM).

- [ ] **Step 7: Обновить `consumer.py` — импорты, `_send_card`, `_reply()`, `executor` типы**

В `services/worker/src/worker/pipeline/consumer.py`:

1. В блоке импортов заменить строку:

```python
from core.events import Event, InboundText, OutboundText, OutboundTyping
```

на:

```python
from core.events import Event, InboundText, OutboundImage, OutboundText, OutboundTyping
```

2. Добавить `from collections.abc import Sequence` в блок импортов —
   isort-порядок в этом файле группирует `from X import Y` по алфавиту
   модуля, поэтому строка встаёт ПЕРЕД `from datetime import UTC, datetime, timedelta`:

```python
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
```

3. Заменить строку:

```python
from tools.base import ToolContext
```

на:

```python
from tools.base import MediaToSend, ToolContext, ToolExecutionResult
```

4. Добавить новую функцию `_send_card` сразу после `_send_reply` (после
   строки 254, перед `async def _schedule_follow_up`):

```python


async def _send_card(
    event: InboundText, redis: Redis, text: str, media: Sequence[MediaToSend]
) -> None:
    """FEATURES.md 4.3/4.4: карточка товара — typing, затем фото (одно или
    несколько, в порядке media), затем текст карточки. client_msg_id — новый
    .hex на КАЖДОЕ исходящее событие, как и в _send_reply (идемпотентность
    gateway ключуется по нему одинаково для любого типа исходящего)."""
    typing_event = OutboundTyping(
        bot_id=event.bot_id, chat_id=event.chat_id, client_msg_id=uuid.uuid4().hex
    )
    await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))
    for item in media:
        image_event = OutboundImage(
            bot_id=event.bot_id,
            chat_id=event.chat_id,
            storage_key=item.storage_key,
            mime_type=item.mime_type,
            client_msg_id=uuid.uuid4().hex,
        )
        await publish(redis, OUT_STREAM, image_event.model_dump(mode="json"))
    text_event = OutboundText(
        bot_id=event.bot_id, chat_id=event.chat_id, text=text, client_msg_id=uuid.uuid4().hex
    )
    await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))
```

5. В `_reply()` заменить блок (текущие строки 337-345):

```python
    if not loop_result.text.strip():
        logger.warning("LLM returned empty text, not sending", bot_id=str(event.bot_id))
        return

    await _send_reply(event, redis, loop_result.text)

    cost = compute_cost(loop_result.model, loop_result.tokens_in, loop_result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, loop_result.text)
```

на:

```python
    if loop_result.override_reply_text is not None:
        # FEATURES.md 4.3/4.4: тулза нашла товар — клиенту уходит ТОЛЬКО
        # карточка, собственный текст LLM в этом ходе отбрасывается
        # (подтверждено пользователем, эталон V1).
        reply_text = loop_result.override_reply_text
        await _send_card(event, redis, reply_text, loop_result.media)
    else:
        if not loop_result.text.strip():
            logger.warning("LLM returned empty text, not sending", bot_id=str(event.bot_id))
            return
        reply_text = loop_result.text
        await _send_reply(event, redis, reply_text)

    cost = compute_cost(loop_result.model, loop_result.tokens_in, loop_result.tokens_out)
    async with session_factory() as session:
        outgoing_seq = await insert_outgoing(session, event.bot_id, contact_id, reply_text)
```

(Строка `await record_usage(...)` сразу после — без изменений: `tokens_in`/
`tokens_out`/`cost` по-прежнему берутся из `loop_result` как есть — реальный
расход LLM не меняется от того, что его текст отбросили.)

6. В `_make_tool_executor` изменить сигнатуру внутренней функции (тело
   не меняется — она и так просто прокидывает `tool.execute(...)`, чей
   тип теперь `ToolExecutionResult` после Task 5):

```python
    async def executor(name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
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
```

- [ ] **Step 8: Прогнать — GREEN**

Run: `cd services/worker && python -m pytest tests/pipeline/test_reply_tools.py tests/pipeline/test_tool_loop.py -v`
Expected: PASS (все тесты обоих файлов).

- [ ] **Step 9: Прогнать полный пакет `services/worker` + mypy strict**

Run: `cd services/worker && python -m pytest -v`
Expected: PASS (регрессии нет — тесты без тулз и без override продолжают
отправлять `loop_result.text` как раньше).

Run: `cd services/worker && mypy --strict src`
Expected: 0 ошибок.

- [ ] **Step 10: Commit**

```bash
git add services/worker/src/worker/pipeline/tool_loop.py services/worker/tests/pipeline/test_tool_loop.py services/worker/src/worker/pipeline/consumer.py services/worker/tests/pipeline/test_reply_tools.py
git commit -m "feat(worker): send product card (photos+text) instead of LLM text on tool override"
```

---

## Task 7: Живой прогон

**Files:** нет изменений кода — только проверка на реальном стенде.

- [ ] **Step 1: Пересобрать и поднять стенд**

```bash
docker compose -f compose/docker-compose.dev.yml up --build -d
```

- [ ] **Step 2: Накатить миграции**

Run (по правилу Windows/Docker из памяти проекта — через контейнер, не с
хоста):

```bash
docker compose -f compose/docker-compose.dev.yml exec api python -m alembic -c /app/libs/db/alembic.ini upgrade head
```

Убедиться, что `product_images` появилась в списке таблиц (например,
`docker compose ... exec postgres psql -U postgres -d platform -c '\dt'`).

- [ ] **Step 3: Проверить сборку `services/gateway`**

Run: `docker compose -f compose/docker-compose.dev.yml build --no-cache gateway`
Expected: успешная сборка (проверка на регресс типа "забыли добавить
зависимость в Dockerfile" — в этой задаче gateway новых npm-пакетов не
получает, но собрать всё равно нужно, раз менялся TS-код).

- [ ] **Step 4: Проверить сборку `services/api` и `services/worker`**

Run:
```bash
docker compose -f compose/docker-compose.dev.yml build --no-cache api worker
```
Expected: успешная сборка (по паттерну этой волны — `libs/tools`/`libs/db`
менялись, `libs/tools` уже стоит в обоих Dockerfile с прошлой итерации,
новых зависимостей пакет не набрал — но собрать всё равно нужно, чтобы
поймать регресс, если он есть).

- [ ] **Step 5: Ручной сквозной прогон**

1. Создать тестового бота с `system_prompt`, включить тулзу
   `search_products` (`tool_bindings`), добавить товар с 1-2 записями в
   `products`/`product_images` (реальный файл-картинка вручную кладётся в
   shared media volume — тот же приём, что уже применялся для inbound-медиа
   в прошлых итерациях, `storage_key` в БД указывает на него же).
2. Отправить боту сообщение, провоцирующее поиск товара по имени.
3. Проверить логи worker/gateway: тулза находит товар, `_reply()` уходит в
   ветку `override_reply_text`, gateway получает `outbound.image` +
   `outbound.text`, читает байты из `Storage.get()`, шлёт через
   `sendImage`.
4. Без `OPENAI_API_KEY` (как и в прошлых итерациях) — деградация ожидаема
   на этапе первого вызова `complete_with_tools`, до генерации ответа;
   специфического для этой фичи пути без ключа не проверить, как и раньше.
   При наличии ключа — убедиться, что реального текста LLM в `wa:out` нет,
   только карточка.

- [ ] **Step 6: Обновить память проекта**

Обновить/создать памятку в
`C:\Users\user\.claude\projects\C--Work-Projects-whatsapp-bot\memory\`
(например `wave2-product-card-progress.md`) с итогом итерации 4.3/4.4:
что сдано, какие находки были, что осталось на 4.5/4.6 (настройки вывода
карточки), и добавить строку в `MEMORY.md`.

---

---

## Task 8: Джиттер между фото + карточки всех найденных товаров (пост-финальный ревью)

**Контекст**: финальный whole-branch ревью (после Task 1-7) нашёл два
расхождения с эталоном V1, не входившие в список исключений, одобренных
пользователем в начале итерации:

1. FEATURES.md 4.3 называет задержку 1000–1500 мс между отправляемыми
   медиа (анти-бан, эталон V1) — в реализации Task 6 её не было вообще.
2. Если LLM находит два товара за один ход (`search_products` вызван
   дважды), `tool_loop.py`'s "последний выигрывает" отправлял клиенту
   ТОЛЬКО карточку последнего товара — карточка первого (фото+текст)
   молча терялась, и текст LLM тоже не уходил.

Пользователь подтвердил оба фикса: добавить джиттер, отправлять карточки
ВСЕХ найденных товаров по очереди (не суммировать в одну, не терять
более ранние).

**Files:**
- Modify: `services/worker/src/worker/pipeline/tool_loop.py`
- Modify: `services/worker/tests/pipeline/test_tool_loop.py`
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Modify: `services/worker/tests/pipeline/test_reply_tools.py`

**Interfaces:**
- Produces: `OverrideReply(text: str, media: Sequence[MediaToSend] = ())` —
  новый dataclass в `tool_loop.py`. `ToolLoopResult.override_replies:
  Sequence[OverrideReply] = ()` заменяет прежние
  `override_reply_text`/`media` (одно значение → список, накапливается,
  не перезаписывается). `tools/base.py`/`ProductSearchTool` (Task 5) **не
  меняются** — один вызов тулзы по-прежнему возвращает один
  `ToolExecutionResult`; накопление нескольких карточек в ходе — забота
  `tool_loop.py`, не тулзы.

- [ ] **Step 1: Обновить `test_tool_loop.py`**

Импорт `OverrideReply` добавить в блок импортов из `worker.pipeline.tool_loop`:
```python
from worker.pipeline.tool_loop import OverrideReply, ToolLoopResult, run_tool_loop
```

В `test_single_round_returns_text_when_no_tool_calls_requested` заменить
хвост теста:
```python
    assert result.text == "готовый ответ"
    assert result.tokens_in == 20
    assert result.tokens_out == 8
    assert result.override_replies == ()
```

В `test_tool_result_with_override_reply_text_propagates_to_loop_result`
заменить последние 3 строки (`assert result.text ==`, `override_reply_text`, `media`):
```python
    assert result.text == "текст LLM, будет отброшен"
    assert len(result.override_replies) == 1
    assert result.override_replies[0].text == "*Nike Air*\nЦена: 5000"
    assert list(result.override_replies[0].media) == [
        MediaToSend(storage_key="img-1", mime_type="image/jpeg")
    ]
```

Добавить новый тест в конец файла:
```python
async def test_two_tool_calls_in_one_round_both_produce_cards_in_order() -> None:
    """FEATURES.md 4.3/4.4: LLM находит два товара за один ход (два
    tool_calls в одном раунде) — обе карточки сохраняются по порядку,
    ни одна не теряется ("последний выигрывает" терял более раннюю —
    находка финального ревью)."""

    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="m",
                tool_calls=[
                    ToolCall(id="call_1", name="search", arguments_json='{"q": "nike"}'),
                    ToolCall(id="call_2", name="search", arguments_json='{"q": "adidas"}'),
                ],
            )
        return LLMResult(text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="m")

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        query = arguments["q"]
        return ToolExecutionResult(
            content=f'[{{"name": "{query}"}}]',
            override_reply_text=f"*{query}*",
            media=[MediaToSend(storage_key=f"img-{query}", mime_type="image/jpeg")],
        )

    result = await run_tool_loop(
        "SYS", [], [_SPEC], executor, complete_with_tools_fn=complete_with_tools_fn
    )

    assert len(result.override_replies) == 2
    assert result.override_replies[0].text == "*nike*"
    assert result.override_replies[1].text == "*adidas*"
```

This test needs `ToolExecutionResult`/`MediaToSend` imports, already present
from Task 6's edit to this file (`from tools.base import MediaToSend,
ToolExecutionResult`).

- [ ] **Step 2: Запустить — RED**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_tool_loop.py -v`
Expected: FAIL — `ToolLoopResult`/`run_tool_loop` ещё не знают про
`override_replies`/`OverrideReply`.

- [ ] **Step 3: Обновить `tool_loop.py`**

Заменить дословно строки 45-119 (от `@dataclass(frozen=True)\nclass
ToolLoopResult:` до конца `run_tool_loop`) на:

```python
@dataclass(frozen=True)
class OverrideReply:
    """Одна карточка товара — текст + её фото, готовые к отправке клиенту
    ВМЕСТО ответа LLM (FEATURES.md 4.3/4.4). Несколько тулз-вызовов в
    одном ходе (клиент спросил про несколько товаров сразу) — несколько
    OverrideReply по порядку, ни один не перезаписывает другой (находка
    финального ревью: прежнее "последний выигрывает" молча теряло более
    ранние товары)."""

    text: str
    media: Sequence[MediaToSend] = ()


@dataclass(frozen=True)
class ToolLoopResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    # Каждый tool-call в этом ходе, вернувший override, добавляет сюда
    # свою карточку — порядок сохраняется, ни одна не теряется, даже если
    # LLM спросила про несколько товаров за один раунд.
    override_replies: Sequence[OverrideReply] = ()


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
            text=result.text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            model=result.model,
        )

    exchange: list[ToolExchangeTurn] = []
    tokens_in_total = 0
    tokens_out_total = 0
    model_name = ""
    override_replies: list[OverrideReply] = []

    for _ in range(max_rounds):
        result = await complete_with_tools_fn(system_prompt, history, tools, exchange)
        tokens_in_total += result.tokens_in
        tokens_out_total += result.tokens_out
        model_name = result.model

        if not result.tool_calls:
            return ToolLoopResult(
                text=result.text,
                tokens_in=tokens_in_total,
                tokens_out=tokens_out_total,
                model=model_name,
                override_replies=tuple(override_replies),
            )

        exchange.append(AssistantToolCallsTurn(result.tool_calls))
        for call in result.tool_calls:
            tool_result = await _run_one_tool(call, executor)
            exchange.append(ToolResultTurn(call.id, call.name, tool_result.content))
            if tool_result.override_reply_text is not None:
                override_replies.append(
                    OverrideReply(text=tool_result.override_reply_text, media=tool_result.media)
                )

    logger.warning("tool loop reached max_rounds, forcing final text answer", max_rounds=max_rounds)
    result = await complete_with_tools_fn(system_prompt, history, tools, exchange, force_text=True)
    tokens_in_total += result.tokens_in
    tokens_out_total += result.tokens_out
    return ToolLoopResult(
        text=result.text,
        tokens_in=tokens_in_total,
        tokens_out=tokens_out_total,
        model=result.model,
        override_replies=tuple(override_replies),
    )
```

`_run_one_tool` (below this in the same file) is unchanged.

- [ ] **Step 4: Запустить — GREEN**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_tool_loop.py -v`
Expected: PASS (8 тестов).

- [ ] **Step 5: Обновить `consumer.py`**

1. В блоке импортов добавить `import random` между `import asyncio` и
   `import uuid` (алфавитный порядок plain-import среди уже
   существующих):
```python
import asyncio
import random
import uuid
```

2. Заменить строку `from .tool_loop import ToolExecutor, run_tool_loop` на:
```python
from .tool_loop import OverrideReply, ToolExecutor, run_tool_loop
```

3. Добавить константы рядом с `STORAGE_READ_TIMEOUT_SECONDS` (после
   `DEFAULT_AUTO_RELEASE_MINUTES = 12`):
```python
# Эталон V1 (FEATURES.md 4.3) — джиттер между отправляемыми медиа,
# анти-бан дисциплина (CLAUDE.md §7): не пачка фото залпом.
PHOTO_JITTER_MIN_SECONDS = 1.0
PHOTO_JITTER_MAX_SECONDS = 1.5
```

4. Заменить функцию `_send_card` (текущие строки 258-281) целиком на:
```python
async def _send_cards(
    event: InboundText, redis: Redis, replies: Sequence[OverrideReply]
) -> None:
    """FEATURES.md 4.3/4.4: карточки товара — typing один раз, затем для
    каждой найденной карточки её фото и текст, по порядку. Джиттер
    1000-1500 мс перед КАЖДЫМ фото, кроме самого первого в этом ходе
    (включая между карточками разных товаров) — эталон V1, анти-бан
    дисциплина. client_msg_id — новый .hex на КАЖДОЕ исходящее событие,
    как и в _send_reply."""
    typing_event = OutboundTyping(
        bot_id=event.bot_id, chat_id=event.chat_id, client_msg_id=uuid.uuid4().hex
    )
    await publish(redis, OUT_STREAM, typing_event.model_dump(mode="json"))

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
            bot_id=event.bot_id, chat_id=event.chat_id, text=reply.text, client_msg_id=uuid.uuid4().hex
        )
        await publish(redis, OUT_STREAM, text_event.model_dump(mode="json"))
```

5. В `_reply()` заменить блок:
```python
    if loop_result.override_reply_text is not None:
        # FEATURES.md 4.3/4.4: тулза нашла товар — клиенту уходит ТОЛЬКО
        # карточка, собственный текст LLM в этом ходе отбрасывается
        # (подтверждено пользователем, эталон V1).
        reply_text = loop_result.override_reply_text
        await _send_card(event, redis, reply_text, loop_result.media)
    else:
```
на:
```python
    if loop_result.override_replies:
        # FEATURES.md 4.3/4.4: тулза(ы) нашли товар(ы) — клиенту уходят
        # ТОЛЬКО карточки, собственный текст LLM в этом ходе отбрасывается
        # (подтверждено пользователем, эталон V1). Несколько товаров в
        # одном ходе — несколько карточек по очереди, ни одна не теряется
        # (находка финального ревью — прежнее "последний выигрывает"
        # молча теряло более ранние товары).
        reply_text = "\n\n".join(reply.text for reply in loop_result.override_replies)
        await _send_cards(event, redis, loop_result.override_replies)
    else:
```

- [ ] **Step 6: Обновить `test_reply_tools.py` — добавить тест на несколько товаров с джиттером**

Добавить в конец файла:
```python


async def test_multiple_products_in_one_turn_send_all_cards_with_jitter_between_photos(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.3/4.4: LLM находит два товара за один ход — уходят
    ОБЕ карточки по очереди (найденная ранее не молча теряется), с
    джиттером между фото (эталон V1, анти-бан) — джиттер подменён на 0,
    чтобы тест не ждал реальные 1-1.5с."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeMultiCardTool:
        name = "search"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}
        calls = 0

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            type(self).calls += 1
            n = type(self).calls
            return ToolExecutionResult(
                content=f'[{{"name": "Товар {n}"}}]',
                override_reply_text=f"*Товар {n}*",
                media=[MediaToSend(storage_key=f"img-{n}.jpg", mime_type="image/jpeg")],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "search", _FakeMultiCardTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[
                    ToolCall(id="call_1", name="search", arguments_json="{}"),
                    ToolCall(id="call_2", name="search", arguments_json="{}"),
                ],
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
        await enable_tool_binding(session, bot_id, "search", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, image1, text1, image2, text2
        assert len(out_entries) == 5
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.image"
        assert payloads[1]["storage_key"] == "img-1.jpg"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "*Товар 1*"
        assert payloads[3]["type"] == "outbound.image"
        assert payloads[3]["storage_key"] == "img-2.jpg"
        assert payloads[4]["type"] == "outbound.text"
        assert payloads[4]["text"] == "*Товар 2*"
        assert not any("текст LLM" in p.get("text", "") for p in payloads)
    finally:
        await redis.aclose()
```

- [ ] **Step 7: Запустить — RED, затем GREEN**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest tests/pipeline/test_reply_tools.py tests/pipeline/test_tool_loop.py -v`
Expected: RED first (before Step 5's consumer.py edit lands — if applying
steps in strict order, this file's new test fails because `_send_card`/
`override_reply_text` no longer match); PASS after Step 5's edits (12
tests: existing 11 + this new one).

- [ ] **Step 8: Полный прогон + линт**

Run: `cd services/worker && ../../.venv/Scripts/python.exe -m pytest -v`
Run: `../../.venv/Scripts/python.exe -m mypy --strict src` (from
`services/worker`, or `.venv/Scripts/python.exe -m mypy --strict
services/worker/src` from repo root)
Run (from repo root): `.venv/Scripts/python.exe -m ruff check .`
Expected: all green/clean.

- [ ] **Step 9: Commit**

```bash
git add services/worker/src/worker/pipeline/tool_loop.py services/worker/tests/pipeline/test_tool_loop.py services/worker/src/worker/pipeline/consumer.py services/worker/tests/pipeline/test_reply_tools.py
git commit -m "feat(worker): send all found products' cards with jitter between photos"
```

## Самопроверка плана (для исполнителя перед стартом)

- **Покрытие спеки**: контракт (Task 1) → Storage.get (Task 2) →
  sendImage/consumer (Task 3) → product_images (Task 4) → Tool Protocol +
  ProductSearchTool (Task 5) → tool_loop/consumer wiring (Task 6) → живой
  прогон (Task 7). Все разделы спеки `2026-09-05-product-card-sending-design.md`
  покрыты, включая "Границы этой итерации" (ничего из списка не
  реализуется).
- **Плейсхолдеров нет**: каждый шаг содержит полный код файла или точную
  вставку/замену с указанием, что менять.
- **Согласованность типов**: `ToolExecutionResult(content, override_reply_text=None, media=())`
  и `MediaToSend(storage_key, mime_type)` определены один раз в Task 5
  (`tools/base.py`) и используются с теми же именами полей везде далее
  (Task 6 `tool_loop.py`/`consumer.py`, тесты). `OutboundImage(bot_id, chat_id, storage_key, mime_type, client_msg_id)`
  определён один раз в Task 1 и используется с теми же именами в Task 3
  (TS) и Task 6 (`_send_card`).
