from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, enable_sqlite_foreign_keys
from app.models import GroupMembership, ThemeGroup, Instrument, IngestionRun, RawPayload
from app.taxonomy import canonical_group_id
from worker import pipeline, sources

D = date(2026, 9, 4)
HOT = canonical_group_id('new-listings', 'new-listings')
OFFICIAL = 'TWSE/TPEx official OpenAPI'


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'membership.db'}")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, 'SessionLocal', factory)
    monkeypatch.setattr(pipeline, 'init_db', lambda: None)
    monkeypatch.setattr(sources, 'RAW_DIR', tmp_path / 'raw')
    yield factory
    engine.dispose()


def observation(kind='etf', day=D, exchange='TWSE', **changes):
    endpoint = ({'TWSE': sources.TWSE_ETF_ENDPOINT, 'TPEx': sources.TPEX_ETF_ENDPOINT} if kind == 'etf'
                else {'TWSE': sources.TWSE_LISTED_ENDPOINT, 'TPEx': sources.TPEX_LISTED_ENDPOINT})[exchange]
    cap = sources.capture_payload(exchange.lower(), endpoint, {'symbol': 'AAA', 'kind': kind},
        '1900-01-01', collected_at=datetime.combine(day, datetime.min.time()) + timedelta(hours=1))
    rec = sources.InstrumentRecord('AAA', 'Alpha', exchange=exchange, instrument_type=kind,
        industry='24', etf_category='broad_market' if kind == 'etf' else None,
        listing_date=date(2000, 1, 1), payload_sha256=cap.sha256)
    return cap, replace(rec, **changes)


def apply(db, cap, rec, *, score=date(2026, 12, 31), captures=None):
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == rec.symbol, Instrument.exchange == rec.exchange))
    if instrument is None:
        instrument = Instrument(symbol=rec.symbol, name=rec.name, exchange=rec.exchange,
                                market='TW', instrument_type=rec.instrument_type)
        db.add(instrument)
        db.flush()
    return pipeline._ensure_official_groups(db, [rec], {(rec.exchange, rec.symbol): instrument},
        date(1990, 1, 1), score, payloads=captures if captures is not None else [cap],
        observed_now=datetime(2027, 1, 1))


def periods(db, domain='etf'):
    return [(r.group_id, r.valid_from, r.valid_to, r.source) for r in db.scalars(
        select(GroupMembership).where(GroupMembership.group_id.like('official-etf-%') if domain == 'etf'
                                      else GroupMembership.group_id == HOT).order_by(GroupMembership.valid_from))]


def snapshot(db):
    return ([(r.id, r.name, r.group_type, r.source, r.definition_version, r.active) for r in db.scalars(select(ThemeGroup).order_by(ThemeGroup.id))],
            [(r.group_id, r.instrument_id, r.valid_from, r.valid_to, r.source) for r in db.scalars(select(GroupMembership).order_by(GroupMembership.id))])


@pytest.mark.parametrize('exchange', ['TWSE', 'TPEx'])
def test_etf_observed_transition_repeat_and_reentry(env, exchange):
    with env() as db:
        cap, rec = observation(exchange=exchange)
        result = apply(db, cap, rec, captures=iter([cap]))
        receipt = result['etf']['observations'][0]
        assert periods(db)[0][1:] == (D, None, f'{OFFICIAL}; exchange={exchange}')
        assert receipt['classification_method'] == 'local_heuristic_from_official_universe'
        assert receipt['observed_date'] == D.isoformat() and receipt['endpoint'] == cap.endpoint
        apply(db, *observation(day=D + timedelta(days=1), exchange=exchange))
        assert len(periods(db)) == 1
        apply(db, *observation(day=D + timedelta(days=2), exchange=exchange, etf_category='bond'))
        apply(db, *observation(day=D + timedelta(days=3), exchange=exchange))
        assert [(r[1], r[2]) for r in periods(db)] == [(D, D + timedelta(days=1)), (D + timedelta(days=2), D + timedelta(days=2)), (D + timedelta(days=3), None)]


