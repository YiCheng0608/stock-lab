"""Add the LLM news inference table.

Revision ID: 0012_news_llm
Revises: 0010_technical_indicators

Additive and forward-only.  Rows are written by the news LLM batch
(worker.news_llm), one per news item and prompt version; news_items is not
read or changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)

revision = "0012_news_llm"
down_revision = "0010_technical_indicators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("news_llm_results"):
        return
    op.create_table(
        "news_llm_results",
        Column("id", Integer, primary_key=True),
        Column("news_item_id", Integer, ForeignKey("news_items.id"), nullable=False),
        Column("prompt_version", String(length=40), nullable=False),
        Column("llm_model", String(length=80), nullable=True),
        Column("llm_input_hash", String(length=64), nullable=False),
        Column("llm_run_at", DateTime, nullable=False),
        Column("llm_status", String(length=20), nullable=False),
        Column("llm_error", Text, nullable=True),
        Column("ai_summary", Text, nullable=True),
        Column("ai_symbol_candidates_json", JSON, nullable=False),
        Column("ai_theme_candidates_json", JSON, nullable=False),
        Column("ai_impact_direction", String(length=20), nullable=True),
        Column("ai_impact_scope", String(length=20), nullable=True),
        Column("ai_impact_rationale", Text, nullable=True),
        Column("ai_unsupported", Boolean, nullable=True),
        Column(
            "ingestion_run_id", Integer, ForeignKey("ingestion_runs.id"), nullable=True
        ),
        Column("raw_payload_id", Integer, ForeignKey("raw_payloads.id"), nullable=True),
        UniqueConstraint(
            "news_item_id", "prompt_version", name="uq_news_llm_item_prompt"
        ),
    )
    op.create_index(
        "ix_news_llm_results_news_item_id", "news_llm_results", ["news_item_id"]
    )
    op.create_index(
        "ix_news_llm_results_llm_status", "news_llm_results", ["llm_status"]
    )


def downgrade() -> None:
    raise RuntimeError("The news LLM migration is forward-only")
