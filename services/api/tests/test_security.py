"""Пароли (bcrypt) и JWT (PyJWT) — без Docker, чистые функции + токен-цикл."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from api.security import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_produces_different_hash_each_time() -> None:
    h1 = hash_password("correct horse")
    h2 = hash_password("correct horse")
    assert h1 != h2  # bcrypt salt меняется каждый раз


def test_verify_password_correct() -> None:
    h = hash_password("correct horse")
    assert verify_password("correct horse", h) is True


def test_verify_password_incorrect() -> None:
    h = hash_password("correct horse")
    assert verify_password("wrong password", h) is False


def test_create_then_decode_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_decode_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    token = create_access_token(uuid.uuid4())
    monkeypatch.setenv("JWT_SECRET", "different-secret")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_decode_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    expired_payload = {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(days=1)}
    token = jwt.encode(expired_payload, "test-secret", algorithm=JWT_ALGORITHM)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)
