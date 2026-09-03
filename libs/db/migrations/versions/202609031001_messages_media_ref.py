"""messages.media_ref

Revision ID: 202609031001
Revises: 202609021001
Create Date: 2026-09-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609031001"
down_revision: str | None = "202609021001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("media_ref", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "media_ref")
