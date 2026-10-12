"""Issue 9's standalone, one-shot FinMind dealer self/hedging RAM source.

There is no import-time I/O. This module reads neither files nor environment
variables. The caller supplies the independently published canonical policy bytes
together with the expected SHA-256 and byte length (the external pin); nothing here
can derive the pin from the policy it is checking. ``acquire`` returns PENDING,
not usable values: every transport, schema, name, date and anchor gate has passed,
but an independent same-RAM oracle must still admit the whole batch before any
consumer can read it. Boundary transports do not demonstrate source truth.

Every capture comes from api.finmindtrade.com: exactly seven GETs of
``TaiwanStockInstitutionalInvestorsBuySell`` (one per symbol, ascending, no
calendar GET). Each symbol-date must carry exactly the five documented ``name``
rows (``Foreign_Investor``, ``Foreign_Dealer_Self``, ``Investment_Trust``,
``Dealer_self``, ``Dealer_Hedging``) and the date set must equal the six fixed
SOURCE_REGISTRY 31.2 trading days (2026-09-29 is anchor-only). FinMind has no net
column; a net is the local value ``buy - sell`` and every step is signed-int64
bounded. The whole batch is also checked against the 56 five-session net anchors of
the policy (SOURCE_REGISTRY 47.6, official TPEx CSV, shares); a mismatch rejects
all seven. The policy's zero-shape comparison (SOURCE_REGISTRY 46.5) is RECORDED
only and never rejects (late bookings may legitimately add equal buy and sell).

The default transport is direct stdlib HTTPS. It requires a FinancialStart and a
matching ExecutionBinding from a separately reviewed explicit Issue 9 seal. These
declarations do not authenticate GitHub/runtime identity; the sole QA
launcher/global review must independently establish them. QA must differ from every
seal role and the roles must be pairwise distinct. The RAM quota survives
release/new source objects in this loaded module; it is not a durable or
cross-process limiter. The external one-shot seal remains authoritative.

Lifecycle: new -> acquiring -> pending -> (admit_independent_verification) ->
available -> released, with failed on the first failure and expired only when the
lifecycle owner calls ``release(expired=True)``: the pinned policy holds the
originals until process exit, so there is no clock-based lease and any caller
``lease_seconds`` is refused. Any attempted GET is SPENT; nothing is retried. The
values are the API's values at acquisition time (not PIT).

Trace selectors (sys.settrace can observe the unmodified default path):
  _capture: capture_buffer while reading; full_body and receipt before return.
  _capture_ready: capture, full_body, receipt BEFORE any decoding/parsing.
  _parse_capture: full_body, receipt, decoded_text, document, parse_results,
                  diagnostics (including exceptional exits).
  _day_records: document, parsed during whole-document validation/failure.
  acquire: exception, diagnostics, pending, results on the failure path.
``inspection`` exposes immutable original bytes/receipts/parsed observations in
RAM for the independent oracle. ``release`` clears owned roots. QA must also clear
its external trace/oracle/result/exception aliases, disable the trace, and exit.
No disk persistence is implemented.

Limits are cooperative boundary checks with remaining-time I/O budgets, not OS
hard deadlines. The deduplicated supported-object estimate is not RSS or peak.
Cleanup preserves primary_code/primary_stage and separately reports at most two
secondary_cleanup_N_code/stage pairs plus an omitted count. Diagnostics never
retain exception messages/objects, responses, frames or tracebacks. Cleanup-only
failure rejects the batch; successful capture never implies that response or
connection cleanup succeeded.
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
from datetime import date, datetime, timezone
from fractions import Fraction
from types import MappingProxyType
from urllib.parse import urlsplit


NAMESPACE = "issue9-dealer-direction-combos-finmind-v1/qa1"
POLICY_VERSION = "issue9-dealer-direction-combos-finmind-v2"
PURPOSE = "local_personal_noncommercial_dealer_self_hedging_direction_combos"
CONSUMER_VERSION = "dealer-self-hedging-direction-combos-five-session-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
CUTOFF = "2026-10-06"
REQUIRED_DATES = ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
WINDOW_DATES = REQUIRED_DATES[1:]
ANCHOR_ONLY_DATES = REQUIRED_DATES[:1]
ANCHOR_WINDOWS = MappingProxyType({"2026-10-05": REQUIRED_DATES[:5], "2026-10-06": REQUIRED_DATES[1:]})
START_DATE = "2026-09-29"
END_DATE = "2026-10-06"
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
DATASET = "TaiwanStockInstitutionalInvestorsBuySell"
HOST = "api.finmindtrade.com"
URL_TEMPLATE = ENDPOINT + "?dataset=" + DATASET + "&data_id={}&start_date=" + START_DATE + "&end_date=" + END_DATE
URLS = tuple(URL_TEMPLATE.format(symbol) for symbol in SYMBOLS)
NAME_FOREIGN = "Foreign_Investor"
NAME_FOREIGN_DEALER = "Foreign_Dealer_Self"
NAME_TRUST = "Investment_Trust"
NAME_SELF = "Dealer_self"
NAME_HEDGE = "Dealer_Hedging"
NAMES = tuple(sorted((NAME_FOREIGN, NAME_FOREIGN_DEALER, NAME_TRUST, NAME_SELF, NAME_HEDGE)))
ROW_KEYS = ("buy", "date", "name", "sell", "stock_id")
ANCHOR_KEYS = ("dealer_self_plus_hedging", "foreign_investor", "investment_trust", "three_total")
ANCHOR_COUNT = len(ANCHOR_WINDOWS) * len(SYMBOLS) * len(ANCHOR_KEYS)
NAME_ROWS = len(SYMBOLS) * len(REQUIRED_DATES) * len(NAMES)
STOCK_DAYS = len(SYMBOLS) * len(REQUIRED_DATES)
# SOURCE_REGISTRY 46.5 text (predecessor, official TPEx CSV): within the five window dates the only
# zeros among Dealer_self/Dealer_Hedging buy, sell and net of the seven symbols (210 values).
EXPECTED_ZERO_SET = (("2026-10-05", "5274", NAME_SELF, "sell"), ("2026-10-06", "5274", NAME_SELF, "sell"))
USER_AGENT = "stock-lab-issue9-local-ram/1"
ACCEPT = "application/json"
BODY_CAP = 1048576
RAW_CAP = 8388608
ROOTS_CAP = 33554432
REQUEST_SECONDS = 20
BATCH_SECONDS = 180
MAX_ROWS = 10000
INT64_MAX = 9223372036854775807
LEASE_HELD_UNTIL_EXIT = "held until process exit"
SESSION_ID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
MODEL_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
SEAL_COMMENT_PATTERN = r"https://github\.com/YiCheng0608/stock-lab/issues/9#issuecomment-([0-9]+)"
SEAL_COMMENT_FLOOR = 6124225468  # the external policy draft; a seal must be newer than the policy it binds

_ANCHOR_VALUE_SHAPE = {key: int for key in ANCHOR_KEYS}
REQUIRED_UNSUPPORTED = frozenset(("historical_pit", "publication_time", "first_availability", "revision_guarantee", "raw_disk_storage",
                                  "cross_process", "db", "redistribution", "mirror"))

# A schema, not a bundled policy or a source of expected values. Dynamic nested maps are `dict` and are
# checked explicitly in _check_policy_semantics.
_POLICY_SHAPE = {
    "ac_revision": str,
    "acquisition": {
        "accept": str, "accept_encoding": str, "attempted_is_spent": bool, "batch_seconds": int,
        "body_cap_bytes": int, "connection": str, "credentials": str, "deadline": str, "max_gets": int,
        "namespace": str, "order": str, "per_source_max_gets": int, "redirects": int, "request_seconds": int,
        "retained_roots_estimate_cap_bytes": int, "retries": int, "stop_on_first_failure": bool,
        "total_raw_cap_bytes": int, "user_agent": str,
    },
    "anchor_only_dates": (str, 1),
    "anchors": {
        "formal_blob": str, "formal_blob_sha256": str, "formal_section": str, "gate": str,
        "mapping": {key: str for key in ANCHOR_KEYS}, "values": dict, "windows": dict,
    },
    "calendar": {"calendar_gets": int, "required_returned_dates": (str, 6), "rule": str, "source": str},
    "consumer": {"failure": str, "per_symbol": str, "trace": str, "version": str},
    "cutoff": str, "lease": str, "first_availability": str, "instrument_type": str, "issue": int,
    "lifecycle": str, "market": str, "profile": str, "publication_time": str,
    "record_only_comparison": {"expected_zero_set": str, "gate": bool, "on_mismatch": str, "source": str},
    "response_shape": {key: str for key in (
        "content_encoding", "content_type", "duplicate_identity_headers", "encoding", "framing",
        "location", "set_cookie", "status")},
    "revision_time": str,
    "row_schema": {
        "buy_sell": str, "date": str, "envelope": str, "extra_keys": str, "keys": (str, 5),
        "names": (str, 5), "names_rule": str, "net": str, "stock_id": str, "value_label": str,
    },
    "source": {
        "dataset": str, "documentation": str, "end_date": str, "endpoint": str, "method": str,
        "provider": str, "query_order": (str, 4), "rights": str, "start_date": str, "urls": (str, 7),
    },
    "source_use": str, "storage": str, "symbols": (str, 7),
    "unit_policy": {"provider_literal_unit_annotation": bool, "unit": str, "verification": str},
    "unsupported": (str, None),
    "version": str,
    "window_dates": (str, 5),
}


class SourceError(ValueError):
    """Diagnostics contain only plain nonfinancial scalar metadata."""

    def __init__(self, code, **diagnostics):
        self.code = code
        self.diagnostics = MappingProxyType({"code": code, **diagnostics})
        super().__init__(code)


def _fail(code, **diagnostics):
    raise SourceError(code, **diagnostics)


def _label(value, default):
    return value if type(value) is str and re.fullmatch(r"[a-z0-9_]{1,64}", value) else default


def _failure_values(exception, stage, fallback="transport_or_parse_failure"):
    """Copy only bounded plain metadata; never message/args/object chains."""
    original = exception.diagnostics if isinstance(exception, SourceError) else {}
    code = _label(exception.code, fallback) if isinstance(exception, SourceError) else fallback
    values = {"code": code, "primary_code": code,
              "primary_stage": _label(original.get("primary_stage"), stage),
              "secondary_cleanup_count": 0, "secondary_cleanup_omitted": 0,
              "secondary_validation_count": 0, "secondary_validation_omitted": 0}
    for name in ("source_index", "estimate_bytes", "attempts", "raw_bytes", "mismatch_count"):
        value = original.get(name)
        if type(value) is int and 0 <= value <= sys.maxsize:
            values[name] = value
    first = original.get("first_label")
    if type(first) is str and re.fullmatch(r"[0-9A-Za-z_/-]{1,64}", first):
        values["first_label"] = first
    for kind in ("cleanup", "validation"):
        prefix = "secondary_" + kind
        count = original.get(prefix + "_count", 0)
        if type(count) is int and 0 <= count <= 2:
            for index in range(1, count + 1):
                item = f"{prefix}_{index}"
                values[item + "_code"] = _label(original.get(item + "_code"), kind + "_failure")
                values[item + "_stage"] = _label(original.get(item + "_stage"), kind)
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


def _float(_):
    # Every admitted number (buy, sell, status, policy integers) is an integer literal.
    _fail("float_json_number")


def _json(text):
    return json.loads(text, object_pairs_hook=_unique_pairs, parse_float=_float, parse_constant=_nonfinite)


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _shape(value, schema):
    if isinstance(schema, dict):
        if type(value) is not dict or value.keys() != schema.keys():
            _fail("policy_keys")
        for key in schema:
            _shape(value[key], schema[key])
    elif isinstance(schema, tuple):
        item_type, count = schema
        if type(value) is not list or (count is None and not value) or (count is not None and len(value) != count):
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


def _bounded(value, code="arithmetic_int64_overflow"):
    if type(value) is not int or not -INT64_MAX - 1 <= value <= INT64_MAX:
        _fail(code)
    return value


def _check_policy_semantics(policy):
    """Cross-check the pinned policy against this module's constants; text fields are not compared."""
    acquisition = policy["acquisition"]
    expected = {"accept": ACCEPT, "accept_encoding": "identity", "attempted_is_spent": True,
                "batch_seconds": BATCH_SECONDS, "body_cap_bytes": BODY_CAP, "connection": "close",
                "max_gets": 7, "namespace": NAMESPACE, "per_source_max_gets": 1, "redirects": 0,
                "request_seconds": REQUEST_SECONDS, "retained_roots_estimate_cap_bytes": ROOTS_CAP,
                "retries": 0, "stop_on_first_failure": True, "total_raw_cap_bytes": RAW_CAP,
                "user_agent": USER_AGENT}
    for key, value in expected.items():
        if type(acquisition[key]) is not type(value) or acquisition[key] != value:
            _fail("policy_acquisition")
    source = policy["source"]
    source_expected = {"dataset": DATASET, "end_date": END_DATE, "endpoint": ENDPOINT, "method": "GET",
                       "provider": "FinMind", "start_date": START_DATE}
    if any(source[key] != value for key, value in source_expected.items()):
        _fail("policy_source")
    if tuple(source["query_order"]) != ("dataset", "data_id", "start_date", "end_date") or tuple(source["urls"]) != URLS:
        _fail("policy_source")
    row_schema = policy["row_schema"]
    if tuple(row_schema["keys"]) != ROW_KEYS or tuple(row_schema["names"]) != NAMES:
        _fail("policy_row_schema")
    if (policy["version"], policy["source_use"], policy["cutoff"], policy["issue"], policy["ac_revision"]) != (
            POLICY_VERSION, PURPOSE, CUTOFF, 9, "2a"):
        _fail("policy_identity")
    if tuple(policy["symbols"]) != SYMBOLS or tuple(policy["window_dates"]) != WINDOW_DATES \
            or tuple(policy["anchor_only_dates"]) != ANCHOR_ONLY_DATES:
        _fail("policy_scope")
    calendar = policy["calendar"]
    if type(calendar["calendar_gets"]) is not int or calendar["calendar_gets"] != 0 \
            or tuple(calendar["required_returned_dates"]) != REQUIRED_DATES:
        _fail("policy_calendar")
    if policy["record_only_comparison"]["gate"] is not False:
        _fail("policy_record_only")
    if policy["consumer"]["version"] != CONSUMER_VERSION:
        _fail("policy_consumer")
    if policy["lease"] != LEASE_HELD_UNTIL_EXIT:
        _fail("policy_lease")
    # Fields the consumer displays or relies on: a policy cannot relabel the unit, the storage or the unknowns.
    fixed = {"market": "TW/TPEx", "instrument_type": "ordinary_stock", "storage": "process_RAM", "profile": "free_public_local",
             "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown"}
    if any(policy[key] != value for key, value in fixed.items()):
        _fail("policy_fixed_fields")
    if policy["unit_policy"]["unit"] != "shares" or policy["unit_policy"]["provider_literal_unit_annotation"] is not False:
        _fail("policy_unit")
    if not REQUIRED_UNSUPPORTED <= set(policy["unsupported"]):
        _fail("policy_unsupported")
    anchors = policy["anchors"]
    windows = anchors["windows"]
    if set(windows) != set(ANCHOR_WINDOWS) or any(tuple(windows[end]) != ANCHOR_WINDOWS[end] for end in ANCHOR_WINDOWS):
        _fail("policy_anchor_windows")
    values = anchors["values"]
    if type(values) is not dict or set(values) != set(ANCHOR_WINDOWS):
        _fail("policy_anchor_values")
    for end in ANCHOR_WINDOWS:
        per_symbol = values[end]
        if type(per_symbol) is not dict or tuple(sorted(per_symbol)) != SYMBOLS:
            _fail("policy_anchor_values")
        for symbol in SYMBOLS:
            entry = per_symbol[symbol]
            _shape(entry, _ANCHOR_VALUE_SHAPE)
            for key in ANCHOR_KEYS:
                _bounded(entry[key], "policy_anchor_values")
            if entry["foreign_investor"] + entry["investment_trust"] + entry["dealer_self_plus_hedging"] != entry["three_total"]:
                _fail("policy_anchor_total")
    if not re.fullmatch(r"[0-9a-f]{64}", anchors["formal_blob_sha256"]):
        _fail("policy_anchor_blob")


