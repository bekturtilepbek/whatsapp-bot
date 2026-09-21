"""product_media rename

Revision ID: 202609221001
Revises: 202609121001
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202609221001"
down_revision: str | None = "202609121001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Чистое переименование — колонки не меняются (mime_type уже был
    # generic), storage_key не содержит слова "photo", данные не трогаются.
    # FEATURES.md 4.4/6.8: поле перестаёт быть строго фото, добавляется
    # поддержка видео (video/mp4) с тем же диспетчером по mime_type, что
    # уже есть у documents (4.9).
    op.rename_table("product_images", "product_media")
    op.execute(
        "ALTER TABLE product_media "
        "RENAME CONSTRAINT uq_product_images_product_position "
        "TO uq_product_media_product_position"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE product_media "
        "RENAME CONSTRAINT uq_product_media_product_position "
        "TO uq_product_images_product_position"
    )
    op.rename_table("product_media", "product_images")
