"""Pydantic v2 схемы логина (FEATURES.md 6.18)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    is_platform_owner: bool
    is_active: bool


class LoginResponse(BaseModel):
    token: str
    user: UserOut
