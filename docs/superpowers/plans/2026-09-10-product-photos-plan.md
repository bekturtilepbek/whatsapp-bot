# Товары: загрузка фото (Волна 3, пятый под-проект) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кабинет умеет создавать товар только вместе с хотя бы одним фото
(обязательность), управлять фото существующего товара (добавить/удалить),
фото ресайзятся при загрузке и отдаются в браузер через api — закрывает
FEATURES.md 6.8 целиком.

**Architecture:** `Storage.put()` добавляется в `libs/integrations`
(симметрично уже существующему TS-интерфейсу gateway). `POST
/bots/{bot_id}/products` меняется с JSON на multipart — создание товара и
загрузка фото происходят одной транзакцией (всё или ничего). Два новых
эндпоинта управляют фото существующего товара, третий — отдаёт байты в
браузер. Ресайз/валидация — Pillow, новая зависимость только у
`services/api` (не у `libs/integrations` — та остаётся тупым байт-хранилищем).

**Tech Stack:** Python 3.12 / FastAPI (`python-multipart`, `UploadFile`) /
SQLAlchemy 2.0 async / Pillow (ресайз) — бэкенд. Next.js 15 / TypeScript /
React 19 (admin-web) · vitest + React Testing Library · pytest +
testcontainers (Docker-тесты) / pytest без Docker (Storage, product_photos).

**Spec:** [docs/superpowers/specs/2026-09-10-product-photos-design.md](../specs/2026-09-10-product-photos-design.md)

## Global Constraints

- Фото обязательно при создании товара (1..10 файлов), `name` — как и
  раньше. Требование НЕ ретроактивно: товары без фото, созданные до этого
  под-проекта, продолжают существовать как есть.
- Допустимые типы: `image/jpeg`, `image/png`, `image/webp`. Максимум 10 МБ
  на файл, максимум 10 фото на товар (суммарно).
- Ресайз до ~1280px по длинной стороне (Pillow), формат не меняется.
  `Image.open()`+`.load()` — одновременно и декодирование, и валидация
  (битый файл → 422, не мусор в Storage).
- Создание — всё или ничего: сбой валидации/Storage при создании товара
  откатывает ВСЮ транзакцию (товар не создаётся). Уже успевшие улететь в
  Storage файлы при частичном сбое НЕ удаляются (`Storage` не умеет
  `delete`, не в скоупе — осиротевшие объекты приняты сознательно, товара
  без такого объекта не существует).
- Удаление последнего фото товара — 422 (обязательность не даёт снести все
  фото до нуля).
- Все операции с фото скоупятся по `bot_id`+`product_id`(+`photo_id`) вместе
  — тот же принцип "чужое не существует", что уже применяется для товаров.
- Ключ Storage: `bots/{bot_id}/products/{product_id}/{photo_id}` —
  `position` НЕ входит в ключ (живёт только в БД).
- Реордер фото (drag/кнопки) — НЕ в этом под-проекте.
- Прямые публичные S3-ссылки — не делаем, всё через `GET
  /bots/{bot_id}/products/{product_id}/photos/{photo_id}` в api.
- `PATCH /bots/{bot_id}/products/{product_id}` остаётся JSON-only и фото не
  трогает — управление фото только через новые под-роуты.
- `Product.photos` (ORM `relationship`) — `lazy="raise"`: доступ без явного
  `selectinload` кидает понятную ошибку сразу, а не `MissingGreenlet` в
  сериализации (async SQLAlchemy не подгружает `relationship` лениво вне
  активного await-контекста). `db.products.get_product`/`list_products`
  получают `with_images: bool = False` — грузят `photos` явно только там,
  где нужно (api-роутер); `worker`/`product_search` (контекст LLM,
  векторный поиск) продолжают вызывать без этого параметра — ни одного
  лишнего запроса на их горячем пути.
- Без Tailwind, обычный CSS (ADR-009) — стили `table`/`form input`/`textarea`
  уже есть в `globals.css`, для миниатюр фото добавляется один класс.

---

### Task 1: `Storage.put()` — filesystem + s3 (libs/integrations)

**Files:**
- Modify: `libs/integrations/src/integrations/storage/__init__.py`
- Modify: `libs/integrations/src/integrations/storage/filesystem.py`
- Modify: `libs/integrations/src/integrations/storage/s3.py`
- Test: `libs/integrations/tests/test_storage_filesystem.py`
- Test: `libs/integrations/tests/test_storage_s3.py`

**Interfaces:**
- Produces: `Storage.put(key: str, data: bytes, mime_type: str) -> None` на
  обеих реализациях (`FilesystemStorage`, `S3Storage`), доступно через уже
  существующий `create_storage()`.

- [ ] **Step 1: Написать падающий тест**

`libs/integrations/tests/test_storage_filesystem.py` — добавить в конец
файла:

```python
async def test_put_then_get_returns_the_same_bytes(tmp_path: Path) -> None:
    storage = FilesystemStorage(str(tmp_path))

    await storage.put("bots/bot-1/products/prod-1/img-1", b"hello photo", "image/jpeg")
    result = await storage.get("bots/bot-1/products/prod-1/img-1")

    assert result == b"hello photo"


async def test_put_creates_missing_parent_directories(tmp_path: Path) -> None:
    storage = FilesystemStorage(str(tmp_path))

    await storage.put("bots/bot-1/products/prod-1/img-1", b"data", "image/png")

    assert (tmp_path / "bots" / "bot-1" / "products" / "prod-1" / "img-1").read_bytes() == b"data"


async def test_put_rejects_a_path_traversal_key(tmp_path: Path) -> None:
    root = tmp_path / "storage-root"
    root.mkdir()

    storage = FilesystemStorage(str(root))

    with pytest.raises(ValueError):
        await storage.put("../escaped", b"data", "image/jpeg")
```

`libs/integrations/tests/test_storage_s3.py` — добавить в конец файла:

```python
async def test_put_sends_object_with_content_type_via_injected_client() -> None:
    client = MagicMock()
    storage = S3Storage(bucket="my-bucket", client=client)

    await storage.put("bots/bot-1/products/prod-1/img-1", b"hello photo", "image/jpeg")

    client.put_object.assert_called_once_with(
        Bucket="my-bucket",
        Key="bots/bot-1/products/prod-1/img-1",
        Body=b"hello photo",
        ContentType="image/jpeg",
    )
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `.venv/Scripts/python.exe -m pytest libs/integrations/tests/test_storage_filesystem.py libs/integrations/tests/test_storage_s3.py -v`
Expected: FAIL — `AttributeError: 'FilesystemStorage' object has no attribute 'put'`
(и аналогично для `S3Storage`). Docker не нужен — эти тесты не используют
testcontainers.

- [ ] **Step 3: Реализовать**

`libs/integrations/src/integrations/storage/__init__.py` — заменить класс
`Storage`:

```python
class Storage(Protocol):
    async def get(self, key: str) -> bytes: ...
    async def put(self, key: str, data: bytes, mime_type: str) -> None: ...
