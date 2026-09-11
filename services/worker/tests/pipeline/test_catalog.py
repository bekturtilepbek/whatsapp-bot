"""Каталог товаров в system prompt (FEATURES.md 3.4) — реальный сценарий
через _process_entry, как test_reply_smoke.py: мок только на границе LLM
(consumer_module.complete), всё остальное — реальный Postgres/fakeredis.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot, Product
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _process_entry

from pipeline.conftest import docker_available

pytestmark = pytest.mark.skipif(
    not docker_available(), reason="Docker недоступен в этом окружении"
)


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError("этот тест не читает из Storage")


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="test-bot", enabled=True, system_prompt="Ты — ассистент магазина.",
            timezone="Asia/Bishkek", settings={"batch_timeout_seconds": 0.02},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _inbound_payload(bot_id: uuid.UUID, wa_msg_id: str = "livecheck-1") -> dict[str, object]:
    return {
        "type": "inbound.text",
        "bot_id": str(bot_id),
        "wa_msg_id": wa_msg_id,
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Что у вас есть?",
        "ts": 1756800000000,
    }


async def test_products_appear_in_system_prompt_sent_to_llm(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Product(bot_id=bot_id, name="Кроссовки Nike Air", price=Decimal("5000.00"))
        )
        await session.commit()

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="Да, есть кроссовки.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert len(captured_system_prompts) == 1
        assert "КАТАЛОГ ТОВАРОВ В БАЗЕ" in captured_system_prompts[0]
        assert "Кроссовки Nike Air | Цена: 5000.00" in captured_system_prompts[0]
    finally:
        await redis.aclose()


async def test_empty_catalog_sends_the_empty_catalog_message(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)  # ни одного товара

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert "Каталог товаров пуст." in captured_system_prompts[0]
    finally:
        await redis.aclose()


async def test_catalog_limit_caps_products_in_the_prompt(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(consumer_module, "PRODUCT_CATALOG_LIMIT", 2)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add_all([Product(bot_id=bot_id, name=f"Товар {i}") for i in range(5)])
        await session.commit()

    captured_system_prompts: list[str] = []

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        prompt = captured_system_prompts[0]
        assert prompt.count(" | Цена: ") == 2
    finally:
        await redis.aclose()
