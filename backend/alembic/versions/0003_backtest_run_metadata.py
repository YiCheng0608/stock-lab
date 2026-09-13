"""Add auditable metadata for technical backtest runs.

Revision ID: 0003_backtest_run_metadata
Revises: 0002_instrument_exchange_key
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


revision = "0003_backtest_run_metadata"
down_revision = "0002_instrument_exchange_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("ingestion_runs"):
        return
    columns = {column["name"] for column in inspect(bind).get_columns("ingestion_runs")}
    if "metadata_json" not in columns:
        bind.execute(
            text(
                'ALTER TABLE "ingestion_runs" '
                'ADD COLUMN "metadata_json" JSON NOT NULL DEFAULT \'{}\''
            )
        )


def downgrade() -> None:
    raise RuntimeError("The backtest metadata migration is forward-only")
