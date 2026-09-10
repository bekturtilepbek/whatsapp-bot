"""Storage поверх локальной ФС — общий docker-volume с gateway в dev
(см. compose/docker-compose.dev.yml, STORAGE_FS_ROOT)."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FilesystemStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _resolve_within_root(self, key: str) -> Path:
        root_resolved = self._root.resolve()
        path = (self._root / key).resolve()
        if not path.is_relative_to(root_resolved):
            raise ValueError(f"storage key resolves outside root: {key!r}")
        return path

    async def get(self, key: str) -> bytes:
        path = self._resolve_within_root(key)
        return await asyncio.to_thread(path.read_bytes)

    async def put(self, key: str, data: bytes, mime_type: str) -> None:
        # mime_type не нужен для fs (нет метаданных объекта) — принимается
        # только чтобы сигнатура совпадала с Storage Protocol/S3Storage.
        path = self._resolve_within_root(key)
        await asyncio.to_thread(self._write_sync, path, data)

    def _write_sync(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
