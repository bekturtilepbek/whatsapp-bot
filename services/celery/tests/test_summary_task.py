"""refresh_contact_summary / _refresh_summary_async (FEATURES.md 6.13): при
срабатывании перепроверяет условия — бот включён, контакт не в ЧС, после
постановки никто не писал, диалог не пустой, это не повторная доставка.

Тело тестируем напрямую (DI redis/session_factory/analyze) — реальный вызов
OpenAI и Celery-воркер проверяются живым прогоном на docker compose.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("testcontainers.postgres")
from db.blocked_contacts import add_blocked_number
from db.contacts import get_contact, match_or_create_contact, set_contact_analysis
from db.engine import make_engine, make_session_factory
from db.messages import insert_incoming, insert_outgoing, latest_message_seq
from db.models import Bot, UsageEvent
from fakeredis.aioredis import FakeRedis
from llm.summary import Analysis, AnalysisOutcome, SummaryMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
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
    return make_session_factory(make_engine(database_url))


class _FakeAnalyze:
    """Подмена llm.summary.analyze_conversation: запоминает вызовы."""

    def __init__(
        self,
        outcome: AnalysisOutcome | None = None,
        error: Exception | None = None,
    ) -> None:
        self.outcome = outcome or AnalysisOutcome(
            analysis=Analysis(summary="Клиент интересуется доставкой.", temperature="warm"),
            tokens_in=1200,
            tokens_out=120,
            model="gpt-6-luna",
        )
        self.error = error
        self.calls: list[list[SummaryMessage]] = []

    async def __call__(self, messages: list[SummaryMessage]) -> AnalysisOutcome:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.outcome


async def _dialog(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    enabled: bool = True,
    turns: int = 2,
    wa_id: str = "996700000001",
) -> tuple[uuid.UUID, uuid.UUID, int]:
    """Бот + контакт + диалог; возвращает (bot_id, contact_id, seq последнего)."""
    async with session_factory() as session:
        bot = Bot(name="summary-bot", enabled=enabled)
        session.add(bot)
        await session.flush()
        contact = await match_or_create_contact(session, bot.id, wa_id=wa_id, lid=None)
        seq = 0
        for i in range(turns):
            await insert_incoming(
                session,
                bot.id,
                contact.id,
                f"вопрос {i}",
                f"w-{uuid.uuid4().hex}",
                datetime.now(UTC),
            )
            seq = await insert_outgoing(session, bot.id, contact.id, f"ответ {i}")
        await session.commit()
        return bot.id, contact.id, seq


async def _run(
    session_factory: async_sessionmaker[AsyncSession],
    redis: FakeRedis,
    analyze: _FakeAnalyze,
    bot_id: uuid.UUID,
    contact_id: uuid.UUID,
    seq: int,
) -> None:
    from tasks.summary import _refresh_summary_async

    await _refresh_summary_async(
        redis, session_factory, str(bot_id), str(contact_id), seq, analyze=analyze
    )


async def test_writes_analysis_and_records_usage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory)
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    assert len(analyze.calls) == 1
    # хронологический диалог, роли как в БД
    assert [(m.role, m.content) for m in analyze.calls[0]][:2] == [
        ("user", "вопрос 0"),
        ("assistant", "ответ 0"),
    ]
    async with session_factory() as session:
        contact = await get_contact(session, contact_id)
        assert contact is not None
        assert contact.summary == "Клиент интересуется доставкой."
        assert contact.temperature == "warm"
        assert contact.summary_updated_at is not None
        usage = (
            (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
            .scalars()
            .all()
        )
        assert [(u.model, u.tokens_in, u.tokens_out) for u in usage] == [("gpt-6-luna", 1200, 120)]
        assert usage[0].cost > 0


async def test_skips_when_a_newer_message_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory, wa_id="996700000008")
    async with session_factory() as session:
        await insert_incoming(
            session, bot_id, contact_id, "ещё вопрос", f"w-{uuid.uuid4().hex}", datetime.now(UTC)
        )
        await session.commit()
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    assert analyze.calls == []  # актуальную задачу поставил более новый вопрос


async def test_bot_reply_after_scheduling_does_not_cancel_the_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Задача ставится от сообщения клиента (seq до ответа бота); ответ бота
    # и реплика менеджера, пришедшие позже, её не отменяют и попадают в диалог.
    async with session_factory() as session:
        bot = Bot(name="reply-after-bot")
        session.add(bot)
        await session.flush()
        contact = await match_or_create_contact(session, bot.id, wa_id="996700000009", lid=None)
        await insert_incoming(
            session, bot.id, contact.id, "вопрос", f"w-{uuid.uuid4().hex}", datetime.now(UTC)
        )
        scheduled_seq = await latest_message_seq(session, contact.id)
        await insert_outgoing(session, bot.id, contact.id, "ответ бота")
        await insert_outgoing(session, bot.id, contact.id, "[Ответ менеджера] подскажу")
        await session.commit()
        bot_id, contact_id = bot.id, contact.id
    assert scheduled_seq is not None
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, scheduled_seq)
    finally:
        await redis.aclose()

    assert len(analyze.calls) == 1
    assert [m.content for m in analyze.calls[0]] == [
        "вопрос",
        "ответ бота",
        "[Ответ менеджера] подскажу",
    ]


async def test_skips_disabled_bot(session_factory: async_sessionmaker[AsyncSession]) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory, enabled=False, wa_id="996700000002")
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    assert analyze.calls == []


async def test_skips_blocked_contact(session_factory: async_sessionmaker[AsyncSession]) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory, wa_id="996700000003")
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000003")
        await session.commit()
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    assert analyze.calls == []


async def test_skips_dialog_with_fewer_than_two_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        bot = Bot(name="one-msg-bot")
        session.add(bot)
        await session.flush()
        contact = await match_or_create_contact(session, bot.id, wa_id="996700000004", lid=None)
        await insert_incoming(
            session, bot.id, contact.id, "привет", f"w-{uuid.uuid4().hex}", datetime.now(UTC)
        )
        await session.commit()
        bot_id, contact_id = bot.id, contact.id
    async with session_factory() as session:
        seq = await latest_message_seq(session, contact_id)
    assert seq is not None
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    assert analyze.calls == []


async def test_duplicate_delivery_is_a_noop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory, wa_id="996700000005")
    analyze = _FakeAnalyze()
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
        await _run(session_factory, redis, analyze, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    assert len(analyze.calls) == 1  # повторная доставка той же задачи не жжёт токены


async def test_llm_failure_keeps_old_values_and_allows_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory, wa_id="996700000006")
    async with session_factory() as session:
        await set_contact_analysis(session, contact_id, "Старое саммари.", "hot")
        await session.commit()
    failing = _FakeAnalyze(error=RuntimeError("OpenAI недоступен"))
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, failing, bot_id, contact_id, seq)  # не бросает
        async with session_factory() as session:
            contact = await get_contact(session, contact_id)
            assert contact is not None
            assert (contact.summary, contact.temperature) == ("Старое саммари.", "hot")

        # повторная доставка после сбоя может попробовать снова
        ok = _FakeAnalyze()
        await _run(session_factory, redis, ok, bot_id, contact_id, seq)
        assert len(ok.calls) == 1
    finally:
        await redis.aclose()


async def test_unusable_model_answer_keeps_old_values_but_records_usage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot_id, contact_id, seq = await _dialog(session_factory, wa_id="996700000007")
    async with session_factory() as session:
        await set_contact_analysis(session, contact_id, "Старое саммари.", "cold")
        await session.commit()
    garbage = _FakeAnalyze(
        outcome=AnalysisOutcome(analysis=None, tokens_in=1000, tokens_out=50, model="gpt-6-luna")
    )
    redis = FakeRedis(decode_responses=True)
    try:
        await _run(session_factory, redis, garbage, bot_id, contact_id, seq)
    finally:
        await redis.aclose()

    async with session_factory() as session:
        contact = await get_contact(session, contact_id)
        assert contact is not None
        assert (contact.summary, contact.temperature) == ("Старое саммари.", "cold")
        usage = (
            (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
            .scalars()
            .all()
        )
        assert [(u.tokens_in, u.tokens_out) for u in usage] == [(1000, 50)]
