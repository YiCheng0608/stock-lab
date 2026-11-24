"""Add the theme cluster tables.

Revision ID: 0036_theme_clusters
Revises: 0035_strategy_lists

``theme_cluster_runs`` keeps one row per trading date and cluster version,
and ``theme_cluster_members`` one row per stock of a cluster (Issue #1018).
The daily's ``theme_discovery`` step writes them (``app.theme_clusters``).
Additive: no existing row is read or changed.  The downgrade drops the two
tables and the clusters in them; an older date is computed again with
``worker.cli theme-discovery --date`` (docs/ops/CLI.md).
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

revision = "0036_theme_clusters"
down_revision = "0035_strategy_lists"
branch_labels = None
depends_on = None

MEMBER_INDEXES = ("theme_cluster_run_id", "trading_date", "instrument_id")


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "theme_cluster_runs" not in tables:
        op.create_table(
            "theme_cluster_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("screened_count", Integer, nullable=False),
            Column("cluster_count", Integer, nullable=False),
            Column("config_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date", "version", name="uq_theme_cluster_run_day_version"
            ),
        )
        op.create_index(
            "ix_theme_cluster_runs_trading_date",
            "theme_cluster_runs",
            ["trading_date"],
        )
    if "theme_cluster_members" not in tables:
        op.create_table(
            "theme_cluster_members",
            Column("id", Integer, primary_key=True),
            Column(
                "theme_cluster_run_id",
                Integer,
                ForeignKey("theme_cluster_runs.id"),
                nullable=False,
            ),
            Column("trading_date", Date, nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("version", String(length=40), nullable=False),
            Column("cluster_no", Integer, nullable=False),
            Column("cluster_size", Integer, nullable=False),
            Column("cluster_mean_corr", Float, nullable=False),
            Column("member_mean_corr", Float, nullable=False),
            Column("excess_return_20d", Float, nullable=False),
            Column("amount_ratio_5_20", Float, nullable=False),
            Column("average_lots_20d", Float, nullable=False),
            UniqueConstraint(
                "trading_date",
                "instrument_id",
                "version",
                name="uq_theme_cluster_member_day_version",
            ),
        )
        for column in MEMBER_INDEXES:
            op.create_index(
                f"ix_theme_cluster_members_{column}",
                "theme_cluster_members",
                [column],
            )


def downgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "theme_cluster_members" in tables:
        for column in MEMBER_INDEXES:
            op.drop_index(
                f"ix_theme_cluster_members_{column}",
                table_name="theme_cluster_members",
            )
        op.drop_table("theme_cluster_members")
    if "theme_cluster_runs" in tables:
        op.drop_index(
            "ix_theme_cluster_runs_trading_date", table_name="theme_cluster_runs"
        )
        op.drop_table("theme_cluster_runs")
