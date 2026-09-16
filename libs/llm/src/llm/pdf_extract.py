"""Извлечение текста из PDF (FEATURES.md 2.4). `pypdf` — чистый Python, без
нативных зависимостей (проще для Docker-образа, чем PyMuPDF/poppler).

Раньше жило в services/worker/src/worker/pipeline/pdf_extract.py —
вынесено в libs/llm (FEATURES.md 9.6 часть B, песочница): функция не имела
ничего worker-специфичного, а api-образ не содержит services/worker (та
же причина, что и у переноса tool_loop в части A).
"""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


class PdfHasNoTextLayerError(Exception):
    """PDF без текстового слоя (скан без OCR) — эталон V1 (`extractPdfText`):
    'PDF не содержит текстового слоя'. Вызывающий код (`_reply_with_pdf`)
    ловит это и деградирует в медиа-заглушку — OCR вне скоупа.
    """


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    text = "".join(page.extract_text() for page in reader.pages).strip()
    if not text:
        raise PdfHasNoTextLayerError("PDF не содержит текстового слоя")
    return text
