"""Finite SQLite settlement identity gate; the migration runner owns atomicity."""
from __future__ import annotations

import re

TABLE = 'signal_settlements'
SCRATCH = TABLE + '__v1_rebuild'
ORIGINAL = {
    'id': 'integer not null',
    'signal_id': 'integer not null',
    'settlement_date': 'date not null',
    'final_status': 'varchar ( 80 )',
    'first_trigger': 'varchar ( 120 )',
    'return_or_risk': 'float',
    'incomparable_reason': 'text',
    'source': 'varchar ( 500 )',
    'data_time': 'varchar ( 80 )',
}
ADDED = {
    'horizon': 'integer not null default 20',
    'execution_date': 'date',
    'execution_price': 'float',
    'comparable': 'boolean',
    'data_quality': "varchar ( 30 ) not null default 'complete'",
}
COLUMNS = {name: (ORIGINAL | ADDED)[name] for name in (
    'id', 'signal_id', 'horizon', 'settlement_date', 'final_status',
    'first_trigger', 'return_or_risk', 'incomparable_reason', 'source',
    'data_time', 'execution_date', 'execution_price', 'comparable', 'data_quality',
)}
INDEXES = {'ix_signal_settlements_signal_id': 'signal_id',
           'ix_signal_settlements_settlement_date': 'settlement_date'}
REVISIONS = {'0001_schema_v1', '0002_instrument_exchange_key',
             '0003_backtest_run_metadata', '0004_product_news_themes',
             '0005_news_temporal_contract', '0006_news_json_defaults',
             '0007_turnover_availability', '0008_portfolio_share_integer'}
_TOKEN = re.compile(r"\s+|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^]]*\]|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[(),;]")


def _error(reason):
    return RuntimeError(f'cannot migrate signal_settlements: {reason}')


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _definitions(sql):
    """Parse only the legacy vocabulary, never rewrite arbitrary SQLite SQL."""
    tokens, position = [], 0
    for match in _TOKEN.finditer(sql):
        if match.start() != position:
            raise _error('unsupported table SQL syntax')
        position = match.end()
        token = match.group()
        if token.isspace():
            continue
        tokens.append(token if token.startswith("'") else
                      token[1:-1].lower() if token[0] in '\"`[' else token.lower())
    if position != len(sql):
        raise _error('unsupported table SQL syntax')
    if tokens[-1:] == [';']:
        tokens.pop()
    if tokens[:4] != ['create', 'table', TABLE, '('] or tokens[-1:] != [')']:
        raise _error('unsupported table option or definition')
    parts, current, depth = [], [], 0
    for token in tokens[4:-1]:
        if token == ',' and depth == 0:
            parts.append(current)
            current = []
            continue
        current.append(token)
        depth += (token == '(') - (token == ')')
        if depth < 0:
            raise _error('unsupported table definition')
    parts.append(current)
    if depth or any(not p for p in parts):
        raise _error('unsupported table definition')
    return parts


def _index_shape(connection, name):
    rows = [r for r in connection.exec_driver_sql(f'PRAGMA main.index_xinfo({_quote(name)})') if r[5]]
    return tuple(r[2] for r in rows), all(r[1] >= 0 and r[3] == 0 and r[4] == 'BINARY' for r in rows)


def _identity(connection):
    identities = set()
    for row in connection.exec_driver_sql(f'PRAGMA main.index_list("{TABLE}")'):
        if not row[2]:
            continue
        columns, simple = _index_shape(connection, row[1])
        if columns in (('signal_id',), ('signal_id', 'horizon')):
            if row[4] or not simple:
                raise _error('partial/noncanonical identity index')
            identities.add(columns)
        elif set(columns) & {'signal_id', 'horizon'} or None in columns:
            raise _error('unsupported unique identity index')
    if identities == {('signal_id',)}:
        return 'legacy'
    if identities == {('signal_id', 'horizon')}:
        return 'current'
    raise _error('mixed or missing full ordered identity')


