# Аудит-лог действий (Волна 3) — дизайн

**Статус:** approved · 2026-09-11
**Фичи FEATURES.md:** 6.19 (аудит-лог действий)

## Контекст

FEATURES.md формулирует фичу как «кто и когда поменял промпт/настройки/
запустил рассылку», статус `NEW` — в V1 такого не было вообще (пара
логин/пароль в `.env` на бота, без пользовательских сущностей — писать
«кто» было некуда). ARCHITECTURE.md §5 содержит аспирационный набросок
`audit_log (actor, bot_id, action, payload, ts)` — таблицы в БД нет,
это была заготовка на будущее.

Роли и доступы (6.18, сдано 2026-09-11) разблокировали фичу: теперь у
каждого мутирующего HTTP-запроса есть аутентифицированный пользователь
(`services/api/src/api/security.py`), то есть «кто» берётся из реальной
сущности `User`, а не изобретается.

Часть формулировки («запустил рассылку») сейчас неприменима буквально:
кампании (6.16, §7 целиком) вне скоупа платформы до анти-бан-дисциплины
— рассылок не существует, нечего логировать. Этот суб-проект покрывает
только реально существующие мутации.

## Явно отложено на потом (не в скоупе этой итерации)

- **Retention / чистка старых записей.** Таблица растёт без ограничения
  — как и остальной рост в проекте на этом этапе (осознанный YAGNI, не
  забытый пункт). Если станет проблемой — отдельная итерация.
- **Аудит аутентификации** (`POST /auth/login`, `GET /auth/me`). Это не
  «поменял конфиг» — другая тема (кто когда логинился), не то, что
  просит FEATURES.md 6.19. Не исключено, что понадобится позже, но не
  здесь.
- **Аудит рассылок (6.16).** Кампаний не существует — нечего аудировать.
  Реестр действий (см. ниже) — то самое расширяемое место, куда это
  добавится, когда/если 6.16 будет реализовано.
- **Более тонкая гранулярность `action` для мультиполевых роутов.**
  `PATCH /bots/{bot_id}` обслуживает промпты, настройки И (с 2026-09-11)
  имя бота одним и тем же роутом — action остаётся общим
  (`bots.update`), а что именно изменилось видно из `payload` (тело
  ответа содержит все поля бота целиком, включая изменённые). Разбивать
  action на `bots.update_prompt`/`bots.update_settings` можно позже, если
  окажется, что `payload` для этого недостаточно читаем.
- **Экспорт лога (CSV/Excel).** Не запрошено, экран с фильтрами
  достаточен для первой итерации.

## Архитектура: ASGI-middleware + статический реестр действий

Централизованный перехват вместо ручной вставки кода в каждый из 19
существующих мутирующих роутов (перечислены в разделе «Данные» ниже).
Middleware оборачивает весь `app` в `services/api/src/api/main.py` и не
меняет ни один файл в `routers/`.

**Реестр действий** — единственное расширяемое место:

```python
# services/api/src/api/audit.py
ACTION_REGISTRY: dict[tuple[str, str], str] = {
    ("POST", "/bots"): "bots.create",
    ("PATCH", "/bots/{bot_id}"): "bots.update",
    ("POST", "/bots/{bot_id}/logout"): "bots.logout",
    ("POST", "/bots/{bot_id}/chats/{chat_id}/release"): "bots.release_chat",
    ("POST", "/bots/{bot_id}/blocked-numbers"): "blocked_numbers.create",
    ("DELETE", "/bots/{bot_id}/blocked-numbers/{phone}"): "blocked_numbers.delete",
    ("POST", "/bots/{bot_id}/tools"): "tools.create",
    ("DELETE", "/bots/{bot_id}/tools/{tool_name}"): "tools.delete",
    ("POST", "/bots/{bot_id}/documents"): "documents.create",
    ("DELETE", "/bots/{bot_id}/documents/{document_id}"): "documents.delete",
    ("POST", "/bots/{bot_id}/products"): "products.create",
    ("PATCH", "/bots/{bot_id}/products/{product_id}"): "products.update",
    ("DELETE", "/bots/{bot_id}/products/{product_id}"): "products.delete",
    ("POST", "/bots/{bot_id}/products/{product_id}/photos"): "product_photos.create",
    ("DELETE", "/bots/{bot_id}/products/{product_id}/photos/{photo_id}"): "product_photos.delete",
    ("POST", "/users"): "users.create",
    ("PATCH", "/users/{user_id}"): "users.update",
    ("POST", "/users/{user_id}/bot-access"): "bot_access.grant",
    ("DELETE", "/users/{user_id}/bot-access/{bot_id}"): "bot_access.revoke",
}

# Роуты с multipart-телом запроса — тело НЕ читается вообще (см. "Payload"
# ниже), даже как fallback. Ответ у всех троих JSON, этого достаточно.
MULTIPART_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/bots/{bot_id}/products"),
    ("POST", "/bots/{bot_id}/products/{product_id}/photos"),
    ("POST", "/bots/{bot_id}/documents"),
})
```

