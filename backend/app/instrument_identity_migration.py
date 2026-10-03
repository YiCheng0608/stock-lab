"""Bounded SQLite legacy instrument identity migration.

Only a finite, known legacy table grammar is rebuilt. Unknown definitions are
rejected before DDL; current identity tables are left alone. The caller owns
the transaction and foreign-key mode, including revision/marker writes.
"""
from __future__ import annotations

import re

SCRATCH = "instruments__v1_rebuild"
_COLUMNS = {
    "id": "integer not null",
    "market": "varchar ( 20 ) not null",
    "exchange": "varchar ( 20 ) not null default 'TWSE'",
    "symbol": "varchar ( 30 ) not null",
    "name": "varchar ( 120 ) not null",
    "instrument_type": "varchar ( 20 ) not null",
    "etf_category": "varchar ( 30 )",
    "industry": "varchar ( 120 )",
    "listing_date": "date",
    "is_watchlisted": "boolean not null",
    "status": "varchar ( 20 ) not null",
    "created_at": "datetime not null",
}
_INDEXES = {
    "ix_instruments_exchange": "exchange",
    "ix_instruments_symbol": "symbol",
    "ix_instruments_instrument_type": "instrument_type",
}
_CHILDREN = {
    "group_memberships", "market_bars", "chip_snapshots", "technical_features",
    "signals", "portfolio_positions", "corporate_actions",
    "fundamental_snapshots", "events",
}
_TOKEN = re.compile(r"\s+|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^]]*\]|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[(),;]")


def _error(reason: str) -> RuntimeError:
    return RuntimeError(f"cannot migrate instruments: {reason}")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _tokens(sql: str) -> list[str]:
    """Recognize a small DDL vocabulary, not a general SQLite rewriter."""
    result = []
    position = 0
    for match in _TOKEN.finditer(sql):
        if match.start() != position:
            raise _error("unsupported table SQL syntax")
        position = match.end()
        token = match.group()
        if token.isspace():
            continue
        if token.startswith("'"):
            result.append(token)
        elif token[0] in '\"`[':
            result.append(token[1:-1].lower())
        else:
            result.append(token.lower())
    if position != len(sql):
        raise _error("unsupported table SQL syntax")
    return result


def _definitions(sql: str) -> list[list[str]]:
    tokens = _tokens(sql)
    if tokens[-1:] == [';']:
        tokens.pop()
    if tokens[:3] != ['create', 'table', 'instruments'] or tokens[3:4] != ['('] or tokens[-1:] != [')']:
        raise _error("unsupported table option or CREATE TABLE definition")
    definitions, current, depth = [], [], 0
    for token in tokens[4:-1]:
        if token == ',' and depth == 0:
            definitions.append(current)
            current = []
            continue
        current.append(token)
        depth += (token == '(') - (token == ')')
        if depth < 0:
            raise _error("unsupported table definition")
    definitions.append(current)
    if depth or any(not part for part in definitions):
        raise _error("unsupported table definition")
    return definitions


def _index_shape(connection, name: str) -> tuple[tuple[str | None, ...], bool]:
    keys = [row for row in connection.exec_driver_sql(f"PRAGMA main.index_xinfo({_quote(name)})") if row[5]]
    return tuple(row[2] for row in keys), all(row[1] >= 0 and row[3] == 0 and row[4] == 'BINARY' for row in keys)


def _identity(connection) -> str:
    full = set()
    for row in connection.exec_driver_sql('PRAGMA main.index_list("instruments")'):
        if not row[2]:
            continue
        name, partial = row[1], row[4]
        columns, simple = _index_shape(connection, name)
        if len(columns) == 2 and set(columns) in ({"market", "symbol"}, {"exchange", "symbol"}) and columns not in (("market", "symbol"), ("exchange", "symbol")):
            raise _error(f"noncanonical ordered identity index {name}")
        if columns in (("market", "symbol"), ("exchange", "symbol")):
            if partial or not simple:
                raise _error(f"partial/noncanonical identity index {name}")
            full.add(columns)
        elif None in columns:
            sql = connection.exec_driver_sql("SELECT sql FROM main.sqlite_schema WHERE type='index' AND name=?", (name,)).scalar() or ''
            if re.search(r'\b(market|exchange|symbol)\b', sql, re.I):
                raise _error(f"expression identity index {name}")
    if full == {("market", "symbol")}:
        return "legacy"
    if full == {("exchange", "symbol")}:
        return "current"
    raise _error("mixed or missing full instrument identity")


