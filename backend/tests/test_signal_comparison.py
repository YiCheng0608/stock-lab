from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from app.signal_artifact import digest_text
from app.signal_artifact_store import (
    ReadonlySnapshotError, SignalArtifactStore, SignalArtifactStoreError,
    snapshot_fingerprint,
)
from app.signal_comparison import SignalComparisonError, compare_signals, comparison_json
from test_signal_artifact import _artifact


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy(path):
    with sqlite3.connect(path) as con:
        con.executescript('''
        CREATE TABLE instruments(id INTEGER, exchange TEXT, symbol TEXT);
        CREATE TABLE strategy_versions(id INTEGER, name TEXT, version TEXT);
        CREATE TABLE signals(id INTEGER, signal_key TEXT, signal_date TEXT,
          instrument_id INTEGER, strategy_version_id INTEGER, status TEXT, entry_type TEXT,
          reference_entry REAL,pullback_low REAL,pullback_high REAL,breakout_price REAL,
          invalid_price REAL,target_1 REAL,target_2 REAL,confidence REAL,rationale TEXT,
          data_cutoff TEXT,source_report TEXT,earliest_execution_date TEXT,execution_date TEXT,
          execution_price REAL,data_quality TEXT,rule_evidence_json TEXT,created_at TEXT);
        INSERT INTO instruments VALUES(1,'TWSE','2330');
        INSERT INTO strategy_versions VALUES(1,'demo_rule','1.0.0');
        INSERT INTO signals VALUES(1,'exact-key','2026-01-01',1,1,'conditional','breakout',
          NULL,NULL,NULL,100,90,120,130,0.75,'rationale','2026-01-01 13:30 Asia/Taipei',
          'synthetic','2026-01-02',NULL,NULL,'complete','{}','2026-01-01 01:00:00');
        ''')


@pytest.fixture
def pair(tmp_path):
    legacy = tmp_path / 'legacy.sqlite'
    artifact = tmp_path / 'artifact.sqlite'
    _legacy(legacy)
    with SignalArtifactStore(artifact) as writer:
        root = writer.save(_artifact(legacy_reference='exact-key'), attempt_id='root', run_id='run')
        other = writer.save(_artifact(input_snapshot={'id':'second','hash':digest_text('second')}), attempt_id='other')
        child = writer.save(_artifact(legacy_reference='exact-key', revision=2,
            supersedes_artifact_key=root.artifact_key,lifecycle_state='withdrawn',
            lifecycle_reason='synthetic withdrawal',lifecycle_at='2026-01-01T02:00:00+00:00',
            generated_at='2026-01-01T02:00:00+00:00'),attempt_id='child',run_id='run')
    return legacy, artifact, root, other, child


def _args(pair, **changes):
    legacy, artifact, root, _, _ = pair
    args = dict(legacy_path=legacy, artifact_path=artifact,
        legacy_expected_database_sha256=_hash(legacy), artifact_expected_database_sha256=_hash(artifact),
        legacy_signal_key='exact-key',artifact_selector={'artifact_key':root.artifact_key})
    args.update(changes)
    return args


def _mutate(path, sql, values=()):
    with sqlite3.connect(path) as con:
        con.execute(sql, values)


def test_deterministic_detached_report_boundaries(pair):
    before = [snapshot_fingerprint(p) for p in pair[:2]]
    report = compare_signals(**_args(pair))
    canonical = comparison_json(report)
    assert canonical == comparison_json(compare_signals(**_args(pair)))
    assert report['contract'] == 'signal-comparison/v1' and report['comparable'] is False
    assert report['dimensions']['subject']['status'] == 'equal'
    assert report['dimensions']['status']['status'] == 'observational'
    assert report['dimensions']['status']['lexically_equal'] is True
    for key in ['confidence','prices','quality','evidence','time','revision','inputs']:
        assert report['dimensions'][key]['status'] == 'incomparable'
    assert report['legacy']['snapshot']['confidence'] == 0.75
    assert report['legacy']['snapshot']['confidence_semantics']['kind'] == 'unknown_numeric'
    assert report['new']['artifact']['artifact']['confidence'] is None
    assert report['new']['artifact']['artifact']['earliest_execution_at'] is None
    report['new']['artifact']['artifact']['rule_evidence']['changed'] = True
    report['legacy']['snapshot']['subject']['symbol'] = 'changed'
    assert canonical == comparison_json(compare_signals(**_args(pair)))
    assert before == [snapshot_fingerprint(p) for p in pair[:2]]


