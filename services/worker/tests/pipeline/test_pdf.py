"""PDF-ответ на документ (FEATURES.md 2.4): текст извлекается ДО вызова LLM
(обычный complete(), не мультимодальный вызов — в отличие от vision),
pdf_prompt как system prompt, ответ уходит клиенту напрямую. Деградация в
медиа-заглушку при сбое storage/извлечения/LLM — без падения консюмера и
без двойного ответа. Follow-up планируется так же, как после vision/текста —
это настоящий LLM-ответ.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot, Message, UsageEvent
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import DEFAULT_MEDIA_FALLBACK_TEXT, _process_entry

from pipeline.conftest import docker_available

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _FakeStorage:
    def __init__(self, data: bytes | None = None, error: Exception | None = None) -> None:
        self._data = data
        self._error = error

    async def get(self, key: str) -> bytes:
        if self._error is not None:
            raise self._error
        assert self._data is not None
        return self._data


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pdf_prompt: str | None = None,
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            pdf_prompt=pdf_prompt,
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_pdf_payload_with_storage(bot_id: uuid.UUID, *, text: str = "") -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-pdf-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": text,
        "media_type": "document",
        "storage_key": f"bots/{bot_id}/media/wamsg-pdf-1",
        "mime_type": "application/pdf",
        "size_bytes": 12345,
        "ts": 1756900000000,
    }


async def test_bot_with_pdf_prompt_sends_pdf_reply_and_records_usage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: object, **_: object) -> LLMResult:
        assert "Изучи документ" in system_prompt  # bot.pdf_prompt подмешан
        return LLMResult(
            text="В договоре указан срок аренды 12 месяцев.",
            tokens_in=500,
            tokens_out=15,
            model="gpt-4o-mini",
        )

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory, pdf_prompt="Изучи документ и ответь клиенту.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_pdf_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=(FIXTURES / "sample.pdf").read_bytes()),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert "срок аренды 12 месяцев" in out_entries[1][1]["payload"]

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
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "В договоре указан срок аренды 12 месяцев."

            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(usage) == 1  # LLM реально вызывался, в отличие от media_fallback
            assert usage[0].tokens_in == 500
    finally:
        await redis.aclose()


async def test_bot_without_pdf_prompt_falls_back_and_skips_llm(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("PDF LLM не должен вызываться без pdf_prompt")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory, pdf_prompt=None)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_pdf_payload_with_storage(bot_id), redis, session_factory, _FakeStorage()
        )
        out_entries = await redis.xrange("wa:out")
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
        async with session_factory() as session:
            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert usage == []
    finally:
        await redis.aclose()


async def test_storage_read_failure_falls_back_without_crashing_or_double_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("PDF LLM не должен вызываться при сбое storage")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory, pdf_prompt="Изучи документ.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_pdf_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(error=OSError("disk unavailable")),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2  # ровно один typing+text, не два ответа
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
        async with session_factory() as session:
            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert usage == []
    finally:
        await redis.aclose()


async def test_pdf_without_text_layer_falls_back_without_crashing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("PDF LLM не должен вызываться при пустом текстовом слое")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory, pdf_prompt="Изучи документ.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_pdf_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=(FIXTURES / "no_text_layer.pdf").read_bytes()),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_pdf_llm_failure_falls_back_without_crashing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_complete(*args: object, **kwargs: object) -> LLMResult:
        raise TimeoutError("OpenAI timed out")

    monkeypatch.setattr(consumer_module, "complete", failing_complete)

    bot_id = await _make_bot(session_factory, pdf_prompt="Изучи документ.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_pdf_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=(FIXTURES / "sample.pdf").read_bytes()),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()
