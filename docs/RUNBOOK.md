# RUNBOOK.md — эксплуатация прод-стенда

Минимальный ранбук для этапа STAGE1_CORE Блок 3, п.3 (деплой). Разрастётся
по мере эксплуатации (метрики, алерты — Волна 1, FEATURES.md 8.6).

## Первый деплой

1. На сервере: `git clone`, затем `.env` рядом с `compose/` — **не из
   репозитория** (ADR-007). Обязательные переменные — см.
   `.env.example` и `compose/docker-compose.prod.yml` (там, где
   `${VAR:?...}`, деплой откажется стартовать без неё): `POSTGRES_USER`,
   `POSTGRES_PASSWORD`, `POSTGRES_DB`, `OPENAI_API_KEY`, `JWT_SECRET`,
   `PLATFORM_OWNER_EMAIL`, `PLATFORM_OWNER_PASSWORD` (роли и доступы,
   FEATURES.md 6.18 — `PLATFORM_OWNER_EMAIL`/`PLATFORM_OWNER_PASSWORD`
   заводят первого владельца платформы при пустой таблице `users`),
   `SITE_ADDRESS` и `ACME_EMAIL` (HTTPS через Caddy — см. раздел «HTTPS и
   доступ без домена» ниже).
   Опционально — `TELEGRAM_BOT_TOKEN` (только если у бота включена тулза
   `send_telegram_lead`, FEATURES.md 4.7); без неё тулза возвращает боту
   текст ошибки, деплой не ломается.
2. `docker compose -f compose/docker-compose.prod.yml up -d --build`.
3. Миграции — из любого контейнера с установленным `db` (например,
   `worker`): `docker compose -f compose/docker-compose.prod.yml exec worker
   sh -c "cd /app/libs/db && python -m alembic upgrade head"` (флаг `-c` с
   абсолютным путём к `alembic.ini` не использовать через git-bash на
   Windows-хосте — путь искажается MSYS; `cd` в директорию — надёжный обход).
4. Войти в кабинет — `https://<SITE_ADDRESS>/login` с `PLATFORM_OWNER_EMAIL`/
   `PLATFORM_OWNER_PASSWORD` из `.env`, создать первого бота на `/bots/new`
   (онбординг из UI, FEATURES.md 6.20).
5. QR — на странице бота (`/bots/{id}`), отсканировать с телефона клиента.
   Запасной путь без публичного адреса (Caddy не поднялся, нет сертификата) —
   SSH-туннель: `ssh -L 3000:localhost:3000 -L 8000:localhost:8000
   user@server`, затем `http://127.0.0.1:3000`. Cookie сессии в проде
   помечается `Secure`: по `http://127.0.0.1` браузер её принимает (localhost
   считается безопасным контекстом), а по `http://<IP сервера>` вход молча не
   сработает — только через HTTPS.

## HTTPS и доступ без домена

Публичная точка входа — сервис `caddy` (`infra/caddy/Caddyfile`): сам получает
и продлевает сертификат Let's Encrypt, проксирует всё на `admin-web`. Наружу
открыты только порты 80 и 443; `api`, `gateway`, `postgres`, `redis` публично
недоступны (api и admin-web слушают лишь `127.0.0.1`).

**Пока своего домена нет** — `SITE_ADDRESS=<ip-через-дефисы>.sslip.io`. Сервис
sslip.io резолвит любое имя с IP внутри в этот IP, поэтому для сервера
`203.0.113.10` адрес — `203-0-113-10.sslip.io`, регистрировать ничего не нужно.
`ACME_EMAIL` — любой рабочий ящик (Let's Encrypt шлёт на него предупреждения
об истечении).

**Когда появится домен** — A-запись на IP сервера, в `.env` меняется только
`SITE_ADDRESS`, затем `docker compose -f compose/docker-compose.prod.yml up -d
caddy`. Старый адрес перестанет отвечать, других правок не нужно.

