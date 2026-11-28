"""Add the official daily securities lending and day trade tables.

Revision ID: 0043_sbl_day_trade
Revises: 0053_ai_list_scores

``securities_lending_daily`` keeps one security's 借券賣出 (當日賣出、還券、餘額)
of one session from TWSE ``TWT93U`` or TPEx ``margin/sbl``; ``day_trade_daily``
its 當日沖銷交易 shares and values from TWSE ``TWTB4U`` or TPEx ``intraday/stat``
(Issue #1089).  Each row names its source, data date and raw payload.  Only the
research database is written (``worker.sbl_daytrade_backfill``); the production
database gets the two empty tables, so both keep one schema.  Additive: no
existing row is read or changed.  The downgrade drops the two tables and their
rows; they are rebuilt by ``sbl-daytrade backfill --reapply`` from the stored raw.
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

revision = "0043_sbl_day_trade"
down_revision = "0053_ai_list_scores"
branch_labels = None
depends_on = None

TABLES = ("securities_lending_daily", "day_trade_daily")


def _provenance() -> list[Column]:
    return [
        Column("source", String(length=40), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("collected_at", DateTime, nullable=False),
    ]


def _indexes(table: str) -> None:
    op.create_index(f"ix_{table}_trading_date", table, ["trading_date"])
    op.create_index(f"ix_{table}_raw_payload_id", table, ["raw_payload_id"])


def upgrade() -> None:
    tables = set(inspect(op.get_bind()).get_table_names())
    if "securities_lending_daily" not in tables:
        op.create_table(
            "securities_lending_daily",
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("trading_date", Date, nullable=False),
            Column("sbl_sell_shares", Integer, nullable=True),
            Column("sbl_return_shares", Integer, nullable=True),
            Column("sbl_balance_shares", Integer, nullable=True),
            Column("note", String(length=20), nullable=True),
            *_provenance(),
            UniqueConstraint(
                "instrument_id",
                "trading_date",
                "source",
                name="uq_securities_lending_daily",
            ),
        )
        _indexes("securities_lending_daily")
    if "day_trade_daily" not in tables:
        op.create_table(
            "day_trade_daily",
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("trading_date", Date, nullable=False),
            Column("day_trade_shares", Integer, nullable=True),
            Column("day_trade_buy_value", Float, nullable=True),
            Column("day_trade_sell_value", Float, nullable=True),
            Column("sell_first_suspended", String(length=20), nullable=True),
            *_provenance(),
            UniqueConstraint(
                "instrument_id", "trading_date", "source", name="uq_day_trade_daily"
            ),
        )
        _indexes("day_trade_daily")


def downgrade() -> None:
    for table in reversed(TABLES):
        if inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
