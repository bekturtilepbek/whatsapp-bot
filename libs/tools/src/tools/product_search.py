"""Поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2); при
находке дополнительно собирает карточку (FEATURES.md 4.3/4.4 — эталон V1,
vectorProductSearch + formatProductText). Точное совпадение по имени
сначала, векторный поиск — только если точного нет.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from db.product_embeddings import find_product_by_embedding
from db.product_images import list_product_images
from db.products import find_product_by_exact_name
from llm.embeddings import generate_embedding

from .base import MediaToSend, ToolContext, ToolExecutionResult

_NOT_SPECIFIED_PRICE = "Не указана"
EMBEDDING_TIMEOUT_SECONDS = 5.0


def _format_card_text(name: str, description: str | None, price: str) -> str:
    """Эталон V1 (formatProductText) при дефолтных глобальных настройках
    вывода (show_name/show_description/show_price всегда true) — сами
    переключатели ещё не реализованы (FEATURES.md 4.5/4.6, следующая
    итерация); когда появятся — эта функция получит параметр displayCfg."""
    parts = [f"*{name}*"]
    if description:
        parts.append(description)
    parts.append(f"Цена: {price}")
    return "\n".join(parts)


class ProductSearchTool:
    name = "search_products"
    description = "Ищет товар в каталоге бота по названию или похожему описанию."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Название или описание товара, которое ищет клиент"}
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        query = str(arguments.get("query", ""))
        if not query.strip():
            return ToolExecutionResult(content="[]")

        # Фото ищем СРАЗУ после нахождения товара, в ТОЙ ЖЕ сессии/ветке —
        # не в отдельном третьем открытии после generate_embedding (урок
        # 4.1/4.2: сессия не должна держаться открытой во время сетевого
        # вызова OpenAI).
        async with ctx.session_factory() as session:
            product = await find_product_by_exact_name(session, ctx.bot.id, query)
            images = await list_product_images(session, product.id) if product is not None else []

        if product is None:
            embedding = await generate_embedding(query, timeout_seconds=EMBEDDING_TIMEOUT_SECONDS)
            async with ctx.session_factory() as session:
                product = await find_product_by_embedding(session, ctx.bot.id, embedding)
                images = await list_product_images(session, product.id) if product is not None else []

        if product is None:
            return ToolExecutionResult(content="[]")

        price = str(product.price) if product.price is not None else _NOT_SPECIFIED_PRICE
        content = json.dumps(
            [{"name": product.name, "description": product.description or "", "price": price}],
            ensure_ascii=False,
        )
        return ToolExecutionResult(
            content=content,
            override_reply_text=_format_card_text(product.name, product.description, price),
            # tuple(), не список: пустой список != () при сравнении (Python
            # не считает [] и () равными), а дефолт ToolExecutionResult.media
            # — именно (). tuple() на пустом images даёт (), совпадает с
            # дефолтом и с ожиданием теста "без фото".
            media=tuple(MediaToSend(storage_key=i.storage_key, mime_type=i.mime_type) for i in images),
        )
