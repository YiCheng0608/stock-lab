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
from sqlalchemy import Column, String, inspect, text

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
    op.add_column(
        "signal_settlements",
        Column(
            "tracking_rules",
            String(length=20),
            nullable=False,
            server_default=text("'tracking_v1'"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("0023_settlement_tracking_rules is forward-only")
