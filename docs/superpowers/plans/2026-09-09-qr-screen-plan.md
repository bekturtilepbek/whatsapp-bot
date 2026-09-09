# QR-экран (Волна 3, первый под-проект) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кабинет умеет показывать QR для привязки WhatsApp-номера к боту, статус
подключения и позволяет отключить номер — через новый сервис `services/admin-web`
поверх уже готового транспорта (gateway QR/logout) и расширенного `api`.

**Architecture:** Next.js 15 (App Router) admin-web получает список ботов и статус
конкретного бота через SSR-фетч к FastAPI `api` (внутренний docker-адрес), а живой
5-секундный поллинг статуса и QR-картинки — прямой fetch из браузера в `api` по
публичному адресу (подход A из спеки: гибрид SSR + client-component на поллинг).
`api` расширяется: `GET /bots` (список), `phone`/`linked_at` в ответах бота, CORS
для admin-web-origin. Транспорт (gateway `/qr/:botId`, `/bots/:botId/logout`) не
меняется — уже реализован и покрыт тестами.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 async (api, libs/db) ·
Next.js 15 / TypeScript / React 19 (admin-web) · vitest + React Testing Library
(admin-web тесты) · pytest + testcontainers (api тесты, уже используется в проекте).

**Spec:** [docs/superpowers/specs/2026-09-09-qr-screen-design.md](../specs/2026-09-09-qr-screen-design.md)

## Global Constraints

- Без auth/ролей в этой итерации (6.18 FEATURES.md — отдельный под-проект Волны 3).
- Без онбординга бота из UI (6.20 — отдельно); бот на эту итерацию создаётся прямым SQL-инсертом в `bots`.
- admin-web — Next.js 15 App Router, TypeScript, обычный CSS без Tailwind (ADR-009: минимальный UI сейчас).
- Подход к данным — гибрид A: SSR-фетч для первого рендера (внутренний адрес api) + client-component на 5с-поллинг (прямой fetch из браузера, публичный адрес api).
- CORS на api — без `allow_credentials` (нет auth/cookies, делить нечего).
- Прод: admin-web слушает только `127.0.0.1` (SSH-туннель), как и `api` сейчас — тот же периметр доверия.
- Технический долг Волн 1-2 (ретраи gateway, лимит исходящего медиа, санитизация имён файлов и т.д.) — не трогаем.
- Транспорт (gateway `/qr/:botId`, `/bots/:botId/logout`) уже реализован и протестирован — не меняем.

---

### Task 1: `GET /bots` (список) + `phone`/`linked_at` в ответах api

**Files:**
- Modify: `libs/db/src/db/models.py:71-73` (свойства `phone`/`linked_at` на `Bot`)
- Modify: `libs/db/src/db/bots.py` (eager-load сессии в `get_bot`, новая `list_bots`)
- Modify: `services/api/src/api/schemas/bots.py:12-23` (поля в `BotOut`)
- Modify: `services/api/src/api/routers/bots.py:15-53` (новый роут `GET /bots`)
- Test: `services/api/tests/test_bots.py`

**Interfaces:**
- Produces: `db.bots.list_bots(session: AsyncSession) -> Sequence[Bot]`; `Bot.phone -> str | None`; `Bot.linked_at -> datetime | None`; `BotOut.phone: str | None`; `BotOut.linked_at: datetime | None`; роут `GET /bots -> list[BotOut]`.
- Consumes: существующие `Bot`, `BotSession` модели (`libs/db/src/db/models.py`), существующий `get_bot`/`update_bot` (`libs/db/src/db/bots.py`), существующая `SessionDep` (`services/api/src/api/db.py`).

- [ ] **Step 1: Написать падающий тест**

Добавить в `services/api/tests/test_bots.py` (после существующего блока импортов —
дописать `BotSession`, `UTC`, `datetime` к импортам, остальные тесты файла не трогать):

```python
from datetime import UTC, datetime

from db.models import Bot, BotSession
```

(строка `from db.models import Bot` уже есть в файле — просто добавь `BotSession` в неё,
и отдельной строкой выше — `from datetime import UTC, datetime`)

Новые тесты — в конец файла:

```python
async def test_list_bots_includes_created_bots(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    linked_id = await _make_bot(session_factory, name="linked-bot")
    unlinked_id = await _make_bot(session_factory, name="unlinked-bot")

    async with session_factory() as session:
        session.add(
            BotSession(bot_id=linked_id, phone="996700000000", linked_at=datetime.now(UTC))
        )
        await session.commit()

    response = await client.get("/bots")
    assert response.status_code == 200
    by_id = {b["id"]: b for b in response.json()}

    assert by_id[str(linked_id)]["phone"] == "996700000000"
    assert by_id[str(linked_id)]["linked_at"] is not None
    assert by_id[str(unlinked_id)]["phone"] is None
    assert by_id[str(unlinked_id)]["linked_at"] is None


async def test_get_bot_includes_phone_and_linked_at(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}")
    body = response.json()
    assert body["phone"] is None
    assert body["linked_at"] is None
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest services/api/tests/test_bots.py -v -k "list_bots or includes_phone"`
Expected: FAIL — `test_list_bots_includes_created_bots` падает 404 (роута `GET /bots` ещё нет),
`test_get_bot_includes_phone_and_linked_at` падает `KeyError: 'phone'` (поля ещё нет в ответе).
(Если Docker недоступен — оба теста будут `SKIPPED`, это ожидаемо в этом окружении;
проверка запуска обязательна там, где Docker есть.)

- [ ] **Step 3: Реализовать**

`libs/db/src/db/models.py:71-73` — добавить свойства сразу после `session`-relationship
(перед пустой строкой, отделяющей класс `Bot` от `class BotSession`):

```python
    session: Mapped[BotSession | None] = relationship(
        back_populates="bot", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def phone(self) -> str | None:
        """Номер, если бот когда-либо был привязан — иначе None.
        Требует, чтобы .session был eager-loaded (см. get_bot/list_bots)."""
        return self.session.phone if self.session else None

    @property
    def linked_at(self) -> datetime | None:
        """Момент привязки; None — бот не привязан или был явно отключён
        (clearSession в gateway обнуляет это поле, см. services/gateway/src/db/bots.ts)."""
        return self.session.linked_at if self.session else None
```

`libs/db/src/db/bots.py` — импорты и `get_bot`/`list_bots`:

```python
from collections.abc import Sequence

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Bot


async def get_bot(session: AsyncSession, bot_id: uuid.UUID) -> Bot | None:
    """options=selectinload(Bot.session) — иначе Bot.phone/linked_at (свойства
    выше) упадут на ленивой подгрузке relationship вне текущего await-контекста."""
    return await session.get(Bot, bot_id, options=[selectinload(Bot.session)])


async def list_bots(session: AsyncSession) -> Sequence[Bot]:
    result = await session.execute(
        select(Bot).options(selectinload(Bot.session)).order_by(Bot.created_at)
    )
    return result.scalars().all()
```

(строка `from sqlalchemy import cast, update` меняется на `from sqlalchemy import cast, select, update`;
добавляется `from collections.abc import Sequence` и `from sqlalchemy.orm import selectinload`;
`get_bot` заменяется целиком, `update_bot` не трогается, `list_bots` добавляется после `get_bot`)

`services/api/src/api/schemas/bots.py:12-23` — `BotOut`:

```python
class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    phone: str | None
    linked_at: datetime | None
    system_prompt: str
    image_prompt: str | None
    pdf_prompt: str | None
    timezone: str
    settings: dict[str, Any]
    created_at: datetime
```

`services/api/src/api/routers/bots.py` — импорт и новый роут (добавить `list_bots` в
существующую строку импорта, добавить роут между `router = APIRouter(...)` и `read_bot`):

```python
from db.bots import get_bot, list_bots, update_bot
```

```python
@router.get("", response_model=list[BotOut])
async def list_all_bots(session: SessionDep) -> list[BotOut]:
    bots = await list_bots(session)
    return [BotOut.model_validate(bot) for bot in bots]


@router.get("/{bot_id}", response_model=BotOut)
async def read_bot(bot_id: uuid.UUID, session: SessionDep) -> BotOut:
    ...
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `pytest services/api/tests/test_bots.py -v`
Expected: PASS (все тесты файла, включая ранее существовавшие — регрессий быть не должно)

- [ ] **Step 5: Коммит**

```bash
git add libs/db/src/db/models.py libs/db/src/db/bots.py services/api/src/api/schemas/bots.py services/api/src/api/routers/bots.py services/api/tests/test_bots.py
git commit -m "feat(api): add GET /bots and expose phone/linked_at on bot responses

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: CORS для admin-web-origin на api

