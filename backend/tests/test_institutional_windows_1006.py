"""Standalone synthetic checks and coordinator-only empty-store live entry.

Use -B -X utf8 and existing dependencies. Guards precede worker/API imports;
normal config mkdir/startup/conftest are never executed. Serve defaults to mock.
Live serve never constructs synthetic institutional bodies or preloads a cache.
"""
from __future__ import annotations
import argparse
import ast
import base64
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
import hashlib
import io
import csv
import json
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--deps')
parser.add_argument('--worker-only', action='store_true')
parser.add_argument('--worker-case')
parser.add_argument('--api-only', action='store_true')
parser.add_argument('--serve', action='store_true')
parser.add_argument('--live-source-opt-in', action='store_true')
parser.add_argument('--policy-version')
parser.add_argument('--policy-digest')
parser.add_argument('--port', type=int, default=8799)
ARGS = parser.parse_args()
if ARGS.live_source_opt_in and not ARGS.serve:
    raise ValueError('live_requires_coordinator_serve')
sys.dont_write_bytecode = True
if ARGS.deps:
    sys.path.insert(0, str(Path(ARGS.deps).resolve()))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
GUARDS = {'disk_writes': 0, 'mutations': 0, 'unapproved_network': 0}
ACTIVE_LIVE = False
APPROVED_ADDRESSES: set = set()
API_MODE = not (ARGS.worker_only or ARGS.worker_case)


def audit(event, args):
    if event == 'open' and ((isinstance(args[1], str) and any(value in args[1] for value in 'wax+')) or
            (isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
        GUARDS['disk_writes'] += 1
        raise AssertionError('disk_write_denied')
    if event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.link', 'os.symlink', 'tempfile.mkstemp', 'tempfile.mkdtemp', 'subprocess.Popen'}:
        GUARDS['mutations'] += 1
        raise AssertionError('filesystem_or_subprocess_denied')
    if event == 'sqlite3.connect' and args[0] != ':memory:':
        raise AssertionError('physical_database_denied')
    if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'}:
        address = args[1] if event in {'socket.connect', 'socket.bind'} else args[0]
        local = isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}
        frame, pair = sys._getframe(1), False
        while frame:
            pair = pair or ('socketpair' in frame.f_code.co_name and frame.f_code.co_filename.endswith('socket.py'))
            frame = frame.f_back
        allowed = API_MODE and local and pair
        allowed = allowed or (ARGS.serve and event == 'socket.bind' and local and address[1] == ARGS.port)
        if event in {'socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr'}:
            allowed = allowed or address in {'localhost', '127.0.0.1', '::1', None}
            allowed = allowed or (ACTIVE_LIVE and ARGS.live_source_opt_in and address in {'www.tpex.org.tw', b'www.tpex.org.tw'} and (event != 'socket.getaddrinfo' or args[1] == 443))
        if event == 'socket.connect' and ACTIVE_LIVE and ARGS.live_source_opt_in:
            allowed = isinstance(address, tuple) and (address[0], address[1]) in APPROVED_ADDRESSES
        if not allowed:
            GUARDS['unapproved_network'] += 1
            raise AssertionError('unapproved_network_denied')


sys.addaudithook(audit)
from worker import tpex_institutional_1006 as chips
import httpx

OBSERVED = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)


