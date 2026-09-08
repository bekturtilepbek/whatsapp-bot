"""Клиент Telegram Bot API (FEATURES.md 4.7) — реальная сеть никогда не
используется, httpx.MockTransport подменяет транспорт целиком.
"""

from __future__ import annotations

import json

import httpx
import pytest
from integrations.telegram import TelegramNotConfiguredError, send_message


def _mock_transport(status_code: int, response_json: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_json)

    return httpx.MockTransport(handler)


async def test_send_message_posts_chat_id_and_text_to_telegram_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    await send_message("12345", "Новая заявка", transport=httpx.MockTransport(handler))

    assert captured["url"] == "https://api.telegram.org/bottest-token/sendMessage"
    assert captured["body"] == {
        "chat_id": "12345",
        "text": "Новая заявка",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


async def test_send_message_raises_when_token_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(TelegramNotConfiguredError):
        await send_message("12345", "текст")


async def test_send_message_raises_on_http_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    transport = _mock_transport(401, {"ok": False, "description": "Unauthorized"})

    with pytest.raises(httpx.HTTPStatusError):
        await send_message("12345", "текст", transport=transport)


async def test_send_message_raises_when_telegram_reports_not_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    transport = _mock_transport(200, {"ok": False, "description": "chat not found"})

    with pytest.raises(RuntimeError, match="chat not found"):
        await send_message("12345", "текст", transport=transport)