```

`libs/integrations/src/integrations/storage/filesystem.py` — полностью:

```python
"""Storage поверх локальной ФС — общий docker-volume с gateway в dev
(см. compose/docker-compose.dev.yml, STORAGE_FS_ROOT)."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FilesystemStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _resolve_within_root(self, key: str) -> Path:
        root_resolved = self._root.resolve()
        path = (self._root / key).resolve()
        if not path.is_relative_to(root_resolved):
            raise ValueError(f"storage key resolves outside root: {key!r}")
        return path

    async def get(self, key: str) -> bytes:
        path = self._resolve_within_root(key)
        return await asyncio.to_thread(path.read_bytes)

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        # mime_type не нужен для fs (нет метаданных объекта) — принимается
        # только чтобы сигнатура совпадала с Storage Protocol/S3Storage.
        path = self._resolve_within_root(key)
        await asyncio.to_thread(self._write_sync, path, data)

    def _write_sync(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
```

`libs/integrations/src/integrations/storage/s3.py` — добавить метод `put`
в класс `S3Storage` (после существующего `get`/`_get_sync`):

```python
    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        await asyncio.to_thread(self._put_sync, key, data, mime_type)

    def _put_sync(self, key: str, data: bytes, mime_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=mime_type)
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `.venv/Scripts/python.exe -m pytest libs/integrations/tests/test_storage_filesystem.py libs/integrations/tests/test_storage_s3.py -v`
Expected: PASS (все тесты, включая уже существовавшие `get`)

- [ ] **Step 5: Коммит**

```bash
git add libs/integrations/src/integrations/storage/__init__.py libs/integrations/src/integrations/storage/filesystem.py libs/integrations/src/integrations/storage/s3.py libs/integrations/tests/test_storage_filesystem.py libs/integrations/tests/test_storage_s3.py
git commit -m "feat(integrations): add Storage.put() for filesystem and s3

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `db.product_images` write-функции + `Product.photos` relationship

**Files:**
- Modify: `libs/db/src/db/models.py`
- Modify: `libs/db/src/db/product_images.py`
- Modify: `libs/db/src/db/products.py`
- Test: `libs/db/tests/test_product_images.py`
- Test: `libs/db/tests/test_products.py`

**Interfaces:**
- Consumes: существующий `ProductImage` (`libs/db/src/db/models.py`).
- Produces:
  - `Product.photos: Mapped[list[ProductImage]]` — ORM relationship, `lazy="raise"`.
  - `db.product_images.get_product_image(session, product_id, photo_id) -> ProductImage | None`
  - `db.product_images.create_product_image(session, product_id, *, id, storage_key, mime_type, position) -> ProductImage`
  - `db.product_images.delete_product_image(session, product_id, photo_id) -> bool`
  - `db.product_images.next_position(session, product_id) -> int`
  - `db.products.get_product(session, bot_id, product_id, *, with_images=False) -> Product | None` (новый kwarg)
  - `db.products.list_products(session, bot_id, *, limit=..., offset=0, with_images=False) -> list[Product]` (новый kwarg)

- [ ] **Step 1: Написать падающий тест**

`libs/db/tests/test_product_images.py` — заменить блок импорта:

```python
from db.product_images import list_product_images
```

на:

```python
from db.product_images import (
    create_product_image,
    delete_product_image,
    get_product_image,
    list_product_images,
    next_position,
)
```

В конец файла добавить:

```python
async def test_next_position_is_zero_when_no_images(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await next_position(session, product_id) == 0


async def test_next_position_is_max_plus_one(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    session.add_all(
        [
            ProductImage(product_id=product_id, storage_key="img-0", mime_type="image/jpeg", position=0),
            ProductImage(product_id=product_id, storage_key="img-2", mime_type="image/jpeg", position=2),
        ]
    )
    await session.flush()

    # Позиция 1 пропущена (например, удалили) — следующая всё равно 3,
    # не переиспользует дыру: next_position = max(position) + 1.
    assert await next_position(session, product_id) == 3


async def test_create_product_image_uses_given_id(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    photo_id = uuid.uuid4()

    image = await create_product_image(
        session, product_id, id=photo_id, storage_key="k", mime_type="image/jpeg", position=0
    )

    assert image.id == photo_id
    assert image.storage_key == "k"


async def test_get_product_image_returns_none_when_missing(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await get_product_image(session, product_id, uuid.uuid4()) is None


async def test_get_product_image_scoped_per_product(session: AsyncSession) -> None:
    product_a = await _make_product(session)
    product_b = await _make_product(session)
    image = await create_product_image(
        session, product_a, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    assert await get_product_image(session, product_a, image.id) is not None
    assert await get_product_image(session, product_b, image.id) is None


async def test_delete_product_image_removes_row(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    image = await create_product_image(
        session, product_id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    deleted = await delete_product_image(session, product_id, image.id)
    assert deleted is True
    assert await get_product_image(session, product_id, image.id) is None


async def test_delete_product_image_returns_false_when_missing(session: AsyncSession) -> None:
    product_id = await _make_product(session)
    assert await delete_product_image(session, product_id, uuid.uuid4()) is False
```

`libs/db/tests/test_products.py` — заменить блок импорта:

```python
from db.products import (
    create_product,
    delete_product,
    find_product_by_exact_name,
    get_product,
    list_products,
    update_product,
)
```

на:

```python
from db.product_images import create_product_image
from db.products import (
    create_product,
    delete_product,
    find_product_by_exact_name,
    get_product,
    list_products,
    update_product,
)
from sqlalchemy.exc import InvalidRequestError
```

В конец файла добавить:

```python
async def test_get_product_without_with_images_does_not_load_photos(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар")
    await create_product_image(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    fetched = await get_product(session, bot_id, product.id)
    assert fetched is not None
    with pytest.raises(InvalidRequestError):  # lazy="raise" — доступ без with_images кидает это
        _ = fetched.photos


async def test_get_product_with_images_loads_photos(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар")
    await create_product_image(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    fetched = await get_product(session, bot_id, product.id, with_images=True)
    assert fetched is not None
    assert len(fetched.photos) == 1
    assert fetched.photos[0].storage_key == "k"


async def test_list_products_with_images_loads_photos_for_every_row(session: AsyncSession) -> None:
    bot_id = await _make_bot(session)
    product = await create_product(session, bot_id, name="Товар")
    await create_product_image(
        session, product.id, id=uuid.uuid4(), storage_key="k", mime_type="image/jpeg", position=0
    )

    products = await list_products(session, bot_id, with_images=True)
    assert len(products) == 1
    assert len(products[0].photos) == 1
```

(`pytest` уже импортирован в `test_products.py` как зависимость
`testcontainers.postgres`-гейта; `uuid` — тоже уже импортирован верхним
блоком файла, отдельно добавлять не нужно.)

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `.venv/Scripts/python.exe -m pytest libs/db/tests/test_product_images.py libs/db/tests/test_products.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_product_image'`
(и аналогично для остальных новых имён). Если Docker недоступен — все
тесты `SKIPPED`, это ожидаемо.

- [ ] **Step 3: Реализовать**

`libs/db/src/db/models.py` — в классе `Product` (после поля `created_at`,
перед закрывающей пустой строкой класса) добавить:

```python
    # lazy="raise" — доступ к .photos без явного selectinload() кидает
    # понятную ошибку сразу, а не MissingGreenlet где-то в сериализации:
    # async SQLAlchemy не умеет лениво подгружать relationship вне активного
    # await-контекста. db.products.get_product/list_products грузят photos
    # явно только когда вызывающий передаёт with_images=True (api-роутер) —
    # worker (контекст LLM, product_search) не платит лишним запросом за то,
    # что не использует.
    photos: Mapped[list["ProductImage"]] = relationship(
        order_by="ProductImage.position", lazy="raise"
    )
```

`libs/db/src/db/product_images.py` — полностью:

```python
"""Фото товара (FEATURES.md 4.3/4.4/6.8) — чтение и запись."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProductImage


async def list_product_images(session: AsyncSession, product_id: uuid.UUID) -> list[ProductImage]:
    stmt = (
        select(ProductImage)
        .where(ProductImage.product_id == product_id)
        .order_by(ProductImage.position)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_product_image(
    session: AsyncSession, product_id: uuid.UUID, photo_id: uuid.UUID
) -> ProductImage | None:
    """Скоуп по product_id И photo_id вместе — чужое фото не находится
    (тот же принцип, что db.products.get_product). Вызывающий (api-роутер)
    сам уже проверил, что product_id принадлежит нужному bot_id, до этого
    вызова — здесь второй уровень скоупа поверх первого."""
    stmt = select(ProductImage).where(
        ProductImage.product_id == product_id, ProductImage.id == photo_id
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_product_image(
    session: AsyncSession,
    product_id: uuid.UUID,
    *,
    id: uuid.UUID,
    storage_key: str,
    mime_type: str,
    position: int,
) -> ProductImage:
    """id передаётся явно (не полагаемся на server_default) — storage_key
    строится из photo_id ДО вставки строки (см. api.product_photos), а
    Storage.put() должен успеть до commit, значит id нужен заранее."""
    image = ProductImage(
        id=id, product_id=product_id, storage_key=storage_key, mime_type=mime_type, position=position
    )
    session.add(image)
    await session.flush()
    return image


async def delete_product_image(
    session: AsyncSession, product_id: uuid.UUID, photo_id: uuid.UUID
) -> bool:
    image = await get_product_image(session, product_id, photo_id)
    if image is None:
        return False
    await session.delete(image)
    await session.flush()
    return True


async def next_position(session: AsyncSession, product_id: uuid.UUID) -> int:
    """max(position) + 1, не count() — удаление создаёт дыры в позициях,
    переиспользовать их нельзя (UniqueConstraint(product_id, position) не
    единственная причина: две функции, использующие переиспользованную
    позицию, легко перезаписали бы друг друга по смыслу порядка)."""
    stmt = select(func.coalesce(func.max(ProductImage.position), -1) + 1).where(
        ProductImage.product_id == product_id
    )
    result = await session.execute(stmt)
    return result.scalar_one()
```

`libs/db/src/db/products.py` — заменить импорт:

```python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
```

на:

```python
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
```

и функции `list_products`/`get_product` — целиком:

```python
async def list_products(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    limit: int = DEFAULT_CATALOG_LIMIT,
    offset: int = 0,
    with_images: bool = False,
) -> list[Product]:
    stmt = (
        select(Product)
        .where(Product.bot_id == bot_id)
        .order_by(Product.name)
        .limit(limit)
        .offset(offset)
    )
    if with_images:
        stmt = stmt.options(selectinload(Product.photos))
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

```python
async def get_product(
    session: AsyncSession, bot_id: uuid.UUID, product_id: uuid.UUID, *, with_images: bool = False
) -> Product | None:
    """Скоуп по bot_id И product_id вместе — товар чужого бота не должен
    быть виден даже как "существует, но 403", а просто не находится (404)."""
    stmt = select(Product).where(Product.bot_id == bot_id, Product.id == product_id)
    if with_images:
        stmt = stmt.options(selectinload(Product.photos))
    result = await session.execute(stmt)
    return result.scalars().first()
```

(Остальные функции файла — `find_product_by_exact_name`, `create_product`,
`update_product`, `delete_product` — не меняются; `update_product`/
`delete_product` вызывают `get_product` без `with_images`, дефолт `False`
сохраняет их прежнее поведение.)

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `.venv/Scripts/python.exe -m pytest libs/db/tests/test_product_images.py libs/db/tests/test_products.py -v`
Expected: PASS (все тесты; при недоступном Docker — SKIPPED, 0 errors)

- [ ] **Step 5: Коммит**

```bash
git add libs/db/src/db/models.py libs/db/src/db/product_images.py libs/db/src/db/products.py libs/db/tests/test_product_images.py libs/db/tests/test_products.py
git commit -m "feat(db): add product_images write functions and Product.photos relationship

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `services/api` — StorageDep, валидация/ресайз фото, зависимости

**Files:**
- Create: `services/api/src/api/storage.py`
- Create: `services/api/src/api/product_photos.py`
- Modify: `services/api/pyproject.toml`
- Modify: `compose/docker-compose.dev.yml`
- Modify: `compose/docker-compose.prod.yml`
- Test: `services/api/tests/test_product_photos.py`

**Interfaces:**
- Consumes: `integrations.storage.Storage`/`create_storage` (Task 1, уже
  существующий пакет).
- Produces:
  - `api.storage.get_storage() -> Storage`, `api.storage.StorageDep = Annotated[Storage, Depends(get_storage)]`
  - `api.product_photos.PhotoValidationError(Exception)`
  - `api.product_photos.ALLOWED_PHOTO_MIME_TYPES: frozenset[str]`
  - `api.product_photos.MAX_PHOTO_SIZE_BYTES: int`
  - `api.product_photos.MAX_PHOTOS_PER_PRODUCT: int`
  - `api.product_photos.PHOTO_RESIZE_MAX_DIMENSION: int`
  - `api.product_photos.validate_photo_uploads(uploads: list[UploadFile], *, max_count: int) -> None` (raises `PhotoValidationError`)
  - `api.product_photos.read_and_resize_photo(upload: UploadFile) -> tuple[bytes, str]` (raises `PhotoValidationError`)
  - `api.product_photos.build_photo_storage_key(bot_id: uuid.UUID, product_id: uuid.UUID, photo_id: uuid.UUID) -> str`

Это не отдельный HTTP-эндпоинт — вся работа этой задачи тестируется юнит-тестами
без Docker (нет testcontainers-гейта в новом тестовом файле).

- [ ] **Step 1: Написать падающий тест**

Создать `services/api/tests/test_product_photos.py`:

```python
"""api.product_photos: валидация метаданных загрузки (тип/размер/количество)
и раскодирование+ресайз (Pillow) — decode здесь же служит валидацией
(битый файл -> PhotoValidationError, не мусор в Storage). Без Docker — эти
тесты юнит-уровня, testcontainers не нужен.
"""

from __future__ import annotations

import io
import uuid
from typing import BinaryIO

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from api.product_photos import (
    MAX_PHOTO_SIZE_BYTES,
    MAX_PHOTOS_PER_PRODUCT,
    PHOTO_RESIZE_MAX_DIMENSION,
    PhotoValidationError,
    build_photo_storage_key,
    read_and_resize_photo,
    validate_photo_uploads,
)


def _make_upload(data: bytes, *, content_type: str, filename: str = "photo.jpg") -> UploadFile:
    file: BinaryIO = io.BytesIO(data)
    # headers передаётся конструктору, не присваивается после — Starlette's
    # Headers иммутабелен (нет поддержки headers[...] = ...).
    headers = Headers({"content-type": content_type})
    return UploadFile(file=file, filename=filename, size=len(data), headers=headers)


def _tiny_jpeg_bytes(*, size: tuple[int, int] = (20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color="red").save(buf, format="JPEG")
    return buf.getvalue()


def test_validate_photo_uploads_rejects_empty_list() -> None:
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads([], max_count=MAX_PHOTOS_PER_PRODUCT)


def test_validate_photo_uploads_rejects_more_than_max_count() -> None:
    uploads = [_make_upload(b"x", content_type="image/jpeg") for _ in range(3)]
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads(uploads, max_count=2)


def test_validate_photo_uploads_rejects_unsupported_mime_type() -> None:
    upload = _make_upload(b"not an image", content_type="text/plain")
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads([upload], max_count=MAX_PHOTOS_PER_PRODUCT)


def test_validate_photo_uploads_rejects_oversized_file() -> None:
    upload = _make_upload(b"x" * (MAX_PHOTO_SIZE_BYTES + 1), content_type="image/jpeg")
    with pytest.raises(PhotoValidationError):
        validate_photo_uploads([upload], max_count=MAX_PHOTOS_PER_PRODUCT)


def test_validate_photo_uploads_accepts_a_valid_photo() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(), content_type="image/jpeg")
    validate_photo_uploads([upload], max_count=MAX_PHOTOS_PER_PRODUCT)  # не бросает


async def test_read_and_resize_photo_returns_bytes_and_mime_type() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(), content_type="image/jpeg")

    data, mime_type = await read_and_resize_photo(upload)

    assert mime_type == "image/jpeg"
    assert Image.open(io.BytesIO(data)).format == "JPEG"


async def test_read_and_resize_photo_shrinks_large_images() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(size=(2000, 1000)), content_type="image/jpeg")

    data, _ = await read_and_resize_photo(upload)

    resized = Image.open(io.BytesIO(data))
    assert resized.width <= PHOTO_RESIZE_MAX_DIMENSION
    assert resized.height <= PHOTO_RESIZE_MAX_DIMENSION


