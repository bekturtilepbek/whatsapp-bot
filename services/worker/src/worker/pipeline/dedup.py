"""Атомарная дедупликация. Грабли прошлой версии: проверка+пометка ДО любого
await, одной атомарной командой — иначе гонка даёт пятикратную отправку.
"""

from __future__ import annotations

from redis.asyncio import Redis

DEDUP_TTL_SECONDS = 86400


def _dedup_key(bot_id: str, wa_msg_id: str) -> str:
    return f"wa:seen:{bot_id}:{wa_msg_id}"


async def is_duplicate(redis: Redis, bot_id: str, wa_msg_id: str) -> bool:
    """True, если это сообщение уже видели (SET NX не сработал)."""
    reserved = await redis.set(
        _dedup_key(bot_id, wa_msg_id), "1", nx=True, ex=DEDUP_TTL_SECONDS
    )
    return not reserved
