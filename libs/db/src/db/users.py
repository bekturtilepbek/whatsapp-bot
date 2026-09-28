"""Пользователи кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


def normalize_email(email: str) -> str:
    """Email хранится и ищется в одном виде — без краевых пробелов, в нижнем
    регистре. Раньше сравнение было строгим: заведённый как "Aigul@Mail.RU"
    не мог войти, введя "aigul@mail.ru", а "Case@x" и "case@x" становились
    двумя разными пользователями (2026-09-28)."""
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    # lower(trim(...)) и на стороне БД — строки, созданные до нормализации,
    # тоже находятся.
    stmt = select(User).where(func.lower(func.trim(User.email)) == normalize_email(email))
    result = await session.execute(stmt)
    return result.scalars().first()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    role: str = "client",
) -> User:
    user = User(email=normalize_email(email), password_hash=password_hash, role=role)
    session.add(user)
    await session.flush()
    return user


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars().all())


async def set_user_active(
    session: AsyncSession, user_id: uuid.UUID, is_active: bool
) -> User | None:
    user = await get_user(session, user_id)
    if user is None:
        return None
    user.is_active = is_active
    await session.flush()
    return user


async def set_user_password(
    session: AsyncSession, user_id: uuid.UUID, password_hash: str
) -> User | None:
    user = await get_user(session, user_id)
    if user is None:
        return None
    user.password_hash = password_hash
    # Отзываем все ранее выданные сессии (JWT с прежним "tv") — иначе после
    # смены утёкшего пароля злоумышленник оставался бы в кабинете до 30 дней.
    user.token_version += 1
    await session.flush()
    return user


async def set_user_role(session: AsyncSession, user_id: uuid.UUID, role: str) -> User | None:
    """superadmin сюда не приходит — схема (UserPatch) ограничивает role
    типом Literal["admin", "prompter", "client"], superadmin назначается
    только bootstrap-скриптом (main.py)."""
    user = await get_user(session, user_id)
    if user is None:
        return None
    user.role = role
    await session.flush()
    return user
