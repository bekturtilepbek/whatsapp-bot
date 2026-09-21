"""Транскрипция голосовых (FEATURES.md 2.2): ffmpeg -> mp3 -> Whisper,
транскрипт пишется прямо в messages.content, дальше обычный _reply()
(каталог, тулзы) без единой правки в нём — в отличие от vision/pdf,
отдельного "текущего хода" не строим. Деградация в медиа-заглушку при
сбое storage/ffmpeg/STT — без падения консюмера и без двойного ответа.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import DEFAULT_MEDIA_FALLBACK_TEXT, _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _FakeStorage:
    def __init__(
        self, data: bytes | None = None, data_by_key: dict[str, bytes] | None = None
    ) -> None:
        self._data = data
        self._data_by_key = data_by_key or {}

    async def get(self, key: str) -> bytes:
        if key in self._data_by_key:
            return self._data_by_key[key]
        assert self._data is not None
        return self._data


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


def _voice_payload(
    bot_id: uuid.UUID, wa_msg_id: str, storage_key: str, *, text: str = ""
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": text,
        "media_type": "audio",
        "storage_key": storage_key,
        "mime_type": "audio/ogg; codecs=opus",
        "size_bytes": 123,
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }


async def test_voice_message_is_transcribed_and_replied_via_normal_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_convert_to_mp3(raw: bytes) -> bytes:
        assert raw == b"ogg-bytes"
        return b"mp3-bytes"

    async def fake_transcribe_audio(audio_bytes: bytes, filename: str, **_: object) -> str:
        assert audio_bytes == b"mp3-bytes"
        return "Здравствуйте, есть доставка?"

    captured_histories: list[list[object]] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_histories.append(list(history))
        return LLMResult(text="Да, доставляем.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "convert_to_mp3", fake_convert_to_mp3)
    monkeypatch.setattr(consumer_module, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    storage = _FakeStorage(data_by_key={"bots/x/media/voice-1": b"ogg-bytes"})
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _voice_payload(bot_id, "wamsg-voice-1", "bots/x/media/voice-1"),
            redis,
            session_factory,
            storage,
        )
        out_entries = await redis.xrange("wa:out")
        assert "Да, доставляем." in out_entries[-1][1]["payload"]

        async with session_factory() as session:
            messages = (
                (
                    await session.execute(
                        select(Message).where(Message.bot_id == bot_id).order_by(Message.seq)
                    )
                )
                .scalars()
                .all()
            )
            # Транскрипт заменил плейсхолдер [голосовое сообщение] в истории.
            assert messages[0].content == "Здравствуйте, есть доставка?"
    finally:
        await redis.aclose()


async def test_multiple_voice_messages_in_one_batch_are_all_transcribed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcripts_by_key = {
        "bots/x/media/voice-1": "Первое сообщение.",
        "bots/x/media/voice-2": "Второе сообщение.",
    }

    async def fake_convert_to_mp3(raw: bytes) -> bytes:
        return raw

    async def fake_transcribe_audio(audio_bytes: bytes, filename: str, **_: object) -> str:
        for key, transcript in transcripts_by_key.items():
            if audio_bytes == key.encode():
                return transcript
        raise AssertionError("unexpected audio bytes")

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "convert_to_mp3", fake_convert_to_mp3)
    monkeypatch.setattr(consumer_module, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    payload1 = _voice_payload(bot_id, "wamsg-voice-1", "bots/x/media/voice-1")
    payload1["ts"] = now_ms
    payload2 = _voice_payload(bot_id, "wamsg-voice-2", "bots/x/media/voice-2")
    payload2["ts"] = now_ms
    storage = _FakeStorage(
        data_by_key={
            "bots/x/media/voice-1": b"bots/x/media/voice-1",
            "bots/x/media/voice-2": b"bots/x/media/voice-2",
        }
    )

    redis = FakeRedis(decode_responses=True)
    try:
        leader_task = asyncio.create_task(
            _process_entry(payload1, redis, session_factory, storage)
        )
        await asyncio.sleep(0.005)
        await _process_entry(payload2, redis, session_factory, storage)
        await leader_task

        async with session_factory() as session:
            messages = (
                (
                    await session.execute(
                        select(Message).where(Message.bot_id == bot_id).order_by(Message.seq)
                    )
                )
                .scalars()
                .all()
            )
            contents = [m.content for m in messages if m.role == "user"]
            assert contents == ["Первое сообщение.", "Второе сообщение."]
    finally:
        await redis.aclose()


async def test_transcription_failure_falls_back_without_crashing_or_double_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_convert_to_mp3(raw: bytes) -> bytes:
        raise RuntimeError("ffmpeg is not installed")

    async def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("transcribe_audio не должен вызываться после сбоя конвертации")

    monkeypatch.setattr(consumer_module, "convert_to_mp3", failing_convert_to_mp3)
    monkeypatch.setattr(consumer_module, "transcribe_audio", fail_if_called)

    bot_id = await _make_bot(session_factory)
    storage = _FakeStorage(data=b"ogg-bytes")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _voice_payload(bot_id, "wamsg-voice-1", "bots/x/media/voice-1"),
            redis,
            session_factory,
            storage,
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 4  # seen+reaction+typing+text, не два ответа
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[-1][1]["payload"]

        async with session_factory() as session:
            messages = (
                (await session.execute(select(Message).where(Message.bot_id == bot_id)))
                .scalars()
                .all()
            )
            # Плейсхолдер остался — транскрипция не засчиталась.
            user_messages = [m for m in messages if m.role == "user"]
            assert user_messages[0].content == "[голосовое сообщение]"
    finally:
        await redis.aclose()
