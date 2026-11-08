"""0029: nullable open/high/low/volume and the index/futures columns of market_bars.

Issue #552 stores real index daily bars: a day whose source gave no
open/high/low keeps them empty (``price_reason``), the volume report is a
second capture (``volume_raw_payload_id``), and a futures row keeps its
contract month, open interest and settlement price.  SQLite cannot drop a
NOT NULL constraint in place, so a table that still has one is rebuilt once
with the current model's definition and every row copied unchanged; a table
that only lacks the new columns gets them added.  Idempotent.  The caller
owns the transaction, with foreign-key enforcement off (Alembic's
environment and ``migrations._fallback_upgrade`` both do), and no other table
references market_bars.
"""

from __future__ import annotations

from sqlalchemy import MetaData, inspect
from sqlalchemy.schema import CreateIndex, CreateTable

from .models import MarketBar

TABLE = "market_bars"
NULLABLE_COLUMNS = ("open", "high", "low", "volume")
NEW_COLUMNS = {
    "price_reason": "VARCHAR(40)",
    "volume_raw_payload_id": "INTEGER REFERENCES raw_payloads(id)",
    "contract_month": "VARCHAR(10)",
    "open_interest": "INTEGER",
    "settlement_price": "FLOAT",
}
_SCRATCH = "_market_bars_0029"


def _columns(connection) -> dict[str, tuple]:
    return {
        row[1]: row
        for row in connection.exec_driver_sql(f'PRAGMA main.table_info("{TABLE}")')
    }


def needs_upgrade(connection) -> bool:
    """Whether market_bars still has a NOT NULL price/volume or lacks a 0029 column."""

    if not inspect(connection).has_table(TABLE):
        return False
    columns = _columns(connection)
    return any(
        name in columns and columns[name][3] for name in NULLABLE_COLUMNS
    ) or any(name not in columns for name in NEW_COLUMNS)


def _rebuild(connection, columns: dict[str, tuple]) -> None:
    table = MarketBar.__table__
    # CREATE TABLE only: the named indexes go on the final table after the
    # rename, since index names are global.
    # The referenced tables are copied too so the foreign keys resolve.
    metadata = MetaData()
    for referenced in {key.column.table for key in table.foreign_keys}:
        referenced.to_metadata(metadata)
    scratch = table.to_metadata(metadata, name=_SCRATCH)
    connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{_SCRATCH}"')
    connection.execute(CreateTable(scratch))
    kept = [column.name for column in table.columns if column.name in columns]
    names = ", ".join(f'"{name}"' for name in kept)
    connection.exec_driver_sql(
        f'INSERT INTO "{_SCRATCH}" ({names}) SELECT {names} FROM "{TABLE}"'
    )
    # Indexes the model does not define (none today) are recreated as stored.
    model_indexes = {index.name for index in table.indexes}
    extra = [
        sql
        for name, sql in connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
            (TABLE,),
        ).all()
        if name not in model_indexes
    ]
    connection.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    connection.exec_driver_sql(f'ALTER TABLE "{_SCRATCH}" RENAME TO "{TABLE}"')
    for index in table.indexes:
        connection.execute(CreateIndex(index, if_not_exists=True))
    for sql in extra:
        connection.exec_driver_sql(sql)


def upgrade_market_bars(connection) -> bool:
    """Apply 0029 to market_bars; return whether anything changed."""

    if not needs_upgrade(connection):
        return False
    columns = _columns(connection)
    if any(name in columns and columns[name][3] for name in NULLABLE_COLUMNS):
        _rebuild(connection, columns)
        return True
    for name, ddl in NEW_COLUMNS.items():
        if name not in columns:
            connection.exec_driver_sql(
                f'ALTER TABLE "{TABLE}" ADD COLUMN "{name}" {ddl}'
            )
    connection.exec_driver_sql(
        f'CREATE INDEX IF NOT EXISTS "ix_market_bars_volume_raw_payload_id" '
        f'ON "{TABLE}" ("volume_raw_payload_id")'
    )
    return True
