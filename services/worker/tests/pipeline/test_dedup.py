"""Дедуп-гонка: SET NX атомарен, второй конкурентный вызов не проходит."""

from __future__ import annotations

import asyncio

from fakeredis.aioredis import FakeRedis
from worker.pipeline.dedup import is_duplicate


async def test_second_concurrent_call_with_same_wa_msg_id_is_duplicate() -> None:
    redis = FakeRedis()
    try:
        results = await asyncio.gather(
            is_duplicate(redis, "bot-1", "wamsg-1"),
            is_duplicate(redis, "bot-1", "wamsg-1"),
        )
        # Ровно один из двух увидел "новое" сообщение, второй — дубликат.
        assert sorted(results) == [False, True]
    finally:
        await redis.aclose()


async def test_different_wa_msg_ids_are_not_duplicates() -> None:
    redis = FakeRedis()
    try:
        first = await is_duplicate(redis, "bot-1", "wamsg-a")
        second = await is_duplicate(redis, "bot-1", "wamsg-b")
        assert first is False
        assert second is False
    finally:
        await redis.aclose()


async def test_same_wa_msg_id_different_bots_are_independent() -> None:
    redis = FakeRedis()
    try:
        first = await is_duplicate(redis, "bot-1", "wamsg-1")
        second = await is_duplicate(redis, "bot-2", "wamsg-1")
        assert first is False
        assert second is False
    finally:
        await redis.aclose()
