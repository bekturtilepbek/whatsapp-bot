"""System prompt основного текстового ответа — одна сборка на worker
(`_reply`) и песочницу кабинета (FEATURES.md 9.6).

Раньше каждый собирал сам, и копии разъехались: песочница не подмешивала
список файлов бота (documents_context), поэтому на "Есть прайс лист?" бот в
песочнице отвечал текстом, а реальный клиент получал файл (2026-09-28).
"""

from __future__ import annotations

from collections.abc import Sequence

from .catalog_context import ProductInfo, catalog_context
from .documents_context import DocumentInfo, documents_context
from .time_context import time_context

SEND_DOCUMENT_TOOL_NAME = "send_document"
# Сколько товаров/файлов максимум уходит в контекст — общий потолок для обоих.
CONTEXT_LIST_LIMIT = 200


def build_text_system_prompt(
    bot_prompt: str | None,
    products: Sequence[ProductInfo],
    documents: Sequence[DocumentInfo] | None,
    timezone: str,
) -> str:
    """documents=None — у бота не привязан send_document: секцию файлов не
    добавляем вовсе (инструкция "зови send_document" без самой тулзы вводит
    модель в заблуждение), в отличие от пустого списка ("Файлов пока нет.").

    Порядок — как в V1 (agentInstructions + catalogContext + timeContext);
    пустые секции пропускаются, а не дают лишних пустых строк.
    """
    sections = [
        bot_prompt,
        catalog_context(products),
        documents_context(documents) if documents is not None else "",
        time_context(timezone),
    ]
    return "\n\n".join(section for section in sections if section)
