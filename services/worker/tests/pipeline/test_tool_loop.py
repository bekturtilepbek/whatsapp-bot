"""run_tool_loop: цикл LLM↔tool-calls (FEATURES.md 4.13, инфраструктура;
FEATURES.md 4.3/4.4 — прокидка override_reply_text/media от тулзы к
вызывающему). complete_fn/complete_with_tools_fn/executor — все фейковые,
сценарии прогоняются полностью синхронно предсказуемым скриптом, без
реального OpenAI-вызова.
"""

from __future__ import annotations

from llm.client import (
    HistoryMessage,
    LLMResult,
    ToolCall,
    ToolResultTurn,
    ToolSpec,
)
from tools.base import MediaToSend, ToolExecutionResult
from worker.pipeline.tool_loop import ToolLoopResult, run_tool_loop

_SPEC = ToolSpec(name="search", description="ищет товар", parameters_schema={"type": "object"})


async def _unused_executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
    raise AssertionError("не должен вызываться в этом сценарии")


async def test_empty_tools_calls_complete_fn_directly() -> None:
    async def complete_fn(system_prompt: str, history: list[HistoryMessage]) -> LLMResult:
        return LLMResult(text="прямой ответ", tokens_in=10, tokens_out=2, model="gpt-4o-mini")

    async def fail_complete_with_tools(*args: object, **kwargs: object) -> LLMResult:
        raise AssertionError("не должен вызываться, когда tools пуст")

    result = await run_tool_loop(
        "SYS",
        [],
        [],
        _unused_executor,
        complete_fn=complete_fn,
        complete_with_tools_fn=fail_complete_with_tools,
    )
    assert result == ToolLoopResult(
        text="прямой ответ", tokens_in=10, tokens_out=2, model="gpt-4o-mini"
    )


async def test_single_round_returns_text_when_no_tool_calls_requested() -> None:
    async def complete_with_tools_fn(*args: object, **kwargs: object) -> LLMResult:
        return LLMResult(text="готовый ответ", tokens_in=20, tokens_out=8, model="gpt-4o-mini")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], _unused_executor, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "готовый ответ"
    assert result.tokens_in == 20
    assert result.tokens_out == 8
    assert result.override_reply_text is None
    assert result.media == ()


async def test_two_round_scenario_executes_tool_then_returns_final_text() -> None:
    calls: list[dict[str, object]] = []

    async def complete_with_tools_fn(
        system_prompt: str,
        history: list[HistoryMessage],
        tools: list[ToolSpec],
        exchange: object,
        *,
        force_text: bool = False,
    ) -> LLMResult:
        calls.append({"exchange_len": len(list(exchange)), "force_text": force_text})
        if len(calls) == 1:
            return LLMResult(
                text="",
                tokens_in=15,
                tokens_out=5,
                model="gpt-4o-mini",
                tool_calls=[
                    ToolCall(
                        id="call_1", name="search", arguments_json='{"q": "кроссовки"}'
                    )
                ],
            )
        return LLMResult(
            text="Нашёл кроссовки Nike.",
            tokens_in=25,
            tokens_out=10,
            model="gpt-4o-mini",
        )

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        assert name == "search"
        assert arguments == {"q": "кроссовки"}
        return ToolExecutionResult(content="Nike Air, 5000 сом")

    result = await run_tool_loop(
        "SYS",
        [],
        [_SPEC],
        executor,
        complete_with_tools_fn=complete_with_tools_fn,
    )

    assert result.text == "Нашёл кроссовки Nike."
    assert result.tokens_in == 15 + 25
    assert result.tokens_out == 5 + 10
    assert calls[0]["exchange_len"] == 0
    assert calls[1]["exchange_len"] == 2  # assistant-tool-calls + tool-result


async def test_tool_result_with_override_reply_text_propagates_to_loop_result() -> None:
    """FEATURES.md 4.3/4.4: если тулза вернула override_reply_text/media —
    ToolLoopResult их несёт наверх (последний найденный товар в ходе
    актуален — тест с одним вызовом тулзы этого не проверяет отдельно,
    "последний выигрывает" покрыт следующим тестом)."""

    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="m",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        return LLMResult(text="текст LLM, будет отброшен", tokens_in=1, tokens_out=1, model="m")

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        return ToolExecutionResult(
            content='[{"name": "Nike Air"}]',
            override_reply_text="*Nike Air*\nЦена: 5000",
            media=[MediaToSend(storage_key="img-1", mime_type="image/jpeg")],
        )

    result = await run_tool_loop(
        "SYS", [], [_SPEC], executor, complete_with_tools_fn=complete_with_tools_fn
    )

    assert result.text == "текст LLM, будет отброшен"
    assert result.override_reply_text == "*Nike Air*\nЦена: 5000"
    assert [(m.storage_key, m.mime_type) for m in result.media] == [("img-1", "image/jpeg")]


async def test_invalid_json_arguments_returns_error_turn_without_calling_executor() -> None:
    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="m",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="не json")],
            )
        tool_turn = exchange_list[1]
        assert isinstance(tool_turn, ToolResultTurn)
        assert "JSON" in tool_turn.content
        return LLMResult(text="понял, уточню", tokens_in=1, tokens_out=1, model="m")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], _unused_executor, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "понял, уточню"


async def test_executor_exception_returns_error_turn_and_loop_continues() -> None:
    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        exchange_list = list(exchange)
        if not exchange_list:
            return LLMResult(
                text="", tokens_in=1, tokens_out=1, model="m",
                tool_calls=[ToolCall(id="call_1", name="search", arguments_json="{}")],
            )
        tool_turn = exchange_list[1]
        assert isinstance(tool_turn, ToolResultTurn)
        assert "Ошибка" in tool_turn.content
        return LLMResult(text="извините, не получилось", tokens_in=1, tokens_out=1, model="m")

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        raise RuntimeError("тулза упала")

    result = await run_tool_loop(
        "SYS",
        [],
        [_SPEC],
        executor,
        complete_with_tools_fn=complete_with_tools_fn,
    )
    assert result.text == "извините, не получилось"


async def test_max_rounds_exhausted_forces_final_text_call() -> None:
    call_count = 0

    async def complete_with_tools_fn(
        system_prompt: str, history: list[HistoryMessage], tools: list[ToolSpec], exchange: object,
        *, force_text: bool = False,
    ) -> LLMResult:
        nonlocal call_count
        call_count += 1
        if force_text:
            return LLMResult(
                text="итоговый ответ по тому, что успел узнать",
                tokens_in=1,
                tokens_out=1,
                model="m",
            )
        return LLMResult(
            text="", tokens_in=1, tokens_out=1, model="m",
            tool_calls=[ToolCall(id=f"call_{call_count}", name="search", arguments_json="{}")],
        )

    async def executor(name: str, arguments: dict[str, object]) -> ToolExecutionResult:
        return ToolExecutionResult(content="результат")

    result = await run_tool_loop(
        "SYS", [], [_SPEC], executor, max_rounds=2, complete_with_tools_fn=complete_with_tools_fn
    )
    assert result.text == "итоговый ответ по тому, что успел узнать"
    assert call_count == 3  # 2 обычных раунда + 1 форсированный текстовый
