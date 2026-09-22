"""bots.responsible_user_id (prompter, отдельно от bot_access)

Revision ID: 202609221003
Revises: 202609221002
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "202609221003"
down_revision: str | None = "202609221002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_bots_responsible_user_id",
        "bots",
        "users",
        ["responsible_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_bots_responsible_user_id", "bots", type_="foreignkey")
    op.drop_column("bots", "responsible_user_id")
