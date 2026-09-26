"""Real migrated external databases and worker transactions; no network."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from app.migrations import upgrade_database
from app.models import Instrument, MarketBar, IngestionRun, Signal, StrategyVersion
from app import domain
from worker import pipeline
from worker import analysis_capture as capture


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def research(tmp_path):
    source = tmp_path / 'source.db'
    engine = create_engine('sqlite:///' + source.as_posix())
    upgrade_database(engine)
    with Session(engine) as db:
        for exchange in ('TWSE', 'TPEX'):
            inst = Instrument(symbol='SAME', name='Synthetic', exchange=exchange)
            db.add(inst); db.flush()
            for index in range(65):
                day = date(2026, 5, 1)+timedelta(days=index)
                close = 90+index*.1
                db.add(MarketBar(instrument_id=inst.id,trading_date=day,open=close,high=close+1,low=close-1,close=close,adj_close=close,volume=100+index,turnover=10000))
        db.add(IngestionRun(run_type='collect',source='official',run_date=day,data_as_of=day.isoformat(),status='success'))
        db.commit()
    engine.dispose()
    original = sha(source)
    target = tmp_path/'research.db'
    owner = capture.create_research_database(source_snapshot_path=source,expected_source_sha256=original,research_database_path=target)
    assert sha(source)==original
    return source,target,owner


def run(target, attempt='one'):
    return capture.execute_analysis_attempt(research_database_path=target,attempt_id=attempt)


def read(target, attempt='one'):
    return capture.read_analysis_attempt(research_database_path=target,attempt_id=attempt)


def _link_selected_raw(target, *, exchange='TWSE'):
    """Add one local metadata relation; the named payload file is not opened."""
    with sqlite3.connect(target) as db:
        run_id, score_date = db.execute(
            "SELECT id,data_as_of FROM ingestion_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        instrument_id = db.execute(
            "SELECT id FROM instruments WHERE exchange=?", (exchange,)
        ).fetchone()[0]
        source = exchange.lower()
        raw_id = db.execute(
            "INSERT INTO raw_payloads (ingestion_run_id,source,endpoint,payload_path,sha256,data_as_of,collected_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, source, 'local-test-endpoint', 'never-opened/raw.json', 'a'*64,
             score_date, '2026-09-26 01:02:03.000000'),
        ).lastrowid
        db.execute(
            "UPDATE market_bars SET source=?,raw_payload_id=? "
            "WHERE instrument_id=? AND trading_date=?",
            (source, raw_id, instrument_id, score_date),
        )
    return raw_id


def test_actual_worker_durable_reuse_append_and_source_unchanged(research, monkeypatch):
    source,target,owner=research
    source_hash=sha(source)
    counts=[]
    for name in ('breakout_v1','pullback_v1'):
        original=getattr(pipeline,'evaluate_'+name)
        def spy(_name=name,_original=original,**kwargs):
            counts.append((_name,copy.deepcopy(kwargs)))
            return _original(**kwargs)
        monkeypatch.setattr(pipeline,'evaluate_'+name,spy)
    result=run(target)
    assert result['outcome']=='committed_verified'
    assert len(counts)==8 and len(result['captures'])==8
    assert {r['subject']['exchange'] for r in result['captures']}=={'TWSE','TPEX'}
    for row, (name,args) in zip(result['captures'],counts):
        assert row['evaluator']==name and row['arguments']==args
        assert row['actual_result']==row['bundle']['recorded_result']
        assert row['arguments']['close'] is not None
        assert row['arguments']['volume']==164.0
        assert len(row['arguments']['prior_volumes'])==20
        assert row['arguments']['group_excess_return_20d'] is None
    history=json.dumps(result['captures'],sort_keys=True)
    before=sha(target)
    reused=run(target)
    assert reused['idempotent_reuse'] and len(counts)==8 and sha(target)==before
    assert reused['receipt']==result['receipt']
    second=run(target,'two')
    assert len(counts)==16 and second['receipt']['attempt_id']=='two'
    assert json.dumps(read(target)['captures'],sort_keys=True)==history
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT count(*) FROM signals').fetchone()[0]==4
    assert sha(source)==source_hash


@pytest.mark.parametrize('stage',['evaluator','capture','flush'])
def test_precommit_errors_rollback_whole_analysis(research,monkeypatch,stage):
    _,target,_=research
    before=sha(target)
    def bomb(*a,**k): raise RuntimeError('injected')
    if stage=='evaluator': monkeypatch.setattr(pipeline,'evaluate_pullback_v1',bomb)
    elif stage=='capture': monkeypatch.setattr(capture._Collector,'persist',bomb)
    else: monkeypatch.setattr(Session,'flush',bomb)
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.outcome=='rollback_confirmed'
    assert sha(target)==before
    with pytest.raises(capture.AnalysisCaptureError,match='attempt_not_found'): read(target)


def test_shared_result_divergence(research,monkeypatch):
    _,target,_=research
    monkeypatch.setattr(pipeline,'evaluate_breakout_v1',lambda **kwargs:domain.RuleEvaluation(True,'passed'))
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.detail=='worker_private_result_mismatch'


@pytest.mark.parametrize('field',['config_json','canonical_config_snapshot'])
def test_strategy_binding_rejects(research,field):
    _,target,_=research
    engine=create_engine('sqlite:///'+target.as_posix())
    with Session(engine) as db:
        strategies=pipeline._ensure_strategies(db)
        strategy=strategies['breakout_v1']
        setattr(strategy,field,{'bad':True})
        db.commit()
    engine.dispose()
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.detail=='worker_strategy_binding_mismatch'


@pytest.mark.parametrize('commit_mode',['before','after'])
def test_commit_exception_fresh_readback(research,monkeypatch,commit_mode):
    _,target,_=research
    original=Session.commit
    def fail(self):
        if commit_mode=='after': original(self)
        raise RuntimeError('commit fault')
    monkeypatch.setattr(Session,'commit',fail)
    if commit_mode=='before':
        with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
        assert error.value.outcome=='not_committed_verified'
    else:
        assert run(target)['outcome']=='committed_verified_after_error'


def test_readback_failure_unknown(research,monkeypatch):
    _,target,_=research
    original=capture.read_analysis_attempt
    times=0
    def fail(**kwargs):
        nonlocal times
        times+=1
        if times>1: raise OSError('readback fault')
        return original(**kwargs)
    monkeypatch.setattr(capture,'read_analysis_attempt',fail)
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.outcome=='commit_outcome_unknown'
    assert original(research_database_path=target,attempt_id='one')['outcome']=='committed_verified'


def test_no_data_no_success_attempt(research):
    _,target,_=research
    with sqlite3.connect(target) as db: db.execute('DELETE FROM ingestion_runs')
    assert run(target)['outcome']=='not_committed'
    with pytest.raises(capture.AnalysisCaptureError,match='attempt_not_found'): read(target)


def test_history_immutable_and_schema_checked(research):
    _,target,_=research
    run(target)
    with sqlite3.connect(target) as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute("DELETE FROM worker_capture_calls")
        db.execute('DROP TRIGGER worker_capture_calls_no_delete')
    with pytest.raises(capture.AnalysisCaptureError,match='capture_schema_mismatch'): read(target)


def test_create_never_adopts_existing_and_hash_required(research,tmp_path):
    source,target,_=research
    before=sha(target)
    with pytest.raises(capture.AnalysisCaptureError,match='target_exists'):
        capture.create_research_database(source_snapshot_path=source,expected_source_sha256=sha(source),research_database_path=target)
    assert sha(target)==before
    new=tmp_path/'new.db'
    with pytest.raises(Exception,match='snapshot_hash_mismatch'):
        capture.create_research_database(source_snapshot_path=source,expected_source_sha256='0'*64,research_database_path=new)
    assert not new.exists()


def test_run_environment_preflight(research,monkeypatch):
    _,target,_=research
    monkeypatch.delenv('STOCK_DATA_DIR')
    before=sha(target)
    with pytest.raises(capture.AnalysisCaptureError,match='isolated_stock_environment_required'): run(target)
    assert sha(target)==before


def test_cli_read_has_no_worker_import_or_stock_environment(research):
    _,target,_=research
    run(target)
    code="from worker.analysis_capture import read_analysis_attempt; import sys; r=read_analysis_attempt(research_database_path=sys.argv[1],attempt_id='one'); assert 'worker.pipeline' not in sys.modules; assert 'app.config' not in sys.modules; print(r['outcome'])"
    env={k:v for k,v in os.environ.items() if not k.startswith('STOCK_')}
    result=subprocess.run([sys.executable,'-B','-c',code,str(target)],env=env,text=True,encoding="utf-8",capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='committed_verified'

@pytest.mark.parametrize('status',['failed','running'])
def test_skipped_no_success_attempt(research,status):
    _,target,_=research
    with sqlite3.connect(target) as db: db.execute('UPDATE ingestion_runs SET status=?',(status,))
    assert run(target)['analysis']['status']=='skipped'
    with pytest.raises(capture.AnalysisCaptureError,match='attempt_not_found'): read(target)


def test_active_instrument_without_bar_does_not_inflate_expected_calls(research):
    _,target,_=research
    engine=create_engine('sqlite:///'+target.as_posix())
    with Session(engine) as db:
        db.add(Instrument(symbol='NO_BAR',exchange='TWSE',name='No bar'))
        db.commit()
    engine.dispose()
    result=run(target)
    assert result['receipt']['analysis']['signals_upserted']==2
    assert len(result['captures'])==8


def test_missing_capture_callback_cannot_commit_success(research,monkeypatch):
    _,target,_=research
    original=capture._Collector.persist
    count=0
    def lost(self,*args,**kwargs):
        nonlocal count
        count+=1
        if count==1:
            self.pending.clear()
            return
        return original(self,*args,**kwargs)
    monkeypatch.setattr(capture._Collector,'persist',lost)
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.outcome=='rollback_confirmed'
    with pytest.raises(capture.AnalysisCaptureError,match='attempt_not_found'): read(target)


@pytest.mark.parametrize('value',[None,[],[100.,None],list(range(80,105))])
def test_call_boundary_preserves_null_empty_order_and_prefix(value):
    collector=capture._Collector({},'probe')
    args={'close':101.,'volume':120.,'prior_highs':value,'prior_volumes':value,'group_excess_return_20d':None,'institutional_flow_to_turnover_ratio_5d':None,'margin_balance_change_ratio_5d':None}
    expected=copy.deepcopy(args)
    collector.before('breakout_v1',args)
    actual=domain.evaluate_breakout_v1(**args)
    if isinstance(value,list): value.append(999.)
    collector.after('breakout_v1',actual)
    assert collector.pending['breakout_v1']['arguments']==expected


@pytest.mark.parametrize('state,volume',[('passed',120.),('rejected',50.)])
def test_actual_nonmissing_result_states(state,volume):
    args={'close':101.,'volume':volume,'prior_highs':[100.]*20,'prior_volumes':[100.]*20,'group_excess_return_20d':.1,'institutional_flow_to_turnover_ratio_5d':0.,'margin_balance_change_ratio_5d':0.}
    collector=capture._Collector({},'probe')
    collector.before('breakout_v1',args)
    collector.after('breakout_v1',domain.evaluate_breakout_v1(**args))
    assert collector.pending['breakout_v1']['actual_result']['state']==state


def test_native_domain_rejects_nonfinite_without_cleaning():
    collector=capture._Collector({},'probe')
    with pytest.raises(Exception,match='nonfinite_number'):
        collector.before('breakout_v1',{'close':float('nan')})


@pytest.mark.parametrize('which',['source','target'])
def test_sidecars_refused(research,tmp_path,which):
    source,target,_=research
    destination=tmp_path/'new.db'
    Path(str(source if which=='source' else destination)+'-wal').write_bytes(b'')
    with pytest.raises(Exception):
        capture.create_research_database(source_snapshot_path=source,expected_source_sha256=sha(source),research_database_path=destination)
    assert not destination.exists()


def test_invalid_path_environment_has_no_mkdir(research,monkeypatch,tmp_path):
    _,target,_=research
    forbidden=Path(__file__).resolve().parents[2]/'data'/'should-not-create-r34'
    monkeypatch.setenv('STOCK_RAW_DIR',str(forbidden))
    with pytest.raises(capture.AnalysisCaptureError,match='protected_path'): run(target)
    assert not forbidden.exists()


def test_create_read_cli_and_invalid_attempt(research):
    _,target,_=research
    with pytest.raises(capture.AnalysisCaptureError,match='invalid_attempt_id'): run(target,'')
    result=subprocess.run([sys.executable,'-B','-Xutf8','-m','worker.analysis_capture','run','--research-database-path',str(target),'--attempt-id','cli'],text=True,encoding="utf-8",capture_output=True)
    assert result.returncode==0,result.stderr+result.stdout
    assert json.loads(result.stdout)['receipt']['attempt_id']=='cli'


def test_real_version_mismatch_rolls_back(research,monkeypatch):
    _,target,_=research
    before=sha(target)
    original=pipeline._ensure_strategies
    def changed(db):
        strategies=original(db)
        strategies['breakout_v1'].version='unsupported'
        return strategies
    monkeypatch.setattr(pipeline,'_ensure_strategies',changed)
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.detail=='worker_strategy_binding_mismatch'
    assert sha(target)==before


@pytest.mark.parametrize('kind',['trigger','index'])
def test_arbitrary_named_extra_schema_object_rejected(research,kind):
    _,target,_=research
    with sqlite3.connect(target) as db:
        if kind=='trigger': db.execute('CREATE TRIGGER surprise AFTER INSERT ON worker_capture_calls BEGIN SELECT 1; END')
        else: db.execute('CREATE INDEX surprise ON worker_capture_calls(digest)')
    with pytest.raises(capture.AnalysisCaptureError,match='capture_schema_mismatch'): run(target)


def test_environment_directory_file_rejected(research,monkeypatch):
    source,target,_=research
    monkeypatch.setenv('STOCK_RAW_DIR',str(source))
    with pytest.raises(capture.AnalysisCaptureError,match='stock_directory_required'): run(target)


@pytest.mark.parametrize('stage',['copy','schema','readback'])
def test_creation_failure_may_leave_target_never_adopts(research,tmp_path,monkeypatch,stage):
    source,_,_=research
    target=tmp_path/'failed-create.db'
    if stage=='copy':
        original=Path.open
        class FailedOutput:
            def __init__(self,file): self.file=file
            def __enter__(self): return self
            def __exit__(self,*args): self.file.close()
            def write(self,data):
                self.file.write(data[:100])
                raise OSError('copy fault')
        def fail(path,*args,**kwargs):
            file=original(path,*args,**kwargs)
            return FailedOutput(file) if path==target and args[0]=='xb' else file
        monkeypatch.setattr(Path,'open',fail)
    elif stage=='schema': monkeypatch.setitem(capture.SCHEMA,'bad_sql','INVALID DDL')
    else:
        monkeypatch.setattr(capture,'_owner',lambda *_: (_ for _ in ()).throw(OSError('readback fault')))
    original_hash=sha(source)
    with pytest.raises(capture.AnalysisCaptureError) as error:
        capture.create_research_database(source_snapshot_path=source,expected_source_sha256=original_hash,research_database_path=target)
    assert error.value.outcome=='creation_outcome_unknown'
    assert target.exists() and sha(source)==original_hash
    with pytest.raises(capture.AnalysisCaptureError,match='target_exists'):
        capture.create_research_database(source_snapshot_path=source,expected_source_sha256=original_hash,research_database_path=target)
    if stage=='readback':
        with sqlite3.connect(target) as db:
            assert db.execute('SELECT count(*) FROM worker_capture_owner').fetchone()[0]==1


@pytest.mark.parametrize('field',['subject','timestamp','snapshot'])
def test_resealed_inconsistent_capture_rejected(research,field):
    _,target,_=research
    run(target)
    with sqlite3.connect(target) as db:
        db.row_factory=sqlite3.Row
        call=db.execute('SELECT * FROM worker_capture_calls WHERE ordinal=0').fetchone()
        payload=json.loads(call['payload'])
        if field=='subject': payload['subject']['instrument_id']+=100
        elif field=='timestamp': payload['captured_at']='2026-09-14T12:00:00'
        else: payload['signal_snapshot']['unexpected']=True
        digest=capture._seal(payload)
        receipt=json.loads(db.execute('SELECT payload FROM worker_capture_attempts').fetchone()[0])
        receipt['call_digests'][0]=digest
        for table in ('worker_capture_calls','worker_capture_attempts'):
            db.execute('DROP TRIGGER '+table+'_no_update')
        db.execute('UPDATE worker_capture_calls SET payload=?,digest=? WHERE ordinal=0',(capture._canonical(payload),digest))
        db.execute('UPDATE worker_capture_attempts SET payload=?,digest=?',(capture._canonical(receipt),capture._seal(receipt)))
        for table in ('worker_capture_calls','worker_capture_attempts'):
            db.execute(capture.SCHEMA[table+'_no_update'])
    with pytest.raises(capture.AnalysisCaptureError): read(target)


@pytest.mark.parametrize('passed,volume',[(0,50.),(0.0,50.),(1,120.),(1.0,120.)])
def test_capture_actual_passed_bool_cannot_be_numeric(passed,volume):
    from types import SimpleNamespace
    args={'close':101.,'volume':volume,'prior_highs':[100.]*20,'prior_volumes':[100.]*20,'group_excess_return_20d':.1,'institutional_flow_to_turnover_ratio_5d':0.,'margin_balance_change_ratio_5d':0.}
    actual=domain.evaluate_breakout_v1(**args)
    assert actual.passed==passed and type(actual.passed) is not type(passed)
    collector=capture._Collector({},'probe')
    collector.before('breakout_v1',args)
    with pytest.raises(capture.AnalysisCaptureError,match='worker_private_result_mismatch'):
        collector.after('breakout_v1',SimpleNamespace(passed=passed,state=actual.state,reasons=actual.reasons))


def _reseal_calls(target, change, change_receipt=None):
    """Model corruption with valid seals, so exact semantic checks are exercised."""
    with sqlite3.connect(target) as db:
        db.row_factory=sqlite3.Row
        calls=db.execute('SELECT * FROM worker_capture_calls ORDER BY ordinal').fetchall()
        receipt=json.loads(db.execute('SELECT payload FROM worker_capture_attempts').fetchone()[0])
        for table in ('worker_capture_calls','worker_capture_attempts'):
            db.execute('DROP TRIGGER '+table+'_no_update')
        for row in calls:
            payload=json.loads(row['payload'])
            change(payload)
            digest=capture._seal(payload)
            receipt['call_digests'][row['ordinal']]=digest
            db.execute('UPDATE worker_capture_calls SET payload=?,digest=? WHERE ordinal=?',
                (capture._canonical(payload),digest,row['ordinal']))
        if change_receipt is not None:
            change_receipt(receipt)
        db.execute('UPDATE worker_capture_attempts SET payload=?,digest=?',(capture._canonical(receipt),capture._seal(receipt)))
        for table in ('worker_capture_calls','worker_capture_attempts'):
            db.execute(capture.SCHEMA[table+'_no_update'])


@pytest.mark.parametrize('numeric_false',[0,0.0])
def test_read_actual_false_cannot_be_numeric_even_when_resealed(research,numeric_false):
    _,target,_=research
    result=run(target)
    assert all(row['actual_result']['passed'] is False for row in result['captures'])
    _reseal_calls(target,lambda payload:payload['actual_result'].__setitem__('passed',numeric_false))
    with pytest.raises(capture.AnalysisCaptureError,match='capture_result_mismatch'): read(target)


@pytest.mark.parametrize('replacement',[True,1])
def test_read_arguments_float_one_cannot_be_bool_or_int(research,replacement):
    _,target,_=research
    with sqlite3.connect(target) as db: db.execute('UPDATE market_bars SET volume=1')
    result=run(target)
    assert all(type(row['arguments']['volume']) is float and row['arguments']['volume']==1.0 for row in result['captures'])
    _reseal_calls(target,lambda payload:payload['arguments'].__setitem__('volume',replacement))
    with pytest.raises(capture.AnalysisCaptureError,match='capture_result_mismatch'): read(target)


def test_read_arguments_history_int_cannot_be_float(research):
    _,target,_=research
    run(target)
    def change(payload):
        history=payload['arguments']['prior_volumes']
        assert type(history[0]) is int
        history[0]=float(history[0])
    _reseal_calls(target,change)
    with pytest.raises(capture.AnalysisCaptureError,match='capture_result_mismatch'): read(target)


@pytest.mark.parametrize('field',['config_json','canonical_config_snapshot'])
def test_worker_config_number_cannot_be_bool(research,field):
    _,target,_=research
    engine=create_engine('sqlite:///'+target.as_posix())
    with Session(engine) as db:
        strategy=pipeline._ensure_strategies(db)['breakout_v1']
        config=copy.deepcopy(getattr(strategy,field))
        metric=config['confirmations']['group_relative_strength']
        assert metric['minimum_excess_return']==0.0
        metric['minimum_excess_return']=False
        setattr(strategy,field,config)
        # SQLAlchemy JSON dirty comparison also treats False == 0.0; force the
        # deliberate malformed stored value so this tests the reader binding.
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(strategy,field)
        db.commit()
    engine.dispose()
    before=sha(target)
    with pytest.raises(capture.AnalysisCaptureError) as error: run(target)
    assert error.value.detail=='worker_strategy_binding_mismatch'
    assert sha(target)==before


def test_read_selected_config_number_cannot_be_bool(research):
    _,target,_=research
    run(target)
    def change(payload):
        payload['selected_strategy']['config']['confirmations']['group_relative_strength']['minimum_excess_return']=False
    _reseal_calls(target,change)
    with pytest.raises(capture.AnalysisCaptureError,match='capture_strategy_link_mismatch'): read(target)


def test_v2_selected_bar_actual_calls_raw_metadata_and_mode_conflict(research, monkeypatch):
    source, target, _ = research
    source_hash = sha(source)
    raw_id = _link_selected_raw(target)
    observed = []
    for name in ('breakout_v1', 'pullback_v1'):
        original = getattr(pipeline, 'evaluate_' + name)

        def spy(_name=name, _original=original, **kwargs):
            observed.append((_name, copy.deepcopy(kwargs)))
            return _original(**kwargs)

        monkeypatch.setattr(pipeline, 'evaluate_' + name, spy)
    result = capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='v2-one',
        input_provenance='selected-bar/v1',
    )
    assert result['receipt']['kind'] == capture.KIND_V2
    assert len(result['captures']) == len(observed) == 8
    assert read(target, 'v2-one')['captures'] == result['captures']
    for call, (name, kwargs) in zip(result['captures'], observed):
        evidence = call['input_provenance']
        bar = evidence['bar']
        assert call['evaluator'] == name and call['arguments'] == kwargs
        assert evidence['schema'] == capture.SELECTED_BAR_SCHEMA
        assert evidence['coverage'] == ['close', 'volume']
        assert evidence['raw_bytes_verification'] == 'bytes_unverified'
        assert bar['instrument_id'] == call['subject']['instrument_id']
        assert bar['trading_date'] == call['observed_market_date']
        assert type(call['arguments']['close']) is float
        assert type(call['arguments']['volume']) is float
        assert call['arguments']['close'] == float(bar['close'])
        assert call['arguments']['volume'] == float(bar['volume'])
        if call['subject']['exchange'] == 'TWSE':
            assert evidence['raw_status'] == 'linked_metadata'
            assert bar['raw_payload_id'] == evidence['raw_payload']['id'] == raw_id
            assert evidence['raw_payload']['sha256'] == 'a'*64
            assert evidence['raw_payload']['payload_path'] == 'never-opened/raw.json'
            assert evidence['raw_payload']['collected_at'] == '2026-09-26 01:02:03.000000'
        else:
            assert evidence['raw_status'] == 'unknown'
            assert evidence['raw_reason'] == 'raw_payload_id_missing'
            assert evidence['raw_payload'] is None
    for first, second in zip(result['captures'][::2], result['captures'][1::2]):
        assert first['input_provenance'] == second['input_provenance']
    before = sha(target)
    assert capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='v2-one',
        input_provenance='selected-bar/v1',
    )['idempotent_reuse'] is True
    with pytest.raises(capture.AnalysisCaptureError, match='attempt_mode_conflict'):
        capture.execute_analysis_attempt(research_database_path=target, attempt_id='v2-one')
    for bad in (True, 1, '', 'selected-bar/v2'):
        with pytest.raises(capture.AnalysisCaptureError, match='invalid_input_provenance'):
            capture.execute_analysis_attempt(
                research_database_path=target, attempt_id='invalid-mode', input_provenance=bad,
            )
    assert sha(target) == before and sha(source) == source_hash
    v1 = run(target, 'v1-next')
    assert v1['receipt']['kind'] == capture.KIND
    assert all('input_provenance' not in call for call in v1['captures'])
    with pytest.raises(capture.AnalysisCaptureError, match='attempt_mode_conflict'):
        capture.execute_analysis_attempt(
            research_database_path=target, attempt_id='v1-next',
            input_provenance='selected-bar/v1',
        )
    with sqlite3.connect(target) as db:
        db.execute("UPDATE raw_payloads SET source='mismatched' WHERE id=?", (raw_id,))
    before = sha(target)
    with pytest.raises(capture.AnalysisCaptureError) as error:
        capture.execute_analysis_attempt(
            research_database_path=target, attempt_id='v2-bad-raw',
            input_provenance='selected-bar/v1',
        )
    assert error.value.outcome == 'rollback_confirmed'
    assert error.value.detail == 'selected_bar_raw_relation_invalid'
    assert sha(target) == before


def test_v2_old_row_evidence_survives_source_change_and_new_attempt_reads_new_row(research):
    _, target, _ = research
    first = capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='v2-first',
        input_provenance='selected-bar/v1',
    )
    old_evidence = copy.deepcopy(first['captures'][0]['input_provenance'])
    score_date = first['receipt']['analysis']['date']
    with sqlite3.connect(target) as db:
        db.execute(
            "UPDATE market_bars SET close=close+2,volume=volume+3,source='changed' "
            "WHERE trading_date=?", (score_date,),
        )
    assert read(target, 'v2-first')['captures'][0]['input_provenance'] == old_evidence
    second = capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='v2-second',
        input_provenance='selected-bar/v1',
    )
    new_evidence = second['captures'][0]['input_provenance']
    assert new_evidence['bar']['close'] == old_evidence['bar']['close'] + 2
    assert new_evidence['bar']['volume'] == old_evidence['bar']['volume'] + 3
    assert new_evidence['bar']['source'] == 'changed'
    assert read(target, 'v2-first')['captures'][0]['input_provenance'] == old_evidence


def test_v2_selected_bar_failure_rolls_back_signal_feature_and_attempt(research, monkeypatch):
    _, target, _ = research
    before = sha(target)
    original = capture._Collector.selected_bar_provenance
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise capture.AnalysisCaptureError('injected_selected_bar_failure')
        return original(self, *args, **kwargs)

    monkeypatch.setattr(capture._Collector, 'selected_bar_provenance', fail_second)
    with pytest.raises(capture.AnalysisCaptureError) as error:
        capture.execute_analysis_attempt(
            research_database_path=target, attempt_id='v2-failed',
            input_provenance='selected-bar/v1',
        )
    assert error.value.outcome == 'rollback_confirmed'
    assert error.value.detail == 'injected_selected_bar_failure'
    assert sha(target) == before
    with pytest.raises(capture.AnalysisCaptureError, match='attempt_not_found'):
        read(target, 'v2-failed')


@pytest.mark.parametrize('change,expected', [
    (lambda p: p['input_provenance']['bar'].__setitem__('instrument_id', 999), 'selected_bar_subject_date_mismatch'),
    (lambda p: p['input_provenance']['bar'].__setitem__('trading_date', '2026-05-01'), 'selected_bar_subject_date_mismatch'),
    (lambda p: p['input_provenance']['bar'].__setitem__('raw_payload_id', 1), 'selected_bar_raw_relation_invalid'),
    (lambda p: p['input_provenance']['bar'].__setitem__('close', 1.0), 'selected_bar_arguments_mismatch'),
    (lambda p: p['input_provenance']['bar'].__setitem__('volume', True), 'selected_bar_value_invalid'),
    (lambda p: p['input_provenance'].__setitem__('schema', 'unsupported'), 'selected_bar_provenance_shape_invalid'),
    (lambda p: p['input_provenance'].pop('coverage'), 'selected_bar_provenance_shape_invalid'),
    (lambda p: p['input_provenance'].__setitem__('extra', True), 'selected_bar_provenance_shape_invalid'),
])
def test_v2_resealed_provenance_inconsistency_fails_closed(research, change, expected):
    _, target, _ = research
    capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='one',
        input_provenance='selected-bar/v1',
    )
    _reseal_calls(target, change)
    with pytest.raises(capture.AnalysisCaptureError, match=expected):
        read(target)


def test_v2_resealed_pair_and_version_mixing_fail_closed(research):
    _, target, _ = research
    capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='one',
        input_provenance='selected-bar/v1',
    )

    def change_one(payload):
        if payload['ordinal'] == 0:
            payload['input_provenance']['bar']['source'] = 'changed'

    _reseal_calls(target, change_one)
    with pytest.raises(capture.AnalysisCaptureError, match='capture_pair_provenance_mismatch'):
        read(target)
    _reseal_calls(target, lambda payload: payload['input_provenance']['bar'].__setitem__('source', 'unknown'))
    assert read(target)['receipt']['kind'] == capture.KIND_V2
    _reseal_calls(target, lambda payload: None,
                  lambda receipt: receipt.__setitem__('kind', capture.KIND))
    with pytest.raises(capture.AnalysisCaptureError, match='capture_keys_mismatch'):
        read(target)
    _reseal_calls(target, lambda payload: None,
                  lambda receipt: receipt.__setitem__('kind', 'worker-analysis-capture/unknown'))
    with pytest.raises(capture.AnalysisCaptureError, match='attempt_manifest_mismatch'):
        read(target)


def test_v2_selected_bar_native_nonfinite_and_bool_rejected():
    provenance = {
        'schema': capture.SELECTED_BAR_SCHEMA,
        'coverage': ['close', 'volume'],
        'bar': {
            'id': 1, 'instrument_id': 2, 'trading_date': '2026-05-01',
            'close': 1.0, 'volume': 2, 'source': 'unknown',
            'raw_payload_id': None, 'data_as_of': None, 'collected_at': None,
        },
        'raw_payload': None, 'raw_status': 'unknown',
        'raw_reason': 'raw_payload_id_missing',
        'raw_bytes_verification': 'bytes_unverified',
    }
    for bad in (True, float('nan'), float('inf'), float('-inf')):
        changed = copy.deepcopy(provenance)
        changed['bar']['close'] = bad
        with pytest.raises(capture.AnalysisCaptureError, match='selected_bar_value_invalid'):
            capture._validate_selected_bar_provenance(
                changed, {'close': 1.0, 'volume': 2.0},
                subject={'instrument_id': 2}, market_date='2026-05-01',
            )


def test_v2_reader_does_not_import_worker_or_config(research):
    _, target, _ = research
    capture.execute_analysis_attempt(
        research_database_path=target, attempt_id='v2-read',
        input_provenance='selected-bar/v1',
    )
    code = (
        "from worker.analysis_capture import read_analysis_attempt; import sys; "
        "r=read_analysis_attempt(research_database_path=sys.argv[1],attempt_id='v2-read'); "
        "assert r['receipt']['kind']=='worker-analysis-capture/v2'; "
        "assert 'worker.pipeline' not in sys.modules; assert 'app.config' not in sys.modules"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith('STOCK_')}
    result = subprocess.run(
        [sys.executable, '-B', '-c', code, str(target)], env=env,
        text=True, encoding='utf-8', capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def _run_prior_volumes(target, attempt='prior-one'):
    return capture.execute_analysis_attempt(
        research_database_path=target, attempt_id=attempt,
        input_provenance=capture.PRIOR_VOLUMES_MODE,
    )


@pytest.mark.parametrize('history_count', [0, 1, 19, 20, 64])
def test_v3_freezes_exact_producer_tail_and_short_history(research, history_count):
    _, target, _ = research
    day = date(2026, 5, 1) + timedelta(days=history_count)
    with sqlite3.connect(target) as db:
        db.execute('UPDATE ingestion_runs SET data_as_of=?,run_date=?',
                   (day.isoformat(), day.isoformat()))
    result = _run_prior_volumes(target)
    assert result['receipt']['kind'] == capture.KIND_V3
    assert len(result['captures']) == 8
    expected = [100 + number for number in range(max(0, history_count - 20), history_count)]
    for call in result['captures']:
        evidence = call['input_provenance']
        prior = evidence['prior_volumes']
        assert call['arguments']['prior_volumes'] == prior['projected_values'] == expected
        assert prior['row_count'] == min(history_count, 20)
        assert [item['ordinal'] for item in prior['rows']] == list(range(len(expected)))
        assert [item['bar']['volume'] for item in prior['rows']] == expected
        assert all(item['bar']['trading_date'] < day.isoformat() for item in prior['rows'])
        assert all(item['raw_status'] == 'unknown' and item['raw_reason'] == 'raw_payload_id_missing'
                   for item in prior['rows'])
        assert evidence['selected_bar']['coverage'] == ['close', 'volume']
        if history_count < 20:
            assert call['actual_result']['state'] == 'data_incomplete'
    assert read(target, 'prior-one')['captures'] == result['captures']


def test_v3_zero_volume_is_preserved_and_evaluator_remains_incomplete(research):
    _, target, _ = research
    with sqlite3.connect(target) as db:
        db.execute("UPDATE market_bars SET volume=0 WHERE trading_date='2026-07-03'")
    result = _run_prior_volumes(target)
    for call in result['captures']:
        assert call['input_provenance']['prior_volumes']['projected_values'][-1] == 0
        assert call['actual_result']['state'] == 'data_incomplete'


def test_v3_equal_values_keep_distinct_row_identity_and_raw_relation(research):
    _, target, _ = research
    with sqlite3.connect(target) as db:
        run_id = db.execute('SELECT id FROM ingestion_runs').fetchone()[0]
        raw_id = db.execute(
            'INSERT INTO raw_payloads '
            '(ingestion_run_id,source,endpoint,payload_path,sha256,data_as_of,collected_at) '
            'VALUES (?,?,?,?,?,?,?)',
            (run_id, 'twse', 'local-only', 'not-opened.json', 'a' * 64, None,
             '2026-09-27 00:00:00'),
        ).lastrowid
        db.execute("UPDATE market_bars SET volume=777 WHERE trading_date='2026-07-02'")
        db.execute("UPDATE market_bars SET volume=777,source='twse',raw_payload_id=? "
                   "WHERE trading_date='2026-07-03'", (raw_id,))
    result = _run_prior_volumes(target)
    rows = result['captures'][0]['input_provenance']['prior_volumes']['rows']
    assert rows[-2]['bar']['volume'] == rows[-1]['bar']['volume'] == 777
    assert rows[-2]['bar']['id'] != rows[-1]['bar']['id']
    assert rows[-2]['bar']['trading_date'] != rows[-1]['bar']['trading_date']
    assert rows[-2]['raw_status'] == 'unknown'
    assert rows[-1]['raw_status'] == 'linked_metadata'
    assert rows[-1]['raw_payload']['id'] == raw_id
    assert rows[-1]['raw_payload']['sha256'] == 'a' * 64


@pytest.mark.parametrize('change,expected', [
    ('row', 'prior_volumes_source_relation_changed'),
    ('feature', 'prior_volumes_feature_mismatch'),
])
def test_v3_change_between_producer_and_call_rolls_back(research, monkeypatch, change, expected):
    _, target, _ = research
    before = sha(target)
    original = pipeline._calculate_group_scores

    def mutate_after_features(db, score_date):
        original(db, score_date)
        if change == 'row':
            db.execute(text('UPDATE market_bars SET volume=volume+1 WHERE id=( '
                            'SELECT id FROM market_bars WHERE trading_date<:day '
                            'ORDER BY trading_date DESC LIMIT 1)'), {'day': score_date.isoformat()})
        else:
            db.execute(text("UPDATE technical_features SET features_json='{}' "
                            'WHERE trading_date=:day'), {'day': score_date.isoformat()})

    monkeypatch.setattr(pipeline, '_calculate_group_scores', mutate_after_features)
    with pytest.raises(capture.AnalysisCaptureError) as error:
        _run_prior_volumes(target)
    assert error.value.outcome == 'rollback_confirmed'
    assert error.value.detail == expected
    assert sha(target) == before
    with pytest.raises(capture.AnalysisCaptureError, match='attempt_not_found'):
        read(target, 'prior-one')


@pytest.mark.parametrize('volume', [100.5, -1])
def test_v3_rejects_unsupported_producer_volume_without_commit(research, volume):
    _, target, _ = research
    with sqlite3.connect(target) as db:
        db.execute("UPDATE market_bars SET volume=? WHERE trading_date='2026-07-03'", (volume,))
    before = sha(target)
    with pytest.raises(capture.AnalysisCaptureError) as error:
        _run_prior_volumes(target)
    assert error.value.outcome == 'rollback_confirmed'
    assert error.value.detail == 'prior_volumes_bar_invalid'
    assert sha(target) == before


def test_v3_dangling_prior_raw_fk_rejected_and_old_attempt_survives_source_change(research):
    _, target, _ = research
    first = _run_prior_volumes(target)
    old = copy.deepcopy(first['captures'][0]['input_provenance']['prior_volumes'])
    with sqlite3.connect(target) as db:
        db.execute("UPDATE market_bars SET volume=volume+2 WHERE trading_date='2026-07-03'")
    assert read(target, 'prior-one')['captures'][0]['input_provenance']['prior_volumes'] == old
    second = _run_prior_volumes(target, 'prior-two')
    assert second['captures'][0]['input_provenance']['prior_volumes']['projected_values'][-1] == old['projected_values'][-1] + 2
    with sqlite3.connect(target) as db:
        db.execute("UPDATE market_bars SET raw_payload_id=987654 WHERE trading_date='2026-07-03'")
    before = sha(target)
    with pytest.raises(capture.AnalysisCaptureError) as error:
        _run_prior_volumes(target, 'prior-bad')
    assert error.value.outcome == 'rollback_confirmed'
    assert error.value.detail == 'prior_volumes_raw_relation_invalid'
    assert sha(target) == before


@pytest.mark.parametrize('change,expected', [
    (lambda p: p['input_provenance']['prior_volumes'].__setitem__('row_count', 19), 'prior_volumes_count_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['rows'][0].__setitem__('ordinal', 1), 'prior_volumes_row_shape_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['rows'][0]['bar'].__setitem__('trading_date', p['observed_market_date']), 'prior_volumes_order_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['rows'][0]['bar'].__setitem__('volume', True), 'prior_volumes_bar_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['rows'][0]['bar'].__setitem__('raw_payload_id', 3), 'prior_volumes_raw_relation_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['subject'].__setitem__('instrument_id', 999), 'prior_volumes_subject_date_mismatch'),
])
def test_v3_resealed_prior_relation_inconsistency_fails_closed(research, change, expected):
    _, target, _ = research
    _run_prior_volumes(target, 'one')
    _reseal_calls(target, change)
    with pytest.raises(capture.AnalysisCaptureError, match=expected):
        read(target)


def test_v3_pair_mixing_and_attempt_mode_conflict(research):
    _, target, _ = research
    first = _run_prior_volumes(target, 'one')
    assert _run_prior_volumes(target, 'one')['idempotent_reuse'] is True
    for mode in (None, capture.INPUT_PROVENANCE_MODE):
        with pytest.raises(capture.AnalysisCaptureError, match='attempt_mode_conflict'):
            capture.execute_analysis_attempt(
                research_database_path=target, attempt_id='one', input_provenance=mode)
    assert read(target)['captures'] == first['captures']

    def change_one(payload):
        if payload['ordinal'] == 0:
            payload['input_provenance']['prior_volumes']['rows'][0]['bar']['source'] = 'changed'

    _reseal_calls(target, change_one)
    with pytest.raises(capture.AnalysisCaptureError, match='capture_pair_provenance_mismatch'):
        read(target)


def _minimal_prior_provenance():
    subject = {'instrument_id': 1, 'market': 'TW', 'exchange': 'TWSE', 'symbol': 'TEST'}
    return {
        'schema': capture.PRIOR_VOLUMES_SCHEMA, 'subject': subject,
        'target_date': '2026-05-03', 'window': 20, 'transform': 'int(volume)',
        'feature': {'id': 5, 'instrument_id': 1, 'trading_date': '2026-05-03',
                    'source': 'derived'},
        'row_count': 2,
        'rows': [
            {'ordinal': ordinal,
             'bar': {'id': 11 + ordinal, 'instrument_id': 1,
                     'trading_date': f'2026-05-0{ordinal + 1}',
                     'volume': volume, 'source': 'twse', 'raw_payload_id': None},
             'raw_payload': None, 'raw_status': 'unknown',
             'raw_reason': 'raw_payload_id_missing'}
            for ordinal, volume in enumerate((100, 200))
        ],
        'projected_values': [100, 200], 'raw_bytes_verification': 'bytes_unverified',
    }


def _link_minimal_raw(provenance):
    row = provenance['rows'][0]
    row['bar']['raw_payload_id'] = 7
    row['raw_payload'] = {'id': 7, 'source': 'twse', 'endpoint': 'local-only',
                          'sha256': None, 'ingestion_run_id': None}
    row['raw_status'] = 'linked_metadata'
    row['raw_reason'] = None


@pytest.mark.parametrize('field,replacement,expected', [
    ('window', 20.0, 'prior_volumes_provenance_shape_invalid'),
    ('window', True, 'prior_volumes_provenance_shape_invalid'),
    ('feature.instrument_id', 1.0, 'prior_volumes_feature_invalid'),
    ('feature.instrument_id', True, 'prior_volumes_feature_invalid'),
    ('rows.0.bar.instrument_id', 1.0, 'prior_volumes_bar_invalid'),
    ('rows.0.bar.instrument_id', True, 'prior_volumes_bar_invalid'),
    ('rows.0.raw_payload.id', 7.0, 'prior_volumes_raw_relation_invalid'),
    ('rows.0.raw_payload.id', True, 'prior_volumes_raw_relation_invalid'),
])
def test_v3_identity_types_reject_equal_float_and_bool_in_memory(field, replacement, expected):
    provenance = _minimal_prior_provenance()
    if 'raw_payload' in field:
        _link_minimal_raw(provenance)
    item = provenance
    parts = field.split('.')
    for part in parts[:-1]:
        item = item[int(part)] if part.isdigit() else item[part]
    item[parts[-1]] = replacement
    with pytest.raises(capture.AnalysisCaptureError, match=expected):
        capture._validate_prior_volumes_provenance(
            provenance, {'prior_volumes': [100, 200]},
            subject=_minimal_prior_provenance()['subject'], market_date='2026-05-03')


def _reverse_prior_rows(provenance):
    provenance['rows'].reverse()
    provenance['projected_values'].reverse()
    for ordinal, row in enumerate(provenance['rows']):
        row['ordinal'] = ordinal


@pytest.mark.parametrize('change,expected', [
    (lambda p: p['rows'][1]['bar'].__setitem__('id', 11), 'prior_volumes_order_invalid'),
    (lambda p: p['rows'][1]['bar'].__setitem__('trading_date', '2026-05-01'), 'prior_volumes_order_invalid'),
    (_reverse_prior_rows, 'prior_volumes_order_invalid'),
    (lambda p: p['rows'].pop(), 'prior_volumes_count_invalid'),
    (lambda p: p['rows'].append(copy.deepcopy(p['rows'][-1])), 'prior_volumes_count_invalid'),
    (lambda p: p['projected_values'].__setitem__(0, 101), 'prior_volumes_value_mismatch'),
    (lambda p: p['rows'][0]['bar'].__setitem__('volume', float('nan')), 'prior_volumes_bar_invalid'),
])
def test_v3_relation_shape_fail_closed_in_memory(change, expected):
    provenance = _minimal_prior_provenance()
    change(provenance)
    with pytest.raises(capture.AnalysisCaptureError, match=expected):
        capture._validate_prior_volumes_provenance(
            provenance, {'prior_volumes': [100, 200]},
            subject=_minimal_prior_provenance()['subject'], market_date='2026-05-03')


def test_v3_nullable_raw_sha_and_missing_fk_are_distinct_valid_local_states():
    provenance = _minimal_prior_provenance()
    _link_minimal_raw(provenance)
    capture._validate_prior_volumes_provenance(
        provenance, {'prior_volumes': [100, 200]},
        subject=provenance['subject'], market_date='2026-05-03')
    assert provenance['rows'][0]['raw_payload']['sha256'] is None
    assert provenance['rows'][1]['raw_status'] == 'unknown'


@pytest.mark.parametrize('kind', ['instrument_float', 'raw_id_float'])
def test_v3_resealed_both_pair_rows_reject_identity_type(research, kind):
    _, target, _ = research
    raw_id = None
    if kind == 'raw_id_float':
        with sqlite3.connect(target) as db:
            run_id = db.execute('SELECT id FROM ingestion_runs').fetchone()[0]
            raw_id = db.execute(
                'INSERT INTO raw_payloads '
                '(ingestion_run_id,source,endpoint,payload_path,sha256,data_as_of,collected_at) '
                'VALUES (?,?,?,?,?,?,?)',
                (run_id, 'twse', 'local-only', None, None, None, '2026-09-27 00:00:00'),
            ).lastrowid
            db.execute("UPDATE market_bars SET source='twse',raw_payload_id=? "
                       "WHERE trading_date='2026-07-03'", (raw_id,))
    _run_prior_volumes(target, 'one')
    if kind == 'instrument_float':
        _reseal_calls(target, lambda p: p['input_provenance']['prior_volumes']['feature']
                      .__setitem__('instrument_id', float(p['subject']['instrument_id'])))
        expected = 'prior_volumes_feature_invalid'
    else:
        _reseal_calls(target, lambda p: p['input_provenance']['prior_volumes']['rows'][-1]
                      ['raw_payload'].__setitem__('id', float(raw_id)))
        expected = 'prior_volumes_raw_relation_invalid'
    with pytest.raises(capture.AnalysisCaptureError, match=expected):
        read(target)


@pytest.mark.parametrize('change,expected', [
    (lambda p: p['input_provenance'].__setitem__('extra', True), 'input_provenance_v3_shape_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['rows'].pop(), 'prior_volumes_count_invalid'),
    (lambda p: p['input_provenance']['prior_volumes']['projected_values'].__setitem__(0, 999), 'prior_volumes_value_mismatch'),
])
def test_v3_resealed_nonselected_call_corruption_rejected(research, change, expected):
    _, target, _ = research
    _run_prior_volumes(target, 'one')
    _reseal_calls(target, lambda p: change(p) if p['evaluator'] != p['selected_strategy']['name'] else None)
    with pytest.raises(capture.AnalysisCaptureError, match=expected):
        read(target)


def test_v3_resealed_receipt_kind_mixing_rejected(research):
    _, target, _ = research
    _run_prior_volumes(target, 'one')
    _reseal_calls(target, lambda p: None,
                  lambda receipt: receipt.__setitem__('kind', capture.KIND_V2))
    with pytest.raises(capture.AnalysisCaptureError, match='selected_bar_provenance_shape_invalid'):
        read(target)
