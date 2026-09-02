"""GET /bots/{id}/qr и POST /bots/{id}/logout — прозрачный прокси к gateway.

Мок httpx.MockTransport вместо реального gateway (плана: "не поднимаем
реальный gateway в тестах api"). Docker/testcontainers не нужны — БД тут
не участвует.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from api.gateway_client import get_gateway_client
from api.main import app

BOT_ID = uuid.uuid4()


def _client_with_transport(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, base_url="http://gateway")


def _override_gateway(mock_client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_gateway_client] = lambda: mock_client


@pytest.fixture(autouse=True)
def _clear_overrides() -> AsyncIterator[None]:
    yield
    app.dependency_overrides.clear()


async def test_qr_proxies_png_body_and_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/qr/{BOT_ID}"
        return httpx.Response(
            200, content=b"\x89PNG-fake-bytes", headers={"content-type": "image/png"}
        )

    mock_client = _client_with_transport(httpx.MockTransport(handler))
    _override_gateway(mock_client)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/bots/{BOT_ID}/qr")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG-fake-bytes"


async def test_qr_proxies_upstream_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "bot not found"})

    mock_client = _client_with_transport(httpx.MockTransport(handler))
    _override_gateway(mock_client)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/bots/{BOT_ID}/qr")

    assert response.status_code == 404


async def test_logout_proxies_post_and_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/bots/{BOT_ID}/logout"
        return httpx.Response(200, json={"status": "logged_out"})

    mock_client = _client_with_transport(httpx.MockTransport(handler))
    _override_gateway(mock_client)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.post(f"/bots/{BOT_ID}/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}


async def test_gateway_unreachable_returns_502() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    mock_client = _client_with_transport(httpx.MockTransport(handler))
    _override_gateway(mock_client)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get(f"/bots/{BOT_ID}/qr")

    assert response.status_code == 502
