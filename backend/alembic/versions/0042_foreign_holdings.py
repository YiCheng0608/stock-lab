"""Add the official daily foreign holding table.

Revision ID: 0042_foreign_holdings
Revises: 0041_valuation_shares

``foreign_holdings_daily`` keeps one security's foreign holding of one session:
shares issued, shares held, % held, available shares, the legal limits, the TWSE
change reason and last filing date, the TPEx note, from TWSE ``MI_QFIIS`` (the raw
stored by ``twse-shares``) or TPEx ``insti/qfii`` (Issue #1121).  Each row names
its source, data date and raw payload.  Only the research database is written
(``worker.valuation_backfill``); the production database gets the empty table, so
both keep one schema.  Additive: no existing row is read or changed.  The downgrade
drops the table and its rows; ``valuation backfill --reapply`` rebuilds them from
the stored raw.
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

revision = "0042_foreign_holdings"
down_revision = "0041_valuation_shares"
branch_labels = None
depends_on = None

TABLE = "foreign_holdings_daily"


def upgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("shares_issued", Integer, nullable=True),
        Column("foreign_shares_held", Integer, nullable=True),
        Column("foreign_held_pct", Float, nullable=True),
        Column("foreign_available_shares", Integer, nullable=True),
        Column("foreign_limit_pct", Float, nullable=True),
        Column("mainland_limit_pct", Float, nullable=True),
        Column("change_reason", String(length=20), nullable=True),
        Column("last_filing_date", Date, nullable=True),
        Column("note", String(length=40), nullable=True),
        Column("source", String(length=40), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("collected_at", DateTime, nullable=False),
        UniqueConstraint(
            "instrument_id",
            "trading_date",
            "source",
            name="uq_foreign_holdings_daily",
        ),
    )
    op.create_index("ix_foreign_holdings_daily_trading_date", TABLE, ["trading_date"])
    op.create_index(
        "ix_foreign_holdings_daily_raw_payload_id", TABLE, ["raw_payload_id"]
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
