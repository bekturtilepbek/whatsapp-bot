"""Интерфейс тулзы бота (FEATURES.md 4.13). Реализация конкретной тулзы —
модуль/класс в этом пакете, регистрируется в registry.py; какому боту она
доступна и с каким config — решает tool_bindings (libs/db), не код тулзы.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from db.models import Bot
from integrations.storage import Storage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class ToolContext:
    """Всё, что нужно тулзе для одного вызова — собирается в
    services/worker/pipeline/consumer.py на каждый tool-call."""

    bot: Bot
    contact_id: uuid.UUID
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: Storage
    config: dict[str, Any]  # tool_bindings.config для этого бота и этой тулзы


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]  # JSON schema тела function для OpenAI

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> str: ...
