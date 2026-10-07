"""contacts.temperature / summary / summary_updated_at (FEATURES.md 6.13)

Revision ID: 202610061002
Revises: 202610061001
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610061002"
down_revision: str | None = "202610061001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Все три NULL: "ещё не оценён" — осознанное состояние (в V1 дефолтом было
    # "холодный", что смешивало "холодный" и "не оценивали").
    op.add_column("contacts", sa.Column("temperature", sa.String(), nullable=True))
    op.add_column("contacts", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "contacts", sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("contacts", "summary_updated_at")
    op.drop_column("contacts", "summary")
    op.drop_column("contacts", "temperature")