def validate_policy(policy_canonical, expected_policy_sha256, expected_policy_bytes):
    """Require the independently supplied exact canonical bytes, external SHA-256 and byte length."""
    if type(policy_canonical) is not bytes or type(expected_policy_sha256) is not str \
            or type(expected_policy_bytes) is not int or isinstance(expected_policy_bytes, bool):
        _fail("policy_input_type")
    if re.fullmatch(r"[0-9a-f]{64}", expected_policy_sha256) is None or expected_policy_bytes <= 0:
        _fail("policy_pin_form")
    if hashlib.sha256(policy_canonical).hexdigest() != expected_policy_sha256 or len(policy_canonical) != expected_policy_bytes:
        _fail("policy_pin")
    try:
        policy = _json(policy_canonical.decode("utf-8"))
        canonical = _canonical(policy)
    except SourceError:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError):
        _fail("policy_encoding")
    if canonical != policy_canonical:
        _fail("policy_canonical_mismatch")
    _shape(policy, _POLICY_SHAPE)
    _check_policy_semantics(policy)
    return _freeze(policy)


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    holder_session_id: str
    model: str
    reasoning_effort: str
    candidate_sha: str
    loaded_source_sha256: str
    script_sha256: str
    native_command: str


@dataclass(frozen=True, slots=True)
class FinancialStart:
    version: str
    issuer_session_id: str
    coordinator_session_ids: tuple
    implementer_session_ids: tuple
    namespace: str
    policy_sha256: str
    seal_comment_url: str
    binding: ExecutionBinding
    authorized: bool
    whole_batch: bool