Роут, отсутствующий в `ACTION_REGISTRY`, просто не аудируется (включая
`GET`-роуты — их там в принципе не будет). Новый мутирующий роут в
будущем добавляется сюда одной строкой; без этого он молча выпадает из
аудита — не ошибка, осознанный trade-off генерического подхода.

**Порядок работы middleware** (`@app.middleware("http")`):

1. Если `request.method` не в `{"POST", "PATCH", "DELETE", "PUT"}` —
   пропустить (`return await call_next(request)`), дальше не идти.
2. Если запрос — не multipart (`Content-Type` не начинается с
   `multipart/`), прочитать и закэшировать тело ДО `call_next`:
   `request_body = await request.body()`. Starlette кэширует прочитанное
   тело — роут ниже по цепочке (Pydantic-парсинг FastAPI) читает те же
   байты повторно, не ломается. Для multipart-запросов тело не читается
   вообще (см. `MULTIPART_ROUTES` — экономит память на файлах/фото,
   которые всё равно не пойдут в payload).
3. `response = await call_next(request)` — роут отрабатывает как обычно.
4. Если `response.status_code` не 2xx — выйти, ничего не писать (аудит
   только успешных мутаций).
5. `route = request.scope.get("route")` — Starlette кладёт туда
   matched-роут после того, как роутинг отработал (к моменту, когда
   `call_next` вернул управление, роутинг уже случился). `route.path` —
   шаблон пути (`"/bots/{bot_id}"`), НЕ конкретные значения — ключ для
   `ACTION_REGISTRY`. Если пары `(method, route.path)` нет в реестре —
   выйти, ничего не писать. **Проверить первым шагом реализации** —
   `request.scope["route"]`/`request.path_params` реально доступны на
   объекте `request`, переданном в middleware, после того как
   `call_next` вернул управление (уверенность высокая — паттерн
   задокументирован и используется, например, Sentry-интеграцией
   FastAPI для транзакций по шаблону пути, но не проверено вживую в
   ЭТОМ стеке версий FastAPI/Starlette) — если нет, придётся парсить
   `request.url.path` вручную по regex не хуже, запасной план тот же
   самый reestr, просто с матчингом по маске вместо точного `route.path`.
6. **actor** — декодировать JWT из заголовка `Authorization` тем же
   `decode_access_token`, что и `get_current_user`
   (`services/api/src/api/security.py`), напрямую (не как FastAPI-
   зависимость — middleware вне DI-графа). Нет валидного токена — выйти
   без записи (не должно случаться для роута, защищённого
   `BotAccessUser`/`PlatformOwner`, но на всякий случай, а не падать).
7. **bot_id** — `request.path_params.get("bot_id")`, если есть в шаблоне
   пути; иначе `None` (платформенные действия — `users.*`,
   `bot_access.*` кроме revoke, у которого `bot_id` в пути).
8. **payload** — см. ниже, трёхуровневый fallback.
9. Открыть отдельную короткую сессию (своя, не сессия роута — см.
   «Данные» про переиспользование `_get_session_factory`), вставить
   строку, закоммитить. Обернуть весь блок 6-9 в `try/except Exception`
   с `logger.warning(...)` — ошибка аудит-записи НИКОГДА не должна
   ронять уже успешно отработавший запрос пользователя (ответ клиенту к
   этому моменту уже вычислен, но ещё не отправлен — падение здесь без
   перехвата превратило бы успешный 200 в 500 клиенту, что абсурдно).

