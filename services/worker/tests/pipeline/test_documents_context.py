"""Список файлов в system prompt (FEATURES.md 4.8/4.9) — реальный
сценарий через _process_entry, как test_catalog.py: мок только на
границе LLM (consumer_module.complete), всё остальное — реальный
Postgres/fakeredis.
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
from db.models import Bot, Document
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
        raise NotImplementedError("этот тест не читает из Storage")


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot", enabled=True, system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek", settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(bot_id: uuid.UUID) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "livecheck-docs-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Пришлите прайс",
        "ts": 1756800000000,
    }


async def test_documents_appear_in_system_prompt_sent_to_llm(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot_id, filename="price-list.pdf", storage_key="k",
                mime_type="application/pdf",
            )
        )
        await session.commit()

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="Сейчас пришлю.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert len(captured_system_prompts) == 1
        assert "ДОСТУПНЫЕ ФАЙЛЫ" in captured_system_prompts[0]
        assert "- price-list.pdf" in captured_system_prompts[0]
    finally:
        await redis.aclose()


async def test_empty_documents_sends_the_empty_documents_message(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    bot_id = await _make_bot(session_factory)  # ни одного файла

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert "Файлов пока нет." in captured_system_prompts[0]
    finally:
        await redis.aclose()
