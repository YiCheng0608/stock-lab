"""Issue 98's one-shot FinMind source for the seven TPEx ordinary shares' trading calendar,
indirect suspension evidence and corporate actions, plus its private derived bundle.

This is the third consumer of the issue 32 acquisition contract (after issue 7). It fetches
37 FinMind documents in a fixed order (``STEPS``): one ``TaiwanStockTradingDate``, then per symbol
``TaiwanStockPrice``, ``TaiwanStockDividendResult``, ``TaiwanStockDividend``,
``TaiwanStockCapitalReductionReferencePrice`` and ``TaiwanStockSplitPrice``, then one ``TaiwanStockInfo``.
Par-value changes are deliberately not requested (issue 98 AC revision 1): a day on which one moves the reference
price has no event to explain it, so the spread check reports an unexplained change and that symbol's adjusted
basis is refused (raw is unaffected). The issue 32 helpers are imported from
``ohlcv_history_source`` (never copied back into or edited in that file; ``IMPORTED_HELPERS``
lists every reference). Only a structural failure stops the batch; a dataset that returns no rows,
a day without a usable price, an event whose terms are missing and a failed consistency check are
recorded as per-day / per-event / per-symbol states and refused at read time instead.

There is no import-time I/O and no environment read. ``acquire`` returns PENDING; only an
independent same-RAM oracle admission (which also binds the SHA-256 of the canonical derived
data) makes ``save`` possible. Disk access exists only in ``save`` (below the fixed private root
``PRIVATE_ROOT`` for the default transport; a boundary transport must name its own root and may
never use the real one) and in the read-only ``load_saved`` (never fetches, never falls back).

The default HTTPS path is bound to the externally published canonical policy v1
(``POLICY_SHA256`` / ``POLICY_BYTES``, issue 98 comment 6170250977; were the pins unset it would fail
closed with ``real_pins_unset`` before any seal check) and still needs a FinancialStart plus a
matching ExecutionBinding from a fresh explicit issue 98 seal newer than ``SEAL_COMMENT_FLOOR``, the
one-shot in-process ledger, body/aggregate/roots caps, cooperative deadlines and the lease.
Publishing the pins is not an authorization to fetch.

Stored per bundle (``<policy_version>/<window_end>/``): ``data.json`` holds the observed calendar,
per-symbol day states, normalized events with their factors and traces, and the consistency-check
results; ``receipt.json`` holds each GET's URL/status/times/body SHA-256 and bytes, the policy and
adapter pins and the limits. Raw bodies and raw prices are never stored. Both files are canonical
UTF-8 JSON. Dates are Asia/Taipei trading calendar dates; receipt times are UTC.
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
_fail = _base._fail

NAMESPACE = "issue98-tpex-seven-calendar-actions-v2/qa1"
POLICY_VERSION = "issue98-tpex-seven-calendar-actions-v2"
PROFILE = "free_public_local"
PURPOSE = "local_personal_noncommercial_private_derived_calendar_actions"
CONSUMER_VERSION = "tpex-calendar-actions-read-v1"
STORAGE_SCHEMA = "tpex-calendar-actions-saved/v1"
RECEIPT_SCHEMA = "tpex-calendar-actions-receipt/v1"
DATA_VERSION_PREFIX = "tpex-calendar-actions-data/v1:"
PRIVATE_ROOT = "C:/Users/YiCheng/AppData/Local/taiwan-stock-research/tpex-calendar-actions-issue98"
MARKET = "TW/TPEx"
INSTRUMENT_TYPE = "ordinary_stock"
READ_MARKET = "TPEx"
READ_SECURITY_TYPE = "ordinary_share"
IDENTITY_AS_OF = "2026-10-06"
SYMBOLS = _base.SYMBOLS
WINDOW_START = "2026-07-01"
WINDOW_END = "2026-10-12"
DIVIDEND_END = "2026-12-31"
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
MAX_GETS = 37

# Externally published pin of the canonical policy v2 (10,136 bytes, sorted keys, compact, no trailing LF):
# issue 98 comment 6170250977. Policy v1 (comment 6139122796) is superseded by AC revision 1 and is no longer
# accepted. The policy text itself is not bundled here.
POLICY_SHA256 = "ef10c3c71b4c643365bafc164d7324a88399b9ec27773c0438ef061b95feb794"
POLICY_BYTES = 10136
# A seal must be a fresh explicit issue 98 comment newer than the policy v2 publication comment above. It is a
# floor, not an authorization.
SEAL_COMMENT_FLOOR = 6170250977
SEAL_VERSION = "issue98-financial-start-v1"
SEAL_URL_PATTERN = r"https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-([0-9]+)"

BODY_CAP = _base.BODY_CAP
RAW_CAP = 16777216
ROOTS_CAP = _base.ROOTS_CAP
REQUEST_SECONDS = _base.REQUEST_SECONDS
BATCH_SECONDS = 600
LEASE_SECONDS = 180

DATA_CAP = 131072
RECEIPT_CAP = 65536
MAX_BUNDLES = 1
MAX_FILES = 2
MAX_TOTAL_BYTES = 196608
DATA_FILE = "data.json"
RECEIPT_FILE = "receipt.json"

SPREAD_MIN_MATCHED_DAYS = 20
STOCK_DIVIDEND_PAR_TWD = 10
INFO_ACCEPTED_TYPES = ("tpex",)
# Tick ladder of SOURCE_REGISTRY #97 (rule version tpex-static-rules/2026-10-12/v1, business rules article 55
# paragraph 2): (lower bound, inclusive; tick). A test locks this table against backend/app/tpex_execution_rules.py.
TICK_LADDER = ((Fraction(0), Fraction(1, 100)), (Fraction(10), Fraction(1, 20)), (Fraction(50), Fraction(1, 10)),
               (Fraction(100), Fraction(1, 2)), (Fraction(500), Fraction(1)), (Fraction(1000), Fraction(5)))
TICK_LADDER_TEXT = tuple("%s=%s" % (lower, tick) for lower, tick in TICK_LADDER)

LIMITATIONS = (
    "date_is_asia_taipei_trading_calendar_date_not_utc",
    "july_and_after_2026-10-06_calendar_days_not_independently_verified",
    "no_event_evidence_is_same_provider_internal_consistency_only",
    "suspension_is_indirect_evidence_only_never_a_positive_fact",
    "spread_semantics_inferred_from_data_not_documented",
    "stock_dividend_par_value_10_twd_is_an_inference",
    "reference_price_rounding_unspecified_cross_check_tolerance_is_strictly_less_than_one_tick",
    "stock_info_type_value_form_unverified_until_a_real_response",
    "par_value_change_not_fetched_detected_only_as_an_unexplained_spread_change",
    "publication_time_first_availability_revision_time_unknown",
    "raw_body_and_raw_prices_not_stored_derived_values_only",
    "personal_noncommercial_local_use_no_redistribution",
)
UNSUPPORTED = (
    "historical_pit", "publication_time", "first_availability", "revision_guarantee",
    "positive_suspension_fact", "paid_subscription", "par_value_change_factor", "provider_adjusted_prices",
    "other_symbols",
    "other_markets", "other_dates", "raw_body_storage", "redistribution", "actionable_strategy",
    "plan", "trading", "historical_simulation",
)

# Every private issue 32 name this module references; the test locks each one.
IMPORTED_HELPERS = (
    "AttemptLedger", "Capture", "ExecutionBinding", "FORMAL_BLOB", "FORMAL_SHA256", "FinancialStart",
    "MODEL_PATTERN", "Receipt", "SESSION_ID_PATTERN", "SYMBOLS", "SourceError", "BODY_CAP", "ROOTS_CAP",
    "REQUEST_SECONDS", "USER_AGENT", "ACCEPT", "_HTTPSTransport", "_canonical", "_close_all", "_fail",
    "_failure_values", "_formal_reference", "_freeze", "_integer", "_iso_date", "_json", "_number",
    "_raise_failure", "_shape", "retained_roots_estimate",
)

_BINARY = getattr(os, "O_BINARY", 0)
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"[a-z0-9_]{1,64}")
_VERSION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_CONTENT_TYPE = re.compile(r"application/json(?:\s*;\s*charset=utf-8)?", re.I)
_SOURCE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}")
_RATIONAL = re.compile(r"[1-9][0-9]*/[1-9][0-9]*")
_SAVE_LOCK = threading.Lock()
_REAL_LEDGER = None


# --- acquisition steps ---------------------------------------------------------------------------

# kind, dataset, per symbol, dated, end date, (required, {field: type code}).
# Type codes: D strict ISO date, d lenient date (None/"" or unparsable -> recorded), S non-empty
# string, T nullable string, A nullable scalar kept as text, P non-negative number, N nullable
# number, I non-negative int64, i nullable non-negative int64. Unknown extra keys are tolerated and
# only their names are recorded.
# Field-name provenance (doc GET receipt, issue 98 comment 6135101980): the TaiwanStockDividend names, including
# StockEarningsDistribution, StockStatutorySurplus, CashEarningsDistribution and CashStatutorySurplus, are the
# schema names on the Fundamental page (SHA-256 801b4f41573ac3388c4c684fd6fe4939bb15427b332234a741a79e0e6d9977c7);
# the TaiwanStockInfo "type" value "tpex" follows the Technical page note that the table keeps both the
# emerging and the twse / tpex rows (SHA-256 6f8747b5fbaa9ba13708bf1a546f7368e460fc59ccd86bd5c78690c10aa52ea5).
# Whether a real response spells the value exactly "tpex" is not yet verified. The amount fields stay optional.
_SOURCES = (
    ("calendar", "TaiwanStockTradingDate", False, True, WINDOW_END,
     (("date",), {"date": "D"})),
    ("price", "TaiwanStockPrice", True, True, WINDOW_END,
     (("date", "stock_id", "open", "max", "min", "close", "Trading_Volume", "Trading_money"),
      {"date": "D", "stock_id": "S", "open": "P", "max": "P", "min": "P", "close": "P",
       "Trading_Volume": "I", "Trading_money": "I", "spread": "N", "Trading_turnover": "i"})),
    ("dividend_result", "TaiwanStockDividendResult", True, True, WINDOW_END,
     (("date", "stock_id", "before_price", "after_price", "reference_price"),
      {"date": "D", "stock_id": "S", "before_price": "N", "after_price": "N", "reference_price": "N",
       "stock_and_cache_dividend": "N", "stock_or_cache_dividend": "A", "max_price": "N",
       "min_price": "N", "open_price": "N"})),
    ("dividend", "TaiwanStockDividend", True, True, DIVIDEND_END,
     (("date", "stock_id"),
      {"date": "D", "stock_id": "S", "StockExDividendTradingDate": "d", "CashExDividendTradingDate": "d",
       "StockEarningsDistribution": "N", "StockStatutorySurplus": "N", "CashEarningsDistribution": "N",
       "CashStatutorySurplus": "N", "TotalNumberOfCashCapitalIncrease": "N",
       "CashIncreaseSubscriptionRate": "N", "CashIncreaseSubscriptionpRrice": "N",
       "AnnouncementDate": "d", "AnnouncementTime": "A"})),
    ("capital_reduction", "TaiwanStockCapitalReductionReferencePrice", True, True, WINDOW_END,
     (("date", "stock_id", "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice"),
      {"date": "D", "stock_id": "S", "ClosingPriceonTheLastTradingDay": "N",
       "PostReductionReferencePrice": "N", "LimitUp": "N", "LimitDown": "N",
       "OpeningReferencePrice": "N", "ExrightReferencePrice": "N", "ReasonforCapitalReduction": "A"})),
    ("split", "TaiwanStockSplitPrice", True, True, WINDOW_END,
     (("date", "stock_id", "before_price", "after_price"),
      {"date": "D", "stock_id": "S", "type": "A", "before_price": "N", "after_price": "N",
       "max_price": "N", "min_price": "N", "open_price": "N"})),
    ("info", "TaiwanStockInfo", False, False, None,
     (("stock_id", "type", "date"),
      {"stock_id": "S", "type": "T", "date": "d", "industry_category": "A", "stock_name": "A"})),
)
_FIELDS = {kind: spec for kind, _, _, _, _, spec in _SOURCES}
SOURCE_IDS = {
    "calendar": "finmind_trading_dates", "price": "finmind_price", "dividend_result": "finmind_dividend_result",
    "dividend": "finmind_dividend", "capital_reduction": "finmind_capital_reduction",
    "split": "finmind_split_price", "info": "finmind_stock_info",
}
EVENT_SOURCE_KINDS = ("dividend_result", "dividend", "capital_reduction", "split")


def _url(dataset, symbol, start, end):
    query = ["dataset=" + dataset]
    if symbol is not None:
        query.append("data_id=" + symbol)
    if start is not None:
        query.append("start_date=" + start)
    if end is not None:
        query.append("end_date=" + end)
    return ENDPOINT + "?" + "&".join(query)


@dataclass(frozen=True, slots=True)
class Step:
    index: int
    kind: str
    dataset: str
    symbol: object
    url: str
    source_id: str


def _build_steps():
    steps = []
    for kind, dataset, per_symbol, dated, end, _ in _SOURCES:
        for symbol in (SYMBOLS if per_symbol else (None,)):
            source_id = SOURCE_IDS[kind] + ("" if symbol is None else "/" + symbol)
            steps.append(Step(len(steps), kind, dataset, symbol,
                              _url(dataset, symbol, WINDOW_START if dated else None, end), source_id))
    return tuple(steps)


STEPS = _build_steps()
if len(STEPS) != MAX_GETS:
    raise RuntimeError("step table must have exactly %d GETs" % MAX_GETS)


# --- policy --------------------------------------------------------------------------------------

def _source_shape(kind):
    required, codes = _FIELDS[kind]
    return {"dataset": str, "data_id": bool, "start_date": str, "end_date": str, "gets": int, "url": str,
            "required_fields": (str, len(required)), "optional_fields": (str, len(codes) - len(required))}


# A schema, not a bundled policy or a source of expected financial values.
_POLICY_SHAPE = {
    "version": str, "profile": str, "source_use": str, "consumer_version": str, "market": str,
    "instrument_type": str, "symbols": (str, 7), "identity_as_of": str,
    "window": {"start_date": str, "end_date": str, "dividend_end_date": str},
    "sources": {kind: _source_shape(kind) for kind, *_ in _SOURCES},
    "calendar": {
        "version": str, "prior_calendar_formal_blob": str, "prior_calendar_formal_sha256": str,
        "prior_verified_counts": {"August": int, "September": int, "October_through_6": int},
        "expected_scope": str,
    },
    "checks": {
        "spread_min_matched_days": int, "stock_dividend_par_twd": int,
        "info_accepted_types": (str, len(INFO_ACCEPTED_TYPES)),
        "spread_reference": str, "spread_semantics_demonstration": str, "zero_price_rows": str,
        "identity_anchor": str, "dividend_factor": str, "reference_ratio_factor": str,
        "paid_subscription": str, "same_day_events": str, "par_value_change": str,
        "reference_tick_ladder": (str, len(TICK_LADDER_TEXT)), "reference_tick_source": str,
        "reference_cross_check": str,
    },
    "storage": {
        "kind": str, "schema": str, "root": str, "layout": str, "raw_body": str, "stored": str,
        "max_data_bytes": int, "max_receipt_bytes": int, "max_bundles": int, "max_files": int,
        "max_total_bytes": int,
    },
    "acquisition": {
        "namespace": str, "order": str, "max_gets": int, "per_source_max_gets": int,
        "body_cap_bytes": int, "total_raw_cap_bytes": int, "retained_roots_estimate_cap_bytes": int,
        "request_seconds": int, "batch_seconds": int, "deadline": str, "accept_encoding": str,
        "accept": str, "user_agent": str, "redirects": int, "retries": int, "stop_on_first_failure": bool,
    },
    "response_shape": {k: str for k in (
        "status", "content_type", "framing", "content_encoding", "duplicate_identity_headers",
        "set_cookie", "encoding", "empty_data", "structure")},
    "attribution": str, "rights": str, "documentation": str,
    "publication_time": str, "first_availability": str, "revision_time": str,
    "unsupported": (str, len(UNSUPPORTED)),
}
_TEXT_LEAVES = (
    ("calendar", "expected_scope"), ("attribution",), ("rights",), ("documentation",),
    ("checks", "spread_reference"), ("checks", "spread_semantics_demonstration"), ("checks", "zero_price_rows"),
    ("checks", "identity_anchor"), ("checks", "dividend_factor"), ("checks", "reference_ratio_factor"),
    ("checks", "paid_subscription"), ("checks", "same_day_events"), ("checks", "reference_tick_source"),
    ("checks", "reference_cross_check"), ("checks", "par_value_change"),
) + tuple(("response_shape", key) for key in _POLICY_SHAPE["response_shape"])


def _expected_policy(policy):
    """The policy this module implements. Free-text leaves are taken from ``policy`` (length-checked)."""
    texts = {}
    for path in _TEXT_LEAVES:
        node = policy
        for key in path:
            node = node[key]
        texts[path] = node
    expected = {
        "version": POLICY_VERSION, "profile": PROFILE, "source_use": PURPOSE,
        "consumer_version": CONSUMER_VERSION, "market": MARKET, "instrument_type": INSTRUMENT_TYPE,
        "symbols": list(SYMBOLS), "identity_as_of": IDENTITY_AS_OF,
        "window": {"start_date": WINDOW_START, "end_date": WINDOW_END, "dividend_end_date": DIVIDEND_END},
        "sources": {}, "calendar": {}, "checks": {}, "storage": {}, "acquisition": {}, "response_shape": {},
        "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
        "unsupported": list(UNSUPPORTED),
    }
    for kind, dataset, per_symbol, dated, end, (required, codes) in _SOURCES:
        template = _url(dataset, "{symbol}" if per_symbol else None, WINDOW_START if dated else None, end)
        expected["sources"][kind] = {
            "dataset": dataset, "data_id": per_symbol, "start_date": WINDOW_START if dated else "",
            "end_date": end or "", "gets": len(SYMBOLS) if per_symbol else 1, "url": template,
            "required_fields": list(required),
            "optional_fields": [name for name in codes if name not in required],
        }
    expected["calendar"] = {
        "version": policy["calendar"]["version"], "prior_calendar_formal_blob": _base.FORMAL_BLOB,
        "prior_calendar_formal_sha256": _base.FORMAL_SHA256,
        "prior_verified_counts": {"August": 21, "September": 20, "October_through_6": 4},
        "expected_scope": texts[("calendar", "expected_scope")],
    }
    expected["checks"] = {
        "spread_min_matched_days": SPREAD_MIN_MATCHED_DAYS, "stock_dividend_par_twd": STOCK_DIVIDEND_PAR_TWD,
        "info_accepted_types": list(INFO_ACCEPTED_TYPES),
        "reference_tick_ladder": list(TICK_LADDER_TEXT),
        **{key: texts[("checks", key)] for key in (
            "spread_reference", "spread_semantics_demonstration", "zero_price_rows", "identity_anchor",
            "dividend_factor", "reference_ratio_factor", "paid_subscription", "same_day_events",
            "reference_tick_source", "reference_cross_check", "par_value_change")},
    }
    expected["storage"] = {
        "kind": "private_local_derived_calendar_actions", "schema": STORAGE_SCHEMA, "root": PRIVATE_ROOT,
        "layout": "<policy_version>/<window_end>/{data.json,receipt.json}", "raw_body": "not_stored",
        "stored": "calendar, per-symbol day states, events, factors, traces and check results; no raw prices",
        "max_data_bytes": DATA_CAP, "max_receipt_bytes": RECEIPT_CAP, "max_bundles": MAX_BUNDLES,
        "max_files": MAX_FILES, "max_total_bytes": MAX_TOTAL_BYTES,
    }
    expected["acquisition"] = {
        "namespace": NAMESPACE,
        "order": "calendar, then per dataset the seven symbols ascending (price, dividend_result, dividend, "
                 "capital_reduction, split), then stock info",
        "max_gets": MAX_GETS, "per_source_max_gets": 1, "body_cap_bytes": BODY_CAP, "total_raw_cap_bytes": RAW_CAP,
        "retained_roots_estimate_cap_bytes": ROOTS_CAP, "request_seconds": REQUEST_SECONDS,
        "batch_seconds": BATCH_SECONDS, "deadline": "cooperative", "accept_encoding": "identity",
        "accept": _base.ACCEPT, "user_agent": _base.USER_AGENT, "redirects": 0, "retries": 0,
        "stop_on_first_failure": True,
    }
    expected["response_shape"] = {key: texts[("response_shape", key)] for key in _POLICY_SHAPE["response_shape"]}
    expected["attribution"] = texts[("attribution",)]
    expected["rights"] = texts[("rights",)]
    expected["documentation"] = texts[("documentation",)]
    return expected


def _first_difference(actual, expected, path=""):
    if isinstance(expected, dict):
        if type(actual) is not dict or actual.keys() != expected.keys():
            return path or "policy"
        for key in expected:
            found = _first_difference(actual[key], expected[key], path + "." + key if path else key)
            if found is not None:
                return found
        return None
    return None if type(actual) is type(expected) and actual == expected else path


def _pins(value):
    if (type(value) is not Pins or type(value.sha256) is not str or not _HEX64.fullmatch(value.sha256)
            or type(value.nbytes) is not int or value.nbytes <= 0):
        _fail("pins_type")
    return value


@dataclass(frozen=True, slots=True)
class Pins:
    """The externally issued canonical-policy pin (digest and exact byte length)."""
    sha256: str
    nbytes: int


def _real_pins():
    if POLICY_SHA256 is None or POLICY_BYTES is None:
        _fail("real_pins_unset")
    return _pins(Pins(POLICY_SHA256, POLICY_BYTES))


def validate_policy(policy_canonical, policy_sha256, pins=None):
    """Require the independently supplied exact canonical bytes, the external pin and this module's values."""
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
    for path in _TEXT_LEAVES:
        node = policy
        for key in path:
            node = node[key]
        if not node or len(node) > 1024:
            _fail("policy_value", field=".".join(path))
    if not _SOURCE_VERSION.fullmatch(policy["calendar"]["version"]):
        _fail("policy_value", field="calendar.version")
    difference = _first_difference(policy, _expected_policy(policy))
    if difference is not None:
        _fail("policy_value", field=difference)
    return _base._freeze(policy)


