"""Нормализация номера (FEATURES.md 9.1) — правила эталона V1
(node-bot3/whatsapp.js::formatPhoneNumber)."""

from __future__ import annotations

import pytest
from core.phone import format_phone_for_display, normalize_phone_digits


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0700 123 456", "996700123456"),  # местный формат с ведущим 0
        ("700123456", "996700123456"),  # 9 цифр без кода
        ("+996 (700) 12-34-56", "996700123456"),  # уже международный
        ("996700123456", "996700123456"),
        ("+7 912 345 67 89", "79123456789"),  # не KG — как есть, только цифры
        ("", ""),
        ("abc", ""),
    ],
)
def test_normalize_phone_digits(raw: str, expected: str) -> None:
    assert normalize_phone_digits(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0700 123 456", "+996700123456"),
        ("+7 912 345 67 89", "+79123456789"),
        ("", ""),
        ("не скажу", "не скажу"),  # не номер — показываем как есть, не "+"
    ],
)
def test_format_phone_for_display(raw: str, expected: str) -> None:
    assert format_phone_for_display(raw) == expected
