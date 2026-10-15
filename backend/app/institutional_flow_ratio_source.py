"""Issue 39's standalone, one-shot institutional-flow / share-volume RAM source.

There is no import-time I/O. Callers supply the independently obtained canonical
policy and exact public formal SOURCE_REGISTRY blob. This module reads neither
files nor environment variables. ``acquire`` returns PENDING, not usable ratios:
an independent same-RAM oracle must admit ALL fifteen captures before any input
or ratio is available. Boundary transports do not demonstrate source truth.

Every capture comes from api.finmindtrade.com in a fixed order: one
TaiwanStockTradingDate document (must equal the formal 24 trading days
2026-09-01..2026-10-06 exactly), then one TaiwanStockPrice document per symbol
(dates must equal those days; the 2026-10-06 volume must equal the formal
SOURCE_REGISTRY 32.2 anchor), then one TaiwanStockInstitutionalInvestorsBuySell
document per symbol (five fixed ``name`` values per day; the two-cutoff net
shares must equal the 56 formal SOURCE_REGISTRY 47.6 anchors). A failure at any
step stops the batch before the next group is requested.

The ratio itself is computed by the stage-1 ``institutional_flow_ratio``
consumer from integer shares; this module only validates and assembles inputs.

The default transport is direct stdlib HTTPS. It requires FinancialStart and a
matching ExecutionBinding from a separately reviewed explicit Issue 39 seal.
These declarations do not authenticate GitHub/runtime identity; the sole QA
launcher/global review must independently establish them: the seal carries the
issuer/coordinator/implementer session ids and the QA caller reads its own
holder/model/effort back from its runtime; none is pinned here. QA must differ
from every seal role and the roles must be pairwise distinct. The RAM quota survives
release/new source objects in this loaded module; it is not a durable or
cross-process limiter. The external one-shot seal remains authoritative.

Trace selectors (sys.settrace can observe the unmodified default path):
  _capture: capture_buffer while reading; full_body and receipt before return.
  _capture_ready: capture, full_body, receipt BEFORE any decoding/parsing.
  _parse_capture: full_body, receipt, decoded_text, document, parse_results,
                  diagnostics (including exceptional exits).
  _trading_dates / _check_trading_dates: document, dates during strict
                  FinMind trading-date validation/failure.
  _prices / _flows: document, found, row during whole-document validation/failure.
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
Cleanup preserves primary_code/primary_stage and separately reports at most two
secondary_cleanup_N_code/stage pairs plus an omitted count. Diagnostics never
retain exception messages/objects, responses, frames or tracebacks. Emitted
exception context is ephemeral and still requires the QA finally alias cleanup.
Cleanup-only failure rejects the batch; successful capture never implies that
response/connection cleanup succeeded.
"""

from __future__ import annotations

import hashlib
import http.client
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

from .institutional_flow_ratio import (
    FORMULA_VERSION,
    PURPOSE_STRATEGY_GATE,
    InstitutionalFlowRatioError,
    compute_institutional_flow_ratio,
)


# Pin of the externally generated canonical policy v1 (global coordinator, Issue 39
# comment 6126200268). ``validate_policy`` rejects an empty pin (``policy_pin_unset``).
POLICY_SHA256 = "00ab692d13bfb7ea242eb5d02dc361def40f51a0b4a583a173df265bd2fd910d"
POLICY_BYTES = 5541
FORMAL_SHA256 = "f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240"
FORMAL_BLOB = "116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md"
NAMESPACE = "issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa1"
PURPOSE = "local_personal_noncommercial_institutional_flow_to_volume_ratio"
CONSUMER_VERSION = "institutional-flow-volume-ratio-two-cutoffs-v1"
FINANCIAL_START_VERSION = "issue39-financial-start-v1"
SEAL_URL_PATTERN = r"https://github\.com/YiCheng0608/stock-lab/issues/39#issuecomment-([0-9]+)"
SEAL_COMMENT_FLOOR = 6124891317  # the stage-2 dispatch comment; a seal must be newer
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
CUTOFFS = ("2026-10-05", "2026-10-06")
FLOW_NAMES = ("Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer_self", "Dealer_Hedging")
TRADING_DATE_URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate&start_date=2026-09-01&end_date=2026-10-06"
PRICE_URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={}&start_date=2026-09-01&end_date=2026-10-06"
FLOW_URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={}&start_date=2026-09-01&end_date=2026-10-06"
WINDOW_START = "2026-09-01"
WINDOW_END = "2026-10-06"
REQUEST_COUNT = 15
USER_AGENT = "stock-lab-issue39-local-ram/1"
ACCEPT = "application/json"
BODY_CAP = 1048576
RAW_CAP = 8388608
ROOTS_CAP = 33554432
REQUEST_SECONDS = 20
BATCH_SECONDS = 180
SESSION_ID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
MODEL_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"

