"""Pydantic v2 схемы управления пользователями кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from .auth import UserOut


class UserWithAccessOut(UserOut):
    bot_ids: list[UUID]


class UserCreate(BaseModel):
    email: str
    # bcrypt (>=4.2) бросает ValueError на пароль длиннее 72 байт вместо
    # молчаливого обрезания — отсекаем на границе Pydantic чистым 422.
    password: str = Field(max_length=72)
    bot_ids: list[UUID] = []


class UserPatch(BaseModel):
    """Оба поля опциональны — трогаем только реально переданные."""

    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=72)
