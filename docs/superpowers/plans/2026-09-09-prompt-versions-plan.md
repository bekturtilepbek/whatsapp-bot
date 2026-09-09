# Промпты с версиями (Волна 3, второй под-проект) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кабинет умеет редактировать три промпта бота (основной/image/pdf),
видеть историю их изменений и откатывать на любую прошлую версию — без
риска для того, что читает worker для LLM-контекста.

**Architecture:** Новая таблица `prompt_versions` — чистая история, НЕ
источник истины (им остаются `bots.system_prompt`/`image_prompt`/
`pdf_prompt`, как и сейчас). Запись версии происходит внутри уже
существующего `update_bot` (никакого нового write-эндпоинта) — при PATCH,
меняющем промпт, сравнивается новое значение с последней версией этого
`kind`; совпадает — не пишет, отличается — добавляет строку. Единственный
новый эндпоинт — чтение истории. Откат в admin-web = обычный PATCH со
старым текстом версии, тот же код-путь, что и обычное редактирование.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 async (api, libs/db,
Alembic-миграция) · Next.js 15 / TypeScript / React 19 (admin-web) · vitest +
React Testing Library (admin-web тесты) · pytest + testcontainers (api тесты).

**Spec:** [docs/superpowers/specs/2026-09-09-prompt-versions-design.md](../specs/2026-09-09-prompt-versions-design.md)

## Global Constraints

- Без auth/ролей в этой итерации; `author` в `prompt_versions` — статичная строка `"admin"`.
- Без отдельного `POST .../rollback` — откат в admin-web делается обычным `PATCH /bots/{id}` со старым текстом (явное решение пользователя).
- `prompt_versions` — только история; `bots.system_prompt`/`image_prompt`/`pdf_prompt` остаются единственным источником для worker. Ничего в worker не меняется.
- Версия пишется только при РЕАЛЬНОМ изменении текста (сравнение с последней версией) — не на каждый PATCH.
- Откат не стирает историю (append-only, как `git revert`, не `git reset`).
- `kind` — обычная строка `"main"|"image"|"pdf"` (как `Message.role`), не Postgres ENUM.
- Без Tailwind, обычный CSS (ADR-009), тот же стиль, что и на QR-экране.
- Технический долг Волны 3 (QR-экран): dev-сервер Next.js в проде, отсутствие `.dockerignore` у admin-web, гонка `refresh()`/ошибка в `QrPanel` — не трогаем.
- Известная особенность `PATCH /bots/{id}`: `image_prompt`/`pdf_prompt` нельзя явно очистить в NULL через API (не в скоупе, не чиним).
- **Урок QR-экрана, применить сразу**: `"use client"`-компоненты рендерятся Next.js и на сервере (SSR), и при гидрации на клиенте — любое значение, которое отличается между этими двумя проходами (`Date.now()`, `new Date().toLocaleString()` без явной таймзоны и т.п.), даёт неустранимый hydration-mismatch. Форматировать `created_at` как чистую строковую операцию над ISO-текстом (`slice`), не через `Date`-объект.

---

### Task 1: Backend — таблица `prompt_versions`, версионирование в `update_bot`, `GET .../versions`

**Files:**
- Create: `libs/db/migrations/versions/202609090001_prompt_versions.py`
- Modify: `libs/db/src/db/models.py:106-109` (новый класс `PromptVersion`)
- Create: `libs/db/src/db/prompt_versions.py`
- Modify: `libs/db/src/db/bots.py` (`update_bot` вызывает `record_version_if_changed`)
- Create: `services/api/src/api/schemas/prompt_versions.py`
- Modify: `services/api/src/api/routers/bots.py` (импорты + новый роут)
- Test: `services/api/tests/test_prompt_versions.py`

**Interfaces:**
- Consumes: существующие `Bot`, `update_bot`, `get_bot_with_session` (`libs/db/src/db/bots.py`), существующая `SessionDep` (`services/api/src/api/db.py`), существующий `router` (`services/api/src/api/routers/bots.py`).
- Produces: `db.prompt_versions.PromptKind = Literal["main", "image", "pdf"]`; `db.prompt_versions.list_versions(session, bot_id, kind) -> Sequence[PromptVersion]`; `db.prompt_versions.record_version_if_changed(session, bot_id, kind, body, author="admin") -> None`; роут `GET /bots/{bot_id}/prompts/{kind}/versions -> list[PromptVersionOut]`.