def _legacy_definitions(connection, sql: str) -> list[str]:
    xinfo = connection.exec_driver_sql('PRAGMA main.table_xinfo("instruments")').all()
    for row in xinfo:
        if row[6]:
            raise _error(f"generated/hidden column {row[1]}")
        if row[1] not in _COLUMNS:
            raise _error(f"unsupported column {row[1]}")
    parts = _definitions(sql)
    result, seen, pk_count, unique_count = [], set(), 0, 0
    for part in parts:
        if part[0] == 'constraint':
            if len(part) < 3:
                raise _error("unsupported named constraint")
            part = part[2:]
        if part == ['primary', 'key', '(', 'id', ')']:
            pk_count += 1
            result.append('PRIMARY KEY (id)')
            continue
        if part == ['unique', '(', 'market', ',', 'symbol', ')']:
            unique_count += 1
            continue
        name = part[0]
        if name not in _COLUMNS or name in seen:
            raise _error(f"unsupported column/constraint {name}")
        seen.add(name)
        definition = ' '.join(part[1:])
        allowed = {_COLUMNS[name]}
        if name == 'id':
            allowed.add('integer not null primary key')
            if definition.endswith('primary key'):
                pk_count += 1
        if name == 'is_watchlisted':
            # Both checked-in ORM legacy and the historical raw legacy fixture.
            allowed.add('boolean not null default 0')
        if definition not in allowed:
            raise _error(f"unsupported definition/default for column {name}")
        result.append(' '.join(part))
    if seen - set(_COLUMNS) or set(_COLUMNS) - seen - {'exchange', 'industry'} or pk_count != 1:
        raise _error("unsupported columns or primary key")
    # A full ordinary unique index is also an allowed legacy identity.
    if unique_count > 1:
        raise _error("duplicate legacy constraints")
    if [row[1] for row in sorted(xinfo, key=lambda item: item[5]) if row[5]] != ['id']:
        raise _error("unsupported primary key")
    return result


def _legacy_objects(connection) -> None:
    for row in connection.exec_driver_sql('PRAGMA main.index_list("instruments")'):
        name, unique, origin, partial = row[1:5]
        columns, simple = _index_shape(connection, name)
        if unique and columns == ('market', 'symbol') and simple and not partial:
            continue
        if unique or partial or not simple or name not in _INDEXES or columns != (_INDEXES[name],):
            raise _error(f"unsupported index {name}")
    objects = connection.exec_driver_sql("SELECT type,name,tbl_name,sql FROM main.sqlite_schema WHERE type IN ('trigger','view')").all()
    for kind, name, owner, sql in objects:
        if owner == 'instruments' or re.search(r'\binstruments\b', sql or '', re.I):
            raise _error(f"unsupported dependent {kind} {name}")
    if connection.exec_driver_sql('PRAGMA main.foreign_key_list("instruments")').first():
        raise _error("unsupported instruments outbound/self foreign key")
    tables = connection.exec_driver_sql("SELECT name,sql FROM main.sqlite_schema WHERE type='table'").all()
    for name, sql in tables:
        grouped = {}
        for row in connection.exec_driver_sql(f'PRAGMA main.foreign_key_list({_quote(name)})'):
            grouped.setdefault(row[0], []).append(row)
        for rows in grouped.values():
            if not any(row[2].lower() == 'instruments' for row in rows):
                continue
            row = rows[0]
            if (name not in _CHILDREN or len(rows) != 1 or tuple(row[3:8]) != ('instrument_id', 'id', 'NO ACTION', 'NO ACTION', 'NONE')
                    or re.search(r'\bDEFERRABLE\b', sql or '', re.I)):
                raise _error(f"unsupported inbound foreign key {name}")


def _check_existing_identity_claim(connection, objects, state: str) -> None:
    if state == 'current':
        return
    known_revisions = {
        '0002_instrument_exchange_key', '0003_backtest_run_metadata',
        '0004_product_news_themes', '0005_news_temporal_contract',
        '0006_news_json_defaults',
        '0007_turnover_availability',
        '0008_portfolio_share_integer',
    }
    marker_columns = {'alembic_version': 'version_num', 'schema_migrations': 'version'}
    for kind, name, sql in objects:
        column = marker_columns.get(name.lower())
        if kind == 'table' and column is not None:
            recorded = {row[0] for row in connection.exec_driver_sql(
                f'SELECT {_quote(column)} FROM main.{_quote(name)}'
            )}
            if known_revisions.intersection(recorded):
                raise _error('revision requires current identity; refusing to repair prior stamp')


