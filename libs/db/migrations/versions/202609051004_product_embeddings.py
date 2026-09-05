"""product_embeddings

Revision ID: 202609051004
Revises: 202609051003
Create Date: 2026-09-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "202609051004"
down_revision: str | None = "202609051003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "product_embeddings",
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(1536), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("product_embeddings")
    # Расширение не откатываем — может использоваться другими объектами схемы.
