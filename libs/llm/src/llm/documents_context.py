"""Список файлов бота, подмешиваемый в system prompt (FEATURES.md
4.8/4.9) — платформенное дополнение сверх V1 (там список файлов знал
только владелец бота, зашивая имена в промпт вручную; здесь LLM видит
актуальный список программно, тем же принципом, что каталог товаров 3.4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_DOCUMENTS_HEADER = "ДОСТУПНЫЕ ФАЙЛЫ (используй send_document с ТОЧНЫМ именем):"
_EMPTY_DOCUMENTS_MESSAGE = "Файлов пока нет."


@dataclass(frozen=True)
class DocumentInfo:
    filename: str


def documents_context(documents: Sequence[DocumentInfo]) -> str:
    if not documents:
        return _EMPTY_DOCUMENTS_MESSAGE
    lines = [f"- {d.filename}" for d in documents]
    return _DOCUMENTS_HEADER + "\n" + "\n".join(lines)
