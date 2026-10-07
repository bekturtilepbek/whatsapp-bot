"""Постановка фонового саммари диалога (FEATURES.md 6.13): после сообщения
клиента worker ставит Celery-задачу с eta "диалог затих". Не ставится для
выключенного бота, номера из ЧС и реплик менеджера; сбой постановки не
ломает приём сообщения.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("testcontainers.postgres")
from db.blocked_contacts import add_blocked_number
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from scheduling.task_names import CONTACT_SUMMARY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)

CHAT_ID = "996700000000@s.whatsapp.net"


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

    def summary_calls(self) -> list[dict[str, object]]:
        return [c for c in self.calls if c["name"] == CONTACT_SUMMARY]


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], *, enabled: bool = True
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=enabled,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _payload(
    bot_id: uuid.UUID, *, from_me: bool = False, wa_msg_id: str = "sum-1"
) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": CHAT_ID,
        "sender_wa_id": "996700000000",
        "from_me": from_me,
        "text": "Здравствуйте, у вас есть доставка?",
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }


async def _process(
    payload: dict[str, object],
    redis: FakeRedis,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Постановка саммари — фоновая задача (не блокирует ответ): дожидаемся её."""
    await _process_entry(payload, redis, session_factory, _NullStorage())
    if consumer_module._background_tasks:
        await asyncio.gather(*consumer_module._background_tasks)


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="Да, есть.", tokens_in=10, tokens_out=5, model="gpt-6-luna")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)


async def test_summary_scheduled_after_client_message(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        before = datetime.now(UTC)
        await _process(_payload(bot_id), redis, session_factory)

        calls = fake_celery.summary_calls()
        assert len(calls) == 1
        bot_arg, contact_arg, seq_arg = calls[0]["args"]  # type: ignore[misc]
        assert bot_arg == str(bot_id)
        uuid.UUID(contact_arg)  # валидный id контакта
        assert isinstance(seq_arg, int)
        eta = calls[0]["eta"]
        assert isinstance(eta, datetime)
        expected = before + timedelta(minutes=10)
        assert abs((eta - expected).total_seconds()) < 5
    finally:
        await redis.aclose()


async def test_summary_not_scheduled_for_disabled_bot(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)
    bot_id = await _make_bot(session_factory, enabled=False)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process(_payload(bot_id), redis, session_factory)
        assert fake_celery.summary_calls() == []
    finally:
        await redis.aclose()


async def test_summary_not_scheduled_for_blocked_contact(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await add_blocked_number(session, bot_id, "996700000000")
        await session.commit()
    redis = FakeRedis(decode_responses=True)
    try:
        await _process(_payload(bot_id), redis, session_factory)
        assert fake_celery.summary_calls() == []
    finally:
        await redis.aclose()


async def test_summary_not_scheduled_for_manager_message(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_celery = _FakeCeleryApp()
    monkeypatch.setattr(consumer_module, "celery_app", fake_celery)
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process(_payload(bot_id, from_me=True, wa_msg_id="sum-mgr"), redis, session_factory)
        assert fake_celery.summary_calls() == []
    finally:
        await redis.aclose()


async def test_scheduling_failure_does_not_break_the_reply(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        consumer_module, "celery_app", _FakeCeleryApp(error=RuntimeError("брокер недоступен"))
    )
    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process(_payload(bot_id), redis, session_factory)

        assert await redis.xlen("wa:out") > 0  # клиент всё равно получил ответ
    finally:
        await redis.aclose()
