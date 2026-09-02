"""Временный echo-режим: wa:in -> тот же текст в wa:out.

Заменяется реальным пайплайном в Блоке 2 STAGE1_CORE (дедуп, фильтры,
батчинг, LLM). Пока только доказывает, что контур gateway<->Redis<->worker
работает целиком.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from core.events import Event
from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis

from .bus import IN_STREAM, OUT_STREAM, ensure_group, publish, read_group

GROUP = "worker"

logger = structlog.get_logger("worker.echo")

_event_adapter: TypeAdapter[Event] = TypeAdapter(Event)


def _build_echo(payload: dict[str, Any]) -> dict[str, Any] | None:
    """None, если событие не подходит под эхо (не inbound.text, from_me, пусто)."""
    try:
        event = _event_adapter.validate_python(payload)
    except ValidationError:
        logger.warning("invalid event on wa:in, skipping", payload=payload)
        return None

    if event.type != "inbound.text" or event.from_me or not event.text:
        return None

    return {
        "type": "outbound.text",
        "bot_id": str(event.bot_id),
        "chat_id": event.chat_id,
        "text": event.text,
        "client_msg_id": str(uuid.uuid4()),
    }


async def run_echo_consumer(redis: Redis, consumer_name: str) -> None:
    """Бесконечный цикл: читает wa:in, эхо-отвечает в wa:out, ACK'ает всегда.

    Останавливается через отмену задачи (asyncio.CancelledError) — так его
    глушит main.py при shutdown.
    """
    await ensure_group(redis, IN_STREAM, GROUP)
    while True:
        async for entry in read_group(redis, IN_STREAM, GROUP, consumer_name):
            try:
                if entry.payload is not None:
                    echo = _build_echo(entry.payload)
                    if echo is not None:
                        await publish(redis, OUT_STREAM, echo)
            finally:
                await redis.xack(IN_STREAM, GROUP, entry.entry_id)