# A schema, not a bundled policy or a source of expected financial values.
_POLICY_SHAPE = {
    "version": str, "profile": str, "source_use": str, "consumer_version": str,
    "market": str, "instrument_type": str, "symbols": (str, 7),
    "cutoffs": (str, 2), "identity_as_of": str,
    "trading_date_source": {
        "provider": str, "dataset": str, "endpoint": str, "url": str, "method": str,
        "format": str, "fields": {"date": str}, "documentation": str, "expected_scope": str,
        "rights": str, "formal_calendar_blob": str, "formal_calendar_sha256": str,
        "formal_counts": {"September": int, "October_through_6": int},
        "version": str,
    },
    "price_source": {
        "provider": str, "dataset": str, "endpoint": str, "method": str,
        "query_order": (str, 4), "start_date": str, "end_date": str,
        "fields": {k: str for k in ("open", "high", "low", "close", "volume", "amount")},
        "basis": str, "rights": str, "version": str,
    },
    "flow_source": {
        "provider": str, "dataset": str, "endpoint": str, "method": str,
        "query_order": (str, 4), "start_date": str, "end_date": str,
        "fields": {k: str for k in ("date", "stock_id", "buy", "sell", "name")},
        "names": (str, 5),
        "category_mapping": {"foreign": str, "investment_trust": str,
                             "dealer": (str, 2), "excluded": str},
        "net": str, "documentation": str, "rights": str, "version": str,
    },
    "response_shape": {k: str for k in (
        "status", "content_type", "framing", "content_encoding", "duplicate_identity_headers",
        "set_cookie", "encoding", "zero_price_rows", "flow_rows", "flow_values")},
    "unit_policy": {
        "version": str, "unit_mapping_inference": bool,
        "provider_literal_unit_annotation": bool, "volume": str, "flow": str,
        "scale": int, "volume_anchor": str, "net_anchor": str,
        "all_seven_must_match": bool,
    },
    "arithmetic": {k: str for k in (
        "flow_window", "volume_window", "ratio", "gate", "oracle")},
    "storage": str, "publication_time": str, "first_availability": str,
    "revision_time": str, "unsupported": (str, 12),
    "acquisition": {
        "namespace": str, "order": str, "max_gets": int, "per_source_max_gets": int,
        "body_cap_bytes": int, "total_raw_cap_bytes": int,
        "retained_roots_estimate_cap_bytes": int, "request_seconds": int,
        "batch_seconds": int, "deadline": str, "accept_encoding": str,
        "accept": str, "user_agent": str,
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


def _failure_values(exception, stage, fallback="transport_or_parse_failure"):
    """Copy only bounded plain metadata; never message/args/object chains."""
    def label(value, default):
        return value if type(value) is str and re.fullmatch(r"[a-z0-9_]{1,64}", value) else default
    original = exception.diagnostics if isinstance(exception, SourceError) else {}
    code = label(exception.code, fallback) if isinstance(exception, SourceError) else fallback
    values = {"code": code, "primary_code": code,
              "primary_stage": label(original.get("primary_stage"), stage),
              "secondary_cleanup_count": 0, "secondary_cleanup_omitted": 0,
              "secondary_validation_count": 0, "secondary_validation_omitted": 0}
    for name in ("source_index", "estimate_bytes", "attempts", "raw_bytes"):
        value = original.get(name)
        if type(value) is int and 0 <= value <= sys.maxsize:
            values[name] = value
    for kind in ("cleanup", "validation"):
        prefix = "secondary_" + kind
        count = original.get(prefix + "_count", 0)
        if type(count) is int and 0 <= count <= 2:
            for index in range(1, count + 1):
                item = f"{prefix}_{index}"
                values[item + "_code"] = label(original.get(item + "_code"), kind + "_failure")
                values[item + "_stage"] = label(original.get(item + "_stage"), kind)
                estimate = original.get(item + "_estimate_bytes")
                if kind == "validation" and type(estimate) is int and 0 <= estimate <= sys.maxsize:
                    values[item + "_estimate_bytes"] = estimate
            values[prefix + "_count"] = count
        omitted = original.get(prefix + "_omitted", 0)
        if type(omitted) is int and 0 <= omitted <= 4:
            values[prefix + "_omitted"] = omitted
    return values


def _close_all(operations, primary_failure=None):
    """Every necessary close is attempted, even when earlier closes raise."""
    failure = primary_failure
    def secondary(code, stage):
        count = failure["secondary_cleanup_count"]
        if count < 2:
            count += 1
            failure["secondary_cleanup_count"] = count
            failure[f"secondary_cleanup_{count}_code"] = code
            failure[f"secondary_cleanup_{count}_stage"] = stage
        else:
            failure["secondary_cleanup_omitted"] += 1
    for stage, close in operations:
        try:
            close()
        except BaseException as cleanup_exception:
            cleanup = _failure_values(cleanup_exception, stage, "cleanup_failure")
            if failure is None:
                failure = cleanup
            else:
                secondary(cleanup["primary_code"], cleanup["primary_stage"])
                for index in range(1, cleanup["secondary_cleanup_count"] + 1):
                    secondary(cleanup[f"secondary_cleanup_{index}_code"], cleanup[f"secondary_cleanup_{index}_stage"])
                failure["secondary_cleanup_omitted"] += cleanup["secondary_cleanup_omitted"]
    return failure


def _raise_failure(values):
    raise SourceError(values["code"], **{key: value for key, value in values.items() if key != "code"}) from None


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
    if not POLICY_SHA256 or type(POLICY_BYTES) is not int or POLICY_BYTES <= 0:
        _fail("policy_pin_unset")
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
    _policy_constants(policy)
    return _freeze(policy)


def _policy_constants(policy):
    """The pinned policy must describe exactly the behavior this module hard-codes."""
    acquisition = policy["acquisition"]
    expected = {
        "namespace": NAMESPACE, "max_gets": REQUEST_COUNT, "per_source_max_gets": 1,
        "body_cap_bytes": BODY_CAP, "total_raw_cap_bytes": RAW_CAP,
        "retained_roots_estimate_cap_bytes": ROOTS_CAP, "request_seconds": REQUEST_SECONDS,
        "batch_seconds": BATCH_SECONDS, "accept_encoding": "identity", "accept": ACCEPT,
        "user_agent": USER_AGENT, "redirects": 0, "retries": 0, "stop_on_first_failure": True,
    }
    if any(acquisition[key] != value or type(acquisition[key]) is not type(value) for key, value in expected.items()):
        _fail("policy_constant_mismatch")
    if (policy["source_use"] != PURPOSE or policy["consumer_version"] != CONSUMER_VERSION
            or tuple(policy["symbols"]) != SYMBOLS or tuple(policy["cutoffs"]) != CUTOFFS
            or tuple(policy["flow_source"]["names"]) != FLOW_NAMES
            or (policy["trading_date_source"]["formal_calendar_blob"],
                policy["trading_date_source"]["formal_calendar_sha256"]) != (FORMAL_BLOB, FORMAL_SHA256)
            or (policy["trading_date_source"]["dataset"], policy["price_source"]["dataset"],
                policy["flow_source"]["dataset"]) != (
                "TaiwanStockTradingDate", "TaiwanStockPrice", "TaiwanStockInstitutionalInvestorsBuySell")
            or any(policy[key]["start_date"] != WINDOW_START or policy[key]["end_date"] != WINDOW_END
                   for key in ("price_source", "flow_source"))):
        _fail("policy_constant_mismatch")


def _section(text, heading):
    match = re.search(r"^" + re.escape(heading) + r"[^\n]*\n", text, re.M)
    if match is None:
        _fail("formal_section")
    level = len(heading) - len(heading.lstrip("#"))
    tail = text[match.end():]
    stop = re.search(r"^#{1," + str(level) + r"} ", tail, re.M)
    return tail[:stop.start()] if stop else tail


def _formal_reference(formal_blob):
    """Parse the three external expectations from the pinned formal blob.

    Returns (24 formal trading days, {symbol: 2026-10-06 volume in shares},
    {(cutoff, symbol): (foreign, trust, dealer, total) net shares}). The values are
    read, never typed into this module, so the product does not carry its own answer.
    """
    if type(formal_blob) is not bytes or hashlib.sha256(formal_blob).hexdigest() != FORMAL_SHA256:
        _fail("formal_blob_pin")
    text = formal_blob.decode("utf-8")
    calendar = _section(text, "### 31.2")
    def public_days(label, month):
        match = re.search(r"^- " + label + r"：[^/]+/([^。]+)。", calendar, re.M)
        if not match:
            _fail("formal_calendar_evidence")
        parts = match.group(1).split("、")
        return tuple(f"2026-{month:02d}-{int(part):02d}" for part in parts)
    september = public_days("Sep20", 9)
    october = public_days("Oct4", 10)
    formal_dates = september + october
    if (len(september), len(october)) != (20, 4):
        _fail("formal_calendar_count")
    if len(set(formal_dates)) != 24 or tuple(sorted(formal_dates)) != formal_dates:
        _fail("formal_calendar_order")
    if formal_dates[0] != WINDOW_START or formal_dates[-1] != WINDOW_END or CUTOFFS[-1] != WINDOW_END:
        _fail("formal_calendar_order")
    volumes = {}
    for line in _section(text, "### 32.2").splitlines():
        match = re.fullmatch(r"\| (\d{4}) \| ([^|]+) \| ([0-9]+)／[^|]+ \| ([0-9]+) \|", line)
        if match:
            symbol, _prices, volume, _amount = match.groups()
            volumes[symbol] = int(volume)
    if tuple(volumes) != SYMBOLS or any(not 0 < value <= 9223372036854775807 for value in volumes.values()):
        _fail("formal_anchor_set")
    nets = {}
    current = None
    for line in _section(text, "### 47.6").splitlines():
        header = re.fullmatch(r"\| (2026-10-0[56]) \| [^|]+ \| [^|]+ \| [^|]+ \| [^|]+ \|", line)
        if header:
            current = header.group(1)
            continue
        match = re.fullmatch(r"\| (\d{4}) \| (-?[0-9,]+) \| (-?[0-9,]+) \| (-?[0-9,]+) \| (-?[0-9,]+) \|", line)
        if match and current is not None:
            symbol = match.group(1)
            values = tuple(int(part.replace(",", "")) for part in match.groups()[1:])
            if values[0] + values[1] + values[2] != values[3] or any(abs(v) > 9223372036854775807 for v in values):
                _fail("formal_net_anchor_values")
            if (current, symbol) in nets:
                _fail("formal_net_anchor_set")
            nets[(current, symbol)] = values
    if tuple(nets) != tuple((cutoff, symbol) for cutoff in CUTOFFS for symbol in SYMBOLS):
        _fail("formal_net_anchor_set")
    return formal_dates, MappingProxyType(volumes), MappingProxyType(nets)


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    holder_thread_id: str
    holder_session_id: str
    parent_thread_id: None
    model: str
    reasoning_effort: str
    candidate_sha: str
    loaded_source_sha256: str
    consumer_source_sha256: str  # the stage-1 institutional_flow_ratio.py this module calls
    script_sha256: str
    native_command: str


@dataclass(frozen=True, slots=True)
class FinancialStart:
    version: str
    issuer_thread_id: str
    coordinator_session_ids: tuple
    implementer_session_ids: tuple
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
        elif item.name in ("coordinator_session_ids", "implementer_session_ids"):
            if type(value) is not tuple or not value or any(type(part) is not str for part in value):
                _fail("financial_start_type")
        elif item.name != "binding" and type(value) is not str:
            _fail("financial_start_type")
    if start.binding != binding:
        _fail("financial_binding_mismatch")
    if (start.version != FINANCIAL_START_VERSION
            or start.namespace != NAMESPACE or start.policy_sha256 != POLICY_SHA256):
        _fail("financial_start_scope")
    # Issuer/coordinator/implementer identities come from the seal and are
    # checked by the QA caller against the Issue receipts; this module pins none.
    roles = (start.issuer_thread_id,) + start.coordinator_session_ids + start.implementer_session_ids
    if any(not re.fullmatch(SESSION_ID_PATTERN, part) for part in roles) or len(set(roles)) != len(roles):
        _fail("financial_start_scope")
    if binding.holder_thread_id != binding.holder_session_id or binding.reasoning_effort != "xhigh":
        _fail("financial_qa_identity")
    if not re.fullmatch(SESSION_ID_PATTERN, binding.holder_thread_id) or not re.fullmatch(MODEL_PATTERN, binding.model):
        _fail("financial_qa_identity")
    if binding.holder_thread_id in roles:
        _fail("financial_qa_identity")
    if not re.fullmatch(r"[0-9a-f]{40}", binding.candidate_sha):
        _fail("financial_candidate")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in (
            binding.loaded_source_sha256, binding.consumer_source_sha256, binding.script_sha256)):
        _fail("financial_script_binding")
    match = re.fullmatch(SEAL_URL_PATTERN, start.seal_comment_url)
    if not match or int(match.group(1)) <= SEAL_COMMENT_FLOOR:
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
        return tuple(range(len(self._attempted), REQUEST_COUNT))

    def begin(self):
        if self._begun or self._attempted:
            _fail("quota_spent")
        self._begun = True

    def charge(self, index):
        if not self._begun or type(index) is not int or index != len(self._attempted) or index >= REQUEST_COUNT:
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
            failure = _close_all((("https_response_close", self.response.close),
                                  ("https_connection_close", self.connection.close)))
        finally:
            self.socket = None
        if failure is not None:
            _raise_failure(failure)


class _HTTPSTransport:
    """Direct HTTPS only: no proxy/env/token/cookie handlers, redirects or retry."""

    def open(self, url, timeout):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "api.finmindtrade.com" or parsed.port is not None or parsed.username is not None:
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
        stage = "https_connect"
        try:
            # Socket waits get the remaining cumulative open budget. Checks are
            # cooperative; DNS/SSL/library calls are not OS-hard preempted.
            connection.timeout = remaining()
            connection.connect()
            connection.sock.settimeout(remaining())
            stage = "https_request"
            # Fixed, non-credential identification; no cookie, token or proxy headers.
            connection.request("GET", parsed.path + "?" + parsed.query,
                               headers={"Accept-Encoding": "identity", "Connection": "close",
                                        "User-Agent": USER_AGENT, "Accept": ACCEPT})
            connection.sock.settimeout(remaining())
            stage = "https_headers"
            response = connection.getresponse()
            remaining()
            stage = "https_wrap"
            return _HTTPSResponse(connection, response)
        except BaseException as exception:
            primary_failure = _failure_values(exception, stage, stage + "_failure")
            operations = (("https_connection_close", connection.close),)
            if response is not None:
                operations = (("https_response_close", response.close),) + operations
            failure = _close_all(operations, primary_failure)
            _raise_failure(failure)


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
class FlowRow:
    date: str
    stock_id: str
    name: str
    buy: int
    sell: int
    source_index: int

    @property
    def net(self):
        return self.buy - self.sell


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
    flow_rows: int
    flow_fields: int
    volume_anchor_fields: int
    net_anchor_fields: int
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


def _iso_date(value, code="price_date"):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _fail(code)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        _fail(code)


def _trading_dates(document):
    """FinMind TaiwanStockTradingDate document -> its in-window dates (documented schema: {date: str});
    no fixed count and no closure inference."""
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("trading_dates_document")
    if type(document["status"]) is not int or document["status"] != 200 or document["msg"] != "success" or type(document["msg"]) is not str:
        _fail("trading_dates_status")
    rows = document["data"]
    if type(rows) is not list or not rows:
        _fail("trading_dates_rows")
    # The documentation does not say whether start_date/end_date filter this dataset, so EVERY returned
    # row is structurally validated (keys, ISO date, unique, ascending) before rows outside the requested
    # window are discarded.
    dates = []
    for row in rows:
        if type(row) is not dict or set(row) != {"date"}:
            _fail("trading_dates_row")
        dates.append(_iso_date(row["date"], "trading_dates_date"))
    if any(earlier >= later for earlier, later in zip(dates, dates[1:])):
        _fail("trading_dates_order")
    return tuple(day for day in dates if WINDOW_START <= day <= WINDOW_END)


def _check_trading_dates(dates, formal_dates):
    """Whole-batch gate on the in-window observed trading days, before any price request."""
    if any(date.fromisoformat(day).weekday() >= 5 for day in dates):
        _fail("trading_dates_weekday")
    if any(cutoff not in dates for cutoff in CUTOFFS):
        _fail("trading_dates_cutoff")
    # The observed days must be exactly the formal 24 days: nothing missing, nothing extra,
    # no closure inferred from a missing row.
    if tuple(dates) != formal_dates:
        _fail("trading_dates_formal_mismatch")


def _prices(document, symbol, dates, source_index, check_roots):
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("price_document")
    if type(document["status"]) is not int or document["status"] != 200 or document["msg"] != "success" or type(document["msg"]) is not str:
        _fail("price_document_status")
    if type(document["data"]) is not list or len(document["data"]) != len(dates):
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


def _flows(document, symbol, dates, source_index, check_roots):
    """FinMind TaiwanStockInstitutionalInvestorsBuySell document -> FlowRow tuple (date, name order).

    Exactly the five documented ``name`` values per trading day, every day, each once; zero
    buy/sell is a normal value and is kept. Nothing is defaulted, skipped or aggregated here."""
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("flow_document")
    if type(document["status"]) is not int or document["status"] != 200 or document["msg"] != "success" or type(document["msg"]) is not str:
        _fail("flow_document_status")
    if type(document["data"]) is not list or len(document["data"]) != len(FLOW_NAMES) * len(dates):
        _fail("flow_row_count")
    found = {}
    for row in document["data"]:
        if type(row) is not dict or set(row) != {"date", "stock_id", "buy", "sell", "name"}:
            _fail("flow_row_fields")
        observed = _iso_date(row["date"], "flow_date")
        if type(row["stock_id"]) is not str or row["stock_id"] != symbol:
            _fail("flow_stock_id")
        if type(row["name"]) is not str or row["name"] not in FLOW_NAMES:
            _fail("flow_name")
        if observed not in dates:
            _fail("flow_calendar")
        if (observed, row["name"]) in found:
            _fail("flow_duplicate")
        buy = _integer(row["buy"], positive=False)
        sell = _integer(row["sell"], positive=False)
        found[(observed, row["name"])] = FlowRow(observed, symbol, row["name"], buy, sell, source_index)
        # The roots estimate walks every retained object, so checking each of the 840 flow rows
        # would cost quadratic time inside the batch budget. Thirty rows is far below the cap's
        # granularity (the whole body is at most 1 MiB).
        if len(found) % 30 == 0:
            check_roots(document, found, row, buy, sell)
    if set(found) != {(day, name) for day in dates for name in FLOW_NAMES}:
        _fail("flow_incomplete")
    return tuple(found[(day, name)] for day in dates for name in FLOW_NAMES)


def _flow_window(rows, cutoff):
    """Five trading days ending on (and including) cutoff -> days and category net shares.

    foreign = Foreign_Investor (foreign dealers excluded), trust = Investment_Trust,
    dealer = Dealer_self + Dealer_Hedging; net = buy - sell; Foreign_Dealer_Self is not counted."""
    days = tuple(sorted({row.date for row in rows if row.date <= cutoff}))[-5:]
    if len(days) != 5 or days[-1] != cutoff:
        _fail("flow_window_incomplete")
    nets = {(row.date, row.name): row.net for row in rows}
    foreign = sum(nets[(day, "Foreign_Investor")] for day in days)
    trust = sum(nets[(day, "Investment_Trust")] for day in days)
    dealer = sum(nets[(day, "Dealer_self")] + nets[(day, "Dealer_Hedging")] for day in days)
    return days, foreign, trust, dealer, foreign + trust + dealer


@dataclass(frozen=True, slots=True)
class FlowVolumeRatio:
    _snapshot: FlowVolumeSource
    _key: tuple

    @property
    def values(self):
        self._snapshot._usable()
        return self._snapshot._ratios[self._key]

    @property
    def provenance(self):
        return self._snapshot.provenance


class FlowVolumeSource:
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
        self._formal_dates, self._volume_anchors, self._net_anchors = _formal_reference(formal_blob)
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
        self._flows = {}
        self._ratios = {}
        self._dates = ()
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

    def _check_failure_roots(self, primary_failure, stage, *stage_roots):
        """Check every failure alias without replacing the saved first failure."""
        try:
            self._check_roots(*stage_roots, primary_failure)
        except BaseException as validation_exception:
            validation = _failure_values(validation_exception, stage, "roots_check_failure")
            count = primary_failure["secondary_validation_count"]
            if count < 2:
                count += 1
                primary_failure["secondary_validation_count"] = count
                prefix = f"secondary_validation_{count}"
                primary_failure[prefix + "_code"] = validation["primary_code"]
                primary_failure[prefix + "_stage"] = stage
                if "estimate_bytes" in validation:
                    primary_failure[prefix + "_estimate_bytes"] = validation["estimate_bytes"]
            else:
                primary_failure["secondary_validation_omitted"] = min(4, primary_failure["secondary_validation_omitted"] + 1)

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
        primary_failure = None
        stage = "capture_open"
        try:
            response = self._transport.open(url, self._remaining())
            stage = "capture_headers"
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
            if not re.fullmatch(r"application/json(?:\s*;\s*charset=utf-8)?", header_values.get("content-type", "").strip(), re.I):
                _fail("content_type")
            stage = "capture_body"
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
            stage = "capture_finalize"
            full_body = bytes(capture_buffer)
            if index == 0:
                source_id, source_version = "finmind_trading_dates", self._policy["trading_date_source"]["version"]
            elif index <= len(SYMBOLS):
                source_id, source_version = "finmind_price/" + SYMBOLS[index - 1], self._policy["price_source"]["version"]
            else:
                source_id = "finmind_institutional_flow/" + SYMBOLS[index - 1 - len(SYMBOLS)]
                source_version = self._policy["flow_source"]["version"]
            receipt = Receipt(source_id, source_version, "GET", url, 200,
                              request_started_utc, datetime.now(timezone.utc).isoformat(),
                              len(full_body), hashlib.sha256(full_body).hexdigest(), True,
                              header_values.get("content-type", ""), encoding, NAMESPACE, POLICY_SHA256)
            capture = Capture(full_body, receipt)
            self._captures.append(capture)
            self._check_roots(capture_buffer, full_body, receipt)
            return self._capture_ready(capture)
        except BaseException as exception:
            primary_failure = _failure_values(exception, stage)
        finally:
            try:
                operations = () if response is None else (("capture_response_close", response.close),)
                failure = _close_all(operations, primary_failure)
            finally:
                capture_buffer.clear()
            if failure is not None:
                _raise_failure(failure)

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
                document = _json(decoded_text)
                self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
                self._remaining()
                parse_results = _trading_dates(document)
            elif index <= len(SYMBOLS):
                document = _json(decoded_text, price=True)
                self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
                self._remaining()
                symbol = SYMBOLS[index - 1]
                parse_results = _prices(document, symbol, dates, index, self._check_roots)
                # 2026-10-06 is the last formal day; its volume must equal the formal 32.2 anchor exactly.
                if parse_results[-1].date != WINDOW_END or parse_results[-1].volume != self._volume_anchors[symbol]:
                    _fail("volume_anchor_mismatch", source_index=index)
            else:
                document = _json(decoded_text, price=True)
                self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
                self._remaining()
                symbol = SYMBOLS[index - 1 - len(SYMBOLS)]
                parse_results = _flows(document, symbol, dates, index, self._check_roots)
                for cutoff in CUTOFFS:
                    _days, foreign, trust, dealer, total = _flow_window(parse_results, cutoff)
                    if (foreign, trust, dealer, total) != self._net_anchors[(cutoff, symbol)]:
                        _fail("net_anchor_mismatch", source_index=index)
            self._documents.append(_freeze(document))
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            return parse_results
        except BaseException as exception:
            primary_failure = _failure_values(exception, "decode_parse")
            primary_failure["source_index"] = index
            self._check_failure_roots(primary_failure, "parse_failure_roots", full_body, receipt,
                                      decoded_text, document, parse_results, diagnostics, exception)
            _raise_failure(primary_failure)
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
        flows = self._flows
        try:
            dates = self._parse_capture(self._capture(0, TRADING_DATE_URL), 0, None)
            _check_trading_dates(dates, self._formal_dates)  # before any price request
            self._dates = dates
            for index, symbol in enumerate(SYMBOLS, 1):
                results[symbol] = self._parse_capture(self._capture(index, PRICE_URL.format(symbol)), index, dates)
                self._check_roots(pending, results)
            # All seven price documents passed (including the volume anchors) before the first flow request.
            for index, symbol in enumerate(SYMBOLS, 1 + len(SYMBOLS)):
                flows[symbol] = self._parse_capture(self._capture(index, FLOW_URL.format(symbol)), index, dates)
                self._check_roots(pending, results, flows)
            self._remaining()
            self._expiry = min(self._now() + self._lease_seconds, self._batch_deadline)
            self._state = "pending"
            return pending
        except BaseException as exception:
            primary_failure = _failure_values(exception, "batch")
            self._state = "failed"
            primary_failure.update(attempts=len(self._ledger.attempted), raw_bytes=self._raw_bytes)
            diagnostics = {"stage": "batch", **primary_failure}
            self._diagnostics = MappingProxyType(diagnostics)
            self._check_failure_roots(primary_failure, "batch_failure_roots", pending, results, flows, diagnostics, exception)
            diagnostics.update(primary_failure)
            _raise_failure(primary_failure)
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
                                 "flows": MappingProxyType(dict(self._flows)),
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
        days = len(self._dates)  # N formal trading days (calendar_rows = trading-date rows)
        names = len(FLOW_NAMES)
        symbols = len(SYMBOLS)
        if (admission.calendar_rows, admission.price_rows, admission.price_fields,
                admission.flow_rows, admission.flow_fields,
                admission.volume_anchor_fields, admission.net_anchor_fields) != (
                days, symbols * days, 6 * symbols * days,
                names * symbols * days, 2 * names * symbols * days,
                symbols, 4 * symbols * len(CUTOFFS)):
            _fail("oracle_complete_scope")
        hashes = tuple(capture.receipt.canonical_sha256 for capture in self._captures)
        if len(hashes) != REQUEST_COUNT or admission.receipt_sha256s != hashes:
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
            "basis": "provider_reported_net_flow_shares_over_volume_shares",
            "unit_policy": self._policy["unit_policy"],
            "formula_version": FORMULA_VERSION,
            "price_rights": self._policy["price_source"]["rights"],
            "flow_rights": self._policy["flow_source"]["rights"],
            "trading_date_rights": self._policy["trading_date_source"]["rights"],
            "formal_blob": FORMAL_BLOB, "formal_sha256": FORMAL_SHA256,
            "trading_date_version": self._policy["trading_date_source"]["version"],
            "trading_dates": self._dates, "receipts": tuple(c.receipt for c in self._captures),
            "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
            "unsupported": self._policy["unsupported"], "storage": "process_RAM",
            "lease_expires_monotonic": self._expiry,
            "deadline": "cooperative", "retained_roots_estimate_bytes": self._roots_estimate,
            "retained_roots_estimate_is_rss_or_peak": False,
        })

    def get_ratio_inputs(self, symbol, cutoff):
        """The AC1 payload handed to the stage-1 consumer, as an immutable mapping.

        Five trading days of net shares ending on (and including) the cutoff, and the
        twenty trading days of volume ending on (and including) the cutoff, from the
        same admitted snapshot. A window that cannot be filled completely is rejected;
        nothing is shortened, defaulted or borrowed from another day."""
        self._scope(symbol, cutoff)
        bars = tuple(row for row in self._results[symbol] if row.date <= cutoff)[-20:]
        if len(bars) != 20 or bars[-1].date != cutoff:
            _fail("window_incomplete")
        days, foreign, trust, dealer, total = _flow_window(self._flows[symbol], cutoff)
        if days != tuple(bar.date for bar in bars[-5:]):
            _fail("window_misaligned")
        payload = _freeze({
            "formula_version": FORMULA_VERSION,
            "purpose": PURPOSE_STRATEGY_GATE,
            "cutoff_date": cutoff,
            "flow": {
                "unit": "shares", "window_trading_days": 5, "basis": "inclusive_cutoff",
                "window_start": days[0], "window_end": days[-1],
                "foreign_net_shares": foreign, "investment_trust_net_shares": trust,
                "dealer_net_shares": dealer, "total_net_shares": total,
            },
            "volume": {
                "unit": "shares", "window_trading_days": 20, "basis": "inclusive_cutoff",
                "daily": [{"date": bar.date, "shares": bar.volume} for bar in bars],
            },
        })
        self._check_roots(bars, payload)
        return payload

    def ratio(self, symbol, cutoff):
        payload = self.get_ratio_inputs(symbol, cutoff)
        try:
            result = compute_institutional_flow_ratio(payload)
        except InstitutionalFlowRatioError as exception:
            code = exception.code if re.fullmatch(r"[a-z0-9_]{1,64}", exception.code) else "consumer_rejected"
            _fail("consumer_rejected", consumer_code=code)
        flow = payload["flow"]
        volume = payload["volume"]
        values = MappingProxyType({
            "consumer_version": CONSUMER_VERSION, "formula_version": result.formula_version,
            "symbol": symbol, "cutoff": cutoff,
            "flow_window_start": flow["window_start"], "flow_window_end": flow["window_end"],
            "foreign_net_shares": flow["foreign_net_shares"],
            "investment_trust_net_shares": flow["investment_trust_net_shares"],
            "dealer_net_shares": flow["dealer_net_shares"],
            "total_net_shares": result.flow_net_shares,
            "volume_window_start": volume["daily"][0]["date"],
            "volume_window_end": volume["daily"][-1]["date"],
            "volume_shares_sum": result.volume_shares_sum,
            "ratio": Rational.of(result.ratio), "threshold": Rational.of(result.threshold),
            "gate_passed": result.gate_passed,
        })
        self._ratios[(symbol, cutoff)] = values
        self._check_roots(payload, values)
        return FlowVolumeRatio(self, (symbol, cutoff))

    def release(self, *, expired=False):
        self._capture_buffer.clear()
        self._captures.clear()
        self._decoded_texts.clear()
        self._documents.clear()
        self._results.clear()
        self._flows.clear()
        self._ratios.clear()
        self._formal_blob = b""
        self._formal_dates = ()
        self._volume_anchors = MappingProxyType({})
        self._net_anchors = MappingProxyType({})
        self._transport = None
        self._observer_roots = None
        self._dates = ()
        self._state = "expired" if expired else "released"
        # The one-shot ledger is deliberately retained and never reset.


def get_ratio_inputs(snapshot, symbol, cutoff):
    if type(snapshot) is not FlowVolumeSource:
        _fail("snapshot_required")
    return snapshot.get_ratio_inputs(symbol, cutoff)


def institutional_flow_volume_ratio_v1(snapshot, symbol, cutoff):
    if type(snapshot) is not FlowVolumeSource:
        _fail("snapshot_required")
    return snapshot.ratio(symbol, cutoff)
