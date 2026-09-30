"""Ответ несколькими сообщениями (FEATURES.md 3.5) — splitMessage эталона V1:
text.split(/\\n\\s*\\n/) и выбросить пустые куски."""

from __future__ import annotations

from worker.pipeline.reply_split import split_reply


def test_splits_on_blank_lines() -> None:
    assert split_reply("Привет!\n\nВот каталог.\n\nЧто выберете?") == [
        "Привет!",
        "Вот каталог.",
        "Что выберете?",
    ]


def test_blank_line_with_spaces_also_splits() -> None:
    # \n\s*\n — пробелы/табы на "пустой" строке не мешают разбиению
    assert split_reply("Раз\n   \t\nДва") == ["Раз", "Два"]


def test_single_newlines_stay_together() -> None:
    text = "Размеры:\n- S\n- M\n- L"
    assert split_reply(text) == [text]


def test_empty_parts_are_dropped() -> None:
    assert split_reply("\n\nОдин\n\n\n\n\nДва\n\n") == ["Один", "Два"]


def test_empty_text_gives_no_parts() -> None:
    assert split_reply("") == []
    assert split_reply("   \n\n  ") == []
