"""ASGI-middleware аудит-лога (FEATURES.md 6.19): что должно/не должно
попадать в audit_log при мутирующих запросах. GET /audit-log — см.
Task 4 этого же файла.

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
from api.security import create_access_token
from db.audit_log import list_entries
from db.engine import make_engine, make_session_factory
from db.models import Bot, User
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
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    # Реальный Bearer-токен для реального персистентного owner-пользователя —
    # не override_owner_auth(): та подменяет только FastAPI DI (get_current_user),
    # используемую роутами, а audit_middleware — plain ASGI middleware, вне
    # графа зависимостей, сам декодирует сырой заголовок Authorization тем же
    # decode_access_token. Реальный токен + реальная строка в users заставляет
    # оба пути (роут через DI и middleware через заголовок) резолвить одного
    # и того же actor — без риска split-brain между «кто действовал» и «кто
    # записан в аудит-лог».
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.state.audit_session_factory = session_factory

    async with session_factory() as session:
        owner = User(
            email=f"owner-{uuid.uuid4()}@example.com",
            password_hash="unused",
            is_platform_owner=True,
            is_active=True,
        )
        session.add(owner)
        await session.flush()
        await session.commit()
        owner_id = owner.id

    token = create_access_token(owner_id)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], *, name: str = "test-bot"
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name=name, enabled=True, system_prompt="", timezone="Asia/Bishkek", settings={})
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_successful_patch_creates_audit_entry_with_response_payload(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "Новое имя"})
    assert response.status_code == 200

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    assert len(entries) == 1
    assert entries[0].action == "bots.update"
    assert entries[0].payload is not None
    assert entries[0].payload["name"] == "Новое имя"


async def test_successful_delete_creates_audit_entry_with_path_params_payload(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/blocked-numbers", json={"phone": "996700000000"})
    response = await client.delete(f"/bots/{bot_id}/blocked-numbers/996700000000")
    assert response.status_code == 204

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    delete_entries = [e for e in entries if e.action == "blocked_numbers.delete"]
    assert len(delete_entries) == 1
    assert delete_entries[0].payload == {"bot_id": str(bot_id), "phone": "996700000000"}


async def test_failed_request_does_not_create_audit_entry(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "   "})
    assert response.status_code == 422

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    assert entries == []


async def test_unregistered_route_does_not_create_audit_entry(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get("/bots")
    assert response.status_code == 200

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    assert entries == []


async def test_grant_bot_access_records_bot_id_from_request_body(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Единственный роут, где payload берётся из тела ЗАПРОСА (уровень 2
    fallback) — ответ 204, bot_id только в теле {"bot_id": ...}."""
    from db.users import create_user

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        user = await create_user(session, email="client@example.com", password_hash="unused")
        await session.commit()
        user_id = user.id

    response = await client.post(f"/users/{user_id}/bot-access", json={"bot_id": str(bot_id)})
    assert response.status_code == 204

    async with session_factory() as session:
        entries = await list_entries(session)
    grant_entries = [e for e in entries if e.action == "bot_access.grant"]
    assert len(grant_entries) == 1
    assert grant_entries[0].payload == {"bot_id": str(bot_id)}


async def test_multipart_document_upload_records_response_payload_not_request_body(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    files = {"file": ("price.pdf", b"%PDF-1.4 fake content", "application/pdf")}
    response = await client.post(f"/bots/{bot_id}/documents", files=files)
    assert response.status_code == 201

    async with session_factory() as session:
        entries = await list_entries(session, bot_id=bot_id)
    create_entries = [e for e in entries if e.action == "documents.create"]
    assert len(create_entries) == 1
    assert create_entries[0].payload is not None
    assert create_entries[0].payload["filename"] == "price.pdf"
