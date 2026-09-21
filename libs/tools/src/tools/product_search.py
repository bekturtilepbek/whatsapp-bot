"""Поиск товара — первая настоящая тулза (FEATURES.md 4.1/4.2); при
находке дополнительно собирает карточку (FEATURES.md 4.3/4.4/4.5/4.6 —
эталон V1, vectorProductSearch + formatProductText + resolveProductDisplay).
Точное совпадение по имени сначала, векторный поиск — только если точного
нет.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from db.product_embeddings import find_product_by_embedding
from db.product_media import list_product_media
from db.products import find_product_by_exact_name
from llm.embeddings import generate_embedding

from .base import MediaToSend, ToolContext, ToolExecutionResult

_NOT_SPECIFIED_PRICE = "Не указана"
EMBEDDING_TIMEOUT_SECONDS = 5.0
_DISPLAY_KEYS = ("show_name", "show_description", "show_price")


def _resolve_display_config(
    bot_settings: dict[str, Any], product_display_custom: dict[str, Any]
) -> dict[str, bool]:
    """Эталон V1 (resolveProductDisplay): «всё или ничего» — если на
    товаре задан display_custom (непустой словарь), он используется
    ЦЕЛИКОМ вместо глобальных настроек бота (bots.settings["product_display"]),
    даже если внутри задан только один ключ. Отсутствующий ключ внутри
    выбранного источника — дефолт true (в V1 такой возможности не было,
    его колонки show_* были NOT NULL с явным значением всегда)."""
    if product_display_custom:
        source = product_display_custom
    else:
        source = bot_settings.get("product_display", {})
    return {key: bool(source.get(key, True)) for key in _DISPLAY_KEYS}


def _format_card_text(
    name: str, description: str | None, price: str, display_cfg: dict[str, bool]
) -> str:
    """Эталон V1 (formatProductText) с учётом переключателей вывода
    (FEATURES.md 4.5/4.6). Отличие от V1: show_price у нас всегда
    показывает строку цены (с фоллбэком "Не указана"), не скрывает её
    целиком при отсутствующей цене — уже согласованное поведение 4.3/4.4,
    переключатель этого не меняет."""
    parts = []
    if display_cfg["show_name"]:
        parts.append(f"*{name}*")
    if display_cfg["show_description"] and description:
        parts.append(description)
    if display_cfg["show_price"]:
        parts.append(f"Цена: {price}")
    return "\n".join(parts)


class ProductSearchTool:
    name = "search_products"
    description = "Ищет товар в каталоге бота по названию или похожему описанию."
    side_effecting = False
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Название или описание товара, которое ищет клиент",
            }
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        query = str(arguments.get("query", ""))
        if not query.strip():
            return ToolExecutionResult(content="[]")

        # Медиа ищем СРАЗУ после нахождения товара, в ТОЙ ЖЕ сессии/ветке —
        # не в отдельном третьем открытии после generate_embedding (урок
        # 4.1/4.2: сессия не должна держаться открытой во время сетевого
        # вызова OpenAI).
        async with ctx.session_factory() as session:
            product = await find_product_by_exact_name(session, ctx.bot.id, query)
            media_items = (
                await list_product_media(session, product.id) if product is not None else []
            )

        if product is None:
            embedding = await generate_embedding(query, timeout_seconds=EMBEDDING_TIMEOUT_SECONDS)
            async with ctx.session_factory() as session:
                product = await find_product_by_embedding(session, ctx.bot.id, embedding)
                media_items = (
                    await list_product_media(session, product.id) if product is not None else []
                )

        if product is None:
            return ToolExecutionResult(content="[]")

        price = str(product.price) if product.price is not None else _NOT_SPECIFIED_PRICE
        content = json.dumps(
            [{"name": product.name, "description": product.description or "", "price": price}],
            ensure_ascii=False,
        )
        display_cfg = _resolve_display_config(ctx.bot.settings, product.display_custom)
        return ToolExecutionResult(
            content=content,
            override_reply_text=_format_card_text(
                product.name, product.description, price, display_cfg
            ),
            # tuple(), не список: пустой список != () при сравнении (Python
            # не считает [] и () равными), а дефолт ToolExecutionResult.media
            # — именно (). tuple() на пустом media_items даёт (), совпадает с
            # дефолтом и с ожиданием теста "без медиа".
            media=tuple(
                MediaToSend(storage_key=i.storage_key, mime_type=i.mime_type)
                for i in media_items
            ),
        )