async def test_read_and_resize_photo_keeps_small_images_unchanged_in_size() -> None:
    upload = _make_upload(_tiny_jpeg_bytes(size=(20, 20)), content_type="image/jpeg")

    data, _ = await read_and_resize_photo(upload)

    resized = Image.open(io.BytesIO(data))
    assert resized.size == (20, 20)


async def test_read_and_resize_photo_rejects_corrupt_file() -> None:
    upload = _make_upload(b"this is not a real image file", content_type="image/jpeg")

    with pytest.raises(PhotoValidationError):
        await read_and_resize_photo(upload)


def test_build_photo_storage_key_format() -> None:
    bot_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    product_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    photo_id = uuid.UUID("33333333-3333-3333-3333-333333333333")

    key = build_photo_storage_key(bot_id, product_id, photo_id)

    assert key == (
        "bots/11111111-1111-1111-1111-111111111111/"
        "products/22222222-2222-2222-2222-222222222222/"
        "33333333-3333-3333-3333-333333333333"
    )
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `.venv/Scripts/python.exe -m pytest services/api/tests/test_product_photos.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.product_photos'`

- [ ] **Step 3: Реализовать**

`services/api/src/api/storage.py` (новый файл):

```python
"""Storage-зависимость для api (FEATURES.md 6.8, загрузка фото товара).

Ленивая инициализация — тот же принцип, что и SessionDep (api/db.py): не
создавать клиента на импорте модуля, чтобы тесты могли подменить
зависимость через dependency_overrides до первого реального использования.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from integrations.storage import Storage, create_storage

_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = create_storage()
    return _storage


StorageDep = Annotated[Storage, Depends(get_storage)]
```

`services/api/src/api/product_photos.py` (новый файл):

```python
"""Валидация и подготовка фото товара к загрузке (FEATURES.md 6.8).

Два уровня проверки: validate_photo_uploads — дешёвая, по метаданным
(количество/тип/размер), до чтения тела файлов; read_and_resize_photo —
раскодирование Pillow (заодно и валидация: битый файл здесь становится
PhotoValidationError, не мусором в Storage) + ресайз до
PHOTO_RESIZE_MAX_DIMENSION по длинной стороне, формат не меняется.
"""

from __future__ import annotations

import asyncio
import io
import uuid

from fastapi import UploadFile
from PIL import Image

ALLOWED_PHOTO_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_PHOTO_SIZE_BYTES = 10 * 1024 * 1024
MAX_PHOTOS_PER_PRODUCT = 10
PHOTO_RESIZE_MAX_DIMENSION = 1280

_PIL_FORMAT_BY_MIME = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class PhotoValidationError(Exception):
    pass


def validate_photo_uploads(uploads: list[UploadFile], *, max_count: int) -> None:
    if not uploads:
        raise PhotoValidationError("at least one photo is required")
    if len(uploads) > max_count:
        raise PhotoValidationError(f"at most {max_count} photos allowed")
    for upload in uploads:
        if upload.content_type not in ALLOWED_PHOTO_MIME_TYPES:
            raise PhotoValidationError(f"unsupported photo type: {upload.content_type}")
        if upload.size is not None and upload.size > MAX_PHOTO_SIZE_BYTES:
            raise PhotoValidationError(f"photo too large: {upload.filename}")


async def read_and_resize_photo(upload: UploadFile) -> tuple[bytes, str]:
    raw = await upload.read()
    mime_type = upload.content_type or "application/octet-stream"
    save_format = _PIL_FORMAT_BY_MIME.get(mime_type, "JPEG")
    try:
        data = await asyncio.to_thread(_decode_resize_encode, raw, save_format)
    except Exception as exc:
        raise PhotoValidationError(f"invalid image file: {upload.filename}") from exc
    return data, mime_type


def _decode_resize_encode(raw: bytes, save_format: str) -> bytes:
    image = Image.open(io.BytesIO(raw))
    image.load()  # Image.open ленив — decode форсируется тут, битые байты всплывают здесь
    if image.width > PHOTO_RESIZE_MAX_DIMENSION or image.height > PHOTO_RESIZE_MAX_DIMENSION:
        image.thumbnail((PHOTO_RESIZE_MAX_DIMENSION, PHOTO_RESIZE_MAX_DIMENSION))
    if save_format == "JPEG" and image.mode in ("RGBA", "P"):
        # JPEG не поддерживает альфа-канал/палитру — конвертируем, иначе
        # save() падает на PNG/GIF, ошибочно помеченных как image/jpeg.
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format=save_format)
    return buf.getvalue()


def build_photo_storage_key(bot_id: uuid.UUID, product_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return f"bots/{bot_id}/products/{product_id}/{photo_id}"
```

`services/api/pyproject.toml` — заменить блок `dependencies`:

```toml
dependencies = [
    "core",
    "db",
    "integrations",
    "llm",
    "scheduling",
    "tools",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "redis>=5.0",
    "python-multipart>=0.0.9",
    "Pillow>=10.4",
]
```

`compose/docker-compose.dev.yml` — блок `api`: добавить `STORAGE_DRIVER`/
`STORAGE_FS_ROOT` в `environment` и volume `media-data:/data/media`
(тот же volume, что уже у `gateway`/`worker`) — найти текущий блок
`api:` (`environment:`/`volumes:` секции внутри него) и заменить целиком на:

```yaml
  api:
    build:
      context: ..
      dockerfile: services/api/Dockerfile
    environment:
      DATABASE_URL: postgres://platform:platform@postgres:5432/platform
      REDIS_URL: redis://redis:6379/0
      GATEWAY_URL: http://gateway:8080
      ADMIN_WEB_ORIGIN: http://localhost:3000
      STORAGE_DRIVER: fs
      STORAGE_FS_ROOT: /data/media
      # Секреты — из .env на хосте (ADR-007), не хардкодим сюда.
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    ports:
      - "8000:8000"
    volumes:
      - ../services/api/src:/app/services/api/src
      - ../libs:/app/libs
      - media-data:/data/media
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      gateway:
        condition: service_started
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      timeout: 5s
      retries: 10
```

`compose/docker-compose.prod.yml` — блок `api`: добавить `STORAGE_DRIVER`/
`S3_*` в `environment` (S3-драйвер в проде, без volume — так же, как у
`worker`/`gateway` в этом файле). Найти текущий блок `api:` и заменить
`environment:` на:

```yaml
    environment:
      DATABASE_URL: postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://redis:6379/0
      GATEWAY_URL: http://gateway:8080
      ADMIN_WEB_ORIGIN: ${ADMIN_WEB_ORIGIN:-http://127.0.0.1:3000}
      OPENAI_API_KEY: ${OPENAI_API_KEY:?OPENAI_API_KEY не задан в .env}
      STORAGE_DRIVER: s3
      S3_ENDPOINT: ${S3_ENDPOINT:?S3_ENDPOINT не задан в .env}
      S3_BUCKET: ${S3_BUCKET:?S3_BUCKET не задан в .env}
      S3_REGION: ${S3_REGION:-fra1}
      S3_ACCESS_KEY: ${S3_ACCESS_KEY:?S3_ACCESS_KEY не задан в .env}
      S3_SECRET_KEY: ${S3_SECRET_KEY:?S3_SECRET_KEY не задан в .env}
```

