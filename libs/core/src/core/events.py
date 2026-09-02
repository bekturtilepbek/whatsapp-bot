"""Pydantic-модели контракта событий v1.

Источник истины — docs/contracts/events.schema.json. Модели написаны вручную
и сверяются с JSON Schema тестом (tests/test_events_contract.py), а не
генерируются, чтобы иметь единообразный питонический API.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InboundText(BaseModel):
    """Входящее сообщение из wa:in."""

    type: Literal["inbound.text"] = "inbound.text"
    bot_id: UUID
    wa_msg_id: str = Field(min_length=1)
    chat_id: str = Field(min_length=1)
    sender_wa_id: str = Field(min_length=1)
    sender_lid: str | None = None
    from_me: bool
    text: str
    quoted_text: str | None = None
    media_type: str | None = None
    ts: int


class OutboundText(BaseModel):
    """Исходящее текстовое сообщение в wa:out."""

    type: Literal["outbound.text"] = "outbound.text"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class OutboundTyping(BaseModel):
    """Индикатор "печатает" в wa:out."""

    type: Literal["outbound.typing"] = "outbound.typing"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class SessionStatus(BaseModel):
    """Статус сессии Baileys (публикуется gateway в wa:in)."""

    type: Literal["session.status"] = "session.status"
    bot_id: UUID
    status: Literal["connecting", "qr", "open", "reconnecting", "logged_out"]
    ts: int


Event = InboundText | OutboundText | OutboundTyping | SessionStatus
