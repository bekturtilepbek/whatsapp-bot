"""GET/PATCH /bots/{id}: чтение, частичное обновление, мерж settings без
затирания (CLAUDE.md: "настройки бота мержатся, не перезаписываются").

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


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], **overrides: object
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="исходный промпт",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 1, "media_fallback_text": "заглушка"},
            **overrides,  # type: ignore[arg-type]
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


async def test_get_bot_returns_full_representation(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(bot_id)
    assert body["enabled"] is True
    assert body["system_prompt"] == "исходный промпт"
    assert body["settings"]["batch_timeout_seconds"] == 1


async def test_get_unknown_bot_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/bots/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_patch_enabled_only_does_not_touch_system_prompt(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"enabled": False})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["system_prompt"] == "исходный промпт"


async def test_patch_settings_merges_without_wiping_other_keys(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Прямая проверка грабли CLAUDE.md: сохранение одной секции не должно
    затирать остальные.
    """
    bot_id = await _make_bot(session_factory)
    response = await client.patch(
        f"/bots/{bot_id}", json={"settings": {"auto_release_minutes": 20}}
    )
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["auto_release_minutes"] == 20
    assert settings["batch_timeout_seconds"] == 1  # не стёрлось
    assert settings["media_fallback_text"] == "заглушка"  # не стёрлось


async def test_patch_system_prompt_only(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200
    body = response.json()
    assert body["system_prompt"] == "новый промпт"
    assert body["enabled"] is True  # не тронуто


async def test_patch_unknown_bot_is_404(client: httpx.AsyncClient) -> None:
    response = await client.patch(f"/bots/{uuid.uuid4()}", json={"enabled": False})
    assert response.status_code == 404


async def test_patch_empty_body_is_a_noop(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["system_prompt"] == "исходный промпт"
