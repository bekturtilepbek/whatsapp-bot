"""Debounce-батчинг: "клиент дописывает — таймер сбрасывается" (FEATURES.md
1.3). Без Celery/таймеров в памяти между рестартами процесса — дедлайн живёт
в Redis (wall-clock, сравним между разными worker-репликами), продлевается
каждым новым сообщением чата; собственно ожидание тишины — короткая
(~batch_timeout_seconds) корутина внутри текущего процесса, а не что-то,
что обязано пережить рестарт (в отличие от Celery-грабли для follow-up).
Ограничение уровня Блока 2: если процесс с "лидером" упадёт посреди
ожидания — батч останется без ответа (ретраи — Волна 1).
"""

from __future__ import annotations

import asyncio
import time

from redis.asyncio import Redis

LEADER_CLAIM_TTL_BUFFER_SECONDS = 5


def _deadline_key(bot_id: str, chat_id: str) -> str:
    return f"batch:deadline:{bot_id}:{chat_id}"


def _leader_key(bot_id: str, chat_id: str) -> str:
    return f"batch:leader:{bot_id}:{chat_id}"


async def register_arrival(
    redis: Redis, bot_id: str, chat_id: str, batch_timeout_seconds: float
) -> bool:
    """Продлевает дедлайн батча этого чата; возвращает True, если вызывающий
    стал лидером окна (первым сообщением — только он должен ждать тишины и
    вести чат дальше по пайплайну).
    """
    ttl = int(batch_timeout_seconds) + LEADER_CLAIM_TTL_BUFFER_SECONDS
    deadline = time.time() + batch_timeout_seconds
    await redis.set(_deadline_key(bot_id, chat_id), repr(deadline), ex=ttl)

    became_leader = await redis.set(_leader_key(bot_id, chat_id), "1", nx=True, ex=ttl)
    if not became_leader:
        # Лидер уже есть — продлеваем его claim, чтобы TTL не истёк, пока он
        # ждёт: без этого при долгой серии сообщений (дедлайн всё время
        # отодвигается) claim-ключ истёк бы раньше и появился бы второй лидер.
        await redis.expire(_leader_key(bot_id, chat_id), ttl)
    return bool(became_leader)


async def wait_for_quiet(redis: Redis, bot_id: str, chat_id: str) -> None:
    """Только для лидера. Спит до дедлайна, перечитывая его на каждом
    пробуждении — если за это время дедлайн отодвинули (пришло ещё
    сообщение), досыпает разницу. Снимает claim лидера по завершении.
    """
    while True:
        raw = await redis.get(_deadline_key(bot_id, chat_id))
        deadline = float(raw) if raw is not None else time.time()
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        await asyncio.sleep(remaining)

    await redis.delete(_leader_key(bot_id, chat_id), _deadline_key(bot_id, chat_id))
