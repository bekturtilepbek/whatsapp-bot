"""Запись и выборка истории диалога."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Message


async def insert_incoming(
    session: AsyncSession,
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    content: str,
    wa_msg_id: str,
    ts: datetime,
    media_ref: dict[str, Any] | None = None,
) -> None:
    """Идемпотентно: редоставка entry консюмер-группой не должна падать
    на UNIQUE(bot_id, wa_msg_id) — тихо игнорируем повтор.
    """
    stmt = (
        insert(Message)
        .values(
            bot_id=bot_id,
            contact_id=contact_id,
            role="user",
            content=content,
            wa_msg_id=wa_msg_id,
            ts=ts,
            media_ref=media_ref,
        )
        .on_conflict_do_nothing(constraint="uq_messages_bot_wa_msg_id")
    )
    await session.execute(stmt)
    await session.flush()


async def insert_outgoing(
    session: AsyncSession,
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    content: str,
) -> int:
    """Ответ ассистента — wa_msg_id нет, UNIQUE(bot_id, wa_msg_id) на NULL не срабатывает.

    ts выставляем на Python-стороне (как и insert_incoming), а не полагаемся
    на server_default=func.now(): внутри одной транзакции now() в Postgres
    заморожен на момент её начала, поэтому ts ответа мог оказаться РАНЬШЕ
    ts входящего сообщения той же транзакции — история сортировалась не по
    реальному порядку записи.

    Возвращает seq вставленной строки — нужен вызывающему коду для
    постановки follow-up-задачи (FEATURES.md 5.5): "было ли что-то новее
    этого сообщения к моменту срабатывания задачи".
    """
    message = Message(
        bot_id=bot_id,
        contact_id=contact_id,
        role="assistant",
        content=content,
        ts=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    return message.seq


async def fetch_recent_history(
    session: AsyncSession,
    contact_id: uuid.UUID,
    window_hours: int = 24,
    limit: int = 50,
) -> list[Message]:
    """Последние `limit` сообщений контакта за `window_hours`, в хронологическом порядке."""
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    stmt = (
        select(Message)
        .where(Message.contact_id == contact_id, Message.ts >= since)
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    rows.reverse()  # выбрали DESC (последние N по seq), отдаём в порядке вставки
    return rows
