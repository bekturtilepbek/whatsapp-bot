"""GET/POST/DELETE /bots/{bot_id}/documents (FEATURES.md 6.7).

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
from api.storage import get_storage
from db.engine import make_engine, make_session_factory
from db.models import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.auth_helpers import override_owner_auth

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


def _doc_file(
    name: str = "price.pdf", content: bytes = b"%PDF-1.4 fake"
) -> tuple[str, tuple[str, bytes, str]]:
    return ("file", (name, content, "application/pdf"))


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
    app.state.audit_session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    app.state.audit_session_factory = None


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="documents-test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_list_is_empty_by_default(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/documents")
    assert response.status_code == 200
    assert response.json() == []


async def test_create_then_list(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/documents", files=[_doc_file()])
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "price.pdf"
    assert body["mime_type"] == "application/pdf"

    listing = await client.get(f"/bots/{bot_id}/documents")
    assert [d["filename"] for d in listing.json()] == ["price.pdf"]

    # Реально записан в Storage под ожидаемым ключом.
    key = f"bots/{bot_id}/documents/{body['id']}"
    assert fake_storage.objects[key] == (b"%PDF-1.4 fake", "application/pdf")


async def test_create_for_unknown_bot_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(f"/bots/{uuid.uuid4()}/documents", files=[_doc_file()])
    assert response.status_code == 404


async def test_create_duplicate_filename_returns_409(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.post(f"/bots/{bot_id}/documents", files=[_doc_file()])
    response = await client.post(f"/bots/{bot_id}/documents", files=[_doc_file()])
    assert response.status_code == 409

    listing = await client.get(f"/bots/{bot_id}/documents")
    assert len(listing.json()) == 1  # дубликат не создал вторую строку


async def test_create_same_filename_different_bots_is_fine(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_a = await _make_bot(session_factory)
    bot_b = await _make_bot(session_factory)
    assert (await client.post(f"/bots/{bot_a}/documents", files=[_doc_file()])).status_code == 201
    assert (await client.post(f"/bots/{bot_b}/documents", files=[_doc_file()])).status_code == 201


async def test_create_too_large_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    huge = b"x" * (20 * 1024 * 1024 + 1)
    response = await client.post(f"/bots/{bot_id}/documents", files=[_doc_file(content=huge)])
    assert response.status_code == 422


async def test_create_accepts_any_mime_type(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(
        f"/bots/{bot_id}/documents",
        files=[("file", ("catalog.docx", b"fake docx bytes", "application/vnd.msword"))],
    )
    assert response.status_code == 201
    assert response.json()["mime_type"] == "application/vnd.msword"


async def test_delete_removes_document(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    created = await client.post(f"/bots/{bot_id}/documents", files=[_doc_file()])
    document_id = created.json()["id"]

    response = await client.delete(f"/bots/{bot_id}/documents/{document_id}")
    assert response.status_code == 204

    listing = await client.get(f"/bots/{bot_id}/documents")
    assert listing.json() == []


async def test_delete_unknown_document_returns_404(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.delete(f"/bots/{bot_id}/documents/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_client_without_grant_gets_403(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from datetime import datetime

    from api.security import get_current_user
    from db.models import User

    bot_id = await _make_bot(session_factory)
    client_user = User(
        id=uuid.uuid4(),
        email="no-grant@example.com",
        password_hash="unused",
        is_platform_owner=False,
        is_active=True,
        created_at=datetime.now(),
    )
    app.dependency_overrides[get_current_user] = lambda: client_user

    response = await client.get(f"/bots/{bot_id}/documents")
    assert response.status_code == 403
