"""Pydantic v2 схемы реестра тулз бота (FEATURES.md 4.13)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolBindingIn(BaseModel):
    tool_name: str
    config: dict[str, Any] = Field(default_factory=dict)


class ToolBindingOut(BaseModel):
    tool_name: str
    config: dict[str, Any]
