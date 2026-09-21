"""_process_and_ack: сбой самого XACK не должен вылетать из корутины таски
наружу (найдено 2026-09-21) — иначе add_done_callback в run_pipeline_consumer
его не забирает (эквивалент unhandledRejection в Node), и сообщение остаётся
в pending list навсегда без единого лога. Не требует Docker — используется
entry.payload=None, чтобы не доходить до _process_entry/БД вообще.
"""

from __future__ import annotations

import structlog
from fakeredis.aioredis import FakeRedis
from worker.bus import IN_STREAM, StreamEntry, ensure_group
from worker.pipeline.consumer import GROUP, _process_and_ack


class _NullStorage:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError


class _NullSessionFactory:
    def __call__(self) -> None:
        raise NotImplementedError


async def test_ack_failure_is_caught_and_logged_not_raised() -> None:
    redis = FakeRedis()
    try:
        await ensure_group(redis, IN_STREAM, GROUP)

        async def failing_xack(*args: object, **kwargs: object) -> None:
            raise ConnectionError("simulated redis blip")

        redis.xack = failing_xack  # type: ignore[method-assign]

        with structlog.testing.capture_logs() as logs:
            # Не должно бросить исключение наружу — иначе оно ушло бы из
            # asyncio.create_task(...) незамеченным.
            await _process_and_ack(
                StreamEntry(entry_id="1-1", payload=None),
                redis,
                _NullSessionFactory(),  # type: ignore[arg-type]
                _NullStorage(),
            )

        assert any(
            log.get("event") == "failed to ack wa:in entry, it will remain pending"
            for log in logs
        )
    finally:
        await redis.aclose()


async def test_successful_ack_is_not_logged_as_a_failure() -> None:
    redis = FakeRedis()
    try:
        await ensure_group(redis, IN_STREAM, GROUP)
        await redis.xadd(IN_STREAM, {"payload": "{}"}, id="1-1")

        with structlog.testing.capture_logs() as logs:
            await _process_and_ack(
                StreamEntry(entry_id="1-1", payload=None),
                redis,
                _NullSessionFactory(),  # type: ignore[arg-type]
                _NullStorage(),
            )

        assert not any(log.get("log_level") == "error" for log in logs)
    finally:
        await redis.aclose()
