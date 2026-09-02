"""Точка входа worker.

Блок 1: /health для healthcheck compose + временный echo-консюмер wa:in
(services/worker/src/worker/echo.py) — доказывает контур gateway<->Redis
<->worker целиком. Реальный пайплайн (дедуп, фильтры, батчинг, LLM) —
Блок 2 STAGE1_CORE.
"""

from __future__ import annotations

import asyncio
import os
import signal

import structlog
from aiohttp import web

from .bus import make_redis
from .echo import run_echo_consumer

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
    consumer_name = f"worker-{os.getpid()}"
    echo_task = asyncio.create_task(run_echo_consumer(redis, consumer_name))

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
    echo_task.cancel()
    try:
        await echo_task
    except asyncio.CancelledError:
        pass
    await redis.aclose()
    await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
