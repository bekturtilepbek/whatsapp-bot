"""Смоук всего пайплайна Шага 5 на фейковом транспорте: inbound.text ->
(мок LLM) -> outbound.seen + outbound.typing + outbound.text в wa:out, обе
стороны в messages, запись в usage_events. Отдельно: сбой LLM не роняет
консюмер и снимает лок.

DB — testcontainers-postgres (нужны реальные constraints/relations); Redis —
fakeredis (тот же выбор, что и для dedup/batching/lock-тестов этого блока:
достаточно верная семантика команд, без лишнего Docker-контейнера).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot, Message, UsageEvent
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry
from worker.pipeline.lock import _lock_key

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


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


class _NullStorage:
    """Заглушка для тестов, которые не доходят до vision-ветки — она никогда
    не должна вызываться, поэтому падает явно, а не тихо возвращает мусор.
    """

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не должен читать из Storage")


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
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 3
        assert '"type": "outbound.seen"' in out_entries[0][1]["payload"]
        assert '"type": "outbound.typing"' in out_entries[1][1]["payload"]
        assert '"type": "outbound.text"' in out_entries[2][1]["payload"]
        assert "Да, доставка есть." in out_entries[2][1]["payload"]

        async with session_factory() as session:
            # БД (testcontainers) общая на весь модуль — фильтруем по своему
            # bot_id, иначе видны строки соседних тестов этого файла; сортируем
            # по ts явно (порядок SELECT без ORDER BY не гарантирован).
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
            assert messages[1].content == "Да, доставка есть."

            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert len(usage) == 1
            assert usage[0].tokens_in == 42
            assert usage[0].tokens_out == 7
            assert usage[0].model == "gpt-4o-mini"

        assert await redis.get(_lock_key(str(bot_id), "996700000000@s.whatsapp.net")) is None
    finally:
        await redis.aclose()


async def test_typing_fires_before_the_llm_call_not_after(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ревизия FEATURES.md 1.8: раньше typing уходил только прямо перед
    отправкой готового текста (после LLM) — клиент видел "печатает…" на
    долю секунды. Эталон V1 — typing сразу после закрытия батч-окна, ДО
    начала обработки. Проверяем это напрямую: к моменту вызова LLM
    outbound.typing уже должен быть в wa:out, а не появиться только после."""
    redis_ref: FakeRedis | None = None

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        assert redis_ref is not None
        out_entries = await redis_ref.xrange("wa:out")
        assert len(out_entries) == 2  # seen (1.11) + typing — оба ДО LLM
        assert '"type": "outbound.seen"' in out_entries[0][1]["payload"]
        assert '"type": "outbound.typing"' in out_entries[1][1]["payload"]
        return LLMResult(text="Да, доставка есть.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    redis_ref = redis
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
    finally:
        await redis.aclose()


async def test_quoted_text_is_mixed_into_stored_content_and_llm_history(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FEATURES.md 1.4: цитата клиента подмешивается в начало content —
    и то, что уходит в БД (для будущих ходов), и то, что видит LLM в этом же
    ходе (fetch_recent_history подхватывает только что вставленную строку)."""
    captured_histories: list[list[object]] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_histories.append(list(history))
        return LLMResult(text="Да, актуально.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    payload = {
        **_inbound_payload(bot_id),
        "text": "да, беру",
        "quoted_text": "Товар ещё в наличии?",
        # fetch_recent_history фильтрует по реальному 24-часовому окну от
        # текущего времени — фиксированный ts из _inbound_payload() слишком
        # старый, история для него всегда пустая (не важно для тестов, не
        # проверяющих сам history, но важно для этого).
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(payload, redis, session_factory, _NullStorage())

        expected_content = '[В ответ на: "Товар ещё в наличии?"]\nда, беру'
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
            assert messages[0].content == expected_content

        assert captured_histories[0][-1].content == expected_content
    finally:
        await redis.aclose()


async def _make_bot_with_settings(
    session_factory: async_sessionmaker[AsyncSession], **settings: object
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="split-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.02, **settings},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


_MULTI_PARAGRAPH = "Здравствуйте!\n\nДоставка есть по всему Бишкеку.\n\nЧто-то ещё?"


async def test_split_reply_sends_paragraphs_as_separate_messages(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FEATURES.md 3.5 (эталон V1 splitMessage): абзацы — отдельными
    сообщениями, пауза перед каждым следующим (V1: 5 с) и "печатает…" перед
    ним; в историю — один ответ целиком."""
    pauses: list[float] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text=_MULTI_PARAGRAPH, tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fake_sleep(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    monkeypatch.setattr(consumer_module, "_split_pause", fake_sleep)

    bot_id = await _make_bot_with_settings(session_factory, split_reply_enabled=True)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        out = [e[1]["payload"] for e in await redis.xrange("wa:out")]
        types = [p.split('"type": "')[1].split('"')[0] for p in out]
        assert types == [
            "outbound.seen",
            "outbound.typing",
            "outbound.text",
            "outbound.typing",
            "outbound.text",
            "outbound.typing",
            "outbound.text",
        ]
        texts = [p for p in out if "outbound.text" in p]
        assert "Здравствуйте!" in texts[0] and "Бишкеку" in texts[1] and "Что-то ещё?" in texts[2]
        assert pauses == [consumer_module.SPLIT_REPLY_PAUSE_SECONDS] * 2

        async with session_factory() as session:
            query = select(Message).where(Message.bot_id == bot_id).order_by(Message.seq)
            messages = (await session.execute(query)).scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == _MULTI_PARAGRAPH
    finally:
        await redis.aclose()


async def test_split_reply_off_by_default_sends_one_message(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text=_MULTI_PARAGRAPH, tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    bot_id = await _make_bot_with_settings(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        texts = [e for e in await redis.xrange("wa:out") if "outbound.text" in e[1]["payload"]]
        assert len(texts) == 1
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
        await _process_entry(
            _inbound_payload(bot_id), redis, session_factory, _NullStorage()
        )  # не должно упасть

        # seen+typing зажигаются ДО вызова LLM (FEATURES.md 1.8 ревизия) —
        # клиент успевает их увидеть, даже когда сам ответ так и не пришёл.
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert '"type": "outbound.seen"' in out_entries[0][1]["payload"]
        assert '"type": "outbound.typing"' in out_entries[1][1]["payload"]
        assert await redis.get(_lock_key(str(bot_id), "996700000000@s.whatsapp.net")) is None

        async with session_factory() as session:
            messages = (
                (await session.execute(select(Message).where(Message.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert [m.role for m in messages] == ["user"]  # ответа нет
            usage = (
                (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
                .scalars()
                .all()
            )
            assert usage == []
    finally:
        await redis.aclose()
