"""Add the observation price level table.

Revision ID: 0018_strategy_levels
Revises: 0017_tracking_plans

``strategy_levels`` keeps, per signal and levels version, the close and
volume the next session needs for the signal's strategy to pass, with
reference stop and targets (V1_SPEC strategy_levels_v1, worker.strategy_levels).
Additive and forward-only: no existing row is read or changed.
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
    UniqueConstraint,
    inspect,
)

revision = "0018_strategy_levels"
down_revision = "0017_tracking_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("strategy_levels"):
        return
    op.create_table(
        "strategy_levels",
        Column("id", Integer, primary_key=True),
        Column("signal_id", Integer, ForeignKey("signals.id"), nullable=False),
        Column("levels_version", String(length=40), nullable=False),
        Column("availability", String(length=30), nullable=False),
        Column("next_session_date", Date, nullable=True),
        Column("trigger_price", Float, nullable=True),
        Column("zone_low", Float, nullable=True),
        Column("zone_high", Float, nullable=True),
        Column("min_volume", Integer, nullable=True),
        Column("max_volume", Integer, nullable=True),
        Column("reference_entry", Float, nullable=True),
        Column("entry_low", Float, nullable=True),
        Column("entry_high", Float, nullable=True),
        Column("invalid_price", Float, nullable=True),
        Column("target_1", Float, nullable=True),
        Column("target_2", Float, nullable=True),
        Column("risk_reward", Float, nullable=True),
        Column("reachable_next_session", Boolean, nullable=True),
        Column("conditions_json", JSON, nullable=False),
        Column("missing_inputs_json", JSON, nullable=False),
        Column("price_basis", String(length=40), nullable=False),
        Column("computed_at", DateTime, nullable=False),
        UniqueConstraint(
            "signal_id", "levels_version", name="uq_strategy_level_signal_version"
        ),
    )
    op.create_index("ix_strategy_levels_signal_id", "strategy_levels", ["signal_id"])


def downgrade() -> None:
    raise RuntimeError("The strategy levels migration is forward-only")
