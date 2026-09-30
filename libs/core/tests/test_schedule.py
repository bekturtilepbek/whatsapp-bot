"""Рабочий график бота (FEATURES.md 1.6) — правила эталона V1
(node-bot3/whatsapp.js, "ЛОГИКА РАБОЧЕГО ГРАФИКА")."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from core.schedule import is_within_schedule

BISHKEK = "Asia/Bishkek"  # UTC+6


def _at_bishkek_hour(hour: int) -> datetime:
    # Бишкек = UTC+6 круглый год
    return datetime(2026, 9, 30, (hour - 6) % 24, 30, tzinfo=UTC)


def test_schedule_disabled_means_always_working() -> None:
    settings = {"schedule_enabled": False, "work_start_hour": 9, "work_end_hour": 18}
    assert is_within_schedule(settings, BISHKEK, _at_bishkek_hour(3))


def test_missing_settings_mean_always_working() -> None:
    # У всех существующих ботов ключей нет — поведение не должно поменяться.
    assert is_within_schedule({}, BISHKEK, _at_bishkek_hour(3))


@pytest.mark.parametrize(("hour", "working"), [(8, False), (9, True), (17, True), (18, False)])
def test_day_shift_uses_bot_timezone(hour: int, working: bool) -> None:
    settings = {"schedule_enabled": True, "work_start_hour": 9, "work_end_hour": 18}
    assert is_within_schedule(settings, BISHKEK, _at_bishkek_hour(hour)) is working


@pytest.mark.parametrize(("hour", "working"), [(20, False), (21, True), (2, True), (9, False)])
def test_night_shift_wraps_midnight(hour: int, working: bool) -> None:
    settings = {"schedule_enabled": True, "work_start_hour": 21, "work_end_hour": 9}
    assert is_within_schedule(settings, BISHKEK, _at_bishkek_hour(hour)) is working


def test_equal_start_and_end_means_round_the_clock() -> None:
    settings = {"schedule_enabled": True, "work_start_hour": 10, "work_end_hour": 10}
    assert is_within_schedule(settings, BISHKEK, _at_bishkek_hour(3))


def test_defaults_are_9_to_18_when_only_enabled() -> None:
    settings = {"schedule_enabled": True}
    assert not is_within_schedule(settings, BISHKEK, _at_bishkek_hour(20))
    assert is_within_schedule(settings, BISHKEK, _at_bishkek_hour(12))


def test_garbage_hours_fall_back_to_defaults_instead_of_crashing() -> None:
    # settings — произвольный dict (API его не валидирует).
    settings = {"schedule_enabled": True, "work_start_hour": "abc", "work_end_hour": 99}
    assert is_within_schedule(settings, BISHKEK, _at_bishkek_hour(12))
    assert not is_within_schedule(settings, BISHKEK, _at_bishkek_hour(20))


def test_unknown_timezone_falls_back_to_bishkek() -> None:
    settings = {"schedule_enabled": True, "work_start_hour": 9, "work_end_hour": 18}
    assert is_within_schedule(settings, "Not/AZone", _at_bishkek_hour(12))
