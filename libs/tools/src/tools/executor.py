"""Сборка ToolSpec-списка и ToolExecutor из tool_bindings бота (FEATURES.md
4.13). Раньше жило приватным кодом в services/worker/src/worker/pipeline/
consumer.py (_tool_specs_for_bindings/_make_tool_executor, включая тип
ToolExecutor) — вынесено сюда, т.к. песочница (FEATURES.md 9.6, api)
собирает executor тем же способом, не проходя через worker/Redis-шину
(тулзы — обычные Python-функции, ADR-002 запрещает публиковать события
САМИМ тулзам, но не запрещает импортировать их из другого сервиса).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from db.models import Bot, ToolBinding
from integrations.storage import Storage
from llm.client import ToolSpec
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .base import ToolContext, ToolExecutionResult
from .registry import get_tool

logger = structlog.get_logger("tools.executor")

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[ToolExecutionResult]]


def tool_specs_for_bindings(bindings: list[ToolBinding]) -> list[ToolSpec]:
    """Тулзы, включённые боту (tool_bindings), но отсутствующие в реестре
    libs/tools — молча пропускаются: рассинхрон между БД и деплоем кода не
    должен ронять диалог."""
    specs: list[ToolSpec] = []
    for binding in bindings:
        tool = get_tool(binding.tool_name)
        if tool is None:
            logger.warning(
                "tool binding references unknown tool, skipping",
                tool_name=binding.tool_name,
            )
            continue
        specs.append(
            ToolSpec(
                name=tool.name,
                description=tool.description,
                parameters_schema=tool.parameters_schema,
            )
        )
    return specs


def build_tool_executor(
    bot: Bot,
    contact_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    storage: Storage,
    bindings: list[ToolBinding],
) -> ToolExecutor:
    config_by_name = {binding.tool_name: binding.config for binding in bindings}

    async def executor(name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        tool = get_tool(name)
        if tool is None:
            raise LookupError(f"tool not in registry: {name}")
        ctx = ToolContext(
            bot=bot,
            contact_id=contact_id,
            session_factory=session_factory,
            redis=redis,
            storage=storage,
            config=config_by_name.get(name, {}),
        )
        return await tool.execute(arguments, ctx)

    return executor