- [ ] **Step 1: Написать падающий тест**

Создать `services/api/tests/test_prompt_versions.py`:

```python
"""GET /bots/{id}/prompts/{kind}/versions + версионирование через PATCH
(FEATURES.md 3.7/3.8): новая версия при реальном изменении, без дублей на
no-op, откат = обычный PATCH со старым текстом поверх истории.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from db.engine import make_engine, make_session_factory
from db.models import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker недоступен в этом окружении"
)


@pytest.fixture(scope="module")
def database_url() -> AsyncIterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="psycopg2") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        yield url


@pytest.fixture
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="prompt-test-bot",
            enabled=True,
            system_prompt="исходный промпт",
            timezone="Asia/Bishkek",
            settings={},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_patch_changing_prompt_creates_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    assert versions.status_code == 200
    body = versions.json()
    assert len(body) == 1
    assert body[0]["body"] == "новый промпт"
    assert body[0]["author"] == "admin"


async def test_patch_with_same_text_does_not_duplicate_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    assert len(versions.json()) == 1


async def test_versions_returned_newest_first(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 1"})
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 2"})

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    body = versions.json()
    assert len(body) == 2
    assert body[0]["body"] == "версия 2"
    assert body[1]["body"] == "версия 1"


async def test_rollback_via_patch_appends_new_version_without_losing_history(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 1"})
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 2"})

    # "Откат" — PATCH тем же текстом, что был у версии 1.
    rollback = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 1"})
    assert rollback.status_code == 200
    assert rollback.json()["system_prompt"] == "версия 1"

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    body = versions.json()
    assert len(body) == 3  # история не укоротилась
    assert body[0]["body"] == "версия 1"  # новая запись сверху
    assert body[1]["body"] == "версия 2"
    assert body[2]["body"] == "версия 1"


async def test_image_and_pdf_prompts_version_independently(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"image_prompt": "опиши фото"})
    await client.patch(f"/bots/{bot_id}", json={"pdf_prompt": "изучи документ"})

    main_versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    image_versions = await client.get(f"/bots/{bot_id}/prompts/image/versions")
    pdf_versions = await client.get(f"/bots/{bot_id}/prompts/pdf/versions")

    assert main_versions.json() == []
    assert len(image_versions.json()) == 1
    assert image_versions.json()[0]["body"] == "опиши фото"
    assert len(pdf_versions.json()) == 1
    assert pdf_versions.json()[0]["body"] == "изучи документ"


async def test_unknown_kind_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/prompts/nonsense/versions")
    assert response.status_code == 422
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest services/api/tests/test_prompt_versions.py -v`
Expected: FAIL — `test_patch_changing_prompt_creates_version` и остальные падают
404/`OperationalError` (таблицы `prompt_versions` и роута ещё нет). Если Docker
недоступен — все тесты `SKIPPED`, это ожидаемо в этом окружении.

- [ ] **Step 3: Реализовать**

`libs/db/migrations/versions/202609090001_prompt_versions.py`:

```python
"""prompt_versions

Revision ID: 202609090001
Revises: 202609080001
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609090001"
down_revision: str | None = "202609080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bot_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("author", sa.String(), nullable=False, server_default=sa.text("'admin'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_prompt_versions_bot_kind_created",
        "prompt_versions",
        ["bot_id", "kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_versions_bot_kind_created", table_name="prompt_versions")
    op.drop_table("prompt_versions")
```

`libs/db/src/db/models.py:106-109` — вставить новый класс между `BotSession`
и `Contact` (после строки `    bot: Mapped[Bot] = relationship(back_populates="session")`
и закрывающих её двух пустых строк, перед `class Contact(Base):`):

