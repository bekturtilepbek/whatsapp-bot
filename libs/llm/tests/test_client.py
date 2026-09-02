"""complete(): сборка запроса, разбор ответа, проброс таймаута и ошибок SDK.

Реального сетевого вызова к OpenAI нет — client инжектится как duck-typed
фейк той же формы, что openai.AsyncOpenAI (.chat.completions.create).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from llm.client import HistoryMessage, complete


@dataclass
class _FakeMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage | None


class _FakeCompletions:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_call_kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> _FakeResponse:
        self.last_call_kwargs = kwargs
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeChat:
    def __init__(self, completions: _FakeCompletions):
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions):
        self.chat = _FakeChat(completions)


def _client_with_response(text: str, tokens_in: int, tokens_out: int) -> _FakeClient:
    response = _FakeResponse(
        choices=[_FakeChoice(message=_FakeMessage(content=text))],
        usage=_FakeUsage(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )
    return _FakeClient(_FakeCompletions(response=response))


async def test_returns_text_and_token_usage_from_response() -> None:
    client = _client_with_response("Да, доставка есть.", tokens_in=120, tokens_out=8)
    result = await complete("system prompt", [], client=client)  # type: ignore[arg-type]

    assert result.text == "Да, доставка есть."
    assert result.tokens_in == 120
    assert result.tokens_out == 8
    assert result.model  # непустая строка модели


async def test_system_prompt_is_first_message_followed_by_history_in_order() -> None:
    client = _client_with_response("ok", 1, 1)
    history = [
        HistoryMessage(role="user", content="вопрос"),
        HistoryMessage(role="assistant", content="ответ"),
        HistoryMessage(role="user", content="ещё вопрос"),
    ]
    await complete("SYS", history, client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "SYS"}
    assert sent[1:] == [
        {"role": "user", "content": "вопрос"},
        {"role": "assistant", "content": "ответ"},
        {"role": "user", "content": "ещё вопрос"},
    ]


async def test_missing_usage_defaults_tokens_to_zero() -> None:
    response = _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content="ok"))], usage=None)
    client = _FakeClient(_FakeCompletions(response=response))
    result = await complete("SYS", [], client=client)  # type: ignore[arg-type]
    assert result.tokens_in == 0
    assert result.tokens_out == 0


async def test_timeout_seconds_is_passed_through_to_sdk_call() -> None:
    client = _client_with_response("ok", 1, 1)
    await complete("SYS", [], client=client, timeout_seconds=12.5)  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["timeout"] == 12.5


async def test_sdk_errors_propagate_to_the_caller() -> None:
    """Здесь не перехватываем — консюмер (Шаг 5) сам логирует и снимает лок."""
    client = _FakeClient(_FakeCompletions(error=TimeoutError("request timed out")))
    with pytest.raises(TimeoutError):
        await complete("SYS", [], client=client)  # type: ignore[arg-type]
