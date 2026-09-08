"""Реестр тулз (FEATURES.md 4.13): get_tool/all_tool_names/register.
Первая настоящая тулза — search_products (FEATURES.md 4.1/4.2).
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from tools import registry
from tools.base import ToolExecutionResult
from tools.product_search import ProductSearchTool


class _DummyTool:
    name = "dummy"
    description = "тестовая тулза"
    parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, object], ctx: object) -> ToolExecutionResult:
        return ToolExecutionResult(content="ok")


def test_get_tool_returns_none_for_unregistered_name() -> None:
    assert registry.get_tool("does_not_exist") is None


def test_all_tool_names_includes_search_products() -> None:
    """Первая настоящая тулза (FEATURES.md 4.1) — реестр больше не пуст."""
    assert "search_products" in registry.all_tool_names()


def test_production_registry_resolves_search_products_to_the_real_tool() -> None:
    tool = registry.get_tool("search_products")
    assert isinstance(tool, ProductSearchTool)
    assert tool.name == "search_products"


def test_register_stores_under_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # Подменяем сам объект словаря на его копию, чтобы не мутировать
    # реальный продакшн-реестр (уже содержит search_products) — monkeypatch
    # откатывает подмену после теста, без ручной очистки.
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))
    dummy = _DummyTool()
    registry.register(dummy)

    assert registry.get_tool("dummy") is dummy
    assert "dummy" in registry.all_tool_names()


def test_get_tool_and_all_tool_names_reflect_registered_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = _DummyTool()
    monkeypatch.setitem(registry._REGISTRY, "dummy", dummy)

    assert registry.get_tool("dummy") is dummy
    assert "dummy" in registry.all_tool_names()


def test_all_tool_names_includes_send_telegram_lead() -> None:
    """Вторая настоящая тулза (FEATURES.md 4.7)."""
    assert "send_telegram_lead" in registry.all_tool_names()


def test_all_tool_names_includes_send_document() -> None:
    """Третья настоящая тулза (FEATURES.md 4.8/4.9)."""
    assert "send_document" in registry.all_tool_names()
