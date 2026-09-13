"""Add product theme labels and the auditable official-news projection.

Revision ID: 0004_product_news_themes
Revises: 0003_backtest_run_metadata

The migration is forward-only.  Existing Event and raw-payload rows are
preserved; NewsItem rows are populated by the idempotent product projection
when the application reads or refreshes the official feed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, inspect


revision = "0004_product_news_themes"
down_revision = "0003_backtest_run_metadata"
branch_labels = None
depends_on = None


def _add_theme_columns(bind) -> None:
    inspector = inspect(bind)
    if not inspector.has_table("theme_groups"):
        return
    existing = {column["name"] for column in inspector.get_columns("theme_groups")}
    columns = (
        ("display_name_zh", "VARCHAR(120)"),
        ("display_description_zh", "TEXT"),
        ("display_category", "VARCHAR(40)"),
        ("name_source", "VARCHAR(500)"),
        ("name_status", "VARCHAR(30) NOT NULL DEFAULT 'pending'"),
    )
    for name, definition in columns:
        if name not in existing:
            bind.exec_driver_sql(f'ALTER TABLE "theme_groups" ADD COLUMN "{name}" {definition}')


def _create_news_table(bind) -> None:
    if inspect(bind).has_table("news_items"):
        return
    op.create_table(
        "news_items",
        Column("id", Integer, primary_key=True),
        Column("canonical_key", String(length=300), nullable=False),
        Column("dedupe_cluster_id", String(length=160), nullable=True),
        Column("category", String(length=30), nullable=False, server_default="taiwan"),
        Column("source_kind", String(length=40), nullable=False, server_default="official_disclosure"),
        Column("source_name", String(length=120), nullable=False),
        Column("source_url", String(length=800), nullable=True),
        Column("source_url_kind", String(length=20), nullable=False, server_default="none"),
        Column("source_item_id", String(length=180), nullable=True),
        Column("title", String(length=300), nullable=False),
        Column("summary", Text, nullable=True),
        Column("language", String(length=20), nullable=False, server_default="zh-Hant"),
        Column("published_at", DateTime, nullable=True),
        Column("event_at", DateTime, nullable=True),
        Column("collected_at", DateTime, nullable=False),
        Column("symbols_json", JSON, nullable=False, server_default="[]"),
        Column("theme_ids_json", JSON, nullable=False, server_default="[]"),
        Column("impact_scope", String(length=30), nullable=False, server_default="instrument"),
        Column("impact_direction", String(length=30), nullable=False, server_default="unknown"),
        Column("impact_rationale", Text, nullable=True),
        Column("impact_method", String(length=120), nullable=False, server_default="default_unknown"),
        Column("confidence", String(length=20), nullable=False, server_default="unknown"),
        Column("raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=True),
        Column("event_id", Integer, ForeignKey("events.id"), nullable=True),
        Column("content_hash", String(length=64), nullable=True),
        Column("status", String(length=30), nullable=False, server_default="active"),
        Column("supersedes_id", Integer, ForeignKey("news_items.id"), nullable=True),
        UniqueConstraint("canonical_key", name="uq_news_canonical_key"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    _add_theme_columns(bind)
    _create_news_table(bind)
    # The table-level unique constraint is created separately so this revision
    # remains safe when a partially applied desktop migration already created
    # the table.
    inspector = inspect(bind)
    unique_names = {
        constraint.get("name")
        for constraint in inspector.get_unique_constraints("news_items")
    } if inspector.has_table("news_items") else set()
    if "uq_news_canonical_key" not in unique_names:
        bind.exec_driver_sql(
            'CREATE UNIQUE INDEX IF NOT EXISTS "uq_news_canonical_key" '
            'ON "news_items" ("canonical_key")'
        )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_collected_id" '
        'ON "news_items" ("collected_at", "id")'
    )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_published" ON "news_items" ("published_at")'
    )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_category" ON "news_items" ("category")'
    )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_source_kind" ON "news_items" ("source_kind")'
    )
    bind.exec_driver_sql(
        'CREATE INDEX IF NOT EXISTS "ix_news_event" ON "news_items" ("event_id")'
    )


def downgrade() -> None:
    raise RuntimeError("The product news/theme migration is forward-only")
