"""Общий override авторизации для существующих тестов (FEATURES.md 6.18,
ролевой пересмотр 2026-09-22).

require_bot_access/require_platform_wide/require_user_manager/
require_full_bot_access требуют CurrentUser — тесты роутов, написанные до
этого суб-проекта, не отправляют Authorization и не должны его знать:
подменяем саму FastAPI-зависимость get_current_user на фиксированного
пользователя нужной роли, тот же паттерн, что уже применяется к
get_session/get_storage/get_redis в этих файлах. superadmin/admin
проходят require_bot_access для ЛЮБОГО bot_id без обращения к БД
(short-circuit в security.py) — эти тесты не нуждаются в реальной строке
users/bot_access.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from api.main import app
from api.security import get_current_user
from db.models import User


def _fake_user(email: str, role: str) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        password_hash="unused",
        role=role,
        is_active=True,
        created_at=datetime.now(),
    )


FAKE_OWNER_USER = _fake_user("test-owner@example.com", "superadmin")
FAKE_ADMIN_USER = _fake_user("test-admin@example.com", "admin")
FAKE_PROMPTER_USER = _fake_user("test-prompter@example.com", "prompter")
FAKE_NON_OWNER_USER = _fake_user("test-non-owner@example.com", "client")
FAKE_CLIENT_USER = FAKE_NON_OWNER_USER  # алиас — читается точнее в новых тестах


def override_owner_auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: FAKE_OWNER_USER


def override_admin_auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: FAKE_ADMIN_USER


def override_prompter_auth() -> None:
    app.dependency_overrides[get_current_user] = lambda: FAKE_PROMPTER_USER


def override_non_owner_auth() -> None:
    """Подменяет текущего пользователя на активного client — для тестов,
    проверяющих 403 на PlatformWide/UserManager-роутах и на роутах,
    урезанных для client (FullBotAccess)."""
    app.dependency_overrides[get_current_user] = lambda: FAKE_NON_OWNER_USER


override_client_auth = override_non_owner_auth  # алиас — читается точнее в новых тестах
