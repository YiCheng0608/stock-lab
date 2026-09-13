"""Add auditable news time fields for display-time sorting.

The revision is additive.  Existing NewsItem/Event/raw rows are preserved;
the idempotent projection fills the new derived fields when an official Event
is reconciled.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


revision = "0005_news_temporal_contract"
down_revision = "0004_product_news_themes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("news_items"):
        return
    existing = {column["name"] for column in inspector.get_columns("news_items")}
    columns = (
        ("event_date", "DATE"),
        ("time_basis", "VARCHAR(20) NOT NULL DEFAULT 'unverified'"),
        ("time_precision", "VARCHAR(20) NOT NULL DEFAULT 'none'"),
        ("time_consistency", "VARCHAR(20) NOT NULL DEFAULT 'verified'"),
        ("display_time", "DATETIME"),
    )
    for name, definition in columns:
        if name not in existing:
            bind.exec_driver_sql(f'ALTER TABLE "news_items" ADD COLUMN "{name}" {definition}')
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_display_id" '
        'ON "news_items" ("display_time", "id")'
    )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_event_date" '
        'ON "news_items" ("event_date")'
    )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_time_consistency" '
        'ON "news_items" ("time_consistency")'
    )


def downgrade() -> None:
    raise RuntimeError("The news temporal contract migration is forward-only")
