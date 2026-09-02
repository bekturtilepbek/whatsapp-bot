"""Ленивый Redis-клиент api (тот же паттерн, что db.py/gateway_client.py —
не создаётся на импорте модуля, иначе тесты не подменили бы его через
dependency_overrides).
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

_client: Redis | None = None


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(_redis_url(), decode_responses=True)
    return _client


RedisDep = Annotated[Redis, Depends(get_redis)]
