"""Саммари диалога и температура клиента (FEATURES.md 6.13).

Реального вызова OpenAI нет — client инжектится как duck-typed фейк.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from llm.summary import (
    MAX_MESSAGE_CHARS,
    SUMMARY_MODEL_DEFAULT,
    SummaryMessage,
    analyze_conversation,
    build_transcript,
    parse_analysis,
    summary_model,
)


def test_parse_valid_json_with_english_codes() -> None:
    result = parse_analysis('{"summary": "Клиент выбирает шкаф.", "temperature": "hot"}')
    assert result is not None
    assert result.summary == "Клиент выбирает шкаф."
    assert result.temperature == "hot"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("горячий", "hot"),
        ("тёплый", "warm"),
        ("теплый", "warm"),  # так писал V1 — без "ё"
        ("холодный", "cold"),
        ("HOT", "hot"),
        (" Warm ", "warm"),
    ],
)
def test_parse_accepts_v1_russian_values_and_normalizes_case(raw: str, expected: str) -> None:
    result = parse_analysis(f'{{"summary": "ок", "temperature": "{raw}"}}')
    assert result is not None
    assert result.temperature == expected


def test_parse_extracts_json_surrounded_by_extra_text() -> None:
    raw = 'Вот ответ:\n```json\n{"summary": "Коротко.", "temperature": "cold"}\n```\nГотово.'
    result = parse_analysis(raw)
    assert result is not None
    assert result.temperature == "cold"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "просто текст без json",
        '{"summary": "x"}',  # нет температуры
        '{"temperature": "hot"}',  # нет саммари
        '{"summary": "x", "temperature": "очень горячий"}',  # неизвестное значение
        '{"summary": "   ", "temperature": "hot"}',  # пустое саммари
        '{"summary": 5, "temperature": "hot"}',  # не строка
        "{битый json",
    ],
)
def test_parse_returns_none_on_unusable_response(raw: str) -> None:
    # В отличие от V1 (молча "холодный") — None, чтобы вызывающий не затирал
    # прежнюю оценку мусором.
    assert parse_analysis(raw) is None


def test_transcript_labels_roles_and_marks_manager() -> None:
    transcript = build_transcript(
        [
            SummaryMessage(role="user", content="Сколько стоит шкаф?"),
            SummaryMessage(role="assistant", content="От 12 000 сом."),
            SummaryMessage(role="assistant", content="[Ответ менеджера] Могу привезти завтра."),
        ]
    )
    assert transcript.splitlines() == [
        "Клиент: Сколько стоит шкаф?",
        "Бот: От 12 000 сом.",
        "Менеджер: Могу привезти завтра.",
    ]


def test_transcript_truncates_long_messages() -> None:
    transcript = build_transcript([SummaryMessage(role="user", content="а" * 5000)])
    assert len(transcript) <= len("Клиент: ") + MAX_MESSAGE_CHARS + 1


def test_summary_model_defaults_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUMMARY_MODEL", raising=False)
    assert summary_model() == SUMMARY_MODEL_DEFAULT
    monkeypatch.setenv("SUMMARY_MODEL", "gpt-4o-mini")
    assert summary_model() == "gpt-4o-mini"


@dataclass
class _Msg:
    content: str | None


@dataclass
class _Choice:
    message: _Msg


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage


class _Completions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.kwargs: dict[str, object] | None = None

    async def create(self, **kwargs: object) -> _Response:
        self.kwargs = kwargs
        return _Response([_Choice(_Msg(self.text))], _Usage(1200, 120))


class _Chat:
    def __init__(self, completions: _Completions) -> None:
        self.completions = completions


class _Client:
    def __init__(self, text: str) -> None:
        self.chat = _Chat(_Completions(text))


async def test_analyze_conversation_returns_parsed_result_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUMMARY_MODEL", raising=False)
    client = _Client('{"summary": "Клиент готов купить.", "temperature": "hot"}')

    outcome = await analyze_conversation(
        [SummaryMessage(role="user", content="Беру, куда оплатить?")],
        client=client,  # type: ignore[arg-type]
    )

    assert outcome.analysis is not None
    assert outcome.analysis.temperature == "hot"
    assert (outcome.tokens_in, outcome.tokens_out) == (1200, 120)
    assert outcome.model == SUMMARY_MODEL_DEFAULT
    sent = client.chat.completions.kwargs
    assert sent is not None and sent["model"] == SUMMARY_MODEL_DEFAULT


async def test_analyze_conversation_returns_no_analysis_on_garbage_but_keeps_usage() -> None:
    # Токены уже потрачены — usage отдаём даже при нечитаемом ответе,
    # чтобы расход попал в учёт.
    outcome = await analyze_conversation(
        [SummaryMessage(role="user", content="привет")],
        client=_Client("не json"),  # type: ignore[arg-type]
    )
    assert outcome.analysis is None
    assert outcome.tokens_in == 1200