```python
    bot: Mapped[Bot] = relationship(back_populates="session")


class PromptVersion(Base):
    """История промптов бота (FEATURES.md 3.7/3.8) — только для отката/аудита.
    Источник истины для ТЕКУЩЕГО промпта остаётся Bot.system_prompt/
    image_prompt/pdf_prompt (см. db.bots.update_bot) — эта таблица ничего
    не меняет в том, что читает worker для LLM-контекста.
    """

    __tablename__ = "prompt_versions"
    __table_args__ = (
        Index("ix_prompt_versions_bot_kind_created", "bot_id", "kind", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    # "main" | "image" | "pdf" — обычная строка (как Message.role,
    # ToolBinding.tool_name), не Postgres ENUM: миграция на новый kind проще.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str] = mapped_column(String, nullable=False, server_default=text("'admin'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Contact(Base):
```

(`Index` уже импортирован в файле — используется `Message`'ом ниже; ничего
менять в блоке импортов не нужно)

`libs/db/src/db/prompt_versions.py` (новый файл):

```python
"""История промптов бота (FEATURES.md 3.7/3.8) — запись/чтение версий.
Вызывается из db.bots.update_bot при каждом PATCH, меняющем промпт; ничего
не решает про ТЕКУЩИЙ промпт — тот остаётся в Bot.system_prompt/
image_prompt/pdf_prompt, эта таблица только история."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PromptVersion

PromptKind = Literal["main", "image", "pdf"]


async def list_versions(
    session: AsyncSession, bot_id: uuid.UUID, kind: PromptKind
) -> Sequence[PromptVersion]:
    result = await session.execute(
        select(PromptVersion)
        .where(PromptVersion.bot_id == bot_id, PromptVersion.kind == kind)
        .order_by(PromptVersion.created_at.desc())
    )
    return result.scalars().all()


async def record_version_if_changed(
    session: AsyncSession,
    bot_id: uuid.UUID,
    kind: PromptKind,
    body: str,
    author: str = "admin",
) -> None:
    """Пишет новую версию, только если body отличается от последней
    сохранённой — иначе повторный PATCH с тем же текстом (например,
    двойной клик "Сохранить") плодил бы дубли в истории.

    .first() (не .scalar_one_or_none()) — различает "версий ещё не было
    вообще" (None) от "последняя версия существует с body=NULL" (Row с
    row.body is None). Без этого первое сохранение промпта, который когда-то
    был NULL, либо считалось бы "без изменений", либо писалось бы криво.
    """
    result = await session.execute(
        select(PromptVersion.body)
        .where(PromptVersion.bot_id == bot_id, PromptVersion.kind == kind)
        .order_by(PromptVersion.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is not None and row.body == body:
        return
    session.add(PromptVersion(bot_id=bot_id, kind=kind, body=body, author=author))
    await session.flush()
```

`libs/db/src/db/bots.py` — импорт и `update_bot`:

```python
from .prompt_versions import record_version_if_changed
```

(добавить эту строку импорта после `from .models import Bot`)

```python
async def update_bot(
    session: AsyncSession,
    bot_id: uuid.UUID,
    *,
    enabled: bool | None = None,
    system_prompt: str | None = None,
    image_prompt: str | None = None,
    pdf_prompt: str | None = None,
    settings_patch: dict[str, Any] | None = None,
) -> Bot | None:
    """Частичное обновление: None-параметр = не трогать это поле.

    settings мержится через Postgres JSONB `||` (shallow merge на стороне
    БД), а не Python-side read-modify-write — атомарно, без гонки двух
    параллельных PATCH на разные ключи settings. Правило CLAUDE.md:
    "настройки бота мержатся, не перезаписываются".

    Промпты (system_prompt/image_prompt/pdf_prompt), если переданы,
    дополнительно версионируются в prompt_versions (FEATURES.md 3.7/3.8) —
    см. record_version_if_changed. NULL остаётся сигналом "не трогать это
    поле" (как и раньше) — версия для kind пишется только когда вызывающий
    передал непустое значение, то же условие, что решает, попадёт ли поле
    в UPDATE bots.
    """
    values: dict[str, Any] = {}
    if enabled is not None:
        values["enabled"] = enabled
    if system_prompt is not None:
        values["system_prompt"] = system_prompt
    if image_prompt is not None:
        values["image_prompt"] = image_prompt
    if pdf_prompt is not None:
        values["pdf_prompt"] = pdf_prompt
    if settings_patch is not None:
        values["settings"] = Bot.settings.op("||")(cast(settings_patch, JSONB))

    if system_prompt is not None:
        await record_version_if_changed(session, bot_id, "main", system_prompt)
    if image_prompt is not None:
        await record_version_if_changed(session, bot_id, "image", image_prompt)
    if pdf_prompt is not None:
        await record_version_if_changed(session, bot_id, "pdf", pdf_prompt)

    if values:
        await session.execute(update(Bot).where(Bot.id == bot_id).values(**values))
        await session.flush()
        # Bulk UPDATE (Core) не обновляет уже загруженный в identity map
        # объект сам по себе — без expire get_bot_with_session() ниже мог бы
        # вернуть объект с полями до PATCH, если бот уже был загружен в этой сессии.
        session.expire_all()

    return await get_bot_with_session(session, bot_id)
```

