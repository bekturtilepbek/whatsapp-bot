"""POST /auth/login, GET /auth/me (FEATURES.md 6.18)."""

from __future__ import annotations

from db.users import get_user_by_email
from fastapi import APIRouter, HTTPException, Request

from ..db import SessionDep
from ..login_throttle import clear_email_attempts, client_ip, register_login_attempt
from ..redis_client import RedisDep
from ..schemas.auth import LoginRequest, LoginResponse, UserOut
from ..security import CurrentUser, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, request: Request, session: SessionDep, redis: RedisDep
) -> LoginResponse:
    # Лимит — до обращения к БД и bcrypt: заблокированный запрос ничего не стоит,
    # а верный пароль во время блокировки тоже не проходит (иначе перебор
    # продолжался бы, просто с другим ответом на угаданный пароль).
    retry_after = await register_login_attempt(redis, email=body.email, ip=client_ip(request))
    if retry_after is not None:
        minutes = -(-retry_after // 60)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток входа. Попробуйте через {minutes} мин.",
            headers={"Retry-After": str(retry_after)},
        )

    user = await get_user_by_email(session, body.email)
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        # Одно и то же сообщение на "нет email" и "неверный пароль" —
        # не раскрываем существование аккаунта.
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    await clear_email_attempts(redis, email=body.email)
    token = create_access_token(user.id, user.token_version)
    return LoginResponse(token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
