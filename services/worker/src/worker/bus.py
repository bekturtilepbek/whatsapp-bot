"""Redis Streams: подключение, consumer group, чтение/публикация событий.

Событие лежит одним JSON-полем "payload" в записи стрима — тот же формат,
что пишет gateway (services/gateway/src/bus/publish.ts).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis

IN_STREAM = "wa:in"
OUT_STREAM = "wa:out"


def make_redis() -> Redis:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    # socket_keepalive снижает риск, но не гарантирует: тихо потерянное сетью
    # (напр. Docker Desktop/WSL2 NAT) TCP-соединение может всё равно оставить
    # XREADGROUP BLOCK висеть без ответа. socket_timeout — вторая линия
    # защиты: клиент сам обрывает такой read и позволяет вызывающему коду
    # заметить и переподключиться, вместо вечного зависания консюмера.
    return Redis.from_url(
        url, decode_responses=True, socket_keepalive=True, socket_timeout=15
    )


async def ensure_group(redis: Redis, stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(stream, group, id="$", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


@dataclass(frozen=True)
class StreamEntry:
    entry_id: str
    # None — записи не распарсить (нет поля "payload" или битый JSON). Такую
    # запись всё равно нужно ACK'нуть вызывающим кодом, иначе она зависнет
    # в pending list навсегда.
    payload: dict[str, Any] | None


async def read_group(
    redis: Redis,
    stream: str,
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 5000,
) -> AsyncIterator[StreamEntry]:
    """Один проход XREADGROUP; отдаёт записи как есть. Не ACK'ает сама."""
    # decode_responses=True в make_redis() -> ключи/значения полей всегда str;
    # библиотечный тип ответа шире (bytes-вариант), сужаем явным cast.
    reply = cast(
        "list[tuple[str, list[tuple[str, dict[str, str]]]]] | None",
        await redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        ),
    )
    if not reply:
        return
    for _stream_name, entries in reply:
        for entry_id, fields in entries:
            raw = fields.get("payload")
            payload: dict[str, Any] | None
            if raw is None:
                payload = None
            else:
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = None
            yield StreamEntry(entry_id=entry_id, payload=payload)


async def publish(redis: Redis, stream: str, event: dict[str, Any]) -> None:
    await redis.xadd(stream, {"payload": json.dumps(event, ensure_ascii=False)})
