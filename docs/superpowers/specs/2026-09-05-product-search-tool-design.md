# pgvector-поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2)

**Статус:** утверждено пользователем 2026-09-05
**Волна:** 2, итерация 3 из 6 (после инфраструктуры тулз + 3.4 каталог;
следующие — 4.3–4.6 карточки товара, 4.7 telegram-лиды, 4.8/4.9 файлы/видео)

## Контекст

Инфраструктура тулзов (итерация 1) и каталог в контексте (3.4) уже
сданы — реестр тулз (`libs/tools`) пуст, `tool_bindings` пуста, механизм
цикла LLM↔tool-calls (`run_tool_loop`) готов и не менялся с тех пор.
Эта итерация — **первая настоящая тулза**: векторный поиск товара по
`pgvector` с fallback на точное совпадение по имени.

Эталон поведения — архив V1 (`webhook_wb.zip`):
`central-admin/main.py` (генерация эмбеддинга при create/update товара,
`text-embedding-3-small`, комбинированный текст `"Name: {name};
Description: {description}"`, хранение как `vector(1536)` строкой вида
`"[0.1,0.2,...]"`) и `node-bot3/whatsapp.js::vectorProductSearch`
(собственно поиск).

**Расхождение с FEATURES.md, зафиксированное и разрешённое пользователем**:
FEATURES.md описывает "векторный поиск → ILIKE fallback, если вектор
ничего не нашёл". Реальный код делает наоборот — **точное
регистронезависимое совпадение по имени первым** (`LOWER(TRIM(name)) =
LOWER($1)`, не `ILIKE`-подстрока), и только если пусто — векторный поиск
(cosine similarity, порог 0.4, `LIMIT 1`). Пользователь подтвердил: делать
как в архиве, расхождение остаётся зафиксированным здесь, не в
FEATURES.md (сам реестр не трогаем).

**Триггер генерации эмбеддинга** — тоже решённый вопрос: CRUD товаров
(FEATURES.md 6.8) — Волна 3, её ещё нет. Эта итерация строит
переиспользуемую функцию генерации+сохранения эмбеддинга, но НЕ строит
автоматический триггер (create/update UI) — это работа Волны 3. Для
живой проверки этой итерации эмбеддинг для тестового товара будет
посчитан вручную одноразовым скриптом вне приложения (не коммитится).

## Разделение по пакетам (ADR-002)

- **`libs/db`** — модели и чистые запросы. НЕ вызывает OpenAI.
- **`libs/llm`** — механика вызова OpenAI (эмбеддинги — тот же принцип,
  что и `complete()`/`complete_with_tools()`). НЕ знает о Postgres.
- **`libs/tools`** — единственный слой, которому разрешено знать и про
  `db`, и про `llm` (тулза — точка композиции бизнес-логики, ADR-002).

`services/worker`/`services/api` в этой итерации **не меняются** —
цикл тулз (`run_tool_loop`) и `/bots/{id}/tools` уже всё умеют; включить
тулзу боту — `POST /bots/{id}/tools {"tool_name": "search_products"}`.

## `libs/db` — схема и запросы

Новая зависимость: `pgvector>=0.3` (пакет с `pgvector.sqlalchemy.Vector`
— типобезопасная колонка-вектор для SQLAlchemy ORM, вместо ручной сборки
`"[1,2,3]"`-строк, как в архиве, у которого не было ORM-обвязки).

### Модель `ProductEmbedding`

```python
from pgvector.sqlalchemy import Vector

class ProductEmbedding(Base):
    """1:1 с товаром (как bot_sessions.bot_id) — эталон V1: комбинированный
    текст "Name: {name}; Description: {description}" в text-embedding-3-small.
    Кто и когда пересчитывает — Волна 3 (CRUD, create/update товара);
    здесь только хранение и чтение.
    """

    __tablename__ = "product_embeddings"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
```

### Миграция

`CREATE EXTENSION IF NOT EXISTS vector` (idempotent — `IF NOT EXISTS`,
безопасно на повторный прогон) + `create_table("product_embeddings", ...)`
с колонкой `sa.Column("embedding", Vector(1536), nullable=False)` — тот же
тип из пакета `pgvector`, что и в модели (миграция и модель должны
совпадать буквально, не дублировать через сырой SQL-тип). Без ANN-индекса
(ivfflat/hnsw) — осознанно отложено: тюнинг под реальные данные, которых
пока нет; при небольших per-bot каталогах полный скан приемлем.

### `libs/db/src/db/products.py` — новая функция

```python
async def find_product_by_exact_name(
    session: AsyncSession, bot_id: uuid.UUID, name: str
) -> Product | None:
    """Точное регистронезависимое совпадение по имени (эталон V1:
    LOWER(TRIM(name)) = LOWER($1)), НЕ подстрока/ILIKE."""
```

### `libs/db/src/db/product_embeddings.py` — новый файл

```python
async def upsert_embedding(
    session: AsyncSession, product_id: uuid.UUID, embedding: list[float]
) -> None:
    """Идемпотентно: PK = product_id, ON CONFLICT DO UPDATE."""

async def find_product_by_embedding(
    session: AsyncSession, bot_id: uuid.UUID, query_embedding: list[float],
    *, threshold: float = 0.4,
) -> Product | None:
    """JOIN products+product_embeddings, WHERE products.bot_id = :bot_id,
    similarity = 1 - cosine_distance > threshold, ORDER BY similarity DESC,
    LIMIT 1 (эталон V1: порог 0.4, ровно один товар, не список)."""
```

## `libs/llm` — генерация эмбеддинга

Новый `libs/llm/src/llm/embeddings.py`:

