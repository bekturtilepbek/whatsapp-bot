"""TelegramLeadTool (FEATURES.md 4.7): generic-набор полей лида,
никогда не бросает исключение из execute() — любой сбой уходит текстом
в content (эталон V1, sendToTelegramGroup). Требует Docker
(testcontainers) для подгрузки контакта — реальная отправка в Telegram
подменена фейком (не настоящая сеть).
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
from db.contacts import match_or_create_contact
from db.engine import make_engine, make_session_factory
from db.models import Bot
from integrations.telegram import TelegramNotConfiguredError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer
from tools import telegram_lead as telegram_lead_module
from tools.base import ToolContext
from tools.telegram_lead import TelegramLeadTool

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


async def _make_bot(session_factory: async_sessionmaker[AsyncSession]) -> Bot:
    async with session_factory() as session:
        bot = Bot(name="test-bot")
        session.add(bot)
        await session.flush()
        await session.commit()
        return bot


async def _make_contact(
    session_factory: async_sessionmaker[AsyncSession], bot_id: uuid.UUID, wa_id: str
) -> uuid.UUID:
    async with session_factory() as session:
        contact = await match_or_create_contact(session, bot_id, wa_id=wa_id, lid=None)
        await session.commit()
        return contact.id


def _make_ctx(
    bot: Bot,
    contact_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    config: dict[str, object],
) -> ToolContext:
    return ToolContext(
        bot=bot,
        contact_id=contact_id,
        session_factory=session_factory,
        redis=None,  # type: ignore[arg-type]  # эта тулза не использует redis
        storage=None,  # type: ignore[arg-type]  # эта тулза не использует storage
        config=config,
    )


async def test_missing_chat_id_returns_error_without_calling_telegram(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_send_message(*args: object, **kwargs: object) -> None:
        raise AssertionError("не должен вызываться без chat_id")

    monkeypatch.setattr(telegram_lead_module, "send_message", fail_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000010")

    result = await TelegramLeadTool().execute(
        {"client_name": "Аяна", "details": "Интересует 2-комнатная"},
        _make_ctx(bot, contact_id, session_factory, config={}),
    )

    assert result.content == telegram_lead_module._MISSING_CHAT_ID_ERROR


async def test_successful_send_returns_confirmation_and_uses_contact_wa_id(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_send_message(chat_id: str, text: str) -> None:
        captured["chat_id"] = chat_id
        captured["text"] = text

    monkeypatch.setattr(telegram_lead_module, "send_message", fake_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000011")

    result = await TelegramLeadTool().execute(
        {"client_name": "Бекзат", "details": "Спрашивал про рассрочку"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-1001234567890"}),
    )

    assert captured["chat_id"] == "-1001234567890"
    assert "Бекзат" in str(captured["text"])
    assert "Спрашивал про рассрочку" in str(captured["text"])
    # Клиент не назвал отдельный номер -> используется wa_id контакта.
    assert "996700000011" in str(captured["text"])
    assert result.content == "Заявка отправлена менеджерам."
    assert result.override_reply_text is None
    assert result.media == ()


async def test_explicit_phone_number_overrides_contact_wa_id(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_send_message(chat_id: str, text: str) -> None:
        captured["text"] = text

    monkeypatch.setattr(telegram_lead_module, "send_message", fake_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000012")

    await TelegramLeadTool().execute(
        {"client_name": "Данияр", "phone_number": "996555000000", "details": "Хочет каталог"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-100999"}),
    )

    # Явный номер клиента идёт в поле "Телефон:"...
    assert "*Телефон:* `996555000000`" in str(captured["text"])
    assert "*Телефон:* `996700000012`" not in str(captured["text"])
    # ...но ссылка "Написать в WhatsApp" всегда ведёт на реальный wa_id
    # контакта (design doc 2026-09-08-telegram-lead-tool-design.md) —
    # LLM-номер может быть телефоном другого человека, а не тем чатом,
    # откуда фактически пишут.
    assert "996700000012" in str(captured["text"])


async def test_telegram_not_configured_returns_error_text(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_send_message(*args: object, **kwargs: object) -> None:
        raise TelegramNotConfiguredError("TELEGRAM_BOT_TOKEN не задан")

    monkeypatch.setattr(telegram_lead_module, "send_message", fail_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000013")

    result = await TelegramLeadTool().execute(
        {"client_name": "Клиент", "details": "Детали"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-100999"}),
    )

    assert result.content == telegram_lead_module._NOT_CONFIGURED_ERROR


async def test_network_failure_returns_error_text_without_raising(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_send_message(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Telegram API error: chat not found")

    monkeypatch.setattr(telegram_lead_module, "send_message", fail_send_message)

    bot = await _make_bot(session_factory)
    contact_id = await _make_contact(session_factory, bot.id, "996700000014")

    result = await TelegramLeadTool().execute(
        {"client_name": "Клиент", "details": "Детали"},
        _make_ctx(bot, contact_id, session_factory, config={"chat_id": "-100999"}),
    )

    assert result.content == "Не удалось отправить заявку в Telegram."
