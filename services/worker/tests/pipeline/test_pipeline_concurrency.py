"""run_pipeline_consumer должен обрабатывать записи wa:in конкурентно, а не
строго одну за другой — иначе фолловер батча (FEATURES.md 1.3/2.1 ревизия)
физически не успевает зарегистрироваться, пока лидер спит в
wait_for_quiet(), и превращается в отдельного лидера собственного окна.
Живая проверка на docker compose воспроизвела именно это: два фото подряд
дали два отдельных ответа вместо одного объединённого vision-вызова.

В отличие от test_vision.py (там `_process_entry` вызывается вручную через
asyncio.create_task, что искусственно эмулирует конкурентность), здесь
события публикуются настоящим XADD и разбираются настоящим
run_pipeline_consumer — тем же путём, что и в проде.

Требует Docker (testcontainers-postgres).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

pytest.importorskip("testcontainers.postgres")
from core.bus import IN_STREAM, publish
from db.models import Bot
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.bus import ensure_group
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import GROUP, run_pipeline_consumer

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _FakeStorage:
    def __init__(self, data_by_key: dict[str, bytes]) -> None:
        self._data_by_key = data_by_key

    async def get(self, key: str) -> bytes:
        return self._data_by_key[key]


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot",
            enabled=True,
            system_prompt="Ты — ассистент.",
            image_prompt="Опиши товар на фото клиенту.",
            timezone="Asia/Bishkek",
            settings={"batch_timeout_seconds": 0.05},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _image_payload(bot_id: uuid.UUID, wa_msg_id: str, storage_key: str) -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "",
        "media_type": "image",
        "storage_key": storage_key,
        "mime_type": "image/jpeg",
        "size_bytes": 12345,
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }


async def test_two_photos_published_close_together_are_combined_by_the_real_consumer_loop(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_images: list[list[tuple[bytes, str]]] = []

    async def fake_complete_with_images(
        system_prompt: str,
        history: list[object],
        caption: str,
        images: list[tuple[bytes, str]],
        **_: object,
    ) -> LLMResult:
        captured_images.append(images)
        return LLMResult(text="Вижу оба фото.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)

    bot_id = await _make_bot(session_factory)
    storage = _FakeStorage(
        {
            "bots/x/media/photo-1": b"photo-one-bytes",
            "bots/x/media/photo-2": b"photo-two-bytes",
        }
    )
    redis = FakeRedis(decode_responses=True)
    try:
        # Группа создаётся ДО паблиша и ДО запуска консюмера — иначе гонка
        # между стартом run_pipeline_consumer (сам зовёт ensure_group) и
        # нашими XADD могла бы породить группу уже ПОСЛЕ первого сообщения
        # (id="$" тогда пропустил бы его).
        await ensure_group(redis, IN_STREAM, GROUP)
        consumer_task = asyncio.create_task(
            run_pipeline_consumer(redis, session_factory, "test-consumer", storage)
        )
        await publish(redis, IN_STREAM, _image_payload(bot_id, "wamsg-1", "bots/x/media/photo-1"))
        await asyncio.sleep(0.01)
        await publish(redis, IN_STREAM, _image_payload(bot_id, "wamsg-2", "bots/x/media/photo-2"))

        await asyncio.sleep(0.5)  # с запасом на батч (0.05с) + оба возможных цикла ответа

        assert len(captured_images) == 1
        assert captured_images[0] == [
            (b"photo-one-bytes", "image/jpeg"),
            (b"photo-two-bytes", "image/jpeg"),
        ]
    finally:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        await redis.aclose()


async def test_one_failing_entry_does_not_block_or_lose_the_next_entry_in_the_same_batch(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Раньше (последовательный async for + await) необработанное исключение
    на записи N обрывало сам `async for` — запись N+1 того же батча чтения
    не просто откладывалась, а вообще не читалась в эту итерацию (при этом
    успевала быть отмечена ">"-доставленной этому consumer'у, то есть не
    попала бы повторно через ">" при следующем XREADGROUP) — то есть падение
    одного сообщения могло похоронить соседнее. Теперь каждая запись — своя
    задача, падение одной не мешает остальным."""
    from db import messages as messages_module

    real_insert_incoming = messages_module.insert_incoming

    async def flaky_insert_incoming(session, bot_id, contact_id, content, wa_msg_id, ts, **kw):
        if wa_msg_id == "wamsg-bad":
            raise RuntimeError("симулированный сбой записи в БД")
        return await real_insert_incoming(
            session, bot_id, contact_id, content, wa_msg_id, ts, **kw
        )

    monkeypatch.setattr(consumer_module, "insert_incoming", flaky_insert_incoming)

    async def fake_complete(system_prompt, history, **_):
        return LLMResult(text="Ответ клиенту.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    def text_payload(wa_msg_id: str, chat_id: str) -> dict[str, object]:
        return {
            "type": "inbound.text",
            "bot_id": str(bot_id),
            "wa_msg_id": wa_msg_id,
            "chat_id": chat_id,
            "sender_wa_id": chat_id.split("@")[0],
            "from_me": False,
            "text": "Привет",
            "ts": now_ms,
        }

    storage = _FakeStorage({})
    redis = FakeRedis(decode_responses=True)
    try:
        await ensure_group(redis, IN_STREAM, GROUP)
        consumer_task = asyncio.create_task(
            run_pipeline_consumer(redis, session_factory, "test-consumer", storage)
        )
        # "Плохая" запись публикуется ПЕРВОЙ (меньший stream id) — именно
        # этот порядок обрывал async for в старом коде раньше, чем он
        # доходил до следующей записи того же батча чтения.
        await publish(redis, IN_STREAM, text_payload("wamsg-bad", "996700000001@s.whatsapp.net"))
        await publish(redis, IN_STREAM, text_payload("wamsg-good", "996700000002@s.whatsapp.net"))

        await asyncio.sleep(0.5)

        pending = await redis.xpending(IN_STREAM, GROUP)
        assert pending["pending"] == 0  # оба ACK'нуты, включая упавшую

        async with session_factory() as session:
            from db.models import Message
            from sqlalchemy import select

            good_messages = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.bot_id == bot_id, Message.wa_msg_id == "wamsg-good")
                    )
                )
                .scalars()
                .all()
            )
            assert len(good_messages) == 1  # входящее от "хорошего" чата всё равно записалось

            assistant_replies = (
                (
                    await session.execute(
                        select(Message).where(Message.bot_id == bot_id, Message.role == "assistant")
                    )
                )
                .scalars()
                .all()
            )
            assert len(assistant_replies) == 1
            assert assistant_replies[0].content == "Ответ клиенту."
    finally:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        await redis.aclose()
