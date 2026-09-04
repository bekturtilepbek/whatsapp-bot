"""Redis Streams: consumer-group чтение wa:in — специфично для worker
(единственный consumer этого стрима). make_redis/publish/IN_STREAM/OUT_STREAM
теперь в core.bus (общие для worker и celery) — реэкспортируются здесь,
чтобы существующие импорты в consumer.py не менялись.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from core.bus import IN_STREAM, OUT_STREAM, make_redis, publish  # noqa: F401
from redis.asyncio import Redis


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
