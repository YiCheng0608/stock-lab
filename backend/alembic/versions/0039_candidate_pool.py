"""Add the candidate pool tables.

Revision ID: 0039_candidate_pool
Revises: 0038_futures_night_bars

``candidate_pool_runs`` keeps one row per trading date, version and phase
(``evening`` / ``morning``), and ``candidate_pool_items`` one row per stock of
a run, selected or left out (Issue #1020).  The daily's ``candidate_pool``
step and the 08:20 ``preopen`` job write them (``app.candidate_pool``).
Additive: no existing row is read or changed.  The downgrade drops the two
tables and the pools in them; an evening is computed again with
``worker.cli candidate-pool --date`` (docs/ops/CLI.md), a morning cannot be
(its news window is gone).
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    inspect,
)

revision = "0039_candidate_pool"
down_revision = "0038_futures_night_bars"
branch_labels = None
depends_on = None

ITEM_INDEXES = ("run_id", "trading_date", "instrument_id")


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "candidate_pool_runs" not in tables:
        op.create_table(
            "candidate_pool_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("phase", String(length=20), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("cap", Integer, nullable=False),
            Column("union_count", Integer, nullable=False),
            Column("selected_count", Integer, nullable=False),
            Column("source_counts_json", JSON, nullable=False),
            Column("summary_json", JSON, nullable=False),
            Column("config_json", JSON, nullable=False),
            Column(
                "base_run_id",
                Integer,
                ForeignKey("candidate_pool_runs.id"),
                nullable=True,
            ),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date",
                "version",
                "phase",
                name="uq_candidate_pool_run_day_version_phase",
            ),
        )
        op.create_index(
            "ix_candidate_pool_runs_trading_date",
            "candidate_pool_runs",
            ["trading_date"],
        )
    if "candidate_pool_items" not in tables:
        op.create_table(
            "candidate_pool_items",
            Column("id", Integer, primary_key=True),
            Column(
                "run_id", Integer, ForeignKey("candidate_pool_runs.id"), nullable=False
            ),
            Column("trading_date", Date, nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("phase", String(length=20), nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("rank", Integer, nullable=True),
            Column("tier", Integer, nullable=False),
            Column("selected", Boolean, nullable=False),
            Column("reject_reason", String(length=20), nullable=True),
            Column("source_count", Integer, nullable=False),
            Column("sources_json", JSON, nullable=False),
            Column("themes_json", JSON, nullable=False),
            Column("features_json", JSON, nullable=False),
            UniqueConstraint(
                "run_id", "instrument_id", name="uq_candidate_pool_item_run_instrument"
            ),
        )
        for column in ITEM_INDEXES:
            op.create_index(
                f"ix_candidate_pool_items_{column}",
                "candidate_pool_items",
                [column],
            )


def downgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "candidate_pool_items" in tables:
        for column in ITEM_INDEXES:
            op.drop_index(
                f"ix_candidate_pool_items_{column}",
                table_name="candidate_pool_items",
            )
        op.drop_table("candidate_pool_items")
    if "candidate_pool_runs" in tables:
        op.drop_index(
            "ix_candidate_pool_runs_trading_date", table_name="candidate_pool_runs"
        )
        op.drop_table("candidate_pool_runs")
