"""Finite, read-only SQLite startup checks; not a full integrity audit.

Only migration markers and mapped structural identities are inspected. No
historical rows are scanned, and no migration or repair is attempted.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import UniqueConstraint

from . import models  # noqa: F401: populate the mapped metadata without DDL
from .config import DB_PATH
from .db import Base


REVISIONS = (
    "0001_schema_v1",
    "0002_instrument_exchange_key",
    "0003_backtest_run_metadata",
    "0004_product_news_themes",
    "0005_news_temporal_contract",
    "0006_news_json_defaults",
    "0007_turnover_availability",
)
READ_TIMEOUT_SECONDS = 1.0
_LEGACY_REQUEST_KEY_DDL = re.compile(
    r'\s*CREATE\s+UNIQUE\s+INDEX\s+(?:ix_ingestion_runs_request_key|"ix_ingestion_runs_request_key")'
    r'\s+ON\s+(?:ingestion_runs|"ingestion_runs")\s*'
    r'\(\s*(?:request_key|"request_key")\s*\)\s+WHERE\s+'
    r'(?:request_key|"request_key")\s+IS\s+NOT\s+NULL\s*',
    re.IGNORECASE,
)


class DatabaseReadinessError(RuntimeError):
    """The configured database cannot safely satisfy the startup contract."""


def _fail(reason: str) -> None:
    raise DatabaseReadinessError(
        f"Database is not ready: {reason}. Verify STOCK_DATA_DIR, STOCK_DB_PATH "
        "and STOCK_RAW_DIR first. Before any explicit initialization/upgrade, "
        "make a consistent backup and rehearse on an external copy; then run "
        "python -m worker.cli init-db only against the intended authorized "
        "database. API startup does not initialize, migrate or repair it."
    )


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _check_markers(connection: sqlite3.Connection, tables: set[str]) -> None:
    has_alembic = "alembic_version" in tables
    if has_alembic:
        rows = connection.execute("SELECT version_num FROM alembic_version LIMIT 2").fetchall()
        if rows != [(REVISIONS[-1],)]:
            _fail("Alembic must contain exactly the current head revision")
    if "schema_migrations" in tables:
        values = [row[0] for row in connection.execute(
            f"SELECT version FROM schema_migrations LIMIT {len(REVISIONS) + 1}"
        )]
        if (
            not values
            or any(type(value) is not str for value in values)
            or len(set(values)) != len(values)
            or set(values) != set(REVISIONS[:len(values)])
            or len(values) > len(REVISIONS)
        ):
            _fail("fallback revisions must be a distinct, nonempty known prefix")
        if not has_alembic and len(values) != len(REVISIONS):
            _fail("fallback-only database requires all seven revisions")
    elif not has_alembic:
        _fail("database has no recognized migration markers")


def _empty_array_literal(default: str | None) -> bool:
    if default is None:
        return False
    value = default.strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    # Accept SQL string literals, never execute a stored SQL expression.
    return value in ("'[]'", '"[]"')


def _known_legacy_unique(connection: sqlite3.Connection, table: str, index: str, key: tuple) -> bool:
    # Revision 0001 preserves multiple legacy NULL request keys. This exact
    # predicate still enforces every non-NULL key just like nullable UNIQUE.
    # Match the entire stored DDL, not a suffix that comments could imitate.
    if (table, index, key) != ("ingestion_runs", "ix_ingestion_runs_request_key", ("request_key",)):
        return False
    row = connection.execute("SELECT sql FROM sqlite_schema WHERE type='index' AND name=?", (index,)).fetchone()
    return bool(row and isinstance(row[0], str) and _LEGACY_REQUEST_KEY_DDL.fullmatch(row[0]))


def _check_instrument_unique_indexes(connection: sqlite3.Connection, by_name: dict[str, tuple]) -> None:
    """Check finite identity metadata without reading rows or parsing dependencies.

    Named generated extras and unrelated unique keys remain outside this gate.
    ASC/BINARY/order are descriptor requirements, not SQL equivalence tests.
    """
    targets = {"market", "exchange", "symbol"}
    if any(by_name[name][6] != 0 for name in targets):
        _fail("instruments requires ordinary writable market/exchange/symbol columns")
    canonical_found = False
    for index in connection.execute('PRAGMA main.index_list("instruments")'):
        if not index[2]:
            continue
        parts = [
            row for row in connection.execute(f"PRAGMA main.index_xinfo({_quote(index[1])})")
            if row[5]
        ]
        if any(row[1] < 0 or row[2] is None for row in parts):
            _fail("instruments has an unsupported unique expression")
        key = tuple(row[2] for row in parts)
        if not targets.intersection(key):
            continue
        if (
            key != ("exchange", "symbol")
            or index[4]
            or any(row[3] != 0 or row[4] != "BINARY" for row in parts)
        ):
            _fail("instruments has a noncanonical target unique identity")
        canonical_found = True
    if not canonical_found:
        _fail("instruments lacks the canonical unique identity (exchange, symbol)")


def _check_settlement_unique_indexes(connection: sqlite3.Connection) -> None:
    """Check finite identity metadata, not arbitrary constraints or row data.

    Unrelated ordinary unique indexes and nonunique extras remain allowed.
    Expressions cannot be attributed to columns using this metadata alone.
    ASC/BINARY/order are compatibility requirements, not SQL equivalence tests.
    """
    canonical_found = False
    for index in connection.execute('PRAGMA main.index_list("signal_settlements")'):
        if not index[2]:
            continue
        parts = [
            row for row in connection.execute(f"PRAGMA main.index_xinfo({_quote(index[1])})")
            if row[5]
        ]
        if any(row[1] < 0 or row[2] is None for row in parts):
            _fail("signal_settlements has an unsupported unique expression")
        key = tuple(row[2] for row in parts)
        if not {"signal_id", "horizon"}.intersection(key):
            continue
        if (
            key != ("signal_id", "horizon")
            or index[4]
            or any(row[3] != 0 or row[4] != "BINARY" for row in parts)
        ):
            _fail("signal_settlements has a noncanonical target unique identity")
        canonical_found = True
    if not canonical_found:
        _fail("signal_settlements lacks the canonical unique identity (signal_id, horizon)")


def _check_schema(connection: sqlite3.Connection, tables: set[str]) -> None:
    for table in Base.metadata.sorted_tables:
        name = table.name
        if name not in tables:
            _fail(f"required real table {name} is missing")
        columns = connection.execute(f"PRAGMA table_xinfo({_quote(name)})").fetchall()
        by_name = {row[1]: row for row in columns}
        missing = set(table.columns.keys()) - by_name.keys()
        if missing:
            _fail(f"{name} is missing columns {sorted(missing)}")
        primary = tuple(row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5])
        if primary != tuple(column.name for column in table.primary_key.columns):
            _fail(f"{name} primary key does not match mapped identity")

        if name == "instruments":
            _check_instrument_unique_indexes(connection, by_name)
        if name == "signal_settlements":
            _check_settlement_unique_indexes(connection)

        unique_keys = set()
        for index in connection.execute(f"PRAGMA index_list({_quote(name)})"):
            if not index[2]:
                continue
            parts = connection.execute(f"PRAGMA index_xinfo({_quote(index[1])})").fetchall()
            key = tuple(row[2] for row in parts if row[5])
            if index[4] and not _known_legacy_unique(connection, name, index[1], key):
                continue
            if all(part is not None for part in key):
                unique_keys.add(key)
        required_unique = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints if isinstance(constraint, UniqueConstraint)
        }
        required_unique.update(
            tuple(column.name for column in index.columns) for index in table.indexes if index.unique
        )
        if not required_unique.issubset(unique_keys):
            _fail(f"{name} lacks required unique identities {sorted(required_unique - unique_keys)}")

        foreign_groups: dict[int, list[tuple]] = {}
        for row in connection.execute(f"PRAGMA foreign_key_list({_quote(name)})"):
            foreign_groups.setdefault(row[0], []).append(row)
        actual_fks = {
            (tuple(row[3] for row in sorted(group, key=lambda row: row[1])),
             group[0][2], tuple(row[4] for row in sorted(group, key=lambda row: row[1])))
            for group in foreign_groups.values()
        }
        required_fks = {
            (tuple(element.parent.name for element in constraint.elements),
             constraint.referred_table.name,
             tuple(element.column.name for element in constraint.elements))
            for constraint in table.foreign_key_constraints
        }
        if not required_fks.issubset(actual_fks):
            _fail(f"{name} lacks required foreign key identities")
        if name == "news_items":
            for column in ("symbols_json", "theme_ids_json"):
                if not _empty_array_literal(by_name[column][4]):
                    _fail(f"news_items.{column} requires the empty-array SQL literal default")


def check_database_readiness(path: Path | None = None) -> None:
    """Check the configured file without opening a create-capable connection.

    The read transaction covers markers and schema at one SQLite snapshot.
    Existing configuration directory creation and later API writes are outside
    this startup check. Deep page corruption and data integrity are not audited.
    """
    target = Path(path) if path is not None else DB_PATH
    try:
        if not target.is_file():
            _fail("configured database file is missing or is not a regular file")
        if target.stat().st_size == 0:
            _fail("configured database file is empty")
        uri = target.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=READ_TIMEOUT_SECONDS)) as connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            objects = dict(connection.execute("SELECT name, type FROM sqlite_schema WHERE type IN ('table','view')"))
            tables = {name for name, kind in objects.items() if kind == "table"}
            for marker in ("alembic_version", "schema_migrations"):
                if marker in objects and marker not in tables:
                    _fail(f"{marker} must be a real table")
            _check_markers(connection, tables)
            _check_schema(connection, tables)
    except (OSError, sqlite3.Error) as exc:
        _fail(f"cannot read configured SQLite database ({exc})")
