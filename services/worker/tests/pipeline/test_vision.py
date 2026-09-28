"""Vision-ответ на фото (FEATURES.md 2.1): один вызов LLM с image_prompt как
system prompt, ответ уходит клиенту напрямую. Деградация в медиа-заглушку
при сбое storage/LLM — без падения консюмера и без двойного ответа.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import asyncio
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
from worker.pipeline.consumer import DEFAULT_MEDIA_FALLBACK_TEXT, _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _FakeStorage:
    def __init__(
        self,
        data: bytes | None = None,
        error: Exception | None = None,
        data_by_key: dict[str, bytes] | None = None,
    ) -> None:
        self._data = data
        self._error = error
        self._data_by_key = data_by_key or {}

    async def get(self, key: str) -> bytes:
        if self._error is not None:
            raise self._error
        if key in self._data_by_key:
            return self._data_by_key[key]
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
        # fetch_recent_history фильтрует по реальному 24-часовому окну от
        # текущего времени (см. память fetch-recent-history-24h-window-
        # gotcha) — _reply_with_vision теперь собирает фото пачки именно
        # через эту историю (не только через event.storage_key напрямую),
        # фиксированный старый ts здесь ломал бы сборку картинок.
        "ts": int(datetime.now(UTC).timestamp() * 1000),
    }


async def test_bot_with_image_prompt_sends_vision_reply_and_records_usage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete_with_images(
        system_prompt: str,
        history: object,
        caption: str,
        images: list[tuple[bytes, str]],
        **_: object,
    ) -> LLMResult:
        assert "Опиши товар" in system_prompt  # bot.image_prompt подмешан
        assert images == [(b"fake-jpeg-bytes", "image/jpeg")]
        return LLMResult(
            text="На фото синие кроссовки 42 размера.",
            tokens_in=300,
            tokens_out=20,
            model="gpt-4o-mini",
        )

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)

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
        assert len(out_entries) == 4  # seen (1.11) + reaction + typing + текст
        assert "На фото синие кроссовки" in out_entries[3][1]["payload"]

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


async def test_quoted_text_is_mixed_into_vision_caption(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FEATURES.md 1.4: клиент цитирует предыдущее сообщение и присылает
    фото — контекст цитаты подмешивается в caption, а не теряется."""
    captured_captions: list[str] = []

    async def fake_complete_with_images(
        system_prompt: str,
        history: object,
        caption: str,
        images: list[tuple[bytes, str]],
        **_: object,
    ) -> LLMResult:
        captured_captions.append(caption)
        return LLMResult(text="Да, это он.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар на фото клиенту.")
    payload = {
        **_inbound_image_payload_with_storage(bot_id, text="такой же?"),
        "quoted_text": "Есть синие кроссовки?",
    }
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(payload, redis, session_factory, _FakeStorage(data=b"fake-jpeg-bytes"))
        assert captured_captions == ['[В ответ на: "Есть синие кроссовки?"]\nтакой же?']
    finally:
        await redis.aclose()


