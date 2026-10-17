"""Add the scalar daily technical indicator table.

Revision ID: 0010_technical_indicators
Revises: 0009_strategy_formula_version

Additive and forward-only.  Rows are derived from market_bars by the
indicator batch (worker.indicator_batch); no existing row is read or changed.
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

revision = "0010_technical_indicators"
down_revision = "0009_strategy_formula_version"
branch_labels = None
depends_on = None

_FLOAT_COLUMNS = (
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma120",
    "macd_dif",
    "macd_signal",
    "macd_hist",
    "rsi6",
    "rsi12",
    "kd_k",
    "kd_d",
    "boll_mid",
    "boll_upper",
    "boll_lower",
    "vol_ma5",
    "vol_ma20",
)


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("technical_indicators"):
        return
    op.create_table(
        "technical_indicators",
        Column("id", Integer, primary_key=True),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("trading_date", Date, nullable=False),
        Column("formula_version", String(length=40), nullable=False),
        Column("price_basis", String(length=40), nullable=False),
        Column("bar_count", Integer, nullable=False),
        *(Column(name, Float, nullable=True) for name in _FLOAT_COLUMNS),
        Column("null_reasons", JSON, nullable=False),
        Column("source", String(length=120), nullable=False),
        Column("computed_at", DateTime, nullable=False),
        UniqueConstraint(
            "instrument_id",
            "trading_date",
            "formula_version",
            name="uq_technical_indicator_day",
        ),
    )
    op.create_index(
        "ix_technical_indicators_trading_date", "technical_indicators", ["trading_date"]
    )


def downgrade() -> None:
    raise RuntimeError("The technical indicator migration is forward-only")
