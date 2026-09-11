"""Список файлов в system prompt (FEATURES.md 4.8/4.9) — реальный
сценарий через _process_entry, как test_catalog.py: мок только на
границе LLM (consumer_module.complete), всё остальное — реальный
Postgres/fakeredis.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("testcontainers.postgres")
from db.models import Bot, Document
from db.tool_bindings import enable as enable_tool_binding
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
    """Регрессия: бот С привязанной тулзой send_document по-прежнему видит
    список файлов в system prompt (Fix 6 не должен сломать уже рабочий
    случай, только добавить гейт на отсутствие привязки)."""
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot_id, filename="price-list.pdf", storage_key="k",
                mime_type="application/pdf",
            )
        )
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    captured_system_prompts: list[str] = []

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="Сейчас пришлю.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

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
    """Бот С привязанной тулзой send_document, но без единого файла в БД —
    видит явное «Файлов пока нет.», а не пустую секцию."""
    bot_id = await _make_bot(session_factory)  # ни одного файла
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    captured_system_prompts: list[str] = []

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        captured_system_prompts.append(system_prompt)
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        assert "Файлов пока нет." in captured_system_prompts[0]
    finally:
        await redis.aclose()


async def test_documents_section_omitted_when_send_document_not_bound(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.8/4.9 review Fix 6: без привязки send_document бот не
    должен получать ни список файлов, ни инструкцию звать тулзу, которой у
    него нет — даже если в documents есть строки (например, для другого
    бота с этой же тулзой)."""
    bot_id = await _make_bot(session_factory)  # тулза НЕ привязана
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
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        prompt = captured_system_prompts[0]
        assert "ДОСТУПНЫЕ ФАЙЛЫ" not in prompt
        assert "price-list.pdf" not in prompt
        assert "send_document" not in prompt
        assert "Файлов пока нет." not in prompt
        # без секции файлов промпт не должен визуально ломаться тремя
        # пустыми строками подряд
        assert "\n\n\n\n" not in prompt
    finally:
        await redis.aclose()
