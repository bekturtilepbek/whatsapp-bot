"""Нормализация номера телефона (FEATURES.md 9.1).

Правила — эталон V1 (node-bot3/whatsapp.js::formatPhoneNumber): там она
приводила номер, который клиент назвал боту, к единому виду для
Telegram-заявки. Здесь то же правило нужно ещё и чёрному списку: номер
контакта приходит из WhatsApp как wa_id (996700123456), а владелец бота
вводит его в местном формате (0700 123 456) — без приведения блокировка
молча не срабатывала.
"""

from __future__ import annotations

import re

_KG_CODE = "996"


def normalize_phone_digits(raw: str) -> str:
    """Только цифры, в формате wa_id (с кодом страны, без "+").

    - 9 цифр (700123456) — кыргызский номер без кода: добавляем 996;
    - 10 цифр с ведущим 0 (0700123456) — местный формат: 0 → 996;
    - остальное (уже с кодом, другие страны) — как есть.
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 9:
        return _KG_CODE + digits
    if len(digits) == 10 and digits.startswith("0"):
        return _KG_CODE + digits[1:]
    return digits


def format_phone_for_display(raw: str) -> str:
    """Номер для человека (Telegram-заявка): "+996700123456". Если в строке
    нет цифр ("не скажу") — возвращаем её как есть, а не голый "+"."""
    digits = normalize_phone_digits(raw)
    return f"+{digits}" if digits else raw
