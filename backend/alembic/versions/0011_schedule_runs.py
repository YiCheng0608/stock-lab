"""Add the scheduled-job run log.

``schedule_runs`` records every ``worker.cli daily`` invocation and
``schedule_run_steps`` its collect/analyze/evaluate/indicators steps.  The
migration only creates the two tables; no existing row is read or changed.

Revision ID: 0011_schedule_runs
Revises: 0010_technical_indicators
"""
from __future__ import annotations

from alembic import op

from app.migrations import ensure_schedule_run_tables

revision = "0011_schedule_runs"
down_revision = "0010_technical_indicators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_schedule_run_tables(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Schedule run log migration is forward-only to preserve run history")
