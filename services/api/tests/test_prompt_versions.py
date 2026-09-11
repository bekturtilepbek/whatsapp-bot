"""GET /bots/{id}/prompts/{kind}/versions + версионирование через PATCH
(FEATURES.md 3.7/3.8): новая версия при реальном изменении, без дублей на
no-op, откат = обычный PATCH со старым текстом поверх истории, первая
правка бэкаппит то, что уже лежало в bots.* (без этого "откат" на первой
же правке был бы no-op — ради этого сценария 3.8 и заведён).

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


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

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


async def test_first_edit_captures_prior_value_as_baseline_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FEATURES.md 3.8: бот заведён (например, SQL-инсертом — онбординга из
    UI ещё нет, 6.20) с системным промптом, который никогда не проходил
    через PATCH. Первая правка через admin-web не должна тихо терять то,
    что было ДО неё — иначе "откат" на первой же правке был бы no-op.
    """
    bot_id = await _make_bot(session_factory)  # system_prompt="исходный промпт"
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    body = versions.json()
    assert len(body) == 2
    assert body[0]["body"] == "новый промпт"
    assert body[1]["body"] == "исходный промпт"


async def test_first_save_matching_existing_value_creates_no_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)  # system_prompt="исходный промпт"
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "исходный промпт"})
    assert response.status_code == 200

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    assert versions.json() == []


async def test_patch_changing_prompt_creates_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    assert versions.status_code == 200
    body = versions.json()
    assert len(body) == 2  # новая версия + baseline ("исходный промпт")
    assert body[0]["body"] == "новый промпт"
    assert body[0]["author"] == "admin"
    assert body[1]["body"] == "исходный промпт"


async def test_patch_with_same_text_does_not_duplicate_version(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    response = await client.patch(f"/bots/{bot_id}", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    assert len(versions.json()) == 2  # первый PATCH: baseline + новая; второй PATCH — no-op


async def test_versions_returned_newest_first(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 1"})
    await client.patch(f"/bots/{bot_id}", json={"system_prompt": "версия 2"})

    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    body = versions.json()
    assert len(body) == 3
    assert body[0]["body"] == "версия 2"
    assert body[1]["body"] == "версия 1"
    assert body[2]["body"] == "исходный промпт"  # baseline от первого PATCH


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
    assert len(body) == 4  # история не укоротилась (baseline + 3 реальных сохранения)
    assert body[0]["body"] == "версия 1"  # новая запись сверху (откат)
    assert body[1]["body"] == "версия 2"
    assert body[2]["body"] == "версия 1"  # исходная вторая правка
    assert body[3]["body"] == "исходный промпт"  # baseline


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
    # image_prompt/pdf_prompt были NULL до этого PATCH — baseline is None,
    # backfill не срабатывает (нечего бэкаппить), только новая версия.
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


async def test_patch_unknown_bot_with_prompt_field_is_404(
    client: httpx.AsyncClient,
) -> None:
    unknown_id = uuid.uuid4()
    response = await client.patch(f"/bots/{unknown_id}", json={"system_prompt": "x"})
    assert response.status_code == 404
