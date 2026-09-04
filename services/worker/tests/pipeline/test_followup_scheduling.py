"""Постановка follow-up-задачи после настоящего LLM-ответа (FEATURES.md
5.5) — НЕ после медиа-заглушки. Сбой постановки не должен портить уже
отправленный клиенту ответ.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine, make_session_factory
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

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


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


class _FakeCeleryApp:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._error = error

    def send_task(self, name: str, args: list[object], eta: datetime) -> None:
        if self._error is not None:
            raise self._error
        self.calls.append({"name": name, "args": args, "eta": eta})


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], **settings: object
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02, **settings},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Здравствуйте, у вас есть доставка?",
        "ts": 1756800000000,
    }


async def test_reminder_scheduled_after_llm_reply_when_enabled(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)

    bot_id = await _make_bot(
        session_factory, reminder_enabled=True, reminder_delay_minutes=45
    )
    redis = FakeRedis(decode_responses=True)
    try:
        before = datetime.now(UTC)
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        assert len(fake_celery.calls) == 1
        call = fake_celery.calls[0]
        assert call["name"] == "tasks.followup.send_reminder"
        bot_id_arg, _contact_id_arg, chat_id_arg, after_seq_arg = call["args"]  # type: ignore[misc]
        assert bot_id_arg == str(bot_id)
        assert chat_id_arg == "996700000000@s.whatsapp.net"
        assert isinstance(after_seq_arg, int)
        eta = call["eta"]
        assert isinstance(eta, datetime)
        expected = before + timedelta(minutes=45)
        assert abs((eta - expected).total_seconds()) < 5
    finally:
        await redis.aclose()


async def test_reminder_not_scheduled_when_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)

    bot_id = await _make_bot(session_factory)  # reminder_enabled отсутствует
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert fake_celery.calls == []
    finally:
        await redis.aclose()


async def test_scheduling_failure_does_not_break_the_reply(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    monkeypatch.setattr(
        consumer_module, "celery_app", _FakeCeleryApp(error=RuntimeError("redis down"))
    )

    bot_id = await _make_bot(session_factory, reminder_enabled=True)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2  # ответ клиенту всё равно ушёл
        assert "Да, есть." in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()
