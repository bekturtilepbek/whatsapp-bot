"""Список активных handoff-чатов одного бота (5.3 — ручной возврат из кабинета).

SCAN, не KEYS — не блокирует Redis даже при большом числе ключей на узле
(десятки ботов × активных чатов). Отдельного индекса активных чатов нет —
их обычно единицы на бота, SCAN по узкому паттерну дешёвый.
"""

from __future__ import annotations

from core.redis_keys import handoff_pattern
from redis.asyncio import Redis


async def list_active_chat_ids(redis: Redis, bot_id: str) -> list[str]:
    prefix = f"handoff:{bot_id}:"
    pattern = handoff_pattern(bot_id)
    chat_ids: list[str] = []
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=100)
        chat_ids.extend(key[len(prefix) :] for key in keys)
        if cursor == 0:
            break
    return chat_ids
