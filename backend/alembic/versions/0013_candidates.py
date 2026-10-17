"""Add the daily candidate tables.

Revision ID: 0013_candidates
Revises: 0012_news_llm

``candidate_runs`` keeps one row per trading date and score version
(including days with zero candidates and their reason); ``daily_candidates``
keeps the ranked rows of each run.  Additive and forward-only: no existing
row is read or changed.
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

revision = "0013_candidates"
down_revision = "0012_news_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("candidate_runs"):
        op.create_table(
            "candidate_runs",
            Column("id", Integer, primary_key=True),
            Column("trading_date", Date, nullable=False),
            Column("score_version", String(length=40), nullable=False),
            Column("status", String(length=20), nullable=False),
            Column("evaluated_signals", Integer, nullable=False),
            Column("pool_count", Integer, nullable=False),
            Column("candidate_count", Integer, nullable=False),
            Column("zero_reason", String(length=60), nullable=True),
            Column("exclusions_json", JSON, nullable=False),
            Column("config_json", JSON, nullable=False),
            Column("summary_json", JSON, nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date", "score_version", name="uq_candidate_run_day_version"
            ),
        )
        op.create_index(
            "ix_candidate_runs_trading_date", "candidate_runs", ["trading_date"]
        )
    if not inspect(bind).has_table("daily_candidates"):
        op.create_table(
            "daily_candidates",
            Column("id", Integer, primary_key=True),
            Column(
                "candidate_run_id",
                Integer,
                ForeignKey("candidate_runs.id"),
                nullable=False,
            ),
            Column("trading_date", Date, nullable=False),
            Column(
                "instrument_id", Integer, ForeignKey("instruments.id"), nullable=False
            ),
            Column("signal_id", Integer, ForeignKey("signals.id"), nullable=False),
            Column("strategy", String(length=60), nullable=False),
            Column("score_version", String(length=40), nullable=False),
            Column("total_score", Float, nullable=False),
            Column("weight_coverage", Float, nullable=False),
            Column("rank", Integer, nullable=False),
            Column("components_json", JSON, nullable=False),
            Column("reasons_json", JSON, nullable=False),
            Column("groups_json", JSON, nullable=False),
            Column("data_as_of", Date, nullable=False),
            Column("created_at", DateTime, nullable=False),
            UniqueConstraint(
                "trading_date",
                "instrument_id",
                "score_version",
                name="uq_daily_candidate_day_version",
            ),
        )
        op.create_index(
            "ix_daily_candidates_candidate_run_id",
            "daily_candidates",
            ["candidate_run_id"],
        )
        op.create_index(
            "ix_daily_candidates_trading_date", "daily_candidates", ["trading_date"]
        )
        op.create_index(
            "ix_daily_candidates_instrument_id", "daily_candidates", ["instrument_id"]
        )


def downgrade() -> None:
    raise RuntimeError(
        "The candidate migration is forward-only to preserve scored history"
    )
