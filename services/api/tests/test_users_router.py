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
from db.engine import make_engine, make_session_factory
from db.models import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_non_owner_auth, override_owner_auth

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
        "/users",
        json={"email": "granted@example.com", "password": "s3cret", "bot_ids": [str(bot_id)]},
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


async def test_list_users_requires_owner(client: httpx.AsyncClient) -> None:
    override_non_owner_auth()
    response = await client.get("/users")
    assert response.status_code == 403


async def test_create_user_requires_owner(client: httpx.AsyncClient) -> None:
    override_non_owner_auth()
    response = await client.post(
        "/users", json={"email": "blocked@example.com", "password": "s3cret", "bot_ids": []}
    )
    assert response.status_code == 403


async def test_grant_bot_access_requires_owner(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        "/users", json={"email": "grant-403@example.com", "password": "s3cret", "bot_ids": []}
    )
    user_id = created.json()["id"]

    override_non_owner_auth()
    response = await client.post(f"/users/{user_id}/bot-access", json={"bot_id": str(bot_id)})
    assert response.status_code == 403


async def test_revoke_bot_access_requires_owner(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    created = await client.post(
        "/users",
        json={"email": "revoke-403@example.com", "password": "s3cret", "bot_ids": [str(bot_id)]},
    )
    user_id = created.json()["id"]

    override_non_owner_auth()
    response = await client.delete(f"/users/{user_id}/bot-access/{bot_id}")
    assert response.status_code == 403


async def test_patch_user_requires_owner(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/users", json={"email": "patch-403@example.com", "password": "s3cret", "bot_ids": []}
    )
    user_id = created.json()["id"]

    override_non_owner_auth()
    response = await client.patch(f"/users/{user_id}", json={"is_active": False})
    assert response.status_code == 403


async def test_grant_bot_access_unknown_user_returns_404(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/users/{uuid.uuid4()}/bot-access", json={"bot_id": str(bot_id)}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "user not found"


async def test_grant_bot_access_unknown_bot_returns_404(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/users", json={"email": "grant-404@example.com", "password": "s3cret", "bot_ids": []}
    )
    user_id = created.json()["id"]

    response = await client.post(
        f"/users/{user_id}/bot-access", json={"bot_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "bot not found"


async def test_create_user_duplicate_email_returns_409(client: httpx.AsyncClient) -> None:
    payload = {"email": "dupe@example.com", "password": "s3cret", "bot_ids": []}
    first = await client.post("/users", json=payload)
    assert first.status_code == 201

    second = await client.post("/users", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "email already registered"
