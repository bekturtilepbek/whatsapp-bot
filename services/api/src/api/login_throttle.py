"""Лимит попыток входа (POST /auth/login) — защита от перебора пароля.

Два счётчика в Redis: по нормализованному email и по IP клиента. Окно
фиксированное — открывается первой попыткой и не продлевается следующими,
иначе тот, кто продолжает долбить закрытую учётку, держал бы её закрытой
бесконечно. Считаются именно ПОПЫТКИ, а не неудачи, и счёт идёт ДО проверки
пароля: параллельные запросы получают разные номера (INCR атомарен) и не
проскакивают лимит все разом, а заблокированные запросы не тратят CPU на bcrypt.

Компромисс: счётчик по email глобальный, поэтому знающий email владельца может
держать его учётку закрытой, пока шлёт 5+ запросов за окно. Это дешевле, чем
оставить без ограничения распределённый перебор; виновника видно по IP-ключам и
закрывается файрволом сервера.

Сбой Redis лимитер пропускает (fail-open, с предупреждением в лог): Redis и так
обязателен всему остальному, /health его проверяет, а превращать его простой в
недоступность кабинета хуже, чем временно остаться без лимита.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress

import structlog
from db.users import normalize_email
from fastapi import Request
from redis.asyncio import Redis

logger = structlog.get_logger("api.login_throttle")

LOGIN_WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS_PER_EMAIL = 5
# Больше, чем по email: за одним IP может сидеть офис клиента, где несколько
# человек опечатываются, а перебор по многим учёткам с одного адреса всё равно
# упирается в этот потолок.
MAX_ATTEMPTS_PER_IP = 20
# "Любой внешний вызов — с таймаутом" (CLAUDE.md): зависший Redis не должен вешать вход.
REDIS_TIMEOUT_SECONDS = 2.0


def _email_key(email: str) -> str:
    # Хеш, а не сам email: ключ ограничен по длине и не светит адреса в Redis.
    digest = hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()
    return f"login:attempts:email:{digest}"


def _ip_key(ip: str) -> str:
    return f"login:attempts:ip:{ip}"


def _parse_ip(value: str) -> str | None:
    # Значение попадает в ключ Redis — пропускаем только настоящие адреса.
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """IP клиента: первое значение X-Forwarded-For (его выставляет Caddy и
    пробрасывает admin-web), иначе адрес сокета.

    Доверие к заголовку — осознанное: api не публичен (в проде слушает только
    127.0.0.1 и docker-сеть), до него дотягивается лишь admin-web. Подделка
    обошла бы только IP-счётчик, счётчик по email остаётся."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        parsed = _parse_ip(forwarded.split(",")[0])
        if parsed is not None:
            return parsed
    if request.client is not None:
        return _parse_ip(request.client.host)
    return None


async def register_login_attempt(redis: Redis, *, email: str, ip: str | None) -> int | None:
    """Учитывает попытку входа. Возвращает None, если пускаем, либо число секунд
    до конца окна, если лимит исчерпан."""
    targets = [(_email_key(email), MAX_ATTEMPTS_PER_EMAIL)]
    if ip is not None:
        targets.append((_ip_key(ip), MAX_ATTEMPTS_PER_IP))

    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            # transaction=True: INCR и EXPIRE NX выполняются атомарно — иначе сбой
            # между ними оставил бы счётчик без TTL, то есть вечную блокировку.
            async with redis.pipeline(transaction=True) as pipe:
                for key, _ in targets:
                    pipe.incr(key)
                    pipe.expire(key, LOGIN_WINDOW_SECONDS, nx=True)
                    pipe.ttl(key)
                results = await pipe.execute()
    except Exception:
        logger.warning("login_throttle_unavailable", exc_info=True)
        return None

    retry_after = 0
    for index, (_, limit) in enumerate(targets):
        count, _, ttl = results[index * 3 : index * 3 + 3]
        if count > limit:
            retry_after = max(retry_after, ttl if ttl > 0 else LOGIN_WINDOW_SECONDS)
    return retry_after or None


async def clear_email_attempts(redis: Redis, *, email: str) -> None:
    """Успешный вход обнуляет счётчик этой учётки. IP-счётчик не трогаем: иначе
    лимит обходился бы чередованием — 19 догадок и один легальный вход в свою
    учётку для сброса."""
    try:
        async with asyncio.timeout(REDIS_TIMEOUT_SECONDS):
            await redis.delete(_email_key(email))
    except Exception:
        logger.warning("login_throttle_clear_failed", exc_info=True)