# --- document parsing ----------------------------------------------------------------------------

def _document_rows(document, kind):
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail(kind + "_document")
    if (type(document["status"]) is not int or document["status"] != 200
            or type(document["msg"]) is not str or document["msg"] != "success"):
        _fail(kind + "_document_status")
    if type(document["data"]) is not list:
        _fail(kind + "_rows")
    return document["data"]


def _lenient_date(value):
    if value is None or value == "":
        return None, True
    if type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value).isoformat(), True
        except ValueError:
            pass
    return None, False


def _number(value, kind):
    try:
        return _base._number(value, positive=False)
    except SourceError:
        _fail(kind + "_number")


def _integer(value, kind):
    try:
        return _base._integer(value, positive=False)
    except SourceError:
        _fail(kind + "_integer")


def _typed(value, code, kind):
    if code == "D":
        return _base._iso_date(value, kind + "_date")
    if code == "S":
        if type(value) is not str or not value:
            _fail(kind + "_string")
        return value
    if code == "T":
        if value is not None and type(value) is not str:
            _fail(kind + "_string")
        return value
    if code == "A":
        if value is None:
            return None
        if type(value) is str:
            return value
        return str(_number(value, kind))
    if code == "P":
        number = _number(value, kind)
        if number < 0:
            _fail(kind + "_negative")
        return number
    if code == "N":
        return None if value is None else _number(value, kind)
    if code == "I":
        return _integer(value, kind)
    if code == "i":
        return None if value is None else _integer(value, kind)
    raise AssertionError(code)


