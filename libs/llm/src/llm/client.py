"""Клиент LLM. Провайдер сейчас — OpenAI, единая модель на платформу через
OPENAI_MODEL (ADR, подтверждено пользователем: gpt-4o-mini дефолт). Интерфейс
узкий (system + история -> текст + usage), чтобы смена провайдера
(пользователь предупредил — возможны Gemini/Deepseek в будущем) была
локальной правкой внутри этого пакета, а не по всему worker'у.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import AsyncOpenAI

DEFAULT_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class HistoryMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str


def current_model() -> str:
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)


_client: AsyncOpenAI | None = None


def _default_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


async def complete(
    system_prompt: str,
    history: list[HistoryMessage],
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """Любой внешний вызов — с таймаутом (CLAUDE.md). Таймаут — нативный
    httpx-таймаут SDK, не обёртка снаружи: так отменяется сам HTTP-запрос,
    а не только ожидание его результата.
    """
    model = current_model()
    messages = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in history
    ]
    active_client = client or _default_client()

    response = await active_client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]  # role/content уже валидные строки
        timeout=timeout_seconds,
    )

    choice = response.choices[0]
    text = choice.message.content or ""
    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    return LLMResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out, model=model)
