"""complete(): сборка запроса, разбор ответа, проброс таймаута и ошибок SDK.

Реального сетевого вызова к OpenAI нет — client инжектится как duck-typed
фейк той же формы, что openai.AsyncOpenAI (.chat.completions.create).
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field

import httpx2
import openai
import pytest
from llm.client import (
    DEFAULT_MODEL,
    AssistantToolCallsTurn,
    HistoryMessage,
    ToolCall,
    ToolResultTurn,
    ToolSpec,
    complete,
    complete_with_image,
    complete_with_images,
    complete_with_tools,
    transcribe_audio,
)


@dataclass
class _FakeMessage:
    content: str | None
    tool_calls: list[object] | None = None


@dataclass
class _FakeFunctionCall:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunctionCall


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


class _FlakyCompletions:
    """Возвращает элементы `outcomes` по очереди на каждый вызов `create()` —
    исключение бросается, ответ возвращается. Для тестов ретраев: N сбоев
    подряд, затем успех (или сбоев больше, чем попыток — на исчерпание).
    """

    def __init__(self, outcomes: list[Exception | _FakeResponse]) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def create(self, **kwargs: object) -> _FakeResponse:
        outcome = self._outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class _RecordingSleep:
    calls: list[float] = field(default_factory=list)

    async def __call__(self, delay: float) -> None:
        self.calls.append(delay)


def _fake_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def _rate_limit_error() -> openai.RateLimitError:
    request = _fake_request()
    return openai.RateLimitError(
        "rate limited", response=httpx2.Response(429, request=request), body=None
    )


def _connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=_fake_request())


def _internal_server_error() -> openai.InternalServerError:
    request = _fake_request()
    return openai.InternalServerError(
        "server error", response=httpx2.Response(500, request=request), body=None
    )


def _auth_error() -> openai.AuthenticationError:
    request = _fake_request()
    return openai.AuthenticationError(
        "invalid api key", response=httpx2.Response(401, request=request), body=None
    )


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


async def test_image_message_sent_as_content_array_with_base64_data_url() -> None:
    client = _client_with_response("На фото кроссовки Nike Air.", tokens_in=200, tokens_out=15)
    result = await complete_with_image(
        "SYS", [], "Что это?", b"\xff\xd8\xff", "image/jpeg", client=client
    )  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "SYS"}
    assert sent[-1]["role"] == "user"
    content = sent[-1]["content"]
    assert content[0] == {"type": "text", "text": "Что это?"}
    expected_b64 = base64.b64encode(b"\xff\xd8\xff").decode("ascii")
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{expected_b64}"},
    }
    assert result.text == "На фото кроссовки Nike Air."
    assert result.tokens_in == 200
    assert result.tokens_out == 15


async def test_image_message_prior_history_sent_as_plain_text_before_final_turn() -> None:
    client = _client_with_response("ok", 1, 1)
    history = [
        HistoryMessage(role="user", content="привет"),
        HistoryMessage(role="assistant", content="здравствуйте"),
    ]
    await complete_with_image("SYS", history, "", b"abc", "image/png", client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[1] == {"role": "user", "content": "привет"}
    assert sent[2] == {"role": "assistant", "content": "здравствуйте"}
    assert sent[3]["role"] == "user"
    assert isinstance(sent[3]["content"], list)  # финальный ход — content-массив, не строка


async def test_empty_caption_uses_placeholder_text_block() -> None:
    client = _client_with_response("ok", 1, 1)
    await complete_with_image("SYS", [], "", b"abc", "image/jpeg", client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    text_block = sent[-1]["content"][0]
    assert text_block["type"] == "text"
    assert text_block["text"]  # не пустая строка


async def test_image_call_passes_timeout_through_to_sdk() -> None:
    client = _client_with_response("ok", 1, 1)
    await complete_with_image(
        "SYS", [], "", b"abc", "image/jpeg", client=client, timeout_seconds=12.5
    )  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["timeout"] == 12.5


async def test_multiple_images_sent_as_content_array_with_one_block_each() -> None:
    """FEATURES.md 2.1, батч из нескольких фото — один вызов LLM, все фото
    в порядке прихода после одного text-блока."""
    client = _client_with_response("На фото кроссовки и коробка.", tokens_in=300, tokens_out=20)
    images = [(b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG", "image/png")]
    result = await complete_with_images("SYS", [], "Что на фото?", images, client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    content = sent[-1]["content"]
    assert content[0] == {"type": "text", "text": "Что на фото?"}
    first_b64 = base64.b64encode(images[0][0]).decode("ascii")
    second_b64 = base64.b64encode(images[1][0]).decode("ascii")
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{first_b64}"},
    }
    assert content[2] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{second_b64}"},
    }
    assert len(content) == 3
    assert result.text == "На фото кроссовки и коробка."


async def test_complete_with_image_is_a_thin_wrapper_around_complete_with_images() -> None:
    """Обёртка сохраняет поведение единственного вызывающего с одной
    картинкой (services/api/src/api/routers/sandbox.py, часть B песочницы) —
    не должна была измениться."""
    client = _client_with_response("ok", 1, 1)
    await complete_with_image("SYS", [], "caption", b"abc", "image/jpeg", client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    content = sent[-1]["content"]
    assert len(content) == 2
    assert content[0] == {"type": "text", "text": "caption"}
    assert content[1]["type"] == "image_url"


async def test_retries_on_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    response = _FakeResponse(
        choices=[_FakeChoice(message=_FakeMessage(content="ok"))],
        usage=_FakeUsage(prompt_tokens=1, completion_tokens=1),
    )
    completions = _FlakyCompletions([_rate_limit_error(), _rate_limit_error(), response])
    client = _FakeClient(completions)  # type: ignore[arg-type]

    result = await complete("SYS", [], client=client)  # type: ignore[arg-type]

    assert result.text == "ok"
    assert completions.call_count == 3
    assert sleep.calls == [1.0, 2.0]  # экспоненциальный backoff между 3 попытками


async def test_retries_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _RecordingSleep())
    response = _FakeResponse(
        choices=[_FakeChoice(message=_FakeMessage(content="ok"))],
        usage=_FakeUsage(prompt_tokens=1, completion_tokens=1),
    )
    completions = _FlakyCompletions([_connection_error(), response])
    client = _FakeClient(completions)  # type: ignore[arg-type]

    result = await complete("SYS", [], client=client)  # type: ignore[arg-type]
    assert result.text == "ok"
    assert completions.call_count == 2


async def test_retries_on_internal_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _RecordingSleep())
    response = _FakeResponse(
        choices=[_FakeChoice(message=_FakeMessage(content="ok"))],
        usage=_FakeUsage(prompt_tokens=1, completion_tokens=1),
    )
    completions = _FlakyCompletions([_internal_server_error(), response])
    client = _FakeClient(completions)  # type: ignore[arg-type]

    result = await complete("SYS", [], client=client)  # type: ignore[arg-type]
    assert result.text == "ok"
    assert completions.call_count == 2


async def test_gives_up_after_max_attempts_and_raises_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    completions = _FlakyCompletions(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()]
    )
    client = _FakeClient(completions)  # type: ignore[arg-type]

    with pytest.raises(openai.RateLimitError):
        await complete("SYS", [], client=client)  # type: ignore[arg-type]

    assert completions.call_count == 3  # ровно 3 попытки, не больше
    assert sleep.calls == [1.0, 2.0]  # задержка только между попытками, не после последней


async def test_does_not_retry_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    completions = _FlakyCompletions([_auth_error()])
    client = _FakeClient(completions)  # type: ignore[arg-type]

    with pytest.raises(openai.AuthenticationError):
        await complete("SYS", [], client=client)  # type: ignore[arg-type]

    assert completions.call_count == 1  # ни одного ретрая
    assert sleep.calls == []


async def test_vision_call_also_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """complete_with_image идёт через тот же _call_and_extract — ретраи общие."""
    monkeypatch.setattr(asyncio, "sleep", _RecordingSleep())
    response = _FakeResponse(
        choices=[_FakeChoice(message=_FakeMessage(content="описание фото"))],
        usage=_FakeUsage(prompt_tokens=1, completion_tokens=1),
    )
    completions = _FlakyCompletions([_rate_limit_error(), response])
    client = _FakeClient(completions)  # type: ignore[arg-type]

    result = await complete_with_image(
        "SYS", [], "", b"abc", "image/jpeg", client=client
    )  # type: ignore[arg-type]
    assert result.text == "описание фото"
    assert completions.call_count == 2


async def test_complete_with_tools_sends_function_specs_and_auto_choice() -> None:
    client = _client_with_response("ok", 1, 1)
    spec = ToolSpec(
        name="search",
        description="ищет товар",
        parameters_schema={"type": "object", "properties": {}},
    )
    await complete_with_tools("SYS", [], [spec], client=client)  # type: ignore[arg-type]

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "ищет товар",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert kwargs["tool_choice"] == "auto"


async def test_complete_with_tools_force_text_sets_tool_choice_none() -> None:
    client = _client_with_response("ok", 1, 1)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    await complete_with_tools("SYS", [], [spec], force_text=True, client=client)  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["tool_choice"] == "none"


async def test_complete_with_tools_parses_tool_calls_from_response() -> None:
    response = _FakeResponse(
        choices=[
            _FakeChoice(
                message=_FakeMessage(
                    content=None,
                    tool_calls=[
                        _FakeToolCall(
                            id="call_1",
                            function=_FakeFunctionCall(
                                name="search", arguments='{"q": "кроссовки"}'
                            ),
                        )
                    ],
                )
            )
        ],
        usage=_FakeUsage(prompt_tokens=10, completion_tokens=5),
    )
    client = _FakeClient(_FakeCompletions(response=response))
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    result = await complete_with_tools("SYS", [], [spec], client=client)  # type: ignore[arg-type]

    assert result.text == ""
    assert result.tool_calls == [
        ToolCall(id="call_1", name="search", arguments_json='{"q": "кроссовки"}')
    ]


async def test_complete_with_tools_no_tool_calls_returns_plain_text() -> None:
    client = _client_with_response("обычный ответ", 5, 5)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    result = await complete_with_tools("SYS", [], [spec], client=client)  # type: ignore[arg-type]
    assert result.text == "обычный ответ"
    assert result.tool_calls is None


async def test_complete_with_tools_exchange_becomes_assistant_and_tool_messages() -> None:
    client = _client_with_response("финальный ответ", 1, 1)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    exchange = [
        AssistantToolCallsTurn([ToolCall(id="call_1", name="search", arguments_json='{"q": "x"}')]),
        ToolResultTurn(tool_call_id="call_1", name="search", content="ничего не найдено"),
    ]
    await complete_with_tools("SYS", [], [spec], exchange, client=client)  # type: ignore[arg-type]

    sent = client.chat.completions.last_call_kwargs["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q": "x"}'},
            }
        ],
    }
    assert sent[2] == {"role": "tool", "tool_call_id": "call_1", "content": "ничего не найдено"}


async def test_complete_without_tools_does_not_send_tools_key() -> None:
    """Регрессия: у ботов без единой включённой тулзы (все сейчас) форма
    запроса к OpenAI не должна меняться вообще."""
    client = _client_with_response("ok", 1, 1)
    await complete("SYS", [], client=client)  # type: ignore[arg-type]
    assert "tools" not in client.chat.completions.last_call_kwargs
    assert "tool_choice" not in client.chat.completions.last_call_kwargs


async def test_complete_uses_explicit_model_override_when_given() -> None:
    """Волна 4 — выбор модели per bot (bots.settings["model"])."""
    client = _client_with_response("ok", 1, 1)
    result = await complete("SYS", [], model="gpt-4o", client=client)  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["model"] == "gpt-4o"
    assert result.model == "gpt-4o"


async def test_complete_falls_back_to_platform_default_when_model_not_given() -> None:
    """Регрессия: боты без настроенной модели (все сейчас) не меняют поведение."""
    client = _client_with_response("ok", 1, 1)
    await complete("SYS", [], client=client)  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["model"] == DEFAULT_MODEL


async def test_complete_with_images_uses_explicit_model_override_when_given() -> None:
    client = _client_with_response("ok", 1, 1)
    await complete_with_images(
        "SYS", [], "caption", [(b"abc", "image/jpeg")], model="gpt-4o", client=client
    )  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["model"] == "gpt-4o"


async def test_complete_with_tools_uses_explicit_model_override_when_given() -> None:
    client = _client_with_response("ok", 1, 1)
    spec = ToolSpec(name="search", description="d", parameters_schema={})
    await complete_with_tools("SYS", [], [spec], model="gpt-4o", client=client)  # type: ignore[arg-type]
    assert client.chat.completions.last_call_kwargs["model"] == "gpt-4o"


@dataclass
class _FakeTranscription:
    text: str


class _FakeAudioTranscriptions:
    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.last_call_kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> _FakeTranscription:
        self.last_call_kwargs = kwargs
        if self.error is not None:
            raise self.error
        assert self.text is not None
        return _FakeTranscription(text=self.text)


class _FakeAudio:
    def __init__(self, transcriptions: _FakeAudioTranscriptions) -> None:
        self.transcriptions = transcriptions


class _FakeAudioClient:
    def __init__(self, transcriptions: _FakeAudioTranscriptions) -> None:
        self.audio = _FakeAudio(transcriptions)


async def test_transcribe_audio_returns_the_transcribed_text() -> None:
    transcriptions = _FakeAudioTranscriptions(text="Здравствуйте, есть доставка?")
    client = _FakeAudioClient(transcriptions)
    result = await transcribe_audio(b"raw audio bytes", "voice.mp3", client=client)  # type: ignore[arg-type]
    assert result == "Здравствуйте, есть доставка?"


async def test_transcribe_audio_sends_whisper_model_and_filename() -> None:
    transcriptions = _FakeAudioTranscriptions(text="ok")
    client = _FakeAudioClient(transcriptions)
    await transcribe_audio(b"raw audio bytes", "voice.mp3", client=client)  # type: ignore[arg-type]
    kwargs = transcriptions.last_call_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "whisper-1"
    assert kwargs["file"] == ("voice.mp3", b"raw audio bytes")


async def test_transcribe_audio_passes_timeout_through_to_sdk() -> None:
    transcriptions = _FakeAudioTranscriptions(text="ok")
    client = _FakeAudioClient(transcriptions)
    await transcribe_audio(
        b"raw audio bytes", "voice.mp3", client=client, timeout_seconds=12.5
    )  # type: ignore[arg-type]
    assert transcriptions.last_call_kwargs["timeout"] == 12.5


async def test_transcribe_audio_propagates_sdk_errors_without_retrying() -> None:
    """В отличие от complete() — STT-ретраи не делаем в этой итерации
    (подтверждено пользователем), сбой уходит наружу как есть."""
    transcriptions = _FakeAudioTranscriptions(error=TimeoutError("stt timed out"))
    client = _FakeAudioClient(transcriptions)
    with pytest.raises(TimeoutError):
        await transcribe_audio(b"raw audio bytes", "voice.mp3", client=client)  # type: ignore[arg-type]
