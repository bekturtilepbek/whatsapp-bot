"""Миграция накатывается на чистый Postgres, таблицы существуют.

Требует Docker (testcontainers поднимает pgvector/pgvector:pg17). Если
Docker недоступен в окружении — тест skip'ается, не падает CI не по вине кода.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import inspect

pytest.importorskip("testcontainers.postgres")
from db.engine import make_engine
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker недоступен в этом окружении"
)


@pytest.fixture
def database_url() -> AsyncIterator[str]:
    with PostgresContainer("pgvector/pgvector:pg17", driver="psycopg2") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        yield url


async def test_migration_creates_expected_tables(database_url: str) -> None:
    # Инспекция — тем же async-движком (asyncpg), что и остальной проект;
    # sync sa.create_engine() тянул бы psycopg2, которого нет среди
    # зависимостей (в проекте везде asyncpg, см. ADR).
    engine = make_engine(database_url)
    async with engine.connect() as conn:
        tables = set(
            await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        )
        assert {
            "bots", "bot_sessions", "contacts", "messages", "usage_events",
            "blocked_contacts", "tool_bindings", "products", "product_embeddings",
            "product_images", "documents",
        } <= tables

        bot_columns = set(
            await conn.run_sync(
                lambda sync_conn: [c["name"] for c in inspect(sync_conn).get_columns("bots")]
            )
        )
        assert bot_columns == {
            "id",
            "name",
            "enabled",
            "system_prompt",
            "image_prompt",
            "pdf_prompt",
            "timezone",
            "settings",
            "created_at",
        }

        session_columns = set(
            await conn.run_sync(
                lambda sync_conn: [
                    c["name"] for c in inspect(sync_conn).get_columns("bot_sessions")
                ]
            )
        )
        assert session_columns == {
            "bot_id",
            "auth_state",
            "phone",
            "linked_at",
            "last_seen",
        }
    await engine.dispose()
