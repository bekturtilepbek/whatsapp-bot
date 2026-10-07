"""Саммари диалога и температура клиента (FEATURES.md 6.13).

Эталон — V1 (central-admin/main.py::generate_conversation_summary_and_temperature):
тот же промпт и критерии температуры, до 20 последних сообщений, JSON-ответ.
Отличия от V1 — сознательные: (1) дешёвая фиксированная модель независимо от
модели бота (SUMMARY_MODEL), (2) нечитаемый ответ — None, а не молчаливое
"холодный" (вызывающий не затирает прежнюю оценку), (3) реплики менеджера
размечены отдельной ролью.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Literal

from openai import AsyncOpenAI

from .client import HistoryMessage, complete

Temperature = Literal["hot", "warm", "cold"]

# Дешёвая модель для фоновых саммари — не модель бота: у бота может стоять
# gpt-4o для ответов, и саммари обходились бы в разы дороже. Переопределяется
# платформенной переменной окружения (в кабинет выбор не выносим).
SUMMARY_MODEL_DEFAULT = "gpt-6-luna"
# Бэкстоп на размер реплики: длинное сообщение/пересланный текст не должны
# раздувать токены фонового вызова.
MAX_MESSAGE_CHARS = 600
SUMMARY_TIMEOUT_SECONDS = 60.0

MANAGER_REPLY_PREFIX = "[Ответ менеджера] "

# Допустимые значения температуры в БД и ответе модели; V1 хранил русские
# слова ("теплый" без ё) — принимаем их тоже.
_TEMPERATURE_ALIASES: dict[str, Temperature] = {
    "hot": "hot",
    "warm": "warm",
    "cold": "cold",
    "горячий": "hot",
    "тёплый": "warm",
    "теплый": "warm",
    "холодный": "cold",
}

SYSTEM_PROMPT = """Проанализируйте диалог между клиентом и агентом (ботом или менеджером) \
и выполните две задачи:

1. Создайте краткое содержание (2-3 предложения) на русском языке.
2. Определите температуру клиента по критериям:
- hot (горячий): клиент проявляет высокий интерес, задаёт конкретные вопросы о покупке, \
обсуждает сроки, цены, доставку, проявляет срочность, готов к действию.
- warm (тёплый): клиент интересуется продуктом, задаёт уточняющие вопросы, \
но ещё не готов к покупке, изучает варианты.
- cold (холодный): клиент только знакомится с информацией, задаёт общие вопросы, \
не проявляет конкретных намерений к покупке.

Ответ дайте строго в формате JSON:
{"summary": "краткое содержание", "temperature": "hot|warm|cold"}"""


@dataclass(frozen=True)
class SummaryMessage:
    role: str  # "user" | "assistant"
    content: str


@dataclass(frozen=True)
class Analysis:
    summary: str
    temperature: Temperature


@dataclass(frozen=True)
class AnalysisOutcome:
    """analysis=None — ответ модели нечитаем; токены при этом потрачены,
    поэтому usage отдаётся всегда (расход должен попасть в учёт)."""

    analysis: Analysis | None
    tokens_in: int
    tokens_out: int
    model: str


def summary_model() -> str:
    return os.environ.get("SUMMARY_MODEL") or SUMMARY_MODEL_DEFAULT


def build_transcript(messages: list[SummaryMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        if message.role == "user":
            label, text = "Клиент", message.content
        elif message.content.startswith(MANAGER_REPLY_PREFIX):
            label, text = "Менеджер", message.content[len(MANAGER_REPLY_PREFIX) :]
        else:
            label, text = "Бот", message.content
        lines.append(f"{label}: {text[:MAX_MESSAGE_CHARS]}")
    return "\n".join(lines)


def parse_analysis(raw: str) -> Analysis | None:
    """JSON достаём регуляркой (модель может обернуть его в ```json или
    текст — как делал V1). Любая непригодность — None."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    summary = data.get("summary")
    temperature = data.get("temperature")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(temperature, str):
        return None
    normalized = _TEMPERATURE_ALIASES.get(temperature.strip().lower())
    if normalized is None:
        return None
    return Analysis(summary=summary.strip(), temperature=normalized)


async def analyze_conversation(
    messages: list[SummaryMessage], *, client: AsyncOpenAI | None = None
) -> AnalysisOutcome:
    """Один вызов LLM (с таймаутом и ретраями временных сбоев из complete()).
    Сетевые ошибки пробрасываются вызывающему."""
    model = summary_model()
    transcript = build_transcript(messages)
    result = await complete(
        SYSTEM_PROMPT,
        [HistoryMessage(role="user", content=f"Диалог:\n{transcript}")],
        model=model,
        client=client,
        timeout_seconds=SUMMARY_TIMEOUT_SECONDS,
    )
    return AnalysisOutcome(
        analysis=parse_analysis(result.text),
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        model=model,
    )
