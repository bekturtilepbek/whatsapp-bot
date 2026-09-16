"""side_effecting на Tool (FEATURES.md 9.6, часть A — песочница). Флаг решает,
может ли тулза быть вызвана в песочнице по-настоящему: тулзы без реального
побочного эффекта (только читают) — False, тулзы с реальным эффектом
(шлют что-то вовне) — True, песочница глушит их вместо вызова.
"""

from __future__ import annotations

from tools.product_search import ProductSearchTool
from tools.send_document import SendDocumentTool
from tools.telegram_lead import TelegramLeadTool


def test_product_search_is_not_side_effecting() -> None:
    assert ProductSearchTool().side_effecting is False


def test_send_document_is_not_side_effecting() -> None:
    assert SendDocumentTool().side_effecting is False


def test_telegram_lead_is_side_effecting() -> None:
    assert TelegramLeadTool().side_effecting is True
