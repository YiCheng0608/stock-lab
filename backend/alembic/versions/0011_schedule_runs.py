"""Add the scheduled-job run log.

Revision ID: 0011_schedule_runs
Revises: 0010_technical_indicators

``schedule_runs`` records every ``worker.cli daily`` invocation and
``schedule_run_steps`` its collect/analyze/evaluate/indicators steps.
Additive and forward-only: only the two tables are created; no existing row
is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)

revision = "0011_schedule_runs"
down_revision = "0010_technical_indicators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("schedule_runs"):
        op.create_table(
            "schedule_runs",
            Column("id", Integer, primary_key=True),
            Column("job", String(length=40), nullable=False),
            Column("target_date", Date, nullable=False),
            Column("trigger", String(length=30), nullable=False),
            Column("status", String(length=30), nullable=False),
            Column("started_at", DateTime, nullable=False),
            Column("finished_at", DateTime, nullable=True),
            Column("records", Integer, nullable=False),
            Column("error", Text, nullable=True),
            Column("summary_json", JSON, nullable=False),
            Column("host", String(length=255), nullable=True),
            Column("pid", Integer, nullable=True),
        )
        op.create_index(
            "ix_schedule_runs_target_date", "schedule_runs", ["target_date"]
        )
        op.create_index("ix_schedule_runs_status", "schedule_runs", ["status"])
        op.create_index(
            "ix_schedule_run_job_date", "schedule_runs", ["job", "target_date"]
        )
    if not inspect(bind).has_table("schedule_run_steps"):
        op.create_table(
            "schedule_run_steps",
            Column("id", Integer, primary_key=True),
            Column(
                "schedule_run_id",
                Integer,
                ForeignKey("schedule_runs.id"),
                nullable=False,
            ),
            Column("step", String(length=40), nullable=False),
            Column("sequence", Integer, nullable=False),
            Column("status", String(length=30), nullable=False),
            Column("started_at", DateTime, nullable=True),
            Column("finished_at", DateTime, nullable=True),
            Column("records", Integer, nullable=True),
            Column("error", Text, nullable=True),
            Column(
                "ingestion_run_id",
                Integer,
                ForeignKey("ingestion_runs.id"),
                nullable=True,
            ),
            Column("details_json", JSON, nullable=False),
            UniqueConstraint("schedule_run_id", "step", name="uq_schedule_run_step"),
        )
        op.create_index(
            "ix_schedule_run_steps_schedule_run_id",
            "schedule_run_steps",
            ["schedule_run_id"],
        )


def downgrade() -> None:
    raise RuntimeError(
        "Schedule run log migration is forward-only to preserve run history"
    )