@pytest.mark.parametrize('kind',['key','hash','lineage','and','withdrawn'])
def test_exact_selectors(pair,kind):
    root,child=pair[2],pair[4]
    selectors={'key':{'artifact_key':root.artifact_key},'hash':{'identity_hash':root.identity_hash},
        'lineage':{'lineage_key':root.lineage_key,'revision':1},
        'and':{'artifact_key':root.artifact_key,'identity_hash':root.identity_hash,'lineage_key':root.lineage_key,'revision':1},
        'withdrawn':{'lineage_key':root.lineage_key,'revision':2}}
    report=compare_signals(**_args(pair,artifact_selector=selectors[kind]))
    assert report['new']['artifact']['artifact_key']==(child if kind=='withdrawn' else root).artifact_key


@pytest.mark.parametrize('legacy_missing,new_missing',[(True,False),(False,True),(True,True)])
def test_missing_diagnostic(pair,legacy_missing,new_missing):
    report=compare_signals(**_args(pair,legacy_signal_key='absent' if legacy_missing else 'exact-key',
        artifact_selector={'artifact_key':'absent'} if new_missing else {'artifact_key':pair[2].artifact_key}))
    assert report['legacy']['state']==('missing' if legacy_missing else 'present')
    assert report['new']['state']==('missing' if new_missing else 'present')
    assert report['dimensions']['subject']['status']=='unavailable'


def test_contradictory_new_selectors_never_fallback(pair):
    report=compare_signals(**_args(pair,artifact_selector={'artifact_key':pair[2].artifact_key,'identity_hash':pair[3].identity_hash}))
    assert report['new']['reason']=='new_artifact_missing'


@pytest.mark.parametrize('selector',[{}, {'revision':1}, {'lineage_key':'x'}, {'artifact_key':None},
    {'artifact_key':''}, {'artifact_key':' x'}, {'artifact_key':'x','revision':True},
    {'artifact_key':'x','revision':0}, {'artifact_key':'x','revision':1.0}, {'latest':True}, {'symbol':'2330'}])
def test_invalid_selector_rejected_before_open(pair,monkeypatch,selector):
    args=_args(pair,artifact_selector=selector)
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k: pytest.fail('SQLite-open'))
    with pytest.raises(SignalComparisonError): compare_signals(**args)


@pytest.mark.parametrize('field,value', [('legacy_expected_database_sha256',None),('artifact_expected_database_sha256','bad'),
    ('artifact_expected_database_sha256','0'*64),('legacy_signal_key',''),('legacy_signal_key',True)])
def test_invalid_hash_or_key_before_open(pair,monkeypatch,field,value):
    args=_args(pair,**{field:value})
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k: pytest.fail('SQLite-open'))
    with pytest.raises((ReadonlySnapshotError,SignalComparisonError)): compare_signals(**args)


@pytest.mark.parametrize('kind',['missing','relative','uri','memory','directory','workspace','formal','local','hardlink','samefile','wal','shm','journal'])
def test_path_rejections_before_either_open(pair,tmp_path,monkeypatch,kind):
    args=_args(pair)
    p=tmp_path/'missing.sqlite'
    if kind=='relative': p=Path('relative.sqlite')
    elif kind=='uri': p='file:'+str(pair[1])
    elif kind=='memory': p=':memory:'
    elif kind=='directory': p=tmp_path
    elif kind=='workspace': p=Path(__file__).resolve()
    elif kind in ('formal','local'):
        p=tmp_path/('formal' if kind=='formal' else '.local')/'input.sqlite'
        p.parent.mkdir();p.write_bytes(pair[1].read_bytes())
    elif kind=='hardlink':
        p=tmp_path/'alias.sqlite';os.link(pair[1],p)
    elif kind=='samefile': p=pair[0];args['artifact_expected_database_sha256']=_hash(p)
    elif kind in ('wal','shm','journal'):
        p=pair[1];Path(str(p)+'-'+kind).write_bytes(b'sentinel')
    args['artifact_path']=p
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k: pytest.fail('SQLite-open'))
    with pytest.raises(ReadonlySnapshotError): compare_signals(**args)
    if kind=='missing': assert not p.exists()


