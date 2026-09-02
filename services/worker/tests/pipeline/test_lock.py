"""Лок диалога: TTL, взаимоисключение, реакк захват после release/expiry."""

from __future__ import annotations

import asyncio

from fakeredis.aioredis import FakeRedis
from worker.pipeline.lock import _lock_key, acquire, release


async def test_second_acquire_fails_while_held() -> None:
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        assert await acquire(redis, "bot-1", "chat-1") is False
    finally:
        await redis.aclose()


async def test_release_allows_reacquire() -> None:
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        await release(redis, "bot-1", "chat-1")
        assert await acquire(redis, "bot-1", "chat-1") is True
    finally:
        await redis.aclose()


async def test_ttl_expiry_allows_reacquire_without_release() -> None:
    """"Лок на диалог — только с TTL": падение процесса не должно вешать чат навсегда."""
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        await redis.pexpire(_lock_key("bot-1", "chat-1"), 50)  # укорачиваем для теста
        await asyncio.sleep(0.1)
        assert await acquire(redis, "bot-1", "chat-1") is True
    finally:
        await redis.aclose()


async def test_different_chats_do_not_block_each_other() -> None:
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        assert await acquire(redis, "bot-1", "chat-2") is True
    finally:
        await redis.aclose()
