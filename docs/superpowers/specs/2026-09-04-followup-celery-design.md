# Follow-up напоминания через Celery (FEATURES.md 5.5)

**Статус:** approved · 2026-09-04

**Волна:** Волна 1. Первое появление `services/celery` — новый сервис,
до этого существовал только в структуре ARCHITECTURE.md §4.

## Контекст

Бот отвечает клиенту и замолкает — если клиент не отвечает N минут, стоит
напомнить о себе. В V1 (архив `webhook_wb.zip`, `whatsapp.js`) это был
`setTimeout` в памяти процесса: работал, но умирал при каждом деплое/рестарте
(грабля, зафиксированная в CLAUDE.md: "Никаких таймеров в памяти. Только
Celery apply_async(eta=...)"). ADR-003 уже выбрал Celery поверх Redis для
ровно этого класса задач.

**Эталон поведения (V1, `whatsapp.js`):**
- После отправки ответа клиенту — таймер на `reminder_delay_minutes`
  (настройка бота, по умолчанию 60 мин), если `reminder_enabled`.
- Клиент написал что угодно до срабатывания — таймер отменяется
  (`clearTimeout`, в начале обработки любого нового входящего от клиента).
- При срабатывании — повторная проверка: активен ли ручной handoff (если
  да — не слать), закрыта ли «воронка» (`funnel_completed` — поле из
  бронирования, у нас нет и не будет: 4.11/4.12 вне скоупа). Текст —
  `reminder_message` (настройка бота), отправка — как обычное сообщение
  ассистента, с записью в историю.

**Решённые в чате отклонения от V1:**
1. `funnel_completed` — не переносим, эквивалента нет и не будет, пока не
   появится букинг. Проверяем только handoff.
2. Триггер — только настоящие LLM-ответы (`_reply`, `_reply_with_vision`).
   Медиа-заглушка (`_reply_with_media_fallback`, FEATURES 2.6) не планирует
   напоминание — бот там ничего не понял, дожимать клиента нечем.

## Решение

### 1. Отмена таймера — НЕ через revoke

V1-подход "clearTimeout при новом сообщении" не переносится буквально:
`revoke` в Celery — оптимизация, не гарантия (ADR-003, CLAUDE.md). Вместо
отмены — задача при срабатывании **сама перепроверяет**, было ли за время
ожидания новое сообщение от клиента: сравнивает `Message.seq` на момент
планирования с текущим состоянием истории контакта. Если появилась более
новая строка с `role='user'` — клиент уже написал, тихо выходим.

`seq` (монотонный `IDENTITY`, добавлен для `messages` в предыдущей итерации
этой же сессии — см. `202609041003_messages_seq`) для этого подходит
идеально: `after_seq` = seq только что вставленного ответа ассистента;
на срабатывании — `SELECT 1 FROM messages WHERE contact_id=? AND role='user'
AND seq > after_seq LIMIT 1`.

### 2. Разделение кода: `libs/scheduling` (конфиг) vs `services/celery` (задачи)

Инстанс Celery-приложения — в новом `libs/scheduling` (не в `libs/core`,
чтобы не тащить `celery` со всеми зависимостями в `services/api`, которому
это не нужно; не в `services/celery`, чтобы `services/worker` мог
ставить задачи в очередь без импорта из чужого сервиса — та же граница,
что уже проведена между transport/pipeline/tasks в ARCHITECTURE.md §3).

```
libs/scheduling/src/scheduling/
  celery_app.py   # celery_app = Celery("platform", broker=REDIS_URL, backend=REDIS_URL)
  task_names.py   # FOLLOW_UP_REMINDER = "tasks.followup.send_reminder" — общая
                   # константа, чтобы имя не разъехалось между постановкой и
                   # регистрацией задачи

services/celery/src/tasks/
  __init__.py     # from scheduling.celery_app import celery_app as celery  (Celery
                   # -A tasks ищет атрибут `celery` в пакете) + `from . import followup`
                   # (регистрирует @celery_app.task при импорте пакета)
  followup.py     # сама задача
```

`services/worker` зависит от `scheduling` (только конфиг + имя задачи,
без реализации), ставит задачу через `celery_app.send_task(name, args, eta=...)`
— имени задачи достаточно, реализацию (`services/celery/tasks/followup.py`)
`worker` не импортирует и знать не должен.

### 3. Общий Redis-паблишер — `core.bus`

`services/celery` тоже должен слать в `wa:out` (typing + текст) — та же
логика, что уже есть в `services/worker/src/worker/bus.py::publish/make_redis`,
но она сервис-локальная (нельзя импортировать `worker.*` из `services/celery`
— та же граница сервисов). Выносим `make_redis`, `publish`, `IN_STREAM`,
`OUT_STREAM` в новый `libs/core/src/core/bus.py`; `worker/bus.py` реэкспортирует
их оттуда для обратной совместимости с уже существующими импортами
(`ensure_group`/`StreamEntry`/`read_group` — consumer-group чтение `wa:in` —
остаются в `worker/bus.py`, читает `wa:in` только он).

### 4. `insert_outgoing` возвращает `seq`

Единственная правка существующего API: `db.messages.insert_outgoing`
возвращает `int` (seq вставленной строки) вместо `None` — нужно
worker'у, чтобы передать `after_seq` в задачу. Три текущих вызывающих места
(`_reply`, `_reply_with_vision`, `_handle_manager_message`) не используют
возврат — не ломаются, меняются только те два, что реально ставят задачу.

### 5. Задача `send_reminder` (`services/celery/src/tasks/followup.py`)

Celery-таск — синхронная обёртка (`asyncio.run(...)`) вокруг async-тела:
тот же паттерн, что уже используется у остального Python-стека
(SQLAlchemy 2.0 async, `db.engine.make_engine`/`make_session_factory` —
переиспользуются как есть).

Порядок проверок при срабатывании (все — "перепроверка актуальности",
как требует ADR-003):
1. Бот существует и `enabled` — иначе no-op.
2. `bot.settings.reminder_enabled` всё ещё `True` — владелец мог выключить
   между постановкой и срабатыванием.
3. Handoff не активен (`redis.exists(handoff_key(bot_id, chat_id))` —
   `handoff_key` уже в `core.redis_keys`, дублировать `worker.pipeline.handoff`
   не нужно — там всего одна строка логики).
4. Нет более новой строки `role='user'` с `seq > after_seq` для этого
   `contact_id` — клиент уже написал.
5. Всё чисто → текст из `bot.settings.reminder_message` (дефолт как в V1) →
   `outbound.typing` + `outbound.text` в `wa:out` (тот же паттерн
   client_msg_id, что и `_send_reply`) → `insert_outgoing` (роль assistant,
   попадает в историю как обычный ответ бота — БЕЗ `usage_events`, вызова
   LLM не было, тот же принцип что и в медиа-заглушке 2.6).

### 6. Постановка задачи в worker'е

Новая функция в `services/worker/src/worker/pipeline/consumer.py`,
вызывается из `_reply` и `_reply_with_vision` сразу после `insert_outgoing`
(внутри уже существующего блока записи в БД, использует его `seq`):

```python
async def _schedule_follow_up(bot, chat_id, contact_id, after_seq) -> None: ...
```

Сбой постановки задачи (Redis/Celery недоступен) — не должен портить уже
успешно отправленный клиенту ответ и не должен маскироваться как "reply
pipeline failed" в общем `except` на уровне `_process_entry`: перехватываем
локально, `logger.warning`, не пробрасываем. Таймаут — `asyncio.wait_for`
(5с) вокруг `asyncio.to_thread(celery_app.send_task, ...)` (`send_task` —
синхронный вызов Celery/kombu, не блокировать event loop напрямую).

### 7. `services/celery` — Dockerfile, compose, без `beat`

Только worker-процесс Celery в этой итерации (`celery -A tasks worker`) —
`beat` нужен для ПЕРИОДИЧЕСКИХ задач (бэкапы, шаги кампаний), follow-up
ставится программно через `apply_async(eta=...)`, beat для этого не
требуется. Добавляем `beat` отдельным пунктом, когда появится первая
периодическая задача — не раньше (YAGNI).

`compose/docker-compose.dev.yml` — новый сервис `celery`, без healthcheck
(нет HTTP-эндпоинта, никто не ждёт его готовности через `depends_on`
— задачи копятся в Redis-очереди, пока воркер не поднимется, это и есть
устойчивость к рестартам, ради которой всё затевалось).

## Границы (в эту итерацию не входит)

- `celery beat` и периодические задачи (бэкапы, кампании) — отдельные
  пункты FEATURES.md, другая волна.
- `tasks/handoff.py` из наброска ARCHITECTURE.md §4 — авто-релиз handoff
  уже решён проще, через TTL самого Redis-ключа (`handoff.mark_manager_reply`
  ставит `SET ... EX`), отдельная Celery-задача для этого не нужна и не
  создаётся.
- `funnel_completed`-эквивалент — ждёт букинга (вне скоупа).
- `libs/scheduling`-тесты ограничены проверкой конфигурации приложения —
  сквозной интеграционный прогон задачи через реальный Celery-воркер
  делается живым прогоном (docker compose), не автотестом (Celery eager-mode
  тестирование в этой волне избыточно для одной задачи).
