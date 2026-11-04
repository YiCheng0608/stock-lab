"""Add the official no-trade day table.

Revision ID: 0025_no_trade_days
Revises: 0024_ingestion_run_indexes

``no_trade_days`` keeps, per security and session, that the day's official
quote table (TWSE MI_INDEX, TPEx dailyQuotes) listed the security with every
price blank, with a link to the raw payload (Issue #454).  ``worker.no_trade_days``
writes it from stored raw only (collect and ``worker.cli no-trade-days``);
coverage reads it to tell an official no-trade day from missing data.
Additive and forward-only: no existing row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0025_no_trade_days"
down_revision = "0024_ingestion_run_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("no_trade_days"):
        return
    op.create_table(
        "no_trade_days",
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("source", String(length=40), nullable=False),
        Column("endpoint", String(length=500), nullable=False),
        Column("data_as_of", String(length=40), nullable=False),
        Column("collected_at", DateTime, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        UniqueConstraint("instrument_id", "trading_date", name="uq_no_trade_day"),
    )
    op.create_index("ix_no_trade_days_trading_date", "no_trade_days", ["trading_date"])
    op.create_index(
        "ix_no_trade_days_raw_payload_id", "no_trade_days", ["raw_payload_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The no-trade day migration is forward-only to preserve collected rows"
    )
