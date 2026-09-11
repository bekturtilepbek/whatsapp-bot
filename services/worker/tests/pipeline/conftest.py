"""Общая инфраструктура testcontainers-Postgres для тестов пайплайна
worker — было продублировано байт-в-байт в 11 файлах (`database_url`,
`session_factory`, проверка доступности Docker), найдено ретро-ревью
4.8/4.9 (2026-09-08), не закрыто в момент находки.

`database_url`/`session_factory` — обычные pytest-фикстуры, pytest
подхватывает их отсюда автоматически в любом тесте этой директории по
имени параметра, импортировать не нужно. `docker_available()` — плюс,
т.к. `pytest.mark.skipif(...)` вычисляется на сборке, а не через
фикстуру (фикстуры недоступны в момент вычисления марки) — импортируется
явно (`from pipeline.conftest import docker_available`) в каждом файле,
который ставит `pytestmark`.

`testcontainers.postgres` импортируется ЛЕНИВО, внутри `database_url` —
не на уровне модуля: в этой же директории есть тесты БЕЗ Postgres
(test_batching.py, test_dedup.py, test_filters.py, test_lock.py,
test_media.py, test_pdf_extract.py, test_tool_loop.py) — conftest.py
подгружается для ВСЕХ тестов директории, и безусловный импорт здесь
сломал бы их сборку в окружении без testcontainers (сейчас у них такой
зависимости нет вообще, сохраняем это).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from db.engine import make_engine, make_session_factory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = REPO_ROOT / "libs" / "db" / "alembic.ini"


def docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def database_url() -> AsyncIterator[str]:
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg17", driver="psycopg2") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
        )
        yield url


@pytest.fixture
def session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(database_url)
    return make_session_factory(engine)
