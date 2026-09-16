"""Волна 4: выбор модели per bot (bots.settings["model"]) — бот без этой
настройки (все ранее существующие) не меняет поведение, платформенный
OPENAI_MODEL используется как раньше.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

from pipeline.conftest import docker_available

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _FakeStorage:
    def __init__(self, data: bytes | None = None) -> None:
        self._data = data

    async def get(self, key: str) -> bytes:
        assert self._data is not None
        return self._data


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    model: str | None = None,
    image_prompt: str | None = None,
    pdf_prompt: str | None = None,
) -> uuid.UUID:
    settings: dict[str, object] = {"batch_timeout_seconds": 0.02}
    if model is not None:
        settings["model"] = model
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            image_prompt=image_prompt,
            pdf_prompt=pdf_prompt,
            timezone="Asia/Bishkek",
            settings=settings,
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _text_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Привет",
        "ts": 1756800000000,
    }


def _image_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-img-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "",
        "media_type": "image",
        "storage_key": f"bots/{bot_id}/media/wamsg-img-1",
        "mime_type": "image/jpeg",
        "size_bytes": 123,
        # fetch_recent_history фильтрует по реальному 24ч окну от текущего
        # времени (см. память fetch-recent-history-24h-window-gotcha) —
        # _reply_with_vision собирает фото пачки именно через эту историю.
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }


def _pdf_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-pdf-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "",
        "media_type": "document",
        "storage_key": f"bots/{bot_id}/media/wamsg-pdf-1",
        "mime_type": "application/pdf",
        "size_bytes": 123,
        "ts": 1756900000000,
    }


async def test_text_reply_uses_bot_configured_model(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_models: list[object] = []

    async def fake_complete(system_prompt: str, history: object, **kwargs: object) -> LLMResult:
        captured_models.append(kwargs.get("model"))
        return LLMResult(text="ответ", tokens_in=1, tokens_out=1, model="gpt-4o")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory, model="gpt-4o")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_text_payload(bot_id), redis, session_factory, _FakeStorage())
        assert captured_models == ["gpt-4o"]
    finally:
        await redis.aclose()


async def test_text_reply_without_configured_model_omits_override(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Регрессия: боты без настроенной модели (все ранее существующие) не
    меняют поведение — платформенный дефолт выбирается самим complete()."""
    captured_models: list[object] = []

    async def fake_complete(system_prompt: str, history: object, **kwargs: object) -> LLMResult:
        captured_models.append(kwargs.get("model"))
        return LLMResult(text="ответ", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_text_payload(bot_id), redis, session_factory, _FakeStorage())
        assert captured_models == [None]
    finally:
        await redis.aclose()


async def test_vision_reply_uses_bot_configured_model(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_models: list[object] = []

    async def fake_complete_with_images(
        system_prompt: str, history: object, caption: str, images: object, **kwargs: object
    ) -> LLMResult:
        captured_models.append(kwargs.get("model"))
        return LLMResult(text="описание", tokens_in=1, tokens_out=1, model="gpt-4o")

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)

    bot_id = await _make_bot(session_factory, model="gpt-4o", image_prompt="Опиши товар.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _image_payload(bot_id), redis, session_factory, _FakeStorage(data=b"fake-jpeg")
        )
        assert captured_models == ["gpt-4o"]
    finally:
        await redis.aclose()


async def test_pdf_reply_uses_bot_configured_model(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_models: list[object] = []
    fixture_pdf = (FIXTURES / "sample.pdf").read_bytes()

    async def fake_complete(system_prompt: str, history: object, **kwargs: object) -> LLMResult:
        captured_models.append(kwargs.get("model"))
        return LLMResult(text="ответ по документу", tokens_in=1, tokens_out=1, model="gpt-4o")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory, model="gpt-4o", pdf_prompt="Изучи документ.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _pdf_payload(bot_id), redis, session_factory, _FakeStorage(data=fixture_pdf)
        )
        assert captured_models == ["gpt-4o"]
    finally:
        await redis.aclose()
