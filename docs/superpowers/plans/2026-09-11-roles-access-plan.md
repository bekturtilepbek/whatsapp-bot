# Роли и доступы (6.18) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-tier auth (platform owner sees all bots; client sees only bots
granted to them) with a login flow, replacing admin-web's direct
browser→api fetch with a BFF proxy through admin-web's own server.

**Architecture:** New `users`/`bot_access` tables in Postgres. `api` issues a
JWT on login (`{sub, exp}` only — no embedded role/grants) and enforces
`require_bot_access`/`require_platform_owner` FastAPI dependencies on every
existing `/bots/{bot_id}/...` route. `admin-web` stops calling `api`
directly from the browser: a new catch-all Route Handler
(`app/api-proxy/[...path]/route.ts`) forwards browser requests to `api`
with the session's Bearer token, and Server Components attach the same
token read from `next/headers` for their own SSR fetches. Existing
client components (`ProductsTable`, `QrPanel`, etc.) are unchanged except
for the `apiBaseUrl` prop they're given.

**Tech Stack:** `bcrypt` (password hashing), `PyJWT` (JWT encode/decode) —
both new to `services/api`. No new admin-web dependency — it never
decodes the token, only stores and forwards it opaquely.

**Spec:** `docs/superpowers/specs/2026-09-11-roles-access-design.md`

## Global Constraints

- JWT payload is **only** `{sub: user_id, exp}` — never embed role or bot
  grants in the token. Authorization (`is_platform_owner`, `bot_access`)
  is checked fresh from the DB on every request so a revoked grant or a
  deactivated user takes effect immediately, not at token expiry.
- JWT TTL is 30 days (`JWT_TTL_DAYS = 30`), algorithm `HS256`, secret from
  the required env var `JWT_SECRET` (no default — same strictness as
  `OPENAI_API_KEY` in prod).
- Password hashing is `bcrypt` directly (the package, not `passlib`).
- Two-tier role model only: `User.is_platform_owner: bool` (sees every
  bot, no grant needed) + `BotAccess(user_id, bot_id)` binary grant table
  for clients. No `role` column on `bot_access` yet — do not add one
  speculatively.
- admin-web's existing client components (`ProductsTable`,
  `BlockedNumbersTable`, `ProductForm`, `QrPanel`, `BotSettingsForm`,
  `PromptEditor`) are **not rewritten** — only the `apiBaseUrl` string
  each `page.tsx` passes them changes, from the old public API origin to
  the new `/api-proxy` relative path.
- **Test-fixture migration is mandatory, same task as wiring
  `require_bot_access`/`require_platform_owner` onto existing routes
  (Task 4).** The moment those dependencies land on `bots.py`/`products.py`,
  every existing Docker-gated test file that calls those routes without a
  token starts failing with 401. Task 4 must add a shared test-auth
  override (`app.dependency_overrides[get_current_user] = ...`, not real
  JWTs — see Task 4) to every existing `client` fixture in the same
  commit sequence that adds the dependencies, so the suite is never red
  in between.

---

## File Structure

- `libs/db/src/db/models.py` — add `User`, `BotAccess` (Task 1).
- `libs/db/migrations/versions/202609110001_users_and_bot_access.py` — new
  migration (Task 1).
- `libs/db/src/db/users.py` (new) — `get_user`, `get_user_by_email`,
  `create_user`, `list_users`, `set_user_active`, `set_user_password`
  (Task 1).
- `libs/db/src/db/bot_access.py` (new) — `grant_bot_access`,
  `revoke_bot_access`, `has_bot_access`, `list_bot_ids_for_user` (Task 1).
- `libs/db/src/db/bots.py` — `list_bots` gains `user_id: uuid.UUID | None`
  filter (Task 1).
- `services/api/src/api/security.py` (new) — password hashing, JWT
  encode/decode, `get_current_user`/`CurrentUser`,
  `require_bot_access`/`BotAccessUser`,
  `require_platform_owner`/`PlatformOwner` (Task 2).
- `services/api/src/api/schemas/auth.py` (new) — `LoginRequest`,
  `LoginResponse`, `UserOut` (Task 3).
- `services/api/src/api/routers/auth.py` (new) — `POST /auth/login`,
  `GET /auth/me` (Task 3).
- `services/api/src/api/main.py` — lifespan bootstrap hook, CORS removed
  (Task 3 for bootstrap, Task 4 for CORS removal).
- `services/api/src/api/routers/bots.py`, `products.py` — every route
  gains `BotAccessUser`/`PlatformOwner`; `GET /bots` filters by user
  (Task 4).
- `services/api/tests/auth_helpers.py` (new) — shared fake-owner-user
  override for existing test files (Task 4).
- `services/api/src/api/schemas/users.py` (new), `routers/users.py`
  (new) — owner-only user/grant management (Task 5).
- `services/admin-web/app/api-proxy/[...path]/route.ts` (new) — BFF proxy
  (Task 6).
- `services/admin-web/lib/api.ts` — internal `apiFetch` wrapper replacing
  raw `fetch` calls (Task 6).
- `services/admin-web/lib/env.ts` — `API_PROXY_PATH` added,
  `API_PUBLIC_URL` removed (Task 6).
- `services/admin-web/app/login/page.tsx`, `actions.ts` (new),
  `middleware.ts` (new), `app/layout.tsx` (header + logout) (Task 7).
- `services/admin-web/app/users/page.tsx`,
  `components/UsersTable.tsx` (new) (Task 8).
- `compose/docker-compose.dev.yml`, `docker-compose.prod.yml`,
  `.env.example`, `docs/FEATURES.md` (Task 9).

---

### Task 1: `users`/`bot_access` tables + DB-layer functions

**Files:**
- Modify: `libs/db/src/db/models.py` (add `User`, `BotAccess` after `ToolBinding`)
- Modify: `libs/db/src/db/bots.py` (`list_bots` filter param)
- Create: `libs/db/migrations/versions/202609110001_users_and_bot_access.py`
- Create: `libs/db/src/db/users.py`
- Create: `libs/db/src/db/bot_access.py`
- Test: `libs/db/tests/test_users.py`
- Test: `libs/db/tests/test_bot_access.py`
- Test: `libs/db/tests/test_bots.py` (new file — no existing tests for `list_bots`)

**Interfaces:**
- Produces: `db.models.User` (`id, email, password_hash, is_platform_owner,
  is_active, created_at`), `db.models.BotAccess` (`id, user_id, bot_id,
  created_at`); `db.users.get_user(session, user_id) -> User | None`,
  `get_user_by_email(session, email) -> User | None`,
  `create_user(session, *, email, password_hash, is_platform_owner=False) -> User`,
  `list_users(session) -> list[User]`,
  `set_user_active(session, user_id, is_active) -> User | None`,
  `set_user_password(session, user_id, password_hash) -> User | None`;
  `db.bot_access.grant_bot_access(session, user_id, bot_id) -> None`,
  `revoke_bot_access(session, user_id, bot_id) -> None`,
  `has_bot_access(session, user_id, bot_id) -> bool`,
  `list_bot_ids_for_user(session, user_id) -> list[uuid.UUID]`;
  `db.bots.list_bots(session, *, user_id: uuid.UUID | None = None) -> Sequence[Bot]`
  (when `user_id` is given, only bots that user has `bot_access` to —
  callers pass `None` for "all bots", used by the platform-owner path).

- [ ] **Step 1: Add `User`/`BotAccess` models**

Append to `libs/db/src/db/models.py` (after the `ToolBinding` class):

