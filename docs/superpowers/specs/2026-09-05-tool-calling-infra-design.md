# Инфраструктура тулзов + реестр per bot (FEATURES.md 4.13)

**Статус:** утверждено пользователем 2026-09-05
**Волна:** 2, итерация 1 из 6 (порядок: инфраструктура → 3.4 каталог → 4.1/4.2 поиск →
4.3–4.6 карточки → 4.7 telegram-лиды → 4.8/4.9 файлы/видео)

## Контекст

Ни одна фича Волны 2 не может быть реализована без механизма вызова функций
LLM — сейчас `libs/llm` умеет только генерировать текст (`complete()`,
`complete_with_image()`), в `services/worker` нет цикла LLM↔tool-calls, в БД
нет `tool_bindings`, `libs/tools/` как директории не существует.

**Объём этой итерации — только механизм**, без единой настоящей тулзы:
- цикл LLM↔tool-calls в `libs/llm` + `services/worker`
- таблица `tool_bindings` (bot_id, tool_name, config) + API
- интерфейс тулзы и пустой реестр в новом `libs/tools/`
- встраивание цикла в основной текстовый путь `_reply()` (при пустом списке
  тулз — поведение бит-в-бит как сейчас)

Первая настоящая тулза (pgvector-поиск товара, FEATURES.md 4.1) — следующая
итерация; UI для включения тулз в кабинете — Волна 3.

**Ограничение среды**, зафиксированное ещё в Волне 1 (vision/PDF/LLM-ретраи):
на машине разработки не настроен `OPENAI_API_KEY` — живой прогон реального
tool-calling через настоящий OpenAI в этой итерации недостижим вне
зависимости от выбора первой тулзы. Живая проверка ограничена тем же, чем
и раньше: контейнеры поднимаются healthy, миграция применяется, обычный
текстовый диалог отвечает как прежде (деградация на отсутствующий ключ),
новый API-эндпоинт работает.

## Разделение ответственности (ADR-002)

- **`libs/llm`** — только механика вызова OpenAI: как выглядит `tools=[...]`
  в запросе, как распарсить `tool_calls` из ответа. Не знает о Postgres/
  Redis/тулзах бизнес-логики — один вызов = один HTTP-запрос, без цикла
  внутри.
- **`services/worker`** — сам цикл (бизнес-оркестрация, ADR-002 "worker:
  пайплайн + LLM+тулзы"): дёргает LLM, при `tool_calls` — исполняет через
  `libs/tools`, отдаёт результат обратно в LLM, повторяет до финального
  текста или лимита раундов.
- **`libs/tools`** — интерфейс тулзы (`Tool` protocol) + реестр
  (`get_tool(name)`), реализации отдельных тулз — по мере итераций Волны 2.

## `libs/llm` — `complete_with_tools()`

Новая функция рядом с `complete()`/`complete_with_image()` в
`libs/llm/src/llm/client.py`, тот же узкий интерфейс пакета.

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]  # JSON schema тела function


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    tool_calls: list[ToolCall] | None = None  # новое поле, обратная совместимость
```

Новые типы для передачи уже случившихся в текущем раунде реплик обратно
в модель (не путать с `HistoryMessage` — это персистентная история из БД,
`ToolExchangeTurn` — эфемерные реплики только внутри одного вызова
`run_tool_loop`):

```python
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

```python
async def complete_with_tools(
    system_prompt: str,
    history: list[HistoryMessage],
    tools: list[ToolSpec],
    exchange: list[ToolExchangeTurn] = (),
    *,
    force_text: bool = False,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult: ...
```

- Собирает `messages` так же, как `complete()`, плюс `exchange`, переведённый
  в OpenAI-формат (`assistant` с `tool_calls`, `tool` с `tool_call_id`).
- `tools` переводятся в `{"type": "function", "function": {"name", "description", "parameters"}}`.
- `tool_choice="auto"`, если не `force_text`, иначе `tool_choice="none"`
  (форсирует текстовый ответ моделью на основе уже собранных в `exchange`
  результатов, а не обрыв диалога).