(остальные ключи блока `api:` — `ports`/`restart`/`depends_on`/
`healthcheck` — не менять)

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `.venv/Scripts/python.exe -m pip install -e services/api` (подтягивает
`python-multipart`/`Pillow` в общий dev-venv — оба новые для проекта)

Run: `.venv/Scripts/python.exe -m pytest services/api/tests/test_product_photos.py -v`
Expected: PASS (11 тестов, реальный прогон — Docker не нужен, это чистые
юнит-тесты)

- [ ] **Step 5: Коммит**

```bash
git add services/api/src/api/storage.py services/api/src/api/product_photos.py services/api/pyproject.toml compose/docker-compose.dev.yml compose/docker-compose.prod.yml services/api/tests/test_product_photos.py
git commit -m "feat(api): photo validation/resize helpers, StorageDep, storage env wiring

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `POST /bots/{bot_id}/products` — multipart, обязательное фото

**Files:**
- Modify: `services/api/src/api/schemas/products.py`
- Modify: `services/api/src/api/routers/products.py`
- Modify: `services/api/tests/test_products.py`

**Interfaces:**
- Consumes: `api.storage.StorageDep`, `api.product_photos.{PhotoValidationError,validate_photo_uploads,read_and_resize_photo,build_photo_storage_key,MAX_PHOTOS_PER_PRODUCT}`
  (Task 3), `db.product_images.create_product_image` (Task 2),
  `db.products.{get_product,list_products}` с `with_images=True` (Task 2).
- Produces: `POST /bots/{bot_id}/products` — теперь `multipart/form-data`;
  `ProductOut.photos: list[ProductPhotoOut]`; схема `ProductCreate`
  удаляется (была JSON-only, POST больше не принимает JSON body).

Это самая крупная задача плана — переписывает уже существующий роут и
МИГРИРУЕТ все существующие тесты создания товара на multipart (были JSON).

- [ ] **Step 1: Написать падающий тест**

`services/api/tests/test_products.py` — внести все изменения ниже одним
проходом (тест УЖЕ падает после Step 3, но так проще один раз пройтись по
файлу, чем чередовать).

Заменить блок импортов (в начале файла) на:

```python
from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from PIL import Image

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from api.routers import products as products_module
from api.storage import get_storage
from db.engine import make_engine, make_session_factory
from db.models import Bot
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
```

Добавить после класса `_FakeCeleryApp`/фикстуры `fake_celery` (перед
фикстурой `client`) — фейковое хранилище и хелперы фото:

```python
class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.objects[key] = (data, mime_type)


@pytest.fixture
def fake_storage() -> _FakeStorage:
    return _FakeStorage()


def _tiny_jpeg_bytes(*, size: tuple[int, int] = (20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color="red").save(buf, format="JPEG")
    return buf.getvalue()


def _photo_file(name: str = "photo.jpg") -> tuple[str, tuple[str, bytes, str]]:
    return ("photos", (name, _tiny_jpeg_bytes(), "image/jpeg"))
```

Заменить фикстуру `client` целиком:

```python
@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_storage] = lambda: fake_storage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

Заменить ВСЕ существующие вызовы `client.post(f"/bots/{bot_id}/products",
json={...})` на multipart-эквиваленты — по одному на каждую из существующих
функций (не переименовывать сами функции):

```python
async def test_create_product_requires_name(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products", data={"name": "   "}, files=[_photo_file()]
    )
    assert response.status_code == 422


async def test_create_product_for_unknown_bot_returns_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        f"/bots/{uuid.uuid4()}/products", data={"name": "Товар"}, files=[_photo_file()]
    )
    assert response.status_code == 404


async def test_create_computes_embedding_and_returns_product(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Кроссовки", "description": "Беговые", "price": "5000"},
        files=[_photo_file()],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Кроссовки"
    assert body["price"] == "5000"
    assert len(body["photos"]) == 1

    async with session_factory() as session:
        from db.product_embeddings import find_product_by_embedding

        found = await find_product_by_embedding(session, bot_id, FAKE_EMBEDDING, threshold=0.0)
        assert found is not None
        assert found.id == uuid.UUID(body["id"])


async def test_create_list_get_flow(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)

    created = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_photo_file()]
    )
    product_id = created.json()["id"]

    listing = await client.get(f"/bots/{bot_id}/products")
    assert listing.status_code == 200
    assert [p["id"] for p in listing.json()] == [product_id]
    assert len(listing.json()[0]["photos"]) == 1

    fetched = await client.get(f"/bots/{bot_id}/products/{product_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == product_id
    assert len(fetched.json()["photos"]) == 1


async def test_list_products_respects_limit_and_offset(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    for name in ("Апельсины", "Бананы", "Вишня"):
        await client.post(f"/bots/{bot_id}/products", data={"name": name}, files=[_photo_file()])

    first_page = await client.get(f"/bots/{bot_id}/products", params={"limit": 2})
    assert first_page.status_code == 200
    assert [p["name"] for p in first_page.json()] == ["Апельсины", "Бананы"]

    second_page = await client.get(
        f"/bots/{bot_id}/products", params={"limit": 2, "offset": 2}
    )
    assert [p["name"] for p in second_page.json()] == ["Вишня"]
```

(остальные тесты этого файла — `test_list_products_limit_out_of_range_returns_422`,
`test_default_list_limit_matches_prior_http_behavior`,
`test_get_patch_delete_unknown_product_returns_404` — не создают товар
через `POST`, не трогать)

```python
async def test_patch_price_only_does_not_recompute_embedding(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def counting_generate_embedding(text: str, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", counting_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Описание"},
        files=[_photo_file()],
    )
    product_id = created.json()["id"]
    assert calls == 1  # создание всегда считает эмбеддинг

    response = await client.patch(f"/bots/{bot_id}/products/{product_id}", json={"price": 999})
    assert response.status_code == 200
    assert calls == 1  # цена — не name/description, пересчёта не было


async def test_patch_description_recomputes_embedding(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def counting_generate_embedding(text: str, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", counting_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Старое"},
        files=[_photo_file()],
    )
    product_id = created.json()["id"]
    assert calls == 1

    response = await client.patch(
        f"/bots/{bot_id}/products/{product_id}", json={"description": "Новое"}
    )
    assert response.status_code == 200
    assert calls == 2


async def test_patch_description_same_value_does_not_recompute_embedding(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def counting_generate_embedding(text: str, **kwargs: object) -> list[float]:
        nonlocal calls
        calls += 1
        return FAKE_EMBEDDING

    monkeypatch.setattr(products_module, "generate_embedding", counting_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар", "description": "Без изменений"},
        files=[_photo_file()],
    )
    product_id = created.json()["id"]
    assert calls == 1

    response = await client.patch(
        f"/bots/{bot_id}/products/{product_id}", json={"description": "Без изменений"}
    )
    assert response.status_code == 200
    assert calls == 1


async def test_create_falls_back_to_celery_when_embedding_fails(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    fake_celery: _FakeCeleryApp,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _failing_generate_embedding)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_photo_file()]
    )

    # Товар всё равно создаётся, несмотря на сбой эмбеддинга.
    assert response.status_code == 201
    product_id = response.json()["id"]

    assert len(fake_celery.calls) == 1
    assert fake_celery.calls[0]["name"] == RECOMPUTE_PRODUCT_EMBEDDING
    assert fake_celery.calls[0]["args"] == [product_id]


async def test_delete_product_removes_it(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_photo_file()]
    )
    product_id = created.json()["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product_id}")
    assert response.status_code == 204

    assert (await client.get(f"/bots/{bot_id}/products/{product_id}")).status_code == 404
```

В конец файла добавить новые тесты на обязательность/валидацию фото и
откат при сбое Storage:

```python
async def test_create_product_without_photos_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"})
    assert response.status_code == 422


async def test_create_product_rejects_unsupported_mime_type(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар"},
        files=[("photos", ("file.txt", b"not an image", "text/plain"))],
    )
    assert response.status_code == 422


async def test_create_product_rejects_corrupt_image(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products",
        data={"name": "Товар"},
        files=[("photos", ("photo.jpg", b"garbage bytes, not a real jpeg", "image/jpeg"))],
    )
    assert response.status_code == 422


async def test_create_product_rejects_more_than_max_photos(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # products_module импортировал MAX_PHOTOS_PER_PRODUCT через
    # "from ..product_photos import MAX_PHOTOS_PER_PRODUCT" — это отдельное
    # имя в его собственном namespace, патчить нужно именно его; патч
    # "api.product_photos.MAX_PHOTOS_PER_PRODUCT" на уже импортированную
    # константу в products_module никак не повлияет.
    monkeypatch.setattr(products_module, "MAX_PHOTOS_PER_PRODUCT", 2)
    bot_id = await _make_bot(session_factory)
    files = [_photo_file(f"photo{i}.jpg") for i in range(3)]
    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"}, files=files)
    assert response.status_code == 422


async def test_create_product_stores_multiple_photos_in_order(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    files = [_photo_file("a.jpg"), _photo_file("b.jpg")]

    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"}, files=files)

    assert response.status_code == 201
    photos = response.json()["photos"]
    assert len(photos) == 2
    assert [p["position"] for p in photos] == [0, 1]


async def test_create_product_rolls_back_when_storage_fails(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_put(key: str, data: bytes, mime_type: str) -> None:
        raise RuntimeError("storage недоступен")

    # fake_storage — тот же экземпляр, что фикстура client уже подключила
    # через dependency_overrides; патчим один метод, не подменяем всю
    # зависимость — проще и не завязано на порядок teardown между тестами.
    monkeypatch.setattr(fake_storage, "put", failing_put)
    bot_id = await _make_bot(session_factory)

    response = await client.post(
        f"/bots/{bot_id}/products", data={"name": "Товар"}, files=[_photo_file()]
    )
    assert response.status_code == 502

    listing = await client.get(f"/bots/{bot_id}/products")
    assert listing.json() == []
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `.venv/Scripts/python.exe -m pytest services/api/tests/test_products.py -v`
Expected: FAIL — старый роут ещё принимает только JSON, `data=`/`files=`
запросы получат 422 от Pydantic (тело не распознано) вместо ожидаемых
статусов. Если Docker недоступен — все тесты `SKIPPED`, это ожидаемо; в
этом случае проверить хотя бы **синтаксическую валидность** правки:
`.venv/Scripts/python.exe -m py_compile services/api/tests/test_products.py`
должен пройти без ошибок.

- [ ] **Step 3: Реализовать**

`services/api/src/api/schemas/products.py` — полностью:

```python
"""Pydantic v2 схемы товара для api (FEATURES.md 6.8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProductPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    price: Decimal | None
    sku: str | None
    description: str | None
    display_custom: dict[str, Any]
    photos: list[ProductPhotoOut]
    created_at: datetime


class ProductPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные
    (exclude_unset). None для price/sku/description неотличим от "поле не
    передано" на уровне db.products.update_product — тот же принятый
    паттерн, что и BotPatch.image_prompt/pdf_prompt."""

    name: str | None = None
    price: Decimal | None = None
    sku: str | None = None
    description: str | None = None
    display_custom: dict[str, Any] | None = None
