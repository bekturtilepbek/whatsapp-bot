"""Каталог товаров, подмешиваемый в system prompt (FEATURES.md 3.4).
Формат — эталон V1 (getCatalogContext, whatsapp.js): только name/price/
description идут в контекст LLM (sku/display_custom — для 4.5/4.6, там же
и появятся у отправки карточки, не здесь).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

_CATALOG_HEADER = "КАТАЛОГ ТОВАРОВ В БАЗЕ (ИСПОЛЬЗУЙ ДЛЯ КОНСУЛЬТАЦИИ):"
_EMPTY_CATALOG_MESSAGE = "Каталог товаров пуст."


@dataclass(frozen=True)
class ProductInfo:
    name: str
    price: str | None
    description: str | None


def catalog_context(products: Sequence[ProductInfo]) -> str:
    if not products:
        return _EMPTY_CATALOG_MESSAGE
    lines = [
        f"- {p.name} | Цена: {p.price or '-'} | Описание: {p.description or '-'}"
        for p in products
    ]
    return _CATALOG_HEADER + "\n" + "\n".join(lines)
