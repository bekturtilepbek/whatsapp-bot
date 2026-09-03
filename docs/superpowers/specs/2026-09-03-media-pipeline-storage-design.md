# Медиа-пайплайн: лимит размера (1.9) + Storage-интерфейс (2.7)

**Статус:** approved · 2026-09-03
**Волна:** Волна 1, первая архитектурная итерация (объединяет пункты 1.9 и 2.7 из
`docs/FEATURES.md` — они делят один поток данных и не проектируются раздельно).

## Контекст

STAGE1_CORE Блоки 1–3 закрыты: пайплайн диалога работает, но медиа — только
заглушка. `gateway` (Baileys/TS) сейчас лишь классифицирует `media_type` в
событии `inbound.text`; байтов содержимого нигде нет. `worker` (Python) не
видит и не может увидеть содержимое медиа — у него нет ключей сессии Baileys,
скачать и расшифровать файл с CDN WhatsApp может только gateway.

Из этого следует, что 1.9 («лимит размера входящего медиа, проверка до
скачивания») нельзя спроектировать в отрыве от 2.7 («Storage-интерфейс») —
оба вопроса про один и тот же путь байтов от gateway к worker.

Эта итерация закрывает 1.9 и 2.7. Собственно обработка медиа (vision/STT/PDF,
пункты 2.1–2.4) — предмет следующих итераций Волны 1 и в объём не входит:
здесь медиа только скачивается, лимитируется и сохраняется со ссылкой в БД;
ответ клиенту остаётся существующим fallback-текстом (FEATURES 2.6, без
изменений).

## Решение

### 1. Поток данных

Gateway скачивает и расшифровывает медиа через Baileys, сразу загружает в
storage и кладёт в событие `wa:in` ссылку (`storage_key`) вместо самих байтов.
Worker при необходимости читает файл из storage по этой ссылке.

Отклонённая альтернатива: worker дёргает gateway по HTTP за медиа в момент
реальной обработки (ленивая загрузка). Отклонено — превращает Redis Streams в
неполный транспорт (нужен синхронный HTTP-путь worker→gateway в дополнение к
шине), не даёт архивации медиа бесплатно, worker подвержен сетевым сбоям CDN
WhatsApp через прокси gateway при каждом ретрае.

### 2. Контракт событий

`docs/contracts/events.schema.json`, определение `inboundText` — три новых
nullable-поля:

```json
"storage_key": { "type": ["string", "null"] },
"mime_type": { "type": ["string", "null"] },
"size_bytes": { "type": ["integer", "null"] }
```

Не обязательные (`required` не меняется). Синхронно обновляются
`services/gateway/src/contracts/events.ts` (zod, `.nullable().optional()`) и
Pydantic-модель в `libs/core/src/core/events.py`.

**Семантика:** `media_type` задан, `storage_key` = `null` — медиа не
скачано (лимит превышен или сбой). Worker трактует это как раньше: ветка
`_reply_with_media_fallback` (FEATURES 2.6), без изменений в её коде. Отдельного
кода причины в контракте нет — причина остаётся в логах gateway (структурный
лог с `reason`), это сознательно минимальный контракт: агрегация причин —
задача метрик (8.6), не этой итерации.

### 3. Storage-абстракция (2.7)

Не единый кросс-языковой интерфейс, а по одному интерфейсу на язык — пишет
только gateway, читает только worker, общий контракт между ними — ключ
объекта и содержимое, не API:

- `services/gateway/src/storage/types.ts` — `interface Storage { put(key: string, bytes: Buffer, mimeType: string): Promise<void> }`
  реализации `filesystem.ts`, `s3.ts`.
- `libs/integrations/src/integrations/storage/` — `Storage` протокол с
  `get(key: str) -> bytes`, реализации `filesystem.py`, `s3.py`. Новый пакет
  `libs/integrations` (первый в этой директории), ставится `pip install -e`
  как остальные `libs/*`.

Выбор реализации — `STORAGE_DRIVER=fs|s3`, одинаково на обеих сторонах.
Ключ объекта: `bots/{bot_id}/media/{wa_msg_id}` (расширение не добавляем —
`mime_type` уже есть рядом в БД/событии, не нужно доставать из имени).

**Dev:** `fs`-драйвер, общий docker-volume, примонтированный в `gateway` и
`worker` (`media-data:/data/media` в `compose/docker-compose.dev.yml`). Без
отдельного MinIO-контейнера — на машине разработчика хронически мало места
([[windows-docker-gotchas]]), а `fs`-драйвер — это то же самое, что делала V1
(`static/` на диске), просто расшаренное между двумя контейнерами через volume.

