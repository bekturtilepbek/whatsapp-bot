"""Реестр тулз (FEATURES.md 4.13): get_tool/all_tool_names. Пуст в
продакшн-коде на этой итерации — тесты monkeypatch'ят _REGISTRY напрямую,
не полагаясь ни на одну настоящую тулзу.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from tools import registry


class _DummyTool:
    name = "dummy"
    description = "тестовая тулза"
    parameters_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, object], ctx: object) -> str:
        return "ok"


def test_get_tool_returns_none_for_unregistered_name() -> None:
    assert registry.get_tool("does_not_exist") is None


def test_all_tool_names_empty_by_default() -> None:
    """Реестр пуст в этой итерации (инфраструктура без тулз) — первая
    настоящая тулза (следующая итерация, 4.1) обновит этот тест."""
    assert registry.all_tool_names() == []


def test_get_tool_and_all_tool_names_reflect_registered_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dummy = _DummyTool()
    monkeypatch.setitem(registry._REGISTRY, "dummy", dummy)

    assert registry.get_tool("dummy") is dummy
    assert registry.all_tool_names() == ["dummy"]