@pytest.mark.parametrize('category', [None, '', ' ', 'garbage', 'BOND'])
def test_missing_category_preserves_history_without_caller_rollback(env, category):
    with env() as db:
        apply(db, *observation())
        before = snapshot(db)
        with pytest.raises(sources.OfficialDataError, match='ETF classification'):
            apply(db, *observation(day=D + timedelta(days=1), etf_category=category))
        assert snapshot(db) == before


@pytest.mark.parametrize('domain', ['etf', 'newlisting'])
@pytest.mark.parametrize('problem', ['same_day', 'future', 'inverted', 'overlap', 'closed'])
def test_period_conflicts_are_atomic(env, domain, problem):
    with env() as db:
        kind = 'etf' if domain == 'etf' else 'ipo'
        cap, rec = observation(kind=kind, listing_date=D)
        apply(db, cap, rec)
        row = db.scalar(select(GroupMembership).where(GroupMembership.group_id.like('official-etf-%') if domain == 'etf' else GroupMembership.group_id == HOT))
        if problem == 'future':
            row.valid_from = D + timedelta(days=3)
        elif problem == 'inverted':
            row.valid_to = D - timedelta(days=1)
        elif problem == 'overlap':
            db.add(GroupMembership(group_id=row.group_id, instrument_id=row.instrument_id, valid_from=D-timedelta(days=1), source=row.source))
        elif problem == 'closed':
            row.valid_to = D + timedelta(days=2)
        db.flush()
        before = snapshot(db)
        day = D if problem == 'same_day' else D + timedelta(days=1)
        if domain == 'etf':
            pair = observation(day=day, etf_category='bond', listing_date=D)
        else:
            pair = observation(kind='etf', day=day, listing_date=D)
        with pytest.raises(sources.OfficialDataError):
            apply(db, *pair)
        assert snapshot(db) == before


@pytest.mark.parametrize('domain', ['etf', 'newlisting'])
@pytest.mark.parametrize('field,value', [('name','Wrong'), ('group_type','manual'), ('definition_version','other'), ('source','manual'), ('active',False)])
def test_canonical_collision_is_not_overwritten(env, domain, field, value):
    with env() as db:
        pair = observation(kind='etf' if domain == 'etf' else 'ipo', listing_date=D)
        apply(db, *pair)
        group = db.get(ThemeGroup, periods(db, domain)[0][0])
        setattr(group, field, value)
        db.flush()
        before = snapshot(db)
        with pytest.raises(sources.OfficialDataError, match='identity'):
            apply(db, *pair)
        assert snapshot(db) == before


@pytest.mark.parametrize('domain', ['etf', 'newlisting'])
def test_manual_same_key_rejected_and_other_domains_untouched(env, domain):
    with env() as db:
        pair = observation(kind='etf' if domain == 'etf' else 'ipo', listing_date=D)
        apply(db, *pair)
        row = db.scalar(select(GroupMembership).where(GroupMembership.group_id == periods(db, domain)[0][0]))
        row.source = 'manual'
        db.flush()
        before = snapshot(db)
        with pytest.raises(sources.OfficialDataError, match='manual'):
            apply(db, *pair)
        assert snapshot(db) == before


@pytest.mark.parametrize('age', [0, 60, 61, -1])
@pytest.mark.parametrize('kind', ['stock', 'ipo'])
def test_listing_window_is_bounded_and_date_driven(env, age, kind):
    with env() as db:
        pair = observation(kind=kind, listing_date=D-timedelta(days=age))
        apply(db, *pair)
        if age in (0,60):
            assert periods(db, 'newlisting')[0][1:3] == (D, D+timedelta(days=60-age))
            apply(db, *pair)
            assert len(periods(db,'newlisting')) == 1
        else:
            assert periods(db,'newlisting') == []


