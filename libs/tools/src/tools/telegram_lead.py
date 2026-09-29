"""Лид в Telegram-группу (FEATURES.md 4.7) — эталон V1 (sendToTelegramGroup),
generic-набор полей (не привязан к нише клиента, см.
docs/superpowers/specs/2026-09-08-telegram-lead-tool-design.md). chat_id —
per bot (tool_bindings.config), токен — платформенный (integrations.telegram).
"""

from __future__ import annotations

import html
from typing import Any, ClassVar

import structlog
from core.phone import format_phone_for_display
from db.contacts import get_contact
from integrations.telegram import TelegramNotConfiguredError, send_message

from .base import ToolContext, ToolExecutionResult

_MISSING_CHAT_ID_ERROR = "Лиды в Telegram не настроены для этого бота (нет chat_id)."
_NOT_CONFIGURED_ERROR = "Лиды в Telegram не настроены на платформе (нет TELEGRAM_BOT_TOKEN)."
_SEND_FAILED_ERROR = "Не удалось отправить заявку в Telegram."
_SUCCESS_MESSAGE = "Заявка отправлена менеджерам."

logger = structlog.get_logger("tools.telegram_lead")


_DEFAULT_MESSAGE_TEMPLATE = (
    "<b>Новая заявка</b>\n\n"
    "<b>Клиент:</b> {client_name}\n"
    "<b>Телефон:</b> <code>{phone}</code>\n"
    "<b>Детали:</b> {details}"
    "{wa_link}"
)


def _format_lead_message(
    client_name: str, phone: str, details: str, wa_link: str | None, template: str | None = None
) -> str:
    """Эталон V1 (sendToTelegramGroup) — нейтральный текст по умолчанию, не
    привязанный к нише клиента (в архиве было под конкретный бизнес каждой
    копии); владелец бота может переопределить его через
    tool_bindings.config["message_template"] (Волна 4, FEATURES.md 4.7).
    HTML parse_mode + html.escape() на всех интерполируемых полях — client_name/
    details это свободный текст, который LLM извлекает из сообщения клиента;
    Telegram legacy Markdown-режим ломает ВСЮ отправку на несбалансированном
    *_`[ в этом тексте (эталон V1 такого экранирования не делал и был подвержен
    этому классу сбоев — найдено финальным ревью этой ветки).

    wa_link — готовый HTML-фрагмент (с ведущими переводами строк) или пустая
    строка, а не голый URL: None только если у контакта почему-то нет wa_id
    (LID-only, переходный случай FEATURES.md 9.2) — тогда строка ссылки не
    добавляется вовсе, а не рендерит невалидный URL; шаблон (в т.ч.
    дефолтный) просто подставляет {wa_link} куда написал автор шаблона, не
    заботясь об условности этой строки.

    Опечатка в кастомном шаблоне (незнакомый плейсхолдер, несбалансированная
    скобка) не должна ронять отправку заявки — деградируем в дефолтный текст,
    а не бросаем исключение наружу."""
    wa_link_block = (
        f'\n\n<a href="{html.escape(wa_link)}">Написать в WhatsApp</a>' if wa_link else ""
    )
    values = {
        "client_name": html.escape(client_name),
        "phone": html.escape(phone),
        "details": html.escape(details),
        "wa_link": wa_link_block,
    }
    if template:
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError, AttributeError):
            # AttributeError — незнакомый шаблон вида "{client_name.foo}":
            # мини-язык str.format поддерживает атрибутный доступ, а значения
            # здесь простые строки — getattr на несуществующий атрибут кидает
            # AttributeError, не KeyError/IndexError/ValueError (найдено
            # 2026-09-21, задокументировано ранее как известный пробел).
            logger.warning("broken telegram lead message_template, falling back to default")
    return _DEFAULT_MESSAGE_TEMPLATE.format(**values)


class TelegramLeadTool:
    name = "send_telegram_lead"
    description = "Отправляет заявку клиента менеджерам в Telegram-группу."
    side_effecting = True
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
        raw_phone = str(arguments.get("phone_number") or wa_id or "")
        # Единый вид +996… для менеджера, как в V1 (formatPhoneNumber, FEATURES.md 9.1):
        # клиент называет номер как привык ("0700 12 34 56").
        phone = format_phone_for_display(raw_phone) if raw_phone else "не указан"
        client_name = str(arguments.get("client_name", ""))
        details = str(arguments.get("details", ""))
        wa_link = f"https://wa.me/{wa_id}" if wa_id else None
        template = ctx.config.get("message_template")

        message = _format_lead_message(client_name, phone, details, wa_link, template)

        try:
            await send_message(str(chat_id), message)
        except TelegramNotConfiguredError:
            return ToolExecutionResult(content=_NOT_CONFIGURED_ERROR)
        except Exception:
            logger.warning(
                "telegram lead send failed",
                bot_id=str(ctx.bot.id),
                chat_id=str(chat_id),
                exc_info=True,
            )
            return ToolExecutionResult(content=_SEND_FAILED_ERROR)

        return ToolExecutionResult(content=_SUCCESS_MESSAGE)
