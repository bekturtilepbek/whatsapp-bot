"""GET/POST /users, POST/DELETE .../bot-access, PATCH /users/{id} —
только суперадмин управляет аккаунтами (FEATURES.md 6.18 + ролевой
пересмотр 2026-09-22: Admin намеренно НЕ получает доступ к этому
роутеру — единственное, что отличает его от Superadmin).
"""

from __future__ import annotations

import uuid

from db.bot_access import grant_bot_access, list_bot_ids_for_user, revoke_bot_access
from db.bots import get_bot
from db.models import User
from db.users import (
    create_user,
    get_user,
    get_user_by_email,
    list_users,
    set_user_active,
    set_user_password,
    set_user_role,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import SessionDep
from ..schemas.users import UserBriefOut, UserCreate, UserPatch, UserWithAccessOut
from ..security import PlatformWide, UserManager, hash_password

router = APIRouter(prefix="/users", tags=["users"])


class _BotAccessIn(BaseModel):
    bot_id: uuid.UUID


async def _to_out(session: SessionDep, user: User) -> UserWithAccessOut:
    bot_ids = await list_bot_ids_for_user(session, user.id)
    return UserWithAccessOut(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        bot_ids=bot_ids,
    )


@router.get("", response_model=list[UserWithAccessOut])
async def list_users_route(session: SessionDep, _owner: UserManager) -> list[UserWithAccessOut]:
    users = await list_users(session)
    return [await _to_out(session, u) for u in users]


@router.get("/prompters", response_model=list[UserBriefOut])
async def list_prompters_route(session: SessionDep, _admin: PlatformWide) -> list[UserBriefOut]:
    """Выбор ответственного при создании/настройке бота (FEATURES.md 6.18) —
    осознанно PlatformWide, не UserManager: Admin тоже создаёт ботов и
    должен видеть, кого назначить, но не весь /users."""
    users = await list_users(session)
    return [UserBriefOut(id=u.id, email=u.email) for u in users if u.role == "prompter"]


@router.post("", response_model=UserWithAccessOut, status_code=201)
async def create_user_route(
    body: UserCreate, session: SessionDep, _owner: UserManager
) -> UserWithAccessOut:
    if await get_user_by_email(session, body.email) is not None:
        raise HTTPException(status_code=409, detail="email already registered")
    # Проверяем существование ВСЕХ bot_id до создания пользователя — иначе
    # неизвестный bot_id на полпути даст FK IntegrityError (500) вместо 404,
    # а пользователь останется частично созданным. Зеркалит grant_bot_access_route.
    for bot_id in body.bot_ids:
        if await get_bot(session, bot_id) is None:
            raise HTTPException(status_code=404, detail="bot not found")
    user = await create_user(
        session, email=body.email, password_hash=hash_password(body.password), role=body.role
    )
    for bot_id in body.bot_ids:
        await grant_bot_access(session, user.id, bot_id)
    await session.commit()
    return await _to_out(session, user)


@router.post("/{user_id}/bot-access", status_code=204)
async def grant_bot_access_route(
    user_id: uuid.UUID, body: _BotAccessIn, session: SessionDep, _owner: UserManager
) -> None:
    if await get_user(session, user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")
    if await get_bot(session, body.bot_id) is None:
        raise HTTPException(status_code=404, detail="bot not found")
    await grant_bot_access(session, user_id, body.bot_id)
    await session.commit()


@router.delete("/{user_id}/bot-access/{bot_id}", status_code=204)
async def revoke_bot_access_route(
    user_id: uuid.UUID, bot_id: uuid.UUID, session: SessionDep, _owner: UserManager
) -> None:
    await revoke_bot_access(session, user_id, bot_id)
    await session.commit()


@router.patch("/{user_id}", response_model=UserWithAccessOut)
async def patch_user_route(
    user_id: uuid.UUID, body: UserPatch, session: SessionDep, _owner: UserManager
) -> UserWithAccessOut:
    if body.is_active is not None:
        updated = await set_user_active(session, user_id, body.is_active)
        if updated is None:
            raise HTTPException(status_code=404, detail="user not found")
    if body.password is not None:
        updated = await set_user_password(session, user_id, hash_password(body.password))
        if updated is None:
            raise HTTPException(status_code=404, detail="user not found")
    if body.role is not None:
        updated = await set_user_role(session, user_id, body.role)
        if updated is None:
            raise HTTPException(status_code=404, detail="user not found")
    user = await get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await session.commit()
    return await _to_out(session, user)
