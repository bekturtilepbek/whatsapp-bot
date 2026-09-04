"""Извлечение текста из PDF (FEATURES.md 2.4) — pypdf на реальных PDF-файлах,
без мока библиотеки: фикстуры в fixtures/ — настоящие, читаемые PDF.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from worker.pipeline.pdf_extract import PdfHasNoTextLayerError, extract_pdf_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_extracts_text_from_a_real_pdf() -> None:
    pdf_bytes = (FIXTURES / "sample.pdf").read_bytes()
    assert extract_pdf_text(pdf_bytes) == "Hello world from a test PDF fixture"


def test_raises_when_pdf_has_no_text_layer() -> None:
    pdf_bytes = (FIXTURES / "no_text_layer.pdf").read_bytes()
    with pytest.raises(PdfHasNoTextLayerError):
        extract_pdf_text(pdf_bytes)
