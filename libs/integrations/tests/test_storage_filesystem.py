"""FilesystemStorage — чтение с общего docker-volume (dev-driver)."""

from __future__ import annotations

from pathlib import Path

from integrations.storage.filesystem import FilesystemStorage


async def test_get_reads_bytes_written_at_nested_key(tmp_path: Path) -> None:
    nested = tmp_path / "bots" / "bot-1" / "media"
    nested.mkdir(parents=True)
    (nested / "msg-1").write_bytes(b"hello")

    storage = FilesystemStorage(str(tmp_path))
    result = await storage.get("bots/bot-1/media/msg-1")

    assert result == b"hello"
