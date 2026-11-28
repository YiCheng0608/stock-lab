"""Add the insider holdings, pledges and transfer declaration tables.

Revision ID: 0048_insider_filings
Revises: 0042_quarterly_statements

``insider_holdings_monthly`` keeps one company's insider holdings of one month
from siis ``IRB110``, ``insider_pledges_monthly`` its insider pledges from siis
``IRB130``, and ``insider_transfer_declarations`` one row of MOPS ``t56sb21`` (an
insider's declaration before a transfer) (Issue #1133).  Each row names its
source, data date and raw payload.  Only the research database is written
(``worker.insider_backfill``); the production database gets the three empty
tables, so both keep one schema.  Additive: no existing row is read or changed.
The downgrade drops the three tables and their rows; ``insider backfill
--reapply`` rebuilds them from the stored raw.
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

revision = "0048_insider_filings"
down_revision = "0042_quarterly_statements"
branch_labels = None
depends_on = None

HOLDINGS = "insider_holdings_monthly"
PLEDGES = "insider_pledges_monthly"
TRANSFERS = "insider_transfer_declarations"


def _shares(*names: str) -> list[Column]:
    return [Column(name, Integer, nullable=True) for name in names]


def _provenance() -> list[Column]:
    return [
        Column("market", String(length=10), nullable=False),
        Column("source", String(length=40), nullable=False),
        Column("data_as_of", Date, nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
    ]


def upgrade() -> None:
    existing = inspect(op.get_bind())
    if not existing.has_table(HOLDINGS):
        op.create_table(
            HOLDINGS,
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("period_month", Date, nullable=False),
            *_shares(
                "shares_issued",
                "director_increase",
                "director_decrease",
                "director_held",
            ),
            Column("director_held_pct", Float, nullable=True),
            *_shares("manager_held", "major_holder_held"),
            *_provenance(),
            Column("collected_at", DateTime, nullable=False),
            UniqueConstraint(
                "instrument_id",
                "period_month",
                "source",
                name="uq_insider_holdings_monthly",
            ),
        )
        op.create_index(f"ix_{HOLDINGS}_period_month", HOLDINGS, ["period_month"])
        op.create_index(f"ix_{HOLDINGS}_raw_payload_id", HOLDINGS, ["raw_payload_id"])
    if not existing.has_table(PLEDGES):
        op.create_table(
            PLEDGES,
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("period_month", Date, nullable=False),
            *_shares(
                "director_held",
                "director_pledge_set",
                "director_pledge_released",
                "director_pledged",
            ),
            Column("director_pledged_pct", Float, nullable=True),
            *_shares("manager_held", "major_holder_held", "manager_major_pledged"),
            Column("manager_major_pledged_pct", Float, nullable=True),
            *_provenance(),
            Column("collected_at", DateTime, nullable=False),
            UniqueConstraint(
                "instrument_id",
                "period_month",
                "source",
                name="uq_insider_pledges_monthly",
            ),
        )
        op.create_index(f"ix_{PLEDGES}_period_month", PLEDGES, ["period_month"])
        op.create_index(f"ix_{PLEDGES}_raw_payload_id", PLEDGES, ["raw_payload_id"])
    if not existing.has_table(TRANSFERS):
        op.create_table(
            TRANSFERS,
            Column("id", Integer, primary_key=True),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("filed_date", Date, nullable=False),
            Column("role_raw", String(length=80), nullable=False),
            Column("insider_type", String(length=40), nullable=True),
            Column("relation", String(length=40), nullable=True),
            Column("via_trustee", Integer, nullable=False),
            Column("person_name", String(length=200), nullable=False),
            Column("transferee", String(length=400), nullable=True),
            Column("method_raw", String(length=200), nullable=False),
            Column("method_shares_raw", String(length=200), nullable=True),
            *_shares(
                "intraday_max_shares",
                "held_own",
                "held_trust",
                "planned_own",
                "planned_trust",
                "after_own",
                "after_trust",
            ),
            Column("period_start", Date, nullable=True),
            Column("period_end", Date, nullable=True),
            Column("unfinished_declared", Integer, nullable=True),
            Column("change_note", String(length=200), nullable=True),
            *_provenance(),
            Column("row_no", Integer, nullable=False),
            Column("collected_at", DateTime, nullable=False),
            UniqueConstraint(
                "raw_payload_id", "row_no", name="uq_insider_transfer_declarations"
            ),
        )
        op.create_index(f"ix_{TRANSFERS}_instrument_id", TRANSFERS, ["instrument_id"])
        op.create_index(f"ix_{TRANSFERS}_filed_date", TRANSFERS, ["filed_date"])
        op.create_index(f"ix_{TRANSFERS}_raw_payload_id", TRANSFERS, ["raw_payload_id"])


def downgrade() -> None:
    existing = inspect(op.get_bind())
    for table in (TRANSFERS, PLEDGES, HOLDINGS):
        if existing.has_table(table):
            op.drop_table(table)
