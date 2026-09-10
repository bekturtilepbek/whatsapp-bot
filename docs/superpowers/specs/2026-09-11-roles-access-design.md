# Роли и доступы (Волна 3) — дизайн

**Статус:** approved · 2026-09-11
**Фичи FEATURES.md:** 6.18 (роли и доступы)

## Контекст

Аутентификации в платформе нет вообще — ни логина, ни сессий, ни ролей.
`admin-web` стучится в `api` напрямую из браузера с открытым CORS
(`allow_credentials` намеренно не выставлен — «делить нечего», см.
`services/api/src/api/main.py:19-21`); сейчас единственная защита —
то, что порт `api`/`admin-web` на проде смотрит только на `127.0.0.1`
за SSH-туннелем, доступным только разработчику. Таблиц `tenants`/`users`
из аспирационной схемы ARCHITECTURE.md §5 не существует — как и
`Contact.temperature` в суб-проекте «переписка», это был набросок, не
реализация.

Этот суб-проект вводит два уровня пользователей — владелец платформы
(видит все боты) и клиент (видит только те боты, на которые ему выдан
доступ) — и делает кабинет пригодным для публичного доступа клиентов
(без самого сетевого периметра — TLS/reverse-proxy — это отдельная,
не запланированная здесь итерация).

Спека `docs/superpowers/specs/2026-09-09-qr-screen-design.md` (раздел
«Явно отложено на потом») уже предвидела этот момент и заранее выбрала
путь миграции: «переход на BFF ... — это добавление прокси-слоя, а не
переписывание `QrPanel`». Этот дизайн следует ровно этому плану.

## Явно отложено на потом (не в скоупе этой итерации)

- **Reverse-proxy/TLS/публичное открытие портов.** Дизайн делает сессию
  TLS-совместимой (`Secure`-cookie в проде), но сам периметр (Caddy/nginx,
  сертификат, снятие `127.0.0.1`-биндинга в `docker-compose.prod.yml`) —
  отдельная итерация. Подтверждено пользователем явно.
- **Самостоятельный сброс пароля по email.** Почтовой инфраструктуры в
  платформе нет. Пароль клиента меняет только владелец платформы через
  `/users`.
- **Более тонкие роли внутри одного бота** (например, «менеджер» без
  доступа к настройкам/промптам versus «админ»). Подтверждено
  пользователем — два уровня достаточно сейчас. `bot_access` оставляет
  место под будущую колонку `role`, если понадобится.
- **Refresh-токены / мгновенный принудительный логаут всех сессий.** JWT
  живёт 30 дней, без refresh-механики — не тот масштаб. Деактивация
  пользователя (`is_active=false`) или отзыв гранта закрывают доступ к
  ДАННЫМ немедленно (проверяются на каждый запрос из БД, не из токена),
  но сам факт «залогинен» в уже открытой вкладке браузера сохраняется до
  следующего запроса/истечения TTL.
- **6.20 (онбординг бота из UI).** Боты по-прежнему создаются вручную
  SQL-инсертом — этот суб-проект не меняет этот процесс, только то, кто
  какие уже существующие боты видит.

## Архитектура: BFF-прокси вместо прямого fetch

Сейчас `admin-web` ходит в `api` двумя путями: SSR-фетч на сервере
(`API_INTERNAL_URL`, внутренняя docker-сеть) и прямой fetch из браузера
(`NEXT_PUBLIC_API_URL`, требует открытого CORS — подход A из спеки
QR-экрана). С ролями это меняется:

- Браузер больше никогда не стучится в `api` напрямую — только в
  `admin-web` (свой origin). `CORSMiddleware` в `services/api/src/api/main.py`
  снимается целиком — он был нужен только для кросс-origin fetch из
  браузера, которого больше не будет.
- Новый catch-all `services/admin-web/app/api-proxy/[...path]/route.ts`
  принимает любой запрос клиентских компонентов, читает `session`-cookie
  admin-web, форвардит метод/тело/query-параметры на
  `${API_INTERNAL_URL}/{path}` с заголовком `Authorization: Bearer
  <token>`, стримит ответ (включая статус-код) обратно. Работает
  прозрачно и для multipart (загрузка фото товара) — тело не парсится,
  только форвардится с оригинальным `Content-Type`.
- SSR остаётся Server Component → `API_INTERNAL_URL` напрямую (без
  прокси-слоя — тот же docker-internal адрес, что и сейчас), но теперь
  тоже подставляет тот же `Authorization: Bearer` из cookie (через
  `next/headers`).
