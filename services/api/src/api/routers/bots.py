"""GET/PATCH /bots/{id} (STAGE1_CORE Блок 3, п.2).

Доступ на каждый bot_id-роут — через require_bot_access/require_platform_owner
(FEATURES.md 6.18, services/api/src/api/security.py): владелец платформы видит
всё, клиент — только бота(ов) с грантом в bot_access.
"""

from __future__ import annotations

import re
import uuid

import httpx
from core.redis_keys import handoff_key
from db.blocked_contacts import add_blocked_number, list_blocked_numbers, remove_blocked_number
from db.bots import get_bot_with_session, list_bots, update_bot
from db.prompt_versions import PromptKind, list_versions
from db.tool_bindings import disable as disable_tool
from db.tool_bindings import enable as enable_tool
from db.tool_bindings import list_enabled as list_enabled_tools
from fastapi import APIRouter, HTTPException, Query, Response
from tools.registry import all_tool_names

from ..db import SessionDep
from ..gateway_client import GatewayClientDep
from ..redis_client import RedisDep
from ..schemas.blocked_contacts import BlockedNumberIn, BlockedNumberOut
from ..schemas.bots import BotOut, BotPatch
from ..schemas.prompt_versions import PromptVersionOut
from ..schemas.tool_bindings import ToolBindingIn, ToolBindingOut
from ..security import BotAccessUser, CurrentUser

router = APIRouter(prefix="/bots", tags=["bots"])

# Пагинация чёрного списка (FEATURES.md 1.5/6.9) — тот же паттерн, что у
# товаров (?limit=&offset=), но дефолт меньше: список номеров, в отличие от
# каталога, не нужен целиком worker'у (у него отдельный is_blocked-чек по
# одному номеру), это чисто витринный список для кабинета.
BLOCKED_LIST_DEFAULT_LIMIT = 20
BLOCKED_LIST_MAX_LIMIT = 100


@router.get("", response_model=list[BotOut])
async def list_all_bots(session: SessionDep, user: CurrentUser) -> list[BotOut]:
    filter_user_id = None if user.is_platform_owner else user.id
    bots = await list_bots(session, user_id=filter_user_id)
    return [BotOut.model_validate(bot) for bot in bots]


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
async def read_bot(bot_id: uuid.UUID, session: SessionDep, user: BotAccessUser) -> BotOut:
    bot = await get_bot_with_session(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    return BotOut.model_validate(bot)


@router.patch("/{bot_id}", response_model=BotOut)
async def patch_bot(
    bot_id: uuid.UUID, patch: BotPatch, session: SessionDep, user: BotAccessUser
) -> BotOut:
    data = patch.model_dump(exclude_unset=True)
    bot = await update_bot(
        session,
        bot_id,
        enabled=data.get("enabled"),
        system_prompt=data.get("system_prompt"),
        image_prompt=data.get("image_prompt"),
        pdf_prompt=data.get("pdf_prompt"),
        settings_patch=data.get("settings"),
    )
    await session.commit()
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    return BotOut.model_validate(bot)


@router.get("/{bot_id}/prompts/{kind}/versions", response_model=list[PromptVersionOut])
async def list_prompt_versions(
    bot_id: uuid.UUID, kind: PromptKind, session: SessionDep, user: BotAccessUser
) -> list[PromptVersionOut]:
    versions = await list_versions(session, bot_id, kind)
    return [PromptVersionOut.model_validate(v) for v in versions]


@router.get("/{bot_id}/qr")
async def get_qr(bot_id: uuid.UUID, gateway: GatewayClientDep, user: BotAccessUser) -> Response:
    return await _proxy_to_gateway(gateway, "GET", f"/qr/{bot_id}")


@router.post("/{bot_id}/logout")
async def logout_bot(bot_id: uuid.UUID, gateway: GatewayClientDep, user: BotAccessUser) -> Response:
    return await _proxy_to_gateway(gateway, "POST", f"/bots/{bot_id}/logout")


@router.post("/{bot_id}/chats/{chat_id}/release")
async def release_chat(
    bot_id: uuid.UUID, chat_id: str, redis: RedisDep, user: BotAccessUser
) -> dict[str, str]:
    """Ручной возврат чата боту — DELETE того же ключа, что снимается по
    TTL (worker/pipeline/handoff.py). На несуществующий ключ — no-op,
    идемпотентно: повторный вызов не ошибка.
    """
    await redis.delete(handoff_key(str(bot_id), chat_id))
    return {"status": "released"}


def _strip_non_digits(phone: str) -> str:
    """Тот же формат хранения, что и Contact.wa_id — без "+"/пробелов/скобок
    (эталон V1: re.sub(r'\\D', '', phone) в central-admin).
    """
    return re.sub(r"\D", "", phone)


@router.get("/{bot_id}/blocked-numbers", response_model=list[BlockedNumberOut])
async def list_blocked(
    bot_id: uuid.UUID,
    session: SessionDep,
    user: BotAccessUser,
    limit: int = Query(BLOCKED_LIST_DEFAULT_LIMIT, ge=1, le=BLOCKED_LIST_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[BlockedNumberOut]:
    phones = await list_blocked_numbers(session, bot_id, limit=limit, offset=offset)
    return [BlockedNumberOut(phone=p) for p in phones]


@router.post("/{bot_id}/blocked-numbers", response_model=BlockedNumberOut, status_code=201)
async def add_blocked(
    bot_id: uuid.UUID, body: BlockedNumberIn, session: SessionDep, user: BotAccessUser
) -> BlockedNumberOut:
    phone = _strip_non_digits(body.phone)
    await add_blocked_number(session, bot_id, phone)
    await session.commit()
    return BlockedNumberOut(phone=phone)


@router.delete("/{bot_id}/blocked-numbers/{phone}", status_code=204)
async def delete_blocked(
    bot_id: uuid.UUID, phone: str, session: SessionDep, user: BotAccessUser
) -> None:
    await remove_blocked_number(session, bot_id, phone)
    await session.commit()


@router.get("/{bot_id}/tools", response_model=list[ToolBindingOut])
async def list_tools(
    bot_id: uuid.UUID, session: SessionDep, user: BotAccessUser
) -> list[ToolBindingOut]:
    bindings = await list_enabled_tools(session, bot_id)
    return [ToolBindingOut(tool_name=b.tool_name, config=b.config) for b in bindings]


@router.post("/{bot_id}/tools", response_model=ToolBindingOut, status_code=201)
async def add_tool(
    bot_id: uuid.UUID, body: ToolBindingIn, session: SessionDep, user: BotAccessUser
) -> ToolBindingOut:
    if body.tool_name not in all_tool_names():
        raise HTTPException(status_code=400, detail=f"unknown tool: {body.tool_name}")
    await enable_tool(session, bot_id, body.tool_name, body.config)
    await session.commit()
    return ToolBindingOut(tool_name=body.tool_name, config=body.config)


@router.delete("/{bot_id}/tools/{tool_name}", status_code=204)
async def delete_tool(
    bot_id: uuid.UUID, tool_name: str, session: SessionDep, user: BotAccessUser
) -> None:
    await disable_tool(session, bot_id, tool_name)
    await session.commit()
