"""messages.seq — монотонный порядок вставки для истории диалога

Revision ID: 202609041003
Revises: 202609041002
Create Date: 2026-09-04

ts не годится как единственный ключ сортировки истории: insert_outgoing
пишет datetime.now(UTC) с полной точностью, insert_incoming — ts из события
(у реального WhatsApp — целые секунды); при вставках впритык друг к другу
более грубый ts может оказаться меньше уже сохранённого точного, хотя
запись сделана позже — сортировка по ts переставляет историю местами.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "202609041003"
down_revision: str | None = "202609041002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False, unique=True),
    )
    op.drop_index("ix_messages_contact_id_ts", table_name="messages")
    op.create_index("ix_messages_contact_id_seq", "messages", ["contact_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_messages_contact_id_seq", table_name="messages")
    op.create_index("ix_messages_contact_id_ts", "messages", ["contact_id", "ts"])
    op.drop_column("messages", "seq")
