"""Align NewsItem JSON server defaults with the declarative model.

Revision ID: 0006_news_json_defaults
Revises: 0005_news_temporal_contract
"""

from __future__ import annotations

from alembic import op

from app import news_json_defaults


revision = "0006_news_json_defaults"
down_revision = "0005_news_temporal_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    news_json_defaults.ensure_news_json_server_defaults(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("The news JSON default migration is forward-only")
