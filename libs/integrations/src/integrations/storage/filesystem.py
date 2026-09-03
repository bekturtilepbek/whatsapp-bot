"""Storage поверх локальной ФС — общий docker-volume с gateway в dev
(см. compose/docker-compose.dev.yml, STORAGE_FS_ROOT)."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FilesystemStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    async def get(self, key: str) -> bytes:
        # Fix 1 (защита на границе join): этот пакет пока никуда не подключён
        # (будущий вызывающий код Task 4 появится позже), но ключ по контракту
        # не доверенный — резолвим оба пути и проверяем, что путь к файлу не
        # ушёл за пределы root (path traversal через "../" в key).
        root_resolved = self._root.resolve()
        path = (self._root / key).resolve()
        if not path.is_relative_to(root_resolved):
            raise ValueError(f"storage key resolves outside root: {key!r}")
        return await asyncio.to_thread(path.read_bytes)
