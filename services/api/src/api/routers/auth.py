"""POST /auth/login, GET /auth/me (FEATURES.md 6.18)."""

from __future__ import annotations

from db.users import get_user_by_email
from fastapi import APIRouter, HTTPException

from ..db import SessionDep
from ..schemas.auth import LoginRequest, LoginResponse, UserOut
from ..security import CurrentUser, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, session: SessionDep) -> LoginResponse:
    user = await get_user_by_email(session, body.email)
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        # Одно и то же сообщение на "нет email" и "неверный пароль" —
        # не раскрываем существование аккаунта.
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    token = create_access_token(user.id, user.token_version)
    return LoginResponse(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
