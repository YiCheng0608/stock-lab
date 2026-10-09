"""Issue 32's standalone, one-shot observed nominal OHLCV RAM source.

There is no import-time I/O. Callers supply the independently obtained canonical
policy and exact public formal SOURCE_REGISTRY blob. This module reads neither
files nor environment variables. ``acquire`` returns PENDING, not usable prices:
an independent same-RAM oracle must admit ALL eight captures before any window
or summary is available. Boundary transports do not demonstrate source truth.

The default transport is direct stdlib HTTPS. It requires FinancialStart and a
matching ExecutionBinding from a separately reviewed explicit Issue 32 seal.
These declarations do not authenticate GitHub/runtime identity; the sole QA
launcher/global review must independently establish them. The RAM quota survives
release/new source objects in this loaded module; it is not a durable or
cross-process limiter. The external one-shot seal remains authoritative.

Trace selectors (sys.settrace can observe the unmodified default path):
  _capture: capture_buffer while reading; full_body and receipt before return.
  _capture_ready: capture, full_body, receipt BEFORE any decoding/parsing.
  _parse_capture: full_body, receipt, decoded_text, document, parse_results,
                  diagnostics (including exceptional exits).
  _calendar: rows, dates, numbers during strict CSV validation/failure.
  _prices: document, found, row during whole-document validation/failure.
  acquire: exception, diagnostics, pending, results on the failure path.
``inspection`` exposes immutable original bytes/receipts/parsed observations in
RAM for the independent oracle. ``release`` clears owned financial roots. QA
must also clear its external trace/oracle/result/exception aliases, disable the
trace, unload the module and exit. No disk persistence is implemented.

Limits are cooperative boundary checks with remaining-time I/O budgets, not OS
hard deadlines. The deduplicated supported-object estimate is not RSS or peak.
QA can include external retained aliases via observer_roots; it cannot replace
the transport or replay captures to establish the real-path AC.
QA must independently check its full launcher/oracle/consumer span against the
180-second batch budget. Product acquisition checks that budget at its own
boundaries and caps the pending/available lease at the same batch deadline; it
cannot preempt time spent inside the external oracle, tracing or arbitrary code.
"""

from __future__ import annotations

import csv
import hashlib
import http.client
import io
import json
import math
import re
import ssl
import sys
import time
import types
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from urllib.parse import urlsplit


POLICY_SHA256 = "0f8c95eca6f0dcd08ca9b874996c4f41f8f8cf356f3282fee1e1c3f23734292d"
POLICY_BYTES = 3266
FORMAL_SHA256 = "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"
FORMAL_BLOB = "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md"
NAMESPACE = "issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa1"
PURPOSE = "local_personal_noncommercial_observed_nominal_ohlcv_snapshot"
CONSUMER_VERSION = "ordinary-nominal-ohlcv-window-summary-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
CUTOFFS = ("2026-10-05", "2026-10-06")
CALENDAR_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data&date=2026%2F07%2F01"
PRICE_URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={}&start_date=2026-07-01&end_date=2026-10-06"
CSV_HEADER = ("資料日期", "開市", "最高價", "最低價", "收市", "漲跌")
BODY_CAP = 1048576
RAW_CAP = 8388608
ROOTS_CAP = 33554432
REQUEST_SECONDS = 20
BATCH_SECONDS = 180
GLOBAL_ISSUER = "01a12102-9891-7293-8c66-a342094e0990"

# A schema, not a bundled policy or a source of expected financial values.
_POLICY_SHAPE = {
    "version": str, "profile": str, "source_use": str, "consumer_version": str,
    "market": str, "instrument_type": str, "symbols": (str, 7),
    "cutoffs": (str, 2), "identity_as_of": str,
    "price_source": {
        "provider": str, "dataset": str, "endpoint": str, "method": str,
        "query_order": (str, 4), "start_date": str, "end_date": str,
        "fields": {k: str for k in ("open", "high", "low", "close", "volume", "amount")},
        "basis": str, "rights": str,
    },
    "calendar_source": {
        "provider": str, "government_dataset": int, "url": str, "method": str,
        "format": str, "header": (str, 6), "expected_scope": str, "rights": str,
        "prior_calendar_formal_blob": str, "prior_calendar_formal_sha256": str,
        "prior_verified_counts": {"August": int, "September": int, "October_through_6": int},
        "version": str,
    },
    "unit_policy": {
        "version": str, "unit_mapping_inference": bool,
        "provider_literal_unit_annotation": bool, "OHLC": str, "volume": str,
        "amount": str, "scale": int, "independent_latest_anchor": str,
        "all_seven_must_match": bool,
    },
    "arithmetic": {k: str for k in ("last60", "ma20", "ma60", "prior20", "means", "prior20_high")},
    "storage": str, "publication_time": str, "first_availability": str,
    "revision_time": str, "unsupported": (str, 16),
    "acquisition": {
        "namespace": str, "order": str, "max_gets": int, "per_source_max_gets": int,
        "body_cap_bytes": int, "total_raw_cap_bytes": int,
        "retained_roots_estimate_cap_bytes": int, "request_seconds": int,
        "batch_seconds": int, "deadline": str, "accept_encoding": str,
        "redirects": int, "retries": int, "stop_on_first_failure": bool,
    },
}


