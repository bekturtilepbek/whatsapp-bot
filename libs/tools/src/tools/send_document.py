"""Отправка файла или видео клиенту (FEATURES.md 4.8/4.9) — эталон V1
(sendDocument), но файл ищется в БД по имени, не на диске (платформа
мультитенантная, файлы — в Storage). Одна тулза на оба случая — LLM не
думает заранее, файл это или видео, тулза сама смотрит mime_type; какое
outbound-событие публиковать (outbound.video/outbound.document) решает
consumer.py::_send_cards по mime_type каждого MediaToSend, не эта тулза.
"""

from __future__ import annotations

from typing import Any, ClassVar

from db.documents import find_document_by_filename

from .base import MediaToSend, ToolContext, ToolExecutionResult

_NOT_FOUND_ERROR = 'Файл "{filename}" не найден.'


class SendDocumentTool:
    name = "send_document"
    description = "Отправляет клиенту файл или видео по точному имени из списка доступных файлов."
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "file_name": {
                "type": "string",
                "description": "Точное имя файла из списка доступных файлов",
            }
        },
        "required": ["file_name"],
    }

    async def execute(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolExecutionResult:
        filename = str(arguments.get("file_name", ""))
        if not filename.strip():
            return ToolExecutionResult(content="Не указано имя файла.")

        async with ctx.session_factory() as session:
            document = await find_document_by_filename(session, ctx.bot.id, filename)

        if document is None:
            return ToolExecutionResult(content=_NOT_FOUND_ERROR.format(filename=filename))

        media = MediaToSend(
            storage_key=document.storage_key,
            mime_type=document.mime_type,
            filename=document.filename,
        )
        return ToolExecutionResult(
            content=f"Файл {filename} поставлен в очередь на отправку.",
            override_reply_text=f"Отправляю файл {filename}.",
            media=(media,),
        )