def _parse_row(row, kind):
    required, codes = _FIELDS[kind]
    if type(row) is not dict:
        _fail(kind + "_row")
    if any(name not in row for name in required):
        _fail(kind + "_row_fields")
    parsed = {}
    unparsed = []
    for name, code in codes.items():
        if name not in row:
            continue
        if code == "d":
            iso, ok = _lenient_date(row[name])
            parsed[name] = iso
            if not ok:
                unparsed.append(name)
        else:
            parsed[name] = _typed(row[name], code, kind)
    parsed["_unparsed"] = tuple(unparsed)
    return parsed, row.keys()


def _trading_dates(document):
    """FinMind TaiwanStockTradingDate document -> its in-window dates; no fixed count, no closure inference."""
    rows = _document_rows(document, "trading_dates")
    if not rows:
        _fail("trading_dates_rows")
    # The documentation does not say whether start_date/end_date filter this dataset, so EVERY returned
    # row is structurally validated (keys, ISO date, unique, ascending) before rows outside the requested
    # window are discarded.
    dates = []
    for row in rows:
        if type(row) is not dict or set(row) != {"date"}:
            _fail("trading_dates_row")
        dates.append(_base._iso_date(row["date"], "trading_dates_date"))
    if any(earlier >= later for earlier, later in zip(dates, dates[1:])):
        _fail("trading_dates_order")
    return tuple(day for day in dates if WINDOW_START <= day <= WINDOW_END)


def _check_scope_against_formal(prior_dates):
    """The window must contain the whole formal span, which must end on the identity (anchor) day."""
    if prior_dates[-1] != IDENTITY_AS_OF or WINDOW_START > prior_dates[0]:
        _fail("scope_formal_coverage")


def _check_calendar(dates, prior_dates):
    """Whole-batch gate on the in-window observed trading days, before any other request."""
    if not dates:
        _fail("trading_dates_empty")
    if any(date.fromisoformat(day).weekday() >= 5 for day in dates):
        _fail("trading_dates_weekday")
    if IDENTITY_AS_OF not in dates:
        _fail("trading_dates_identity_day")
    # Independent in-repo check: the verified formal span must be exactly the formal dates. July and the
    # days after the formal span have no second source and are accepted as the provider returned them.
    if tuple(day for day in dates if prior_dates[0] <= day <= prior_dates[-1]) != prior_dates:
        _fail("trading_dates_formal_mismatch")


@dataclass(frozen=True, slots=True)
class PriceRow:
    date: str
    open: Fraction
    high: Fraction
    low: Fraction
    close: Fraction
    volume: int
    amount: int
    spread: object


def _price_rows(document, symbol):
    """Structure of every row first; zero-price rows are kept (they make the day incomparable)."""
    found = {}
    names = set()
    for row in _document_rows(document, "price"):
        parsed, keys = _parse_row(row, "price")
        names.update(keys)
        if parsed["stock_id"] != symbol:
            _fail("price_stock_id")
        if parsed["date"] in found:
            _fail("price_duplicate")
        found[parsed["date"]] = PriceRow(parsed["date"], parsed["open"], parsed["max"], parsed["min"],
                                         parsed["close"], parsed["Trading_Volume"], parsed["Trading_money"],
                                         parsed.get("spread"))
    return found, names


def _event_rows(document, kind, symbol):
    """All structurally valid rows of the requested symbol (any date), the foreign-row count and field names."""
    rows = []
    foreign = 0
    names = set()
    for row in _document_rows(document, kind):
        parsed, keys = _parse_row(row, kind)
        names.update(keys)
        if parsed["stock_id"] != symbol:
            foreign += 1
        else:
            rows.append(parsed)
    return tuple(rows), foreign, names


def _info_rows(document):
    """Structure of every row first; only the seven symbols are kept."""
    rows = {symbol: [] for symbol in SYMBOLS}
    names = set()
    for row in _document_rows(document, "info"):
        parsed, keys = _parse_row(row, "info")
        names.update(keys)
        if parsed["stock_id"] in rows:
            rows[parsed["stock_id"]].append((parsed.get("date"), parsed.get("type")))
    return {symbol: tuple(items) for symbol, items in rows.items()}, names



# --- derivation ----------------------------------------------------------------------------------

EVENT_KINDS = ("announced_without_result", "capital_reduction", "ex_dividend", "paid_subscription", "split")
_CAPITAL_FIELDS = ("TotalNumberOfCashCapitalIncrease", "CashIncreaseSubscriptionRate",
                   "CashIncreaseSubscriptionpRrice")
_AMOUNT_FIELDS = ("StockEarningsDistribution", "StockStatutorySurplus", "CashEarningsDistribution",
                  "CashStatutorySurplus")
_EX_DATE_FIELDS = ("StockExDividendTradingDate", "CashExDividendTradingDate")
_RATIO_EVENTS = (
    ("capital_reduction", "capital_reduction", "ClosingPriceonTheLastTradingDay", "PostReductionReferencePrice"),
    ("split", "split", "before_price", "after_price"),
)
_FORMULA_DIVIDEND = "(P-C)/P*1/(1+Rf)"
_FORMULA_RATIO = "after_reference/before_close"
_SPREAD_STATUSES = ("consistent", "semantics_unverified", "unexplained_change")
_DAY_REASONS = ("missing_row", "ohlc_zero", "ohlc_partial_zero", "ohlc_bounds")


def _ft(value):
    """Exact lowest-terms rational text ``n/d`` (positive denominator), or None."""
    return None if value is None else "%d/%d" % (value.numerator, value.denominator)


