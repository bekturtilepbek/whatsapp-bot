"""Смоук всего пайплайна Шага 5 на фейковом транспорте: inbound.text ->
(мок LLM) -> outbound.typing + outbound.text в wa:out, обе стороны в
messages, запись в usage_events. Отдельно: сбой LLM не роняет консюмер
и снимает лок.

DB — testcontainers-postgres (нужны реальные constraints/relations); Redis —
fakeredis (тот же выбор, что и для dedup/batching/lock-тестов этого блока:
достаточно верная семантика команд, без лишнего Docker-контейнера).
"""

from __future__ import annotations

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
from worker.pipeline.consumer import _process_entry
from worker.pipeline.lock import _lock_key

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
            env={"DATABASE_URL": url},
        )
        yield url


@pytest.fixture
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — вежливый ассистент магазина.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
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


async def test_inbound_text_produces_reply_history_and_usage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        assert "Ты — вежливый ассистент" in system_prompt
        return LLMResult(text="Да, доставка есть.", tokens_in=42, tokens_out=7, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory)

        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert '"type": "outbound.typing"' in out_entries[0][1]["payload"]
        assert '"type": "outbound.text"' in out_entries[1][1]["payload"]
        assert "Да, доставка есть." in out_entries[1][1]["payload"]

        async with session_factory() as session:
            messages = (await session.execute(select(Message))).scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "Да, доставка есть."

            usage = (await session.execute(select(UsageEvent))).scalars().all()
            assert len(usage) == 1
            assert usage[0].tokens_in == 42
            assert usage[0].tokens_out == 7
            assert usage[0].model == "gpt-4o-mini"

        assert await redis.get(_lock_key(str(bot_id), "996700000000@s.whatsapp.net")) is None
    finally:
        await redis.aclose()


async def test_llm_failure_does_not_crash_and_releases_lock(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_complete(*args: object, **kwargs: object) -> LLMResult:
        raise RuntimeError("OpenAI недоступен")

    monkeypatch.setattr(consumer_module, "complete", failing_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory)  # не должно упасть

        assert await redis.xlen("wa:out") == 0
        assert await redis.get(_lock_key(str(bot_id), "996700000000@s.whatsapp.net")) is None

        async with session_factory() as session:
            messages = (await session.execute(select(Message))).scalars().all()
            assert [m.role for m in messages] == ["user"]  # ответа нет
            usage = (await session.execute(select(UsageEvent))).scalars().all()
            assert usage == []
    finally:
        await redis.aclose()
