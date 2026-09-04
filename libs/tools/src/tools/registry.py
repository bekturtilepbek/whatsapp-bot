"""Реестр доступных тулз (FEATURES.md 4.13). Пуст в этой итерации —
инфраструктура без единой настоящей тулзы; заполняется в следующих
итерациях Волны 2 (первая — 4.1, pgvector-поиск товара).

Какие тулзы ВКЛЮЧЕНЫ конкретному боту — решает не этот файл, а таблица
tool_bindings (libs/db/src/db/tool_bindings.py); этот реестр — что вообще
существует в коде.
"""

from __future__ import annotations

from .base import Tool

_REGISTRY: dict[str, Tool] = {}


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tool_names() -> list[str]:
    return list(_REGISTRY)