def test_bounded_listing_expires_without_future_collection_and_never_extends(env):
    with env() as db:
        apply(db, *observation(kind='ipo', listing_date=D))
        expiry = D + timedelta(days=60)
        assert pipeline._effective_memberships(db, HOT, expiry)
        assert pipeline._effective_memberships(db, HOT, expiry+timedelta(days=1)) == []
        before = periods(db,'newlisting')
        apply(db, *observation(kind='stock', day=expiry+timedelta(days=1), listing_date=D))
        assert periods(db,'newlisting') == before
        with pytest.raises(sources.OfficialDataError, match='expiry'):
            apply(db, *observation(kind='stock', day=expiry+timedelta(days=2), listing_date=expiry))


@pytest.mark.parametrize('age,action', [(10,'legacy_window_cap'), (61,'legacy_forward_close')])
def test_legacy_open_listing_is_repaired_only_forward(env, age, action):
    with env() as db:
        apply(db, *observation(kind='ipo', listing_date=D))
        row = db.scalar(select(GroupMembership).where(GroupMembership.group_id == HOT))
        row.valid_from = D-timedelta(days=2)
        row.valid_to = None
        db.flush()
        day = D+timedelta(days=age)
        result = apply(db, *observation(kind='stock', day=day, listing_date=D))
        assert row.valid_from == D-timedelta(days=2)
        assert row.valid_to == (D+timedelta(days=60) if age == 10 else day-timedelta(days=1))
        receipt = result['newlisting']['observations'][0]
        assert receipt['action'] == action and receipt['historical_limit']


def test_missing_listing_retains_hot_but_authoritative_stock_closes_etf(env):
    with env() as db:
        apply(db, *observation())
        result = apply(db, *observation(kind='stock', day=D+timedelta(days=1), listing_date=None))
        assert periods(db)[0][2] == D
        assert result['newlisting']['unresolved_count'] == 1
        apply(db, *observation(kind='ipo', day=D+timedelta(days=2), listing_date=D))
        before = periods(db,'newlisting')
        result = apply(db, *observation(kind='stock', day=D+timedelta(days=3), listing_date=None))
        assert periods(db,'newlisting') == before


def test_bounded_ipo_to_etf_closes_hot_without_changing_industry(env):
    with env() as db:
        apply(db, *observation(kind='ipo', listing_date=D))
        industry = [(r.group_id,r.valid_from,r.valid_to) for r in db.scalars(select(GroupMembership).join(ThemeGroup).where(ThemeGroup.group_type=='official_industry'))]
        apply(db, *observation(day=D+timedelta(days=1), listing_date=D))
        assert periods(db,'newlisting')[0][2] == D
        assert [(r.group_id,r.valid_from,r.valid_to) for r in db.scalars(select(GroupMembership).join(ThemeGroup).where(ThemeGroup.group_type=='official_industry'))] == industry


def test_index_absent_and_custom_hot_groups_are_retained(env):
    with env() as db:
        apply(db, *observation())
        instrument = db.scalar(select(Instrument))
        group = ThemeGroup(id='official-twse-manual', name='Manual', group_type='daily_hot_group', active=True, source='manual')
        db.add(group); db.flush()
        db.add(GroupMembership(group_id=group.id,instrument_id=instrument.id,valid_from=D,source=OFFICIAL))
        db.flush()
        before = snapshot(db)
        result = apply(db, *observation(kind='index', day=D+timedelta(days=1)))
        assert result['etf']['unresolved_count'] == result['newlisting']['unresolved_count'] == 1
        assert snapshot(db) == before
        pipeline._ensure_official_groups(db, [], {}, D, D, payloads=[], observed_now=datetime(2026,9,5))
        assert snapshot(db) == before
        apply(db, *observation(kind='stock', day=D+timedelta(days=2)))
        assert group.active and db.scalar(select(GroupMembership).where(GroupMembership.group_id==group.id)).valid_to is None


@pytest.mark.parametrize('kind', ['etf','stock','ipo'])
def test_capture_after_score_skips_both_domains(env, kind):
    with env() as db:
        result = apply(db, *observation(kind=kind,listing_date=D), score=D-timedelta(days=1))
        assert snapshot(db) == ([],[])
        assert result['etf']['skipped_count'] == result['newlisting']['skipped_count'] == 1


