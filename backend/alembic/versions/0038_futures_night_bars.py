"""Add the TX after-hours (夜盤) bar table.

Revision ID: 0038_futures_night_bars
Revises: 0037_theme_clusters

``futures_night_bars`` keeps one row per symbol and TAIFEX trading date of
the near-month after-hours session from the website download
``futDataDown`` (Issue #1040, ``worker.futures_history``).  Additive: no
existing row is read or changed, and ``market_bars`` (the regular-session
TX bars) is untouched.  The downgrade drops the table and its rows; they
are read again with ``worker.cli index-bars futures-night --month``
(docs/ops/CLI.md).
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

revision = "0038_futures_night_bars"
down_revision = "0037_theme_clusters"
branch_labels = None
depends_on = None

TABLE = "futures_night_bars"
INDEXES = ("trading_date", "raw_payload_id")


def upgrade() -> None:
    if TABLE in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLE,
        Column("id", Integer, primary_key=True),
        Column("symbol", String(length=20), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("contract_month", String(length=10), nullable=False),
        Column("open", Float, nullable=True),
        Column("high", Float, nullable=True),
        Column("low", Float, nullable=True),
        Column("close", Float, nullable=False),
        Column("change", Float, nullable=True),
        Column("volume", Integer, nullable=False),
        Column("price_reason", String(length=40), nullable=True),
        Column("source", String(length=120), nullable=False),
        Column("data_as_of", DateTime, nullable=False),
        Column("collected_at", DateTime, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        UniqueConstraint("symbol", "trading_date", name="uq_futures_night_bar_day"),
    )
    for column in INDEXES:
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])


def downgrade() -> None:
    if TABLE not in inspect(op.get_bind()).get_table_names():
        return
    for column in INDEXES:
        op.drop_index(f"ix_{TABLE}_{column}", table_name=TABLE)
    op.drop_table(TABLE)