`services/api/src/api/schemas/prompt_versions.py` (новый файл):

```python
"""Pydantic v2 схема истории версий промпта для api."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str | None
    author: str
    created_at: datetime
```

`services/api/src/api/routers/bots.py` — импорты и новый роут. Файл сейчас
(строки 15-27) содержит:

```python
from db.bots import get_bot_with_session, list_bots, update_bot
from db.tool_bindings import disable as disable_tool
from db.tool_bindings import enable as enable_tool
from db.tool_bindings import list_enabled as list_enabled_tools
from fastapi import APIRouter, HTTPException, Response
from tools.registry import all_tool_names

from ..db import SessionDep
from ..gateway_client import GatewayClientDep
from ..redis_client import RedisDep
from ..schemas.blocked_contacts import BlockedNumberIn, BlockedNumberOut
from ..schemas.bots import BotOut, BotPatch
from ..schemas.tool_bindings import ToolBindingIn, ToolBindingOut
```

Добавить одну новую строку импорта сразу после `from db.bots import ...`
(строка 15) — сам `from db.bots import ...` не менять:

```python
from db.prompt_versions import PromptKind, list_versions
```

И одну новую строку сразу после `from ..schemas.bots import BotOut, BotPatch`
(строка 26) — остальные строки этого блока (включая `blocked_contacts` выше
и `tool_bindings` ниже) не менять:

```python
from ..schemas.prompt_versions import PromptVersionOut
```

Новый роут — добавить сразу после `patch_bot` (перед `@router.get("/{bot_id}/qr")`):

```python
@router.get("/{bot_id}/prompts/{kind}/versions", response_model=list[PromptVersionOut])
async def list_prompt_versions(
    bot_id: uuid.UUID, kind: PromptKind, session: SessionDep
) -> list[PromptVersionOut]:
    versions = await list_versions(session, bot_id, kind)
    return [PromptVersionOut.model_validate(v) for v in versions]
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `pytest services/api/tests/test_prompt_versions.py services/api/tests/test_bots.py -v`
Expected: PASS (новый файл + регрессия — PATCH-логика в `update_bot` не должна
сломать существующие тесты `test_bots.py`)

- [ ] **Step 5: Коммит**

```bash
git add libs/db/migrations/versions/202609090001_prompt_versions.py libs/db/src/db/models.py libs/db/src/db/prompt_versions.py libs/db/src/db/bots.py services/api/src/api/schemas/prompt_versions.py services/api/src/api/routers/bots.py services/api/tests/test_prompt_versions.py
git commit -m "feat(api): version prompt changes in prompt_versions

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `lib/api.ts` — поля промптов на `Bot`, `patchBotPrompt`, `fetchPromptVersions`

**Files:**
- Modify: `services/admin-web/lib/api.ts`
- Modify: `services/admin-web/components/QrPanel.test.tsx:16-23`
- Modify: `services/admin-web/components/BotsTable.test.tsx:6-15`
- Test: `services/admin-web/lib/api.test.ts`

