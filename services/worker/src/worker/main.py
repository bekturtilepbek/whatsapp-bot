"""Точка входа worker.

/health для healthcheck compose + пайплайн диалога
(services/worker/src/worker/pipeline/consumer.py) — дедуп, фильтры,
батчинг, история, LLM, ответ. Заменяет временный echo Блока 1.
"""

from __future__ import annotations

import asyncio
import os
import signal

import structlog
from aiohttp import web
from db.engine import make_engine, make_session_factory

from .bus import make_redis
from .pipeline.consumer import run_pipeline_consumer

logger = structlog.get_logger("worker")


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def run_health_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("WORKER_HEALTH_PORT", "8081"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("worker health server listening", port=port)
    return runner


async def main() -> None:
    health_runner = await run_health_server()
    redis = make_redis()
    engine = make_engine()
    session_factory = make_session_factory(engine)
    consumer_name = f"worker-{os.getpid()}"
    pipeline_task = asyncio.create_task(
        run_pipeline_consumer(redis, session_factory, consumer_name)
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
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
