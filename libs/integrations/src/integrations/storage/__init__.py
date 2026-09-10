"""Storage-абстракция (FEATURES.md 2.7): gateway пишет (TS-сторона,
services/gateway/src/storage), worker читает через этот пакет. Реализация
выбирается STORAGE_DRIVER=fs|s3, одинаково на обеих сторонах.
"""

from __future__ import annotations

import os
from typing import Protocol


class Storage(Protocol):
    async def get(self, key: str) -> bytes: ...
    async def put(self, key: str, data: bytes, mime_type: str) -> None: ...


_DEFAULT_FS_ROOT = "/data/media"


def create_storage(env: dict[str, str] | None = None) -> Storage:
    env = env if env is not None else dict(os.environ)
    driver = env.get("STORAGE_DRIVER", "fs")
    if driver == "s3":
        from .s3 import S3Storage

        bucket = env.get("S3_BUCKET")
        if not bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_DRIVER=s3")
        return S3Storage(
            bucket=bucket,
            endpoint_url=env.get("S3_ENDPOINT"),
            region_name=env.get("S3_REGION", "us-east-1"),
            aws_access_key_id=env.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=env.get("S3_SECRET_KEY", ""),
        )
    from .filesystem import FilesystemStorage

    return FilesystemStorage(env.get("STORAGE_FS_ROOT", _DEFAULT_FS_ROOT))
