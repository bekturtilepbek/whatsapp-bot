# Vision-анализ фото (FEATURES.md 2.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот, у которого настроен `image_prompt`, отвечает на присланное фото
осмысленным LLM-ответом (vision), а не статической заглушкой — без изменения
поведения для ботов, у которых `image_prompt` не задан.

**Architecture:** Однопроходная схема (подтверждена пользователем 2026-09-04):
`bot.image_prompt` используется КАК system prompt единственного вызова LLM;
картинка идёт вложением (base64 data URL); ответ модели уходит клиенту
напрямую — без второго прохода «описание → отдельный LLM-вызов». Это
осознанно проще двухпроходной схемы: 2.5 (поиск товара по фото), которая
могла бы потребовать текстового описания как промежуточного артефакта, — вне
скоупа Волны 1 (см. FEATURES.md «Скоуп и порядок работ»).

**Tech Stack:** OpenAI `gpt-4o-mini` (уже vision-capable, без отдельной
модели), `libs/integrations` Storage (первый реальный потребитель
`Storage.get()` — интерфейс уже собран и протестирован в прошлой итерации,
но никем не вызывается), SQLAlchemy + Alembic.

**Spec:** нет отдельного design-документа — архитектурная развилка
(однопроходная vs двухпроходная) решена в чате 2026-09-04, детальный дизайн
провалидирован Plan-агентом на чтении текущего кода; этот файл — итоговый
план с учётом обоих.

## Global Constraints

- Любой внешний вызов — с таймаутом (CLAUDE.md): чтение из Storage
  оборачивается `asyncio.wait_for(..., timeout=STORAGE_READ_TIMEOUT_SECONDS)`
  (20с — не короче встроенного `read_timeout=20` у `S3Storage`, чтобы не
  отменять уже идущее S3-чтение раньше его же собственного таймаута); LLM-вызов
  уже таймаутится нативно через `complete()`/`complete_with_image()`.
- `bot.image_prompt` — обычная nullable-колонка `bots`, БЕЗ версионирования
  (`prompt_versions` — явно Волна 3, не здесь).
- NULL/пустая строка в `image_prompt` = vision не настроен → поведение
  идентично сегодняшнему (заглушка `media_fallback_text`), ноль сюрпризов для
  ботов, которые ничего не настраивали.
- Любой сбой на пути vision (Storage, таймаут, сам LLM-вызов, пустой ответ) —
  НЕ бросается наружу и НЕ приводит к тишине: деградирует в существующий
  `_reply_with_media_fallback`, ровно один ответ клиенту, не два.
- Не трогаем STT (2.2/2.3), PDF (2.4), поиск товара по фото (2.5 — вне
  скоупа), не строим `prompt_versions`. Не вводим отдельный
  vision-специфичный `OPENAI_MODEL` — переиспользуем существующий
  `current_model()`.
- Conventional Commits; каждый коммит заканчивается
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

## Task 1: `bots.image_prompt` — миграция и модель

**Files:**
- Modify: `libs/db/src/db/models.py`
- Create: `libs/db/migrations/versions/202609041001_bots_image_prompt.py`
- Modify: `libs/db/tests/test_migration.py`

**Interfaces:**
- Produces: `Bot.image_prompt: str | None` (ORM-атрибут, читается напрямую —
  как `bot.system_prompt`/`bot.timezone` сегодня, без отдельной
  read/write-функции).

- [ ] **Step 1: Обновить падающий тест на состав колонок `bots`**

В `libs/db/tests/test_migration.py`, в блоке `assert bot_columns == {...}`
(строки 67-75), добавить `"image_prompt"` в множество:

```python
        assert bot_columns == {
            "id",
            "name",
            "enabled",
            "system_prompt",
            "image_prompt",
            "timezone",
            "settings",
            "created_at",
        }
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest libs/db/tests/test_migration.py -v` (нужен Docker)

Expected: FAIL — `bot_columns` из реальной БД не содержит `image_prompt`
(миграция ещё не написана), множества не совпадают.

- [ ] **Step 3: Добавить колонку в модель**

В `libs/db/src/db/models.py`, класс `Bot`, сразу после `system_prompt`:

