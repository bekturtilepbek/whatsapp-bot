"""S3Storage — read-путь worker'а из S3-совместимого хранилища (prod-driver)."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

from integrations.storage.s3 import S3Storage


async def test_get_reads_object_body_via_injected_client() -> None:
    client = MagicMock()
    client.get_object.return_value = {"Body": BytesIO(b"hello")}
    storage = S3Storage(bucket="my-bucket", client=client)

    result = await storage.get("bots/bot-1/media/msg-1")

    assert result == b"hello"
    client.get_object.assert_called_once_with(Bucket="my-bucket", Key="bots/bot-1/media/msg-1")
