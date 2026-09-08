"""Клиент Telegram Bot API (FEATURES.md 4.7) — тонкая обёртка над
sendMessage. Токен — платформенный (ADR-007, .env только на серверах),
chat_id — per bot, передаётся вызывающим
(tool_bindings.config, см. libs/tools/telegram_lead.py).
"""

from __future__ import annotations

import os

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT_SECONDS = 10.0


class TelegramNotConfiguredError(Exception):
    """TELEGRAM_BOT_TOKEN не задан в окружении — платформа не настроена
    на отправку уведомлений в Telegram вообще (не путать с тем, что у
    конкретного бота нет chat_id — это отдельная, per-bot ошибка,
    обрабатывается в tools/telegram_lead.py)."""


async def send_message(
    chat_id: str, text: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Бросает исключение при сбое (нет токена, сетевая ошибка, ошибка
    Telegram API) — вызывающий (тулза) решает, как это представить LLM.

    transport — только для тестов (httpx.MockTransport), в проде всегда
    None (реальный транспорт httpx)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN не задан")

    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload.get('description')}")
