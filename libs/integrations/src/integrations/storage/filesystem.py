"""Storage поверх локальной ФС — общий docker-volume с gateway в dev
(см. compose/docker-compose.dev.yml, STORAGE_FS_ROOT)."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FilesystemStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    async def get(self, key: str) -> bytes:
        path = self._root / key
        return await asyncio.to_thread(path.read_bytes)