def csv_body(header, rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\r\n')
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def daily_row(day, symbol, ordinal=1, large=False):
    # A reconstructable small fixture, not the coordinator's actual reference.
    foreign = (9223372036854775807, 0, 9223372036854775807) if large else (100 + ordinal, 20, 80 + ordinal)
    foreign_dealer = (0, 0, 0) if large else (2, 1, 1)
    trust = (0, 0, 0) if large else (3, 10 + ordinal, -7 - ordinal)
    own, hedge = ((0, 0, 0), (0, 0, 0)) if large else ((10, 3, 7), (7 + ordinal, 4, 3 + ordinal))
    total_foreign = tuple(a + b for a, b in zip(foreign, foreign_dealer))
    dealer = tuple(a + b for a, b in zip(own, hedge))
    values = [value for group in (foreign, foreign_dealer, total_foreign, trust, own, hedge, dealer) for value in group]
    return [f'{day.year - 1911:03d}{day.month:02d}{day.day:02d}', symbol, 'Synthetic ' + symbol,
            *map(str, values), str(foreign[2] + trust[2] + dealer[2])]


def make_capture(source, day, body):
    return chips.CapturedCSV1006(source, day, chips.source_url(source, day), body, hashlib.sha256(body).hexdigest(),
        OBSERVED, OBSERVED, chips.POLICY_VERSION, chips.POLICY_DIGEST, chips.PROFILE,
        chips.window_policy()['sources'][source]['source_version'])


def captures(large=False):
    items = []
    for month in chips.MONTH_REQUESTS:
        rows = [[day.strftime('%Y%m%d'), '10', '12', '9', '11', '1'] for day in chips.EXPECTED_SESSIONS if day.month == month.month]
        items.append(make_capture(chips.INDEX_SOURCE_ID, month, csv_body(chips.INDEX_HEADER, rows)))
    for ordinal, day in enumerate(chips.DAILY_REQUESTS, 1):
        items.append(make_capture(chips.DAILY_SOURCE_ID, day, csv_body(chips.DAILY_HEADER, [daily_row(day, symbol, ordinal, large) for symbol in chips.SYMBOLS])))
    assert sum(len(item.body) for item in items) <= 24 * 1024, 'synthetic_body_batch_quota'
    assert chips.retained_graph_estimate(items) <= 1024 * 1024, 'synthetic_graph_quota'
    return tuple(items)


def summarize(items, **overrides):
    arguments = dict(policy=chips.window_policy(), profile=chips.PROFILE, expected_policy_version=chips.POLICY_VERSION,
                     expected_policy_digest=chips.POLICY_DIGEST, as_of=chips.CUTOFF, calendar_version=chips.CALENDAR_VERSION)
    arguments.update(overrides)
    return chips.summarize_window_captures(items, **arguments)


def cache(**extra):
    return chips.MemoryWindowCache1006(policy=chips.window_policy(), profile=chips.PROFILE,
        expected_policy_version=chips.POLICY_VERSION, expected_policy_digest=chips.POLICY_DIGEST, **extra)


def changed(item, body):
    return replace(item, body=body, body_sha256=hashlib.sha256(body).hexdigest())


class WorkerTests(unittest.TestCase):
    def test_independent_policy_sources_and_original_receipt(self):
        items = captures()
        self.assertEqual(chips._digest(chips.window_policy()), chips.POLICY_DIGEST)
        self.assertEqual((len(items), len(chips.EXPECTED_SESSIONS), len(chips.DAILY_REQUESTS)), (22, 24, 20))
        self.assertEqual(chips.WINDOW_DATES[5][0], date(2026, 9, 30))
        result = summarize(items)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['calendar']['expected_dates'], [day.isoformat() for day in chips.EXPECTED_SESSIONS])
        self.assertLess(chips.retained_graph_estimate((items, result)), 1024 * 1024)
        for symbol in chips.SYMBOLS:
            for horizon in (5, 20):
                window = result['stocks'][symbol]['windows'][str(horizon)]
                selected = range(21 - horizon, 21)
                self.assertEqual(window['values'], {'foreign': str(sum(80 + i for i in selected)), 'trust': str(sum(-7 - i for i in selected)), 'dealer': str(sum(10 + i for i in selected))})
                self.assertEqual(len(window['daily_evidence']), horizon)
                for evidence in window['daily_evidence']:
                    self.assertEqual(len(evidence['row']['source_values']), 25)
                    raw = next(item for item in items if item.source_id == chips.DAILY_SOURCE_ID and item.requested_date.isoformat() == evidence['row']['date'])
                    self.assertEqual(evidence['provenance']['receipt_sha256'], chips._digest(raw.receipt()))

    def test_policy_calendar_and_date_gates_without_http(self):
        for arguments in ({'expected_policy_digest': 'sha256:' + '0'*64}, {'expected_policy_version': 'm1-w8-tpex-window-2026-10-05.1'},
                          {'calendar_version': 'old'}, {'as_of': date(2026, 10, 2)}):
            self.assertEqual(summarize(captures(), **arguments)['status'], 'unavailable')
        for day in (date(2026, 9, 1), date(2026, 10, 7)):
            with self.assertRaises(chips.WindowEvidenceError): chips.source_url(chips.DAILY_SOURCE_ID, day)

    def test_calendar_full_rows_missing_extra_closed_and_bad_values(self):
        items = captures()
        original = list(csv.reader(io.StringIO(items[0].body.decode('utf-8'))))[1:]
        variants = [original[:-1], original + [original[0]], original + [['20260925','10','12','9','11','1']],
                    original + [['20261007','10','12','9','11','1']]]
        bad = [list(row) for row in original]; bad[0][2] = 'NaN'; variants.append(bad)
        bad = [list(row) for row in original]; bad[0][3] = '13'; variants.append(bad)
        for rows in variants:
            result = summarize((changed(items[0], csv_body(chips.INDEX_HEADER, rows)), *items[1:]))
            self.assertEqual(result['calendar']['status'], 'unavailable')
        self.assertEqual(summarize(items[1:])['calendar']['status'], 'unavailable')

    def test_no_blank_record_bom_roc_or_width_relaxation(self):
        items = captures()
        for body in (items[0].body + b'\r\n', b'\xef\xbb\xbf' + items[0].body,
                     items[0].body.replace(b'20260901', b'1150901'), items[0].body.replace(b',10,12,9,11,1', b',10,12,9,11')):
            self.assertEqual(summarize((changed(items[0], body), *items[1:]))['calendar']['status'], 'unavailable')

    def test_missing_early_daily_only_rejects_twenty(self):
        result = summarize((*captures()[:2], *captures()[3:]))
        for stock in result['stocks'].values():
            self.assertEqual(stock['windows']['5']['status'], 'available')
            self.assertEqual(stock['windows']['20']['values'], None)
            self.assertEqual(stock['windows']['20']['missing_dates'], ['2026-09-07'])

    def test_daily_structure_selected_relations_and_canonical_quantity(self):
        items, day = captures(), chips.DAILY_REQUESTS[-1]
        original = daily_row(day, '3105', 20)
        for offset in (5,8,11,14,17,20,23,24):
            row = list(original); row[offset] = str(int(row[offset]) + 1)
            body = csv_body(chips.DAILY_HEADER, [row, daily_row(day, '6488', 20)])
            self.assertEqual(summarize((*items[:-1], changed(items[-1], body)))['stocks']['3105']['windows']['5']['status'], 'unavailable')
        for bad in ('01', '-0', '+1', '1.0', '9223372036854775808'):
            row = list(original); row[3] = bad
            self.assertEqual(summarize((*items[:-1], changed(items[-1], csv_body(chips.DAILY_HEADER, [row, daily_row(day,'6488',20)]))))['status'], 'unavailable')
        for rows in ([original], [original, original], [original, daily_row(day,'6488',20), [original[0], 'A000', ''] + ['']*22]):
            self.assertEqual(summarize((*items[:-1], changed(items[-1], csv_body(chips.DAILY_HEADER,rows))))['status'], 'unavailable')

    def test_exact_int64_inputs_unbounded_window_sum_and_zero(self):
        result = summarize(captures(large=True))
        self.assertEqual(result['stocks']['3105']['windows']['20']['values'], {'foreign': str(20*9223372036854775807), 'trust':'0','dealer':'0'})

    def test_capture_hash_pin_source_mime_encoding_utc(self):
        items = captures()
        replacements = [dict(body_sha256='0'*64), dict(policy_digest='sha256:'+'0'*64), dict(source_version='old'),
            dict(method='POST'), dict(http_status=True), dict(content_type='application/json'), dict(content_encoding='gzip'),
            dict(captured_at=OBSERVED-timedelta(seconds=1)), dict(request_started_at=OBSERVED.replace(tzinfo=None))]
        for replacement in replacements:
            self.assertEqual(summarize((*items[:-1], replace(items[-1], **replacement)))['status'], 'unavailable')

    def test_once_only_calendar_before_daily_and_bad_calendar_no_daily(self):
        items, requests = captures(), []
        bodies = {item.url:item.body for item in items}
        def handler(request):
            requests.append(str(request.url)); return httpx.Response(200, headers={'Content-Type':'application/csv;charset=utf-8'}, stream=httpx.ByteStream(bodies[str(request.url)]))
        store = cache(); transport = httpx.MockTransport(handler)
        first = store.load(as_of=chips.CUTOFF,calendar_version=chips.CALENDAR_VERSION,transport=transport)
        self.assertEqual(first['status'],'available'); self.assertEqual(requests,[item.url for item in items])
        store.load(as_of=chips.CUTOFF,calendar_version=chips.CALENDAR_VERSION,transport=transport)
        self.assertEqual(len(requests),22); self.assertEqual(store.snapshot()['status'],'available')
        requests.clear(); bodies[items[0].url] = b'bad\n'
        store = cache(); self.assertEqual(store.load(as_of=chips.CUTOFF,calendar_version=chips.CALENDAR_VERSION,transport=transport)['calendar']['status'],'unavailable')
        self.assertEqual(len(requests),2)

    def test_deadline_stream_size_header_and_failure_never_retry(self):
        items = captures(); now, requests = [0.0], []
        def handler(request):
            requests.append(str(request.url)); now[0] = 181.0
            return httpx.Response(200,headers={'Content-Type':'application/csv'},stream=httpx.ByteStream(items[0].body))
        store = cache(clock=lambda:now[0]); result = store.load(as_of=chips.CUTOFF,calendar_version=chips.CALENDAR_VERSION,transport=httpx.MockTransport(handler))
        self.assertEqual(result['reasons'],['chips_batch_deadline_exceeded']); self.assertEqual(len(requests),1)
        store.load(as_of=chips.CUTOFF,calendar_version=chips.CALENDAR_VERSION,transport=httpx.MockTransport(handler)); self.assertEqual(len(requests),1)
        for headers in ({'Content-Type':'application/csv','x-too-big':'x'*chips.MAX_RESPONSE_HEADER_BYTES}, {'Content-Type':'application/csv','Content-Encoding':'gzip'}):
            store=cache(); store.load(as_of=chips.CUTOFF,calendar_version=chips.CALENDAR_VERSION,transport=httpx.MockTransport(lambda request:httpx.Response(200,headers=headers,stream=httpx.ByteStream(b'bad'))))
            self.assertEqual(store.request_count,2); self.assertFalse(any(item.source_id==chips.DAILY_SOURCE_ID for item in store.raw_captures))

    def test_small_scaled_stream_body_total_and_retained_limits(self):
        # Exercise production boundary branches without constructing large bodies.
        items = captures()
        for limit_name in ('MAX_INDEX_BYTES', 'MAX_TOTAL_BYTES'):
            requests = []
            def handler(request):
                requests.append(str(request.url))
                return httpx.Response(200, headers={'Content-Type':'application/csv'}, stream=httpx.ByteStream(items[0].body))
            store = cache()
            with patch.object(chips, limit_name, len(items[0].body)-1):
                result = store.load(as_of=chips.CUTOFF, calendar_version=chips.CALENDAR_VERSION, transport=httpx.MockTransport(handler))
                self.assertEqual(result['reasons'], ['chips_capture_body_or_total_size_limit'])
                self.assertEqual(store.raw_captures, ())
                store.load(as_of=chips.CUTOFF, calendar_version=chips.CALENDAR_VERSION, transport=httpx.MockTransport(handler))
                self.assertEqual(len(requests), 1)
        with patch.object(chips, 'MAX_RETAINED_ESTIMATE_BYTES', chips.retained_graph_estimate((items, chips.window_policy(), ()))-1):
            self.assertEqual(summarize(items)['reasons'], ['chips_retained_graph_size_limit'])


