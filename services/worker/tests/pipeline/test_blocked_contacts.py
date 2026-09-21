"""Чёрный список (FEATURES.md 1.5): сообщение от заблокированного номера
не получает ответа, но записывается в историю (решение пользователя
2026-09-21 — тот же принцип, что и у паузы бота: реальный сценарий чёрного
списка часто не спам, а родные/друзья клиента, чей номер бот подключён на
личный телефон, молчаливая потеря их сообщений из истории не нужна).
Менеджер (from_me) не блокируется.
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
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(
    bot_id: uuid.UUID, *, from_me: bool = False, wa_msg_id: str = "wamsg-1"
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": from_me,
        "text": "Здравствуйте!",
        "ts": 1756800000000,
    }


async def test_message_from_blocked_number_is_recorded_but_not_replied(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для заблокированного номера")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000000")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        assert await redis.xlen("wa:out") == 0  # ни ответа, ни typing
        async with session_factory() as session:
            messages = (
                (await session.execute(select(Message).where(Message.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(messages) == 1  # история пишется, как и при паузе бота
            assert messages[0].role == "user"
    finally:
        await redis.aclose()


async def test_message_from_non_blocked_number_is_unaffected(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from llm.client import LLMResult

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996799999999")  # другой номер
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert await redis.xlen("wa:out") == 2  # typing + text — обычный ответ
    finally:
        await redis.aclose()


async def test_manager_message_from_blocked_number_is_not_blocked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000000")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_payload(bot_id, from_me=True, wa_msg_id="wamsg-manager-1"),
            redis,
            session_factory,
            _NullStorage(),
        )
        async with session_factory() as session:
            messages = (
                (await session.execute(select(Message).where(Message.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(messages) == 1  # ручное сообщение менеджера записалось как обычно
            assert messages[0].role == "assistant"
    finally:
        await redis.aclose()
