"""prompt_versions

Revision ID: 202609090001
Revises: 202609080001
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609090001"
down_revision: str | None = "202609080001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "bot_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("author", sa.String(), nullable=False, server_default=sa.text("'admin'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_prompt_versions_bot_kind_created",
        "prompt_versions",
        ["bot_id", "kind", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_versions_bot_kind_created", table_name="prompt_versions")
    op.drop_table("prompt_versions")
