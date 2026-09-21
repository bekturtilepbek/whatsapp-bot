"""Матчинг контакта: wa_id ИЛИ lid, без дублей (FEATURES.md 9.2)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Contact


async def match_or_create_contact(
    session: AsyncSession,
    bot_id: uuid.UUID,
    wa_id: str | None,
    lid: str | None,
    name: str | None = None,
) -> Contact:
    """Находит контакт по wa_id ИЛИ lid; при первом появлении второго
    идентификатора — дозаписывает его в ту же строку, не создаёт вторую.

    wa_id-путь атомарен относительно гонки (UNIQUE(bot_id, wa_id) + ON
    CONFLICT). lid-only гонка не защищена constraint'ом — сейчас не
    актуально: Baileys этой версии не отдаёт lid на уровне сообщения
    (см. services/gateway/src/normalize/inbound.ts), путь ждёт будущей волны.
    """
    if wa_id is None and lid is None:
        raise ValueError("match_or_create_contact: нужен хотя бы один из wa_id/lid")

    existing = await _find_existing(session, bot_id, wa_id, lid)
    if existing is not None:
        changed = False
        if wa_id is not None and existing.wa_id is None:
            existing.wa_id = wa_id
            changed = True
        if lid is not None and existing.lid is None:
            existing.lid = lid
            changed = True
        if name is not None and existing.name is None:
            existing.name = name
            changed = True
        if changed:
            await session.flush()
        return existing

    if wa_id is not None:
        # ON CONFLICT покрывает гонку двух параллельных первых сообщений
        # одного нового контакта (UNIQUE(bot_id, wa_id)).
        stmt = (
            insert(Contact)
            .values(bot_id=bot_id, wa_id=wa_id, lid=lid, name=name)
            .on_conflict_do_nothing(constraint="uq_contacts_bot_wa_id")
            .returning(Contact)
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        # Конфликт — кто-то успел раньше; перечитываем актуальную строку.
        created = await _find_existing(session, bot_id, wa_id, lid)
        if created is None:  # pragma: no cover — защитный случай, не должен наступать
            raise RuntimeError("contact insert conflicted but no row found on reread")
        return created

    contact = Contact(bot_id=bot_id, wa_id=wa_id, lid=lid, name=name)
    session.add(contact)
    await session.flush()
    return contact


async def _find_existing(
    session: AsyncSession, bot_id: uuid.UUID, wa_id: str | None, lid: str | None
) -> Contact | None:
    conditions = []
    if wa_id is not None:
        conditions.append(Contact.wa_id == wa_id)
    if lid is not None:
        conditions.append(Contact.lid == lid)
    if not conditions:
        return None

    stmt = select(Contact).where(Contact.bot_id == bot_id)
    stmt = stmt.where(conditions[0] if len(conditions) == 1 else or_(*conditions))
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_contact(session: AsyncSession, contact_id: uuid.UUID) -> Contact | None:
    return await session.get(Contact, contact_id)


async def count_contacts(session: AsyncSession, bot_id: uuid.UUID) -> int:
    """Для стат-плитки "Обзора" бота в кабинете — та же логика индекса, что
    у count_messages (messages.py): bot_id ведущий столбец UNIQUE(bot_id, wa_id)."""
    stmt = select(func.count()).select_from(Contact).where(Contact.bot_id == bot_id)
    result = await session.execute(stmt)
    return result.scalar_one()


async def find_by_identifier(
    session: AsyncSession, bot_id: uuid.UUID, identifier: str
) -> Contact | None:
    """Best-effort поиск контакта по "голому" JID user-part (без @domain) —
    список активных handoff-чатов (bots.py::list_active_chats) знает только
    chat_id из Redis (remoteJid), а контакт матчится/хранится по wa_id/lid
    (9.2). Совпадение не гарантировано на 100% при LID-миграции — это
    подсказка для UI (показать имя вместо голого JID), не авторитетный
    источник."""
    return await _find_existing(session, bot_id, identifier, identifier)
