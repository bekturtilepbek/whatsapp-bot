# QR-экран (Волна 3, первый под-проект) — дизайн

**Статус:** approved · 2026-09-09
**Фичи FEATURES.md:** 6.1 (QR-подключение + динамическое обновление), 6.2 (отсоединение номера), 6.4 (вывод подключённого номера — включена как состояние того же экрана)

## Контекст

Волна 3 в целом — это §6 FEATURES.md целиком (кабинет), но это не одна фича,
а набор независимых экранов поверх общего фундамента. По решению пользователя
Волна 3 разбивается на упорядоченные под-проекты; первый — QR-экран.

На момент дизайна `services/admin-web` не существует вообще. Транспортная
часть уже готова и покрыта тестами:

- `services/gateway/src/main.ts` — `GET /qr/:botId` (отдаёт PNG через
  `sessions.waitForQr`, 504 если QR не готов за 20с), `POST /bots/:botId/logout`.
- `services/api/src/api/routers/bots.py` — `GET /bots/{id}/qr` и
  `POST /bots/{id}/logout` проксируют в gateway как есть (`_proxy_to_gateway`).
- `services/api/tests/test_gateway_proxy.py` — уже покрывает эту проксирующую пару.

Не хватает: списка ботов в api (сейчас только `GET /bots/{id}`), `phone`/
`linked_at` в ответе api (сейчас это только в таблице `bot_sessions`, наружу
не отдаётся) и самого admin-web.

## Явно отложено на потом (не в скоупе этой итерации)

- **6.18 роли/авторизация** — экран без auth, в том же периметре доверия,
  что и api сейчас (`bots.py`: «Без auth — доступ на проде через SSH-туннель»).
  Подтверждено пользователем: роли — отдельная итерация, которая
  переопределит этот периметр (вероятно, добавив BFF-слой поверх нынешнего
  прямого fetch — см. «Подход к данным» ниже).
- **6.20 онбординг бота из UI** — бот на эту итерацию создаётся вручную,
  SQL-инсертом. admin-web только показывает существующие записи `bots`.
- Технический долг Волн 1-2 (ретраи gateway, лимит исходящего медиа,
  санитизация имён файлов и т.д., см. память `deferred-items`) — не трогаем.

## Подход к получению данных

Рассмотрены три варианта, различающиеся тем, где живёт HTTP-фетч к api:

- **(A) Гибрид — выбран.** Server Component делает первичный SSR-фетч по
  внутреннему docker-адресу api; отдельный Client Component (`QrPanel`)
  держит цикл поллинга и стучится в api напрямую из браузера. Требует CORS
  на api и два адреса api (внутренний для SSR, публичный для браузера), но
  даёт мгновенный первый рендер без лишнего прокси-слоя.
- (B) Всё на клиенте — один env var, но без SSR (страница открывается
  пустой на долю секунды), и паттерн пришлось бы повторять на каждом
  следующем экране кабинета.
- (C) BFF через Next.js Route Handlers — без CORS и публичного API URL
  вообще, но лишний прокси-слой уже сейчас ради выгоды (единая точка
  будущей авторизации), которая наступит только в отдельной, ещё не
  спланированной итерации 6.18.

Подход A принят пользователем: минимум кода сейчас, стандартный паттерн
Next.js 15 App Router; переход на BFF (C) при появлении ролей — это
добавление прокси-слоя, а не переписывание `QrPanel`.

## Backend: изменения

### `libs/db/src/db/models.py`

`Bot` получает вычисляемые свойства, читающие уже существующий relationship
`Bot.session` (`BotSession | None`, one-to-one):

```python
@property
def phone(self) -> str | None:
    return self.session.phone if self.session else None

@property
def linked_at(self) -> datetime | None:
    return self.session.linked_at if self.session else None
```

### `libs/db/src/db/bots.py`

- `get_bot` — грузит `Bot` с `selectinload(Bot.session)` (иначе `MissingGreenlet`
  при обращении к `.session` в асинхронной сессии вне текущего awaitable-контекста).
- Новая `list_bots(session) -> Sequence[Bot]` — то же самое, `select(Bot).options(selectinload(Bot.session)).order_by(Bot.created_at)`.

