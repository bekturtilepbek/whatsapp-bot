"""Клиент LLM. Провайдер сейчас — OpenAI, единая модель на платформу через
OPENAI_MODEL (ADR, подтверждено пользователем: gpt-4o-mini дефолт). Интерфейс
узкий (system + история -> текст + usage), чтобы смена провайдера
(пользователь предупредил — возможны Gemini/Deepseek в будущем) была
локальной правкой внутри этого пакета, а не по всему worker'у.
"""

from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from openai import (
    APIConnectionError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

DEFAULT_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT_SECONDS = 60.0

# Ретраи — только временные сбои (Волна 1, отложено ещё в Блоке 2:
# "ретраи — Волна 1 (STAGE1_CORE)"). APIConnectionError включает
# APITimeoutError (подкласс) — таймаут одного запроса тоже ретраится.
# Постоянные ошибки (авторизация, некорректный запрос и т.п.) НЕ ретраим —
# лишняя задержка ответа клиенту без единого шанса на успех.
_RETRYABLE_EXCEPTIONS = (APIConnectionError, RateLimitError, InternalServerError)
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0


@dataclass(frozen=True)
class HistoryMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str  # сырой JSON от OpenAI — разбор на стороне вызывающего


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters_schema: dict[str, Any]


@dataclass(frozen=True)
class AssistantToolCallsTurn:
    tool_calls: list[ToolCall]


@dataclass(frozen=True)
class ToolResultTurn:
    tool_call_id: str
    name: str
    content: str


ToolExchangeTurn = AssistantToolCallsTurn | ToolResultTurn


@dataclass(frozen=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    tool_calls: list[ToolCall] | None = None


def current_model() -> str:
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)


_client: AsyncOpenAI | None = None


def _default_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _client


async def _call_and_extract(
    active_client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, object]],
    timeout_seconds: float,
    *,
    tools: list[dict[str, object]] | None = None,
    tool_choice: str | None = None,
) -> LLMResult:
    """Ретрай — только на временные сбои SDK (см. _RETRYABLE_EXCEPTIONS),
    экспоненциальный backoff (1с, 2с) между попытками. Таймаут на каждую
    попытку — тот же timeout_seconds, не суммируется отдельно.

    tools/tool_choice — опциональны: complete()/complete_with_image() их не
    передают, форма запроса для них не меняется (регрессия — см.
    test_complete_without_tools_does_not_send_tools_key).
    """
    response = None
    kwargs: dict[str, object] = {"model": model, "messages": messages, "timeout": timeout_seconds}
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            # kwargs — dict[str, object], mypy теряет типизацию по отдельным полям
            # и не может подобрать нужную перегрузку create()
            response = await active_client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            break
        except _RETRYABLE_EXCEPTIONS:
            if attempt == RETRY_MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
    # цикл либо break (успех), либо raise на последней попытке — эта ветка недостижима
    assert response is not None  # pragma: no cover

    choice = response.choices[0]
    text = choice.message.content or ""
    raw_tool_calls = getattr(choice.message, "tool_calls", None)
    tool_calls: list[ToolCall] | None = None
    if raw_tool_calls:
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments_json=tc.function.arguments or "")
            for tc in raw_tool_calls
        ]

    usage = response.usage
    tokens_in = usage.prompt_tokens if usage else 0
    tokens_out = usage.completion_tokens if usage else 0
    return LLMResult(
        text=text, tokens_in=tokens_in, tokens_out=tokens_out, model=model, tool_calls=tool_calls
    )


