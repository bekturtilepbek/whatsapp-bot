"""Pydantic v2 схемы управления пользователями кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .auth import PasswordStr, UserOut

# superadmin НЕ входит — назначается только bootstrap-скриптом
# (main.py::_bootstrap_platform_owner), не через API/UI.
AssignableRole = Literal["admin", "prompter", "client"]


class UserWithAccessOut(UserOut):
    bot_ids: list[UUID]


class UserCreate(BaseModel):
    email: str
    password: PasswordStr
    role: AssignableRole = "client"
    bot_ids: list[UUID] = []


class UserPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные."""

    is_active: bool | None = None
    password: PasswordStr | None = None
    role: AssignableRole | None = None
