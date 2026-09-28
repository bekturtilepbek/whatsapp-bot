"""Пароли, JWT и FastAPI-зависимости авторизации (FEATURES.md 6.18).

JWT payload — только {sub: user_id, exp}, БЕЗ роли/доступа к ботам: то
проверяется свежо из БД на каждый запрос (require_bot_access/
require_full_bot_access/require_platform_wide/require_user_manager), чтобы
отзыв гранта, смена роли или деактивация пользователя срабатывали
немедленно, не дожидаясь протухания токена (30 дней).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from db.bot_access import has_bot_access
from db.models import User
from db.users import get_user
from fastapi import Depends, Header, HTTPException

from .db import SessionDep

JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = 30


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(days=JWT_TTL_DAYS),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Бросает jwt.InvalidTokenError (и подклассы — ExpiredSignatureError,
    InvalidSignatureError, DecodeError, ...) на любую проблему."""
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    return uuid.UUID(payload["sub"])


async def get_current_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Нужно войти в кабинет")
    token = authorization.removeprefix("Bearer ")
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Сессия истекла — войдите заново") from exc
    user = await get_user(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Нужно войти в кабинет")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

# superadmin/admin видят все боты без грантов и все платформенные разделы
# (кроме /users — там только superadmin, см. require_user_manager).
# prompter/client — только по гранту в bot_access; на уровне конкретного
# бота prompter имеет полный доступ (как superadmin/admin), а client —
# урезанный (см. require_full_bot_access).
PLATFORM_WIDE_ROLES = {"superadmin", "admin"}


async def require_bot_access(bot_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> User:
    """bot_id приходит из пути роута, в котором эта зависимость
    используется — FastAPI резолвит одноимённый параметр пути
    автоматически."""
    if user.role in PLATFORM_WIDE_ROLES:
        return user
    if not await has_bot_access(session, user.id, bot_id):
        raise HTTPException(status_code=403, detail="Нет доступа к этому боту")
    return user


BotAccessUser = Annotated[User, Depends(require_bot_access)]


async def require_full_bot_access(bot_id: uuid.UUID, user: BotAccessUser) -> User:
    """Доступ есть (require_bot_access уже проверил), но client урезан —
    без промптов/тулз/чёрного списка/настроек/QR (FEATURES.md 6.18
    ролевой пересмотр, 2026-09-22)."""
    if user.role == "client":
        raise HTTPException(status_code=403, detail="У роли «Клиент» нет доступа к этому разделу")
    return user


FullBotAccess = Annotated[User, Depends(require_full_bot_access)]


async def require_platform_wide(user: CurrentUser) -> User:
    if user.role not in PLATFORM_WIDE_ROLES:
        raise HTTPException(status_code=403, detail="Доступно только администраторам")
    return user


PlatformWide = Annotated[User, Depends(require_platform_wide)]


async def require_user_manager(user: CurrentUser) -> User:
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Доступно только суперадмину")
    return user


UserManager = Annotated[User, Depends(require_user_manager)]
