"""FilesystemStorage — чтение с общего docker-volume (dev-driver)."""

from __future__ import annotations

from pathlib import Path

import pytest
from integrations.storage.filesystem import FilesystemStorage


async def test_get_reads_bytes_written_at_nested_key(tmp_path: Path) -> None:
    nested = tmp_path / "bots" / "bot-1" / "media"
    nested.mkdir(parents=True)
    (nested / "msg-1").write_bytes(b"hello")

    storage = FilesystemStorage(str(tmp_path))
    result = await storage.get("bots/bot-1/media/msg-1")

    assert result == b"hello"


async def test_get_rejects_a_path_traversal_key(tmp_path: Path) -> None:
    # Fix 1 (финальный review): защита на границе join() — этот пакет пока
    # никуда не подключён, но key по контракту не доверенный.
    root = tmp_path / "storage-root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"do not read me")

    storage = FilesystemStorage(str(root))

    with pytest.raises(ValueError):
        await storage.get("../secret.txt")


async def test_put_then_get_returns_the_same_bytes(tmp_path: Path) -> None:
    storage = FilesystemStorage(str(tmp_path))

    await storage.put("bots/bot-1/products/prod-1/img-1", b"hello photo", "image/jpeg")
    result = await storage.get("bots/bot-1/products/prod-1/img-1")

    assert result == b"hello photo"


async def test_put_creates_missing_parent_directories(tmp_path: Path) -> None:
    storage = FilesystemStorage(str(tmp_path))

    await storage.put("bots/bot-1/products/prod-1/img-1", b"data", "image/png")

    assert (tmp_path / "bots" / "bot-1" / "products" / "prod-1" / "img-1").read_bytes() == b"data"


async def test_put_rejects_a_path_traversal_key(tmp_path: Path) -> None:
    root = tmp_path / "storage-root"
    root.mkdir()

    storage = FilesystemStorage(str(root))

    with pytest.raises(ValueError):
        await storage.put("../escaped", b"data", "image/jpeg")
