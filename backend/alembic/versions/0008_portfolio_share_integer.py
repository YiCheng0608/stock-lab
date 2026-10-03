"""Preserve exact user portfolio share quantities alongside legacy Float.

Revision ID: 0008_portfolio_share_integer
Revises: 0007_turnover_availability
"""
from __future__ import annotations

from alembic import op

from app.portfolio_share_migration import ensure_portfolio_share_integer

revision = "0008_portfolio_share_integer"
down_revision = "0007_turnover_availability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_portfolio_share_integer(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Portfolio exact share migration is forward-only to preserve legacy data")