class SourceError(ValueError):
    """Diagnostics contain only plain nonfinancial scalar metadata."""

    def __init__(self, code, **diagnostics):
        self.code = code
        self.diagnostics = MappingProxyType({"code": code, **diagnostics})
        super().__init__(code)


def _fail(code, **diagnostics):
    raise SourceError(code, **diagnostics)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_):
    _fail("nonfinite_json_number")


def _json(text, *, price=False):
    return json.loads(text, object_pairs_hook=_unique_pairs,
                      parse_float=Decimal if price else float,
                      parse_constant=_nonfinite)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _shape(value, schema):
    if isinstance(schema, dict):
        if type(value) is not dict or value.keys() != schema.keys():
            _fail("policy_keys")
        for key in schema:
            _shape(value[key], schema[key])
    elif isinstance(schema, tuple):
        item_type, count = schema
        if type(value) is not list or len(value) != count:
            _fail("policy_list")
        for item in value:
            if type(item) is not item_type:
                _fail("policy_type")
    elif type(value) is not schema:
        _fail("policy_type")


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if type(value) is list:
        return tuple(_freeze(v) for v in value)
    return value


def validate_policy(policy_canonical, policy_sha256):
    """Require the independently supplied exact canonical bytes and external pin."""
    if type(policy_canonical) is not bytes or type(policy_sha256) is not str:
        _fail("policy_input_type")
    if policy_sha256 != POLICY_SHA256:
        _fail("policy_pin")
    try:
        policy = _json(policy_canonical.decode("utf-8"))
        _shape(policy, _POLICY_SHAPE)
        canonical = _canonical(policy)
    except SourceError:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError):
        _fail("policy_encoding")
    if (len(canonical) != POLICY_BYTES or canonical != policy_canonical
            or hashlib.sha256(canonical).hexdigest() != policy_sha256):
        _fail("policy_canonical_mismatch")
    return _freeze(policy)


def _weekdays(start, end):
    result = []
    current = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while current <= stop:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(result)


JULY_DATES = _weekdays("2026-07-01", "2026-07-31")


def _section(text, heading):
    match = re.search(r"^" + re.escape(heading) + r"[^\n]*\n", text, re.M)
    if match is None:
        _fail("formal_section")
    level = len(heading) - len(heading.lstrip("#"))
    tail = text[match.end():]
    stop = re.search(r"^#{1," + str(level) + r"} ", tail, re.M)
    return tail[:stop.start()] if stop else tail


def _formal_reference(formal_blob):
    if type(formal_blob) is not bytes or hashlib.sha256(formal_blob).hexdigest() != FORMAL_SHA256:
        _fail("formal_blob_pin")
    text = formal_blob.decode("utf-8")
    history = _section(text, "### 19.2")
    calendar = _section(text, "### 31.2")
    if "8月21" not in history or "pre-calendar16" not in history:
        _fail("formal_august_evidence")
    def public_days(label, month):
        match = re.search(r"^- " + label + r"：[^/]+/([^。]+)。", calendar, re.M)
        if not match:
            _fail("formal_calendar_evidence")
        parts = match.group(1).split("、")
        return tuple(f"2026-{month:02d}-{int(part):02d}" for part in parts)
    august = _weekdays("2026-08-01", "2026-08-31")
    september = public_days("Sep20", 9)
    october = public_days("Oct4", 10)
    prior_dates = august + september + october
    if (len(august), len(september), len(october)) != (21, 20, 4):
        _fail("formal_calendar_count")
    if len(set(prior_dates)) != 45 or tuple(sorted(prior_dates)) != prior_dates:
        _fail("formal_calendar_order")
    anchors = {}
    table = _section(text, "### 32.2")
    for line in table.splitlines():
        match = re.fullmatch(r"\| (\d{4}) \| ([^|]+) \| ([0-9]+)／[^|]+ \| ([0-9]+) \|", line)
        if match:
            symbol, prices, volume, amount = match.groups()
            anchors[symbol] = tuple(Fraction(x.strip()) for x in prices.split("／")) + (int(volume), int(amount))
    if tuple(anchors) != SYMBOLS or any(len(values) != 6 for values in anchors.values()):
        _fail("formal_anchor_set")
    return prior_dates, MappingProxyType(anchors)


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    holder_thread_id: str
    holder_session_id: str
    parent_thread_id: None
    model: str
    reasoning_effort: str
    candidate_sha: str
    loaded_source_sha256: str
    script_sha256: str
    native_command: str