```

(`ProductCreate` удалён — `POST` больше не принимает JSON-тело, поля идут
через `Form`/`File` параметры роута)

`services/api/src/api/routers/products.py` — заменить блок импортов:

```python
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

import structlog
from db.bots import get_bot
from db.models import Product
from db.product_embeddings import upsert_embedding
from db.product_images import create_product_image
from db.products import (
    DEFAULT_CATALOG_LIMIT,
    create_product,
    delete_product,
    get_product,
    list_products,
    update_product,
)
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from llm.embeddings import generate_embedding, product_embedding_input
from scheduling.celery_app import celery_app
from scheduling.task_names import RECOMPUTE_PRODUCT_EMBEDDING
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionDep
from ..product_photos import (
    MAX_PHOTOS_PER_PRODUCT,
    PhotoValidationError,
    build_photo_storage_key,
    read_and_resize_photo,
    validate_photo_uploads,
)
from ..schemas.products import ProductOut, ProductPatch, ProductPhotoOut
from ..storage import StorageDep
```

(`from ..schemas.products import ProductCreate, ProductOut, ProductPatch`
удаляется — заменено на импорт без `ProductCreate` + `ProductPhotoOut`
выше)

После существующих `PRODUCT_EMBEDDING_SCHEDULE_TIMEOUT_SECONDS`/
`PRODUCTS_LIST_DEFAULT_LIMIT`/`PRODUCTS_LIST_MAX_LIMIT` (не трогать их)
добавить новую функцию-хелпер перед `_recompute_embedding`:

```python
def _parse_display_custom(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="display_custom must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail="display_custom must be a JSON object")
    return parsed
```

Заменить `list_products_route` (добавить `with_images=True`):

```python
@router.get("/{bot_id}/products", response_model=list[ProductOut])
async def list_products_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    limit: int = Query(PRODUCTS_LIST_DEFAULT_LIMIT, ge=1, le=PRODUCTS_LIST_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[ProductOut]:
    products = await list_products(session, bot_id, limit=limit, offset=offset, with_images=True)
    return [ProductOut.model_validate(p) for p in products]
```

Заменить `create_product_route` целиком:

```python
@router.post("/{bot_id}/products", response_model=ProductOut, status_code=201)
async def create_product_route(
    bot_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    name: str = Form(...),
    price: Decimal | None = Form(None),
    sku: str | None = Form(None),
    description: str | None = Form(None),
    display_custom: str | None = Form(None),
    photos: list[UploadFile] = File(...),
) -> ProductOut:
    try:
        validate_photo_uploads(photos, max_count=MAX_PHOTOS_PER_PRODUCT)
    except PhotoValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    name_stripped = name.strip()
    if not name_stripped:
        raise HTTPException(status_code=422, detail="name must not be empty")

    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")

    display_custom_parsed = _parse_display_custom(display_custom)

    product = await create_product(
        session,
        bot_id,
        name=name_stripped,
        price=price,
        sku=sku,
        description=description,
        display_custom=display_custom_parsed,
    )
    await session.flush()  # нужен product.id для ключей Storage ниже

    try:
        for position, upload in enumerate(photos):
            data, mime_type = await read_and_resize_photo(upload)
            photo_id = uuid.uuid4()
            key = build_photo_storage_key(bot_id, product.id, photo_id)
            await storage.put(key, data, mime_type)
            await create_product_image(
                session, product.id, id=photo_id, storage_key=key, mime_type=mime_type, position=position
            )
    except PhotoValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="failed to store product photo") from exc

    await session.commit()

    product = await get_product(session, bot_id, product.id, with_images=True)
    assert product is not None  # только что закоммитили
    await _recompute_embedding(session, product)
    return ProductOut.model_validate(product)
```

Заменить `get_product_route` (добавить `with_images=True`):

```python
@router.get("/{bot_id}/products/{product_id}", response_model=ProductOut)
async def get_product_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, session: SessionDep
) -> ProductOut:
    product = await get_product(session, bot_id, product_id, with_images=True)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return ProductOut.model_validate(product)
```

Заменить `patch_product_route` — только последние 4 строки (после
`if product.name != old_name or product.description != old_description:`),
перечитать товар с фото перед сериализацией:

```python
    if product.name != old_name or product.description != old_description:
        await _recompute_embedding(session, product)

    product = await get_product(session, bot_id, product_id, with_images=True)
    assert product is not None  # только что успешно обновили выше
    return ProductOut.model_validate(product)
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `.venv/Scripts/python.exe -m pytest services/api/tests/test_products.py services/api/tests/test_product_photos.py -v`
Expected: PASS (если Docker недоступен — тесты из `test_products.py`
`SKIPPED`, `test_product_photos.py` — реальный PASS, 0 errors в обоих
файлах)

Run: `.venv/Scripts/python.exe -m ruff check services/api/src/api/routers/products.py services/api/src/api/schemas/products.py services/api/tests/test_products.py`
Run: `.venv/Scripts/python.exe -m mypy services/api/src/api/routers/products.py services/api/src/api/schemas/products.py`
Expected: чисто

- [ ] **Step 5: Коммит**

```bash
git add services/api/src/api/schemas/products.py services/api/src/api/routers/products.py services/api/tests/test_products.py
git commit -m "feat(api): require photo(s) on product create, multipart POST

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Управление фото существующего товара (add/delete/get)

**Files:**
- Modify: `services/api/src/api/routers/products.py`
- Modify: `services/api/tests/test_products.py`

**Interfaces:**
- Consumes: `db.product_images.{get_product_image,delete_product_image,next_position}`,
  `db.product_images.list_product_images` (Task 2), всё из Task 3/4.
- Produces:
  - `POST /bots/{bot_id}/products/{product_id}/photos -> list[ProductPhotoOut]`
  - `DELETE /bots/{bot_id}/products/{product_id}/photos/{photo_id} -> 204 | 404 | 422`
  - `GET /bots/{bot_id}/products/{product_id}/photos/{photo_id} -> bytes` (Content-Type = mime_type)

- [ ] **Step 1: Написать падающий тест**

`services/api/tests/test_products.py` — в конец файла добавить:

```python
async def _create_product_with_photos(
    client: httpx.AsyncClient, bot_id: uuid.UUID, *, count: int = 1
) -> dict[str, object]:
    files = [_photo_file(f"p{i}.jpg") for i in range(count)]
    response = await client.post(f"/bots/{bot_id}/products", data={"name": "Товар"}, files=files)
    assert response.status_code == 201
    return response.json()


async def test_add_product_photos_appends_with_next_position(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id)

    response = await client.post(
        f"/bots/{bot_id}/products/{product['id']}/photos", files=[_photo_file("new.jpg")]
    )

    assert response.status_code == 201
    added = response.json()
    assert len(added) == 1
    assert added[0]["position"] == 1  # первое фото товара уже заняло 0


async def test_add_product_photos_rejects_exceeding_max_total(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    # Тот же нюанс, что в test_create_product_rejects_more_than_max_photos —
    # патчить нужно имя в namespace products_module, не в product_photos.
    monkeypatch.setattr(products_module, "MAX_PHOTOS_PER_PRODUCT", 2)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id, count=2)

    response = await client.post(
        f"/bots/{bot_id}/products/{product['id']}/photos", files=[_photo_file("one_too_many.jpg")]
    )

    assert response.status_code == 422


async def test_add_product_photos_for_unknown_product_returns_404(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/products/{uuid.uuid4()}/photos", files=[_photo_file()]
    )
    assert response.status_code == 404


async def test_delete_product_photo_removes_it_when_not_the_last_one(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id, count=2)
    photo_id = product["photos"][0]["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product['id']}/photos/{photo_id}")
    assert response.status_code == 204

    fetched = await client.get(f"/bots/{bot_id}/products/{product['id']}")
    assert len(fetched.json()["photos"]) == 1


async def test_delete_last_product_photo_returns_422(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id, count=1)
    photo_id = product["photos"][0]["id"]

    response = await client.delete(f"/bots/{bot_id}/products/{product['id']}/photos/{photo_id}")
    assert response.status_code == 422

    fetched = await client.get(f"/bots/{bot_id}/products/{product['id']}")
    assert len(fetched.json()["photos"]) == 1


async def test_delete_product_photo_unknown_id_returns_404(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id, count=1)

    response = await client.delete(
        f"/bots/{bot_id}/products/{product['id']}/photos/{uuid.uuid4()}"
    )
    assert response.status_code == 404