### `services/api/src/api/schemas/bots.py`

`BotOut` получает `phone: str | None` и `linked_at: datetime | None` —
`from_attributes=True` подхватит новые properties модели без изменений в
router-коде, который уже делает `BotOut.model_validate(bot)`.

### `services/api/src/api/routers/bots.py`

Новый `GET /bots -> list[BotOut]`, вызывает `list_bots`.

### `services/api/src/api/main.py`

`CORSMiddleware`, `allow_origins` из env `ADMIN_WEB_ORIGIN` (дефолт
`http://localhost:3000`), без `allow_credentials` (auth ещё нет — cookies/
токены не используются, делить нечего).

## admin-web: структура

Новый сервис, Next.js 15 (App Router, TypeScript), без Tailwind — обычный
CSS, по духу ADR-009 («минимальный UI сейчас», редизайн отдельно).

- `app/bots/page.tsx` — Server Component, SSR-фетч `GET {API_INTERNAL_URL}/bots`,
  таблица: имя · статус (Подключён/Не подключён, по наличию `linked_at`) ·
  номер · ссылка «Открыть» → `/bots/[id]`.
- `app/bots/[id]/page.tsx` — Server Component, начальный фетч `GET {API_INTERNAL_URL}/bots/{id}`
  (404 у api → `notFound()`), рендерит `<QrPanel initialBot={bot} apiBaseUrl={NEXT_PUBLIC_API_URL} botId={id} />`.
- `components/QrPanel.tsx` (client component) — единственный держатель поллинга,
  интервал 5с (`setInterval`, чистится в `useEffect` cleanup):
  - каждый тик: `GET {apiBaseUrl}/bots/{botId}`;
  - если `linked_at` есть → рендерим номер (`phone`) и кнопку «Отключить»,
    QR-картинку не грузим;
  - если `linked_at` нет → рендерим `<img src="{apiBaseUrl}/bots/{botId}/qr?t={Date.now()}">`
    (query-параметр — cache-busting, иначе браузер закэширует PNG по URL и не
    подхватит смену QR при ротации WhatsApp раз в ~20с); 504 от gateway
    (QR ещё не готов) — не ошибка, просто ждём следующего тика;
  - кнопка «Отключить» → `POST {apiBaseUrl}/bots/{botId}/logout`, затем
    немедленный внеочередной рефетч статуса (не ждать 5с) и возврат к
    QR-состоянию.
- `Dockerfile` по образцу `services/gateway/Dockerfile`.
- Env: `API_INTERNAL_URL` (server-side, docker-network адрes, напр.
  `http://api:8000`), `NEXT_PUBLIC_API_URL` (browser-side, напр.
  `http://localhost:8000`).

## Compose

`compose/docker-compose.dev.yml` и `compose/docker-compose.prod.yml` —
новый сервис `admin-web`, порт `3000:3000`, `depends_on: api`,
`ADMIN_WEB_ORIGIN` в api-сервисе выставлен на адрес admin-web.

## Тесты

- `services/api/tests/test_bots.py` — новый кейс на `GET /bots` (по образцу
  существующих testcontainers-тестов в этом же файле): пустой список,
  список из нескольких ботов, `phone`/`linked_at` корректно null/заполнены
  в зависимости от наличия строки в `bot_sessions`.
- `services/admin-web` — vitest + React Testing Library на `QrPanel`:
  переход QR → «подключён» при появлении `linked_at` в ответе поллинга,
  вызов `POST .../logout` по кнопке и возврат к QR-состоянию.
- `Makefile` — цели `install`/`test`/`lint` дополняются шагами для
  `services/admin-web` (`npm install`/`npm test`/`npm run lint`),
  симметрично тому, как уже подключён `services/gateway`.

## Живая проверка (конец итерации)

По уже установленному предпочтению пользователя — прогон на реальном
`docker compose`: поднять стек, создать бота прямым SQL-инсертом в `bots`,
открыть `/bots` в admin-web, увидеть его в списке, открыть `/bots/[id]`,
отсканировать QR реальным WhatsApp, увидеть переключение экрана на номер
без ручного обновления страницы, нажать «Отключить», увидеть возврат к QR.
