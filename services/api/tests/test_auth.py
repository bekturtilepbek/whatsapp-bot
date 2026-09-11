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
from api.main import _bootstrap_platform_owner, app, lifespan
from api.security import hash_password, verify_password
from db.engine import make_engine, make_session_factory
from db.models import User
from db.users import create_user, get_user_by_email
from sqlalchemy import select
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
    app.state.audit_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None


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
    await _make_user(
        session_factory, email="a@example.com", password="s3cret", is_platform_owner=True
    )
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


async def test_login_password_over_72_bytes_returns_422_not_500(
    client: httpx.AsyncClient,
) -> None:
    # bcrypt (>=4.2) бросает ValueError на пароль длиннее 72 байт вместо
    # молчаливого обрезания — Pydantic должен отсечь его чистым 422 раньше,
    # чем он дойдёт до bcrypt.checkpw.
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "x" * 73}
    )
    assert response.status_code == 422


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


async def test_bootstrap_creates_platform_owner_when_absent(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("PLATFORM_OWNER_PASSWORD", "bootstrap-pass")

    await _bootstrap_platform_owner()

    async with session_factory() as session:
        user = await get_user_by_email(session, "owner@example.com")
        assert user is not None
        assert user.is_platform_owner is True
        assert verify_password("bootstrap-pass", user.password_hash)


async def test_bootstrap_is_idempotent_and_does_not_touch_existing_password(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Пользователь с этим email уже существует с другим паролем —
    # bootstrap не должен ни создавать дубликат, ни перезаписывать пароль.
    await _make_user(
        session_factory,
        email="existing-owner@example.com",
        password="original-pass",
        is_platform_owner=True,
    )

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", "existing-owner@example.com")
    monkeypatch.setenv("PLATFORM_OWNER_PASSWORD", "different-pass")

    await _bootstrap_platform_owner()
    await _bootstrap_platform_owner()  # второй вызов — тоже no-op

    async with session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == "existing-owner@example.com")
        )
        users = result.scalars().all()
        assert len(users) == 1
        assert verify_password("original-pass", users[0].password_hash)
        assert not verify_password("different-pass", users[0].password_hash)


async def test_bootstrap_is_noop_when_env_vars_unset(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("PLATFORM_OWNER_EMAIL", raising=False)
    monkeypatch.delenv("PLATFORM_OWNER_PASSWORD", raising=False)

    await _bootstrap_platform_owner()  # не должен падать и не должен ничего создавать

    async with session_factory() as session:
        user = await get_user_by_email(session, "never-created-owner@example.com")
        assert user is None


async def test_lifespan_survives_bootstrap_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # На свежем томе без применённых миграций (таблицы users ещё нет) запрос
    # бутстрапа падает UndefinedTableError — lifespan не должен ронять приложение.
    async def _boom() -> None:
        raise RuntimeError("relation \"users\" does not exist")

    monkeypatch.setattr("api.main._bootstrap_platform_owner", _boom)

    async with lifespan(app):
        pass  # не должно бросить исключение
