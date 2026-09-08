# ARCHITECTURE.md — платформа WhatsApp-ботов

## 1. Что строим

Мультитенантная платформа WhatsApp-ботов для SMB: клиент подключает номер по QR,
настраивает промпт и товары в кабинете — бот отвечает покупателям через LLM, отправляет
товары, принимает брони, передаёт диалог менеджеру и забирает обратно.

Greenfield-проект, один разработчик; основной инструмент разработки — Claude Code.
Архитектура выведена из уроков
прошлой версии продукта (см. ADR в `DECISIONS.md`); архив старого кода хранится
вне репозитория как справочник поведения V1-фич.

Главный принцип: **один код и одна инсталляция на всех клиентов. Бот — запись в БД.**

## 2. Стек (утверждено)

| Слой | Технология |
|------|-----------|
| Транспорт WhatsApp | **Baileys** (TypeScript, Node 22) — протокольная библиотека, без браузера |
| Ядро | **Python 3.12**: FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 |
| БД | **PostgreSQL 17 + pgvector** — единая, `bot_id` в каждой таблице |
| Шина событий | **Redis 7 Streams** (`wa:in` / `wa:out`, consumer groups) |
| Отложенные и периодические задачи | **Celery** (broker и backend — тот же Redis) + celery beat |
| Фронтенд кабинета | **Next.js 15** — минимальный UI сейчас, редизайн позже (ADR-009) |
| Python-пакеты | классический pip + venv, `libs/*` через `pip install -e` |
| Качество | ruff, mypy strict, pytest + testcontainers; eslint, vitest |
| Инфра | Docker Compose, GitHub Actions → GHCR → SSH-деплой; без k8s (ADR-004) |
| Наблюдаемость | structlog → Loki, prometheus-client → Grafana, алерты в Telegram, Sentry |
| Секреты | `.env` только на серверах, GitHub Secrets в CI |

Граница языков = граница сервисов: TypeScript только в gateway (~1–1.5 тыс. строк),
всё остальное — Python.

## 3. Архитектура

```
                WhatsApp (WebSocket, multi-device)
                          ▲   ▲
                ┌─────────┴───┴──────────┐
                │  gateway (Node/TS)     │  Baileys; десятки сессий на инстанс;
                │  auth-state в Postgres │  НЕ содержит бизнес-логики
                └──────┬─────────▲───────┘
         XADD wa:in ── │         │ ── XREADGROUP wa:out
                       ▼         │
                ┌────────────────┴───────┐
                │        Redis           │  Streams · дедуп · локи ·
                │                        │  handoff-state · брокер Celery
                └──────┬─────────▲───────┘
                       ▼         │
        ┌──────────────────────┐ │  ┌──────────────────────────┐
        │  worker (Python)      │ │  │  celery worker + beat     │
        │  async-консюмер wa:in │ │  │  follow-up, авто-релиз,   │
        │  пайплайн + LLM+тулзы │ │  │  кампании, бэкапы, cron   │
        └──────┬────────▲───────┘ │  └───────────┬──────────────┘
               ▼        │         │              │
        ┌───────────────────────────────────────────┐
        │  PostgreSQL + pgvector                     │
        └───────────────────────────────────────────┘
                       ▲
               ┌───────┴────────┐       ┌─────────────┐
               │  api (FastAPI) │◄──────┤  admin-web  │
               └────────────────┘       └─────────────┘
```

### Роли сервисов

**gateway** — «телефонная станция»: держит WebSocket-сессии и ключи Signal/Noise,
нормализует события в единый JSON и кладёт в `wa:in`; читает `wa:out` и отправляет.
Ноль бизнес-логики. Деплой логики не трогает сессии.

**worker** — stateless async-консюмер `wa:in`. Пайплайн: дедуп → фильтры (группы,
чёрный список, график, пауза) → батчинг → медиа → контекст → LLM + tool loop →
исходящие (typing, разбиение, ретраи). Реплик может быть сколько угодно.

**celery worker + beat** — только отложенное и периодическое: follow-up, авто-релиз
handoff, шаги кампаний с джиттером, бэкапы, чистка retention. Диалоговый пайплайн
через Celery НЕ ходит.

**api** — CRUD ботов/промптов/товаров/кампаний, QR-статусы, роли, аудит.
**admin-web** — кабинет: владелец платформы видит всё, клиент — только своего бота.

### Ключевые механики

- **Контракт событий** — `docs/contracts/events.schema.json` (JSON Schema) — единый
  источник истины; из него — Pydantic-модели (Python) и zod-схемы (TS). Версионируется.
- **Порядок в диалоге**: consumer group + Redis-лок с TTL на `conversation_id`.
  Один диалог — строго последовательно, разные — параллельно.
- **Дедуп**: `SET wa:seen:{msg_id} NX EX 86400` + UNIQUE `(bot_id, wa_msg_id)` в БД.
  Проверка и пометка — до любого await.
- **Отложенные задачи** — Celery `apply_async(eta=...)`. Задача при срабатывании
  **перепроверяет актуальность условия** (клиент написал? менеджер ответил? → no-op);
  `revoke` — только оптимизация, на него не полагаемся (ненадёжен при рестартах с eta).
- **Auth-state сессий — в Postgres** → сессия поднимается на любом узле без QR.
- **Транспорт за интерфейсом** `WhatsAppTransport` — Baileys заменяем на Cloud API
  или whatsmeow без переписывания логики.