**Files:**
- Modify: `services/api/src/api/main.py`
- Test: `services/api/tests/test_cors.py` (новый файл)

**Interfaces:**
- Consumes: `services/api/src/api/main.py`'s существующий `app = FastAPI(...)`.
- Produces: env var `ADMIN_WEB_ORIGIN` (дефолт `http://localhost:3000`), читаемая при старте api.

- [ ] **Step 1: Написать падающий тест**

Создать `services/api/tests/test_cors.py`:

```python
"""CORS для admin-web (Волна 3, QR-экран): браузер стучится в api напрямую с
другого origin (порт admin-web) — без allow-origin браузер зарубит fetch.
Без Docker — CORSMiddleware не трогает БД.
"""

from __future__ import annotations

import httpx
from api.main import app


async def test_configured_admin_web_origin_is_allowed() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_unknown_origin_is_not_allowed() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `pytest services/api/tests/test_cors.py -v`
Expected: FAIL — `test_configured_admin_web_origin_is_allowed` не находит заголовок
(CORS middleware ещё не подключён).

- [ ] **Step 3: Реализовать**

`services/api/src/api/main.py` — полностью:

```python
"""FastAPI: HTTP-ручки управления ботами (STAGE1_CORE Блок 3, п.2).

Слушает 0.0.0.0 внутри контейнера (стандартная докер-практика); публичная
доступность решается маппингом порта в compose — на проде на хост
пробрасывается только 127.0.0.1 (SSH-туннель), в dev — обычный маппинг.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import bots

app = FastAPI(title="platform-api")

# admin-web стучится в api напрямую из браузера (Волна 3, QR-экран, подход A) —
# без allow-origin браузер зарубит fetch кросс-порта. allow_credentials не
# нужен — auth ещё нет (6.18, отдельная итерация), делить нечего.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ADMIN_WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bots.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `pytest services/api/tests/test_cors.py services/api/tests/test_gateway_proxy.py -v`
Expected: PASS (второй файл — регрессия: CORS не должен ломать существующие проксирующие роуты)

- [ ] **Step 5: Коммит**

```bash
git add services/api/src/api/main.py services/api/tests/test_cors.py
git commit -m "feat(api): allow CORS from ADMIN_WEB_ORIGIN

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Скаффолд admin-web (Next.js 15)

**Files:**
- Create: `services/admin-web/package.json`
- Create: `services/admin-web/tsconfig.json`
- Create: `services/admin-web/next.config.mjs`
- Create: `services/admin-web/next-env.d.ts`
- Create: `services/admin-web/.eslintrc.json`
- Create: `services/admin-web/.gitignore`
- Create: `services/admin-web/vitest.config.ts`
- Create: `services/admin-web/vitest.setup.ts`
- Create: `services/admin-web/app/layout.tsx`
- Create: `services/admin-web/app/globals.css`
- Create: `services/admin-web/app/page.tsx`
- Modify: `.gitignore` (корень репозитория — добавить `.next/`)

**Interfaces:**
- Produces: рабочий Next.js проект, `npm run build` проходит; путь-алиас `@/*` → корень `services/admin-web`.
- Consumes: ничего из предыдущих задач (независимый скаффолд).

- [ ] **Step 1: Создать файлы проекта**

`services/admin-web/package.json`:

```json
{
  "name": "@platform/admin-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 3000 -H 0.0.0.0",
    "build": "next build",
    "start": "next start -p 3000 -H 0.0.0.0",
    "lint": "next lint",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "^15.0.3",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.0.1",
    "@types/node": "^22.7.4",
    "@types/react": "^19.0.1",
    "@types/react-dom": "^19.0.2",
    "@vitejs/plugin-react": "^4.3.3",
    "eslint": "^8.57.0",
    "eslint-config-next": "^15.0.3",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.2",
    "vitest": "^2.1.1"
  }
}
```

`services/admin-web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./*"]
    },
    "plugins": [{ "name": "next" }]
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

`services/admin-web/next.config.mjs`:

```js
/** @type {import('next').NextConfig} */
const nextConfig = {};

export default nextConfig;
```

`services/admin-web/next-env.d.ts`:

```ts
/// <reference types="next" />
/// <reference types="next/image-types/global" />

// NOTE: This file should not be edited
// see https://nextjs.org/docs/app/api-reference/config/typescript for more information.
```

`services/admin-web/.eslintrc.json`:

```json
{
  "extends": "next/core-web-vitals"
}
```

`services/admin-web/.gitignore`:

```
node_modules
.next
```

`services/admin-web/vitest.config.ts`:

```ts
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules", ".next"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
```

`services/admin-web/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`services/admin-web/app/layout.tsx`:

```tsx
import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Панель ботов",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
```

`services/admin-web/app/globals.css`:

```css
body {
  font-family: system-ui, sans-serif;
  margin: 2rem;
  color: #1a1a1a;
}

table {
  border-collapse: collapse;
  width: 100%;
}

th,
td {
  text-align: left;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #ddd;
}

button {
  padding: 0.5rem 1rem;
  cursor: pointer;
}
```

`services/admin-web/app/page.tsx`:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/bots");
}
```

Корневой `.gitignore` — в секцию `# Node`, после `dist/`:

```
# Node
node_modules/
dist/
.next/
```

- [ ] **Step 2: Установить зависимости и проверить сборку**

Run (из `services/admin-web`): `npm install`
Expected: завершается без ошибок, создаёт `package-lock.json` и `node_modules/`
(без `package-lock.json` следующая задача с `Dockerfile`/`npm ci` не соберётся)

Run: `npm run build`
Expected: `Compiled successfully`, страница `/` собрана (редиректит на `/bots`,
которого пока нет — это ок, `/bots` появится в Task 6, сборка проверяет только
корректность самого проекта)

- [ ] **Step 3: Коммит**

```bash
git add services/admin-web .gitignore
git commit -m "chore(admin-web): scaffold Next.js 15 project

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `lib/api.ts` — типы и фетч-функции

**Files:**
- Create: `services/admin-web/lib/api.ts`
- Test: `services/admin-web/lib/api.test.ts`

**Interfaces:**
- Consumes: ничего (чистые функции поверх глобального `fetch`).
- Produces:
  - `interface Bot { id: string; name: string; enabled: boolean; phone: string | null; linked_at: string | null }`
  - `fetchBots(baseUrl: string): Promise<Bot[]>`
  - `fetchBot(baseUrl: string, id: string): Promise<Bot | null>` (`null` на 404)
  - `logoutBot(baseUrl: string, id: string): Promise<void>`
  - `qrImageUrl(baseUrl: string, id: string): string` (с cache-busting `?t=`)

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/lib/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchBot, fetchBots, logoutBot, qrImageUrl } from "@/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchBots", () => {
  it("returns the parsed bot list on success", async () => {
    const bots = [
      { id: "1", name: "Bot", enabled: true, phone: null, linked_at: null },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => bots }),
    );

    const result = await fetchBots("http://api");

    expect(result).toEqual(bots);
    expect(fetch).toHaveBeenCalledWith("http://api/bots", { cache: "no-store" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    await expect(fetchBots("http://api")).rejects.toThrow();
  });
});

describe("fetchBot", () => {
  it("returns null on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    const result = await fetchBot("http://api", "1");
    expect(result).toBeNull();
  });

  it("returns the parsed bot on success", async () => {
    const bot = {
      id: "1",
      name: "Bot",
      enabled: true,
      phone: "996700000000",
      linked_at: "2026-09-09T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => bot }));
    const result = await fetchBot("http://api", "1");
    expect(result).toEqual(bot);
  });
});

describe("logoutBot", () => {
  it("posts to the logout endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    await logoutBot("http://api", "1");

    expect(fetchMock).toHaveBeenCalledWith("http://api/bots/1/logout", { method: "POST" });
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502 }));
    await expect(logoutBot("http://api", "1")).rejects.toThrow();
  });
});

describe("qrImageUrl", () => {
  it("includes a cache-busting query param", () => {
    const url = qrImageUrl("http://api", "1");
    expect(url).toMatch(/^http:\/\/api\/bots\/1\/qr\?t=\d+$/);
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- lib/api.test.ts`
Expected: FAIL — `Cannot find module '@/lib/api'`

- [ ] **Step 3: Реализовать**

`services/admin-web/lib/api.ts`:

```ts
// Тонкий фетч-слой admin-web поверх api. Используется и на сервере (SSR
// первого рендера, baseUrl = API_INTERNAL_URL) и в браузере (поллинг в
// QrPanel, baseUrl = NEXT_PUBLIC_API_URL) — см. docs/superpowers/specs/
// 2026-09-09-qr-screen-design.md, подход A.

export interface Bot {
  id: string;
  name: string;
  enabled: boolean;
  phone: string | null;
  linked_at: string | null;
}

export async function fetchBots(baseUrl: string): Promise<Bot[]> {
  const res = await fetch(`${baseUrl}/bots`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots failed: ${res.status}`);
  }
  return (await res.json()) as Bot[];
}

export async function fetchBot(baseUrl: string, id: string): Promise<Bot | null> {
  const res = await fetch(`${baseUrl}/bots/${id}`, { cache: "no-store" });
  if (res.status === 404) {
    return null;
  }
  if (!res.ok) {
    throw new Error(`GET /bots/${id} failed: ${res.status}`);
  }
  return (await res.json()) as Bot;
}

export async function logoutBot(baseUrl: string, id: string): Promise<void> {
  const res = await fetch(`${baseUrl}/bots/${id}/logout`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`POST /bots/${id}/logout failed: ${res.status}`);
  }
}

/** Query-параметр — cache-busting: без него браузер закэширует PNG по URL и
 * не подхватит смену QR при ротации WhatsApp (~раз в 20с). */
export function qrImageUrl(baseUrl: string, id: string): string {
  return `${baseUrl}/bots/${id}/qr?t=${Date.now()}`;
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- lib/api.test.ts`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/lib/api.ts services/admin-web/lib/api.test.ts
git commit -m "feat(admin-web): fetch helpers for bots API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `QrPanel` — поллинг статуса и QR

**Files:**
- Create: `services/admin-web/components/QrPanel.tsx`
- Test: `services/admin-web/components/QrPanel.test.tsx`

**Interfaces:**
- Consumes: `Bot`, `fetchBot`, `logoutBot`, `qrImageUrl` из `@/lib/api` (Task 4).
- Produces: `QrPanel({ initialBot: Bot; apiBaseUrl: string; pollIntervalMs?: number })` —
  client component; `pollIntervalMs` по умолчанию `5000`, тесты передают меньшее
  значение вместо фейковых таймеров.

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/QrPanel.test.tsx`:

```tsx
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QrPanel } from "@/components/QrPanel";
import * as api from "@/lib/api";
import type { Bot } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    fetchBot: vi.fn(),
    logoutBot: vi.fn(),
  };
});

const unlinkedBot: Bot = { id: "1", name: "Bot", enabled: true, phone: null, linked_at: null };
const linkedBot: Bot = {
  id: "1",
  name: "Bot",
  enabled: true,
  phone: "996700000000",
  linked_at: "2026-09-09T00:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

it("shows the QR image while the bot is not linked", () => {
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" pollIntervalMs={10000} />);
  expect(screen.getByRole("img", { name: /qr/i })).toBeInTheDocument();
  expect(screen.queryByText(/отключить/i)).not.toBeInTheDocument();
});

it("switches to the connected view once polling finds linked_at set", async () => {
  vi.mocked(api.fetchBot).mockResolvedValue(linkedBot);
  render(<QrPanel initialBot={unlinkedBot} apiBaseUrl="http://api" pollIntervalMs={20} />);

  await waitFor(() => {
    expect(screen.getByText(/996700000000/)).toBeInTheDocument();
  });
  expect(screen.queryByRole("img", { name: /qr/i })).not.toBeInTheDocument();
});

it("logs out and returns to the QR view", async () => {
  vi.mocked(api.fetchBot).mockResolvedValue(unlinkedBot);
  vi.mocked(api.logoutBot).mockResolvedValue(undefined);
  render(<QrPanel initialBot={linkedBot} apiBaseUrl="http://api" pollIntervalMs={10000} />);

  fireEvent.click(screen.getByRole("button", { name: /отключить/i }));

  await waitFor(() => {
    expect(api.logoutBot).toHaveBeenCalledWith("http://api", "1");
  });
  await waitFor(() => {
    expect(screen.getByRole("img", { name: /qr/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/QrPanel.test.tsx`
Expected: FAIL — `Cannot find module '@/components/QrPanel'`

- [ ] **Step 3: Реализовать**

`services/admin-web/components/QrPanel.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchBot, logoutBot, qrImageUrl, type Bot } from "@/lib/api";

interface QrPanelProps {
  initialBot: Bot;
  apiBaseUrl: string;
  /** 5с по умолчанию (FEATURES.md 6.1) — тесты передают меньшее значение
   * вместо фейковых таймеров. */
  pollIntervalMs?: number;
}

export function QrPanel({ initialBot, apiBaseUrl, pollIntervalMs = 5000 }: QrPanelProps) {
  const [bot, setBot] = useState<Bot>(initialBot);
  const [qrUrl, setQrUrl] = useState<string>(() => qrImageUrl(apiBaseUrl, initialBot.id));
  const [loggingOut, setLoggingOut] = useState(false);

  const refresh = useCallback(async () => {
    const updated = await fetchBot(apiBaseUrl, initialBot.id);
    if (!updated) return;
    setBot(updated);
    if (!updated.linked_at) {
      // Перегенерируем URL — cache-busting подхватывает ротацию QR (~20с).
      setQrUrl(qrImageUrl(apiBaseUrl, initialBot.id));
    }
  }, [apiBaseUrl, initialBot.id]);

  useEffect(() => {
    const timer = setInterval(() => {
      void refresh();
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [refresh, pollIntervalMs]);

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await logoutBot(apiBaseUrl, bot.id);
      await refresh();
    } finally {
      setLoggingOut(false);
    }
  };

  if (bot.linked_at) {
    return (
      <div>
        <p>Подключён: {bot.phone}</p>
        <button onClick={() => void handleLogout()} disabled={loggingOut}>
          {loggingOut ? "Отключаем…" : "Отключить"}
        </button>
      </div>
    );
  }

  return (
    <div>
      <p>Отсканируйте QR в WhatsApp на телефоне</p>
      {/* eslint-disable-next-line @next/next/no-img-element -- PNG отдаёт api напрямую, не статический ассет Next.js */}
      <img src={qrUrl} alt="QR-код для подключения WhatsApp" width={300} height={300} />
    </div>
  );
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/QrPanel.test.tsx`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/QrPanel.tsx services/admin-web/components/QrPanel.test.tsx
git commit -m "feat(admin-web): QrPanel with 5s status/QR polling and logout

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `BotsTable` + список ботов (`/bots`)

**Files:**
- Create: `services/admin-web/components/BotsTable.tsx`
- Test: `services/admin-web/components/BotsTable.test.tsx`
- Create: `services/admin-web/app/bots/page.tsx`

**Interfaces:**
- Consumes: `Bot`, `fetchBots` из `@/lib/api` (Task 4).
- Produces: `BotsTable({ bots: Bot[] })`; страница `/bots` (Server Component).

- [ ] **Step 1: Написать падающий тест**

`services/admin-web/components/BotsTable.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BotsTable } from "@/components/BotsTable";
import type { Bot } from "@/lib/api";

const bots: Bot[] = [
  {
    id: "1",
    name: "Линкованный",
    enabled: true,
    phone: "996700000000",
    linked_at: "2026-09-09T00:00:00Z",
  },
  { id: "2", name: "Не линкованный", enabled: true, phone: null, linked_at: null },
];

it("shows status and phone for each bot", () => {
  render(<BotsTable bots={bots} />);
  expect(screen.getByText("Подключён")).toBeInTheDocument();
  expect(screen.getByText("996700000000")).toBeInTheDocument();
  expect(screen.getByText("Не подключён")).toBeInTheDocument();
  expect(screen.getByText("—")).toBeInTheDocument();
});

it("links to the bot detail page", () => {
  render(<BotsTable bots={bots} />);
  const link = screen.getAllByRole("link", { name: /открыть/i })[0];
  expect(link).toHaveAttribute("href", "/bots/1");
});
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `npm test -- components/BotsTable.test.tsx`
Expected: FAIL — `Cannot find module '@/components/BotsTable'`

- [ ] **Step 3: Реализовать**

`services/admin-web/components/BotsTable.tsx`:

```tsx
import Link from "next/link";
import type { Bot } from "@/lib/api";

interface BotsTableProps {
  bots: Bot[];
}

export function BotsTable({ bots }: BotsTableProps) {
  return (
    <table>
      <thead>
        <tr>
          <th>Имя</th>
          <th>Статус</th>
          <th>Номер</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {bots.map((bot) => (
          <tr key={bot.id}>
            <td>{bot.name}</td>
            <td>{bot.linked_at ? "Подключён" : "Не подключён"}</td>
            <td>{bot.phone ?? "—"}</td>
            <td>
              <Link href={`/bots/${bot.id}`}>Открыть</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`services/admin-web/app/bots/page.tsx`:

```tsx
import { BotsTable } from "@/components/BotsTable";
import { fetchBots } from "@/lib/api";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export default async function BotsPage() {
  const bots = await fetchBots(API_INTERNAL_URL);

  return (
    <main>
      <h1>Боты</h1>
      <BotsTable bots={bots} />
    </main>
  );
}
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `npm test -- components/BotsTable.test.tsx`
Expected: PASS

Run: `npm run build`
Expected: `Compiled successfully` — `/bots` теперь тоже собирается (SSR-фетч к
`API_INTERNAL_URL` во время build не выполняется для App Router динамических
страниц без `force-static`, ошибка сети на этом шаге не ожидается)

- [ ] **Step 5: Коммит**

```bash
git add services/admin-web/components/BotsTable.tsx services/admin-web/components/BotsTable.test.tsx services/admin-web/app/bots/page.tsx
git commit -m "feat(admin-web): bots list page

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Страница бота (`/bots/[id]`)

**Files:**
- Create: `services/admin-web/app/bots/[id]/page.tsx`

**Interfaces:**
- Consumes: `fetchBot` из `@/lib/api` (Task 4), `QrPanel` из `@/components/QrPanel` (Task 5).
- Produces: страница `/bots/[id]` (Server Component), 404 через `notFound()` для несуществующего бота.

- [ ] **Step 1: Реализовать**

`services/admin-web/app/bots/[id]/page.tsx`:

```tsx
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
      <QrPanel initialBot={bot} apiBaseUrl={API_PUBLIC_URL} />
    </main>
  );
}
```

Эта страница — тонкая обвязка над уже протестированными `fetchBot` (Task 4) и
`QrPanel` (Task 5); отдельного unit-теста не заводим (RSC-тестирование не
установлено в стеке проекта), проверяется сборкой и живой проверкой (Task 9).

- [ ] **Step 2: Проверить сборку**

Run: `npm run build`
Expected: `Compiled successfully`, среди роутов — `/bots/[id]`

- [ ] **Step 3: Коммит**

```bash
git add services/admin-web/app/bots/[id]/page.tsx
git commit -m "feat(admin-web): bot detail page wires QrPanel to fetched bot

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Dockerfile, compose (dev/prod), Makefile

**Files:**
- Create: `services/admin-web/Dockerfile`
- Modify: `compose/docker-compose.dev.yml`
- Modify: `compose/docker-compose.prod.yml`
- Modify: `Makefile`

**Interfaces:**
- Consumes: готовый `services/admin-web` (Task 3-7), готовый `api` c `ADMIN_WEB_ORIGIN`/CORS (Task 2).
- Produces: сервис `admin-web` в обоих compose-файлах на порту 3000.

- [ ] **Step 1: Dockerfile**

`services/admin-web/Dockerfile`:

```dockerfile
FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
```

- [ ] **Step 2: `compose/docker-compose.dev.yml`**

В блок `api.environment` добавить (после `GATEWAY_URL: http://gateway:8080`):

```yaml
      ADMIN_WEB_ORIGIN: http://localhost:3000
```

Новый сервис — после блока `api:` (перед `volumes:`):

```yaml

  admin-web:
    build:
      context: ../services/admin-web
      dockerfile: Dockerfile
    environment:
      API_INTERNAL_URL: http://api:8000
      NEXT_PUBLIC_API_URL: http://localhost:8000
    ports:
      - "3000:3000"
    volumes:
      - ../services/admin-web/app:/app/app
      - ../services/admin-web/components:/app/components
      - ../services/admin-web/lib:/app/lib
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://localhost:3000/bots').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 10s
      timeout: 5s
      retries: 10
```

- [ ] **Step 3: `compose/docker-compose.prod.yml`**

В блок `api.environment` добавить (после `GATEWAY_URL: http://gateway:8080`):

```yaml
      ADMIN_WEB_ORIGIN: ${ADMIN_WEB_ORIGIN:-http://127.0.0.1:3000}
```

Новый сервис — после блока `api:` (перед `volumes:`):

```yaml

  # NEXT_PUBLIC_API_URL здесь запечён в dev-сборку Next.js (CMD npm run dev,
  # тот же Dockerfile что в dev-compose) — полноценный прод-билд (Dockerfile.prod
  # с `next build`/`next start`, аналогично services/gateway/Dockerfile.prod, и
  # передачей NEXT_PUBLIC_* через build-arg) не входит в эту итерацию: живая
  # проверка идёт через docker-compose.dev.yml, прод не блокируется, но и не
  # оптимизирован — известный технический долг, не молчаливое допущение.
  admin-web:
    build:
      context: ../services/admin-web
      dockerfile: Dockerfile
    environment:
      API_INTERNAL_URL: http://api:8000
      # Адрес api, каким его видит браузер после SSH-туннеля — НЕ адрес самого
      # admin-web. Дефолт совпадает с тем, что api слушает на хосте (см. блок
      # api.ports выше, "127.0.0.1:8000:8000").
      NEXT_PUBLIC_API_URL: ${ADMIN_WEB_API_PUBLIC_URL:-http://127.0.0.1:8000}
    ports:
      - "127.0.0.1:3000:3000"
    restart: unless-stopped
    depends_on:
      api:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://localhost:3000/bots').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 10s
      timeout: 5s
      retries: 10
```

- [ ] **Step 4: `Makefile`**

`install` — после `cd services/gateway && npm install`:

```makefile
	cd services/admin-web && npm install
```

`test` — после `cd services/gateway && npm test`:

```makefile
	cd services/admin-web && npm test
```

`lint` — после `cd services/gateway && npm run lint`:

```makefile
	cd services/admin-web && npm run lint
```

- [ ] **Step 5: Проверить**

Run: `docker compose -f compose/docker-compose.dev.yml config`
Expected: валидный YAML, без ошибок интерполяции переменных

- [ ] **Step 6: Коммит**

```bash
git add services/admin-web/Dockerfile compose/docker-compose.dev.yml compose/docker-compose.prod.yml Makefile
git commit -m "chore: wire admin-web into compose and Makefile

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Живая проверка (docker compose)

**Files:** нет изменений кода — сквозная проверка собранного стека.

- [ ] **Step 1: Поднять стек**

```bash
make dev
```

Дождаться, пока все сервисы, включая `admin-web`, станут healthy.

- [ ] **Step 2: Создать тестового бота**

```bash
docker compose -f compose/docker-compose.dev.yml exec postgres \
  psql -U platform -d platform -c "INSERT INTO bots (name) VALUES ('demo-qr') RETURNING id;"
```

Запомнить выведенный `id`.

- [ ] **Step 3: Проверить список**

Открыть `http://localhost:3000/bots` — в таблице должен быть `demo-qr`, статус
«Не подключён», номер «—», ссылка «Открыть».

- [ ] **Step 4: Проверить QR и подключение**

Открыть `http://localhost:3000/bots/<id>` — должен появиться QR-код. Отсканировать
реальным WhatsApp на телефоне (Привязка устройства). В течение ~5с (без ручного
обновления страницы) экран должен переключиться на «Подключён: <номер>» и кнопку
«Отключить».

- [ ] **Step 5: Проверить logout**

Нажать «Отключить» — экран должен вернуться к QR-состоянию, `GET /bots/<id>` в api
должен снова отдавать `linked_at: null`.

- [ ] **Step 6: Остановить стек**

```bash
make dev-down
```

Если что-то из Шагов 3-5 не совпало с ожиданием — не коммитить как готово,
вернуться к соответствующей задаче.
