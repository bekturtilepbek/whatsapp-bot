"""Имена Redis-ключей, общие между сервисами (worker, api, gateway-TS).

Чистые функции построения строки, без I/O — каждый сервис использует их
со своим собственным Redis-клиентом. Держим здесь, а не в каждом сервисе
по отдельности: имя ключа, задокументированное в двух местах, рискует
разъехаться (например, TTL/формат поменяют в одном месте и забудут в другом).
"""

from __future__ import annotations


def wa_sent_key(client_msg_id: str) -> str:
    """Идемпотентность отправки (gateway, Блок 1) — тот же ключ Блок 3
    использует для детекта "это наш echo, а не ручной ответ менеджера".
    """
    return f"wa:sent:{client_msg_id}"


def handoff_key(bot_id: str, chat_id: str) -> str:
    """Пока ключ жив — worker молчит на этот чат, отвечает менеджер вручную."""
    return f"handoff:{bot_id}:{chat_id}"


def handoff_pattern(bot_id: str) -> str:
    """SCAN-паттерн всех активных handoff-чатов одного бота (список "Активные
    чаты" в кабинете) — отдельного индекса нет, ключей с TTL немного."""
    return f"handoff:{bot_id}:*"


def followup_sent_key(contact_id: str, after_seq: int) -> str:
    """Идемпотентность отправки напоминания (FEATURES.md 5.5): Redis-брокер
    может доставить ETA-задачу повторно (см. scheduling/celery_app.py про
    visibility_timeout) — эта пометка не даёт напоминание уйти дважды даже
    при повторной доставке. Проверка и пометка — атомарно, до публикации
    (тот же принцип "дедуп до любого await", что и pipeline/dedup.py).
    """
    return f"followup:sent:{contact_id}:{after_seq}"