def stub_config():
    if 'app.config' in sys.modules: return
    filename = Path(__file__).resolve().parents[1] / 'app/config.py'
    tree = ast.parse(filename.read_text(encoding='utf-8'), filename=str(filename))
    tree.body = [node for node in tree.body if not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
                 and isinstance(node.value.func,ast.Attribute) and node.value.func.attr=='mkdir')]
    config = types.ModuleType('app.config'); config.__file__=str(filename)
    exec(compile(tree,str(filename),'exec'),config.__dict__)
    config.DATA_DIR,config.RAW_DIR,config.DB_PATH=Path('__memory_only__'),Path('__memory_only__/raw'),Path(':memory:')
    sys.modules['app.config']=config


class ApprovedLiveTransport(httpx.BaseTransport):
    def __init__(self):
        if not ARGS.serve or not ARGS.live_source_opt_in or ARGS.policy_version != chips.POLICY_VERSION or ARGS.policy_digest != chips.POLICY_DIGEST:
            raise ValueError('root_live_opt_in_and_external_pins_required')
        self.urls={chips.source_url(chips.INDEX_SOURCE_ID,day) for day in chips.MONTH_REQUESTS}|{chips.source_url(chips.DAILY_SOURCE_ID,day) for day in chips.DAILY_REQUESTS}
        self.requests=[]; self.original_resolver=socket.getaddrinfo
        def resolver(host,port,*args,**kwargs):
            values=self.original_resolver(host,port,*args,**kwargs)
            if ACTIVE_LIVE and host in {'www.tpex.org.tw',b'www.tpex.org.tw'} and port==443:
                APPROVED_ADDRESSES.update((item[4][0],item[4][1]) for item in values)
            return values
        self.resolver=resolver;socket.getaddrinfo=resolver
        self.inner=httpx.HTTPTransport(retries=0,trust_env=False)
    def handle_request(self,request):
        global ACTIVE_LIVE
        target=str(request.url)
        if request.method!='GET' or target not in self.urls or target in self.requests or len(self.requests)>=22:
            raise AssertionError('unapproved_or_repeated_source_request')
        self.requests.append(target);ACTIVE_LIVE=True
        try:return self.inner.handle_request(request)
        finally:ACTIVE_LIVE=False
    def close(self):
        self.inner.close()
        if socket.getaddrinfo is self.resolver:socket.getaddrinfo=self.original_resolver


