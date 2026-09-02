"""SQLAlchemy 2.0 async модели ядра. Блок 1 STAGE1_CORE: bots, bot_sessions.

Остальные таблицы из ARCHITECTURE.md §5 (contacts, messages, usage_events...)
добавляются по мере фаз — см. STAGE1_CORE Блок 2/3.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func, text
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
