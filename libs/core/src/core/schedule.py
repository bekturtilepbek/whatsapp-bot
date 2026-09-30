"""Рабочий график бота (FEATURES.md 1.6).

Правила — эталон V1 (node-bot3/whatsapp.js, "ЛОГИКА РАБОЧЕГО ГРАФИКА"):
целые часы, [start, end) в пределах суток; start > end — ночная смена через
полночь; start == end — круглосуточно. Отличие от V1: время в таймзоне бота
(bots.timezone), а не захардкоженный Бишкек.

Нужна и worker'у (не отвечать вне графика), и celery (не слать напоминание
ночью) — поэтому здесь, в libs/core.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_WORK_START_HOUR = 9
DEFAULT_WORK_END_HOUR = 18
DEFAULT_TIMEZONE = "Asia/Bishkek"


def _hour(value: Any, default: int) -> int:
    # settings — произвольный dict (API его не валидирует): мусор не должен
    # ронять пайплайн, откатываемся на дефолт.
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 23:
        return value
    return default


def is_within_schedule(settings: dict[str, Any], timezone: str, now: datetime) -> bool:
    """True — бот сейчас работает. График выключен или не настроен — всегда True
    (у существующих ботов ключей нет, их поведение не меняется)."""
    if not settings.get("schedule_enabled", False):
        return True
    start = _hour(settings.get("work_start_hour"), DEFAULT_WORK_START_HOUR)
    end = _hour(settings.get("work_end_hour"), DEFAULT_WORK_END_HOUR)
    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    hour = now.astimezone(tz).hour
    if start < end:
        return start <= hour < end
    if start > end:
        return hour >= start or hour < end
    return True
