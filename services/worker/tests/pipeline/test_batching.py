"""Debounce-батчинг: лидерство, продление дедлайна, ожидание тишины."""

from __future__ import annotations

import asyncio
import time

from fakeredis.aioredis import FakeRedis
from worker.pipeline.batching import (
    pop_batch_images,
    register_arrival,
    register_image_arrival,
    wait_for_quiet,
)

TIMEOUT = 0.15  # секунды — короткое окно, но с запасом от дребезга шедулера ОС


async def test_first_arrival_becomes_leader_second_does_not() -> None:
    redis = FakeRedis()
    try:
        first = await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        second = await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        assert first is True
        assert second is False
    finally:
        await redis.aclose()


async def test_different_chats_each_get_their_own_leader() -> None:
    redis = FakeRedis()
    try:
        a = await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        b = await register_arrival(redis, "bot-1", "chat-2", TIMEOUT)
        assert a is True
        assert b is True
    finally:
        await redis.aclose()


async def test_wait_for_quiet_returns_only_after_silence_window() -> None:
    redis = FakeRedis()
    try:
        await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        start = time.monotonic()
        await wait_for_quiet(redis, "bot-1", "chat-1")
        elapsed = time.monotonic() - start
        assert elapsed >= TIMEOUT * 0.6  # не вернулся сразу
    finally:
        await redis.aclose()


async def test_new_arrival_during_wait_pushes_deadline_further() -> None:
    redis = FakeRedis()
    try:
        await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        start = time.monotonic()
        waiter = asyncio.create_task(wait_for_quiet(redis, "bot-1", "chat-1"))

        await asyncio.sleep(TIMEOUT * 0.5)
        # клиент дописал — "не лидер", таймер должен сброситься
        became_leader = await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        assert became_leader is False

        await waiter
        elapsed = time.monotonic() - start
        # без продления wait_for_quiet вернулся бы к ~TIMEOUT; с продлением —
        # не раньше TIMEOUT*0.5 (второе сообщение) + TIMEOUT
        assert elapsed >= TIMEOUT * 1.3
    finally:
        await redis.aclose()


async def test_leader_claim_is_released_after_quiet_window() -> None:
    redis = FakeRedis()
    try:
        await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        await wait_for_quiet(redis, "bot-1", "chat-1")

        # прошлый батч завершился — новое сообщение начинает новый цикл лидерства
        became_leader = await register_arrival(redis, "bot-1", "chat-1", TIMEOUT)
        assert became_leader is True
    finally:
        await redis.aclose()


async def test_pop_batch_images_returns_registered_ids_in_arrival_order() -> None:
    redis = FakeRedis()
    try:
        await register_image_arrival(redis, "bot-1", "chat-1", "wamsg-1", TIMEOUT)
        await register_image_arrival(redis, "bot-1", "chat-1", "wamsg-2", TIMEOUT)
        assert await pop_batch_images(redis, "bot-1", "chat-1") == ["wamsg-1", "wamsg-2"]
    finally:
        await redis.aclose()


async def test_pop_batch_images_clears_the_list() -> None:
    redis = FakeRedis()
    try:
        await register_image_arrival(redis, "bot-1", "chat-1", "wamsg-1", TIMEOUT)
        await pop_batch_images(redis, "bot-1", "chat-1")
        assert await pop_batch_images(redis, "bot-1", "chat-1") == []
    finally:
        await redis.aclose()


async def test_pop_batch_images_returns_empty_list_when_nothing_registered() -> None:
    redis = FakeRedis()
    try:
        assert await pop_batch_images(redis, "bot-1", "chat-1") == []
    finally:
        await redis.aclose()


async def test_batch_images_do_not_leak_across_chats_or_bots() -> None:
    redis = FakeRedis()
    try:
        await register_image_arrival(redis, "bot-1", "chat-1", "wamsg-1", TIMEOUT)
        await register_image_arrival(redis, "bot-1", "chat-2", "wamsg-2", TIMEOUT)
        await register_image_arrival(redis, "bot-2", "chat-1", "wamsg-3", TIMEOUT)

        assert await pop_batch_images(redis, "bot-1", "chat-1") == ["wamsg-1"]
        assert await pop_batch_images(redis, "bot-1", "chat-2") == ["wamsg-2"]
        assert await pop_batch_images(redis, "bot-2", "chat-1") == ["wamsg-3"]
    finally:
        await redis.aclose()