def preflight_instrument_identity(connection) -> str:
    """Read-only gate; must run before 0001/create_all can mask old damage."""
    if connection.dialect.name != 'sqlite':
        return 'other'
    # SQLite object names are case-insensitive. Reject any kind of occupied
    # scratch name, including old variants, before looking for the parent.
    temporary = connection.exec_driver_sql("SELECT type,name FROM temp.sqlite_schema").all()
    for kind, name in temporary:
        if name.lower() == "instruments" or name.lower().startswith(SCRATCH):
            raise _error(f"unsupported TEMP shadow {kind} {name}")
    objects = connection.exec_driver_sql("SELECT type,name,sql FROM main.sqlite_schema").all()
    for kind, name, sql in objects:
        if name.lower().startswith(SCRATCH):
            raise _error(f"occupied scratch {kind} {name}; manual recovery required")
    table = next((row for row in objects if row[1].lower() == 'instruments'), None)
    if table is None:
        _check_existing_identity_claim(connection, objects, 'absent')
        return 'absent'
    if table[0] != 'table':
        raise _error(f"instruments is a {table[0]}, not a table")
    state = _identity(connection)
    _check_existing_identity_claim(connection, objects, state)
    columns = {row[1] for row in connection.exec_driver_sql('PRAGMA main.table_xinfo("instruments")')}
    exchange = '"exchange"' if 'exchange' in columns else "'TWSE'"
    if 'symbol' not in columns or (state == 'current' and 'exchange' not in columns):
        raise _error("missing identity columns")
    if connection.exec_driver_sql(f'SELECT 1 FROM "instruments" WHERE {exchange} IS NULL OR "symbol" IS NULL LIMIT 1').first():
        raise _error("NULL exchange/symbol")
    if connection.exec_driver_sql(f'SELECT 1 FROM "instruments" GROUP BY {exchange}, "symbol" HAVING COUNT(*) > 1 LIMIT 1').first():
        raise _error("duplicate exchange/symbol rows")
    if state == 'legacy':
        _legacy_definitions(connection, table[2] or '')
        _legacy_objects(connection)
    return state


def check_sqlite_migration_integrity(connection) -> None:
    """Whole-database guard, inside the caller's transaction before commit."""
    if connection.exec_driver_sql('PRAGMA integrity_check').scalar() != 'ok':
        raise RuntimeError('cannot migrate database: SQLite integrity_check failed')
    violations = connection.exec_driver_sql('PRAGMA foreign_key_check').fetchmany(3)
    if violations:
        raise RuntimeError(f'cannot migrate database: foreign-key violation(s): {violations!r}')


def rebuild_instrument_identity(connection) -> bool:
    """Replace only the validated identity, retaining known column definitions."""
    if preflight_instrument_identity(connection) != 'legacy':
        return False
    sql = connection.exec_driver_sql("SELECT sql FROM main.sqlite_schema WHERE type='table' AND name='instruments' COLLATE NOCASE").scalar_one()
    definitions = _legacy_definitions(connection, sql)
    columns = [row[1] for row in connection.exec_driver_sql('PRAGMA main.table_xinfo("instruments")')]
    if not {'exchange', 'industry'}.issubset(columns):
        raise _error('additive exchange/industry migration must run before rebuild')
    definitions.append('CONSTRAINT uq_instrument_exchange_symbol UNIQUE (exchange, symbol)')
    connection.exec_driver_sql(f'CREATE TABLE "{SCRATCH}" (' + ', '.join(definitions) + ')')
    names = ', '.join(_quote(name) for name in columns)
    connection.exec_driver_sql(f'INSERT INTO "{SCRATCH}" ({names}) SELECT {names} FROM "instruments"')
    connection.exec_driver_sql('DROP TABLE "instruments"')
    connection.exec_driver_sql(f'ALTER TABLE "{SCRATCH}" RENAME TO "instruments"')
    for name, column in _INDEXES.items():
        connection.exec_driver_sql(f'CREATE INDEX "{name}" ON "instruments" ("{column}")')
    if preflight_instrument_identity(connection) != 'current':
        raise _error('post-rebuild identity mismatch')
    return True
