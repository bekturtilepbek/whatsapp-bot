"""SQLAlchemy 2.0 async модели ядра.

Блок 1 STAGE1_CORE: bots, bot_sessions. Блок 2: contacts, messages,
usage_events. Остальное из ARCHITECTURE.md §5 — по мере фаз (Блок 3+).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Bot(Base):
    """Бот = запись в БД (ADR-005). Ничего per-bot в коде — только здесь."""

    __tablename__ = "bots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    # Отдельный system prompt для vision-ответа на фото (FEATURES.md 2.1).
    # NULL = vision не настроен у этого бота — падаем в старую медиа-заглушку.
    # Без server_default: NULL — осознанное состояние "не настроено", в
    # отличие от system_prompt, где пустая строка была бы валидным (хоть и
    # бесполезным) промптом.
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Дефолт по прежней практике продукта (FEATURES.md 9.4) — единственный
    # известный рынок на старте; поле переопределяется per bot.
    timezone: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'Asia/Bishkek'")
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[BotSession | None] = relationship(
        back_populates="bot", uselist=False, cascade="all, delete-orphan"
    )


class BotSession(Base):
    """Auth-state сессии Baileys — в Postgres (ADR-006), не в памяти процесса.

    bot_id — одновременно PK и FK: у бота ровно одна сессия.
    """

    __tablename__ = "bot_sessions"

    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )
    auth_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bot: Mapped[Bot] = relationship(back_populates="session")


class Contact(Base):
    """Контакт = wa_id + lid (FEATURES.md 9.2): WhatsApp мигрирует на LID,
    без второго поля история человека раздваивается. Матчинг — по wa_id ИЛИ
    lid, см. db.contacts.match_or_create_contact.
    """

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("bot_id", "wa_id", name="uq_contacts_bot_wa_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    wa_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lid: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Message(Base):
    """История диалога. wa_msg_id — только у сообщений клиента (role=user);
    у ответов ассистента NULL (свой client_msg_id живёт в Redis-идемпотентности
    gateway, не здесь) — UNIQUE(bot_id, wa_msg_id) NULL с NULL не конфликтует.
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("bot_id", "wa_msg_id", name="uq_messages_bot_wa_msg_id"),
        Index("ix_messages_contact_id_ts", "contact_id", "ts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    wa_msg_id: Mapped[str | None] = mapped_column(String, nullable=True)
    media_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UsageEvent(Base):
    """Учёт токенов и стоимости вызовов LLM (FEATURES.md 3.9 — упрощённая
    локальная оценка cost вместо OpenAI usage API, см. libs/llm/pricing.py).
    """

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BlockedContact(Base):
    """Чёрный список номеров (FEATURES.md 1.5). Матчинг — по тому же
    "сырому" wa_id (без "+"), что и Contact.wa_id/дедуп/handoff, НЕ по
    нормализованному телефону (эталон — V1, ignored_numbers).
    """

    __tablename__ = "blocked_contacts"
    __table_args__ = (
        UniqueConstraint("bot_id", "phone", name="uq_blocked_contacts_bot_phone"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
