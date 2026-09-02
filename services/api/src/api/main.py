"""FastAPI: HTTP-ручки управления ботами (STAGE1_CORE Блок 3, п.2).

Слушает 0.0.0.0 внутри контейнера (стандартная докер-практика); публичная
доступность решается маппингом порта в compose — на проде на хост
пробрасывается только 127.0.0.1 (SSH-туннель), в dev — обычный маппинг.
"""

from __future__ import annotations

from fastapi import FastAPI

from .routers import bots

app = FastAPI(title="platform-api")
app.include_router(bots.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
