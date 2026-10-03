"""Real SQLite rebuild/failure tests for the finite instrument contract."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError

from app import instrument_identity_migration as identity
from app import migrations
from app.db import Base
from app import models  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
ENTRIES = ['engine', 'external', 'fallback']
CHILDREN = ['group_memberships', 'market_bars', 'chip_snapshots', 'technical_features',
            'signals', 'portfolio_positions', 'corporate_actions', 'fundamental_snapshots', 'events']
HEAD = '0008_portfolio_share_integer'
DDL = '''CREATE TABLE instruments (
 id INTEGER NOT NULL PRIMARY KEY, market VARCHAR(20) NOT NULL,
 exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE', symbol VARCHAR(30) NOT NULL,
 name VARCHAR(120) NOT NULL, instrument_type VARCHAR(20) NOT NULL,
 etf_category VARCHAR(30), industry VARCHAR(120), listing_date DATE,
 is_watchlisted BOOLEAN NOT NULL DEFAULT 0, status VARCHAR(20) NOT NULL,
 created_at DATETIME NOT NULL, CONSTRAINT uq_instrument_market_symbol UNIQUE (market, symbol))'''


def _config(target):
    cfg = Config(str(ROOT / 'backend/alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'backend/alembic'))
    cfg.attributes['connection'] = target
    return cfg


def _run(engine, entry):
    if entry == 'engine':
        migrations.upgrade_database(engine)
    elif entry == 'fallback':
        migrations._fallback_upgrade(engine)
    else:
        with engine.connect() as connection:
            try:
                command.upgrade(_config(connection), 'head')
            finally:
                assert not connection.in_transaction()


def _snapshot(engine, label):
    # Independent reader; no SQLAlchemy conversion of SQLite storage types.
    with sqlite3.connect(engine.url.database) as connection:
        schema = connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        tables = {}
        for kind, name, owner, sql in schema:
            if kind != 'table':
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            rows = connection.execute('SELECT * FROM ' + quoted).fetchall()
            typed = [[(type(v).__name__, v.hex() if isinstance(v, bytes) else v) for v in row] for row in rows]
            tables[name] = {
                'columns': connection.execute('PRAGMA table_xinfo(' + quoted + ')').fetchall(),
                'foreign_keys': connection.execute('PRAGMA foreign_key_list(' + quoted + ')').fetchall(),
                'rows': sorted(typed, key=repr),
            }
        health = {}
        for pragma in ('integrity_check', 'foreign_key_check'):
            try:
                health[pragma] = connection.execute('PRAGMA ' + pragma).fetchall()
            except sqlite3.DatabaseError as error:
                # Some deliberately unsupported FK definitions are themselves
                # invalid; record the same diagnostic before/after rejection.
                health[pragma] = {'error': type(error).__name__, 'message': str(error)}
        snapshot = {'schema': schema, 'tables': tables, 'health': health}
    (Path(engine.url.database).parent / (label + '.json')).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf8')
    return snapshot


def _fixture(tmp_path, fk, variant='plain', *, children=True):
    engine = create_engine('sqlite:///' + str(tmp_path / 'instruments.db'))
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE instruments')
        ddl = DDL
        if variant == 'missing':
            ddl = ddl.replace(" exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE',", '').replace(' industry VARCHAR(120),', '')
        elif variant == 'current':
            ddl = ddl.replace('uq_instrument_market_symbol UNIQUE (market, symbol)', 'uq_instrument_exchange_symbol UNIQUE (exchange, symbol)')
        elif variant == 'column':
            ddl = ddl.replace('CONSTRAINT uq_', "custom_payload BLOB DEFAULT X'CAFE', CONSTRAINT uq_")
        elif variant == 'generated':
            ddl = ddl.replace('CONSTRAINT uq_', 'custom_length INTEGER GENERATED ALWAYS AS (length(symbol)) STORED, CONSTRAINT uq_')
        elif variant == 'default':
            ddl = ddl.replace('name VARCHAR(120) NOT NULL', "name VARCHAR(120) NOT NULL DEFAULT 'custom'")
        elif variant == 'check':
            ddl = ddl.replace('CONSTRAINT uq_', 'CHECK(length(symbol)>1), CONSTRAINT uq_')
        elif variant == 'self_fk':
            ddl = ddl.replace('CONSTRAINT uq_', 'FOREIGN KEY(id) REFERENCES instruments(id), CONSTRAINT uq_')
        elif variant == 'autoincrement':
            ddl = ddl.replace('PRIMARY KEY', 'PRIMARY KEY AUTOINCREMENT', 1)
        elif variant == 'without_rowid':
            ddl += ' WITHOUT ROWID'
        elif variant == 'nullable':
            ddl = ddl.replace('name VARCHAR(120) NOT NULL', 'name VARCHAR(120)')
        elif variant == 'neither' or variant == 'partial_legacy':
            ddl = ddl.replace(', CONSTRAINT uq_instrument_market_symbol UNIQUE (market, symbol)', '')
        c.exec_driver_sql(ddl)
        if variant == 'missing':
            c.exec_driver_sql("INSERT INTO instruments(id,market,symbol,name,instrument_type,status,created_at) VALUES(7,'TW','2330','台積電','stock','active','2020-01-01')")
        else:
            c.exec_driver_sql("INSERT INTO instruments(id,market,exchange,symbol,name,instrument_type,status,created_at,industry) VALUES(7,'TW','TPEx','2330','台積電','stock','active','2020-01-01',X'00CAFE')")
        statements = {
            'index': 'CREATE INDEX custom_instrument_name ON instruments(name)',
            'partial_index': "CREATE INDEX custom_instrument_name ON instruments(name) WHERE status='active'",
            'expression_index': 'CREATE INDEX custom_instrument_name ON instruments(lower(name))',
            'spoof_index': 'CREATE INDEX ix_instruments_symbol ON instruments(name)',
            'partial_legacy': "CREATE UNIQUE INDEX old_partial ON instruments(market,symbol) WHERE status='active'",
            'partial_target': "CREATE UNIQUE INDEX new_partial ON instruments(exchange,symbol) WHERE status='active'",
            'expression_target': 'CREATE UNIQUE INDEX expression_target ON instruments(lower(exchange),symbol)',
            'mixed': 'CREATE UNIQUE INDEX new_full ON instruments(exchange,symbol)',
            'collated_identity': 'CREATE UNIQUE INDEX custom_target ON instruments(exchange COLLATE NOCASE,symbol)',
            'view': 'CREATE VIEW instrument_view AS SELECT * FROM instruments',
        }
        if variant in statements:
            c.exec_driver_sql(statements[variant])
        if variant in ('trigger', 'external_trigger', 'current'):
            c.exec_driver_sql('CREATE TABLE audit(payload TEXT)')
            if variant == 'external_trigger':
                c.exec_driver_sql('CREATE TRIGGER external_reference AFTER INSERT ON audit BEGIN UPDATE instruments SET name=NEW.payload; END')
            else:
                c.exec_driver_sql('CREATE TRIGGER instrument_audit AFTER UPDATE ON instruments BEGIN INSERT INTO audit VALUES(NEW.name); END')
        if variant == 'current':
            c.exec_driver_sql('ALTER TABLE instruments ADD COLUMN custom_blob BLOB DEFAULT X\'CAFE\'')
            c.exec_driver_sql('CREATE INDEX current_custom ON instruments(name)')
        if variant in ('scratch', 'absent_scratch'):
            c.exec_driver_sql('CREATE TABLE instruments__v1_rebuild(payload BLOB)')
            c.exec_driver_sql("INSERT INTO instruments__v1_rebuild VALUES(X'00CAFE')")
            if variant == 'absent_scratch':
                c.exec_driver_sql('DROP TABLE instruments')
        if variant == 'scratch_view':
            c.exec_driver_sql('CREATE VIEW INSTRUMENTS__V1_REBUILD AS SELECT 1 AS payload')
        if variant == 'scratch_index':
            c.exec_driver_sql('CREATE INDEX instruments__v1_rebuild ON instruments(name)')
        if variant == 'unknown_child':
            c.exec_driver_sql('CREATE TABLE unknown_child(id INTEGER, instrument_id INTEGER REFERENCES instruments(id))')
            c.exec_driver_sql('INSERT INTO unknown_child VALUES(3,7)')
        if variant == 'duplicate':
            c.exec_driver_sql("INSERT INTO instruments SELECT 8,'US',exchange,symbol,name,instrument_type,etf_category,industry,listing_date,is_watchlisted,status,created_at FROM instruments")
        if children and variant != 'absent_scratch':
            # Real application tables, with all nine inbound FK descriptors.
            # Populate all nine and their required parents using typed values.
            wanted = set(CHILDREN) | {'theme_groups'}
            for table in Base.metadata.sorted_tables:
                if table.name not in wanted:
                    continue
                values = {}
                for column in table.columns:
                    if column.nullable:
                        continue
                    if column.name == 'instrument_id':
                        values[column.name] = 7
                    elif column.foreign_keys:
                        values[column.name] = 'fixture'
                    elif column.default is not None:
                        continue
                    else:
                        typ = column.type.python_type
                        values[column.name] = {int: 11, float: 1.25, bool: False, str: 'fixture', date: date(2020,1,2), datetime: datetime(2020,1,2), dict: {}, list: []}[typ]
                if table.name == 'events':
                    values['instrument_id'] = 7
                c.execute(table.insert().values(**values))
    with engine.connect() as c:
        c.exec_driver_sql(f'PRAGMA foreign_keys={fk}')
        c.commit()
    return engine


def _fk(engine):
    with engine.connect() as c:
        return c.exec_driver_sql('PRAGMA foreign_keys').scalar()


def _assert_head(engine, entry):
    with engine.connect() as c:
        assert c.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
        assert c.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert identity.preflight_instrument_identity(c) == 'current'
        if entry == 'fallback':
            assert len(c.exec_driver_sql('SELECT version FROM schema_migrations').all()) == 8
            assert c.exec_driver_sql('SELECT version FROM schema_migrations WHERE version=?', (HEAD,)).scalar() == HEAD
        else:
            assert c.exec_driver_sql('SELECT version_num FROM alembic_version').all() == [(HEAD,)]


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('variant', ['plain', 'missing', 'current'])
def test_success_preserves_typed_rows_all_known_children_and_repeats(tmp_path, entry, fk, variant):
    engine = _fixture(tmp_path, fk, variant)
    before = _snapshot(engine, 'before')
    _run(engine, entry)
    after = _snapshot(engine, 'after')
    assert _fk(engine) == fk
    _assert_head(engine, entry)
    for name in CHILDREN:
        assert before['tables'][name] == after['tables'][name]
    old_columns = [row[1] for row in before['tables']['instruments']['columns']]
    new_columns = [row[1] for row in after['tables']['instruments']['columns']]
    positions = [new_columns.index(name) for name in old_columns]
    assert [[row[i] for i in positions] for row in after['tables']['instruments']['rows']] == before['tables']['instruments']['rows']
    if variant == 'current':
        assert before['tables']['instruments'] == after['tables']['instruments']
        assert [x for x in before['schema'] if x[2]=='instruments'] == [x for x in after['schema'] if x[2]=='instruments']
    with engine.begin() as c:
        exchange = c.exec_driver_sql('SELECT exchange FROM instruments').scalar()
        if variant == 'missing':
            assert exchange == 'TWSE'
        with pytest.raises(IntegrityError):
            c.exec_driver_sql('INSERT INTO instruments(id,market,exchange,symbol,name,instrument_type,is_watchlisted,status,created_at) SELECT 8,market,exchange,symbol,name,instrument_type,is_watchlisted,status,created_at FROM instruments WHERE id=7')
        c.exec_driver_sql("INSERT INTO instruments(id,market,exchange,symbol,name,instrument_type,is_watchlisted,status,created_at) SELECT 8,market,'OTHER',symbol,name,instrument_type,is_watchlisted,status,created_at FROM instruments WHERE id=7")
    first = _snapshot(engine, 'before-repeat')
    _run(engine, entry)
    second = _snapshot(engine, 'after-repeat')
    if entry == 'fallback':
        for snapshot in (first, second):
            snapshot['tables']['schema_migrations']['rows'] = [row[:1] for row in snapshot['tables']['schema_migrations']['rows']]
    assert first == second
    engine.dispose()


REJECTIONS = ['column','generated','default','check','self_fk','autoincrement','without_rowid','nullable',
              'neither','partial_legacy','index','partial_index','expression_index','spoof_index',
              'partial_target','expression_target','mixed','collated_identity','view','trigger','external_trigger',
              'scratch','absent_scratch','scratch_view','scratch_index','unknown_child','duplicate']


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('variant', REJECTIONS)
def test_unsupported_shape_rejected_before_ddl_without_loss(tmp_path, entry, fk, variant):
    engine = _fixture(tmp_path, fk, variant)
    before = _snapshot(engine, 'before')
    mutations = []
    def observe(c, cursor, statement, parameters, context, many):
        if statement.lstrip().lower().startswith(('create ', 'drop ', 'alter ', 'insert ', 'update ', 'delete ')):
            mutations.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    with pytest.raises(RuntimeError, match='cannot migrate instruments'):
        _run(engine, entry)
    event.remove(engine, 'before_cursor_execute', observe)
    assert not mutations
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    engine.dispose()


PHASES = ['create','copy','drop','rename','index','marker','head_marker','later']


def _matches(statement, parameters, phase, entry):
    s = ' '.join(statement.lower().split())
    if phase == 'create': return s.startswith('create table "instruments__v1_rebuild"')
    if phase == 'copy': return s.startswith('insert into "instruments__v1_rebuild"')
    if phase == 'drop': return s == 'drop table "instruments"'
    if phase == 'rename': return s.startswith('alter table "instruments__v1_rebuild" rename')
    if phase == 'index': return s.startswith('create index "ix_instruments_symbol"')
    if entry == 'fallback':
        version = {'marker':'0002_', 'head_marker':'0006_', 'later':'0003_'}[phase]
        return s.startswith('insert or replace into schema_migrations') and version in s
    version = {'marker':'0002_', 'head_marker':'0006_', 'later':'0003_'}[phase]
    return s.startswith('update alembic_version') and version in (s + repr(parameters))


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('timing', ['before', 'after'])
def test_statement_failure_rolls_back_entire_chain_and_same_db_retry(tmp_path, entry, fk, phase, timing):
    engine = _fixture(tmp_path, fk)
    before = _snapshot(engine, 'before')
    hits, statements = [], []
    def fault(c, cursor, statement, parameters, context, many):
        statements.append([statement, repr(parameters)])
        if _matches(statement, parameters, phase, entry):
            hits.append(statement)
            raise RuntimeError('instrument injected failure')
    hook = timing + '_cursor_execute'
    event.listen(engine, hook, fault)
    with pytest.raises(RuntimeError, match='instrument injected failure'):
        _run(engine, entry)
    event.remove(engine, hook, fault)
    (tmp_path/'fault-sql.json').write_text(json.dumps({'phase':phase,'timing':timing,'hits':hits,'statements':statements},indent=2),encoding='utf8')
    assert len(hits) == 1
    assert _snapshot(engine, 'after-failure') == before
    assert _fk(engine) == fk
    _run(engine, entry)
    _assert_head(engine, entry)
    after = _snapshot(engine, 'after-retry')
    assert after['tables']['instruments']['rows'] == before['tables']['instruments']['rows']
    for name in CHILDREN:
        assert after['tables'][name] == before['tables'][name]
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
def test_postflight_fk_violation_rolls_back_rebuild_and_markers(tmp_path, entry, fk):
    engine = _fixture(tmp_path, fk)
    before = _snapshot(engine, 'before')
    hits = []
    def orphan(c, cursor, statement, parameters, context, many):
        if _matches(statement, parameters, 'head_marker', entry):
            hits.append(statement)
            # A real orphan produced while enforcement is temporarily off.
            cursor.execute('UPDATE events SET instrument_id=999 WHERE instrument_id=7')
    event.listen(engine, 'after_cursor_execute', orphan)
    with pytest.raises(RuntimeError, match='foreign-key violation'):
        _run(engine, entry)
    event.remove(engine, 'after_cursor_execute', orphan)
    assert len(hits) == 1
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    _run(engine, entry)
    _assert_head(engine, entry)
    engine.dispose()


@pytest.mark.parametrize('fk', [0, 1])
def test_active_external_connection_rejected_without_owning_caller_transaction(tmp_path, fk):
    engine = _fixture(tmp_path, fk)
    before = _snapshot(engine, 'before')
    with engine.connect() as c:
        c.exec_driver_sql('BEGIN')
        c.exec_driver_sql("UPDATE instruments SET name='uncommitted' WHERE id=7")
        with pytest.raises(RuntimeError, match='inactive caller connection'):
            command.upgrade(_config(c), 'head')
        assert c.in_transaction()
        assert c.exec_driver_sql('PRAGMA foreign_keys').scalar() == fk
        assert c.exec_driver_sql('SELECT name FROM instruments WHERE id=7').scalar() == 'uncommitted'
        c.rollback()
    assert _snapshot(engine, 'after') == before
    engine.dispose()


@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('name', ['INSTRUMENTS','instruments__v1_rebuild','instruments__v1_rebuild_old'])
def test_external_temp_shadow_preserves_main_and_temp_data(tmp_path, fk, name):
    engine = _fixture(tmp_path, fk)
    before = _snapshot(engine, 'before')
    with engine.connect() as c:
        c.exec_driver_sql(f'CREATE TEMP TABLE "{name}"(payload BLOB)')
        c.exec_driver_sql(f'INSERT INTO temp."{name}" VALUES(X\'CAFE\')')
        c.commit()
        with pytest.raises(RuntimeError, match='TEMP shadow'):
            command.upgrade(_config(c), 'head')
        assert not c.in_transaction()
        assert c.exec_driver_sql(f'SELECT payload FROM temp."{name}"').all() == [(bytes.fromhex('CAFE'),)]
        assert c.exec_driver_sql('PRAGMA foreign_keys').scalar() == fk
    assert _snapshot(engine, 'after') == before
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
def test_restore_failure_retains_original_exception_chain(tmp_path, entry):
    engine = _fixture(tmp_path, 1)
    before = _snapshot(engine, 'before')
    original = RuntimeError('original instrument fault')
    restore = RuntimeError('restore FK fault')
    hit = []
    def fail(c,cursor,statement,parameters,context,many):
        if _matches(statement,parameters,'drop',entry):
            hit.append('original')
            raise original
        if hit and statement.lower() == 'pragma foreign_keys=on':
            hit.append('restore')
            raise restore
    event.listen(engine,'before_cursor_execute',fail)
    with pytest.raises(RuntimeError,match='original instrument fault') as error:
        if entry == 'external':
            # The deliberate restore failure can leave SQLAlchemy's PRAGMA
            # autobegin open; inspect chaining without the normal reuse oracle.
            with engine.connect() as c:
                command.upgrade(_config(c), 'head')
        else:
            _run(engine,entry)
    event.remove(engine,'before_cursor_execute',fail)
    assert error.value is original
    assert error.value.__cause__ is restore
    assert hit == ['original','restore']
    assert _snapshot(engine,'after') == before
    # Restoration was deliberately prevented; do not claim the mode restored.
    engine.dispose()


@pytest.mark.parametrize('entry', ['engine', 'external'])
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('shape', ['legacy', 'absent'])
def test_late_revision_marker_cannot_mask_missing_current_identity(tmp_path, entry, fk, shape):
    engine = _fixture(tmp_path, fk, children=False)
    with engine.begin() as c:
        if shape == 'absent':
            c.exec_driver_sql('DROP TABLE instruments')
        c.exec_driver_sql('CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
        c.exec_driver_sql('INSERT INTO alembic_version VALUES(?)', ('0005_news_temporal_contract' if shape=='legacy' else HEAD,))
    before = _snapshot(engine, 'before')
    with pytest.raises(RuntimeError, match='revision requires current identity'):
        _run(engine, entry)
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    engine.dispose()


def test_revision_0001_target_can_keep_legacy_identity_without_false_head(tmp_path):
    engine = _fixture(tmp_path, 1, 'missing')
    command.upgrade(_config(engine), '0001_schema_v1')
    with engine.connect() as c:
        assert identity.preflight_instrument_identity(c) == 'legacy'
        assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == '0001_schema_v1'
    _run(engine, 'engine')
    _assert_head(engine, 'engine')
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
def test_existing_orphan_is_rejected_without_repair(tmp_path, entry, fk):
    engine = _fixture(tmp_path, 0)
    with engine.begin() as c:
        c.exec_driver_sql('UPDATE events SET instrument_id=999')
    with engine.connect() as c:
        c.exec_driver_sql(f'PRAGMA foreign_keys={fk}')
        c.commit()
    before = _snapshot(engine, 'before')
    with pytest.raises(RuntimeError, match='foreign-key violation'):
        _run(engine, entry)
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
def test_failed_postflight_integrity_does_not_commit(tmp_path, monkeypatch, entry, fk):
    engine = _fixture(tmp_path, fk)
    before = _snapshot(engine, 'before')
    original = identity.check_sqlite_migration_integrity
    hits = []
    def guard(c):
        original(c)
        hits.append(True)
        if len(hits) == 2:
            raise RuntimeError('injected integrity_check failure')
    monkeypatch.setattr(identity, 'check_sqlite_migration_integrity', guard)
    monkeypatch.setattr(migrations, 'check_sqlite_migration_integrity', guard)
    with pytest.raises(RuntimeError, match='injected integrity_check failure'):
        _run(engine, entry)
    assert len(hits) == 2
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    monkeypatch.setattr(identity, 'check_sqlite_migration_integrity', original)
    monkeypatch.setattr(migrations, 'check_sqlite_migration_integrity', original)
    _run(engine, entry)
    _assert_head(engine, entry)
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('kind', ['action', 'compound', 'non_id', 'deferrable'])
def test_unknown_inbound_definition_is_preserved_and_rejected(tmp_path, entry, fk, kind):
    engine = _fixture(tmp_path, 0, children=False)
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE events')
        references = {
            'action': 'FOREIGN KEY(instrument_id) REFERENCES instruments(id) ON DELETE CASCADE',
            'compound': 'FOREIGN KEY(instrument_id,other) REFERENCES instruments(market,symbol)',
            'non_id': 'FOREIGN KEY(instrument_id) REFERENCES instruments(symbol)',
            'deferrable': 'FOREIGN KEY(instrument_id) REFERENCES instruments(id) DEFERRABLE INITIALLY DEFERRED',
        }
        c.exec_driver_sql('CREATE TABLE events(id INTEGER PRIMARY KEY, instrument_id INTEGER, other TEXT, '+references[kind]+')')
    with engine.connect() as c:
        c.exec_driver_sql(f'PRAGMA foreign_keys={fk}')
        c.commit()
    before = _snapshot(engine, 'before')
    with pytest.raises(RuntimeError, match='unsupported inbound foreign key events'):
        _run(engine, entry)
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
def test_current_plus_reversed_legacy_identity_is_not_a_noop(tmp_path, entry, fk):
    engine = _fixture(tmp_path, fk, 'current')
    with engine.begin() as c:
        c.exec_driver_sql('CREATE UNIQUE INDEX reversed_legacy ON instruments(symbol,market)')
    before = _snapshot(engine, 'before')
    with pytest.raises(RuntimeError, match='noncanonical ordered identity'):
        _run(engine, entry)
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('shape', ['known_indexes', 'quoted_table', 'orm_legacy'])
def test_supported_legacy_definition_variants_keep_values(tmp_path, entry, fk, shape):
    engine = _fixture(tmp_path, 0)
    with engine.begin() as c:
        if shape == 'known_indexes':
            c.exec_driver_sql('CREATE INDEX ix_instruments_symbol ON instruments(symbol)')
            c.exec_driver_sql('CREATE INDEX ix_instruments_instrument_type ON instruments(instrument_type)')
        else:
            # Recreate exactly the known parent variant without renaming the
            # original: ALTER RENAME would rewrite child FK fixture references.
            rows = c.exec_driver_sql('SELECT * FROM instruments').all()
            c.exec_driver_sql('DROP TABLE instruments')
            ddl = DDL.replace('instruments (', '"Instruments" (') if shape=='quoted_table' else DDL.replace('is_watchlisted BOOLEAN NOT NULL DEFAULT 0', 'is_watchlisted BOOLEAN NOT NULL').replace('id INTEGER NOT NULL PRIMARY KEY', 'id INTEGER NOT NULL').replace('CONSTRAINT uq_', 'PRIMARY KEY(id), CONSTRAINT uq_')
            c.exec_driver_sql(ddl)
            for row in rows:
                c.exec_driver_sql('INSERT INTO instruments VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', tuple(row))
    with engine.connect() as c:
        c.exec_driver_sql(f'PRAGMA foreign_keys={fk}')
        c.commit()
    before = _snapshot(engine,'before')
    _run(engine,entry)
    after = _snapshot(engine,'after')
    old_name = 'Instruments' if shape=='quoted_table' else 'instruments'
    assert before['tables'][old_name]['rows'] == after['tables']['instruments']['rows']
    for name in CHILDREN:
        assert before['tables'][name] == after['tables'][name]
    _assert_head(engine,entry)
    assert _fk(engine) == fk
    engine.dispose()


@pytest.mark.parametrize('entry', ENTRIES)
@pytest.mark.parametrize('fk', [0, 1])
@pytest.mark.parametrize('shape', ['legacy', 'absent'])
@pytest.mark.parametrize('marker', ['alembic_version', 'schema_migrations'])
def test_prior_identity_stamp_cannot_be_repaired_or_masked_by_create_all(tmp_path, entry, fk, shape, marker):
    engine = _fixture(tmp_path, fk, children=False)
    with engine.begin() as c:
        if shape == 'absent':
            c.exec_driver_sql('DROP TABLE instruments')
        if marker == 'alembic_version':
            c.exec_driver_sql('CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)')
            c.exec_driver_sql('INSERT INTO alembic_version VALUES(?)', (HEAD,))
        else:
            c.exec_driver_sql('CREATE TABLE schema_migrations(version VARCHAR(64) PRIMARY KEY, applied_at DATETIME NOT NULL)')
            c.exec_driver_sql("INSERT INTO schema_migrations VALUES('0002_instrument_exchange_key','2000-01-01')")
    before = _snapshot(engine, 'before')
    mutations = []
    def observe(c, cursor, statement, parameters, context, many):
        if statement.lstrip().lower().startswith(('create ', 'drop ', 'alter ', 'insert ', 'update ', 'delete ')):
            mutations.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    with pytest.raises(RuntimeError, match='refusing to repair prior stamp'):
        _run(engine, entry)
    event.remove(engine, 'before_cursor_execute', observe)
    assert not mutations
    assert _snapshot(engine, 'after') == before
    assert _fk(engine) == fk
    engine.dispose()
