"""POST /bots/{bot_id}/sandbox/messages (FEATURES.md 9.6) — тестовый прогон
промпта без реальных клиентов, owner-only (тратит реальные токены OpenAI).

Сознательно урезано против настоящего пайплайна (services/worker/src/worker/
pipeline/consumer.py::_reply): БЕЗ tool loop — вызовы тулз (карточки товара,
файлы/видео, Telegram-лид) отложены отдельной итерацией (подтверждено
пользователем при брейншторме FEATURES.md 9.6). Поэтому не нужен ни Redis,
ни ToolContext — простой system prompt (промпт бота + каталог + время) и
один вызов complete(). История — целиком в теле запроса (админка хранит её
в браузере), ничего не пишется в contacts/messages: это не реальный диалог.
usage_events пишется как обычно — тестовые сообщения реально стоят токенов
и должны быть видны в /usage (FEATURES.md 6.15), это ожидаемо.
"""

from __future__ import annotations

import uuid

from db.bots import get_bot
from db.products import DEFAULT_CATALOG_LIMIT, list_products
from db.usage import record_usage
from fastapi import APIRouter, HTTPException
from llm.catalog_context import ProductInfo, catalog_context
from llm.client import HistoryMessage, complete
from llm.pricing import compute_cost
from llm.time_context import time_context

from ..db import SessionDep
from ..schemas.sandbox import SandboxMessageIn, SandboxMessageOut
from ..security import PlatformOwner

router = APIRouter(prefix="/bots", tags=["sandbox"])


@router.post("/{bot_id}/sandbox/messages", response_model=SandboxMessageOut)
async def send_sandbox_message(
    bot_id: uuid.UUID, body: SandboxMessageIn, session: SessionDep, _owner: PlatformOwner
) -> SandboxMessageOut:
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")

    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")

    products = await list_products(session, bot_id, limit=DEFAULT_CATALOG_LIMIT)
    catalog = catalog_context(
        [
            ProductInfo(
                name=p.name,
                price=str(p.price) if p.price is not None else None,
                description=p.description,
            )
            for p in products
        ]
    )
    time_ctx = time_context(bot.timezone)
    system_prompt = "\n\n".join(
        section for section in (bot.system_prompt, catalog, time_ctx) if section
    )

    history = [HistoryMessage(role=item.role, content=item.content) for item in body.history]
    history.append(HistoryMessage(role="user", content=body.message))

    result = await complete(system_prompt, history)
    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    await record_usage(session, bot_id, result.model, result.tokens_in, result.tokens_out, cost)
    await session.commit()

    return SandboxMessageOut(
        reply=result.text,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        model=result.model,
    )
