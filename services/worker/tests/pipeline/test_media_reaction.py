"""Авто-реакция на входящее медиа (FEATURES.md 9.10) — быстрый фидбек до
батчинга/лока/ответа. Без tool loop, без LLM (сознательно урезано —
подтверждено пользователем при брейншторме).
"""

from __future__ import annotations

import json
import uuid

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import DEFAULT_MEDIA_REACTION_EMOJI, _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)

CHAT_ID = "996700000000@s.whatsapp.net"


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], settings: dict[str, object] | None = None
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02, **(settings or {})},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


def _inbound_image_payload(
    bot_id: uuid.UUID, wa_msg_id: str = "wamsg-photo-1"
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": CHAT_ID,
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "",
        "media_type": "image",
        "ts": 1756800000000,
    }


def _inbound_text_payload(bot_id: uuid.UUID, wa_msg_id: str = "wamsg-text-1") -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": CHAT_ID,
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Привет",
        "ts": 1756800000000,
    }


async def test_media_message_publishes_reaction_before_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload(bot_id), redis, session_factory, _NullStorage()
        )

        out_entries = await redis.xrange("wa:out")
        # seen (1.11) публикуется ДО батчинга/лока/ответа — первая в потоке,
        # затем реакция, typing + фолбэк-текст (медиа без image_prompt — заглушка).
        assert len(out_entries) == 4
        assert '"type": "outbound.seen"' in out_entries[0][1]["payload"]
        reaction = json.loads(out_entries[1][1]["payload"])
        assert reaction["type"] == "outbound.reaction"
        assert reaction["chat_id"] == CHAT_ID
        assert reaction["reply_to_wa_msg_id"] == "wamsg-photo-1"
        assert reaction["emoji"] == DEFAULT_MEDIA_REACTION_EMOJI
        assert '"type": "outbound.typing"' in out_entries[2][1]["payload"]
    finally:
        await redis.aclose()


async def test_text_message_does_not_trigger_reaction(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object):
        from llm.client import LLMResult

        return LLMResult(text="Здравствуйте!", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_text_payload(bot_id), redis, session_factory, _NullStorage())

        out_entries = await redis.xrange("wa:out")
        types = [json.loads(e[1]["payload"])["type"] for e in out_entries]
        assert "outbound.reaction" not in types
    finally:
        await redis.aclose()


async def test_media_reaction_disabled_via_settings(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory, settings={"media_reaction_enabled": False})
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload(bot_id), redis, session_factory, _NullStorage()
        )

        out_entries = await redis.xrange("wa:out")
        types = [json.loads(e[1]["payload"])["type"] for e in out_entries]
        assert "outbound.reaction" not in types
        # Остальной фолбэк-путь не сломан отключением реакции.
        assert "outbound.typing" in types
    finally:
        await redis.aclose()


async def test_media_reaction_custom_emoji(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory, settings={"media_reaction_emoji": "🎉"})
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload(bot_id), redis, session_factory, _NullStorage()
        )

        out_entries = await redis.xrange("wa:out")
        reaction = json.loads(out_entries[1][1]["payload"])  # 0=seen, 1=reaction
        assert reaction["emoji"] == "🎉"
    finally:
        await redis.aclose()


async def test_media_reaction_respects_active_handoff(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Менеджер уже ведёт чат вручную — бот молчит целиком (5.1), включая
    реакцию: это тоже "ответ", не должен идти поверх ручного ведения."""
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        manager_payload = {
            "type": "inbound.text",
            "bot_id": str(bot_id),
            "wa_msg_id": "wamsg-manager-1",
            "chat_id": CHAT_ID,
            "sender_wa_id": "996700000000",
            "from_me": True,
            "text": "Уже помогаю",
            "ts": 1756800000000,
        }
        await _process_entry(manager_payload, redis, session_factory, _NullStorage())

        await _process_entry(
            _inbound_image_payload(bot_id, "wamsg-photo-2"), redis, session_factory, _NullStorage()
        )

        assert await redis.xlen("wa:out") == 0  # ни реакции, ни ответа
    finally:
        await redis.aclose()
