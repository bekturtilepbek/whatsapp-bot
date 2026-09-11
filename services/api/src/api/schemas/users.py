"""Pydantic v2 схемы управления пользователями кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from .auth import PasswordStr, UserOut


class UserWithAccessOut(UserOut):
    bot_ids: list[UUID]


class UserCreate(BaseModel):
    email: str
    password: PasswordStr
    bot_ids: list[UUID] = []


class UserPatch(BaseModel):
    """Оба поля опциональны — трогаем только реально переданные."""

    is_active: bool | None = None
    password: PasswordStr | None = None
