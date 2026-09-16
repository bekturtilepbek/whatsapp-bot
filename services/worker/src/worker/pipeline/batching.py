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


def _batch_media_key(kind: str, bot_id: str, chat_id: str) -> str:
    return f"batch:{kind}:{bot_id}:{chat_id}"


def _ttl(batch_timeout_seconds: float) -> int:
    return int(batch_timeout_seconds) + LEADER_CLAIM_TTL_BUFFER_SECONDS


async def register_arrival(
    redis: Redis, bot_id: str, chat_id: str, batch_timeout_seconds: float
) -> bool:
    """Продлевает дедлайн батча этого чата; возвращает True, если вызывающий
    стал лидером окна (первым сообщением — только он должен ждать тишины и
    вести чат дальше по пайплайну).
    """
    ttl = _ttl(batch_timeout_seconds)
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


async def _register_batch_media_arrival(
    redis: Redis, kind: str, bot_id: str, chat_id: str, wa_msg_id: str, batch_timeout_seconds: float
) -> None:
    """Копит `wa_msg_id` медиа заданного вида (`kind` — например, "images"
    или "audio"), пришедших в текущее окно батчинга (лидер и фолловеры —
    любое событие этого вида, не только лидерское) — лидер после
    `wait_for_quiet` заберёт список через `_pop_batch_media` и объединит всё
    в один вызов (vision — FEATURES.md 2.1 ревизия, транскрипция — 2.2),
    вместо того чтобы обрабатывать только своё собственное."""
    key = _batch_media_key(kind, bot_id, chat_id)
    # redis-py стаб не разрешает overload rpush/lrange без generic-параметра
    # Redis[str] — та же природа, что и у celery-декоратора без py.typed
    # (см. scheduling/celery_app.py).
    await redis.rpush(key, wa_msg_id)  # type: ignore[misc]
    await redis.expire(key, _ttl(batch_timeout_seconds))


async def _pop_batch_media(redis: Redis, kind: str, bot_id: str, chat_id: str) -> list[str]:
    """Забирает и чистит список `wa_msg_id` медиа заданного вида текущего
    батча — одноразово, вызывается лидером ровно один раз за ход."""
    key = _batch_media_key(kind, bot_id, chat_id)
    raw_ids = await redis.lrange(key, 0, -1)  # type: ignore[misc]
    await redis.delete(key)
    return [raw_id.decode() if isinstance(raw_id, bytes) else raw_id for raw_id in raw_ids]


async def register_image_arrival(
    redis: Redis, bot_id: str, chat_id: str, wa_msg_id: str, batch_timeout_seconds: float
) -> None:
    await _register_batch_media_arrival(
        redis, "images", bot_id, chat_id, wa_msg_id, batch_timeout_seconds
    )


async def pop_batch_images(redis: Redis, bot_id: str, chat_id: str) -> list[str]:
    return await _pop_batch_media(redis, "images", bot_id, chat_id)


async def register_audio_arrival(
    redis: Redis, bot_id: str, chat_id: str, wa_msg_id: str, batch_timeout_seconds: float
) -> None:
    await _register_batch_media_arrival(
        redis, "audio", bot_id, chat_id, wa_msg_id, batch_timeout_seconds
    )


async def pop_batch_audio(redis: Redis, bot_id: str, chat_id: str) -> list[str]:
    return await _pop_batch_media(redis, "audio", bot_id, chat_id)
