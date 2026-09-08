# Отправка файлов и видео (FEATURES.md 4.8/4.9)

**Статус:** утверждено пользователем 2026-09-08
**Волна:** 2, итерация 7 из 7 — последняя в Волне 2 (после 4.13, 3.4,
4.1/4.2, 4.3/4.4, 4.5/4.6, 4.7)

## Контекст

Третья настоящая тулза платформы (после `search_products` и
`send_telegram_lead`). Клиент просит прайс-лист/договор/видео — LLM
вызывает `send_document(file_name)`, тулза находит файл по имени в
таблице `documents`, отправляет байты через `Storage.get()` (уже есть
из 4.3/4.4), клиенту уходит документ или видео (нативный плеер).

**Архив** (`node-bot3/whatsapp.js`, `sendDocument`, строки ~347-392,
915-953): читает файл **с локального диска** по пути
`static/docs/{botId}/{fileName}` — LLM передаёт точное имя файла как
аргумент tool call, значит промпт бота должен был заранее ЗНАТЬ список
файлов (в архиве это зашито вручную владельцем бота в системный промпт
текстом — программной передачи списка в контекст нет вообще, грепнул
весь файл — ничего похожего на `getDocumentsContext` не нашлось).
MIME-тип определяется по расширению файла вручную (switch). Отправка —
`sendMediaAsDocument: true`. **Отдельного пути для видео в архиве нет
вообще** — `SUPPORTED_MEDIA_TYPES` включает video/* только для ВХОДЯЩИХ
типов; `sendDocument` — единственная исходящая функция для файлов любого
рода, случай видео не выделен.

**Ключевая находка, подтверждающая архитектуру этой спеки**: в архиве
`isFileSent` (строка 827, 923) работает ТОЧНО как override у карточки
товара — если файл отправлен, финальный текст LLM подавляется целиком
(строка 1026-1029: `"Текстовое сообщение заблокировано, так как клиент
уже получил PDF-документ"`). Один и тот же принцип и для товаров, и для
файлов — подтверждает решение пользователя переиспользовать существующий
`override_reply_text` без изменения контракта тулз.

**Решения пользователя**:
1. Список файлов — в system prompt (платформенное улучшение сверх V1,
   аналогично каталогу товаров 3.4) — тулза ищет `Document` в БД по
   точному имени, не читает с диска.
2. Видео — нативное video-сообщение (свой Baileys-путь, плеер в чате),
   не как обычный документ.
3. Одна тулза `send_document` на оба случая (файл/видео) — LLM не
   должна думать заранее, что это. Тулза сама смотрит `mime_type`
   найденного документа и решает способ отправки.
4. Override-паттерн как у карточки товара, без изменения контракта
   тулз — LLM не комментирует в том же ходе, эталон V1 (`isFileSent`).

## Слои

- **`docs/contracts`** — два новых узких типа: `outboundDocument`,
  `outboundVideo` (принцип «не унифицировать заранее» — тот же, что у
  `outbound.image` в 4.3/4.4; документ несёт `filename`, видео — нет,
  разная семантика Baileys API).
- **`libs/db`** — новая таблица `documents` (уже описана в
  ARCHITECTURE.md §5, не создавалась) + `list_documents`.
- **`libs/llm`** — новый `documents_context.py`, симметричен
  `catalog_context.py`.
- **`services/gateway`** — `SessionManager.sendDocument()`/`sendVideo()`
  + `OutboundConsumer` — новые ветки, тот же паттерн, что `outbound.image`
  (storage.get() с таймаутом, dedup, sendX с таймаутом).
- **`libs/tools`** — `MediaToSend` получает необязательное поле
  `filename` (нужно только документам); новая тулза `send_document.py`.
- **`services/worker`** — `_reply()` подключает `documents_context` в
  system prompt; `_send_cards()` (существующая с 4.3/4.4/Task 8, шлёт
  карточки товара) научится диспетчеризовать по `mime_type` каждого
  `MediaToSend`: `image/*` → `outbound.image` (как сейчас, без
  изменений), `video/*` → `outbound.video`, всё остальное →
  `outbound.document`.

## `docs/contracts/events.schema.json` + модели

Новые определения (вставить после `outboundImage`, перед
`outboundTyping`):

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
}
```

Добавить в `oneOf`. Зеркально — `libs/core/src/core/events.py`
(`OutboundDocument`, `OutboundVideo`) и
`services/gateway/src/contracts/events.ts` (те же две zod-схемы), `Event`
union в обоих местах расширяется. Фикстуры
`docs/contracts/examples/outbound.document.json` и
`outbound.video.json` — уже существующие data-driven контрактные тесты
подхватят их без единой правки самих тестов (тот же паттерн, что у
`outbound.image`).

## `libs/db` — `documents`

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

`UNIQUE(bot_id, filename)` — точное совпадение имени должно однозначно
резолвиться в один файл (та же логика, что уникальность имени товара по
факту в 4.1/4.2, хоть там constraint не заведён на уровне БД).

`libs/db/src/db/documents.py`:

```python
async def list_documents(session: AsyncSession, bot_id: uuid.UUID) -> list[Document]:
    stmt = select(Document).where(Document.bot_id == bot_id).order_by(Document.filename)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_document_by_filename(
    session: AsyncSession, bot_id: uuid.UUID, filename: str
) -> Document | None:
    stmt = select(Document).where(Document.bot_id == bot_id, Document.filename == filename)
    result = await session.execute(stmt)
    return result.scalars().first()
```

Точное совпадение (`==`), не `LOWER(TRIM())` как у товаров (4.1/4.2) —
имена файлов регистрозависимы на уровне файловых систем/URL, в отличие
от разговорных названий товаров; LLM видит точное имя в
`documents_context` и должна передать его как есть.

## `libs/llm` — `documents_context.py`

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

## `services/gateway` — отправка

`SessionManager` — два новых метода рядом с `sendImage`:

```typescript
async sendDocument(
  botId: string, chatId: string, document: Buffer, mimeType: string,
  filename: string, clientMsgId: string,
): Promise<void> {
  await this.activeSocket(botId).sendMessage(
    chatId, { document, mimetype: mimeType, fileName: filename },
    { messageId: clientMsgId },
  );
}

async sendVideo(
  botId: string, chatId: string, video: Buffer, mimeType: string, clientMsgId: string,
): Promise<void> {
  await this.activeSocket(botId).sendMessage(
    chatId, { video, mimetype: mimeType },
    { messageId: clientMsgId },
  );
}
```

`OutboundConsumer` — `processEntry`/`handleOutbound` добавляют
`"outbound.document"`/`"outbound.video"` в проверяемый набор типов, та
же ветка `storage.get()` (с таймаутом) → `sendDocument`/`sendVideo` (с
таймаутом) → лог+ACK при сбое, без ретраев — идентичный паттерн
`outbound.image`, просто третья/четвёртая ветка `if/else if`.

## `libs/tools` — `MediaToSend` + `send_document.py`

`tools/base.py` — `MediaToSend` получает третье, необязательное поле
(нужно только документам, не фото/видео):

```python
@dataclass(frozen=True)
class MediaToSend:
    storage_key: str
    mime_type: str
    filename: str | None = None  # только для outbound.document (Baileys требует fileName)
```

`libs/tools/src/tools/send_document.py`:

```python
"""Отправка файла или видео клиенту (FEATURES.md 4.8/4.9) — эталон V1
(sendDocument), но файл ищется в БД по имени, не на диске (платформа
мультитенантная, файлы — в Storage). Одна тулза на оба случая — LLM не
думает заранее, файл это или видео, тулза сама смотрит mime_type."""

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

## `services/worker` — прокидка и диспетчеризация по mime_type

`consumer.py::_reply()` — добавить рядом с `products`:

```python
documents = await list_documents(session, bot.id)
...
docs_ctx = documents_context([DocumentInfo(filename=d.filename) for d in documents])
system_prompt = f"{bot.system_prompt}\n\n{catalog}\n\n{docs_ctx}\n\n{time_context(bot.timezone)}"
```

`_send_cards()` — заменить единственную ветку `OutboundImage` на
диспетчеризацию по `mime_type`:

```python
    sent_media = False
    for reply in replies:
        for item in reply.media:
            if sent_media:
                await asyncio.sleep(
                    random.uniform(PHOTO_JITTER_MIN_SECONDS, PHOTO_JITTER_MAX_SECONDS)
                )
            if item.mime_type.startswith("video/"):
                media_event: OutboundImage | OutboundVideo | OutboundDocument = OutboundVideo(
                    bot_id=event.bot_id, chat_id=event.chat_id,
                    storage_key=item.storage_key, mime_type=item.mime_type,
                    client_msg_id=uuid.uuid4().hex,
                )
            elif item.mime_type.startswith("image/"):
                media_event = OutboundImage(
                    bot_id=event.bot_id, chat_id=event.chat_id,
                    storage_key=item.storage_key, mime_type=item.mime_type,
                    client_msg_id=uuid.uuid4().hex,
                )
            else:
                media_event = OutboundDocument(
                    bot_id=event.bot_id, chat_id=event.chat_id,
                    storage_key=item.storage_key, mime_type=item.mime_type,
                    filename=item.filename or "file",
                    client_msg_id=uuid.uuid4().hex,
                )
            await publish(redis, OUT_STREAM, media_event.model_dump(mode="json"))
            sent_media = True
        ...
```

(Полный код — задача плана, здесь фиксируется факт диспетчеризации по
mime_type и что она подменяет прежнюю единственную image-ветку; текст
после медиа — без изменений, `OutboundText` как раньше.)

Реестр (`libs/tools/src/tools/registry.py`) — `register(SendDocumentTool())`.

## Границы этой итерации

Не входит: загрузка файлов ботом (Wave 3, 6.7 CRUD — на этой итерации
заполнение `documents` только вручную через SQL, тот же прецедент, что
`product_images`); превью/точное имя файла с эмодзи-иконкой (то, что
делал `fileTypeFromBuffer` в V1 для проверки реального MIME по
содержимому — у нас MIME хранится в БД при загрузке, доверяем ему, не
перепроверяем содержимое файла при каждой отправке); ретраи с backoff
(тот же техдолг, что и у `outbound.image`); ограничение размера
исходящего файла (зеркало FEATURES.md 1.9, тот же открытый пункт, что
уже отмечен для 4.3/4.4 — актуальным станет вместе с upload-эндпоинтом).

## Тесты

- `libs/core`/`services/gateway`: контрактные (data-driven, только
  фикстуры) для `outbound.document`/`outbound.video`.
- `services/gateway`: `sendDocument`/`sendVideo` (messageId=clientMsgId,
  правильные поля Baileys-вызова), `OutboundConsumer` — обе новые ветки
  (идемпотентность, storage.get() с таймаутом, sendX с таймаутом).
- `libs/db`: `list_documents` (сортировка по filename, скоуп per bot,
  пусто по умолчанию), `find_document_by_filename` (точное совпадение
  с учётом регистра, не найдено → None, скоуп per bot).
- `libs/tools`: `SendDocumentTool` — найден документ (mime_type
  document → media с filename, override_reply_text), найдено видео
  (mime_type video/* → media без обязательного использования filename,
  override_reply_text), не найден (текст ошибки, media=(), override=None),
  пустое имя файла (не идёт в БД вообще).
- `services/worker`: `_send_cards()` — диспетчеризация по mime_type
  (image/video/document каждый уходит своим типом события), джиттер
  между медиа работает одинаково для всех типов (регрессия — уже
  протестировано для image в Task 8 прошлой итерации, здесь — что
  video/document тоже его получают).
- Живой прогон: миграция `documents`, реальный файл вручную в shared
  media volume (тот же приём, что и для `product_images`), строка в
  `documents` вручную через SQL, тулза находит файл и (при доступном
  `OPENAI_API_KEY`, которого нет на машине разработки) реально
  отправила бы; без ключа — деградация ожидаема на том же месте, что и
  раньше.
