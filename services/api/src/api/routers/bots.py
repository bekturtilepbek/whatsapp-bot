"""GET/PATCH /bots/{id} (STAGE1_CORE Блок 3, п.2).

Без auth — прямым текстом отложено на Волну 3 в STAGE1_CORE; сервис слушает
localhost, доступ на проде — через SSH-туннель (см. compose/docker-compose.prod.yml).
"""

from __future__ import annotations

import uuid

import httpx
from db.bots import get_bot, update_bot
from fastapi import APIRouter, HTTPException, Response

from ..db import SessionDep
from ..gateway_client import GatewayClientDep
from ..schemas.bots import BotOut, BotPatch

router = APIRouter(prefix="/bots", tags=["bots"])


async def _proxy_to_gateway(gateway: httpx.AsyncClient, method: str, path: str) -> Response:
    """Пробрасывает ответ gateway как есть (тело/content-type/статус) —
    QR это PNG, logout — JSON, оба маршрута gateway уже сами проверяют
    существование бота (404), дублировать эту проверку в api не нужно.
    """
    try:
        upstream = await gateway.request(method, path)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="gateway unreachable") from exc
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        status_code=upstream.status_code,
    )


@router.get("/{bot_id}", response_model=BotOut)
async def read_bot(bot_id: uuid.UUID, session: SessionDep) -> BotOut:
    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    return BotOut.model_validate(bot)


@router.patch("/{bot_id}", response_model=BotOut)
async def patch_bot(bot_id: uuid.UUID, patch: BotPatch, session: SessionDep) -> BotOut:
    data = patch.model_dump(exclude_unset=True)
    bot = await update_bot(
        session,
        bot_id,
        enabled=data.get("enabled"),
        system_prompt=data.get("system_prompt"),
        settings_patch=data.get("settings"),
    )
    await session.commit()
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    return BotOut.model_validate(bot)


@router.get("/{bot_id}/qr")
async def get_qr(bot_id: uuid.UUID, gateway: GatewayClientDep) -> Response:
    return await _proxy_to_gateway(gateway, "GET", f"/qr/{bot_id}")


@router.post("/{bot_id}/logout")
async def logout_bot(bot_id: uuid.UUID, gateway: GatewayClientDep) -> Response:
    return await _proxy_to_gateway(gateway, "POST", f"/bots/{bot_id}/logout")
