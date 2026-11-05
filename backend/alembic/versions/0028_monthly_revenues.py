"""Add the monthly revenue table.

Revision ID: 0028_monthly_revenues
Revises: 0027_emerging_issuers

``monthly_revenues`` keeps one row per company and month: the month's revenue,
the same month a year earlier, the year-on-year change the source reported and
the year-to-date sum, in NT$ thousands, with the availability date, source and
raw payload (Issue #530).  collect writes the latest month from the OpenAPI
snapshots ``t187ap05_L``／``mopsfin_t187ap05_O``; ``worker.cli revenue backfill``
writes past months from the MOPS ``t21sc03`` pages.  The stock page reads it;
no strategy or score does.  Additive and forward-only: no existing row is read
or changed.
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

revision = "0028_monthly_revenues"
down_revision = "0027_emerging_issuers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("monthly_revenues"):
        return
    op.create_table(
        "monthly_revenues",
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("revenue_month", Date, nullable=False),
        Column("revenue", Float, nullable=True),
        Column("prior_year_revenue", Float, nullable=True),
        Column("yoy", Float, nullable=True),
        Column("cumulative_revenue", Float, nullable=True),
        Column("announcement_date", Date, nullable=False),
        Column("source", String(length=40), nullable=False),
        Column(
            "raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=False
        ),
        Column("data_json", JSON, nullable=False),
        Column("data_as_of", String(length=40), nullable=False),
        Column("collected_at", DateTime, nullable=False),
        UniqueConstraint(
            "instrument_id", "revenue_month", name="uq_monthly_revenue_month"
        ),
    )
    op.create_index(
        "ix_monthly_revenues_revenue_month", "monthly_revenues", ["revenue_month"]
    )
    op.create_index(
        "ix_monthly_revenues_raw_payload_id", "monthly_revenues", ["raw_payload_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The monthly revenue migration is forward-only to preserve collected rows"
    )
