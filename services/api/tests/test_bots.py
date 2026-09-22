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
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session
from api.main import app
from db.contacts import match_or_create_contact
from db.engine import make_engine, make_session_factory
from db.messages import insert_incoming, insert_outgoing
from db.models import Bot, BotSession
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


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str = "test-bot",
    **overrides: object,
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name=name,
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
    response = await client.patch(f"/bots/{bot_id}/enabled", json={"enabled": False})
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


async def test_patch_name_renames_bot(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """FEATURES.md 6.3 — название бота редактируемо после создания."""
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "Новое имя"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Новое имя"
    assert body["system_prompt"] == "исходный промпт"  # не тронуто


async def test_patch_name_strips_whitespace(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "  С пробелами  "})
    assert response.status_code == 200
    assert response.json()["name"] == "С пробелами"


async def test_patch_name_blank_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}", json={"name": "   "})
    assert response.status_code == 422


async def test_patch_system_prompt_only(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(f"/bots/{bot_id}/prompts", json={"system_prompt": "новый промпт"})
    assert response.status_code == 200
    body = response.json()
    assert body["system_prompt"] == "новый промпт"
    assert body["enabled"] is True  # не тронуто


async def test_patch_bot_updates_image_prompt(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(
        f"/bots/{bot_id}/prompts", json={"image_prompt": "Опиши товар клиенту."}
    )
    assert response.status_code == 200
    assert response.json()["image_prompt"] == "Опиши товар клиенту."

    follow_up = await client.get(f"/bots/{bot_id}")
    assert follow_up.json()["image_prompt"] == "Опиши товар клиенту."


async def test_get_bot_includes_null_image_prompt_by_default(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}")
    assert response.json()["image_prompt"] is None


async def test_patch_bot_updates_pdf_prompt(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.patch(
        f"/bots/{bot_id}/prompts", json={"pdf_prompt": "Изучи документ и ответь клиенту."}
    )
    assert response.status_code == 200
    assert response.json()["pdf_prompt"] == "Изучи документ и ответь клиенту."

    follow_up = await client.get(f"/bots/{bot_id}")
    assert follow_up.json()["pdf_prompt"] == "Изучи документ и ответь клиенту."


async def test_get_bot_includes_null_pdf_prompt_by_default(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}")
    assert response.json()["pdf_prompt"] is None


async def test_patch_unknown_bot_is_404(client: httpx.AsyncClient) -> None:
    response = await client.patch(f"/bots/{uuid.uuid4()}/enabled", json={"enabled": False})
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


async def test_get_bot_includes_status_and_last_seen(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)

    response = await client.get(f"/bots/{bot_id}")
    body = response.json()
    assert body["status"] is None
    assert body["last_seen"] is None

    async with session_factory() as session:
        session.add(BotSession(bot_id=bot_id, status="open", last_seen=datetime.now(UTC)))
        await session.commit()

    response = await client.get(f"/bots/{bot_id}")
    body = response.json()
    assert body["status"] == "open"
    assert body["last_seen"] is not None


async def test_client_without_grant_gets_403_on_bot_route(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    from api.security import get_current_user
    from db.models import User

    bot_id = await _make_bot(session_factory)
    client_user = User(
        id=uuid.uuid4(),
        email="client@example.com",
        password_hash="unused",
        role="client",
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
        role="client",
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


async def _make_granted_client(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID, email: str
) -> None:
    """Ролевой пересмотр 2026-09-22: client с грантом на бота видит его
    (BotAccessUser), но урезан на технических/рискованных действиях
    (FullBotAccess — промпты/настройки/чёрный список/тулзы/QR)."""
    from api.security import get_current_user
    from db.bot_access import grant_bot_access
    from db.models import User

    client_user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash="unused",
        role="client",
        is_active=True,
        created_at=datetime.now(),
    )
    async with session_factory() as session:
        session.add(client_user)
        await grant_bot_access(session, client_user.id, bot_id)
        await session.commit()
    app.dependency_overrides[get_current_user] = lambda: client_user


async def test_granted_client_can_toggle_enabled(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await _make_granted_client(session_factory, bot_id, "client-enabled@example.com")

    response = await client.patch(f"/bots/{bot_id}/enabled", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False


async def test_granted_client_gets_403_on_prompts(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await _make_granted_client(session_factory, bot_id, "client-prompts@example.com")

    response = await client.patch(
        f"/bots/{bot_id}/prompts", json={"system_prompt": "попытка клиента"}
    )
    assert response.status_code == 403


async def test_granted_client_gets_403_on_settings(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await _make_granted_client(session_factory, bot_id, "client-settings@example.com")

    response = await client.patch(f"/bots/{bot_id}", json={"name": "Переименовано клиентом"})
    assert response.status_code == 403


async def test_granted_client_gets_403_on_blocked_numbers(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await _make_granted_client(session_factory, bot_id, "client-blocked@example.com")

    response = await client.get(f"/bots/{bot_id}/blocked-numbers")
    assert response.status_code == 403


async def test_granted_client_gets_403_on_tools(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    await _make_granted_client(session_factory, bot_id, "client-tools@example.com")

    response = await client.get(f"/bots/{bot_id}/tools")
    assert response.status_code == 403


async def test_granted_client_can_still_see_active_chats_and_prompt_history(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Активные чаты и история промптов (только чтение) остаются
    BotAccessUser — доступны client, в отличие от записи промптов."""
    bot_id = await _make_bot(session_factory)
    await _make_granted_client(session_factory, bot_id, "client-readonly@example.com")

    chats = await client.get(f"/bots/{bot_id}/chats")
    assert chats.status_code == 200
    versions = await client.get(f"/bots/{bot_id}/prompts/main/versions")
    assert versions.status_code == 200


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
        role="client",
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


async def test_create_bot_returns_201_with_defaults(client: httpx.AsyncClient) -> None:
    response = await client.post("/bots", json={"name": "Новый бот"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Новый бот"
    assert body["enabled"] is True
    assert body["phone"] is None
    assert body["linked_at"] is None
    assert body["timezone"] == "Asia/Bishkek"


async def test_create_bot_appears_in_list(client: httpx.AsyncClient) -> None:
    created = await client.post("/bots", json={"name": "В списке"})
    bot_id = created.json()["id"]

    listing = await client.get("/bots")
    assert any(b["id"] == bot_id for b in listing.json())


async def test_create_bot_empty_name_returns_422(client: httpx.AsyncClient) -> None:
    response = await client.post("/bots", json={"name": "   "})
    assert response.status_code == 422


async def test_create_bot_non_owner_returns_403(client: httpx.AsyncClient) -> None:
    from api.security import get_current_user
    from db.models import User

    client_user = User(
        id=uuid.uuid4(),
        email="not-owner@example.com",
        password_hash="unused",
        role="client",
        is_active=True,
        created_at=datetime.now(),
    )
    app.dependency_overrides[get_current_user] = lambda: client_user

    response = await client.post("/bots", json={"name": "Чужой бот"})
    assert response.status_code == 403


async def test_get_bot_stats_counts_messages_and_contacts(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        contact = await match_or_create_contact(session, bot_id, wa_id="996700000030", lid=None)
        await insert_incoming(
            session, bot_id, contact.id, "привет", "wamsg-stats-1", datetime.now(UTC)
        )
        await insert_outgoing(session, bot_id, contact.id, "ответ")
        await session.commit()

    response = await client.get(f"/bots/{bot_id}/stats")

    assert response.status_code == 200
    body = response.json()
    assert body == {"messages_count": 2, "contacts_count": 1}


async def test_get_bot_stats_is_zero_for_a_fresh_bot(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.get(f"/bots/{bot_id}/stats")
    assert response.status_code == 200
    assert response.json() == {"messages_count": 0, "contacts_count": 0}
