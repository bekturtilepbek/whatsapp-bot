"""Эмбеддинг товара для векторного поиска (FEATURES.md 4.1). Эталон V1
(add_product/update_product, central-admin/main.py): text-embedding-3-small,
комбинированный текст "Name: {name}; Description: {description}".
"""

from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from .client import (
    _RETRYABLE_EXCEPTIONS,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BASE_DELAY_SECONDS,
    RETRY_MAX_ATTEMPTS,
    _default_client,
)

EMBEDDING_MODEL = "text-embedding-3-small"


def product_embedding_input(name: str, description: str | None) -> str:
    return f"Name: {name}; Description: {description or ''}"


async def generate_embedding(
    text: str,
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> list[float]:
    """Тот же ретрай-принцип, что и _call_and_extract в client.py (3
    попытки, backoff 1с/2с, те же retryable-исключения) — отдельный
    небольшой цикл, не общий рефакторинг: не трогаем уже протестированный
    текстовый путь ради этой фичи.
    """
    active_client = client or _default_client()
    response = None
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            response = await active_client.embeddings.create(
                model=EMBEDDING_MODEL, input=text, timeout=timeout_seconds
            )
            break
        except _RETRYABLE_EXCEPTIONS:
            if attempt == RETRY_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    assert response is not None  # pragma: no cover
    return response.data[0].embedding