def _financial_start(start, binding, policy_sha256):
    if type(start) is not FinancialStart or type(binding) is not ExecutionBinding:
        _fail("financial_start_required")
    if type(start.binding) is not ExecutionBinding:
        _fail("financial_binding_type")
    for item in fields(binding):
        if type(getattr(binding, item.name)) is not str or not getattr(binding, item.name):
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
    if (start.version != "issue9-financial-start-v1" or start.namespace != NAMESPACE
            or start.policy_sha256 != policy_sha256):
        _fail("financial_start_scope")
    # Issuer/coordinator/implementer identities come from the seal and are checked by the QA caller
    # against the Issue receipts; this module pins none.
    roles = (start.issuer_session_id,) + start.coordinator_session_ids + start.implementer_session_ids
    if any(not re.fullmatch(SESSION_ID_PATTERN, part) for part in roles) or len(set(roles)) != len(roles):
        _fail("financial_start_scope")
    if binding.reasoning_effort != "xhigh" or not re.fullmatch(SESSION_ID_PATTERN, binding.holder_session_id) \
            or not re.fullmatch(MODEL_PATTERN, binding.model):
        _fail("financial_qa_identity")
    if binding.holder_session_id in roles:
        _fail("financial_qa_identity")
    if not re.fullmatch(r"[0-9a-f]{40}", binding.candidate_sha):
        _fail("financial_candidate")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in (binding.loaded_source_sha256, binding.script_sha256)):
        _fail("financial_script_binding")
    match = re.fullmatch(SEAL_COMMENT_PATTERN, start.seal_comment_url)
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
        return tuple(range(len(self._attempted), len(SYMBOLS)))

    def begin(self):
        if self._begun or self._attempted:
            _fail("quota_spent")
        self._begun = True

    def charge(self, index):
        if not self._begun or type(index) is not int or index != len(self._attempted) or index >= len(SYMBOLS):
            _fail("quota_order")
        self._attempted.append(index)  # SPENT before open, including open failure.