async def test_get_product_photo_returns_bytes_with_content_type(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id, count=1)
    photo_id = product["photos"][0]["id"]

    response = await client.get(f"/bots/{bot_id}/products/{product['id']}/photos/{photo_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) > 0


async def test_get_product_photo_unknown_id_returns_404(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(products_module, "generate_embedding", _fake_generate_embedding)
    bot_id = await _make_bot(session_factory)
    product = await _create_product_with_photos(client, bot_id, count=1)

    response = await client.get(
        f"/bots/{bot_id}/products/{product['id']}/photos/{uuid.uuid4()}"
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `.venv/Scripts/python.exe -m pytest services/api/tests/test_products.py -v -k "photo"`
Expected: FAIL — `404 Not Found` от FastAPI (роутов ещё нет) там, где тест
ждёт 201/204/200/422. Если Docker недоступен — `SKIPPED`.

- [ ] **Step 3: Реализовать**

`services/api/src/api/routers/products.py` — заменить импорт из
`db.product_images`:

```python
from db.product_images import create_product_image
```

на:

```python
from db.product_images import (
    create_product_image,
    delete_product_image,
    get_product_image,
    list_product_images,
    next_position,
)
```

Добавить 3 новых роута в конец файла (после `delete_product_route`):

```python
@router.post(
    "/{bot_id}/products/{product_id}/photos",
    response_model=list[ProductPhotoOut],
    status_code=201,
)
async def add_product_photos_route(
    bot_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    photos: list[UploadFile] = File(...),
) -> list[ProductPhotoOut]:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    existing_count = len(await list_product_images(session, product_id))
    remaining_slots = MAX_PHOTOS_PER_PRODUCT - existing_count
    try:
        validate_photo_uploads(photos, max_count=max(remaining_slots, 0))
    except PhotoValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    created: list[Any] = []
    try:
        for upload in photos:
            data, mime_type = await read_and_resize_photo(upload)
            position = await next_position(session, product_id)
            photo_id = uuid.uuid4()
            key = build_photo_storage_key(bot_id, product_id, photo_id)
            await storage.put(key, data, mime_type)
            image = await create_product_image(
                session, product_id, id=photo_id, storage_key=key, mime_type=mime_type, position=position
            )
            created.append(image)
    except PhotoValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail="failed to store product photo") from exc

    await session.commit()
    return [ProductPhotoOut.model_validate(img) for img in created]


@router.delete("/{bot_id}/products/{product_id}/photos/{photo_id}", status_code=204)
async def delete_product_photo_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, photo_id: uuid.UUID, session: SessionDep
) -> None:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    remaining = await list_product_images(session, product_id)
    if len(remaining) <= 1:
        if not any(img.id == photo_id for img in remaining):
            raise HTTPException(status_code=404, detail="photo not found")
        raise HTTPException(status_code=422, detail="cannot delete the last photo of a product")

    deleted = await delete_product_image(session, product_id, photo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="photo not found")
    await session.commit()


@router.get("/{bot_id}/products/{product_id}/photos/{photo_id}")
async def get_product_photo_route(
    bot_id: uuid.UUID, product_id: uuid.UUID, photo_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> Response:
    product = await get_product(session, bot_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    image = await get_product_image(session, product_id, photo_id)
    if image is None:
        raise HTTPException(status_code=404, detail="photo not found")
    try:
        data = await storage.get(image.storage_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="failed to read photo") from exc
    return Response(content=data, media_type=image.mime_type)
```

(`typing.Any` уже импортирован в файле для `_parse_display_custom` из
Task 4 — используется здесь для `created: list[Any]`)

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `.venv/Scripts/python.exe -m pytest services/api/tests/test_products.py -v`
Expected: PASS (весь файл целиком, включая Task 4 и Task 5 тесты)

Run: `.venv/Scripts/python.exe -m ruff check services/api/src/api/routers/products.py`
Run: `.venv/Scripts/python.exe -m mypy services/api/src/api/routers/products.py`
Expected: чисто

- [ ] **Step 5: Коммит**

```bash
git add services/api/src/api/routers/products.py services/api/tests/test_products.py
git commit -m "feat(api): add/delete/get individual product photos

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `lib/api.ts` — multipart createProduct, addProductPhotos, deleteProductPhoto

**Files:**
- Modify: `services/admin-web/lib/api.ts`
- Modify: `services/admin-web/lib/api.test.ts`

**Interfaces:**
- Produces:
  - `interface ProductPhoto { id: string; position: number }`
  - `Product.photos: ProductPhoto[]` (новое поле)
  - `productPhotoUrl(apiBaseUrl: string, botId: string, productId: string, photoId: string): string`
  - `createProduct(baseUrl: string, botId: string, input: ProductInput, photos: File[]): Promise<Product>` (сигнатура меняется — теперь multipart, требует `photos`)
  - `addProductPhotos(baseUrl: string, botId: string, productId: string, photos: File[]): Promise<ProductPhoto[]>`
  - `deleteProductPhoto(baseUrl: string, botId: string, productId: string, photoId: string): Promise<void>`

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/lib/api.test.ts` — найти блок `describe("createProduct", ...)`
и заменить его целиком:

```ts
describe("createProduct", () => {
  it("POSTs multipart form data with the given fields and photos", async () => {
    const created = {
      id: "p1",
      name: "Товар",
      price: null,
      sku: null,
      description: null,
      display_custom: {},
      photos: [{ id: "ph1", position: 0 }],
      created_at: "2026-09-10T10:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => created });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["fake image bytes"], "photo.jpg", { type: "image/jpeg" });

    const result = await createProduct("http://api", "1", { name: "Товар" }, [photo]);

    expect(result).toEqual(created);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/bots/1/products");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    const body = init.body as FormData;
    expect(body.get("name")).toBe("Товар");
    expect(body.getAll("photos")).toEqual([photo]);
  });

  it("omits optional fields from the form when not provided", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "p1",
        name: "Товар",
        price: null,
        sku: null,
        description: null,
        display_custom: {},
        photos: [],
        created_at: "2026-09-10T10:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    await createProduct("http://api", "1", { name: "Товар" }, [photo]);

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.has("price")).toBe(false);
    expect(body.has("sku")).toBe(false);
    expect(body.has("description")).toBe(false);
    expect(body.has("display_custom")).toBe(false);
  });

  it("sends display_custom as a JSON string when given", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "p1",
        name: "Товар",
        price: null,
        sku: null,
        description: null,
        display_custom: { show_price: false },
        photos: [],
        created_at: "2026-09-10T10:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    await createProduct(
      "http://api",
      "1",
      { name: "Товар", display_custom: { show_price: false } },
      [photo],
    );

    const body = fetchMock.mock.calls[0][1].body as FormData;
    expect(body.get("display_custom")).toBe(JSON.stringify({ show_price: false }));
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });
    await expect(createProduct("http://api", "1", { name: "x" }, [photo])).rejects.toThrow();
  });
});

describe("addProductPhotos", () => {
  it("POSTs multipart photos to the sub-resource", async () => {
    const added = [{ id: "ph2", position: 1 }];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => added });
    vi.stubGlobal("fetch", fetchMock);
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });

    const result = await addProductPhotos("http://api", "1", "p1", [photo]);

    expect(result).toEqual(added);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api/bots/1/products/p1/photos");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).getAll("photos")).toEqual([photo]);
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    const photo = new File(["x"], "photo.jpg", { type: "image/jpeg" });
    await expect(addProductPhotos("http://api", "1", "p1", [photo])).rejects.toThrow();
  });
});

describe("deleteProductPhoto", () => {
  it("DELETEs the photo", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await deleteProductPhoto("http://api", "1", "p1", "ph1");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/products/p1/photos/ph1", {
      method: "DELETE",
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    await expect(deleteProductPhoto("http://api", "1", "p1", "ph1")).rejects.toThrow();
  });
});

describe("productPhotoUrl", () => {
  it("builds the photo URL", () => {
    expect(productPhotoUrl("http://api/", "1", "p1", "ph1")).toBe(
      "http://api/bots/1/products/p1/photos/ph1",
    );
  });
});
```

Заменить строку импорта в начале файла (заменить весь именованный импорт
из `@/lib/api`):

```ts
import {
  addProductPhotos,
  createProduct,
  deleteProduct,
  deleteProductPhoto,
  fetchBot,
  fetchBots,
  fetchProduct,
  fetchProducts,
  fetchPromptVersions,
  logoutBot,
  patchBotPrompt,
  productPhotoUrl,
  qrImageUrl,
  updateProduct,
} from "@/lib/api";
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- lib/api.test.ts` (из `services/admin-web/`)
Expected: FAIL — `"@/lib/api" does not provide an export named 'addProductPhotos'`

- [ ] **Step 3: Реализовать**

`services/admin-web/lib/api.ts` — заменить блок `Product`/`ProductInput`:

```ts
// Decimal (Pydantic v2) сериализуется бэкендом как JSON-строка ("5000.00"),
// не число — см. services/api/src/api/schemas/products.py.
export interface ProductPhoto {
  id: string;
  position: number;
}

export interface Product {
  id: string;
  name: string;
  price: string | null;
  sku: string | null;
  description: string | null;
  display_custom: Record<string, boolean>;
  photos: ProductPhoto[];
  created_at: string;
}

export interface ProductInput {
  name: string;
  price?: number | null;
  sku?: string | null;
  description?: string | null;
  display_custom?: Record<string, boolean>;
}
```

Заменить функцию `createProduct` (сигнатура меняется — добавляется
обязательный параметр `photos`):

```ts
/** Собирает multipart/form-data — поле опускается целиком, если его
 * значение null/undefined/пусто (не отправляем пустую строку вместо
 * отсутствующего поля: на бэкенде Form(None)-параметр для Decimal не
 * умеет коэрсить "" в None, только реальное отсутствие ключа). */
function buildProductFormData(input: ProductInput, photos: File[]): FormData {
  const form = new FormData();
  form.set("name", input.name);
  if (input.price !== null && input.price !== undefined) {
    form.set("price", String(input.price));
  }
  if (input.sku !== null && input.sku !== undefined) {
    form.set("sku", input.sku);
  }
  if (input.description !== null && input.description !== undefined) {
    form.set("description", input.description);
  }
  if (input.display_custom !== undefined) {
    form.set("display_custom", JSON.stringify(input.display_custom));
  }
  for (const photo of photos) {
    form.append("photos", photo);
  }
  return form;
}

export async function createProduct(
  baseUrl: string,
  botId: string,
  input: ProductInput,
  photos: File[],
): Promise<Product> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products`, {
    method: "POST",
    body: buildProductFormData(input, photos),
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/products failed: ${res.status}`);
  }
  return (await res.json()) as Product;
}
```

(`updateProduct` не меняется — `PATCH` остаётся JSON-only, фото не
затрагивает; `deleteProduct` тоже не меняется)

В конец файла добавить:

```ts
export async function addProductPhotos(
  baseUrl: string,
  botId: string,
  productId: string,
  photos: File[],
): Promise<ProductPhoto[]> {
  const base = normalizeBaseUrl(baseUrl);
  const form = new FormData();
  for (const photo of photos) {
    form.append("photos", photo);
  }
  const res = await fetch(`${base}/bots/${botId}/products/${productId}/photos`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(`POST /bots/${botId}/products/${productId}/photos failed: ${res.status}`);
  }
  return (await res.json()) as ProductPhoto[];
}

export async function deleteProductPhoto(
  baseUrl: string,
  botId: string,
  productId: string,
  photoId: string,
): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${botId}/products/${productId}/photos/${photoId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(
      `DELETE /bots/${botId}/products/${productId}/photos/${photoId} failed: ${res.status}`,
    );
  }
}

export function productPhotoUrl(
  baseUrl: string,
  botId: string,
  productId: string,
  photoId: string,
): string {
  const base = normalizeBaseUrl(baseUrl);
  return `${base}/bots/${botId}/products/${productId}/photos/${photoId}`;
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- lib/api.test.ts`
Expected: PASS

Run: `npx tsc --noEmit`
Expected: без ошибок — поймает несовпадение сигнатуры `createProduct` в
местах, которые Task 7 ещё не обновил (`ProductForm.tsx` — обнови в Task 7,
здесь просто ожидаем, что `tsc` отругает именно его, а не `api.ts`/`api.test.ts`)

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/lib/api.ts services/admin-web/lib/api.test.ts
git commit -m "feat(admin-web): multipart createProduct, addProductPhotos, deleteProductPhoto

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: `ProductForm` — обязательное фото при создании, управление фото при редактировании

**Files:**
- Modify: `services/admin-web/components/ProductForm.tsx`
- Modify: `services/admin-web/components/ProductForm.test.tsx`

**Interfaces:**
- Consumes: `createProduct` (новая сигнатура с `photos: File[]`),
  `addProductPhotos`, `deleteProductPhoto`, `productPhotoUrl`, `ProductPhoto`
  (Task 6).
- Produces: `ProductForm` — то же API компонента (`{botId, apiBaseUrl, product?}`),
  внутреннее поведение меняется.

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/ProductForm.test.tsx` — заменить блок
`vi.mock("@/lib/api", ...)`:

```tsx
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createProduct: vi.fn(),
    updateProduct: vi.fn(),
    addProductPhotos: vi.fn(),
    deleteProductPhoto: vi.fn(),
  };
});
```

Заменить фикстуру `existingProduct` (добавить `photos`):

```tsx
const existingProduct: Product = {
  id: "p1",
  name: "Старое имя",
  price: "100.00",
  sku: "SKU-1",
  description: "Старое описание",
  display_custom: {},
  photos: [{ id: "ph1", position: 0 }],
  created_at: "2026-09-10T10:00:00Z",
};

function makeFile(name = "photo.jpg"): File {
  return new File(["fake bytes"], name, { type: "image/jpeg" });
}
```

Заменить тест `"creates a product with trimmed optional fields"` и
`"sends display_custom only when the override checkbox is on"` (оба сейчас
вызывают `createProduct` со старой сигнатурой без фото — фото теперь
обязательно, без него форма не даёт отправить):

```tsx
it("rejects submit in create mode without a photo", async () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/фото/i);
  expect(api.createProduct).not.toHaveBeenCalled();
});

