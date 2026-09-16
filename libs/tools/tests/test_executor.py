"""tool_specs_for_bindings()/build_tool_executor() (FEATURES.md 4.13,
9.6 часть A) — сборка ToolSpec-списка и ToolExecutor из tool_bindings.
Перенесено из services/worker/src/worker/pipeline/consumer.py (было
приватными _tool_specs_for_bindings/_make_tool_executor) — нужно и
worker'у, и api (песочница), поэтому теперь общий код libs/tools.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest
from db.models import ToolBinding
from fakeredis.aioredis import FakeRedis
from structlog.testing import capture_logs
from tools import registry as tools_registry
from tools.base import ToolContext, ToolExecutionResult
from tools.executor import build_tool_executor, tool_specs_for_bindings


class _FakeTool:
    name = "dummy"
    description = "тестовая тулза"
    side_effecting = False
    parameters_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.captured_ctx: ToolContext | None = None
        self.captured_arguments: dict[str, Any] | None = None

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        self.captured_ctx = ctx
        self.captured_arguments = arguments
        return ToolExecutionResult(content="ok")


@pytest.fixture
def fake_tool(monkeypatch: pytest.MonkeyPatch) -> _FakeTool:
    tool = _FakeTool()
    monkeypatch.setitem(tools_registry._REGISTRY, "dummy", tool)
    return tool


def test_tool_specs_for_bindings_includes_registered_tool(fake_tool: _FakeTool) -> None:
    bindings = [ToolBinding(tool_name="dummy", config={})]
    specs = tool_specs_for_bindings(bindings)
    assert len(specs) == 1
    assert specs[0].name == "dummy"
    assert specs[0].description == "тестовая тулза"
    assert specs[0].parameters_schema == {"type": "object", "properties": {}}


def test_tool_specs_for_bindings_skips_unknown_tool_and_logs_warning() -> None:
    bindings = [ToolBinding(tool_name="phantom", config={})]
    with capture_logs() as logs:
        specs = tool_specs_for_bindings(bindings)
    assert specs == []
    warnings = [entry for entry in logs if entry["log_level"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["tool_name"] == "phantom"


async def test_build_tool_executor_constructs_context_and_calls_tool(
    fake_tool: _FakeTool,
) -> None:
    bot = object()
    contact_id = uuid.uuid4()
    session_factory = object()
    redis = FakeRedis(decode_responses=True)
    storage = object()
    bindings = [ToolBinding(tool_name="dummy", config={"limit": 3})]

    executor = build_tool_executor(bot, contact_id, session_factory, redis, storage, bindings)
    result = await executor("dummy", {"query": "test"})

    assert result.content == "ok"
    assert fake_tool.captured_arguments == {"query": "test"}
    ctx = fake_tool.captured_ctx
    assert ctx is not None
    assert ctx.bot is bot
    assert ctx.contact_id == contact_id
    assert ctx.session_factory is session_factory
    assert ctx.redis is redis
    assert ctx.storage is storage
    assert ctx.config == {"limit": 3}
    await redis.aclose()


async def test_build_tool_executor_raises_lookup_error_for_unknown_tool() -> None:
    executor = build_tool_executor(object(), uuid.uuid4(), object(), object(), object(), [])
    with pytest.raises(LookupError):
        await executor("phantom", {})
