"""Проверка config тулзы при включении (POST /bots/{id}/tools).

Во время работы тулзы плохой config не роняет диалог (тулза отвечает LLM
ошибкой), но и не работает: например, мусорный chat_id у Telegram-лидов
молча терял каждую заявку, а песочница эту тулзу глушит — владелец узнавал
о проблеме только по потерянным клиентам (2026-09-28). Отсекаем на входе.
"""

from __future__ import annotations

import re
from typing import Any

# Telegram: числовой id чата/группы (группы — отрицательные) или @username.
_TELEGRAM_CHAT_ID_RE = re.compile(r"^(-?\d{5,20}|@[A-Za-z0-9_]{5,32})$")


def validate_tool_config(tool_name: str, config: dict[str, Any]) -> str | None:
    """None — config годен; иначе текст ошибки для 422."""
    if tool_name == "send_telegram_lead":
        chat_id = str(config.get("chat_id", "")).strip()
        if not _TELEGRAM_CHAT_ID_RE.match(chat_id):
            return "ID группы Telegram — число (например -1001234567890) или @username"
    return None
