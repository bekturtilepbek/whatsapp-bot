"""GET/PATCH /bots/{id} (STAGE1_CORE Блок 3, п.2).

Без auth — прямым текстом отложено на Волну 3 в STAGE1_CORE; сервис слушает
localhost, доступ на проде — через SSH-туннель (см. compose/docker-compose.prod.yml).
"""

from __future__ import annotations

import uuid

from db.bots import get_bot, update_bot
from fastapi import APIRouter, HTTPException

from ..db import SessionDep
from ..schemas.bots import BotOut, BotPatch

router = APIRouter(prefix="/bots", tags=["bots"])


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
