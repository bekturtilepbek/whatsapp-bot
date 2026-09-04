"""Цикл LLM↔tool-calls (FEATURES.md 4.13, инфраструктура). Оркестрация —
здесь (ADR-002: worker = бизнес-логика); механика одного вызова OpenAI —
libs/llm. См. docs/superpowers/specs/2026-09-05-tool-calling-infra-design.md

При пустом списке тулз — один вызов complete_fn(), форма запроса и
поведение идентичны тому, что было до этой фичи: это гарантирует, что
подключение цикла в _reply() (Task 5) при пустом реестре тулз у всех
ботов сейчас — ноль изменений в живом поведении.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from llm.client import (
    AssistantToolCallsTurn,
    HistoryMessage,
    LLMResult,
    ToolCall,
    ToolExchangeTurn,
    ToolResultTurn,
    ToolSpec,
)
from llm.client import complete as _default_complete
from llm.client import complete_with_tools as _default_complete_with_tools

logger = structlog.get_logger("worker.pipeline.tool_loop")

MAX_TOOL_ROUNDS = 5
TOOL_CALL_TIMEOUT_SECONDS = 20.0

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]
_CompleteFn = Callable[[str, list[HistoryMessage]], Awaitable[LLMResult]]
_CompleteWithToolsFn = Callable[..., Awaitable[LLMResult]]


@dataclass(frozen=True)
class ToolLoopResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


async def run_tool_loop(
    system_prompt: str,
    history: list[HistoryMessage],
    tools: list[ToolSpec],
    executor: ToolExecutor,
    *,
    max_rounds: int = MAX_TOOL_ROUNDS,
    complete_fn: _CompleteFn = _default_complete,
    complete_with_tools_fn: _CompleteWithToolsFn = _default_complete_with_tools,
) -> ToolLoopResult:
    if not tools:
        result = await complete_fn(system_prompt, history)
        return ToolLoopResult(
            text=result.text,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            model=result.model,
        )

    exchange: list[ToolExchangeTurn] = []
    tokens_in_total = 0
    tokens_out_total = 0
    model_name = ""

    for _ in range(max_rounds):
        result = await complete_with_tools_fn(system_prompt, history, tools, exchange)
        tokens_in_total += result.tokens_in
        tokens_out_total += result.tokens_out
        model_name = result.model

        if not result.tool_calls:
            return ToolLoopResult(
                text=result.text,
                tokens_in=tokens_in_total,
                tokens_out=tokens_out_total,
                model=model_name,
            )

        exchange.append(AssistantToolCallsTurn(result.tool_calls))
        for call in result.tool_calls:
            output = await _run_one_tool(call, executor)
            exchange.append(ToolResultTurn(call.id, call.name, output))

    logger.warning("tool loop reached max_rounds, forcing final text answer", max_rounds=max_rounds)
    result = await complete_with_tools_fn(system_prompt, history, tools, exchange, force_text=True)
    tokens_in_total += result.tokens_in
    tokens_out_total += result.tokens_out
    return ToolLoopResult(
        text=result.text, tokens_in=tokens_in_total, tokens_out=tokens_out_total, model=result.model
    )


async def _run_one_tool(call: ToolCall, executor: ToolExecutor) -> str:
    try:
        arguments: dict[str, Any] = json.loads(call.arguments_json) if call.arguments_json else {}
    except json.JSONDecodeError:
        logger.warning("tool call arguments are not valid json", tool_name=call.name)
        return "Ошибка: не удалось разобрать аргументы как JSON. Повтори вызов с корректным JSON."

    try:
        return await asyncio.wait_for(
            executor(call.name, arguments), timeout=TOOL_CALL_TIMEOUT_SECONDS
        )
    except Exception:
        logger.warning("tool execution failed", tool_name=call.name, exc_info=True)
        return "Ошибка при вызове инструмента. Продолжай без этого результата или попробуй иначе."
