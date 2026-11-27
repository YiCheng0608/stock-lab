"""Add the quarterly report filing table.

Revision ID: 0046_report_filings
Revises: 0040_premarket_ai

``financial_report_filings`` keeps one row per file of a company's quarterly
report on the TWSE e-book page ``t57sb01`` (電子資料查詢作業): the report kind,
the file, its size, its upload time (Taipei) and the page's correction cell
(Issue #1100).  Only the research database is written
(``worker.report_filings``); the production database gets the empty table, so
both keep one schema.  Additive: no existing row is read or changed.  The
downgrade drops the table and its rows; ``filings write`` rebuilds them from
the stored raw.
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

revision = "0046_report_filings"
down_revision = "0040_premarket_ai"
branch_labels = None
depends_on = None

TABLE = "financial_report_filings"


def upgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("period_end", Date, nullable=False),
        Column("fiscal_period", String(length=30), nullable=False),
        Column("report_kind", String(length=120), nullable=False),
        Column("uploaded_at", DateTime, nullable=False),
        Column("file_name", String(length=120), nullable=False),
        Column("file_size", Integer, nullable=False),
        Column("correction", String(length=500), nullable=False),
        Column("source", String(length=40), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("collected_at", DateTime, nullable=False),
        UniqueConstraint(
            "instrument_id", "file_name", name="uq_financial_report_filings"
        ),
    )
    for column in ("instrument_id", "period_end", "raw_payload_id"):
        op.create_index(f"ix_{TABLE}_{column}", TABLE, [column])


def downgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
