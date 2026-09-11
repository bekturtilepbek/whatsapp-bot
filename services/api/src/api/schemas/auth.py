"""Pydantic v2 схемы логина (FEATURES.md 6.18)."""

from __future__ import annotations

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


class LoginRequest(BaseModel):
    email: str
    password: PasswordStr


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    is_platform_owner: bool
    is_active: bool


class LoginResponse(BaseModel):
    token: str
    user: UserOut