- Если `response.choices[0].finish_reason == "tool_calls"` — `LLMResult.text=""`,
  `tool_calls` заполнен; иначе `tool_calls=None`, `text` как обычно.
- Ретраи/таймаут — переиспользуют существующий `_call_and_extract` (общий
  для `complete`/`complete_with_image`/`complete_with_tools`).

## `services/worker` — `pipeline/tool_loop.py`

```python
@dataclass(frozen=True)
class ToolLoopResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]

MAX_TOOL_ROUNDS = 5
TOOL_CALL_TIMEOUT_SECONDS = 20.0


async def run_tool_loop(
    system_prompt: str,
    history: list[HistoryMessage],
    tools: list[ToolSpec],
    executor: ToolExecutor,
    *,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> ToolLoopResult: ...
```

Поведение:
1. Если `tools` пуст — один вызов `complete()` (не `complete_with_tools`),
   ноль изменений в поведении и в форме запроса к OpenAI по сравнению с
   текущим кодом. Это гарантирует, что встраивание в `_reply()` в этой
   итерации (при пустом реестре тулз у всех ботов) не меняет живое
   поведение вообще.
2. Иначе — до `max_rounds` раз: `complete_with_tools(..., exchange=exchange)`.
   Если `tool_calls is None` — возврат (собрать `ToolLoopResult`,
   просуммировав `tokens_in`/`tokens_out` по всем раундам, а не только
   последнему — иначе usage_events занизит стоимость многошагового ответа).
