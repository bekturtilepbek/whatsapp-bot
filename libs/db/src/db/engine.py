"""Фабрика async engine/session для подключения к Postgres."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def to_asyncpg_url(url: str) -> str:
    """DATABASE_URL пишем в обычной postgres:// форме — тут переводим под asyncpg-драйвер."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# "Любой внешний вызов — с таймаутом" (CLAUDE.md) — без него зависшее TCP-
# соединение (сетевой блип без RST, зависший запрос под блокировкой) висит
# на await НАВСЕГДА. Для worker это напрямую держит лок диалога открытым
# бессрочно (см. pipeline/lock.py::keep_alive — renew продлевает TTL, пока
# код внутри реально работает, и не отличает "долгий LLM/tool loop" от
# "застрявший await" — security review, 2026-09-28). asyncpg's command_timeout
# — таймаут на КАЖДЫЙ запрос по соединению, не агрегат на сессию: реальные
# запросы этого проекта (история, инкремент/вставка сообщений) — миллисекунды,
# 30с — большой запас, никогда не задевает легитимную нагрузку.
_COMMAND_TIMEOUT_SECONDS = 30


def make_engine(database_url: str | None = None) -> AsyncEngine:
    url = to_asyncpg_url(database_url or os.environ["DATABASE_URL"])
    return create_async_engine(
        url,
        pool_pre_ping=True,
        connect_args={"command_timeout": _COMMAND_TIMEOUT_SECONDS},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
