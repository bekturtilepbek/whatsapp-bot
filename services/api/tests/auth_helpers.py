"""Общий override авторизации для существующих тестов (FEATURES.md 6.18).

require_bot_access/require_platform_owner требуют CurrentUser — тесты
роутов, написанные до этого суб-проекта, не отправляют Authorization и не
должны его знать: подменяем саму FastAPI-зависимость get_current_user на
фиксированного владельца платформы (is_platform_owner=True), тот же
паттерн, что уже применяется к get_session/get_storage/get_redis в этих
файлах. Владелец проходит require_bot_access для ЛЮБОГО bot_id без
обращения к БД (short-circuit в security.py) — эти тесты не нуждаются в
реальной строке users/bot_access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from api.main import app
from api.security import get_current_user
from db.models import User

FAKE_OWNER_USER = User(
    id=uuid.uuid4(),
    email="test-owner@example.com",
    password_hash="unused",
    is_platform_owner=True,
    is_active=True,
    created_at=datetime.now(),
)

FAKE_NON_OWNER_USER = User(
    id=uuid.uuid4(),
    email="test-non-owner@example.com",
    password_hash="unused",
    is_platform_owner=False,
    is_active=True,
    created_at=datetime.now(),
)


def override_owner_auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: FAKE_OWNER_USER


def override_non_owner_auth() -> None:
    """Подменяет текущего пользователя на активного, но НЕ владельца
    платформы — для тестов, проверяющих 403 на PlatformOwner-роутах."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_NON_OWNER_USER