def _ftp(value):
    """Rational text of a strictly positive value; anything else is not stored as a price or factor."""
    return _ft(value) if value is not None and value > 0 else None


def _in_window(day):
    return WINDOW_START <= day <= WINDOW_END


def _tick(price):
    """Tick of the ladder band holding ``price`` (> 0); bands include their lower bound."""
    found = None
    for lower, tick in TICK_LADDER:
        if price >= lower:
            found = tick
    return found


def _reference_check(trace, prefix, computed, observed):
    """Compare ``computed`` with an observed reference; the observed value's own tick is the tolerance.

    Records the comparison in ``trace`` and returns None (nothing observed), True (strictly less than one tick
    apart) or False. The official rounding of reference prices is not stated, so equality is not required.
    """
    trace[prefix + "_reference"] = _ft(observed)
    if observed is None:
        trace[prefix + "_diff"] = trace[prefix + "_tick"] = None
        return None
    tick = _tick(observed) if observed > 0 else None
    difference = abs(computed - observed)
    trace[prefix + "_diff"] = _ft(difference)
    trace[prefix + "_tick"] = _ft(tick)
    return tick is not None and difference < tick


def _positive(value):
    return value is not None and value > 0


def _day_state(row):
    if row is None:
        return "missing_row"
    o, h, l, c = row.open, row.high, row.low, row.close
    zeros = [value == 0 for value in (o, h, l, c)]
    if all(zeros):
        return "ohlc_zero"
    if any(zeros):
        return "ohlc_partial_zero"
    if h < max(o, l, c) or l > min(o, h, c):
        return "ohlc_bounds"
    return None


def _spread_status(demonstrated, matched, unexplained):
    if not demonstrated or matched < SPREAD_MIN_MATCHED_DAYS:
        return "semantics_unverified"
    return "unexplained_change" if unexplained else "consistent"


def _supported_from(calendar, events, reasons):
    """First date for which the back-adjusted basis is supported: events strictly after a date affect it."""
    if reasons:
        return None
    return max((event["date"] for event in events if not event["supported"]), default=calendar[0])


def _event(kind, dataset, day, *, before=None, reference=None, factor=None, formula, trace, reasons,
           announced=(None, None)):
    reasons = sorted(set(reasons))
    if factor is None and not reasons:
        reasons = ["factor_unavailable"]
    return {"kind": kind, "date": day, "dataset": dataset, "announced_date": announced[0],
            "announced_time": announced[1], "before": _ftp(before), "reference": _ftp(reference),
            "factor": _ftp(factor), "formula": formula, "trace": trace,
            "supported": factor is not None and not reasons, "reasons": reasons}


def _dedupe(rows):
    seen = {}
    for row in rows:
        seen.setdefault(tuple(sorted((key, value) for key, value in row.items() if key != "_unparsed")), row)
    return list(seen.values())


def _by_date(rows):
    groups = {}
    for row in rows:
        if _in_window(row["date"]):
            groups.setdefault(row["date"], []).append(row)
    return groups


def _paid(row):
    """True / False, or None when the capital-increase fields cannot show either."""
    if any(name not in row for name in _CAPITAL_FIELDS):
        return None
    return any(row[name] is not None and row[name] > 0 for name in _CAPITAL_FIELDS)


def _has_amount(row):
    return any(row.get(name) is not None and row[name] > 0 for name in _AMOUNT_FIELDS + _CAPITAL_FIELDS)


def _terms(term, day):
    reasons = []
    totals = {"cash": Fraction(0), "stock": Fraction(0)}
    for name, ex_field, keys in (("cash", "CashExDividendTradingDate", ("CashEarningsDistribution", "CashStatutorySurplus")),
                                 ("stock", "StockExDividendTradingDate", ("StockEarningsDistribution", "StockStatutorySurplus"))):
        if term.get(ex_field) != day:
            continue
        if any(key not in term for key in keys):
            reasons.append("dividend_terms_missing")
        elif any(term[key] is not None and term[key] < 0 for key in keys):
            reasons.append("dividend_terms_invalid")
        else:
            totals[name] = sum((term[key] for key in keys if term[key] is not None), Fraction(0))
    return totals["cash"], totals["stock"] / STOCK_DIVIDEND_PAR_TWD, reasons


def _announced(term):
    time_text = term.get("AnnouncementTime")
    return term.get("AnnouncementDate"), time_text if time_text else None


def _dividend_events(result_rows, dividend_rows, implied):
    events = []
    for day, rows in sorted(_by_date(result_rows).items()):
        unique = _dedupe(rows)
        row = unique[0]
        reasons = ["event_duplicate_conflict"] if len(unique) > 1 else []
        price, reference = row.get("before_price"), row.get("reference_price")
        if not (_positive(price) and _positive(reference)):
            reasons.append("event_price_invalid")
        ratio = reference / price if _positive(reference) and _positive(price) else None
        candidates = _dedupe([term for term in dividend_rows
                              if day in (term.get("StockExDividendTradingDate"), term.get("CashExDividendTradingDate"))])
        cash = rf = None
        announced = (None, None)
        if not candidates:
            reasons.append("dividend_terms_unmatched")
        elif len(candidates) > 1:
            reasons.append("dividend_terms_ambiguous")
        else:
            term = candidates[0]
            announced = _announced(term)
            paid = _paid(term)
            if paid is None:
                reasons.append("paid_subscription_fields_missing")
            elif paid:
                reasons.append("paid_subscription_unsupported")
            cash, rf, term_reasons = _terms(term, day)
            reasons += term_reasons
        factor = None
        trace = {"P": _ft(price), "C": _ft(cash), "Rf": _ft(rf), "par_twd": str(STOCK_DIVIDEND_PAR_TWD),
                 "reference_ratio": _ft(ratio), "R": None, "f3_reference": None, "f3_diff": None, "f3_tick": None,
                 "spread_reference": None, "spread_diff": None, "spread_tick": None}
        if not reasons:
            if price - cash <= 0:
                reasons.append("cash_exceeds_price")
            else:
                factor = (price - cash) / price / (1 + rf)
                computed = (price - cash) / (1 + rf)  # the unrounded reference price the factor implies
                trace["R"] = _ft(computed)
                # Both checks must pass; the spread one only exists when the day has a comparable row with spread.
                checks = (_reference_check(trace, "f3", computed, reference),
                          _reference_check(trace, "spread", computed, implied.get(day)))
                if False in checks:
                    reasons.append("factor_reference_mismatch")
        events.append(_event(
            "ex_dividend", "dividend_result", day, before=price, reference=reference, factor=factor,
            formula=_FORMULA_DIVIDEND, announced=announced, reasons=reasons, trace=trace))
    return events


def _ratio_events(rows, event_kind, dataset, before_field, after_field, implied):
    events = []
    for day, group in sorted(_by_date(rows).items()):
        unique = _dedupe(group)
        row = unique[0]
        reasons = ["event_duplicate_conflict"] if len(unique) > 1 else []
        before, after = row.get(before_field), row.get(after_field)
        if not (_positive(before) and _positive(after)):
            reasons.append("event_price_invalid")
        trace = {"before_field": before_field, "after_field": after_field, "spread_reference": None,
                 "spread_diff": None, "spread_tick": None}
        factor = None
        if not reasons:
            factor = after / before
            # No other source states this reference, so the day's close - spread is the only cross-check.
            check = _reference_check(trace, "spread", after, implied.get(day))
            if check is None:
                reasons.append("factor_reference_unverified")
            elif not check:
                reasons.append("factor_reference_mismatch")
        events.append(_event(event_kind, dataset, day, before=before, reference=after, factor=factor,
                             formula=_FORMULA_RATIO, reasons=reasons, trace=trace))
    return events


def _dividend_only_events(dividend_rows, covered):
    """In-window ex-dates that no result / reduction / split row explains."""
    days = sorted({day for term in dividend_rows for day in (term.get(name) for name in _EX_DATE_FIELDS)
                   if day is not None and _in_window(day)})
    events = []
    for day in days:
        if day in covered:
            continue
        candidates = _dedupe([term for term in dividend_rows if day in (term.get(name) for name in _EX_DATE_FIELDS)])
        term = candidates[0]
        paid = _paid(term)
        reasons = ["dividend_terms_ambiguous"] if len(candidates) > 1 else []
        reasons.append("paid_subscription_unsupported" if paid else "dividend_result_missing")
        if paid is None:
            reasons.append("paid_subscription_fields_missing")
        events.append(_event("paid_subscription" if paid else "announced_without_result", "dividend", day,
                             formula="unsupported", reasons=reasons, announced=_announced(term), trace={}))
    return events


def _dividend_symbol_reasons(dividend_rows):
    reasons = set()
    for row in dividend_rows:
        if not WINDOW_START <= row["date"] <= DIVIDEND_END:
            continue
        ex_dates = [row.get(name) for name in _EX_DATE_FIELDS if row.get(name) is not None]
        if any(name in row["_unparsed"] for name in _EX_DATE_FIELDS):
            reasons.add("f4_date_unparsed")
        if not ex_dates and _has_amount(row):
            reasons.add("f4_ex_date_unknown")
        if any(_in_window(day) for day in ex_dates) and _paid(row) is None:
            reasons.add("paid_subscription_fields_missing")
    return reasons


def _select_info(items):
    if not items:
        return None, None, ["info_missing"]
    newest = max(day or "" for day, _ in items)
    top = {(day, kind) for day, kind in items if (day or "") == newest}
    if len(top) > 1:
        return None, None, ["info_ambiguous"]
    day, kind = next(iter(top))
    return day, kind, [] if kind in INFO_ACCEPTED_TYPES else ["market_type_not_accepted"]


