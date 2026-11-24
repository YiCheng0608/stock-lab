"""Move the H2 lists into the common strategy list tables.

Revision ID: 0035_strategy_lists
Revises: 0034_h2_lists

``strategy_list_runs`` keeps one row per trading date, strategy and definition
version, and ``strategy_list_items`` one row per ranked stock with the
strategy's own values in ``values_json`` (Issue #1014, ``app.strategy_lists``).
The upgrade makes the two tables, copies every ``h2_runs`` / ``h2_items`` row
into them as strategy ``h2`` (ids, dates and values unchanged;
``high_gap_240`` into ``values_json``) and drops the old tables.  The
downgrade makes ``h2_runs`` / ``h2_items`` again as 0034 made them, copies the
``h2`` rows back and drops the new tables; another strategy's lists, which
0034 has no place for, are dropped with them.
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

from app.strategy_lists import move_h2_in, move_h2_out

revision = "0035_strategy_lists"
down_revision = "0034_h2_lists"
branch_labels = None
depends_on = None

ITEM_INDEXES = ("run_id", "trading_date", "instrument_id")
H2_ITEM_INDEXES = ("h2_run_id", "trading_date", "instrument_id")


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "strategy_list_runs" not in tables:
        op.create_table(
            "strategy_list_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("strategy", String(length=40), nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("definitions_sha256", String(length=64), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("universe_count", Integer, nullable=False),
            Column("item_count", Integer, nullable=False),
            Column("config_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date",
                "strategy",
                "version",
                name="uq_strategy_list_run_day_strategy_version",
            ),
        )
        op.create_index(
            "ix_strategy_list_runs_trading_date",
            "strategy_list_runs",
            ["trading_date"],
        )
    if "strategy_list_items" not in tables:
        op.create_table(
            "strategy_list_items",
            Column("id", Integer, primary_key=True),
            Column(
                "run_id",
                Integer,
                ForeignKey("strategy_list_runs.id"),
                nullable=False,
            ),
            Column("trading_date", Date, nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("strategy", String(length=40), nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("rank", Integer, nullable=False),
            Column("close", Float, nullable=False),
            Column("values_json", JSON, nullable=False),
            UniqueConstraint(
                "trading_date",
                "instrument_id",
                "strategy",
                "version",
                name="uq_strategy_list_item_day_strategy_version",
            ),
        )
        for column in ITEM_INDEXES:
            op.create_index(
                f"ix_strategy_list_items_{column}", "strategy_list_items", [column]
            )
    move_h2_in(op.get_bind())


def downgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    # 0034's two tables, as it made them.
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
        for column in H2_ITEM_INDEXES:
            op.create_index(f"ix_h2_items_{column}", "h2_items", [column])
    if "strategy_list_runs" in tables:
        move_h2_out(op.get_bind())
    if "strategy_list_items" in tables:
        for column in ITEM_INDEXES:
            op.drop_index(
                f"ix_strategy_list_items_{column}", table_name="strategy_list_items"
            )
        op.drop_table("strategy_list_items")
    if "strategy_list_runs" in tables:
        op.drop_index(
            "ix_strategy_list_runs_trading_date", table_name="strategy_list_runs"
        )
        op.drop_table("strategy_list_runs")
