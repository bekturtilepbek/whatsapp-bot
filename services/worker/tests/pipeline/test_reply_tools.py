"""_reply(): включённые в tool_bindings тулзы попадают в run_tool_loop;
тулза, которой нет в реестре libs/tools, молча пропускается (FEATURES.md
4.13, инфраструктура — реального дозвона до LLM здесь нет, run_tool_loop
патчится тестовыми фейками, как и complete/complete_with_image в
test_reply_smoke.py).
"""

from __future__ import annotations

import json
import uuid
from typing import ClassVar

import pytest
from structlog.testing import capture_logs

pytest.importorskip("testcontainers.postgres")
from db.models import Bot, Document
from db.tool_bindings import enable as enable_tool_binding
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult, ToolCall, ToolResultTurn
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tools import registry as tools_registry
from tools.base import MediaToSend, ToolContext, ToolExecutionResult
from tools.send_document import SendDocumentTool
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
        "wa_msg_id": "wamsg-1",
        "chat_id": "996700000000@s.whatsapp.net",
        "sender_wa_id": "996700000000",
        "from_me": False,
        "text": "Привет",
        "ts": 1756800000000,
    }


async def test_no_bindings_uses_complete_fn_fast_path(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ни одной строки в tool_bindings — как сейчас у всех ботов: быстрый
    путь run_tool_loop (просто complete()), поведение не меняется."""

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="ответ без тулз", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)

    bot_id = await _make_bot(session_factory)
    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert "ответ без тулз" in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_binding_for_tool_missing_from_registry_is_silently_skipped(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """tool_bindings ссылается на имя, которого нет в реестре libs/tools
    (рассинхрон БД/деплоя кода) — не должно ронять диалог и не должно
    доходить до complete_with_tools (итоговых тулз для LLM — ноль)."""

    async def fake_complete(system_prompt: str, history: list[object], **_: object) -> LLMResult:
        return LLMResult(text="ok", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_complete_with_tools(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("не должен вызываться — тулза не найдена в реестре")

    monkeypatch.setattr(consumer_module, "complete", fake_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fail_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "phantom_tool", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert "ok" in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_registered_tool_is_offered_and_can_be_invoked_end_to_end(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Реестр временно содержит фейковую тулзу (monkeypatch, не продакшн-код)
    — доказывает, что вся цепочка tool_bindings -> реестр -> ToolContext ->
    executor реально работает, без реального OpenAI-вызова."""

    # Ассерты по ctx нельзя класть внутрь execute(): tool_loop._run_one_tool
    # оборачивает вызов executor'а в `except Exception` и превращает любое
    # исключение (в т.ч. AssertionError — он тоже Exception) в текст ошибки
    # для LLM, а не даёт тесту упасть. Поэтому просто запоминаем ctx здесь и
    # проверяем его уже вне колбэка, где падение реально валит тест.
    captured_contexts: list[ToolContext] = []

    class _FakeSearchTool:
        name = "search"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            captured_contexts.append(ctx)
            return ToolExecutionResult(content="найдено: тестовый товар")

    monkeypatch.setitem(tools_registry._REGISTRY, "search", _FakeSearchTool())

    captured_tool_specs: list[object] = []
    captured_exchanges: list[list[object]] = []

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        captured_tool_specs.append(tools)
        exchange_list = list(exchange)
        captured_exchanges.append(exchange_list)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        return LLMResult(text="Вот тестовый товар.", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "search", {"limit": 3})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert "Вот тестовый товар." in out_entries[1][1]["payload"]
        assert len(captured_tool_specs[0]) == 1
        assert captured_tool_specs[0][0].name == "search"

        # Ассерты по ToolContext — здесь, а не внутри execute() (см. коммент
        # выше): падение реально валит тест, а не тонет в except Exception
        # тул-лупа.
        assert len(captured_contexts) == 1
        assert captured_contexts[0].config == {"limit": 3}
        assert captured_contexts[0].contact_id is not None

        # Бонус: убеждаемся, что результат тулзы реально дошёл до второго
        # вызова complete_with_tools как ToolResultTurn.content.
        assert len(captured_exchanges) == 2
        second_exchange = captured_exchanges[1]
        tool_results = [
            turn for turn in second_exchange if isinstance(turn, ToolResultTurn)
        ]
        assert len(tool_results) == 1
        assert tool_results[0].content == "найдено: тестовый товар"
    finally:
        await redis.aclose()


async def test_tool_override_reply_sends_media_and_override_text_instead_of_llm_text(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.3/4.4: если тулза вернула override_reply_text —
    клиенту уходит typing + карточка (фото + текст карточки), а не текст
    LLM."""

    class _FakeCardTool:
        name = "search"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content='[{"name": "Nike Air"}]',
                override_reply_text="*Nike Air*\nЦена: 5000",
                media=[
                    MediaToSend(storage_key="bots/x/products/img-1.jpg", mime_type="image/jpeg")
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "search", _FakeCardTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        return LLMResult(
            text="этот текст LLM не должен уйти клиенту",
            tokens_in=1, tokens_out=1, model="gpt-4o-mini",
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "search", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, outbound.image, outbound.text — три события, текст LLM среди них нет
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.image"
        assert payloads[1]["storage_key"] == "bots/x/products/img-1.jpg"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "*Nike Air*\nЦена: 5000"
        assert not any("этот текст LLM" in p.get("text", "") for p in payloads)
    finally:
        await redis.aclose()


async def test_multiple_products_in_one_turn_send_all_cards_with_jitter_between_media(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.3/4.4: LLM находит два товара за один ход — уходят
    ОБЕ карточки по очереди (найденная ранее не молча теряется), с
    джиттером между фото (эталон V1, анти-бан) — джиттер подменён на 0,
    чтобы тест не ждал реальные 1-1.5с."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeMultiCardTool:
        name = "search"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}
        calls = 0

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            type(self).calls += 1
            n = type(self).calls
            return ToolExecutionResult(
                content=f'[{{"name": "Товар {n}"}}]',
                override_reply_text=f"*Товар {n}*",
                media=[MediaToSend(storage_key=f"img-{n}.jpg", mime_type="image/jpeg")],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "search", _FakeMultiCardTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[
                    ToolCall(id="call_1", name="search", arguments_json="{}"),
                    ToolCall(id="call_2", name="search", arguments_json="{}"),
                ],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "search", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, image1, text1, image2, text2
        assert len(out_entries) == 5
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.image"
        assert payloads[1]["storage_key"] == "img-1.jpg"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "*Товар 1*"
        assert payloads[3]["type"] == "outbound.image"
        assert payloads[3]["storage_key"] == "img-2.jpg"
        assert payloads[4]["type"] == "outbound.text"
        assert payloads[4]["text"] == "*Товар 2*"
        assert not any("текст LLM" in p.get("text", "") for p in payloads)
    finally:
        await redis.aclose()


async def test_document_media_dispatches_to_outbound_document_with_filename(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.8: media с не-image/не-video mime_type уходит как
    outbound.document с filename (Baileys требует его для показа имени
    файла клиенту)."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeDocumentTool:
        name = "send_document"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content="Файл price-list.pdf успешно отправлен.",
                override_reply_text="Файл price-list.pdf отправлен.",
                media=[
                    MediaToSend(
                        storage_key="bots/x/documents/price-list.pdf",
                        mime_type="application/pdf",
                        filename="price-list.pdf",
                    )
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", _FakeDocumentTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="send_document", arguments_json="{}")],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, document, text
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.document"
        assert payloads[1]["storage_key"] == "bots/x/documents/price-list.pdf"
        assert payloads[1]["filename"] == "price-list.pdf"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "Файл price-list.pdf отправлен."
    finally:
        await redis.aclose()


async def test_real_send_document_tool_dispatches_to_outbound_document(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seam-тест (найдено ретро-ревью 4.8/4.9, 2026-09-08): тест выше
    (`test_document_media_dispatches_to_outbound_document_with_filename`)
    проверяет диспетчеризацию по mime_type через `_FakeDocumentTool` —
    доказывает, что "нечто в форме SendDocumentTool" доходит до
    _send_media_replies корректно, но не доказывает, что РЕАЛЬНАЯ тулза
    (со своим поиском Document по имени в БД) действительно производит эту
    форму, будучи зарегистрированной и вызванной через настоящий
    tool_loop. libs/tools/tests/test_send_document.py тестирует тулзу
    саму по себе (execute() -> ToolExecutionResult), эта же проверка
    отдельно — само соединение между двумя концами не было проверено
    ни одним из них."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", SendDocumentTool())

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        session.add(
            Document(
                bot_id=bot_id,
                filename="price-list.pdf",
                storage_key="bots/x/documents/price-list.pdf",
                mime_type="application/pdf",
            )
        )
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="send_document",
                        arguments_json='{"file_name": "price-list.pdf"}',
                    )
                ],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        # typing, document, text
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[0]["type"] == "outbound.typing"
        assert payloads[1]["type"] == "outbound.document"
        # Ровно то, что реальный SendDocumentTool взял из реальной строки
        # Document в БД — не то, что тест сам захардкодил в фейке.
        assert payloads[1]["storage_key"] == "bots/x/documents/price-list.pdf"
        assert payloads[1]["mime_type"] == "application/pdf"
        assert payloads[1]["filename"] == "price-list.pdf"
        assert payloads[2]["type"] == "outbound.text"
        assert payloads[2]["text"] == "Отправляю файл price-list.pdf."
    finally:
        await redis.aclose()


async def test_video_media_dispatches_to_outbound_video(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.9: media с video/* mime_type уходит как outbound.video
    (нативный плеер), не outbound.document."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeVideoTool:
        name = "send_document"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content="Файл tour.mp4 успешно отправлен.",
                override_reply_text="Файл tour.mp4 отправлен.",
                media=[
                    MediaToSend(
                        storage_key="bots/x/documents/tour.mp4",
                        mime_type="video/mp4",
                        filename="tour.mp4",
                    )
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", _FakeVideoTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="send_document", arguments_json="{}")],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[1]["type"] == "outbound.video"
        assert payloads[1]["storage_key"] == "bots/x/documents/tour.mp4"
        assert "filename" not in payloads[1]
    finally:
        await redis.aclose()


async def test_mixed_case_mime_type_dispatches_case_insensitively(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.8/4.9 review Fix 4: MIME-типы регистронезависимы (RFC
    2045). `mime_type="Image/JPEG"` (смешанный регистр — реалистично, т.к.
    Document.mime_type сейчас вручную вбивается в SQL) должен уйти как
    outbound.image, не outbound.document — но исходное написание сохраняется
    в самом поле mime_type события (регистронезависимость касается только
    решения о диспетчеризации)."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeMixedCaseImageTool:
        name = "send_document"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content="Файл photo.jpg поставлен в очередь на отправку.",
                override_reply_text="Отправляю файл photo.jpg.",
                media=[
                    MediaToSend(
                        storage_key="bots/x/documents/photo.jpg",
                        mime_type="Image/JPEG",
                        filename="photo.jpg",
                    )
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", _FakeMixedCaseImageTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="send_document", arguments_json="{}")],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 3
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[1]["type"] == "outbound.image"
        assert payloads[1]["storage_key"] == "bots/x/documents/photo.jpg"
        # диспетчеризация регистронезависима, но написание в самом событии — нет
        assert payloads[1]["mime_type"] == "Image/JPEG"
    finally:
        await redis.aclose()


async def test_missing_filename_fallback_logs_a_warning(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """FEATURES.md 4.8/4.9 review Fix 5: сегодня `item.filename or "file"`
    недостижим через реальные тулзы (SendDocumentTool всегда ставит
    filename; ProductSearchTool — всегда image/*). Если когда-нибудь
    появится тулза без filename для не-image/не-video медиа — это должно
    попасть в логи, а не тихо назвать файл "file"."""
    monkeypatch.setattr(consumer_module.random, "uniform", lambda a, b: 0.0)

    class _FakeNoFilenameTool:
        name = "send_document"
        description = "тестовая тулза"
        parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

        async def execute(
            self, arguments: dict[str, object], ctx: ToolContext
        ) -> ToolExecutionResult:
            return ToolExecutionResult(
                content="ok",
                override_reply_text="Отправляю файл.",
                media=[
                    MediaToSend(
                        storage_key="bots/x/documents/mystery",
                        mime_type="application/pdf",
                        filename=None,
                    )
                ],
            )

    monkeypatch.setitem(tools_registry._REGISTRY, "send_document", _FakeNoFilenameTool())

    async def fake_complete_with_tools(
        system_prompt: str, history: list[object], tools: list[object], exchange: object = (),
        *, force_text: bool = False, **_: object,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini",
                tool_calls=[ToolCall(id="call_1", name="send_document", arguments_json="{}")],
            )
        return LLMResult(
            text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="gpt-4o-mini"
        )

    async def fail_complete(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза включена — быстрый путь не должен вызываться")

    monkeypatch.setattr(consumer_module, "complete", fail_complete)
    monkeypatch.setattr(consumer_module, "complete_with_tools", fake_complete_with_tools)

    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_document", {})
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        with capture_logs() as logs:
            await _process_entry(_inbound_payload(bot_id), redis, session_factory, _NullStorage())

        warnings = [
            entry for entry in logs
            if entry["log_level"] == "warning"
            and entry["event"] == "media reply missing filename, using fallback"
        ]
        assert len(warnings) == 1
        assert warnings[0]["mime_type"] == "application/pdf"

        out_entries = await redis.xrange("wa:out")
        payloads = [json.loads(entry[1]["payload"]) for entry in out_entries]
        assert payloads[1]["type"] == "outbound.document"
        assert payloads[1]["filename"] == "file"
    finally:
        await redis.aclose()
