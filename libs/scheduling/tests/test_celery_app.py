"""Конфигурация Celery-приложения и имя follow-up задачи."""

from __future__ import annotations

from scheduling.celery_app import celery_app
from scheduling.task_names import FOLLOW_UP_REMINDER


def test_celery_app_uses_redis_for_broker_and_backend() -> None:
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.conf.result_backend.startswith("redis://")


def test_celery_app_uses_json_serialization() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]


def test_follow_up_task_name_is_stable() -> None:
    # Строка захардкожена в тесте намеренно — меняется редко и осознанно;
    # оба потребителя (worker, celery) должны совпадать именно на ней.
    assert FOLLOW_UP_REMINDER == "tasks.followup.send_reminder"
