"""Redis Streams: подключение и публикация — общее между services/worker
(шлёт ответы) и services/celery (шлёт follow-up). Чтение wa:in (consumer
group) остаётся в services/worker/bus.py — только он consumer этого стрима.
"""

from __future__ import annotations

import json
import os
from typing import Any

from redis.asyncio import Redis

IN_STREAM = "wa:in"
OUT_STREAM = "wa:out"


def make_redis() -> Redis:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    # socket_keepalive снижает риск, но не гарантирует: тихо потерянное сетью
    # (напр. Docker Desktop/WSL2 NAT) TCP-соединение может всё равно оставить
    # чтение висеть без ответа. socket_timeout — вторая линия защиты.
    return Redis.from_url(
        url, decode_responses=True, socket_keepalive=True, socket_timeout=15
    )


async def publish(redis: Redis, stream: str, event: dict[str, Any]) -> None:
    await redis.xadd(stream, {"payload": json.dumps(event, ensure_ascii=False)})
