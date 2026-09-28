"""POST /bots/{bot_id}/sandbox/messages (FEATURES.md 9.6) — тестовый прогон
промпта без реальных клиентов, доступна всем ролям с доступом к боту
(ролевой пересмотр 2026-09-22 — раньше owner-only; тратит реальные токены
OpenAI, но это уже не повод резать доступ ролям с полным доступом к боту).

Часть A (тулзы, 2026-09-16): тулзы бота (tool_bindings) подключены через
run_tool_loop — тот же контракт, что и в реальном пайплайне
(worker/pipeline/consumer.py::_reply), тулзы и цикл — общий код из
libs/tools (ADR-002 не запрещает импортировать тулзы напрямую, запрещает
только публиковать события САМИМ тулзам). Отличия от реального диалога:
ничего не пишется в contacts/messages (история — целиком в теле запроса);
side_effecting-тулзы (сейчас только send_telegram_lead) глушатся
каноническим ответом вместо реального вызова — тестировщик не должен
случайно разослать что-то реальное, тестируя промпт. contact_id для
ToolContext — одноразовая заглушка (uuid4()): ни одна НЕ заглушённая тулза
его не читает (единственная, кто читает, — send_telegram_lead, а она
всегда заглушена раньше, до обращения к contact_id).

Часть B (vision/PDF, 2026-09-16): POST .../sandbox/media-messages —
зеркало _reply_with_vision/_reply_with_pdf (worker/pipeline/consumer.py).
Без image_prompt/pdf_prompt (или PDF без текстового слоя) — ТОЧНО тот же
fallback-текст, что увидел бы реальный клиент, без вызова LLM (подтверждено
пользователем на брейншторме — парите важнее диагностического сообщения).
"""

from __future__ import annotations

import functools
import uuid
from pathlib import PurePosixPath
from typing import Any

from core.media import DEFAULT_MEDIA_FALLBACK_TEXT
from db.bots import get_bot
from db.products import DEFAULT_CATALOG_LIMIT, list_products
from db.tool_bindings import list_enabled as list_enabled_tool_bindings
from db.usage import record_usage
from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from llm.catalog_context import ProductInfo, catalog_context
from llm.client import HistoryMessage, complete, complete_with_image, complete_with_tools
from llm.pdf_extract import PdfHasNoTextLayerError, extract_pdf_text
from llm.pricing import compute_cost
from llm.time_context import time_context
from pydantic import TypeAdapter, ValidationError
from tools.base import ToolExecutionResult
from tools.executor import ToolExecutor, build_tool_executor, tool_specs_for_bindings
from tools.registry import get_tool
from tools.tool_loop import run_tool_loop

from ..db import SessionDep, SessionFactoryDep
from ..redis_client import RedisDep
from ..schemas.sandbox import (
    SandboxHistoryItem,
    SandboxMediaOut,
    SandboxMessageIn,
    SandboxMessageOut,
)
from ..security import BotAccessUser
from ..storage import StorageDep

DEFAULT_MEDIA_MAX_SIZE_BYTES = 16 * 1024 * 1024
_HistoryAdapter = TypeAdapter(list[SandboxHistoryItem])

# Единственные типы, которые SandboxChat.tsx рендерит ИНЛАЙН (<img>/<video>) —
# всё остальное (документы, PDF) уже уходит как ссылка-скачивание, поэтому
# сужение сюда не меняет поведение для легитимных случаев. Обязательно, а не
# косметика: mime_type ниже приходит от КЛИЕНТА нетронутым, а send_document
# по конструкции принимает файл любого типа (FEATURES.md 4.8) — без белого
# списка можно было бы попросить отдать .html-документ как text/html и
# получить XSS на origin кабинета (see security review, 2026-09-28).
_INLINE_SAFE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "video/mp4"}

router = APIRouter(prefix="/bots", tags=["sandbox"])

