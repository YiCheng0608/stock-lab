"""Standalone synthetic boundary runner; no source requests or test artifacts.

Run: python -B -X utf8 backend/tests/test_ohlcv_history_source.py
Reads only this source/test and the public pinned repo SOURCE_REGISTRY reference.
The policy v3 literal below was independently parsed from the single json fence
of Issue 32 comment 6111873522 (global publication, AC revision 3) and matches its
4,766 B pin. Policy v2 (comment 6111290434, 3,497 B) and the v1 reference values
(original comment 6084911117) are kept only to prove they are now rejected. None
was obtained from product policy/expected-value helpers. Response-shape cases are
canned wire bytes parsed by the real http.client; synthetic prices and trading dates
exercise boundaries and arithmetic; they are not QA financial truth.
"""
from __future__ import annotations

import copy
import hashlib
import http.client
import importlib.util
import io
import json
import math
import types
from pathlib import Path
from fractions import Fraction
from dataclasses import replace
from datetime import date, timedelta
import unittest
from unittest.mock import patch
import os
import sys


def _audit_boundary(event, args):
    if event in ("socket.connect", "socket.connect_ex", "subprocess.Popen"):
        raise AssertionError("standalone boundary runner forbids network/process launch")
    if event == "open":
        _, mode, flags = args
        if (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("standalone boundary runner forbids disk writes")


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the boundary runner does not permit bytecode artifacts")
sys.addaudithook(_audit_boundary)

EXTERNAL_POLICY = b'{"acquisition":{"accept":"application/json","accept_encoding":"identity","batch_seconds":180,"body_cap_bytes":1048576,"deadline":"cooperative","max_gets":8,"namespace":"issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2","order":"FinMind trading dates then seven prices ascending","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608,"user_agent":"stock-lab-issue32-local-ram/1"},"arithmetic":{"last60":"cutoff inclusive; no later rows","ma20":"last20 cutoff inclusive","ma60":"last60 cutoff inclusive","means":"exact reduced integer rational numerator/positive denominator; no floating/context rounding","prior20":"20 sessions strictly before cutoff","prior20_high":"exact maximum nominal high"},"consumer_version":"ordinary-nominal-ohlcv-window-summary-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown","identity_as_of":"2026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","price_source":{"basis":"provider_reported_nominal_ohlcv","dataset":"TaiwanStockPrice","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","fields":{"amount":"Trading_money","close":"close","high":"max","low":"min","open":"open","volume":"Trading_Volume"},"method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-07-01"},"profile":"free_public_local","publication_time":"unknown","response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8; anything else rejects","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure","zero_price_rows":"FinMind no-posted-price rows with zero OHLC reject the whole batch (accepted risk; suspension unsupported)"},"revision_time":"unknown","source_use":"local_personal_noncommercial_observed_nominal_ohlcv_snapshot","storage":"process_RAM","symbols":["3105","3293","5274","5347","6488","6510","8069"],"trading_date_source":{"dataset":"TaiwanStockTradingDate","documentation":"https://finmind.github.io/tutor/TaiwanMarket/Technical/ (doc GET receipt issue32 comment 6111856880); free tokenless use is inferred, 401/402/403 is first failure","endpoint":"https://api.finmindtrade.com/api/v4/data","expected_scope":"observed FinMind trading dates; every returned row structurally valid, unique and ascending; rows outside 2026-07-01..2026-10-06 are discarded only after structural validation; in-range dates must be weekdays, include both cutoffs, give at least 60 sessions at or before each cutoff, equal formal Aug-Oct 45 dates exactly within that span, and equal each of seven price date sets exactly; no fixed count; no closure inference; any unexplained mismatch rejects whole batch","fields":{"date":"date"},"format":"JSON","method":"GET","prior_calendar_formal_blob":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md","prior_calendar_formal_sha256":"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde","prior_verified_counts":{"August":21,"October_through_6":4,"September":20},"provider":"FinMind","rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate&start_date=2026-07-01&end_date=2026-10-06","version":"finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue32-v3"},"unit_policy":{"OHLC":"TWD/share","all_seven_must_match":true,"amount":"TWD","independent_latest_anchor":"stock-lab/master:d8918bc6491ec8ef65874979cf88d1322df2da43:SOURCE_REGISTRY/32.2:2026-10-06:42-fields","provider_literal_unit_annotation":false,"scale":1,"unit_mapping_inference":true,"version":"issue32-composite-six-field-scale1-v1","volume":"shares"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","adjusted_prices","company_actions","suspension_comparability","whole_window_historical_membership","historical_eligibility","actionable_strategy","plan","trading","historical_simulation","raw_disk_storage","redistribution","other_cutoffs"],"version":"issue32-ordinary-nominal-ohlcv-history-seven-cutoffs-v3"}'
EXTERNAL_PIN = "2f454a9aa51b70db331e867ffdb3cf3391a45e238e55cf885fe4396e34b86b91"
# Policy v2 (3,497 B, Issue 32 comment 6111290434) is superseded by v3 and must now be rejected.
V2_POLICY = b'{"acquisition":{"accept_encoding":"identity","batch_seconds":180,"body_cap_bytes":1048576,"deadline":"cooperative","max_gets":8,"namespace":"issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2","order":"newJuly calendar then seven price ascending","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608},"arithmetic":{"last60":"cutoff inclusive; no later rows","ma20":"last20 cutoff inclusive","ma60":"last60 cutoff inclusive","means":"exact reduced integer rational numerator/positive denominator; no floating/context rounding","prior20":"20 sessions strictly before cutoff","prior20_high":"exact maximum nominal high"},"calendar_source":{"expected_scope":"2026-07 observed official trading dates; each unique, in July 2026, weekday, header exact; no fixed count; no closure inference; each of seven FinMind price date sets must equal observed July plus formal 45 dates exactly; any unexplained mismatch rejects whole batch; at least 60 sessions at or before each cutoff","format":"UTF8_CSV","government_dataset":11391,"header":["\xe8\xb3\x87\xe6\x96\x99\xe6\x97\xa5\xe6\x9c\x9f","\xe9\x96\x8b\xe5\xb8\x82","\xe6\x9c\x80\xe9\xab\x98\xe5\x83\xb9","\xe6\x9c\x80\xe4\xbd\x8e\xe5\x83\xb9","\xe6\x94\xb6\xe5\xb8\x82","\xe6\xbc\xb2\xe8\xb7\x8c"],"method":"GET","prior_calendar_formal_blob":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md","prior_calendar_formal_sha256":"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde","prior_verified_counts":{"August":21,"October_through_6":4,"September":20},"provider":"TPEx","rights":"OGL-1.0 government dataset resource / TPEx terms section 7 exception; TPEx attribution","url":"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F07%2F01","version":"tpex-july-observed-plus-formal-aug21-sep20-oct4/issue32-v2"},"consumer_version":"ordinary-nominal-ohlcv-window-summary-v1","cutoffs":["2026-10-05","2026-10-06"],"first_availability":"unknown","identity_as_of":"2026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","price_source":{"basis":"provider_reported_nominal_ohlcv","dataset":"TaiwanStockPrice","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","fields":{"amount":"Trading_money","close":"close","high":"max","low":"min","open":"open","volume":"Trading_Volume"},"method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror","start_date":"2026-07-01"},"profile":"free_public_local","publication_time":"unknown","revision_time":"unknown","source_use":"local_personal_noncommercial_observed_nominal_ohlcv_snapshot","storage":"process_RAM","symbols":["3105","3293","5274","5347","6488","6510","8069"],"unit_policy":{"OHLC":"TWD/share","all_seven_must_match":true,"amount":"TWD","independent_latest_anchor":"stock-lab/master:d8918bc6491ec8ef65874979cf88d1322df2da43:SOURCE_REGISTRY/32.2:2026-10-06:42-fields","provider_literal_unit_annotation":false,"scale":1,"unit_mapping_inference":true,"version":"issue32-composite-six-field-scale1-v1","volume":"shares"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","adjusted_prices","company_actions","suspension_comparability","whole_window_historical_membership","historical_eligibility","actionable_strategy","plan","trading","historical_simulation","raw_disk_storage","redistribution","other_cutoffs"],"version":"issue32-ordinary-nominal-ohlcv-history-seven-cutoffs-v2"}'
V2_PIN = "076e36f2c3bb3169866fc728e155e99886e084871480810f2cda6f54aff1eaba"

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/ohlcv_history_source.py"
spec = importlib.util.spec_from_file_location("issue32_ohlcv_boundary", SOURCE)
source = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = source
spec.loader.exec_module(source)
FORMAL = (ROOT / "docs/SOURCE_REGISTRY.md").read_bytes()

# External formal table, independently read rather than projected from source.
ANCHORS = {
    "3105": (615, 623, 588, 592, 19731700, 11863581093),
    "3293": (794, 794, 772, 780, 1495462, 1164617657),
    "5274": (19520, 19895, 18855, 18985, 188693, 3627465565),
    "5347": (184.5, 195, 184.5, 191, 34637793, 6615109776),
    "6488": (1175, 1260, 1145, 1205, 13913614, 16835605385),
    "6510": (3125, 3140, 3050, 3055, 560518, 1729347985),
    "8069": (147, 151.5, 145, 149, 10796741, 1607943663),
}
SYMBOLS = tuple(ANCHORS)
CUTOFFS = ("2026-10-05", "2026-10-06")
NAMESPACE = "issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2"

# Issue 32 financial-start identity guard (user approval 6109493002, design
# 6109319936): issuer/coordinator/implementer ids arrive in the seal and the QA
# holder/model/effort are runtime read-backs. The ids below are synthetic; the
# product pins no session or model, so none of these are product constants.
SEAL_ISSUER = "f0000000-0000-0000-0000-0000000000a1"
SEAL_COORDINATORS = ("f0000000-0000-0000-0000-0000000000b1", "f0000000-0000-0000-0000-0000000000b2")
SEAL_IMPLEMENTERS = ("f0000000-0000-0000-0000-0000000000c1", "f0000000-0000-0000-0000-0000000000c2")
CLAUDE_QA_HOLDER = "5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d"
SEAL_URL = "https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999"
SEAL_URL_THRESHOLD = 6085344604


def declaration(holder=CLAUDE_QA_HOLDER, model="claude-sonnet-5-5", url=SEAL_URL):
    # Pure configuration boundary only; these synthetic declarations are NEVER
    # passed to a real transport/source constructor or used for acquisition.
    binding = source.ExecutionBinding(holder, holder, None, model, "xhigh", "a" * 40, "b" * 64, "c" * 64,
                                      "NOAUTH RAM pure guard; no financial execution")
    start = source.FinancialStart("issue32-financial-start-v1", SEAL_ISSUER, SEAL_COORDINATORS,
                                  SEAL_IMPLEMENTERS, NAMESPACE, EXTERNAL_PIN, url, binding, True, True)
    return start, binding


def days(start, stop):
    value, end = date.fromisoformat(start), date.fromisoformat(stop)
    result = []
    while value <= end:
        if value.weekday() < 5 and value.isoformat() not in ("2026-09-25", "2026-09-28"):
            result.append(value.isoformat())
        value += timedelta(days=1)
    return tuple(result)


DATES = days("2026-07-01", "2026-10-06")
JULY = days("2026-07-01", "2026-07-31")
PRIOR = days("2026-08-01", "2026-10-06")
assert len(DATES) == 68 and len(JULY) == 23 and len(PRIOR) == 45 and DATES == JULY + PRIOR
assert hashlib.sha256(FORMAL).hexdigest() == "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"
# Policy v1 / qa1 reference values (original comment 6084911117): must now be rejected.
V1_PIN = "0f8c95eca6f0dcd08ca9b874996c4f41f8f8cf356f3282fee1e1c3f23734292d"
V1_BYTES = 3266
V1_NAMESPACE = "issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa1"


def july_without(*missing):
    """Observed-July subset for a synthetic closure; not a claim about a real closure day."""
    assert all(day in JULY for day in missing)
    return tuple(day for day in JULY if day not in missing)


def trading_body(dates, extra_rows=()):
    """Synthetic FinMind TaiwanStockTradingDate document: rows are exactly {date}."""
    rows = [{"date": day} for day in dates] + list(extra_rows)
    return json.dumps({"msg": "success", "status": 200, "data": rows}, separators=(",", ":")).encode("utf8")


def corpus(july=JULY):
    """Small regenerable RAM corpus; no provider transport or fixture files."""
    trading = trading_body(july + PRIOR)
    documents = []
    for stock_index, symbol in enumerate(SYMBOLS):
        rows = []
        for index, day in enumerate(july + PRIOR):
            close = 100 + stock_index * 10 + index
            if index == 8:
                close += 1  # force a nonterminating /60 mean at one cutoff
            row = {"date": day, "stock_id": symbol, "open": close,
                   "max": close + 2, "min": close - 2, "close": close,
                   "Trading_Volume": 1000 + index * 3,
                   "Trading_money": 100000 + index * 13,
                   "spread": -1, "Trading_turnover": 2}
            if day == "2026-10-06":
                o, h, l, c, v, a = ANCHORS[symbol]
                row.update(open=o, max=h, min=l, close=c, Trading_Volume=v, Trading_money=a)
            rows.append(row)
        documents.append({"status": 200, "msg": "success", "data": rows})
    return trading, documents


def canonical(value):
    """Independent stdlib serialization, never the product's policy helper."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def body_docs(trading=None, documents=None, july=JULY):
    default_trading, default_documents = corpus(july)
    return [trading if trading is not None else default_trading] + [
        json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf8")
        for document in (documents if documents is not None else default_documents)]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


JSON_TYPE = (("Content-Type", "application/json"),)


class Response:
    def __init__(self, body, *, declared=True, eof=True, clock=None, read_delay=0, status=200, headers=None, close_raises=False):
        self.body = body
        self.offset = 0
        self.status = status
        self.headers = headers if headers is not None else (
            ((("Content-Length", str(len(body))),) if declared else ()) + JSON_TYPE)
        self.closed = False
        self.eof_enabled = eof
        self.clock = clock
        self.read_delay = read_delay
        self.read_calls = []
        self.close_raises = close_raises
        self.close_calls = 0

    @property
    def known_eof(self):
        return self.eof_enabled and self.offset == len(self.body)

    def read(self, count, timeout):
        self.read_calls.append((count, timeout))
        assert count > 0
        if self.clock:
            self.clock.now += self.read_delay
        chunk = self.body[self.offset:self.offset + count]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True
        self.close_calls += 1
        if self.close_raises:
            raise OSError("DO_NOT_RETAIN_RAW" * 1000)


class Transport:
    def __init__(self, bodies=None, *, response_options=None, clock=None, open_delay=0, fail_at=None):
        self.bodies = bodies or body_docs()
        self.response_options = response_options or {}
        self.clock, self.open_delay, self.fail_at = clock, open_delay, fail_at
        self.opens = []
        self.responses = []

    def open(self, url, timeout):
        index = len(self.opens)
        self.opens.append((url, timeout))
        if self.clock:
            self.clock.now += self.open_delay
        if index == self.fail_at:
            raise OSError("synthetic transport failure")
        options = self.response_options.get(index, {})
        response = Response(self.bodies[index], **options)
        self.responses.append(response)
        return response


def build(*, transport=None, clock=None, ledger=None, **kwargs):
    transport = transport or Transport()
    clock = clock or Clock()
    snapshot = source.HistorySource(policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN,
                                    formal_blob=FORMAL, transport=transport,
                                    ledger=ledger or source.AttemptLedger(NAMESPACE), clock=clock, **kwargs)
    return snapshot, transport, clock


def admission(snapshot, july_days=len(JULY)):
    # Independent arithmetic: N = observed July days + 45 formal days = trading-date rows.
    captures = snapshot.inspection()["captures"]
    total = july_days + len(PRIOR)
    return source.OracleAdmission(NAMESPACE, EXTERNAL_PIN, "synthetic-boundary-oracle",
                                  "a" * 40, "b" * 64,
                                  tuple(c.receipt.canonical_sha256 for c in captures),
                                  total, 7 * total, 42 * total, 42, True)


def available():
    snapshot, transport, clock = build()
    snapshot.acquire()
    snapshot.admit_independent_verification(admission(snapshot))
    return snapshot, transport, clock


# --- Response-shape replay: canned wire bytes -> real http.client parsing -> the real
# _HTTPSTransport.open / _HTTPSResponse / _capture path. Only the socket and TLS are
# replaced (the audit guard bans real sockets); every value below is synthetic.
class ReplayFile(io.BytesIO):
    """Response file whose .raw._sock mirrors socket.SocketIO as in the stdlib path."""


class ReplaySocket:
    def __init__(self, wire):
        self.wire = wire
        self.timeouts = []

    def makefile(self, mode="rb", *args, **kwargs):
        stream = ReplayFile(self.wire)
        stream.raw = types.SimpleNamespace(_sock=self)
        return stream

    def settimeout(self, value):
        self.timeouts.append(value)


class ReplayTransport:
    def __init__(self, wires):
        self.wires = list(wires)
        self.opens = []
        self.requests = []

    def open(self, url, timeout):
        wire = self.wires[len(self.opens)]
        self.opens.append(url)
        owner = self

        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.sock = host, ReplaySocket(wire)

            def connect(self):
                pass

            def request(self, method, target, headers):
                owner.requests.append((self.host, method, target, dict(headers)))

            def getresponse(self):
                response = http.client.HTTPResponse(self.sock, method="GET")
                response.begin()
                if response.will_close:  # stdlib hands the socket to the response
                    self.sock = None
                return response

            def close(self):
                self.sock = None

        with patch.object(source.http.client, "HTTPSConnection", Connection), \
                patch.object(source.ssl, "create_default_context", lambda: object()):
            return source._HTTPSTransport().open(url, timeout)


def chunk_encode(body, size=61):
    out = b""
    for offset in range(0, len(body), size):
        part = body[offset:offset + size]
        out += b"%x\r\n" % len(part) + part + b"\r\n"
    return out + b"0\r\n\r\n"


def raw_http(headers, body=b"", *, status=200, reason="OK", version="1.1"):
    head = f"HTTP/{version} {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers) + "\r\n"
    return head.encode("utf-8") + body


FINMIND_REQUEST_HEADERS = {"Accept-Encoding": "identity", "Connection": "close",
                           "User-Agent": "stock-lab-issue32-local-ram/1", "Accept": "application/json"}
# Independent URL literals (policy v3 trading_date_source.url / price_source.endpoint), not product constants.
TRADING_DATE_URL_LITERAL = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate"
                            "&start_date=2026-07-01&end_date=2026-10-06")
PRICE_URL_LITERAL = ("https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={}"
                     "&start_date=2026-07-01&end_date=2026-10-06")
EXPECTED_URLS = (TRADING_DATE_URL_LITERAL,) + tuple(PRICE_URL_LITERAL.format(symbol) for symbol in SYMBOLS)


def finmind_wire(body, *, framing="length", content_type="application/json", extra=(), status=200,
                 reason="OK", version="1.1", content_encoding=None, te="chunked"):
    headers = [("Date", "Mon, 12 Oct 2026 00:00:00 GMT"), ("Server", "synthetic"), ("CF-RAY", "synthetic-0000"),
               ("Vary", "Accept-Encoding"), ("Alt-Svc", 'h3=":443"')]
    if content_type is not None:
        headers.append(("Content-Type", content_type))
    wire = body
    if framing == "length":
        headers.append(("Content-Length", str(len(body))))
    elif framing == "chunked":
        headers.append(("Transfer-Encoding", te))
        wire = chunk_encode(body)
    elif framing == "both":
        headers += [("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked")]
        wire = chunk_encode(body)
    elif framing == "close":
        pass  # EOF-delimited
    if content_encoding is not None:
        headers.append(("Content-Encoding", content_encoding))
    return raw_http(headers + list(extra), wire, status=status, reason=reason, version=version)


def replay(wires):
    transport = ReplayTransport(wires)
    snapshot, _, _ = build(transport=transport)
    return snapshot, transport


class Boundaries(unittest.TestCase):
    def assertFailure(self, expected, function, *args, **kwargs):
        with self.assertRaises(source.SourceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def test_external_policy_all_recursive_keys_types_values_and_canonical(self):
        self.assertEqual(len(EXTERNAL_POLICY), 4766)
        self.assertEqual(hashlib.sha256(EXTERNAL_POLICY).hexdigest(), EXTERNAL_PIN)
        source.validate_policy(EXTERNAL_POLICY, EXTERNAL_PIN)
        policy = json.loads(EXTERNAL_POLICY)
        self.assertEqual(policy["acquisition"]["namespace"], NAMESPACE)
        self.assertNotIn("calendar_source", policy)
        scope = policy["trading_date_source"]["expected_scope"]
        self.assertIn("no fixed count", scope)
        self.assertIn("discarded only after structural validation", scope)
        self.assertEqual(policy["trading_date_source"]["url"], TRADING_DATE_URL_LITERAL)
        self.assertEqual((policy["acquisition"]["user_agent"], policy["acquisition"]["accept"]),
                         ("stock-lab-issue32-local-ram/1", "application/json"))
        self.assertIn("close-delimited", policy["response_shape"]["framing"])
        self.assertEqual(policy["acquisition"]["max_gets"], 8)
        nodes = []
        def visit(value):
            if isinstance(value, dict):
                nodes.append(value)
                for child in value.values():
                    visit(child)
        visit(policy)
        for index, node in enumerate(nodes):
            for mode in ("extra", "missing"):
                mutated = copy.deepcopy(policy)
                cloned_nodes = []
                def collect(value):
                    if isinstance(value, dict):
                        cloned_nodes.append(value)
                        for child in value.values():
                            collect(child)
                collect(mutated)
                target = cloned_nodes[index]
                if mode == "extra":
                    target["unexpected"] = 1
                else:
                    del target[next(iter(target))]
                self.assertFailure("policy_keys", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        paths = [("acquisition", "redirects"), ("unit_policy", "scale"),
                 ("acquisition", "max_gets"), ("acquisition", "request_seconds")]
        for outer, key in paths:
            for replacement in (True, 1.0, "1", None):
                mutated = copy.deepcopy(policy)
                mutated[outer][key] = replacement
                self.assertFailure("policy_type", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        for replacement in (1, "true", None):
            mutated = copy.deepcopy(policy)
            mutated["unit_policy"]["unit_mapping_inference"] = replacement
            self.assertFailure("policy_type", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        for outer, key, value in (("unit_policy", "scale", 1000), ("acquisition", "namespace", "other"),
                                  ("price_source", "dataset", "other")):
            mutated = copy.deepcopy(policy)
            mutated[outer][key] = value
            self.assertFailure("policy_canonical_mismatch", source.validate_policy, canonical(mutated), EXTERNAL_PIN)
        self.assertFailure("policy_pin", source.validate_policy, EXTERNAL_POLICY, "0" * 64)
        self.assertFailure("policy_canonical_mismatch", source.validate_policy, EXTERNAL_POLICY + b" ", EXTERNAL_PIN)
        self.assertFailure("duplicate_json_key", source.validate_policy, EXTERNAL_POLICY.replace(b'{', b'{"version":"duplicate",', 1), EXTERNAL_PIN)

    def test_old_policies_and_qa1_namespace_are_rejected(self):
        # Rebuild v1 from v2 by restoring its four leaves; the pin/length prove it is exactly v1.
        v1 = json.loads(V2_POLICY)
        v1["version"] = "issue32-ordinary-nominal-ohlcv-history-seven-cutoffs-v1"
        v1["calendar_source"]["expected_scope"] = "2026-07 full 23 weekdays; exact positive dates required; no missing-day closure inference"
        v1["calendar_source"]["version"] = "tpex-july23-plus-formal-aug21-sep20-oct4/issue32-v1"
        v1["acquisition"]["namespace"] = V1_NAMESPACE
        v1_policy = canonical(v1)
        self.assertEqual((len(v1_policy), hashlib.sha256(v1_policy).hexdigest()), (V1_BYTES, V1_PIN))
        self.assertEqual((len(V2_POLICY), hashlib.sha256(V2_POLICY).hexdigest()), (3497, V2_PIN))
        self.assertNotEqual(V1_NAMESPACE, NAMESPACE)
        for label, blob, pin in (("v1", v1_policy, V1_PIN), ("v2", V2_POLICY, V2_PIN)):
            with self.subTest(old_policy=label):
                self.assertFailure("policy_pin", source.validate_policy, blob, pin)
                self.assertFailure("policy_keys", source.validate_policy, blob, EXTERNAL_PIN)  # old shape under the v3 pin
                self.assertFailure("policy_pin", source.validate_policy, EXTERNAL_POLICY, pin)
                self.assertFailure("policy_pin", source.HistorySource, policy_canonical=blob, policy_sha256=pin,
                                   formal_blob=FORMAL, transport=Transport(), ledger=source.AttemptLedger(NAMESPACE))
        self.assertFailure("quota_namespace", source.AttemptLedger, V1_NAMESPACE)
        snapshot, transport, _ = build()
        snapshot.acquire()
        proof = admission(snapshot)
        for label, mutation in (("namespace_qa1", replace(proof, namespace=V1_NAMESPACE)),
                                ("policy_v1", replace(proof, policy_sha256=V1_PIN)),
                                ("policy_v2", replace(proof, policy_sha256=V2_PIN))):
            with self.subTest(case=label):
                self.assertFailure("oracle_scope", snapshot.admit_independent_verification, mutation)
        snapshot.release()

    def test_unsupported_every_purpose_before_transport(self):
        for purpose in json.loads(EXTERNAL_POLICY)["unsupported"] + ["strategy", "storage", "random", None]:
            transport = Transport()
            self.assertFailure("unsupported_purpose", build, transport=transport, purpose=purpose)
            self.assertEqual(transport.opens, [])
        self.assertFailure("financial_start_required", source.HistorySource,
                           policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN, formal_blob=FORMAL)
        self.assertFailure("formal_blob_pin", source.HistorySource,
                           policy_canonical=EXTERNAL_POLICY, policy_sha256=EXTERNAL_PIN, formal_blob=FORMAL + b" ")

    def test_financial_start_requires_exact_typed_reviewed_binding(self):
        start, binding = declaration(model="gpt-6.1-sol")
        source._financial_start(start, binding)
        cases = [
            (replace(start, authorized=1), binding, "financial_start_not_authorized"),
            (replace(start, namespace="other"), binding, "financial_start_scope"),
            (replace(start, namespace=V1_NAMESPACE), binding, "financial_start_scope"),
            (replace(start, policy_sha256="0" * 64), binding, "financial_start_scope"),
            (replace(start, policy_sha256=V1_PIN), binding, "financial_start_scope"),
            (replace(start, seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6084911117"), binding, "financial_new_explicit_seal_required"),
            (start, replace(binding, candidate_sha="d" * 40), "financial_binding_mismatch"),
            (start, replace(binding, script_sha256="e" * 64), "financial_binding_mismatch"),
        ]
        for seal, runtime, code in cases:
            self.assertFailure(code, source._financial_start, seal, runtime)
        self.assertFailure("financial_start_with_boundary_transport", build, financial_start=start, execution_binding=binding)

    def test_financial_start_seal_supplied_identity_pure_guards(self):
        # NOAUTH: synthetic declarations validate only the pure guard; no
        # constructor/acquire and no network. Identities come from the seal.
        self.assertFalse(hasattr(source, "GLOBAL_ISSUER"))
        for model in ("claude-sonnet-5-5", "claude-opus-5-5", "gpt-6.1-sol"):
            with self.subTest(case="runtime_model_is_read_back", model=model):
                self.assertIsNone(source._financial_start(*declaration(model=model)))
        # Former hard-coded session ids carry no special status unless the seal lists them.
        for holder in ("01a12416-7c0d-7143-87e3-5da9e0ab4394", "01a12102-9891-7293-8c66-a342094e0990"):
            with self.subTest(case="unlisted_holder_not_pinned", holder=holder):
                self.assertIsNone(source._financial_start(*declaration(holder=holder)))
        start, binding = declaration()
        for holder in (SEAL_ISSUER,) + SEAL_COORDINATORS + SEAL_IMPLEMENTERS:
            with self.subTest(case="qa_not_independent_of_seal_role", holder=holder):
                self.assertFailure("financial_qa_identity", source._financial_start, *declaration(holder=holder))
        for label, role in (
                ("issuer_is_coordinator", {"issuer_thread_id": SEAL_COORDINATORS[0]}),
                ("issuer_is_implementer", {"issuer_thread_id": SEAL_IMPLEMENTERS[0]}),
                ("coordinator_is_implementer", {"coordinator_session_ids": (SEAL_IMPLEMENTERS[0],)}),
                ("duplicate_implementer", {"implementer_session_ids": (SEAL_IMPLEMENTERS[0], SEAL_IMPLEMENTERS[0])}),
                ("issuer_malformed", {"issuer_thread_id": "not-a-session-id"}),
                ("coordinator_uppercase", {"coordinator_session_ids": (SEAL_COORDINATORS[0].upper(),)}),
                ("implementer_malformed", {"implementer_session_ids": ("x",)})):
            with self.subTest(case=label):
                self.assertFailure("financial_start_scope", source._financial_start, replace(start, **role), binding)
        for label, role in (
                ("coordinators_empty", {"coordinator_session_ids": ()}),
                ("implementers_empty", {"implementer_session_ids": ()}),
                ("coordinators_list", {"coordinator_session_ids": list(SEAL_COORDINATORS)}),
                ("implementers_non_str", {"implementer_session_ids": (SEAL_IMPLEMENTERS[0], 1)}),
                ("issuer_non_str", {"issuer_thread_id": None})):
            with self.subTest(case=label):
                self.assertFailure("financial_start_type", source._financial_start, replace(start, **role), binding)
        for label, url, code in (
                ("seal_at_threshold", f"https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-{SEAL_URL_THRESHOLD}",
                 "financial_new_explicit_seal_required"),
                ("seal_other_issue", "https://github.com/YiCheng0608/stock-lab/issues/33#issuecomment-9999999999",
                 "financial_new_explicit_seal_required"),
                ("seal_after_threshold", f"https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-{SEAL_URL_THRESHOLD + 1}",
                 None)):
            with self.subTest(case=label):
                if code is None:
                    self.assertIsNone(source._financial_start(*declaration(url=url)))
                else:
                    self.assertFailure(code, source._financial_start, *declaration(url=url))

        cases = (
            ("start_type", None, binding, "financial_start_required"),
            ("binding_type", start, None, "financial_start_required"),
            ("seal_binding_type", replace(start, binding=None), binding, "financial_binding_type"),
            ("authorized_bool", replace(start, authorized=1), binding, "financial_start_not_authorized"),
            ("authorized_false", replace(start, authorized=False), binding, "financial_start_not_authorized"),
            ("whole_batch_bool", replace(start, whole_batch=1), binding, "financial_start_not_authorized"),
            ("whole_batch_false", replace(start, whole_batch=False), binding, "financial_start_not_authorized"),
            ("namespace", replace(start, namespace="other"), binding, "financial_start_scope"),
            ("policy_pin", replace(start, policy_sha256="0" * 64), binding, "financial_start_scope"),
            ("seal_threshold", replace(start, seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6084911117"), binding, "financial_new_explicit_seal_required"),
            ("candidate_mismatch", start, replace(binding, candidate_sha="d" * 40), "financial_binding_mismatch"),
            ("script_mismatch", start, replace(binding, script_sha256="e" * 64), "financial_binding_mismatch"),
        )
        for label, seal, runtime, code in cases:
            with self.subTest(case=label):
                self.assertFailure(code, source._financial_start, seal, runtime)
        for label, runtime, code in (
                ("not_top_level", replace(binding, parent_thread_id=SEAL_ISSUER), "financial_qa_not_top_level"),
                ("session_mismatch", replace(binding, holder_session_id=SEAL_ISSUER), "financial_qa_identity"),
                ("holder_malformed", replace(binding, holder_thread_id="NOT-A-SESSION", holder_session_id="NOT-A-SESSION"), "financial_qa_identity"),
                ("holder_uppercase", replace(binding, holder_thread_id=CLAUDE_QA_HOLDER.upper(), holder_session_id=CLAUDE_QA_HOLDER.upper()), "financial_qa_identity"),
                ("model_shape", replace(binding, model="bad model"), "financial_qa_identity"),
                ("model_too_long", replace(binding, model="m" * 65), "financial_qa_identity"),
                ("model_empty", replace(binding, model=""), "financial_binding_type"),
                ("effort", replace(binding, reasoning_effort="ultra"), "financial_qa_identity")):
            with self.subTest(case=label):
                self.assertFailure(code, source._financial_start, replace(start, binding=runtime), runtime)

    def test_trading_date_document_gate_stops_before_any_price_get(self):
        all_dates = JULY + PRIOR
        base = json.loads(trading_body(all_dates))

        def mutate(change):
            document = copy.deepcopy(base)
            change(document)
            return json.dumps(document, separators=(",", ":")).encode("utf8")

        def dates_body(dates):
            return trading_body(tuple(sorted(dates)))

        variants = [
            ("not_json", b"<html>blocked</html>", "transport_or_parse_failure"),
            ("utf8_bom", b"\xef\xbb\xbf" + trading_body(all_dates), "transport_or_parse_failure"),
            ("invalid_utf8", b"\xff" + trading_body(all_dates), "transport_or_parse_failure"),
            ("extra_top_level_key", mutate(lambda d: d.update(extra=1)), "trading_dates_document"),
            ("missing_top_level_key", mutate(lambda d: d.pop("msg")), "trading_dates_document"),
            ("status_402_paid", mutate(lambda d: d.update(status=402)), "trading_dates_status"),
            ("status_401_login", mutate(lambda d: d.update(status=401, msg="login required")), "trading_dates_status"),
            ("msg_not_success", mutate(lambda d: d.update(msg="ok")), "trading_dates_status"),
            ("status_is_bool", mutate(lambda d: d.update(status=True)), "trading_dates_status"),
            ("data_is_object", mutate(lambda d: d.update(data={})), "trading_dates_rows"),
            ("data_empty", mutate(lambda d: d.update(data=[])), "trading_dates_rows"),
            ("row_is_string", mutate(lambda d: d["data"].__setitem__(3, "2026-07-06")), "trading_dates_row"),
            ("row_extra_key", mutate(lambda d: d["data"][3].update(extra=1)), "trading_dates_row"),
            ("row_missing_date", mutate(lambda d: d["data"][3].pop("date")), "trading_dates_row"),
            ("date_compact", mutate(lambda d: d["data"][3].update(date="20260706")), "trading_dates_date"),
            ("date_impossible", mutate(lambda d: d["data"][3].update(date="2026-02-30")), "trading_dates_date"),
            ("date_is_number", mutate(lambda d: d["data"][3].update(date=20260706)), "trading_dates_date"),
            ("duplicate_date", mutate(lambda d: d["data"].insert(4, copy.deepcopy(d["data"][3]))), "trading_dates_order"),
            ("not_ascending", mutate(lambda d: d["data"].insert(3, d["data"].pop(4))), "trading_dates_order"),
            # Rows OUTSIDE the window are still structurally validated before they are discarded.
            ("bad_date_outside_window", trading_body(("2005-01-03",) + all_dates, extra_rows=[{"date": "2026-10-32"}]), "trading_dates_date"),
            ("extra_key_outside_window", mutate(lambda d: d["data"].insert(0, {"date": "2005-01-03", "x": 1})), "trading_dates_row"),
            ("unsorted_outside_window", trading_body(("2005-01-04", "2005-01-03") + all_dates), "trading_dates_order"),
            ("duplicate_outside_window", trading_body(("2005-01-03", "2005-01-03") + all_dates), "trading_dates_order"),
            # In-window semantics.
            ("weekend_in_window", dates_body(set(all_dates) | {"2026-07-04"}), "trading_dates_weekday"),
            ("cutoff_1005_missing", dates_body(set(all_dates) - {"2026-10-05"}), "trading_dates_cutoff"),
            ("cutoff_1006_missing", dates_body(set(all_dates) - {"2026-10-06"}), "trading_dates_cutoff"),
            ("window_insufficient_15_july_days", trading_body(JULY[:15] + PRIOR), "trading_dates_window_insufficient"),
            ("formal_day_missing", dates_body(set(all_dates) - {"2026-09-01"}), "trading_dates_formal_mismatch"),
            ("formal_closed_day_present", dates_body(set(all_dates) | {"2026-09-25"}), "trading_dates_formal_mismatch"),
        ]
        for label, raw, code in variants:
            with self.subTest(case=label):
                snapshot, transport, _ = build(transport=Transport(body_docs(raw)))
                self.assertFailure(code, snapshot.acquire)
                self.assertEqual(snapshot.state, "failed")
                self.assertEqual(snapshot.ledger.attempted, (0,))
                self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
                self.assertEqual(len(transport.opens), 1)  # no price GET after a bad trading-date document
                self.assertTrue(transport.responses[0].closed)
                self.assertEqual(snapshot._capture_buffer, b"")
                self.assertEqual(len(snapshot.inspection()["captures"]), 1)
                self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
                snapshot.release()

    def test_trading_dates_outside_window_are_validated_then_discarded(self):
        # The dataset documentation shows history from 2005-01-03: if start_date/end_date were ignored the whole
        # history (~5,500 rows) comes back and must still fit the body and retained-roots caps.
        before = tuple(sorted(set(days("2005-01-03", "2026-06-30")) | {"2026-06-27", "2026-06-28"}))  # incl. weekend
        after = ("2026-10-07", "2026-10-08", "2026-10-10")  # last one is a Saturday
        dates = before + JULY + PRIOR + after
        self.assertEqual(tuple(sorted(dates)), dates)
        self.assertGreater(len(dates), 5000)
        self.assertLess(len(trading_body(dates)), source.BODY_CAP)
        snapshot, transport, _ = build(transport=Transport(body_docs(trading_body(dates))))
        snapshot.acquire()
        self.assertEqual(len(transport.opens), 8)
        self.assertEqual(len(snapshot.inspection()["documents"][0]["data"]), len(dates))  # every returned row kept as received
        snapshot.admit_independent_verification(admission(snapshot))  # N counts in-window days only
        self.assertEqual(snapshot.provenance["trading_dates"], JULY + PRIOR)
        for cutoff in CUTOFFS:
            self.assertEqual(len(snapshot.get_nominal_ohlcv60("3105", cutoff).bars), 60)
        snapshot.release()

    def test_observed_july_days_variable_count_accepted_with_exact_windows(self):
        # Window arithmetic is derived here, not from product helpers.
        self.assertEqual(sum(day <= "2026-10-05" for day in PRIOR), 44)
        self.assertEqual(sum(day <= "2026-10-06" for day in PRIOR), 45)
        for label, july in (("23_all_weekdays", JULY), ("22_one_gap", july_without("2026-07-15")),
                            ("16_minimum", july_without(*JULY[1:8]))):
            with self.subTest(case=label):
                total = len(july) + 45
                snapshot, transport, _ = build(transport=Transport(body_docs(july=july)))
                snapshot.acquire()
                self.assertEqual(len(transport.opens), 8)
                results = snapshot.inspection()["results"]
                self.assertEqual(tuple(results), SYMBOLS)
                for symbol in SYMBOLS:
                    self.assertEqual(tuple(bar.date for bar in results[symbol]), july + PRIOR)
                self.assertEqual(len(results["3105"]), total)
                proof = admission(snapshot, len(july))
                self.assertEqual((proof.calendar_rows, proof.price_rows, proof.price_fields, proof.latest_anchor_fields),
                                 (total, 7 * total, 42 * total, 42))
                self.assertFailure("oracle_complete_scope", snapshot.admit_independent_verification,
                                   replace(proof, calendar_rows=23, price_rows=476, price_fields=2856))  # the old fixed scope
                for field, delta in (("calendar_rows", 1), ("price_rows", -1), ("price_fields", 1), ("latest_anchor_fields", -1)):
                    self.assertFailure("oracle_complete_scope", snapshot.admit_independent_verification,
                                       replace(proof, **{field: getattr(proof, field) + delta}))
                snapshot.admit_independent_verification(proof)
                self.assertEqual(snapshot.provenance["trading_dates"], july + PRIOR)
                _, documents = corpus(july)
                for index, symbol in enumerate(SYMBOLS):
                    for cutoff in CUTOFFS:
                        expected = tuple(day for day in july + PRIOR if day <= cutoff)[-60:]
                        window = snapshot.get_nominal_ohlcv60(symbol, cutoff)
                        self.assertEqual(tuple(bar.date for bar in window.bars), expected)
                        self.assertEqual(len(window.bars), 60)
                        summary = snapshot.summarize_nominal_ohlcv60(symbol, cutoff).values
                        rows = {row["date"]: row for row in documents[index]["data"]}
                        self.assertEqual(summary["start_date"], expected[0])
                        self.assertEqual(summary["end_date"], cutoff)
                        prior = tuple(day for day in july + PRIOR if day < cutoff)[-20:]
                        self.assertEqual((summary["prior20_start"], summary["prior20_end"]), (prior[0], prior[-1]))
                        total_close = sum((Fraction(str(rows[day]["close"])) for day in expected), Fraction(0))
                        expected_ma60 = total_close / 60
                        self.assertEqual((summary["ma60_close"].numerator, summary["ma60_close"].denominator),
                                         (expected_ma60.numerator, expected_ma60.denominator))
                snapshot.release()

    def test_insufficient_window_rejects_before_any_price_get_without_shrinking(self):
        for count in (15, 1):
            with self.subTest(observed_july_days=count):
                # 10/05 needs 44 + count >= 60 (count >= 16); 10/06 needs count >= 15.
                snapshot, transport, _ = build(transport=Transport(body_docs(july=JULY[:count])))
                self.assertFailure("trading_dates_window_insufficient", snapshot.acquire)
                self.assertEqual(len(transport.opens), 1)
                self.assertEqual(snapshot.ledger.attempted, (0,))
                self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
                self.assertEqual(snapshot.state, "failed")
                self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-06")
                snapshot.release()

    def test_price_dates_must_equal_trading_dates_for_every_symbol(self):
        gap = "2026-07-15"
        july = july_without(gap)
        trading, original = corpus(july)

        def mutated(symbol_index, change):
            documents = copy.deepcopy(original)
            change(documents[symbol_index]["data"])
            return body_docs(trading, documents, july)

        def add_gap_row(rows):
            rows.append({**rows[0], "date": gap})

        def swap_in_gap(rows):
            rows[3]["date"] = gap

        cases = (
            ("extra_day_not_in_trading_dates", 0, add_gap_row, "price_row_count", 2),
            ("missing_day", 0, lambda rows: rows.pop(5), "price_row_count", 2),
            ("same_count_wrong_date", 0, swap_in_gap, "price_duplicate_or_calendar", 2),
            ("duplicate_date_hides_missing", 0, lambda rows: rows.__setitem__(4, copy.deepcopy(rows[5])), "price_duplicate_or_calendar", 2),
            ("only_third_symbol_missing_day", 2, lambda rows: rows.pop(9), "price_row_count", 4),
            ("only_fifth_symbol_wrong_date", 4, swap_in_gap, "price_duplicate_or_calendar", 6),
            ("only_last_symbol_extra_day", 6, add_gap_row, "price_row_count", 8),
        )
        for label, symbol_index, change, code, opens in cases:
            with self.subTest(case=label):
                snapshot, transport, _ = build(transport=Transport(mutated(symbol_index, change)))
                self.assertFailure(code, snapshot.acquire)
                self.assertEqual(len(transport.opens), opens)
                self.assertEqual(snapshot.ledger.attempted, tuple(range(opens)))
                self.assertEqual(snapshot.state, "failed")
                self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-06")
                snapshot.release()
        # Cross-source disagreement in either direction: provider has one more or one fewer
        # trading day than the FinMind trading dates, for every symbol.
        full_trading, full_documents = corpus()
        for label, bodies in (("provider_has_extra_day", body_docs(trading, full_documents, july)),
                              ("provider_lacks_day", body_docs(full_trading, original, JULY))):
            with self.subTest(case=label):
                snapshot, transport, _ = build(transport=Transport(bodies))
                self.assertFailure("price_row_count", snapshot.acquire)
                self.assertEqual(len(transport.opens), 2)
                snapshot.release()

    def test_all_price_rows_gate_no_partial_symbol_or_calendar(self):
        _, original = corpus()
        mutations = [
            (lambda row: row.update(stock_id="6488"), "price_stock_id"),
            (lambda row: row.update(date="2026-09-25"), "price_duplicate_or_calendar"),
            (lambda row: row.update(date="2026-10-07"), "price_duplicate_or_calendar"),
            (lambda row: row.update(date="2026-02-30"), "price_date"),
            (lambda row: row.update(date=20260701), "price_date"),
            (lambda row: row.update(close=0), "nonpositive_price"),
            (lambda row: row.update(open=True), "price_number_type"),
            (lambda row: row.update(close="100"), "price_number_type"),
            (lambda row: row.update(max=1), "ohlc_bounds"),
            (lambda row: row.update(Trading_Volume=True), "canonical_int64"),
            (lambda row: row.update(Trading_money=1.0), "canonical_int64"),
            (lambda row: row.update(Trading_money=9223372036854775808), "canonical_int64"),
            (lambda row: row.update(spread="bad"), "price_number_type"),
            (lambda row: row.update(Trading_turnover=-1), "canonical_int64"),
        ]
        for mutate, code in mutations:
            documents = copy.deepcopy(original)
            mutate(documents[0]["data"][0])  # validates pre-last60 rows too
            snapshot, transport, _ = build(transport=Transport(body_docs(documents=documents)))
            self.assertFailure(code, snapshot.acquire)
            self.assertEqual(len(transport.opens), 2)
            self.assertEqual(snapshot.ledger.attempted, (0, 1))
            snapshot.release()
        for mode in ("missing", "extra", "duplicate", "anchor", "last_symbol"):
            documents = copy.deepcopy(original)
            if mode == "missing":
                documents[0]["data"].pop(0)
                code, expected = "price_row_count", 2
            elif mode == "extra":
                documents[0]["data"].append(copy.deepcopy(documents[0]["data"][0]))
                code, expected = "price_row_count", 2
            elif mode == "duplicate":
                documents[0]["data"][0] = copy.deepcopy(documents[0]["data"][1])
                code, expected = "price_duplicate_or_calendar", 2
            elif mode == "anchor":
                documents[0]["data"][-1]["Trading_money"] += 1
                code, expected = "latest_anchor_mismatch", 2
            else:
                documents[-1]["data"][0]["close"] = 0
                code, expected = "nonpositive_price", 8
            snapshot, transport, _ = build(transport=Transport(body_docs(documents=documents)))
            self.assertFailure(code, snapshot.acquire)
            self.assertEqual(len(transport.opens), expected)
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
            snapshot.release()

    def test_zero_price_rows_reject_whole_batch(self):
        _, original = corpus()
        changes = [(f"{key}_zero", lambda row, key=key: row.update({key: 0})) for key in ("open", "max", "min", "close")]
        changes += [
            ("no_posted_price_zero_volume", lambda row: row.update(open=0, max=0, min=0, close=0, Trading_Volume=0)),
            ("no_posted_price_with_volume", lambda row: row.update(open=0, max=0, min=0, close=0, Trading_Volume=451)),
            ("no_posted_price_decimal_zero", lambda row: row.update(open=0.0, max=0.0, min=0.0, close=0.0)),
        ]
        for label, change in changes:
            for symbol_index, row_index in ((0, 0), (3, 30), (6, 66)):
                with self.subTest(case=label, symbol=SYMBOLS[symbol_index], row=row_index):
                    documents = copy.deepcopy(original)
                    change(documents[symbol_index]["data"][row_index])
                    snapshot, transport, _ = build(transport=Transport(body_docs(documents=documents)))
                    self.assertFailure("nonpositive_price", snapshot.acquire)
                    self.assertEqual(len(transport.opens), symbol_index + 2)  # first failure stops the batch
                    self.assertEqual(snapshot.ledger.attempted, tuple(range(symbol_index + 2)))
                    self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-06")
                    snapshot.release()

    def test_price_json_duplicate_nonfinite_full_document(self):
        for raw, expected in ((b'{"status":200,"status":200,"msg":"success","data":[]}', "duplicate_json_key"),
                              (b'{"status":200,"msg":"success","data":[],"extra":NaN}', "nonfinite_json_number"),
                              (b'{"status":200,"msg":"success","data":[],"extra":Infinity}', "nonfinite_json_number")):
            bodies = body_docs()
            bodies[1] = raw
            snapshot, _, _ = build(transport=Transport(bodies))
            self.assertFailure(expected, snapshot.acquire)
            snapshot.release()

    def test_pending_oracle_exact_captures_tamper_counts_then_admit(self):
        snapshot, transport, _ = build()
        pending = snapshot.acquire()
        self.assertIs(pending, snapshot)
        self.assertEqual(snapshot.state, "pending")
        self.assertEqual(tuple(url for url, _ in transport.opens), EXPECTED_URLS)
        self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
        proof = admission(snapshot)
        for mutation in (replace(proof, price_rows=475), replace(proof, latest_anchor_fields=41)):
            self.assertFailure("oracle_complete_scope", snapshot.admit_independent_verification, mutation)
        self.assertFailure("oracle_type", snapshot.admit_independent_verification, replace(proof, calendar_rows=True))
        self.assertFailure("oracle_receipt_type", snapshot.admit_independent_verification, replace(proof, receipt_sha256s=(1,) * 8))
        for hashes in (proof.receipt_sha256s[:-1], proof.receipt_sha256s[::-1],
                       proof.receipt_sha256s[:-1] + (proof.receipt_sha256s[0],), ("0" * 64,) * 8):
            self.assertFailure("oracle_capture_binding", snapshot.admit_independent_verification, replace(proof, receipt_sha256s=hashes))
        snapshot.admit_independent_verification(proof)
        self.assertEqual(snapshot.state, "available")
        self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, proof)
        snapshot.release()

    def test_fourteen_windows_values_exact_rationals_and_prior_exclusion(self):
        snapshot, _, _ = available()
        _, documents = corpus()
        nonterminating = False
        for index, symbol in enumerate(SYMBOLS):
            for cutoff in CUTOFFS:
                records = [row for row in documents[index]["data"] if row["date"] <= cutoff][-60:]
                prior = [row for row in documents[index]["data"] if row["date"] < cutoff][-20:]
                window = source.get_nominal_ohlcv60(snapshot, symbol, cutoff)
                self.assertEqual(len(window.bars), 60)
                self.assertEqual(window.bars[0].date, "2026-07-10" if cutoff.endswith("05") else "2026-07-13")
                for actual, expected in zip(window.bars, records):
                    self.assertEqual(actual.date, expected["date"])
                    for field, provider in (("open", "open"), ("high", "max"), ("low", "min"), ("close", "close")):
                        self.assertEqual(getattr(actual, field), Fraction(str(expected[provider])))
                    self.assertEqual(actual.volume, expected["Trading_Volume"])
                    self.assertEqual(actual.amount, expected["Trading_money"])
                summary = source.ordinary_nominal_ohlcv_window_summary_v1(snapshot, symbol, cutoff).values
                def exact(values):
                    total = sum((Fraction(str(value)) for value in values), Fraction(0))
                    return total / len(values)
                expectations = {
                    "ma20_close": exact([r["close"] for r in records[-20:]]),
                    "ma60_close": exact([r["close"] for r in records]),
                    "prior20_high": max(Fraction(str(r["max"])) for r in prior),
                    "prior20_volume_mean": exact([r["Trading_Volume"] for r in prior]),
                    "prior20_amount_mean": exact([r["Trading_money"] for r in prior]),
                }
                for field, expected in expectations.items():
                    actual = summary[field]
                    self.assertEqual((actual.numerator, actual.denominator), (expected.numerator, expected.denominator))
                    self.assertGreater(actual.denominator, 0)
                    self.assertEqual(math.gcd(actual.numerator, actual.denominator), 1)
                denominator = summary["ma60_close"].denominator
                while denominator % 2 == 0:
                    denominator //= 2
                while denominator % 5 == 0:
                    denominator //= 5
                nonterminating |= denominator > 1
                self.assertLess(summary["prior20_end"], cutoff)
                self.assertEqual(summary["prior20_end"], prior[-1]["date"])
        self.assertTrue(nonterminating)
        provenance = snapshot.provenance
        self.assertEqual(provenance["unit_policy"]["scale"], 1)
        self.assertIs(provenance["unit_policy"]["unit_mapping_inference"], True)
        self.assertIs(provenance["unit_policy"]["provider_literal_unit_annotation"], False)
        self.assertEqual((provenance["publication_time"], provenance["first_availability"], provenance["revision_time"]), ("unknown",) * 3)
        for symbol, cutoff in (("0000", "2026-10-05"), ("3105", "2026-10-07"), ("3105", "2026-09-30")):
            self.assertFailure("unsupported_window_scope", snapshot.get_nominal_ohlcv60, symbol, cutoff)
        snapshot.release()

    def test_release_expiry_invalidates_held_windows_summaries_and_roots(self):
        for expiry in (False, True):
            snapshot, _, clock = available()
            window = snapshot.get_nominal_ohlcv60("3105", "2026-10-05")
            summary = snapshot.summarize_nominal_ohlcv60("3105", "2026-10-05")
            if expiry:
                clock.now += 180
                self.assertEqual(snapshot.state, "expired")
            else:
                snapshot.release()
            self.assertFailure("consumer_unavailable", lambda: window.bars)
            self.assertFailure("consumer_unavailable", lambda: summary.values)
            self.assertFailure("consumer_unavailable", lambda: snapshot.provenance)
            for value in (snapshot._captures, snapshot._decoded_texts, snapshot._documents, snapshot._results, snapshot._summaries, snapshot._capture_buffer, snapshot._formal_blob, snapshot._anchors):
                self.assertFalse(value)
            self.assertIsNone(snapshot._transport)
            self.assertIsNone(snapshot._observer_roots)
            self.assertEqual(snapshot.ledger.attempted, tuple(range(8)))
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)

    def test_attempt_charged_before_open_no_reacquire_same_ledger(self):
        ledger = source.AttemptLedger(NAMESPACE)
        snapshot, transport, _ = build(ledger=ledger, transport=Transport(fail_at=0))
        self.assertFailure("transport_or_parse_failure", snapshot.acquire)
        self.assertEqual(ledger.attempted, (0,))
        snapshot.release()
        another, other_transport, _ = build(ledger=ledger)
        self.assertFailure("quota_spent", another.acquire)
        self.assertEqual(other_transport.opens, [])
        self.assertEqual(ledger.unrun, tuple(range(1, 8)))

    def test_known_eof_exact_cap_no_plus_one_unknown_exact_cap_rejects(self):
        body = b"x" * source.BODY_CAP
        for known in (False, True):
            transport = Transport([body], response_options={0: {"declared": False, "eof": known}})
            snapshot, _, _ = build(transport=transport)
            code = "transport_or_parse_failure" if known else "body_cap_without_known_eof"
            self.assertFailure(code, snapshot.acquire)
            response = transport.responses[0]
            self.assertEqual(sum(count for count, _ in response.read_calls), source.BODY_CAP)
            self.assertEqual(len(response.read_calls), 16)
            self.assertTrue(all(count > 0 for count, _ in response.read_calls))
            self.assertEqual(len(snapshot.inspection()["captures"]), int(known))
            self.assertTrue(response.closed)
            self.assertEqual(snapshot._capture_buffer, b"")
            snapshot.release()

    def test_remaining_aggregate_and_declared_length_fail_closed(self):
        transport = Transport(response_options={0: {"headers": (("Content-Length", str(source.BODY_CAP + 1)),)}})
        snapshot, _, _ = build(transport=transport)
        self.assertFailure("declared_body_cap", snapshot.acquire)
        self.assertEqual(transport.responses[0].read_calls, [])
        self.assertEqual(snapshot._captures, [])
        snapshot.release()
        # Direct capture boundary starts with a synthetic used-byte scalar;
        # still charges before open, never reads beyond aggregate remaining.
        for known in (False, True):
            transport = Transport([b"12345"], response_options={0: {"declared": False, "eof": known}})
            snapshot, _, clock = build(transport=transport)
            snapshot._ledger.begin()
            snapshot._batch_deadline = clock.now + 180
            snapshot._raw_bytes = source.RAW_CAP - 5
            if known:
                capture = snapshot._capture(0, source.TRADING_DATE_URL)
                self.assertEqual(capture.body, b"12345")
                self.assertTrue(capture.receipt.full_eof)
            else:
                self.assertFailure("body_cap_without_known_eof", snapshot._capture, 0, source.TRADING_DATE_URL)
                self.assertEqual(snapshot._captures, [])
            self.assertEqual(transport.responses[0].read_calls[0][0], 5)
            self.assertEqual(len(transport.responses[0].read_calls), 1)
            self.assertEqual(snapshot._raw_bytes, source.RAW_CAP)
            snapshot.release()
        transport = Transport([b"123"], response_options={0: {"headers": (("Content-Length", "4"),) + JSON_TYPE}})
        snapshot, _, _ = build(transport=transport)
        self.assertFailure("incomplete_content_length", snapshot.acquire)
        self.assertEqual(snapshot._captures, [])
        snapshot.release()

    def test_framing_encoding_http_and_close_failure_boundaries(self):
        variants = [
            ({"status": 302}, "http_status"),
            ({"headers": (("Content-Encoding", "gzip"),)}, "content_encoding"),
            ({"headers": (("Content-Length", "01"),)}, "content_length"),
            ({"headers": (("Content-Length", "1"), ("Content-Length", "1"))}, "duplicate_framing_header"),
            ({"headers": (("Transfer-Encoding", "chunked"), ("Content-Length", "1"))}, "ambiguous_framing"),
            ({"headers": (("Transfer-Encoding", "other"),)}, "ambiguous_framing"),
        ]
        for options, code in variants:
            transport = Transport(response_options={0: options})
            snapshot, _, _ = build(transport=transport)
            self.assertFailure(code, snapshot.acquire)
            self.assertTrue(transport.responses[0].closed)
            self.assertEqual(len(transport.opens), 1)
            snapshot.release()

    def test_capture_primary_survives_close_raise_and_cleanup_only_rejects(self):
        for status, code, stage, secondary in ((302, "http_status", "capture_headers", 1),
                                               (200, "cleanup_failure", "capture_response_close", 0)):
            transport = Transport(response_options={0: {"status": status, "close_raises": True}})
            snapshot, _, _ = build(transport=transport)
            error = self.assertFailure(code, snapshot.acquire)
            self.assertEqual(error.diagnostics["primary_code"], code)
            self.assertEqual(error.diagnostics["primary_stage"], stage)
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], secondary)
            self.assertEqual(snapshot.diagnostics["code"], code)
            self.assertEqual(snapshot.diagnostics["primary_stage"], stage)
            if secondary:
                self.assertEqual(snapshot.diagnostics["secondary_cleanup_1_stage"], "capture_response_close")
                self.assertEqual(snapshot.diagnostics["secondary_cleanup_1_code"], "cleanup_failure")
            self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
            self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(snapshot.diagnostics)))
            self.assertEqual(transport.responses[0].close_calls, 1)
            self.assertEqual(snapshot.state, "failed")
            self.assertEqual(snapshot.ledger.attempted, (0,))
            self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
            self.assertEqual(snapshot._capture_buffer, b"")
            self.assertEqual(len(snapshot.inspection()["captures"]), int(status == 200))
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
            self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
            snapshot.release()
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)

    def test_https_response_both_closes_attempted_first_cleanup_preserved(self):
        calls = []
        class Body:
            status = 200
            fp = None
            def getheaders(self):
                return ()
            def close(self):
                calls.append("response")
                raise OSError("DO_NOT_RETAIN_RAW_response")
        class Connection:
            sock = object()
            def close(self):
                calls.append("connection")
                raise RuntimeError("DO_NOT_RETAIN_RAW_connection")
        response = source._HTTPSResponse(Connection(), Body())
        error = self.assertFailure("cleanup_failure", response.close)
        self.assertEqual(calls, ["response", "connection"])
        self.assertIsNone(response.socket)
        self.assertEqual(error.diagnostics["primary_stage"], "https_response_close")
        self.assertEqual(error.diagnostics["secondary_cleanup_count"], 1)
        self.assertEqual(error.diagnostics["secondary_cleanup_1_stage"], "https_connection_close")
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))
        # The outer capture already has an HTTP failure: preserve that primary
        # while flattening both close failures from the real response wrapper.
        calls.clear()
        class WrappedTransport:
            def open(self, url, timeout):
                body = Body()
                body.status = 302
                return source._HTTPSResponse(Connection(), body)
        snapshot, _, _ = build(transport=WrappedTransport())
        error = self.assertFailure("http_status", snapshot.acquire)
        self.assertEqual(calls, ["response", "connection"])
        self.assertEqual(error.diagnostics["primary_stage"], "capture_headers")
        self.assertEqual(error.diagnostics["secondary_cleanup_count"], 2)
        self.assertEqual(error.diagnostics["secondary_cleanup_1_stage"], "https_response_close")
        self.assertEqual(error.diagnostics["secondary_cleanup_2_stage"], "https_connection_close")
        self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(snapshot.diagnostics)))
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertEqual(snapshot.state, "failed")
        snapshot.release()

    def test_https_open_connect_header_primary_survives_multiple_cleanup(self):
        clock = Clock()
        for phase in ("connect", "headers"):
            calls = []
            class Body:
                def close(self):
                    calls.append("response_close")
                    raise OSError("DO_NOT_RETAIN_RAW_response")
            class Socket:
                def settimeout(self, value):
                    pass
            class Connection:
                def __init__(self, *args, **kwargs):
                    self.sock = Socket()
                def connect(self):
                    calls.append("connect")
                    if phase == "connect":
                        raise OSError("DO_NOT_RETAIN_RAW_connect")
                def request(self, *args, **kwargs):
                    calls.append("request")
                def getresponse(self):
                    calls.append("headers")
                    clock.now += 21
                    return Body()
                def close(self):
                    calls.append("connection_close")
                    raise RuntimeError("DO_NOT_RETAIN_RAW_connection")
            expected = "https_connect_failure" if phase == "connect" else "cooperative_deadline"
            with patch.object(source.time, "monotonic", clock), patch.object(source.http.client, "HTTPSConnection", Connection), patch.object(source.ssl, "create_default_context", lambda: object()):
                error = self.assertFailure(expected, source._HTTPSTransport().open, source.TRADING_DATE_URL, 20)
            self.assertEqual(error.diagnostics["primary_stage"], "https_" + phase)
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], 1 if phase == "connect" else 2)
            self.assertEqual(calls, ["connect", "connection_close"] if phase == "connect" else ["connect", "request", "headers", "response_close", "connection_close"])
            self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))

    def test_cumulative_request_and_batch_cooperative_deadlines(self):
        clock = Clock()
        transport = Transport(clock=clock, open_delay=12,
                              response_options={0: {"clock": clock, "read_delay": 9}})
        snapshot, _, _ = build(transport=transport, clock=clock)
        self.assertFailure("cooperative_deadline", snapshot.acquire)
        self.assertEqual(transport.responses[0].read_calls[0][1], 8)
        self.assertEqual(snapshot._raw_bytes, len(transport.bodies[0]))
        self.assertEqual(snapshot.ledger.attempted, (0,))
        self.assertTrue(transport.responses[0].closed)
        snapshot.release()
        # Independent direct-capture seam makes the last batch budget 3 seconds;
        # request budget is 20, so every I/O must receive the tighter 3.
        clock = Clock()
        transport = Transport(response_options={0: {"clock": clock, "read_delay": 4}})
        snapshot, _, _ = build(transport=transport, clock=clock)
        snapshot._ledger.begin()
        snapshot._batch_deadline = clock.now + 3
        self.assertFailure("cooperative_deadline", snapshot._capture, 0, source.TRADING_DATE_URL)
        self.assertEqual(transport.opens[0][1], 3)
        self.assertEqual(transport.responses[0].read_calls[0][1], 3)
        self.assertTrue(transport.responses[0].closed)
        snapshot.release()

    def test_observer_roots_dedup_and_over_cap_before_io(self):
        root = bytearray(1024)
        self.assertEqual(source.retained_roots_estimate(root, root), source.retained_roots_estimate(root))
        huge = bytearray(source.ROOTS_CAP)
        transport = Transport()
        self.assertFailure("retained_roots_estimate_cap", build, transport=transport, observer_roots=lambda: (huge,))
        self.assertEqual(transport.opens, [])
        huge.clear()

    def test_cleanup_primary_survives_later_failure_roots_cap(self):
        external = []
        failure_checks = []
        def observer():
            if external:
                failure_checks.append(True)
            return external
        class GrowingCloseTransport(Transport):
            def open(self, url, timeout):
                response = super().open(url, timeout)
                def close():
                    response.closed = True
                    response.close_calls += 1
                    external.append(bytearray(source.ROOTS_CAP))
                    raise OSError("DO_NOT_RETAIN_RAW" * 1000)
                response.close = close
                return response
        snapshot, transport, _ = build(transport=GrowingCloseTransport(), observer_roots=observer)
        try:
            error = self.assertFailure("cleanup_failure", snapshot.acquire)
            self.assertEqual(error.diagnostics["primary_stage"], "capture_response_close")
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], 0)
            self.assertEqual(error.diagnostics["secondary_validation_count"], 1)
            self.assertEqual(error.diagnostics["secondary_validation_1_code"], "retained_roots_estimate_cap")
            self.assertEqual(error.diagnostics["secondary_validation_1_stage"], "batch_failure_roots")
            self.assertGreater(error.diagnostics["secondary_validation_1_estimate_bytes"], source.ROOTS_CAP)
            self.assertEqual(failure_checks, [True])
            self.assertEqual(transport.responses[0].close_calls, 1)
            self.assertEqual(snapshot.ledger.attempted, (0,))
            self.assertEqual(snapshot.ledger.unrun, tuple(range(1, 8)))
            self.assertEqual(snapshot.state, "failed")
            self.assertEqual(snapshot._capture_buffer, b"")
            self.assertEqual(len(snapshot.inspection()["captures"]), 1)
            self.assertEqual(snapshot.diagnostics["primary_code"], "cleanup_failure")
            self.assertEqual(snapshot.diagnostics["secondary_validation_count"], 1)
            self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
            self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(snapshot.diagnostics)))
            self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)
        finally:
            snapshot.release()
            external.clear()

    def test_parse_primary_survives_later_failure_roots_caps(self):
        external = []
        failure_checks = []
        def observer():
            if external:
                failure_checks.append(True)
            return external
        trading, documents = corpus()
        documents[0]["data"][0]["close"] = 0
        snapshot, transport, _ = build(transport=Transport(body_docs(trading, documents)), observer_roots=observer)
        def trace(frame, event, arg):
            if (frame.f_globals.get("__name__") == spec.name and frame.f_code.co_name == "_prices"
                    and event == "exception" and isinstance(arg[1], source.SourceError)
                    and arg[1].code == "nonpositive_price" and not external):
                # Add the observed alias only after the actual price validator
                # has failed. The mandatory failure-path checks must still run.
                external.append(bytearray(source.ROOTS_CAP))
            return trace
        try:
            sys.settrace(trace)
            error = self.assertFailure("nonpositive_price", snapshot.acquire)
            sys.settrace(None)
            self.assertEqual(error.diagnostics["primary_stage"], "decode_parse")
            self.assertEqual(error.diagnostics["secondary_cleanup_count"], 0)
            self.assertEqual(error.diagnostics["secondary_validation_count"], 2)
            for index, stage in enumerate(("parse_failure_roots", "batch_failure_roots"), 1):
                self.assertEqual(error.diagnostics[f"secondary_validation_{index}_code"], "retained_roots_estimate_cap")
                self.assertEqual(error.diagnostics[f"secondary_validation_{index}_stage"], stage)
                self.assertGreater(error.diagnostics[f"secondary_validation_{index}_estimate_bytes"], source.ROOTS_CAP)
            self.assertEqual(failure_checks, [True, True])
            self.assertEqual([response.close_calls for response in transport.responses], [1, 1])
            self.assertEqual(snapshot.ledger.attempted, (0, 1))
            self.assertEqual(snapshot.ledger.unrun, tuple(range(2, 8)))
            self.assertEqual(snapshot.state, "failed")
            self.assertEqual(snapshot._capture_buffer, b"")
            self.assertEqual(len(snapshot.inspection()["captures"]), 2)
            self.assertEqual(snapshot.diagnostics["primary_code"], "nonpositive_price")
            self.assertEqual(snapshot.diagnostics["secondary_validation_count"], 2)
            self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
            self.assertFailure("oracle_pending_required", snapshot.admit_independent_verification, admission(snapshot))
            self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-06")
            self.assertFailure("snapshot_already_attempted", snapshot.acquire)
        finally:
            sys.settrace(None)
            snapshot.release()
            external.clear()

    def test_active_root_cap_invalidates_consumers_and_handles_are_immutable(self):
        external = []
        snapshot, _, _ = build(observer_roots=lambda: external)
        snapshot.acquire()
        snapshot.admit_independent_verification(admission(snapshot))
        window = snapshot.get_nominal_ohlcv60("3105", "2026-10-05")
        with self.assertRaises(AttributeError):
            window.cutoff = "2026-10-07"
        external.append(bytearray(source.ROOTS_CAP))
        self.assertFailure("retained_roots_estimate_cap", lambda: window.bars)
        self.assertEqual(snapshot.state, "failed")
        self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-05")
        snapshot.release()
        external.clear()

    def test_default_https_budget_boundaries_and_header_failure_closes_response(self):
        # The actual stdlib transport implementation is exercised with an
        # in-memory HTTPConnection boundary; the audit guard bans real sockets.
        clock = Clock()
        class Socket:
            def __init__(self):
                self.timeouts = []
            def settimeout(self, value):
                self.timeouts.append(value)
        class HTTPBody:
            status = 200
            length = 0
            fp = None
            def __init__(self):
                self.closed = False
            def getheaders(self):
                return (("Content-Length", "0"),)
            def isclosed(self):
                return self.closed
            def close(self):
                self.closed = True
        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.timeout, self.context = host, timeout, context
                self.sock = Socket()
                self.closed = False
                self.body = HTTPBody()
                self.requests = []
            def connect(self):
                clock.now += 12
            def request(self, method, target, headers):
                self.requests.append((method, target, headers))
                clock.now += 3
            def getresponse(self):
                clock.now += header_delay[0]
                return self.body
            def close(self):
                self.closed = True
        for delay in (1, 6):
            header_delay = [delay]
            clock.now = 100
            connections = []
            def factory(*args, **kwargs):
                value = Connection(*args, **kwargs)
                connections.append(value)
                return value
            with patch.object(source.time, "monotonic", clock), patch.object(source.http.client, "HTTPSConnection", factory), patch.object(source.ssl, "create_default_context", lambda: object()):
                if delay == 1:
                    response = source._HTTPSTransport().open(source.TRADING_DATE_URL, 20)
                    response.close()
                else:
                    self.assertFailure("cooperative_deadline", source._HTTPSTransport().open, source.TRADING_DATE_URL, 20)
            connection = connections[0]
            self.assertEqual(connection.timeout, 20)
            self.assertEqual(connection.sock.timeouts, [8, 5])
            self.assertTrue(connection.closed)
            self.assertTrue(connection.body.closed)
            self.assertEqual(connection.requests[0][0], "GET")
            self.assertEqual(connection.requests[0][2], FINMIND_REQUEST_HEADERS)

    def test_default_https_request_headers_are_the_four_fixed_finmind_headers(self):
        # In-memory HTTPSConnection boundary: the audit guard bans real sockets.
        class Socket:
            def settimeout(self, value):
                pass

        class HTTPBody:
            status = 200
            length = 0
            fp = None
            closed = False

            def getheaders(self):
                return (("Content-Length", "0"),)

            def isclosed(self):
                return self.closed

            def close(self):
                self.closed = True

        class Connection:
            def __init__(self, host, timeout, context):
                self.host, self.timeout, self.context = host, timeout, context
                self.sock, self.body, self.requests = Socket(), HTTPBody(), []
                self.tunnel_used = False

            def connect(self):
                pass

            def set_tunnel(self, *args, **kwargs):
                self.tunnel_used = True

            def request(self, method, target, headers):
                self.requests.append((method, target, headers))

            def getresponse(self):
                return self.body

            def close(self):
                pass

        self.assertEqual(source.TRADING_DATE_URL, TRADING_DATE_URL_LITERAL)
        self.assertEqual([source.PRICE_URL.format(symbol) for symbol in SYMBOLS], list(EXPECTED_URLS[1:]))
        forbidden = {"cookie", "set-cookie", "authorization", "proxy-authorization", "proxy-connection", "x-api-key", "token"}
        connections = []

        def factory(*args, **kwargs):
            value = Connection(*args, **kwargs)
            connections.append(value)
            return value

        for url in EXPECTED_URLS:
            with self.subTest(url=url):
                with patch.object(source.http.client, "HTTPSConnection", factory), patch.object(source.ssl, "create_default_context", lambda: object()):
                    source._HTTPSTransport().open(url, 20).close()
                connection = connections[-1]
                self.assertEqual(connection.host, "api.finmindtrade.com")
                self.assertFalse(connection.tunnel_used)
                self.assertEqual(len(connection.requests), 1)
                method, target, headers = connection.requests[0]
                self.assertEqual(method, "GET")
                self.assertEqual(target, url.split(connection.host, 1)[1])
                self.assertEqual(headers, FINMIND_REQUEST_HEADERS)
                self.assertTrue(forbidden.isdisjoint(key.lower() for key in headers))
        # Every other host/scheme/port/userinfo (TPEx included) is refused before a connection is built.
        built = len(connections)
        for bad in ("https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F07%2F01",
                    "https://example.org/a?b=1", "http://api.finmindtrade.com/a?b=1",
                    "https://api.finmindtrade.com:443/a?b=1", "https://user@api.finmindtrade.com/a?b=1"):
            with self.subTest(refused=bad), patch.object(source.http.client, "HTTPSConnection", factory):
                self.assertFailure("transport_url", source._HTTPSTransport().open, bad, 20)
        self.assertEqual(len(connections), built)

    def assertReplayAccepted(self, wires, july_days):
        snapshot, transport = replay(wires)
        snapshot.acquire()
        self.assertEqual(snapshot.state, "pending")
        self.assertEqual(tuple(transport.opens), EXPECTED_URLS)
        self.assertEqual(snapshot.ledger.attempted, tuple(range(8)))
        for host, method, target, headers in transport.requests:
            self.assertEqual((host, method, headers), ("api.finmindtrade.com", "GET", FINMIND_REQUEST_HEADERS))
        # Set-Cookie is observed but never stored or echoed: no request carries a credential.
        self.assertFalse(any(key.lower() in ("cookie", "authorization", "proxy-authorization")
                             for request in transport.requests for key in request[3]))
        snapshot.admit_independent_verification(admission(snapshot, july_days))
        for cutoff in CUTOFFS:
            self.assertEqual(len(snapshot.get_nominal_ohlcv60("3105", cutoff).bars), 60)
        snapshot.release()
        return transport

    def assertReplayPrefixAccepted(self, accepted_wires):
        """Every wire in accepted_wires is captured, parsed and validated; a poison response then stops the batch."""
        poison = finmind_wire(b"<html>poison</html>")
        snapshot, transport = replay(list(accepted_wires) + [poison])
        count = len(accepted_wires)
        error = self.assertFailure("transport_or_parse_failure", snapshot.acquire)
        self.assertEqual(error.diagnostics["source_index"], count)
        self.assertEqual(snapshot.ledger.attempted, tuple(range(count + 1)))
        self.assertEqual(len(snapshot.inspection()["documents"]), count)
        captures = tuple(snapshot.inspection()["captures"])
        for _, _, _, headers in transport.requests:
            self.assertEqual(headers, FINMIND_REQUEST_HEADERS)
        self.assertFalse(any(key.lower() in ("cookie", "authorization", "proxy-authorization")
                             for request in transport.requests for key in request[3]))
        snapshot.release()
        return captures, transport

    def assertReplayRejected(self, wires, code, opens):
        snapshot, transport = replay(wires)
        self.assertFailure(code, snapshot.acquire)
        self.assertEqual(len(transport.opens), opens)  # first-failure stop: no redirect follow, no later GET
        self.assertEqual(snapshot.ledger.attempted, tuple(range(opens)))
        self.assertEqual(snapshot.state, "failed")
        self.assertFailure("consumer_unavailable", snapshot.get_nominal_ohlcv60, "3105", "2026-10-06")
        snapshot.release()

    def test_replay_full_pipeline_for_each_accepted_framing(self):
        july = july_without("2026-07-15")
        trading, _ = corpus(july)
        bodies = body_docs(july=july)[1:]
        shapes = (("content_length_keep_alive", dict(extra=[("Connection", "keep-alive")])),
                  ("chunked_with_set_cookie_and_duplicate_vary",
                   dict(framing="chunked", extra=[("Set-Cookie", "__cf_bm=synthetic; Path=/; HttpOnly"), ("Vary", "Origin")])),
                  ("close_delimited_http11", dict(framing="close")))
        for label, options in shapes:
            with self.subTest(framing=label):
                self.assertReplayAccepted([finmind_wire(body, **options) for body in [trading] + bodies], len(july))

    def test_response_shape_v3_every_row_accept_and_reject(self):
        july = july_without("2026-07-15")
        trading, _ = corpus(july)
        price = body_docs(july=july)[1]
        # Each accepted shape is applied to the trading-date response AND the first price response.
        accepted = (
            # content_type: application/json with or without charset=utf-8
            ("ct_plain", {}),
            ("ct_charset_utf8", dict(content_type="application/json; charset=utf-8")),
            ("ct_charset_upper_no_space", dict(content_type="application/json;charset=UTF-8")),
            ("ct_mixed_case", dict(content_type="Application/JSON; Charset=UTF-8")),
            ("ct_space_before_semicolon", dict(content_type="application/json ;charset=utf-8")),
            # framing: content-length, chunked, close-delimited (HTTP/1.1 and 1.0)
            ("framing_content_length", dict(framing="length")),
            ("framing_chunked", dict(framing="chunked")),
            ("framing_chunked_mixed_case_token", dict(framing="chunked", te="Chunked")),
            ("framing_close_delimited_http11", dict(framing="close")),
            ("framing_close_delimited_http10", dict(framing="close", version="1.0")),
            # content_encoding: identity or absent
            ("encoding_identity", dict(content_encoding="identity")),
            ("encoding_identity_mixed_case", dict(content_encoding="Identity")),
            # set_cookie accepted; other duplicate headers accepted and ignored
            ("set_cookie_once", dict(extra=[("Set-Cookie", "__cf_bm=synthetic; Path=/; HttpOnly")])),
            ("set_cookie_twice", dict(extra=[("Set-Cookie", "__cf_bm=synthetic; Path=/; HttpOnly"), ("Set-Cookie", "other=1")])),
            ("duplicate_non_identity_headers", dict(extra=[("Vary", "Origin"), ("Vary", "Accept"), ("Cache-Control", "no-store"),
                                                          ("Cache-Control", "no-cache"), ("X-Ratelimit-Remaining", "299"),
                                                          ("X-Ratelimit-Remaining", "298")])),
            ("connection_header_values", dict(extra=[("Connection", "keep-alive")])),
        )
        for label, options in accepted:
            with self.subTest(accepted=label):
                captures, _ = self.assertReplayPrefixAccepted([finmind_wire(trading, **options), finmind_wire(price, **options)])
                self.assertEqual(captures[0].receipt.status, 200)
                self.assertEqual(captures[0].receipt.content_encoding, "identity")

        header_rejects = []
        for status, reason in ((201, "Created"), (204, "No Content"), (206, "Partial Content"), (304, "Not Modified"),
                               (400, "Bad Request"), (401, "Unauthorized"), (402, "Payment Required"), (403, "Forbidden"),
                               (404, "Not Found"), (429, "Too Many Requests"), (500, "Internal Server Error"),
                               (503, "Service Unavailable")):
            header_rejects.append((f"status_{status}", lambda body, s=status, r=reason: finmind_wire(body, status=s, reason=r), "http_status"))
        for status, reason in ((301, "Moved Permanently"), (302, "Found"), (307, "Temporary Redirect"), (308, "Permanent Redirect")):
            header_rejects.append((f"redirect_{status}", lambda body, s=status, r=reason: finmind_wire(
                body, status=s, reason=r, extra=[("Location", "https://example.invalid/next")]), "http_status"))
        for label, content_type in (("missing", None), ("empty", ""), ("text_html", "text/html; charset=utf-8"),
                                    ("application_csv", "application/csv"), ("text_json", "text/json"),
                                    ("x_json", "application/x-json"), ("jsonp", "application/jsonp"),
                                    ("charset_big5", "application/json; charset=big5"),
                                    ("charset_latin1", "application/json; charset=iso-8859-1"),
                                    ("extra_parameter", "application/json; charset=utf-8; boundary=x")):
            header_rejects.append((f"content_type_{label}", lambda body, c=content_type: finmind_wire(body, content_type=c), "content_type"))
        for value in ("gzip", "br", "deflate", "zstd", "gzip, identity", ""):
            header_rejects.append((f"content_encoding_{value or 'empty'}", lambda body, v=value: finmind_wire(body, content_encoding=v),
                                   "content_encoding"))
        header_rejects += [
            ("content_length_and_chunked", lambda body: finmind_wire(body, framing="both"), "ambiguous_framing"),
            ("transfer_encoding_gzip_chunked", lambda body: finmind_wire(body, framing="close", extra=[("Transfer-Encoding", "gzip, chunked")]),
             "ambiguous_framing"),
            ("transfer_encoding_identity", lambda body: finmind_wire(body, framing="close", extra=[("Transfer-Encoding", "identity")]),
             "ambiguous_framing"),
            ("content_length_leading_zero", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", "0" + str(len(body)))]),
             "content_length"),
            ("content_length_plus_sign", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", "+" + str(len(body)))]),
             "content_length"),
            ("content_length_over_body_cap", lambda body: finmind_wire(body, framing="close", extra=[("Content-Length", str(source.BODY_CAP + 1))]),
             "declared_body_cap"),
            ("duplicate_content_length", lambda body: finmind_wire(body, extra=[("Content-Length", str(len(body)))]), "duplicate_framing_header"),
            ("duplicate_content_length_lower_case", lambda body: finmind_wire(body, extra=[("content-length", str(len(body)))]),
             "duplicate_framing_header"),
            ("duplicate_content_type", lambda body: finmind_wire(body, extra=[("Content-Type", "application/json")]), "duplicate_framing_header"),
            ("duplicate_content_type_upper_case", lambda body: finmind_wire(body, extra=[("CONTENT-TYPE", "application/json")]),
             "duplicate_framing_header"),
            ("duplicate_content_encoding", lambda body: finmind_wire(body, content_encoding="identity", extra=[("content-encoding", "identity")]),
             "duplicate_framing_header"),
            ("duplicate_transfer_encoding", lambda body: finmind_wire(body, framing="chunked", extra=[("Transfer-Encoding", "chunked")]),
             "duplicate_framing_header"),
        ]
        junk = b"x" * (source.BODY_CAP + 1024)
        body_rejects = [
            ("content_length_longer_than_body",
             lambda body: raw_http([("Content-Type", "application/json"), ("Content-Length", "999")], b"x" * 10), "missing_known_eof"),
            ("chunked_truncated",
             lambda body: raw_http([("Content-Type", "application/json"), ("Transfer-Encoding", "chunked")], chunk_encode(body)[:-5]),
             "transport_or_parse_failure"),
            ("close_delimited_cap_reached_without_eof", lambda body: finmind_wire(junk, framing="close"), "body_cap_without_known_eof"),
            ("close_delimited_exactly_cap_no_eof_seen", lambda body: finmind_wire(b"x" * source.BODY_CAP, framing="close"),
             "body_cap_without_known_eof"),
            ("chunked_cap_reached_without_eof", lambda body: finmind_wire(junk, framing="chunked"), "body_cap_without_known_eof"),
            ("empty_body", lambda body: finmind_wire(b""), "empty_body"),
            ("utf8_bom", lambda body: finmind_wire(b"\xef\xbb\xbf" + body), "transport_or_parse_failure"),
            ("invalid_utf8", lambda body: finmind_wire(b"\xff" + body), "transport_or_parse_failure"),
            ("utf16_body", lambda body: finmind_wire(body.decode("utf8").encode("utf-16")), "transport_or_parse_failure"),
            ("html_error_page_with_200", lambda body: finmind_wire(b"<html>blocked</html>"), "transport_or_parse_failure"),
        ]
        for label, build_wire, code in header_rejects + body_rejects:
            with self.subTest(rejected=label, at="trading_dates"):
                self.assertReplayRejected([build_wire(trading)], code, 1)
            with self.subTest(rejected=label, at="price"):
                self.assertReplayRejected([finmind_wire(trading), build_wire(price)], code, 2)

        # status inside a 200 body: paid / login / limit responses are first failures at either position.
        paid = json.dumps({"msg": "Your level is register. Please update your user level.", "status": 402}).encode()
        login = json.dumps({"msg": "login required", "status": 401, "data": []}).encode()
        self.assertReplayRejected([finmind_wire(paid)], "trading_dates_document", 1)
        self.assertReplayRejected([finmind_wire(login)], "trading_dates_status", 1)
        self.assertReplayRejected([finmind_wire(trading), finmind_wire(paid)], "price_document", 2)
        self.assertReplayRejected([finmind_wire(trading), finmind_wire(login)], "price_document_status", 2)

    def test_trace_same_body_receipt_before_parse_and_error_roots(self):
        events = {"during": [], "ready": [], "error": []}
        trading, documents = corpus()
        documents[0]["data"][0]["close"] = 0
        snapshot, transport, _ = build(transport=Transport(body_docs(trading, documents)),
                                      observer_roots=lambda: events)
        def trace(frame, event, arg):
            if frame.f_globals.get("__name__") != spec.name:
                return trace
            name = frame.f_code.co_name
            if name == "_capture" and event == "line" and frame.f_locals.get("capture_buffer"):
                events["during"].append(frame.f_locals["capture_buffer"])
            if name == "_capture_ready" and event == "return":
                events["ready"].append((frame.f_locals["full_body"], frame.f_locals["receipt"]))
            if name == "_parse_capture" and event == "exception":
                events["error"].append({key: frame.f_locals.get(key) for key in
                                         ("full_body", "receipt", "decoded_text", "document", "parse_results", "diagnostics")})
            return trace
        try:
            sys.settrace(trace)
            self.assertFailure("nonpositive_price", snapshot.acquire)
        finally:
            sys.settrace(None)
        self.assertTrue(events["during"])
        self.assertEqual(len(events["ready"]), 2)
        for index, (body, receipt) in enumerate(events["ready"]):
            self.assertIs(body, snapshot._captures[index].body)
            self.assertEqual(hashlib.sha256(body).hexdigest(), receipt.body_sha256)
            self.assertEqual(len(body), receipt.body_bytes)
            self.assertTrue(receipt.full_eof)
        self.assertTrue(any(event["document"] is not None and event["decoded_text"] is not None for event in events["error"]))
        self.assertEqual(snapshot.diagnostics["primary_code"], "nonpositive_price")
        self.assertEqual(snapshot.diagnostics["primary_stage"], "decode_parse")
        self.assertTrue(all(type(value) in (str, int) for value in snapshot.diagnostics.values()))
        snapshot.release()
        events.clear()
        self.assertEqual(snapshot._capture_buffer, b"")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        sys.modules.pop(spec.name, None)
