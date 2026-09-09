"""prompt_versions seq column

Revision ID: 202609090002
Revises: 202609090001
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609090002"
down_revision: str | None = "202609090001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_versions",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
    )
    op.create_unique_constraint("uq_prompt_versions_seq", "prompt_versions", ["seq"])


def downgrade() -> None:
    op.drop_constraint("uq_prompt_versions_seq", "prompt_versions", type_="unique")
    op.drop_column("prompt_versions", "seq")