def test_symlink_path_rejected_before_open(pair,tmp_path,monkeypatch):
    alias=tmp_path/'alias.sqlite'
    try: alias.symlink_to(pair[1])
    except OSError: pytest.skip('Windows symlink privilege unavailable')
    args=_args(pair,artifact_path=alias)
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k: pytest.fail('SQLite-open'))
    with pytest.raises(ReadonlySnapshotError): compare_signals(**args)


@pytest.mark.parametrize('sql,values',[
    ("INSERT INTO signals SELECT * FROM signals",()),
    ("UPDATE signals SET instrument_id=NULL",()),
    ("UPDATE signals SET strategy_version_id=NULL",()),
    ("DELETE FROM instruments",()),
    ("DELETE FROM strategy_versions",()),
    ("INSERT INTO instruments SELECT * FROM instruments",()),
    ("INSERT INTO strategy_versions SELECT * FROM strategy_versions",()),
    ("INSERT INTO instruments VALUES(2,'TWSE','2330')",()),
    ("UPDATE signals SET signal_date='20260101'",()),
    ("UPDATE signals SET earliest_execution_date='not-date'",()),
    ("UPDATE signals SET confidence=?",(float('inf'),)),
    ("UPDATE signals SET target_1='invalid'",()),
    ("UPDATE signals SET created_at=X'1234'",()),
    ("UPDATE signals SET rule_evidence_json=?",('{bad',)),
    ("UPDATE signals SET rule_evidence_json=?",('[]',)),
    ("UPDATE signals SET rule_evidence_json=?",('null',)),
    ("UPDATE signals SET rule_evidence_json=?",('{"x":NaN}',)),
    ("UPDATE signals SET rule_evidence_json=?",('{"x":1e999}',)),
    ("UPDATE signals SET rule_evidence_json=?",('{"x":1,"x":2}',)),
    ("UPDATE signals SET rule_evidence_json=?",('{"strategy":"other"}',)),
    ("UPDATE signals SET rule_evidence_json=?",('{"strategy_version":1}',)),
    ("UPDATE signals SET rule_evidence_json=?",('{"strategy":null}',)),
])
def test_invalid_legacy_rows_hard_fail_unchanged(pair,sql,values):
    _mutate(pair[0],sql,values)
    before=[snapshot_fingerprint(p) for p in pair[:2]]
    with pytest.raises(SignalComparisonError): compare_signals(**_args(pair))
    assert before==[snapshot_fingerprint(p) for p in pair[:2]]


@pytest.mark.parametrize('kind',['view','generated','missing','virtual'])
def test_legacy_schema_fail_closed(pair,kind):
    with sqlite3.connect(pair[0]) as con:
        con.execute('ALTER TABLE instruments RENAME TO saved_instruments')
        if kind=='view': con.execute('CREATE VIEW instruments AS SELECT * FROM saved_instruments')
        elif kind=='generated': con.execute("CREATE TABLE instruments(id INTEGER,exchange TEXT,symbol TEXT GENERATED ALWAYS AS ('2330'))")
        elif kind=='missing': con.execute('CREATE TABLE instruments(id INTEGER,exchange TEXT)')
        else: con.execute('CREATE VIRTUAL TABLE instruments USING fts5(id,exchange,symbol)')
    with pytest.raises(SignalComparisonError,match='invalid_legacy_schema'): compare_signals(**_args(pair))


@pytest.mark.parametrize('change,expected', [('NULL',None),("'{}'",{}),
    ("'{\"confidence_semantics\":{\"is_probability\":true}}'",{'confidence_semantics':{'is_probability':True}})])
def test_evidence_null_empty_untrusted_marker(pair,change,expected):
    _mutate(pair[0],'UPDATE signals SET rule_evidence_json='+change)
    row=compare_signals(**_args(pair))['legacy']['snapshot']
    assert row['rule_evidence']==expected
    assert row['confidence_semantics']['is_probability'] is False
    assert row['evidence_reason']==('legacy_evidence_unavailable' if expected is None else None)


