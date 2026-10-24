"""Add the user tracking plan tables.

Revision ID: 0017_tracking_plans
Revises: 0016_group_score_archive

``tracking_plans`` keeps one user plan copied from a conditional signal and
``tracking_plan_sessions`` its tracked sessions (V1_SPEC 使用者追蹤計畫,
worker.plan_tracking).  The partial unique index allows at most one plan per
signal that is not cancelled.  Additive and forward-only: no existing row is
read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
    text,
)

revision = "0017_tracking_plans"
down_revision = "0016_group_score_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("tracking_plans"):
        return
    op.create_table(
        "tracking_plans",
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("signal_id", Integer, ForeignKey("signals.id"), nullable=False),
        Column(
            "daily_candidate_id",
            Integer,
            ForeignKey("daily_candidates.id"),
            nullable=True,
        ),
        Column("source_kind", String(length=20), nullable=False),
        Column("strategy", String(length=60), nullable=False),
        Column(
            "strategy_version_id",
            Integer,
            ForeignKey("strategy_versions.id"),
            nullable=True,
        ),
        Column("formula_version", String(length=80), nullable=True),
        Column("score_version", String(length=40), nullable=True),
        Column("tracking_version", String(length=40), nullable=False),
        Column("plan_date", Date, nullable=False),
        Column("earliest_execution_date", Date, nullable=True),
        Column("entry_type", String(length=30), nullable=False),
        Column("reference_entry", Float, nullable=True),
        Column("pullback_low", Float, nullable=True),
        Column("pullback_high", Float, nullable=True),
        Column("breakout_price", Float, nullable=True),
        Column("invalid_price", Float, nullable=True),
        Column("target_1", Float, nullable=True),
        Column("target_2", Float, nullable=True),
        Column("window_sessions", Integer, nullable=False),
        Column("status", String(length=20), nullable=False),
        Column("status_reason", Text, nullable=True),
        Column("sessions_observed", Integer, nullable=False),
        Column("last_session_date", Date, nullable=True),
        Column("execution_date", Date, nullable=True),
        Column("execution_price", Float, nullable=True),
        Column("outcome_date", Date, nullable=True),
        Column("outcome_price", Float, nullable=True),
        Column("result_return", Float, nullable=True),
        Column("result_comparable", Boolean, nullable=True),
        Column("incomparable_reason", Text, nullable=True),
        Column("data_quality", String(length=30), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        Column("cancelled_at", DateTime, nullable=True),
    )
    op.create_index(
        "ix_tracking_plans_instrument_id", "tracking_plans", ["instrument_id"]
    )
    op.create_index("ix_tracking_plans_signal_id", "tracking_plans", ["signal_id"])
    op.create_index("ix_tracking_plans_plan_date", "tracking_plans", ["plan_date"])
    op.create_index("ix_tracking_plans_status", "tracking_plans", ["status"])
    op.create_index(
        "uq_tracking_plan_open_signal",
        "tracking_plans",
        ["signal_id"],
        unique=True,
        sqlite_where=text("cancelled_at IS NULL"),
    )
    op.create_table(
        "tracking_plan_sessions",
        Column("id", Integer, primary_key=True),
        Column("plan_id", Integer, ForeignKey("tracking_plans.id"), nullable=False),
        Column("session_date", Date, nullable=False),
        Column("session_no", Integer, nullable=False),
        Column("status", String(length=40), nullable=False),
        Column("reason", Text, nullable=True),
        Column("ohlc_json", JSON, nullable=False),
        Column("adjusted_ohlc_json", JSON, nullable=False),
        Column("entry_trigger", Boolean, nullable=False),
        Column("target_trigger", Boolean, nullable=False),
        Column("invalid_trigger", Boolean, nullable=False),
        Column("suspended", Boolean, nullable=False),
        Column("comparable", Boolean, nullable=False),
        Column("execution_price", Float, nullable=True),
        Column("source", String(length=500), nullable=True),
        Column("data_time", String(length=80), nullable=True),
        UniqueConstraint("plan_id", "session_date", name="uq_tracking_plan_session"),
    )
    op.create_index(
        "ix_tracking_plan_sessions_plan_id", "tracking_plan_sessions", ["plan_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "The tracking plan migration is forward-only to preserve user plans"
    )
