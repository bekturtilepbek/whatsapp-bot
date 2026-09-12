"""POST /bots/{bot_id}/sandbox/messages (FEATURES.md 9.6): owner-only
тестовый прогон промпта, без тулз, без записи в contacts/messages.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from api.routers import sandbox as sandbox_module
from db.engine import make_engine, make_session_factory
from db.models import Bot, Product, UsageEvent
from llm.client import LLMResult
from sqlalchemy import select
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


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], *, system_prompt: str = "Ты — ассистент."
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="sandbox-test-bot",
            enabled=True,
            system_prompt=system_prompt,
            timezone="Asia/Bishkek",
            settings={},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _fake_complete(
    captured_prompts: list[str], captured_histories: list[list[object]], reply: str = "Привет!"
):
    async def fake_complete(system_prompt: str, history: list[object]) -> LLMResult:
        captured_prompts.append(system_prompt)
        captured_histories.append(history)
        return LLMResult(text=reply, tokens_in=11, tokens_out=7, model="gpt-4o-mini")

    return fake_complete


async def test_sandbox_message_returns_reply_and_records_usage(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)
    captured_prompts: list[str] = []
    captured_histories: list[list[object]] = []
    monkeypatch.setattr(
        sandbox_module, "complete", _fake_complete(captured_prompts, captured_histories)
    )

    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 200
    body = response.json()
    assert body == {"reply": "Привет!", "tokens_in": 11, "tokens_out": 7, "model": "gpt-4o-mini"}

    async with session_factory() as session:
        rows = (
            (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].tokens_in == 11
    assert rows[0].tokens_out == 7


async def test_sandbox_message_does_not_persist_contact_or_message_history(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)
    monkeypatch.setattr(sandbox_module, "complete", _fake_complete([], []))

    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 200

    from db.models import Contact, Message

    async with session_factory() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()
        messages = (await session.execute(select(Message))).scalars().all()
    assert contacts == []
    assert messages == []


async def test_sandbox_message_includes_history_and_catalog_in_system_prompt(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory, system_prompt="Ты — ассистент магазина.")
    async with session_factory() as session:
        session.add(Product(bot_id=bot_id, name="Кроссовки", price=Decimal("5000.00")))
        await session.commit()

    captured_prompts: list[str] = []
    captured_histories: list[list[object]] = []
    monkeypatch.setattr(
        sandbox_module, "complete", _fake_complete(captured_prompts, captured_histories)
    )

    response = await client.post(
        f"/bots/{bot_id}/sandbox/messages",
        json={
            "history": [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Здравствуйте!"},
            ],
            "message": "Что у вас есть?",
        },
    )
    assert response.status_code == 200
    assert "Ты — ассистент магазина." in captured_prompts[0]
    assert "Кроссовки" in captured_prompts[0]
    history = captured_histories[0]
    assert [(m.role, m.content) for m in history] == [
        ("user", "Привет"),
        ("assistant", "Здравствуйте!"),
        ("user", "Что у вас есть?"),
    ]


async def test_sandbox_message_empty_text_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "   "})
    assert response.status_code == 422


async def test_sandbox_message_unknown_bot_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/bots/{uuid.uuid4()}/sandbox/messages", json={"message": "Привет"}
    )
    assert response.status_code == 404


async def test_sandbox_message_non_owner_returns_403(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    override_non_owner_auth()
    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 403


async def test_sandbox_message_too_much_history_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    history = [{"role": "user", "content": "x"} for _ in range(51)]
    response = await client.post(
        f"/bots/{bot_id}/sandbox/messages", json={"history": history, "message": "Привет"}
    )
    assert response.status_code == 422
