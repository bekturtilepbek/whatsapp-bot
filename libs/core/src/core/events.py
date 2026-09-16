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
    quoted_media_type: str | None = None
    media_type: str | None = None
    storage_key: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    ts: int


class OutboundText(BaseModel):
    """Исходящее текстовое сообщение в wa:out."""

    type: Literal["outbound.text"] = "outbound.text"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class OutboundImage(BaseModel):
    """Исходящее изображение в wa:out (FEATURES.md 4.3/4.4 — карточка товара)."""

    type: Literal["outbound.image"] = "outbound.image"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class OutboundDocument(BaseModel):
    """Исходящий файл в wa:out (FEATURES.md 4.8)."""

    type: Literal["outbound.document"] = "outbound.document"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class OutboundVideo(BaseModel):
    """Исходящее видео в wa:out (FEATURES.md 4.9)."""

    type: Literal["outbound.video"] = "outbound.video"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    client_msg_id: str = Field(min_length=1)


class OutboundReaction(BaseModel):
    """Реакция-эмодзи на входящее сообщение клиента, в wa:out (FEATURES.md 9.10)."""

    type: Literal["outbound.reaction"] = "outbound.reaction"
    bot_id: UUID
    chat_id: str = Field(min_length=1)
    reply_to_wa_msg_id: str = Field(min_length=1)
    emoji: str = Field(min_length=1)
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


Event = (
    InboundText
    | OutboundText
    | OutboundImage
    | OutboundDocument
    | OutboundVideo
    | OutboundReaction
    | OutboundTyping
    | SessionStatus
)
