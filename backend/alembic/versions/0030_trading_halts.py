"""Add the official trading halt table.

Revision ID: 0030_trading_halts
Revises: 0029_market_bar_ohlc_nullable

``trading_halts`` keeps one row per security and resumption: the interval in
which an exchange stopped trading the security for a capital reduction, from
the TWSE ``TWTAUU`` and TPEx ``revivt`` tables, with the source row and a link
to the raw payload (Issue #582).  ``worker.trading_halts`` writes it (collect
and ``worker.cli trading-halts``); coverage and the stock page read it to tell
a stopped session from missing data.  Additive and forward-only: no existing
row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0030_trading_halts"
down_revision = "0029_market_bar_ohlc_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("trading_halts"):
        return
    op.create_table(
        "trading_halts",
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("exchange", String(length=20), nullable=False),
        Column("halt_start", Date, nullable=False),
        Column("resume_date", Date, nullable=False),
        Column("last_trade_date", Date, nullable=True),
        Column("reason", String(length=40), nullable=False),
        Column("reason_detail", String(length=100), nullable=True),
        Column("source", String(length=40), nullable=False),
        Column("endpoint", String(length=500), nullable=False),
        Column("data_as_of", String(length=40), nullable=False),
        Column("collected_at", DateTime, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("details_json", JSON, nullable=False),
        UniqueConstraint(
            "instrument_id", "source", "resume_date", name="uq_trading_halt"
        ),
    )
    op.create_index("ix_trading_halts_halt_start", "trading_halts", ["halt_start"])
    op.create_index("ix_trading_halts_resume_date", "trading_halts", ["resume_date"])
    op.create_index(
        "ix_trading_halts_raw_payload_id", "trading_halts", ["raw_payload_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The trading halt migration is forward-only to preserve collected rows"
    )