**Interfaces:**
- Consumes: существующий `normalizeBaseUrl` (внутренний, не экспортируется — переиспользуется, не дублируется), существующий `Bot` (расширяется).
- Produces:
  - `Bot` получает поля `system_prompt: string; image_prompt: string | null; pdf_prompt: string | null` (backend их уже отдаёт — `BotOut` в `services/api/src/api/schemas/bots.py` не меняется).
  - `type PromptKind = "main" | "image" | "pdf"`
  - `interface PromptVersion { id: string; body: string | null; author: string; created_at: string }`
  - `patchBotPrompt(baseUrl: string, id: string, kind: PromptKind, body: string): Promise<Bot>`
  - `fetchPromptVersions(baseUrl: string, id: string, kind: PromptKind): Promise<PromptVersion[]>`

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/lib/api.test.ts` — заменить первую строку импорта и
дописать два новых `describe`-блока в конец файла:

Строку
```ts
import { fetchBot, fetchBots, logoutBot, qrImageUrl } from "@/lib/api";
```
заменить на:
```ts
import { fetchBot, fetchBots, fetchPromptVersions, logoutBot, patchBotPrompt, qrImageUrl } from "@/lib/api";
```

В конец файла добавить:

```ts
describe("patchBotPrompt", () => {
  it("PATCHes the mapped field and returns the updated bot", async () => {
    const bot = {
      id: "1",
      name: "Bot",
      enabled: true,
      phone: null,
      linked_at: null,
      system_prompt: "новый текст",
      image_prompt: null,
      pdf_prompt: null,
    };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => bot });
    vi.stubGlobal("fetch", fetchMock);

    const result = await patchBotPrompt("http://api", "1", "main", "новый текст");

    expect(result).toEqual(bot);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: "новый текст" }),
    });
  });

  it("maps image and pdf kinds to their own field", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    await patchBotPrompt("http://api", "1", "image", "опиши фото");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api/bots/1",
      expect.objectContaining({ body: JSON.stringify({ image_prompt: "опиши фото" }) }),
    );

    await patchBotPrompt("http://api", "1", "pdf", "изучи документ");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api/bots/1",
      expect.objectContaining({ body: JSON.stringify({ pdf_prompt: "изучи документ" }) }),
    );
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400 }));
    await expect(patchBotPrompt("http://api", "1", "main", "x")).rejects.toThrow();
  });
});

describe("fetchPromptVersions", () => {
  it("returns the parsed version list", async () => {
    const versions = [
      { id: "v1", body: "текст", author: "admin", created_at: "2026-09-09T10:00:00Z" },
    ];
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => versions });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchPromptVersions("http://api", "1", "main");

    expect(result).toEqual(versions);
    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/prompts/main/versions", {
      cache: "no-store",
    });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(fetchPromptVersions("http://api", "1", "main")).rejects.toThrow();
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- lib/api.test.ts`
Expected: FAIL — `"@/lib/api" does not provide an export named 'patchBotPrompt'`
(и `fetchPromptVersions`)

- [ ] **Step 3: Реализовать**

`services/admin-web/lib/api.ts` — заменить блок `export interface Bot { ... }`
на:

```ts
export interface Bot {
  id: string;
  name: string;
  enabled: boolean;
  phone: string | null;
  linked_at: string | null;
  system_prompt: string;
  image_prompt: string | null;
  pdf_prompt: string | null;
}
```

В конец файла добавить:

```ts
export type PromptKind = "main" | "image" | "pdf";

export interface PromptVersion {
  id: string;
  body: string | null;
  author: string;
  created_at: string;
}

const PROMPT_FIELD_BY_KIND: Record<PromptKind, "system_prompt" | "image_prompt" | "pdf_prompt"> = {
  main: "system_prompt",
  image: "image_prompt",
  pdf: "pdf_prompt",
};

