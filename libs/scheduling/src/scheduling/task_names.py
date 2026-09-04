"""Имена Celery-задач, общие между постановкой (services/worker) и
регистрацией (services/celery) — держим в одном месте, чтобы строка не
разъехалась между двумя сторонами (тот же принцип, что и
libs/core/redis_keys.py для имён Redis-ключей).
"""

from __future__ import annotations

FOLLOW_UP_REMINDER = "tasks.followup.send_reminder"