def _foreign_key(connection, sql):
    rows = connection.exec_driver_sql(f'PRAGMA main.foreign_key_list("{TABLE}")').all()
    if (len(rows) != 1 or tuple(rows[0][1:]) != (0, 'signals', 'signal_id', 'id', 'NO ACTION', 'NO ACTION', 'NONE')
            or re.search(r'\bDEFERRABLE\b', sql, re.I)):
        raise _error('unsupported outbound/self foreign key')
    parent = connection.exec_driver_sql("SELECT 1 FROM main.sqlite_schema WHERE type='table' AND name='signals' COLLATE NOCASE").first()
    if not parent:
        raise _error('missing signals parent')


def _legacy(connection, sql, columns):
    if set(columns) not in (set(ORIGINAL), set(COLUMNS)):
        raise _error('unsupported legacy columns')
    pk, unique, foreign, seen = 0, 0, 0, set()
    for part in _definitions(sql):
        if part[0] == 'constraint':
            part = part[2:]
        if part == ['primary', 'key', '(', 'id', ')']:
            pk += 1
            continue
        if part == ['unique', '(', 'signal_id', ')']:
            unique += 1
            continue
        if part == ['foreign', 'key', '(', 'signal_id', ')', 'references', 'signals', '(', 'id', ')']:
            foreign += 1
            continue
        if not part or part[0] not in COLUMNS or part[0] in seen:
            raise _error('unsupported legacy column/constraint')
        name = part[0]
        seen.add(name)
        definition = ' '.join(part[1:])
        allowed = {COLUMNS[name]}
        if name == 'id':
            allowed.add('integer not null primary key')
            pk += definition.endswith('primary key')
        if name == 'signal_id':
            allowed.add('integer not null unique')
            unique += definition.endswith('unique')
        if name == 'horizon':
            allowed.update({'integer', 'integer default 20', "integer default '20'", "integer not null default '20'"})
        if definition not in allowed:
            raise _error(f'unsupported definition/default for {name}')
    if seen != set(columns) or pk != 1 or unique > 1 or foreign != 1:
        raise _error('unsupported legacy constraints')
    for row in connection.exec_driver_sql(f'PRAGMA main.index_list("{TABLE}")'):
        name, unique, origin, partial = row[1:5]
        shape, simple = _index_shape(connection, name)
        if unique and shape == ('signal_id',) and simple and not partial:
            continue
        if unique or partial or not simple or name not in INDEXES or shape != (INDEXES[name],):
            raise _error(f'unsupported legacy index {name}')
    for kind, name, owner, body in connection.exec_driver_sql("SELECT type,name,tbl_name,sql FROM main.sqlite_schema WHERE type IN ('trigger','view')"):
        if owner.lower() == TABLE or re.search(r'\bsignal_settlements\b', body or '', re.I):
            raise _error(f'unsupported dependent {kind} {name}')
    for (name,) in connection.exec_driver_sql("SELECT name FROM main.sqlite_schema WHERE type='table'"):
        if any(r[2].lower() == TABLE for r in connection.exec_driver_sql(f'PRAGMA main.foreign_key_list({_quote(name)})')):
            raise _error(f'unsupported legacy inbound foreign key {name}')


def _current(columns):
    if not set(COLUMNS).issubset(columns):
        raise _error('missing current columns')
    for name, definition in COLUMNS.items():
        row = columns[name]
        expected_type = definition.split(' not null')[0].split(' default')[0].replace(' ', '').upper()
        if row[2].replace(' ', '').upper() != expected_type or row[6]:
            raise _error(f'unsupported current column {name}')
        if name in ('id', 'signal_id', 'horizon', 'settlement_date', 'data_quality') and not row[3]:
            raise _error(f'missing current NOT NULL {name}')
        expected_default = '20' if name == 'horizon' else 'complete' if name == 'data_quality' else None
        value = row[4]
        if value is not None:
            value = str(value).strip()
            while value.startswith('(') and value.endswith(')'):
                value = value[1:-1].strip()
            if value.startswith("'") and value.endswith("'"):
                value = value[1:-1].replace("''", "'")
        if value != expected_default:
            raise _error(f'unsupported current default {name}')


