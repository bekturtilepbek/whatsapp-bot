"""Плейсхолдеры медиа для messages.content."""

from __future__ import annotations

from worker.pipeline.media import incoming_content


def test_plain_text_passes_through() -> None:
    assert incoming_content("привет", None) == "привет"


def test_image_without_caption_gets_placeholder() -> None:
    assert incoming_content("", "image") == "[фото]"


def test_image_with_caption_uses_caption_text() -> None:
    assert incoming_content("такой есть?", "image") == "такой есть?"


def test_unknown_media_type_gets_generic_placeholder() -> None:
    assert incoming_content("", "poll") == "[медиа]"


def test_empty_text_no_media_stays_empty() -> None:
    assert incoming_content("", None) == ""
