"""Плейсхолдеры медиа в истории (FEATURES.md 2.6). Ответ-заглушка на медиа
(без LLM, settings.media_fallback_text) подключается в консюмере отдельно —
здесь только текстовое представление входящего для messages.content.
"""

from __future__ import annotations

_PLACEHOLDER_BY_MEDIA_TYPE: dict[str, str] = {
    "image": "[фото]",
    "video": "[видео]",
    "audio": "[голосовое сообщение]",
    "document": "[документ]",
    "sticker": "[стикер]",
}

DEFAULT_MEDIA_PLACEHOLDER = "[медиа]"


def incoming_content(text: str, media_type: str | None) -> str:
    """Текст для messages.content: сам текст, а для медиа без подписи — плейсхолдер."""
    if text:
        return text
    if media_type is not None:
        return _PLACEHOLDER_BY_MEDIA_TYPE.get(media_type, DEFAULT_MEDIA_PLACEHOLDER)
    return text
