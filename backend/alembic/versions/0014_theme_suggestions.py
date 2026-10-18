"""Add the news theme suggestion tables.

Revision ID: 0014_theme_suggestions
Revises: 0013_candidates

``theme_suggestions`` keeps one row per prompt version and normalized theme
name aggregated from news_llm_results; ``theme_suggestion_news`` links each
suggestion to its news items.  Additive and forward-only: no existing row is
read or changed.
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

revision = "0014_theme_suggestions"
down_revision = "0013_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("theme_suggestions"):
        op.create_table(
            "theme_suggestions",
            Column("id", Integer, primary_key=True),
            Column("theme_key", String(length=80), nullable=False),
            Column("display_name", String(length=80), nullable=False),
            Column("prompt_version", String(length=40), nullable=False),
            Column("aggregation_version", String(length=40), nullable=False),
            Column("llm_models_json", JSON, nullable=False),
            Column("news_count", Integer, nullable=False),
            Column("first_news_date", Date, nullable=False),
            Column("last_news_date", Date, nullable=False),
            Column("matched_group_id", String(length=80), nullable=True),
            Column("status", String(length=30), nullable=False),
            Column("computed_at", DateTime, nullable=False),
            UniqueConstraint(
                "prompt_version", "theme_key", name="uq_theme_suggestion_prompt_key"
            ),
        )
        op.create_index(
            "ix_theme_suggestions_last_news_date",
            "theme_suggestions",
            ["last_news_date"],
        )
    if not inspect(bind).has_table("theme_suggestion_news"):
        op.create_table(
            "theme_suggestion_news",
            Column("id", Integer, primary_key=True),
            Column(
                "suggestion_id",
                Integer,
                ForeignKey("theme_suggestions.id"),
                nullable=False,
            ),
            Column(
                "news_item_id", Integer, ForeignKey("news_items.id"), nullable=False
            ),
            Column(
                "news_llm_result_id",
                Integer,
                ForeignKey("news_llm_results.id"),
                nullable=False,
            ),
            Column("theme_text", String(length=80), nullable=False),
            Column("reason", Text, nullable=True),
            Column("news_date", Date, nullable=False),
            UniqueConstraint(
                "suggestion_id", "news_item_id", name="uq_theme_suggestion_news_item"
            ),
        )
        op.create_index(
            "ix_theme_suggestion_news_suggestion_id",
            "theme_suggestion_news",
            ["suggestion_id"],
        )
        op.create_index(
            "ix_theme_suggestion_news_news_item_id",
            "theme_suggestion_news",
            ["news_item_id"],
        )


def downgrade() -> None:
    raise RuntimeError("The theme suggestion migration is forward-only")