@dataclass(frozen=True, slots=True)
class FinancialStart:
    version: str
    issuer_thread_id: str
    namespace: str
    policy_sha256: str
    seal_comment_url: str
    binding: ExecutionBinding
    authorized: bool
    whole_batch: bool


def _financial_start(start, binding):
    if type(start) is not FinancialStart or type(binding) is not ExecutionBinding:
        _fail("financial_start_required")
    if type(start.binding) is not ExecutionBinding:
        _fail("financial_binding_type")
    for item in fields(binding):
        value = getattr(binding, item.name)
        if item.name == "parent_thread_id":
            if value is not None:
                _fail("financial_qa_not_top_level")
        elif type(value) is not str or not value:
            _fail("financial_binding_type")
    for item in fields(start):
        value = getattr(start, item.name)
        if item.name in ("authorized", "whole_batch"):
            if type(value) is not bool or value is not True:
                _fail("financial_start_not_authorized")
        elif item.name != "binding" and type(value) is not str:
            _fail("financial_start_type")
    if start.binding != binding:
        _fail("financial_binding_mismatch")
    if (start.version != "issue32-financial-start-v1" or start.issuer_thread_id != GLOBAL_ISSUER
            or start.namespace != NAMESPACE or start.policy_sha256 != POLICY_SHA256):
        _fail("financial_start_scope")
    if binding.holder_thread_id != binding.holder_session_id or binding.model != "gpt-6.1-sol" or binding.reasoning_effort != "xhigh":
        _fail("financial_qa_identity")
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", binding.holder_thread_id):
        _fail("financial_qa_identity")
    if binding.holder_thread_id in (GLOBAL_ISSUER, "01a12185-0e76-73c1-ad90-f47aded769b4", "01a12191-e54b-7b11-a081-428c5deee49d"):
        _fail("financial_qa_identity")
    if not re.fullmatch(r"[0-9a-f]{40}", binding.candidate_sha):
        _fail("financial_candidate")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in (binding.loaded_source_sha256, binding.script_sha256)):
        _fail("financial_script_binding")
    match = re.fullmatch(r"https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-([0-9]+)", start.seal_comment_url)
    if not match or int(match.group(1)) <= 6085344604:
        _fail("financial_new_explicit_seal_required")


class AttemptLedger:
    """One whole batch per ledger; no reset/release/retry API."""

    def __init__(self, namespace):
        if namespace != NAMESPACE:
            _fail("quota_namespace")
        self.namespace = namespace
        self._begun = False
        self._attempted = []

    @property
    def attempted(self):
        return tuple(self._attempted)

    @property
    def unrun(self):
        return tuple(range(len(self._attempted), 8))

    def begin(self):
        if self._begun or self._attempted:
            _fail("quota_spent")
        self._begun = True

    def charge(self, index):
        if not self._begun or type(index) is not int or index != len(self._attempted) or index >= 8:
            _fail("quota_order")
        self._attempted.append(index)  # SPENT before open, including open failure.


_REAL_LEDGER = None


class _HTTPSResponse:
    def __init__(self, connection, response):
        self.connection = connection
        self.response = response
        self.status = response.status
        self.headers = tuple(response.getheaders())
        self.socket = connection.sock
        if self.socket is None and response.fp is not None:
            self.socket = getattr(getattr(response.fp, "raw", None), "_sock", None)

    @property
    def known_eof(self):
        return self.response.isclosed() and (self.response.length in (None, 0))

    def read(self, count, timeout):
        if type(count) is not int or count <= 0:
            _fail("invalid_read_budget")
        if self.socket is None:
            _fail("transport_socket_budget")
        self.socket.settimeout(timeout)
        return self.response.read(count)

    def close(self):
        try:
            self.response.close()
        finally:
            self.connection.close()
            self.socket = None


