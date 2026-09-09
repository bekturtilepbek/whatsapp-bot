"""CORS для admin-web (Волна 3, QR-экран): браузер стучится в api напрямую с
другого origin (порт admin-web) — без allow-origin браузер зарубит fetch.
Без Docker — CORSMiddleware не трогает БД.
"""

from __future__ import annotations

import httpx
from api.main import app


async def test_configured_admin_web_origin_is_allowed() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_unknown_origin_is_not_allowed() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