# side_effecting-тулзы (libs/tools/src/tools/base.py) в песочнице не
# вызываются по-настоящему — LLM получает канонический ответ и продолжает
# диалог естественно, реального похода вовне (Telegram и т.п.) не
# происходит. Пер-тулзовый текст — там, где известен правдоподобный
# реальный успех; дефолт — для будущих side_effecting тулз без записи здесь.
_SANDBOX_MUTED_RESPONSES: dict[str, str] = {
    "send_telegram_lead": "Заявка отправлена менеджерам.",
}
_DEFAULT_SANDBOX_MUTED_RESPONSE = "Действие выполнено."


def _mute_side_effecting_tools(base_executor: ToolExecutor) -> ToolExecutor:
    async def executor(name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        tool = get_tool(name)
        if tool is not None and tool.side_effecting:
            return ToolExecutionResult(
                content=_SANDBOX_MUTED_RESPONSES.get(name, _DEFAULT_SANDBOX_MUTED_RESPONSE)
            )
        return await base_executor(name, arguments)

    return executor


@router.post("/{bot_id}/sandbox/messages", response_model=SandboxMessageOut)
async def send_sandbox_message(
    bot_id: uuid.UUID,
    body: SandboxMessageIn,
    session: SessionDep,
    session_factory: SessionFactoryDep,
    redis: RedisDep,
    storage: StorageDep,
    _user: BotAccessUser,
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

    bindings = await list_enabled_tool_bindings(session, bot_id)
    tool_specs = tool_specs_for_bindings(bindings)
    base_executor = build_tool_executor(
        bot, uuid.uuid4(), session_factory, redis, storage, bindings
    )
    executor = _mute_side_effecting_tools(base_executor)

    # bots.settings["model"] (Волна 4) — та же логика, что и в реальном
    # пайплайне (worker/pipeline/consumer.py::_reply): песочница должна
    # тестировать промпт на ТОЙ ЖЕ модели, что реально отвечает клиентам.
    model = bot.settings.get("model")
    loop_result = await run_tool_loop(
        system_prompt,
        history,
        tool_specs,
        executor,
        complete_fn=functools.partial(complete, model=model),
        complete_with_tools_fn=functools.partial(complete_with_tools, model=model),
    )

    if loop_result.override_replies:
        reply_text = "\n\n".join(reply.text for reply in loop_result.override_replies)
        media = [
            SandboxMediaOut(
                storage_key=item.storage_key, mime_type=item.mime_type, filename=item.filename
            )
            for reply in loop_result.override_replies
            for item in reply.media
        ]
    else:
        reply_text = loop_result.text
        media = []

    cost = compute_cost(loop_result.model, loop_result.tokens_in, loop_result.tokens_out)
    await record_usage(
        session, bot_id, loop_result.model, loop_result.tokens_in, loop_result.tokens_out, cost
    )
    await session.commit()

    return SandboxMessageOut(
        reply=reply_text,
        tokens_in=loop_result.tokens_in,
        tokens_out=loop_result.tokens_out,
        model=loop_result.model,
        media=media,
    )


@router.get("/{bot_id}/sandbox/media")
async def get_sandbox_media(
    bot_id: uuid.UUID,
    storage: StorageDep,
    _user: BotAccessUser,
    key: str = Query(...),
    mime_type: str = Query(...),
) -> Response:
    """Байты медиа, которое тулза вернула в этом ходе песочницы (карточка
    товара, файл) — эфемерные, нигде в БД для песочницы не хранятся, поэтому
    mime_type передаётся явно (не вычитывается из строки в БД, как у
    products.media/documents). Префикс ключа — проверка, что запрашивается
    объект именно ЭТОГО бота, не чужой (owner и так видит все боты, но
    эндпоинт не должен превращаться в открытое чтение произвольных ключей
    Storage по названию) — ключ дополнительно нормализуется: голая проверка
    startswith() пропускала "bots/{bot_id}/../{другой_bot_id}/..." (совпадает
    по СТРОКЕ с нужным префиксом, а после ".." реально читает чужого бота,
    т.к. Storage.get проверяет только выход за пределы ОБЩЕГО корня, не
    поддиректории конкретного бота — see security review, 2026-09-28)."""
    if ".." in PurePosixPath(key).parts or not key.startswith(f"bots/{bot_id}/"):
        raise HTTPException(status_code=404, detail="media not found")
    try:
        data = await storage.get(key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc
    if mime_type not in _INLINE_SAFE_MIME_TYPES:
        # Не доверяем mime_type для всего вне белого списка — иначе клиент
        # мог бы запросить произвольно загруженный документ (send_document
        # принимает любой тип) как text/html и получить XSS на origin
        # кабинета через этот же эндпоинт (see security review, 2026-09-28).
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"},
        )
    return Response(
        content=data, media_type=mime_type, headers={"X-Content-Type-Options": "nosniff"}
    )


def _parse_history(raw: str | None) -> list[HistoryMessage]:
    if raw is None:
        return []
    try:
        items = _HistoryAdapter.validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail="history must be valid JSON matching SandboxHistoryItem[]"
        ) from exc
    return [HistoryMessage(role=item.role, content=item.content) for item in items]


@router.post("/{bot_id}/sandbox/media-messages", response_model=SandboxMessageOut)
async def send_sandbox_media_message(
    bot_id: uuid.UUID,
    session: SessionDep,
    _user: BotAccessUser,
    file: UploadFile = File(...),  # noqa: B008
    history: str | None = Form(None),
    caption: str | None = Form(None),
) -> SandboxMessageOut:
    """Зеркало _reply_with_vision/_reply_with_pdf (worker/pipeline/
    consumer.py) — фото/PDF от "клиента" в песочнице. Ничего не пишется в
    Storage (байты только в памяти запроса) — в отличие от медиа из тулз
    (GET .../sandbox/media), этому файлу неоткуда взяться повторно, он
    существует только на время одного запроса.
    """
    bot = await get_bot(session, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")

    content_type = file.content_type or ""
    is_image = content_type.startswith("image/")
    is_pdf = content_type == "application/pdf"
    if not is_image and not is_pdf:
        raise HTTPException(
            status_code=415, detail="only image/* and application/pdf are supported"
        )

    data = await file.read()
    max_size = bot.settings.get("media_max_size_bytes") or DEFAULT_MEDIA_MAX_SIZE_BYTES
    if len(data) > max_size:
        raise HTTPException(status_code=413, detail="file too large")

    history_messages = _parse_history(history)
    time_ctx = time_context(bot.timezone)
    fallback_text = bot.settings.get("media_fallback_text") or DEFAULT_MEDIA_FALLBACK_TEXT
    fallback = SandboxMessageOut(reply=fallback_text, tokens_in=0, tokens_out=0, model="", media=[])

    if is_image:
        if not bot.image_prompt:
            return fallback
        system_prompt = "\n\n".join(section for section in (bot.image_prompt, time_ctx) if section)
        result = await complete_with_image(
            system_prompt,
            history_messages,
            caption or "",
            data,
            content_type,
            model=bot.settings.get("model"),
        )
    else:
        if not bot.pdf_prompt:
            return fallback
        try:
            pdf_text = extract_pdf_text(data)
        except PdfHasNoTextLayerError:
            return fallback
        system_prompt = "\n\n".join(section for section in (bot.pdf_prompt, time_ctx) if section)
        document_turn = f"Текст документа:\n{pdf_text}"
        current_turn = f"{caption}\n\n{document_turn}" if caption else document_turn
        history_messages.append(HistoryMessage(role="user", content=current_turn))
        result = await complete(system_prompt, history_messages, model=bot.settings.get("model"))

    cost = compute_cost(result.model, result.tokens_in, result.tokens_out)
    await record_usage(session, bot_id, result.model, result.tokens_in, result.tokens_out, cost)
    await session.commit()

    return SandboxMessageOut(
        reply=result.text,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        model=result.model,
        media=[],
    )