class _HTTPSTransport:
    """Direct HTTPS only: no proxy/env/token/cookie handlers, redirects or retry."""

    def open(self, url, timeout):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ("www.tpex.org.tw", "api.finmindtrade.com") or parsed.port is not None or parsed.username is not None:
            _fail("transport_url")
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=timeout,
                                                context=ssl.create_default_context())
        response = None
        deadline = time.monotonic() + timeout
        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                _fail("cooperative_deadline")
            return budget
        try:
            # Socket waits get the remaining cumulative open budget. Checks are
            # cooperative; DNS/SSL/library calls are not OS-hard preempted.
            connection.timeout = remaining()
            connection.connect()
            connection.sock.settimeout(remaining())
            connection.request("GET", parsed.path + "?" + parsed.query,
                               headers={"Accept-Encoding": "identity", "Connection": "close"})
            connection.sock.settimeout(remaining())
            response = connection.getresponse()
            remaining()
            return _HTTPSResponse(connection, response)
        except BaseException:
            try:
                if response is not None:
                    response.close()
            finally:
                connection.close()
            raise


@dataclass(frozen=True, slots=True)
class Receipt:
    source_id: str
    source_version: str
    method: str
    url: str
    status: int
    request_started_utc: str
    observed_utc: str
    body_bytes: int
    body_sha256: str
    full_eof: bool
    content_type: str
    content_encoding: str
    namespace: str
    policy_sha256: str

    @property
    def canonical_sha256(self):
        return hashlib.sha256(_canonical({f.name: getattr(self, f.name) for f in fields(self)})).hexdigest()


@dataclass(frozen=True, slots=True)
class Capture:
    body: bytes
    receipt: Receipt


@dataclass(frozen=True, slots=True)
class Bar:
    date: str
    stock_id: str
    open: Fraction
    high: Fraction
    low: Fraction
    close: Fraction
    volume: int
    amount: int
    source_index: int


@dataclass(frozen=True, slots=True)
class Rational:
    numerator: int
    denominator: int

    @classmethod
    def of(cls, value):
        value = Fraction(value)
        return cls(value.numerator, value.denominator)


@dataclass(frozen=True, slots=True)
class OracleAdmission:
    """Independent source-oracle assertion; consumer arithmetic is checked next."""
    namespace: str
    policy_sha256: str
    holder_thread_id: str
    candidate_sha: str
    script_sha256: str
    receipt_sha256s: tuple
    calendar_rows: int
    price_rows: int
    price_fields: int
    latest_anchor_fields: int
    independent: bool


def retained_roots_estimate(*roots):
    """Deduplicated declared supported roots; not OS/RSS/peak measurement.

    Supports containers, our objects/dataclasses, decimal/rational leaves and
    exception traceback frame locals/cause/context. Modules/functions/classes/
    sockets/transports outside those declared containers are shallow leaves.
    """
    seen = set()
    pending = list(roots)
    total = 0
    while pending:
        value = pending.pop()
        ident = id(value)
        if ident in seen:
            continue
        seen.add(ident)
        total += sys.getsizeof(value)
        if isinstance(value, (dict, MappingProxyType)):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
        elif isinstance(value, BaseException):
            pending.extend((value.args, value.__dict__, value.__cause__, value.__context__, value.__traceback__))
        elif isinstance(value, types.TracebackType):
            pending.extend((value.tb_frame, value.tb_next))
        elif isinstance(value, types.FrameType):
            pending.append(value.f_locals)
        elif isinstance(value, Fraction):
            pending.extend((value.numerator, value.denominator))
        elif is_dataclass(value) and not isinstance(value, type):
            pending.extend(getattr(value, item.name) for item in fields(value))
        elif type(value).__module__ == __name__ and hasattr(value, "__dict__"):
            pending.append(value.__dict__)
    return total


def _number(value, *, positive=True):
    if type(value) not in (int, Decimal) or (isinstance(value, Decimal) and not value.is_finite()):
        _fail("price_number_type")
    if isinstance(value, Decimal):
        representation = value.as_tuple()
        # Compact JSON exponents can otherwise expand into an arbitrarily huge
        # integer/denominator before the supported-roots estimate can run.
        if len(representation.digits) + abs(representation.exponent) > BODY_CAP:
            _fail("numeric_representation_cap")
    exact = Fraction(value)
    if positive and exact <= 0:
        _fail("nonpositive_price")
    return exact


def _integer(value, *, positive=True):
    if type(value) is not int or not (0 <= value <= 9223372036854775807) or (positive and value == 0):
        _fail("canonical_int64")
    return value


def _bounds(o, h, l, c):
    if h < max(o, l, c) or l > min(o, h, c):
        _fail("ohlc_bounds")