```python
EMBEDDING_MODEL = "text-embedding-3-small"

def product_embedding_input(name: str, description: str | None) -> str:
    """Эталон V1 (add_product/update_product, central-admin/main.py):
    "Name: {name}; Description: {description}"."""
    return f"Name: {name}; Description: {description or ''}"

async def generate_embedding(
    text: str, *, client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> list[float]:
    """OpenAI embeddings.create(model=EMBEDDING_MODEL, input=text).
    Тот же ретрай-механизм (3 попытки, backoff 1с/2с, те же
    retryable-исключения), что и complete() — переиспользует
    _RETRYABLE_EXCEPTIONS/RETRY_MAX_ATTEMPTS/RETRY_BASE_DELAY_SECONDS
    из client.py (тот же пакет, отдельный небольшой цикл ретраев —
    не общий рефакторинг _call_and_extract, чтобы не трогать
    уже протестированный текстовый путь ради этой фичи)."""
```

## `libs/tools` — `ProductSearchTool`

Новая зависимость: `llm` (первая тулза, которой реально нужен LLM-вызов
изнутри — до сих пор `libs/tools` зависел только от `db`+`integrations`).

Новый `libs/tools/src/tools/product_search.py`:

```python
class ProductSearchTool:
    name = "search_products"
    description = "Ищет товар в каталоге бота по названию или похожему описанию."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Название или описание товара, которое ищет клиент"}
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        query = str(arguments.get("query", ""))
        async with ctx.session_factory() as session:
            product = await find_product_by_exact_name(session, ctx.bot.id, query)
            if product is None:
                embedding = await generate_embedding(query)
                product = await find_product_by_embedding(session, ctx.bot.id, embedding)
        if product is None:
            return "[]"
        price = str(product.price) if product.price is not None else "Не указана"
        return json.dumps(
            [{"name": product.name, "description": product.description or "", "price": price}],
            ensure_ascii=False,
        )
```

Контракт результата — точная копия V1 (`formatProductForTool` +
`JSON.stringify`): JSON-массив из 0 или 1 объекта `{name, description,
price}`, `price` по умолчанию `"Не указана"` (не `null`/`"-"`, как в
каталоге 3.4 — это разные контракты: 3.4 говорит LLM "вот весь каталог",
здесь LLM получает результат конкретного поиска, эталон V1 отличается
намеренно, не унифицирую).

### Реестр — заодно чиню находку прошлого финального ревью

`libs/tools/src/tools/registry.py` — было: `_REGISTRY: dict[str, Tool] =
{}`, заполнялось только в тестах через `monkeypatch.setitem`. Прошлый
финальный ревью (opus) отметил риск: ключ реестра и `tool.name` могут
разойтись, если регистрировать вручную `_REGISTRY[key] = tool`. Добавляю:

```python
def register(tool: Tool) -> None:
    """Ключ реестра — всегда tool.name, никогда не отдельная строка —
    расхождение между ними было находкой финального ревью 2026-09-05
    (инфраструктура тулз)."""
    _REGISTRY[tool.name] = tool

register(ProductSearchTool())
```

`test_all_tool_names_empty_by_default` (Task 1 инфраструктуры) обновится
— реестр больше не пуст, комментарий там уже это предсказывал ("первая
тулза — 4.1, тест обновится").

## Тесты

- `libs/db`: `find_product_by_exact_name` (найден/не найден/регистр и
  пробелы игнорируются/скоуп per bot), `upsert_embedding` (идемпотентность
  через ON CONFLICT), `find_product_by_embedding` (порог 0.4 отсекает
  непохожие, скоуп per bot, `LIMIT 1` — не список). Настоящие векторы в
  тестах — не заглушки: не обязательно реальный OpenAI-эмбеддинг, но
  реальные числовые векторы одинаковой размерности 1536, с управляемой
  похожестью (например, идентичные векторы = similarity 1.0, ортогональные
  = similarity 0.0), чтобы порог 0.4 был осмысленно проверяем.
- `libs/llm`: `product_embedding_input` (точный формат строки),
  `generate_embedding` (мок `AsyncOpenAI.embeddings.create`, разбор
  ответа, ретраи на те же исключения, что и `complete()`).
- `libs/tools`: `ProductSearchTool.execute()` — точное совпадение находит
  сразу (эмбеддинг не вызывается — фейковый `generate_embedding` кидает
  `AssertionError`, если позвали), точного нет → вызывается эмбеддинг →
  векторный поиск; ничего не найдено → `"[]"`; JSON-контракт результата
  (`price` по умолчанию); `registry.register()`/`get_tool()` не
  расходятся по ключу.
- Живой прогон: `docker compose up`, миграция `product_embeddings`
  применяется (`\d product_embeddings`, `SELECT * FROM
  pg_extension WHERE extname='vector'`), тестовый товар + вручную
  посчитанный эмбеддинг (одноразовый скрипт, не в репозитории),
  `POST /bots/{id}/tools {"tool_name": "search_products"}` включает
  тулзу боту, реальный `XADD wa:in` — деградация на отсутствующий
  `OPENAI_API_KEY` (как и раньше) на этот раз происходит уже ВНУТРИ
  цикла тулз (не на быстром пути), что само по себе подтверждает, что
  тулза была предложена модели.

## Границы этой итерации

Не входит: CRUD товаров и UI кабинета (Волна 3, 6.8), автоматический
пересчёт эмбеддинга при создании/правке товара (тоже Волна 3 — здесь
только переиспользуемая функция), карточка товара с фото (4.3–4.6,
следующая итерация), ANN-индекс на `product_embeddings.embedding`
(осознанно отложено до реальных объёмов данных).
