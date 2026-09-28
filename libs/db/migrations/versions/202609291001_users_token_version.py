"""users.token_version — отзыв сессий при смене пароля

Revision ID: 202609291001
Revises: 202609221003
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609291001"
down_revision: str | None = "202609221003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default 0: у всех существующих пользователей версия 0, а токены
    # без claim "tv" тоже читаются как 0 — выкатка никого не разлогинивает.
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
