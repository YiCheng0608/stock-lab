"""Add the pre-open news check table.

Revision ID: 0032_preopen_news_checks
Revises: 0031_drop_theme_suggestions

``preopen_news_checks`` keeps one row per list date and candidate: the news the
list's daily had not seen, collected after ``candidate_runs.computed_at`` and
published up to the 08:20 check, with the AI direction of each as it was at the
check (Issue #755).  ``worker.preopen`` writes it; ``/api/candidates`` reads it.
Display only.  Additive and forward-only: no existing row is read or changed.
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
    UniqueConstraint,
    inspect,
)

revision = "0032_preopen_news_checks"
down_revision = "0031_drop_theme_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if inspect(op.get_bind()).has_table("preopen_news_checks"):
        return
    op.create_table(
        "preopen_news_checks",
        Column("id", Integer, primary_key=True),
        Column("list_date", Date, nullable=False),
        Column(
            "candidate_run_id",
            Integer,
            ForeignKey("candidate_runs.id"),
            nullable=False,
        ),
        Column("instrument_id", Integer, ForeignKey("instruments.id"), nullable=False),
        Column("rank", Integer, nullable=False),
        Column("window_start", DateTime, nullable=False),
        Column("checked_at", DateTime, nullable=False),
        Column("news_count", Integer, nullable=False),
        Column("positive", Integer, nullable=False),
        Column("negative", Integer, nullable=False),
        Column("mixed", Integer, nullable=False),
        Column("unknown", Integer, nullable=False),
        Column("unscored", Integer, nullable=False),
        Column("news_json", JSON, nullable=False),
        Column("prompt_version", String(length=40), nullable=False),
        UniqueConstraint("list_date", "instrument_id", name="uq_preopen_news_check"),
    )
    op.create_index(
        "ix_preopen_news_checks_list_date", "preopen_news_checks", ["list_date"]
    )
    op.create_index(
        "ix_preopen_news_checks_candidate_run_id",
        "preopen_news_checks",
        ["candidate_run_id"],
    )
    op.create_index(
        "ix_preopen_news_checks_instrument_id",
        "preopen_news_checks",
        ["instrument_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "The pre-open news check migration is forward-only to preserve the checks"
    )
