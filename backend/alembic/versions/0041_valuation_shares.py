"""Add the official daily valuation and issued-share tables.

Revision ID: 0041_valuation_shares
Revises: 0040_premarket_ai

``valuation_daily`` keeps one security's P/B, P/E, dividend yield and statement
period of one session from TWSE ``BWIBBU_d`` or TPEx ``peQryDate``;
``shares_outstanding_daily`` its issued shares from TWSE ``MI_QFIIS`` or the TPEx
daily quote table (Issue #1075).  Each row names its source, data date and raw
payload.  Only the research database is written (``worker.valuation_backfill``);
the production database gets the two empty tables, so both keep one schema.
Additive: no existing row is read or changed.  The downgrade drops the two tables
and their rows; they are rebuilt by ``valuation backfill`` (``--reapply`` reads the
stored raw).
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

revision = "0041_valuation_shares"
down_revision = "0040_premarket_ai"
branch_labels = None
depends_on = None


def _provenance() -> list[Column]:
    return [
        Column("source", String(length=40), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("collected_at", DateTime, nullable=False),
    ]


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "valuation_daily" not in tables:
        op.create_table(
            "valuation_daily",
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("trading_date", Date, nullable=False),
            Column("pb_ratio", Float, nullable=True),
            Column("pe_ratio", Float, nullable=True),
            Column("dividend_yield", Float, nullable=True),
            Column("report_period", String(length=10), nullable=True),
            *_provenance(),
            UniqueConstraint(
                "instrument_id", "trading_date", "source", name="uq_valuation_daily"
            ),
        )
        op.create_index(
            "ix_valuation_daily_trading_date", "valuation_daily", ["trading_date"]
        )
        op.create_index(
            "ix_valuation_daily_raw_payload_id", "valuation_daily", ["raw_payload_id"]
        )
    if "shares_outstanding_daily" not in tables:
        op.create_table(
            "shares_outstanding_daily",
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("trading_date", Date, nullable=False),
            Column("shares_issued", Integer, nullable=True),
            *_provenance(),
            UniqueConstraint(
                "instrument_id",
                "trading_date",
                "source",
                name="uq_shares_outstanding_daily",
            ),
        )
        op.create_index(
            "ix_shares_outstanding_daily_trading_date",
            "shares_outstanding_daily",
            ["trading_date"],
        )
        op.create_index(
            "ix_shares_outstanding_daily_raw_payload_id",
            "shares_outstanding_daily",
            ["raw_payload_id"],
        )


def downgrade() -> None:
    for table in ("shares_outstanding_daily", "valuation_daily"):
        if inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
