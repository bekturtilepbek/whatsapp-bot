# Товары: CRUD без фото (Волна 3, четвёртый под-проект) — дизайн

**Статус:** approved · 2026-09-10
**Фичи FEATURES.md:** 6.8 (CRUD товаров + обязательные/необязательные поля) — первая половина

## Контекст

Волна 3 разбита на упорядоченные под-проекты (QR-экран → промпты →
настройки → **товары** → переписка → роли → онбординг). Товары решено
делить на два под-проекта: сначала CRUD текстовых полей с автосчётом
эмбеддинга (этот документ), затем отдельно загрузка фото — потому что в
проекте вообще нет write-пути для медиа с Python-стороны
(`libs/integrations/src/integrations/storage/` умеет только `get()`),
ни для товаров, ни для документов (6.7).

Схема `products`/`product_embeddings`/`product_images` уже существует
(`libs/db/src/db/models.py`) и не меняется — миграция не нужна. Читающие
функции (`list_products`, `find_product_by_exact_name`,
`list_product_images`, поиск по эмбеддингу) уже используются тулзой
`product_search` (Волна 2). Этот под-проект добавляет запись: создание,
редактирование, удаление, автопересчёт эмбеддинга — и экран в admin-web.

## Явно отложено на потом (не в скоупе этой итерации)

- **Обязательность фото.** Пользователь явно потребовал, чтобы `name` И
  фото товара были обязательны в форме загрузки и в БД. Ограничение по
  фото добавляется вторым под-проектом (вместе с самой загрузкой) — в
  этом под-проекте `name` обязателен, фото нет. Пока UI второго
  под-проекта не сдан, товар без единой фотографии — штатное,
  ожидаемое, временное состояние, не баг.
- **Очистка `price`/`sku`/`description` обратно в NULL через PATCH.** Тот
  же принятый паттерн, что уже есть у `image_prompt`/`pdf_prompt`
  (`bots.py`): `None` в патч-схеме неотличим от «поле не передано» —
  значит explicit-сброс поля в NULL этим PATCH недостижим. Не чиним
  заново, будет отдельной находкой при желании (например через
  `PATCH ?clear=price`), вне скоупа.
- **Уникальность SKU.** По решению пользователя SKU свободен, без
  проверки уникальности даже в рамках одного бота — возможно, поле
  вообще уйдёт из схемы позже. Ничего не валидируем.
- **Дизайн ретрая эмбеддинга помечен как вероятный кандидат на
  пересмотр** пользователем — см. memory `product-embedding-retry-design`.
  Delivering as designed now; не удивляться будущему запросу переделать
  именно этот кусок.
- **Архивирование/мягкое удаление товаров.** По решению пользователя —
  схема БД и есть ответ: колонки `deleted_at` нет, `DELETE` — обычный
  SQL DELETE. Если понадобится история цен/архив — отдельная фича.

## Архитектура

### Обязательные/необязательные поля

Из полей `products`: **обязательно только `name`** (непустая строка
после `.strip()`). `price`, `sku`, `description` — опциональны.
`display_custom` — опционален, дефолт `{}` (уже есть на уровне колонки).

### Эмбеддинг: когда считается и что при сбое

Эмбеддинг строится **только из `name`+`description`**
(`product_embedding_input`, уже существует) — они единственные поля,
описывающие, ЧТО товар такое по смыслу, для семантического поиска
(4.1). `price`/`sku`/`display_custom` — метаданные, не меняют «смысл»
товара, эмбеддинг от них не зависит и не пересчитывается.

Пересчёт происходит при `create_product` всегда и при `update_product`
только если `name` или `description` реально изменились (сравнение
новых значений со старыми, тем же принципом, что в `prompt_versions` —
no-op изменения не должны создавать лишнюю работу).

**Обработка сбоя.** Расчёт эмбеддинга — внешний вызов (OpenAI), может
упасть даже после встроенного retry-with-backoff в `generate_embedding`.
Продукт без эмбеддинга невидим для векторного поиска (4.1), но остаётся
доступен через точное совпадение по имени (4.2, fallback уже есть и не
зависит от эмбеддинга) — то есть отсутствие эмбеддинга деградирует
одну функцию, а не ломает товар целиком. Поэтому:

1. Внутри HTTP-запроса на create/update — синхронная попытка
   `generate_embedding()` (с уже встроенным ретраем).
2. Если и это не удалось — товар всё равно сохраняется (или
   обновляется) без эмбеддинга/со старым эмбеддинга, ошибка
   логируется, ставится Celery-задача
   `recompute_product_embedding(product_id)` — идемпотентная, при
   срабатывании читает текущие `name`/`description` из БД (не то, что
   было на момент постановки — на случай что товар успеют отредактировать
   снова) и делает `upsert_embedding`.
3. Задача регистрируется в `services/celery/src/tasks/products.py` по
   образцу `followup.py`; имя — новая константа в
   `libs/scheduling/src/scheduling/task_names.py`
   (`RECOMPUTE_PRODUCT_EMBEDDING = "tasks.products.recompute_embedding"`).
   Диспетчинг из `services/api` — `asyncio.wait_for(asyncio.to_thread(celery_app.send_task, ...), timeout=...)`,
   как в `worker/pipeline/consumer.py`, обёрнутый в `try/except Exception`
   (постановка задачи сама не должна ронять HTTP-ответ).

**Помечено как вероятный кандидат на пересмотр** — см. memory
`product-embedding-retry-design`.

### display_custom

Уже реализованная логика чтения (`_resolve_display_config` в
`product_search.py`, «всё или ничего») не меняется. Этот под-проект
добавляет только запись: `POST`/`PATCH` принимают `display_custom` как
опциональный объект `{show_name?, show_description?, show_price?}` —
не валидируем состав ключей на бэкенде (fail-open, как и чтение —
отсутствующий ключ уже трактуется как `true`), просто сохраняем как
есть в JSONB.

