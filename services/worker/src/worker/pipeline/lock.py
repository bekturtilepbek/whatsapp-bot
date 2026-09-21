"""Лок диалога: строго последовательная обработка одного chat_id (ARCHITECTURE
§3), разные чаты — параллельно. "Лок на диалог — только с TTL" (грабли
прошлой версии) — снятие руками есть, но никогда не единственная гарантия.

keep_alive() продлевает TTL в фоне, пока код внутри `async with` реально
работает — ретраи LLM (до ~183с на один вызов) и цикл тулз (FEATURES.md
4.13, до нескольких раундов) могут длиться дольше LOCK_TTL_SECONDS. Ничего
не знает о LLM/тулзах — просто держит лок живым для любой работы внутри
блока. Самоисцеление не отменяется: если воркер падает целиком, фоновая
задача продления падает вместе с процессом, и лок всё равно истечёт не
позже чем через LOCK_TTL_SECONDS после последнего продления.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import structlog
from redis.asyncio import Redis

logger = structlog.get_logger("worker.pipeline.lock")

LOCK_TTL_SECONDS = 60
# Треть от TTL — запас на джиттер планировщика, чтобы продление всегда
# успевало раньше истечения, а не впритык к нему.
LOCK_RENEW_INTERVAL_SECONDS = LOCK_TTL_SECONDS / 3


def _lock_key(bot_id: str, chat_id: str) -> str:
    return f"lock:{bot_id}:{chat_id}"


async def acquire(redis: Redis, bot_id: str, chat_id: str) -> bool:
    acquired = await redis.set(_lock_key(bot_id, chat_id), "1", nx=True, ex=LOCK_TTL_SECONDS)
    return bool(acquired)


async def release(redis: Redis, bot_id: str, chat_id: str) -> None:
    await redis.delete(_lock_key(bot_id, chat_id))


async def renew(redis: Redis, bot_id: str, chat_id: str) -> None:
    """Продлевает TTL уже удерживаемого лока (EXPIRE, не SET NX — не
    создаёт лок заново). На отсутствующий ключ — безопасный no-op:
    EXPIRE ничего не создаёт, если лок уже снят/истёк, renew его не
    воскрешает."""
    await redis.expire(_lock_key(bot_id, chat_id), LOCK_TTL_SECONDS)


async def _renew_periodically(redis: Redis, bot_id: str, chat_id: str) -> None:
    while True:
        await asyncio.sleep(LOCK_RENEW_INTERVAL_SECONDS)
        try:
            await renew(redis, bot_id, chat_id)
        except Exception:
            # Разовый сбой Redis не должен убивать цикл продления на весь
            # остаток работы под локом (LLM/tool loop могут идти минуты) —
            # без этого лок молча переставал бы продлеваться навсегда после
            # первой же временной ошибки, а ошибка всплыла бы только когда
            # основная работа под локом уже закончится (найдено 2026-09-21,
            # тот же класс бага, что и unhandledRejection в gateway).
            logger.warning(
                "lock renew failed, will retry next interval", bot_id=bot_id, chat_id=chat_id
            )


@contextlib.asynccontextmanager
async def keep_alive(redis: Redis, bot_id: str, chat_id: str) -> AsyncIterator[None]:
    """Держит лок продлённым на всё время выполнения тела `async with`.
    Вызывать только между успешным acquire() и release() — сам лок не
    трогает при выходе (ни при обычном завершении, ни при исключении),
    снятие лока остаётся за release()."""
    task = asyncio.create_task(_renew_periodically(redis, bot_id, chat_id))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
