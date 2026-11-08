"""Let market_bars keep an empty open/high/low/volume and the index/futures fields.

Revision ID: 0029_market_bar_ohlc_nullable
Revises: 0028_monthly_revenues

Issue #552 stores real index daily bars: ``open``/``high``/``low``/``volume``
become nullable (a day the source gave no open/high/low keeps them empty with
``price_reason``, never the close), and ``price_reason``,
``volume_raw_payload_id`` (the volume report's capture), ``contract_month``,
``open_interest`` and ``settlement_price`` (futures) are added.  SQLite drops
NOT NULL only by rebuilding the table, so ``app.market_bar_migration`` copies
every row unchanged into the new definition.  Forward-only.
"""

from __future__ import annotations

from alembic import op

from app.market_bar_migration import upgrade_market_bars

revision = "0029_market_bar_ohlc_nullable"
down_revision = "0028_monthly_revenues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    upgrade_market_bars(op.get_bind())


def downgrade() -> None:
    raise RuntimeError(
        "0029 is forward-only: rows written since may hold an empty open/high/low"
    )
