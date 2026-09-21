"""Pydantic v2 схемы бота для api."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    phone: str | None
    linked_at: datetime | None
    # Живой статус сессии Baileys (FEATURES.md 6.17) — connecting/qr/open/
    # reconnecting/logged_out, None пока не привязан ни разу. Пишет gateway
    # напрямую при каждом connection.update, см. Bot.status в libs/db/src/db/models.py.
    status: str | None
    last_seen: datetime | None
    system_prompt: str
    image_prompt: str | None
    pdf_prompt: str | None
    timezone: str
    settings: dict[str, Any]
    created_at: datetime


class BotCreate(BaseModel):
    name: str


class BotPatch(BaseModel):
    """Все поля опциональны — трогаем только реально переданные (exclude_unset)."""

    name: str | None = None
    enabled: bool | None = None
    system_prompt: str | None = None
    image_prompt: str | None = None
    pdf_prompt: str | None = None
    settings: dict[str, Any] | None = None


class BotStats(BaseModel):
    """Стат-плитки вкладки "Обзор" в кабинете — отдельная ручка (не поле
    BotOut), чтобы не вешать два лишних COUNT(*) на каждый GET /bots
    (список ботов рендерит их пачкой, детальная статистика ему не нужна)."""

    messages_count: int
    contacts_count: int


class ActiveChatOut(BaseModel):
    """Один активный (перехваченный менеджером) чат — вкладка "Активные
    чаты". chat_id — сырой WhatsApp JID (remoteJid), contact_* — best-effort
    подсказка из БД (см. db.contacts.find_by_identifier), может быть пустой."""

    chat_id: str
    contact_name: str | None = None
    contact_phone: str | None = None
    # Сколько секунд осталось до авто-возврата — None если TTL почему-то не
    # читается (ключ истёк между SCAN и TTL, защитный случай).
    auto_release_in_seconds: int | None = None