```python
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # Отдельный system prompt для vision-ответа на фото (FEATURES.md 2.1).
    # NULL = vision не настроен у этого бота — падаем в старую медиа-заглушку.
    # Без server_default: NULL — осознанное состояние "не настроено", в
    # отличие от system_prompt, где пустая строка была бы валидным (хоть и
    # бесполезным) промптом.
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Создать миграцию Alembic**

Создать `libs/db/migrations/versions/202609041001_bots_image_prompt.py`:

```python
"""bots.image_prompt

Revision ID: 202609041001
Revises: 202609031001
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609041001"
down_revision: str | None = "202609031001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("image_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "image_prompt")
```

- [ ] **Step 5: Прогнать — ожидаем PASS**

Run: `pytest libs/db/tests/test_migration.py -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add libs/db/src/db/models.py libs/db/migrations/versions/202609041001_bots_image_prompt.py libs/db/tests/test_migration.py
git commit -m "feat(db): add bots.image_prompt column

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `llm.complete_with_image` — однопроходный vision-вызов

**Files:**
- Modify: `libs/llm/src/llm/client.py`
- Modify: `libs/llm/tests/test_client.py`

**Interfaces:**
- Consumes: `HistoryMessage`, `LLMResult`, `current_model()`,
  `_default_client()` (все уже существуют в этом файле).
- Produces: `async def complete_with_image(system_prompt: str, history: list[HistoryMessage], caption: str, image_bytes: bytes, image_mime_type: str, *, client: AsyncOpenAI | None = None, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> LLMResult`.
  `history` — ТОЛЬКО предыдущие ходы, без текущего (вызывающий код сам
  собирает текущий ход из caption+картинки — текущая строка в БД это
  плейсхолдер вроде `"[фото]"`, отправлять его в LLM как текст бессмысленно).

- [ ] **Step 1: Написать падающие тесты**

В `libs/llm/tests/test_client.py`, добавить `import base64` в начало файла
и в конец файла:

```python
from llm.client import complete_with_image


async def test_image_message_sent_as_content_array_with_base64_data_url() -> None:
    client = _client_with_response("На фото кроссовки Nike Air.", tokens_in=200, tokens_out=15)
    result = await complete_with_image(
        "SYS", [], "Что это?", b"\xff\xd8\xff", "image/jpeg", client=client
    )  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "SYS"}
    assert sent[-1]["role"] == "user"
    content = sent[-1]["content"]
    assert content[0] == {"type": "text", "text": "Что это?"}
    expected_b64 = base64.b64encode(b"\xff\xd8\xff").decode("ascii")
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{expected_b64}"},
    }
    assert result.text == "На фото кроссовки Nike Air."
    assert result.tokens_in == 200
    assert result.tokens_out == 15


async def test_image_message_prior_history_sent_as_plain_text_before_final_turn() -> None:
    client = _client_with_response("ok", 1, 1)
    history = [
        HistoryMessage(role="user", content="привет"),
        HistoryMessage(role="assistant", content="здравствуйте"),
    ]
    await complete_with_image("SYS", history, "", b"abc", "image/png", client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[1] == {"role": "user", "content": "привет"}
    assert sent[2] == {"role": "assistant", "content": "здравствуйте"}
    assert sent[3]["role"] == "user"
    assert isinstance(sent[3]["content"], list)  # финальный ход — content-массив, не строка


async def test_empty_caption_uses_placeholder_text_block() -> None:
    client = _client_with_response("ok", 1, 1)
    await complete_with_image("SYS", [], "", b"abc", "image/jpeg", client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    text_block = sent[-1]["content"][0]
    assert text_block["type"] == "text"
    assert text_block["text"]  # не пустая строка


async def test_image_call_passes_timeout_through_to_sdk() -> None:
    client = _client_with_response("ok", 1, 1)
    await complete_with_image(
        "SYS", [], "", b"abc", "image/jpeg", client=client, timeout_seconds=12.5
    )  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["timeout"] == 12.5
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest libs/llm/tests/test_client.py -v`

Expected: FAIL — `complete_with_image` не существует (`ImportError`).

- [ ] **Step 3: Реализовать**

В `libs/llm/src/llm/client.py`:

1. Добавить `import base64` в начало файла.
2. Извлечь общий хвост «вызвать SDK, собрать `LLMResult`» в приватный
   хелпер, переиспользуемый и `complete()`, и новой функцией:

```python
async def _call_and_extract(
    active_client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, object]],
    timeout_seconds: float,
) -> LLMResult:
    response = await active_client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        timeout=timeout_seconds,
    )
    choice = response.choices[0]
    text = choice.message.content or ""
    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    return LLMResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out, model=model)
```

3. Переписать `complete()`, чтобы использовать хелпер (поведение и сигнатура
   не меняются — только тело):

```python
async def complete(
    system_prompt: str,
    history: list[HistoryMessage],
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """Любой внешний вызов — с таймаутом (CLAUDE.md). Таймаут — нативный
    httpx-таймаут SDK, не обёртка снаружи: так отменяется сам HTTP-запрос,
    а не только ожидание его результата.
    """
    model = current_model()
    messages = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in history
    ]
    active_client = client or _default_client()
    return await _call_and_extract(active_client, model, messages, timeout_seconds)
```

4. Добавить новую функцию в конец файла:

```python
_EMPTY_CAPTION_PLACEHOLDER = "Опиши, что на фото, и ответь клиенту по инструкции."


async def complete_with_image(
    system_prompt: str,
    history: list[HistoryMessage],
    caption: str,
    image_bytes: bytes,
    image_mime_type: str,
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """FEATURES.md 2.1: единственный вызов LLM на сообщение с фото —
    image_prompt бота используется КАК system prompt, ответ модели уходит
    клиенту напрямую (без второго прохода "описание -> ещё один LLM-вызов").

    history — ТОЛЬКО предыдущие ходы, без текущего: текущий ход собирается
    здесь явно из caption + картинки (текущая строка истории в БД — это
    плейсхолдер вроде "[фото]", отправлять его в LLM как текст бессмысленно
    и вводит модель в заблуждение).

    base64 data URL, а не Files API/публичный URL — картинка уже лежит у нас
    байтами (Storage.get), а не в общедоступном месте: data URL не требует
    отдельного аплоада и не "утекает" наружу.
    """
    model = current_model()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": caption or _EMPTY_CAPTION_PLACEHOLDER},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime_type};base64,{b64}"},
                },
            ],
        }
    )
    active_client = client or _default_client()
    return await _call_and_extract(active_client, model, messages, timeout_seconds)
```

- [ ] **Step 4: Прогнать весь файл — ожидаем PASS, без регрессий**

Run: `pytest libs/llm/tests/test_client.py -v`

Expected: PASS — все старые тесты `complete()` (5 шт.) ПЛЮС новые 4 теста
`complete_with_image` зелёные. Рефакторинг `complete()` в `_call_and_extract`
не должен ничего сломать — это чисто извлечение, без изменения поведения.

- [ ] **Step 5: Commit**

```bash
git add libs/llm/src/llm/client.py libs/llm/tests/test_client.py
git commit -m "feat(llm): add complete_with_image for single-pass vision replies

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Прокинуть `Storage` через консюмер (без нового поведения)

Чисто инфраструктурный шаг: signature threading, как уже сделано для
`redis`/`session_factory`. Отдельная задача — чтобы Task 5 (реальная
vision-ветка) не смешивала «прокинуть зависимость» и «использовать её».

**Files:**
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Modify: `services/worker/tests/pipeline/test_media_fallback.py`
- Modify: `services/worker/tests/pipeline/test_reply_smoke.py`
- Modify: `services/worker/tests/pipeline/test_consumer.py`
- Modify: `services/worker/tests/pipeline/test_handoff.py`

**Interfaces:**
- Produces: `_process_entry(payload, redis, session_factory, storage: Storage)`,
  `run_pipeline_consumer(redis, session_factory, consumer_name, storage: Storage)`
  — оба получают обязательный (без default) 4-й параметр `storage`. Никакая
  ветка пайплайна пока его не читает — это следующая задача.

- [ ] **Step 1: Добавить импорт и параметр в сигнатуры**

В `services/worker/src/worker/pipeline/consumer.py`, добавить импорт:

```python
from integrations.storage import Storage
```

Изменить сигнатуры (тело функций пока не трогать, кроме передачи параметра
дальше):

```python
async def _process_entry(
    payload: dict[str, Any],
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
```

```python
async def run_pipeline_consumer(
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    consumer_name: str,
    storage: Storage,
) -> None:
    ...
    await ensure_group(redis, IN_STREAM, GROUP)
    while True:
        try:
            async for entry in read_group(redis, IN_STREAM, GROUP, consumer_name):
                try:
                    if entry.payload is not None:
                        await _process_entry(entry.payload, redis, session_factory, storage)
                finally:
                    await redis.xack(IN_STREAM, GROUP, entry.entry_id)
        except Exception:
            logger.exception("wa:in read loop failed, retrying")
            await asyncio.sleep(1)
```

- [ ] **Step 2: Прогнать — ожидаем FAIL (много мест)**

Run: `pytest services/worker/tests/pipeline -v`

Expected: FAIL — `TypeError: _process_entry() missing 1 required positional
argument: 'storage'` во всех вызовах `_process_entry(...)` без 4-го
аргумента (17 мест в 4 файлах: `test_media_fallback.py`,
`test_reply_smoke.py`, `test_consumer.py`, `test_handoff.py`).

- [ ] **Step 3: Добавить фейковый Storage и обновить все вызовы**

В каждом из 4 тестовых файлов, рядом с остальными helper'ами файла (нет
общего `conftest.py` в проекте — паттерн такой, каждый файл самодостаточен),
добавить:

```python
class _NullStorage:
    """Заглушка для тестов, которые не доходят до vision-ветки — она никогда
    не должна вызываться, поэтому падает явно, а не тихо возвращает мусор.
    """

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")
```

Затем в КАЖДОМ вызове `_process_entry(...)` в этих 4 файлах добавить
`_NullStorage()` последним позиционным аргументом — например:

```python
await _process_entry(_inbound_image_payload(bot_id), redis, session_factory, _NullStorage())
```

(механическая правка — 17 вызовов, но каждый получает ровно один и тот же
4-й аргумент; список точных строк смотри в результате Step 2)

- [ ] **Step 4: Прогнать — ожидаем PASS, без регрессий**

Run: `pytest services/worker/tests/pipeline -v`

Expected: PASS — все существующие тесты зелёные, поведение не изменилось
(эта задача ничего не меняет в логике, только прокидывает параметр).

- [ ] **Step 5: Commit**

```bash
git add services/worker/src/worker/pipeline/consumer.py \
        services/worker/tests/pipeline/test_media_fallback.py \
        services/worker/tests/pipeline/test_reply_smoke.py \
        services/worker/tests/pipeline/test_consumer.py \
        services/worker/tests/pipeline/test_handoff.py
git commit -m "refactor(worker): thread Storage through pipeline consumer

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: Собрать `Storage` в `main.py`

**Files:**
- Modify: `services/worker/src/worker/main.py`

**Interfaces:**
- Consumes: `integrations.storage.create_storage()` (уже существует),
  `run_pipeline_consumer(..., storage)` (Task 3).

- [ ] **Step 1: Добавить импорт и вызов**

В `services/worker/src/worker/main.py`:

```python
from db.engine import make_engine, make_session_factory
from integrations.storage import create_storage

from .bus import make_redis
from .pipeline.consumer import run_pipeline_consumer
```

```python
async def main() -> None:
    health_runner = await run_health_server()
    redis = make_redis()
    engine = make_engine()
    session_factory = make_session_factory(engine)
    storage = create_storage()
    consumer_name = f"worker-{os.getpid()}"
    pipeline_task = asyncio.create_task(
        run_pipeline_consumer(redis, session_factory, consumer_name, storage)
    )
```

`create_storage()` без `env` читает `os.environ` — `STORAGE_DRIVER`,
`STORAGE_FS_ROOT`, `S3_*` уже прописаны для сервиса `worker` в
`compose/docker-compose.dev.yml` и `.prod.yml` (прошлая итерация). Никакого
teardown не требуется — `Storage`-реализации держат либо `Path` (fs), либо
самоуправляемый `boto3`-клиент (s3), как остальные ресурсы в этом файле, у
которых нет explicit close (сравни: `engine.dispose()`/`redis.aclose()` есть
только там, где ресурс реально держит соединение).

- [ ] **Step 2: Проверить, что worker стартует**

Run: `cd services/worker && python -c "from worker.main import main"` (или
эквивалент — импорт не должен падать; полный живой прогон — в Task 7)

Expected: без ошибок импорта.

- [ ] **Step 3: Commit**

```bash
git add services/worker/src/worker/main.py
git commit -m "feat(worker): construct Storage in main entrypoint

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `_reply_with_vision` — реальная vision-ветка

**Files:**
- Modify: `services/worker/src/worker/pipeline/consumer.py`
- Create: `services/worker/tests/pipeline/test_vision.py`

**Interfaces:**
- Consumes: `complete_with_image` (Task 2), `storage: Storage` (Task 3/4),
  `bot.image_prompt` (Task 1), `event.storage_key/mime_type/text` (уже в
  контракте).
- Produces: `_reply_with_vision(event, bot, contact_id, redis, session_factory, storage) -> None`.

- [ ] **Step 1: Написать падающие тесты**

Создать `services/worker/tests/pipeline/test_vision.py` — скопировать
шапку/фикстуры (`_docker_available`, `database_url`, `session_factory`)
дословно из `services/worker/tests/pipeline/test_media_fallback.py` (тот же
паттерн testcontainers + alembic upgrade), затем:

```python
"""Vision-ответ на фото (FEATURES.md 2.1): один вызов LLM с image_prompt как
system prompt, ответ уходит клиенту напрямую. Деградация в медиа-заглушку
при сбое storage/LLM — без падения консюмера и без двойного ответа.
"""
# ... (шапка как в test_media_fallback.py: docker-gate, database_url,
# session_factory fixtures — дословно) ...

import uuid

import pytest
from db.models import Message, UsageEvent
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import DEFAULT_MEDIA_FALLBACK_TEXT, _process_entry


class _FakeStorage:
    def __init__(self, data: bytes | None = None, error: Exception | None = None) -> None:
        self._data = data
        self._error = error

    async def get(self, key: str) -> bytes:
        if self._error is not None:
            raise self._error
        assert self._data is not None
        return self._data


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    image_prompt: str | None = None,
) -> uuid.UUID:
    from db.models import Bot

    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            image_prompt=image_prompt,
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_image_payload_with_storage(
    bot_id: uuid.UUID, *, text: str = ""
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-vision-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": text,
        "media_type": "image",
        "storage_key": f"bots/{bot_id}/media/wamsg-vision-1",
        "mime_type": "image/jpeg",
        "size_bytes": 12345,
        "ts": 1756900000000,
    }


async def test_bot_with_image_prompt_sends_vision_reply_and_records_usage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete_with_image(
        system_prompt: str, history: object, caption: str, image_bytes: bytes, mime_type: str, **_: object
    ) -> LLMResult:
        assert "Опиши товар" in system_prompt  # bot.image_prompt подмешан
        assert image_bytes == b"fake-jpeg-bytes"
        return LLMResult(
            text="На фото синие кроссовки 42 размера.",
            tokens_in=300,
            tokens_out=20,
            model="gpt-4o-mini",
        )

    monkeypatch.setattr(consumer_module, "complete_with_image", fake_complete_with_image)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар на фото клиенту.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=b"fake-jpeg-bytes"),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert "На фото синие кроссовки" in out_entries[1][1]["payload"]

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
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "На фото синие кроссовки 42 размера."

            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(usage) == 1  # в отличие от media_fallback — здесь LLM реально вызывался
            assert usage[0].tokens_in == 300
    finally:
        await redis.aclose()


async def test_bot_without_image_prompt_falls_back_and_skips_llm(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("vision LLM не должен вызываться без image_prompt")

    monkeypatch.setattr(consumer_module, "complete_with_image", fail_if_called)

    bot_id = await _make_bot(session_factory, image_prompt=None)  # регрессия — старое поведение
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id), redis, session_factory, _FakeStorage()
        )
        out_entries = await redis.xrange("wa:out")
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
        async with session_factory() as session:
            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert usage == []
    finally:
        await redis.aclose()


async def test_storage_read_failure_falls_back_without_crashing_or_double_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("vision LLM не должен вызываться при сбое storage")

    monkeypatch.setattr(consumer_module, "complete_with_image", fail_if_called)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(error=OSError("disk unavailable")),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2  # ровно один typing+text, не два ответа
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
        async with session_factory() as session:
            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert usage == []
    finally:
        await redis.aclose()


async def test_vision_llm_failure_falls_back_without_crashing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_complete(*args: object, **kwargs: object) -> LLMResult:
        raise TimeoutError("OpenAI vision timed out")

    monkeypatch.setattr(consumer_module, "complete_with_image", failing_complete)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=b"fake-jpeg-bytes"),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()
```

- [ ] **Step 2: Прогнать — ожидаем FAIL**

Run: `pytest services/worker/tests/pipeline/test_vision.py -v`

Expected: FAIL — `_reply_with_vision` не существует, ветка в `_process_entry`
всегда уходит в фолбэк (LLM не вызывается никогда, тест 1 падает на
отсутствии vision-ответа).

- [ ] **Step 3: Реализовать**

В `services/worker/src/worker/pipeline/consumer.py`:

1. Обновить импорт:

```python
from llm.client import HistoryMessage, complete, complete_with_image
```

2. Добавить константу рядом с остальными:

```python
STORAGE_READ_TIMEOUT_SECONDS = 20.0
```

3. Обновить докстринг модуля (в начале файла) — заменить текущее описание
   потока на:

```python
"""Реальный пайплайн диалога — заменяет временный echo (Блок 1).