def preflight_settlement_identity(connection):
    """Read-only gate before create_all, DDL or trusting revision markers."""
    if connection.dialect.name != 'sqlite':
        return 'other'
    for kind, name in connection.exec_driver_sql('SELECT type,name FROM temp.sqlite_schema'):
        if name.lower() == TABLE or name.lower().startswith(SCRATCH):
            raise _error(f'unsupported TEMP shadow {kind} {name}')
    objects = connection.exec_driver_sql('SELECT type,name,sql FROM main.sqlite_schema').all()
    if any(name.lower().startswith(SCRATCH) for kind, name, sql in objects):
        raise _error('occupied scratch; manual recovery required')
    table = next((r for r in objects if r[1].lower() == TABLE), None)
    state = 'absent'
    if table is not None:
        if table[0] != 'table':
            raise _error('settlements is not a table')
        state = _identity(connection)
        columns = {r[1]: r for r in connection.exec_driver_sql(f'PRAGMA main.table_xinfo("{TABLE}")')}
        if [r[1] for r in sorted(columns.values(), key=lambda r: r[5]) if r[5]] != ['id']:
            raise _error('unsupported primary key')
        if any(r[6] for r in columns.values()) and state == 'legacy':
            raise _error('unsupported generated/hidden column')
        _foreign_key(connection, table[2] or '')
        if state == 'legacy':
            _legacy(connection, table[2] or '', columns)
        else:
            _current(columns)
        if 'horizon' in columns and connection.exec_driver_sql(f'SELECT 1 FROM "{TABLE}" WHERE horizon IS NOT NULL AND typeof(horizon) != \'integer\' LIMIT 1').first():
            raise _error('non-integer horizon')
        if connection.exec_driver_sql(f'SELECT 1 FROM "{TABLE}" WHERE id IS NULL OR signal_id IS NULL LIMIT 1').first():
            raise _error('NULL identity')
        if state == 'current' and connection.exec_driver_sql(f'SELECT 1 FROM "{TABLE}" WHERE horizon IS NULL OR data_quality IS NULL LIMIT 1').first():
            raise _error('NULL current identity/quality')
        if state == 'current' and connection.exec_driver_sql(f'SELECT 1 FROM "{TABLE}" GROUP BY signal_id,horizon HAVING COUNT(*)>1 LIMIT 1').first():
            raise _error('duplicate current pair')
    if state != 'current':
        for kind, name, sql in objects:
            marker_column = {'alembic_version': 'version_num', 'schema_migrations': 'version'}.get(name.lower())
            if kind == 'table' and marker_column:
                recorded = {r[0] for r in connection.exec_driver_sql(f'SELECT {_quote(marker_column)} FROM main.{_quote(name)}')}
                if recorded & REVISIONS:
                    raise _error('revision requires current identity; refusing to repair prior stamp')
    return state


def rebuild_settlement_identity(connection):
    if preflight_settlement_identity(connection) != 'legacy':
        return False
    columns = {r[1] for r in connection.exec_driver_sql(f'PRAGMA main.table_xinfo("{TABLE}")')}
    definitions = [f'{_quote(name)} {definition}' for name, definition in COLUMNS.items()]
    definitions += ['PRIMARY KEY (id)', 'CONSTRAINT uq_signal_settlement_horizon UNIQUE (signal_id,horizon)',
                    'FOREIGN KEY(signal_id) REFERENCES signals(id)']
    connection.exec_driver_sql(f'CREATE TABLE "{SCRATCH}" (' + ','.join(definitions) + ')')
    expressions = []
    for name in COLUMNS:
        if name == 'horizon':
            expressions.append('COALESCE("horizon",20)' if name in columns else '20')
        elif name in columns:
            expressions.append(_quote(name))
        else:
            expressions.append("'complete'" if name == 'data_quality' else 'NULL')
    connection.exec_driver_sql(f'INSERT INTO "{SCRATCH}" (' + ','.join(map(_quote,COLUMNS)) + ') SELECT ' + ','.join(expressions) + f' FROM "{TABLE}"')
    connection.exec_driver_sql(f'DROP TABLE "{TABLE}"')
    connection.exec_driver_sql(f'ALTER TABLE "{SCRATCH}" RENAME TO "{TABLE}"')
    for name, column in INDEXES.items():
        connection.exec_driver_sql(f'CREATE INDEX "{name}" ON "{TABLE}" ({_quote(column)})')
    if preflight_settlement_identity(connection) != 'current':
        raise _error('post-rebuild identity mismatch')
    return True
