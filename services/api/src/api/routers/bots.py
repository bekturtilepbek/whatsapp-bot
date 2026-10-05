"""GET/PATCH /bots/{id} (STAGE1_CORE Блок 3, п.2).

Доступ на каждый bot_id-роут — через require_bot_access/require_full_bot_access/
require_platform_wide (FEATURES.md 6.18, services/api/src/api/security.py):
superadmin/admin видят всё; prompter/client — только бота(ов) с грантом в
bot_access, причём client на самом боте урезан (без промптов/тулз/чёрного
списка/настроек/QR — см. FullBotAccess).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from core.phone import normalize_phone_digits
from core.redis_keys import handoff_key
from db.blocked_contacts import add_blocked_number, list_blocked_numbers, remove_blocked_number
from db.bot_access import grant_bot_access
from db.bots import UNSET, create_bot, get_bot_with_session, list_bots, update_bot
from db.contacts import count_contacts, find_by_identifier
from db.handoff_events import KIND_RELEASED_MANUAL, record_handoff_event
from db.messages import count_messages
from db.models import Bot
from db.overview import handoff_tracked_since, window_counts
from db.prompt_versions import PromptKind, list_versions
from db.tool_bindings import disable as disable_tool
from db.tool_bindings import enable as enable_tool
from db.tool_bindings import list_enabled as list_enabled_tools
from db.users import get_user
from fastapi import APIRouter, HTTPException, Query, Response
from tools.config_validation import validate_tool_config
from tools.registry import all_tool_names

from ..db import SessionDep
from ..gateway_client import GatewayClientDep
from ..handoff import list_active_chat_ids
from ..redis_client import RedisDep
from ..schemas.blocked_contacts import BlockedNumberIn, BlockedNumberOut
from ..schemas.bots import (
    ActiveChatOut,
    BotCreate,
    BotEnabledPatch,
    BotOut,
    BotOverview,
    BotPatch,
    BotPromptsPatch,
    BotStats,
    OverviewCounts,
    OverviewPeriod,
)
from ..schemas.prompt_versions import PromptVersionOut
from ..schemas.tool_bindings import ToolBindingIn, ToolBindingOut
from ..security import PLATFORM_WIDE_ROLES, BotAccessUser, CurrentUser, FullBotAccess, PlatformWide

logger = structlog.get_logger("api.bots")

router = APIRouter(prefix="/bots", tags=["bots"])

# Пагинация чёрного списка (FEATURES.md 1.5/6.9) — тот же паттерн, что у
# товаров (?limit=&offset=), но дефолт меньше: список номеров, в отличие от
# каталога, не нужен целиком worker'у (у него отдельный is_blocked-чек по
# одному номеру), это чисто витринный список для кабинета.
BLOCKED_LIST_DEFAULT_LIMIT = 20
BLOCKED_LIST_MAX_LIMIT = 100


def _to_bot_out(bot: Bot) -> BotOut:
    """BotOut.responsible_user_email не ORM-атрибут (from_attributes его не
    подхватит сам) — требует bot.responsible_user eager-loaded
    (get_bot_with_session/list_bots уже это делают)."""
    out = BotOut.model_validate(bot)
    out.responsible_user_email = bot.responsible_user.email if bot.responsible_user else None
    return out


async def _validate_responsible_user(session: SessionDep, user_id: uuid.UUID) -> None:
    """Ответственный — только роль prompter (FEATURES.md 6.18): клиенты и
    админы не "ведут" бота в этом смысле."""
    responsible = await get_user(session, user_id)
    if responsible is None:
        raise HTTPException(status_code=404, detail="Ответственный пользователь не найден")
    if responsible.role != "prompter":
        raise HTTPException(status_code=422, detail="Ответственным может быть только промптер")


@router.get("", response_model=list[BotOut])
async def list_all_bots(session: SessionDep, user: CurrentUser) -> list[BotOut]:
    filter_user_id = None if user.role in PLATFORM_WIDE_ROLES else user.id
    bots = await list_bots(session, user_id=filter_user_id)
    return [_to_bot_out(bot) for bot in bots]


@router.post("", response_model=BotOut, status_code=201)
async def create_bot_route(body: BotCreate, session: SessionDep, _admin: PlatformWide) -> BotOut:
    """Онбординг бота из UI (FEATURES.md 6.20) — имя + опциональный
    ответственный (prompter), всё остальное server_default модели.
    PlatformWide: создание бота — административное действие. Никакой
    привязки к номеру здесь нет — это отдельный шаг (QR-экран, 6.1/6.2),
    уже сданный и работающий "из коробки" для любого существующего bot_id:
    gateway поднимает сессию Baileys лениво по первому GET /qr/:botId, а
    не при создании строки в bots."""
    name = _validated_bot_name(body.name)
    if body.responsible_user_id is not None:
        await _validate_responsible_user(session, body.responsible_user_id)
    bot = await create_bot(session, name=name, responsible_user_id=body.responsible_user_id)
    # Ответственный сразу получает доступ к боту (иначе не увидел бы его в
    # своём /bots) — тот же grant_bot_access, что использует /users.
    if body.responsible_user_id is not None:
        await grant_bot_access(session, body.responsible_user_id, bot.id)
    await session.commit()
    created = await get_bot_with_session(session, bot.id)
    assert created is not None  # только что закоммитили
    return _to_bot_out(created)


async def _proxy_to_gateway(gateway: httpx.AsyncClient, method: str, path: str) -> Response:
    """Пробрасывает ответ gateway как есть (тело/content-type/статус) —
    QR это PNG, logout — JSON, оба маршрута gateway уже сами проверяют
    существование бота (404), дублировать эту проверку в api не нужно.
    """
    try:
        upstream = await gateway.request(method, path)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Сервис WhatsApp недоступен, попробуйте позже",
        ) from exc
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        status_code=upstream.status_code,
    )


@router.get("/{bot_id}", response_model=BotOut)
async def read_bot(bot_id: uuid.UUID, session: SessionDep, user: BotAccessUser) -> BotOut:
    bot = await get_bot_with_session(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Бот не найден")
    return _to_bot_out(bot)


@router.patch("/{bot_id}", response_model=BotOut)
async def patch_bot(
    bot_id: uuid.UUID, patch: BotPatch, session: SessionDep, user: FullBotAccess
) -> BotOut:
    """Имя + настройки + ответственный — вкладка "Настройки" (недоступна
    client, см. FullBotAccess). enabled/промпты — отдельные роуты ниже."""
    data = patch.model_dump(exclude_unset=True)
    name = data.get("name")
    if name is not None:
        name = _validated_bot_name(name)
    # dict.get(key, UNSET) возвращает UNSET, только если ключ ОТСУТСТВУЕТ —
    # если клиент явно прислал null (снять ответственного), get вернёт
    # именно None, а не UNSET, так и отличаем "не трогать" от "снять".
    responsible_user_id = data.get("responsible_user_id", UNSET)
    if responsible_user_id is not UNSET and responsible_user_id is not None:
        await _validate_responsible_user(session, responsible_user_id)
    bot = await update_bot(
        session,
        bot_id,
        name=name,
        settings_patch=data.get("settings"),
        responsible_user_id=responsible_user_id,
    )
    await session.commit()
    if bot is None:
        raise HTTPException(status_code=404, detail="Бот не найден")
    return _to_bot_out(bot)


@router.patch("/{bot_id}/enabled", response_model=BotOut)
async def patch_bot_enabled(
    bot_id: uuid.UUID, patch: BotEnabledPatch, session: SessionDep, user: BotAccessUser
) -> BotOut:
    """Пауза/возобновление — тумблер на вкладке "Обзор", доступен всем
    ролям с доступом к боту (включая client)."""
    bot = await update_bot(session, bot_id, enabled=patch.enabled)
    await session.commit()
    if bot is None:
        raise HTTPException(status_code=404, detail="Бот не найден")
    return _to_bot_out(bot)


@router.patch("/{bot_id}/prompts", response_model=BotOut)
async def patch_bot_prompts(
    bot_id: uuid.UUID, patch: BotPromptsPatch, session: SessionDep, user: FullBotAccess
) -> BotOut:
    """Вкладка "Промпты" — недоступна client, см. FullBotAccess."""
    data = patch.model_dump(exclude_unset=True)
    bot = await update_bot(
        session,
        bot_id,
        system_prompt=data.get("system_prompt"),
        image_prompt=data.get("image_prompt"),
        pdf_prompt=data.get("pdf_prompt"),
    )
    await session.commit()
    if bot is None:
        raise HTTPException(status_code=404, detail="Бот не найден")
    return _to_bot_out(bot)


@router.get("/{bot_id}/stats", response_model=BotStats)
async def read_bot_stats(bot_id: uuid.UUID, session: SessionDep, user: BotAccessUser) -> BotStats:
    """Стат-плитки вкладки "Обзор" — отдельная ручка, не поле BotOut (см.
    schemas/bots.py::BotStats)."""
    messages_count = await count_messages(session, bot_id)
    contacts_count = await count_contacts(session, bot_id)
    return BotStats(messages_count=messages_count, contacts_count=contacts_count)


_OVERVIEW_PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


@router.get("/{bot_id}/overview", response_model=BotOverview)
async def read_bot_overview(
    bot_id: uuid.UUID,
    session: SessionDep,
    user: BotAccessUser,
    period: OverviewPeriod = "7d",
) -> BotOverview:
    """Агрегаты "Обзора" за скользящий период и за соседнее окно того же
    размера (6.23). /stats — общие счётчики за всё время, здесь по периоду.
    """
    delta = _OVERVIEW_PERIODS[period]
    now = datetime.now(UTC)
    tracked_since = await handoff_tracked_since(session)
    current = await window_counts(session, bot_id, now - delta, None, tracked_since)
    previous = await window_counts(session, bot_id, now - 2 * delta, now - delta, tracked_since)
    return BotOverview(
        period=period,
        handoff_tracked_since=tracked_since,
        previous=OverviewCounts(**previous.__dict__),
        **current.__dict__,
    )


@router.get("/{bot_id}/chats", response_model=list[ActiveChatOut])
async def list_active_chats(
    bot_id: uuid.UUID, session: SessionDep, redis: RedisDep, user: BotAccessUser
) -> list[ActiveChatOut]:
    """Вкладка "Активные чаты" (5.3) — какие диалоги сейчас ведёт человек,
    не бот. TTL читаем отдельным вызовом на каждый ключ (не MULTI/pipeline) —
    активных чатов на бота обычно единицы, а не сотни, накладные расходы
    незаметны; если это когда-нибудь изменится — первый кандидат на pipeline.
    """
    chat_ids = await list_active_chat_ids(redis, str(bot_id))
    result: list[ActiveChatOut] = []
    for chat_id in chat_ids:
        ttl = await redis.ttl(handoff_key(str(bot_id), chat_id))
        contact = await find_by_identifier(session, bot_id, chat_id.split("@", 1)[0])
        result.append(
            ActiveChatOut(
                chat_id=chat_id,
                contact_name=contact.name if contact else None,
                contact_phone=contact.phone if contact else None,
                auto_release_in_seconds=ttl if ttl and ttl > 0 else None,
            )
        )
    return result


@router.get("/{bot_id}/prompts/{kind}/versions", response_model=list[PromptVersionOut])
async def list_prompt_versions(
    bot_id: uuid.UUID, kind: PromptKind, session: SessionDep, user: BotAccessUser
) -> list[PromptVersionOut]:
    versions = await list_versions(session, bot_id, kind)
    return [PromptVersionOut.model_validate(v) for v in versions]


@router.get("/{bot_id}/qr")
async def get_qr(bot_id: uuid.UUID, gateway: GatewayClientDep, user: FullBotAccess) -> Response:
    return await _proxy_to_gateway(gateway, "GET", f"/qr/{bot_id}")


@router.post("/{bot_id}/logout")
async def logout_bot(bot_id: uuid.UUID, gateway: GatewayClientDep, user: FullBotAccess) -> Response:
    return await _proxy_to_gateway(gateway, "POST", f"/bots/{bot_id}/logout")


@router.post("/{bot_id}/chats/{chat_id}/release")
async def release_chat(
    bot_id: uuid.UUID, chat_id: str, session: SessionDep, redis: RedisDep, user: BotAccessUser
) -> dict[str, str]:
    """Ручной возврат чата боту — DELETE того же ключа, что снимается по
    TTL (worker/pipeline/handoff.py). На несуществующий ключ — no-op,
    идемпотентно: повторный вызов не ошибка и события (5.7) не пишет.
    """
    deleted = await redis.delete(handoff_key(str(bot_id), chat_id))
    if deleted:
        # Ключ уже снят — сбой записи статистики не должен превращать
        # успешный возврат в 500 (тот же принцип, что у worker/consumer.py).
        try:
            await record_handoff_event(
                session, bot_id, chat_id, KIND_RELEASED_MANUAL, actor_user_id=user.id
            )
            await session.commit()
        except Exception:
            logger.exception("handoff event write failed", bot_id=str(bot_id), chat_id=chat_id)
    return {"status": "released"}


BOT_NAME_MAX_LENGTH = 100


def _validated_bot_name(raw: str) -> str:
    """Имя обязательно и не длиннее BOT_NAME_MAX_LENGTH — раньше принималось
    имя из 5000 символов (ломало вёрстку списка/шапки, 2026-09-28)."""
    name = raw.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Название не может быть пустым")
    if len(name) > BOT_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=422, detail=f"Название — не длиннее {BOT_NAME_MAX_LENGTH} символов"
        )
    return name


BLOCKED_PHONE_MIN_DIGITS = 7
BLOCKED_PHONE_MAX_DIGITS = 15


@router.get("/{bot_id}/blocked-numbers", response_model=list[BlockedNumberOut])
async def list_blocked(
    bot_id: uuid.UUID,
    session: SessionDep,
    user: FullBotAccess,
    limit: int = Query(BLOCKED_LIST_DEFAULT_LIMIT, ge=1, le=BLOCKED_LIST_MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> list[BlockedNumberOut]:
    phones = await list_blocked_numbers(session, bot_id, limit=limit, offset=offset)
    return [BlockedNumberOut(phone=p) for p in phones]


@router.post("/{bot_id}/blocked-numbers", response_model=BlockedNumberOut, status_code=201)
async def add_blocked(
    bot_id: uuid.UUID, body: BlockedNumberIn, session: SessionDep, user: FullBotAccess
) -> BlockedNumberOut:
    # Тот же формат, что Contact.wa_id (цифры с кодом страны). Местный KG-формат
    # ("0700 123 456") приводится к 996… — иначе блокировка молча не срабатывала
    # (FEATURES.md 9.1, правило V1 formatPhoneNumber).
    phone = normalize_phone_digits(body.phone)
    # "abc" раньше превращался в "" и сохранялся: пустая строка в списке,
    # которую нельзя удалить (DELETE .../blocked-numbers/ — 405). Матчинг идёт
    # по wa_id, а это номер с кодом страны: 7–15 цифр (E.164).
    if not BLOCKED_PHONE_MIN_DIGITS <= len(phone) <= BLOCKED_PHONE_MAX_DIGITS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Номер должен содержать от {BLOCKED_PHONE_MIN_DIGITS} до "
                f"{BLOCKED_PHONE_MAX_DIGITS} цифр вместе с кодом страны"
            ),
        )
    await add_blocked_number(session, bot_id, phone)
    await session.commit()
    return BlockedNumberOut(phone=phone)


@router.delete("/{bot_id}/blocked-numbers/{phone}", status_code=204)
async def delete_blocked(
    bot_id: uuid.UUID, phone: str, session: SessionDep, user: FullBotAccess
) -> None:
    await remove_blocked_number(session, bot_id, phone)
    await session.commit()


@router.get("/{bot_id}/tools", response_model=list[ToolBindingOut])
async def list_tools(
    bot_id: uuid.UUID, session: SessionDep, user: FullBotAccess
) -> list[ToolBindingOut]:
    bindings = await list_enabled_tools(session, bot_id)
    return [ToolBindingOut(tool_name=b.tool_name, config=b.config) for b in bindings]


@router.post("/{bot_id}/tools", response_model=ToolBindingOut, status_code=201)
async def add_tool(
    bot_id: uuid.UUID, body: ToolBindingIn, session: SessionDep, user: FullBotAccess
) -> ToolBindingOut:
    if body.tool_name not in all_tool_names():
        raise HTTPException(status_code=400, detail=f"Неизвестный инструмент: {body.tool_name}")
    config_error = validate_tool_config(body.tool_name, body.config)
    if config_error is not None:
        raise HTTPException(status_code=422, detail=config_error)
    await enable_tool(session, bot_id, body.tool_name, body.config)
    await session.commit()
    return ToolBindingOut(tool_name=body.tool_name, config=body.config)


@router.delete("/{bot_id}/tools/{tool_name}", status_code=204)
async def delete_tool(
    bot_id: uuid.UUID, tool_name: str, session: SessionDep, user: FullBotAccess
) -> None:
    await disable_tool(session, bot_id, tool_name)
    await session.commit()
