"""AsyncSession per-request dependency.

Engine создаётся лениво (не на импорте модуля) — иначе импорт api.main
в тестах требовал бы настоящий DATABASE_URL ещё до того, как тест успел
подменить get_session на testcontainers-версию через dependency_overrides.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from db.engine import make_engine, make_session_factory
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with _get_session_factory()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
