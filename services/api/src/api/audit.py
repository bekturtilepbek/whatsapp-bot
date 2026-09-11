"""ASGI-middleware, пишущий аудит-лог (FEATURES.md 6.19) на каждую
успешную мутацию — без единой правки в routers/*.py.

Реестр ACTION_REGISTRY — единственное расширяемое место: новый
мутирующий роут в будущем добавляется сюда одной строкой; без записи в
реестре роут просто не аудируется, тихо (документированное поведение,
не баг). Три-уровневый fallback payload'а и все технические ограничения
см. docs/superpowers/specs/2026-09-11-audit-log-design.md.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from db.audit_log import create_entry
from fastapi import Request
from starlette.responses import Response

from .db import get_session_factory
from .security import decode_access_token

logger = structlog.get_logger("api.audit")

AUDIT_METHODS = frozenset({"POST", "PATCH", "DELETE", "PUT"})

ACTION_REGISTRY: dict[tuple[str, str], str] = {
    ("POST", "/bots"): "bots.create",
    ("PATCH", "/bots/{bot_id}"): "bots.update",
    ("POST", "/bots/{bot_id}/logout"): "bots.logout",
    ("POST", "/bots/{bot_id}/chats/{chat_id}/release"): "bots.release_chat",
    ("POST", "/bots/{bot_id}/blocked-numbers"): "blocked_numbers.create",
    ("DELETE", "/bots/{bot_id}/blocked-numbers/{phone}"): "blocked_numbers.delete",
    ("POST", "/bots/{bot_id}/tools"): "tools.create",
    ("DELETE", "/bots/{bot_id}/tools/{tool_name}"): "tools.delete",
    ("POST", "/bots/{bot_id}/documents"): "documents.create",
    ("DELETE", "/bots/{bot_id}/documents/{document_id}"): "documents.delete",
    ("POST", "/bots/{bot_id}/products"): "products.create",
    ("PATCH", "/bots/{bot_id}/products/{product_id}"): "products.update",
    ("DELETE", "/bots/{bot_id}/products/{product_id}"): "products.delete",
    ("POST", "/bots/{bot_id}/products/{product_id}/photos"): "product_photos.create",
    ("DELETE", "/bots/{bot_id}/products/{product_id}/photos/{photo_id}"): "product_photos.delete",
    ("POST", "/users"): "users.create",
    ("PATCH", "/users/{user_id}"): "users.update",
    ("POST", "/users/{user_id}/bot-access"): "bot_access.grant",
    ("DELETE", "/users/{user_id}/bot-access/{bot_id}"): "bot_access.revoke",
}

# Тело запроса НЕ читается вообще для этих роутов (multipart — файлы/фото,
# бессмысленно и дорого буферить в память ради аудит-лога). Payload для
# них всегда берётся из ответа (все три возвращают JSON-объект).
MULTIPART_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/bots/{bot_id}/products"),
        ("POST", "/bots/{bot_id}/products/{product_id}/photos"),
        ("POST", "/bots/{bot_id}/documents"),
    }
)


def _json_safe_path_params(path_params: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) for k, v in path_params.items()}


async def audit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if request.method not in AUDIT_METHODS:
        return await call_next(request)

    request_content_type = request.headers.get("content-type", "")
    is_multipart = request_content_type.startswith("multipart/")
    request_body: bytes | None = None
    if not is_multipart:
        # Кэшируется Starlette'ом — роут ниже читает те же байты повторно,
        # парсинг Pydantic-моделью не ломается.
        request_body = await request.body()

    response = await call_next(request)

    if not (200 <= response.status_code < 300):
        return response

    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path is None:
        return response

    action = ACTION_REGISTRY.get((request.method, route_path))
    if action is None:
        return response

    # Response — StreamingResponse (BaseHTTPMiddleware) — тело читается
    # один раз через body_iterator, дальше нужно вернуть НОВЫЙ Response с
    # теми же байтами, иначе клиент получит пустой ответ.
    response_body = b""
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        response_body += chunk
    rebuilt_response = Response(
        content=response_body,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )

    try:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return rebuilt_response
        actor_user_id = decode_access_token(auth_header.removeprefix("Bearer "))

        bot_id_raw = request.path_params.get("bot_id")
        bot_id = uuid.UUID(bot_id_raw) if bot_id_raw else None

        payload: dict[str, Any] | None = None
        response_content_type = response.headers.get("content-type", "")
        if response_content_type.startswith("application/json") and response_body:
            payload = json.loads(response_body)
        elif (
            not response_body
            and (request.method, route_path) not in MULTIPART_ROUTES
            and request_body
            and request_content_type.startswith("application/json")
        ):
            payload = json.loads(request_body)
        else:
            path_params = dict(request.path_params)
            if path_params:
                payload = _json_safe_path_params(path_params)

        session_factory = getattr(request.app.state, "audit_session_factory", None)
        if session_factory is None:
            session_factory = get_session_factory()

        async with session_factory() as session:
            await create_entry(
                session,
                actor_user_id=actor_user_id,
                bot_id=bot_id,
                action=action,
                payload=payload,
            )
            await session.commit()
    except Exception:
        logger.warning("audit_log_write_failed", action=action, exc_info=True)

    return rebuilt_response