**Требования к серверу:** файрвол пропускает 22, 80 и 443 (и в `ufw`, и в
Cloud Firewall DigitalOcean, если он включён). Порт 80 нужен для выдачи
сертификата, даже если пользоваться будете только HTTPS.

**Сертификат не выдаётся** — `docker compose -f compose/docker-compose.prod.yml
logs caddy`: чаще всего закрыт порт 80/443 или `SITE_ADDRESS` не совпадает с IP
сервера. Том `caddy-data` хранит выпущенные сертификаты — не удалять
(`down -v`): у Let's Encrypt есть лимиты на повторные выпуски одного имени.

## Логи

Все сервисы пишут в stdout, смотреть — `docker compose -f
compose/docker-compose.prod.yml logs <сервис> --tail=200` (добавить `-f`, чтобы
следить). Docker хранит логи в json-файлах с ротацией: 5 файлов по 10 МБ на
контейнер (`x-logging` в `docker-compose.prod.yml`), то есть не больше ~50 МБ на
сервис, старые строки отбрасываются. Это значит, что `logs` показывает только
хвост — для разбора инцидента недельной давности логов уже нет, нужен
Loki/централизованный сбор (FEATURES.md 8.6, не сделан). Лимит действует на
контейнер при создании: после правки значений нужен `up -d` (пересоздание), а не
просто `restart`.

## Вход заблокирован («Слишком много попыток входа»)

Лимит попыток входа (FEATURES.md 6.21): 5 попыток на email и 20 на IP за
15 минут, считаются и неверные, и верные. Обычно достаточно подождать — окно
закрывается само, срок указан в сообщении.

**Нужно пустить человека сразу** (например, клиент опечатался несколько раз и
звонит):

```bash
docker compose -f compose/docker-compose.prod.yml exec redis sh -c \
  'redis-cli --scan --pattern "login:attempts:*" | xargs -r redis-cli del'
```

Сбрасывает все счётчики разом (и по email, и по IP). Ключ по email хранится как
sha256 от адреса, так что по имени ключа учётку не найти — только сбросить всё.

**Подозрение на перебор** — посмотреть, с каких адресов идут попытки:

```bash
docker compose -f compose/docker-compose.prod.yml exec redis sh -c \
  'for k in $(redis-cli --scan --pattern "login:attempts:ip:*"); do echo "$k $(redis-cli get $k)"; done'
```

Адрес с большим счётчиком закрывается на файрволе сервера (`ufw deny from <ip>`).

## Обновление стенда

Порядок важен: **миграция — до того, как новый код начнёт её использовать**.
Обратный порядок (рестарт сервисов раньше миграции) — источник силентных
сбоев: новый код падает на "relation does not exist" при первом же
обращении к новой таблице/колонке, исключение перехватывается общим
`except Exception` в пайплайне (`_process_entry`), клиент не получает
ответа без единой явной ошибки в логах, которую легко пропустить. Так
работали бы, например, `image_prompt`/`pdf_prompt` (Волна 1) и
`tool_bindings` (Волна 2) при обновлении в обратном порядке.

1. `git pull` (или обновить код иным способом).
2. Собрать новые образы, не трогая работающие контейнеры:
   `docker compose -f compose/docker-compose.prod.yml build`.
3. Прогнать миграцию НА НОВОМ образе в одноразовом контейнере — старые
   `worker`/`api`/`celery` продолжают работать со старой схемой, пока это
   выполняется:
   `docker compose -f compose/docker-compose.prod.yml run --rm worker
   sh -c "cd /app/libs/db && python -m alembic upgrade head"` (обход
   git-bash + `-c` — см. "Первый деплой", шаг 3).
4. Только теперь пересоздать контейнеры на новых образах:
   `docker compose -f compose/docker-compose.prod.yml up -d`.

Это безопасно именно потому, что миграции проекта только additive (новая
таблица или nullable-колонка, см. DECISIONS.md) — старый код (ещё не
рестартованный на шаге 4) просто не знает о новой таблице/колонке и
продолжает работать как раньше, пока схема уже готова к моменту, когда
новый код её увидит.