it("creates a product with trimmed optional fields and the selected photo", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);
  const photo = makeFile();

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Новый товар" } });
  fireEvent.change(screen.getByLabelText(/фото/i), { target: { files: [photo] } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith(
      "http://api",
      "1",
      { name: "Новый товар", price: null, sku: null, description: null, display_custom: {} },
      [photo],
    );
  });
  expect(pushMock).toHaveBeenCalledWith("/bots/1/products");
});

it("sends display_custom only when the override checkbox is on", async () => {
  vi.mocked(api.createProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" />);

  fireEvent.change(screen.getByLabelText(/название/i), { target: { value: "Товар" } });
  fireEvent.change(screen.getByLabelText(/фото/i), { target: { files: [makeFile()] } });
  fireEvent.click(screen.getByLabelText(/переопределить вывод/i));
  fireEvent.click(screen.getByLabelText(/показывать цену/i));
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.createProduct).toHaveBeenCalledWith(
      "http://api",
      "1",
      expect.objectContaining({
        display_custom: { show_name: true, show_description: true, show_price: false },
      }),
      expect.any(Array),
    );
  });
});
```

Заменить тест `"updates an existing product"` (в режиме редактирования
`updateProduct` не меняется — сигнатура та же, но теперь проверяем и
секцию «Фото» рядом):

```tsx
it("updates an existing product's text fields (photos untouched by this save)", async () => {
  vi.mocked(api.updateProduct).mockResolvedValue(existingProduct);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);

  fireEvent.change(screen.getByLabelText(/цена/i), { target: { value: "200" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.updateProduct).toHaveBeenCalledWith("http://api", "1", "p1", {
      name: "Старое имя",
      price: 200,
      sku: "SKU-1",
      description: "Старое описание",
      display_custom: {},
    });
  });
});

it("does not render a photo input in edit mode (photos have their own section)", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.queryByLabelText(/^фото$/i)).not.toBeInTheDocument();
});

it("renders existing photos with a delete button in edit mode", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByRole("img", { name: /фото товара/i })).toHaveAttribute(
    "src",
    "http://api/bots/1/products/p1/photos/ph1",
  );
  expect(screen.getByRole("button", { name: /удалить фото/i })).toBeInTheDocument();
});

it("disables the delete button when it is the only photo", () => {
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  expect(screen.getByRole("button", { name: /удалить фото/i })).toBeDisabled();
});

it("enables delete and removes the photo from view when there is more than one", async () => {
  const twoPhotos: Product = {
    ...existingProduct,
    photos: [
      { id: "ph1", position: 0 },
      { id: "ph2", position: 1 },
    ],
  };
  vi.mocked(api.deleteProductPhoto).mockResolvedValue(undefined);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={twoPhotos} />);

  const deleteButtons = screen.getAllByRole("button", { name: /удалить фото/i });
  expect(deleteButtons[0]).not.toBeDisabled();
  fireEvent.click(deleteButtons[0]);

  await waitFor(() => {
    expect(api.deleteProductPhoto).toHaveBeenCalledWith("http://api", "1", "p1", "ph1");
  });
  await waitFor(() => {
    expect(screen.getAllByRole("img", { name: /фото товара/i })).toHaveLength(1);
  });
});

