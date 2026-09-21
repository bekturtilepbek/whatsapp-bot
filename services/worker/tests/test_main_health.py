"""_make_health_handler (worker/main.py) — FEATURES.md 8.8: /health должен
реально бить в Postgres/Redis, а не только отвечать на порту (иначе сбой
ПОСЛЕ старта — compose гарантирует здоровье зависимостей только на старте,
depends_on: service_healthy — никак не отражался бы в healthcheck)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

from aiohttp.test_utils import make_mocked_request
from worker.main import _make_health_handler


class _FakeConnection:
    async def execute(self, *args: Any, **kwargs: Any) -> None:
        pass


class _FakeEngine:
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    @asynccontextmanager
    async def connect(self) -> Any:
        if self._fail:
            raise ConnectionError("simulated blip")
        yield _FakeConnection()


async def test_health_ok_when_db_and_redis_reachable() -> None:
    handler = _make_health_handler(_FakeEngine(), AsyncMock())
    response = await handler(make_mocked_request("GET", "/health"))
    assert response.status == 200


async def test_health_degraded_when_db_unreachable() -> None:
    handler = _make_health_handler(_FakeEngine(fail=True), AsyncMock())
    response = await handler(make_mocked_request("GET", "/health"))
    assert response.status == 503


async def test_health_degraded_when_redis_unreachable() -> None:
    redis = AsyncMock()
    redis.ping.side_effect = ConnectionError("simulated blip")
    handler = _make_health_handler(_FakeEngine(), redis)
    response = await handler(make_mocked_request("GET", "/health"))
    assert response.status == 503
