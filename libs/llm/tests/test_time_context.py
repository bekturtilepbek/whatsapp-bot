"""Форматирование времени бота для system prompt (FEATURES.md 3.3)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from llm.time_context import time_context


def test_formats_weekday_date_and_time_in_bot_timezone() -> None:
    moment = datetime(2026, 9, 3, 14, 5, tzinfo=ZoneInfo("Asia/Bishkek"))  # четверг
    result = time_context("Asia/Bishkek", now=moment)
    assert result == "Текущие дата и время: четверг, 3 сентября 2026 года, 14:05 (Asia/Bishkek)"


def test_converts_from_a_different_source_timezone() -> None:
    # то же мгновение, но передано в UTC — должно пересчитаться в TZ бота
    moment_utc = datetime(2026, 9, 3, 8, 5, tzinfo=ZoneInfo("UTC"))
    result = time_context("Asia/Bishkek", now=moment_utc)
    assert "14:05" in result
