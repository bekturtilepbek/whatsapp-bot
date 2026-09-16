"""Интерфейс тулзы бота (FEATURES.md 4.13). Тулза возвращает
ToolExecutionResult, а не голую строку (FEATURES.md 4.3/4.4) — так тулза
может сообщить "отправь клиенту вот это фото+текст ВМЕСТО ответа LLM", не
проходя эту возможность через отдельный API. Кто реально публикует
событие в wa:out — services/worker/pipeline/consumer.py::_reply() (у него
уже есть chat_id/redis/OUT_STREAM); ToolContext НЕ меняется — тулза не
публикует события сама (ADR-002, worker — оркестрация).

parameters_schema объявлен как read-only property (не обычный атрибут) —
это принимает и ClassVar-объявление в реализациях (естественная идиома
для неизменяемого dict), и обычный instance-атрибут, снимая
несовместимость с mypy strict, найденную финальным ревью 4.1/4.2.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from db.models import Bot
from integrations.storage import Storage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass(frozen=True)
class ToolContext:
    bot: Bot
    contact_id: uuid.UUID
    session_factory: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: Storage
    config: dict[str, Any]


@dataclass(frozen=True)
class MediaToSend:
    storage_key: str
    mime_type: str
    filename: str | None = None  # только для outbound.document (Baileys требует fileName)


@dataclass(frozen=True)
class ToolExecutionResult:
    content: str  # как раньше — уходит в LLM как результат tool call
    # Если задано — уходит клиенту ВМЕСТО ответа LLM (FEATURES.md 4.3/4.4);
    # None — поведение как раньше (LLM отвечает своим текстом).
    override_reply_text: str | None = None
    media: Sequence[MediaToSend] = ()  # фото, отправляются раньше override_reply_text


class Tool(Protocol):
    name: str
    description: str
    # True — тулза производит реальный побочный эффект вовне (шлёт
    # сообщение, деньги и т.п.); песочница (FEATURES.md 9.6) глушит такие
    # тулзы каноническим ответом вместо реального вызова execute().
    side_effecting: bool

    @property
    def parameters_schema(self) -> dict[str, Any]: ...

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult: ...
