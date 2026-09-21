"""GET /health — FEATURES.md 8.8: должен реально бить в Postgres/Redis, не
только отвечать на порту (иначе сбой ПОСЛЕ старта — compose гарантирует
здоровье зависимостей только на старте, depends_on: service_healthy —
никак не отражался бы в healthcheck). Не требует Docker: сессия/Redis
подменены через dependency_overrides.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from api.db import get_session
from api.main import app
from api.redis_client import get_redis


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    yield
    app.dependency_overrides.clear()


async def test_health_ok_when_db_and_redis_reachable() -> None:
    session = AsyncMock()
    redis = AsyncMock()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: redis

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_degraded_when_db_unreachable() -> None:
    session = AsyncMock()
    session.execute.side_effect = ConnectionError("simulated blip")
    redis = AsyncMock()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: redis

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}


async def test_health_degraded_when_redis_unreachable() -> None:
    session = AsyncMock()
    redis = AsyncMock()
    redis.ping.side_effect = ConnectionError("simulated blip")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_redis] = lambda: redis

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded"}
