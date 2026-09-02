# STAGE1_CORE.md — этап 1: живое ядро

Первый рабочий результат проекта: **один WhatsApp-бот на новой архитектуре в проде** —
отвечает клиентам через LLM по промпту, помнит историю, замолкает при вмешательстве
менеджера. Управление — через SQL/HTTP-ручки, UI появляется в Волне 3.

Жёсткого дедлайна нет; объём — три последовательных блока, каждый заканчивается
проверяемым результатом. Архитектура — строго по ARCHITECTURE.md §3
(gateway / worker / Redis Streams), без упрощений каркаса.

В этап НЕ входит (см. волны в FEATURES.md): медиа-обработка (vision/STT/PDF),
Celery и follow-up (авто-возврат handoff — Redis TTL), товары, кабинет, метрики
Prometheus (пока только structlog), чёрный список, рассылки (запрещены).

---

## Блок 1 — транспорт. Результат: эхо-бот с реального номера

1. Каркас: структура ARCHITECTURE.md §4 (без services/celery и admin-web),
   `compose/docker-compose.dev.yml` (postgres:17-pgvector, redis:7, gateway, worker),
   Makefile (dev/test/lint/migrate), git.
2. Контракт `docs/contracts/events.schema.json`, v1 — только:
   `inbound.text`, `outbound.text`, `outbound.typing`, `session.status`.
   Поля inbound: `bot_id, wa_msg_id, chat_id, sender_wa_id, sender_lid?, from_me,
   text, quoted_text?, media_type?, ts`. Поля outbound: `bot_id, chat_id, text,
   client_msg_id`.
3. `libs/db`: таблицы `bots` (id, name, enabled, system_prompt TEXT, timezone,
   settings JSONB), `bot_sessions` (auth-state JSONB). Alembic-миграция.
4. `services/gateway` (TS + Baileys): сессия на запись в `bots`; auth-state в
   `bot_sessions`; QR — `GET /qr/:botId` (PNG); реконнект с backoff + watchdog;
   `from_me`-события тоже публикуются (нужны для handoff); XADD в `wa:in`;
   консюмер `wa:out` → отправка; идемпотентность по `client_msg_id`
   (Redis SET NX EX 3600).
5. Временный echo-режим в worker: `wa:in` → тот же текст в `wa:out`.

## Блок 2 — мозг. Результат: осмысленный диалог по промпту

1. `libs/db`: `contacts` (bot_id, wa_id, lid, phone, name; UNIQUE(bot_id, wa_id);
   матчинг входящего: по wa_id ИЛИ lid, при первом появлении второго идентификатора —
   дозаписать в ту же строку, не создавать вторую), `messages` (bot_id, contact_id,
   role, content, wa_msg_id, ts; UNIQUE(bot_id, wa_msg_id); INDEX(contact_id, ts DESC)),
   `usage_events` (bot_id, model, tokens_in, tokens_out, cost, ts).
2. Пайплайн worker вместо echo, порядок строгий:
   дедуп (Redis SET NX EX 86400, до любого await) → игнор групп/broadcast →
   `bots.enabled` (при false — молчим, но историю пишем) → батчинг (Redis-буфер +
   debounce из `settings.batch_timeout_seconds`, дефолт 1) → лок диалога
   (Redis, TTL 60с) → история (24ч, max 50) → OpenAI (system = `bots.system_prompt`
   + текущее время в TZ бота) → typing → ответ → запись обеих сторон в `messages`
   → запись в `usage_events`.
3. Таймаут на каждый внешний вызов (OpenAI 60с, отправка 20с); ошибка → лог,
   лок снимается, сообщение ACK (ретраи LLM — Волна 1).
4. Медиа-заглушка: `media_type` ≠ text → ответ из `settings.media_fallback_text`
   (дефолт: «Пока я умею отвечать только на текстовые сообщения»), входящее
   помечается в истории как `[голосовое сообщение]` / `[фото]` и т.п.
5. Тесты (минимум, обязательны): дедуп-гонка; смоук пайплайна на фейковом
   транспорте (in → LLM-мок → out); батчинг склеивает два сообщения; матчинг
   контакта wa_id↔lid не создаёт дубль.

## Блок 3 — живой клиент. Результат: бот в проде

1. Handoff: `from_me`-событие без нашего `client_msg_id` (= менеджер писал руками)
   → `SET handoff:{bot}:{chat} EX <settings.auto_release_minutes*60>` (дефолт 12,
   продлевается каждым сообщением менеджера); пока ключ жив — пайплайн молчит,
   входящие пишутся в историю; сообщение менеджера — в историю ролью assistant
   с префиксом `[Ответ менеджера]`. Ручной возврат: `DELETE handoff-ключа` через
   API-ручку.
2. HTTP-ручки api (слушаем localhost, доступ через SSH-туннель; auth — Волна 3):
   `GET/PATCH /bots/{id}` (enabled, system_prompt, settings), `GET /bots/{id}/qr`,
   `POST /bots/{id}/logout`, `POST /bots/{id}/chats/{chatId}/release`.
3. Деплой: `compose/docker-compose.prod.yml`, `.env` на сервере; крон
   `pg_dump` в файл — обязателен.
4. Подключение боевого номера, прогон чек-листа приёмки.

## Чек-лист приёмки этапа

- [ ] диалог 5+ сообщений: история учитывается, батчинг склеивает
- [ ] дубль события не порождает второй ответ (входящий и исходящий)
- [ ] менеджер вмешался → бот молчит; после N минут тишины — снова отвечает;
      ручной release работает
- [ ] `enabled=false` → бот молчит, история пишется
- [ ] рестарт всех контейнеров: сессия жива без QR, диалог продолжается,
      контакт не задвоился
- [ ] голосовое/фото → заглушка, в истории пометка типа
- [ ] `usage_events` наполняется после каждого вызова LLM
- [ ] ключей и паролей нет в git

## Правила этапа

Одна задача из списка — одна итерация с коммитом; план блока утверждается до кода.
После приёмки этапа — Волна 1 из FEATURES.md.
