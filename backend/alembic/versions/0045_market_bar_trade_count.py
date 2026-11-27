"""Add the official trade count to market_bars.

Revision ID: 0045_market_bar_trade_count
Revises: 0040_premarket_ai

Issue #1094: ``market_bars.trade_count`` is the exchange's 成交筆數 of the
same quote-table row as the bar (TWSE ``MI_INDEX`` / OpenAPI
``STOCK_DAY_ALL`` ``Transaction``, TPEx ``dailyQuotes`` / OpenAPI
``TransactionNumber``), so it shares the bar's source, data_as_of and
raw_payload_id.  A nullable ``ADD COLUMN``: the table is not rebuilt and
every existing row reads null until collect or ``worker.cli trade-count
reread`` (research DB only) fills it.  Index, futures and US index bars stay
null.  The downgrade drops the column and its values, which the reread
rebuilds from the stored captures.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, Integer, inspect

revision = "0045_market_bar_trade_count"
down_revision = "0040_premarket_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    # As 0026 does: only a partial schema (the old-revision fixtures) lacks it.
    if not inspector.has_table("market_bars"):
        return
    columns = {column["name"] for column in inspector.get_columns("market_bars")}
    if "trade_count" not in columns:
        op.add_column("market_bars", Column("trade_count", Integer, nullable=True))


def downgrade() -> None:
    # SQLite 3.35+ drops a column in place, without rebuilding the table.
    op.get_bind().exec_driver_sql("ALTER TABLE market_bars DROP COLUMN trade_count")