def _assess_symbol(symbol, calendar, prices, info_items, anchor, rows, foreign):
    window_prices = {day: row for day, row in prices.items() if _in_window(day)}
    trading = set(calendar)
    info_day, info_type, refusal = _select_info(info_items)
    if any(day not in trading for day in window_prices):
        refusal.append("price_row_off_calendar")
    if not window_prices:
        refusal.append("price_rows_missing")
    row = window_prices.get(IDENTITY_AS_OF)
    if row is None or (row.open, row.high, row.low, row.close, row.volume, row.amount) != anchor:
        refusal.append("identity_anchor_mismatch")
    incomparable = []
    for day in calendar:
        reason = _day_state(window_prices.get(day))
        if reason:
            incomparable.append([day, reason])
    implied = {day: item.close - item.spread for day, item in window_prices.items()
               if item.spread is not None and _day_state(item) is None}  # close - spread = the day's reference price
    events = _dividend_events(rows["dividend_result"], rows["dividend"], implied)
    for kind, event_kind, before_field, after_field in _RATIO_EVENTS:
        events += _ratio_events(rows[kind], event_kind, kind, before_field, after_field, implied)
    events += _dividend_only_events(rows["dividend"], {event["date"] for event in events})
    by_day = {}
    for event in events:
        by_day.setdefault(event["date"], []).append(event)
        if event["date"] not in trading:
            event["reasons"] = sorted(set(event["reasons"]) | {"event_date_not_trading_day"})
    for items in by_day.values():
        if len(items) > 1:
            for event in items:
                event["reasons"] = sorted(set(event["reasons"]) | {"same_day_multiple_events"})
    for event in events:
        event["supported"] = event["factor"] is not None and not event["reasons"]
    events.sort(key=lambda event: (event["date"], event["kind"]))
    event_days = set(by_day)
    prior = None
    checked = matched = 0
    mismatch, unexplained, demonstrating = [], [], []
    for day in calendar:
        item = window_prices.get(day)
        if item is None or _day_state(item) is not None:
            continue
        if prior is not None and item.spread is not None:
            checked += 1
            if item.close - item.spread == prior:
                matched += 1
            else:
                mismatch.append(day)
                (demonstrating if day in event_days else unexplained).append(day)
        prior = item.close
    return {
        "status": "refused" if refusal else "usable", "refusal_reasons": sorted(set(refusal)),
        "info": {"type": info_type, "date": info_day}, "incomparable_days": incomparable,
        "spread_check": {"status": "", "checked": checked, "matched": matched, "mismatch_dates": mismatch,
                         "unexplained_dates": unexplained, "demonstrating_dates": demonstrating},
        "events": events, "adjusted": {"supported_from": None, "reasons": sorted(_dividend_symbol_reasons(rows["dividend"]))},
        "foreign_rows": dict(foreign),
    }


def _derive(dates, prices, rows, info, prior_dates, anchors, observed, foreign):
    """Per-symbol assessments and the canonical data document from the structurally valid captures."""
    calendar = list(dates)
    symbols = {}
    for symbol in SYMBOLS:
        symbols[symbol] = _assess_symbol(
            symbol, calendar, prices[symbol], info[symbol], anchors[symbol],
            {kind: rows[kind][symbol] for kind in EVENT_SOURCE_KINDS}, foreign[symbol])
    evidence = sorted([symbol, day] for symbol, entry in symbols.items()
                      for day in entry["spread_check"]["demonstrating_dates"])
    demonstrated = bool(evidence)
    for entry in symbols.values():
        check = entry["spread_check"]
        check["status"] = _spread_status(demonstrated, check["matched"], check["unexplained_dates"])
        adjusted = entry["adjusted"]
        if check["status"] != "consistent":
            adjusted["reasons"] = sorted(set(adjusted["reasons"]) | {check["status"]})
        adjusted["supported_from"] = _supported_from(calendar, entry["events"], adjusted["reasons"])
    data = {
        "schema": STORAGE_SCHEMA,
        "window": {"start_date": WINDOW_START, "end_date": WINDOW_END, "dividend_end_date": DIVIDEND_END},
        "calendar": calendar, "calendar_after_formal": [day for day in calendar if day > IDENTITY_AS_OF],
        "spread_semantics": {"demonstrated": demonstrated, "evidence": evidence},
        "observed_fields": {kind: sorted(names) for kind, names in sorted(observed.items())},
        "symbols": symbols,
    }
    metrics = {"calendar_rows": len(calendar),
               "price_rows": sum(1 for symbol in SYMBOLS for day in prices[symbol] if _in_window(day)),
               "event_rows": sum(len(entry["events"]) for entry in symbols.values())}
    return data, metrics



# --- acquisition ---------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OracleAdmission:
    """Independent source-oracle assertion; it also binds the canonical derived-data bytes."""
    namespace: str
    policy_sha256: str
    holder_thread_id: str
    candidate_sha: str
    script_sha256: str
    receipt_sha256s: tuple
    calendar_rows: int
    price_rows: int
    event_rows: int
    data_sha256: str
    independent: bool


@dataclass(frozen=True, slots=True)
class SavedBundle:
    action: str
    policy_version: str
    window_end: str
    path: str
    data_sha256: str
    data_bytes: int
    receipt_sha256: str
    receipt_bytes: int
    saved_at: str


class AttemptLedger(_base.AttemptLedger):
    """One whole batch per ledger; no reset/release/retry API (issue 32 semantics, 37 GETs, issue 98 namespace)."""

    def __init__(self, namespace):
        if namespace != NAMESPACE:
            _fail("quota_namespace")
        self.namespace = namespace
        self._begun = False
        self._attempted = []

    @property
    def unrun(self):
        return tuple(range(len(self._attempted), MAX_GETS))

    def charge(self, index):
        if not self._begun or type(index) is not int or index != len(self._attempted) or index >= MAX_GETS:
            _fail("quota_order")
        self._attempted.append(index)  # SPENT before open, including open failure.


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


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
    if start.version != SEAL_VERSION or start.namespace != NAMESPACE or start.policy_sha256 != pins.sha256:
        _fail("financial_start_scope")
    # Issuer/coordinator/implementer identities come from the seal and are checked by the QA caller
    # against the Issue receipts; this module pins none.
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
    if SEAL_COMMENT_FLOOR is None:
        _fail("seal_floor_unset")
    match = re.fullmatch(SEAL_URL_PATTERN, start.seal_comment_url)
    if not match or int(match.group(1)) <= SEAL_COMMENT_FLOOR:
        _fail("financial_new_explicit_seal_required")


