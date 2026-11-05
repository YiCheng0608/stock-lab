"""Store the action tiers and the news projection's fingerprint ahead of the GETs.

Revision ID: 0026_projection_snapshots
Revises: 0025_no_trade_days

Issue #476: the dashboard and the action list read a day's action tiers from
``action_tier_snapshots`` (written after the daily's strategy_levels step and
by ``worker.cli action-tiers``), and the news GETs project the official events
only when the fingerprint in ``news_projection_state`` no longer matches.
``events.updated_at`` lets that fingerprint see an event corrected in place;
existing rows take their ``collected_at``.  Additive and forward-only: the
only existing rows written are that one column of ``events``.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0026_projection_snapshots"
down_revision = "0025_no_trade_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    # As 0021 does: 0001 creates every model table, so only a partial schema
    # (the old-revision fixtures) lacks events.
    if inspector.has_table("events"):
        columns = {column["name"] for column in inspector.get_columns("events")}
        if "updated_at" not in columns:
            op.add_column("events", Column("updated_at", DateTime, nullable=True))
        bind.exec_driver_sql(
            "UPDATE events SET updated_at = collected_at WHERE updated_at IS NULL"
        )
    if not inspector.has_table("news_projection_state"):
        op.create_table(
            "news_projection_state",
            Column("key", String(length=40), primary_key=True),
            Column("fingerprint", String(length=64), nullable=False),
            Column("basis_json", JSON, nullable=False),
            Column("projected_at", DateTime, nullable=False),
        )
    if not inspector.has_table("action_tier_snapshots"):
        op.create_table(
            "action_tier_snapshots",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("store_version", String(length=40), nullable=False),
            Column("fingerprint", String(length=64), nullable=False),
            Column("basis_json", JSON, nullable=False),
            Column("rows_json", JSON, nullable=False),
            Column("row_count", Integer, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date", "store_version", name="uq_action_tier_snapshot_day"
            ),
        )
        op.create_index(
            "ix_action_tier_snapshots_trading_date",
            "action_tier_snapshots",
            ["trading_date"],
        )


def downgrade() -> None:
    raise RuntimeError("The projection snapshot migration is forward-only")
