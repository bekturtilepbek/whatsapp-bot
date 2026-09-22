"""users role (superadmin/admin/prompter/client)

Revision ID: 202609221002
Revises: 202609221001
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609221002"
down_revision: str | None = "202609221001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(), nullable=False, server_default=sa.text("'client'")),
    )
    op.execute("UPDATE users SET role = 'superadmin' WHERE is_platform_owner = true")
    op.drop_column("users", "is_platform_owner")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_owner", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.execute("UPDATE users SET is_platform_owner = true WHERE role = 'superadmin'")
    op.drop_column("users", "role")
