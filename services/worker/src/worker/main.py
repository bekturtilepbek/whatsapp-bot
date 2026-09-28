"""Точка входа worker.

/health для healthcheck compose + пайплайн диалога
(services/worker/src/worker/pipeline/consumer.py) — дедуп, фильтры,
батчинг, история, LLM, ответ. Заменяет временный echo Блока 1.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiohttp import web
from db.engine import make_engine, make_session_factory
from integrations.storage import create_storage
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .bus import make_redis
from .pipeline.consumer import run_pipeline_consumer

logger = structlog.get_logger("worker")


def _make_health_handler(
    engine: AsyncEngine, redis: Redis
) -> Callable[[web.Request], Awaitable[web.Response]]:
    # FEATURES.md 8.8: раньше — только "процесс отвечает на порту". Postgres/
    # Redis, упавшие ПОСЛЕ старта (compose гарантирует их здоровье только на
    # старте, depends_on: service_healthy), не отражались бы в healthcheck
    # вообще, маскируя реальный простой сколько угодно долго.
    async def health(_: web.Request) -> web.Response:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await redis.ping()
        except Exception:
            logger.warning("health check failed", exc_info=True)
            return web.json_response({"status": "degraded"}, status=503)
        return web.json_response({"status": "ok"})

    return health


async def run_health_server(engine: AsyncEngine, redis: Redis) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/health", _make_health_handler(engine, redis))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("WORKER_HEALTH_PORT", "8081"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("worker health server listening", port=port)
    return runner


def _log_loop_exception(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """FEATURES.md 8.4: страховка от ещё не найденных источников. Каждая
    запись wa:in обрабатывается своей задачей (consumer.py); если её
    исключение ни разу не заберут, asyncio пишет "Task exception was never
    retrieved" стандартным logging только при сборке мусора — в структурных
    логах worker его не видно. Процесс не роняем: один сбойный диалог не
    должен останавливать остальные."""
    logger.error(
        "unhandled asyncio exception",
        detail=context.get("message"),
        exc_info=context.get("exception"),
    )


async def main() -> None:
    redis = make_redis()
    engine = make_engine()
    session_factory = make_session_factory(engine)
    storage = create_storage()
    health_runner = await run_health_server(engine, redis)
    consumer_name = f"worker-{os.getpid()}"
    pipeline_task = asyncio.create_task(
        run_pipeline_consumer(redis, session_factory, consumer_name, storage)
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_log_loop_exception)
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
    except NotImplementedError:
        # add_signal_handler недоступен на Windows event loop; в проде всегда
        # Linux-контейнер (compose/Docker) — тут просто не подписываемся.
        logger.warning("signal handlers unavailable on this platform")

    await stop.wait()
    logger.info("shutting down")
    pipeline_task.cancel()
    try:
        await pipeline_task
    except asyncio.CancelledError:
        pass
    await redis.aclose()
    await engine.dispose()
    await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
