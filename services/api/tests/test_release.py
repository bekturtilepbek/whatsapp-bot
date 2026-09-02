"""POST /bots/{id}/chats/{chatId}/release — ручной возврат чата боту.

Fakeredis — не нужен ни testcontainers, ни реальный Redis.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from api.main import app
from api.redis_client import get_redis
from core.redis_keys import handoff_key
from fakeredis.aioredis import FakeRedis

BOT_ID = uuid.uuid4()
CHAT_ID = "996700000000@s.whatsapp.net"


@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, FakeRedis]]:
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
