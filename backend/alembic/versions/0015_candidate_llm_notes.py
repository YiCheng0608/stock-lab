"""Add the candidate LLM note table.

Revision ID: 0015_candidate_llm_notes
Revises: 0014_theme_suggestions

``candidate_llm_notes`` keeps one row per daily candidate and prompt version
with the LLM explanation (worker.candidate_notes).  Additive and
forward-only: no existing row is read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
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

revision = "0015_candidate_llm_notes"
down_revision = "0014_theme_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("candidate_llm_notes"):
        return
    op.create_table(
        "candidate_llm_notes",
        Column("id", Integer, primary_key=True),
        Column(
            "daily_candidate_id",
            Integer,
            ForeignKey("daily_candidates.id"),
            nullable=False,
        ),
        Column(
            "candidate_run_id", Integer, ForeignKey("candidate_runs.id"), nullable=False
        ),
        Column("trading_date", Date, nullable=False),
        Column("prompt_version", String(length=40), nullable=False),
        Column("llm_model", String(length=80), nullable=True),
        Column("llm_input_hash", String(length=64), nullable=False),
        Column("llm_run_at", DateTime, nullable=False),
        Column("llm_status", String(length=20), nullable=False),
        Column("llm_error", Text, nullable=True),
        Column("ai_selection", Text, nullable=True),
        Column("ai_levels", Text, nullable=True),
        Column("ai_risks", Text, nullable=True),
        Column(
            "ingestion_run_id", Integer, ForeignKey("ingestion_runs.id"), nullable=True
        ),
        Column("raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=True),
        UniqueConstraint(
            "daily_candidate_id", "prompt_version", name="uq_candidate_llm_note_prompt"
        ),
    )
    for column in ("daily_candidate_id", "candidate_run_id", "trading_date"):
        op.create_index(
            f"ix_candidate_llm_notes_{column}", "candidate_llm_notes", [column]
        )


def downgrade() -> None:
    raise RuntimeError("The candidate LLM note migration is forward-only")
