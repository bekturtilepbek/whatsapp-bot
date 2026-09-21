"""Пайплайн Шага 2: дедуп -> фильтры -> contact -> запись входящего -> enabled.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("testcontainers.postgres")
from db.blocked_contacts import add_blocked_number
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline.consumer import _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], enabled: bool = True
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(name="test-bot", enabled=enabled)
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


class _NullStorage:
    """Заглушка для тестов, которые не доходят до vision-ветки — она никогда
    не должна вызываться, поэтому падает явно, а не тихо возвращает мусор.
    """

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


def _inbound_payload(bot_id: uuid.UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "привет",
        "ts": 1756800000000,
    }
    payload.update(overrides)
    return payload


async def _count_messages(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID
) -> int:
    # БД (testcontainers) на весь модуль — считаем строго по своему bot_id,
    # иначе тесты видят строки, оставленные предыдущими тестами того же файла.
    async with session_factory() as session:
        result = await session.execute(select(Message).where(Message.bot_id == bot_id))
        return len(result.scalars().all())


async def test_enabled_bot_writes_incoming_message(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory, bot_id) == 1


async def test_disabled_bot_still_writes_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FEATURES.md: enabled=false -> молчим, но историю пишем."""
    bot_id = await _make_bot(session_factory, enabled=False)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory, bot_id) == 1


async def test_blocked_contact_still_writes_history_but_no_reply(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FEATURES.md 1.5, решение пользователя 2026-09-21: заблокированный
    контакт — та же логика, что и пауза бота выше (принимаем и логируем,
    не отвечаем), а не полная тишина без следа в истории. Реальный сценарий
    чёрного списка — не только спам, но и родные/друзья клиента (бот часто
    подключают на личный номер) — молчаливая потеря их сообщений из истории
    не нужна, легче заметить и разблокировать ошибочно попавший номер.
    Раньше is_blocked отбрасывал событие ДО insert_incoming — сообщение не
    попадало в БД вообще, ни следа."""
    bot_id = await _make_bot(session_factory, enabled=True)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000000")
        await session.commit()

    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory, bot_id) == 1


async def test_duplicate_wa_msg_id_is_not_written_twice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory, bot_id) == 1


async def test_group_chat_event_is_not_written(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    try:
        await _process_entry(
            _inbound_payload(bot_id, chat_id="120363000000000000@g.us"),
            redis,
            session_factory,
            _NullStorage(),
        )
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory, bot_id) == 0


async def test_session_status_event_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory, enabled=True)
    redis = FakeRedis()
    payload = {"type": "session.status", "bot_id": str(bot_id), "status": "open", "ts": 1}
    try:
        await _process_entry(payload, redis, session_factory, _NullStorage())
    finally:
        await redis.aclose()

    assert await _count_messages(session_factory, bot_id) == 0
