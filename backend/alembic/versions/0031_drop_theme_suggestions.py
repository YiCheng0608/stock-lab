"""Drop the news theme suggestion tables.

Revision ID: 0031_drop_theme_suggestions
Revises: 0030_trading_halts

``theme_suggestions`` and ``theme_suggestion_news`` (0014) held an aggregate of
the theme candidates in ``news_llm_results``, shown on the themes page.  The
page section, the daily step, the CLI command and the API are gone (Issue
#629), so nothing reads or writes the tables.  Their rows were derived from
``news_llm_results``, which stays; no source data is lost.  Forward-only.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0031_drop_theme_suggestions"
down_revision = "0030_trading_halts"
branch_labels = None
depends_on = None

# The child table first: it references theme_suggestions.
TABLES = ("theme_suggestion_news", "theme_suggestions")


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    for table in TABLES:
        if inspector.has_table(table):
            op.drop_table(table)


def downgrade() -> None:
    raise RuntimeError(
        "Dropping the theme suggestion tables is forward-only; the rows were "
        "an aggregate of news_llm_results and are not restored"
    )
