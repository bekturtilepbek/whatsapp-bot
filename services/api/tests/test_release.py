"""POST /bots/{id}/chats/{chatId}/release — ручной возврат чата боту.

Fakeredis — не нужен ни testcontainers, ни реальный Redis.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from api.db import get_session
from api.main import app
from api.redis_client import get_redis
from core.redis_keys import handoff_key
from fakeredis.aioredis import FakeRedis

from tests.auth_helpers import override_owner_auth

BOT_ID = uuid.uuid4()
CHAT_ID = "996700000000@s.whatsapp.net"


async def _unused_session() -> AsyncIterator[None]:
    """require_bot_access объявляет session: SessionDep как параметр —
    FastAPI резолвит его ДО тела функции, даже если владелец платформы
    возвращается раньше (short-circuit) и session ни разу не используется.
    Без реальной БД в этом файле (только fakeredis) достаточно заглушки,
    которая никогда не обратится к DATABASE_URL."""
    yield None


@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, FakeRedis]]:
    override_owner_auth()
    app.dependency_overrides[get_session] = _unused_session
    redis = FakeRedis(decode_responses=True)
    app.dependency_overrides[get_redis] = lambda: redis
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, redis
    app.dependency_overrides.clear()
    await redis.aclose()


async def test_release_deletes_active_handoff_key(
    client: tuple[httpx.AsyncClient, FakeRedis],
) -> None:
    c, redis = client
    await redis.set(handoff_key(str(BOT_ID), CHAT_ID), "1", ex=720)

    response = await c.post(f"/bots/{BOT_ID}/chats/{CHAT_ID}/release")

    assert response.status_code == 200
    assert not await redis.exists(handoff_key(str(BOT_ID), CHAT_ID))


async def test_release_on_no_active_handoff_is_a_noop(
    client: tuple[httpx.AsyncClient, FakeRedis],
) -> None:
    c, _redis = client
    response = await c.post(f"/bots/{BOT_ID}/chats/{CHAT_ID}/release")
    assert response.status_code == 200  # не падает, даже если ключа не было