Порядок (STAGE1_CORE Блок 2+3, Волна 1 п.2.1): дедуп → фильтры → from_me? handoff-ветка :
contact → запись входящего → enabled → handoff активен? молчим : батчинг
(debounce) → лок диалога → фото с настроенным image_prompt? vision-ответ (один
вызов LLM, image_prompt как system prompt, ответ уходит клиенту напрямую) :
прочее медиа? заглушка без LLM : история → LLM → typing → ответ → запись
ответа → usage_events (LLM-ветки, включая vision).

Любая ошибка на отрезке батчинг..запись (Redis/LLM/БД) — лог, лок
снимается, ACK без ответа; ретраи — Волна 1 (STAGE1_CORE). Исключение:
сбой именно vision-вызова (storage/LLM/таймаут) не проваливается наружу —
_reply_with_vision сама деградирует в _reply_with_media_fallback, чтобы
клиент не остался без ответа из-за временной недоступности OpenAI vision
или хранилища.
"""
```

4. Заменить двухветочный if в `_process_entry` (внутри `try:`) на трёхветочный:

```python
    try:
        if event.media_type == "image" and event.storage_key is not None and bot.image_prompt:
            await _reply_with_vision(event, bot, contact.id, redis, session_factory, storage)
        elif event.media_type is not None:
            await _reply_with_media_fallback(event, bot, contact.id, redis, session_factory)
        else:
            await _reply(event, bot, contact.id, redis, session_factory)
```

5. Добавить новую функцию (после `_reply`, перед `_reply_with_media_fallback`):

```python
async def _reply_with_vision(
    event: InboundText,
    bot: Bot,
    contact_id: uuid.UUID,
    redis: Redis,
    session_factory: async_sessionmaker[AsyncSession],
    storage: Storage,
) -> None:
    """FEATURES.md 2.1: один вызов LLM на фото — image_prompt бота как system
    prompt, ответ модели уходит клиенту напрямую (без второго прохода).

    Любой сбой на этом пути (чтение из storage, таймаут, сам вызов LLM,
    пустой ответ) — НЕ бросаем наружу: тихо деградируем в
    _reply_with_media_fallback, чтобы клиент гарантированно получил хоть
    какой-то ответ, а не тишину (в отличие от сбоя обычного _reply, который
    в _process_entry просто логируется без всякого ответа — здесь так
    нельзя, у нас уже есть рабочий fallback ровно для медиа-сообщений).
    """
    try:
        async with session_factory() as session:
            history_rows = await fetch_recent_history(session, contact_id)
        # Последняя строка — плейсхолдер текущего фото ("[фото]"), уже
        # вставленный insert_incoming выше по _process_entry; текущий ход
        # собирается заново из самих байтов картинки, а не из плейсхолдера.
        history = [
            HistoryMessage(role=m.role, content=m.content) for m in history_rows[:-1]
        ]

        assert event.storage_key is not None  # гарантировано веткой в _process_entry
        image_bytes = await asyncio.wait_for(
            storage.get(event.storage_key), timeout=STORAGE_READ_TIMEOUT_SECONDS
        )

        assert bot.image_prompt is not None  # гарантировано веткой в _process_entry
        system_prompt = f"{bot.image_prompt}\n\n{time_context(bot.timezone)}"
        mime_type = event.mime_type or "image/jpeg"
        result = await complete_with_image(
            system_prompt, history, event.text, image_bytes, mime_type
        )
        if not result.text.strip():
            logger.warning(
                "vision LLM returned empty text, falling back", bot_id=str(event.bot_id)
            )
            await _reply_with_media_fallback(event, bot, contact_id, redis, session_factory)
            return
    except Exception:
        logger.warning(
            "vision reply failed, falling back to media placeholder",
            bot_id=str(event.bot_id),
            chat_id=event.chat_id,
            exc_info=True,
        )
        await _reply_with_media_fallback(event, bot, contact_id, redis, session_factory)
        return

    await _send_reply(event, redis, result.text)

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    async with session_factory() as session:
        await insert_outgoing(session, event.bot_id, contact_id, result.text)
        await record_usage(
            session, event.bot_id, result.model, result.tokens_in, result.tokens_out, cost
        )
        await session.commit()
```

- [ ] **Step 4: Прогнать новые тесты — ожидаем PASS**

Run: `pytest services/worker/tests/pipeline/test_vision.py -v`

Expected: PASS (4 теста)

- [ ] **Step 5: Прогнать ВЕСЬ worker-пакет — регрессия**

Run: `pytest services/worker -v`

Expected: PASS, включая `test_media_fallback.py::test_media_message_with_storage_key_persists_media_ref`
(это ровно случай «фото со storage_key, но у бота НЕТ image_prompt» —
должен остаться на старом поведении: LLM не вызывается, `media_ref`
пишется, ответ — заглушка).

- [ ] **Step 6: Commit**

```bash
git add services/worker/src/worker/pipeline/consumer.py services/worker/tests/pipeline/test_vision.py
git commit -m "feat(worker): single-pass vision reply for photos with configured image_prompt

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: `image_prompt` через API (иначе фича не включаема без raw SQL)

Без этого шага `image_prompt` можно выставить только вручную в БД — то есть
фича не эксплуатируема в проде. Зеркалит существующий путь `system_prompt`
1-в-1.

**Files:**
- Modify: `libs/db/src/db/bots.py`
- Modify: `services/api/src/api/schemas/bots.py`
- Modify: `services/api/src/api/routers/bots.py`
- Modify: `services/api/tests/test_bots.py`

**Interfaces:**
- Produces: `update_bot(..., image_prompt: str | None = None, ...)` —
  новый keyword-параметр, аналогичный `system_prompt`; `BotOut.image_prompt: str | None`;
  `BotPatch.image_prompt: str | None = None`.

- [ ] **Step 1: Проверенный существующий паттерн PATCH-теста**

`services/api/tests/test_bots.py::test_patch_system_prompt_only(client,
session_factory)` создаёт бота через `bot_id = await
_make_bot(session_factory)` прямо в теле теста (фикстуры `bot_id` не
существует). Новый тест — по этому же образцу.

- [ ] **Step 2: Написать падающий тест**

Добавить в `services/api/tests/test_bots.py` (рядом с
`test_patch_system_prompt_only`):

```python
async def test_patch_bot_updates_image_prompt(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"image_prompt": "Опиши товар клиенту."})
    assert response.status_code == 200
    assert response.json()["image_prompt"] == "Опиши товар клиенту."

    follow_up = await client.get(f"/bots/{bot_id}")
    assert follow_up.json()["image_prompt"] == "Опиши товар клиенту."


async def test_get_bot_includes_null_image_prompt_by_default(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}")
    assert response.json()["image_prompt"] is None
```

- [ ] **Step 3: Прогнать — ожидаем FAIL**

Run: `pytest services/api/tests/test_bots.py -v`

Expected: FAIL — `image_prompt` не в `BotPatch`/`BotOut`, PATCH его
игнорирует (`exclude_unset` его просто не видит), GET его не возвращает
(`KeyError` при `response.json()["image_prompt"]`).

- [ ] **Step 4: Добавить поле в схемы**

В `services/api/src/api/schemas/bots.py`:

```python
class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    system_prompt: str
    image_prompt: str | None
    timezone: str
    settings: dict[str, Any]
    created_at: datetime


class BotPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные (exclude_unset)."""

    enabled: bool | None = None
    system_prompt: str | None = None
    image_prompt: str | None = None
    settings: dict[str, Any] | None = None
