"""bots.image_prompt

Revision ID: 202609041001
Revises: 202609031001
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609041001"
down_revision: str | None = "202609031001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("image_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "image_prompt")