**Prod:** `s3`-драйвер → DO Spaces, `S3_ENDPOINT/S3_BUCKET/S3_ACCESS_KEY/
S3_SECRET_KEY/S3_REGION` в `.env` на сервере (ADR-007, секреты не в репозитории).
TS — `@aws-sdk/client-s3`, Python — `boto3`. Оба клиента настраиваются с
таймаутом на запрос (грабля «любой внешний вызов — с таймаутом»).

### 4. Gateway-флоу (1.9)

Новый модуль `services/gateway/src/media/download.ts`, вызывается из
`normalize/inbound.ts` там, где сейчас определяется `media_type`:

1. Достаём `fileLength` из протобаф-сообщения Baileys (есть до сети, до
   `downloadContentFromMessage`).
2. Запрашиваем лимит бота: `SELECT settings FROM bots WHERE id=$1`,
   `settings.media_max_size_bytes` (default `16 * 1024 * 1024`). По конвенции
   проекта лимиты — per-bot настройка (`bots.settings`), не константа в коде.
3. `fileLength > лимита` → скачивание не начинаем вовсе. Событие уходит без
   `storage_key/mime_type/size_bytes`. Структурный лог
   `{event: "media_skipped", reason: "too_large", bot_id, fileLength, limit}`.
4. Иначе — `downloadContentFromMessage` (таймаут через `Promise.race` или
   AbortSignal) → `storage.put()` (таймаут в самом клиенте). Любая ошибка на
   этом отрезке (сеть CDN, storage недоступен) — тот же исход: событие без
   `storage_key`, лог `{event: "media_skipped", reason: "download_failed" | "upload_failed", error}`.
   Пайплайн приёма сообщений не блокируется и не падает — деградация к
   существующему fallback-тексту.
5. Успех — событие несёт `storage_key`, `mime_type` (из протобаф-сообщения,
   Baileys его знает), `size_bytes` (= фактический скачанный размер).

Запрос лимита к БД — по одному на медиа-сообщение (не на каждое сообщение),
без кеша: тот же паттерн простоты, что у worker (`get_bot` читается заново на
каждое событие, кеша нет нигде в пайплайне пока).

### 5. Worker + БД

Миграция Alembic: `messages.media_ref JSONB NULL`, без `server_default`
(отсутствие = не медиа-сообщение). Заполняется в `insert_incoming`, когда в
событии есть `storage_key`:

```json
{"storage_key": "...", "mime_type": "...", "size_bytes": 123456}
```

JSONB, а не три отдельные колонки — совпадает с полем `media_ref` из
`docs/ARCHITECTURE.md` §5, и оставляет место для будущих полей (превью,
длительность аудио для 2.2/2.3) без новой миграции под каждое.

Обработка самого содержимого (чтение из storage, vision/STT/PDF) — вне этой
итерации. Ответ клиенту остаётся `_reply_with_media_fallback` независимо от
того, есть `storage_key` или нет — это осознанно: канал для будущих итераций
готов, поведение бота пока не меняется.

### 6. Конфигурация

Новые env-переменные, добавляются в `compose/docker-compose.dev.yml` (fs) и
`compose/docker-compose.prod.yml` (s3):

- `STORAGE_DRIVER=fs|s3`
- `STORAGE_FS_ROOT=/data/media` (только для `fs`)
- `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`
  (только для `s3`, из `.env` на сервере)

Per-bot: `bots.settings.media_max_size_bytes` (default 16 МБ), мержится по
существующей конвенции (не перезаписывает остальные настройки).

## Тестирование

- **Gateway (vitest):** `fileLength` сверх лимита → `storage.put` не
  вызывается, событие без `storage_key`; успешный путь → `put` вызван с
  ожидаемым ключом, событие несёт все три поля; сбой `downloadContentFromMessage`
  / `storage.put` → событие без `storage_key`, пайплайн не бросает исключение.
- **Worker (pytest):** событие с `storage_key` → `messages.media_ref`
  заполнен ожидаемым JSON; событие без него → поведение не отличается от
  текущего (регрессия на существующий `test_media_fallback.py`).
- **Живой прогон** (по [[live-verification-preference]]): в конце блока —
  `docker compose up`, реальное медиа-сообщение (фото) через тестовый номер
  ИЛИ прямой `XADD` в `wa:in` с руками собранным событием, свериться, что
  файл лёг в `STORAGE_FS_ROOT` и `messages.media_ref` заполнен.

## Границы (в эту итерацию не входит)

- Чтение и обработка медиа воркером (vision/STT/PDF) — 2.1–2.4, следующие
  итерации Волны 1.
- Метрики/алерты по пропущенным медиа (8.6) — позже, лог уже структурный,
  агрегация будет тривиальной.
- Retention/удаление медиа из storage (9.9) — вне скоупа Волны 1 по
  `docs/FEATURES.md` («Скоуп и порядок работ»).
