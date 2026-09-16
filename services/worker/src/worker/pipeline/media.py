"""Плейсхолдеры медиа в истории (FEATURES.md 2.6) и контекст цитирования
(FEATURES.md 1.4). Ответ-заглушка на медиа (без LLM, settings.media_fallback_text)
подключается в консюмере отдельно — здесь только текстовое представление
входящего для messages.content.
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


def quote_prefix(quoted_text: str | None, quoted_media_type: str | None) -> str:
    """Контекст цитируемого сообщения, подмешиваемый в начало содержимого
    текущего хода — эталон V1 (resolveQuotedContext, node-bot3/whatsapp.js):
    '[В ответ на: "..."]\\n'. Если у цитаты нет текста (медиа без подписи) —
    не теряем контекст молча, как теряла бы голая проверка на quoted_text,
    а называем тип цитируемого сообщения (то же слово, что и у плейсхолдера
    медиа, без скобок — единый словарь, не дублируем русские слова)."""
    if quoted_text:
        return f'[В ответ на: "{quoted_text}"]\n'
    if quoted_media_type is not None:
        word = _PLACEHOLDER_BY_MEDIA_TYPE.get(quoted_media_type, DEFAULT_MEDIA_PLACEHOLDER)
        return f"[В ответ на: {word.strip('[]')}]\n"
    return ""
