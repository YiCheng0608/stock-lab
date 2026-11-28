"""Add the AI list scores table.

Revision ID: 0053_ai_list_scores
Revises: 0051_ai_list

``ai_list_scores`` keeps the scored outcomes of the AI list readings under
``ai_list_score_v1`` (Issue #1147, ``worker.ai_list_score``,
docs/spec/ai_list.md 對答案).  Additive: no existing row is read or changed.
The number is 0053: 0043 to 0050 are the research database's queued
migrations and 0052 is #1149's (#1147 決定 7238340331).  The downgrade drops
the table and its rows; ``worker.cli ai-list-score`` writes them again from the
stored readings and bars.
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

revision = "0053_ai_list_scores"
down_revision = "0051_ai_list"
branch_labels = None
depends_on = None

SCORES = "ai_list_scores"
INDEXES = ("reading_id", "session_date")


def upgrade() -> None:
    if SCORES in set(inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        SCORES,
        Column("id", Integer, primary_key=True),
        Column(
            "reading_id", Integer, ForeignKey("ai_list_readings.id"), nullable=False
        ),
        Column("pick_id", Integer, ForeignKey("ai_list_picks.id"), nullable=True),
        Column("session_date", Date, nullable=False),
        Column("prompt_version", String(length=40), nullable=False),
        Column("role", String(length=20), nullable=False),
        Column("scope", String(length=20), nullable=False),
        Column("subject", String(length=40), nullable=False),
        Column("horizon", String(length=20), nullable=False),
        Column("score_version", String(length=40), nullable=False),
        Column("outcome_json", JSON, nullable=False),
        Column("computed_at", DateTime, nullable=False),
        UniqueConstraint(
            "reading_id",
            "scope",
            "subject",
            "horizon",
            "score_version",
            name="uq_ai_list_score",
        ),
    )
    for column in INDEXES:
        op.create_index(f"ix_{SCORES}_{column}", SCORES, [column])


def downgrade() -> None:
    if SCORES not in set(inspect(op.get_bind()).get_table_names()):
        return
    for column in INDEXES:
        op.drop_index(f"ix_{SCORES}_{column}", table_name=SCORES)
    op.drop_table(SCORES)