## Данные

Схема не меняется. Новые функции в `libs/db/src/db/products.py`:

```python
async def get_product(session, bot_id: uuid.UUID, product_id: uuid.UUID) -> Product | None
async def create_product(session, bot_id: uuid.UUID, *, name: str, price=None, sku=None,
                          description=None, display_custom=None) -> Product
async def update_product(session, bot_id: uuid.UUID, product_id: uuid.UUID, **fields) -> Product | None
async def delete_product(session, bot_id: uuid.UUID, product_id: uuid.UUID) -> bool
```

`get_product`/`update_product`/`delete_product` фильтруют по
`bot_id` И `product_id` вместе (как везде в проекте — чужой бот не
должен даже узнать через 404 vs 403, существует ли товар с этим id у
другого бота). `create_product`/`update_product`, при изменении
`name`/`description`, сами вызывают `generate_embedding` +
`upsert_embedding` внутри — либо роутер делает это отдельным шагом
после записи товара (решаем на этапе плана, что чище для тестируемости
— вероятно роутер, чтобы DB-слой не знал про LLM/Celery).

## API

```
GET    /bots/{bot_id}/products              -> list[ProductOut]
POST   /bots/{bot_id}/products               -> ProductOut (201)
GET    /bots/{bot_id}/products/{product_id}  -> ProductOut | 404
PATCH  /bots/{bot_id}/products/{product_id}  -> ProductOut | 404
DELETE /bots/{bot_id}/products/{product_id}  -> 204 | 404
```

Схемы (`services/api/src/api/schemas/products.py`), по образцу
`bots.py`/`prompt_versions.py`:

```python
class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    price: Decimal | None
    sku: str | None
    description: str | None
    display_custom: dict
    created_at: datetime

class ProductCreate(BaseModel):
    name: str  # непустая строка после strip — валидатор
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict | None = None

class ProductPatch(BaseModel):
    name: str | None = None
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict | None = None
```

`PATCH` — `exclude_unset` семантика (как `BotPatch`): непереданное
поле не трогается; см. «Отложено» про `None`-в-NULL ограничение.
Как и у `bots.py`, `update_bot`-паттерн для 404: сначала проверяем
существование бота/товара до записи, чтобы не поймать FK-500 вместо
404 (тот же класс бага, что чинился в `prompt_versions`).

## admin-web

- `/bots/[id]/products` — Server Component, список: имя, цена, SKU,
  ссылки «Редактировать»/кнопка «Удалить» (confirm), кнопка «Добавить
  товар».
- `/bots/[id]/products/new` и `/bots/[id]/products/[productId]/edit` —
  используют общий Client Component `ProductForm` (по аналогии с тем,
  что `BotSettingsForm` был один компонент на чтение+запись): поля
  name (required, HTML `required` + собственная JS-валидация,
  `noValidate` на форме — тот же паттерн, что в `BotSettingsForm`,
  чтобы native constraint validation не блокировала submit молча),
  price, sku, description, чекбокс «переопределить вывод для этого
  товара» → 3 подчекбокса (имя/описание/цена).
- `lib/api.ts`: тип `Product`, `fetchProducts`, `fetchProduct`,
  `createProduct`, `updateProduct`, `deleteProduct` — тонкие обёртки
  над API, по образцу существующих `fetchBots`/`patchBotSettings`.
- Ссылка на список товаров — с `/bots/[id]` (карточка бота, туда же
  уже ведут ссылки на QR/промпты/настройки).
- Без Tailwind, обычный CSS (ADR-009), как у остальных экранов кабинета.

## Тесты

- `services/api/tests/test_products.py` (новый файл, testcontainers, по
  образцу `test_prompt_versions.py`): create/list/get/patch/delete
  happy-path; создание без `name` → 422; операции над товаром чужого
  бота → 404; PATCH/GET/DELETE несуществующего товара → 404 (не 500);
  пересчёт эмбеддинга при смене `name` или `description` (мок
  `generate_embedding`, проверка `upsert_embedding` вызван с новым
  вектором); отсутствие пересчёта при смене только `price`/`sku`
  (мок `generate_embedding` не должен вызываться); при падении
  `generate_embedding` — товар всё равно создаётся/обновляется,
  `celery_app.send_task` вызван с `RECOMPUTE_PRODUCT_EMBEDDING` и
  верным `product_id`.
- `services/celery/tests/test_products.py` (новый): задача
  `recompute_product_embedding` читает текущий товар из БД, считает
  эмбеддинг, апсертит; на несуществующий `product_id` — no-op, не падает.
- `services/admin-web/lib/api.test.ts` — новые тесты на 5 функций
  товаров, по образцу существующих.
- `services/admin-web/components/ProductForm.test.tsx` — новый файл:
  рендер пустой формы (create) и с данными (edit), submit без name
  показывает ошибку и не вызывает `createProduct`, успешный submit
  вызывает `createProduct`/`updateProduct` с ожидаемым телом,
  чекбокс display_custom раскрывает/собирает 3 подчекбокса корректно.

## Живая проверка (конец итерации)

На поднятом dev-стеке: открыть `/bots/[id]/products` для существующего
бота (список пуст), добавить товар с именем и описанием — увидеть его
в списке; убедиться в БД, что эмбеддинг посчитан
(`product_embeddings` содержит строку); отредактировать только цену —
эмбеддинг не изменился (тот же вектор); отредактировать описание —
эмбеддинг обновился; удалить товар — пропал из списка и из БД
(включая `product_embeddings`, ON DELETE CASCADE).