- **Идемпотентность исходящих**: `client_msg_id` генерирует worker, gateway не отправляет
  дубликат при ретрае.

## 4. Структура репозитория

```
platform/
├── CLAUDE.md
├── Makefile                        # dev, test, lint, migrate
├── docs/
│   ├── ARCHITECTURE.md  FEATURES.md  DECISIONS.md  RUNBOOK.md
│   └── contracts/events.schema.json
├── services/
│   ├── gateway/                    # TS: src/{session,bridge,normalize,http}/
│   ├── worker/                     # Python: src/worker/{main.py,pipeline/,handoff/}
│   ├── celery/                     # Python: src/tasks/{followup,handoff,campaigns,maintenance}.py
│   ├── api/                        # FastAPI: src/api/{routers,schemas,services,security}/
│   └── admin-web/
├── libs/                           # общие пакеты, ставятся pip install -e
│   ├── core/                       # доменные типы, конфиг, события (Pydantic из схемы)
│   ├── db/                         # модели SQLAlchemy + Alembic
│   ├── llm/                        # клиент OpenAI, tool registry, токены/стоимость
│   ├── tools/                      # products, telegram_lead, documents, booking_*
│   └── integrations/               # sheets, telegram, stt, storage (S3)
├── compose/                        # docker-compose.dev.yml / .prod.yml
├── infra/                          # nginx, бэкапы, provisioning
└── .github/workflows/
```

Конвенции: тулза = модуль в `libs/tools/`, включается записью в `tool_bindings`;
ничего per-bot в коде — только в БД; миграции только Alembic; Conventional Commits.

## 5. Схема данных (ядро)

```
tenants              (клиенты-владельцы ботов)
bots                 (tenant_id, name, timezone, enabled, settings JSONB, transport, model)
bot_sessions         (bot_id, auth_state JSONB, phone, linked_at, last_seen)
prompt_versions      (bot_id, kind: main|image|pdf, body, author, created_at)
contacts             (bot_id, wa_id, lid, phone, name, temperature, summary,
                      manager_status)                     -- UNIQUE(bot_id, wa_id)
messages             (bot_id, contact_id, role, content, wa_msg_id, media_ref,
                      tokens_in, tokens_out, ts)          -- UNIQUE(bot_id, wa_msg_id)
                                                          -- INDEX(contact_id, ts DESC)
blocked_contacts     (bot_id, phone)
products             (bot_id, name, price, sku, description, display_custom JSONB)
product_images       (product_id, storage_key, position)
product_embeddings   (product_id, embedding vector(1536))
documents            (bot_id, filename, storage_key, mime_type)
campaigns            (bot_id, kind, payload, status, limits JSONB)
campaign_targets     (campaign_id, contact_id, status, sent_at, delivered_at, read_at)
tool_bindings        (bot_id, tool_name, config JSONB)
usage_events         (bot_id, model, tokens_in, tokens_out, cost, ts)
audit_log            (actor, bot_id, action, payload, ts)
```

Вертикали броней (номера, шахматка, слоты) — в отдельных Postgres-схемах.

## 6. План работ (соло)

Фазы идут последовательно; контракт событий фиксируется в Фазе 0 и расширяется по
мере надобности. Гранулярность работы — одна фича из FEATURES.md за итерацию
Claude Code, с тестом.

| Фаза | Содержание | ≈ |
|------|-----------|---|
| **0. Каркас** | Репозиторий, структура, dev-compose (PG+Redis+заглушки), контракт событий v1, модели БД + первая миграция, Makefile, CI | ~1 нед |
| **1. Транспорт** | Gateway на Baileys: сессии, QR, auth-state в PG, реконнект, watchdog, bridge в Streams, идемпотентная отправка | 2 нед |
| **2. Ядро диалога** | Консюмер, дедуп, фильтры, батчинг, история, контекст, LLM + tool loop, исходящие. Тесты на фейковом транспорте | 2–3 нед |
| **3. Медиа, тулзы, handoff** | Vision, STT (вкл. `kir`), PDF; товары + pgvector; telegram-лиды; документы; handoff + Celery-задачи (follow-up, авто-релиз) | 2–3 нед |
| **4. Кабинет** | api + фронт: QR, промпты с версиями, настройки, товары, чёрный список, переписка, роли, аудит | 2–3 нед |
| **5. Эксплуатация** | Метрики, алерты, бэкапы, staging с тестовым номером | 1–2 нед |

Фазы 3 и 4 допустимо перемежать (сделал тулзу → сразу экран под неё). Работа в
своём темпе, без жёсткого дедлайна; детальный скоуп и волны — в FEATURES.md,
этап живого ядра — в STAGE1_CORE.md. Рассылки — вне скоупа до реализации
анти-бан-дисциплины.

Milestone-критерии: Ф1 — тестовый номер гоняет сообщение туда-обратно через Streams;
Ф2 — бот отвечает end-to-end; Ф3 — паритет по приоритету «MVP» из FEATURES.md;
Ф4 — клиент обслуживает бота сам; Ф5 — Grafana показывает живость сессий, алерты приходят.

## 7. Размещение

Старт — **один узел** (4–8 ГБ): все сервисы в одном compose. Сессия Baileys ≈ 50 МБ,
десятки ботов на узле — не проблема. Рост: первым выносится gateway на отдельный узел
(auth-state в общей БД делает перенос сессий рестартом, без QR), затем реплика worker.
Бэкапы: nightly `pg_dump` + auth-state в S3-совместимое хранилище.