class MemoryAPIFixture1006:
    def __init__(self, *, live=False, failure=None):
        stub_config()
        from fastapi import FastAPI
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import StaticPool
        from app import api, institutional_windows_1006 as wrapper, institutional_windows as old
        from app.db import Base
        from app.models import Instrument, MarketBar
        self.wrapper,self.api=wrapper,api
        self.requests=[]; self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            identities = (('TPEx','3105','穩懋'),('TPEx','6488','環球晶')) if live else (('TPEx','3105','Synthetic 3105'),('TPEx','6488','Synthetic 6488'),('TPEx','9999','Synthetic 9999'),('TWSE','3105','Synthetic 3105'))
            for exchange,symbol,name in identities:
                instrument=Instrument(market='TW',exchange=exchange,symbol=symbol,name=name,instrument_type='stock',status='active')
                db.add(instrument);db.flush()
                if not live:
                    db.add(MarketBar(instrument_id=instrument.id,trading_date=chips.CUTOFF,open=10,high=12,low=9,close=11,adj_close=11,volume=1000,source='synthetic-memory',is_suspended=False))
            db.commit()
        def database():
            with Session(self.engine) as db:yield db
        self.app=FastAPI();self.app.include_router(api.router);self.app.dependency_overrides[api.get_db]=database
        if live:
            self.transport=ApprovedLiveTransport()
        else:
            bodies={item.url:item.body for item in captures()}
            def handler(request):
                self.requests.append(str(request.url))
                if failure=='calendar' and str(request.url)==chips.source_url(chips.INDEX_SOURCE_ID,chips.MONTH_REQUESTS[0]):
                    return httpx.Response(200,headers={'Content-Type':'application/csv'},stream=httpx.ByteStream(b'bad\n'))
                if failure=='timeout' and str(request.url)==chips.source_url(chips.DAILY_SOURCE_ID,chips.DAILY_REQUESTS[0]):
                    raise httpx.ReadTimeout('synthetic timeout',request=request)
                return httpx.Response(200,headers={'Content-Type':'application/csv;charset=utf-8'},stream=httpx.ByteStream(bodies[str(request.url)]))
            self.transport=httpx.MockTransport(handler)
        self.store=wrapper.InstitutionalWindowStore1006(transport=self.transport)
        self.store_patch=patch.object(wrapper,'STORE',self.store);self.store_patch.start()
        self.old_store=old.InstitutionalWindowStore(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError('old_source_unapproved'))))
        self.old_patch=patch.object(old,'STORE',self.old_store);self.old_patch.start()
        self.env_patch=patch.dict(os.environ,{wrapper.ENABLE_ENV:'1',wrapper.VERSION_ENV:chips.POLICY_VERSION,wrapper.DIGEST_ENV:chips.POLICY_DIGEST,
            old.ENABLE_ENV:'0','STOCK_TPEX_PRICE_MEMORY_CAPTURE':'0','STOCK_PRICE_PRIVATE_SAVE':'0'});self.env_patch.start()
        self.before=self.database_snapshot()
        @self.app.get('/__chips1006_validation/receipt')
        def receipt():return self.receipt()

    def database_snapshot(self):
        with self.engine.connect() as connection:
            names=[row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            result={}
            for name in names:
                quoted='"'+name.replace('"','""')+'"'
                schema=[tuple(row) for row in connection.exec_driver_sql('PRAGMA table_info('+quoted+')')]
                columns=[row[1] for row in schema]
                expressions=','.join('typeof("'+column.replace('"','""')+'")' for column in columns)
                result[name]={'schema':schema,'columns':columns,
                    'create_sql':connection.exec_driver_sql('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',name)).scalar(),
                    'values':[tuple(row) for row in connection.exec_driver_sql('SELECT * FROM '+quoted+' ORDER BY rowid')],
                    'types':[tuple(row) for row in connection.exec_driver_sql('SELECT '+expressions+' FROM '+quoted+' ORDER BY rowid')]}
            return result
    def receipt(self):
        raw=self.store.raw_captures
        return {'mode':'live-empty-store' if ARGS.live_source_opt_in else 'synthetic-memory',
            'source_requests':list(self.transport.requests if isinstance(self.transport,ApprovedLiveTransport) else self.requests),
            'captures':[{**item.receipt(),'receipt_sha256':chips._digest(item.receipt())} for item in raw],
            'snapshots':{symbol:self.store.read('TPEx',symbol,chips.CUTOFF) for symbol in chips.SYMBOLS},
            'db_preserved':self.database_snapshot()==self.before,'db_tables':len(self.before),'guard':dict(GUARDS),'disk_artifacts':0,
            'retained_raw_graph_estimate_bytes':chips.retained_graph_estimate(raw),'memory_basis':'deduplicated_sys_getsizeof; not_RSS_or_peak'}
    def close(self):
        self.env_patch.stop();self.store_patch.stop();self.old_patch.stop();self.transport.close();self.engine.dispose()


