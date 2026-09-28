"""Pydantic v2 схемы логина (FEATURES.md 6.18)."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict

# bcrypt (>=4.2) бросает ValueError на пароль длиннее 72 БАЙТ (UTF-8) вместо
# молчаливого обрезания — отсекаем на границе Pydantic чистым 422. Важно:
# лимит именно в БАЙТАХ, не в символах — Field(max_length=72) считал бы
# символы, и 72-символьный кириллический пароль (144 байта) всё равно
# уронил бы bcrypt (найдено на ре-ревью финального ревью 6.18: реальный
# сценарий для русскоязычного продукта, не гипотетический edge case).
MAX_PASSWORD_BYTES = 72


def _validate_password_byte_length(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes (UTF-8 encoded)")
    return password


PasswordStr = Annotated[str, AfterValidator(_validate_password_byte_length)]

# Не полная RFC-проверка (email-validator не в зависимостях) — отсекаем
# явный мусор: пусто, без "@", пустые части, пробелы внутри.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not _EMAIL_RE.match(normalized):
        raise ValueError("email must look like name@example.com")
    return normalized


# Только для создания пользователя: логин принимает любую строку (иначе
# старая учётка с нестандартным email не смогла бы войти) — нормализация
# регистра для логина делается в db.users.get_user_by_email.
EmailAddress = Annotated[str, AfterValidator(_validate_email)]


class LoginRequest(BaseModel):
    email: str
    password: PasswordStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    role: str
    is_active: bool


class LoginResponse(BaseModel):
    token: str
    user: UserOut
