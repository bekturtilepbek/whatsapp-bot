"""Юнит-тесты чистой логики эха — без Redis/Docker."""

from __future__ import annotations

import uuid

from worker.echo import _build_echo

BOT_ID = str(uuid.uuid4())


def _inbound(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "inbound.text",
        "bot_id": BOT_ID,
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "привет",
        "ts": 1756800000000,
    }
    base.update(overrides)
    return base


def test_builds_outbound_text_with_same_content() -> None:
    echo = _build_echo(_inbound())
    assert echo is not None
    assert echo["type"] == "outbound.text"
    assert echo["bot_id"] == BOT_ID
    assert echo["chat_id"] == "996700000000@s.whatsapp.net"
    assert echo["text"] == "привет"
    assert echo["client_msg_id"]  # непустой uuid


def test_two_calls_produce_different_client_msg_ids() -> None:
    first = _build_echo(_inbound())
    second = _build_echo(_inbound())
    assert first is not None and second is not None
    assert first["client_msg_id"] != second["client_msg_id"]


def test_from_me_is_not_echoed() -> None:
    assert _build_echo(_inbound(from_me=True)) is None


def test_empty_text_is_not_echoed() -> None:
    assert _build_echo(_inbound(text="")) is None


def test_non_inbound_text_event_is_ignored() -> None:
    session_status = {
        "type": "session.status",
        "bot_id": BOT_ID,
        "status": "open",
        "ts": 1756800000000,
    }
    assert _build_echo(session_status) is None


def test_malformed_payload_returns_none() -> None:
    assert _build_echo({"type": "inbound.text"}) is None
