"""Миграция накатывается на чистый Postgres, таблицы существуют.

Требует Docker (testcontainers поднимает pgvector/pgvector:pg17). Если
Docker недоступен в окружении — тест skip'ается, не падает CI не по вине кода.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect

pytest.importorskip("testcontainers.postgres")
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"


def _docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"], capture_output=True, check=True, timeout=10
        )
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_available(), reason="Docker недоступен в этом окружении")
def test_migration_creates_expected_tables() -> None:
    with PostgresContainer("pgvector/pgvector:pg17", driver="psycopg2") as pg:
        database_url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            env={"DATABASE_URL": database_url},
        )

        engine = sa.create_engine(pg.get_connection_url())
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {"bots", "bot_sessions"} <= tables

        bot_columns = {c["name"] for c in inspector.get_columns("bots")}
        assert bot_columns == {
            "id", "name", "enabled", "system_prompt", "timezone", "settings", "created_at",
        }

        session_columns = {c["name"] for c in inspector.get_columns("bot_sessions")}
        assert session_columns == {
            "bot_id", "auth_state", "phone", "linked_at", "last_seen",
        }
