"""Тонкая httpx-обёртка над внутренними ручками gateway (QR, logout).

GATEWAY_URL — внутренний адрес в docker-сети (http://gateway:8080 в
compose), не публичный. Таймаут чуть больше, чем собственный таймаут
ожидания QR у gateway (20с) — не режем легитимно долгий, но укладывающийся
в его же бюджет ответ.
"""

from __future__ import annotations

import os
from typing import Annotated

import httpx
from fastapi import Depends

_TIMEOUT_SECONDS = 25.0

_client: httpx.AsyncClient | None = None


def _base_url() -> str:
    return os.environ.get("GATEWAY_URL", "http://localhost:8080")


def get_gateway_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=_base_url(), timeout=_TIMEOUT_SECONDS)
    return _client


GatewayClientDep = Annotated[httpx.AsyncClient, Depends(get_gateway_client)]
