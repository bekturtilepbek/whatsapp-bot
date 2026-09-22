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


class UserBriefOut(BaseModel):
    """Узкий срез — для выбора ответственного (GET /users/prompters),
    доступного PlatformWide (Admin тоже), не только UserManager
    (superadmin). Никаких is_active/bot_ids/role — Admin не должен видеть
    больше, чем нужно для выбора одного prompter'а."""

    id: UUID
    email: str


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
