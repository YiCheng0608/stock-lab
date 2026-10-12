"""Standalone synthetic runner for issue 7's ordinary-close source, saved bundle and reader.

Run from the repository root with TMPDIR/TEMP/TMP pointing at a short isolated directory:
  python -I -B -X utf8 backend/tests/test_ordinary_close_source.py

No source request, no database, no service, no seal. Before the module under test is even
imported an audit hook forbids sockets and every write outside this process's single temporary
session directory; subprocesses are allowed only for the fixed ``python -I -B`` reader child.
The pinned formal blob d8918bc... is read once with ``git cat-file`` before the hook exists
(never the working-tree registry). Every calendar and price value below is synthetic boundary
data, not source truth. The policy under test is the published policy v1 (issue 7 comment
6125706492, kept below as an independent literal); other cutoffs and windows are that same text
with only the window parameters replaced, and their pins are computed here, not taken from the module.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import http.client
import inspect
import io
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FORMAL_OBJECT = "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md"
FORMAL_SHA = "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"


def _read_pinned_formal_blob():
    """Read the pinned formal blob from git, once, before the audit hook forbids subprocess."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("cannot read pinned formal blob %s: git executable not found" % FORMAL_OBJECT)
    try:
        done = subprocess.run([git, "cat-file", "blob", FORMAL_OBJECT], cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("cannot read pinned formal blob %s: git cat-file failed to run (%r)" % (FORMAL_OBJECT, error)) from error
    if done.returncode != 0:
        raise RuntimeError("pinned formal blob %s is unavailable (git cat-file exit %d: %s)"
                           % (FORMAL_OBJECT, done.returncode, done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


if not sys.dont_write_bytecode:
    raise RuntimeError("Use -B: the runner does not permit bytecode artifacts")
FORMAL = _read_pinned_formal_blob()
assert hashlib.sha256(FORMAL).hexdigest() == FORMAL_SHA
SESSION = tempfile.mkdtemp(prefix="o")  # the only place this process may write
if len(SESSION) > 190:  # final bundle paths add ~70 characters; Windows MAX_PATH is 260
    shutil.rmtree(SESSION)
    raise RuntimeError("point TMPDIR/TEMP/TMP at a shorter directory (session path %d chars)" % len(SESSION))
PYTHON = sys.executable
_CHILD_PREFIX = subprocess.list2cmdline([PYTHON, "-I", "-B"]) + " "
BLOCKED = []
CHILD_ALLOWED = [False]
_APPROVED = os.path.normcase(os.path.abspath(SESSION))
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_APPEND", 0)
_PATH_EVENTS = ("os.mkdir", "os.rmdir", "os.remove", "os.rename", "os.chmod", "os.truncate", "os.utime",
                "os.link", "os.symlink", "os.chown", "shutil.copyfile", "shutil.copymode", "shutil.copystat",
                "shutil.copytree", "shutil.move", "shutil.rmtree")


def _inside(path):
    if isinstance(path, int):
        return True
    try:
        text = os.fsdecode(path)
    except TypeError:
        return False
    full = os.path.normcase(os.path.abspath(text))
    return full == _APPROVED or full.startswith(_APPROVED + os.sep)


def _audit(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname"):
        BLOCKED.append(event)
        raise AssertionError("runner forbids network")
    if event == "subprocess.Popen":
        command = args[1] if len(args) > 1 else None  # Windows hands the audit hook the joined command line
        isolated = (command.startswith(_CHILD_PREFIX) if isinstance(command, str)
                    else isinstance(command, (list, tuple)) and list(command[:3]) == [PYTHON, "-I", "-B"])
        if CHILD_ALLOWED[0] and isolated:
            return
        BLOCKED.append(event)
        raise AssertionError("runner forbids process launch")
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(letter in mode for letter in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing and not (isinstance(path, str) and os.path.normcase(path) in (os.devnull, "nul")) and not _inside(path):
            BLOCKED.append(event)
            raise AssertionError("runner forbids writes outside its session directory")
    elif event in _PATH_EVENTS:
        for item in args[:2]:
            if isinstance(item, (str, bytes, os.PathLike)) and not _inside(item):
                BLOCKED.append(event)
                raise AssertionError("runner forbids writes outside its session directory")


sys.addaudithook(_audit)
sys.path.insert(0, str(ROOT / "backend"))
from app import ohlcv_history_source as base  # noqa: E402  (imported under the hook: no import-time I/O)
from app import ordinary_close_source as occ  # noqa: E402

IMPORT_BLOCKED = tuple(BLOCKED)

OCC_FILE = ROOT / "backend/app/ordinary_close_source.py"
BASE_FILE = ROOT / "backend/app/ohlcv_history_source.py"

NAMESPACE = "issue7-ordinary-close-saved-seven-v1/qa1"
POLICY_VERSION = "issue7-ordinary-close-saved-seven-v1"
PURPOSE = "local_personal_noncommercial_private_derived_close_window"
CONSUMER = "ordinary-close-saved-window-v1"
STORAGE_SCHEMA = "ordinary-close-saved/v1"
RECEIPT_SCHEMA = "ordinary-close-receipt/v1"
ROOT_ENV = "STOCK_ORDINARY_CLOSE_PRIVATE_ROOT"
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
TRADING_VERSION = "finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue7-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
LIMITATIONS = [
    "date_is_asia_taipei_trading_calendar_date_not_utc",
    "identity_and_unit_anchored_only_at_2026-10-06",
    "publication_time_first_availability_revision_time_unknown",
    "closes_only_no_open_high_low_volume_amount",
    "raw_body_not_stored_hashes_only",
    "personal_noncommercial_local_use_no_redistribution",
]
UNSUPPORTED = ["historical_pit", "publication_time", "first_availability", "revision_guarantee", "adjusted_prices",
               "company_actions", "suspension_comparability", "whole_window_historical_membership",
               "historical_eligibility", "actionable_strategy", "plan", "trading", "historical_simulation",
               "raw_body_storage", "redistribution", "other_cutoffs"]
ANCHORS = {
    "3105": (615, 623, 588, 592, 19731700, 11863581093),
    "3293": (794, 794, 772, 780, 1495462, 1164617657),
    "5274": (19520, 19895, 18855, 18985, 188693, 3627465565),
    "5347": (184.5, 195, 184.5, 191, 34637793, 6615109776),
    "6488": (1175, 1260, 1145, 1205, 13913614, 16835605385),
    "6510": (3125, 3140, 3050, 3055, 560518, 1729347985),
    "8069": (147, 151.5, 145, 149, 10796741, 1607943663),
}
START, END, CUT = "2026-07-01", "2026-10-06", "2026-10-06"
FORMAL_END = "2026-10-06"
FORMAL_CLOSED = ("2026-09-25", "2026-09-28")
BEYOND = ("2026-10-07", "2026-10-08", "2026-10-09")
RIGHTS = "FinMind personal noncommercial local private derived closes; attribution; no raw body storage, redistribution or mirror"
ATTRIBUTION = ("Source: FinMind (finmindtrade.com) TaiwanStockPrice and TaiwanStockTradingDate; provider-reported daily closes "
               "kept as private local derived values; raw bodies not stored or redistributed")

# Synthetic financial-start identities (pure guard only; never passed to an acquiring constructor).
SEAL_ISSUER = "f0000000-0000-0000-0000-0000000000a1"
SEAL_COORDINATORS = ("f0000000-0000-0000-0000-0000000000b1", "f0000000-0000-0000-0000-0000000000b2")
SEAL_IMPLEMENTERS = ("f0000000-0000-0000-0000-0000000000c1", "f0000000-0000-0000-0000-0000000000c2")
QA_HOLDER = "5d2f6c1e-7a40-4b8e-9c3d-1e2f3a4b5c6d"
SEAL_FLOOR = 6125706492  # the policy v1 publication comment: a seal must be newer
SEAL_URL = "https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-9999999999"


def canonical(value):
    """Independent stdlib serialization, never the product's helper."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def weekdays(start, stop):
    value, end = date.fromisoformat(start), date.fromisoformat(stop)
    result = []
    while value <= end:
        if value.weekday() < 5:
            result.append(value.isoformat())
        value += timedelta(days=1)
    return tuple(result)


def calendar(start=START, end=END, beyond=()):
    inside = tuple(day for day in weekdays(start, min(end, FORMAL_END)) if day not in FORMAL_CLOSED)
    return inside + tuple(beyond)


DATES = calendar()
JULY = weekdays("2026-07-01", "2026-07-31")
PRIOR = tuple(day for day in DATES if day >= "2026-08-01")
assert len(DATES) == 68 and len(JULY) == 23 and len(PRIOR) == 45 and DATES == JULY + PRIOR


def fmt(value):
    """Independent canonical decimal text of a synthetic price."""
    return format(Decimal(repr(value)).normalize(), "f")


def price_rows(stock_index, symbol, dates, variant=0):
    rows = []
    for index, day in enumerate(dates):
        close = 100 + stock_index * 10 + index + ((index + stock_index) % 4) * 0.25 + (0.5 if variant == 1 else 0)
        row = {"date": day, "stock_id": symbol, "open": close, "max": close + 2, "min": close - 2, "close": close,
               "Trading_Volume": 1000 + index * 3 + (7 if variant == 2 else 0), "Trading_money": 100000 + index * 13,
               "spread": -1, "Trading_turnover": 2}
        if day == FORMAL_END:
            o, h, l, c, v, a = ANCHORS[symbol]
            row.update(open=o, max=h, min=l, close=c, Trading_Volume=v, Trading_money=a)
        rows.append(row)
    return rows


def trading_body(dates, extra_rows=()):
    rows = [{"date": day} for day in dates] + list(extra_rows)
    return json.dumps({"msg": "success", "status": 200, "data": rows}, separators=(",", ":")).encode("utf8")


def price_body(document):
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf8")


class Corpus:
    def __init__(self, start=START, end=END, beyond=(), variant=0):
        self.dates = calendar(start, end, beyond)
        self.rows = {symbol: price_rows(index, symbol, self.dates, variant) for index, symbol in enumerate(SYMBOLS)}
        self.documents = [{"status": 200, "msg": "success", "data": self.rows[symbol]} for symbol in SYMBOLS]
        self.bodies = [trading_body(self.dates)] + [price_body(document) for document in self.documents]

    def closes_doc(self, cutoff):
        rows = {symbol: [[row["date"], fmt(row["close"])] for row in self.rows[symbol] if row["date"] <= cutoff][-60:]
                for symbol in SYMBOLS}
        return {"schema": STORAGE_SCHEMA, "cutoff": cutoff, "count": 60, "symbols": list(SYMBOLS),
                "trading_dates": [day for day, _ in rows[SYMBOLS[0]]], "counts": {symbol: 60 for symbol in SYMBOLS},
                "closes": rows}

    def closes_bytes(self, cutoff):
        return canonical(self.closes_doc(cutoff))


_CORPORA = {}


def corpus(start=START, end=END, beyond=(), variant=0):
    key = (start, end, tuple(beyond), variant)
    if key not in _CORPORA:
        _CORPORA[key] = Corpus(start, end, beyond, variant)
    return _CORPORA[key]


# Policy v1 exactly as published in issue 7 comment 6125706492 (5,173 bytes; sorted keys, compact, no trailing LF).
V1_POLICY = b'{"acquisition":{"accept":"application/json","accept_encoding":"identity","batch_seconds":180,"body_cap_bytes":1048576,"deadline":"cooperative","max_gets":8,"namespace":"issue7-ordinary-close-saved-seven-v1/qa1","order":"FinMind trading dates then seven prices ascending","per_source_max_gets":1,"redirects":0,"request_seconds":20,"retained_roots_estimate_cap_bytes":33554432,"retries":0,"stop_on_first_failure":true,"total_raw_cap_bytes":8388608,"user_agent":"stock-lab-issue32-local-ram/1"},"attribution":"Source: FinMind (finmindtrade.com) TaiwanStockPrice and TaiwanStockTradingDate; provider-reported daily closes kept as private local derived values; raw bodies not stored or redistributed","consumer_version":"ordinary-close-saved-window-v1","cutoff":"2026-10-06","first_availability":"unknown","identity_as_of":"2026-10-06","instrument_type":"ordinary_stock","market":"TW/TPEx","price_source":{"basis":"provider_reported_nominal_ohlcv","dataset":"TaiwanStockPrice","end_date":"2026-10-06","endpoint":"https://api.finmindtrade.com/api/v4/data","fields":{"amount":"Trading_money","close":"close","high":"max","low":"min","open":"open","volume":"Trading_Volume"},"method":"GET","provider":"FinMind","query_order":["dataset","data_id","start_date","end_date"],"rights":"FinMind personal noncommercial local private derived closes; attribution; no raw body storage, redistribution or mirror","start_date":"2026-07-01"},"profile":"free_public_local","publication_time":"unknown","response_shape":{"content_encoding":"identity or absent; gzip/br rejects (accepted risk)","content_type":"application/json with or without charset=utf-8; anything else rejects","duplicate_identity_headers":"content-length, content-encoding, transfer-encoding, content-type duplicates reject; other duplicate headers accepted and ignored","encoding":"strict UTF-8 without BOM","framing":"content-length, chunked, or close-delimited (read to EOF within body cap); content-length and chunked together rejects; cap reached without EOF rejects","set_cookie":"accepted, never stored or sent","status":"200 only; 401/402/403 or any paid/login response is first failure","zero_price_rows":"FinMind no-posted-price rows with zero OHLC reject the whole batch (accepted risk; suspension unsupported)"},"revision_time":"unknown","source_use":"local_personal_noncommercial_private_derived_close_window","storage":{"kind":"private_local_derived_closes","layout":"<policy_version>/<cutoff>/{closes.json,receipt.json}","max_bundles":2,"max_closes_bytes":65536,"max_files":4,"max_receipt_bytes":32768,"max_total_bytes":196608,"raw_body":"not_stored","root_env":"STOCK_ORDINARY_CLOSE_PRIVATE_ROOT","schema":"ordinary-close-saved/v1","stored_fields":["date","close"]},"symbols":["3105","3293","5274","5347","6488","6510","8069"],"trading_date_source":{"dataset":"TaiwanStockTradingDate","documentation":"https://finmind.github.io/tutor/TaiwanMarket/Technical/ (doc GET receipt issue32 comment 6111856880); free tokenless use is inferred, 401/402/403 is first failure","endpoint":"https://api.finmindtrade.com/api/v4/data","expected_scope":"observed FinMind trading dates; every returned row structurally valid, unique and ascending; rows outside the window are discarded only after structural validation; in-window dates must be weekdays, include the cutoff, give at least 60 sessions at or before the cutoff, equal formal Aug-Oct 45 dates exactly within that span, contain no day after 2026-10-06 except the declared beyond_formal_trading_dates (empty here), and equal each of seven price date sets exactly; no fixed count; no closure inference; any unexplained mismatch rejects whole batch","fields":{"date":"date"},"format":"JSON","method":"GET","prior_calendar_formal_blob":"d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md","prior_calendar_formal_sha256":"b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde","prior_verified_counts":{"August":21,"October_through_6":4,"September":20},"provider":"FinMind","rights":"FinMind personal noncommercial local private derived closes; attribution; no raw body storage, redistribution or mirror","url":"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate&start_date=2026-07-01&end_date=2026-10-06","version":"finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue7-v1"},"unit_policy":{"OHLC":"TWD/share","all_seven_must_match":true,"amount":"TWD","independent_latest_anchor":"stock-lab/master:d8918bc6491ec8ef65874979cf88d1322df2da43:SOURCE_REGISTRY/32.2:2026-10-06:42-fields","provider_literal_unit_annotation":false,"scale":1,"unit_mapping_inference":true,"version":"issue32-composite-six-field-scale1-v1","volume":"shares"},"unsupported":["historical_pit","publication_time","first_availability","revision_guarantee","adjusted_prices","company_actions","suspension_comparability","whole_window_historical_membership","historical_eligibility","actionable_strategy","plan","trading","historical_simulation","raw_body_storage","redistribution","other_cutoffs"],"version":"issue7-ordinary-close-saved-seven-v1","window":{"beyond_formal_trading_dates":[],"end_date":"2026-10-06","start_date":"2026-07-01"}}'
V1_SHA = "f7659362cd3056413545d48a40a2e89bc97b810dc9c5535a4c8bdca41fcb9968"  # as quoted in that comment
V1_BYTES = 5173


def policy_dict(cutoff=CUT, start=START, end=END, beyond=()):
    """The published policy with only the window parameters replaced (the identity for the default arguments)."""
    policy = json.loads(V1_POLICY)
    policy["cutoff"] = cutoff
    policy["window"] = {"start_date": start, "end_date": end, "beyond_formal_trading_dates": list(beyond)}
    policy["price_source"]["start_date"], policy["price_source"]["end_date"] = start, end
    policy["trading_date_source"]["url"] = f"{ENDPOINT}?dataset=TaiwanStockTradingDate&start_date={start}&end_date={end}"
    return policy


assert len(V1_POLICY) == V1_BYTES and hashlib.sha256(V1_POLICY).hexdigest() == V1_SHA
assert canonical(policy_dict()) == V1_POLICY


def policy_pack(cutoff=CUT, start=START, end=END, beyond=()):
    blob = canonical(policy_dict(cutoff, start, end, beyond))
    return blob, occ.Pins(hashlib.sha256(blob).hexdigest(), len(blob))


def pack_of(document):
    blob = canonical(document)
    return blob, occ.Pins(hashlib.sha256(blob).hexdigest(), len(blob))


def trading_url(start=START, end=END):
    return f"{ENDPOINT}?dataset=TaiwanStockTradingDate&start_date={start}&end_date={end}"


def price_url(symbol, start=START, end=END):
    return f"{ENDPOINT}?dataset=TaiwanStockPrice&data_id={symbol}&start_date={start}&end_date={end}"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


JSON_TYPE = (("Content-Type", "application/json"),)


class Response:
    def __init__(self, body, *, declared=True, eof=True, clock=None, read_delay=0, status=200, headers=None,
                 close_raises=False):
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
    def __init__(self, bodies, *, response_options=None, clock=None, open_delay=0, fail_at=None, response_class=None):
        self.bodies = bodies
        self.response_options = response_options or {}
        self.clock, self.open_delay, self.fail_at = clock, open_delay, fail_at
        self.response_class = response_class or Response
        self.opens = []
        self.responses = []

    def open(self, url, timeout):
        index = len(self.opens)
        self.opens.append((url, timeout))
        if self.clock:
            self.clock.now += self.open_delay
        if index == self.fail_at:
            raise OSError("synthetic transport failure")
        response = self.response_class(self.bodies[index], **self.response_options.get(index, {}))
        self.responses.append(response)
        return response


def build(*, cutoff=CUT, start=START, end=END, beyond=(), variant=0, bodies=None, transport=None, clock=None,
          ledger=None, blob_pins=None, **kwargs):
    data = corpus(start, end, beyond, variant)
    blob, pins = blob_pins or policy_pack(cutoff, start, end, beyond)
    transport = transport or Transport(bodies if bodies is not None else data.bodies)
    clock = clock or Clock()
    source = occ.CloseSource(policy_canonical=blob, policy_sha256=pins.sha256, pins=pins, formal_blob=FORMAL,
                             transport=transport, ledger=ledger or occ.AttemptLedger(NAMESPACE), clock=clock, **kwargs)
    return source, transport, clock


def receipt_hash(receipt):
    return hashlib.sha256(canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)})).hexdigest()


def admission(source, *, cutoff=CUT, start=START, end=END, beyond=(), variant=0, **changes):
    data = corpus(start, end, beyond, variant)
    captures = source.inspection()["captures"]
    total = len(data.dates)
    proof = occ.OracleAdmission(
        NAMESPACE, source._pins.sha256, "synthetic-boundary-oracle", "a" * 40, "b" * 64,
        tuple(receipt_hash(capture.receipt) for capture in captures), total, 7 * total, 42 * total, 42,
        hashlib.sha256(data.closes_bytes(cutoff)).hexdigest(), True)
    return replace(proof, **changes) if changes else proof


def available(**kwargs):
    source, transport, clock = build(**kwargs)
    source.acquire()
    source.admit_independent_verification(admission(
        source, **{key: kwargs[key] for key in ("cutoff", "start", "end", "beyond", "variant") if key in kwargs}))
    return source, transport, clock


def declaration(holder=QA_HOLDER, model="claude-sonnet-5-5", url=SEAL_URL):
    binding = occ.ExecutionBinding(holder, holder, None, model, "xhigh", "a" * 40, "b" * 64, "c" * 64,
                                   "NOAUTH RAM pure guard; no financial execution")
    start = occ.FinancialStart("issue7-financial-start-v1", SEAL_ISSUER, SEAL_COORDINATORS, SEAL_IMPLEMENTERS,
                               NAMESPACE, policy_pack()[1].sha256, url, binding, True, True)
    return start, binding


# --- Response-shape replay: canned wire bytes -> real http.client parsing -> the real
# _HTTPSTransport.open / _HTTPSResponse / this module's _capture. Only socket and TLS are replaced.
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

        with patch.object(base.http.client, "HTTPSConnection", Connection), \
                patch.object(base.ssl, "create_default_context", lambda: object()):
            return base._HTTPSTransport().open(url, timeout)


def chunk_encode(body, size=61):
    out = b""
    for offset in range(0, len(body), size):
        part = body[offset:offset + size]
        out += b"%x\r\n" % len(part) + part + b"\r\n"
    return out + b"0\r\n\r\n"


def raw_http(headers, body=b"", *, status=200, reason="OK", version="1.1"):
    head = f"HTTP/{version} {status} {reason}\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers) + "\r\n"
    return head.encode("utf-8") + body


def finmind_wire(body, *, framing="length", content_type="application/json", extra=(), status=200, reason="OK",
                 content_encoding=None):
    headers = [("Date", "Mon, 12 Oct 2026 00:00:00 GMT"), ("Server", "synthetic"), ("Vary", "Accept-Encoding")]
    if content_type is not None:
        headers.append(("Content-Type", content_type))
    wire = body
    if framing == "length":
        headers.append(("Content-Length", str(len(body))))
    elif framing == "chunked":
        headers.append(("Transfer-Encoding", "chunked"))
        wire = chunk_encode(body)
    elif framing == "both":
        headers += [("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked")]
        wire = chunk_encode(body)
    if content_encoding is not None:
        headers.append(("Content-Encoding", content_encoding))
    return raw_http(headers + list(extra), wire, status=status, reason=reason)


_counter = [0]


def _cheap_roots(self, *stage_roots):
    """Stand-in outside the roots tests: the real per-row walk of the whole object graph costs seconds per acquisition."""
    self._roots_estimate = 0


class Case(unittest.TestCase):
    real_roots_tests = ()  # test methods that run the product's real retained-roots accounting

    def setUp(self):
        self.addCleanup(self._assert_no_residue)  # registered first, so it runs last
        if self._testMethodName not in self.real_roots_tests:
            patcher = patch.object(occ.CloseSource, "_check_roots", _cheap_roots)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _assert_no_residue(self):
        self.assertEqual(os.listdir(SESSION), [], "session directory must be empty after each test")

    def new_dir(self):
        _counter[0] += 1
        path = os.path.join(SESSION, "t%d" % _counter[0])
        os.mkdir(path)
        self.addCleanup(self._remove, path)
        return path

    def new_root(self):
        """A not-yet-existing private root below a fresh session subdirectory."""
        return os.path.join(self.new_dir(), "r")

    @staticmethod
    def _remove(path):
        if os.path.lexists(path):
            shutil.rmtree(path)

    def assertFailure(self, expected, function, *args, **kwargs):
        with self.assertRaises(occ.SourceError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def tree(self, root):
        """Sorted (relative path, size) listing of every file and directory below ``root``."""
        found = []
        for folder, names, files in os.walk(root):
            for name in names:
                found.append((os.path.relpath(os.path.join(folder, name), root), None))
            for name in files:
                full = os.path.join(folder, name)
                found.append((os.path.relpath(full, root), os.path.getsize(full)))
        return sorted(found)


class PolicyAndGates(Case):
    def test_import_is_inert_and_the_pins_are_the_published_policy_v1(self):
        self.assertEqual((occ.POLICY_SHA256, occ.POLICY_BYTES), (V1_SHA, V1_BYTES))
        self.assertEqual((occ.NAMESPACE, occ.POLICY_VERSION, occ.PURPOSE, occ.CONSUMER_VERSION),
                         (NAMESPACE, POLICY_VERSION, PURPOSE, CONSUMER))
        self.assertEqual((occ.STORAGE_SCHEMA, occ.RECEIPT_SCHEMA, occ.ROOT_ENV), (STORAGE_SCHEMA, RECEIPT_SCHEMA, ROOT_ENV))
        self.assertEqual(occ.SYMBOLS, SYMBOLS)
        self.assertEqual(list(occ.LIMITATIONS), LIMITATIONS)
        self.assertEqual(occ.SEAL_COMMENT_FLOOR, SEAL_FLOOR)
        self.assertEqual((occ.CLOSES_CAP, occ.RECEIPT_CAP, occ.MAX_BUNDLES, occ.MAX_FILES, occ.MAX_TOTAL_BYTES),
                         (65536, 32768, 2, 4, 196608))
        self.assertEqual(IMPORT_BLOCKED, ())  # the module was imported under the hook: no socket, write or process
        # The published policy text validates under the module's own default pins (no pins argument).
        policy = occ.validate_policy(V1_POLICY, V1_SHA)
        self.assertEqual(occ._policy_scope(policy), occ.Scope(CUT, START, END, ()))
        self.assertEqual(len(occ._POLICY_EXPECTED), 61)
        self.assertFailure("policy_pin", occ.validate_policy, V1_POLICY, "0" * 64)
        self.assertFailure("policy_canonical_mismatch", occ.validate_policy, V1_POLICY + b" ", V1_SHA)
        # If the pins were ever unset the module would still fail closed before anything else.
        for unset in (dict(POLICY_SHA256=None), dict(POLICY_BYTES=None), dict(POLICY_SHA256=None, POLICY_BYTES=None)):
            with patch.multiple(occ, **unset):
                self.assertFailure("real_pins_unset", occ.validate_policy, V1_POLICY, V1_SHA)
                self.assertFailure("real_pins_unset", occ.load_saved_closes, "C:\\none", POLICY_VERSION, CUT)
                self.assertFailure("real_pins_unset", occ.CloseSource, policy_canonical=V1_POLICY, policy_sha256=V1_SHA,
                                   formal_blob=FORMAL)

    def test_default_path_is_bound_to_policy_v1_and_still_refuses_without_a_valid_seal(self):
        blob, pins = policy_pack()
        self.assertEqual((blob, pins), (V1_POLICY, occ.Pins(V1_SHA, V1_BYTES)))
        # No seal at all: the real path stops at the financial-start gate, before any transport exists.
        self.assertFailure("financial_start_required", occ.CloseSource, policy_canonical=blob, policy_sha256=pins.sha256,
                           formal_blob=FORMAL)
        self.assertFailure("financial_start_required", occ.CloseSource, policy_canonical=blob, policy_sha256=pins.sha256,
                           formal_blob=FORMAL, transport=base._HTTPSTransport())
        # Caller pins can never reach the default HTTPS path.
        self.assertFailure("pins_with_default_transport", occ.CloseSource, policy_canonical=blob,
                           policy_sha256=pins.sha256, formal_blob=FORMAL, pins=pins)
        # Any other policy, even a well-formed one for another cutoff, is not the published one.
        other_blob, other_pins = policy_pack(cutoff="2026-10-05")
        self.assertFailure("policy_pin", occ.CloseSource, policy_canonical=other_blob, policy_sha256=other_pins.sha256,
                           formal_blob=FORMAL)
        self.assertFailure("policy_pin", occ.CloseSource, policy_canonical=blob, policy_sha256="0" * 64, formal_blob=FORMAL)
        # Typed but invalid or unauthorized seals are refused by the real constructor, gate by gate.
        start, binding = declaration()
        in_roles = replace(binding, holder_thread_id=SEAL_ISSUER, holder_session_id=SEAL_ISSUER)
        weak = replace(binding, reasoning_effort="ultra")
        floor_url = f"https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-{SEAL_FLOOR}"
        gates = [
            ("not_authorized", replace(start, authorized=False), binding, "financial_start_not_authorized"),
            ("not_whole_batch", replace(start, whole_batch=False), binding, "financial_start_not_authorized"),
            ("seal_at_floor", replace(start, seal_comment_url=floor_url), binding, "financial_new_explicit_seal_required"),
            ("seal_before_policy", replace(start, seal_comment_url=floor_url.replace(str(SEAL_FLOOR), "6124203633")), binding,
             "financial_new_explicit_seal_required"),
            ("seal_for_issue32", replace(start, seal_comment_url="https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999"),
             binding, "financial_new_explicit_seal_required"),
            ("namespace", replace(start, namespace=NAMESPACE + "x"), binding, "financial_start_scope"),
            ("seal_policy_pin", replace(start, policy_sha256="0" * 64), binding, "financial_start_scope"),
            ("issue32_seal_version", replace(start, version="issue32-financial-start-v1"), binding, "financial_start_scope"),
            ("runtime_differs_from_seal", start, replace(binding, candidate_sha="d" * 40), "financial_binding_mismatch"),
            ("qa_is_a_seal_role", replace(start, binding=in_roles), in_roles, "financial_qa_identity"),
            ("qa_effort", replace(start, binding=weak), weak, "financial_qa_identity"),
        ]
        for label, seal, runtime, code in gates:
            with self.subTest(gate=label):
                self.assertFailure(code, occ.CloseSource, policy_canonical=blob, policy_sha256=pins.sha256,
                                   formal_blob=FORMAL, financial_start=seal, execution_binding=runtime)
        # The synthetic declarations are never accepted together with a boundary transport.
        self.assertFailure("financial_start_with_boundary_transport", build, financial_start=start, execution_binding=binding)
        self.assertFailure("boundary_pins_required", occ.CloseSource, policy_canonical=blob, policy_sha256=pins.sha256,
                           formal_blob=FORMAL, transport=Transport([]), ledger=occ.AttemptLedger(NAMESPACE))
        for bad in (object(), (pins.sha256, pins.nbytes), "pins"):
            self.assertFailure("boundary_pins_required", occ.CloseSource, policy_canonical=blob, policy_sha256=pins.sha256,
                               formal_blob=FORMAL, pins=bad, transport=Transport([]), ledger=occ.AttemptLedger(NAMESPACE))
        for bad in (occ.Pins("x", 1), occ.Pins("0" * 64, 0), occ.Pins("0" * 64, True), occ.Pins("A" * 64, 5)):
            self.assertFailure("pins_type", occ.CloseSource, policy_canonical=blob, policy_sha256=pins.sha256,
                               formal_blob=FORMAL, pins=bad, transport=Transport([]), ledger=occ.AttemptLedger(NAMESPACE))

    def test_policy_shape_every_recursive_key_and_type(self):
        blob, pins = policy_pack()
        occ.validate_policy(blob, pins.sha256, pins)
        policy = policy_dict()
        nodes = []

        def visit(value):
            if isinstance(value, dict):
                nodes.append(value)
                for child in value.values():
                    visit(child)
        visit(policy)
        self.assertEqual(len(nodes), 11)
        for index in range(len(nodes)):
            for mode in ("extra", "missing"):
                mutated = copy.deepcopy(policy)
                cloned = []

                def collect(value):
                    if isinstance(value, dict):
                        cloned.append(value)
                        for child in value.values():
                            collect(child)
                collect(mutated)
                target = cloned[index]
                if mode == "extra":
                    target["unexpected"] = 1
                else:
                    del target[next(iter(target))]
                mutated_blob, mutated_pins = pack_of(mutated)
                self.assertFailure("policy_keys", occ.validate_policy, mutated_blob, mutated_pins.sha256, mutated_pins)
        for outer, key in (("acquisition", "redirects"), ("unit_policy", "scale"), ("acquisition", "max_gets"),
                           ("storage", "max_files"), ("window", "start_date")):
            wrong = (True, 1, 1.0, None, ["x"]) if type(policy[outer][key]) is str else (True, 1.0, "1", None, [1])
            for replacement in wrong:
                mutated = copy.deepcopy(policy)
                mutated[outer][key] = replacement
                mutated_blob, mutated_pins = pack_of(mutated)
                self.assertFailure("policy_type", occ.validate_policy, mutated_blob, mutated_pins.sha256, mutated_pins)
        for replacement in (1, "true", None):
            mutated = copy.deepcopy(policy)
            mutated["unit_policy"]["unit_mapping_inference"] = replacement
            mutated_blob, mutated_pins = pack_of(mutated)
            self.assertFailure("policy_type", occ.validate_policy, mutated_blob, mutated_pins.sha256, mutated_pins)
        for label, key in (("symbols", "symbols"), ("stored_fields", None), ("unsupported", "unsupported")):
            mutated = copy.deepcopy(policy)
            if label == "stored_fields":
                mutated["storage"]["stored_fields"].append("x")
            else:
                mutated[key].append("x")
            mutated_blob, mutated_pins = pack_of(mutated)
            self.assertFailure("policy_list", occ.validate_policy, mutated_blob, mutated_pins.sha256, mutated_pins)
        self.assertFailure("policy_pin", occ.validate_policy, blob, "0" * 64, pins)
        self.assertFailure("policy_pin", occ.validate_policy, blob, hashlib.sha256(b"x").hexdigest(), pins)
        self.assertFailure("policy_canonical_mismatch", occ.validate_policy, blob + b" ", pins.sha256, pins)
        self.assertFailure("policy_canonical_mismatch", occ.validate_policy, blob, pins.sha256, replace(pins, nbytes=pins.nbytes + 1))
        self.assertFailure("duplicate_json_key", occ.validate_policy, blob.replace(b"{", b'{"version":"dup",', 1), pins.sha256, pins)
        self.assertFailure("policy_encoding", occ.validate_policy, b"\xef\xbb\xbf" + blob, pins.sha256, pins)
        self.assertFailure("policy_input_type", occ.validate_policy, "text", pins.sha256, pins)
        self.assertFailure("policy_input_type", occ.validate_policy, blob, None, pins)
        # A policy of the old shape (no window / storage) is rejected under its own valid pin.
        old = copy.deepcopy(policy)
        del old["window"]
        del old["storage"]
        old["arithmetic"] = {"last60": "x"}
        old_blob, old_pins = pack_of(old)
        self.assertFailure("policy_keys", occ.validate_policy, old_blob, old_pins.sha256, old_pins)

    def test_policy_leaves_must_equal_the_module_behaviour(self):
        base_policy = policy_dict()
        paths = [path for path, _ in occ._POLICY_EXPECTED]
        self.assertGreaterEqual(len(paths), 55)
        for path in paths:
            mutated = copy.deepcopy(base_policy)
            node = mutated
            for key in path[:-1]:
                node = node[key]
            leaf = node[path[-1]]
            if isinstance(leaf, bool):
                node[path[-1]] = not leaf
            elif isinstance(leaf, int):
                node[path[-1]] = leaf + 1
            elif isinstance(leaf, list):
                node[path[-1]] = ["x"] + leaf[1:]
            else:
                node[path[-1]] = leaf + "x"
            blob, pins = pack_of(mutated)
            with self.subTest(field=".".join(path)):
                error = self.assertFailure("policy_value", build, blob_pins=(blob, pins))
                self.assertEqual(error.diagnostics["field"], ".".join(path))
        window_cases = {
            "cutoff_not_after_start": policy_dict(cutoff="2026-07-01"),
            "cutoff_after_end": policy_dict(cutoff="2026-10-07"),
            "end_before_identity": policy_dict(cutoff="2026-10-05", end="2026-10-05"),
            "cutoff_not_iso": {**policy_dict(), "cutoff": "20261006"},
        }
        for label, document in window_cases.items():
            blob, pins = pack_of(document)
            code = "policy_cutoff" if label == "cutoff_not_iso" else "policy_window"
            with self.subTest(case=label):
                self.assertFailure(code, build, blob_pins=(blob, pins))
        for label, beyond, end in (("weekend", ("2026-10-10",), "2026-10-10"), ("descending", ("2026-10-08", "2026-10-07"), "2026-10-09"),
                                   ("duplicate", ("2026-10-07", "2026-10-07"), "2026-10-09"), ("not_after_identity", ("2026-10-06",), "2026-10-09"),
                                   ("after_end", ("2026-10-12",), "2026-10-09"), ("declared_with_equal_end", ("2026-10-07",), "2026-10-06")):
            blob, pins = pack_of(policy_dict(end=end, beyond=beyond))
            with self.subTest(beyond=label):
                self.assertFailure("policy_beyond", build, blob_pins=(blob, pins))
        document = policy_dict(end="2026-10-09", beyond=BEYOND)
        document["price_source"]["end_date"] = "2026-10-08"
        blob, pins = pack_of(document)
        self.assertEqual(self.assertFailure("policy_value", build, blob_pins=(blob, pins)).diagnostics["field"], "price_source.end_date")
        document = policy_dict(end="2026-10-09", beyond=BEYOND)
        document["trading_date_source"]["url"] = trading_url(START, "2026-10-06")
        blob, pins = pack_of(document)
        self.assertEqual(self.assertFailure("policy_value", build, blob_pins=(blob, pins)).diagnostics["field"], "trading_date_source.url")
        for label, change in (("attribution_empty", lambda d: d.update(attribution="")),
                              ("attribution_long", lambda d: d.update(attribution="a" * 513)),
                              ("rights_empty", lambda d: d["price_source"].update(rights="")),
                              ("trading_rights_long", lambda d: d["trading_date_source"].update(rights="r" * 513)),
                              ("trading_version_bad", lambda d: d["trading_date_source"].update(version="bad version"))):
            document = policy_dict()
            change(document)
            blob, pins = pack_of(document)
            with self.subTest(case=label):
                self.assertFailure("policy_value", build, blob_pins=(blob, pins))
        for required in occ.REQUIRED_UNSUPPORTED:
            document = policy_dict()
            document["unsupported"][document["unsupported"].index(required)] = "other_" + required
            blob, pins = pack_of(document)
            with self.subTest(required=required):
                self.assertEqual(self.assertFailure("policy_value", build, blob_pins=(blob, pins)).diagnostics["field"], "unsupported")

    def test_scope_must_start_before_the_formal_span(self):
        for start in ("2026-08-04", "2026-09-01", "2026-09-30"):
            blob, pins = policy_pack(start=start)
            with self.subTest(start=start):
                self.assertFailure("scope_formal_coverage", build, start=start, blob_pins=(blob, pins))
        with patch.object(base, "_formal_reference", return_value=(PRIOR[:-1], {})):
            self.assertFailure("scope_formal_coverage", build)

    def test_unsupported_purpose_and_constructor_arguments_before_transport(self):
        for purpose in occ.REQUIRED_UNSUPPORTED + ("strategy", "storage", "random", None, "", PURPOSE + " "):
            transport = Transport([])
            self.assertFailure("unsupported_purpose", build, transport=transport, purpose=purpose)
            self.assertEqual(transport.opens, [])
        self.assertFailure("formal_blob_pin", occ.CloseSource, policy_canonical=policy_pack()[0],
                           policy_sha256=policy_pack()[1].sha256, pins=policy_pack()[1], formal_blob=FORMAL + b" ",
                           transport=Transport([]), ledger=occ.AttemptLedger(NAMESPACE))
        for lease in (0, -1, 181, float("nan"), float("inf"), "5", None):
            self.assertFailure("lease_seconds", build, lease_seconds=lease)
        self.assertFailure("clock_or_roots_type", build, clock=5)
        self.assertFailure("clock_or_roots_type", build, observer_roots=5)
        self.assertFailure("boundary_ledger_required", occ.CloseSource, policy_canonical=policy_pack()[0],
                           policy_sha256=policy_pack()[1].sha256, pins=policy_pack()[1], formal_blob=FORMAL,
                           transport=Transport([]))
        self.assertFailure("boundary_ledger_required", build, ledger=base.AttemptLedger("issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2"))

    def test_financial_start_pure_guards(self):
        pins = policy_pack()[1]
        start, binding = declaration(model="gpt-6.1-sol")
        self.assertIsNone(occ._financial_start(start, binding, pins))
        for model in ("claude-sonnet-5-5", "claude-opus-5-5", "gpt-6.1-sol"):
            with self.subTest(case="runtime_model_is_read_back", model=model):
                self.assertIsNone(occ._financial_start(*declaration(model=model), pins))
        start, binding = declaration()
        for holder in (SEAL_ISSUER,) + SEAL_COORDINATORS + SEAL_IMPLEMENTERS:
            with self.subTest(case="qa_not_independent_of_seal_role", holder=holder):
                self.assertFailure("financial_qa_identity", occ._financial_start, *declaration(holder=holder), pins)
        for label, role in (
                ("issuer_is_coordinator", {"issuer_thread_id": SEAL_COORDINATORS[0]}),
                ("issuer_is_implementer", {"issuer_thread_id": SEAL_IMPLEMENTERS[0]}),
                ("coordinator_is_implementer", {"coordinator_session_ids": (SEAL_IMPLEMENTERS[0],)}),
                ("duplicate_implementer", {"implementer_session_ids": (SEAL_IMPLEMENTERS[0], SEAL_IMPLEMENTERS[0])}),
                ("issuer_malformed", {"issuer_thread_id": "not-a-session-id"}),
                ("coordinator_uppercase", {"coordinator_session_ids": (SEAL_COORDINATORS[0].upper(),)}),
                ("implementer_malformed", {"implementer_session_ids": ("x",)})):
            with self.subTest(case=label):
                self.assertFailure("financial_start_scope", occ._financial_start, replace(start, **role), binding, pins)
        for label, role in (
                ("coordinators_empty", {"coordinator_session_ids": ()}),
                ("implementers_empty", {"implementer_session_ids": ()}),
                ("coordinators_list", {"coordinator_session_ids": list(SEAL_COORDINATORS)}),
                ("implementers_non_str", {"implementer_session_ids": (SEAL_IMPLEMENTERS[0], 1)}),
                ("issuer_non_str", {"issuer_thread_id": None})):
            with self.subTest(case=label):
                self.assertFailure("financial_start_type", occ._financial_start, replace(start, **role), binding, pins)
        for label, url, code in (
                ("seal_at_floor", f"https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-{SEAL_FLOOR}", "financial_new_explicit_seal_required"),
                ("seal_before_floor", f"https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-{SEAL_FLOOR - 1}", "financial_new_explicit_seal_required"),
                ("seal_issue32", "https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-9999999999", "financial_new_explicit_seal_required"),
                ("seal_other_issue", "https://github.com/YiCheng0608/stock-lab/issues/8#issuecomment-9999999999", "financial_new_explicit_seal_required"),
                ("seal_not_url", "6124203634", "financial_new_explicit_seal_required"),
                ("seal_after_floor", f"https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-{SEAL_FLOOR + 1}", None)):
            with self.subTest(case=label):
                if code is None:
                    self.assertIsNone(occ._financial_start(*declaration(url=url), pins))
                else:
                    self.assertFailure(code, occ._financial_start, *declaration(url=url), pins)
        cases = (
            ("start_type", None, binding, "financial_start_required"),
            ("binding_type", start, None, "financial_start_required"),
            ("issue32_start_class_instance", start, object(), "financial_start_required"),
            ("seal_binding_type", replace(start, binding=None), binding, "financial_binding_type"),
            ("authorized_bool", replace(start, authorized=1), binding, "financial_start_not_authorized"),
            ("authorized_false", replace(start, authorized=False), binding, "financial_start_not_authorized"),
            ("whole_batch_bool", replace(start, whole_batch=1), binding, "financial_start_not_authorized"),
            ("whole_batch_false", replace(start, whole_batch=False), binding, "financial_start_not_authorized"),
            ("version_issue32", replace(start, version="issue32-financial-start-v1"), binding, "financial_start_scope"),
            ("namespace", replace(start, namespace="other"), binding, "financial_start_scope"),
            ("namespace_issue32", replace(start, namespace="issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2"), binding, "financial_start_scope"),
            ("policy_pin", replace(start, policy_sha256="0" * 64), binding, "financial_start_scope"),
            ("candidate_mismatch", start, replace(binding, candidate_sha="d" * 40), "financial_binding_mismatch"),
            ("script_mismatch", start, replace(binding, script_sha256="e" * 64), "financial_binding_mismatch"),
        )
        for label, seal, runtime, code in cases:
            with self.subTest(case=label):
                self.assertFailure(code, occ._financial_start, seal, runtime, pins)
        for label, runtime, code in (
                ("not_top_level", replace(binding, parent_thread_id=SEAL_ISSUER), "financial_qa_not_top_level"),
                ("session_mismatch", replace(binding, holder_session_id=SEAL_ISSUER), "financial_qa_identity"),
                ("holder_malformed", replace(binding, holder_thread_id="NOT-A-SESSION", holder_session_id="NOT-A-SESSION"), "financial_qa_identity"),
                ("holder_uppercase", replace(binding, holder_thread_id=QA_HOLDER.upper(), holder_session_id=QA_HOLDER.upper()), "financial_qa_identity"),
                ("model_shape", replace(binding, model="bad model"), "financial_qa_identity"),
                ("model_too_long", replace(binding, model="m" * 65), "financial_qa_identity"),
                ("model_empty", replace(binding, model=""), "financial_binding_type"),
                ("effort", replace(binding, reasoning_effort="ultra"), "financial_qa_identity"),
                ("effort_medium", replace(binding, reasoning_effort="medium"), "financial_qa_identity"),
                ("candidate_short", replace(binding, candidate_sha="a" * 39), "financial_candidate"),
                ("loaded_source_short", replace(binding, loaded_source_sha256="b" * 63), "financial_script_binding"),
                ("script_uppercase", replace(binding, script_sha256="C" * 64), "financial_script_binding")):
            with self.subTest(case=label):
                self.assertFailure(code, occ._financial_start, replace(start, binding=runtime), runtime, pins)



class PublishedPolicy(Case):
    """The published policy v1, its pins and a full synthetic run under the module's own default pins."""

    def test_literal_is_the_published_policy_and_states_what_the_module_implements(self):
        self.assertEqual((len(V1_POLICY), hashlib.sha256(V1_POLICY).hexdigest()), (5173, V1_SHA))
        self.assertFalse(V1_POLICY.endswith(chr(10).encode()))
        document = json.loads(V1_POLICY)
        self.assertEqual(canonical(document), V1_POLICY)
        self.assertEqual((document["version"], document["acquisition"]["namespace"], document["source_use"],
                          document["consumer_version"]), (POLICY_VERSION, NAMESPACE, PURPOSE, CONSUMER))
        self.assertEqual((document["cutoff"], document["window"]), (CUT, {"start_date": START, "end_date": END,
                                                                         "beyond_formal_trading_dates": []}))
        self.assertEqual(document["trading_date_source"]["url"], trading_url())
        self.assertEqual(document["price_source"]["endpoint"], ENDPOINT)
        self.assertEqual((document["acquisition"]["user_agent"], document["acquisition"]["accept"],
                          document["acquisition"]["max_gets"], document["acquisition"]["redirects"],
                          document["acquisition"]["retries"]), ("stock-lab-issue32-local-ram/1", "application/json", 8, 0, 0))
        self.assertEqual((document["price_source"]["rights"], document["trading_date_source"]["rights"], document["attribution"]),
                         (RIGHTS, RIGHTS, ATTRIBUTION))
        self.assertEqual(document["unsupported"], UNSUPPORTED)
        self.assertEqual(document["storage"]["stored_fields"], ["date", "close"])
        self.assertEqual(document["storage"]["raw_body"], "not_stored")
        self.assertEqual((occ.POLICY_SHA256, occ.POLICY_BYTES, occ.SEAL_COMMENT_FLOOR), (V1_SHA, V1_BYTES, SEAL_FLOOR))
        self.assertGreater(SEAL_FLOOR, 6124203633)

    def test_full_synthetic_run_under_the_published_policy_uses_only_the_modules_own_pins(self):
        source, transport, _ = available()
        self.addCleanup(source.release)
        self.assertEqual(source._pins, occ.Pins(occ.POLICY_SHA256, occ.POLICY_BYTES))
        root = self.new_root()
        result = source.save(environment={ROOT_ENV: root})
        loaded = occ.load_saved_closes(root, POLICY_VERSION, CUT)  # no pins argument
        self.assertEqual(loaded.closes_sha256, result.closes_sha256)
        self.assertEqual(dict(loaded.receipt["source_policy"]), {"version": POLICY_VERSION, "sha256": V1_SHA, "bytes": V1_BYTES})
        self.assertEqual({entry["policy_sha256"] for entry in loaded.receipt["gets"]}, {V1_SHA})
        self.assertEqual(loaded.receipt["namespace"], NAMESPACE)
        self.assertEqual(len(transport.opens), 8)
        # A bundle made under any other policy text is not readable with the module's pins.
        other, _, _ = available(cutoff="2026-10-05")
        self.addCleanup(other.release)
        other_root = self.new_root()
        other.save(environment={ROOT_ENV: other_root})
        self.assertFailure("saved_pin_or_scope", occ.load_saved_closes, other_root, POLICY_VERSION, "2026-10-05")


class Calendar(Case):
    def test_trading_date_document_gate_stops_before_any_price_get(self):
        all_dates = DATES
        base_document = json.loads(trading_body(all_dates))

        def mutate(change):
            document = copy.deepcopy(base_document)
            change(document)
            return json.dumps(document, separators=(",", ":")).encode("utf8")

        def dates_body(dates):
            return trading_body(tuple(sorted(dates)))

        variants = [
            ("not_json", b"<html>blocked</html>", "transport_or_parse_failure"),
            ("utf8_bom", b"\xef\xbb\xbf" + trading_body(all_dates), "transport_or_parse_failure"),
            ("invalid_utf8", b"\xff" + trading_body(all_dates), "transport_or_parse_failure"),
            ("nonfinite", trading_body(all_dates).replace(b'"status":200', b'"status":NaN'), "nonfinite_json_number"),
            ("duplicate_key", trading_body(all_dates).replace(b'{"msg"', b'{"msg":"x","msg"', 1), "duplicate_json_key"),
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
            ("cutoff_missing", dates_body(set(all_dates) - {CUT}), "trading_dates_cutoff"),
            ("window_insufficient_14_july_days", trading_body(JULY[:14] + PRIOR), "trading_dates_window_insufficient"),
            ("formal_day_missing", dates_body(set(all_dates) - {"2026-09-01"}), "trading_dates_formal_mismatch"),
            ("formal_closed_day_present", dates_body(set(all_dates) | {"2026-09-25"}), "trading_dates_formal_mismatch"),
            ("day_after_formal_undeclared", dates_body(set(all_dates) | {"2026-10-07"}), "trading_dates_cutoff"),
        ]
        # The last case: the window ends on the identity day, so 10/07 is outside and simply discarded.
        for label, raw, code in variants:
            data = corpus()
            bodies = [raw] + data.bodies[1:]
            with self.subTest(case=label):
                source, transport, _ = build(bodies=bodies)
                if label == "day_after_formal_undeclared":
                    source.acquire()  # outside the window: structurally valid and discarded
                    self.assertEqual(source.state, "pending")
                    source.release()
                    continue
                self.assertFailure(code, source.acquire)
                self.assertEqual(source.state, "failed")
                self.assertEqual(source.ledger.attempted, (0,))
                self.assertEqual(source.ledger.unrun, tuple(range(1, 8)))
                self.assertEqual(len(transport.opens), 1)  # no price GET after a bad trading-date document
                self.assertTrue(transport.responses[0].closed)
                self.assertEqual(source._capture_buffer, b"")
                self.assertEqual(len(source.inspection()["captures"]), 1)
                self.assertEqual(transport.opens[0][0], trading_url())

    def test_cutoff_is_parameterized_and_saved_window_is_exactly_the_independent_expectation(self):
        cases = [
            ("formal_end_cutoff", dict(cutoff="2026-10-06")),
            ("earlier_cutoff_same_window", dict(cutoff="2026-10-05")),
            ("much_earlier_cutoff", dict(cutoff="2026-10-02")),
            ("beyond_formal_cutoff_middle", dict(cutoff="2026-10-08", end="2026-10-09", beyond=BEYOND)),
            ("beyond_formal_cutoff_last", dict(cutoff="2026-10-09", end="2026-10-09", beyond=BEYOND)),
            ("beyond_formal_cutoff_first", dict(cutoff="2026-10-07", end="2026-10-07", beyond=BEYOND[:1])),
            ("cutoff_on_identity_with_later_declared_days", dict(cutoff="2026-10-06", end="2026-10-09", beyond=BEYOND)),
        ]
        for label, kwargs in cases:
            with self.subTest(case=label):
                data = corpus(kwargs.get("start", START), kwargs.get("end", END), kwargs.get("beyond", ()))
                source, transport, _ = build(**kwargs)
                source.acquire()
                self.assertEqual(source.state, "pending")
                cutoff = kwargs["cutoff"]
                expected = data.closes_bytes(cutoff)
                self.assertEqual(source.inspection()["closes_bytes"], expected)
                document = json.loads(expected)
                self.assertEqual((document["trading_dates"][-1], len(document["trading_dates"])), (cutoff, 60))
                self.assertEqual(source.inspection()["dates"], data.dates)
                self.assertEqual(source.inspection()["scope"].cutoff, cutoff)
                start = kwargs.get("start", START)
                end = kwargs.get("end", END)
                self.assertEqual([url for url, _ in transport.opens],
                                 [trading_url(start, end)] + [price_url(symbol, start, end) for symbol in SYMBOLS])
                # Bars after the cutoff are fetched but never enter the saved window.
                self.assertTrue(all(day <= cutoff for day in document["trading_dates"]))
                source.admit_independent_verification(admission(source, **kwargs))
                source.release()

    def test_days_after_the_formal_coverage_must_equal_the_declared_set_exactly(self):
        kwargs = dict(cutoff="2026-10-08", end="2026-10-09", beyond=BEYOND)
        full = calendar(START, "2026-10-09", BEYOND)
        base_document = json.loads(trading_body(full))
        data = corpus(START, "2026-10-09", BEYOND)

        def run(dates, extra_rows=(), **override):
            options = {**kwargs, **override}
            bodies = [trading_body(dates, extra_rows)] + data.bodies[1:]
            return build(bodies=bodies, **options)

        cases = [
            ("declared_day_missing", tuple(day for day in full if day != "2026-10-09"), "trading_dates_beyond_formal_mismatch"),
            ("cutoff_day_missing", tuple(day for day in full if day != "2026-10-08"), "trading_dates_cutoff"),
            ("first_declared_missing", tuple(day for day in full if day != "2026-10-07"), "trading_dates_beyond_formal_mismatch"),
            ("formal_day_missing", tuple(day for day in full if day != "2026-09-02"), "trading_dates_formal_mismatch"),
            ("weekend_day_in_window", tuple(sorted(set(full) | {"2026-10-03"})), "trading_dates_weekday"),
        ]
        for label, dates, code in cases:
            with self.subTest(case=label):
                source, transport, _ = run(dates)
                self.assertFailure(code, source.acquire)
                self.assertEqual(len(transport.opens), 1)
        # An undeclared extra day INSIDE the window is a mismatch; the same day OUTSIDE it is discarded.
        undeclared = policy_pack(cutoff="2026-10-06", end="2026-10-09", beyond=BEYOND[:2])
        source, transport, _ = build(cutoff="2026-10-06", end="2026-10-09", beyond=BEYOND[:2], blob_pins=undeclared,
                                     bodies=[trading_body(full)] + data.bodies[1:])
        self.assertFailure("trading_dates_beyond_formal_mismatch", source.acquire)
        outside = run(full, extra_rows=[{"date": "2026-10-12"}, {"date": "2026-10-13"}])
        outside[0].acquire()
        self.assertEqual(outside[0].state, "pending")
        outside[0].release()
        # A window that ends on the identity day declares nothing, so FinMind returning later days there is discarded.
        source, transport, _ = build(cutoff="2026-10-06", bodies=[trading_body(full)] + corpus().bodies[1:])
        source.acquire()
        self.assertEqual(source.state, "pending")
        source.release()
        self.assertEqual(base_document["status"], 200)

    def test_parameterized_calendar_gate_is_equivalent_to_issue32_on_its_original_window(self):
        """E1: replay issue 32's own window (2026-07-01..2026-10-06, cutoffs 10/05 and 10/06) through both gates."""
        rank = {"trading_dates_weekday": 1, "trading_dates_cutoff": 2, "trading_dates_window_insufficient": 3,
                "trading_dates_formal_mismatch": 4}
        prior = base._formal_reference(FORMAL)[0]
        self.assertEqual(prior, PRIOR)

        def original(document):
            try:
                dates = base._trading_dates(document)
                base._check_trading_dates(dates, prior)
            except base.SourceError as error:
                return "fail", error.code
            return "ok", dates

        def parameterized(document):
            try:
                dates = occ._trading_dates(document, occ.Scope(CUT, START, END, ()))
            except occ.SourceError as error:
                return "fail", error.code
            failures = []
            for cutoff in ("2026-10-05", "2026-10-06"):
                try:
                    occ._check_calendar(dates, occ.Scope(cutoff, START, END, ()), prior)
                except occ.SourceError as error:
                    failures.append(error.code)
            # Issue 32 judges both cutoffs in one pass, so its code is the earliest-stage failure of either cutoff.
            return ("fail", min(failures, key=rank.__getitem__)) if failures else ("ok", dates)

        def doc(dates, extra=()):
            return {"msg": "success", "status": 200, "data": [{"date": day} for day in dates] + list(extra)}

        documents = [("base", doc(DATES))]
        for day in PRIOR:
            documents.append(("missing_" + day, doc([d for d in DATES if d != day])))
        for day in ("2026-09-25", "2026-09-28", "2026-07-04", "2026-07-11", "2026-08-01", "2026-10-03", "2026-09-26", "2026-07-10"):
            documents.append(("added_" + day, doc(sorted(set(DATES) | {day}))))
        for removed in (("2026-10-05",), ("2026-10-06",), ("2026-10-02",), ("2026-10-05", "2026-10-06"), ("2026-07-13",)):
            documents.append(("removed_" + "_".join(removed), doc([d for d in DATES if d not in removed])))
        for count in range(0, 24):
            documents.append((f"july_head_{count}", doc(JULY[:count] + PRIOR)))
            documents.append((f"july_tail_{count}", doc((JULY[-count:] if count else ()) + PRIOR)))
        documents += [
            ("outside_rows_discarded", doc(("2005-01-03",) + DATES + ("2026-10-07", "2026-10-08", "2027-01-04"))),
            ("only_outside_rows", doc(("2005-01-03", "2005-01-04"))),
            ("status_402", {**doc(DATES), "status": 402}), ("msg_ok", {**doc(DATES), "msg": "ok"}),
            ("data_empty", {**doc(DATES), "data": []}), ("data_object", {**doc(DATES), "data": {}}),
            ("extra_top_key", {**doc(DATES), "extra": 1}), ("missing_top_key", {"status": 200, "data": []}),
            ("row_extra_key", doc(DATES[:3], extra=[{"date": "2026-07-06", "x": 1}])),
            ("row_not_dict", {**doc(DATES), "data": ["2026-07-01"] + doc(DATES)["data"]}),
            ("bad_date_outside", doc(("2005-01-03",) + DATES, extra=[{"date": "2026-10-32"}])),
            ("unsorted", doc(("2026-07-02", "2026-07-01") + DATES[2:])),
            ("duplicate", doc(DATES[:5] + DATES[4:])),
            ("unsorted_outside", doc(("2005-01-04", "2005-01-03") + DATES)),
        ]
        outcomes = {}
        for name, document in documents:
            with self.subTest(document=name):
                self.assertEqual(parameterized(copy.deepcopy(document)), original(copy.deepcopy(document)))
            outcomes[name] = original(copy.deepcopy(document))
        codes = {code for kind, code in outcomes.values() if kind == "fail"}
        self.assertTrue({"trading_dates_weekday", "trading_dates_cutoff", "trading_dates_window_insufficient",
                         "trading_dates_formal_mismatch", "trading_dates_order", "trading_dates_status",
                         "trading_dates_document", "trading_dates_rows", "trading_dates_row", "trading_dates_date"} <= codes, codes)
        passing = [name for name, (kind, _) in outcomes.items() if kind == "ok"]
        self.assertIn("base", passing)
        self.assertIn("outside_rows_discarded", passing)
        self.assertGreaterEqual(len(documents), 120)


class Prices(Case):
    def run_price_case(self, mutator, index=3, **options):
        data = corpus()
        documents = copy.deepcopy(data.documents)
        raw = mutator(documents[index])
        bodies = list(data.bodies)
        bodies[index + 1] = raw if isinstance(raw, bytes) else price_body(documents[index])
        source, transport, _ = build(bodies=bodies, **options)
        return source, transport, index

    def test_price_document_gates_stop_the_whole_batch_at_the_first_bad_symbol(self):
        def row(document, position=5):
            return document["data"][position]

        cases = [
            ("row_dropped", lambda d: d["data"].pop(0), "price_row_count"),
            ("row_added", lambda d: d["data"].append(copy.deepcopy(d["data"][-1])), "price_row_count"),
            ("wrong_stock_id", lambda d: row(d).update(stock_id="9999"), "price_stock_id"),
            ("stock_id_int", lambda d: row(d).update(stock_id=5347), "price_stock_id"),
            ("duplicate_date", lambda d: row(d).update(date=row(d, 4)["date"]), "price_duplicate_or_calendar"),
            ("date_off_calendar", lambda d: row(d).update(date="2026-07-04"), "price_duplicate_or_calendar"),
            ("date_slash", lambda d: row(d).update(date="2026/07/08"), "price_date"),
            ("missing_field", lambda d: row(d).pop("max"), "price_row_fields"),
            ("extra_field", lambda d: row(d).update(unexpected=1), "price_row_fields"),
            ("status_500", lambda d: d.update(status=500), "price_document_status"),
            ("document_extra_key", lambda d: d.update(extra=1), "price_document"),
            ("close_string", lambda d: row(d).update(close="100"), "price_number_type"),
            ("close_zero", lambda d: row(d).update(close=0), "nonpositive_price"),
            ("open_negative", lambda d: row(d).update(open=-1), "nonpositive_price"),
            ("bounds_high_below_close", lambda d: row(d).update(max=row(d)["close"] - 1), "ohlc_bounds"),
            ("bounds_low_above_open", lambda d: row(d).update(min=row(d)["open"] + 1), "ohlc_bounds"),
            ("volume_float", lambda d: row(d).update(Trading_Volume=1.5), "canonical_int64"),
            ("volume_zero", lambda d: row(d).update(Trading_Volume=0), "canonical_int64"),
            ("amount_over_int64", lambda d: row(d).update(Trading_money=9223372036854775808), "canonical_int64"),
            ("spread_string", lambda d: row(d).update(spread="x"), "price_number_type"),
            ("turnover_negative", lambda d: row(d).update(Trading_turnover=-1), "canonical_int64"),
            ("anchor_close_off_by_one", lambda d: (d["data"][-1].update(close=d["data"][-1]["close"] + 1,
                                                                        max=d["data"][-1]["max"] + 1), None)[1],
             "latest_anchor_mismatch"),
            ("anchor_volume_off_by_one", lambda d: d["data"][-1].update(Trading_Volume=d["data"][-1]["Trading_Volume"] + 1),
             "latest_anchor_mismatch"),
            ("anchor_amount_off_by_one", lambda d: d["data"][-1].update(Trading_money=d["data"][-1]["Trading_money"] + 1),
             "latest_anchor_mismatch"),
            ("nan_value", lambda d: price_body(d).replace(b'"spread":-1', b'"spread":NaN', 1), "nonfinite_json_number"),
            ("duplicate_json_key", lambda d: price_body(d).replace(b'{"date"', b'{"date":"x","date"', 1), "duplicate_json_key"),
            ("not_json", lambda d: b"<html>blocked</html>", "transport_or_parse_failure"),
            ("invalid_utf8", lambda d: b"\xff" + price_body(d), "transport_or_parse_failure"),
        ]
        for index in (0, 3, 6):
            for label, mutator, code in cases:
                if index != 3 and label not in ("row_dropped", "anchor_close_off_by_one", "close_zero"):
                    continue
                with self.subTest(case=label, symbol=SYMBOLS[index]):
                    source, transport, position = self.run_price_case(mutator, index)
                    self.assertFailure(code, source.acquire)
                    self.assertEqual(source.state, "failed")
                    self.assertEqual(source.ledger.attempted, tuple(range(position + 2)))
                    self.assertEqual(source.ledger.unrun, tuple(range(position + 2, 8)))
                    self.assertEqual(len(transport.opens), position + 2)  # stop on first failure, no retry, no later GET
                    self.assertTrue(all(response.closed for response in transport.responses))
                    self.assertEqual(source.inspection()["closes_bytes"], b"")  # nothing is derived from a failed batch
                    self.assertEqual(source._capture_buffer, b"")

    def test_identity_day_must_be_present_exactly_once_for_the_anchor_check(self):
        real = base._prices

        def without_identity(*args, **kwargs):
            return tuple(bar for bar in real(*args, **kwargs) if bar.date != FORMAL_END)

        def doubled(*args, **kwargs):
            bars = real(*args, **kwargs)
            return bars + tuple(bar for bar in bars if bar.date == FORMAL_END)
        for label, replacement in (("missing", without_identity), ("duplicated", doubled)):
            with self.subTest(case=label), patch.object(base, "_prices", replacement):
                source, transport, _ = build()
                self.assertFailure("latest_anchor_mismatch", source.acquire)
                self.assertEqual(source.state, "failed")
                self.assertEqual(len(transport.opens), 2)

    def test_closes_document_over_its_cap_rejects_the_batch_before_it_can_be_pending(self):
        with patch.object(occ, "CLOSES_CAP", 100):
            source, transport, _ = build()
            self.assertFailure("closes_cap", source.acquire)
        self.assertEqual((source.state, len(transport.opens)), ("failed", 8))
        self.assertEqual(source.inspection()["closes_bytes"], b"")
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, admission(source))

    def test_numbers_that_cannot_be_saved_as_exact_decimal_text_reject_the_batch(self):
        for label, literal, code, expected in (
                ("seven_decimals", "100.1234567", "close_representation", None),
                ("fourteen_integer_digits", "12345678901234.5", "close_representation", None),
                ("exponent_form_when_exact", "1E+2", None, "100"),
                ("trailing_zero_form_when_exact", "100.50", None, "100.5"),
                ("six_decimals", "100.000001", None, "100.000001")):
            data = corpus()
            documents = copy.deepcopy(data.documents)
            # Third from last: inside the 60-day window and not the identity day; keep the OHLC bounds valid.
            documents[0]["data"][-3].update(open=1, max=10 ** 15, min=1, close=1)
            raw = price_body(documents[0])
            self.assertEqual(raw.count(b'"close":1,'), 1)
            bodies = list(data.bodies)
            bodies[1] = raw.replace(b'"close":1,', b'"close":' + literal.encode() + b",", 1)
            with self.subTest(case=label):
                source, transport, _ = build(bodies=bodies)
                if code is None:
                    source.acquire()
                    saved = json.loads(source.inspection()["closes_bytes"])
                    self.assertEqual(saved["closes"]["3105"][-3][1], expected)
                    source.release()
                else:
                    self.assertFailure(code, source.acquire)
                    self.assertEqual(source.state, "failed")


class Acquisition(Case):
    real_roots_tests = ("test_retained_roots_cap_fails_closed_before_and_during_acquisition",
                        "test_pending_until_independent_admission_binds_receipts_and_closes")

    def assertCaptureFailure(self, code, *, index=0, options=None, bodies=None, **kwargs):
        source, transport, _ = build(transport=Transport(bodies if bodies is not None else corpus().bodies,
                                                         response_options={index: options or {}}), **kwargs)
        error = self.assertFailure(code, source.acquire)
        self.assertEqual(source.state, "failed")
        self.assertEqual(source.ledger.attempted, tuple(range(index + 1)))
        self.assertEqual(len(transport.opens), index + 1)
        self.assertTrue(all(response.closed for response in transport.responses))
        self.assertEqual(source._capture_buffer, b"")
        return source, error

    def test_http_framing_and_body_boundaries_fail_the_whole_batch(self):
        body = corpus().bodies[0]
        length = (("Content-Length", str(len(body))),)
        cases = [
            ("status_401", {"status": 401}, "http_status"), ("status_402", {"status": 402}, "http_status"),
            ("status_403", {"status": 403}, "http_status"), ("status_404", {"status": 404}, "http_status"),
            ("status_500", {"status": 500}, "http_status"), ("status_301", {"status": 301}, "http_status"),
            ("status_bool", {"status": True}, "http_status"),
            ("gzip", {"headers": length + JSON_TYPE + (("Content-Encoding", "gzip"),)}, "content_encoding"),
            ("br", {"headers": length + JSON_TYPE + (("content-encoding", "br"),)}, "content_encoding"),
            ("duplicate_length", {"headers": length + length + JSON_TYPE}, "duplicate_framing_header"),
            ("duplicate_type", {"headers": length + JSON_TYPE + JSON_TYPE}, "duplicate_framing_header"),
            ("duplicate_encoding", {"headers": length + JSON_TYPE + (("Content-Encoding", "identity"), ("content-encoding", "identity"))}, "duplicate_framing_header"),
            ("length_plus_sign", {"headers": (("Content-Length", "+5"),) + JSON_TYPE}, "content_length"),
            ("length_leading_zero", {"headers": (("Content-Length", "05"),) + JSON_TYPE}, "content_length"),
            ("length_text", {"headers": (("Content-Length", "five"),) + JSON_TYPE}, "content_length"),
            ("declared_over_body_cap", {"headers": (("Content-Length", str(base.BODY_CAP + 1)),) + JSON_TYPE}, "declared_body_cap"),
            ("chunked_and_length", {"headers": length + (("Transfer-Encoding", "chunked"),) + JSON_TYPE}, "ambiguous_framing"),
            ("transfer_gzip", {"headers": (("Transfer-Encoding", "gzip"),) + JSON_TYPE}, "ambiguous_framing"),
            ("type_html", {"headers": length + (("Content-Type", "text/html"),)}, "content_type"),
            ("type_missing", {"headers": length}, "content_type"),
            ("type_utf16", {"headers": length + (("Content-Type", "application/json; charset=utf-16"),)}, "content_type"),
            ("type_prefix", {"headers": length + (("Content-Type", "application/jsonx"),)}, "content_type"),
            ("declared_longer_than_body", {"headers": (("Content-Length", str(len(body) + 1)),) + JSON_TYPE}, "incomplete_content_length"),
            ("declared_shorter_than_body", {"headers": (("Content-Length", str(len(body) - 1)),) + JSON_TYPE}, "incomplete_content_length"),
            ("no_known_eof", {"declared": False, "eof": False}, "missing_known_eof"),
        ]
        for label, options, code in cases:
            with self.subTest(case=label):
                self.assertCaptureFailure(code, options=options)
        with self.subTest(case="empty_body"):
            data = corpus()
            self.assertCaptureFailure("empty_body", bodies=[b""] + data.bodies[1:], options={"declared": False})
        with self.subTest(case="body_cap_without_known_eof"):
            big = b" " * (base.BODY_CAP + 10)
            data = corpus()
            self.assertCaptureFailure("body_cap_without_known_eof", bodies=[big] + data.bodies[1:], options={"declared": False})
        for accepted in ("application/json", "Application/JSON", "application/json; charset=utf-8",
                         "application/json;charset=UTF-8", "application/json ; charset=utf-8"):
            with self.subTest(content_type=accepted):
                data = corpus()
                headers = (("Content-Length", str(len(data.bodies[0]))), ("Content-Type", accepted))
                source, _, _ = build(transport=Transport(data.bodies, response_options={0: {"headers": headers}}))
                source.acquire()
                self.assertEqual(source.state, "pending")
                source.release()

    def test_price_get_failures_stop_after_the_failing_get(self):
        for index in (1, 4, 7):
            for label, options, code in (("status_429", {"status": 429}, "http_status"),
                                         ("gzip", {"headers": JSON_TYPE + (("Content-Encoding", "gzip"),)}, "content_encoding"),
                                         ("type", {"headers": (("Content-Type", "text/plain"),)}, "content_type")):
                with self.subTest(index=index, case=label):
                    source, _ = self.assertCaptureFailure(code, index=index, options=options)
                    self.assertEqual(source.ledger.unrun, tuple(range(index + 1, 8)))
        source, transport, _ = build(transport=Transport(corpus().bodies, fail_at=5))
        self.assertFailure("transport_or_parse_failure", source.acquire)
        self.assertEqual(len(transport.opens), 6)
        self.assertEqual(source.ledger.attempted, tuple(range(6)))

    def test_invalid_transport_reads_are_rejected_and_the_response_is_closed(self):
        class Str(Response):
            def read(self, count, timeout):
                return "text"

        class Over(Response):
            def read(self, count, timeout):
                return b"x" * (count + 1)

        for label, response_class in (("str", Str), ("over", Over)):
            with self.subTest(case=label):
                source, transport, _ = build(transport=Transport(corpus().bodies, response_class=response_class,
                                                                  response_options={0: {"declared": False}}))
                self.assertFailure("invalid_transport_read", source.acquire)
                self.assertTrue(transport.responses[0].closed)

    def test_close_failures_keep_the_primary_code_and_cleanup_only_failure_rejects(self):
        source, transport, _ = build(transport=Transport(corpus().bodies, response_options={0: {"status": 403, "close_raises": True}}))
        error = self.assertFailure("http_status", source.acquire)
        self.assertEqual(error.diagnostics["secondary_cleanup_count"], 1)
        self.assertEqual(error.diagnostics["secondary_cleanup_1_code"], "cleanup_failure")
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(dict(error.diagnostics)))
        self.assertNotIn("DO_NOT_RETAIN_RAW", repr(source.diagnostics))
        self.assertEqual(source.state, "failed")
        source, transport, _ = build(transport=Transport(corpus().bodies, response_options={2: {"close_raises": True}}))
        error = self.assertFailure("cleanup_failure", source.acquire)
        self.assertEqual(error.diagnostics["primary_stage"], "capture_response_close")
        self.assertEqual(source.state, "failed")
        self.assertEqual(len(transport.opens), 3)  # a successful read never implies the close succeeded

    def test_cooperative_request_batch_and_lease_deadlines(self):
        clock = Clock()
        source, transport, _ = build(transport=Transport(corpus().bodies, clock=clock, open_delay=21), clock=clock)
        self.assertFailure("cooperative_deadline", source.acquire)
        self.assertEqual(len(transport.opens), 1)
        # The batch budget is exhausted by external time spent between captures (a clock jump after the 4th capture).
        holder = []

        class Jumping(Clock):
            def __call__(self):
                if holder and len(holder[0]._captures) == 4 and not self.jumped:
                    self.jumped = True
                    self.now += 200
                return self.now
        clock = Jumping()
        clock.jumped = False
        source, transport, _ = build(transport=Transport(corpus().bodies, clock=clock), clock=clock)
        holder.append(source)
        self.assertFailure("cooperative_deadline", source.acquire)
        self.assertEqual(source.state, "failed")
        self.assertEqual(len(transport.opens), 4)
        # A non-monotonic clock is rejected.
        clock = Clock()
        source, transport, _ = build(transport=Transport(corpus().bodies, clock=clock), clock=clock)
        clock.now = 50.0
        source._last_clock = 100.0
        self.assertFailure("invalid_monotonic_clock", source.acquire)
        # Lease: pending and available are both cut at the lease and become inert.
        for admitted in (False, True):
            clock = Clock()
            source, transport, _ = build(transport=Transport(corpus().bodies, clock=clock), clock=clock, lease_seconds=5)
            source.acquire()
            if admitted:
                source.admit_independent_verification(admission(source))
            self.assertEqual(source.state, "available" if admitted else "pending")
            clock.now += 6
            self.assertEqual(source.state, "expired")
            self.assertFailure("inspection_unavailable", source.inspection)
            self.assertFailure("oracle_pending_required", source.admit_independent_verification, object())
            self.assertFailure("consumer_unavailable", source.save, environment={ROOT_ENV: self.new_root()})
            self.assertEqual(source._closes_bytes, b"")
            self.assertEqual(source._captures, [])

    def test_retained_roots_cap_fails_closed_before_and_during_acquisition(self):
        with patch.object(base, "ROOTS_CAP", 100):
            transport = Transport(corpus().bodies)
            self.assertFailure("retained_roots_estimate_cap", build, transport=transport)
            self.assertEqual(transport.opens, [])
        baseline = build()[0]._roots_estimate  # the pinned formal blob alone is ~270 KB
        self.assertGreater(baseline, 250000)
        with patch.object(base, "ROOTS_CAP", baseline + 60000):
            source, transport, _ = build()
            error = self.assertFailure("retained_roots_estimate_cap", source.acquire)
            self.assertEqual(source.state, "failed")
            self.assertIsInstance(error.diagnostics["estimate_bytes"], int)
            self.assertEqual(source._closes_bytes, b"")
        # The cap is also enforced while the body is still being read, not only after it has been assembled.
        rows = [{"date": (date(1970, 1, 1) + timedelta(days=offset)).isoformat()} for offset in range(20000)]
        large = json.dumps({"msg": "success", "status": 200, "data": rows}, separators=(",", ":")).encode()
        self.assertTrue(400000 < len(large) < base.BODY_CAP)
        with patch.object(base, "ROOTS_CAP", baseline + 150000):
            source, transport, _ = build(bodies=[large] + corpus().bodies[1:])
            error = self.assertFailure("retained_roots_estimate_cap", source.acquire)
            self.assertEqual(error.diagnostics["primary_stage"], "capture_body")
            self.assertEqual(len(transport.opens), 1)

    def test_one_shot_ledger_namespace_and_no_second_attempt(self):
        ledger = occ.AttemptLedger(NAMESPACE)
        source, transport, _ = build(ledger=ledger)
        source.acquire()
        self.assertEqual(ledger.attempted, tuple(range(8)))
        self.assertEqual(ledger.unrun, ())
        self.assertFailure("snapshot_already_attempted", source.acquire)
        again, again_transport, _ = build(ledger=ledger)
        self.assertFailure("quota_spent", again.acquire)
        self.assertEqual(again_transport.opens, [])
        self.assertFailure("quota_namespace", occ.AttemptLedger, "issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2")
        self.assertFailure("quota_namespace", occ.AttemptLedger, NAMESPACE + "x")
        fresh = occ.AttemptLedger(NAMESPACE)
        self.assertFailure("quota_order", fresh.charge, 0)
        fresh.begin()
        self.assertFailure("quota_order", fresh.charge, 1)
        self.assertFailure("quota_order", fresh.charge, True) if False else None
        fresh.charge(0)
        self.assertFailure("quota_spent", fresh.begin)
        self.assertEqual(fresh.attempted, (0,))
        self.assertFalse(any(hasattr(fresh, name) for name in ("reset", "release", "retry", "refund")))
        source.release()
        self.assertEqual(ledger.attempted, tuple(range(8)))  # the one-shot ledger survives release

    def test_pending_until_independent_admission_binds_receipts_and_closes(self):
        source, transport, _ = build()
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, object())
        source.acquire()
        self.assertEqual(source.state, "pending")
        self.assertFailure("consumer_unavailable", source.save, environment={ROOT_ENV: self.new_root()})
        proof = admission(source)
        bogus = "f" * 64
        cases = [
            ("not_independent", replace(proof, independent=False), "oracle_scope"),
            ("namespace", replace(proof, namespace=NAMESPACE + "x"), "oracle_scope"),
            ("issue32_namespace", replace(proof, namespace="issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2"), "oracle_scope"),
            ("policy_sha", replace(proof, policy_sha256=bogus), "oracle_scope"),
            ("bool_count", replace(proof, calendar_rows=True), "oracle_type"),
            ("list_receipts", replace(proof, receipt_sha256s=list(proof.receipt_sha256s)), "oracle_type"),
            ("int_closes", replace(proof, closes_sha256=5), "oracle_type"),
            ("independent_int", replace(proof, independent=1), "oracle_type"),
            ("receipt_not_hex", replace(proof, receipt_sha256s=("x",) * 8), "oracle_receipt_type"),
            ("receipt_upper", replace(proof, receipt_sha256s=tuple(value.upper() for value in proof.receipt_sha256s)), "oracle_receipt_type"),
            ("closes_not_hex", replace(proof, closes_sha256="xyz"), "oracle_receipt_type"),
            ("calendar_rows", replace(proof, calendar_rows=proof.calendar_rows + 1), "oracle_complete_scope"),
            ("price_rows", replace(proof, price_rows=proof.price_rows - 1), "oracle_complete_scope"),
            ("price_fields", replace(proof, price_fields=proof.price_fields + 1), "oracle_complete_scope"),
            ("anchor_fields", replace(proof, latest_anchor_fields=41), "oracle_complete_scope"),
            ("receipts_short", replace(proof, receipt_sha256s=proof.receipt_sha256s[:-1]), "oracle_capture_binding"),
            ("receipts_swapped", replace(proof, receipt_sha256s=(proof.receipt_sha256s[1], proof.receipt_sha256s[0]) + proof.receipt_sha256s[2:]), "oracle_capture_binding"),
            ("receipt_wrong", replace(proof, receipt_sha256s=(bogus,) + proof.receipt_sha256s[1:]), "oracle_capture_binding"),
            ("closes_differ", replace(proof, closes_sha256=bogus), "oracle_closes_binding"),
            ("closes_of_other_cutoff", replace(proof, closes_sha256=hashlib.sha256(corpus().closes_bytes("2026-10-05")).hexdigest()), "oracle_closes_binding"),
        ]
        for label, bad, code in cases:
            with self.subTest(case=label):
                self.assertFailure(code, source.admit_independent_verification, bad)
                self.assertEqual(source.state, "pending")
        source.admit_independent_verification(proof)
        self.assertEqual(source.state, "available")
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, proof)
        # Admission is only an assertion about THIS acquisition: hashes change with any new capture.
        other, _, _ = build()
        other.acquire()
        self.assertFailure("oracle_capture_binding", other.admit_independent_verification, proof)
        other.release()
        source.release()
        self.assertEqual(source.state, "released")
        self.assertFailure("inspection_unavailable", source.inspection)
        self.assertFailure("consumer_unavailable", source.save, environment={ROOT_ENV: self.new_root()})
        self.assertEqual((source._captures, source._results, source._documents, source._decoded_texts), ([], {}, [], []))
        self.assertEqual((source._closes, source._closes_bytes, source._dates, source._formal_blob), ({}, b"", (), b""))
        self.assertEqual(dict(source._anchors), {})

    def test_failed_acquisition_exposes_no_derived_state_and_cannot_be_saved(self):
        data = corpus()
        documents = copy.deepcopy(data.documents)
        documents[6]["data"][-1].update(close=documents[6]["data"][-1]["close"] + 1,
                                        max=documents[6]["data"][-1]["max"] + 1)
        bodies = [data.bodies[0]] + [price_body(document) for document in documents]
        source, transport, _ = build(bodies=bodies)
        self.assertFailure("latest_anchor_mismatch", source.acquire)
        self.assertEqual(source.state, "failed")
        self.assertEqual(source.inspection()["closes_bytes"], b"")
        self.assertEqual(source.diagnostics["primary_code"], "latest_anchor_mismatch")
        self.assertEqual(source.diagnostics["attempts"], 8)
        self.assertFailure("oracle_pending_required", source.admit_independent_verification, admission(source))
        self.assertFailure("consumer_unavailable", source.save, environment={ROOT_ENV: self.new_root()})
        for plain in source.diagnostics.values():
            self.assertIn(type(plain), (str, int, bool, type(None)))


class Replay(Case):
    """Canned wire bytes -> the real http.client parser -> the real _HTTPSTransport.open and this module's capture."""
    real_roots_tests = ("test_full_pipeline_for_each_accepted_framing",)

    def replay_source(self, wires, **kwargs):
        transport = ReplayTransport(wires)
        source, _, _ = build(transport=transport, **kwargs)
        return source, transport

    def test_full_pipeline_for_each_accepted_framing(self):
        data = corpus()
        for framing in ("length", "chunked", "close"):
            with self.subTest(framing=framing):
                source, transport = self.replay_source([finmind_wire(body, framing=framing) for body in data.bodies])
                source.acquire()
                self.assertEqual(source.state, "pending")
                self.assertEqual(transport.opens, [trading_url()] + [price_url(symbol) for symbol in SYMBOLS])
                self.assertEqual(source.inspection()["closes_bytes"], data.closes_bytes(CUT))
                fixed = {"Accept-Encoding": "identity", "Connection": "close",
                         "User-Agent": "stock-lab-issue32-local-ram/1", "Accept": "application/json"}
                for url, (host, method, target, headers) in zip(transport.opens, transport.requests):
                    self.assertEqual((host, method, target, headers),
                                     ("api.finmindtrade.com", "GET", url.replace(ENDPOINT, "/api/v4/data"), fixed))
                receipts = [capture.receipt for capture in source.inspection()["captures"]]
                self.assertEqual([r.body_sha256 for r in receipts], [hashlib.sha256(body).hexdigest() for body in data.bodies])
                self.assertTrue(all(r.full_eof and r.status == 200 and r.content_encoding == "identity" for r in receipts))
                source.admit_independent_verification(admission(source))
                source.release()

    def test_response_shapes_that_must_reject_the_batch_after_one_get(self):
        data = corpus()
        body = data.bodies[0]
        cases = [
            ("gzip", dict(content_encoding="gzip"), "content_encoding"),
            ("length_and_chunked", dict(framing="both"), "ambiguous_framing"),
            ("type_html", dict(content_type="text/html"), "content_type"),
            ("type_missing", dict(content_type=None), "content_type"),
            ("status_401", dict(status=401, reason="Unauthorized"), "http_status"),
            ("status_402", dict(status=402, reason="Payment Required"), "http_status"),
            ("status_403", dict(status=403, reason="Forbidden"), "http_status"),
            ("redirect_301", dict(status=301, reason="Moved Permanently", extra=[("Location", "https://example.invalid/")]), "http_status"),
        ]
        for label, options, code in cases:
            with self.subTest(case=label):
                source, transport = self.replay_source([finmind_wire(body, **options)] + [finmind_wire(b) for b in data.bodies[1:]])
                self.assertFailure(code, source.acquire)
                self.assertEqual(len(transport.opens), 1)  # a redirect is never followed
                self.assertEqual(source.ledger.attempted, (0,))
        for accepted in ("application/json; charset=utf-8", "Application/JSON"):
            with self.subTest(content_type=accepted):
                source, transport = self.replay_source([finmind_wire(b, content_type=accepted) for b in data.bodies])
                source.acquire()
                self.assertEqual(source.state, "pending")
                source.release()
        with self.subTest(case="set_cookie_is_ignored"):
            source, transport = self.replay_source([finmind_wire(b, extra=[("Set-Cookie", "a=b")]) for b in data.bodies])
            source.acquire()
            self.assertEqual(source.state, "pending")
            self.assertNotIn("Cookie", transport.requests[0][3])
            source.release()


def expected_receipt(source, data, cutoff, saved_at, pins, start=START, end=END):
    """The receipt the contract requires, built from independent literals (not from the product)."""
    gets = []
    for index, capture in enumerate(source.inspection()["captures"]):
        seen = capture.receipt
        entry = {
            "source_id": "finmind_trading_dates" if index == 0 else "finmind_nominal_ohlcv/" + SYMBOLS[index - 1],
            "source_version": TRADING_VERSION if index == 0 else POLICY_VERSION, "method": "GET",
            "url": trading_url(start, end) if index == 0 else price_url(SYMBOLS[index - 1], start, end),
            "status": 200, "request_started_utc": seen.request_started_utc, "observed_utc": seen.observed_utc,
            "body_bytes": len(data.bodies[index]), "body_sha256": hashlib.sha256(data.bodies[index]).hexdigest(),
            "full_eof": True, "content_type": "application/json", "content_encoding": "identity",
            "namespace": NAMESPACE, "policy_sha256": pins.sha256}
        entry["receipt_sha256"] = hashlib.sha256(canonical(entry)).hexdigest()
        gets.append(entry)
    closes = data.closes_bytes(cutoff)
    return {
        "schema": RECEIPT_SCHEMA, "storage": "private_local", "storage_schema": STORAGE_SCHEMA,
        "namespace": NAMESPACE, "purpose": PURPOSE, "consumer_version": CONSUMER,
        "source_policy": {"version": POLICY_VERSION, "sha256": pins.sha256, "bytes": pins.nbytes},
        "trading_date_source_version": TRADING_VERSION, "market": "TW/TPEx", "instrument_type": "ordinary_stock",
        "identity_as_of": "2026-10-06", "cutoff": cutoff, "window": {"start_date": start, "end_date": end},
        "calendar_rows": len(data.dates), "gets": gets,
        "adapter": {"ordinary_close_source_sha256": hashlib.sha256(OCC_FILE.read_bytes()).hexdigest(),
                    "ohlcv_history_source_sha256": hashlib.sha256(BASE_FILE.read_bytes()).hexdigest()},
        "closes": {"file": "closes.json", "sha256": hashlib.sha256(closes).hexdigest(), "bytes": len(closes)},
        "saved_at": saved_at, "attribution": ATTRIBUTION, "rights": {"price_source": RIGHTS, "trading_date_source": RIGHTS},
        "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
        "limitations": list(LIMITATIONS),
    }


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def write_bytes(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


KEEP = set()
EXPECTED_BLOCKED = [0]


class Saving(Case):
    real_roots_tests = ("test_bundle_is_the_independent_expectation_and_stores_no_raw_values",)

    def source(self, **kwargs):
        source, transport, _ = available(**kwargs)
        self.addCleanup(source.release)
        return source, transport

    def test_bundle_is_the_independent_expectation_and_stores_no_raw_values(self):
        source, transport = self.source()
        root = self.new_root()
        pins = policy_pack()[1]
        result = source.save(environment={ROOT_ENV: root})
        data = corpus()
        final = os.path.join(root, POLICY_VERSION, CUT)
        closes_bytes, receipt_bytes = read_bytes(os.path.join(final, "closes.json")), read_bytes(os.path.join(final, "receipt.json"))
        # Exact layout: one policy directory, one cutoff directory, two files, no staging leftovers.
        self.assertEqual(self.tree(root), sorted([
            (POLICY_VERSION, None), (os.path.join(POLICY_VERSION, CUT), None),
            (os.path.join(POLICY_VERSION, CUT, "closes.json"), len(closes_bytes)),
            (os.path.join(POLICY_VERSION, CUT, "receipt.json"), len(receipt_bytes))]))
        self.assertEqual(closes_bytes, data.closes_bytes(CUT))
        receipt = json.loads(receipt_bytes)
        expected = expected_receipt(source, data, CUT, receipt["saved_at"], pins)
        self.assertEqual(receipt, expected)
        self.assertEqual(receipt_bytes, canonical(expected))
        self.assertEqual((result.action, result.policy_version, result.cutoff, result.path), ("created", POLICY_VERSION, CUT, final))
        self.assertEqual((result.closes_sha256, result.closes_bytes), (hashlib.sha256(closes_bytes).hexdigest(), len(closes_bytes)))
        self.assertEqual((result.receipt_sha256, result.receipt_bytes, result.saved_at),
                         (hashlib.sha256(receipt_bytes).hexdigest(), len(receipt_bytes), receipt["saved_at"]))
        self.assertTrue(receipt["saved_at"].endswith("+00:00"))
        self.assertGreaterEqual(receipt["saved_at"], receipt["gets"][-1]["observed_utc"])
        self.assertLessEqual(len(closes_bytes), 65536)
        self.assertLessEqual(len(receipt_bytes), 32768)
        self.assertLessEqual(len(closes_bytes) + len(receipt_bytes), 196608)
        # The ordinary-close adapter and #32 helper hashes bind the code identity that produced the bundle.
        self.assertEqual(set(receipt["adapter"]), {"ordinary_close_source_sha256", "ohlcv_history_source_sha256"})
        # Neither raw bodies nor any open/high/low/volume/amount value is stored.
        combined = closes_bytes + receipt_bytes
        for forbidden in (b'"open"', b'"max"', b'"min"', b'"Trading_Volume"', b'"Trading_money"', b'"stock_id"', b'"spread"',
                          b'"data"', b'"status":200,"msg"'):
            self.assertNotIn(forbidden, combined)
        for volume_or_amount in (b"19731700", b"11863581093", b"34637793", b"6615109776", b"1000", b"100000"):
            self.assertNotIn(volume_or_amount, closes_bytes)  # receipt hashes are hex; closes hold only dates and closes
        for body in data.bodies:
            self.assertNotIn(body[:60], combined)
        self.assertEqual(set(json.loads(closes_bytes)), {"schema", "cutoff", "count", "symbols", "trading_dates", "counts", "closes"})
        for symbol in SYMBOLS:
            rows = json.loads(closes_bytes)["closes"][symbol]
            self.assertEqual(len(rows), 60)
            self.assertTrue(all(type(close) is str and len(row) == 2 for row in rows for close in [row[1]]))
        self.assertEqual(len(transport.opens), 8)

    def test_unset_or_invalid_root_writes_nothing(self):
        source, _ = self.source()
        for label, env, code in (
                ("absent", {}, "root_unset"), ("empty", {ROOT_ENV: ""}, "root_unset"), ("none", {ROOT_ENV: None}, "root_unset"),
                ("int", {ROOT_ENV: 5}, "root_unset"), ("relative", {ROOT_ENV: "relative\\dir"}, "root_invalid"),
                ("dotdot", {ROOT_ENV: os.path.join(SESSION, "..", "x")}, "root_invalid"),
                ("nul", {ROOT_ENV: SESSION + "\x00x"}, "root_invalid")):
            with self.subTest(case=label):
                before = self.tree(SESSION)
                self.assertFailure(code, source.save, environment=env)
                self.assertEqual(self.tree(SESSION), before)
        with patch.dict(os.environ, {ROOT_ENV: ""}):
            self.assertFailure("root_unset", source.save)
        root = self.new_root()
        with patch.dict(os.environ, {ROOT_ENV: root}):
            self.assertEqual(source.save().action, "created")
        self.assertFailure("source_required", occ.save_closes, object())
        self.assertEqual(occ.save_closes(source, environment={ROOT_ENV: root}).action, "idempotent")

    def test_resaving_the_same_snapshot_is_idempotent_and_different_content_is_refused(self):
        source, _ = self.source()
        root = self.new_root()
        first = source.save(environment={ROOT_ENV: root})
        final = os.path.join(root, POLICY_VERSION, CUT)
        before = {name: (read_bytes(os.path.join(final, name)), os.stat(os.path.join(final, name)).st_mtime_ns)
                  for name in ("closes.json", "receipt.json")}
        second = source.save(environment={ROOT_ENV: root})
        self.assertEqual((second.action, second.saved_at, second.receipt_sha256, second.closes_sha256),
                         ("idempotent", first.saved_at, first.receipt_sha256, first.closes_sha256))
        after = {name: (read_bytes(os.path.join(final, name)), os.stat(os.path.join(final, name)).st_mtime_ns)
                 for name in ("closes.json", "receipt.json")}
        self.assertEqual(before, after)
        tree = self.tree(root)
        # A later acquisition (new receipts) or different closes never replace the published bundle.
        for variant, label in ((0, "new_acquisition_same_closes"), (1, "different_closes"), (2, "same_closes_other_bodies")):
            other, _ = self.source(variant=variant)
            with self.subTest(case=label):
                self.assertFailure("final_conflict", other.save, environment={ROOT_ENV: root})
                self.assertEqual(self.tree(root), tree)
                self.assertEqual({name: read_bytes(os.path.join(final, name)) for name in before},
                                 {name: before[name][0] for name in before})
        self.assertEqual(corpus(variant=2).closes_bytes(CUT), corpus().closes_bytes(CUT))
        self.assertNotEqual(corpus(variant=1).closes_bytes(CUT), corpus().closes_bytes(CUT))

    def test_quota_of_bundles_files_and_bytes_fails_closed_without_partial_writes(self):
        root = self.new_root()
        cutoffs = ("2026-10-06", "2026-10-05", "2026-10-02")
        sources = [self.source(cutoff=cutoff)[0] for cutoff in cutoffs]
        first = sources[0].save(environment={ROOT_ENV: root})
        second = sources[1].save(environment={ROOT_ENV: root})
        self.assertEqual((first.action, second.action), ("created", "created"))
        tree = self.tree(root)
        self.assertEqual(sum(1 for _, size in tree if size is not None), 4)
        self.assertLessEqual(sum(size for _, size in tree if size is not None), 196608)
        self.assertFailure("quota_bundles", sources[2].save, environment={ROOT_ENV: root})
        self.assertEqual(self.tree(root), tree)
        # The other two limits, each with the bundle count still allowed.
        other = self.new_root()
        sources[0].save(environment={ROOT_ENV: other})
        tree = self.tree(other)
        used = first.closes_bytes + first.receipt_bytes
        with patch.object(occ, "MAX_FILES", 3):
            self.assertFailure("quota_files", sources[1].save, environment={ROOT_ENV: other})
        with patch.object(occ, "MAX_TOTAL_BYTES", used + 10):
            self.assertFailure("quota_bytes", sources[1].save, environment={ROOT_ENV: other})
        with patch.object(occ, "MAX_BUNDLES", 1):
            self.assertFailure("quota_bundles", sources[1].save, environment={ROOT_ENV: other})
        self.assertEqual(self.tree(other), tree)
        # Exact boundaries: the limit itself is allowed, one byte / file / bundle over it is not.
        needed = second.closes_bytes + second.receipt_bytes
        with patch.object(occ, "MAX_TOTAL_BYTES", used + needed - 1):
            self.assertFailure("quota_bytes", sources[1].save, environment={ROOT_ENV: other})
        self.assertEqual(self.tree(other), tree)
        with patch.object(occ, "MAX_TOTAL_BYTES", used + needed), patch.object(occ, "MAX_FILES", 4), patch.object(occ, "MAX_BUNDLES", 2):
            self.assertEqual(sources[1].save(environment={ROOT_ENV: other}).action, "created")
        # Per-file caps are checked in RAM before the root is even created.
        fresh = self.new_root()
        with patch.object(occ, "CLOSES_CAP", 100):
            self.assertFailure("closes_cap", sources[0].save, environment={ROOT_ENV: fresh})
        with patch.object(occ, "RECEIPT_CAP", 100):
            self.assertFailure("receipt_cap", sources[0].save, environment={ROOT_ENV: fresh})
        self.assertFalse(os.path.exists(fresh))

    def test_failures_leave_no_staging_and_the_snapshot_can_save_again(self):
        source, _ = self.source()
        real_rmdir = os.rmdir
        for label, patcher, stage, errno in (
                ("fsync", lambda: patch.object(occ.os, "fsync", side_effect=OSError(5, "synthetic fsync failure")), "staging_fsync", 5),
                ("write", lambda: patch.object(occ.os, "write", side_effect=OSError(28, "synthetic write failure")), "staging_write", 28),
                ("rename", lambda: patch.object(occ.os, "rename", side_effect=PermissionError(13, "synthetic rename failure")), "publish_rename", 13)):
            for existing_root in (False, True):
                root = self.new_root()
                if existing_root:
                    os.mkdir(root)
                with self.subTest(case=label, existing_root=existing_root):
                    with patcher():
                        error = self.assertFailure("storage_io_failure", source.save, environment={ROOT_ENV: root})
                    self.assertEqual((error.diagnostics["primary_stage"], error.diagnostics["errno"]), (stage, errno))
                    self.assertEqual(error.diagnostics["secondary_cleanup_count"], 0)
                    self.assertEqual(self.tree(root) if existing_root else os.path.exists(root), [] if existing_root else False)
                    self.assertEqual(source.state, "available")
                    self.assertEqual(source.save(environment={ROOT_ENV: root}).action, "created")  # retry inside the lease
        # A failing cleanup is reported separately and blocks the next save until the leftover is removed.
        root = self.new_root()
        os.mkdir(root)

        def rmdir(path, *args, **kwargs):
            if ".staging-" in os.fspath(path):
                raise OSError(32, "synthetic cleanup failure")
            return real_rmdir(path, *args, **kwargs)
        with patch.object(occ.os, "rename", side_effect=PermissionError(13, "synthetic")), patch.object(occ.os, "rmdir", side_effect=rmdir):
            error = self.assertFailure("storage_io_failure", source.save, environment={ROOT_ENV: root})
        self.assertEqual((error.diagnostics["primary_stage"], error.diagnostics["secondary_cleanup_count"],
                          error.diagnostics["secondary_cleanup_1_stage"]), ("publish_rename", 1, "staging_rmdir"))
        leftovers = [name for name in os.listdir(root)]
        self.assertEqual(len(leftovers), 1)
        self.assertTrue(leftovers[0].startswith(".staging-"))
        self.assertFailure("root_entries_invalid", source.save, environment={ROOT_ENV: root})
        os.rmdir(os.path.join(root, leftovers[0]))
        self.assertEqual(source.save(environment={ROOT_ENV: root}).action, "created")
        # Concurrent writer: busy fails closed before touching the disk.
        busy = self.new_root()
        occ._SAVE_LOCK.acquire()
        try:
            self.assertFailure("storage_busy", source.save, environment={ROOT_ENV: busy})
        finally:
            occ._SAVE_LOCK.release()
        self.assertFalse(os.path.exists(busy))

    def test_read_back_failure_is_reported_and_the_published_bundle_is_kept_for_inspection(self):
        source, _ = self.source()
        for label, patcher, code, extra in (
                ("mismatch", patch.object(occ, "_load_verified", return_value=(b"x", b"y", {}, {"saved_at": "x"}, "f")),
                 "saved_readback_mismatch", None),
                ("reader_rejects", patch.object(occ, "_load_verified", side_effect=occ.SourceError("saved_entries")),
                 "saved_readback_failed", "saved_entries")):
            root = self.new_root()
            with self.subTest(case=label):
                with patcher:
                    error = self.assertFailure(code, source.save, environment={ROOT_ENV: root})
                if extra:
                    self.assertEqual(error.diagnostics["reader_code"], extra)
                self.assertEqual(len([1 for _, size in self.tree(root) if size is not None]), 2)  # not silently deleted
                self.assertEqual(source.save(environment={ROOT_ENV: root}).action, "idempotent")

    def test_root_that_is_not_exactly_the_expected_layout_fails_closed_untouched(self):
        source, _ = self.source()
        version = "other-policy"

        def make(root, entries):
            os.mkdir(root)
            for kind, relative in entries:
                path = os.path.join(root, relative)
                if kind == "dir":
                    os.makedirs(path)
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    write_bytes(path, b"x")
        cases = [
            ("foreign_file", [("file", "x.txt")], "root_entries_invalid"),
            ("staging_leftover", [("dir", ".staging-0123456789abcdef")], "root_entries_invalid"),
            ("uppercase_policy_dir", [("dir", "BadDir")], "root_entries_invalid"),
            ("file_as_policy_dir", [("file", "other-policy")], "root_entries_invalid"),
            ("non_date_cutoff_dir", [("dir", os.path.join(version, "latest"))], "root_entries_invalid"),
            ("bundle_missing_receipt", [("file", os.path.join(version, "2026-10-05", "closes.json"))], "root_entries_invalid"),
            ("bundle_extra_file", [("file", os.path.join(version, "2026-10-05", name)) for name in ("closes.json", "receipt.json", "x")],
             "root_entries_invalid"),
            ("file_where_cutoff_dir_expected", [("file", os.path.join(version, "2026-10-05"))], "root_entries_invalid"),
        ]
        for label, entries, code in cases:
            root = self.new_root()
            make(root, entries)
            before = self.tree(root)
            with self.subTest(case=label):
                self.assertFailure(code, source.save, environment={ROOT_ENV: root})
                self.assertEqual(self.tree(root), before)
        root = self.new_root()
        os.mkdir(root)
        os.makedirs(os.path.join(root, version, "2026-10-05"))
        write_bytes(os.path.join(root, version, "2026-10-05", "closes.json"), b" " * (occ.CLOSES_CAP + 1))
        write_bytes(os.path.join(root, version, "2026-10-05", "receipt.json"), b"{}")
        self.assertFailure("saved_size_cap", source.save, environment={ROOT_ENV: root})
        # Foreign but well-formed bundles of another policy version are allowed and counted.
        root = self.new_root()
        os.mkdir(root)
        os.makedirs(os.path.join(root, version, "2026-10-05"))
        write_bytes(os.path.join(root, version, "2026-10-05", "closes.json"), b"{}")
        write_bytes(os.path.join(root, version, "2026-10-05", "receipt.json"), b"{}")
        self.assertEqual(source.save(environment={ROOT_ENV: root}).action, "created")
        # Missing parent, a file as the root, and a reparse point are refused before anything is created.
        parent = os.path.join(self.new_dir(), "missing", "r")
        self.assertFailure("saved_missing", source.save, environment={ROOT_ENV: parent})
        self.assertFalse(os.path.exists(os.path.dirname(parent)))
        file_root = os.path.join(self.new_dir(), "r")
        write_bytes(file_root, b"x")
        self.assertFailure("saved_not_dir", source.save, environment={ROOT_ENV: file_root})
        root = self.new_root()
        os.mkdir(root)
        real = os.lstat

        def reparse(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if os.path.normcase(os.fspath(path)) == os.path.normcase(root):
                return types.SimpleNamespace(st_mode=result.st_mode, st_size=0, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return result
        with patch.object(occ.os, "lstat", side_effect=reparse):
            self.assertFailure("saved_reparse_point", source.save, environment={ROOT_ENV: root})
        self.assertEqual(os.listdir(root), [])

    def test_save_and_load_never_fetch(self):
        source, transport = self.source()
        root = self.new_root()
        with patch.object(base._HTTPSTransport, "open", side_effect=AssertionError("must not fetch")), \
                patch.object(socket.socket, "connect", side_effect=AssertionError("must not connect")):
            source.save(environment={ROOT_ENV: root})
            occ.load_saved_closes(root, POLICY_VERSION, CUT, pins=policy_pack()[1])
            self.assertFailure("saved_missing", occ.load_saved_closes, root, POLICY_VERSION, "2026-10-05", pins=policy_pack()[1])
        self.assertEqual(len(transport.opens), 8)
        self.assertEqual(source.ledger.attempted, tuple(range(8)))


def shift_window_back(closes):
    """A coherent 60-day window (dates and every stock's rows agree) that ends one session before the cutoff."""
    previous = "2026-07-10"
    closes["trading_dates"] = [previous] + closes["trading_dates"][:-1]
    for symbol in SYMBOLS:
        closes["closes"][symbol] = [[previous, "100"]] + closes["closes"][symbol][:-1]


class Reader(Case):
    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(SESSION, "base")
        KEEP.add("base")
        os.mkdir(cls.dir)
        cls.addClassCleanup(cls._drop_base)  # also runs when the rest of setUpClass fails
        cls.root = os.path.join(cls.dir, "r")
        source, _, _ = available()
        cls.saved = source.save(environment={ROOT_ENV: cls.root})
        source.release()
        cls.pins = policy_pack()[1]
        cls.final = os.path.join(cls.root, POLICY_VERSION, CUT)
        cls.closes_bytes = read_bytes(os.path.join(cls.final, "closes.json"))
        cls.receipt_bytes = read_bytes(os.path.join(cls.final, "receipt.json"))

    @classmethod
    def _drop_base(cls):
        shutil.rmtree(cls.dir)
        KEEP.discard("base")

    def _assert_no_residue(self):
        self.assertEqual([name for name in os.listdir(SESSION) if name not in KEEP], [])

    def clone(self):
        root = os.path.join(self.new_dir(), "r")
        shutil.copytree(self.root, root)
        return root, os.path.join(root, POLICY_VERSION, CUT)

    def load(self, root, version=POLICY_VERSION, cutoff=CUT, pins=None):
        return occ.load_saved_closes(root, version, cutoff, pins=self.pins if pins is None else pins)

    def mutated(self, closes_fn=None, receipt_fn=None, fix=True):
        root, final = self.clone()
        closes, receipt = json.loads(self.closes_bytes), json.loads(self.receipt_bytes)
        if closes_fn:
            closes_fn(closes)
        closes_bytes = canonical(closes)
        if fix:
            receipt["closes"] = {"file": "closes.json", "sha256": hashlib.sha256(closes_bytes).hexdigest(), "bytes": len(closes_bytes)}
        if receipt_fn:
            receipt_fn(receipt)
        write_bytes(os.path.join(final, "closes.json"), closes_bytes)
        write_bytes(os.path.join(final, "receipt.json"), canonical(receipt))
        return root

    def test_valid_bundle_loads_exact_values_and_derives_the_20_and_21_day_windows(self):
        data = corpus()
        loaded = self.load(self.root)
        self.assertEqual((loaded.policy_version, loaded.cutoff, loaded.symbols), (POLICY_VERSION, CUT, SYMBOLS))
        self.assertEqual(loaded.trading_dates, tuple(json.loads(self.closes_bytes)["trading_dates"]))
        self.assertEqual((loaded.trading_dates[-1], len(loaded.trading_dates)), (CUT, 60))
        self.assertEqual((loaded.closes_sha256, loaded.receipt_sha256),
                         (hashlib.sha256(self.closes_bytes).hexdigest(), hashlib.sha256(self.receipt_bytes).hexdigest()))
        for symbol in SYMBOLS:
            expected = [(row["date"], fmt(row["close"])) for row in data.rows[symbol]][-60:]
            full = loaded.window(symbol, 60)
            self.assertEqual([(close.date, close.text) for close in full], expected)
            self.assertEqual([close.value for close in full], [Fraction(text) for _, text in expected])
            for count in (1, 20, 21, 59):
                window = loaded.window(symbol, count)
                self.assertEqual([(close.date, close.text) for close in window], expected[-count:])
                self.assertEqual(window, full[-count:])
        self.assertEqual(loaded.window("3105", 20)[0].date, loaded.trading_dates[40])
        self.assertEqual(loaded.window("3105", 21)[0].date, loaded.trading_dates[39])
        for symbol, count in (("3105", 0), ("3105", 61), ("3105", True), ("3105", "20"), ("3105", None), ("9999", 20), (b"3105", 20), (3105, 20)):
            self.assertFailure("saved_window_scope", loaded.window, symbol, count)
        self.assertEqual(loaded.receipt["cutoff"], CUT)
        with self.assertRaises(TypeError):
            loaded.receipt["cutoff"] = "x"
        with self.assertRaises(TypeError):
            loaded.closes["3105"] = ()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            loaded.cutoff = "x"

    def test_pollution_partial_and_oversize_bundles_are_refused(self):
        closes, receipt = self.closes_bytes, self.receipt_bytes

        def changed(closes_edit):
            document = json.loads(closes)
            closes_edit(document)
            return canonical(document)

        cases = [
            ("closes_missing", lambda f: os.remove(os.path.join(f, "closes.json")), "saved_entries"),
            ("receipt_missing", lambda f: os.remove(os.path.join(f, "receipt.json")), "saved_entries"),
            ("extra_file", lambda f: write_bytes(os.path.join(f, "x"), b""), "saved_entries"),
            ("extra_directory", lambda f: os.mkdir(os.path.join(f, "x")), "saved_entries"),
            ("closes_empty", lambda f: write_bytes(os.path.join(f, "closes.json"), b""), "saved_parse"),
            ("receipt_empty", lambda f: write_bytes(os.path.join(f, "receipt.json"), b""), "saved_parse"),
            ("closes_bom", lambda f: write_bytes(os.path.join(f, "closes.json"), b"\xef\xbb\xbf" + closes), "saved_parse"),
            ("closes_invalid_utf8", lambda f: write_bytes(os.path.join(f, "closes.json"), b"\xff" + closes), "saved_parse"),
            ("receipt_truncated", lambda f: write_bytes(os.path.join(f, "receipt.json"), receipt[:-5]), "saved_parse"),
            ("closes_trailing_newline", lambda f: write_bytes(os.path.join(f, "closes.json"), closes + b"\n"), "saved_not_canonical"),
            ("receipt_pretty", lambda f: write_bytes(os.path.join(f, "receipt.json"), json.dumps(json.loads(receipt), indent=2).encode()), "saved_not_canonical"),
            ("closes_array", lambda f: write_bytes(os.path.join(f, "closes.json"), b"[]"), "saved_shape"),
            ("closes_duplicate_key", lambda f: write_bytes(os.path.join(f, "closes.json"), b'{"closes":1,' + closes[1:]), "duplicate_json_key"),
            ("closes_oversize", lambda f: write_bytes(os.path.join(f, "closes.json"), closes + b" " * (occ.CLOSES_CAP + 1)), "saved_size_cap"),
            ("receipt_oversize", lambda f: write_bytes(os.path.join(f, "receipt.json"), receipt + b" " * (occ.RECEIPT_CAP + 1)), "saved_size_cap"),
            ("files_swapped", lambda f: (write_bytes(os.path.join(f, "closes.json"), receipt), write_bytes(os.path.join(f, "receipt.json"), closes)), "saved_shape"),
            ("close_changed_reference_stale", lambda f: write_bytes(os.path.join(f, "closes.json"),
                changed(lambda d: d["closes"]["3105"][5].__setitem__(1, "999"))), "saved_closes_reference"),
        ]
        for label, edit, code in cases:
            root, final = self.clone()
            edit(final)
            with self.subTest(case=label):
                self.assertFailure(code, self.load, root)

    def test_closes_document_contract_violations(self):
        cases = [
            ("schema", lambda c: c.update(schema="x"), "saved_value"),
            ("count", lambda c: c.update(count=59), "saved_value"),
            ("symbols_reversed", lambda c: c["symbols"].reverse(), "saved_value"),
            ("counts", lambda c: c["counts"].update({"3105": 59}), "saved_value"),
            ("extra_key", lambda c: c.update(extra=1), "saved_shape"),
            ("missing_key", lambda c: c.pop("counts"), "saved_shape"),
            ("cutoff", lambda c: c.update(cutoff="2026-10-05"), "saved_pin_or_scope"),
            ("dates_duplicate", lambda c: c["trading_dates"].__setitem__(5, c["trading_dates"][4]), "saved_dates"),
            ("dates_weekend_first", lambda c: c["trading_dates"].__setitem__(0, "2026-07-12"), "saved_dates"),
            ("dates_last_not_cutoff", lambda c: c["trading_dates"].__setitem__(59, "2026-10-07"), "saved_dates"),
            ("whole_window_ends_before_cutoff", shift_window_back, "saved_dates"),
            ("dates_before_window", lambda c: c["trading_dates"].__setitem__(0, "2026-06-30"), "saved_dates"),
            ("dates_not_iso", lambda c: c["trading_dates"].__setitem__(0, "20260713"), "saved_date"),
            ("row_date_differs", lambda c: c["closes"]["3105"][3].__setitem__(0, "2026-07-17"), "saved_dates"),
            ("row_too_short", lambda c: c["closes"]["3105"][3].pop(), "saved_shape"),
            ("row_too_long", lambda c: c["closes"]["3105"][3].append("x"), "saved_shape"),
            ("row_dropped", lambda c: c["closes"]["3105"].pop(), "saved_shape"),
            ("symbol_removed", lambda c: c["closes"].pop("8069"), "saved_shape"),
        ]
        for label, edit, code in cases:
            with self.subTest(case=label):
                self.assertFailure(code, self.load, self.mutated(closes_fn=edit))
        bad_closes = ["0", "0.50", "+5", "1e2", "-5", " 5", "5 ", "05", "5.", ".5", "1.1234567", "12345678901234.5",
                      "NaN", "", "١٢٣", 5, None, True, ["5"], {"a": 1}]
        for bad in bad_closes:
            with self.subTest(close=bad):
                self.assertFailure("saved_close", self.load, self.mutated(closes_fn=lambda c: c["closes"]["5274"][7].__setitem__(1, bad)))
        for good in ("1", "0.000001", "100.5", "19520", "9999999999999.999999"):
            with self.subTest(close=good):
                loaded = self.load(self.mutated(closes_fn=lambda c: c["closes"]["5274"][7].__setitem__(1, good)))
                self.assertEqual(loaded.window("5274", 60)[7].value, Fraction(good))

    def test_receipt_contract_violations(self):
        def get(index, **change):
            return lambda r: r["gets"][index].update(change)

        def shifted(index, field, seconds, anchor=None):
            def edit(r):
                from_text = r["gets"][index if anchor is None else anchor]["observed_utc"]
                r["gets"][index][field] = datetime_text(from_text, seconds)
            return edit

        cases = []
        for key, value in (("schema", "x"), ("storage", "ram"), ("storage_schema", "x"), ("namespace", NAMESPACE + "x"), ("purpose", "strategy"),
                           ("consumer_version", "x"), ("market", "TW"), ("instrument_type", "etf"), ("identity_as_of", "2026-10-05"),
                           ("publication_time", "2026-10-06"), ("first_availability", "known"), ("revision_time", "none")):
            cases.append((key, (lambda k, v: lambda r: r.update({k: v}))(key, value), "saved_value"))
        cases += [
            ("limitations_swapped", lambda r: r["limitations"].reverse(), "saved_value"),
            ("limitations_text", lambda r: r["limitations"].__setitem__(0, "x"), "saved_value"),
            ("limitations_short", lambda r: r["limitations"].pop(), "saved_shape"),
            ("policy_version", lambda r: r["source_policy"].update(version="issue7-other"), "saved_pin_or_scope"),
            ("policy_sha", lambda r: r["source_policy"].update(sha256="0" * 64), "saved_pin_or_scope"),
            ("policy_bytes", lambda r: r["source_policy"].update(bytes=r["source_policy"]["bytes"] + 1), "saved_pin_or_scope"),
            ("cutoff", lambda r: r.update(cutoff="2026-10-05"), "saved_pin_or_scope"),
            ("window_start_not_before_cutoff", lambda r: r["window"].update(start_date=CUT), "saved_window"),
            ("window_end_before_cutoff", lambda r: r["window"].update(end_date="2026-10-05"), "saved_window"),
            ("window_start_not_iso", lambda r: r["window"].update(start_date="20260701"), "saved_window"),
            ("attribution_empty", lambda r: r.update(attribution=""), "saved_value"),
            ("rights_empty", lambda r: r["rights"].update(price_source=""), "saved_value"),
            ("rights_long", lambda r: r["rights"].update(trading_date_source="r" * 513), "saved_value"),
            ("trading_version_bad", lambda r: r.update(trading_date_source_version="bad version"), "saved_value"),
            ("calendar_rows_low", lambda r: r.update(calendar_rows=59), "saved_calendar_rows"),
            ("calendar_rows_high", lambda r: r.update(calendar_rows=100000), "saved_calendar_rows"),
            ("calendar_rows_bool", lambda r: r.update(calendar_rows=True), "saved_shape"),
            ("extra_key", lambda r: r.update(extra=1), "saved_shape"),
            ("missing_key", lambda r: r.pop("adapter"), "saved_shape"),
            ("gets_seven", lambda r: r["gets"].pop(), "saved_shape"),
            ("gets_entry_extra_key", lambda r: r["gets"][2].update(extra=1), "saved_shape"),
            ("adapter_upper", lambda r: r["adapter"].update(ordinary_close_source_sha256="A" * 64), "saved_adapter"),
            ("adapter_short", lambda r: r["adapter"].update(ohlcv_history_source_sha256="a" * 63), "saved_adapter"),
            ("closes_file", lambda r: r["closes"].update(file="x.json"), "saved_closes_reference"),
            ("closes_bytes", lambda r: r["closes"].update(bytes=r["closes"]["bytes"] + 1), "saved_closes_reference"),
            ("closes_sha", lambda r: r["closes"].update(sha256="0" * 64), "saved_closes_reference"),
            ("closes_bytes_bool", lambda r: r["closes"].update(bytes=True), "saved_shape"),
            ("saved_at_before_last_observed", lambda r: r.update(saved_at=datetime_text(r["gets"][7]["observed_utc"], -1)), "saved_get_times"),
            ("saved_at_not_utc_offset", lambda r: r.update(saved_at="2026-10-12T10:00:00+08:00"), "saved_time"),
            ("saved_at_z_suffix", lambda r: r.update(saved_at="2026-10-12T10:00:00Z"), "saved_time"),
            ("saved_at_naive", lambda r: r.update(saved_at="2026-10-12T10:00:00"), "saved_time"),
            ("saved_at_garbage", lambda r: r.update(saved_at="yesterday"), "saved_time"),
        ]
        for index in (0, 1, 7):
            for field, value, code in (
                    ("source_id", "x", "saved_get"), ("source_version", "x", "saved_get"), ("method", "POST", "saved_get"),
                    ("url", price_url("9999"), "saved_get"), ("status", 201, "saved_get"), ("full_eof", False, "saved_get"),
                    ("content_encoding", "gzip", "saved_get"), ("content_type", "text/html", "saved_get"),
                    ("namespace", NAMESPACE + "x", "saved_get"), ("policy_sha256", "0" * 64, "saved_get"),
                    ("body_bytes", 0, "saved_get"), ("body_bytes", 1048577, "saved_get"), ("body_sha256", "X" * 64, "saved_get"),
                    ("body_sha256", "a" * 63, "saved_get"), ("request_started_utc", "2026-10-12T10:00:00+08:00", "saved_time"),
                    ("observed_utc", "2026-10-12T10:00:00Z", "saved_time"), ("receipt_sha256", "0" * 64, "saved_get_receipt_sha")):
                cases.append((f"get{index}_{field}_{str(value)[:12]}", get(index, **{field: value}), code))
        cases += [
            ("get2_started_after_observed", shifted(2, "request_started_utc", 1, anchor=2), "saved_get_times"),
            ("get3_started_before_previous_observed", shifted(3, "request_started_utc", -1, anchor=2), "saved_get_times"),
        ]
        for label, edit, code in cases:
            with self.subTest(case=label):
                self.assertFailure(code, self.load, self.mutated(receipt_fn=edit))

    def test_arguments_pins_and_missing_paths_never_fall_back(self):
        root = self.root
        wrong_sha = replace(self.pins, sha256="0" * 64)
        wrong_len = replace(self.pins, nbytes=self.pins.nbytes + 1)
        for label, pins in (("sha", wrong_sha), ("bytes", wrong_len)):
            with self.subTest(pins=label):
                self.assertFailure("saved_pin_or_scope", self.load, root, pins=pins)
        loaded = occ.load_saved_closes(root, POLICY_VERSION, CUT)  # no pins argument: the module's published pins
        self.assertEqual(loaded.closes_sha256, hashlib.sha256(self.closes_bytes).hexdigest())
        with patch.object(occ, "POLICY_SHA256", None):
            self.assertFailure("real_pins_unset", occ.load_saved_closes, root, POLICY_VERSION, CUT)
        with patch.object(occ, "POLICY_BYTES", V1_BYTES + 1):
            self.assertFailure("saved_pin_or_scope", occ.load_saved_closes, root, POLICY_VERSION, CUT)
        self.assertFailure("pins_type", occ.load_saved_closes, root, POLICY_VERSION, CUT, pins=(self.pins.sha256, 1))
        for version, code in (("issue7-other", "saved_policy_version"), ("Bad_Version", "saved_scope"), ("../x", "saved_scope"),
                              ("", "saved_scope"), (None, "saved_scope"), (POLICY_VERSION + "/", "saved_scope"), ("a" * 65, "saved_scope")):
            with self.subTest(version=version):
                self.assertFailure(code, self.load, root, version=version)
        for cutoff, code in (("2026-13-45", "saved_scope"), ("20261006", "saved_scope"), (None, "saved_scope"), (20261006, "saved_scope"),
                             ("2026-10-06 ", "saved_scope"), ("../2026-10-06", "saved_scope"), ("2026-10-05", "saved_missing"),
                             ("2026-10-07", "saved_missing")):
            with self.subTest(cutoff=cutoff):
                self.assertFailure(code, self.load, root, cutoff=cutoff)
        for label, bad_root, code in (("relative", "r", "root_invalid"), ("dotdot", os.path.join(root, "..", "r"), "root_invalid"),
                                      ("bytes", os.fsencode(root), "root_invalid"), ("none", None, "root_invalid"), ("int", 5, "root_invalid"),
                                      ("missing", os.path.join(self.new_dir(), "nothing"), "saved_missing"),
                                      ("file_as_root", os.path.join(self.final, "closes.json"), "saved_not_dir")):
            with self.subTest(root=label):
                self.assertFailure(code, self.load, bad_root)
        empty = self.new_root()
        os.mkdir(empty)
        self.assertFailure("saved_missing", self.load, empty)
        os.mkdir(os.path.join(empty, POLICY_VERSION))
        self.assertFailure("saved_missing", self.load, empty)

    def test_a_bad_bundle_is_never_replaced_by_another_version(self):
        root, final = self.clone()
        other, _, _ = available(cutoff="2026-10-05")
        other.save(environment={ROOT_ENV: root})
        other.release()
        # One policy pins one cutoff, so each bundle is read with the pins of the policy that produced it.
        pins_1005 = policy_pack(cutoff="2026-10-05")[1]
        self.assertNotEqual(pins_1005, self.pins)
        self.assertFailure("saved_pin_or_scope", self.load, root, cutoff="2026-10-05")
        earlier = self.load(root, cutoff="2026-10-05", pins=pins_1005)
        self.assertEqual(earlier.cutoff, "2026-10-05")
        self.assertNotEqual(earlier.closes_sha256, self.load(root).closes_sha256)
        write_bytes(os.path.join(final, "closes.json"), self.closes_bytes[:-3])
        self.assertFailure("saved_parse", self.load, root)
        self.assertEqual(self.load(root, cutoff="2026-10-05", pins=pins_1005).cutoff, "2026-10-05")
        self.assertFailure("saved_missing", self.load, root, cutoff="2026-10-02")
        real = os.lstat

        def reparse(path, *args, **kwargs):
            result = real(path, *args, **kwargs)
            if os.path.normcase(os.fspath(path)) == os.path.normcase(final):
                return types.SimpleNamespace(st_mode=result.st_mode, st_size=0, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return result
        with patch.object(occ.os, "lstat", side_effect=reparse):
            self.assertFailure("saved_reparse_point", self.load, root, cutoff=CUT)
            self.assertEqual(self.load(root, cutoff="2026-10-05", pins=pins_1005).cutoff, "2026-10-05")


def datetime_text(text, seconds=0):
    from datetime import datetime
    return (datetime.fromisoformat(text) + timedelta(seconds=seconds)).isoformat()


CHILD = r'''
import json, os, sys
def hook(event, args):
    if event in ("socket.connect", "socket.connect_ex", "socket.getaddrinfo", "subprocess.Popen"):
        raise AssertionError(event)
    if event == "open":
        path, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            raise AssertionError("write " + str(path))
    if event in ("os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.truncate"):
        raise AssertionError(event)
sys.addaudithook(hook)
backend, root, version, cutoff, sha, nbytes = sys.argv[1:7]
sys.path.insert(0, backend)
from app import ordinary_close_source as m
try:
    pins = None if sha == "-" else m.Pins(sha, int(nbytes))
    saved = m.load_saved_closes(root, version, cutoff, pins=pins)
except m.SourceError as error:
    print(json.dumps({"error": error.code}))
    sys.exit(3)
print(json.dumps({"cutoff": saved.cutoff, "dates": list(saved.trading_dates), "closes_sha256": saved.closes_sha256,
                  "receipt_sha256": saved.receipt_sha256,
                  "w20": [[c.date, c.text] for c in saved.window("3105", 20)],
                  "w21": [[c.date, c.text] for c in saved.window("8069", 21)],
                  "n": {s: len(saved.closes[s]) for s in saved.symbols}}))
'''


class CrossProcess(Case):
    real_roots_tests = ("test_a_new_process_rereads_and_rejects_pollution_without_writing_or_fetching",)

    def child(self, root, version, cutoff, pins):
        env = {"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "TEMP": tempfile.gettempdir(), "TMP": tempfile.gettempdir(),
               "TMPDIR": tempfile.gettempdir()}
        sha, nbytes = ("-", "0") if pins is None else (pins.sha256, str(pins.nbytes))
        CHILD_ALLOWED[0] = True
        try:
            done = subprocess.run([PYTHON, "-I", "-B", "-X", "utf8", "-c", CHILD, str(ROOT / "backend"), root, version, cutoff, sha, nbytes],
                                  capture_output=True, stdin=subprocess.DEVNULL, timeout=120, cwd=SESSION, env=env)
        finally:
            CHILD_ALLOWED[0] = False
        return done.returncode, done.stdout.decode("utf-8").strip(), done.stderr.decode("utf-8", "replace")

    def test_a_new_process_rereads_and_rejects_pollution_without_writing_or_fetching(self):
        source, _, _ = available()
        self.addCleanup(source.release)
        root = self.new_root()
        source.save(environment={ROOT_ENV: root})
        pins = policy_pack()[1]
        parent = occ.load_saved_closes(root, POLICY_VERSION, CUT, pins=pins)
        before = self.tree(root)
        code, out, err = self.child(root, POLICY_VERSION, CUT, pins)
        self.assertEqual((code, err), (0, ""), err)
        reread = json.loads(out)
        self.assertEqual(reread["cutoff"], CUT)
        self.assertEqual(reread["dates"], list(parent.trading_dates))
        self.assertEqual((reread["closes_sha256"], reread["receipt_sha256"]), (parent.closes_sha256, parent.receipt_sha256))
        self.assertEqual(reread["w20"], [[c.date, c.text] for c in parent.window("3105", 20)])
        self.assertEqual(reread["w21"], [[c.date, c.text] for c in parent.window("8069", 21)])
        self.assertEqual(reread["n"], {symbol: 60 for symbol in SYMBOLS})
        self.assertEqual(self.tree(root), before)  # the reader process wrote nothing
        # No pins argument: a fresh process uses the module's own published pins and verifies the same bundle.
        code, out, err = self.child(root, POLICY_VERSION, CUT, None)
        self.assertEqual((code, err), (0, ""), err)
        self.assertEqual(json.loads(out), reread)
        # A different cutoff is a different, absent bundle: never a fallback.
        code, out, _ = self.child(root, POLICY_VERSION, "2026-10-05", pins)
        self.assertEqual((code, json.loads(out)), (3, {"error": "saved_missing"}))
        # Pollution made after the save is detected by the new process, not trusted from the writer.
        final = os.path.join(root, POLICY_VERSION, CUT)
        document = json.loads(read_bytes(os.path.join(final, "closes.json")))
        document["closes"]["3105"][5][1] = "999"
        write_bytes(os.path.join(final, "closes.json"), canonical(document))
        code, out, _ = self.child(root, POLICY_VERSION, CUT, pins)
        self.assertEqual((code, json.loads(out)), (3, {"error": "saved_closes_reference"}))
        os.remove(os.path.join(final, "receipt.json"))
        code, out, _ = self.child(root, POLICY_VERSION, CUT, pins)
        self.assertEqual((code, json.loads(out)), (3, {"error": "saved_entries"}))


class HelperLocks(Case):
    """Everything this module takes from issue 32's private surface, with its signature and key behaviour pinned."""

    def test_reference_manifest_equals_the_names_actually_referenced(self):
        tree = ast.parse(OCC_FILE.read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "_base" and not node.attr.startswith("__")}
        self.assertEqual(used, set(occ.IMPORTED_HELPERS))
        self.assertEqual(len(occ.IMPORTED_HELPERS), len(set(occ.IMPORTED_HELPERS)))
        modules = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        sources = [(node.module, tuple(alias.name for alias in node.names), node.level) for node in modules if isinstance(node, ast.ImportFrom)]
        self.assertIn(("", ("ohlcv_history_source",), 1), [(m or "", n, level) for m, n, level in sources])
        self.assertEqual([m for m, _, _ in sources if m and "ohlcv" in m], [])

    def test_issue32_product_file_is_unchanged_since_the_qa2_candidate(self):
        # SOURCE_REGISTRY 49.2: the qa2 candidate 8c7b5ab product file. A later edit to that file must be noticed here.
        self.assertEqual(hashlib.sha256(BASE_FILE.read_bytes()).hexdigest(),
                         "528875c3b14f5ce7a7f140e7385f32a209d45118219b8e1e63de7848cf3f9a7b")

    def test_signatures_fields_and_constants(self):
        signature = lambda function: str(inspect.signature(function))  # noqa: E731
        expected = {
            "_prices": "(document, symbol, dates, source_index, check_roots)", "_formal_reference": "(formal_blob)",
            "_iso_date": "(value, code='price_date')", "_json": "(text, *, price=False)", "_canonical": "(value)",
            "_shape": "(value, schema)", "_freeze": "(value)",
            "_failure_values": "(exception, stage, fallback='transport_or_parse_failure')",
            "_close_all": "(operations, primary_failure=None)", "_raise_failure": "(values)", "_fail": "(code, **diagnostics)",
            "retained_roots_estimate": "(*roots)"}
        for name, text in expected.items():
            with self.subTest(helper=name):
                self.assertEqual(signature(getattr(base, name)), text)
        self.assertEqual(signature(base.AttemptLedger.__init__), "(self, namespace)")
        self.assertEqual(signature(base.AttemptLedger.begin), "(self)")
        self.assertEqual(signature(base.AttemptLedger.charge), "(self, index)")
        self.assertEqual(signature(base._HTTPSTransport.open), "(self, url, timeout)")
        names = lambda cls: [field.name for field in dataclasses.fields(cls)]  # noqa: E731
        self.assertEqual(names(base.Receipt), ["source_id", "source_version", "method", "url", "status", "request_started_utc",
                                               "observed_utc", "body_bytes", "body_sha256", "full_eof", "content_type",
                                               "content_encoding", "namespace", "policy_sha256"])
        self.assertEqual(names(base.Capture), ["body", "receipt"])
        self.assertEqual(names(base.Bar), ["date", "stock_id", "open", "high", "low", "close", "volume", "amount", "source_index"])
        self.assertEqual(names(base.FinancialStart), ["version", "issuer_thread_id", "coordinator_session_ids",
                                                      "implementer_session_ids", "namespace", "policy_sha256", "seal_comment_url",
                                                      "binding", "authorized", "whole_batch"])
        self.assertEqual(names(base.ExecutionBinding), ["holder_thread_id", "holder_session_id", "parent_thread_id", "model",
                                                        "reasoning_effort", "candidate_sha", "loaded_source_sha256", "script_sha256",
                                                        "native_command"])
        self.assertEqual(_RECEIPT_FIELDS_LITERAL, tuple(occ._RECEIPT_FIELDS))
        for cls in (base.Receipt, base.Capture, base.Bar, base.FinancialStart, base.ExecutionBinding):
            self.assertTrue(cls.__dataclass_params__.frozen)
        constants = {"BODY_CAP": 1048576, "RAW_CAP": 8388608, "ROOTS_CAP": 33554432, "REQUEST_SECONDS": 20, "BATCH_SECONDS": 180,
                     "USER_AGENT": "stock-lab-issue32-local-ram/1", "ACCEPT": "application/json",
                     "SESSION_ID_PATTERN": r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                     "MODEL_PATTERN": r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", "FORMAL_BLOB": FORMAL_OBJECT, "FORMAL_SHA256": FORMAL_SHA,
                     "SYMBOLS": SYMBOLS}
        for name, value in constants.items():
            with self.subTest(constant=name):
                self.assertEqual(getattr(base, name), value)
        self.assertTrue(issubclass(base.SourceError, ValueError))
        self.assertIs(occ.SourceError, base.SourceError)
        self.assertTrue(issubclass(occ.AttemptLedger, base.AttemptLedger))
        self.assertEqual(base.AttemptLedger.__init__.__code__.co_varnames[:2], ("self", "namespace"))

    def test_json_canonical_shape_freeze_and_date_helpers(self):
        self.assertFailure("duplicate_json_key", base._json, '{"a":1,"a":2}')
        self.assertFailure("nonfinite_json_number", base._json, '{"a":NaN}')
        self.assertFailure("nonfinite_json_number", base._json, "[Infinity]")
        self.assertFailure("nonfinite_json_number", base._json, "[-Infinity]", price=True)
        self.assertEqual(base._json('{"a":1.5}'), {"a": 1.5})
        self.assertIs(type(base._json('{"a":1.5}')["a"]), float)
        self.assertEqual(base._json('{"a":1.50}', price=True)["a"], Decimal("1.50"))
        self.assertEqual(base._canonical({"b": [1, "鈴"], "a": None}), '{"a":null,"b":[1,"鈴"]}'.encode("utf-8"))
        self.assertFailure("policy_keys", base._shape, {"a": 1}, {"b": int})
        self.assertFailure("policy_keys", base._shape, {"a": 1}, {"a": int, "b": int})
        self.assertFailure("policy_list", base._shape, ["x"], (str, 2))
        self.assertFailure("policy_list", base._shape, ("x", "y"), (str, 2))
        self.assertFailure("policy_type", base._shape, [1, "y"], (str, 2))
        self.assertFailure("policy_type", base._shape, True, int)
        self.assertFailure("policy_type", base._shape, 1.0, int)
        self.assertIsNone(base._shape({"a": [1, 2], "b": {"c": True}}, {"a": (int, 2), "b": {"c": bool}}))
        frozen = base._freeze({"a": [1, {"b": [2]}]})
        self.assertIsInstance(frozen, types.MappingProxyType)
        self.assertEqual(frozen["a"], (1, frozen["a"][1]))
        self.assertEqual(frozen["a"][1]["b"], (2,))
        with self.assertRaises(TypeError):
            frozen["a"] = 1
        self.assertEqual(base._iso_date("2026-10-06"), "2026-10-06")
        for bad in ("2026-10-6", "20261006", "2026-02-30", "2026-10-06 ", 20261006, None, b"2026-10-06", "٢026-10-06"):
            self.assertFailure("price_date", base._iso_date, bad)
            self.assertFailure("custom_code", base._iso_date, bad, "custom_code")

    def test_formal_reference_and_prices_helpers(self):
        prior, anchors = base._formal_reference(FORMAL)
        self.assertEqual((len(prior), prior[0], prior[-1]), (45, "2026-08-03", "2026-10-06"))
        self.assertEqual(prior, PRIOR)
        self.assertTrue(all(day not in prior for day in FORMAL_CLOSED))
        self.assertEqual(tuple(anchors), SYMBOLS)
        for symbol, values in ANCHORS.items():
            self.assertEqual(anchors[symbol], tuple(Fraction(str(value)) for value in values[:4]) + values[4:])
        self.assertFailure("formal_blob_pin", base._formal_reference, FORMAL + b" ")
        self.assertFailure("formal_blob_pin", base._formal_reference, "text")
        dates = DATES[:3]
        document = {"status": 200, "msg": "success", "data": price_rows(0, "3105", dates)}
        document = json.loads(json.dumps(document), parse_float=Decimal)
        seen = []
        bars = base._prices(document, "3105", dates, 1, lambda *roots: seen.append(roots))
        self.assertEqual(len(seen), 3)
        self.assertEqual(tuple(bar.date for bar in bars), dates)
        self.assertTrue(all(isinstance(bar, base.Bar) and bar.stock_id == "3105" and bar.source_index == 1 for bar in bars))
        self.assertEqual((bars[0].open, bars[0].high, bars[0].low, bars[0].close, bars[0].volume, bars[0].amount),
                         (Fraction(100), Fraction(102), Fraction(98), Fraction(100), 1000, 100000))
        self.assertIs(type(bars[0].close), Fraction)
        for label, edit, code in (("count", lambda d: d["data"].pop(), "price_row_count"), ("stock", lambda d: d["data"][0].update(stock_id="x"), "price_stock_id"),
                                  ("zero", lambda d: d["data"][0].update(close=Decimal(0)), "nonpositive_price"),
                                  ("bounds", lambda d: d["data"][0].update(max=Decimal(1)), "ohlc_bounds"),
                                  ("volume", lambda d: d["data"][0].update(Trading_Volume=0), "canonical_int64")):
            mutated = copy.deepcopy(document)
            edit(mutated)
            with self.subTest(case=label):
                self.assertFailure(code, base._prices, mutated, "3105", dates, 1, lambda *roots: None)

    def test_failure_cleanup_roots_and_ledger_helpers(self):
        error = base.SourceError("some_code", detail=1)
        self.assertEqual((error.code, dict(error.diagnostics)), ("some_code", {"code": "some_code", "detail": 1}))
        self.assertIsInstance(error.diagnostics, types.MappingProxyType)
        values = base._failure_values(OSError("SECRET RAW BODY" * 100), "capture_open", "fallback_code")
        self.assertEqual((values["code"], values["primary_code"], values["primary_stage"]), ("fallback_code", "fallback_code", "capture_open"))
        self.assertNotIn("SECRET", repr(values))
        sourced = base._failure_values(base.SourceError("Bad Code!", source_index=3, message="SECRET", raw_bytes=7), "stage_x")
        self.assertEqual((sourced["code"], sourced["primary_code"], sourced["primary_stage"], sourced["source_index"], sourced["raw_bytes"]),
                         ("transport_or_parse_failure", "transport_or_parse_failure", "stage_x", 3, 7))
        self.assertNotIn("message", sourced)
        self.assertNotIn("SECRET", repr(sourced))
        calls = []

        def closer(name, fail):
            def close():
                calls.append(name)
                if fail:
                    raise OSError("x")
            return close
        failure = base._close_all([("a", closer("a", True)), ("b", closer("b", False)), ("c", closer("c", True)),
                                   ("d", closer("d", True)), ("e", closer("e", True))])
        self.assertEqual(calls, ["a", "b", "c", "d", "e"])
        self.assertEqual((failure["primary_stage"], failure["secondary_cleanup_count"], failure["secondary_cleanup_omitted"]), ("a", 2, 1))
        primary = base._failure_values(base.SourceError("first"), "stage")
        kept = base._close_all([("x", closer("x", True))], primary)
        self.assertEqual((kept["code"], kept["secondary_cleanup_count"], kept["secondary_cleanup_1_stage"]), ("first", 1, "x"))
        self.assertIsNone(base._close_all([("ok", closer("ok", False))]))
        with self.assertRaises(base.SourceError) as caught:
            base._raise_failure({"code": "boom", "primary_code": "boom", "extra": 1})
        self.assertEqual((caught.exception.code, caught.exception.diagnostics["extra"]), ("boom", 1))
        self.assertTrue(caught.exception.__suppress_context__)
        shared = [1, 2, 3]
        self.assertEqual(base.retained_roots_estimate(shared), base.retained_roots_estimate(shared, shared))
        self.assertGreater(base.retained_roots_estimate(shared, [4]), base.retained_roots_estimate(shared))
        self.assertGreater(base.retained_roots_estimate(Fraction(10 ** 40, 3)), base.retained_roots_estimate(Fraction(1, 3)))
        ledger = base.AttemptLedger(base.NAMESPACE)
        self.assertEqual((ledger.attempted, ledger.unrun), ((), tuple(range(8))))
        self.assertFailure("quota_order", ledger.charge, 0)
        ledger.begin()
        self.assertFailure("quota_spent", ledger.begin)
        for index in range(8):
            ledger.charge(index)
        self.assertFailure("quota_order", ledger.charge, 8)
        self.assertEqual((ledger.attempted, ledger.unrun), (tuple(range(8)), ()))
        receipt = base.Receipt("a", "b", "GET", "https://x", 200, "s", "o", 1, "h" * 64, True, "t", "identity", "n", "p")
        self.assertEqual(receipt.canonical_sha256, hashlib.sha256(canonical({f.name: getattr(receipt, f.name) for f in dataclasses.fields(receipt)})).hexdigest())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.status = 201

    def test_default_transport_url_rules_and_fixed_request_headers(self):
        transport = base._HTTPSTransport()
        for url in ("http://api.finmindtrade.com/api/v4/data?x=1", "https://example.invalid/api/v4/data?x=1",
                    "https://api.finmindtrade.com:444/api/v4/data?x=1", "https://user@api.finmindtrade.com/api/v4/data?x=1",
                    "https://api.finmindtrade.com.evil.invalid/api/v4/data?x=1", "ftp://api.finmindtrade.com/x"):
            with self.subTest(url=url):
                self.assertFailure("transport_url", transport.open, url, 5)
        data = corpus()
        replay = ReplayTransport([finmind_wire(data.bodies[0])])
        response = replay.open(trading_url(), 5)
        try:
            self.assertEqual(replay.requests[0][3], {"Accept-Encoding": "identity", "Connection": "close",
                                                     "User-Agent": "stock-lab-issue32-local-ram/1", "Accept": "application/json"})
            self.assertEqual(response.status, 200)
        finally:
            response.close()


_RECEIPT_FIELDS_LITERAL = ("source_id", "source_version", "method", "url", "status", "request_started_utc", "observed_utc",
                           "body_bytes", "body_sha256", "full_eof", "content_type", "content_encoding", "namespace", "policy_sha256")


class RunnerGuards(Case):
    def test_import_time_calls_are_pure_and_the_hook_blocks_network_foreign_writes_and_processes(self):
        tree = ast.parse(OCC_FILE.read_text(encoding="utf-8"))
        called = set()

        def walk(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for decorator in getattr(node, "decorator_list", []):
                    walk(decorator)
                return
            if isinstance(node, ast.Call):
                function = node.func
                called.add(function.attr if isinstance(function, ast.Attribute) else function.id)
            for child in ast.iter_child_nodes(node):
                walk(child)
        for node in tree.body:
            walk(node)
        self.assertEqual(called, {"dataclass", "getattr", "tuple", "compile", "Lock", "fields", "len"})
        before = len(BLOCKED)
        outside = os.path.join(os.path.dirname(SESSION), "must-not-exist-" + os.path.basename(SESSION))
        with self.assertRaises(AssertionError):
            socket.create_connection(("127.0.0.1", 9), timeout=1)
        with self.assertRaises(AssertionError):
            socket.getaddrinfo("localhost", 80)
        with self.assertRaises(AssertionError):
            open(outside, "w")
        with self.assertRaises(AssertionError):
            os.mkdir(outside)
        with self.assertRaises(AssertionError):
            subprocess.run([PYTHON, "-c", "pass"], capture_output=True)
        with self.assertRaises(AssertionError):
            subprocess.run(["cmd", "/c", "echo", "x"], capture_output=True)
        self.assertFalse(os.path.exists(outside))
        self.assertEqual(len(BLOCKED) - before, 6)
        EXPECTED_BLOCKED[0] += 6


def tearDownModule():
    leftovers = os.listdir(SESSION)
    if leftovers:
        raise AssertionError("session directory not empty: %r" % leftovers)
    os.rmdir(SESSION)
    sys.stdout.write("RESIDUE session_dir_exists=%s hook_blocked=%d expected_probe_blocks=%d\n"
                     % (os.path.exists(SESSION), len(BLOCKED), EXPECTED_BLOCKED[0]))
    if len(BLOCKED) != EXPECTED_BLOCKED[0]:
        raise AssertionError("the hook blocked an unexpected operation: %r" % BLOCKED)


if __name__ == "__main__":
    unittest.main(verbosity=1)
