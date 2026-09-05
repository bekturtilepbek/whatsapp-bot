"""Генерация эмбеддинга товара (FEATURES.md 4.1). Реального сетевого
вызова нет — client инжектится как duck-typed фейк формы
openai.AsyncOpenAI (.embeddings.create), тот же приём, что test_client.py
для .chat.completions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx2
import openai
import pytest
from llm.embeddings import generate_embedding, product_embedding_input


@dataclass
class _FakeEmbeddingData:
    embedding: list[float]


@dataclass
class _FakeEmbeddingResponse:
    data: list[_FakeEmbeddingData]


class _FakeEmbeddingsEndpoint:
    def __init__(
        self, response: _FakeEmbeddingResponse | None = None, error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.last_call_kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> _FakeEmbeddingResponse:
        self.last_call_kwargs = kwargs
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeClient:
    def __init__(self, embeddings: _FakeEmbeddingsEndpoint) -> None:
        self.embeddings = embeddings


def _client_with_vector(vector: list[float]) -> _FakeClient:
    response = _FakeEmbeddingResponse(data=[_FakeEmbeddingData(embedding=vector)])
    return _FakeClient(_FakeEmbeddingsEndpoint(response=response))


class _FlakyEmbeddingsEndpoint:
    """Возвращает элементы `outcomes` по очереди на каждый вызов `create()` —
    исключение бросается, ответ возвращается (тот же приём, что
    _FlakyCompletions в test_client.py)."""

    def __init__(self, outcomes: list[Exception | _FakeEmbeddingResponse]) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def create(self, **kwargs: object) -> _FakeEmbeddingResponse:
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
    return httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


def _rate_limit_error() -> openai.RateLimitError:
    request = _fake_request()
    return openai.RateLimitError(
        "rate limited", response=httpx2.Response(429, request=request), body=None
    )


def _auth_error() -> openai.AuthenticationError:
    request = _fake_request()
    return openai.AuthenticationError(
        "invalid api key", response=httpx2.Response(401, request=request), body=None
    )


def test_product_embedding_input_combines_name_and_description() -> None:
    result = product_embedding_input("Кроссовки Nike Air", "Беговые")
    assert result == "Name: Кроссовки Nike Air; Description: Беговые"


def test_product_embedding_input_handles_missing_description() -> None:
    result = product_embedding_input("Товар без описания", None)
    assert result == "Name: Товар без описания; Description: "


async def test_generate_embedding_returns_the_vector() -> None:
    client = _client_with_vector([0.1, 0.2, 0.3])
    result = await generate_embedding("Name: X; Description: Y", client=client)  # type: ignore[arg-type]
    assert result == [0.1, 0.2, 0.3]


async def test_generate_embedding_sends_the_configured_model_and_input_text() -> None:
    client = _client_with_vector([0.1])
    await generate_embedding("some text", client=client)  # type: ignore[arg-type]
    assert client.embeddings.last_call_kwargs["model"] == "text-embedding-3-small"
    assert client.embeddings.last_call_kwargs["input"] == "some text"


async def test_generate_embedding_passes_timeout_through_to_sdk() -> None:
    client = _client_with_vector([0.1])
    await generate_embedding("text", client=client, timeout_seconds=12.5)  # type: ignore[arg-type]
    assert client.embeddings.last_call_kwargs["timeout"] == 12.5


async def test_retries_on_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)

    response = _FakeEmbeddingResponse(data=[_FakeEmbeddingData(embedding=[0.5])])
    endpoint = _FlakyEmbeddingsEndpoint([_rate_limit_error(), _rate_limit_error(), response])
    client = _FakeClient(endpoint)  # type: ignore[arg-type]

    result = await generate_embedding("text", client=client)  # type: ignore[arg-type]

    assert result == [0.5]
    assert endpoint.call_count == 3
    assert sleep.calls == [1.0, 2.0]


async def test_gives_up_after_max_attempts_and_raises_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _RecordingSleep())
    endpoint = _FlakyEmbeddingsEndpoint(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()]
    )
    client = _FakeClient(endpoint)  # type: ignore[arg-type]

    with pytest.raises(openai.RateLimitError):
        await generate_embedding("text", client=client)  # type: ignore[arg-type]

    assert endpoint.call_count == 3


async def test_does_not_retry_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = _RecordingSleep()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    endpoint = _FlakyEmbeddingsEndpoint([_auth_error()])
    client = _FakeClient(endpoint)  # type: ignore[arg-type]

    with pytest.raises(openai.AuthenticationError):
        await generate_embedding("text", client=client)  # type: ignore[arg-type]

    assert endpoint.call_count == 1
    assert sleep.calls == []
