"""Add the trading calendar table.

Revision ID: 0020_trading_calendar
Revises: 0019_strategy_levels

``trading_calendar_days`` keeps TWSE's yearly official holiday schedule, one
row per listed date with its classification and a link to its raw payload,
written by the daily ``trading_calendar`` step and ``worker.cli
trading-calendar`` (Issue #294).  analyze reads it for a signal's earliest
execution date.  Additive and forward-only: no existing row is read or
changed.
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

revision = "0020_trading_calendar"
down_revision = "0019_strategy_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("trading_calendar_days"):
        return
    op.create_table(
        "trading_calendar_days",
        Column("id", Integer, primary_key=True),
        Column("exchange", String(length=20), nullable=False),
        Column("calendar_date", Date, nullable=False),
        Column("year", Integer, nullable=False),
        Column("kind", String(length=20), nullable=False),
        Column("name", String(length=200), nullable=False),
        Column("description", String(length=1000), nullable=False),
        Column("source", String(length=120), nullable=False),
        Column("collected_at", DateTime, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        UniqueConstraint("exchange", "calendar_date", name="uq_trading_calendar_day"),
    )
    op.create_index("ix_trading_calendar_days_year", "trading_calendar_days", ["year"])
    op.create_index(
        "ix_trading_calendar_days_raw_payload_id",
        "trading_calendar_days",
        ["raw_payload_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "The trading calendar migration is forward-only to preserve collected rows"
    )
