"""Add exact portfolio quantity storage without rewriting legacy values.

The caller owns the transaction and revision marker. Backfill is performed
only when the nullable column is first added; no unsafe Float is cast.
"""
from __future__ import annotations

from sqlalchemy import inspect

from .units import safe_legacy_position_shares


def check_portfolio_share_column(connection) -> bool:
    """Inspect finite SQLite metadata; return whether the column exists."""
    if connection.dialect.name != "sqlite":
        raise RuntimeError("exact portfolio share migration requires SQLite")
    columns = {row[1]: row for row in connection.exec_driver_sql(
        'PRAGMA main.table_xinfo("portfolio_positions")'
    )}
    column = columns.get("shares_integer")
    if column is None:
        return False
    if (column[2].strip().upper() != "INTEGER" or column[3] != 0
            or column[4] is not None or column[5] != 0 or column[6] != 0):
        raise RuntimeError("portfolio_positions.shares_integer requires an ordinary nullable INTEGER without a default")
    return True


def ensure_portfolio_share_integer(connection) -> bool:
    """Add once, backfill only safe stored numbers, and preserve every other field."""
    if not inspect(connection).has_table("portfolio_positions"):
        raise RuntimeError("portfolio_positions table is required before exact share migration")
    if check_portfolio_share_column(connection):
        return False
    connection.exec_driver_sql('ALTER TABLE "portfolio_positions" ADD COLUMN "shares_integer" INTEGER')
    rows = connection.exec_driver_sql('SELECT id, shares FROM "portfolio_positions"').all()
    for row_id, legacy in rows:
        integer = safe_legacy_position_shares(legacy)
        if integer is not None:
            connection.exec_driver_sql(
                'UPDATE "portfolio_positions" SET "shares_integer"=? WHERE id=?', (integer, row_id)
            )
    check_portfolio_share_column(connection)
    return True