```

- [ ] **Step 5: Добавить параметр в `update_bot`**

В `libs/db/src/db/bots.py`, функция `update_bot`:

```python
async def update_bot(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    enabled: bool | None = None,
    system_prompt: str | None = None,
    image_prompt: str | None = None,
    settings_patch: dict[str, Any] | None = None,
) -> Bot | None:
    """..."""
    values: dict[str, Any] = {}
    if enabled is not None:
        values["enabled"] = enabled
    if system_prompt is not None:
        values["system_prompt"] = system_prompt
    if image_prompt is not None:
        values["image_prompt"] = image_prompt
    if settings_patch is not None:
        values["settings"] = Bot.settings.op("||")(cast(settings_patch, JSONB))
    ...
```

- [ ] **Step 6: Прокинуть в роутере**

В `services/api/src/api/routers/bots.py`, `patch_bot`:

```python
    bot = await update_bot(
        session,
        bot_id,
        enabled=data.get("enabled"),
        system_prompt=data.get("system_prompt"),
        image_prompt=data.get("image_prompt"),
        settings_patch=data.get("settings"),
    )
```

- [ ] **Step 7: Прогнать — ожидаем PASS**

Run: `pytest services/api/tests/test_bots.py -v`

Expected: PASS

- [ ] **Step 8: Полный прогон Python-пакета — регрессия**

Run: `pytest -q` (из корня, полный набор — libs + services/worker +
services/api)

Expected: PASS, без регрессий нигде.

- [ ] **Step 9: Commit**

```bash
git add libs/db/src/db/bots.py services/api/src/api/schemas/bots.py \
        services/api/src/api/routers/bots.py services/api/tests/test_bots.py