@pytest.mark.parametrize('change', [{'source':'wrong'}, {'endpoint':'https://invalid'}, {'sha256':'wrong'}, {'collected_at':None}, {'collected_at':datetime(2099,1,1)}])
def test_bad_etf_capture_is_rejected(env, change):
    with env() as db:
        cap, rec = observation()
        with pytest.raises(sources.OfficialDataError):
            apply(db, replace(cap,**change), rec)
        assert snapshot(db) == ([],[])


def test_duplicate_capture_rejected(env):
    with env() as db:
        cap,rec=observation()
        with pytest.raises(sources.OfficialDataError):
            apply(db,cap,rec,captures=[cap,cap])
        assert snapshot(db)==([],[])


def test_timezone_rollover_uses_capture_not_requested_or_listing_date(env):
    with env() as db:
        cap,rec=observation()
        cap=replace(cap,collected_at=datetime(2026,9,3,17,tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-5))))
        result=apply(db,cap,rec)
        assert periods(db)[0][1]==D
        assert result['etf']['observations'][0]['captured_at_utc']=='2026-09-03T17:00:00+00:00'


def test_future_listing_with_existing_history_rejects_atomically(env):
    with env() as db:
        apply(db,*observation(kind='stock',listing_date=D))
        before=snapshot(db)
        with pytest.raises(sources.OfficialDataError,match='future listing'):
            apply(db,*observation(kind='stock',day=D+timedelta(days=1),listing_date=D+timedelta(days=2)))
        assert snapshot(db)==before


def test_industry_changes_rollback_when_listing_preflight_fails(env):
    with env() as db:
        apply(db,*observation(kind='ipo',listing_date=D))
        before=snapshot(db)
        with pytest.raises(sources.OfficialDataError):
            apply(db,*observation(kind='ipo',day=D+timedelta(days=1),listing_date=D+timedelta(days=2),industry='01'))
        assert snapshot(db)==before

@pytest.mark.parametrize('domain', ['etf','newlisting'])
@pytest.mark.parametrize('field,value', [('name','Wrong'),('active',False)])
def test_prior_group_identity_conflict_blocks_exit(env,domain,field,value):
    with env() as db:
        apply(db,*observation(kind='etf' if domain=='etf' else 'ipo',listing_date=D))
        group=db.get(ThemeGroup,periods(db,domain)[0][0])
        setattr(group,field,value);db.flush()
        before=snapshot(db)
        pair=observation(kind='stock' if domain=='etf' else 'etf',day=D+timedelta(days=1),listing_date=D)
        with pytest.raises(sources.OfficialDataError,match='identity'):
            apply(db,*pair)
        assert snapshot(db)==before


def test_future_listed_record_cannot_close_etf_history(env):
    with env() as db:
        apply(db,*observation())
        before=snapshot(db)
        with pytest.raises(sources.OfficialDataError,match='future listing'):
            apply(db,*observation(kind='stock',day=D+timedelta(days=1),listing_date=D+timedelta(days=2)))
        assert snapshot(db)==before


class UniverseFetcher:
    """Local wire-shaped fixtures exercise the production exchange parsers."""
    def __call__(self,url,**kwargs):
        rows={
            sources.TWSE_LISTED_ENDPOINT:[{'Code':'1101','Name':'Stock','Industry':'01','DateOfListing':'2026/09/01'}],
            sources.TWSE_ETF_ENDPOINT:[{'FundCode':'0050','Name':'Taiwan 50 ETF','FundType':'broad market','DateOfListing':'2003/06/30'}],
            sources.TWSE_NEW_LISTING_ENDPOINT:[{'Code':'9999','Name':'New','ApprovedListingDate':'2026/09/02'}],
            sources.TPEX_LISTED_ENDPOINT:[{'SecuritiesCompanyCode':'7001','CompanyName':'OTC','SecuritiesIndustryCode':'20','DateOfListing':'2026/09/03'}],
            sources.TPEX_ETF_ENDPOINT:{'status':'success','data':[{'stockNo':'00679B','stockName':'Bond ETF','listingDate':'2020/01/02','indexName':''}]},
        }
        return rows[url]


