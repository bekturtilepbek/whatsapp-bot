"""Игнор групп и статус-рассылок (FEATURES.md 1.1)."""

from __future__ import annotations


def is_ignored_chat(chat_id: str) -> bool:
    return chat_id.endswith("@g.us") or chat_id == "status@broadcast"
