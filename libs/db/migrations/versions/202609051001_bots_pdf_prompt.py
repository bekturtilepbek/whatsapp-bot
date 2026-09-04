"""bots.pdf_prompt

Revision ID: 202609051001
Revises: 202609041003
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609051001"
down_revision: str | None = "202609041003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("pdf_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "pdf_prompt")
