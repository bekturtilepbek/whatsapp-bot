"""Точка входа Celery-воркера: `celery -A tasks worker`. Экспортирует
`celery` (конвенция — Celery -A ищет этот атрибут в пакете) из общего
libs/scheduling и импортирует модули задач, чтобы @celery_app.task
зарегистрировался при старте воркера.
"""

from __future__ import annotations

from scheduling.celery_app import celery_app as celery  # noqa: F401

from . import followup  # noqa: F401
