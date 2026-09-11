"""Pydantic v2 схемы логина (FEATURES.md 6.18)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str
    # bcrypt (>=4.2) бросает ValueError на пароль длиннее 72 байт вместо
    # молчаливого обрезания — отсекаем на границе Pydantic чистым 422.
    password: str = Field(max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    is_platform_owner: bool
    is_active: bool


class LoginResponse(BaseModel):
    token: str
    user: UserOut
