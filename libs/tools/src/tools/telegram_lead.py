"""Лид в Telegram-группу (FEATURES.md 4.7) — эталон V1 (sendToTelegramGroup),
generic-набор полей (не привязан к нише клиента, см.
docs/superpowers/specs/2026-09-08-telegram-lead-tool-design.md). chat_id —
per bot (tool_bindings.config), токен — платформенный (integrations.telegram).
"""

from __future__ import annotations

from typing import Any, ClassVar

from db.contacts import get_contact
from integrations.telegram import TelegramNotConfiguredError, send_message

from .base import ToolContext, ToolExecutionResult

_MISSING_CHAT_ID_ERROR = "Лиды в Telegram не настроены для этого бота (нет chat_id)."
_NOT_CONFIGURED_ERROR = "Лиды в Telegram не настроены на платформе (нет TELEGRAM_BOT_TOKEN)."
_SEND_FAILED_ERROR = "Не удалось отправить заявку в Telegram."
_SUCCESS_MESSAGE = "Заявка отправлена менеджерам."


def _format_lead_message(client_name: str, phone: str, details: str, wa_link: str | None) -> str:
    """Эталон V1 (sendToTelegramGroup) — нейтральный текст, не привязанный
    к нише клиента (в архиве было под конкретный бизнес каждой копии).
    wa_link — None только если у контакта почему-то нет wa_id (LID-only,
    редкий переходный случай FEATURES.md 9.2) — тогда строку ссылки не
    добавляем вовсе, а не рендерим невалидный Markdown-URL."""
    parts = [
        "*Новая заявка*",
        "",
        f"*Клиент:* {client_name}",
        f"*Телефон:* `{phone}`",
        f"*Детали:* {details}",
    ]
    if wa_link:
        parts += ["", f"[Написать в WhatsApp]({wa_link})"]
    return "\n".join(parts)


class TelegramLeadTool:
    name = "send_telegram_lead"
    description = "Отправляет заявку клиента менеджерам в Telegram-группу."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {"type": "string", "description": "Имя клиента"},
            "phone_number": {
                "type": "string",
                "description": (
                    "Номер телефона клиента, если он назвал ДРУГОЙ номер, не тот, "
                    "с которого пишет в WhatsApp. Если не называл — не заполнять."
                ),
            },
            "details": {
                "type": "string",
                "description": "Что интересует клиента, контекст диалога",
            },
        },
        "required": ["client_name", "details"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        chat_id = ctx.config.get("chat_id")
        if not chat_id:
            return ToolExecutionResult(content=_MISSING_CHAT_ID_ERROR)

        async with ctx.session_factory() as session:
            contact = await get_contact(session, ctx.contact_id)

        wa_id = contact.wa_id if contact is not None else None
        phone = str(arguments.get("phone_number") or wa_id or "не указан")
        client_name = str(arguments.get("client_name", ""))
        details = str(arguments.get("details", ""))
        wa_link = f"https://wa.me/{wa_id}" if wa_id else None

        message = _format_lead_message(client_name, phone, details, wa_link)

        try:
            await send_message(str(chat_id), message)
        except TelegramNotConfiguredError:
            return ToolExecutionResult(content=_NOT_CONFIGURED_ERROR)
        except Exception:
            return ToolExecutionResult(content=_SEND_FAILED_ERROR)

        return ToolExecutionResult(content=_SUCCESS_MESSAGE)
