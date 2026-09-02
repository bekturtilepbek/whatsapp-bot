"""Точка входа worker.

На шаге 1 — только каркас и /health для healthcheck compose; консюмер wa:in
с echo-режимом добавляется в шаге 5.
"""

import asyncio
import os

import structlog
from aiohttp import web

logger = structlog.get_logger("worker")


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def run_health_server() -> None:
    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("WORKER_HEALTH_PORT", "8081"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("worker health server listening", port=port)


async def main() -> None:
    await run_health_server()
    # Консюмер wa:in подключается в шаге 5; пока просто держим процесс живым.
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
