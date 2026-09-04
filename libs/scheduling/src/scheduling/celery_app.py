"""Celery-приложение: общий брокер/backend (Redis) для services/worker
(постановка задач) и services/celery (исполнение). Сами задачи регистрирует
services/celery — здесь только конфиг, чтобы не тащить celery со всеми
зависимостями в services/api, которому это не нужно (ADR-003).
"""

from __future__ import annotations

import os

from celery import Celery


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


celery_app = Celery("platform", broker=_redis_url(), backend=_redis_url())
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Redis-брокер не умеет нативную отложенную доставку: задача с eta
    # вычитывается воркером сразу и ждёт eta в памяти процесса, ack уходит
    # только по факту исполнения. Если eta длиннее visibility_timeout,
    # Redis решает, что сообщение потеряно, и отдаёт его повторно —
    # то есть задача выполняется дважды. Дефолт kombu — 3600с, ровно на
    # границе DEFAULT_REMINDER_DELAY_MINUTES=60; поднимаем с запасом на
    # реалистичные настройки reminder_delay_minutes per bot.
    broker_transport_options={"visibility_timeout": 86400},
)