class APITests(unittest.TestCase):
    def test_actual_router_same_cutoff_stock_default_and_w8_isolation(self):
        from fastapi.testclient import TestClient
        fixture=MemoryAPIFixture1006()
        try:
            with TestClient(fixture.app) as client:
                for route in ('/api/stocks/TPEx/3105','/api/stocks/TPEx/3105/overview'):
                    client.get(route);self.assertEqual(fixture.requests,[])
                default=client.post('/api/stocks/TPEx/3105/institutional-windows/capture').json()
                self.assertEqual(default['version'],'institutional-windows/w8-v1');self.assertEqual(fixture.requests,[])
                first=client.post('/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06').json()
                self.assertEqual(first['status'],'available');self.assertEqual(first['capture_state']['request_count'],22)
                for symbol in chips.SYMBOLS:
                    post=client.post(f'/api/stocks/TPEx/{symbol}/institutional-windows/capture?as_of=2026-10-06').json()
                    detail=client.get(f'/api/stocks/TPEx/{symbol}?as_of=2026-10-06').json()['overview']
                    overview=client.get(f'/api/stocks/TPEx/{symbol}/overview?as_of=2026-10-06').json()
                    self.assertEqual(detail['institutional'],post);self.assertEqual(overview['institutional'],post)
                    self.assertEqual(post['symbol'],symbol);self.assertEqual(post['version'],'institutional-windows/chips-1006-v1')
                self.assertEqual(len(fixture.requests),22);self.assertEqual(fixture.old_store.raw_captures,())
                old=client.get('/api/stocks/TPEx/3105/overview?as_of=2026-10-02').json()
                self.assertEqual(old['institutional']['version'],'institutional-windows/w8-v1')
                self.assertEqual(fixture.database_snapshot(),fixture.before);self.assertEqual(len(fixture.before),19)
        finally:fixture.close()

    def test_scope_external_pins_configuration_and_bad_input_never_fetch(self):
        from fastapi.testclient import TestClient
        fixture=MemoryAPIFixture1006()
        try:
            with TestClient(fixture.app) as client:
                for exchange,symbol,day in (('TWSE','3105','2026-10-06'),('TPEx','9999','2026-10-06'),('TPEx','3105','2026-10-07')):
                    self.assertEqual(client.post(f'/api/stocks/{exchange}/{symbol}/institutional-windows/capture?as_of={day}').json()['status'],'unavailable')
                self.assertEqual(client.post('/api/stocks/TPEx/missing/institutional-windows/capture?as_of=2026-10-06').status_code,404)
                self.assertEqual(client.post('/api/stocks/TPEx/3105/institutional-windows/capture?as_of=bad').status_code,422)
                for key,value in ((fixture.wrapper.ENABLE_ENV,'0'),(fixture.wrapper.ENABLE_ENV,'bad'),(fixture.wrapper.DIGEST_ENV,'old'),(fixture.wrapper.VERSION_ENV,'old')):
                    with patch.dict(os.environ,{key:value}):self.assertEqual(client.post('/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06').json()['status'],'unavailable')
                self.assertEqual(fixture.requests,[])
        finally:fixture.close()

    def test_busy_calendar_failure_and_missing_early_daily_one_shot(self):
        from fastapi.testclient import TestClient
        for failure,count in (('calendar',2),('timeout',22)):
            fixture=MemoryAPIFixture1006(failure=failure)
            try:
                with TestClient(fixture.app) as client:
                    fixture.store._lock.acquire()
                    try:self.assertEqual(client.post('/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06').json()['reasons'],['chips_capture_busy'])
                    finally:fixture.store._lock.release()
                    first=client.post('/api/stocks/TPEx/3105/institutional-windows/capture?as_of=2026-10-06').json()
                    self.assertEqual(first['status'],'unavailable')
                    if failure=='timeout':self.assertEqual(first['windows']['5']['status'],'available')
                    client.post('/api/stocks/TPEx/6488/institutional-windows/capture?as_of=2026-10-06')
                    self.assertEqual(len(fixture.requests),count);self.assertEqual(fixture.database_snapshot(),fixture.before)
            finally:fixture.close()


