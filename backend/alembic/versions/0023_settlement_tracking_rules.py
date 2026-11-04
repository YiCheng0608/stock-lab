"""Record the tracking rule version of each signal settlement.

Revision ID: 0023_settlement_tracking_rules
Revises: 0022_margin_lists

``signal_settlements.tracking_rules`` names the ``app.tracking`` rule version a
T+N result was computed with (docs/spec/tracking.md 口徑版本, Issue #444).
Every existing row was computed with ``tracking_v1``, so the column is added
with that default, which fills it for the stored rows; the worker writes the
version explicitly on every new or recomputed settlement.  Additive and
forward-only: no existing value is changed.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

# The same statement as the fallback step (app.migrations), so both entries
# store the same table SQL.
ADD_COLUMN = (
    'ALTER TABLE "signal_settlements" ADD COLUMN "tracking_rules" '
    "VARCHAR(20) NOT NULL DEFAULT 'tracking_v1'"
)

revision = "0023_settlement_tracking_rules"
down_revision = "0022_margin_lists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    # A partial legacy schema in the migration tests may lack the table.
    if not inspector.has_table("signal_settlements"):
        return
    if "tracking_rules" in {
        column["name"] for column in inspector.get_columns("signal_settlements")
    }:
        return
    op.execute(ADD_COLUMN)


def downgrade() -> None:
    raise RuntimeError("0023_settlement_tracking_rules is forward-only")
