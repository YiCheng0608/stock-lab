"""Add the H2 list tables.

Revision ID: 0034_h2_lists
Revises: 0033_mainstream_lists

``h2_runs`` keeps one row per trading date and definition version, and
``h2_items`` one row per ranked stock (Issue #881).  The daily's ``h2_list``
step writes them (``app.h2_list``); ``/api/h2`` reads them.  Additive: no
existing row is read or changed.  The downgrade drops the two tables; every
list is computed again from the stored bars by the step.
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

revision = "0034_h2_lists"
down_revision = "0033_mainstream_lists"
branch_labels = None
depends_on = None

ITEM_INDEXES = ("h2_run_id", "trading_date", "instrument_id")


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "h2_runs" not in tables:
        op.create_table(
            "h2_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("definitions_sha256", String(length=64), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("universe_count", Integer, nullable=False),
            Column("item_count", Integer, nullable=False),
            Column("config_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint("trading_date", "version", name="uq_h2_run_day_version"),
        )
        op.create_index("ix_h2_runs_trading_date", "h2_runs", ["trading_date"])
    if "h2_items" not in tables:
        op.create_table(
            "h2_items",
            Column("id", Integer, primary_key=True),
            Column("h2_run_id", Integer, ForeignKey("h2_runs.id"), nullable=False),
            Column("trading_date", Date, nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("version", String(length=40), nullable=False),
            Column("rank", Integer, nullable=False),
            Column("high_gap_240", Float, nullable=True),
            Column("close", Float, nullable=False),
            UniqueConstraint(
                "trading_date",
                "instrument_id",
                "version",
                name="uq_h2_item_day_version",
            ),
        )
        for column in ITEM_INDEXES:
            op.create_index(f"ix_h2_items_{column}", "h2_items", [column])


def downgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "h2_items" in tables:
        for column in ITEM_INDEXES:
            op.drop_index(f"ix_h2_items_{column}", table_name="h2_items")
        op.drop_table("h2_items")
    if "h2_runs" in tables:
        op.drop_index("ix_h2_runs_trading_date", table_name="h2_runs")
        op.drop_table("h2_runs")
