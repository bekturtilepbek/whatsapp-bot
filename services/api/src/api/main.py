"""FastAPI: HTTP-ручки управления ботами (STAGE1_CORE Блок 3, п.2).

Слушает 0.0.0.0 внутри контейнера (стандартная докер-практика); публичная
доступность решается маппингом порта в compose — на проде на хост
пробрасывается только 127.0.0.1 (SSH-туннель), в dev — обычный маппинг.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import bots, products

app = FastAPI(title="platform-api")

# admin-web стучится в api напрямую из браузера (Волна 3, QR-экран, подход A) —
# без allow-origin браузер зарубит fetch кросс-порта. allow_credentials не
# нужен — auth ещё нет (6.18, отдельная итерация), делить нечего.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ADMIN_WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bots.router)
app.include_router(products.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
