"""send_reminder / _send_reminder_async: перепроверка условий при
срабатывании (FEATURES.md 5.5) — бот включён и настроен слать
напоминания, handoff не активен, клиент не ответил с момента постановки.

Тестируем async-тело напрямую (DI redis/session_factory, как _process_entry
в worker) — реальный прогон через Celery-воркер: живой прогон, docker
compose (см. план, Task 6).
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
from db.engine import make_engine, make_session_factory
from db.messages import insert_incoming, insert_outgoing
from db.models import Bot, Message
from fakeredis.aioredis import FakeRedis
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
    engine = make_engine(database_url)
    return make_session_factory(engine)


CHAT_ID = "996700000000@s.whatsapp.net"


async def _make_bot_and_contact(
    session_factory: async_sessionmaker[AsyncSession], **settings: object
) -> tuple[uuid.UUID, uuid.UUID]:
    from db.contacts import match_or_create_contact

    async with session_factory() as session:
        bot = Bot(name="test-bot", settings={"reminder_enabled": True, **settings})
        session.add(bot)
        await session.flush()
        contact = await match_or_create_contact(session, bot.id, wa_id="996700000000", lid=None)
        await session.commit()
        return bot.id, contact.id


async def test_sends_reminder_and_records_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(
        session_factory, reminder_message="Напоминаем о себе!"
    )
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "исходный ответ бота")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )

        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert "Напоминаем о себе!" in out_entries[1][1]["payload"]

        async with session_factory() as session:
            messages = (
                (
                    await session.execute(
                        select(Message)
                        .where(Message.contact_id == contact_id)
                        .order_by(Message.seq)
                    )
                )
                .scalars()
                .all()
            )
            assert [m.content for m in messages] == [
                "исходный ответ бота",
                "Напоминаем о себе!",
            ]
    finally:
        await redis.aclose()


async def test_uses_default_message_when_not_configured(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import DEFAULT_REMINDER_MESSAGE, _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)  # без reminder_message
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        out_entries = await redis.xrange("wa:out")
        assert DEFAULT_REMINDER_MESSAGE in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_uses_default_message_when_configured_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """bots.settings — свободный JSONB без схемы (db.bots.update_bot мержит
    патч как есть): будущий UI настроек или ручная правка может выставить
    reminder_message="" — падать с ValidationError на OutboundText(min_length=1)
    нельзя, должен сработать дефолт.
    """
    from tasks.followup import DEFAULT_REMINDER_MESSAGE, _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory, reminder_message="")
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2
        assert DEFAULT_REMINDER_MESSAGE in out_entries[1][1]["payload"]
    finally:
        await redis.aclose()


async def test_skips_when_customer_already_replied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ бота")
        await session.commit()
    async with session_factory() as session:
        await insert_incoming(
            session, bot_id, contact_id, "клиент ответил", "wamsg-1", datetime.now(UTC)
        )
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_skips_when_manager_replied(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Gate 4 расширен с role='user' на любое более новое сообщение
    (FEATURES.md 5.5, разбор controller): ответ менеджера логируется как
    role='assistant' (см. _handle_manager_message в consumer.py) — раньше
    напоминание всё равно уходило клиенту поверх уже решённого вопроса.
    """
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ бота")
        await session.commit()
    async with session_factory() as session:
        await insert_outgoing(session, bot_id, contact_id, "[Ответ менеджера] решили вопрос")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_duplicate_delivery_sends_reminder_only_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Redis-брокер может доставить ETA-задачу повторно (visibility_timeout,
    см. celery_app.py) — симулируем это прямым повторным вызовом
    _send_reminder_async с идентичными аргументами и тем же redis.

    Примечание: этот тест проходит не благодаря guard'у SET NX (как можно
    предположить), а потому что вторая доставка попадает в gate 4, которая
    обнаруживает более новое сообщение, созданное первой доставкой. Для
    изолированного тестирования самого guard'а — см.
    test_idempotency_guard_blocks_duplicate_when_key_already_set.
    """
    from tasks.followup import DEFAULT_REMINDER_MESSAGE, _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ бота")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )

        out_entries = await redis.xrange("wa:out")
        assert len(out_entries) == 2  # ровно один typing + один text, не два раза

        async with session_factory() as session:
            reminders = (
                (
                    await session.execute(
                        select(Message).where(
                            Message.contact_id == contact_id,
                            Message.role == "assistant",
                            Message.content == DEFAULT_REMINDER_MESSAGE,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(reminders) == 1  # не два — вторая доставка не должна была дописать строку
    finally:
        await redis.aclose()


async def test_skips_when_reminder_disabled_since_scheduling(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory, reminder_enabled=False)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_skips_when_handoff_active(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from core.redis_keys import handoff_key
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await redis.set(handoff_key(str(bot_id), CHAT_ID), "1", ex=600)
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_skips_when_bot_disabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ")
        from db.bots import update_bot

        await update_bot(session, bot_id, enabled=False)
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()


async def test_idempotency_guard_blocks_duplicate_when_key_already_set(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Guard'ом на основе SET NX EX можно сразу же блокировать повторную
    доставку, если ключ в Redis уже установлен — без необходимости
    дожидаться gate 4. Тестируем это в изолированном режиме: pre-set guard'а
    перед вызовом, все остальные условия чистые (бот включён, reminder_enabled,
    handoff не активен, нет более новых сообщений) — единственное, что может
    остановить доставку, это сам guard.
    """
    from core.redis_keys import followup_sent_key
    from tasks.followup import _send_reminder_async

    bot_id, contact_id = await _make_bot_and_contact(session_factory)
    async with session_factory() as session:
        seq = await insert_outgoing(session, bot_id, contact_id, "ответ бота")
        await session.commit()

    redis = FakeRedis(decode_responses=True)
    try:
        # Guard's key is already set — симулирует задачу, повторно доставленную
        # брокером уже после того, как первая доставка отправила (или готовилась
        # отправить). Все 4 gate'ы проходят чисто (нет более нового сообщения,
        # handoff не активен, бот включён, reminder_enabled) — единственное, что
        # может остановить этот вызов, это сам guard SET NX.
        await redis.set(followup_sent_key(str(contact_id), seq), "1", ex=172800)

        await _send_reminder_async(
            redis, session_factory, str(bot_id), str(contact_id), CHAT_ID, seq
        )

        # Никаких событий в очередь не должно быть: не typing, не text.
        assert await redis.xlen("wa:out") == 0
    finally:
        await redis.aclose()
