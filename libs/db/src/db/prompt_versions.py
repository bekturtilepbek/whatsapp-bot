"""История промптов бота (FEATURES.md 3.7/3.8) — запись/чтение версий.
Вызывается из db.bots.update_bot при каждом PATCH, меняющем промпт; ничего
не решает про ТЕКУЩИЙ промпт — тот остаётся в Bot.system_prompt/
image_prompt/pdf_prompt, эта таблица только история."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PromptVersion

PromptKind = Literal["main", "image", "pdf"]


async def list_versions(
    session: AsyncSession, bot_id: uuid.UUID, kind: PromptKind
) -> Sequence[PromptVersion]:
    result = await session.execute(
        select(PromptVersion)
        .where(PromptVersion.bot_id == bot_id, PromptVersion.kind == kind)
        .order_by(PromptVersion.created_at.desc())
    )
    return result.scalars().all()


async def record_version_if_changed(
    session: AsyncSession,
    bot_id: uuid.UUID,
    kind: PromptKind,
    body: str,
    author: str = "admin",
) -> None:
    """Пишет новую версию, только если body отличается от последней
    сохранённой — иначе повторный PATCH с тем же текстом (например,
    двойной клик "Сохранить") плодил бы дубли в истории.

    .first() (не .scalar_one_or_none()) — различает "версий ещё не было
    вообще" (None) от "последняя версия существует с body=NULL" (Row с
    row.body is None). Без этого первое сохранение промпта, который когда-то
    был NULL, либо считалось бы "без изменений", либо писалось бы криво.
    """
    result = await session.execute(
        select(PromptVersion.body)
        .where(PromptVersion.bot_id == bot_id, PromptVersion.kind == kind)
        .order_by(PromptVersion.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if row is not None and row.body == body:
        return
    session.add(PromptVersion(bot_id=bot_id, kind=kind, body=body, author=author))
    await session.flush()
