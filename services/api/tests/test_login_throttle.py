"""Лимит попыток входа (POST /auth/login) — модуль login_throttle.

FakeRedis, без Docker. Эндпоинтовые сценарии (429 на роуте, сброс после
успешного входа) — в test_auth.py, там уже есть Postgres-фикстуры.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from api import login_throttle
from api.login_throttle import (
    LOGIN_WINDOW_SECONDS,
    MAX_ATTEMPTS_PER_EMAIL,
    MAX_ATTEMPTS_PER_IP,
    clear_email_attempts,
    client_ip,
    register_login_attempt,
)
from fakeredis.aioredis import FakeRedis
from starlette.requests import Request


@pytest.fixture
async def redis() -> AsyncIterator[FakeRedis]:
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


async def _attempt(
    redis: FakeRedis, email: str = "a@example.com", ip: str | None = "1.1.1.1"
) -> int | None:
    return await register_login_attempt(redis, email=email, ip=ip)


async def test_allows_up_to_the_email_limit_then_blocks(redis: FakeRedis) -> None:
    for _ in range(MAX_ATTEMPTS_PER_EMAIL):
        assert await _attempt(redis) is None

    retry_after = await _attempt(redis)

    assert retry_after is not None
    assert 0 < retry_after <= LOGIN_WINDOW_SECONDS


async def test_other_email_is_not_affected_by_a_blocked_one(redis: FakeRedis) -> None:
    for _ in range(MAX_ATTEMPTS_PER_EMAIL + 1):
        await _attempt(redis, email="victim@example.com", ip=None)

    assert await _attempt(redis, email="other@example.com", ip=None) is None


async def test_email_is_normalized_so_case_and_spaces_share_one_counter(redis: FakeRedis) -> None:
    variants = ["Aigul@Mail.RU", " aigul@mail.ru", "AIGUL@MAIL.RU  ", "aigul@mail.ru"]
    for i in range(MAX_ATTEMPTS_PER_EMAIL):
        assert await _attempt(redis, email=variants[i % len(variants)], ip=None) is None

    assert await _attempt(redis, email="aigul@mail.ru", ip=None) is not None


async def test_ip_limit_blocks_guessing_across_many_emails(redis: FakeRedis) -> None:
    """Один IP перебирает разные учётки — по email ни одна не упирается в лимит,
    но IP-счётчик срабатывает."""
    for i in range(MAX_ATTEMPTS_PER_IP):
        assert await _attempt(redis, email=f"user{i}@example.com", ip="9.9.9.9") is None

    assert await _attempt(redis, email="fresh@example.com", ip="9.9.9.9") is not None
    assert await _attempt(redis, email="fresh@example.com", ip="8.8.8.8") is None


async def test_without_ip_only_the_email_limit_applies(redis: FakeRedis) -> None:
    for _ in range(MAX_ATTEMPTS_PER_EMAIL):
        assert await _attempt(redis, ip=None) is None

    assert await _attempt(redis, ip=None) is not None
    assert len(await redis.keys("*")) == 1  # только email-счётчик, IP-счётчика нет


async def test_every_counter_expires_after_the_window(redis: FakeRedis) -> None:
    """Ключ без TTL — вечная блокировка (INCR создал, EXPIRE не дошёл)."""
    await _attempt(redis)

    keys = await redis.keys("*")
    assert len(keys) == 2  # email + ip
    for key in keys:
        assert 0 < await redis.ttl(key) <= LOGIN_WINDOW_SECONDS


async def test_blocked_attempts_do_not_extend_the_window(redis: FakeRedis) -> None:
    """Окно фиксируется первой попыткой. Иначе тот, кто продолжает долбить
    заблокированную учётку, держал бы её закрытой бесконечно."""
    await _attempt(redis)
    keys = await redis.keys("*")
    for key in keys:
        await redis.expire(key, 100)

    for _ in range(MAX_ATTEMPTS_PER_EMAIL + 3):
        await _attempt(redis)

    for key in keys:
        assert await redis.ttl(key) <= 100


async def test_keys_do_not_contain_the_raw_email(redis: FakeRedis) -> None:
    await _attempt(redis, email="secret.person@example.com")

    assert not any("secret" in key or "@" in key for key in await redis.keys("*"))


async def test_clear_email_attempts_resets_the_email_counter_but_not_the_ip_counter(
    redis: FakeRedis,
) -> None:
    for _ in range(MAX_ATTEMPTS_PER_EMAIL + 1):
        await _attempt(redis, email="a@example.com", ip="1.1.1.1")  # a: 6, ip: 6
    await _attempt(redis, email="b@example.com", ip="1.1.1.1")  # b: 1, ip: 7
    assert len(await redis.keys("*")) == 3

    await clear_email_attempts(redis, email="a@example.com")

    # Остались счётчик b и IP-счётчик: успешный вход в СВОЮ учётку не должен
    # обнулять бюджет перебора чужих — иначе лимит обходится чередованием
    # (19 догадок + один легальный вход).
    remaining = [int(await redis.get(key) or 0) for key in await redis.keys("*")]
    assert sorted(remaining) == [1, MAX_ATTEMPTS_PER_EMAIL + 2]
    assert await _attempt(redis, email="a@example.com", ip="2.2.2.2") is None


async def test_clear_email_attempts_is_harmless_when_nothing_was_counted(redis: FakeRedis) -> None:
    await clear_email_attempts(redis, email="never-seen@example.com")


class _BrokenRedis:
    def pipeline(self, transaction: bool = True) -> _BrokenRedis:
        raise ConnectionError("redis is down")

    async def delete(self, *keys: str) -> int:
        raise ConnectionError("redis is down")


async def test_fails_open_when_redis_is_down() -> None:
    """Лимитер не должен превращать сбой Redis в недоступность кабинета."""
    assert await register_login_attempt(_BrokenRedis(), email="a@example.com", ip="1.1.1.1") is None  # type: ignore[arg-type]
    await clear_email_attempts(_BrokenRedis(), email="a@example.com")  # type: ignore[arg-type]


class _HangingPipeline:
    def incr(self, *_: object) -> None: ...
    def expire(self, *_: object, **__: object) -> None: ...
    def ttl(self, *_: object) -> None: ...

    async def execute(self) -> list[int]:
        await asyncio.sleep(30)
        return []

    async def __aenter__(self) -> _HangingPipeline:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _HangingRedis:
    def pipeline(self, transaction: bool = True) -> _HangingPipeline:
        return _HangingPipeline()


async def test_fails_open_when_redis_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Любой внешний вызов — с таймаутом (CLAUDE.md): зависший Redis не должен
    вешать логин."""
    monkeypatch.setattr(login_throttle, "REDIS_TIMEOUT_SECONDS", 0.05)

    result = await asyncio.wait_for(
        register_login_attempt(_HangingRedis(), email="a@example.com", ip="1.1.1.1"),  # type: ignore[arg-type]
        timeout=2,
    )

    assert result is None


def _request(
    headers: dict[str, str], client: tuple[str, int] | None = ("10.0.0.5", 1234)
) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": client,
        }
    )


def test_client_ip_prefers_the_first_forwarded_for_entry() -> None:
    assert client_ip(_request({"X-Forwarded-For": "203.0.113.7, 10.0.0.2"})) == "203.0.113.7"


def test_client_ip_falls_back_to_the_socket_peer() -> None:
    assert client_ip(_request({})) == "10.0.0.5"


def test_client_ip_ignores_garbage_in_forwarded_for() -> None:
    """Значение идёт в ключ Redis — мусор/очень длинная строка не должны туда попасть."""
    assert client_ip(_request({"X-Forwarded-For": "not-an-ip"})) == "10.0.0.5"
    assert client_ip(_request({"X-Forwarded-For": "x" * 5000})) == "10.0.0.5"


def test_client_ip_accepts_ipv6() -> None:
    assert client_ip(_request({"X-Forwarded-For": "2001:db8::1"})) == "2001:db8::1"


def test_client_ip_is_none_when_nothing_is_known() -> None:
    assert client_ip(_request({}, client=None)) is None
