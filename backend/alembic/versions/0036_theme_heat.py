"""Add the theme heat tables.

Revision ID: 0036_theme_heat
Revises: 0035_strategy_lists

``theme_heat_runs`` keeps one row per trading date and version, and
``theme_heat_scores`` one row per theme of the run (Issue #1017).  The daily's
``theme_heat`` step and ``worker.cli theme-heat`` write them
(``app.theme_heat``); ``/api/theme-heat`` reads them.  Additive: no existing
row is read or changed.  The downgrade drops the two tables; every day is
computed again from the stored bars, chips and news by the CLI.
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

revision = "0036_theme_heat"
down_revision = "0035_strategy_lists"
branch_labels = None
depends_on = None

SCORE_INDEXES = ("run_id", "trading_date", "group_id")


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "theme_heat_runs" not in tables:
        op.create_table(
            "theme_heat_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("theme_count", Integer, nullable=False),
            Column("ranked_count", Integer, nullable=False),
            Column("news_status", String(length=20), nullable=False),
            Column("news_through_id", Integer, nullable=True),
            Column("config_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date", "version", name="uq_theme_heat_run_day_version"
            ),
        )
        op.create_index(
            "ix_theme_heat_runs_trading_date", "theme_heat_runs", ["trading_date"]
        )
    if "theme_heat_scores" not in tables:
        op.create_table(
            "theme_heat_scores",
            Column("id", Integer, primary_key=True),
            Column("run_id", Integer, ForeignKey("theme_heat_runs.id"), nullable=False),
            Column("trading_date", Date, nullable=False),
            Column(
                "group_id",
                String(length=80),
                ForeignKey("theme_groups.id"),
                nullable=False,
            ),
            Column("version", String(length=40), nullable=False),
            Column("rank", Integer, nullable=True),
            Column("heat", Float, nullable=True),
            Column("quality", String(length=30), nullable=False),
            Column("member_count", Integer, nullable=False),
            Column("eligible_members", Integer, nullable=False),
            Column("available_weight", Float, nullable=True),
            Column("components_json", JSON, nullable=False),
            Column("details_json", JSON, nullable=False),
            UniqueConstraint(
                "trading_date", "group_id", "version", name="uq_theme_heat_day_group"
            ),
        )
        for column in SCORE_INDEXES:
            op.create_index(
                f"ix_theme_heat_scores_{column}", "theme_heat_scores", [column]
            )


def downgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "theme_heat_scores" in tables:
        for column in SCORE_INDEXES:
            op.drop_index(
                f"ix_theme_heat_scores_{column}", table_name="theme_heat_scores"
            )
        op.drop_table("theme_heat_scores")
    if "theme_heat_runs" in tables:
        op.drop_index("ix_theme_heat_runs_trading_date", table_name="theme_heat_runs")
        op.drop_table("theme_heat_runs")