```python
class User(Base):
    """Пользователь кабинета. Владелец платформы (is_platform_owner=True)
    видит все боты без грантов; клиент — только те, что перечислены в
    BotAccess (FEATURES.md 6.18)."""

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
    (User.is_platform_owner) грант не нужен."""

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

No new imports needed — `Boolean`, `String`, `DateTime`, `ForeignKey`,
`UniqueConstraint`, `func`, `text`, `UUID`, `Mapped`, `mapped_column` are
already imported at the top of `models.py`.

- [ ] **Step 2: Write the Alembic migration**

Check the current head revision first: `grep -rl "down_revision = None" libs/db/migrations/versions/ ; ls libs/db/migrations/versions/ | sort | tail -3` should show `202609090002_prompt_versions_seq.py` as the latest — this migration's `down_revision` must be `"202609090002"`.

Create `libs/db/migrations/versions/202609110001_users_and_bot_access.py`:

```python
"""users and bot_access

Revision ID: 202609110001
Revises: 202609090002
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609110001"
down_revision: str | None = "202609090002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "is_platform_owner", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "bot_access",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "bot_id", name="uq_bot_access_user_bot"),
    )


def downgrade() -> None:
    op.drop_table("bot_access")
    op.drop_table("users")
```

- [ ] **Step 3: Write failing tests for `db.users`**

Create `libs/db/tests/test_users.py`, mirroring
`libs/db/tests/test_blocked_contacts.py`'s Docker-gated setup exactly
(same `_docker_available`, `database_url`, `session` fixtures — copy them
verbatim from that file):

```python
"""users: create/lookup/activate/password (FEATURES.md 6.18).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.users import (
    create_user,
    get_user,
    get_user_by_email,
    list_users,
    set_user_active,
    set_user_password,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
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
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_create_then_get_by_email(session: AsyncSession) -> None:
    user = await create_user(session, email="owner@example.com", password_hash="hash")
    fetched = await get_user_by_email(session, "owner@example.com")
    assert fetched is not None
    assert fetched.id == user.id
    assert fetched.is_platform_owner is False
    assert fetched.is_active is True


async def test_create_platform_owner(session: AsyncSession) -> None:
    user = await create_user(
        session, email="owner2@example.com", password_hash="hash", is_platform_owner=True
    )
    assert user.is_platform_owner is True


async def test_get_by_email_unknown_returns_none(session: AsyncSession) -> None:
    assert await get_user_by_email(session, "nobody@example.com") is None


async def test_get_user_by_id(session: AsyncSession) -> None:
    user = await create_user(session, email="a@example.com", password_hash="hash")
    fetched = await get_user(session, user.id)
    assert fetched is not None
    assert fetched.email == "a@example.com"


async def test_get_user_unknown_id_returns_none(session: AsyncSession) -> None:
    assert await get_user(session, uuid.uuid4()) is None


async def test_duplicate_email_raises(session: AsyncSession) -> None:
    await create_user(session, email="dup@example.com", password_hash="hash")
    with pytest.raises(IntegrityError):
        await create_user(session, email="dup@example.com", password_hash="hash2")


async def test_list_users_returns_all(session: AsyncSession) -> None:
    await create_user(session, email="b1@example.com", password_hash="hash")
    await create_user(session, email="b2@example.com", password_hash="hash")
    emails = {u.email for u in await list_users(session)}
    assert {"b1@example.com", "b2@example.com"} <= emails


async def test_set_user_active_false_then_true(session: AsyncSession) -> None:
    user = await create_user(session, email="c@example.com", password_hash="hash")
    updated = await set_user_active(session, user.id, False)
    assert updated is not None
    assert updated.is_active is False
    updated = await set_user_active(session, user.id, True)
    assert updated is not None
    assert updated.is_active is True


async def test_set_user_active_unknown_returns_none(session: AsyncSession) -> None:
    assert await set_user_active(session, uuid.uuid4(), False) is None


async def test_set_user_password(session: AsyncSession) -> None:
    user = await create_user(session, email="d@example.com", password_hash="old")
    updated = await set_user_password(session, user.id, "new-hash")
    assert updated is not None
    assert updated.password_hash == "new-hash"
```

- [ ] **Step 4: Run — expect failure**

Run: `python -m pytest libs/db/tests/test_users.py -v`
Expected: `ModuleNotFoundError: No module named 'db.users'`

- [ ] **Step 5: Implement `libs/db/src/db/users.py`**

```python
"""Пользователи кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    is_platform_owner: bool = False,
) -> User:
    user = User(email=email, password_hash=password_hash, is_platform_owner=is_platform_owner)
    session.add(user)
    await session.flush()
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def set_user_active(session: AsyncSession, user_id: uuid.UUID, is_active: bool) -> User | None:
    user = await get_user(session, user_id)
    if user is None:
        return None
    user.is_active = is_active
    await session.flush()
    return user


async def set_user_password(
    session: AsyncSession, user_id: uuid.UUID, password_hash: str
) -> User | None:
    user = await get_user(session, user_id)
    if user is None:
        return None
    user.password_hash = password_hash
    await session.flush()
    return user
```

- [ ] **Step 6: Run — expect pass**

Run: `python -m pytest libs/db/tests/test_users.py -v`
Expected: all pass.

- [ ] **Step 7: Write failing tests for `db.bot_access`**

Create `libs/db/tests/test_bot_access.py` (same fixture boilerplate as
Step 3 — copy `_docker_available`/`database_url`/`session` verbatim
again; each test file in this repo duplicates it rather than sharing a
conftest, matching the existing convention in `libs/db/tests/`):

```python
"""bot_access: grant/revoke/check (FEATURES.md 6.18).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.bot_access import grant_bot_access, has_bot_access, list_bot_ids_for_user, revoke_bot_access
from db.engine import make_engine, make_session_factory
from db.models import Bot, User
from sqlalchemy.ext.asyncio import AsyncSession
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
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_user(session: AsyncSession) -> User:
    user = User(email=f"{id(object())}@example.com", password_hash="hash")
    session.add(user)
    await session.flush()
    return user


async def _make_bot(session: AsyncSession) -> Bot:
    bot = Bot(name="test-bot")
    session.add(bot)
    await session.flush()
    return bot


async def test_has_access_false_by_default(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    assert await has_bot_access(session, user.id, bot.id) is False


async def test_grant_then_has_access_true(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await grant_bot_access(session, user.id, bot.id)
    assert await has_bot_access(session, user.id, bot.id) is True


async def test_grant_is_idempotent_on_conflict(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await grant_bot_access(session, user.id, bot.id)
    await grant_bot_access(session, user.id, bot.id)  # не должно упасть
    assert await list_bot_ids_for_user(session, user.id) == [bot.id]


async def test_revoke_then_has_access_false(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await grant_bot_access(session, user.id, bot.id)
    await revoke_bot_access(session, user.id, bot.id)
    assert await has_bot_access(session, user.id, bot.id) is False


async def test_revoke_unknown_grant_is_a_noop(session: AsyncSession) -> None:
    user, bot = await _make_user(session), await _make_bot(session)
    await revoke_bot_access(session, user.id, bot.id)  # не должно упасть


async def test_list_bot_ids_for_user_scoped_per_user(session: AsyncSession) -> None:
    user_a, user_b = await _make_user(session), await _make_user(session)
    bot = await _make_bot(session)
    await grant_bot_access(session, user_a.id, bot.id)
    assert await list_bot_ids_for_user(session, user_a.id) == [bot.id]
    assert await list_bot_ids_for_user(session, user_b.id) == []
```

- [ ] **Step 8: Run — expect failure**

Run: `python -m pytest libs/db/tests/test_bot_access.py -v`
Expected: `ModuleNotFoundError: No module named 'db.bot_access'`

- [ ] **Step 9: Implement `libs/db/src/db/bot_access.py`**

```python
"""Гранты доступа клиентов к ботам (FEATURES.md 6.18)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BotAccess


async def grant_bot_access(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    """Идемпотентно: повторная выдача того же гранта — не ошибка."""
    stmt = (
        insert(BotAccess)
        .values(user_id=user_id, bot_id=bot_id)
        .on_conflict_do_nothing(constraint="uq_bot_access_user_bot")
    )
    await session.execute(stmt)
    await session.flush()


async def revoke_bot_access(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    """Идемпотентно: отзыв отсутствующего гранта — не ошибка (0 строк)."""
    from sqlalchemy import delete

    stmt = delete(BotAccess).where(BotAccess.user_id == user_id, BotAccess.bot_id == bot_id)
    await session.execute(stmt)
    await session.flush()


async def has_bot_access(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> bool:
    stmt = select(BotAccess.id).where(BotAccess.user_id == user_id, BotAccess.bot_id == bot_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def list_bot_ids_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = (
        select(BotAccess.bot_id)
        .where(BotAccess.user_id == user_id)
        .order_by(BotAccess.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

Note: move the `delete` import to the top-level import block with `select`
(written inline above only to keep the diff readable in this plan — the
actual file should import both at the top, matching
`libs/db/src/db/blocked_contacts.py`'s style).

- [ ] **Step 10: Run — expect pass**

Run: `python -m pytest libs/db/tests/test_bot_access.py -v`
Expected: all pass.

- [ ] **Step 11: `list_bots` filter — failing test first**

Create `libs/db/tests/test_bots.py` (same fixture boilerplate again):

```python
"""list_bots: unfiltered vs filtered by user access (FEATURES.md 6.18).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.bot_access import grant_bot_access
from db.bots import list_bots
from db.engine import make_engine, make_session_factory
from db.models import Bot, User
from sqlalchemy.ext.asyncio import AsyncSession
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
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = make_engine(database_url)
    factory = make_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_list_bots_without_user_id_returns_all(session: AsyncSession) -> None:
    bot_a = Bot(name="a")
    bot_b = Bot(name="b")
    session.add_all([bot_a, bot_b])
    await session.flush()
    names = {b.name for b in await list_bots(session)}
    assert {"a", "b"} <= names


async def test_list_bots_with_user_id_filters_to_granted(session: AsyncSession) -> None:
    bot_a = Bot(name="granted")
    bot_b = Bot(name="not-granted")
    user = User(email="client@example.com", password_hash="hash")
    session.add_all([bot_a, bot_b, user])
    await session.flush()
    await grant_bot_access(session, user.id, bot_a.id)

    result = await list_bots(session, user_id=user.id)
    assert [b.name for b in result] == ["granted"]
```

- [ ] **Step 12: Run — expect the second test to fail**

Run: `python -m pytest libs/db/tests/test_bots.py -v`
Expected: `test_list_bots_without_user_id_returns_all` PASSes (current
`list_bots` takes no `user_id` kwarg, so this test doesn't exercise the
new behavior — actually run it first with `list_bots(session,
user_id=user.id)` present in the file: it FAILs with `TypeError:
list_bots() got an unexpected keyword argument 'user_id'`).

- [ ] **Step 13: Add the `user_id` filter to `list_bots`**

In `libs/db/src/db/bots.py`, replace:

```python
async def list_bots(session: AsyncSession) -> Sequence[Bot]:
    result = await session.execute(
        select(Bot).options(selectinload(Bot.session)).order_by(Bot.created_at)
    )
    return result.scalars().all()
```

with:

```python
async def list_bots(session: AsyncSession, *, user_id: uuid.UUID | None = None) -> Sequence[Bot]:
    """user_id=None — все боты (владелец платформы). user_id задан —
    только боты с грантом в bot_access (клиент)."""
    stmt = select(Bot).options(selectinload(Bot.session)).order_by(Bot.created_at)
    if user_id is not None:
        stmt = stmt.join(BotAccess, BotAccess.bot_id == Bot.id).where(BotAccess.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalars().all()
```

Add `BotAccess` to the `from .models import Bot` line → `from .models
import Bot, BotAccess`.

- [ ] **Step 14: Run — expect pass**

Run: `python -m pytest libs/db/tests/test_bots.py libs/db/tests/test_users.py libs/db/tests/test_bot_access.py -v`
Expected: all pass.

- [ ] **Step 15: Run full `libs/db` suite to check nothing else broke**

Run: `python -m pytest libs/db/tests/ -v`
Expected: all pass (existing `list_bots(session)` callers — worker/api —
still work since `user_id` defaults to `None`).

- [ ] **Step 16: Commit**

```bash
git add libs/db/src/db/models.py libs/db/src/db/bots.py libs/db/src/db/users.py libs/db/src/db/bot_access.py libs/db/migrations/versions/202609110001_users_and_bot_access.py libs/db/tests/test_users.py libs/db/tests/test_bot_access.py libs/db/tests/test_bots.py
git commit -m "feat(db): users and bot_access tables (6.18)"
```

---

### Task 2: Password hashing + JWT (`services/api/src/api/security.py`)

**Files:**
- Modify: `services/api/pyproject.toml` (add `bcrypt`, `PyJWT`)
- Create: `services/api/src/api/security.py`
- Test: `services/api/tests/test_security.py`

**Interfaces:**
- Consumes: `db.models.User`, `db.users.get_user`, `db.bot_access.has_bot_access`
  (Task 1), `SessionDep` (`services/api/src/api/db.py`, already exists).
- Produces: `hash_password(password: str) -> str`,
  `verify_password(password: str, password_hash: str) -> bool`,
  `create_access_token(user_id: uuid.UUID) -> str`,
  `decode_access_token(token: str) -> uuid.UUID` (raises
  `jwt.InvalidTokenError` on any problem — expired, bad signature,
  malformed), `get_current_user` (FastAPI dependency function),
  `CurrentUser` (`Annotated[User, Depends(get_current_user)]`),
  `require_bot_access` (dependency function taking `bot_id` from the
  route path), `BotAccessUser` (`Annotated[User, Depends(require_bot_access)]`),
  `require_platform_owner`, `PlatformOwner`
  (`Annotated[User, Depends(require_platform_owner)]`). Task 3 uses
  `hash_password`/`verify_password`/`create_access_token`/`CurrentUser`.
  Task 4 uses `BotAccessUser`/`PlatformOwner`/`CurrentUser`.

- [ ] **Step 1: Add dependencies**

In `services/api/pyproject.toml`, add to the `dependencies` list (after
`"Pillow>=10.4"`):

```toml
    "bcrypt>=4.2",
    "PyJWT>=2.9",
```

Run: `pip install -e services/api` (from repo root, inside the active
venv) to install them.

- [ ] **Step 2: Write failing tests for password hashing and tokens**

Create `services/api/tests/test_security.py`:

```python
"""Пароли (bcrypt) и JWT (PyJWT) — без Docker, чистые функции + токен-цикл."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from api.security import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_different_hash_each_time() -> None:
    h1 = hash_password("correct horse")
    h2 = hash_password("correct horse")
    assert h1 != h2  # bcrypt salt меняется каждый раз


def test_verify_password_correct() -> None:
    h = hash_password("correct horse")
    assert verify_password("correct horse", h) is True


def test_verify_password_incorrect() -> None:
    h = hash_password("correct horse")
    assert verify_password("wrong password", h) is False


def test_create_then_decode_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_decode_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = create_access_token(uuid.uuid4())
    monkeypatch.setenv("JWT_SECRET", "different-secret")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    expired_payload = {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(days=1)}
    token = jwt.encode(expired_payload, "test-secret", algorithm=JWT_ALGORITHM)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)
```

- [ ] **Step 3: Run — expect failure**

Run: `python -m pytest services/api/tests/test_security.py -v`
Expected: `ModuleNotFoundError: No module named 'api.security'`

- [ ] **Step 4: Implement `services/api/src/api/security.py`**

```python
"""Пароли, JWT и FastAPI-зависимости авторизации (FEATURES.md 6.18).

JWT payload — только {sub: user_id, exp}, БЕЗ роли/доступа к ботам: то
проверяется свежо из БД на каждый запрос (require_bot_access/
require_platform_owner), чтобы отзыв гранта или деактивация пользователя
срабатывали немедленно, не дожидаясь протухания токена (30 дней).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from db.bot_access import has_bot_access
from db.models import User
from db.users import get_user
from fastapi import Depends, Header, HTTPException

from .db import SessionDep

JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = 30


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(days=JWT_TTL_DAYS),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Бросает jwt.InvalidTokenError (и подклассы — ExpiredSignatureError,
    InvalidSignatureError, DecodeError, ...) на любую проблему."""
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    return uuid.UUID(payload["sub"])


async def get_current_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="not authenticated")
    token = authorization.removeprefix("Bearer ")
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc
    user = await get_user(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_bot_access(bot_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> User:
    """bot_id приходит из пути роута, в котором эта зависимость
    используется — FastAPI резолвит одноимённый параметр пути
    автоматически."""
    if user.is_platform_owner:
        return user
    if not await has_bot_access(session, user.id, bot_id):
        raise HTTPException(status_code=403, detail="no access to this bot")
    return user


BotAccessUser = Annotated[User, Depends(require_bot_access)]


async def require_platform_owner(user: CurrentUser) -> User:
    if not user.is_platform_owner:
        raise HTTPException(status_code=403, detail="platform owner only")
    return user


PlatformOwner = Annotated[User, Depends(require_platform_owner)]
```

- [ ] **Step 5: Run — expect pass**

Run: `python -m pytest services/api/tests/test_security.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/pyproject.toml services/api/src/api/security.py services/api/tests/test_security.py
git commit -m "feat(api): password hashing + JWT primitives and auth dependencies (6.18)"
```

---

### Task 3: `POST /auth/login`, `GET /auth/me`, bootstrap

**Files:**
- Create: `services/api/src/api/schemas/auth.py`
- Create: `services/api/src/api/routers/auth.py`
- Modify: `services/api/src/api/main.py` (lifespan bootstrap + router registration)
- Test: `services/api/tests/test_auth.py`

**Interfaces:**
- Consumes: `hash_password`, `verify_password`, `create_access_token`,
  `CurrentUser` (Task 2); `create_user`, `get_user_by_email` (Task 1);
  `SessionDep` (existing).
- Produces: `POST /auth/login` (body `{email, password}` → `{token, user:
  {id, email, is_platform_owner}}`), `GET /auth/me` (→ `{id, email,
  is_platform_owner}`). Task 4/5/routers reuse `CurrentUser` from Task 2,
  not anything new here.

- [ ] **Step 1: Schemas**

Create `services/api/src/api/schemas/auth.py`:

```python
"""Pydantic v2 схемы логина (FEATURES.md 6.18)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    is_platform_owner: bool


class LoginResponse(BaseModel):
    token: str
    user: UserOut
```

- [ ] **Step 2: Write failing tests**

Create `services/api/tests/test_auth.py`, using the same Docker-gated
`client`/`database_url`/`session_factory` fixtures as
`services/api/tests/test_blocked_contacts.py` (copy verbatim), plus a
`JWT_SECRET` env var:

```python
"""POST /auth/login, GET /auth/me (FEATURES.md 6.18).

Требует Docker (testcontainers). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from api.security import hash_password
from db.engine import make_engine, make_session_factory
from db.users import create_user
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


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")


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


async def _make_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = "user@example.com",
    password: str = "correct horse",
    is_active: bool = True,
    is_platform_owner: bool = False,
) -> None:
    async with session_factory() as session:
        user = await create_user(
            session,
            email=email,
            password_hash=hash_password(password),
            is_platform_owner=is_platform_owner,
        )
        user.is_active = is_active
        await session.commit()


async def test_login_success_returns_token_and_user(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _make_user(session_factory, email="a@example.com", password="s3cret", is_platform_owner=True)
    response = await client.post(
        "/auth/login", json={"email": "a@example.com", "password": "s3cret"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "a@example.com"
    assert body["user"]["is_platform_owner"] is True
    assert isinstance(body["token"], str) and body["token"]


async def test_login_wrong_password_returns_401(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _make_user(session_factory, email="b@example.com", password="s3cret")
    response = await client.post(
        "/auth/login", json={"email": "b@example.com", "password": "wrong"}
    )
    assert response.status_code == 401


async def test_login_unknown_email_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "x"}
    )
    assert response.status_code == 401


async def test_login_inactive_user_returns_401(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _make_user(session_factory, email="c@example.com", password="s3cret", is_active=False)
    response = await client.post(
        "/auth/login", json={"email": "c@example.com", "password": "s3cret"}
    )
    assert response.status_code == 401


async def test_me_returns_current_user(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _make_user(session_factory, email="d@example.com", password="s3cret")
    login = await client.post(
        "/auth/login", json={"email": "d@example.com", "password": "s3cret"}
    )
    token = login.json()["token"]
    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "d@example.com"


async def test_me_without_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401
```

- [ ] **Step 3: Run — expect failure**

Run: `python -m pytest services/api/tests/test_auth.py -v`
Expected: `ModuleNotFoundError: No module named 'api.routers.auth'`

- [ ] **Step 4: Implement the router**

Create `services/api/src/api/routers/auth.py`:

```python
"""POST /auth/login, GET /auth/me (FEATURES.md 6.18)."""

from __future__ import annotations

from db.users import get_user_by_email
from fastapi import APIRouter, HTTPException

from ..db import SessionDep
from ..schemas.auth import LoginRequest, LoginResponse, UserOut
from ..security import CurrentUser, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, session: SessionDep) -> LoginResponse:
    user = await get_user_by_email(session, body.email)
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        # Одно и то же сообщение на "нет email" и "неверный пароль" —
        # не раскрываем существование аккаунта.
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = create_access_token(user.id)
    return LoginResponse(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
```

- [ ] **Step 5: Register the router and add the bootstrap lifespan hook**

Read `services/api/src/api/main.py` first (it currently registers `bots`
and `products` routers and configures `CORSMiddleware` — CORS removal is
Task 4, not this step; leave it as-is here). Replace its content with:

```python
"""FastAPI: HTTP-ручки управления ботами (STAGE1_CORE Блок 3, п.2).

Слушает 0.0.0.0 внутри контейнера (стандартная докер-практика); публичная
доступность решается маппингом порта в compose — на проде на хост
пробрасывается только 127.0.0.1 (SSH-туннель), в dev — обычный маппинг.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from db.engine import make_engine, make_session_factory, session_scope
from db.users import get_user_by_email
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import auth, bots, products
from .security import hash_password


async def _bootstrap_platform_owner() -> None:
    """PLATFORM_OWNER_EMAIL/PLATFORM_OWNER_PASSWORD заданы — создаёт
    владельца платформы при первом старте, если такого email ещё нет.
    Идемпотентно: не трогает уже существующий пароль на повторных стартах."""
    email = os.environ.get("PLATFORM_OWNER_EMAIL")
    password = os.environ.get("PLATFORM_OWNER_PASSWORD")
    if not email or not password:
        return
    engine = make_engine()
    try:
        async with session_scope(make_session_factory(engine)) as session:
            if await get_user_by_email(session, email) is not None:
                return
            from db.users import create_user

            await create_user(
                session, email=email, password_hash=hash_password(password), is_platform_owner=True
            )
            await session.commit()
    finally:
        await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _bootstrap_platform_owner()
    yield


app = FastAPI(title="platform-api", lifespan=lifespan)

# admin-web стучится в api напрямую из браузера (Волна 3, QR-экран, подход A) —
# без allow-origin браузер зарубит fetch. allow_credentials не
# нужен — auth ещё нет (6.18, отдельная итерация), делить нечего.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ADMIN_WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(bots.router)
app.include_router(products.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

(CORS middleware is left in place here deliberately — Task 4 removes it
in the same commit as wiring `require_bot_access`, since removing it
early would be a no-op change disconnected from the reason it's safe to
remove.)

- [ ] **Step 6: Run — expect pass**

Run: `python -m pytest services/api/tests/test_auth.py -v`
Expected: all pass.

- [ ] **Step 7: Run the full api test suite to check nothing broke**

Run: `python -m pytest services/api/tests/ -v`
Expected: all pass (no route gained an auth dependency yet — that's Task 4).

- [ ] **Step 8: Commit**

```bash
git add services/api/src/api/schemas/auth.py services/api/src/api/routers/auth.py services/api/src/api/main.py services/api/tests/test_auth.py
git commit -m "feat(api): POST /auth/login, GET /auth/me, platform-owner bootstrap (6.18)"
```

---

### Task 4: Wire `require_bot_access`/`require_platform_owner` onto every existing route + migrate all test fixtures

**This is the pivotal task — read the Global Constraints section again
before starting.** The moment `BotAccessUser`/`PlatformOwner` land on a
route, every test hitting that route via the existing Docker-gated
`client` fixtures starts returning 401 instead of its expected status,
because those fixtures never send an `Authorization` header. This task
fixes that in the SAME set of commits, using `app.dependency_overrides`
(the pattern this codebase already uses for `get_session`/`get_storage`/
`get_redis`) rather than minting real JWTs per test — it's simpler and
matches the existing idiom exactly.

**Files:**
- Create: `services/api/tests/auth_helpers.py`
- Modify: `services/api/src/api/routers/bots.py` (every route)
- Modify: `services/api/src/api/routers/products.py` (every route)
- Modify: `services/api/src/api/main.py` (remove `CORSMiddleware`)
- Modify: `services/api/tests/test_products.py`, `test_blocked_contacts.py`,
  `test_bots.py`, `test_tool_bindings.py`, `test_prompt_versions.py`,
  `test_release.py`, `test_gateway_proxy.py` (add the auth override to
  each `client` fixture / equivalent setup)
- Delete: `services/api/tests/test_cors.py` (tests a middleware that no
  longer exists)
- Test: `services/api/tests/test_bots.py` (extend — see Step 6)

**Interfaces:**
- Consumes: `get_current_user`, `BotAccessUser`, `PlatformOwner`,
  `CurrentUser` (Task 2); `list_bots(session, user_id=...)` (Task 1).
- Produces: `services/api/tests/auth_helpers.py::FAKE_OWNER_USER` (a
  `db.models.User`-shaped stand-in with `is_platform_owner=True`,
  `is_active=True`) and `override_owner_auth(app) -> None` (sets
  `app.dependency_overrides[get_current_user] = lambda: FAKE_OWNER_USER`)
  — every later task's test files that hit bot-scoped routes import and
  call this in their `client` fixture.

- [ ] **Step 1: Read the current route lists**

Run: `grep -n "@router\." services/api/src/api/routers/bots.py
services/api/src/api/routers/products.py` — confirm the 13 routes in
`bots.py` (`GET ""`, `GET/PATCH /{bot_id}`, `GET
/{bot_id}/prompts/{kind}/versions`, `GET /{bot_id}/qr`, `POST
/{bot_id}/logout`, `POST /{bot_id}/chats/{chat_id}/release`, `GET/POST
/{bot_id}/blocked-numbers`, `DELETE /{bot_id}/blocked-numbers/{phone}`,
`GET/POST /{bot_id}/tools`, `DELETE /{bot_id}/tools/{tool_name}`) and the
8 routes in `products.py` (`GET/POST /{bot_id}/products`, `GET/PATCH/DELETE
/{bot_id}/products/{product_id}`, `POST
/{bot_id}/products/{product_id}/photos`, `DELETE/GET
/{bot_id}/products/{product_id}/photos/{photo_id}`) match what this step
expects. If the actual file has diverged (a route added/removed since
this plan was written), cover every route that has `{bot_id}` in its path
— that is the actual rule, this list is just today's inventory.

- [ ] **Step 2: Create the shared test-auth helper**

Create `services/api/tests/auth_helpers.py`:

```python
"""Общий override авторизации для существующих тестов (FEATURES.md 6.18).

require_bot_access/require_platform_owner требуют CurrentUser — тесты
роутов, написанные до этого суб-проекта, не отправляют Authorization и не
должны его знать: подменяем саму FastAPI-зависимость get_current_user на
фиксированного владельца платформы (is_platform_owner=True), тот же
паттерн, что уже применяется к get_session/get_storage/get_redis в этих
файлах. Владелец проходит require_bot_access для ЛЮБОГО bot_id без
обращения к БД (short-circuit в security.py) — эти тесты не нуждаются в
реальной строке users/bot_access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from api.main import app
from api.security import get_current_user
from db.models import User

FAKE_OWNER_USER = User(
    id=uuid.uuid4(),
    email="test-owner@example.com",
    password_hash="unused",
    is_platform_owner=True,
    is_active=True,
    created_at=datetime.now(),
)


def override_owner_auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: FAKE_OWNER_USER
```

- [ ] **Step 3: Wire the dependencies onto `bots.py`**

Read `services/api/src/api/routers/bots.py` in full first. Add the
import:

```python
from .security import BotAccessUser, CurrentUser, PlatformOwner
```

(adjust the relative import prefix to match the file's existing
`from ..db import SessionDep`-style imports — `security.py` lives at
`services/api/src/api/security.py`, same level as `db.py`).

For every route with `{bot_id}` in its path, add a `user: BotAccessUser`
parameter (name doesn't matter functionally — `user` matches this plan's
convention). Example for `read_bot`:

```python
@router.get("/{bot_id}", response_model=BotOut)
async def read_bot(bot_id: uuid.UUID, session: SessionDep, user: BotAccessUser) -> BotOut:
    ...
```

Apply the same one-line addition (`user: BotAccessUser`) to: `patch_bot`,
`list_prompt_versions`, `get_qr`, `logout_bot`, `release_chat`,
`list_blocked`, `add_blocked`, `delete_blocked`, `list_tools`, `add_tool`,
`delete_tool`. None of these routes' bodies need any other change —
`BotAccessUser` raises `HTTPException` itself (401/403) before the route
body runs if access is denied.

For `GET ""` (`list_all_bots`), do NOT add `BotAccessUser` (there's no
`bot_id` in this path) — instead change it to filter:

```python
@router.get("", response_model=list[BotOut])
async def list_all_bots(session: SessionDep, user: CurrentUser) -> list[BotOut]:
    filter_user_id = None if user.is_platform_owner else user.id
    bots = await list_bots(session, user_id=filter_user_id)
    return [BotOut.model_validate(b) for b in bots]
```

(`list_bots` needs to be imported from `db.bots` if not already — check
the current import line.)

- [ ] **Step 4: Wire the dependencies onto `products.py`**

Read `services/api/src/api/routers/products.py` in full first (already
quoted above in this plan's research). Add the import:

```python
from ..security import BotAccessUser
```

Add `user: BotAccessUser` as a parameter to every route function:
`list_products_route`, `create_product_route`, `get_product_route`,
`patch_product_route`, `delete_product_route`, `add_product_photos_route`,
`delete_product_photo_route`, `get_product_photo_route`. Place it
immediately after `session: SessionDep` (or after `storage: StorageDep`
where both are present — parameter order doesn't matter to FastAPI, but
keep it consistent for readability). None of these route bodies need any
other change.

- [ ] **Step 5: Remove CORS and delete its test**

In `services/api/src/api/main.py`, remove the `CORSMiddleware` import and
`app.add_middleware(CORSMiddleware, ...)` block entirely (browser no
longer calls `api` directly — Task 6 introduces the BFF proxy that makes
this true). Delete `services/api/tests/test_cors.py`.

```bash
rm services/api/tests/test_cors.py
```

- [ ] **Step 6: Update every existing test file's fixture**

For each of `test_products.py`, `test_blocked_contacts.py`,
`test_bots.py`, `test_tool_bindings.py`, `test_prompt_versions.py`: add
`from auth_helpers import override_owner_auth` to the imports, and call
`override_owner_auth()` as the first line inside the `client` fixture,
before `app.dependency_overrides[get_session] = ...`. Example diff shape
for `test_products.py`'s `client` fixture:

```python
@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

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

Apply the same shape (`override_owner_auth()` as the first line of the
fixture body) to `test_blocked_contacts.py`, `test_bots.py`,
`test_tool_bindings.py`, `test_prompt_versions.py` — each has a `client`
fixture that already does `app.dependency_overrides[get_session] = ...`
in the same shape (confirmed in this plan's research).

For `test_release.py` (no `get_session` override — pure Redis, but
`release_chat` now needs `BotAccessUser` which needs `CurrentUser`, which
needs a DB session to look up the fake user... except the override
replaces `get_current_user` entirely, so `SessionDep` inside
`require_bot_access` is never actually reached for the owner
short-circuit path — no `get_session` override is needed here since the
owner path never touches the DB). Update its `client` fixture:

```python
@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, FakeRedis]]:
    override_owner_auth()
    redis = FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: redis
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, redis
    app.dependency_overrides.clear()
    await redis.aclose()
```

Add `from auth_helpers import override_owner_auth` to its imports.

For `test_gateway_proxy.py` (no `client` fixture — each test builds its
own `httpx.AsyncClient` inline, with `_clear_overrides` as an
`autouse=True` fixture that only clears afterward), add a sibling
autouse fixture that sets the override beforehand:

```python
@pytest.fixture(autouse=True)
def _override_auth() -> None:
    override_owner_auth()
```

Add `from auth_helpers import override_owner_auth` to its imports. Keep
the existing `_clear_overrides` fixture as-is (it still clears
everything, including this new override, after each test).

- [ ] **Step 7: Add new coverage for the access-control behavior itself**

Add to `services/api/tests/test_bots.py` (read its existing structure
first, place these alongside the existing tests, reusing its
`session_factory`/`_make_bot`-equivalent helpers):

```python
async def test_client_without_grant_gets_403_on_bot_route(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from api.security import get_current_user
    from db.models import User

    bot_id = await _make_bot(session_factory)  # use this file's existing bot-creation helper
    client_user = User(
        id=uuid.uuid4(),
        email="client@example.com",
        password_hash="unused",
        is_platform_owner=False,
        is_active=True,
        created_at=datetime.now(),
    )
    app.dependency_overrides[get_current_user] = lambda: client_user

    response = await client.get(f"/bots/{bot_id}")
    assert response.status_code == 403


async def test_client_with_grant_gets_200_on_bot_route(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from api.security import get_current_user
    from db.bot_access import grant_bot_access
    from db.models import User

    bot_id = await _make_bot(session_factory)
    client_user = User(
        id=uuid.uuid4(),
        email="client2@example.com",
        password_hash="unused",
        is_platform_owner=False,
        is_active=True,
        created_at=datetime.now(),
    )
    async with session_factory() as session:
        session.add(client_user)
        await grant_bot_access(session, client_user.id, bot_id)
        await session.commit()
    app.dependency_overrides[get_current_user] = lambda: client_user

    response = await client.get(f"/bots/{bot_id}")
    assert response.status_code == 200


async def test_list_bots_filters_by_grant_for_non_owner(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from api.security import get_current_user
    from db.bot_access import grant_bot_access
    from db.models import User

    granted_bot_id = await _make_bot(session_factory)
    await _make_bot(session_factory)  # not granted
    client_user = User(
        id=uuid.uuid4(),
        email="client3@example.com",
        password_hash="unused",
        is_platform_owner=False,
        is_active=True,
        created_at=datetime.now(),
    )
    async with session_factory() as session:
        session.add(client_user)
        await grant_bot_access(session, client_user.id, granted_bot_id)
        await session.commit()
    app.dependency_overrides[get_current_user] = lambda: client_user

    response = await client.get("/bots")
    assert [b["id"] for b in response.json()] == [str(granted_bot_id)]
```

(Add `import uuid`, `from datetime import datetime` to the file's imports
if not already present — check first, `test_bots.py` likely already
imports `uuid` for bot ids.)

- [ ] **Step 8: Run the full api test suite**

Run: `python -m pytest services/api/tests/ -v`
Expected: all pass, including the three new tests in Step 7. If any
existing test still fails with 401/403, its `client` fixture is missing
`override_owner_auth()` — go back to Step 6.

- [ ] **Step 9: Run mypy/ruff on changed files**

Run: `python -m ruff check services/api/src services/api/tests && python
-m mypy services/api/src --strict`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add services/api/src/api/routers/bots.py services/api/src/api/routers/products.py services/api/src/api/main.py services/api/tests/
git rm services/api/tests/test_cors.py
git commit -m "feat(api): enforce bot access control on every bot-scoped route (6.18)"
```

---

### Task 5: Owner-only user management API

**Files:**
- Create: `services/api/src/api/schemas/users.py`
- Create: `services/api/src/api/routers/users.py`
- Modify: `services/api/src/api/main.py` (register router)
- Test: `services/api/tests/test_users_router.py`

**Interfaces:**
- Consumes: `create_user`, `list_users`, `set_user_active`,
  `set_user_password`, `get_user` (Task 1); `grant_bot_access`,
  `revoke_bot_access`, `list_bot_ids_for_user` (Task 1); `hash_password`
  (Task 2); `PlatformOwner` (Task 2); `override_owner_auth` (Task 4, for
  this task's own tests).
- Produces: `GET /users`, `POST /users`, `POST
  /users/{user_id}/bot-access`, `DELETE
  /users/{user_id}/bot-access/{bot_id}`, `PATCH /users/{user_id}`. Task 8
  (admin-web `/users` screen) is the consumer of all five.

- [ ] **Step 1: Schemas**

Create `services/api/src/api/schemas/users.py`:

```python
"""Pydantic v2 схемы управления пользователями кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from .auth import UserOut


class UserWithAccessOut(UserOut):
    bot_ids: list[UUID]


class UserCreate(BaseModel):
    email: str
    password: str
    bot_ids: list[UUID] = []


class UserPatch(BaseModel):
    """Оба поля опциональны — трогаем только реально переданные."""

    is_active: bool | None = None
    password: str | None = None
```

(`UserOut` already has `model_config = ConfigDict(from_attributes=True)`
from Task 3 — `UserWithAccessOut` inherits it, no need to redeclare.)

- [ ] **Step 2: Write failing tests**

Create `services/api/tests/test_users_router.py`, same Docker-gated setup
as `test_blocked_contacts.py` plus `override_owner_auth()` from Task 4's
helper in the `client` fixture:

```python
"""GET/POST /users, POST/DELETE .../bot-access, PATCH /users/{id}
(FEATURES.md 6.18, owner-only).

Требует Docker (testcontainers). Без него — skip, не fail.
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
from auth_helpers import override_owner_auth
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
    override_owner_auth()

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
        bot = Bot(name="users-test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_create_user_then_list(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/users", json={"email": "new@example.com", "password": "s3cret", "bot_ids": []}
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"

    listing = await client.get("/users")
    assert any(u["email"] == "new@example.com" for u in listing.json())


async def test_create_user_with_initial_bot_access(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        "/users", json={"email": "granted@example.com", "password": "s3cret", "bot_ids": [str(bot_id)]}
    )
    assert response.status_code == 201
    assert response.json()["bot_ids"] == [str(bot_id)]


async def test_grant_then_revoke_bot_access(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        "/users", json={"email": "grantee@example.com", "password": "s3cret", "bot_ids": []}
    )
    user_id = created.json()["id"]

    grant = await client.post(f"/users/{user_id}/bot-access", json={"bot_id": str(bot_id)})
    assert grant.status_code == 204

    listing = await client.get("/users")
    granted_user = next(u for u in listing.json() if u["id"] == user_id)
    assert granted_user["bot_ids"] == [str(bot_id)]

    revoke = await client.delete(f"/users/{user_id}/bot-access/{bot_id}")
    assert revoke.status_code == 204

    listing = await client.get("/users")
    granted_user = next(u for u in listing.json() if u["id"] == user_id)
    assert granted_user["bot_ids"] == []


async def test_patch_deactivates_user(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/users", json={"email": "deactivate@example.com", "password": "s3cret", "bot_ids": []}
    )
    user_id = created.json()["id"]

    response = await client.patch(f"/users/{user_id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_non_owner_gets_403(client: httpx.AsyncClient) -> None:
    from api.security import get_current_user
    from datetime import datetime
    from db.models import User

    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(),
        email="not-owner@example.com",
        password_hash="unused",
        is_platform_owner=False,
        is_active=True,
        created_at=datetime.now(),
    )
    response = await client.get("/users")
    assert response.status_code == 403
```

Note: `UserOut`/`UserWithAccessOut` don't carry `is_active` in Task 3's
`UserOut` — check whether the `test_patch_deactivates_user` assertion
needs `UserWithAccessOut` (used by `PATCH`'s response) to include
`is_active`. It doesn't yet — add it:

- [ ] **Step 2b: Add `is_active` to the response schemas**

In `services/api/src/api/schemas/auth.py`, add `is_active: bool` to
`UserOut` (right after `is_platform_owner: bool`). This is a small,
justified widening of Task 3's schema — `GET /auth/me` gains an
`is_active` field too (harmless, always `true` there since
`get_current_user` already rejects inactive users), and it's needed here
so the users-management screen can show/patch it.

- [ ] **Step 3: Run — expect failure**

Run: `python -m pytest services/api/tests/test_users_router.py -v`
Expected: `ModuleNotFoundError: No module named 'api.routers.users'`

- [ ] **Step 4: Implement the router**

Create `services/api/src/api/routers/users.py`:

```python
"""GET/POST /users, POST/DELETE .../bot-access, PATCH /users/{id} —
владелец платформы управляет клиентскими аккаунтами (FEATURES.md 6.18).
"""

from __future__ import annotations

import uuid

from db.bot_access import grant_bot_access, list_bot_ids_for_user, revoke_bot_access
from db.models import User
from db.users import create_user, get_user, list_users, set_user_active, set_user_password
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import SessionDep
from ..schemas.users import UserCreate, UserPatch, UserWithAccessOut
from ..security import PlatformOwner, hash_password

router = APIRouter(prefix="/users", tags=["users"])


class _BotAccessIn(BaseModel):
    bot_id: uuid.UUID


async def _to_out(session: SessionDep, user: User) -> UserWithAccessOut:
    bot_ids = await list_bot_ids_for_user(session, user.id)
    return UserWithAccessOut(
        id=user.id,
        email=user.email,
        is_platform_owner=user.is_platform_owner,
        is_active=user.is_active,
        bot_ids=bot_ids,
    )


@router.get("", response_model=list[UserWithAccessOut])
async def list_users_route(session: SessionDep, _owner: PlatformOwner) -> list[UserWithAccessOut]:
    users = await list_users(session)
    return [await _to_out(session, u) for u in users]


@router.post("", response_model=UserWithAccessOut, status_code=201)
async def create_user_route(
    body: UserCreate, session: SessionDep, _owner: PlatformOwner
) -> UserWithAccessOut:
    user = await create_user(session, email=body.email, password_hash=hash_password(body.password))
    for bot_id in body.bot_ids:
        await grant_bot_access(session, user.id, bot_id)
    await session.commit()
    return await _to_out(session, user)


@router.post("/{user_id}/bot-access", status_code=204)
async def grant_bot_access_route(
    user_id: uuid.UUID, body: _BotAccessIn, session: SessionDep, _owner: PlatformOwner
) -> None:
    await grant_bot_access(session, user_id, body.bot_id)
    await session.commit()


@router.delete("/{user_id}/bot-access/{bot_id}", status_code=204)
async def revoke_bot_access_route(
    user_id: uuid.UUID, bot_id: uuid.UUID, session: SessionDep, _owner: PlatformOwner
) -> None:
    await revoke_bot_access(session, user_id, bot_id)
    await session.commit()


@router.patch("/{user_id}", response_model=UserWithAccessOut)
async def patch_user_route(
    user_id: uuid.UUID, body: UserPatch, session: SessionDep, _owner: PlatformOwner
) -> UserWithAccessOut:
    if body.is_active is not None:
        updated = await set_user_active(session, user_id, body.is_active)
        if updated is None:
            raise HTTPException(status_code=404, detail="user not found")
    if body.password is not None:
        updated = await set_user_password(session, user_id, hash_password(body.password))
        if updated is None:
            raise HTTPException(status_code=404, detail="user not found")
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await session.commit()
    return await _to_out(session, user)
```

(The `# type: ignore[attr-defined]` comments in `_to_out` are a plan-time
placeholder for typing `user: object` loosely — the actual implementer
should type it properly as `db.models.User` instead, which removes the
need for those comments entirely. Fix this during implementation, don't
carry the `type: ignore`s into the real file.)

Register the router in `services/api/src/api/main.py`:
`from .routers import auth, bots, products, users` and
`app.include_router(users.router)`.

- [ ] **Step 5: Run — expect pass**

Run: `python -m pytest services/api/tests/test_users_router.py -v`
Expected: all pass.

- [ ] **Step 6: Run mypy/ruff and full suite**

Run: `python -m ruff check services/api/src services/api/tests && python
-m mypy services/api/src --strict && python -m pytest services/api/tests/ -v`
Expected: clean, all pass. Fix the `_to_out` typing properly here if not
already done.

- [ ] **Step 7: Commit**

```bash
git add services/api/src/api/schemas/users.py services/api/src/api/schemas/auth.py services/api/src/api/routers/users.py services/api/src/api/main.py services/api/tests/test_users_router.py
git commit -m "feat(api): owner-only user and bot-access management (6.18)"
```

---

### Task 6: admin-web BFF proxy + `apiFetch`

**Files:**
- Create: `services/admin-web/app/api-proxy/[...path]/route.ts`
- Modify: `services/admin-web/lib/api.ts` (introduce `apiFetch`, replace
  all raw `fetch(` calls)
- Modify: `services/admin-web/lib/env.ts` (`API_PROXY_PATH` added,
  `API_PUBLIC_URL` removed)
- Modify: 7 `page.tsx` files (see Task list below) — `apiBaseUrl` prop
  value change only
- Test: `services/admin-web/app/api-proxy/route.test.ts`
- Test: `services/admin-web/lib/api.test.ts` (extend — read it first)

**Interfaces:**
- Consumes: nothing new from earlier tasks (this task is admin-web-only;
  it targets the `api` HTTP surface that already exists).
- Produces: `API_PROXY_PATH = "/api-proxy"` (exported from `lib/env.ts`)
  — Task 7/8 use it for client components, and the proxy route itself.

- [ ] **Step 1: Read the current `lib/api.ts` and `lib/env.ts` in full**

`lib/api.ts` currently has ~15 separate `fetch(` calls, one per exported
function (`fetchBots`, `fetchBot`, `fetchProducts`, `fetchProduct`,
`createProduct`, `updateProduct`, `deleteProduct`, `addProductPhotos`,
`deleteProductPhoto`, `fetchBlockedNumbers`, `addBlockedNumber`,
`deleteBlockedNumber`, plus prompts/settings functions not shown in this
plan's research — read the actual file, it will have grown since this
plan was written). Every one of them needs its `fetch(` call routed
through a new shared `apiFetch` wrapper instead.

- [ ] **Step 2: Add `apiFetch` to `lib/api.ts`**

At the top of `services/admin-web/lib/api.ts`, after the existing header
comment, add:

```typescript
/** Общая обёртка вокруг fetch — на сервере (Server Component / Route
 * Handler, typeof window === "undefined") сама подмешивает `Authorization`
 * из cookie сессии admin-web (FEATURES.md 6.18); в браузере просто зовёт
 * fetch как есть — cookie для "/api-proxy" (свой origin) браузер приложит
 * сам. Динамический импорт next/headers — этот модуль не должен тянуться
 * в клиентский бандл (next/headers ломает сборку клиентских компонентов). */
async function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  if (typeof window === "undefined") {
    const { cookies } = await import("next/headers");
    const token = (await cookies()).get("session")?.value;
    if (token) {
      const headers = new Headers(init?.headers);
      headers.set("Authorization", `Bearer ${token}`);
      return fetch(url, { ...init, headers });
    }
  }
  return fetch(url, init);
}
```

- [ ] **Step 3: Replace every raw `fetch(` call with `apiFetch(`**

For each exported function in `lib/api.ts`, change its `await
fetch(...)` call to `await apiFetch(...)` — the call signature (url,
init) is identical, so this is a pure find-and-replace per call site, no
other change. Example (`fetchBots`):

```typescript
export async function fetchBots(baseUrl: string): Promise<Bot[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/bots`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /bots failed: ${res.status}`);
  }
  return (await res.json()) as Bot[];
}
```

Apply the same `fetch(` → `apiFetch(` substitution to every other
function in the file. Do not change anything else about each function —
URLs, error messages, and response parsing stay identical.

- [ ] **Step 4: Write the BFF proxy Route Handler**

Create `services/admin-web/app/api-proxy/[...path]/route.ts`:

```typescript
import { cookies } from "next/headers";
import { API_INTERNAL_URL } from "@/lib/env";

// Единая точка входа для всех client-компонентов кабинета (FEATURES.md
// 6.18) — браузер больше не стучится в api напрямую. Читает session-cookie
// admin-web, форвардит на API_INTERNAL_URL с Authorization: Bearer, стримит
// ответ обратно. Работает и для multipart (загрузка фото товара) — тело не
// парсится, только форвардится с оригинальным Content-Type.

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "content-length",
  "host",
]);

async function proxy(request: Request, path: string[]): Promise<Response> {
  const token = (await cookies()).get("session")?.value;
  if (!token) {
    return new Response(JSON.stringify({ detail: "not authenticated" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const url = new URL(request.url);
  const target = `${API_INTERNAL_URL}/${path.join("/")}${url.search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  headers.set("Authorization", `Bearer ${token}`);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstream = await fetch(target, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
  });

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export async function GET(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
export async function POST(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
export async function PATCH(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
export async function DELETE(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(request, (await params).path);
}
```

- [ ] **Step 5: `lib/env.ts` — add `API_PROXY_PATH`, remove `API_PUBLIC_URL`**

Replace `services/admin-web/lib/env.ts` entirely:

```typescript
// Адреса api — общие для всех Server Component-страниц кабинета.

/** Внутренний адрес api в docker-сети — для SSR-фетчей на сервере и для
 * BFF-прокси (app/api-proxy). */
export const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** Путь BFF-прокси на самом admin-web — им пользуются клиентские
 * компоненты вместо прямого адреса api (FEATURES.md 6.18: браузер больше
 * не стучится в api напрямую, только в свой origin). */
export const API_PROXY_PATH = "/api-proxy";
```

- [ ] **Step 6: Update the 7 `page.tsx` files**

For each of `app/bots/[id]/page.tsx`, `app/bots/[id]/products/page.tsx`,
`app/bots/[id]/products/new/page.tsx`,
`app/bots/[id]/products/[productId]/edit/page.tsx`,
`app/bots/[id]/prompts/page.tsx`, `app/bots/[id]/settings/page.tsx`,
`app/bots/[id]/blocked-numbers/page.tsx`: change the import from
`API_PUBLIC_URL` to `API_PROXY_PATH` (both from `@/lib/env`), and change
every prop currently passed as `apiBaseUrl={API_PUBLIC_URL}` to
`apiBaseUrl={API_PROXY_PATH}`. This is the only change to each of these
7 files — read each one first to find its exact `API_PUBLIC_URL` usage
site(s) (some pass it to more than one child component, e.g. `ProductForm`
might also need it for direct browser uploads).

- [ ] **Step 7: Write tests for `apiFetch` behavior**

Read `services/admin-web/lib/api.test.ts` first (32 existing tests, per
this plan's research context). Add, near the top of the file:

```typescript
import { describe, expect, it, vi, beforeEach } from "vitest";

describe("apiFetch (server-side auth header)", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("attaches the session cookie as a Bearer header on the server", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({
        get: (name: string) => (name === "session" ? { value: "test-token" } : undefined),
      }),
    }));
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { fetchBots } = await import("./api");
    await fetchBots("http://api-internal:8000");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer test-token");
  });
});
```

(This test relies on `typeof window === "undefined"` being true in the
vitest environment used for `lib/api.test.ts` — check the file's
existing `describe`/environment setup; if that file's vitest config runs
under `jsdom` — which defines `window` — this test needs to run in a
separate file configured for the `node` environment, e.g. add a
`// @vitest-environment node` comment at the top of a new
`lib/apiFetch.test.ts` file instead of extending `api.test.ts`. Decide
based on what `vitest.config.ts`/`package.json` actually specifies —
read it before writing this step's final form.)

- [ ] **Step 8: Write a test for the proxy route handler**

Create `services/admin-web/app/api-proxy/route.test.ts`
(`// @vitest-environment node` at the top, since this handler uses
`next/headers` and Web `Request`/`Response`, not DOM):

```typescript
// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (name === "session" ? { value: "test-token" } : undefined),
  }),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api-proxy route handler", () => {
  it("forwards GET with Authorization header and streams the response", async () => {
    const upstreamResponse = new Response(JSON.stringify([{ id: "b1" }]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(upstreamResponse);

    const { GET } = await import("./[...path]/route");
    const request = new Request("http://admin-web/api-proxy/bots");
    const response = await GET(request, { params: Promise.resolve({ path: ["bots"] }) });

    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:8000/bots",
      expect.objectContaining({ method: "GET" }),
    );
    const [, init] = fetchSpy.mock.calls[0];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer test-token");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ id: "b1" }]);
  });

  it("returns 401 without hitting api when there is no session cookie", async () => {
    vi.doMock("next/headers", () => ({
      cookies: async () => ({ get: () => undefined }),
    }));
    const fetchSpy = vi.spyOn(global, "fetch");

    const { GET } = await import("./[...path]/route");
    const request = new Request("http://admin-web/api-proxy/bots");
    const response = await GET(request, { params: Promise.resolve({ path: ["bots"] }) });

    expect(response.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 9: Run vitest, tsc, eslint**

Run: `cd services/admin-web && npx vitest run && npx tsc --noEmit && npx eslint .`
Expected: all clean. Fix the environment-annotation issue from Step 7 if
tests fail due to `window` being defined.

- [ ] **Step 10: Commit**

```bash
git add services/admin-web/app/api-proxy services/admin-web/lib/api.ts services/admin-web/lib/env.ts services/admin-web/app/bots
git commit -m "feat(admin-web): BFF proxy replaces direct browser->api fetch (6.18)"
```

---

### Task 7: Login, logout, middleware, header

**Files:**
- Create: `services/admin-web/app/login/page.tsx`
- Create: `services/admin-web/app/login/actions.ts`
- Create: `services/admin-web/middleware.ts`
- Create: `services/admin-web/components/AppHeader.tsx`
- Modify: `services/admin-web/app/layout.tsx`
- Test: `services/admin-web/app/login/actions.test.ts`
- Test: `services/admin-web/middleware.test.ts`

**Interfaces:**
- Consumes: `API_INTERNAL_URL` (`lib/env.ts`), `POST /auth/login`,
  `GET /auth/me` (Task 3, reached directly — not through the proxy, since
  these run server-side).
- Produces: the `session` cookie contract every later screen (Task 8)
  and the proxy (Task 6) already assume: `httpOnly`, `sameSite: "lax"`,
  `secure` in production, `maxAge` 30 days, name `session`, value = the
  raw JWT string.

- [ ] **Step 1: Server Action for login**

Create `services/admin-web/app/login/actions.ts`:

```typescript
"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_INTERNAL_URL } from "@/lib/env";

const SESSION_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export async function login(_prevState: string | null, formData: FormData): Promise<string | null> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  const res = await fetch(`${API_INTERNAL_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    return "Неверный email или пароль";
  }

  const body = (await res.json()) as { token: string };
  (await cookies()).set("session", body.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: SESSION_COOKIE_MAX_AGE_SECONDS,
    path: "/",
  });

  redirect("/bots");
}

export async function logout(): Promise<void> {
  (await cookies()).delete("session");
  redirect("/login");
}
```

- [ ] **Step 2: Login page**

Create `services/admin-web/app/login/page.tsx`:

```typescript
"use client";

import { useActionState } from "react";
import { login } from "./actions";

export default function LoginPage() {
  const [error, formAction, pending] = useActionState(login, null);

  return (
    <main>
      <h1>Вход</h1>
      <form action={formAction}>
        <label>
          Email
          <input type="email" name="email" required autoFocus />
        </label>
        <label>
          Пароль
          <input type="password" name="password" required />
        </label>
        {error && (
          <p role="alert" style={{ color: "crimson" }}>
            {error}
          </p>
        )}
        <button type="submit" disabled={pending}>
          {pending ? "Входим…" : "Войти"}
        </button>
      </form>
    </main>
  );
}
```

(`useActionState`'s error type here is `string | null` matching `login`'s
return type — a successful login calls `redirect()` inside the action,
which never returns a value to the client, so the "success" branch of
`error` is unreachable by construction.)

- [ ] **Step 3: Middleware**

Create `services/admin-web/middleware.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";

// UX-гейт: реальная авторизация проверяется api на каждый запрос
// (require_bot_access/require_platform_owner, FEATURES.md 6.18) — баг или
// отсутствие здесь не открывает дыру, только портит UX (пустая страница
// вместо редиректа на /login).
export function middleware(request: NextRequest): NextResponse {
  const hasSession = request.cookies.has("session");
  if (!hasSession && request.nextUrl.pathname !== "/login") {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!login|api-proxy|_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 4: Write a unit test for the middleware logic**

Create `services/admin-web/middleware.test.ts`:

```typescript
// @vitest-environment node
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "./middleware";

function makeRequest(path: string, cookie?: string): NextRequest {
  const headers = new Headers();
  if (cookie) headers.set("cookie", cookie);
  return new NextRequest(new Request(`http://admin-web${path}`, { headers }));
}

describe("middleware", () => {
  it("redirects to /login when there is no session cookie", () => {
    const response = middleware(makeRequest("/bots"));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/login");
  });

  it("passes through when a session cookie is present", () => {
    const response = middleware(makeRequest("/bots", "session=token"));
    expect(response.status).toBe(200);
  });

  it("does not redirect the /login page itself", () => {
    const response = middleware(makeRequest("/login"));
    expect(response.status).toBe(200);
  });
});
```

- [ ] **Step 5: Header with logout + owner-only nav**

Create `services/admin-web/components/AppHeader.tsx`:

```typescript
import Link from "next/link";
import { logout } from "@/app/login/actions";
import { API_INTERNAL_URL } from "@/lib/env";

interface CurrentUser {
  email: string;
  is_platform_owner: boolean;
}

async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const { cookies } = await import("next/headers");
  const token = (await cookies()).get("session")?.value;
  if (!token) return null;
  const res = await fetch(`${API_INTERNAL_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as CurrentUser;
}

export async function AppHeader() {
  const user = await fetchCurrentUser();
  if (!user) return null;

  return (
    <header>
      <span>{user.email}</span>
      {user.is_platform_owner && <Link href="/users">Пользователи</Link>}
      <form action={logout}>
        <button type="submit">Выйти</button>
      </form>
    </header>
  );
}
```

- [ ] **Step 6: Wire the header into the layout**

Modify `services/admin-web/app/layout.tsx`:

```typescript
import type { ReactNode } from "react";
import { AppHeader } from "@/components/AppHeader";
import "./globals.css";

export const metadata = {
  title: "Панель ботов",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <AppHeader />
        {children}
      </body>
    </html>
  );
}
```

(`AppHeader` reads the cookie itself and renders nothing on `/login`
since there's no session yet — no special-casing needed in the layout.)

- [ ] **Step 7: Run vitest, tsc, eslint**

Run: `cd services/admin-web && npx vitest run && npx tsc --noEmit && npx eslint .`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add services/admin-web/app/login services/admin-web/middleware.ts services/admin-web/middleware.test.ts services/admin-web/components/AppHeader.tsx services/admin-web/app/layout.tsx
git commit -m "feat(admin-web): login/logout, session middleware, header (6.18)"
```

---

### Task 8: `/users` screen (owner-only)

**Files:**
- Create: `services/admin-web/app/users/page.tsx`
- Create: `services/admin-web/components/UsersTable.tsx`
- Modify: `services/admin-web/lib/api.ts` (add `fetchUsers`, `createUser`,
  `grantBotAccess`, `revokeBotAccess`, `patchUser` client functions)
- Test: `services/admin-web/components/UsersTable.test.tsx`

**Interfaces:**
- Consumes: `GET/POST /users`, `POST/DELETE .../bot-access`, `PATCH
  /users/{id}` (Task 5); `API_PROXY_PATH`, `apiFetch` (Task 6);
  `fetchBots` (existing, for the bot-grant checkboxes).

- [ ] **Step 1: Add client functions to `lib/api.ts`**

Following the exact shape of `fetchBlockedNumbers`/`addBlockedNumber`/
`deleteBlockedNumber` already in the file (read them again for the
pattern), add:

```typescript
// Пользователи кабинета (FEATURES.md 6.18, только для владельца платформы).

export interface CabinetUser {
  id: string;
  email: string;
  is_platform_owner: boolean;
  is_active: boolean;
  bot_ids: string[];
}

export async function fetchUsers(baseUrl: string): Promise<CabinetUser[]> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`GET /users failed: ${res.status}`);
  }
  return (await res.json()) as CabinetUser[];
}

export async function createUser(
  baseUrl: string,
  input: { email: string; password: string; bot_ids: string[] },
): Promise<CabinetUser> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(`POST /users failed: ${res.status}`);
  }
  return (await res.json()) as CabinetUser;
}

export async function grantBotAccess(baseUrl: string, userId: string, botId: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/${userId}/bot-access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bot_id: botId }),
  });
  if (!res.ok) {
    throw new Error(`POST /users/${userId}/bot-access failed: ${res.status}`);
  }
}

export async function revokeBotAccess(baseUrl: string, userId: string, botId: string): Promise<void> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/${userId}/bot-access/${botId}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`DELETE /users/${userId}/bot-access/${botId} failed: ${res.status}`);
  }
}

export async function patchUser(
  baseUrl: string,
  userId: string,
  patch: { is_active?: boolean; password?: string },
): Promise<CabinetUser> {
  const base = normalizeBaseUrl(baseUrl);
  const res = await apiFetch(`${base}/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    throw new Error(`PATCH /users/${userId} failed: ${res.status}`);
  }
  return (await res.json()) as CabinetUser;
}
```

- [ ] **Step 2: `UsersTable` component**

Create `services/admin-web/components/UsersTable.tsx`, following
`BlockedNumbersTable.tsx`'s shape (add-form + table + per-row actions, no
pagination needed — client accounts are expected to be few):

```typescript
"use client";

import { useState, type FormEvent } from "react";
import {
  createUser,
  grantBotAccess,
  patchUser,
  revokeBotAccess,
  type CabinetUser,
} from "@/lib/api";
import type { Bot } from "@/lib/api";

interface UsersTableProps {
  apiBaseUrl: string;
  users: CabinetUser[];
  bots: Bot[];
}

export function UsersTable({ apiBaseUrl, users, bots }: UsersTableProps) {
  const [rows, setRows] = useState(users);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password.trim()) return;
    setError(null);
    setCreating(true);
    try {
      const created = await createUser(apiBaseUrl, { email, password, bot_ids: [] });
      setRows((current) => [...current, created]);
      setEmail("");
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать");
    } finally {
      setCreating(false);
    }
  };

  const toggleAccess = async (userId: string, botId: string, hasAccess: boolean) => {
    setError(null);
    try {
      if (hasAccess) {
        await revokeBotAccess(apiBaseUrl, userId, botId);
      } else {
        await grantBotAccess(apiBaseUrl, userId, botId);
      }
      setRows((current) =>
        current.map((u) =>
          u.id === userId
            ? {
                ...u,
                bot_ids: hasAccess ? u.bot_ids.filter((id) => id !== botId) : [...u.bot_ids, botId],
              }
            : u,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить доступ");
    }
  };

  const toggleActive = async (userId: string, isActive: boolean) => {
    setError(null);
    try {
      await patchUser(apiBaseUrl, userId, { is_active: !isActive });
      setRows((current) =>
        current.map((u) => (u.id === userId ? { ...u, is_active: !isActive } : u)),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось изменить статус");
    }
  };

  return (
    <>
      {error && (
        <p role="alert" style={{ color: "crimson" }}>
          {error}
        </p>
      )}
      <form onSubmit={(event) => void handleCreate(event)}>
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="client@example.com"
          aria-label="Email"
        />
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Пароль"
          aria-label="Пароль"
        />
        <button type="submit" disabled={creating}>
          {creating ? "Создаём…" : "Создать пользователя"}
        </button>
      </form>
      <table>
        <thead>
          <tr>
            <th>Email</th>
            <th>Активен</th>
            {bots.map((bot) => (
              <th key={bot.id}>{bot.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows
            .filter((u) => !u.is_platform_owner)
            .map((user) => (
              <tr key={user.id}>
                <td>{user.email}</td>
                <td>
                  <input
                    type="checkbox"
                    checked={user.is_active}
                    onChange={() => void toggleActive(user.id, user.is_active)}
                    aria-label={`Активен: ${user.email}`}
                  />
                </td>
                {bots.map((bot) => {
                  const hasAccess = user.bot_ids.includes(bot.id);
                  return (
                    <td key={bot.id}>
                      <input
                        type="checkbox"
                        checked={hasAccess}
                        onChange={() => void toggleAccess(user.id, bot.id, hasAccess)}
                        aria-label={`${bot.name}: ${user.email}`}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
        </tbody>
      </table>
    </>
  );
}
```

- [ ] **Step 3: Page**

Create `services/admin-web/app/users/page.tsx`:

```typescript
import { redirect } from "next/navigation";
import { UsersTable } from "@/components/UsersTable";
import { fetchBots, fetchUsers } from "@/lib/api";
import { API_INTERNAL_URL, API_PROXY_PATH } from "@/lib/env";

async function currentUserIsOwner(): Promise<boolean> {
  const { cookies } = await import("next/headers");
  const token = (await cookies()).get("session")?.value;
  if (!token) return false;
  const res = await fetch(`${API_INTERNAL_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!res.ok) return false;
  const user = (await res.json()) as { is_platform_owner: boolean };
  return user.is_platform_owner;
}

export default async function UsersPage() {
  if (!(await currentUserIsOwner())) {
    redirect("/bots");
  }

  const [users, bots] = await Promise.all([
    fetchUsers(API_INTERNAL_URL),
    fetchBots(API_INTERNAL_URL),
  ]);

  return (
    <main>
      <h1>Пользователи</h1>
      <UsersTable apiBaseUrl={API_PROXY_PATH} users={users} bots={bots} />
    </main>
  );
}
```

(`currentUserIsOwner`'s duplicated shape versus `AppHeader.tsx`'s
`fetchCurrentUser` is acceptable here — both are small, single-purpose,
server-only helpers; if this repeats a third time, extract a shared
`lib/currentUser.ts`, but YAGNI for two call sites.)

- [ ] **Step 4: Component test**

Create `services/admin-web/components/UsersTable.test.tsx`, mirroring
`BlockedNumbersTable.test.tsx`'s mocking shape (mock `createUser`,
`grantBotAccess`, `revokeBotAccess`, `patchUser` from `@/lib/api`; test
rendering, create-user, grant/revoke checkbox toggling, deactivate
toggle, and the error-banner-on-failure path for each action) — at least
8 tests covering: renders rows, hides the platform owner's own row,
creates a user, shows an error on create failure, grants access via
checkbox, revokes access via checkbox, toggles active/inactive, shows an
error on a failed toggle.

- [ ] **Step 5: Run vitest, tsc, eslint**

Run: `cd services/admin-web && npx vitest run && npx tsc --noEmit && npx eslint .`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/admin-web/app/users services/admin-web/components/UsersTable.tsx services/admin-web/components/UsersTable.test.tsx services/admin-web/lib/api.ts
git commit -m "feat(admin-web): owner-only users and bot-access screen (6.18)"
```

---

### Task 9: Compose/env wiring, docs, live verification

**Files:**
- Modify: `compose/docker-compose.dev.yml` (api: add `JWT_SECRET`,
  `PLATFORM_OWNER_EMAIL`, `PLATFORM_OWNER_PASSWORD`; admin-web: remove
  dead `NEXT_PUBLIC_API_URL`)
- Modify: `compose/docker-compose.prod.yml` (api: add the same three as
  required `${VAR:?...}`; admin-web: remove `NEXT_PUBLIC_API_URL`)
- Modify: `.env.example`
- Modify: `docs/FEATURES.md` (row 6.18)

- [ ] **Step 1: Dev compose**

In `compose/docker-compose.dev.yml`'s `api` service `environment:` block,
add (hardcoded dev values, matching the existing convention of hardcoded
`POSTGRES_USER`/`POSTGRES_PASSWORD` for dev — no `.env` required to run
`docker compose -f compose/docker-compose.dev.yml up`):

```yaml
      JWT_SECRET: dev-insecure-jwt-secret-do-not-use-in-prod
      PLATFORM_OWNER_EMAIL: owner@dev.local
      PLATFORM_OWNER_PASSWORD: devpassword123
```

In the `admin-web` service's `environment:` block, remove the
`NEXT_PUBLIC_API_URL: http://localhost:8000` line — it's dead now that
client components use the BFF proxy, not a public api URL. Keep
`API_INTERNAL_URL: http://api:8000` — Server Components still use it.

- [ ] **Step 2: Prod compose**

In `compose/docker-compose.prod.yml`'s `api` service `environment:`
block, add (matching the strict `${VAR:?... не задан в .env}` pattern
already used for `POSTGRES_PASSWORD`/`OPENAI_API_KEY`/etc. in this file):

```yaml
      JWT_SECRET: ${JWT_SECRET:?JWT_SECRET не задан в .env}
      PLATFORM_OWNER_EMAIL: ${PLATFORM_OWNER_EMAIL:?PLATFORM_OWNER_EMAIL не задан в .env}
      PLATFORM_OWNER_PASSWORD: ${PLATFORM_OWNER_PASSWORD:?PLATFORM_OWNER_PASSWORD не задан в .env}
```

The `admin-web` service in this file no longer has a `NEXT_PUBLIC_API_URL`
build-arg or environment entry to remove — that variable name was already
retired in the earlier admin-web-prod-build fix (its `build.args` now
only carries `NEXT_PUBLIC_API_URL` for... check the current state of this
block first: if a leftover `NEXT_PUBLIC_API_URL` build-arg still exists
from before this plan, remove it here too, since admin-web's client code
no longer references it after Task 6).

- [ ] **Step 3: `.env.example`**

Add near the other prod-only secrets in `.env.example` (after the
`TELEGRAM_BOT_TOKEN` block, before `STORAGE_DRIVER`):

```
# Только для docker-compose.prod.yml (дев-значения захардкожены в
# docker-compose.dev.yml) — роли и доступы (FEATURES.md 6.18).
JWT_SECRET=
PLATFORM_OWNER_EMAIL=
PLATFORM_OWNER_PASSWORD=
```

- [ ] **Step 4: `docs/FEATURES.md`**

Update row 6.18 (currently `| 6.18 | Роли и доступы | NEW | Сейчас пара
логин/пароль в .env на каждого бота. Нужно: клиент видит только своего
бота, ты — всё |`):

```
| 6.18 | Роли и доступы | NEW | Сдано (2026-09-11): двухуровневая модель
(владелец платформы / клиент), таблицы users/bot_access, JWT-сессии
(30 дней, только {sub, exp} в payload), BFF-прокси admin-web→api (см.
docs/superpowers/specs/2026-09-11-roles-access-design.md). Публичный
сетевой периметр (TLS/reverse-proxy) — отдельная, ещё не запланированная
итерация |
```

- [ ] **Step 5: Live verification on docker compose**

This step is executed directly by the controller (not dispatched as an
implementer task) after the final whole-branch review passes. Checklist:

1. `docker compose -f compose/docker-compose.dev.yml up -d --build`,
   apply migrations (`docker compose ... exec -w /app/libs/db api python
   -m alembic upgrade head` — see `windows-docker-gotchas` memory for the
   `MSYS_NO_PATHCONV=1`/Git-Bash path caveat on Windows).
2. Confirm the platform owner was bootstrapped: `docker compose ... exec
   postgres psql -U platform -d platform -c "SELECT email,
   is_platform_owner FROM users;"` shows `owner@dev.local`.
3. `curl -X POST http://localhost:8000/auth/login -H "Content-Type:
   application/json" -d '{"email":"owner@dev.local","password":"devpassword123"}'`
   returns a token.
4. `curl http://localhost:8000/bots` (no token) → 401.
5. `curl http://localhost:8000/bots -H "Authorization: Bearer
   <token>"` → 200, lists all bots (owner).
6. Create a bot directly via SQL (existing manual-onboarding convention),
   create a second (client) user via `POST /users` as the owner, confirm
   that user's `GET /bots` (with their own token from `POST
   /auth/login`) only shows bots they've been granted, and that `GET
   /bots/{ungranted_bot_id}` returns 403 for them.
7. Open `http://localhost:3000` in the browser pane — confirm redirect to
   `/login` (no session cookie yet). Log in as the owner through the
   actual UI form. Confirm `/bots` renders, `/users` link appears in the
   header, creating a user and toggling their bot access through the
   `/users` screen works end-to-end (checkbox → real grant → visible
   effect on next reload).
8. Log out, confirm redirect to `/login`. Log back in as the client user
   created in step 6/7 — confirm they see only their granted bot(s), and
   that no "Пользователи" link appears in their header.
9. Confirm the existing screens (products, blocked-numbers, settings,
   prompts) still work end-to-end through the new BFF proxy (thumbnails
   render, "Показать ещё" pagination works, forms submit) — these
   exercise `apiFetch`/the proxy route for the first time in a real
   browser, not just tests.

Report exactly which of these were verified against the real running
stack versus any that had to be worked around (mirroring how the
товары/фото live verification report distinguished real Docker evidence
from direct-API-call substitutes).

- [ ] **Step 6: Commit**

```bash
git add compose/docker-compose.dev.yml compose/docker-compose.prod.yml .env.example docs/FEATURES.md
git commit -m "chore: wire JWT_SECRET/PLATFORM_OWNER_* into compose, update FEATURES.md (6.18)"
```

---

## Self-Review Notes (for the plan author, not the executor)

- **Spec coverage:** Architecture (BFF) → Task 6. Data (users/bot_access)
  → Task 1. API (auth, security deps, wiring, users router) → Tasks 2-5.
  admin-web (login/middleware/proxy/apiFetch/users screen/header) → Tasks
  6-8. Explicitly-deferred items (reverse-proxy/TLS, self-service reset,
  finer roles, refresh tokens, 6.20) are not implemented anywhere in this
  plan — correct, matches spec.
- **Test-fixture ordering constraint:** satisfied by Task 4 doing the
  wiring and the fixture migration in the same task, using
  `app.dependency_overrides[get_current_user]` rather than real JWTs —
  simpler than the spec's literal wording ("подмешать Authorization-заголовок"),
  same effect, consistent with this codebase's existing
  `get_session`/`get_storage`/`get_redis` override idiom.
- **Type consistency check:** `BotAccessUser`/`PlatformOwner`/`CurrentUser`
  (Task 2) are used identically in Tasks 3, 4, 5 — no renaming across
  tasks. `API_PROXY_PATH` (Task 6) is the same constant Task 8 imports.
  `UserOut`/`UserWithAccessOut` (Tasks 3/5) share the same field names
  throughout (`id`, `email`, `is_platform_owner`, `is_active`).
- **Placeholder scan:** no TBD/TODO/"add appropriate handling" phrasing
  anywhere in the task steps; every code block is complete, runnable code
  matching this codebase's actual current patterns (verified against the
  real files during research, not assumed).