## Ночной бэкап БД

`infra/backup/backup.sh` — `pg_dump` контейнера `postgres` в файл (gzip) +
ротация бэкапов старше `RETENTION_DAYS` (дефолт 14 дней). Переменные —
из `.env` рядом с репозиторием на сервере.

Строка для `crontab -e`:

```cron
0 3 * * * /opt/platform/infra/backup/backup.sh >> /var/log/platform-backup.log 2>&1
```

(путь `/opt/platform` — пример; поправить под реальное расположение
репозитория на сервере). Куда льются бэкапы — `BACKUP_DIR` (дефолт
`<репозиторий>/backups`), стоит держать вне диска с самой БД или
периодически синкать на отдельное хранилище — здесь этого шага нет,
это уже вне обязательного минимума STAGE1_CORE.

## Восстановление из бэкапа

```bash
gunzip -c backups/<файл>.sql.gz | docker compose -f compose/docker-compose.prod.yml exec -T postgres psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

## Ручной возврат чата боту (handoff)

Если авто-релиз (`settings.auto_release_minutes`, дефолт 30 мин) ждать не
нужно: `POST /bots/{id}/chats/{chatId}/release` через тот же SSH-туннель.
Ручка, как и все bot-scoped роуты, требует `Authorization: Bearer <token>`
(FEATURES.md 6.18) — сначала логин:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"'"$PLATFORM_OWNER_EMAIL"'","password":"'"$PLATFORM_OWNER_PASSWORD"'"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

curl -X POST http://127.0.0.1:8000/bots/{id}/chats/{chatId}/release \
  -H "Authorization: Bearer $TOKEN"
```

## Сессия бота застряла (не открывается после рестарта gateway)

Симптом: `/dashboard` (владелец платформы) показывает бота со статусом,
отличным от «Подключён», дольше нескольких минут — `connecting`/
`reconnecting` не проходит в `open`, хотя номер точно был привязан
(`phone` заполнен).

**Известная причина** (2026-09-12): частые/прерванные реконнекты gateway
(например, несколько рестартов подряд за короткое время — при деплое,
crash-loop, нестабильной сети) иногда доводят Signal-сессию до состояния,
из которого Baileys сам не восстанавливается — в логах gateway это видно
как повторяющееся `bad decrypt`/`SessionError: No session record` при
попытке синхронизировать состояние (`critical_unblock_low` и т.п. в
`resyncing ... from vN`). Это ограничение самого протокола/библиотеки
(Baileys неофициальная, ADR-001), не баг конкретной фичи — автоматического
восстановления для этого случая в коде сознательно нет (см.
FEATURES.md — риск ошибочно разлогинить здоровую сессию, реагируя не на
тот сигнал, выше риска подождать и почитать логи вручную).

**Что делать:**
1. Смотреть логи gateway (`docker compose logs gateway --tail=100`) — если
   там `bad decrypt`/повторяющийся `watchdog: session stale, forcing
   reconnect` без успешного `opened connection to WA` между ними, само
   не пройдёт.
2. Разлогинить и привязать заново: `POST /bots/{id}/logout`, затем новый
   QR (`GET /bots/{id}/qr` в кабинете) — сессия создаётся с нуля, старое
   повреждённое состояние Signal-сессии не переносится.
3. Обычный (не зациклившийся) рестарт gateway — не эта проблема: с
   2026-09-12 gateway сам поднимает уже привязанные боты при старте без
   QR (`services/gateway/src/db/bots.ts::listLinkedBotIds`, условие —
   `bot_sessions.phone IS NOT NULL`). Если после ОДНОГО чистого рестарта
   бот не поднялся — это либо сетевая проблема до WhatsApp, либо именно
   зацикленный случай выше, не путать с более ранним багом (тот
   проверял несуществующий на практике Baileys-флаг `registered` и не
   поднимал НИ ОДНОГО бота вообще — уже исправлено).
