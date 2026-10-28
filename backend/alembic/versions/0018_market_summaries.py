"""Add the market summary table.

Revision ID: 0018_market_summaries
Revises: 0017_tracking_plans

``market_summaries`` keeps one official market summary per exchange and
session (index close and change, turnover, advancers and decliners), written
by collect and by ``worker.cli market-summary`` with a link to its raw
payload (Issue #275).  Additive and forward-only: no existing row is read or
changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0018_market_summaries"
down_revision = "0017_tracking_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("market_summaries"):
        return
    op.create_table(
        "market_summaries",
        Column("id", Integer, primary_key=True),
        Column("exchange", String(length=20), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("index_name", String(length=60), nullable=False),
        Column("index_close", Float, nullable=True),
        Column("index_change", Float, nullable=True),
        Column("index_change_pct", Float, nullable=True),
        Column("change_pct_method", String(length=20), nullable=False),
        Column("turnover", Integer, nullable=True),
        Column("turnover_scope", String(length=40), nullable=False),
        Column("advancers", Integer, nullable=True),
        Column("decliners", Integer, nullable=True),
        Column("unchanged", Integer, nullable=True),
        Column("limit_up", Integer, nullable=True),
        Column("limit_down", Integer, nullable=True),
        Column("unmatched", Integer, nullable=True),
        Column("not_comparable", Integer, nullable=True),
        Column("breadth_scope", String(length=40), nullable=False),
        Column("source", String(length=120), nullable=False),
        Column("data_as_of", String(length=80), nullable=True),
        Column("collected_at", DateTime, nullable=False),
        Column("raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=True),
        UniqueConstraint("exchange", "trading_date", name="uq_market_summary_day"),
    )
    op.create_index(
        "ix_market_summaries_trading_date", "market_summaries", ["trading_date"]
    )
    op.create_index(
        "ix_market_summaries_raw_payload_id", "market_summaries", ["raw_payload_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The market summary migration is forward-only to preserve collected rows"
    )
