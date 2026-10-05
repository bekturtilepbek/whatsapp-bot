"""bots.lifecycle_status — служебный статус клиента-бота (FEATURES.md 6.22)

Revision ID: 202610061001
Revises: 202610051001
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202610061001"
down_revision: str | None = "202610051001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "lifecycle_status",
            sa.String(),
            nullable=False,
            server_default=sa.text("'in_development'"),
        ),
    )
    # Уже работающие боты (номер привязан) — "Подключён", остальные остаются
    # "В разработке" (server_default).
    op.execute(
        "UPDATE bots SET lifecycle_status = 'active' "
        "WHERE id IN (SELECT bot_id FROM bot_sessions WHERE phone IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_column("bots", "lifecycle_status")
