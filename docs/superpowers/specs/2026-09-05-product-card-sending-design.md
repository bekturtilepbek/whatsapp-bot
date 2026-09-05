# Отправка карточки товара — фото + текст (FEATURES.md 4.3/4.4)

**Статус:** утверждено пользователем 2026-09-05
**Волна:** 2, итерация 4 из 6 (после инфраструктуры тулз, 3.4 каталог,
4.1/4.2 поиск; следующие — 4.5/4.6 настройки вывода, 4.7 telegram-лиды,
4.8/4.9 файлы/видео)

## Контекст

4.1/4.2 (прошлая итерация) дали первую тулзу — поиск товара, результат
уходит в LLM как JSON-текст. Эта итерация — реальная ОТПРАВКА найденного
товара клиенту: фото (одно или несколько) + текстовая карточка, точно как
в архиве V1 (`node-bot3/whatsapp.js`, строки ~980–1025).

**4.3 и 4.4 объединены сознательно**: в архиве это один и тот же код
(`for (i=0; i<mediaArray.length; i++)`), который одинаково работает и для
одного фото, и для нескольких — искусственный сплит на "только 1 фото"
только ради нумерации FEATURES.md добавил бы работу без пользы.

**Найденное расхождение с FEATURES.md, разрешённое пользователем**:
FEATURES.md 4.3 упоминает "ретраи с backoff" и "ресайз через sharp до
~1280px" — ни того, ни другого нет в архиве. Пользователь подтвердил:
**не добавлять в этой итерации**. Ретраи с backoff для исходящих —
отдельный, уже задокументированный технический долг `services/gateway`
(`outbound/consumer.ts`: "ретраи с backoff — Волна 1, вне скоупа Блока
1" — общий для text/typing/media, не специфичный для карточек, чинить
отдельной задачей). Ресайз — некуда встраивать: загрузки изображений
(Wave 3, CRUD 6.8) ещё нет, встраивать ресайз в SEND-путь означало бы
пересчитывать один и тот же файл при каждой отправке — правильное место
для этого появится вместе с upload-эндпоинтом.

**Подтверждённое пользователем поведение** (эталон V1): если товар
найден — клиенту уходит ТОЛЬКО структурированная карточка (фото + текст
из полей товара), собственный свободный текстовый ответ LLM в этом ходе
**не отправляется вообще** (не "и то, и то" — во избежание дублирующих/
противоречивых сообщений). Заметка на будущее (не в этой итерации): в
`bots.settings` может появиться переключатель "отвечать ли LLM вдобавок
к карточке" — сейчас жёстко "нет".

## Разделение по слоям

Это первая итерация, которая реально трогает `services/gateway` (TS) с
тех пор, как появился weiter tool-calling — исходящие медиа не
существовали в контракте вообще.

- **`docs/contracts/events.schema.json`** — новый `outbound.image`.
- **`services/gateway`** — `Storage.get()` (симметрично уже существующему
  `put()`), `SessionManager.sendImage()`, `OutboundConsumer` обрабатывает
  `outbound.image`.
- **`libs/db`** — новая таблица `product_images` + запрос.
- **`libs/tools`** — `Tool.execute()` возвращает структурированный
  результат (не голую строку) — новая возможность "тулза решает, что
  реально отправить клиенту вместо ответа LLM". Заодно чинится
  находка прошлого финального ревью (`parameters_schema` как `@property`
  в Protocol вместо plain-атрибута — снимает несовместимость с
  `ClassVar` под mypy strict, было решено чинить именно в следующей
  итерации, добавляющей что-то в `tools/base.py`).
- **`services/worker`** — `tool_loop.py` прокидывает новые поля наверх,
  `consumer.py::_reply()` решает, что реально отправить.

## `docs/contracts/events.schema.json` + модели

