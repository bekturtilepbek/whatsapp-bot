"""Игнор групп и статус-рассылок (FEATURES.md 1.1)."""

from __future__ import annotations

from worker.pipeline.filters import is_ignored_chat


def test_group_chat_is_ignored() -> None:
    assert is_ignored_chat("120363000000000000@g.us") is True


def test_status_broadcast_is_ignored() -> None:
    assert is_ignored_chat("status@broadcast") is True


def test_regular_chat_is_not_ignored() -> None:
    assert is_ignored_chat("996700000000@s.whatsapp.net") is False


def test_lid_chat_is_not_ignored() -> None:
    assert is_ignored_chat("111222333@lid") is False
