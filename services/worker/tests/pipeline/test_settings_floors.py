"""Нижние пороги числовых настроек бота на стороне worker.

`PATCH /bots/{id}` принимает `settings` как произвольный dict без валидации
значений — кабинет единственный, кто проверяет числа, и до фикса 2026-09-28
пустое поле формы сохранялось как 0. Эти тесты — защита второго рубежа:
что бы ни лежало в bots.settings, worker не должен сломаться/заспамить.

Чистые юнит-тесты, без Docker: обе функции читают только bot.settings.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from db.models import Bot
from worker.pipeline import consumer as consumer_module
from worker.pipeline.consumer import _handoff_ttl_seconds, _schedule_follow_up


def _bot(**settings: object) -> Bot:
    return Bot(id=uuid.uuid4(), name="t", enabled=True, timezone="Asia/Bishkek", settings=settings)


@pytest.mark.parametrize("value", [0, 0.001, -5])
def test_handoff_ttl_never_below_one_minute(value: float) -> None:
    # 0 -> SET ... EX 0 -> Redis отвергает команду ("invalid expire time"):
    # каждое сообщение менеджера падало, handoff не ставился, и бот
    # продолжал отвечать клиенту поверх менеджера.
    assert _handoff_ttl_seconds(_bot(auto_release_minutes=value)) == 60


def test_handoff_ttl_keeps_normal_values() -> None:
    assert _handoff_ttl_seconds(_bot(auto_release_minutes=12)) == 720


@pytest.mark.parametrize("value", [0, -3])
async def test_follow_up_delay_never_below_one_minute(
    monkeypatch: pytest.MonkeyPatch, value: float
) -> None:
    # 0 -> eta = "сейчас": напоминание уходило клиенту через секунды после
    # каждого ответа бота (и лишняя исходящая активность — анти-бан-риск).
    captured: dict[str, Any] = {}

    def fake_send_task(name: str, *, args: list[object], eta: datetime) -> None:
        captured["eta"] = eta

    monkeypatch.setattr(consumer_module.celery_app, "send_task", fake_send_task)

    before = datetime.now(UTC)
    await _schedule_follow_up(
        _bot(reminder_enabled=True, reminder_delay_minutes=value),
        "996700000000@s.whatsapp.net",
        uuid.uuid4(),
        1,
    )

    assert captured["eta"] >= before + timedelta(minutes=1)