Новое определение `outboundImage`:

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
}
```

Добавить в `oneOf`. Зеркально — `libs/core/src/core/events.py`
(`OutboundImage(BaseModel)`) и `services/gateway/src/contracts/events.ts`
(`OutboundImage` zod-схема), `Event` union в обоих местах расширяется.

**Почему не общий `outbound.media`** (на будущее 4.8/4.9 — файлы/видео):
у документов/видео своя семантика (имя файла, другие поля Baileys-API) —
узкий тип сейчас, отдельные типы позже, тот же принцип, что и с узкими
миграциями. Не унифицировать заранее.

## `services/gateway` — чтение из Storage + отправка

`services/gateway/src/storage/types.ts` — добавить в интерфейс:

```typescript
export interface Storage {
  put(key: string, bytes: Buffer, mimeType: string): Promise<void>;
  get(key: string): Promise<Buffer>;
}
```

`FilesystemStorage.get()` — та же защита от path traversal, что уже есть
в `put()` (resolve + startsWith-с-разделителем), симметричный `readFile`.
`S3Storage.get()` — `GetObjectCommand` + сборка потока в `Buffer`
(симметрично уже существующему `PutObjectCommand`).

`SessionManager` (`services/gateway/src/session/manager.ts`) — новый
метод рядом с `sendText`/`sendTyping`:

```typescript
async sendImage(
  botId: string, chatId: string, image: Buffer, mimeType: string, clientMsgId: string,
): Promise<void> {
  await this.activeSocket(botId).sendMessage(
    chatId, { image, mimetype: mimeType }, { messageId: clientMsgId },
  );
}
```

`messageId: clientMsgId` — та же связка с handoff-echo-детектом
(`wa:sent:{client_msg_id}`), что и у `sendText` — ничего специального
чинить не нужно, идемпотентность/echo уже работают по этому ключу
одинаково для любого типа исходящего.

`OutboundConsumer` (`services/gateway/src/outbound/consumer.ts`):
- конструктор получает `storage: Storage` четвёртым параметром;
- `processEntry`/`handleOutbound` — добавить ветку `outbound.image`:
  идемпотентность (`wa:sent:{client_msg_id}`, тот же `SET NX`, что уже
  есть) → `storage.get(event.storage_key)` → `sessions.sendImage(...)`
  под тем же `withTimeout(..., SEND_TIMEOUT_MS, "sendImage")`, что и
  текст. Сбой — лог + ACK, без ретраев (тот же принцип, что уже
  документирован в файле для text/typing — ретраи не добавляем).

`main.ts` — `new OutboundConsumer(redis, sessions, app.log, storage)`
(`storage` уже создаётся там же строкой раньше, просто не была
прокинута).

## `libs/db` — `product_images`

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

`libs/db/src/db/product_images.py`:

```python
async def list_product_images(session: AsyncSession, product_id: uuid.UUID) -> list[ProductImage]:
    stmt = (
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

## `libs/tools` — расширение контракта тулзы

### Фикс Protocol (закрывает находку прошлого финального ревью)

`libs/tools/src/tools/base.py` — `parameters_schema` становится
read-only property в Protocol (принимает и `ClassVar`, и обычный
атрибут — проверено предыдущим ревью):

```python
class Tool(Protocol):
    name: str
    description: str

    @property
    def parameters_schema(self) -> dict[str, Any]: ...

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult: ...
```

### Новый структурированный результат

```python
@dataclass(frozen=True)
class MediaToSend:
    storage_key: str
    mime_type: str


@dataclass(frozen=True)
class ToolExecutionResult:
    content: str  # как раньше — уходит в LLM как результат tool call
    override_reply_text: str | None = None  # если задано — уходит клиенту
    # ВМЕСТО ответа LLM (FEATURES.md 4.3/4.4); None — поведение как раньше
    media: Sequence[MediaToSend] = ()  # фото, отправляются раньше override_reply_text
```

Тулзы, которым новая возможность не нужна (будущие 4.7 и т.д.), просто
возвращают `ToolExecutionResult(content=результат)` — не сложнее, чем
раньше вернуть голую строку.

`ToolContext` **не меняется** — тулза не публикует события сама, только
возвращает данные; кто реально шлёт — `_reply()` (у него уже есть
`chat_id`/`redis`/`OUT_STREAM`), ADR-002 (worker — оркестрация) от этого
не страдает.

### `ProductSearchTool` — обновление

Убрать `# noqa: RUF012`, вернуть естественный `ClassVar` (Protocol
теперь принимает). При найденном товаре — дополнительно тянуть его фото
(`list_product_images`) и собирать текст карточки:

```python
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
```

Session-lifetime — тот же урок, что уже чинили в 4.1/4.2 (не держать
сессию БД открытой во время сетевого вызова OpenAI): поиск фото для
найденного товара делается СРАЗУ после того, как товар найден, в ТОЙ ЖЕ
сессии/ветке (exact-match или vector), НЕ в отдельном третьем открытии
сессии после `generate_embedding` — эта функция и так уже открывает
сессию дважды (exact-match, затем vector), просто в векторной ветке
после `find_product_by_embedding` в той же сессии добавляется вызов
`list_product_images`, а не после закрытия.

`execute()` при найденном товаре возвращает `ToolExecutionResult(content=...,
override_reply_text=_format_card_text(...), media=[MediaToSend(storage_key=i.storage_key,
mime_type=i.mime_type) for i in images])`. Не найдено — как раньше,
`ToolExecutionResult(content="[]")` (`override_reply_text`/`media` —
дефолты, ничего не меняется в поведении "не нашли").

## `services/worker` — прокидка и реальная отправка

`tool_loop.py`:
- `_run_one_tool` теперь получает `ToolExecutionResult` от
  `executor(...)` вместо строки — в `ToolResultTurn.content` идёт
  `.content` (как раньше был весь возврат).
- `ToolLoopResult` получает два новых поля: `override_reply_text: str |
  None = None`, `media: Sequence[MediaToSend] = ()` — после каждого
  раунда, если у результата `execute()` есть `override_reply_text`,
  он (и `media`) перезаписывают текущее значение в `ToolLoopResult`
  (не суммируются — только последний найденный товар в ходе актуален).

`consumer.py::_reply()` — после `run_tool_loop`:
- если `loop_result.override_reply_text is not None`: typing → отправить
  каждый `MediaToSend` (`OutboundImage`, новый `client_msg_id` на
  каждое) → отправить `override_reply_text` (`OutboundText`) → **не**
  отправлять `loop_result.text`; в `messages`/`usage_events` записывать
  `override_reply_text` как содержимое исходящего сообщения (что реально
  ушло клиенту), но `tokens_in/out/cost` — из `loop_result` как есть
  (реальный расход LLM не меняется от того, что его текст отбросили).
- если `override_reply_text is None` — всё как раньше, без изменений.

Изображения в `messages.media_ref` **не отражаются** в этой итерации
(только текст карточки идёт в историю) — просмотр прикреплённых
исходящих медиа осмысленен только с кабинетом (Волна 3, 6.14), не
делаем эту работу впустую сейчас.

## Тесты

- `services/gateway`: `Storage.get()` (fs + s3, включая path traversal
  guard на fs), `SessionManager.sendImage()`, `OutboundConsumer` —
  обрабатывает `outbound.image` (идемпотентность, реальный вызов
  `sendImage` с байтами из storage, таймаут).
- `libs/db`: `list_product_images` — порядок по `position`, скоуп per
  product, пусто по умолчанию.
- `libs/tools`: `Tool` Protocol принимает и `ClassVar`, и property-формы
  (mypy strict, тем же способом, каким прошлый ревью проверял); `ProductSearchTool`
  — найденный товар с фото возвращает `override_reply_text`+`media`,
  без фото — `override_reply_text` без `media` (карточка всё равно есть,
  просто без фото), не найдено — `ToolExecutionResult(content="[]")` без
  override.
- `services/worker`: `tool_loop.py` прокидывает `override_reply_text`/
  `media` через `ToolLoopResult`; `_reply()` — при override отправляет
  media+text, не отправляет `loop_result.text`, история/usage пишутся
  корректно; без override — поведение как в прошлых итерациях (регрессия).
- Живой прогон: миграция `product_images`, реальный файл-изображение
  вручную кладётся в shared media volume (тот же приём, что и раньше для
  inbound-медиа в тестах), строка `product_images` вручную через SQL,
  тулза находит товар и (при доступном `OPENAI_API_KEY` — которого нет
  на машине разработки) реально прислала бы фото+карточку; без ключа —
  деградация на том же месте, что и раньше (после наступления тулзы,
  до генерации итогового текста) — специфического для этой фичи пути
  без ключа не проверить, как и раньше.

## Границы этой итерации

Не входит: настройки вывода (4.5/4.6 — глобальные и per-product
переключатели show_name/show_description/show_price, `display_custom`
остаётся неиспользуемым столбцом до той итерации), загрузка изображений
(Wave 3, 6.8), ресайз изображений, ретраи с backoff в gateway (отдельный
технический долг, вне этой фичи), отражение исходящих медиа в истории
диалога.
