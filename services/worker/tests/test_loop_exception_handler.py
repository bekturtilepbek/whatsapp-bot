"""FEATURES.md 8.4 (Python-сторона): исключение в фоновой asyncio-задаче,
результат которой никто не забрал, не должно тонуть молча."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from worker import main as main_module


def test_loop_exception_handler_logs_the_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Logger:
        def error(self, event: str, **kw: Any) -> None:
            calls.append((event, kw))

    monkeypatch.setattr(main_module, "logger", _Logger())
    loop = asyncio.new_event_loop()
    try:
        main_module._log_loop_exception(
            loop, {"message": "Task exception was never retrieved", "exception": ValueError("x")}
        )
    finally:
        loop.close()

    assert calls
    event, kw = calls[0]
    assert event == "unhandled asyncio exception"
    assert kw["detail"] == "Task exception was never retrieved"
    assert isinstance(kw["exc_info"], ValueError)