3. Если есть `tool_calls` — добавить `AssistantToolCallsTurn` в `exchange`,
   выполнить каждый вызов через `executor(name, arguments)` под
   `asyncio.wait_for(..., TOOL_CALL_TIMEOUT_SECONDS)`:
   - аргументы не распарсились как JSON → `ToolResultTurn` с текстом
     ошибки для модели ("не удалось разобрать аргументы, повтори вызов
     корректным JSON"), тулза не вызывается;
   - `executor` вернул исключение (таймаут, неизвестное имя тулзы, сбой
     самой тулзы) → тоже `ToolResultTurn` с текстом ошибки, лог
     `logger.warning`, цикл продолжается (не падает на одном плохом
     вызове тулзы — тот же принцип, что и общий `except Exception` в
     `_process_entry`, но здесь не теряем весь ответ, а даём модели шанс
     справиться без этого результата или попробовать иначе).
4. После `max_rounds` раундов, если модель всё ещё просит тулзу —
   финальный вызов `complete_with_tools(..., force_text=True)` на
   собранном `exchange`, чтобы модель ответила по тому, что уже узнала,
   вместо тишины.

**Executor** в `_reply()` собирается по `ToolContext` (см. ниже) и
`libs.tools.get_tool`; неизвестное `tool_name` (тулза выключена/удалена из
реестра между постановкой в `tool_bindings` и вызовом) — тоже ошибка для
модели, не исключение наружу.

## `libs/tools` — интерфейс и реестр

```python
# libs/tools/src/tools/base.py
@dataclass(frozen=True)
class ToolContext:
    bot: Bot
    contact_id: uuid.UUID
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: Storage
    config: dict[str, Any]  # tool_bindings.config для этого бота и этой тулзы


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> str: ...
```

```python
# libs/tools/src/tools/registry.py
_REGISTRY: dict[str, Tool] = {}  # пусто в этой итерации — заполняется по мере
                                   # появления реальных тулз в следующих итерациях

def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)

def all_tool_names() -> list[str]:
    return list(_REGISTRY)
```

Новый pip-пакет (`pip install -e libs/tools`), по образцу существующих
`libs/*` — попадает в `make install`.

## БД — `tool_bindings`

Точно по ARCHITECTURE.md §5.

```python
class ToolBinding(Base):
    __tablename__ = "tool_bindings"
    __table_args__ = (
        UniqueConstraint("bot_id", "tool_name", name="uq_tool_bindings_bot_tool_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    bot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

Alembic-миграция. `libs/db/src/db/tool_bindings.py`:
`list_enabled(session, bot_id) -> list[ToolBinding]`,
`enable(session, bot_id, tool_name, config) -> ToolBinding` (upsert по
`UNIQUE(bot_id, tool_name)` — повторное включение обновляет `config`, не
дублирует строку),
`disable(session, bot_id, tool_name) -> None`.

## API — `/bots/{id}/tools`

В существующем `services/api/src/api/routers/bots.py` (по прецеденту
blocked-numbers, тот же файл):

- `GET /bots/{id}/tools` → `list[ToolBindingOut]` (`tool_name`, `config`)
- `POST /bots/{id}/tools` (`tool_name`, `config`) → 201; **400**, если
  `tool_name` не в `libs.tools.registry.all_tool_names()` — сейчас реестр
  пуст, поэтому в этой итерации включить нельзя ничего, это ожидаемо
  и является рабочей живой проверкой самого эндпоинта и валидации
- `DELETE /bots/{id}/tools/{tool_name}` → 204

Схемы — `services/api/src/api/schemas/tool_bindings.py`, по образцу
`schemas/blocked_contacts.py`.

## Встраивание в `_reply()`

`_reply()` в `services/worker/src/worker/pipeline/consumer.py` берёт
`tool_bindings.list_enabled(session, bot.id)` при сборке истории, строит
`list[ToolSpec]` через `get_tool(name)` (пропуская молча записи, для
которых тулза не найдена в реестре — рассинхрон реестра и БД не должен
ронять диалог) и зовёт `run_tool_loop(...)` вместо `complete(...)`.

При пустом списке тулз (все боты сейчас) `run_tool_loop` делегирует в
`complete()` — см. п.1 поведения выше — **ноль изменений в живом
поведении**. `usage_events`/`_schedule_follow_up` берут суммарные
`tokens_in/out` из `ToolLoopResult`, остальной код `_reply()` не меняется.

**Не меняются** `_reply_with_vision`/`_reply_with_pdf` (у них нет и не
предполагается тулз в рамках этой итерации — однопроходная архитектура
image_prompt/pdf_prompt осознанно сохраняется).

**История в БД** — как у vision/PDF: сохраняется только финальный текст
ответа. Промежуточные `tool_calls`/результаты тулз в `messages` не
пишутся отдельными строками — эфемерны в рамках одного вызова
`run_tool_loop`, не CoT-лог. (Если Волна 3/6.14 "просмотр переписки"
впоследствии потребует видимость вызовов тулз менеджеру — отдельная
фича, не блокирует эту итерацию.)

## Тесты

- `libs/llm`: `complete_with_tools` — сборка `tools=[...]` в запросе,
  разбор ответа с `tool_calls`, разбор чисто текстового ответа (мок
  `AsyncOpenAI`, как для `complete`/`complete_with_image`).
- `services/worker`: `tool_loop` — фейковая тулза (реализация `Tool`
  protocol) в тестовом коде (не в реестре продакшн-кода):
  - пустой список тулз → делегирует в `complete()`, не в
    `complete_with_tools`
  - многораундовый сценарий (раунд 1 — tool_calls, раунд 2 — текст)
  - невалидный JSON в аргументах тулзы → ошибка модели, не краш
  - исключение из `executor` (включая таймаут) → ошибка модели, цикл
    продолжается
  - исчерпание `max_rounds` → `force_text=True` на последнем вызове
  - суммирование `tokens_in`/`tokens_out` по всем раундам
- `libs/db`: CRUD `tool_bindings`, включая upsert-семантику `enable()`.
- `services/api`: список (пусто по умолчанию), `POST` с неизвестным
  `tool_name` → 400, `POST` с известным (замоканный реестр в тесте) → 201,
  `DELETE` → 204.
- Живой прогон: `docker compose up`, миграция применяется (`\d tool_bindings`),
  обычный текстовый диалог отвечает как раньше (деградация на отсутствующий
  `OPENAI_API_KEY` — как и в vision/PDF/ретраях), `POST /bots/{id}/tools`
  с несуществующим именем → 400 через реальный `curl`.

## Границы этой итерации

Не входит: сама первая тулза (4.1, следующая итерация), UI включения тулз
(Волна 3), видимость tool-calls в истории для менеджера, любая связь
с `bots.settings` (тулзы — отдельная таблица, не JSONB-настройки бота).
