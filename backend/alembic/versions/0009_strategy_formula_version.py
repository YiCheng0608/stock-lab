"""Identify strategy rows by their formula sub-version.

``StrategyVersion.version`` stays ``1.0.0`` across a formula change (V1_SPEC),
so a row written under the previous formula and one for the current formula
need different identities.  Existing rows keep their id, version, config and
snapshot; each is classified as a known formula or ``unclassified/<reason>``,
and rows that are not the current formula are deactivated.

Revision ID: 0009_strategy_formula_version
Revises: 0008_portfolio_share_integer
"""
from __future__ import annotations

from alembic import op

from app.migrations import ensure_strategy_formula_version

revision = "0009_strategy_formula_version"
down_revision = "0008_portfolio_share_integer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_strategy_formula_version(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Strategy formula identity migration is forward-only to preserve legacy data")
