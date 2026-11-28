"""Add the index constituent change table.

Revision ID: 0052_index_constituent_changes
Revises: 0042_quarterly_statements

``index_constituent_changes`` keeps one addition, deletion or reserve of 臺灣50
(``TW50``) or 臺灣中型100 (``TWMC100``) as one Taiwan Index Plus technical notice
writes it (``source=tip_technical_notice``, Issue #1149): the date in the text
(``announced_date``), the date the site lists (``site_file_date``), the effective
date as written (NULL when deferred) and the free float.  ``instrument_id`` is NULL
when the research database has no such instrument.  Only the research database is
written (``worker.tip_notices``); the production database gets the empty table, so
both keep one schema.  Additive: no existing row is read or changed.  The downgrade
drops the table and its rows; ``valuation backfill --feed tip-notices --reapply``
rebuilds them from the stored raw.
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

revision = "0052_index_constituent_changes"
down_revision = "0042_quarterly_statements"
branch_labels = None
depends_on = None

TABLE = "index_constituent_changes"


def upgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        Column("id", Integer, primary_key=True),
        Column("index_code", String(length=20), nullable=False),
        Column("symbol", String(length=30), nullable=False),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=True),
        Column("name_in_source", String(length=80), nullable=False),
        Column("action", String(length=10), nullable=False),
        Column("review_kind", String(length=10), nullable=False),
        Column("announced_date", Date, nullable=False),
        Column("site_file_date", Date, nullable=True),
        Column("announced_time", String(length=8), nullable=True),
        Column("effective_date", Date, nullable=True),
        Column("free_float_pct", Float, nullable=True),
        Column("source", String(length=40), nullable=False),
        Column("source_doc_id", String(length=20), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("collected_at", DateTime, nullable=False),
        UniqueConstraint(
            "index_code",
            "symbol",
            "action",
            "announced_date",
            "source_doc_id",
            name="uq_index_constituent_changes",
        ),
    )
    op.create_index(
        "ix_index_constituent_changes_announced_date", TABLE, ["announced_date"]
    )
    op.create_index(
        "ix_index_constituent_changes_instrument_id", TABLE, ["instrument_id"]
    )
    op.create_index(
        "ix_index_constituent_changes_source_doc_id", TABLE, ["source_doc_id"]
    )
    op.create_index(
        "ix_index_constituent_changes_raw_payload_id", TABLE, ["raw_payload_id"]
    )


def downgrade() -> None:
    if inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