def parsed_batch(monkeypatch, day=D):
    original=sources.capture_payload
    def capture(*args,**kwargs):
        return original(*args,**{**kwargs,'collected_at':datetime.combine(day,datetime.min.time())+timedelta(hours=1)})
    with monkeypatch.context() as patch:
        patch.setattr(sources,'capture_payload',capture)
        twse,tpayloads=sources.TwseAdapter(UniverseFetcher()).fetch_universe(D)
        tpex,opayloads=sources.TpexAdapter(UniverseFetcher()).fetch_universe(D)
    records=twse+tpex
    payloads=tpayloads+opayloads
    records.append(sources.InstrumentRecord('TAIEX','Index',instrument_type='index',payload_sha256=payloads[0].sha256))
    bars=[sources.BarRecord(r.symbol,D,100,101,99,100,1000,100000,exchange=r.exchange,payload_sha256=r.payload_sha256) for r in records]
    return sources.OfficialBatch(instruments=records,bars=bars,payloads=payloads)


def test_both_market_parsers_collect_raw_binding_force_and_failure_history(env,monkeypatch):
    batch=parsed_batch(monkeypatch)
    def collect(batch,force=False):
        return pipeline.collect(D,adapter=SimpleNamespace(fetch=lambda *_:batch),force=force)
    first=collect(batch)
    assert first['status']=='success',first
    result=first['industry_membership_observations']
    etfs=[r for r in result['etf']['observations'] if r.get('instrument_type')=='etf']
    assert {r['normalized_category'] for r in etfs}=={'broad_market','bond'}
    assert {r['endpoint'] for r in etfs}=={sources.TWSE_ETF_ENDPOINT,sources.TPEX_ETF_ENDPOINT}
    assert all(r['classification_method_version']=='normalize_etf_category-v1' for r in etfs)
    with env() as db:
        for receipt in etfs:
            raw=db.get(RawPayload,receipt['raw_payload_id'])
            assert (raw.source,raw.endpoint,raw.sha256)==(receipt['source'],receipt['endpoint'],receipt['sha256'])
        listings=db.scalars(select(GroupMembership).where(GroupMembership.group_id==HOT)).all()
        assert len(listings)==3 and all(r.valid_from==D and r.valid_to is not None for r in listings)
    later=replace(batch,payloads=[replace(p,collected_at=p.collected_at+timedelta(days=1)) for p in batch.payloads])
    forced=collect(later,True)
    assert forced['status']=='success',forced
    nodes=forced['industry_membership_observations']
    for domain in ['etf','newlisting']:
        observations=[r for r in nodes[domain]['observations'] if 'captured_at_utc' in r]
        assert all(r['captured_at_utc'].startswith('2026-09-05') for r in observations)
        assert all(r['stored_raw_collected_at_utc'].startswith('2026-09-04') for r in observations)
        assert nodes[domain]['skipped_count']==5
    reused=collect(later)
    assert reused['idempotent_reuse'] and reused['industry_membership_observations']==nodes
    bad=replace(batch,instruments=[replace(r,etf_category=None) if r.instrument_type=='etf' else r for r in batch.instruments])
    failed=collect(bad,True)
    assert failed['status']=='failed'
    with env() as db:
        run=db.get(IngestionRun,first['run_id'])
        assert run.metadata_json['industry_membership_observations']==nodes
        assert 'ETF classification' in run.metadata_json['industry_failed_attempts'][-1]['error']
        assert len(db.scalars(select(GroupMembership).where(GroupMembership.group_id==HOT)).all())==3

@pytest.mark.parametrize('domain',['etf','newlisting'])
def test_wrong_exchange_provenance_is_rejected(env,domain):
    with env() as db:
        pair=observation(kind='etf' if domain=='etf' else 'ipo',listing_date=D)
        apply(db,*pair)
        row=db.scalar(select(GroupMembership).where(GroupMembership.group_id==periods(db,domain)[0][0]))
        row.source=f'{OFFICIAL}; exchange=TPEx';db.flush()
        before=snapshot(db)
        with pytest.raises(sources.OfficialDataError,match='exchange conflict'):
            apply(db,*pair)
        assert snapshot(db)==before