it("adds a photo via the file input in edit mode", async () => {
  const added = [{ id: "ph2", position: 1 }];
  vi.mocked(api.addProductPhotos).mockResolvedValue(added);
  render(<ProductForm botId="1" apiBaseUrl="http://api" product={existingProduct} />);
  const photo = makeFile("new.jpg");

  fireEvent.change(screen.getByLabelText(/добавить ещё/i), { target: { files: [photo] } });

  await waitFor(() => {
    expect(api.addProductPhotos).toHaveBeenCalledWith("http://api", "1", "p1", [photo]);
  });
  await waitFor(() => {
    expect(screen.getAllByRole("img", { name: /фото товара/i })).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/ProductForm.test.tsx`
Expected: FAIL — новые тесты ищут элементы/поведение, которых пока нет
(`/фото/i` label, `role="img"` миниатюры и т.д.)

- [ ] **Step 3: Реализовать**

`services/admin-web/components/ProductForm.tsx` — полностью:

```tsx
"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  addProductPhotos,
  createProduct,
  deleteProductPhoto,
  productPhotoUrl,
  updateProduct,
  type Product,
  type ProductInput,
  type ProductPhoto,
} from "@/lib/api";

interface ProductFormProps {
  botId: string;
  apiBaseUrl: string;
  /** Если задан — режим редактирования, иначе — создание нового товара. */
  product?: Product;
}

interface FormState {
  name: string;
  price: string;
  sku: string;
  description: string;
  displayOverride: boolean;
  showName: boolean;
  showDescription: boolean;
  showPrice: boolean;
}

function initialState(product: Product | undefined): FormState {
  const hasOverride = !!product && Object.keys(product.display_custom).length > 0;
  return {
    name: product?.name ?? "",
    price: product?.price ?? "",
    sku: product?.sku ?? "",
    description: product?.description ?? "",
    displayOverride: hasOverride,
    showName: product?.display_custom.show_name ?? true,
    showDescription: product?.display_custom.show_description ?? true,
    showPrice: product?.display_custom.show_price ?? true,
  };
}

function toInput(state: FormState): ProductInput {
  return {
    name: state.name.trim(),
    price: state.price.trim() === "" ? null : Number(state.price),
    sku: state.sku.trim() === "" ? null : state.sku.trim(),
    description: state.description.trim() === "" ? null : state.description.trim(),
    display_custom: state.displayOverride
      ? {
          show_name: state.showName,
          show_description: state.showDescription,
          show_price: state.showPrice,
        }
      : {},
  };
}

export function ProductForm({ botId, apiBaseUrl, product }: ProductFormProps) {
  const router = useRouter();
  const [state, setState] = useState<FormState>(() => initialState(product));
  const [newPhotos, setNewPhotos] = useState<File[]>([]);
  const [photos, setPhotos] = useState<ProductPhoto[]>(product?.photos ?? []);
  const [saving, setSaving] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // PATCH на бэкенде мержит поля: null/пропуск значит «не трогать», а не
  // «очистить» (см. аналогичное поведение bots.image_prompt/pdf_prompt).
  // Значит стереть цену/артикул/описание обратно в пустоту через эту форму
  // нельзя — предупреждаем об этом в режиме редактирования там, где у товара
  // уже есть значение поля. Берём исходное значение из product, а не из
  // текущего state — подсказка не должна пропадать в момент, когда админ
  // как раз стирает поле (самый нужный момент её увидеть).
  const clearHint = "Поле нельзя очистить обратно — здесь можно только заменить значение на другое.";
  const showPriceHint = !!product && !!product.price && product.price.trim() !== "";
  const showSkuHint = !!product && !!product.sku && product.sku.trim() !== "";
  const showDescriptionHint = !!product && !!product.description && product.description.trim() !== "";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (state.name.trim() === "") {
      setError("Название обязательно");
      return;
    }
    if (!product && newPhotos.length === 0) {
      setError("Нужно хотя бы одно фото");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const input = toInput(state);
      if (product) {
        await updateProduct(apiBaseUrl, botId, product.id, input);
      } else {
        await createProduct(apiBaseUrl, botId, input, newPhotos);
      }
      router.push(`/bots/${botId}/products`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  const handleAddPhotos = async (files: FileList | null) => {
    if (!product || !files || files.length === 0) {
      return;
    }
    setError(null);
    setPhotoBusy(true);
    try {
      const added = await addProductPhotos(apiBaseUrl, botId, product.id, Array.from(files));
      setPhotos((current) => [...current, ...added]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось добавить фото");
    } finally {
      setPhotoBusy(false);
    }
  };

  const handleDeletePhoto = async (photoId: string) => {
    if (!product) {
      return;
    }
    setError(null);
    setPhotoBusy(true);
    try {
      await deleteProductPhoto(apiBaseUrl, botId, product.id, photoId);
      setPhotos((current) => current.filter((p) => p.id !== photoId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось удалить фото");
    } finally {
      setPhotoBusy(false);
    }
  };

  return (
    // noValidate — та же причина, что и в BotSettingsForm: нативная
    // HTML5-валидация (required/min) тихо блокирует submit ДО нашей проверки.
    <form noValidate onSubmit={(e) => void handleSubmit(e)}>
      <label>
        Название
        <input
          type="text"
          value={state.name}
          onChange={(e) => setState({ ...state, name: e.target.value })}
        />
      </label>
      <label>
        Цена
        <input
          type="number"
          min={0}
          step={0.01}
          value={state.price}
          onChange={(e) => setState({ ...state, price: e.target.value })}
        />
      </label>
      {showPriceHint && (
        <p style={{ color: "gray", fontSize: "0.85em" }}>{clearHint}</p>
      )}
      <label>
        Артикул (SKU)
        <input
          type="text"
          value={state.sku}
          onChange={(e) => setState({ ...state, sku: e.target.value })}
        />
      </label>
      {showSkuHint && (
        <p style={{ color: "gray", fontSize: "0.85em" }}>{clearHint}</p>
      )}
      <label>
        Описание
        <textarea
          rows={4}
          value={state.description}
          onChange={(e) => setState({ ...state, description: e.target.value })}
        />
      </label>
      {showDescriptionHint && (
        <p style={{ color: "gray", fontSize: "0.85em" }}>{clearHint}</p>
      )}
      <label>
        <input
          type="checkbox"
          checked={state.displayOverride}
          onChange={(e) => setState({ ...state, displayOverride: e.target.checked })}
        />
        Переопределить вывод для этого товара
      </label>
      {state.displayOverride && (
        <fieldset>
          <label>
            <input
              type="checkbox"
              checked={state.showName}
              onChange={(e) => setState({ ...state, showName: e.target.checked })}
            />
            Показывать название
          </label>
          <label>
            <input
              type="checkbox"
              checked={state.showDescription}
              onChange={(e) => setState({ ...state, showDescription: e.target.checked })}
            />
            Показывать описание
          </label>
          <label>
            <input
              type="checkbox"
              checked={state.showPrice}
              onChange={(e) => setState({ ...state, showPrice: e.target.checked })}
            />
            Показывать цену
          </label>
        </fieldset>
      )}

      {!product && (
        <label>
          Фото
          <input
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp"
            onChange={(e) => setNewPhotos(e.target.files ? Array.from(e.target.files) : [])}
          />
        </label>
      )}

      <button type="submit" disabled={saving}>
        {saving ? "Сохраняем…" : "Сохранить"}
      </button>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}

      {product && (
        <section>
          <h2>Фото</h2>
          <div>
            {photos.map((photo) => (
              <div key={photo.id} style={{ display: "inline-block", marginRight: "1rem" }}>
                <img
                  src={productPhotoUrl(apiBaseUrl, botId, product.id, photo.id)}
                  alt="Фото товара"
                  style={{ width: "96px", height: "96px", objectFit: "cover" }}
                />
                <div>
                  <button
                    type="button"
                    disabled={photoBusy || photos.length <= 1}
                    onClick={() => void handleDeletePhoto(photo.id)}
                  >
                    Удалить фото
                  </button>
                </div>
              </div>
            ))}
          </div>
          <label>
            Добавить ещё
            <input
              type="file"
              multiple
              accept="image/jpeg,image/png,image/webp"
              disabled={photoBusy}
              onChange={(e) => void handleAddPhotos(e.target.files)}
            />
          </label>
        </section>
      )}
    </form>
  );
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/ProductForm.test.tsx`
Expected: PASS

Run: `npx tsc --noEmit`
Expected: без ошибок

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/ProductForm.tsx services/admin-web/components/ProductForm.test.tsx
git commit -m "feat(admin-web): required photo on product create, photo management in edit

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: `ProductsTable` — миниатюра первого фото

**Files:**
- Modify: `services/admin-web/components/ProductsTable.tsx`
- Modify: `services/admin-web/components/ProductsTable.test.tsx`

**Interfaces:**
- Consumes: `productPhotoUrl`, `Product.photos` (Task 6).

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/ProductsTable.test.tsx` — заменить фикстуру
`products` (добавить `photos`):

```tsx
const products: Product[] = [
  {
    id: "p1",
    name: "Кроссовки",
    price: "5000.00",
    sku: "NK-001",
    description: null,
    display_custom: {},
    photos: [{ id: "ph1", position: 0 }],
    created_at: "2026-09-10T10:00:00Z",
  },
  {
    id: "p2",
    name: "Без цены",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    photos: [],
    created_at: "2026-09-10T10:00:00Z",
  },
];
```

В конец файла добавить:

```tsx
it("renders a thumbnail for the first photo and nothing for a product without photos", () => {
  render(<ProductsTable botId="1" apiBaseUrl="http://api" products={products} pageSize={10} />);

  const thumbnail = screen.getByRole("img", { name: /кроссовки/i });
  expect(thumbnail).toHaveAttribute("src", "http://api/bots/1/products/p1/photos/ph1");
  expect(screen.queryByRole("img", { name: /без цены/i })).not.toBeInTheDocument();
});
```

В том же файле — тест «shows "Показать ещё", loads and appends the next
page...» содержит объект `nextProduct` без поля `photos` (`tsc` его
теперь отвергнет, `Product` требует это поле). Заменить:

```tsx
  const nextProduct: Product = {
    id: "p3",
    name: "Третий товар",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    created_at: "2026-09-10T10:00:00Z",
  };
```

на:

```tsx
  const nextProduct: Product = {
    id: "p3",
    name: "Третий товар",
    price: null,
    sku: null,
    description: null,
    display_custom: {},
    photos: [],
    created_at: "2026-09-10T10:00:00Z",
  };
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/ProductsTable.test.tsx`
Expected: FAIL — `TypeError` (нет поля `photos` в типе до правки фикстуры)
или новый тест не находит `role="img"`

- [ ] **Step 3: Реализовать**

`services/admin-web/components/ProductsTable.tsx` — заменить импорт:

```tsx
import { deleteProduct, fetchProducts, productPhotoUrl, type Product } from "@/lib/api";
```

Заменить `<thead>`/строку таблицы (добавить колонку миниатюры первой):

```tsx
      <table>
        <thead>
          <tr>
            <th />
            <th>Название</th>
            <th>Цена</th>
            <th>SKU</th>
            <th />
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((product) => (
            <tr key={product.id}>
              <td>
                {product.photos[0] && (
                  <img
                    src={productPhotoUrl(apiBaseUrl, botId, product.id, product.photos[0].id)}
                    alt={product.name}
                    style={{ width: "48px", height: "48px", objectFit: "cover" }}
                  />
                )}
              </td>
              <td>{product.name}</td>
              <td>{product.price ?? "—"}</td>
              <td>{product.sku ?? "—"}</td>
              <td>
                <Link href={`/bots/${botId}/products/${product.id}/edit`}>Редактировать</Link>
              </td>
              <td>
                <button onClick={() => void handleDelete(product.id)}>Удалить</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/ProductsTable.test.tsx`
Expected: PASS

Run: `npm test` (из `services/admin-web/`)
Expected: PASS — весь набор (регрессия остальных компонентов/`lib/api.test.ts`)

Run: `npx tsc --noEmit`
Expected: без ошибок

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/ProductsTable.tsx services/admin-web/components/ProductsTable.test.tsx
git commit -m "feat(admin-web): show first-photo thumbnail in products list

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Живая проверка (docker compose)

**Files:** нет изменений кода — сквозная проверка собранного стека.

- [ ] **Step 1: Поднять стек**

```bash
make dev
```

Дождаться, пока все сервисы станут healthy — включая `api` (первая
проверка, что новые зависимости `Pillow`/`python-multipart` в его образе
действительно ставятся, и что `media-data`-volume у него смонтирован).

- [ ] **Step 2: Проверить обязательность фото**

Открыть `http://localhost:3000/bots` → бот → «Товары →» → «Добавить
товар». Заполнить название, НЕ выбирать фото, нажать «Сохранить» — форма
должна показать ошибку и не уйти со страницы. Выбрать 2 фото (jpeg/png),
сохранить — должен появиться в списке с миниатюрой первого фото.

- [ ] **Step 3: Проверить, что фото реально ресайзится**

```bash
docker compose -f compose/docker-compose.dev.yml exec api sh -c "find /data/media/bots -type f -exec ls -la {} \;"
```

Загруженный ранее файл (если оригинал был больше 1280px) должен быть
заметно меньше исходного по размеру.

- [ ] **Step 4: Проверить управление фото существующего товара**

Открыть товар на редактирование — обе миниатюры видны, у каждой активна
кнопка «Удалить фото». Добавить третье фото через «Добавить ещё» — три
миниатюры. Удалить одно — две миниатюры, кнопки всё ещё активны. Удалить
ещё одно — одна миниатюра, кнопка «Удалить фото» задизейблена.

- [ ] **Step 5: Проверить 422 на удаление последнего фото напрямую**

```bash
# Подставить реальные bot_id/product_id/photo_id из шага 4
curl -i -X DELETE http://localhost:8000/bots/{bot_id}/products/{product_id}/photos/{photo_id}
```

Ожидается `422`, товар остаётся с одним фото.

- [ ] **Step 6: Остановить стек**

```bash
make dev-down
```

Если что-то из Шагов 2-5 не совпало с ожиданием — не коммитить как готово,
вернуться к соответствующей задаче.
