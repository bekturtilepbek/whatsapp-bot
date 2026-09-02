"""Лок диалога: строго последовательная обработка одного chat_id (ARCHITECTURE
§3), разные чаты — параллельно. "Лок на диалог — только с TTL" (грабли
прошлой версии) — снятие руками есть, но никогда не единственная гарантия.
"""

from __future__ import annotations

from redis.asyncio import Redis

LOCK_TTL_SECONDS = 60


def _lock_key(bot_id: str, chat_id: str) -> str:
    return f"lock:{bot_id}:{chat_id}"


async def acquire(redis: Redis, bot_id: str, chat_id: str) -> bool:
    acquired = await redis.set(_lock_key(bot_id, chat_id), "1", nx=True, ex=LOCK_TTL_SECONDS)
    return bool(acquired)


async def release(redis: Redis, bot_id: str, chat_id: str) -> None:
    await redis.delete(_lock_key(bot_id, chat_id))
