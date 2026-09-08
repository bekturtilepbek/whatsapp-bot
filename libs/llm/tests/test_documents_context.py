"""documents_context — список файлов бота для system prompt (FEATURES.md
4.8/4.9), платформенное дополнение сверх V1 (симметрично catalog_context,
FEATURES.md 3.4)."""

from __future__ import annotations

from llm.documents_context import DocumentInfo, documents_context


def test_empty_documents_list_returns_empty_message() -> None:
    assert documents_context([]) == "Файлов пока нет."


def test_lists_filenames_with_header() -> None:
    result = documents_context(
        [DocumentInfo(filename="price-list.pdf"), DocumentInfo(filename="dogovor.docx")]
    )
    assert "ДОСТУПНЫЕ ФАЙЛЫ" in result
    assert "- price-list.pdf" in result
    assert "- dogovor.docx" in result