_REAL_LEDGER = None

# Captured at import: the stdlib class is only valid while http.client still binds this very object under
# its own name (its __init__ rebinds itself by module-global name, so a replaced name breaks it opaquely).
_NATIVE_HTTPS_CONNECTION = http.client.HTTPSConnection


def _native_transport_intact():
    current = http.client.HTTPSConnection
    return (current is _NATIVE_HTTPS_CONNECTION and getattr(current, "__module__", None) == "http.client"
            and getattr(current, "__qualname__", None) == "HTTPSConnection")


def native_connection(host, timeout):
    """Direct stdlib HTTPS connection; construction never connects.

    An auditor wraps it by composition through ``connection_factory`` instead of replacing the class;
    a replaced class is refused before anything is spent whether or not a factory is supplied.
    """
    if not _native_transport_intact():
        _fail("transport_class_replaced")
    return _NATIVE_HTTPS_CONNECTION(host, timeout=timeout, context=ssl.create_default_context())


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

    def __init__(self, connection_factory=None):
        self._connection_factory = connection_factory

    def open(self, url, timeout):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != HOST or parsed.port is not None or parsed.username is not None:
            _fail("transport_url")
        factory = self._connection_factory or native_connection
        connection = factory(parsed.hostname, timeout)
        response = None
        deadline = time.monotonic() + timeout

        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                _fail("cooperative_deadline")
            return budget
        stage = "https_connect"
        try:
            # Socket waits get the remaining cumulative open budget. Checks are cooperative;
            # DNS/SSL/library calls are not OS-hard preempted.
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
    def canonical_bytes(self):
        return _canonical({f.name: getattr(self, f.name) for f in fields(self)})

    @property
    def canonical_sha256(self):
        return hashlib.sha256(self.canonical_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class Capture:
    body: bytes
    receipt: Receipt


@dataclass(frozen=True, slots=True)
class NameRow:
    """One original FinMind row: values exactly as returned, plus its ordinal in the response ``data``."""
    row_index: int
    key_order: tuple
    date: str
    stock_id: str
    name: str
    buy: int
    sell: int


@dataclass(frozen=True, slots=True)
class DayRecord:
    """The five name rows of one symbol-date, in the original response order."""
    symbol: str
    date: str
    source_index: int
    rows: tuple

    def row(self, name):
        for item in self.rows:
            if item.name == name:
                return item
        _fail("name_missing")


@dataclass(frozen=True, slots=True)
class OracleAdmission:
    """Independent source-oracle assertion; consumer arithmetic is checked next."""
    namespace: str
    policy_sha256: str
    holder_session_id: str
    candidate_sha: str
    script_sha256: str
    receipt_sha256s: tuple
    name_rows: int
    stock_days: int
    anchor_values: int
    record_only_matches: bool
    independent: bool


def retained_roots_estimate(*roots):
    """Deduplicated declared supported roots; not OS/RSS/peak measurement."""
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


def _iso_date(value, code="row_date"):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _fail(code)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        _fail(code)


def _integer(value):
    if type(value) is not int or not 0 <= value <= INT64_MAX:
        _fail("canonical_int64")
    return value


def _day_records(document, symbol, source_index, check_roots):
    """Validate EVERY returned row first, then keep only the required dates; return symbol-date records."""
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("document_envelope")
    if type(document["status"]) is not int or document["status"] != 200 or type(document["msg"]) is not str \
            or document["msg"] != "success":
        _fail("document_status")
    rows = document["data"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_ROWS:
        _fail("document_rows")
    parsed = []
    for row_index, row in enumerate(rows):
        if type(row) is not dict or set(row) != set(ROW_KEYS):
            _fail("row_fields")
        observed = _iso_date(row["date"])
        if type(row["stock_id"]) is not str or row["stock_id"] != symbol:
            _fail("row_stock_id")
        if type(row["name"]) is not str:
            _fail("row_name_type")
        buy, sell = _integer(row["buy"]), _integer(row["sell"])
        parsed.append(NameRow(row_index, tuple(row), observed, row["stock_id"], row["name"], buy, sell))
    check_roots(document, parsed)  # the 1 MiB body cap bounds the row count, so once per document is enough
    # Only now are rows outside start_date..end_date discarded, so whether FinMind filters by the requested
    # range never changes the outcome.
    kept = [item for item in parsed if START_DATE <= item.date <= END_DATE]
    for item in kept:
        if item.name not in NAMES:
            _fail("name_not_admitted")
    grouped = {}
    for item in kept:
        day = grouped.setdefault(item.date, {})
        if item.name in day:
            _fail("duplicate_symbol_date_name")
        day[item.name] = item
    if set(grouped) != set(REQUIRED_DATES):
        _fail("calendar_dates_mismatch")
    for day in grouped.values():
        if set(day) != set(NAMES):
            _fail("name_missing")
    result = []
    for day in REQUIRED_DATES:
        ordered = tuple(sorted(grouped[day].values(), key=lambda item: item.row_index))
        result.append(DayRecord(symbol, day, source_index, ordered))
    return tuple(result)


def window_nets(records, names):
    """Per-name sums of the local net (buy - sell), each step signed-int64 bounded; keyed by name."""
    totals = {}
    for name in names:
        running = 0
        for record in records:
            row = record.row(name)
            running = _bounded(running + _bounded(row.buy - row.sell))
        totals[name] = running
    return totals


def anchor_comparison(policy, results):
    """Compare all 56 policy anchors with the values recomputed from the captured rows."""
    mismatches = []
    checked = 0
    for end in ANCHOR_WINDOWS:
        for symbol in SYMBOLS:
            records = tuple(record for record in results[symbol] if record.date in ANCHOR_WINDOWS[end])
            if tuple(record.date for record in records) != ANCHOR_WINDOWS[end]:
                _fail("anchor_window_dates")
            sums = window_nets(records, (NAME_FOREIGN, NAME_TRUST, NAME_SELF, NAME_HEDGE))
            dealer = _bounded(sums[NAME_SELF] + sums[NAME_HEDGE])
            total = _bounded(_bounded(sums[NAME_FOREIGN] + sums[NAME_TRUST]) + dealer)
            actual = {"dealer_self_plus_hedging": dealer, "foreign_investor": sums[NAME_FOREIGN],
                      "investment_trust": sums[NAME_TRUST], "three_total": total}
            for key in ANCHOR_KEYS:
                checked += 1
                if actual[key] != policy["anchors"]["values"][end][symbol][key]:
                    mismatches.append(end + "/" + symbol + "/" + key)
    return checked, tuple(mismatches)


def record_only_comparison(results):
    """SOURCE_REGISTRY 46.5 zero shape: recorded for the receipt, never a gate (late bookings may add gross)."""
    observed = []
    for symbol in SYMBOLS:
        for record in results[symbol]:
            if record.date not in WINDOW_DATES:
                continue
            for name in (NAME_SELF, NAME_HEDGE):
                row = record.row(name)
                for metric, value in (("buy", row.buy), ("sell", row.sell), ("net", row.buy - row.sell)):
                    if value == 0:
                        observed.append((record.date, symbol, name, metric))
    observed = tuple(sorted(observed))
    expected = tuple(sorted(EXPECTED_ZERO_SET))
    return MappingProxyType({
        "compared_values": len(SYMBOLS) * len(WINDOW_DATES) * 2 * 3,
        "expected_zero_set": expected, "observed_zero_set": observed,
        "only_expected": tuple(item for item in expected if item not in observed),
        "only_observed": tuple(item for item in observed if item not in expected),
        "matches": observed == expected, "gate": False})


class DealerDirectionSource:
    """Only snapshot object; pending/failed/expired/released are consumer-inert."""

    def __init__(self, *, policy_canonical, expected_policy_sha256, expected_policy_bytes,
                 purpose=PURPOSE, transport=None, ledger=None,
                 financial_start=None, execution_binding=None,
                 connection_factory=None,
                 clock=time.monotonic, lease_seconds=None, observer_roots=None):
        self._policy = validate_policy(policy_canonical, expected_policy_sha256, expected_policy_bytes)
        self._policy_sha256 = expected_policy_sha256
        if type(purpose) is not str or purpose != PURPOSE:
            _fail("unsupported_purpose")
        if lease_seconds is not None:
            _fail("lease_policy_conflict")  # the pinned policy holds the originals until process exit: no caller lease exists
        if not callable(clock) or (observer_roots is not None and not callable(observer_roots)) \
                or (connection_factory is not None and not callable(connection_factory)):
            _fail("clock_or_roots_type")
        self._real = transport is None
        if self._real or isinstance(transport, _HTTPSTransport):
            _financial_start(financial_start, execution_binding, expected_policy_sha256)
            if transport is not None or ledger is not None:
                _fail("default_transport_required_for_financial")
        else:
            if financial_start is not None or execution_binding is not None or connection_factory is not None:
                _fail("financial_start_with_boundary_transport")
        if not self._real and (type(ledger) is not AttemptLedger or ledger.namespace != NAMESPACE):
            _fail("boundary_ledger_required")
        self._binding = execution_binding
        self._transport = _HTTPSTransport(connection_factory) if self._real else transport
        self._ledger = ledger
        self._clock = clock
        self._observer_roots = observer_roots
        self._last_clock = None
        self._batch_deadline = self._request_deadline = None
        self._state = "new"
        self._raw_bytes = 0
        self._captures = []
        self._decoded_texts = []
        self._documents = []
        self._results = {}
        self._comparison = MappingProxyType({})
        self._anchor_checked = 0
        self._capture_buffer = bytearray()
        self._diagnostics = MappingProxyType({})
        self._roots_estimate = 0
        self._check_roots()

    @property
    def state(self):
        return self._state

    @property
    def ledger(self):
        return self._ledger

    @property
    def diagnostics(self):
        return self._diagnostics

    @property
    def policy_sha256(self):
        return self._policy_sha256

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
                if key in header_values and key in ("content-length", "content-encoding", "transfer-encoding", "content-type", "location"):
                    _fail("duplicate_framing_header")
                header_values[key] = value
            if "location" in header_values:
                _fail("http_redirect")
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
            content_type = header_values.get("content-type", "").strip()
            if len(content_type) > 128 or not re.fullmatch(r'application/json(?:\s*;\s*charset=("?)utf-8\1)?', content_type, re.I):
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
            receipt = Receipt("finmind_institutional_investors/" + SYMBOLS[index], POLICY_VERSION, "GET", url, 200,
                              request_started_utc, datetime.now(timezone.utc).isoformat(),
                              len(full_body), hashlib.sha256(full_body).hexdigest(), True,
                              content_type, encoding, NAMESPACE, self._policy_sha256)
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

    def _parse_capture(self, capture, index):
        full_body, receipt = capture.body, capture.receipt
        decoded_text = document = parse_results = None
        diagnostics = {"source_index": index, "stage": "decode_parse"}
        try:
            self._remaining()
            if full_body.startswith(b"\xef\xbb\xbf"):
                _fail("bom_rejected")
            decoded_text = full_body.decode("utf-8")
            self._decoded_texts.append(decoded_text)
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            document = _json(decoded_text)
            self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
            self._remaining()
            parse_results = _day_records(document, SYMBOLS[index], index, self._check_roots)
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
            if not _native_transport_intact():
                _fail("transport_class_replaced")  # before anything is spent, with or without a connection_factory
            if _REAL_LEDGER is None:
                _REAL_LEDGER = AttemptLedger(NAMESPACE)
            self._ledger = _REAL_LEDGER
        try:
            self._ledger.begin()
        except SourceError as exception:
            # Nothing was requested, but the one-shot quota is gone: report FAILED (not a retryable `new`).
            primary_failure = _failure_values(exception, "quota")
            self._state = "failed"
            primary_failure.update(attempts=0, raw_bytes=0)  # this batch requested nothing
            self._diagnostics = MappingProxyType({"stage": "quota", **primary_failure})
            _raise_failure(primary_failure)
        self._state = "acquiring"
        pending = self
        results = self._results
        try:
            self._batch_deadline = self._now() + BATCH_SECONDS
            for index, symbol in enumerate(SYMBOLS):
                results[symbol] = self._parse_capture(self._capture(index, URLS[index]), index)
                self._check_roots(pending, results)
            checked, mismatches = anchor_comparison(self._policy, results)
            if checked != ANCHOR_COUNT:
                _fail("anchor_count")
            if mismatches:
                _fail("anchor_mismatch", mismatch_count=len(mismatches), first_label=mismatches[0])
            self._anchor_checked = checked
            self._comparison = record_only_comparison(results)
            self._remaining()
            self._state = "pending"
            return pending
        except BaseException as exception:
            primary_failure = _failure_values(exception, "batch")
            self._state = "failed"
            primary_failure.update(attempts=len(self._ledger.attempted), raw_bytes=self._raw_bytes)
            diagnostics = {"stage": "batch", **primary_failure}
            self._diagnostics = MappingProxyType(diagnostics)
            self._check_failure_roots(primary_failure, "batch_failure_roots", pending, results, diagnostics, exception)
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
                                 "record_only_comparison": self._comparison,
                                 "diagnostics": self._diagnostics,
                                 "retained_roots_estimate_bytes": self._roots_estimate})

    def admit_independent_verification(self, admission):
        if self.state != "pending" or type(admission) is not OracleAdmission:
            _fail("oracle_pending_required")
        for item in fields(admission):
            value = getattr(admission, item.name)
            expected = tuple if item.name == "receipt_sha256s" else bool if item.name in ("independent", "record_only_matches") \
                else int if item.name in ("name_rows", "stock_days", "anchor_values") else str
            if type(value) is not expected:
                _fail("oracle_type")
        if admission.independent is not True or (admission.namespace, admission.policy_sha256) != (NAMESPACE, self._policy_sha256):
            _fail("oracle_scope")
        if any(type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value) for value in admission.receipt_sha256s):
            _fail("oracle_receipt_type")
        if (admission.name_rows, admission.stock_days, admission.anchor_values) != (NAME_ROWS, STOCK_DAYS, ANCHOR_COUNT):
            _fail("oracle_complete_scope")
        hashes = tuple(capture.receipt.canonical_sha256 for capture in self._captures)
        if len(hashes) != len(SYMBOLS) or admission.receipt_sha256s != hashes:
            _fail("oracle_capture_binding")
        if admission.record_only_matches is not self._comparison["matches"]:
            _fail("oracle_record_only")
        if self._real and (admission.holder_session_id, admission.candidate_sha, admission.script_sha256) != (
                self._binding.holder_session_id, self._binding.candidate_sha, self._binding.script_sha256):
            _fail("oracle_qa_binding")
        self._check_roots(admission)
        self._state = "available"

    def _usable(self):
        if self.state != "available":
            _fail("consumer_unavailable")
        self._check_roots()

    def window_records(self, symbol):
        """The five window-date records of a symbol (the anchor-only date is not exposed)."""
        self._usable()
        if type(symbol) is not str or symbol not in SYMBOLS:
            _fail("unsupported_scope")
        return tuple(record for record in self._results[symbol] if record.date in WINDOW_DATES)

    @property
    def receipts(self):
        self._usable()
        return tuple(capture.receipt for capture in self._captures)

    @property
    def provenance(self):
        self._usable()
        return MappingProxyType({
            "namespace": NAMESPACE, "policy_sha256": self._policy_sha256, "policy_version": POLICY_VERSION,
            "consumer_version": CONSUMER_VERSION, "market": "TW/TPEx", "cutoff": CUTOFF,
            "instrument_type": "ordinary_stock", "source_use": PURPOSE, "dataset": DATASET,
            "unit": self._policy["unit_policy"]["unit"], "rights": self._policy["source"]["rights"],
            "calendar_reference": "SOURCE_REGISTRY 31.2", "calendar_gets": 0,
            "required_dates": REQUIRED_DATES, "window_dates": WINDOW_DATES, "anchor_only_dates": ANCHOR_ONLY_DATES,
            "value_label": self._policy["row_schema"]["value_label"],
            "anchors_checked": self._anchor_checked, "record_only_comparison": self._comparison,
            "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
            "unsupported": self._policy["unsupported"], "storage": "process_RAM",
            "lease_policy": self._policy["lease"], "deadline": "cooperative",
            "retained_roots_estimate_bytes": self._roots_estimate,
            "retained_roots_estimate_is_rss_or_peak": False,
        })

    def release(self, *, expired=False):
        """Clear every owned root. ``expired=True`` is the only way into ``expired``: the lifecycle owner declares it."""
        self._capture_buffer.clear()
        self._captures.clear()
        self._decoded_texts.clear()
        self._documents.clear()
        self._results.clear()
        self._comparison = MappingProxyType({})
        self._transport = None
        self._observer_roots = None
        self._state = "expired" if expired else "released"
        # The one-shot ledger is deliberately retained and never reset.
