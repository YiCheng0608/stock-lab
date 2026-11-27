"""Add the quarterly balance sheet and cash flow table.

Revision ID: 0042_quarterly_statements
Revises: 0040_premarket_ai

``quarterly_statements`` keeps one company's main balance sheet items, operating
cash flow, capital expenditure, gross profit and operating income of one quarter,
read from the MOPS quarterly XBRL archive (``source=mops_tifrs_zip``, Issue #1083).
Balance sheet items are quarter-end values, the others year-to-date as filed; all
in thousand NTD.  Each row names its raw payload (the archive) and its data date.
Only the research database is written (``worker.quarterly_statements``); the
production database gets the empty table, so both keep one schema.  Additive: no
existing row is read or changed.  The downgrade drops the table and its rows; they
are rebuilt by ``fundamentals statements-apply`` from the stored archives.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
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

revision = "0042_quarterly_statements"
down_revision = "0040_premarket_ai"
branch_labels = None
depends_on = None

AMOUNTS = (
    "total_assets",
    "total_liabilities",
    "equity_parent",
    "equity_total",
    "current_assets",
    "current_liabilities",
    "cash",
    "receivables",
    "inventories",
    "share_capital_common",
    "share_capital_total",
    "cfo_ytd",
    "capex_ytd",
    "gross_profit_ytd",
    "operating_income_ytd",
)


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("quarterly_statements"):
        return
    op.create_table(
        "quarterly_statements",
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("period_end", Date, nullable=False),
        Column("fiscal_period", String(length=10), nullable=False),
        Column("announcement_date", Date, nullable=False),
        *(Column(name, Float, nullable=True) for name in AMOUNTS),
        Column("source", String(length=40), nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("data_as_of", Date, nullable=False),
        Column("collected_at", DateTime, nullable=False),
        Column("data_json", JSON, nullable=False),
        UniqueConstraint(
            "instrument_id",
            "period_end",
            "fiscal_period",
            name="uq_quarterly_statements_period",
        ),
    )
    op.create_index(
        "ix_quarterly_statements_period_end", "quarterly_statements", ["period_end"]
    )
    op.create_index(
        "ix_quarterly_statements_raw_payload_id",
        "quarterly_statements",
        ["raw_payload_id"],
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table("quarterly_statements"):
        op.drop_table("quarterly_statements")
