"""Поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2). Точное
совпадение по имени сначала (эталон V1: node-bot3/whatsapp.js
vectorProductSearch), векторный поиск — только если точного нет.
"""

from __future__ import annotations

import json
from typing import Any

from db.product_embeddings import find_product_by_embedding
from db.products import find_product_by_exact_name
from llm.embeddings import generate_embedding

from .base import ToolContext

_NOT_SPECIFIED_PRICE = "Не указана"

# Бюджет на 3 попытки + backoff (1с+2с) должен уместиться в
# TOOL_CALL_TIMEOUT_SECONDS=20с исполнителя тулз (worker/pipeline/tool_loop.py) —
# иначе внешний asyncio.wait_for там отменяет весь вызов раньше, чем
# успевает сработать хоть один ретрай.
EMBEDDING_TIMEOUT_SECONDS = 5.0


class ProductSearchTool:
    name = "search_products"
    description = "Ищет товар в каталоге бота по названию или похожему описанию."
    # Не ClassVar: Tool (base.py) — Protocol, где parameters_schema объявлен
    # как атрибут экземпляра; mypy strict сверяет структуру буквально и не
    # засчитывает класс с ClassVar-версией как реализацию Tool. Схема
    # только читается (JSON schema для OpenAI), не мутируется в рантайме.
    parameters_schema: dict[str, Any] = {  # noqa: RUF012
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Название или описание товара, которое ищет клиент",
            }
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        query = str(arguments.get("query", ""))
        if not query.strip():
            return "[]"

        async with ctx.session_factory() as session:
            product = await find_product_by_exact_name(session, ctx.bot.id, query)

        if product is None:
            embedding = await generate_embedding(query, timeout_seconds=EMBEDDING_TIMEOUT_SECONDS)
            async with ctx.session_factory() as session:
                product = await find_product_by_embedding(session, ctx.bot.id, embedding)

        if product is None:
            return "[]"

        price = str(product.price) if product.price is not None else _NOT_SPECIFIED_PRICE
        return json.dumps(
            [{"name": product.name, "description": product.description or "", "price": price}],
            ensure_ascii=False,
        )
