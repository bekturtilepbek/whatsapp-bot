"""Ответ несколькими сообщениями (FEATURES.md 3.5).

Эталон V1 (прислан пользователем 2026-09-30, в архиве копия с этой функцией
не сохранилась):

    function splitMessage(text) {
      const parts = text.split(/\\n\\s*\\n/);
      return parts.filter(part => part.trim().length > 0);
    }

Отличие только одно: края каждой части обрезаются (strip) — в V1 куски шли
с хвостовыми пробелами/переводами строк, клиенту они не видны, а в тестах и
логах мешают.
"""

from __future__ import annotations

import re

_BLANK_LINE = re.compile(r"\n\s*\n")


def split_reply(text: str) -> list[str]:
    return [part.strip() for part in _BLANK_LINE.split(text) if part.strip()]