class CalendarActionsSource:
    """Only acquisition object; pending/failed/expired/released are consumer-inert."""

    def __init__(self, *, policy_canonical, policy_sha256, formal_blob, purpose=PURPOSE, pins=None,
                 transport=None, ledger=None, financial_start=None, execution_binding=None,
                 clock=time.monotonic, lease_seconds=LEASE_SECONDS, observer_roots=None):
        real = transport is None or isinstance(transport, _base._HTTPSTransport)
        if real:
            if pins is not None:
                _fail("pins_with_default_transport")
            pins = _real_pins()
        elif type(pins) is not Pins:
            _fail("boundary_pins_required")
        self._pins = _pins(pins)
        self._policy = validate_policy(policy_canonical, policy_sha256, self._pins)
        if type(purpose) is not str or purpose != PURPOSE:
            _fail("unsupported_purpose")
        self._formal_blob = formal_blob
        self._prior_dates, self._anchors = _base._formal_reference(formal_blob)
        _check_scope_against_formal(self._prior_dates)
        if (type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds)
                or not 0 < lease_seconds <= LEASE_SECONDS):
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
        self._dates = ()
        self._prices = {}
        self._rows = {kind: {} for kind in EVENT_SOURCE_KINDS}
        self._foreign = {symbol: {kind: 0 for kind in EVENT_SOURCE_KINDS} for symbol in SYMBOLS}
        self._info = {}
        self._observed = {}
        self._data = {}
        self._data_bytes = b""
        self._metrics = {}
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
        if (type(current) not in (int, float) or not math.isfinite(current)
                or (self._last_clock is not None and current < self._last_clock)):
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
        if self._roots_estimate > ROOTS_CAP:
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
                primary_failure["secondary_validation_omitted"] = min(
                    4, primary_failure["secondary_validation_omitted"] + 1)

    def _capture_ready(self, capture):
        full_body, receipt = capture.body, capture.receipt
        self._check_roots(full_body, receipt)
        return capture

    def _capture(self, step):
        index, url = step.index, step.url
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
            if not _CONTENT_TYPE.fullmatch(header_values.get("content-type", "").strip()):
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
            version = self._policy["calendar"]["version"] if step.kind == "calendar" else self._policy["version"]
            receipt = _base.Receipt(step.source_id, version, "GET", url, 200,
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

    def _store(self, step, results, names, foreign=0):
        kind = step.kind
        self._observed.setdefault(kind, set()).update(names)
        if kind == "price":
            self._prices[step.symbol] = results
        elif kind == "info":
            self._info = results
        elif kind in EVENT_SOURCE_KINDS:
            self._rows[kind][step.symbol] = results
            self._foreign[step.symbol][kind] = foreign

    def _parse_capture(self, capture, step):
        full_body, receipt = capture.body, capture.receipt
        decoded_text = document = parse_results = None
        diagnostics = {"source_index": step.index, "stage": "decode_parse"}
        try:
            self._remaining()
            decoded_text = full_body.decode("utf-8")
            self._decoded_texts.append(decoded_text)
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            kind = step.kind
            document = _base._json(decoded_text, price=kind != "calendar")
            self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
            self._remaining()
            if kind == "calendar":
                parse_results = _trading_dates(document)
            elif kind == "price":
                parse_results, names = _price_rows(document, step.symbol)
                self._store(step, parse_results, names)
            elif kind == "info":
                parse_results, names = _info_rows(document)
                self._store(step, parse_results, names)
            else:
                parse_results, foreign, names = _event_rows(document, kind, step.symbol)
                self._store(step, parse_results, names, foreign)
            self._documents.append(_base._freeze(document))
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            return parse_results
        except BaseException as exception:
            primary_failure = _base._failure_values(exception, "decode_parse")
            primary_failure["source_index"] = step.index
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
        self._batch_deadline = self._now() + BATCH_SECONDS
        pending = self
        try:
            dates = self._parse_capture(self._capture(STEPS[0]), STEPS[0])
            _check_calendar(dates, self._prior_dates)  # before any other request
            self._dates = dates
            for step in STEPS[1:]:
                self._parse_capture(self._capture(step), step)
                self._check_roots(pending, self._prices, self._rows)
            self._remaining()
            self._data, self._metrics = _derive(
                dates, self._prices, self._rows, self._info, self._prior_dates, self._anchors,
                self._observed, self._foreign)
            self._data_bytes = _base._canonical(self._data)
            if len(self._data_bytes) > DATA_CAP:
                _fail("data_cap")
            self._check_roots(pending, self._data)
            self._remaining()
            self._expiry = min(self._now() + self._lease_seconds, self._batch_deadline)
            self._state = "pending"
            return pending
        except BaseException as exception:
            primary_failure = _base._failure_values(exception, "batch")
            self._state = "failed"
            self._data, self._data_bytes, self._metrics = {}, b"", {}  # a failed batch derives nothing
            primary_failure.update(attempts=len(self._ledger.attempted), raw_bytes=self._raw_bytes)
            diagnostics = {"stage": "batch", **primary_failure}
            self._diagnostics = MappingProxyType(diagnostics)
            self._check_failure_roots(primary_failure, "batch_failure_roots", pending, diagnostics, exception)
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
                                 "prices": MappingProxyType(dict(self._prices)),
                                 "event_rows": MappingProxyType({kind: MappingProxyType(dict(rows))
                                                                  for kind, rows in self._rows.items()}),
                                 "info": MappingProxyType(dict(self._info)),
                                 "dates": self._dates,
                                 "data_bytes": self._data_bytes,
                                 "metrics": MappingProxyType(dict(self._metrics)),
                                 "diagnostics": self._diagnostics,
                                 "retained_roots_estimate_bytes": self._roots_estimate})

    def admit_independent_verification(self, admission):
        if self.state != "pending" or type(admission) is not OracleAdmission:
            _fail("oracle_pending_required")
        for item in fields(admission):
            value = getattr(admission, item.name)
            expected = (tuple if item.name == "receipt_sha256s" else bool if item.name == "independent"
                        else int if item.name.endswith("rows") else str)
            if type(value) is not expected:
                _fail("oracle_type")
        if (admission.independent is not True
                or (admission.namespace, admission.policy_sha256) != (NAMESPACE, self._pins.sha256)):
            _fail("oracle_scope")
        if any(type(value) is not str or not _HEX64.fullmatch(value) for value in admission.receipt_sha256s):
            _fail("oracle_receipt_type")
        if not _HEX64.fullmatch(admission.data_sha256):
            _fail("oracle_receipt_type")
        counts = (self._metrics["calendar_rows"], self._metrics["price_rows"], self._metrics["event_rows"])
        if (admission.calendar_rows, admission.price_rows, admission.event_rows) != counts:
            _fail("oracle_complete_scope")
        hashes = tuple(capture.receipt.canonical_sha256 for capture in self._captures)
        if len(hashes) != MAX_GETS or admission.receipt_sha256s != hashes:
            _fail("oracle_capture_binding")
        if admission.data_sha256 != hashlib.sha256(self._data_bytes).hexdigest():
            _fail("oracle_data_binding")
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
        digest = hashlib.sha256(self._data_bytes).hexdigest()
        return {
            "schema": RECEIPT_SCHEMA, "storage": "private_local", "storage_schema": STORAGE_SCHEMA,
            "namespace": NAMESPACE, "purpose": PURPOSE, "consumer_version": CONSUMER_VERSION,
            "source_policy": {"version": POLICY_VERSION, "sha256": self._pins.sha256, "bytes": self._pins.nbytes},
            "calendar_source_version": policy["calendar"]["version"],
            "market": MARKET, "instrument_type": INSTRUMENT_TYPE, "identity_as_of": IDENTITY_AS_OF,
            "window": {"start_date": WINDOW_START, "end_date": WINDOW_END, "dividend_end_date": DIVIDEND_END},
            "calendar_rows": len(self._dates), "gets": gets,
            "adapter": {"tpex_calendar_actions_source_sha256": _file_sha256(os.path.abspath(__file__)),
                        "ohlcv_history_source_sha256": _file_sha256(os.path.abspath(_base.__file__))},
            "data": {"file": DATA_FILE, "sha256": digest, "bytes": len(self._data_bytes)},
            "data_version": DATA_VERSION_PREFIX + digest,
            "saved_at": saved_at, "attribution": policy["attribution"], "rights": policy["rights"],
            "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
            "limitations": list(LIMITATIONS),
        }

    def save(self, *, root=None):
        """Publish the admitted derived data below the private root (idempotent, never overwrites).

        The default transport writes only to ``PRIVATE_ROOT``; a boundary transport must name its own
        root and can never name the real one.
        """
        self._usable()
        if self._real:
            if root is not None and not _same_path(_absolute(root, "root_invalid"), PRIVATE_ROOT):
                _fail("root_not_private_root")
            root = PRIVATE_ROOT
        else:
            if root is None:
                _fail("root_required_for_boundary")
            root = _absolute(root, "root_invalid")
            if _same_path(root, PRIVATE_ROOT):
                _fail("boundary_root_is_private_root")
        root = _absolute(root, "root_invalid")
        receipt_bytes = _base._canonical(self._receipt_document(_utc_now()))
        if len(self._data_bytes) > DATA_CAP:
            _fail("data_cap")
        if len(receipt_bytes) > RECEIPT_CAP:
            _fail("receipt_cap")
        # Full verification in RAM, with the reader's own code, before anything touches the disk.
        _verify_bundle(self._data_bytes, receipt_bytes, self._pins)
        return _publish(root, self._data_bytes, receipt_bytes, self._pins)

    def release(self, *, expired=False):
        self._capture_buffer.clear()
        self._captures.clear()
        self._decoded_texts.clear()
        self._documents.clear()
        self._prices = {}
        self._rows = {kind: {} for kind in EVENT_SOURCE_KINDS}
        self._info = {}
        self._observed = {}
        self._data = {}
        self._data_bytes = b""
        self._metrics = {}
        self._formal_blob = b""
        self._anchors = MappingProxyType({})
        self._transport = None
        self._observer_roots = None
        self._dates = ()
        self._state = "expired" if expired else "released"
        # The one-shot ledger is deliberately retained and never reset.


def save_calendar_actions(source, *, root=None):
    if type(source) is not CalendarActionsSource:
        _fail("source_required")
    return source.save(root=root)



# --- saved bundle: layout, verification, publication ---------------------------------------------

_RECEIPT_FIELDS = tuple(item.name for item in fields(_base.Receipt))
_GET_STRINGS = ("source_id", "source_version", "method", "url", "request_started_utc", "observed_utc",
                "body_sha256", "content_type", "content_encoding", "namespace", "policy_sha256", "receipt_sha256")
_GET_SHAPE = {**{key: str for key in _GET_STRINGS}, "status": int, "body_bytes": int, "full_eof": bool}
_RECEIPT_SHAPE = {
    "schema": str, "storage": str, "storage_schema": str, "namespace": str, "purpose": str,
    "consumer_version": str,
    "source_policy": {"version": str, "sha256": str, "bytes": int},
    "calendar_source_version": str, "market": str, "instrument_type": str, "identity_as_of": str,
    "window": {"start_date": str, "end_date": str, "dividend_end_date": str}, "calendar_rows": int,
    "gets": (dict, MAX_GETS),
    "adapter": {"tpex_calendar_actions_source_sha256": str, "ohlcv_history_source_sha256": str},
    "data": {"file": str, "sha256": str, "bytes": int}, "data_version": str,
    "saved_at": str, "attribution": str, "rights": str,
    "publication_time": str, "first_availability": str, "revision_time": str,
    "limitations": (str, len(LIMITATIONS)),
}
_DATA_KEYS = {"schema", "window", "calendar", "calendar_after_formal", "spread_semantics", "observed_fields", "symbols"}
_SYMBOL_KEYS = {"status", "refusal_reasons", "info", "incomparable_days", "spread_check", "events", "adjusted",
                "foreign_rows"}
_SPREAD_KEYS = {"status", "checked", "matched", "mismatch_dates", "unexplained_dates", "demonstrating_dates"}
_EVENT_KEYS = {"kind", "date", "dataset", "announced_date", "announced_time", "before", "reference", "factor",
               "formula", "trace", "supported", "reasons"}


def _file_sha256(path):
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        _fail("adapter_hash_unavailable")


def _same_path(first, second):
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


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


def _need(condition, code="saved_shape", **diagnostics):
    if not condition:
        _fail(code, **diagnostics)