export async function patchBotPrompt(
  baseUrl: string,
  id: string,
  kind: PromptKind,
  body: string,
): Promise<Bot> {
  const base = normalizeBaseUrl(baseUrl);
  const field = PROMPT_FIELD_BY_KIND[kind];
  const res = await fetch(`${base}/bots/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [field]: body }),
  });
  if (!res.ok) {
    throw new Error(`PATCH /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function fetchPromptVersions(
  baseUrl: string,
  id: string,
  kind: PromptKind,
): Promise<PromptVersion[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await fetch(`${base}/bots/${id}/prompts/${kind}/versions`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots/${id}/prompts/${kind}/versions failed: ${res.status}`);
  }
  return (await res.json()) as PromptVersion[];
}
```

`services/admin-web/components/QrPanel.test.tsx:16-23` — `Bot` теперь требует
3 новых поля; обновить оба фикстур-объекта:

```ts
const unlinkedBot: Bot = {
  id: "1",
  name: "Bot",
  enabled: true,
  phone: null,
  linked_at: null,
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};
const linkedBot: Bot = {
  id: "1",
  name: "Bot",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-09T00:00:00Z",
  system_prompt: "промпт",
  image_prompt: null,
  pdf_prompt: null,
};
```

`services/admin-web/components/BotsTable.test.tsx:6-15` — та же причина,
добавить 3 поля в оба объекта массива `bots`:

```ts
const bots: Bot[] = [
  {
    id: "1",
    name: "Линкованный",
    enabled: true,
    phone: "996700000000",
    linked_at: "2026-09-09T00:00:00Z",
    system_prompt: "промпт",
    image_prompt: null,
    pdf_prompt: null,
  },
  {
    id: "2",
    name: "Не линкованный",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "промпт",
    image_prompt: null,
    pdf_prompt: null,
  },
];
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test`
Expected: PASS — все файлы (`lib/api.test.ts`, `QrPanel.test.tsx`, `BotsTable.test.tsx`)

Run: `npx tsc --noEmit`
Expected: без ошибок — это единственная проверка, которая реально ловит
несовпадение типов в фикстурах `QrPanel.test.tsx`/`BotsTable.test.tsx`
(vitest сам по себе типы не проверяет, только транспилирует)

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/lib/api.ts services/admin-web/lib/api.test.ts services/admin-web/components/QrPanel.test.tsx services/admin-web/components/BotsTable.test.tsx
git commit -m "feat(admin-web): prompt fields on Bot, patchBotPrompt, fetchPromptVersions

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `PromptEditor` — редактирование + история + откат одной кнопкой

**Files:**
- Create: `services/admin-web/components/PromptEditor.tsx`
- Test: `services/admin-web/components/PromptEditor.test.tsx`

**Interfaces:**
- Consumes: `PromptKind`, `PromptVersion`, `patchBotPrompt`, `fetchPromptVersions` из `@/lib/api` (Task 2).
- Produces: `PromptEditor({ botId: string; apiBaseUrl: string; kind: PromptKind; label: string; initialBody: string | null; initialVersions: PromptVersion[] })` — client component.

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/PromptEditor.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PromptEditor } from "@/components/PromptEditor";
import * as api from "@/lib/api";
import type { PromptVersion } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    patchBotPrompt: vi.fn(),
    fetchPromptVersions: vi.fn(),
  };
});

const existingVersion: PromptVersion = {
  id: "v1",
  body: "старый текст",
  author: "admin",
  created_at: "2026-09-08T10:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("renders the current prompt body and existing history", () => {
  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );
  expect(screen.getByRole("textbox")).toHaveValue("текущий текст");
  expect(screen.getByText(/старый текст/)).toBeInTheDocument();
});

it("saves the edited body and refreshes version history", async () => {
  vi.mocked(api.patchBotPrompt).mockResolvedValue({
    id: "1",
    name: "Bot",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "новый текст",
    image_prompt: null,
    pdf_prompt: null,
  });
  const newVersion: PromptVersion = {
    id: "v2",
    body: "новый текст",
    author: "admin",
    created_at: "2026-09-09T10:00:00Z",
  };
  vi.mocked(api.fetchPromptVersions).mockResolvedValue([newVersion, existingVersion]);

  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "новый текст" } });
  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(api.patchBotPrompt).toHaveBeenCalledWith("http://api", "1", "main", "новый текст");
  });
  await waitFor(() => {
    expect(screen.getAllByText(/новый текст/).length).toBeGreaterThan(0);
  });
});

it("rolls back to a past version with one click", async () => {
  vi.mocked(api.patchBotPrompt).mockResolvedValue({
    id: "1",
    name: "Bot",
    enabled: true,
    phone: null,
    linked_at: null,
    system_prompt: "старый текст",
    image_prompt: null,
    pdf_prompt: null,
  });
  vi.mocked(api.fetchPromptVersions).mockResolvedValue([existingVersion]);

  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[existingVersion]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /откатить/i }));

  await waitFor(() => {
    expect(api.patchBotPrompt).toHaveBeenCalledWith("http://api", "1", "main", "старый текст");
  });
});

