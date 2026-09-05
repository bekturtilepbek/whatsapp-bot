"""Форматирование каталога товаров для system prompt (FEATURES.md 3.4).
Формат — точное соответствие V1 (getCatalogContext, whatsapp.js): заголовок
+ "- {name} | Цена: {price или '-'} | Описание: {description или '-'}" на
товар, пустой каталог -> отдельное сообщение.
"""

from __future__ import annotations

from llm.catalog_context import ProductInfo, catalog_context


def test_empty_catalog_returns_the_empty_message() -> None:
    assert catalog_context([]) == "Каталог товаров пуст."


def test_single_product_with_all_fields() -> None:
    result = catalog_context(
        [ProductInfo(name="Кроссовки Nike Air", price="5000.00", description="Беговые")]
    )
    assert result == (
        "КАТАЛОГ ТОВАРОВ В БАЗЕ (ИСПОЛЬЗУЙ ДЛЯ КОНСУЛЬТАЦИИ):\n"
        "- Кроссовки Nike Air | Цена: 5000.00 | Описание: Беговые"
    )


def test_missing_price_and_description_render_as_dash() -> None:
    result = catalog_context([ProductInfo(name="Товар без деталей", price=None, description=None)])
    assert result == (
        "КАТАЛОГ ТОВАРОВ В БАЗЕ (ИСПОЛЬЗУЙ ДЛЯ КОНСУЛЬТАЦИИ):\n"
        "- Товар без деталей | Цена: - | Описание: -"
    )


def test_multiple_products_join_with_newlines_in_given_order() -> None:
    result = catalog_context(
        [
            ProductInfo(name="Апельсины", price="150", description=None),
            ProductInfo(name="Бананы", price="120", description="Из Эквадора"),
        ]
    )
    assert result == (
        "КАТАЛОГ ТОВАРОВ В БАЗЕ (ИСПОЛЬЗУЙ ДЛЯ КОНСУЛЬТАЦИИ):\n"
        "- Апельсины | Цена: 150 | Описание: -\n"
        "- Бананы | Цена: 120 | Описание: Из Эквадора"
    )