**Payload — три уровня fallback:**

1. Тело **ответа**, если `response.headers["content-type"]` начинается
   с `application/json` и тело непустое — большинство роутов
   (`response_model=...`) возвращают полное JSON-представление объекта
   после мутации. Схемы ответов (`BotOut`, `ProductOut`,
   `UserWithAccessOut` и т.д.) не содержат `password`/`password_hash` ни
   в одном поле — проверено (`services/api/src/api/schemas/auth.py`,
   `UserOut`: `id/email/is_platform_owner/is_active`, без пароля) —
   редактирование чувствительных полей НЕ требуется для этого уровня.
2. Тело **запроса** (закэшированное на шаге 2), если ответ пуст (204) И
   запрос не в `MULTIPART_ROUTES` И `Content-Type` запроса —
   `application/json` И тело непустое. На практике это нужно ровно
   одному роуту — `POST /users/{user_id}/bot-access` (204, `bot_id`
   только в теле `_BotAccessIn`). Тело этого запроса безопасно
   (`{"bot_id": "..."}, `— пароля там нет; для остальных 204-роутов
   (все DELETE) тело запроса пустое, этот уровень не сработает, упадём
   на уровень 3.
3. `dict(request.path_params)` — для всех DELETE-роутов (204, без тела)
   это покрывает `bot_id`/`product_id`/`photo_id`/`phone`/`tool_name`/
   `document_id`/`user_id`/`chat_id` — сериализуются в JSON-совместимые
   строки (`UUID` → `str`).

## Данные

Новая таблица `audit_log` (`libs/db/src/db/models.py` + Alembic-миграция,
по образцу существующих моделей — `UniqueConstraint`/`mapped_column`
стиль как в `BotAccess`):

```python
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

Индекс `(created_at DESC)` — экран сортирует по времени, самое частое
чтение. Индекс `(bot_id)` — фильтр по боту на экране. Оба — обычные
btree, как у существующих таблиц с похожим паттерном чтения
(`messages(contact_id, ts DESC)` в ARCHITECTURE.md §5).

`libs/db/src/db/audit_log.py` (новый, по образцу `blocked_contacts.py`):
`create_entry(session, *, actor_user_id, bot_id, action, payload) -> AuditLog`,
`list_entries(session, *, bot_id=None, actor_user_id=None, limit, offset) -> list[AuditLog]`.

**19 мутирующих роутов, покрытых реестром** (список для реализации,
сверено с текущим кодом `services/api/src/api/routers/*.py`):

| Метод | Путь | action |
|---|---|---|
| POST | `/bots` | `bots.create` |
| PATCH | `/bots/{bot_id}` | `bots.update` |
| POST | `/bots/{bot_id}/logout` | `bots.logout` |
| POST | `/bots/{bot_id}/chats/{chat_id}/release` | `bots.release_chat` |
| POST | `/bots/{bot_id}/blocked-numbers` | `blocked_numbers.create` |
| DELETE | `/bots/{bot_id}/blocked-numbers/{phone}` | `blocked_numbers.delete` |
| POST | `/bots/{bot_id}/tools` | `tools.create` |
| DELETE | `/bots/{bot_id}/tools/{tool_name}` | `tools.delete` |
| POST | `/bots/{bot_id}/documents` | `documents.create` |
| DELETE | `/bots/{bot_id}/documents/{document_id}` | `documents.delete` |
| POST | `/bots/{bot_id}/products` | `products.create` |
| PATCH | `/bots/{bot_id}/products/{product_id}` | `products.update` |
| DELETE | `/bots/{bot_id}/products/{product_id}` | `products.delete` |
| POST | `/bots/{bot_id}/products/{product_id}/photos` | `product_photos.create` |
| DELETE | `/bots/{bot_id}/products/{product_id}/photos/{photo_id}` | `product_photos.delete` |
| POST | `/users` | `users.create` |
| PATCH | `/users/{user_id}` | `users.update` |
| POST | `/users/{user_id}/bot-access` | `bot_access.grant` |
| DELETE | `/users/{user_id}/bot-access/{bot_id}` | `bot_access.revoke` |

`services/api/src/api/db.py::_get_session_factory` — переименовать в
публичное `get_session_factory` (убрать ведущее подчёркивание) при этой
итерации: middleware живёт в том же пакете `api`, но лезть в приватное
имя другого модуля — плохой знак; экспорт делает переиспользование
явным, не тайным.

## API

`GET /audit-log` (новый роутер `services/api/src/api/routers/audit_log.py`),
owner-only (`PlatformOwner` — аудит-лог целиком, включая платформенные
действия над другими ботами, не должен быть виден клиенту одного бота).

Query-параметры: `bot_id: uuid | None`, `actor_user_id: uuid | None`,
`limit: int = 50` (default), `max = 200`, `offset: int = 0` — тот же
паттерн верхней границы, что у товаров/чёрного списка
(`PRODUCTS_LIST_MAX_LIMIT`/`BLOCKED_LIST_DEFAULT_LIMIT`).

Ответ — `AuditLogOut`: `id, actor_user_id, actor_email, bot_id, bot_name,
action, payload, created_at`. `actor_email`/`bot_name` — денормализованный
join на `users`/`bots` в `list_entries`, чтобы экран не делал N+1 запрос
на каждую строку ради email/имени бота (тот же принцип, что уже решён
для списка ботов с `phone`/`linked_at`).

## admin-web

Новый экран `/audit-log` (owner-only, ссылка в `AppHeader` рядом с
«Пользователи», видна только `is_platform_owner`). Таблица: время
(локальное форматирование, как в `PromptEditor` — чистая строковая
операция над ISO, не `new Date()`, чтобы не ловить hydration-mismatch),
кто (`actor_email`), бот (`bot_name` или «—» для платформенных действий),
действие (`action` как есть, моноширинным/кодом), payload — свёрнутый
`<details>`/`<summary>` с `JSON.stringify(payload, null, 2)` внутри
(простейший вариант, без специального форматтера — ADR-009, минимальный
UI). Пагинация — «Показать ещё» по образцу `BlockedNumbersTable`/
`ProductsTable`. Фильтр по боту — `<select>` со списком ботов (тот же
источник, что и в других owner-экранах).

## Тестирование

**Backend** (`services/api/tests/test_audit_log.py`, Docker-gated,
testcontainers-postgres):

- Успешный `PATCH /bots/{bot_id}` создаёт запись `bots.update` с
  `actor_user_id` вызывающего и payload = тело ответа.
- Успешный `DELETE /bots/{bot_id}/blocked-numbers/{phone}` создаёт
  запись с payload, содержащим `phone` из path_params (тело ответа
  пустое).
- Успешный `POST /users/{user_id}/bot-access` создаёт запись с payload,
  содержащим `bot_id` (уровень 2 fallback — единственный роут, где это
  проверяется).
- Неуспешный запрос (404/422/403) НЕ создаёт запись в аудит-логе.
- `GET /users` (не в реестре) НЕ создаёт запись.
- `POST /bots/{bot_id}/documents` (multipart) создаёт запись с payload
  из ОТВЕТА (`DocumentOut`), не падает на попытке распарсить multipart
  как JSON.
- Ручка аудит-лога падения при записи — намеренно сломанная запись
  (например, мок `create_entry` кидает исключение) НЕ должна превращать
  успешный ответ пользователю в 500 — сам мутирующий запрос всё равно
  возвращает 200/201/204 как обычно.
- `GET /audit-log` — owner видит записи; не-owner получает 403; фильтр
  `bot_id`; пагинация `limit/offset`.

**Frontend** (`app/audit-log/page.test.tsx`/`AuditLogTable.test.tsx`,
vitest, по образцу `BlockedNumbersTable.test.tsx`): рендер строк,
пагинация «Показать ещё», фильтр по боту, разворачивание payload по
клику на `<summary>`, ссылка в `AppHeader` видна только owner'у (уже
есть прецедент — `lib/currentUser.ts::currentUserIsOwner`).

**Живая проверка на docker compose** (в конце): выполнить несколько
реальных мутаций через настоящий UI (переименовать бота, добавить номер
в чёрный список, создать пользователя), открыть `/audit-log`, убедиться,
что все действия появились с правильным actor/action/payload, SQL-запрос
к `audit_log` напрямую для перекрёстной проверки.