git commit -m "feat(api): expose bots.image_prompt via GET/PATCH

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Живой прогон (docker compose)

По [[live-verification-preference]] — не только зелёные тесты.

**Files:** нет (верификация)

- [ ] **Step 1: Поднять dev-стек**

Проверить свободное место (`Get-PSDrive C`), затем `make dev` или
`docker compose -f compose/docker-compose.dev.yml up --build -d`.

- [ ] **Step 2: Прогнать миграции**

`docker compose -f compose/docker-compose.dev.yml exec worker sh -c "cd /app/libs/db && alembic upgrade head"`

- [ ] **Step 3: Создать тестового бота с `image_prompt`**

Через `psql` — бот с заполненными `system_prompt` и `image_prompt`
(например «Ты — продавец кроссовок, опиши что на фото и предложи похожие
модели»).

- [ ] **Step 4: Скормить событие с реальной картинкой**

Либо реальный тестовый номер (сфотографировать что-то и отправить боту),
либо `XADD` в `wa:in` с `storage_key`, указывающим на файл, заранее
положенный в `/data/media/...` внутри volume (`docker compose exec gateway
sh -c "..."` для копирования тестового jpeg в примонтированный путь).

- [ ] **Step 5: Свериться**

`wa:out` содержит осмысленный (не заглушечный) текст;
`usage_events` пополнился строкой с ненулевыми токенами;
`messages` содержит ответ ассистента с реальным текстом vision-модели.

- [ ] **Step 6: Обновить память проекта**

Обновить [[stage1-core-progress]]: 2.1 закрыт, следующий пункт Волны 1 —
2.2–2.3 (STT).
