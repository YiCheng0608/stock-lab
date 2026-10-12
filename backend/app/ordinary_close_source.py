"""Issue 7's one-shot FinMind ordinary-close source and its private saved-close bundle.

This is the second consumer of the issue 32 acquisition contract. It fetches one
FinMind ``TaiwanStockTradingDate`` document and seven ``TaiwanStockPrice``
documents for ONE parameterized cutoff, validates them with the issue 32 helpers
(imported from ``ohlcv_history_source``, never copied back into or edited in that
file; ``IMPORTED_HELPERS`` lists every reference), and after the same independent
same-RAM oracle admission keeps only each stock's close for the 60 trading days
ending at the cutoff.

There is no import-time I/O and no environment read at import. ``acquire`` returns
PENDING; only an independent oracle admission (which also binds the SHA-256 of the
canonical closes file) makes ``save`` possible. Disk access exists only in ``save``
(below the single root named by ``STOCK_ORDINARY_CLOSE_PRIVATE_ROOT``; unset means
nothing is written) and in the read-only ``load_saved_closes`` (never fetches, never
falls back to another version).

The default HTTPS path stays closed until the externally issued policy pins
(``POLICY_SHA256`` / ``POLICY_BYTES``) are published: with the pins unset it fails
closed before any seal check, so only synthetic boundary transports run today. Once
set it still requires a FinancialStart and a matching ExecutionBinding from a fresh
explicit issue 7 seal exactly like issue 32, plus the one-shot in-process ledger,
body/aggregate/roots caps, cooperative deadlines and the lease.

Stored per bundle (``<policy_version>/<cutoff>/``): ``closes.json`` holds the
normalized cutoff-inclusive 60-day closes (decimal strings), their dates and counts;
``receipt.json`` holds each GET's URL/status/times/body SHA-256 and bytes, policy and
adapter pins and the limits. Raw bodies and open/high/low/volume/amount are never
stored. Both files are canonical UTF-8 JSON; the 20/21-day windows are the tail of
the 60 rows. The ``date`` fields are Asia/Taipei trading calendar dates; the receipt
times are UTC.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import secrets
import stat
import threading
import time
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from types import MappingProxyType

from . import ohlcv_history_source as _base


SourceError = _base.SourceError
FinancialStart = _base.FinancialStart
ExecutionBinding = _base.ExecutionBinding
Bar = _base.Bar
_fail = _base._fail

NAMESPACE = "issue7-ordinary-close-saved-seven-v1/qa1"
POLICY_VERSION = "issue7-ordinary-close-saved-seven-v1"
PROFILE = "free_public_local"
PURPOSE = "local_personal_noncommercial_private_derived_close_window"
CONSUMER_VERSION = "ordinary-close-saved-window-v1"
STORAGE_SCHEMA = "ordinary-close-saved/v1"
RECEIPT_SCHEMA = "ordinary-close-receipt/v1"
ROOT_ENV = "STOCK_ORDINARY_CLOSE_PRIVATE_ROOT"
MARKET = "TW/TPEx"
INSTRUMENT_TYPE = "ordinary_stock"
IDENTITY_AS_OF = "2026-10-06"
SYMBOLS = _base.SYMBOLS
WINDOW_COUNT = 60
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
TRADING_DATE_URL = ENDPOINT + "?dataset=TaiwanStockTradingDate&start_date={start}&end_date={end}"
PRICE_URL = ENDPOINT + "?dataset=TaiwanStockPrice&data_id={symbol}&start_date={start}&end_date={end}"

# Externally issued policy pin, not yet published: the default HTTPS path fails
# closed (real_pins_unset) until the global publishes the canonical policy.
POLICY_SHA256 = None
POLICY_BYTES = None
# A seal must be a fresh explicit issue 7 comment newer than this one (the stage 1
# dispatch comment). It is a floor, not an authorization.
SEAL_COMMENT_FLOOR = 6124203633
SEAL_VERSION = "issue7-financial-start-v1"
SEAL_URL_PATTERN = r"https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-([0-9]+)"

CLOSES_CAP = 65536
RECEIPT_CAP = 32768
MAX_BUNDLES = 2
MAX_FILES = 4
MAX_TOTAL_BYTES = 196608
CLOSE_SCALE_MAX = 6
CLOSE_TEXT_MAX = 20
CLOSES_FILE = "closes.json"
RECEIPT_FILE = "receipt.json"
LIMITATIONS = (
    "date_is_asia_taipei_trading_calendar_date_not_utc",
    "identity_and_unit_anchored_only_at_2026-10-06",
    "publication_time_first_availability_revision_time_unknown",
    "closes_only_no_open_high_low_volume_amount",
    "raw_body_not_stored_hashes_only",
    "personal_noncommercial_local_use_no_redistribution",
)
REQUIRED_UNSUPPORTED = ("historical_pit", "revision_guarantee", "raw_body_storage", "redistribution",
                        "other_cutoffs")

# Every private issue 32 name this module references; the test locks each one.
IMPORTED_HELPERS = (
    "AttemptLedger", "BATCH_SECONDS", "BODY_CAP", "Bar", "Capture", "ExecutionBinding", "FORMAL_BLOB",
    "FORMAL_SHA256", "FinancialStart", "MODEL_PATTERN", "RAW_CAP", "REQUEST_SECONDS", "ROOTS_CAP",
    "Receipt", "SESSION_ID_PATTERN", "SYMBOLS", "SourceError", "USER_AGENT", "ACCEPT", "_HTTPSTransport",
    "_canonical", "_close_all", "_fail", "_formal_reference", "_failure_values", "_freeze", "_iso_date",
    "_json", "_prices", "_raise_failure", "_shape", "retained_roots_estimate",
)

_BINARY = getattr(os, "O_BINARY", 0)
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_VERSION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CONTENT_TYPE = re.compile(r"application/json(?:\s*;\s*charset=utf-8)?", re.I)
_CLOSE_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{0,5}[1-9])?")
_SOURCE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
_SAVE_LOCK = threading.Lock()
_REAL_LEDGER = None

# A schema, not a bundled policy or a source of expected financial values.
_POLICY_SHAPE = {
    "version": str, "profile": str, "source_use": str, "consumer_version": str,
    "market": str, "instrument_type": str, "symbols": (str, 7),
    "identity_as_of": str, "cutoff": str,
    "window": {"start_date": str, "end_date": str, "beyond_formal_trading_dates": list},
    "price_source": {
        "provider": str, "dataset": str, "endpoint": str, "method": str,
        "query_order": (str, 4), "start_date": str, "end_date": str,
        "fields": {k: str for k in ("open", "high", "low", "close", "volume", "amount")},
        "basis": str, "rights": str,
    },
    "trading_date_source": {
        "provider": str, "dataset": str, "endpoint": str, "url": str, "method": str,
        "format": str, "fields": {"date": str}, "documentation": str, "expected_scope": str,
        "rights": str, "prior_calendar_formal_blob": str, "prior_calendar_formal_sha256": str,
        "prior_verified_counts": {"August": int, "September": int, "October_through_6": int},
        "version": str,
    },
    "response_shape": {k: str for k in (
        "status", "content_type", "framing", "content_encoding", "duplicate_identity_headers",
        "set_cookie", "encoding", "zero_price_rows")},
    "unit_policy": {
        "version": str, "unit_mapping_inference": bool,
        "provider_literal_unit_annotation": bool, "OHLC": str, "volume": str,
        "amount": str, "scale": int, "independent_latest_anchor": str,
        "all_seven_must_match": bool,
    },
    "storage": {
        "kind": str, "schema": str, "root_env": str, "layout": str, "raw_body": str,
        "stored_fields": (str, 2), "max_closes_bytes": int, "max_receipt_bytes": int,
        "max_bundles": int, "max_files": int, "max_total_bytes": int,
    },
    "attribution": str, "publication_time": str, "first_availability": str,
    "revision_time": str, "unsupported": (str, 16),
    "acquisition": {
        "namespace": str, "order": str, "max_gets": int, "per_source_max_gets": int,
        "body_cap_bytes": int, "total_raw_cap_bytes": int,
        "retained_roots_estimate_cap_bytes": int, "request_seconds": int,
        "batch_seconds": int, "deadline": str, "accept_encoding": str,
        "accept": str, "user_agent": str,
        "redirects": int, "retries": int, "stop_on_first_failure": bool,
    },
}

# Leaves of the externally pinned policy that must equal this module's behaviour.
_POLICY_EXPECTED = (
    (("version",), POLICY_VERSION), (("profile",), PROFILE), (("source_use",), PURPOSE),
    (("consumer_version",), CONSUMER_VERSION), (("market",), MARKET),
    (("instrument_type",), INSTRUMENT_TYPE), (("symbols",), SYMBOLS),
    (("identity_as_of",), IDENTITY_AS_OF),
    (("publication_time",), "unknown"), (("first_availability",), "unknown"), (("revision_time",), "unknown"),
    (("price_source", "provider"), "FinMind"), (("price_source", "dataset"), "TaiwanStockPrice"),
    (("price_source", "endpoint"), ENDPOINT), (("price_source", "method"), "GET"),
    (("price_source", "query_order"), ("dataset", "data_id", "start_date", "end_date")),
    (("price_source", "fields", "open"), "open"), (("price_source", "fields", "high"), "max"),
    (("price_source", "fields", "low"), "min"), (("price_source", "fields", "close"), "close"),
    (("price_source", "fields", "volume"), "Trading_Volume"), (("price_source", "fields", "amount"), "Trading_money"),
    (("trading_date_source", "provider"), "FinMind"), (("trading_date_source", "dataset"), "TaiwanStockTradingDate"),
    (("trading_date_source", "endpoint"), ENDPOINT), (("trading_date_source", "method"), "GET"),
    (("trading_date_source", "fields", "date"), "date"),
    (("trading_date_source", "prior_calendar_formal_blob"), _base.FORMAL_BLOB),
    (("trading_date_source", "prior_calendar_formal_sha256"), _base.FORMAL_SHA256),
    (("trading_date_source", "prior_verified_counts", "August"), 21),
    (("trading_date_source", "prior_verified_counts", "September"), 20),
    (("trading_date_source", "prior_verified_counts", "October_through_6"), 4),
    (("unit_policy", "scale"), 1), (("unit_policy", "unit_mapping_inference"), True),
    (("unit_policy", "provider_literal_unit_annotation"), False), (("unit_policy", "all_seven_must_match"), True),
    (("storage", "kind"), "private_local_derived_closes"), (("storage", "schema"), STORAGE_SCHEMA),
    (("storage", "root_env"), ROOT_ENV), (("storage", "raw_body"), "not_stored"),
    (("storage", "stored_fields"), ("date", "close")),
    (("storage", "max_closes_bytes"), CLOSES_CAP), (("storage", "max_receipt_bytes"), RECEIPT_CAP),
    (("storage", "max_bundles"), MAX_BUNDLES), (("storage", "max_files"), MAX_FILES),
    (("storage", "max_total_bytes"), MAX_TOTAL_BYTES),
    (("acquisition", "namespace"), NAMESPACE), (("acquisition", "max_gets"), 8),
    (("acquisition", "per_source_max_gets"), 1), (("acquisition", "body_cap_bytes"), _base.BODY_CAP),
    (("acquisition", "total_raw_cap_bytes"), _base.RAW_CAP),
    (("acquisition", "retained_roots_estimate_cap_bytes"), _base.ROOTS_CAP),
    (("acquisition", "request_seconds"), _base.REQUEST_SECONDS), (("acquisition", "batch_seconds"), _base.BATCH_SECONDS),
    (("acquisition", "deadline"), "cooperative"), (("acquisition", "accept_encoding"), "identity"),
    (("acquisition", "accept"), _base.ACCEPT), (("acquisition", "user_agent"), _base.USER_AGENT),
    (("acquisition", "redirects"), 0), (("acquisition", "retries"), 0),
    (("acquisition", "stop_on_first_failure"), True),
)

_GET_STRINGS = ("source_id", "source_version", "method", "url", "request_started_utc", "observed_utc",
                "body_sha256", "content_type", "content_encoding", "namespace", "policy_sha256", "receipt_sha256")
_GET_SHAPE = {**{key: str for key in _GET_STRINGS}, "status": int, "body_bytes": int, "full_eof": bool}
_RECEIPT_FIELDS = tuple(item.name for item in fields(_base.Receipt))
_RECEIPT_SHAPE = {
    "schema": str, "storage": str, "storage_schema": str, "namespace": str, "purpose": str,
    "consumer_version": str,
    "source_policy": {"version": str, "sha256": str, "bytes": int},
    "trading_date_source_version": str,
    "market": str, "instrument_type": str, "identity_as_of": str,
    "cutoff": str, "window": {"start_date": str, "end_date": str}, "calendar_rows": int,
    "gets": (dict, 8),
    "adapter": {"ordinary_close_source_sha256": str, "ohlcv_history_source_sha256": str},
    "closes": {"file": str, "sha256": str, "bytes": int},
    "saved_at": str, "attribution": str,
    "rights": {"price_source": str, "trading_date_source": str},
    "publication_time": str, "first_availability": str, "revision_time": str,
    "limitations": (str, len(LIMITATIONS)),
}
_CLOSES_SHAPE = {
    "schema": str, "cutoff": str, "count": int, "symbols": (str, 7), "trading_dates": (str, WINDOW_COUNT),
    "counts": {symbol: int for symbol in SYMBOLS}, "closes": {symbol: (list, WINDOW_COUNT) for symbol in SYMBOLS},
}


@dataclass(frozen=True, slots=True)
class Pins:
    """The externally issued canonical-policy pin (digest and exact byte length)."""
    sha256: str
    nbytes: int


@dataclass(frozen=True, slots=True)
class Scope:
    cutoff: str
    window_start: str
    window_end: str
    beyond: tuple


@dataclass(frozen=True, slots=True)
class OracleAdmission:
    """Independent source-oracle assertion; it also binds the canonical closes bytes."""
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
    closes_sha256: str
    independent: bool


@dataclass(frozen=True, slots=True)
class SavedBundle:
    action: str
    policy_version: str
    cutoff: str
    path: str
    closes_sha256: str
    closes_bytes: int
    receipt_sha256: str
    receipt_bytes: int
    saved_at: str


@dataclass(frozen=True, slots=True)
class Close:
    date: str
    text: str
    value: Fraction


@dataclass(frozen=True, slots=True)
class SavedCloses:
    policy_version: str
    cutoff: str
    symbols: tuple
    trading_dates: tuple
    closes: object
    receipt: object
    closes_sha256: str
    receipt_sha256: str

    def window(self, symbol, count):
        """The trailing ``count`` (1..60) rows, e.g. 20 or 21 for the 20/21-day windows."""
        if type(symbol) is not str or symbol not in self.closes:
            _fail("saved_window_scope")
        if type(count) is not int or not 1 <= count <= WINDOW_COUNT:
            _fail("saved_window_scope")
        return self.closes[symbol][-count:]


class AttemptLedger(_base.AttemptLedger):
    """One whole batch per ledger; no reset/release/retry API (issue 32 semantics, issue 7 namespace)."""

    def __init__(self, namespace):
        if namespace != NAMESPACE:
            _fail("quota_namespace")
        self.namespace = namespace
        self._begun = False
        self._attempted = []


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _pins(value):
    if (type(value) is not Pins or type(value.sha256) is not str or not _HEX64.fullmatch(value.sha256)
            or type(value.nbytes) is not int or value.nbytes <= 0):
        _fail("pins_type")
    return value


def _real_pins():
    if POLICY_SHA256 is None or POLICY_BYTES is None:
        _fail("real_pins_unset")
    return _pins(Pins(POLICY_SHA256, POLICY_BYTES))


def validate_policy(policy_canonical, policy_sha256, pins=None):
    """Require the independently supplied exact canonical bytes and the external pin."""
    pins = _real_pins() if pins is None else _pins(pins)
    if type(policy_canonical) is not bytes or type(policy_sha256) is not str:
        _fail("policy_input_type")
    if policy_sha256 != pins.sha256:
        _fail("policy_pin")
    try:
        policy = _base._json(policy_canonical.decode("utf-8"))
        _base._shape(policy, _POLICY_SHAPE)
        canonical = _base._canonical(policy)
    except SourceError:
        raise
    except (ValueError, UnicodeError, TypeError, RecursionError):
        _fail("policy_encoding")
    if (len(canonical) != pins.nbytes or canonical != policy_canonical
            or hashlib.sha256(canonical).hexdigest() != policy_sha256):
        _fail("policy_canonical_mismatch")
    return _base._freeze(policy)


def _policy_scope(policy):
    """Cross-check the pinned policy against this module and derive the parameterized scope."""
    for path, expected in _POLICY_EXPECTED:
        node = policy
        for key in path:
            node = node[key]
        if type(node) is not type(expected) or node != expected:
            _fail("policy_value", field=".".join(path))
    unsupported = policy["unsupported"]
    if any(item not in unsupported for item in REQUIRED_UNSUPPORTED):
        _fail("policy_value", field="unsupported")
    if not policy["attribution"] or len(policy["attribution"]) > 512:
        _fail("policy_value", field="attribution")
    for section in ("price_source", "trading_date_source"):
        if not policy[section]["rights"] or len(policy[section]["rights"]) > 512:
            _fail("policy_value", field=section + ".rights")
    if not _SOURCE_VERSION.fullmatch(policy["trading_date_source"]["version"]):
        _fail("policy_value", field="trading_date_source.version")
    cutoff = _base._iso_date(policy["cutoff"], "policy_cutoff")
    start = _base._iso_date(policy["window"]["start_date"], "policy_window")
    end = _base._iso_date(policy["window"]["end_date"], "policy_window")
    if not start < cutoff <= end or end < IDENTITY_AS_OF:
        _fail("policy_window")
    beyond = tuple(_base._iso_date(day, "policy_beyond") for day in policy["window"]["beyond_formal_trading_dates"])
    if (any(date.fromisoformat(day).weekday() >= 5 for day in beyond) or list(beyond) != sorted(set(beyond))
            or any(day <= IDENTITY_AS_OF or day > end for day in beyond)):
        _fail("policy_beyond")
    for field, actual, expected in (
            ("price_source.start_date", policy["price_source"]["start_date"], start),
            ("price_source.end_date", policy["price_source"]["end_date"], end),
            ("trading_date_source.url", policy["trading_date_source"]["url"],
             TRADING_DATE_URL.format(start=start, end=end))):
        if actual != expected:
            _fail("policy_value", field=field)
    return Scope(cutoff, start, end, beyond)


def _check_scope_against_formal(scope, prior_dates):
    """The window must contain the whole formal span, which must end on the identity (anchor) day."""
    if prior_dates[-1] != IDENTITY_AS_OF or scope.window_start > prior_dates[0]:
        _fail("scope_formal_coverage")


def _trading_dates(document, scope):
    """FinMind TaiwanStockTradingDate document -> its in-window dates; no fixed count, no closure inference."""
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("trading_dates_document")
    if type(document["status"]) is not int or document["status"] != 200 or document["msg"] != "success" or type(document["msg"]) is not str:
        _fail("trading_dates_status")
    rows = document["data"]
    if type(rows) is not list or not rows:
        _fail("trading_dates_rows")
    # Every returned row is structurally validated (keys, ISO date, unique, ascending) before
    # rows outside the requested window are discarded, whatever the provider filters.
    dates = []
    for row in rows:
        if type(row) is not dict or set(row) != {"date"}:
            _fail("trading_dates_row")
        dates.append(_base._iso_date(row["date"], "trading_dates_date"))
    if any(earlier >= later for earlier, later in zip(dates, dates[1:])):
        _fail("trading_dates_order")
    return tuple(day for day in dates if scope.window_start <= day <= scope.window_end)


def _check_calendar(dates, scope, prior_dates):
    """Whole-batch gate on the in-window observed trading days, before any price request."""
    if any(date.fromisoformat(day).weekday() >= 5 for day in dates):
        _fail("trading_dates_weekday")
    if scope.cutoff not in dates:
        _fail("trading_dates_cutoff")
    # The cutoff needs a full 60-day window; never shrink it.
    if sum(day <= scope.cutoff for day in dates) < WINDOW_COUNT:
        _fail("trading_dates_window_insufficient")
    # Independent in-repo check: the verified formal span must be exactly the formal dates.
    if tuple(day for day in dates if prior_dates[0] <= day <= prior_dates[-1]) != prior_dates:
        _fail("trading_dates_formal_mismatch")
    # Days after the formal coverage exist only if the pinned policy declares them.
    if tuple(day for day in dates if day > prior_dates[-1]) != scope.beyond:
        _fail("trading_dates_beyond_formal_mismatch")


def _decimal_text(value):
    """Exact canonical decimal text of a positive finite price (no exponent, no trailing zeros)."""
    if type(value) is not Fraction or value <= 0:
        _fail("close_value")
    numerator, denominator = value.numerator, value.denominator
    if (denominator > 10 ** CLOSE_SCALE_MAX
            or numerator >= 10 ** (CLOSE_TEXT_MAX - 1 - CLOSE_SCALE_MAX) * denominator):
        _fail("close_representation")
    scale = next((digits for digits in range(CLOSE_SCALE_MAX + 1) if 10 ** digits % denominator == 0), None)
    if scale is None:
        _fail("close_representation")
    text = str(numerator * 10 ** scale // denominator)
    if scale:
        text = text.rjust(scale + 1, "0")
        text = text[:-scale] + "." + text[-scale:]
    if len(text) > CLOSE_TEXT_MAX:
        _fail("close_representation")
    return text


def _parse_close(text):
    if type(text) is not str or not _CLOSE_PATTERN.fullmatch(text):
        _fail("saved_close")
    value = Fraction(text)
    try:
        canonical_text = _decimal_text(value) if value > 0 else None
    except SourceError:
        canonical_text = None
    if canonical_text != text:
        _fail("saved_close")
    return value


def _closes_rows(results, scope):
    rows = {}
    for symbol in SYMBOLS:
        window = tuple(bar for bar in results[symbol] if bar.date <= scope.cutoff)[-WINDOW_COUNT:]
        if len(window) != WINDOW_COUNT or window[-1].date != scope.cutoff:
            _fail("window_incomplete")
        rows[symbol] = tuple((bar.date, _decimal_text(bar.close)) for bar in window)
    dates = tuple(day for day, _ in rows[SYMBOLS[0]])
    if any(tuple(day for day, _ in rows[symbol]) != dates for symbol in SYMBOLS):
        _fail("window_dates_differ")
    return dates, rows


def _closes_document(dates, rows, scope):
    return {"schema": STORAGE_SCHEMA, "cutoff": scope.cutoff, "count": WINDOW_COUNT,
            "symbols": list(SYMBOLS), "trading_dates": list(dates),
            "counts": {symbol: WINDOW_COUNT for symbol in SYMBOLS},
            "closes": {symbol: [list(row) for row in rows[symbol]] for symbol in SYMBOLS}}


def _financial_start(start, binding, pins):
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
    if (start.version != SEAL_VERSION or start.namespace != NAMESPACE or start.policy_sha256 != pins.sha256):
        _fail("financial_start_scope")
    # Issuer/coordinator/implementer identities come from the seal and are checked by the
    # QA caller against the Issue receipts; this module pins none.
    roles = (start.issuer_thread_id,) + start.coordinator_session_ids + start.implementer_session_ids
    if any(not re.fullmatch(_base.SESSION_ID_PATTERN, part) for part in roles) or len(set(roles)) != len(roles):
        _fail("financial_start_scope")
    if binding.holder_thread_id != binding.holder_session_id or binding.reasoning_effort != "xhigh":
        _fail("financial_qa_identity")
    if (not re.fullmatch(_base.SESSION_ID_PATTERN, binding.holder_thread_id)
            or not re.fullmatch(_base.MODEL_PATTERN, binding.model)):
        _fail("financial_qa_identity")
    if binding.holder_thread_id in roles:
        _fail("financial_qa_identity")
    if not re.fullmatch(r"[0-9a-f]{40}", binding.candidate_sha):
        _fail("financial_candidate")
    if any(not _HEX64.fullmatch(value) for value in (binding.loaded_source_sha256, binding.script_sha256)):
        _fail("financial_script_binding")
    match = re.fullmatch(SEAL_URL_PATTERN, start.seal_comment_url)
    if not match or int(match.group(1)) <= SEAL_COMMENT_FLOOR:
        _fail("financial_new_explicit_seal_required")


class CloseSource:
    """Only acquisition object; pending/failed/expired/released are consumer-inert."""

    def __init__(self, *, policy_canonical, policy_sha256, formal_blob, purpose=PURPOSE, pins=None,
                 transport=None, ledger=None, financial_start=None, execution_binding=None,
                 clock=time.monotonic, lease_seconds=180, observer_roots=None):
        real = transport is None or isinstance(transport, _base._HTTPSTransport)
        if real:
            if pins is not None:
                _fail("pins_with_default_transport")
            pins = _real_pins()
        elif type(pins) is not Pins:
            _fail("boundary_pins_required")
        self._pins = _pins(pins)
        self._policy = validate_policy(policy_canonical, policy_sha256, self._pins)
        self._scope = _policy_scope(self._policy)
        if type(purpose) is not str or purpose != PURPOSE:
            _fail("unsupported_purpose")
        self._formal_blob = formal_blob
        self._prior_dates, self._anchors = _base._formal_reference(formal_blob)
        _check_scope_against_formal(self._scope, self._prior_dates)
        if type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 180:
            _fail("lease_seconds")
        if not callable(clock) or (observer_roots is not None and not callable(observer_roots)):
            _fail("clock_or_roots_type")
        self._real = transport is None
        if real:
            _financial_start(financial_start, execution_binding, self._pins)
            if transport is not None or ledger is not None:
                _fail("default_transport_required_for_financial")
        elif financial_start is not None or execution_binding is not None:
            _fail("financial_start_with_boundary_transport")
        if not self._real and (type(ledger) is not AttemptLedger or ledger.namespace != NAMESPACE):
            _fail("boundary_ledger_required")
        self._binding = execution_binding
        self._transport = _base._HTTPSTransport() if self._real else transport
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
        self._dates = ()
        self._window_dates = ()
        self._closes = {}
        self._closes_bytes = b""
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

    @property
    def scope(self):
        return self._scope

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
        self._roots_estimate = _base.retained_roots_estimate(self.__dict__, stage_roots, external)
        if self._roots_estimate > _base.ROOTS_CAP:
            if getattr(self, "_state", None) in ("pending", "available"):
                self._state = "failed"
            _fail("retained_roots_estimate_cap", estimate_bytes=self._roots_estimate)

    def _check_failure_roots(self, primary_failure, stage, *stage_roots):
        """Check every failure alias without replacing the saved first failure."""
        try:
            self._check_roots(*stage_roots, primary_failure)
        except BaseException as validation_exception:
            validation = _base._failure_values(validation_exception, stage, "roots_check_failure")
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
        full_body, receipt = capture.body, capture.receipt
        self._check_roots(full_body, receipt)
        return capture

    def _capture(self, index, url):
        self._remaining()
        self._request_deadline = self._now() + _base.REQUEST_SECONDS
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
                if declared_length > _base.BODY_CAP or declared_length > _base.RAW_CAP - self._raw_bytes:
                    _fail("declared_body_cap")
            transfer = header_values.get("transfer-encoding", "").strip().lower()
            if transfer not in ("", "chunked") or (transfer and declared_length is not None):
                _fail("ambiguous_framing")
            if not _CONTENT_TYPE.fullmatch(header_values.get("content-type", "").strip()):
                _fail("content_type")
            stage = "capture_body"
            while True:
                self._remaining()
                if response.known_eof is True:
                    break
                available = min(_base.BODY_CAP - len(capture_buffer), _base.RAW_CAP - self._raw_bytes)
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
            source_id = "finmind_trading_dates" if index == 0 else "finmind_nominal_ohlcv/" + SYMBOLS[index - 1]
            source_version = self._policy["trading_date_source"]["version"] if index == 0 else self._policy["version"]
            receipt = _base.Receipt(source_id, source_version, "GET", url, 200,
                                    request_started_utc, datetime.now(timezone.utc).isoformat(),
                                    len(full_body), hashlib.sha256(full_body).hexdigest(), True,
                                    header_values.get("content-type", ""), encoding, NAMESPACE, self._pins.sha256)
            capture = _base.Capture(full_body, receipt)
            self._captures.append(capture)
            self._check_roots(capture_buffer, full_body, receipt)
            return self._capture_ready(capture)
        except BaseException as exception:
            primary_failure = _base._failure_values(exception, stage)
        finally:
            try:
                operations = () if response is None else (("capture_response_close", response.close),)
                failure = _base._close_all(operations, primary_failure)
            finally:
                capture_buffer.clear()
            if failure is not None:
                _base._raise_failure(failure)

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
                document = _base._json(decoded_text)
                self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
                self._remaining()
                parse_results = _trading_dates(document, self._scope)
            else:
                document = _base._json(decoded_text, price=True)
                self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
                self._remaining()
                symbol = SYMBOLS[index - 1]
                parse_results = _base._prices(document, symbol, dates, index, self._check_roots)
                identity = [bar for bar in parse_results if bar.date == IDENTITY_AS_OF]
                if len(identity) != 1:
                    _fail("latest_anchor_mismatch", source_index=index)
                bar = identity[0]
                if (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount) != self._anchors[symbol]:
                    _fail("latest_anchor_mismatch", source_index=index)
            self._documents.append(_base._freeze(document))
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            return parse_results
        except BaseException as exception:
            primary_failure = _base._failure_values(exception, "decode_parse")
            primary_failure["source_index"] = index
            self._check_failure_roots(primary_failure, "parse_failure_roots", full_body, receipt,
                                      decoded_text, document, parse_results, diagnostics, exception)
            _base._raise_failure(primary_failure)
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
        self._batch_deadline = self._now() + _base.BATCH_SECONDS
        pending = self
        results = self._results
        scope = self._scope
        try:
            dates = self._parse_capture(
                self._capture(0, TRADING_DATE_URL.format(start=scope.window_start, end=scope.window_end)), 0, None)
            _check_calendar(dates, scope, self._prior_dates)  # before any price request
            self._dates = dates
            for index, symbol in enumerate(SYMBOLS, 1):
                url = PRICE_URL.format(symbol=symbol, start=scope.window_start, end=scope.window_end)
                results[symbol] = self._parse_capture(self._capture(index, url), index, dates)
                self._check_roots(pending, results)
            self._window_dates, self._closes = _closes_rows(results, scope)
            self._closes_bytes = _base._canonical(_closes_document(self._window_dates, self._closes, scope))
            if len(self._closes_bytes) > CLOSES_CAP:
                _fail("closes_cap")
            self._check_roots(pending, results)
            self._remaining()
            self._expiry = min(self._now() + self._lease_seconds, self._batch_deadline)
            self._state = "pending"
            return pending
        except BaseException as exception:
            primary_failure = _base._failure_values(exception, "batch")
            self._state = "failed"
            self._closes, self._closes_bytes, self._window_dates = {}, b"", ()  # a failed batch derives nothing
            primary_failure.update(attempts=len(self._ledger.attempted), raw_bytes=self._raw_bytes)
            diagnostics = {"stage": "batch", **primary_failure}
            self._diagnostics = MappingProxyType(diagnostics)
            self._check_failure_roots(primary_failure, "batch_failure_roots", pending, results, diagnostics, exception)
            diagnostics.update(primary_failure)
            _base._raise_failure(primary_failure)
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
                                 "dates": self._dates,
                                 "closes_bytes": self._closes_bytes,
                                 "scope": self._scope,
                                 "diagnostics": self._diagnostics,
                                 "retained_roots_estimate_bytes": self._roots_estimate})

    def admit_independent_verification(self, admission):
        if self.state != "pending" or type(admission) is not OracleAdmission:
            _fail("oracle_pending_required")
        for item in fields(admission):
            value = getattr(admission, item.name)
            expected = (tuple if item.name == "receipt_sha256s" else bool if item.name == "independent"
                        else int if item.name.endswith(("rows", "fields")) else str)
            if type(value) is not expected:
                _fail("oracle_type")
        if admission.independent is not True or (admission.namespace, admission.policy_sha256) != (NAMESPACE, self._pins.sha256):
            _fail("oracle_scope")
        if any(type(value) is not str or not _HEX64.fullmatch(value) for value in admission.receipt_sha256s):
            _fail("oracle_receipt_type")
        if not _HEX64.fullmatch(admission.closes_sha256):
            _fail("oracle_receipt_type")
        days = len(self._dates)  # N observed trading days (calendar_rows = trading-date rows)
        if (admission.calendar_rows, admission.price_rows, admission.price_fields, admission.latest_anchor_fields) != (
                days, 7 * days, 42 * days, 42):
            _fail("oracle_complete_scope")
        hashes = tuple(capture.receipt.canonical_sha256 for capture in self._captures)
        if len(hashes) != 8 or admission.receipt_sha256s != hashes:
            _fail("oracle_capture_binding")
        if admission.closes_sha256 != hashlib.sha256(self._closes_bytes).hexdigest():
            _fail("oracle_closes_binding")
        if self._real and (admission.holder_thread_id, admission.candidate_sha, admission.script_sha256) != (
                self._binding.holder_thread_id, self._binding.candidate_sha, self._binding.script_sha256):
            _fail("oracle_qa_binding")
        self._check_roots(admission)
        self._state = "available"

    def _usable(self):
        if self.state != "available":
            _fail("consumer_unavailable")
        self._check_roots()

    def _receipt_document(self, saved_at):
        policy = self._policy
        gets = []
        for capture in self._captures:
            entry = {name: getattr(capture.receipt, name) for name in _RECEIPT_FIELDS}
            entry["receipt_sha256"] = capture.receipt.canonical_sha256
            gets.append(entry)
        here = os.path.abspath(__file__)
        return {
            "schema": RECEIPT_SCHEMA, "storage": "private_local", "storage_schema": STORAGE_SCHEMA,
            "namespace": NAMESPACE, "purpose": PURPOSE, "consumer_version": CONSUMER_VERSION,
            "source_policy": {"version": POLICY_VERSION, "sha256": self._pins.sha256, "bytes": self._pins.nbytes},
            "trading_date_source_version": policy["trading_date_source"]["version"],
            "market": MARKET, "instrument_type": INSTRUMENT_TYPE, "identity_as_of": IDENTITY_AS_OF,
            "cutoff": self._scope.cutoff,
            "window": {"start_date": self._scope.window_start, "end_date": self._scope.window_end},
            "calendar_rows": len(self._dates), "gets": gets,
            "adapter": {"ordinary_close_source_sha256": _file_sha256(here),
                        "ohlcv_history_source_sha256": _file_sha256(os.path.abspath(_base.__file__))},
            "closes": {"file": CLOSES_FILE, "sha256": hashlib.sha256(self._closes_bytes).hexdigest(),
                       "bytes": len(self._closes_bytes)},
            "saved_at": saved_at, "attribution": policy["attribution"],
            "rights": {"price_source": policy["price_source"]["rights"],
                       "trading_date_source": policy["trading_date_source"]["rights"]},
            "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
            "limitations": list(LIMITATIONS),
        }

    def save(self, *, environment=None):
        """Publish the admitted closes below the configured private root (idempotent, never overwrites)."""
        self._usable()
        root = configured_root(environment)
        receipt = self._receipt_document(_utc_now())
        receipt_bytes = _base._canonical(receipt)
        if len(self._closes_bytes) > CLOSES_CAP:
            _fail("closes_cap")
        if len(receipt_bytes) > RECEIPT_CAP:
            _fail("receipt_cap")
        # Full verification in RAM, with the reader's own code, before anything touches the disk.
        _verify_bundle(self._closes_bytes, receipt_bytes, POLICY_VERSION, self._scope.cutoff, self._pins)
        return _publish(root, POLICY_VERSION, self._scope.cutoff, self._closes_bytes, receipt_bytes, self._pins)

    def release(self, *, expired=False):
        self._capture_buffer.clear()
        self._captures.clear()
        self._decoded_texts.clear()
        self._documents.clear()
        self._results.clear()
        self._closes = {}
        self._closes_bytes = b""
        self._window_dates = ()
        self._formal_blob = b""
        self._anchors = MappingProxyType({})
        self._transport = None
        self._observer_roots = None
        self._dates = ()
        self._state = "expired" if expired else "released"
        # The one-shot ledger is deliberately retained and never reset.


def save_closes(source, *, environment=None):
    if type(source) is not CloseSource:
        _fail("source_required")
    return source.save(environment=environment)


def _file_sha256(path):
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        _fail("adapter_hash_unavailable")


def configured_root(environment=None):
    """The only root source: the environment variable. Unset or relative means nothing is written."""
    env = os.environ if environment is None else environment
    value = env.get(ROOT_ENV)
    if type(value) is not str or not value:
        _fail("root_unset")
    return _absolute(value, "root_invalid")


def _absolute(value, code):
    try:
        text = os.fspath(value)
    except TypeError:
        _fail(code)
    if type(text) is not str or not text or "\x00" in text or not os.path.isabs(text):
        _fail(code)
    if ".." in re.split(r"[\\/]", text):
        _fail(code)
    return text


def _lstat(path, kind, expected):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        _fail("saved_missing", kind=kind)
    except OSError:
        _fail("storage_io_failure", kind=kind)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
        _fail("saved_reparse_point", kind=kind)
    if not (stat.S_ISDIR if expected == "dir" else stat.S_ISREG)(info.st_mode):
        _fail("saved_not_" + expected, kind=kind)
    return info


def _read_capped(path, cap, kind):
    info = _lstat(path, kind, "file")
    try:
        with open(path, "rb") as handle:
            data = handle.read(cap + 1)
    except OSError:
        _fail("storage_io_failure", kind=kind)
    if len(data) > cap or len(data) != info.st_size:
        _fail("saved_size_cap", kind=kind)
    return data


def _utc(text):
    if type(text) is not str:
        _fail("saved_time")
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        _fail("saved_time")
    if value.tzinfo is None or value.utcoffset() != timedelta(0) or value.isoformat() != text:
        _fail("saved_time")
    return value


def _saved_shape(value, schema):
    try:
        _base._shape(value, schema)
    except SourceError:
        _fail("saved_shape")


def _parse_saved(data, kind):
    try:
        document = _base._json(data.decode("utf-8"))
    except SourceError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        _fail("saved_parse", kind=kind)
    if type(document) is not dict:
        _fail("saved_shape", kind=kind)
    if _base._canonical(document) != data:
        _fail("saved_not_canonical", kind=kind)
    return document


def _verify_bundle(closes_bytes, receipt_bytes, policy_version, cutoff, pins):
    """Full verification of the two byte strings; returns the parsed (closes, receipt) documents."""
    if len(closes_bytes) > CLOSES_CAP or len(receipt_bytes) > RECEIPT_CAP:
        _fail("saved_size_cap")
    closes = _parse_saved(closes_bytes, "closes")
    receipt = _parse_saved(receipt_bytes, "receipt")
    _saved_shape(closes, _CLOSES_SHAPE)
    _saved_shape(receipt, _RECEIPT_SHAPE)
    fixed = (
        (receipt["schema"], RECEIPT_SCHEMA), (receipt["storage"], "private_local"),
        (receipt["storage_schema"], STORAGE_SCHEMA), (receipt["namespace"], NAMESPACE),
        (receipt["purpose"], PURPOSE), (receipt["consumer_version"], CONSUMER_VERSION),
        (receipt["market"], MARKET), (receipt["instrument_type"], INSTRUMENT_TYPE),
        (receipt["identity_as_of"], IDENTITY_AS_OF), (receipt["publication_time"], "unknown"),
        (receipt["first_availability"], "unknown"), (receipt["revision_time"], "unknown"),
        (receipt["limitations"], list(LIMITATIONS)), (closes["schema"], STORAGE_SCHEMA),
        (closes["count"], WINDOW_COUNT), (closes["symbols"], list(SYMBOLS)),
        (closes["counts"], {symbol: WINDOW_COUNT for symbol in SYMBOLS}),
    )
    if any(actual != expected for actual, expected in fixed):
        _fail("saved_value")
    policy = receipt["source_policy"]
    if (policy["version"] != policy_version or policy["sha256"] != pins.sha256 or policy["bytes"] != pins.nbytes
            or receipt["cutoff"] != cutoff or closes["cutoff"] != cutoff):
        _fail("saved_pin_or_scope")
    start = _base._iso_date(receipt["window"]["start_date"], "saved_window")
    end = _base._iso_date(receipt["window"]["end_date"], "saved_window")
    if not start < cutoff <= end or end < IDENTITY_AS_OF:
        _fail("saved_window")
    if (not receipt["attribution"] or len(receipt["attribution"]) > 512 or not _SOURCE_VERSION.fullmatch(receipt["trading_date_source_version"])
            or any(not text or len(text) > 512 for text in receipt["rights"].values())):
        _fail("saved_value")
    span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    if type(receipt["calendar_rows"]) is not int or not WINDOW_COUNT <= receipt["calendar_rows"] <= span:
        _fail("saved_calendar_rows")
    # Closes: 60 unique ascending weekday dates ending at the cutoff, canonical positive closes,
    # and every stock holding exactly those dates.
    dates = closes["trading_dates"]
    normalized = [_base._iso_date(day, "saved_date") for day in dates]
    if (normalized != dates or dates != sorted(set(dates)) or dates[-1] != cutoff
            or any(date.fromisoformat(day).weekday() >= 5 for day in dates) or dates[0] < start):
        _fail("saved_dates")
    for symbol in SYMBOLS:
        rows = closes["closes"][symbol]
        for row in rows:
            if type(row) is not list or len(row) != 2:
                _fail("saved_shape")
        if [row[0] for row in rows] != dates:
            _fail("saved_dates")
        for row in rows:
            _parse_close(row[1])
    # Receipt GET list.
    ids = ("finmind_trading_dates",) + tuple("finmind_nominal_ohlcv/" + symbol for symbol in SYMBOLS)
    previous = None
    total = 0
    for index, entry in enumerate(receipt["gets"]):
        _saved_shape(entry, _GET_SHAPE)
        url = (TRADING_DATE_URL.format(start=start, end=end) if index == 0
               else PRICE_URL.format(symbol=SYMBOLS[index - 1], start=start, end=end))
        version = receipt["trading_date_source_version"] if index == 0 else policy_version
        if (entry["source_id"] != ids[index] or entry["source_version"] != version or entry["method"] != "GET"
                or entry["url"] != url or entry["status"] != 200 or entry["full_eof"] is not True
                or entry["content_encoding"] != "identity" or not _CONTENT_TYPE.fullmatch(entry["content_type"])
                or entry["namespace"] != NAMESPACE or entry["policy_sha256"] != pins.sha256):
            _fail("saved_get", source_index=index)
        if not 1 <= entry["body_bytes"] <= _base.BODY_CAP or not _HEX64.fullmatch(entry["body_sha256"]):
            _fail("saved_get", source_index=index)
        total += entry["body_bytes"]
        started, observed = _utc(entry["request_started_utc"]), _utc(entry["observed_utc"])
        if started > observed or (previous is not None and started < previous):
            _fail("saved_get_times", source_index=index)
        previous = observed
        recomputed = hashlib.sha256(_base._canonical({name: entry[name] for name in _RECEIPT_FIELDS})).hexdigest()
        if entry["receipt_sha256"] != recomputed:
            _fail("saved_get_receipt_sha", source_index=index)
    if total > _base.RAW_CAP:
        _fail("saved_get")
    if _utc(receipt["saved_at"]) < previous:
        _fail("saved_get_times")
    adapter = receipt["adapter"]
    if any(not _HEX64.fullmatch(value) for value in adapter.values()):
        _fail("saved_adapter")
    reference = receipt["closes"]
    if (reference["file"] != CLOSES_FILE or reference["bytes"] != len(closes_bytes)
            or reference["sha256"] != hashlib.sha256(closes_bytes).hexdigest()):
        _fail("saved_closes_reference")
    return closes, receipt


def _check_components(policy_version, cutoff):
    if type(policy_version) is not str or not _VERSION_PATTERN.fullmatch(policy_version):
        _fail("saved_scope")
    if policy_version != POLICY_VERSION:
        _fail("saved_policy_version")
    return _base._iso_date(cutoff, "saved_scope")


def _load_verified(root, policy_version, cutoff, pins):
    cutoff = _check_components(policy_version, cutoff)
    root = _absolute(root, "root_invalid")
    _lstat(root, "root", "dir")
    _lstat(os.path.join(root, policy_version), "policy_dir", "dir")
    final = os.path.join(root, policy_version, cutoff)
    _lstat(final, "final", "dir")
    try:
        names = sorted(os.listdir(final))
    except OSError:
        _fail("storage_io_failure", kind="final")
    if names != sorted((CLOSES_FILE, RECEIPT_FILE)):
        _fail("saved_entries")
    closes_bytes = _read_capped(os.path.join(final, CLOSES_FILE), CLOSES_CAP, "closes")
    receipt_bytes = _read_capped(os.path.join(final, RECEIPT_FILE), RECEIPT_CAP, "receipt")
    closes, receipt = _verify_bundle(closes_bytes, receipt_bytes, policy_version, cutoff, pins)
    return closes_bytes, receipt_bytes, closes, receipt, final


def load_saved_closes(root, policy_version, cutoff, *, pins=None):
    """Read-only, fully re-verified view of one saved bundle; never fetches and never falls back."""
    pins = _real_pins() if pins is None else _pins(pins)
    closes_bytes, receipt_bytes, closes, receipt, _ = _load_verified(root, policy_version, cutoff, pins)
    rows = {}
    for symbol in SYMBOLS:
        rows[symbol] = tuple(Close(day, text, Fraction(text)) for day, text in closes["closes"][symbol])
    return SavedCloses(policy_version, cutoff, SYMBOLS, tuple(closes["trading_dates"]), MappingProxyType(rows),
                       _base._freeze(receipt), hashlib.sha256(closes_bytes).hexdigest(),
                       hashlib.sha256(receipt_bytes).hexdigest())


def _entry(path, kind, expected):
    """A root entry of the wrong type is a foreign entry; a reparse point keeps its own code."""
    try:
        return _lstat(path, kind, expected)
    except SourceError as error:
        if error.code in ("saved_not_dir", "saved_not_file"):
            _fail("root_entries_invalid", kind=kind)
        raise


def _scan_root(root):
    """Structure and size census of the private root; anything foreign or partial fails closed."""
    bundles = set()
    files = total = 0
    for name in sorted(os.listdir(root)):
        if not _VERSION_PATTERN.fullmatch(name):
            _fail("root_entries_invalid", kind="root_entry")
        policy_dir = os.path.join(root, name)
        _entry(policy_dir, "policy_dir", "dir")
        for cutoff in sorted(os.listdir(policy_dir)):
            if _base._iso_date(cutoff, "root_entries_invalid") != cutoff:
                _fail("root_entries_invalid", kind="bundle_entry")
            final = os.path.join(policy_dir, cutoff)
            _entry(final, "final", "dir")
            if sorted(os.listdir(final)) != sorted((CLOSES_FILE, RECEIPT_FILE)):
                _fail("root_entries_invalid", kind="bundle_files")
            for file_name, cap in ((CLOSES_FILE, CLOSES_CAP), (RECEIPT_FILE, RECEIPT_CAP)):
                info = _entry(os.path.join(final, file_name), "bundle_file", "file")
                if info.st_size > cap:
                    _fail("saved_size_cap", kind="bundle_file")
                files += 1
                total += info.st_size
            bundles.add((name, cutoff))
    return bundles, files, total


def _carry(failure, exception):
    """Copy the few plain labels/integers that locate a storage failure (never messages or objects)."""
    original = exception.diagnostics if isinstance(exception, SourceError) else {}
    for name in ("kind", "field", "reader_code"):
        value = original.get(name)
        if type(value) is str and re.fullmatch(r"[a-z0-9_.]{1,64}", value):
            failure[name] = value
    errno = original.get("errno", getattr(exception, "errno", None))
    if type(errno) is int and 0 <= errno <= 65535:
        failure["errno"] = errno
    return failure


def _without_saved_at(receipt):
    return {key: value for key, value in receipt.items() if key != "saved_at"}


def _fsync_directory(path):
    if os.name == "nt":  # Windows has no directory fsync
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_if_present(function, path):
    def remove():
        try:
            function(path)
        except FileNotFoundError:
            pass
    return remove


def _publish(root, policy_version, cutoff, closes_bytes, receipt_bytes, pins):
    if not _SAVE_LOCK.acquire(blocking=False):
        _fail("storage_busy")
    try:
        return _publish_locked(root, policy_version, cutoff, closes_bytes, receipt_bytes, pins)
    except OSError as error:
        _fail("storage_io_failure", errno=error.errno if type(error.errno) is int else 0)
    finally:
        _SAVE_LOCK.release()


def _publish_locked(root, policy_version, cutoff, closes_bytes, receipt_bytes, pins):
    created_root = False
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        _lstat(os.path.dirname(root), "root_parent", "dir")
        os.mkdir(root)
        created_root = True
        info = None
    if info is not None:
        _lstat(root, "root", "dir")
    try:
        bundles, files, total = _scan_root(root)
        new_receipt = _parse_saved(receipt_bytes, "receipt")
        if (policy_version, cutoff) in bundles:
            existing_closes, existing_receipt_bytes, _, existing, final = _load_verified(root, policy_version, cutoff, pins)
            if existing_closes != closes_bytes or _without_saved_at(existing) != _without_saved_at(new_receipt):
                _fail("final_conflict")
            return SavedBundle("idempotent", policy_version, cutoff, final,
                               hashlib.sha256(existing_closes).hexdigest(), len(existing_closes),
                               hashlib.sha256(existing_receipt_bytes).hexdigest(), len(existing_receipt_bytes),
                               existing["saved_at"])
        if len(bundles) + 1 > MAX_BUNDLES:
            _fail("quota_bundles")
        if files + 2 > MAX_FILES:
            _fail("quota_files")
        if total + len(closes_bytes) + len(receipt_bytes) > MAX_TOTAL_BYTES:
            _fail("quota_bytes")
    except BaseException as exception:
        failure = _carry(_base._failure_values(exception, "root_check", "storage_io_failure"), exception)
        if created_root:
            failure = _base._close_all((("root_rmdir", _remove_if_present(os.rmdir, root)),), failure)
        _base._raise_failure(failure)
    staging = os.path.join(root, ".staging-" + secrets.token_hex(8))
    parent = os.path.join(root, policy_version)
    final = os.path.join(parent, cutoff)
    created_parent = False
    stage = "staging_create"
    try:
        os.mkdir(staging)
        for name, data in ((CLOSES_FILE, closes_bytes), (RECEIPT_FILE, receipt_bytes)):
            stage = "staging_write"
            descriptor = os.open(os.path.join(staging, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | _BINARY, 0o600)
            try:
                view = memoryview(data)
                written = 0
                while written < len(data):
                    written += os.write(descriptor, view[written:])
                stage = "staging_fsync"
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _fsync_directory(staging)
        stage = "publish_rename"
        if os.path.lexists(parent):
            _lstat(parent, "policy_dir", "dir")
        else:
            os.mkdir(parent)
            created_parent = True
        os.rename(staging, final)
    except BaseException as exception:
        failure = _carry(_base._failure_values(exception, stage, "storage_io_failure"), exception)
        operations = (
            ("staging_remove_closes", _remove_if_present(os.remove, os.path.join(staging, CLOSES_FILE))),
            ("staging_remove_receipt", _remove_if_present(os.remove, os.path.join(staging, RECEIPT_FILE))),
            ("staging_rmdir", _remove_if_present(os.rmdir, staging)),
        )
        if created_parent:
            operations += (("policy_dir_rmdir", _remove_if_present(os.rmdir, parent)),)
        if created_root:
            operations += (("root_rmdir", _remove_if_present(os.rmdir, root)),)
        failure = _base._close_all(operations, failure)
        _base._raise_failure(failure)
    # Read back with the reader's own code; a published bundle that does not verify is reported, not hidden.
    try:
        read_closes, read_receipt, _, document, _ = _load_verified(root, policy_version, cutoff, pins)
    except SourceError as error:
        _fail("saved_readback_failed", reader_code=error.code)
    if read_closes != closes_bytes or read_receipt != receipt_bytes:
        _fail("saved_readback_mismatch")
    return SavedBundle("created", policy_version, cutoff, final, hashlib.sha256(read_closes).hexdigest(),
                       len(read_closes), hashlib.sha256(read_receipt).hexdigest(), len(read_receipt),
                       document["saved_at"])
