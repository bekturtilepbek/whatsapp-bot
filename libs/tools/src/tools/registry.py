"""Реестр доступных тулз (FEATURES.md 4.13). Первая настоящая тулза —
поиск товара (FEATURES.md 4.1/4.2).
"""

from __future__ import annotations

from .base import Tool
from .product_search import ProductSearchTool

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Ключ реестра — ВСЕГДА tool.name, никогда отдельная строка —
    расхождение между ними было находкой финального ревью инфраструктуры
    тулз (2026-09-05): если тулза зарегистрирована под другим ключом, чем
    её собственное имя, get_tool(tool.name) вернёт None и тулза станет
    недоступной, даже если включена через tool_bindings."""
    _REGISTRY[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tool_names() -> list[str]:
    return list(_REGISTRY)


register(ProductSearchTool())
