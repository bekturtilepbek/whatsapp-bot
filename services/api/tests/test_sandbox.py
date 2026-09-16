"""POST /bots/{bot_id}/sandbox/messages (FEATURES.md 9.6): owner-only
тестовый прогон промпта. Часть A (9.6, тулзы) — тулзы бота (tool_bindings)
подключены через run_tool_loop, как в реальном пайплайне
(worker/pipeline/consumer.py::_reply), но с той же song, что и раньше:
ничего не пишется в contacts/messages. side_effecting-тулзы (сейчас только
send_telegram_lead) глушатся каноническим ответом — реального похода вовне
из песочницы быть не должно.

Требует Docker (testcontainers-postgres). Без него — skip, не fail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

pytest.importorskip("testcontainers.postgres")
from api.db import get_session, get_session_factory
from api.main import app
from api.redis_client import get_redis
from api.routers import sandbox as sandbox_module
from api.storage import get_storage
from db.engine import make_engine, make_session_factory
from db.models import Bot, Product, ProductImage, UsageEvent
from db.tool_bindings import enable as enable_tool_binding
from fakeredis.aioredis import FakeRedis
from llm.client import LLMResult, ToolCall
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import telegram_lead as telegram_lead_module

from tests.auth_helpers import override_non_owner_auth, override_owner_auth

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
    engine = make_engine(database_url)
    return make_session_factory(engine)


class _FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        self.objects[key] = (data, mime_type)


@pytest.fixture
def fake_storage() -> _FakeStorage:
    return _FakeStorage()


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> AsyncIterator[httpx.AsyncClient]:
    override_owner_auth()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_storage] = lambda: fake_storage
    app.dependency_overrides[get_redis] = lambda: FakeRedis(decode_responses=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_bot(
    session_factory: async_sessionmaker[AsyncSession], *, system_prompt: str = "Ты — ассистент."
) -> uuid.UUID:
    async with session_factory() as session:
        bot = Bot(
            name="sandbox-test-bot",
            enabled=True,
            system_prompt=system_prompt,
            timezone="Asia/Bishkek",
            settings={},
        )
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot.id


def _fake_complete(
    captured_prompts: list[str], captured_histories: list[list[object]], reply: str = "Привет!"
):
    async def fake_complete(system_prompt: str, history: list[object]) -> LLMResult:
        captured_prompts.append(system_prompt)
        captured_histories.append(history)
        return LLMResult(text=reply, tokens_in=11, tokens_out=7, model="gpt-4o-mini")

    return fake_complete


async def test_sandbox_message_returns_reply_and_records_usage(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)
    captured_prompts: list[str] = []
    captured_histories: list[list[object]] = []
    monkeypatch.setattr(
        sandbox_module, "complete", _fake_complete(captured_prompts, captured_histories)
    )

    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "reply": "Привет!",
        "tokens_in": 11,
        "tokens_out": 7,
        "model": "gpt-4o-mini",
        "media": [],
    }

    async with session_factory() as session:
        rows = (
            (await session.execute(select(UsageEvent).where(UsageEvent.bot_id == bot_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].tokens_in == 11
    assert rows[0].tokens_out == 7


async def test_sandbox_message_does_not_persist_contact_or_message_history(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory)
    monkeypatch.setattr(sandbox_module, "complete", _fake_complete([], []))

    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 200

    from db.models import Contact, Message

    async with session_factory() as session:
        contacts = (await session.execute(select(Contact))).scalars().all()
        messages = (await session.execute(select(Message))).scalars().all()
    assert contacts == []
    assert messages == []


async def test_sandbox_message_includes_history_and_catalog_in_system_prompt(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_id = await _make_bot(session_factory, system_prompt="Ты — ассистент магазина.")
    async with session_factory() as session:
        session.add(Product(bot_id=bot_id, name="Кроссовки", price=Decimal("5000.00")))
        await session.commit()

    captured_prompts: list[str] = []
    captured_histories: list[list[object]] = []
    monkeypatch.setattr(
        sandbox_module, "complete", _fake_complete(captured_prompts, captured_histories)
    )

    response = await client.post(
        f"/bots/{bot_id}/sandbox/messages",
        json={
            "history": [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Здравствуйте!"},
            ],
            "message": "Что у вас есть?",
        },
    )
    assert response.status_code == 200
    assert "Ты — ассистент магазина." in captured_prompts[0]
    assert "Кроссовки" in captured_prompts[0]
    history = captured_histories[0]
    assert [(m.role, m.content) for m in history] == [
        ("user", "Привет"),
        ("assistant", "Здравствуйте!"),
        ("user", "Что у вас есть?"),
    ]


async def test_sandbox_message_empty_text_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "   "})
    assert response.status_code == 422


async def test_sandbox_message_unknown_bot_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/bots/{uuid.uuid4()}/sandbox/messages", json={"message": "Привет"}
    )
    assert response.status_code == 404


async def test_sandbox_message_non_owner_returns_403(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    override_non_owner_auth()
    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 403


async def test_sandbox_message_too_much_history_returns_422(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    history = [{"role": "user", "content": "x"} for _ in range(51)]
    response = await client.post(
        f"/bots/{bot_id}/sandbox/messages", json={"history": history, "message": "Привет"}
    )
    assert response.status_code == 422


def _fake_complete_with_tools(
    tool_call: ToolCall, final_text: str = "текст LLM после результата тулзы"
):
    """Первый вызов (пустой exchange) — LLM просит вызвать тулзу; второй
    (exchange уже содержит ToolResultTurn) — финальный текст. Тот же
    двухфазный фейк, что и в services/worker/tests/pipeline/test_reply_tools.py."""

    async def fake(
        system_prompt: str,
        history: list[object],
        tools: list[object],
        exchange: object = (),
        *,
        force_text: bool = False,
        **_: object,
    ) -> LLMResult:
        if not list(exchange):
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="gpt-4o-mini", tool_calls=[tool_call]
            )
        return LLMResult(text=final_text, tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    return fake


async def _fail_complete(*args: object, **kwargs: object) -> LLMResult:
    raise AssertionError(
        "тулза включена в этом ходе — быстрый путь complete() не должен вызываться"
    )


async def test_sandbox_message_with_enabled_tool_returns_media_from_tool_card(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FEATURES.md 9.6 часть A: реальная (не фейковая) search_products —
    LLM вызывает тулзу, найденный товар уходит в ответе как медиа (карточка),
    override_reply_text тулзы становится reply — тот же контракт, что и в
    реальном диалоге (FEATURES.md 4.3/4.4)."""
    bot_id = await _make_bot(session_factory)
    storage_key = f"bots/{bot_id}/products/img-1.jpg"
    await fake_storage.put(storage_key, b"fake-jpeg-bytes", "image/jpeg")

    async with session_factory() as session:
        product = Product(bot_id=bot_id, name="Кроссовки", price=Decimal("5000.00"))
        session.add(product)
        await session.flush()
        session.add(
            ProductImage(product_id=product.id, storage_key=storage_key, mime_type="image/jpeg")
        )
        await enable_tool_binding(session, bot_id, "search_products", {})
        await session.commit()

    tool_call = ToolCall(
        id="call_1", name="search_products", arguments_json='{"query": "Кроссовки"}'
    )
    monkeypatch.setattr(sandbox_module, "complete", _fail_complete)
    monkeypatch.setattr(sandbox_module, "complete_with_tools", _fake_complete_with_tools(tool_call))

    response = await client.post(
        f"/bots/{bot_id}/sandbox/messages", json={"message": "Есть кроссовки?"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "Кроссовки" in body["reply"]
    assert body["media"] == [
        {"storage_key": storage_key, "mime_type": "image/jpeg", "filename": None}
    ]


async def test_sandbox_message_side_effecting_tool_is_muted_not_really_called(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """send_telegram_lead — side_effecting=True: песочница НЕ должна реально
    слать в Telegram. Проверяем это спаем на send_message, а не только тем,
    что ответ выглядит правдоподобно (мало ли реальный вызов молча упал бы
    и тоже дал такой же текст)."""
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "send_telegram_lead", {"chat_id": "123456"})
        await session.commit()

    send_message_calls: list[tuple[str, str]] = []

    async def spy_send_message(chat_id: str, text: str, **_: object) -> None:
        send_message_calls.append((chat_id, text))

    monkeypatch.setattr(telegram_lead_module, "send_message", spy_send_message)

    tool_call = ToolCall(
        id="call_1",
        name="send_telegram_lead",
        arguments_json='{"client_name": "Иван", "details": "хочет кроссовки"}',
    )
    monkeypatch.setattr(sandbox_module, "complete", _fail_complete)
    monkeypatch.setattr(
        sandbox_module,
        "complete_with_tools",
        _fake_complete_with_tools(tool_call, final_text="Спасибо, передал заявку менеджеру!"),
    )

    response = await client.post(
        f"/bots/{bot_id}/sandbox/messages", json={"message": "Хочу кроссовки, вот мои данные"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Спасибо, передал заявку менеджеру!"
    assert body["media"] == []
    assert send_message_calls == []


async def test_sandbox_message_unknown_tool_binding_uses_fast_path(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Рассинхрон БД/деплоя (tool_bindings ссылается на несуществующую в
    реестре тулзу) — как в реальном пайплайне (FEATURES.md 4.13): молча
    пропускается, ноль тулз для LLM, быстрый путь complete()."""
    bot_id = await _make_bot(session_factory)
    async with session_factory() as session:
        await enable_tool_binding(session, bot_id, "phantom_tool", {})
        await session.commit()

    async def fake_complete(system_prompt: str, history: list[object]) -> LLMResult:
        return LLMResult(text="ok, без тулз", tokens_in=1, tokens_out=1, model="gpt-4o-mini")

    async def fail_complete_with_tools(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("тулза не в реестре — до complete_with_tools доходить не должно")

    monkeypatch.setattr(sandbox_module, "complete", fake_complete)
    monkeypatch.setattr(sandbox_module, "complete_with_tools", fail_complete_with_tools)

    response = await client.post(f"/bots/{bot_id}/sandbox/messages", json={"message": "Привет"})
    assert response.status_code == 200
    assert response.json()["reply"] == "ok, без тулз"


async def test_sandbox_media_returns_bytes_for_known_key(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> None:
    bot_id = await _make_bot(session_factory)
    storage_key = f"bots/{bot_id}/documents/price.pdf"
    await fake_storage.put(storage_key, b"%PDF-1.4 fake", "application/pdf")

    response = await client.get(
        f"/bots/{bot_id}/sandbox/media",
        params={"key": storage_key, "mime_type": "application/pdf"},
    )
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake"
    assert response.headers["content-type"] == "application/pdf"


async def test_sandbox_media_rejects_key_outside_bot_prefix(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    bot_id = await _make_bot(session_factory)
    other_bot_id = uuid.uuid4()
    response = await client.get(
        f"/bots/{bot_id}/sandbox/media",
        params={
            "key": f"bots/{other_bot_id}/documents/price.pdf",
            "mime_type": "application/pdf",
        },
    )
    assert response.status_code == 404


async def test_sandbox_media_non_owner_returns_403(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    fake_storage: _FakeStorage,
) -> None:
    bot_id = await _make_bot(session_factory)
    storage_key = f"bots/{bot_id}/documents/price.pdf"
    await fake_storage.put(storage_key, b"data", "application/pdf")
    override_non_owner_auth()

    response = await client.get(
        f"/bots/{bot_id}/sandbox/media",
        params={"key": storage_key, "mime_type": "application/pdf"},
    )
    assert response.status_code == 403
