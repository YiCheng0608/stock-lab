"""Add the official daily index constituent table.

Revision ID: 0042_index_constituents
Revises: 0041_valuation_shares

``index_constituents_daily`` keeps one code of an index's official constituent
list of one session: TPEx ``indexInfo/r50`` (富櫃50, ``TPEX50``; Issue #1134).
Each row names its source, data date and raw payload; ``instrument_id`` is NULL
when the research database has no such instrument that day.  Only the research
database is written (``worker.valuation_backfill``); the production database gets
the empty table, so both keep one schema.  Additive: no existing row is read or
changed.  The downgrade drops the table and its rows; ``valuation backfill
--reapply`` rebuilds them from the stored raw.
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

revision = "0042_index_constituents"
down_revision = "0041_valuation_shares"
branch_labels = None
depends_on = None

TABLE = "index_constituents_daily"


def upgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        Column("id", Integer, primary_key=True),
        Column("index_code", String(length=20), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("symbol", String(length=30), nullable=False),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=True),
        Column("name_in_source", String(length=80), nullable=False),
        Column("source", String(length=40), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("collected_at", DateTime, nullable=False),
        UniqueConstraint(
            "index_code",
            "trading_date",
            "symbol",
            name="uq_index_constituents_daily",
        ),
    )
    op.create_index("ix_index_constituents_daily_trading_date", TABLE, ["trading_date"])
    op.create_index(
        "ix_index_constituents_daily_instrument_id", TABLE, ["instrument_id"]
    )
    op.create_index(
        "ix_index_constituents_daily_raw_payload_id", TABLE, ["raw_payload_id"]
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