@pytest.mark.parametrize('timestamp',[None,'bad'])
def test_collect_bad_etf_timestamp_keeps_failure_audit(env,monkeypatch,timestamp):
    batch=parsed_batch(monkeypatch)
    bad=replace(batch,payloads=[replace(p,collected_at=timestamp) if p.endpoint==sources.TWSE_ETF_ENDPOINT else p for p in batch.payloads])
    result=pipeline.collect(D,adapter=SimpleNamespace(fetch=lambda *_:bad))
    assert result['status']=='failed'
    with env() as db:
        assert db.scalars(select(GroupMembership)).all()==[]
        run=db.get(IngestionRun,result['run_id'])
        attempt=run.metadata_json['industry_observation_attempt']
        capture=next(p for p in attempt['captures'] if p['endpoint']==sources.TWSE_ETF_ENDPOINT)
        assert capture['timestamp_status']=='missing_or_invalid'
        assert attempt['raw_persistence_errors']

@pytest.mark.parametrize('commit', [False, True])
def test_sqlite_read_only_outer_transaction_owns_successful_memberships(env, commit):
    # A SELECT starts SQLAlchemy's logical transaction but does not issue BEGIN
    # in sqlite3 legacy mode.  Exercise separate sessions on a real file DB.
    with env() as db:
        db.add(Instrument(symbol='AAA',name='Alpha',exchange='TWSE',market='TW',instrument_type='etf'))
        db.commit()
    with env() as db:
        assert db.scalar(select(Instrument)) is not None
        assert not db.new and not db.dirty and not db.deleted
        apply(db,*observation())
        if commit:
            db.commit()
        else:
            db.rollback()
    with env() as db:
        assert len(db.scalars(select(GroupMembership)).all()) == (1 if commit else 0)
        assert len(db.scalars(select(ThemeGroup)).all()) == (1 if commit else 0)
        assert len(db.scalars(select(Instrument)).all()) == 1


def test_helper_failure_savepoint_preserves_caller_pending_writes(env, monkeypatch):
    with env() as db:
        db.add(Instrument(symbol='AAA',name='Alpha',exchange='TWSE',market='TW',instrument_type='stock'))
        db.commit()
    with env() as db:
        caller_group=ThemeGroup(id='caller-pending',name='Caller',group_type='manual',source='manual',active=True)
        db.add(caller_group)
        assert caller_group in db.new
        def fail_after_industry(*args,**kwargs):
            raise sources.OfficialDataError('injected after industry projection')
        monkeypatch.setattr(pipeline,'_nonindustry_observations',fail_after_industry)
        with pytest.raises(sources.OfficialDataError,match='after industry'):
            apply(db,*observation(kind='stock'))
        assert db.get(ThemeGroup,'caller-pending') is caller_group
        assert db.scalars(select(GroupMembership)).all()==[]
        assert [g.id for g in db.scalars(select(ThemeGroup))]==['caller-pending']
        db.commit()
    with env() as db:
        assert [g.id for g in db.scalars(select(ThemeGroup))]==['caller-pending']
        assert db.scalars(select(GroupMembership)).all()==[]
        assert db.scalar(select(Instrument)).symbol=='AAA'


def test_collect_failure_after_helper_rolls_back_normalized_writes(env,monkeypatch):
    from app.models import MarketBar
    batch=parsed_batch(monkeypatch)
    def fail_after_memberships(db):
        assert db.scalars(select(GroupMembership)).all()
        raise sources.OfficialDataError('injected after memberships')
    monkeypatch.setattr(pipeline,'sync_news_from_events',fail_after_memberships)
    result=pipeline.collect(D,adapter=SimpleNamespace(fetch=lambda *_:batch))
    assert result['status']=='failed'
    with env() as db:
        for model in [Instrument,MarketBar,GroupMembership,ThemeGroup]:
            assert db.scalars(select(model)).all()==[]
        assert len(db.scalars(select(RawPayload)).all())==5
        run=db.get(IngestionRun,result['run_id'])
        assert run.status=='failed' and 'after memberships' in run.error
