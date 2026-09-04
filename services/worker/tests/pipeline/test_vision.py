"""Vision-ответ на фото (FEATURES.md 2.1): один вызов LLM с image_prompt как
system prompt, ответ уходит клиенту напрямую. Деградация в медиа-заглушку
при сбое storage/LLM — без падения консюмера и без двойного ответа.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.models import Bot, Message, UsageEvent
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import DEFAULT_MEDIA_FALLBACK_TEXT, _process_entry

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker недоступен в этом окружении"
)


@pytest.fixture(scope="module")
def database_url() -> AsyncIterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="psycopg2") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        yield url


@pytest.fixture
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


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
    image_prompt: str | None = None,
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            image_prompt=image_prompt,
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_image_payload_with_storage(
    bot_id: uuid.UUID, *, text: str = ""
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-vision-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": text,
        "media_type": "image",
        "storage_key": f"bots/{bot_id}/media/wamsg-vision-1",
        "mime_type": "image/jpeg",
        "size_bytes": 12345,
        "ts": 1756900000000,
    }


async def test_bot_with_image_prompt_sends_vision_reply_and_records_usage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete_with_image(
        system_prompt: str,
        history: object,
        caption: str,
        image_bytes: bytes,
        mime_type: str,
        **_: object,
    ) -> LLMResult:
        assert "Опиши товар" in system_prompt  # bot.image_prompt подмешан
        assert image_bytes == b"fake-jpeg-bytes"
        return LLMResult(
            text="На фото синие кроссовки 42 размера.",
            tokens_in=300,
            tokens_out=20,
            model="gpt-4o-mini",
        )

    monkeypatch.setattr(consumer_module, "complete_with_image", fake_complete_with_image)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар на фото клиенту.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=b"fake-jpeg-bytes"),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert "На фото синие кроссовки" in out_entries[1][1]["payload"]

        async with session_factory() as session:
            messages = (
                (
                    await session.execute(
                        select(Message).where(Message.bot_id == bot_id).order_by(Message.ts)
                    )
                )
                .scalars()
                .all()
            )
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "На фото синие кроссовки 42 размера."

            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(usage) == 1  # в отличие от media_fallback — здесь LLM реально вызывался
            assert usage[0].tokens_in == 300
    finally:
        await redis.aclose()


async def test_bot_without_image_prompt_falls_back_and_skips_llm(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("vision LLM не должен вызываться без image_prompt")

    monkeypatch.setattr(consumer_module, "complete_with_image", fail_if_called)

    bot_id = await _make_bot(session_factory, image_prompt=None)  # регрессия — старое поведение
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id), redis, session_factory, _FakeStorage()
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
        raise AssertionError("vision LLM не должен вызываться при сбое storage")

    monkeypatch.setattr(consumer_module, "complete_with_image", fail_if_called)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id),
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


async def test_vision_llm_failure_falls_back_without_crashing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_complete(*args: object, **kwargs: object) -> LLMResult:
        raise TimeoutError("OpenAI vision timed out")

    monkeypatch.setattr(consumer_module, "complete_with_image", failing_complete)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар.")
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id),
            redis,
            session_factory,
            _FakeStorage(data=b"fake-jpeg-bytes"),
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()
