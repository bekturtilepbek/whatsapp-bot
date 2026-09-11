"""schemas.auth.PasswordStr — байтовый (не символьный) лимит bcrypt, 72
байта UTF-8 (FEATURES.md 6.18, закрытие техдолга: bcrypt>=4.2 бросает
ValueError на пароль длиннее 72 БАЙТ, а Pydantic Field(max_length=72)
считал СИМВОЛЫ — 72-символьный кириллический пароль (144 байта) всё
ещё падал в 500, обнаружено ре-ревью финального ревью 6.18. Без Docker,
чистые юнит-тесты."""

from __future__ import annotations

import pytest
from api.schemas.auth import LoginRequest
from api.schemas.users import UserCreate, UserPatch
from pydantic import ValidationError


def test_ascii_password_at_limit_passes() -> None:
    LoginRequest(email="a@example.com", password="x" * 72)


def test_ascii_password_over_limit_raises() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com", password="x" * 73)


def test_cyrillic_password_72_chars_144_bytes_raises() -> None:
    """Ровно тот сценарий, который был найден незакрытым: 72 символа,
    но 144 байта в UTF-8 — старый Field(max_length=72) это пропускал."""
    password = "а" * 72
    assert len(password) == 72
    assert len(password.encode("utf-8")) == 144
    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com", password=password)


def test_cyrillic_password_at_byte_limit_passes() -> None:
    """36 кириллических символов = 72 байта UTF-8 (каждый по 2 байта) — ровно на границе."""
    password = "а" * 36
    assert len(password.encode("utf-8")) == 72
    LoginRequest(email="a@example.com", password=password)


def test_short_password_passes() -> None:
    LoginRequest(email="a@example.com", password="correct horse")


def test_user_patch_password_none_bypasses_validator() -> None:
    """PasswordStr | None — None должен спокойно проходить мимо
    байтового валидатора (нет пароля для проверки), не падать."""
    patch = UserPatch(password=None)
    assert patch.password is None


def test_user_patch_password_over_limit_raises() -> None:
    with pytest.raises(ValidationError):
        UserPatch(password="а" * 72)


def test_user_create_cyrillic_password_over_limit_raises() -> None:
    with pytest.raises(ValidationError):
        UserCreate(email="a@example.com", password="а" * 72, bot_ids=[])
