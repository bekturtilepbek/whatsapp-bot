"""Pydantic v2 схемы чёрного списка номеров (FEATURES.md 1.5)."""

from __future__ import annotations

from pydantic import BaseModel


class BlockedNumberIn(BaseModel):
    phone: str


class BlockedNumberOut(BaseModel):
    phone: str
