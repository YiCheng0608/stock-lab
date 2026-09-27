"""Preserve turnover availability separately from its numeric storage.

Existing positive values retain their calculation behavior. A historical
zero is ambiguous: its source response cannot be reconstructed from the
stored number. Negative or NULL legacy values also remain unverified.

Revision ID: 0007_turnover_availability
Revises: 0006_news_json_defaults
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, String, inspect, text


revision = "0007_turnover_availability"
down_revision = "0006_news_json_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("market_bars")}
    added_status = "turnover_status" not in columns
    if added_status:
        op.add_column(
            "market_bars",
            Column("turnover_status", String(20), nullable=False, server_default="unknown"),
        )
    if "turnover_reason" not in columns:
        op.add_column("market_bars", Column("turnover_reason", String(40), nullable=True))
    if added_status:
        bind.execute(text("UPDATE market_bars SET turnover_status = 'available' WHERE turnover > 0"))
        bind.execute(text(
            "UPDATE market_bars SET turnover_reason = 'legacy_zero_ambiguous' "
            "WHERE turnover = 0"
        ))
        bind.execute(text(
            "UPDATE market_bars SET turnover_reason = 'legacy_invalid' "
            "WHERE turnover < 0 OR turnover IS NULL"
        ))


def downgrade() -> None:
    raise RuntimeError("Turnover availability migration is forward-only")