async def complete(
    system_prompt: str,
    history: list[HistoryMessage],
    *,
    model: str | None = None,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """Любой внешний вызов — с таймаутом (CLAUDE.md). Таймаут — нативный
    httpx-таймаут SDK, не обёртка снаружи: так отменяется сам HTTP-запрос,
    а не только ожидание его результата.

    model — переопределение per bot (bots.settings["model"], Волна 4);
    None (боты без настроенной модели — все на момент введения этого
    параметра) сохраняет старое поведение — платформенный OPENAI_MODEL.
    """
    model = model or current_model()
    messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    active_client = client or _default_client()
    return await _call_and_extract(active_client, model, messages, timeout_seconds)


_EMPTY_CAPTION_PLACEHOLDER = "Опиши, что на фото, и ответь клиенту по инструкции."


async def complete_with_image(
    system_prompt: str,
    history: list[HistoryMessage],
    caption: str,
    image_bytes: bytes,
    image_mime_type: str,
    *,
    model: str | None = None,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """Обёртка над `complete_with_images` для единственного фото — сигнатура
    сохранена ради `services/api/src/api/routers/sandbox.py` (часть B
    песочницы: там всегда ровно одно загруженное фото, батчинга нет)."""
    return await complete_with_images(
        system_prompt,
        history,
        caption,
        [(image_bytes, image_mime_type)],
        model=model,
        client=client,
        timeout_seconds=timeout_seconds,
    )


async def complete_with_images(
    system_prompt: str,
    history: list[HistoryMessage],
    caption: str,
    images: Sequence[tuple[bytes, str]],
    *,
    model: str | None = None,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """FEATURES.md 2.1: один вызов LLM на сообщение с фото (одним или
    несколькими — если клиент прислал их пачкой, FEATURES.md 1.3/2.1
    ревизия) — image_prompt бота используется КАК system prompt, ответ
    модели уходит клиенту напрямую (без второго прохода "описание -> ещё
    один LLM-вызов").

    history — ТОЛЬКО предыдущие ходы, без текущего: текущий ход собирается
    здесь явно из caption + картинок (текущие строки истории в БД — это
    плейсхолдеры вроде "[фото]", отправлять их в LLM как текст бессмысленно
    и вводит модель в заблуждение).

    base64 data URL, а не Files API/публичный URL — картинки уже лежат у нас
    байтами (Storage.get), а не в общедоступном месте: data URL не требует
    отдельного аплоада и не "утекает" наружу.

    model — переопределение per bot (bots.settings["model"], Волна 4), см.
    complete().
    """
    model = model or current_model()
    content: list[dict[str, object]] = [
        {"type": "text", "text": caption or _EMPTY_CAPTION_PLACEHOLDER}
    ]
    for image_bytes, image_mime_type in images:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image_mime_type};base64,{b64}"},
            }
        )
    messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": content})
    active_client = client or _default_client()
    return await _call_and_extract(active_client, model, messages, timeout_seconds)


def _tool_specs_to_openai(tools: list[ToolSpec]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
            },
        }
        for t in tools
    ]


def _exchange_to_messages(exchange: Sequence[ToolExchangeTurn]) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for turn in exchange:
        if isinstance(turn, AssistantToolCallsTurn):
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {"name": call.name, "arguments": call.arguments_json},
                        }
                        for call in turn.tool_calls
                    ],
                }
            )
        else:
            messages.append(
                {"role": "tool", "tool_call_id": turn.tool_call_id, "content": turn.content}
            )
    return messages


async def complete_with_tools(
    system_prompt: str,
    history: list[HistoryMessage],
    tools: list[ToolSpec],
    exchange: Sequence[ToolExchangeTurn] = (),
    *,
    force_text: bool = False,
    model: str | None = None,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> LLMResult:
    """Один вызов LLM с доступными тулзами (FEATURES.md 4.13, инфраструктура).
    Цикл по нескольким раундам — НЕ здесь, а в libs/tools/src/tools/tool_loop.py
    (используется и worker'ом, и api-песочницей, FEATURES.md 9.6 часть A;
    этот пакет — только механика одного вызова OpenAI).

    exchange — уже случившиеся в ТЕКУЩЕМ раунде реплики (assistant с
    tool_calls + результаты тулз), эфемерны в рамках одного вызова
    run_tool_loop — не путать с history (постоянная история из БД).

    force_text=True форсирует tool_choice="none" — модель обязана ответить
    текстом по уже собранным в exchange результатам, а не запросить ещё
    одну тулзу (используется, когда исчерпан лимит раундов цикла).

    model — переопределение per bot (bots.settings["model"], Волна 4), см.
    complete().
    """
    model = model or current_model()
    messages: list[dict[str, object]] = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages += _exchange_to_messages(exchange)
    active_client = client or _default_client()
    return await _call_and_extract(
        active_client,
        model,
        messages,
        timeout_seconds,
        tools=_tool_specs_to_openai(tools),
        tool_choice="none" if force_text else "auto",
    )


TRANSCRIPTION_MODEL = "whisper-1"


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    *,
    client: AsyncOpenAI | None = None,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """FEATURES.md 2.2: голосовое -> текст (worker перед вызовом уже
    перекодировал байты в формат, который принимает Whisper — эта функция
    просто шлёт готовые байты). Без ретраев (в отличие от _call_and_extract)
    — подтверждено пользователем, сбой STT уходит наружу как есть, вызывающий
    (worker) решает деградировать в fallback."""
    active_client = client or _default_client()
    response = await active_client.audio.transcriptions.create(
        model=TRANSCRIPTION_MODEL,
        file=(filename, audio_bytes),
        timeout=timeout_seconds,
    )
    return response.text
