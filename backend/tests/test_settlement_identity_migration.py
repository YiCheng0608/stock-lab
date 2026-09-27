"""Handwritten legacy data through real migration entrypoints and rollback."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError

from app import migrations
from app.settlement_identity_migration import preflight_settlement_identity

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = ['fallback', 'engine', 'connection']
REVISIONS = ['0001_schema_v1', '0002_instrument_exchange_key',
             '0003_backtest_run_metadata', '0004_product_news_themes',
             '0005_news_temporal_contract', '0006_news_json_defaults',
             '0007_turnover_availability']
ORIGINAL = '''id INTEGER NOT NULL PRIMARY KEY, signal_id INTEGER NOT NULL,
settlement_date DATE NOT NULL, final_status VARCHAR(80), first_trigger VARCHAR(120),
return_or_risk FLOAT, incomparable_reason TEXT, source VARCHAR(500), data_time VARCHAR(80)'''
ADDED = ''', horizon INTEGER NOT NULL DEFAULT 20, execution_date DATE,
execution_price FLOAT, comparable BOOLEAN, data_quality VARCHAR(30) NOT NULL DEFAULT 'complete' '''
FK = ', FOREIGN KEY(signal_id) REFERENCES signals(id)'


def _config(target):
    cfg = Config(str(ROOT / 'backend/alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'backend/alembic'))
    cfg.attributes['connection'] = target
    return cfg


def _run(engine, entry):
    if entry == 'fallback':
        with patch.object(migrations, 'ALEMBIC_CONFIG_PATH', str(Path(engine.url.database).parent / 'missing.ini')):
            migrations.upgrade_database(engine)
    elif entry == 'engine':
        migrations.upgrade_database(engine)
    else:
        with engine.connect() as c:
            try:
                command.upgrade(_config(c), 'head')
            finally:
                assert not c.in_transaction()


def _snapshot(engine):
    with engine.connect() as c:
        result = {'fk': c.exec_driver_sql('PRAGMA foreign_keys').scalar()}
        for schema in ('main', 'temp'):
            objects = c.exec_driver_sql(f'SELECT type,name,tbl_name,sql FROM {schema}.sqlite_schema ORDER BY type,name').all()
            tables = {}
            for kind, name, owner, sql in objects:
                if kind == 'table':
                    quoted = '"' + name.replace('"', '""') + '"'
                    rows = c.exec_driver_sql(f'SELECT * FROM {schema}.{quoted}').all()
                    tables[name] = sorted([tuple((type(v).__name__, v) for v in row) for row in rows], key=repr)
            result[schema] = (objects, tables)
        return result


def _fixture(tmp_path, fk, shape='legacy'):
    engine = create_engine('sqlite:///' + str(tmp_path / 'settlements.db'))
    with engine.begin() as c:
        c.exec_driver_sql('CREATE TABLE signals(id INTEGER NOT NULL PRIMARY KEY)')
        c.exec_driver_sql('INSERT INTO signals VALUES(1),(2)')
        body = ORIGINAL + ('' if shape == 'nine' else ADDED)
        unique = ', UNIQUE(signal_id,horizon)' if shape.startswith('current') else ', UNIQUE(signal_id)'
        if shape in ('ordinary_index', 'partial', 'expression', 'reverse', 'missing_unique'):
            unique = ''
        if shape == 'mixed':
            unique += ', UNIQUE(signal_id,horizon)'
        if shape == 'null_horizon':
            body = body.replace('horizon INTEGER NOT NULL DEFAULT 20', 'horizon INTEGER')
        if shape == 'extra':
            body += ', custom_note BLOB'
        if shape == 'default':
            body = body.replace('final_status VARCHAR(80)', "final_status VARCHAR(80) DEFAULT 'pending'")
        if shape == 'check':
            body += ', CHECK(return_or_risk>=0)'
        if shape == 'generated':
            body += ', custom_generated INTEGER GENERATED ALWAYS AS (signal_id+1)'
        if shape == 'autoincrement':
            body = body.replace('PRIMARY KEY', 'PRIMARY KEY AUTOINCREMENT')
        if shape == 'current_missing_default':
            body = body.replace('horizon INTEGER NOT NULL DEFAULT 20', 'horizon INTEGER NOT NULL')
        if shape == 'current_nullable':
            body = body.replace('horizon INTEGER NOT NULL DEFAULT 20', 'horizon INTEGER DEFAULT 20')
        if shape == 'current_quoted_default':
            body = body.replace('DEFAULT 20', "DEFAULT '20'")
        foreign = FK + (' DEFERRABLE INITIALLY DEFERRED' if shape == 'deferrable' else '')
        if shape == 'fk_action':
            foreign += ' ON DELETE CASCADE'
        if shape == 'outbound':
            foreign += ', FOREIGN KEY(id) REFERENCES signals(id)'
        ddl = 'CREATE TABLE signal_settlements (' + body + unique + foreign + ')'
        if shape == 'without_rowid':
            ddl += ' WITHOUT ROWID'
        c.exec_driver_sql(ddl)
        names = 'id,signal_id,settlement_date,final_status,first_trigger,return_or_risk,incomparable_reason,source,data_time'
        values = (7, 1, '2026-01-20', '完成', 'target', 1.25, b'\x00\xca\xfe', 'source', 'clock')
        if shape != 'nine':
            names += ',horizon,execution_date,execution_price,comparable,data_quality'
            values += (None if shape == 'null_horizon' else 5, '2026-01-02', 99.5, 1, 'complete')
        c.exec_driver_sql(f'INSERT INTO signal_settlements({names}) VALUES(' + ','.join('?' for _ in values) + ')', values)
        statements = {
            'ordinary_index': 'CREATE UNIQUE INDEX old_identity ON signal_settlements(signal_id)',
            'partial': 'CREATE UNIQUE INDEX old_identity ON signal_settlements(signal_id) WHERE horizon=5',
            'expression': 'CREATE UNIQUE INDEX old_identity ON signal_settlements(abs(signal_id))',
            'reverse': 'CREATE UNIQUE INDEX old_identity ON signal_settlements(horizon,signal_id)',
            'custom_index': 'CREATE INDEX custom_payload ON signal_settlements(source)',
            'view': 'CREATE VIEW settlement_view AS SELECT * FROM signal_settlements',
            'trigger': 'CREATE TRIGGER settlement_trigger AFTER UPDATE ON signal_settlements BEGIN SELECT 1; END',
            'scratch': 'CREATE TABLE signal_settlements__v1_rebuild(note TEXT)',
            'scratch_suffix': 'CREATE TABLE SIGNAL_SETTLEMENTS__V1_REBUILD_old(note TEXT)',
            'temp_scratch': 'CREATE TEMP TABLE signal_settlements__v1_rebuild(note TEXT)',
            'temp_shadow': 'CREATE TEMP TABLE signal_settlements(note TEXT)',
            'inbound': 'CREATE TABLE child(id INTEGER REFERENCES signal_settlements(id))',
        }
        if shape in statements:
            c.exec_driver_sql(statements[shape])
        if shape in ('scratch', 'scratch_suffix', 'temp_scratch'):
            name = 'SIGNAL_SETTLEMENTS__V1_REBUILD_old' if shape == 'scratch_suffix' else 'signal_settlements__v1_rebuild'
            c.exec_driver_sql(f"INSERT INTO {name} VALUES('DO NOT DELETE')")
        if shape == 'missing_parent':
            c.exec_driver_sql('DROP TABLE signals')
        if shape == 'bad_horizon':
            c.exec_driver_sql("UPDATE signal_settlements SET horizon=x'3230'")
        if shape == 'current_extra':
            c.exec_driver_sql("ALTER TABLE signal_settlements ADD COLUMN custom_blob BLOB DEFAULT X'CAFE'")
            c.exec_driver_sql('CREATE INDEX custom_payload ON signal_settlements(source)')
            c.exec_driver_sql('CREATE VIEW settlement_view AS SELECT * FROM signal_settlements')
            c.exec_driver_sql('CREATE TRIGGER settlement_trigger AFTER UPDATE ON signal_settlements BEGIN SELECT 1; END')
    with engine.connect() as c:
        c.exec_driver_sql(f'PRAGMA foreign_keys={fk}')
        c.commit()
    return engine


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('shape', ['nine', 'legacy', 'null_horizon', 'ordinary_index', 'current', 'current_extra', 'current_quoted_default'])
def test_payload_identity_defaults_and_idempotence(tmp_path, entry, fk, shape):
    engine = _fixture(tmp_path, fk, shape)
    before = _snapshot(engine)
    _run(engine, entry)
    with engine.connect() as c:
        assert preflight_settlement_identity(c) == 'current'
        row = c.exec_driver_sql('SELECT id,signal_id,settlement_date,final_status,first_trigger,return_or_risk,incomparable_reason,source,data_time,horizon,execution_date,execution_price,comparable,data_quality FROM signal_settlements').one()
        assert tuple(row) == (7, 1, '2026-01-20', '完成', 'target', 1.25, b'\x00\xca\xfe', 'source', 'clock', 20 if shape in ('nine', 'null_horizon') else 5, None if shape == 'nine' else '2026-01-02', None if shape == 'nine' else 99.5, None if shape == 'nine' else 1, 'complete')
        c.exec_driver_sql("INSERT INTO signal_settlements(id,signal_id,horizon,settlement_date) VALUES(8,1,99,'2026-02-01')")
        with pytest.raises(IntegrityError):
            c.exec_driver_sql("INSERT INTO signal_settlements(id,signal_id,horizon,settlement_date) VALUES(9,1,99,'2026-02-01')")
        c.exec_driver_sql("INSERT INTO signal_settlements(id,signal_id,settlement_date) VALUES(10,2,'2026-02-01')")
        assert tuple(c.exec_driver_sql('SELECT horizon,typeof(horizon),data_quality FROM signal_settlements WHERE id=10').one()) == (20, 'integer', 'complete')
        c.rollback()
        assert c.exec_driver_sql('PRAGMA foreign_keys').scalar() == fk
    if shape == 'current_extra':
        after = _snapshot(engine)
        assert [r for r in before['main'][0] if r[2]=='signal_settlements' or r[1]=='settlement_view'] == [r for r in after['main'][0] if r[2]=='signal_settlements' or r[1]=='settlement_view']
        assert before['main'][1]['signal_settlements'] == after['main'][1]['signal_settlements']
    _run(engine, entry)
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT count(*) FROM signal_settlements').scalar() == 1
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('shape', ['extra', 'default', 'check', 'generated', 'autoincrement', 'without_rowid', 'custom_index', 'view', 'trigger', 'scratch', 'scratch_suffix', 'temp_scratch', 'temp_shadow', 'inbound', 'outbound', 'fk_action', 'deferrable', 'missing_parent', 'bad_horizon', 'mixed', 'partial', 'expression', 'reverse', 'missing_unique', 'current_missing_default', 'current_nullable'])
def test_unsupported_refuses_before_ddl(tmp_path, entry, fk, shape):
    engine = _fixture(tmp_path, fk, shape)
    before = _snapshot(engine)
    writes = []
    def record(c, cursor, sql, params, context, many):
        if sql.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'DROP ', 'INSERT ', 'UPDATE ', 'DELETE ')):
            writes.append(sql)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        with pytest.raises(RuntimeError, match='cannot migrate signal_settlements'):
            _run(engine, entry)
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert writes == []
    assert _snapshot(engine) == before
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('family', ['alembic_version', 'schema_migrations'])
@pytest.mark.parametrize('revision', REVISIONS)
@pytest.mark.parametrize('state', ['absent', 'legacy'])
def test_false_revision_claims_are_not_salvaged(tmp_path, entry, fk, family, revision, state):
    engine = _fixture(tmp_path, fk)
    with engine.begin() as c:
        if state == 'absent':
            c.exec_driver_sql('DROP TABLE signal_settlements')
        # Isolate settlement claims from the earlier instrument identity gate.
        c.exec_driver_sql('CREATE TABLE instruments(id INTEGER PRIMARY KEY,exchange TEXT NOT NULL,symbol TEXT NOT NULL,UNIQUE(exchange,symbol))')
        column = 'version_num' if family == 'alembic_version' else 'version'
        c.exec_driver_sql(f'CREATE TABLE {family}({column} TEXT PRIMARY KEY)')
        c.exec_driver_sql(f'INSERT INTO {family} VALUES(?)', (revision,))
    before = _snapshot(engine)
    with pytest.raises(RuntimeError, match='revision requires current identity'):
        _run(engine, entry)
    assert _snapshot(engine) == before
    engine.dispose()


def _stage(sql):
    sql = ' '.join(sql.lower().split())
    if sql.startswith('create table "signal_settlements__v1_rebuild"'): return 'create'
    if sql.startswith('insert into "signal_settlements__v1_rebuild"'): return 'copy'
    if sql.startswith('drop table "signal_settlements"'): return 'drop'
    if sql.startswith('alter table "signal_settlements__v1_rebuild"'): return 'rename'
    if sql.startswith('create index "ix_signal_settlements_signal_id"'): return 'index_signal'
    if sql.startswith('create index "ix_signal_settlements_settlement_date"'): return 'index_date'
    if sql.startswith(('insert', 'update')) and ('alembic_version' in sql or 'schema_migrations' in sql): return 'marker'


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('when', ['before', 'after'])
@pytest.mark.parametrize('point', ['create', 'copy', 'drop', 'rename', 'index_signal', 'index_date', 'marker'])
def test_faults_restore_entire_database_and_retry(tmp_path, entry, fk, when, point):
    engine = _fixture(tmp_path, fk, 'nine')
    before = _snapshot(engine)
    hit = []
    def fail(c, cursor, sql, params, context, many):
        if not hit and _stage(sql) == point:
            hit.append(sql)
            raise RuntimeError('injected settlement fault')
    event.listen(engine, when + '_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='injected settlement fault'):
            _run(engine, entry)
    finally:
        event.remove(engine, when + '_cursor_execute', fail)
    assert len(hit) == 1
    assert _snapshot(engine) == before
    _run(engine, entry)
    with engine.connect() as c:
        assert preflight_settlement_identity(c) == 'current'
        assert c.exec_driver_sql('SELECT id FROM signal_settlements').scalar() == 7
        assert c.exec_driver_sql('PRAGMA foreign_keys').scalar() == fk
    engine.dispose()


def test_active_connection_is_not_committed(tmp_path):
    engine = _fixture(tmp_path, 1, 'nine')
    before = _snapshot(engine)
    with engine.connect() as c:
        c.exec_driver_sql("UPDATE signals SET id=3 WHERE id=2")
        with pytest.raises(RuntimeError, match='inactive caller connection'):
            command.upgrade(_config(c), 'head')
        assert c.in_transaction()
        c.rollback()
    assert _snapshot(engine) == before
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('when', ['before', 'after'])
def test_late_revision_fault_still_restores_settlement_rebuild(tmp_path, entry, fk, when):
    engine = _fixture(tmp_path, fk, 'nine')
    before = _snapshot(engine)
    hit = []
    def fail(c, cursor, sql, params, context, many):
        if not hit and sql.lstrip().lower().startswith(('insert', 'update')) and '0006_news_json_defaults' in sql:
            hit.append(sql)
            raise RuntimeError('injected late revision')
    event.listen(engine, when + '_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='injected late revision'):
            _run(engine, entry)
    finally:
        event.remove(engine, when + '_cursor_execute', fail)
    assert hit
    assert _snapshot(engine) == before
    _run(engine, entry)
    with engine.connect() as c:
        assert preflight_settlement_identity(c) == 'current'
    engine.dispose()


def test_news_slice_prerequisites_are_empty_and_current(tmp_path):
    from test_news_json_defaults import _old_005_engine
    from test_migration_recovery import _load_fixed_fixture
    first = _old_005_engine(tmp_path)
    path = tmp_path / 'slice.db'
    _load_fixed_fixture(path)
    second = create_engine('sqlite:///' + str(path))
    for engine in (first, second):
        with engine.connect() as c:
            assert preflight_settlement_identity(c) == 'current'
            assert c.exec_driver_sql('SELECT count(*) FROM signals').scalar() == 0
            assert c.exec_driver_sql('SELECT count(*) FROM signal_settlements').scalar() == 0
        engine.dispose()