def test_namespace_exchange_and_reference_descriptive_only(pair):
    with sqlite3.connect(pair[0]) as con:
        con.execute("INSERT INTO instruments VALUES(2,'TPEX','2330')")
        con.execute("INSERT INTO signals SELECT 2,'other-namespace',signal_date,2,strategy_version_id,status,entry_type,reference_entry,pullback_low,pullback_high,breakout_price,invalid_price,target_1,target_2,confidence,rationale,data_cutoff,source_report,earliest_execution_date,execution_date,execution_price,data_quality,rule_evidence_json,created_at FROM signals")
    report=compare_signals(**_args(pair,legacy_signal_key='other-namespace'))
    assert report['legacy']['snapshot']['id']==2
    assert report['dimensions']['subject']['status']=='different'
    assert report['dimensions']['linkage']['status']=='conflict'
    assert compare_signals(**_args(pair,legacy_signal_key='EXACT-KEY'))['legacy']['state']=='missing'
    report=compare_signals(**_args(pair,artifact_selector={'artifact_key':pair[3].artifact_key}))
    assert report['dimensions']['linkage']['status']=='unknown'


@pytest.mark.parametrize('table,column,value',[
    ('signal_artifacts','canonical_payload_json','{}'),
    ('signal_artifacts','seal','bad'),
    ('signal_artifact_bindings','implementation_digest','bad'),
    ('signal_artifact_feature_refs','feature_artifact_key','bad'),
    ('signal_artifact_lifecycle','state','bad'),
    ('signal_artifact_attempts','payload_hash','bad'),
    ('signal_artifact_run_relations','run_id','bad'),
])
def test_strict_artifact_corruption_including_ancestor(pair,table,column,value):
    with sqlite3.connect(pair[1]) as con:
        con.execute('PRAGMA ignore_check_constraints=ON')
        triggers=list(con.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        for name,_ in triggers: con.execute(f'DROP TRIGGER "{name}"')
        # Root-only artifact corruption must also fail when selecting child.
        if table=='signal_artifacts':
            con.execute(f'UPDATE {table} SET {column}=? WHERE artifact_key=?',(value,pair[2].artifact_key))
        else: con.execute(f'UPDATE {table} SET {column}=?',(value,))
        for _,sql in triggers: con.execute(sql)
    before=[snapshot_fingerprint(p) for p in pair[:2]]
    with pytest.raises(SignalArtifactStoreError):
        compare_signals(**_args(pair,artifact_selector={'artifact_key':pair[4].artifact_key}))
    assert before==[snapshot_fingerprint(p) for p in pair[:2]]


@pytest.mark.parametrize('kind',['empty','foreign','not_sqlite','unknown_version'])
def test_store_rejects_ownership_without_mutation(pair,kind):
    if kind in ('empty','not_sqlite'):
        pair[1].write_bytes(b'' if kind=='empty' else b'not sqlite')
    elif kind=='foreign':
        pair[1].write_bytes(b'')
        _mutate(pair[1],'CREATE TABLE foreign_table(x)')
    else:
        with sqlite3.connect(pair[1]) as con:
            con.execute('PRAGMA ignore_check_constraints=ON')
            con.execute('UPDATE signal_artifact_store_metadata SET schema_version=99')
    before=snapshot_fingerprint(pair[1])
    with pytest.raises((SignalArtifactStoreError,sqlite3.DatabaseError)): compare_signals(**_args(pair))
    assert snapshot_fingerprint(pair[1])==before


def test_readonly_factory_trace_and_inherited_write_denial(pair,monkeypatch):
    original=sqlite3.connect
    trace=[];opens=[]
    def connect(*args,**kwargs):
        opens.append((args,kwargs));con=original(*args,**kwargs);con.set_trace_callback(trace.append);return con
    monkeypatch.setattr(sqlite3,'connect',connect)
    for name in ('__init__','_initialize_or_validate','_create_schema','save_artifact','save'):
        monkeypatch.setattr(SignalArtifactStore,name,lambda *a,**k: pytest.fail('writer invoked'))
    before=snapshot_fingerprint(pair[1])
    with SignalArtifactStore.open_readonly(pair[1]) as reader:
        assert reader.get_exact(artifact_key=pair[2].artifact_key).artifact_key==pair[2].artifact_key
        for name in ('save','save_artifact','append'):
            with pytest.raises(ReadonlySnapshotError): getattr(reader,name)(_artifact())
        for sql in ('CREATE TABLE forbidden(x)','DELETE FROM signal_artifacts','PRAGMA query_only=OFF',
                    "ATTACH DATABASE ':memory:' AS other", "SELECT load_extension('absent')"):
            with pytest.raises(sqlite3.DatabaseError): reader.connection.execute(sql)
    assert all(args[0].endswith('?mode=ro') and kwargs['uri'] for args,kwargs in opens)
    assert sum(sql=='BEGIN' for sql in trace)==1
    assert not any('BEGIN IMMEDIATE' in sql for sql in trace)
    assert snapshot_fingerprint(pair[1])==before


def test_observed_source_change_fails_closed(pair,monkeypatch):
    original=SignalArtifactStore.get_exact
    def read(self,**selectors):
        result=original(self,**selectors)
        st=pair[0].stat();os.utime(pair[0],ns=(st.st_atime_ns,st.st_mtime_ns+1000000))
        return result
    monkeypatch.setattr(SignalArtifactStore,'get_exact',read)
    with pytest.raises(ReadonlySnapshotError,match='snapshot_changed'): compare_signals(**_args(pair))


def test_checkpointed_wal_header_rejected_before_open(pair,monkeypatch):
    with sqlite3.connect(pair[1]) as con:
        assert con.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
    con.close()
    assert not Path(str(pair[1])+'-wal').exists()
    args=_args(pair)
    monkeypatch.setattr(sqlite3,'connect',lambda *a,**k: pytest.fail('SQLite-open'))
    with pytest.raises(ReadonlySnapshotError,match='snapshot_wal_header'): compare_signals(**args)
    assert not Path(str(pair[1])+'-wal').exists()


@pytest.mark.parametrize('confidence,name,version,kind',[(0.75,'breakout_v1','1.0.0','legacy_fixed_value'),
    (0.75,'pullback_v1','1.0.0','legacy_fixed_value'),(0.75,'breakout_v1','2','unknown_numeric'),
    (None,'demo_rule','1.0.0','not_calibrated'),(0.5,'demo_rule','1.0.0','unknown_numeric')])
def test_confidence_classification_never_probability(pair,confidence,name,version,kind):
    _mutate(pair[0],'UPDATE signals SET confidence=?',(confidence,))
    _mutate(pair[0],'UPDATE strategy_versions SET name=?,version=?',(name,version))
    result=compare_signals(**_args(pair))
    semantics=result['legacy']['snapshot']['confidence_semantics']
    assert semantics['kind']==kind and semantics['is_probability'] is False
    assert result['dimensions']['confidence']['status']=='incomparable'


def test_null_optional_text_dates_and_unknown_evidence_key(pair):
    _mutate(pair[0],'''UPDATE signals SET rationale=NULL,data_cutoff=NULL,source_report=NULL,
        created_at=NULL,earliest_execution_date=NULL,execution_date=NULL,
        rule_evidence_json='{"strategy_name":null}' ''')
    report=compare_signals(**_args(pair))
    row=report['legacy']['snapshot']
    assert row['created_at'] is None and row['rule_evidence']=={'strategy_name':None}


def test_reference_checked_against_requested_key_even_when_legacy_missing(pair):
    _mutate(pair[0],'DELETE FROM signals')
    report=compare_signals(**_args(pair))
    assert report['legacy']['state']=='missing' and report['dimensions']['linkage']['status']=='match'
    assert report['dimensions']['linkage']['reasons']==['matching_caller_declaration_only']
    report=compare_signals(**_args(pair,legacy_signal_key='another'))
    assert report['dimensions']['linkage']['status']=='conflict'


def test_opaque_same_subject_keys_never_fallback(pair):
    with sqlite3.connect(pair[0]) as con:
        con.execute("INSERT INTO signals SELECT 2,'any opaque key-namespace',signal_date,instrument_id,strategy_version_id,status,entry_type,reference_entry,pullback_low,pullback_high,breakout_price,invalid_price,target_1,target_2,confidence,rationale,data_cutoff,source_report,earliest_execution_date,execution_date,execution_price,data_quality,rule_evidence_json,created_at FROM signals")
    report=compare_signals(**_args(pair,legacy_signal_key='any opaque key-namespace'))
    assert report['legacy']['snapshot']['id']==2 and report['dimensions']['subject']['status']=='equal'
    assert compare_signals(**_args(pair,legacy_signal_key='unknown'))['legacy']['state']=='missing'


@pytest.mark.parametrize('field,value',[(key,value) for key in ['id','instrument_id','strategy_version_id'] for value in [0,-1,'text',1.5]])
def test_legacy_ids_are_stored_positive_integers(pair,field,value):
    _mutate(pair[0],f'UPDATE signals SET {field}=?',(value,))
    with pytest.raises(SignalComparisonError): compare_signals(**_args(pair))