def _iso_date(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _fail("price_date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        _fail("price_date")


def _calendar(text):
    # Deliberately reject preambles, changed headers, JSON, HTML and partial CSV.
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error:
        _fail("calendar_csv_syntax")
    if not rows or tuple(rows[0]) != CSV_HEADER or len(rows) != 24:
        _fail("calendar_header_or_count")
    dates = []
    for row in rows[1:]:
        if len(row) != 6 or not re.fullmatch(r"[0-9]{8}", row[0]):
            _fail("calendar_row")
        try:
            observed = datetime.strptime(row[0], "%Y%m%d").date().isoformat()
            numbers = tuple(Decimal(item) for item in row[1:])
        except (ValueError, ArithmeticError):
            _fail("calendar_value")
        if any(not item.is_finite() for item in numbers) or any(item <= 0 for item in numbers[:4]):
            _fail("calendar_number")
        _bounds(*numbers[:4])
        dates.append(observed)
    if len(set(dates)) != 23 or set(dates) != set(JULY_DATES):
        _fail("calendar_exact_dates")
    return rows, tuple(sorted(dates))


def _prices(document, symbol, dates, source_index, check_roots):
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("price_document")
    if type(document["status"]) is not int or document["status"] != 200 or document["msg"] != "success" or type(document["msg"]) is not str:
        _fail("price_document_status")
    if type(document["data"]) is not list or len(document["data"]) != 68:
        _fail("price_row_count")
    required = {"date", "stock_id", "open", "max", "min", "close", "Trading_Volume", "Trading_money"}
    allowed = required | {"spread", "Trading_turnover"}
    found = {}
    for row in document["data"]:
        if type(row) is not dict or not required.issubset(row) or not set(row).issubset(allowed):
            _fail("price_row_fields")
        observed = _iso_date(row["date"])
        if type(row["stock_id"]) is not str or row["stock_id"] != symbol:
            _fail("price_stock_id")
        if observed in found or observed not in dates:
            _fail("price_duplicate_or_calendar")
        o, h, l, c = (_number(row[key]) for key in ("open", "max", "min", "close"))
        _bounds(o, h, l, c)
        volume, amount = (_integer(row[key]) for key in ("Trading_Volume", "Trading_money"))
        if "spread" in row:
            _number(row["spread"], positive=False)
        if "Trading_turnover" in row:
            _integer(row["Trading_turnover"], positive=False)
        found[observed] = Bar(observed, symbol, o, h, l, c, volume, amount, source_index)
        check_roots(document, found, row, o, h, l, c, volume, amount)
    if set(found) != set(dates):
        _fail("price_incomplete_calendar")
    return tuple(found[day] for day in dates)


@dataclass(frozen=True, slots=True)
class NominalWindow:
    _snapshot: HistorySource
    symbol: str
    cutoff: str

    @property
    def bars(self):
        self._snapshot._usable()
        return tuple(row for row in self._snapshot._results[self.symbol] if row.date <= self.cutoff)[-60:]

    @property
    def provenance(self):
        return self._snapshot.provenance


@dataclass(frozen=True, slots=True)
class NominalSummary:
    _snapshot: HistorySource
    _key: tuple

    @property
    def values(self):
        self._snapshot._usable()
        return self._snapshot._summaries[self._key]

    @property
    def provenance(self):
        return self._snapshot.provenance


class HistorySource:
    """Only snapshot object; pending/failed/expired/released are consumer-inert."""

    def __init__(self, *, policy_canonical, policy_sha256, formal_blob,
                 purpose=PURPOSE, transport=None, ledger=None,
                 financial_start=None, execution_binding=None,
                 clock=time.monotonic, lease_seconds=180, observer_roots=None):
        self._policy = validate_policy(policy_canonical, policy_sha256)
        self._policy_canonical = policy_canonical
        if type(purpose) is not str or purpose != PURPOSE:
            _fail("unsupported_purpose")
        self._formal_blob = formal_blob
        self._prior_dates, self._anchors = _formal_reference(formal_blob)
        if type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 180:
            _fail("lease_seconds")
        if not callable(clock) or (observer_roots is not None and not callable(observer_roots)):
            _fail("clock_or_roots_type")
        self._real = transport is None
        if self._real or isinstance(transport, _HTTPSTransport):
            _financial_start(financial_start, execution_binding)
            if transport is not None or ledger is not None:
                _fail("default_transport_required_for_financial")
        elif financial_start is not None or execution_binding is not None:
            _fail("financial_start_with_boundary_transport")
        if not self._real and (type(ledger) is not AttemptLedger or ledger.namespace != NAMESPACE):
            _fail("boundary_ledger_required")
        self._binding = execution_binding
        self._transport = _HTTPSTransport() if self._real else transport
        self._ledger = ledger
        self._clock = clock
        self._observer_roots = observer_roots
        self._lease_seconds = lease_seconds
        self._last_clock = None
        self._batch_deadline = self._request_deadline = None
        self._expiry = None
        self._state = "new"
        self._raw_bytes = 0
        self._captures = []
        self._decoded_texts = []
        self._documents = []
        self._results = {}
        self._summaries = {}
        self._capture_buffer = bytearray()
        self._diagnostics = MappingProxyType({})
        self._roots_estimate = 0
        self._check_roots()

    @property
    def state(self):
        if self._state in ("pending", "available") and self._now() >= self._expiry:
            self.release(expired=True)
        return self._state

    @property
    def ledger(self):
        return self._ledger

    @property
    def diagnostics(self):
        return self._diagnostics

    def _now(self):
        current = self._clock()
        if type(current) not in (int, float) or not math.isfinite(current) or (self._last_clock is not None and current < self._last_clock):
            _fail("invalid_monotonic_clock")
        self._last_clock = current
        return current

    def _remaining(self):
        now = self._now()
        remaining = self._batch_deadline - now
        if self._request_deadline is not None:
            remaining = min(remaining, self._request_deadline - now)
        if remaining <= 0:
            _fail("cooperative_deadline")
        return remaining

    def _check_roots(self, *stage_roots):
        external = () if self._observer_roots is None else self._observer_roots()
        self._roots_estimate = retained_roots_estimate(self.__dict__, stage_roots, external)
        if self._roots_estimate > ROOTS_CAP:
            if getattr(self, "_state", None) in ("pending", "available"):
                self._state = "failed"
            _fail("retained_roots_estimate_cap", estimate_bytes=self._roots_estimate)

    def _capture_ready(self, capture):
        # Stable BEFORE-DECODE trace point. Failure paths also reach this point.
        full_body, receipt = capture.body, capture.receipt
        self._check_roots(full_body, receipt)
        return capture

    def _capture(self, index, url):
        self._remaining()
        self._request_deadline = self._now() + REQUEST_SECONDS
        self._ledger.charge(index)
        response = None
        capture_buffer = self._capture_buffer
        capture_buffer.clear()
        request_started_utc = datetime.now(timezone.utc).isoformat()
        full_body = receipt = None
        try:
            response = self._transport.open(url, self._remaining())
            self._remaining()
            if type(response.status) is not int or response.status != 200:
                _fail("http_status", source_index=index)
            header_values = {}
            for key, value in response.headers:
                key = key.lower()
                if key in header_values:
                    if key in ("content-length", "content-encoding", "transfer-encoding", "content-type"):
                        _fail("duplicate_framing_header")
                header_values[key] = value
            encoding = header_values.get("content-encoding", "identity").strip().lower()
            if encoding != "identity":
                _fail("content_encoding")
            length_text = header_values.get("content-length")
            declared_length = None
            if length_text is not None:
                if not re.fullmatch(r"0|[1-9][0-9]*", length_text):
                    _fail("content_length")
                declared_length = int(length_text)
                if declared_length > BODY_CAP or declared_length > RAW_CAP - self._raw_bytes:
                    _fail("declared_body_cap")
            transfer = header_values.get("transfer-encoding", "").strip().lower()
            if transfer not in ("", "chunked") or (transfer and declared_length is not None):
                _fail("ambiguous_framing")
            while True:
                self._remaining()
                if response.known_eof is True:
                    break
                available = min(BODY_CAP - len(capture_buffer), RAW_CAP - self._raw_bytes)
                if available <= 0:
                    _fail("body_cap_without_known_eof")
                count = min(65536, available)
                chunk = response.read(count, self._remaining())
                if type(chunk) is not bytes or len(chunk) > count:
                    _fail("invalid_transport_read")
                self._raw_bytes += len(chunk)
                capture_buffer.extend(chunk)
                self._check_roots(capture_buffer, chunk)
                self._remaining()
                if not chunk:
                    if response.known_eof is not True:
                        _fail("missing_known_eof")
                    break
            if declared_length is not None and declared_length != len(capture_buffer):
                _fail("incomplete_content_length")
            if not capture_buffer:
                _fail("empty_body")
            full_body = bytes(capture_buffer)
            source_id = "tpex_government_index_csv" if index == 0 else "finmind_nominal_ohlcv/" + SYMBOLS[index - 1]
            source_version = self._policy["calendar_source"]["version"] if index == 0 else self._policy["version"]
            receipt = Receipt(source_id, source_version, "GET", url, 200,
                              request_started_utc, datetime.now(timezone.utc).isoformat(),
                              len(full_body), hashlib.sha256(full_body).hexdigest(), True,
                              header_values.get("content-type", ""), encoding, NAMESPACE, POLICY_SHA256)
            capture = Capture(full_body, receipt)
            self._captures.append(capture)
            self._check_roots(capture_buffer, full_body, receipt)
            return self._capture_ready(capture)
        finally:
            try:
                if response is not None:
                    response.close()
            finally:
                capture_buffer.clear()

    def _parse_capture(self, capture, index, dates):
        full_body, receipt = capture.body, capture.receipt
        decoded_text = document = parse_results = None
        diagnostics = {"source_index": index, "stage": "decode_parse"}
        try:
            self._remaining()
            decoded_text = full_body.decode("utf-8")
            self._decoded_texts.append(decoded_text)
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            if index == 0:
                document, parse_results = _calendar(decoded_text)
            else:
                document = _json(decoded_text, price=True)
                self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
                self._remaining()
                parse_results = _prices(document, SYMBOLS[index - 1], dates, index, self._check_roots)
                latest = parse_results[-1]
                actual = (latest.open, latest.high, latest.low, latest.close, latest.volume, latest.amount)
                if actual != self._anchors[SYMBOLS[index - 1]]:
                    _fail("latest_anchor_mismatch", source_index=index)
            self._documents.append(_freeze(document))
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            return parse_results
        except BaseException as exception:
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics, exception)
            raise
        finally:
            self._request_deadline = None

    def acquire(self):
        """Whole ordered batch, no retry; success is still pending oracle admission."""
        global _REAL_LEDGER
        if self._state != "new":
            _fail("snapshot_already_attempted")
        if self._real:
            if _REAL_LEDGER is None:
                _REAL_LEDGER = AttemptLedger(NAMESPACE)
            self._ledger = _REAL_LEDGER
        self._ledger.begin()
        self._state = "acquiring"
        self._batch_deadline = self._now() + BATCH_SECONDS
        pending = self
        results = self._results
        try:
            july = self._parse_capture(self._capture(0, CALENDAR_URL), 0, None)
            dates = july + self._prior_dates
            if len(dates) != 68 or len(set(dates)) != 68:
                _fail("calendar_combination")
            self._dates = dates
            for index, symbol in enumerate(SYMBOLS, 1):
                results[symbol] = self._parse_capture(self._capture(index, PRICE_URL.format(symbol)), index, dates)
                self._check_roots(pending, results)
            self._remaining()
            self._expiry = min(self._now() + self._lease_seconds, self._batch_deadline)
            self._state = "pending"
            return pending
        except BaseException as exception:
            self._state = "failed"
            diagnostics = {"stage": "batch", "attempts": len(self._ledger.attempted),
                           "raw_bytes": self._raw_bytes,
                           "code": exception.code if isinstance(exception, SourceError) else "transport_or_parse_failure"}
            self._diagnostics = MappingProxyType(diagnostics)
            self._check_roots(pending, results, diagnostics, exception)
            if isinstance(exception, SourceError):
                raise
            raise SourceError("transport_or_parse_failure", attempts=len(self._ledger.attempted), raw_bytes=self._raw_bytes) from None
        finally:
            self._capture_buffer.clear()
            self._request_deadline = None

    def inspection(self):
        if self.state not in ("pending", "available", "failed"):
            _fail("inspection_unavailable")
        return MappingProxyType({"captures": tuple(self._captures),
                                 "decoded_texts": tuple(self._decoded_texts),
                                 "documents": tuple(self._documents),
                                 "results": MappingProxyType(dict(self._results)),
                                 "diagnostics": self._diagnostics,
                                 "retained_roots_estimate_bytes": self._roots_estimate})

    def admit_independent_verification(self, admission):
        if self.state != "pending" or type(admission) is not OracleAdmission:
            _fail("oracle_pending_required")
        for item in fields(admission):
            value = getattr(admission, item.name)
            expected = tuple if item.name == "receipt_sha256s" else bool if item.name == "independent" else int if item.name.endswith(("rows", "fields")) else str
            if type(value) is not expected:
                _fail("oracle_type")
        if admission.independent is not True or (admission.namespace, admission.policy_sha256) != (NAMESPACE, POLICY_SHA256):
            _fail("oracle_scope")
        if any(type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value) for value in admission.receipt_sha256s):
            _fail("oracle_receipt_type")
        if (admission.calendar_rows, admission.price_rows, admission.price_fields, admission.latest_anchor_fields) != (23, 476, 2856, 42):
            _fail("oracle_complete_scope")
        hashes = tuple(capture.receipt.canonical_sha256 for capture in self._captures)
        if len(hashes) != 8 or admission.receipt_sha256s != hashes:
            _fail("oracle_capture_binding")
        if self._real and (admission.holder_thread_id, admission.candidate_sha, admission.script_sha256) != (self._binding.holder_thread_id, self._binding.candidate_sha, self._binding.script_sha256):
            _fail("oracle_qa_binding")
        self._check_roots(admission)
        self._state = "available"

    def _usable(self):
        if self.state != "available":
            _fail("consumer_unavailable")
        self._check_roots()

    def _scope(self, symbol, cutoff):
        self._usable()
        if type(symbol) is not str or symbol not in SYMBOLS or type(cutoff) is not str or cutoff not in CUTOFFS:
            _fail("unsupported_window_scope")

    @property
    def provenance(self):
        self._usable()
        return MappingProxyType({
            "namespace": NAMESPACE, "policy_sha256": POLICY_SHA256,
            "consumer_version": CONSUMER_VERSION, "market": "TW/TPEx",
            "identity_as_of": "2026-10-06", "instrument_type": "ordinary_stock",
            "basis": "provider_reported_nominal_ohlcv", "unit_policy": self._policy["unit_policy"],
            "price_rights": self._policy["price_source"]["rights"],
            "calendar_rights": self._policy["calendar_source"]["rights"],
            "formal_blob": FORMAL_BLOB, "formal_sha256": FORMAL_SHA256,
            "calendar_version": self._policy["calendar_source"]["version"],
            "calendar_dates": self._dates, "receipts": tuple(c.receipt for c in self._captures),
            "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
            "unsupported": self._policy["unsupported"], "storage": "process_RAM",
            "lease_expires_monotonic": self._expiry,
            "deadline": "cooperative", "retained_roots_estimate_bytes": self._roots_estimate,
            "retained_roots_estimate_is_rss_or_peak": False,
        })

    def get_nominal_ohlcv60(self, symbol, cutoff):
        self._scope(symbol, cutoff)
        window = NominalWindow(self, symbol, cutoff)
        if len(window.bars) != 60 or window.bars[-1].date != cutoff:
            _fail("window_incomplete")
        self._check_roots(window)
        return window

    def summarize_nominal_ohlcv60(self, symbol, cutoff):
        window = self.get_nominal_ohlcv60(symbol, cutoff)
        bars = window.bars
        prior = tuple(row for row in self._results[symbol] if row.date < cutoff)[-20:]
        if len(prior) != 20:
            _fail("prior_window_incomplete")
        values = MappingProxyType({
            "consumer_version": CONSUMER_VERSION, "symbol": symbol, "cutoff": cutoff,
            "start_date": bars[0].date, "end_date": bars[-1].date, "count": 60,
            "ma20_close": Rational.of(sum((row.close for row in bars[-20:]), Fraction()) / 20),
            "ma60_close": Rational.of(sum((row.close for row in bars), Fraction()) / 60),
            "prior20_start": prior[0].date, "prior20_end": prior[-1].date,
            "prior20_high": Rational.of(max(row.high for row in prior)),
            "prior20_volume_mean": Rational.of(Fraction(sum(row.volume for row in prior), 20)),
            "prior20_amount_mean": Rational.of(Fraction(sum(row.amount for row in prior), 20)),
        })
        self._summaries[(symbol, cutoff)] = values
        self._check_roots(window, bars, prior, values)
        return NominalSummary(self, (symbol, cutoff))

    def release(self, *, expired=False):
        self._capture_buffer.clear()
        self._captures.clear()
        self._decoded_texts.clear()
        self._documents.clear()
        self._results.clear()
        self._summaries.clear()
        self._formal_blob = b""
        self._anchors = MappingProxyType({})
        self._transport = None
        self._observer_roots = None
        self._dates = ()
        self._state = "expired" if expired else "released"
        # The one-shot ledger is deliberately retained and never reset.


def get_nominal_ohlcv60(snapshot, symbol, cutoff):
    if type(snapshot) is not HistorySource:
        _fail("snapshot_required")
    return snapshot.get_nominal_ohlcv60(symbol, cutoff)


def ordinary_nominal_ohlcv_window_summary_v1(snapshot, symbol, cutoff):
    if type(snapshot) is not HistorySource:
        _fail("snapshot_required")
    return snapshot.summarize_nominal_ohlcv60(symbol, cutoff)
