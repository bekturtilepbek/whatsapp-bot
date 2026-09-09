"""Медиа-заглушка (FEATURES.md 2.6): фолбэк-ответ без LLM, без usage_events,
плейсхолдер в истории.
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
    """Заглушка для тестов, которые не доходят до vision-ветки — она никогда
    не должна вызываться, поэтому падает явно, а не тихо возвращает мусор.
    """

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


def _inbound_image_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-photo-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "",
        "media_type": "image",
        "ts": 1756800000000,
    }


async def test_media_message_gets_fallback_reply_without_llm(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для медиа-сообщения")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_image_payload(bot_id), redis, session_factory, _NullStorage())

        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert '"type": "outbound.typing"' in out_entries[0][1]["payload"]
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]

        async with session_factory() as session:
            # БД (testcontainers) общая на весь модуль — фильтруем по своему
            # bot_id и сортируем по ts явно (порядок SELECT без ORDER BY не
            # гарантирован SQL-семантикой).
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
            assert messages[0].content == "[фото]"  # плейсхолдер, не пустая строка
            assert messages[1].content == DEFAULT_MEDIA_FALLBACK_TEXT

            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert usage == []  # LLM не вызывался — нечего учитывать
    finally:
        await redis.aclose()


async def test_media_fallback_text_is_configurable_via_bot_settings(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для медиа-сообщения")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    custom_text = "Мы получили ваше фото, менеджер ответит вручную."
    bot_id = await _make_bot(session_factory, settings={"media_fallback_text": custom_text})
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_image_payload(bot_id), redis, session_factory, _NullStorage())

        out_entries = await redis.xrange("wa:out")
        assert custom_text in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_empty_media_fallback_text_falls_back_to_default(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустая строка в settings — не то же самое, что "ключ не задан", но
    результат должен быть одинаковым: OutboundText требует min_length=1
    (libs/core/src/core/events.py), падать с ValidationError на реальном
    сообщении нельзя (найдено code review настроек бота, 2026-09-09)."""

    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для медиа-сообщения")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory, settings={"media_fallback_text": ""})
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_image_payload(bot_id), redis, session_factory, _NullStorage())

        out_entries = await redis.xrange("wa:out")
        assert consumer_module.DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


def _inbound_image_payload_with_storage(bot_id: uuid.UUID) -> dict[str, object]:
    payload = _inbound_image_payload(bot_id)
    payload.update(
        {
            "wa_msg_id": "wamsg-photo-stored-1",
            "storage_key": f"bots/{bot_id}/media/wamsg-photo-stored-1",
            "mime_type": "image/jpeg",
            "size_bytes": 245760,
        }
    )
    return payload


async def test_media_message_with_storage_key_persists_media_ref(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("LLM не должен вызываться для медиа-сообщения")

    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id), redis, session_factory, _NullStorage()
        )

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
            assert messages[0].media_ref == {
                "storage_key": f"bots/{bot_id}/media/wamsg-photo-stored-1",
                "mime_type": "image/jpeg",
                "size_bytes": 245760,
            }
    finally:
        await redis.aclose()
