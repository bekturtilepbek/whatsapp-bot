"""Handoff: пока менеджер отвечает вручную с телефона, бот молчит на этот чат.

Различение "наш echo" / "ответ менеджера" — по совпадению wa_msg_id
пришедшего from_me-события с client_msg_id, который worker сам выдал при
отправке (gateway проставляет его как Baileys messageId, см. Блок 3 шаг 1).
"""

from __future__ import annotations

from core.redis_keys import handoff_key, wa_sent_key
from redis.asyncio import Redis

MANAGER_REPLY_PREFIX = "[Ответ менеджера] "


async def is_own_echo(redis: Redis, wa_msg_id: str) -> bool:
    """True — это отправлял сам бот (wa:sent:{wa_msg_id} ставит gateway при отправке)."""
    return bool(await redis.exists(wa_sent_key(wa_msg_id)))


async def is_active(redis: Redis, bot_id: str, chat_id: str) -> bool:
    return bool(await redis.exists(handoff_key(bot_id, chat_id)))


async def mark_manager_reply(redis: Redis, bot_id: str, chat_id: str, ttl_seconds: int) -> bool:
    """Каждое сообщение менеджера продлевает окно — SET EX без NX, не 'если нет'.

    Возвращает True, если это начало нового эпизода (ключа не было). SET ... GET
    отдаёт прежнее значение атомарно — проверка и пометка одной командой, без
    гонки между репликами воркера (FEATURES.md 5.7).
    """
    previous = await redis.set(handoff_key(bot_id, chat_id), "1", ex=ttl_seconds, get=True)
    return previous is None


async def release(redis: Redis, bot_id: str, chat_id: str) -> None:
    """Ручной возврат чата боту (API-ручка) — то же самое, что истечение TTL."""
    await redis.delete(handoff_key(bot_id, chat_id))