def _is_iso(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _is_day(value, allowed):
    return type(value) is str and value in allowed


def _is_date_list(value, allowed):
    return type(value) is list and all(_is_day(day, allowed) for day in value) and value == sorted(set(value))


def _is_code_list(value):
    return (type(value) is list and all(type(item) is str and _CODE.fullmatch(item) for item in value)
            and value == sorted(set(value)))


def _is_rational(value):
    if type(value) is not str or not _RATIONAL.fullmatch(value):
        return False
    numerator, denominator = (int(part) for part in value.split("/"))
    return math.gcd(numerator, denominator) == 1


def _check_event(event, symbol, calendar_set):
    _need(type(event) is dict and set(event) == _EVENT_KEYS, "saved_event", symbol=symbol)
    _need(event["kind"] in EVENT_KINDS and event["dataset"] in EVENT_SOURCE_KINDS, "saved_event", symbol=symbol)
    _need(_is_iso(event["date"]) and _in_window(event["date"]), "saved_event", symbol=symbol)
    _need(event["announced_date"] is None or _is_iso(event["announced_date"]), "saved_event", symbol=symbol)
    time_text = event["announced_time"]
    _need(time_text is None or (type(time_text) is str and 0 < len(time_text) <= 32), "saved_event", symbol=symbol)
    _need(all(event[name] is None or _is_rational(event[name]) for name in ("before", "reference", "factor")),
          "saved_event", symbol=symbol)
    _need(event["formula"] in (_FORMULA_DIVIDEND, _FORMULA_RATIO, "unsupported"), "saved_event", symbol=symbol)
    trace = event["trace"]
    _need(type(trace) is dict and len(trace) <= 16 and all(
        type(key) is str and 0 < len(key) <= 64 and (value is None or (type(value) is str and len(value) <= 128))
        for key, value in trace.items()), "saved_event", symbol=symbol)
    _need(_is_code_list(event["reasons"]), "saved_event", symbol=symbol)
    _need(type(event["supported"]) is bool
          and event["supported"] == (event["factor"] is not None and not event["reasons"]),
          "saved_event", symbol=symbol)
    if event["date"] not in calendar_set:
        _need("event_date_not_trading_day" in event["reasons"], "saved_event", symbol=symbol)


def _check_symbol(symbol, entry, calendar, demonstrated):
    calendar_set = set(calendar)
    _need(type(entry) is dict and set(entry) == _SYMBOL_KEYS, "saved_symbol", symbol=symbol)
    _need(entry["status"] in ("usable", "refused"), "saved_symbol", symbol=symbol)
    _need(_is_code_list(entry["refusal_reasons"]) and (entry["status"] == "refused") == bool(entry["refusal_reasons"]),
          "saved_symbol", symbol=symbol)
    info = entry["info"]
    _need(type(info) is dict and set(info) == {"type", "date"}
          and (info["type"] is None or (type(info["type"]) is str and len(info["type"]) <= 64))
          and (info["date"] is None or _is_iso(info["date"])), "saved_symbol", symbol=symbol)
    days = entry["incomparable_days"]
    _need(type(days) is list and all(
        type(item) is list and len(item) == 2 and _is_day(item[0], calendar_set) and item[1] in _DAY_REASONS
        for item in days) and [item[0] for item in days] == sorted({item[0] for item in days}),
        "saved_symbol", symbol=symbol)
    check = entry["spread_check"]
    _need(type(check) is dict and set(check) == _SPREAD_KEYS, "saved_symbol", symbol=symbol)
    _need(all(type(check[name]) is int and check[name] >= 0 for name in ("checked", "matched"))
          and check["matched"] <= check["checked"] <= len(calendar), "saved_symbol", symbol=symbol)
    lists = [check[name] for name in ("mismatch_dates", "unexplained_dates", "demonstrating_dates")]
    _need(all(_is_date_list(item, calendar_set) for item in lists), "saved_symbol", symbol=symbol)
    mismatch, unexplained, demonstrating = (set(item) for item in lists)
    _need(not unexplained & demonstrating and mismatch == unexplained | demonstrating
          and len(mismatch) == check["checked"] - check["matched"], "saved_symbol", symbol=symbol)
    _need(check["status"] == _spread_status(demonstrated, check["matched"], check["unexplained_dates"]),
          "saved_spread_status", symbol=symbol)
    events = entry["events"]
    _need(type(events) is list, "saved_event", symbol=symbol)
    for event in events:
        _check_event(event, symbol, calendar_set)
    keys = [(event["date"], event["kind"]) for event in events]
    _need(keys == sorted(set(keys)), "saved_event", symbol=symbol)
    event_days = {event["date"] for event in events}
    _need(not unexplained & event_days and demonstrating <= event_days, "saved_event", symbol=symbol)
    for day in event_days:
        group = [event for event in events if event["date"] == day]
        _need(len(group) == 1 or all("same_day_multiple_events" in event["reasons"] for event in group),
              "saved_event", symbol=symbol)
    adjusted = entry["adjusted"]
    _need(type(adjusted) is dict and set(adjusted) == {"supported_from", "reasons"}
          and _is_code_list(adjusted["reasons"]), "saved_adjusted", symbol=symbol)
    _need(check["status"] == "consistent" or check["status"] in adjusted["reasons"], "saved_adjusted", symbol=symbol)
    supported_from = adjusted["supported_from"]
    _need(supported_from is None or _is_iso(supported_from), "saved_adjusted", symbol=symbol)
    _need(supported_from == _supported_from(calendar, events, adjusted["reasons"]), "saved_adjusted", symbol=symbol)
    foreign = entry["foreign_rows"]
    _need(type(foreign) is dict and set(foreign) == set(EVENT_SOURCE_KINDS)
          and all(type(value) is int and value >= 0 for value in foreign.values()), "saved_symbol", symbol=symbol)
    return [[symbol, day] for day in check["demonstrating_dates"]]


def _check_data(data):
    _need(type(data) is dict and set(data) == _DATA_KEYS)
    _need(data["schema"] == STORAGE_SCHEMA and data["window"] == {
        "start_date": WINDOW_START, "end_date": WINDOW_END, "dividend_end_date": DIVIDEND_END}, "saved_value")
    calendar = data["calendar"]
    _need(type(calendar) is list and calendar and all(_is_iso(day) for day in calendar), "saved_calendar")
    _need(calendar == sorted(set(calendar)) and all(
        date.fromisoformat(day).weekday() < 5 and _in_window(day) for day in calendar)
        and IDENTITY_AS_OF in calendar, "saved_calendar")
    _need(data["calendar_after_formal"] == [day for day in calendar if day > IDENTITY_AS_OF], "saved_calendar")
    semantics = data["spread_semantics"]
    _need(type(semantics) is dict and set(semantics) == {"demonstrated", "evidence"}
          and type(semantics["demonstrated"]) is bool and type(semantics["evidence"]) is list, "saved_semantics")
    observed = data["observed_fields"]
    _need(type(observed) is dict and set(observed) <= {kind for kind, *_ in _SOURCES} and all(
        type(names) is list and names == sorted(set(names))
        and all(type(name) is str and 0 < len(name) <= 128 for name in names)
        for names in observed.values()))
    symbols = data["symbols"]
    _need(type(symbols) is dict and list(symbols) == list(SYMBOLS))
    evidence = []
    for symbol in SYMBOLS:
        evidence += _check_symbol(symbol, symbols[symbol], calendar, semantics["demonstrated"])
    _need(semantics["evidence"] == sorted(evidence) and semantics["demonstrated"] == bool(evidence),
          "saved_semantics")


def _verify_bundle(data_bytes, receipt_bytes, pins):
    """Full verification of the two byte strings; returns the parsed (data, receipt) documents."""
    if len(data_bytes) > DATA_CAP or len(receipt_bytes) > RECEIPT_CAP:
        _fail("saved_size_cap")
    data = _parse_saved(data_bytes, "data")
    receipt = _parse_saved(receipt_bytes, "receipt")
    _check_data(data)
    _saved_shape(receipt, _RECEIPT_SHAPE)
    digest = hashlib.sha256(data_bytes).hexdigest()
    fixed = (
        (receipt["schema"], RECEIPT_SCHEMA), (receipt["storage"], "private_local"),
        (receipt["storage_schema"], STORAGE_SCHEMA), (receipt["namespace"], NAMESPACE),
        (receipt["purpose"], PURPOSE), (receipt["consumer_version"], CONSUMER_VERSION),
        (receipt["market"], MARKET), (receipt["instrument_type"], INSTRUMENT_TYPE),
        (receipt["identity_as_of"], IDENTITY_AS_OF), (receipt["publication_time"], "unknown"),
        (receipt["first_availability"], "unknown"), (receipt["revision_time"], "unknown"),
        (receipt["limitations"], list(LIMITATIONS)),
        (receipt["window"], {"start_date": WINDOW_START, "end_date": WINDOW_END, "dividend_end_date": DIVIDEND_END}),
        (receipt["data_version"], DATA_VERSION_PREFIX + digest),
    )
    if any(actual != expected for actual, expected in fixed):
        _fail("saved_value")
    policy = receipt["source_policy"]
    if (policy["version"] != POLICY_VERSION or policy["sha256"] != pins.sha256 or policy["bytes"] != pins.nbytes):
        _fail("saved_pin_or_scope")
    if (not receipt["attribution"] or len(receipt["attribution"]) > 1024 or not receipt["rights"]
            or len(receipt["rights"]) > 1024 or not _SOURCE_VERSION.fullmatch(receipt["calendar_source_version"])):
        _fail("saved_value")
    if receipt["calendar_rows"] != len(data["calendar"]):
        _fail("saved_calendar_rows")
    previous = None
    total = 0
    for index, entry in enumerate(receipt["gets"]):
        _saved_shape(entry, _GET_SHAPE)
        step = STEPS[index]
        version = receipt["calendar_source_version"] if step.kind == "calendar" else POLICY_VERSION
        if (entry["source_id"] != step.source_id or entry["source_version"] != version or entry["method"] != "GET"
                or entry["url"] != step.url or entry["status"] != 200 or entry["full_eof"] is not True
                or entry["content_encoding"] != "identity" or not _CONTENT_TYPE.fullmatch(entry["content_type"])
                or entry["namespace"] != NAMESPACE or entry["policy_sha256"] != pins.sha256):
            _fail("saved_get", source_index=index)
        if not 1 <= entry["body_bytes"] <= BODY_CAP or not _HEX64.fullmatch(entry["body_sha256"]):
            _fail("saved_get", source_index=index)
        total += entry["body_bytes"]
        started, observed = _utc(entry["request_started_utc"]), _utc(entry["observed_utc"])
        if started > observed or (previous is not None and started < previous):
            _fail("saved_get_times", source_index=index)
        previous = observed
        recomputed = hashlib.sha256(_base._canonical({name: entry[name] for name in _RECEIPT_FIELDS})).hexdigest()
        if entry["receipt_sha256"] != recomputed:
            _fail("saved_get_receipt_sha", source_index=index)
    if total > RAW_CAP:
        _fail("saved_get")
    if _utc(receipt["saved_at"]) < previous:
        _fail("saved_get_times")
    if any(not _HEX64.fullmatch(value) for value in receipt["adapter"].values()):
        _fail("saved_adapter")
    reference = receipt["data"]
    if reference["file"] != DATA_FILE or reference["bytes"] != len(data_bytes) or reference["sha256"] != digest:
        _fail("saved_data_reference")
    return data, receipt


def _load_verified(root, pins):
    root = _absolute(root, "root_invalid")
    _lstat(root, "root", "dir")
    _lstat(os.path.join(root, POLICY_VERSION), "policy_dir", "dir")
    final = os.path.join(root, POLICY_VERSION, WINDOW_END)
    _lstat(final, "final", "dir")
    try:
        names = sorted(os.listdir(final))
    except OSError:
        _fail("storage_io_failure", kind="final")
    if names != sorted((DATA_FILE, RECEIPT_FILE)):
        _fail("saved_entries")
    data_bytes = _read_capped(os.path.join(final, DATA_FILE), DATA_CAP, "data")
    receipt_bytes = _read_capped(os.path.join(final, RECEIPT_FILE), RECEIPT_CAP, "receipt")
    data, receipt = _verify_bundle(data_bytes, receipt_bytes, pins)
    return data_bytes, receipt_bytes, data, receipt, final


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
    bundles = files = total = 0
    for name in sorted(os.listdir(root)):
        if name != POLICY_VERSION:
            _fail("root_entries_invalid", kind="root_entry")
        policy_dir = os.path.join(root, name)
        _entry(policy_dir, "policy_dir", "dir")
        for sub in sorted(os.listdir(policy_dir)):
            if sub != WINDOW_END:
                _fail("root_entries_invalid", kind="bundle_entry")
            final = os.path.join(policy_dir, sub)
            _entry(final, "final", "dir")
            if sorted(os.listdir(final)) != sorted((DATA_FILE, RECEIPT_FILE)):
                _fail("root_entries_invalid", kind="bundle_files")
            for file_name, cap in ((DATA_FILE, DATA_CAP), (RECEIPT_FILE, RECEIPT_CAP)):
                info = _entry(os.path.join(final, file_name), "bundle_file", "file")
                if info.st_size > cap:
                    _fail("saved_size_cap", kind="bundle_file")
                files += 1
                total += info.st_size
            bundles += 1
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


def _publish(root, data_bytes, receipt_bytes, pins):
    if not _SAVE_LOCK.acquire(blocking=False):
        _fail("storage_busy")
    try:
        return _publish_locked(root, data_bytes, receipt_bytes, pins)
    except OSError as error:
        _fail("storage_io_failure", errno=error.errno if type(error.errno) is int else 0)
    finally:
        _SAVE_LOCK.release()


def _bundle(action, final, data_bytes, receipt_bytes, saved_at):
    return SavedBundle(action, POLICY_VERSION, WINDOW_END, final, hashlib.sha256(data_bytes).hexdigest(),
                       len(data_bytes), hashlib.sha256(receipt_bytes).hexdigest(), len(receipt_bytes), saved_at)


def _publish_locked(root, data_bytes, receipt_bytes, pins):
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
        if bundles:
            existing_data, existing_receipt_bytes, _, existing, final = _load_verified(root, pins)
            if existing_data != data_bytes or _without_saved_at(existing) != _without_saved_at(new_receipt):
                _fail("final_conflict")
            return _bundle("idempotent", final, existing_data, existing_receipt_bytes, existing["saved_at"])
        if bundles + 1 > MAX_BUNDLES:
            _fail("quota_bundles")
        if files + 2 > MAX_FILES:
            _fail("quota_files")
        if total + len(data_bytes) + len(receipt_bytes) > MAX_TOTAL_BYTES:
            _fail("quota_bytes")
    except BaseException as exception:
        failure = _carry(_base._failure_values(exception, "root_check", "storage_io_failure"), exception)
        if created_root:
            failure = _base._close_all((("root_rmdir", _remove_if_present(os.rmdir, root)),), failure)
        _base._raise_failure(failure)
    staging = os.path.join(root, ".staging-" + secrets.token_hex(8))
    parent = os.path.join(root, POLICY_VERSION)
    final = os.path.join(parent, WINDOW_END)
    created_parent = False
    stage = "staging_create"
    try:
        os.mkdir(staging)
        for name, data in ((DATA_FILE, data_bytes), (RECEIPT_FILE, receipt_bytes)):
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
            ("staging_remove_data", _remove_if_present(os.remove, os.path.join(staging, DATA_FILE))),
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
        read_data, read_receipt, _, document, _ = _load_verified(root, pins)
    except SourceError as error:
        _fail("saved_readback_failed", reader_code=error.code)
    if read_data != data_bytes or read_receipt != receipt_bytes:
        _fail("saved_readback_mismatch")
    return _bundle("created", final, read_data, read_receipt, document["saved_at"])


# --- read-only consumer interface (AC-3) -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DayRead:
    symbol: str
    on_date: str
    basis: str
    data_version: str
    factor: object
    events: tuple
    provenance: object


@dataclass(frozen=True, slots=True)
class SavedCalendarActions:
    """Fully re-verified, immutable view of one saved bundle. Every read names market, security type,
    symbol, data version and purpose; anything else, and anything the data cannot support, is refused."""
    policy_version: str
    calendar: tuple
    calendar_after_formal: tuple
    _symbols: object  # private on purpose: every symbol-scoped read goes through the _symbol() gate
    spread_semantics: object
    data_sha256: str
    data_version: str
    receipt: object
    receipt_sha256: str

    def _check(self, market, security_type, data_version, purpose):
        if type(market) is not str or market != READ_MARKET:
            _fail("unsupported_market")
        if type(security_type) is not str or security_type != READ_SECURITY_TYPE:
            _fail("unsupported_security_type")
        if type(data_version) is not str or data_version != self.data_version:
            _fail("data_version_mismatch")
        if type(purpose) is not str or purpose != PURPOSE:
            _fail("unsupported_purpose")

    def _symbol(self, symbol):
        """The one gate for every symbol-scoped read: a refused symbol yields nothing, not even its events."""
        if type(symbol) is not str or symbol not in self._symbols:
            _fail("unsupported_symbol")
        entry = self._symbols[symbol]
        if entry["status"] != "usable":
            _fail("symbol_refused", reason=entry["refusal_reasons"][0])
        return entry

    @property
    def provenance(self):
        return MappingProxyType({
            "namespace": NAMESPACE, "policy_version": self.policy_version,
            "policy_sha256": self.receipt["source_policy"]["sha256"], "consumer_version": CONSUMER_VERSION,
            "data_version": self.data_version, "market": MARKET, "instrument_type": INSTRUMENT_TYPE,
            "identity_as_of": IDENTITY_AS_OF, "publication_time": "unknown", "first_availability": "unknown",
            "revision_time": "unknown", "storage": "private_local", "limitations": self.receipt["limitations"],
            "unsupported": UNSUPPORTED,
        })

    def trading_days(self, *, market, security_type, data_version, purpose):
        """The calendar days the provider returned; a missing weekday is not asserted to be a closure."""
        self._check(market, security_type, data_version, purpose)
        return self.calendar

    def events(self, *, market, security_type, symbol, data_version, purpose):
        """The symbol's normalized events (supported or not, each with its reasons); refused symbols raise."""
        self._check(market, security_type, data_version, purpose)
        return self._symbol(symbol)["events"]

    def read_day(self, *, market, security_type, symbol, data_version, on_date, purpose, basis):
        self._check(market, security_type, data_version, purpose)
        entry = self._symbol(symbol)
        if type(basis) is not str or basis not in ("raw", "adjusted"):
            _fail("unsupported_basis")
        if not _is_iso(on_date):
            _fail("date_invalid")
        if not WINDOW_START <= on_date <= WINDOW_END:
            _fail("date_outside_window")
        if on_date not in self.calendar:
            _fail("date_not_in_observed_calendar")
        for day, reason in entry["incomparable_days"]:
            if day == on_date:
                _fail("day_incomparable", reason=reason)
        factor = None
        applied = ()
        if basis == "adjusted":
            adjusted = entry["adjusted"]
            if adjusted["supported_from"] is None or on_date < adjusted["supported_from"]:
                reasons = adjusted["reasons"]
                _fail("adjusted_unsupported", reason=reasons[0] if reasons else "event_unsupported")
            applied = tuple((event["date"], event["kind"], Fraction(event["factor"]))
                            for event in entry["events"] if event["date"] > on_date)
            factor = Fraction(1)
            for _, _, value in applied:
                factor *= value
        return DayRead(symbol, on_date, basis, self.data_version, factor, applied, self.provenance)


def load_saved(root=None, *, pins=None):
    """Read-only, fully re-verified view of the saved bundle; never fetches and never falls back."""
    pins = _real_pins() if pins is None else _pins(pins)
    data_bytes, receipt_bytes, data, receipt, _ = _load_verified(PRIVATE_ROOT if root is None else root, pins)
    digest = hashlib.sha256(data_bytes).hexdigest()
    return SavedCalendarActions(
        POLICY_VERSION, tuple(data["calendar"]), tuple(data["calendar_after_formal"]),
        MappingProxyType({symbol: _base._freeze(data["symbols"][symbol]) for symbol in SYMBOLS}),
        _base._freeze(data["spread_semantics"]), digest, DATA_VERSION_PREFIX + digest,
        _base._freeze(receipt), hashlib.sha256(receipt_bytes).hexdigest())
