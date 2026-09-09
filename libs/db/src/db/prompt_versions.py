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
        .order_by(PromptVersion.seq.desc())
    )
    return result.scalars().all()


async def record_version_if_changed(
    session: AsyncSession,
    bot_id: uuid.UUID,
    kind: PromptKind,
    body: str,
    *,
    baseline: str | None = None,
    author: str = "admin",
) -> None:
    """Пишет новую версию, только если body отличается от последней
    сохранённой — иначе повторный PATCH с тем же текстом (например,
    двойной клик "Сохранить") плодил бы дубли в истории.

    baseline — значение, которое уже лежало в Bot.system_prompt/
    image_prompt/pdf_prompt ДО этого PATCH (вызывающий код — update_bot —
    передаёт уже загруженный объект бота, лишнего запроса нет). Нужно для
    самой первой версии этого kind: без baseline первая правка через
    admin-web писала бы в историю только НОВЫЙ текст, а то, что было ДО
    неё (например, промпт, заданный SQL при заведении бота — онбординга
    из UI ещё нет, 6.20), терялось бы безвозвратно — "откат" на первой же
    правке был бы no-op, хотя ради ровно этого сценария FEATURES.md 3.8
    и заведён.

    .first() (не .scalar_one_or_none()) — различает "версий ещё не было
    вообще" (None) от "последняя версия существует с body=NULL" (Row с
    row.body is None). Без этого первое сохранение промпта, который когда-то
    был NULL, либо считалось бы "без изменений", либо писалось бы криво.

    order_by(seq), не created_at — created_at = func.now() фиксируется на
    начало транзакции в Postgres; baseline- и новая версия ниже могут
    вставиться в одной транзакции с идентичным created_at (см. models.py).
    """
    result = await session.execute(
        select(PromptVersion.body)
        .where(PromptVersion.bot_id == bot_id, PromptVersion.kind == kind)
        .order_by(PromptVersion.seq.desc())
        .limit(1)
    )
    row = result.first()

    if row is None:
        # Первая версия этого kind вообще.
        if baseline == body:
            # Реального изменения нет: либо запрошенное значение совпадает
            # с тем, что уже лежит в bots.* (baseline не None), либо
            # backfill'ить нечего (baseline is None — kind никогда не был
            # настроен, а body всегда непустая строка, так что None==body
            # тут невозможно).
            return
        if baseline is not None:
            # backfill: то, что было ДО этого PATCH, тоже становится версией.
            session.add(PromptVersion(bot_id=bot_id, kind=kind, body=baseline, author=author))
            await session.flush()
        session.add(PromptVersion(bot_id=bot_id, kind=kind, body=body, author=author))
        await session.flush()
        return

    if row.body == body:
        return
    session.add(PromptVersion(bot_id=bot_id, kind=kind, body=body, author=author))
    await session.flush()