async def test_bot_without_image_prompt_falls_back_and_skips_llm(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("vision LLM не должен вызываться без image_prompt")

    monkeypatch.setattr(consumer_module, "complete_with_images", fail_if_called)

    bot_id = await _make_bot(session_factory, image_prompt=None)  # регрессия — старое поведение
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(
            _inbound_image_payload_with_storage(bot_id), redis, session_factory, _FakeStorage()
        )
        out_entries = await redis.xrange("wa:out")
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[3][1]["payload"]
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

    monkeypatch.setattr(consumer_module, "complete_with_images", fail_if_called)

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
        assert len(out_entries) == 4  # seen+reaction+typing+text, не два ответа
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[3][1]["payload"]
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

    monkeypatch.setattr(consumer_module, "complete_with_images", failing_complete)

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
        assert len(out_entries) == 4
        assert DEFAULT_MEDIA_FALLBACK_TEXT in out_entries[3][1]["payload"]
    finally:
        await redis.aclose()


async def test_multiple_photos_in_one_batch_are_combined_into_one_vision_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FEATURES.md 2.1 ревизия: клиент шлёт несколько фото подряд в одном
    окне батчинга — раньше анализировалось только фото лидера, остальные
    оставались [фото]-заглушками в истории, никогда не увиденными vision-
    моделью. Теперь все фото пачки уходят одним мультимодальным вызовом."""
    captured_images: list[list[tuple[bytes, str]]] = []
    captured_histories: list[list[object]] = []

    async def fake_complete_with_images(
        system_prompt: str,
        history: list[object],
        caption: str,
        images: list[tuple[bytes, str]],
        **_: object,
    ) -> LLMResult:
        captured_images.append(images)
        captured_histories.append(list(history))
        return LLMResult(text="Вижу оба фото.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар на фото клиенту.")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    payload1 = {
        **_inbound_image_payload_with_storage(bot_id),
        "wa_msg_id": "wamsg-batch-1",
        "storage_key": "bots/x/media/photo-1",
        "ts": now_ms,
    }
    payload2 = {
        **_inbound_image_payload_with_storage(bot_id),
        "wa_msg_id": "wamsg-batch-2",
        "storage_key": "bots/x/media/photo-2",
        "ts": now_ms,
    }
    storage = _FakeStorage(
        data_by_key={
            "bots/x/media/photo-1": b"photo-one-bytes",
            "bots/x/media/photo-2": b"photo-two-bytes",
        }
    )

    redis = FakeRedis(decode_responses=True)
    try:
        leader_task = asyncio.create_task(_process_entry(payload1, redis, session_factory, storage))
        await asyncio.sleep(0.005)  # даём лидеру зарегистрироваться и уйти в wait_for_quiet
        await _process_entry(payload2, redis, session_factory, storage)  # фолловер — вернётся сразу
        await leader_task

        assert len(captured_images) == 1  # один объединённый вызов, не два отдельных ответа клиенту
        assert captured_images[0] == [
            (b"photo-one-bytes", "image/jpeg"),
            (b"photo-two-bytes", "image/jpeg"),
        ]
        # обе заглушки этой же пачки исключены из истории — это первые
        # сообщения контакта, значит для этого хода history пустая
        assert captured_histories[0] == []
    finally:
        await redis.aclose()


async def test_photo_arriving_after_a_text_leader_is_still_analyzed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Раньше диспетчеризация (vision/pdf/fallback/текст) решалась только по
    типу СОБЫТИЯ-ЛИДЕРА — если клиент сначала написал текст, а фото прислал
    следом в том же окне батчинга, весь ход уходил по текстовому пути и
    фото никогда не анализировалось. Теперь достаточно, чтобы фото было
    ГДЕ-ТО в пачке."""
    captured_captions: list[str] = []
    captured_images: list[list[tuple[bytes, str]]] = []

    async def fake_complete_with_images(
        system_prompt: str,
        history: list[object],
        caption: str,
        images: list[tuple[bytes, str]],
        **_: object,
    ) -> LLMResult:
        captured_captions.append(caption)
        captured_images.append(images)
        return LLMResult(text="Да, есть такое.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_if_called(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("текстовый путь не должен сработать — в пачке есть фото")

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)
    monkeypatch.setattr(consumer_module, "complete", fail_if_called)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар на фото клиенту.")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    text_payload = {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-text-leader",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Такое есть?",
        "ts": now_ms,
    }
    photo_payload = {
        **_inbound_image_payload_with_storage(bot_id),
        "wa_msg_id": "wamsg-photo-follower",
        "storage_key": "bots/x/media/photo-follower",
        "ts": now_ms,
    }
    storage = _FakeStorage(data_by_key={"bots/x/media/photo-follower": b"photo-bytes"})

    redis = FakeRedis(decode_responses=True)
    try:
        leader_task = asyncio.create_task(
            _process_entry(text_payload, redis, session_factory, storage)
        )
        await asyncio.sleep(0.005)
        await _process_entry(photo_payload, redis, session_factory, storage)
        await leader_task

        assert captured_captions == ["Такое есть?"]
        assert captured_images == [[(b"photo-bytes", "image/jpeg")]]
    finally:
        await redis.aclose()


async def test_voice_leader_with_photo_follower_does_not_send_audio_bytes_as_an_image(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Живой баг (security review, 2026-09-28): batch_ids всегда включал
    event.wa_msg_id (лидера), даже когда лидер САМ не фото — голосовое,
    прилетевшее ПЕРВЫМ, следом за которым в том же окне батчинга приходит
    фото, уходило по vision-пути (т.к. в пачке ЕСТЬ фото), но лидер (аудио-
    байты) тоже попадал в выборку batch_rows и отправлялся модели как
    картинка. Фильтр по mime_type в batch_rows должен исключать лидера,
    если он не image/*."""
    captured_images: list[list[tuple[bytes, str]]] = []

    async def fake_complete_with_images(
        system_prompt: str,
        history: list[object],
        caption: str,
        images: list[tuple[bytes, str]],
        **_: object,
    ) -> LLMResult:
        captured_images.append(images)
        return LLMResult(text="Вот такое же.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete_with_images", fake_complete_with_images)

    bot_id = await _make_bot(session_factory, image_prompt="Опиши товар на фото клиенту.")
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    voice_leader_payload = {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": "wamsg-voice-leader",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "",
        "media_type": "audio",
        "storage_key": "bots/x/media/voice-leader",
        "mime_type": "audio/ogg; codecs=opus",
        "size_bytes": 123,
        "ts": now_ms,
    }
    photo_follower_payload = {
        **_inbound_image_payload_with_storage(bot_id),
        "wa_msg_id": "wamsg-photo-follower",
        "storage_key": "bots/x/media/photo-follower",
        "ts": now_ms,
    }
    storage = _FakeStorage(
        data_by_key={
            "bots/x/media/voice-leader": b"ogg-bytes-not-an-image",
            "bots/x/media/photo-follower": b"photo-bytes",
        }
    )

    redis = FakeRedis(decode_responses=True)
    try:
        leader_task = asyncio.create_task(
            _process_entry(voice_leader_payload, redis, session_factory, storage)
        )
        await asyncio.sleep(0.005)
        await _process_entry(photo_follower_payload, redis, session_factory, storage)
        await leader_task

        assert captured_images == [[(b"photo-bytes", "image/jpeg")]]
    finally:
        await redis.aclose()
