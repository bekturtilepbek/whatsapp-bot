"""События передачи диалога менеджеру (FEATURES.md 5.7)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .contacts import find_by_identifier
from .models import HandoffEvent

KIND_STARTED = "started"
KIND_RELEASED_MANUAL = "released_manual"


async def record_handoff_event(
    session: AsyncSession,
    bot_id: uuid.UUID,
    chat_id: str,
    kind: str,
    *,
    contact_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> HandoffEvent:
    """contact_id не передан — ищем best-effort по user-part chat_id (как
    список активных чатов); не нашли — остаётся NULL, chat_id есть всегда."""
    if contact_id is None:
        contact = await find_by_identifier(session, bot_id, chat_id.split("@", 1)[0])
        contact_id = contact.id if contact else None
    event = HandoffEvent(
        bot_id=bot_id,
        chat_id=chat_id,
        contact_id=contact_id,
        kind=kind,
        actor_user_id=actor_user_id,
    )
    session.add(event)
    await session.flush()
    return event
