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


def _reseal_calls(target, change):
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
