"""Add current investments, interest-bearing debt and net income to quarterly_statements.

Revision ID: 0050_quarterly_statement_debt
Revises: 0042_quarterly_statements

Issue #1140: seventeen more items of the MOPS quarterly XBRL archive
(``source=mops_tifrs_zip``, #1135 7234320089): seven current investment lines (IFRS
9's three, IAS 39's four), other current financial assets as a reference, five
interest-bearing debt lines, current and non-current lease liabilities, and the
year-to-date net income with the parent's share.  Thousand NTD as the other amounts,
nullable ``ADD COLUMN``s: the table is not rebuilt and every existing row reads null
until ``fundamentals statements-apply`` rereads the stored archives (research
database only; the production database's table stays empty).  The downgrade drops
the columns and their values, which that rerun rebuilds.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import Column, Float, inspect

revision = "0050_quarterly_statement_debt"
down_revision = "0042_quarterly_statements"
branch_labels = None
depends_on = None

# The same names as the fallback step (app.migrations._ADDITIVE_COLUMNS).
AMOUNTS = (
    "st_inv_fvtpl",
    "st_inv_fvoci",
    "st_inv_amortised",
    "st_inv_afs",
    "st_inv_htm",
    "st_inv_no_active_market",
    "st_inv_at_cost",
    "other_current_financial_assets",
    "short_term_borrowings",
    "short_term_bills_payable",
    "long_term_current_portion",
    "bonds_payable_noncurrent",
    "long_term_borrowings",
    "lease_liabilities_current",
    "lease_liabilities_noncurrent",
    "net_income_ytd",
    "net_income_parent_ytd",
)


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    # As 0045 does: only a partial schema (the old-revision fixtures) lacks it.
    if not inspector.has_table("quarterly_statements"):
        return
    columns = {
        column["name"] for column in inspector.get_columns("quarterly_statements")
    }
    for name in AMOUNTS:
        if name not in columns:
            op.add_column("quarterly_statements", Column(name, Float, nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if not inspector.has_table("quarterly_statements"):
        return
    columns = {
        column["name"] for column in inspector.get_columns("quarterly_statements")
    }
    # SQLite 3.35+ DROP COLUMN: no new table, but each drop rewrites every row.
    for name in reversed(AMOUNTS):
        if name in columns:
            op.get_bind().exec_driver_sql(
                f'ALTER TABLE "quarterly_statements" DROP COLUMN "{name}"'
            )
