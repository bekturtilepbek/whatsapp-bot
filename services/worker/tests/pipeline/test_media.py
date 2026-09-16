"""Плейсхолдеры медиа для messages.content."""

from __future__ import annotations

from worker.pipeline.media import incoming_content, quote_prefix


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


def test_quote_prefix_with_quoted_text() -> None:
    """FEATURES.md 1.4, эталон V1 (resolveQuotedContext): '[В ответ на:
    "..."]\\n'."""
    assert quote_prefix("Товар ещё в наличии?", None) == '[В ответ на: "Товар ещё в наличии?"]\n'


def test_quote_prefix_with_media_type_when_no_text() -> None:
    """Цитата на фото без подписи — в V1 контекст не терялся, передавался
    тип цитируемого сообщения вместо текста."""
    assert quote_prefix(None, "image") == "[В ответ на: фото]\n"


def test_quote_prefix_prefers_text_over_media_type() -> None:
    assert quote_prefix("Привет", "image") == '[В ответ на: "Привет"]\n'


def test_quote_prefix_empty_when_nothing_quoted() -> None:
    assert quote_prefix(None, None) == ""


def test_quote_prefix_unknown_media_type_gets_generic_word() -> None:
    assert quote_prefix(None, "poll") == "[В ответ на: медиа]\n"