- Существующие клиентские компоненты (`ProductsTable`, `ProductForm`,
  `BlockedNumbersTable`, `QrPanel`, `BotSettingsForm`, `PromptEditor`) **не
  переписываются** — меняется только значение `apiBaseUrl`, которое им
  передаёт соответствующий `page.tsx`: было `API_PUBLIC_URL` (абсолютный
  адрес `api`), станет литерал `"/api-proxy"` (относительный путь на
  самом `admin-web`). `lib/env.ts`'s `API_PUBLIC_URL`/`NEXT_PUBLIC_API_URL`
  выходят из употребления в admin-web (браузер их больше не использует).

## Данные

Две новые таблицы (новая ревизия Alembic), без введения аспирационного
`tenants` — YAGNI, эта сущность сейчас нигде не используется:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_platform_owner: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BotAccess(Base):
    """Грант доступа клиента к конкретному боту. Владельцу платформы
    (User.is_platform_owner) грант не нужен — видит все боты безусловно."""

    __tablename__ = "bot_access"
    __table_args__ = (UniqueConstraint("user_id", "bot_id", name="uq_bot_access_user_bot"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
```

- Пароли — `bcrypt` (новая зависимость `services/api`; прямой пакет, не
  `passlib` — фактически неподдерживаемая обёртка, `bcrypt` делает ровно
  то же самое без лишнего слоя).
- Роль внутри гранта не нужна (см. «Явно отложено» выше) — двоичный
  грант per bot достаточен.
- **Бутстрап первого владельца** — при старте `api` (lifespan-хук в
  `main.py`, до приёма запросов): если заданы `PLATFORM_OWNER_EMAIL` и
  `PLATFORM_OWNER_PASSWORD` и такого пользователя ещё нет по email —
  создать с `is_platform_owner=True`. Идемпотентно — повторный старт не
  перезаписывает уже существующий пароль. Секреты только в `.env`
  (ADR-007), добавляются в `.env.example` с пояснением.

## API

**Новый роутер `auth.py`** (`/auth`):
- `POST /auth/login` — `{email, password}` → сверка с `users` (bcrypt),
  `is_active` обязателен, иначе 401 (то же сообщение, что и на неверный
  пароль — не раскрываем существование email). Успех: JWT (`HS256`,
  секрет `JWT_SECRET` — обязательная переменная окружения, тот же паттерн
  строгости, что у `OPENAI_API_KEY`), payload **только** `{sub: user_id,
  exp}` — роль/доступ к ботам НЕ кладём в токен, проверяем свежо из БД на
  каждый запрос (см. «Явно отложено» — так отзыв гранта или деактивация
  срабатывают немедленно). TTL — 30 дней, константа
  `JWT_TTL_DAYS = 30`. Ответ: `{token, user: {id, email,
  is_platform_owner}}`.
- `GET /auth/me` — текущий пользователь (для рендера навигации в
  admin-web: показывать ли ссылку «Пользователи»).

**Новый роутер `users.py`** (`/users`, только для `is_platform_owner`):
- `GET /users` — список клиентских аккаунтов + их гранты (join с
  `bot_access`).
- `POST /users` — создать пользователя (`email`, `password`, опционально
  список `bot_id` для сразу выданных грантов).
- `POST /users/{user_id}/bot-access` / `DELETE
  /users/{user_id}/bot-access/{bot_id}` — выдать/забрать доступ.
- `PATCH /users/{user_id}` — деактивировать (`is_active`) или сменить
  пароль. Ручной процесс владельца, не self-service.

**Зависимости** (новый `services/api/src/api/security.py`):
- `CurrentUser` — читает заголовок `Authorization: Bearer`, валидирует
  JWT (подпись + `exp`), грузит `User` по `sub`, проверяет `is_active`;
  401 в любом другом случае (нет заголовка, битый токен, истёк,
  пользователь не найден/деактивирован).
- `require_bot_access(bot_id)` — зависит от `CurrentUser`; пропускает,
  если `is_platform_owner`, иначе 403 при отсутствии строки в
  `bot_access(user_id, bot_id)`. Добавляется на КАЖДЫЙ существующий
  роут с `{bot_id}` в пути, включая сам `GET /bots/{bot_id}` (базовый
  роут чтения бота, которым пользуется каждая `page.tsx` для `notFound()`) —
  явно уточняю, чтобы не осталось дыры: клиент без гранта получает 403
  уже на этом роуте, а не только на дочерних. Плюс `PATCH /bots/{bot_id}`
  (настройки), products (весь CRUD + фото), blocked-numbers, prompts,
  QR/logout, `chats/{chat_id}/release`, tools.
- `require_platform_owner` — 403 иначе. На весь `users.py` router.
- `GET /bots` (список, без `{bot_id}`) — не 403, а фильтрация: владелец
  видит все боты, клиент — только те, где есть `bot_access` (`JOIN`, не
  N+1 запрос на бота).

**CORS снимается** — `CORSMiddleware` был нужен только для прямого
кросс-origin fetch из браузера в `api`; с BFF браузер в `api` больше не
ходит.

## admin-web

- **`/login`** — форма (email/пароль), Server Action вызывает `POST
  {API_INTERNAL_URL}/auth/login`. Успех — кладёт токен в свою cookie
  (`session`: `httpOnly`, `secure` в проде — по тому же признаку прода,
  что уже различает `Dockerfile`/`Dockerfile.prod`, `sameSite: "lax"`,
  `maxAge` 30 дней), редирект на `/bots`. Ошибка — сообщение в форме, без
  различия «неверный email» / «неверный пароль».
- **`middleware.ts`** (новый, корень `admin-web`) — если `session`-cookie
  нет и путь не `/login` (и не статика) — редирект на `/login`. Это
  UX-гейт: реальная авторизация всё равно проверяется на каждый запрос в
  `api` (см. `require_bot_access`/`require_platform_owner`), так что
  баг или отсутствие middleware не открывает дыру, только portит UX
  (пустая страница вместо редиректа).
- **Логаут** — Server Action, чистит cookie, редирект на `/login`.
- **`app/api-proxy/[...path]/route.ts`** (новый) — см. «Архитектура»
  выше. Возвращает 401 без похода в `api`, если `session`-cookie нет
  вообще (мелкая оптимизация, не заменяет проверку в `api`).
- **`lib/api.ts`** — вместо правки сигнатуры каждой из ~15 функций,
  все прямые `fetch(...)` внутри файла переезжают на общий приватный
  `apiFetch(url, init)`: на сервере (`typeof window === "undefined"`) он
  сам подмешивает `Authorization` из cookie через `next/headers` (динамический
  импорт — этот модуль не должен тянуться в клиентский бандл); в браузере
  просто вызывает обычный `fetch` — cookie для `/api-proxy` (свой origin)
  браузер приложит сам. Компоненты и `page.tsx` не меняются вообще, кроме
  прокидывания `apiBaseUrl="/api-proxy"` клиентским компонентам вместо
  `API_PUBLIC_URL`.
- **`/users`** (новый экран, только `is_platform_owner`; иначе редирект
  на `/bots`) — таблица клиентских аккаунтов и их гранты, форма создания,
  чекбоксы/кнопки выдачи и отзыва доступа к ботам.
- **Общий header** в `app/layout.tsx` (сейчас голый — только `<body>{children}</body>`) —
  ссылка «Пользователи» (только владельцу, по `GET /auth/me`) и кнопка
  «Выйти».
- **`/bots`** (список) — если у клиента нет ни одного гранта, показывать
  «Доступа пока нет, обратитесь к владельцу платформы», не пустую таблицу
  без объяснений.

## Тестирование

- Бэкенд: `bcrypt`-хеширование, `POST /auth/login` (успех/неверный
  пароль/неактивный пользователь), `CurrentUser` (валидный/битый/истёкший
  токен), `require_bot_access` (владелец проходит всегда, клиент — только
  со своим грантом, 403 без), `require_platform_owner`, `GET /bots`
  фильтрация, `users.py` CRUD + грант/отзыв.
- **Global Constraint для плана:** после добавления `require_bot_access`
  ко всем `/bots/{bot_id}/...`-роутам ВСЕ существующие Docker-gated тесты
  (`test_products.py`, `test_blocked_contacts.py`, промпты, настройки)
  начнут получать 401 без токена — план обязан завести тестовую
  фикстуру (пользователь + JWT) и подмешать её `Authorization`-заголовок
  во все существующие `client`-фикстуры этих файлов ОДНИМ из первых
  тасков, иначе вся модель тестов ляжет разом при первом же таске,
  добавляющем зависимость на реальный роут.
- admin-web: vitest на `apiFetch`/новые компоненты (`/login` форма,
  `/users` экран), возможно лёгкий тест на `middleware.ts` (редирект без
  cookie).
- Живая проверка на docker compose (по итогам всего суб-проекта, как
  обычно): логин владельцем и клиентом, доступ клиента ограничен своим
  ботом, `GET /bots` без токена → 401, деактивированный пользователь не
  проходит.
