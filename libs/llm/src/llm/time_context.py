"""Текущее время бота, подмешиваемое в system prompt (FEATURES.md 3.3)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_WEEKDAYS_RU = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]
_MONTHS_RU = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


def time_context(timezone: str, now: datetime | None = None) -> str:
    """Строка вида "четверг, 2 сентября 2026 года, 14:05 (Asia/Bishkek)"."""
    tz = ZoneInfo(timezone)
    moment = (now or datetime.now(tz)).astimezone(tz)
    weekday = _WEEKDAYS_RU[moment.weekday()]
    month = _MONTHS_RU[moment.month]
    return (
        f"Текущие дата и время: {weekday}, {moment.day} {month} {moment.year} года, "
        f"{moment.strftime('%H:%M')} ({timezone})"
    )
