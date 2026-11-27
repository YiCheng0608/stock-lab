"""Add the official attention notice and disposal tables.

Revision ID: 0044_trading_notices
Revises: 0040_premarket_ai

``trading_attentions`` keeps each 公布注意有價證券 notice of TWSE
``announcement/notice`` and TPEx ``bulletin/attention``; ``trading_disposals`` each
處置 period of TWSE ``announcement/punish`` and TPEx ``bulletin/disposal`` (Issue
#1090).  Every row the exchanges print is kept, warrants and ETFs too, so
``instrument_id`` may be NULL; ``symbol`` is always there.  Each row names its
source, data date and raw payload.  Only the research database is written
(``worker.trading_notices``); the production database gets the two empty tables,
so both keep one schema.  Additive: no existing row is read or changed.  The
downgrade drops the two tables and their rows; ``trading-notices backfill
--reapply`` rebuilds them from the stored raw.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)

revision = "0044_trading_notices"
down_revision = "0040_premarket_ai"
branch_labels = None
depends_on = None


def _security() -> list[Column]:
    return [
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=True),
        Column("exchange", String(length=20), nullable=False),
        Column("symbol", String(length=30), nullable=False),
        Column("security_name", String(length=120), nullable=False),
    ]


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
    if "trading_attentions" not in tables:
        op.create_table(
            "trading_attentions",
            *_security(),
            Column("attention_date", Date, nullable=False),
            Column("clauses", String(length=60), nullable=True),
            Column("detail", Text, nullable=False),
            Column("close_price", Float, nullable=True),
            Column("pe_ratio", Float, nullable=True),
            Column("cumulative_count", Integer, nullable=True),
            *_provenance(),
            UniqueConstraint(
                "exchange",
                "symbol",
                "attention_date",
                "source",
                name="uq_trading_attentions",
            ),
        )
        for column in ("instrument_id", "attention_date", "raw_payload_id"):
            op.create_index(
                f"ix_trading_attentions_{column}", "trading_attentions", [column]
            )
    if "trading_disposals" not in tables:
        op.create_table(
            "trading_disposals",
            *_security(),
            Column("announced_date", Date, nullable=False),
            Column("start_date", Date, nullable=False),
            Column("end_date", Date, nullable=False),
            Column("measure", String(length=60), nullable=True),
            Column("reason", Text, nullable=True),
            Column("match_interval_minutes", Integer, nullable=True),
            Column("prepayment", Boolean, nullable=True),
            Column("detail", Text, nullable=True),
            Column("cumulative_count", Integer, nullable=True),
            *_provenance(),
            UniqueConstraint(
                "exchange",
                "symbol",
                "announced_date",
                "start_date",
                "source",
                name="uq_trading_disposals",
            ),
        )
        for column in (
            "instrument_id",
            "announced_date",
            "start_date",
            "raw_payload_id",
        ):
            op.create_index(
                f"ix_trading_disposals_{column}", "trading_disposals", [column]
            )


def downgrade() -> None:
    for table in ("trading_disposals", "trading_attentions"):
        if inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
