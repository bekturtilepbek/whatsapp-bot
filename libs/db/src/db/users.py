"""Пользователи кабинета (FEATURES.md 6.18)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    is_platform_owner: bool = False,
) -> User:
    user = User(email=email, password_hash=password_hash, is_platform_owner=is_platform_owner)
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
    await session.flush()
    return user
