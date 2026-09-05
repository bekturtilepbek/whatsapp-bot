"""Лок диалога: TTL, взаимоисключение, реакк захват после release/expiry."""

from __future__ import annotations

import asyncio

import pytest
from fakeredis.aioredis import FakeRedis
from worker.pipeline import lock as lock_module
from worker.pipeline.lock import _lock_key, acquire, release, renew


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


async def test_renew_extends_ttl_of_held_lock() -> None:
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        await redis.pexpire(_lock_key("bot-1", "chat-1"), 100)  # укорачиваем для теста
        await renew(redis, "bot-1", "chat-1")
        ttl_ms = await redis.pttl(_lock_key("bot-1", "chat-1"))
        assert ttl_ms > 1000  # вернулся к полному LOCK_TTL_SECONDS (60с), не 100мс
    finally:
        await redis.aclose()


async def test_renew_on_missing_key_is_noop_and_does_not_create_lock() -> None:
    redis = FakeRedis()
    try:
        await renew(redis, "bot-1", "chat-1")  # лока никогда не было — не должно упасть/создать
        assert await acquire(redis, "bot-1", "chat-1") is True  # чат свободен, не "фантомно" занят
    finally:
        await redis.aclose()


async def test_keep_alive_renews_lock_past_its_original_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Лок на диалог — только с TTL" не отменяется: keep_alive лишь продлевает
    тот же TTL, пока код внутри блока реально работает (ретраи LLM/цикл тулз,
    FEATURES.md 4.13, могут длиться дольше исходного окна)."""
    monkeypatch.setattr(lock_module, "LOCK_TTL_SECONDS", 1)
    monkeypatch.setattr(lock_module, "LOCK_RENEW_INTERVAL_SECONDS", 0.2)
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        async with lock_module.keep_alive(redis, "bot-1", "chat-1"):
            await asyncio.sleep(1.5)  # дольше исходного LOCK_TTL_SECONDS=1с
            # второй "клиент" по-прежнему не может забрать лок — он продлился
            assert await acquire(redis, "bot-1", "chat-1") is False
    finally:
        await redis.aclose()


async def test_keep_alive_stops_renewing_once_the_block_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lock_module, "LOCK_TTL_SECONDS", 1)
    monkeypatch.setattr(lock_module, "LOCK_RENEW_INTERVAL_SECONDS", 0.2)
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        async with lock_module.keep_alive(redis, "bot-1", "chat-1"):
            await asyncio.sleep(0.05)  # продление успело сработать хотя бы раз

        # никто больше не продлевает — последнее продление тоже должно истечь
        await asyncio.sleep(1.3)
        assert await acquire(redis, "bot-1", "chat-1") is True
    finally:
        await redis.aclose()


async def test_keep_alive_propagates_exception_and_still_stops_renewing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lock_module, "LOCK_TTL_SECONDS", 1)
    monkeypatch.setattr(lock_module, "LOCK_RENEW_INTERVAL_SECONDS", 0.2)
    redis = FakeRedis()
    try:
        assert await acquire(redis, "bot-1", "chat-1") is True
        with pytest.raises(RuntimeError, match="сбой пайплайна ответа"):
            async with lock_module.keep_alive(redis, "bot-1", "chat-1"):
                raise RuntimeError("сбой пайплайна ответа")

        await asyncio.sleep(1.3)
        assert await acquire(redis, "bot-1", "chat-1") is True
    finally:
        await redis.aclose()