def main():
    if ARGS.serve:
        if ARGS.live_source_opt_in and (ARGS.policy_version!=chips.POLICY_VERSION or ARGS.policy_digest!=chips.POLICY_DIGEST):raise ValueError('root_external_pins_required')
        import uvicorn
        fixture=MemoryAPIFixture1006(live=ARGS.live_source_opt_in)
        try:
            print(json.dumps({'ready':True,'pid':os.getpid(),'parent_pid':os.getppid(),'port':ARGS.port,'empty_new_store':not fixture.store.raw_captures,
                'empty_w8_store':not fixture.old_store.raw_captures,'source_requests':0,'preloaded':False,'db_tables':len(fixture.before),
                'catalog':'accepted identities TPEx3105/穩懋 and6488/環球晶 only' if ARGS.live_source_opt_in else 'synthetic test catalog',
                'financial_seed':'none' if ARGS.live_source_opt_in else 'synthetic test bars',
                'db_proof':'all19table schema/columns/values/SQLite typeof',
                'policy_version':chips.POLICY_VERSION,'policy_digest':chips.POLICY_DIGEST,'guard':GUARDS,'disk_artifacts':0}),flush=True)
            uvicorn.run(fixture.app,host='127.0.0.1',port=ARGS.port,lifespan='off',access_log=False)
        finally:
            print(json.dumps({'shutdown':True,'db_preserved':fixture.database_snapshot()==fixture.before,'source_requests':len(fixture.transport.requests if ARGS.live_source_opt_in else fixture.requests),'guard':GUARDS,'disk_artifacts':0}),flush=True)
            fixture.close()
        return 0
    suite=unittest.TestSuite()
    if ARGS.worker_case:
        suite.addTest(WorkerTests(ARGS.worker_case))
    else:
        if not ARGS.api_only:suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WorkerTests))
        if not ARGS.worker_only:suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(APITests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sample=captures()
    print(json.dumps({'passed':result.wasSuccessful(),'cases':result.testsRun,'python':sys.version.split()[0],'httpx':httpx.__version__,
        'policy_canonical_bytes':len(chips.canonical_bytes(chips.window_policy())),'policy_digest':chips.POLICY_DIGEST,
        'synthetic_body_bytes':sum(len(item.body) for item in sample),'synthetic_graph_estimate_bytes':chips.retained_graph_estimate((sample,summarize(sample))),
        'guard':GUARDS,'disk_artifacts':0,'source_requests':0,'historical_pit':'unsupported'}))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