it("shows an error when saving fails", async () => {
  vi.mocked(api.patchBotPrompt).mockRejectedValue(new Error("save failed"));

  render(
    <PromptEditor
      botId="1"
      apiBaseUrl="http://api"
      kind="main"
      label="Основной промпт"
      initialBody="текущий текст"
      initialVersions={[]}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /сохранить/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(/save failed/i);
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/PromptEditor.test.tsx`
Expected: FAIL — `Cannot find module '@/components/PromptEditor'`

- [ ] **Step 3: Реализовать**

`services/admin-web/components/PromptEditor.tsx`:

```tsx
"use client";

import { useState } from "react";
import { fetchPromptVersions, patchBotPrompt, type PromptKind, type PromptVersion } from "@/lib/api";

interface PromptEditorProps {
  botId: string;
  apiBaseUrl: string;
  kind: PromptKind;
  label: string;
  initialBody: string | null;
  initialVersions: PromptVersion[];
}

export function PromptEditor({
  botId,
  apiBaseUrl,
  kind,
  label,
  initialBody,
  initialVersions,
}: PromptEditorProps) {
  const [body, setBody] = useState(initialBody ?? "");
  const [versions, setVersions] = useState<PromptVersion[]>(initialVersions);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (newBody: string) => {
    setSaving(true);
    setError(null);
    try {
      await patchBotPrompt(apiBaseUrl, botId, kind, newBody);
      setBody(newBody);
      const updated = await fetchPromptVersions(apiBaseUrl, botId, kind);
      setVersions(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сохранить");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <h2>{label}</h2>
      <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} />
      <div>
        <button onClick={() => void save(body)} disabled={saving}>
          {saving ? "Сохраняем…" : "Сохранить"}
        </button>
      </div>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <ul>
        {versions.map((version) => (
          <li key={version.id}>
            {/* Чистая строковая операция над ISO-текстом, не new Date(...) —
             * иначе разное форматирование на SSR и на клиенте даёт
             * hydration-mismatch (урок QR-экрана, components/QrPanel.tsx). */}
            <span>{version.created_at.slice(0, 16).replace("T", " ")}</span>{" "}
            <span>{version.author}</span>{" "}
            <span>{(version.body ?? "").slice(0, 60)}</span>{" "}
            <button onClick={() => void save(version.body ?? "")} disabled={saving}>
              Откатить
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/PromptEditor.test.tsx`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/PromptEditor.tsx services/admin-web/components/PromptEditor.test.tsx
git commit -m "feat(admin-web): PromptEditor with save, history, one-click rollback

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Страница `/bots/[id]/prompts` + ссылки, CSS

**Files:**
- Create: `services/admin-web/app/bots/[id]/prompts/page.tsx`
- Modify: `services/admin-web/app/bots/[id]/page.tsx`
- Modify: `services/admin-web/app/globals.css`

**Interfaces:**
- Consumes: `fetchBot`, `fetchPromptVersions` из `@/lib/api` (Task 2), `PromptEditor` из `@/components/PromptEditor` (Task 3).
- Produces: страница `/bots/[id]/prompts` (Server Component); ссылка на неё с `/bots/[id]`.

- [ ] **Step 1: Реализовать**

`services/admin-web/app/bots/[id]/prompts/page.tsx` (новый файл):

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { PromptEditor } from "@/components/PromptEditor";
import { fetchBot, fetchPromptVersions } from "@/lib/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const API_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default async function BotPromptsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  const [mainVersions, imageVersions, pdfVersions] = await Promise.all([
    fetchPromptVersions(API_INTERNAL_URL, id, "main"),
    fetchPromptVersions(API_INTERNAL_URL, id, "image"),
    fetchPromptVersions(API_INTERNAL_URL, id, "pdf"),
  ]);

  return (
    <main>
      <p>
        <Link href={`/bots/${id}`}>← Назад к боту</Link>
      </p>
      <h1>{bot.name} — промпты</h1>
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PUBLIC_URL}
        kind="main"
        label="Основной промпт"
        initialBody={bot.system_prompt}
        initialVersions={mainVersions}
      />
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PUBLIC_URL}
        kind="image"
        label="Промпт для фото"
        initialBody={bot.image_prompt}
        initialVersions={imageVersions}
      />
      <PromptEditor
        botId={id}
        apiBaseUrl={API_PUBLIC_URL}
        kind="pdf"
        label="Промпт для PDF"
        initialBody={bot.pdf_prompt}
        initialVersions={pdfVersions}
      />
    </main>
  );
}
```

`services/admin-web/app/bots/[id]/page.tsx` — полностью:

```tsx
import Link from "next/link";
import { notFound } from "next/navigation";
import { QrPanel } from "@/components/QrPanel";
import { fetchBot } from "@/lib/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";
const API_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default async function BotPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = await fetchBot(API_INTERNAL_URL, id);
  if (!bot) {
    notFound();
  }

  return (
    <main>
      <h1>{bot.name}</h1>
      <p>
        <Link href={`/bots/${bot.id}/prompts`}>Промпты и история →</Link>
      </p>
      <QrPanel initialBot={bot} apiBaseUrl={API_PUBLIC_URL} />
    </main>
  );
}
```

`services/admin-web/app/globals.css` — добавить в конец файла:

```css
textarea {
  width: 100%;
  font-family: inherit;
  font-size: 1rem;
  padding: 0.5rem;
  box-sizing: border-box;
}

section {
  margin-bottom: 2rem;
}

ul {
  list-style: none;
  padding: 0;
}

li {
  padding: 0.5rem 0;
  border-bottom: 1px solid #ddd;
}
```

- [ ] **Step 2: Запустить и убедиться, что проходит**

Run: `npm run build`
Expected: `Compiled successfully` — среди роутов появляется `/bots/[id]/prompts`

Run: `npm test`
Expected: PASS (все файлы, включая `QrPanel.test.tsx` — страница `/bots/[id]`
поменялась, но не поведение `QrPanel` самого по себе)

- [ ] **Step 3: Коммит**

```bash
git add services/admin-web/app/bots/[id]/prompts/page.tsx services/admin-web/app/bots/[id]/page.tsx services/admin-web/app/globals.css
git commit -m "feat(admin-web): prompts page wired to bot detail

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Живая проверка (docker compose)

**Files:** нет изменений кода — сквозная проверка собранного стека.

- [ ] **Step 1: Поднять стек**

```bash
make dev
```

Дождаться, пока все сервисы станут healthy.

- [ ] **Step 2: Применить миграцию**

Дев-Postgres — отдельный volume от testcontainers, миграция `202609090001`
туда ещё не попадала. С хоста `alembic` к Postgres в Docker Desktop не
подключается (см. память `windows-docker-gotchas`) — гнать через контейнер:

```bash
docker compose -f compose/docker-compose.dev.yml exec worker sh -c "cd /app/libs/db && python -m alembic upgrade head"
```

- [ ] **Step 3: Проверить редактирование и историю**

Открыть `http://localhost:3000/bots` — выбрать любого существующего бота
(например, оставшегося от прошлой итерации), «Открыть» → на странице QR
должна появиться ссылка «Промпты и история →». Перейти по ней.

Изменить текст основного промпта, нажать «Сохранить» — под textarea должна
появиться одна строка истории с текущей датой/временем и текстом.

- [ ] **Step 4: Проверить отсутствие дублей**

Нажать «Сохранить» второй раз без изменения текста — строка истории не
должна задвоиться (список остаётся из одной записи).

- [ ] **Step 5: Проверить откат без потери истории**

Изменить текст ещё раз (вторая реальная правка) и сохранить — в истории
две записи. Нажать «Откатить» на самой старой (первой) версии — textarea
должна показать её текст; в истории должна появиться ТРЕТЬЯ запись
(идентичная по тексту первой), а не удалиться ничего — итого 3 записи в
списке, самая новая сверху.

- [ ] **Step 6: Проверить независимость image/pdf**

Заполнить промпт для фото (`image_prompt` был `NULL`), сохранить — история
именно этого раздела получает первую запись, история основного промпта и
промпта PDF не меняются.

- [ ] **Step 7: Остановить стек**

```bash
make dev-down
```

Если что-то из Шагов 3-6 не совпало с ожиданием — не коммитить как готово,
вернуться к соответствующей задаче.
