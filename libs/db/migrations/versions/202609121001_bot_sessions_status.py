"""bot_sessions status

Revision ID: 202609121001
Revises: 202609111001
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609121001"
down_revision: str | None = "202609111001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL = ни разу не подключался. Простой text, не Postgres enum — набор
    # значений (connecting/qr/open/reconnecting/logged_out) валидируется на
    # уровне gateway/api, не в БД (тот же подход, что PromptKind).
    op.add_column("bot_sessions", sa.Column("status", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_sessions", "status")
