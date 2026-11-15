"""Add the 主流族群前 20 tables.

Revision ID: 0033_mainstream_lists
Revises: 0032_preopen_news_checks

``mainstream_runs`` keeps one row per trading date and definition version, and
``mainstream_items`` one row per ranked stock (Issue #768).  The daily's
``mainstream`` step writes them (``app.mainstream``); ``/api/mainstream`` reads
them.  Additive and forward-only: no existing row is read or changed.
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

revision = "0033_mainstream_lists"
down_revision = "0032_preopen_news_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = inspect(op.get_bind()).get_table_names()
    if "mainstream_runs" not in tables:
        op.create_table(
            "mainstream_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("version", String(length=40), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("window", Integer, nullable=False),
            Column("group_count", Integer, nullable=False),
            Column("universe_count", Integer, nullable=False),
            Column("ranked_group_count", Integer, nullable=False),
            Column("item_count", Integer, nullable=False),
            Column("index_return", Float, nullable=False),
            Column("groups_json", JSON, nullable=False),
            Column("config_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date", "version", name="uq_mainstream_run_day_version"
            ),
        )
        op.create_index(
            "ix_mainstream_runs_trading_date", "mainstream_runs", ["trading_date"]
        )
    if "mainstream_items" not in tables:
        op.create_table(
            "mainstream_items",
            Column("id", Integer, primary_key=True),
            Column(
                "mainstream_run_id",
                Integer,
                ForeignKey("mainstream_runs.id"),
                nullable=False,
            ),
            Column("trading_date", Date, nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("version", String(length=40), nullable=False),
            Column("rank", Integer, nullable=False),
            Column("return_w", Float, nullable=False),
            Column("excess_w", Float, nullable=False),
            Column("group_ids_json", JSON, nullable=False),
            UniqueConstraint(
                "trading_date",
                "instrument_id",
                "version",
                name="uq_mainstream_item_day_version",
            ),
        )
        for column in ("mainstream_run_id", "trading_date", "instrument_id"):
            op.create_index(
                f"ix_mainstream_items_{column}", "mainstream_items", [column]
            )


def downgrade() -> None:
    raise RuntimeError(
        "The mainstream list migration is forward-only to preserve the lists"
    )
