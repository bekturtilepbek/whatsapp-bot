"""Pydantic v2 схемы песочницы (FEATURES.md 9.6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SandboxHistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SandboxMessageIn(BaseModel):
    # 50 — тот же порядок, что и окно реальной истории диалога
    # (fetch_recent_history, FEATURES.md 3.1); защита от разгона запроса,
    # не потому что кто-то конкретно попросил именно это число.
    history: list[SandboxHistoryItem] = Field(default_factory=list, max_length=50)
    message: str


class SandboxMessageOut(BaseModel):
    reply: str
    tokens_in: int
    tokens_out: int
    model: str
