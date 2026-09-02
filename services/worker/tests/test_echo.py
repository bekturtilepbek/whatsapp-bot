"""Смоук-тест echo-режима на реальном Redis (testcontainers).

Требует Docker. Если недоступен — skip, не fail (см. libs/db/tests/test_migration.py
для того же паттерна).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid

import pytest

pytest.importorskip("testcontainers.redis")
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer
from worker.bus import IN_STREAM, OUT_STREAM, publish
from worker.echo import run_echo_consumer


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker недоступен в этом окружении")
async def test_inbound_text_echoes_to_outbound() -> None:
    with RedisContainer() as container:
        url = f"redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}/0"
        redis: Redis = Redis.from_url(url, decode_responses=True)

        consumer_task = asyncio.create_task(run_echo_consumer(redis, "test-consumer"))
        try:
            bot_id = str(uuid.uuid4())
            await publish(
                redis,
                IN_STREAM,
                {
                    "type": "inbound.text",
                    "bot_id": bot_id,
                    "wa_msg_id": "wamsg-1",
                    "chat_id": "996700000000@s.whatsapp.net",
                    "sender_wa_id": "996700000000",
                    "from_me": False,
                    "text": "привет",
                    "ts": 1756800000000,
                },
            )

            for _ in range(50):  # до ~5с на подъём консюмера и обработку
                entries = await redis.xrange(OUT_STREAM)
                if entries:
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("no echo appeared on wa:out in time")

            _entry_id, fields = entries[0]
            echoed = json.loads(fields["payload"])
            assert echoed["type"] == "outbound.text"
            assert echoed["bot_id"] == bot_id
            assert echoed["chat_id"] == "996700000000@s.whatsapp.net"
            assert echoed["text"] == "привет"
            assert echoed["client_msg_id"]
        finally:
            consumer_task.cancel()
            try:
                await consumer_task
            except asyncio.CancelledError:
                pass
            await redis.aclose()
