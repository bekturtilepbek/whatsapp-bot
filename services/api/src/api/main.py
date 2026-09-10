"""FastAPI: HTTP-ручки управления ботами (STAGE1_CORE Блок 3, п.2).

Слушает 0.0.0.0 внутри контейнера (стандартная докер-практика); публичная
доступность решается маппингом порта в compose — на проде на хост
пробрасывается только 127.0.0.1 (SSH-туннель), в dev — обычный маппинг.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from db.engine import make_engine, make_session_factory, session_scope
from db.users import get_user_by_email
from fastapi import FastAPI

from .routers import auth, bots, products
from .security import hash_password


async def _bootstrap_platform_owner() -> None:
    """PLATFORM_OWNER_EMAIL/PLATFORM_OWNER_PASSWORD заданы — создаёт
    владельца платформы при первом старте, если такого email ещё нет.
    Идемпотентно: не трогает уже существующий пароль на повторных стартах."""
    email = os.environ.get("PLATFORM_OWNER_EMAIL")
    password = os.environ.get("PLATFORM_OWNER_PASSWORD")
    if not email or not password:
        return
    engine = make_engine()
    try:
        async with session_scope(make_session_factory(engine)) as session:
            if await get_user_by_email(session, email) is not None:
                return
            from db.users import create_user

            await create_user(
                session, email=email, password_hash=hash_password(password), is_platform_owner=True
            )
            await session.commit()
    finally:
        await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _bootstrap_platform_owner()
    yield


app = FastAPI(title="platform-api", lifespan=lifespan)

# CORS убран (FEATURES.md 6.18): браузер больше не стучится в api напрямую —
# admin-web ходит через свой BFF-прокси (Task 6 этого суб-проекта), у которого
# общий origin с браузером, preflight не нужен.

app.include_router(auth.router)
app.include_router(bots.router)
app.include_router(products.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
