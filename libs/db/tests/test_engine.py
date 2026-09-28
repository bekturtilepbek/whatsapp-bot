"""make_engine() должен ставить таймаут на каждый Postgres-запрос — без него
зависшее соединение держит вызывающий код (в частности лок диалога worker'а,
pipeline/lock.py::keep_alive) на await бессрочно (security review, 2026-09-28,
CLAUDE.md "любой внешний вызов — с таймаутом")."""

from __future__ import annotations

from unittest.mock import patch

from db.engine import make_engine


def test_make_engine_sets_a_command_timeout_on_every_query() -> None:
    with patch("db.engine.create_async_engine") as mock_create:
        make_engine("postgresql://user:pass@localhost/db")

    assert mock_create.call_count == 1
    _, kwargs = mock_create.call_args
    assert kwargs["connect_args"]["command_timeout"] == 30
