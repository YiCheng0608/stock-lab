"""Issue 37's standalone, one-shot inferred cutoff industry-membership RAM source.

There is no import-time I/O. Callers supply the independently obtained canonical
policy; this module reads neither files nor environment variables and imports no
other application module (the section 2/3 mapper tables below are an embedded copy,
guarded by a test against ``taxonomy.py``, so the loaded-source hash binds all of it).

Membership for the cutoffs 2026-10-05/2026-10-06 is INFERRED from a snapshot taken
on a later Taipei date D (2026-10-06 <= D <= 2026-10-31) from exactly four GETs, in
order: FinMind TaiwanStockInfo, TWSE t187ap03_L, TPEx mopsfin_t187ap03_O, FinMind
TaiwanStockDelisting. It is NOT point-in-time: classification effective/expiry times
are unknown and off-cycle reclassification between a cutoff and D cannot be excluded.
``acquire`` returns PENDING, not usable sets: an independent same-RAM oracle must
state the expected status and members of all 2 cutoffs x 3 groups and they must equal
the inferred outcomes before ``lookup`` is available. Boundary transports do not
demonstrate source truth.

The default transport is direct stdlib HTTPS. It requires FinancialStart and a
matching ExecutionBinding from a separately reviewed explicit Issue 37 seal. These
declarations do not authenticate GitHub/runtime identity; the sole QA launcher/global
review must independently establish them: the seal carries the issuer/coordinator/
implementer session ids and the QA caller reads its own holder/model/effort back from
its runtime; none is pinned here. QA must differ from every seal role and the roles
must be pairwise distinct. The RAM quota survives release/new source objects in this
loaded module; it is not a durable or cross-process limiter. The external one-shot
seal remains authoritative.

Trace selectors (sys.settrace can observe the unmodified default path):
  _capture: capture_buffer while reading; full_body and receipt before return.
  _capture_ready: capture, full_body, receipt BEFORE any decoding/parsing.
  _parse_capture: full_body, receipt, decoded_text, document, parse_results,
                  diagnostics (including exceptional exits).
  acquire: exception, diagnostics, pending, results on the failure path.
``inspection`` exposes immutable original bytes/receipts and the inferred outcomes in
RAM for the independent oracle. ``release`` clears owned roots. QA must also clear
its external trace/oracle/result/exception aliases, disable the trace, unload the
module and exit. No disk persistence is implemented (artifact bytes: 0).

Limits are cooperative boundary checks with remaining-time I/O budgets, not OS hard
deadlines. The deduplicated supported-object estimate is not RSS or peak. Cleanup
preserves primary_code/primary_stage and separately reports at most two
secondary_cleanup_N_code/stage pairs plus an omitted count. Diagnostics never retain
exception messages/objects, responses, frames or tracebacks. Cleanup-only failure
rejects the batch; successful capture never implies that response/connection cleanup
succeeded.
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
from types import MappingProxyType
from typing import NamedTuple
from urllib.parse import urlsplit


# Pins of the externally published canonical policy v1 (sorted keys, compact JSON, UTF-8,
# no trailing LF). An unset or mismatching pin rejects every policy before use
# (policy_pin_unset, policy_pin, policy_canonical_mismatch).
POLICY_SHA256 = "8f6de996077b836a8a6d3129401d70bdf3a044b1cc126c709c5f5aa566fe2f06"
POLICY_BYTES = 10370
POLICY_VERSION = "issue37-industry-membership-inferred-cutoffs-1005-1006-v1"
POLICY_SCHEMA = "issue37-industry-membership-source-policy/v1"
NAMESPACE = POLICY_VERSION + "/qa1"
PURPOSE = "local_personal_noncommercial_process_ram_inferred_cutoff_membership_snapshot"
CONSUMER_VERSION = "industry-membership-inferred-cutoffs-lookup-v1"
FINANCIAL_START_VERSION = "issue37-financial-start-v1"
SEAL_URL_PATTERN = r"https://github\.com/YiCheng0608/stock-lab/issues/37#issuecomment-([0-9]+)"
SEAL_COMMENT_FLOOR = 6128163640  # AC revision 2 approval comment; any older location is refused
USER_AGENT = "stock-lab-issue37-local-ram/1"
ACCEPT = "application/json"
HOSTS = ("api.finmindtrade.com", "openapi.twse.com.tw", "www.tpex.org.tw")
URLS = (
    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo",
    "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDelisting",
)
SOURCE_IDS = ("finmind_taiwan_stock_info", "twse_t187ap03_l", "tpex_mopsfin_t187ap03_o", "finmind_taiwan_stock_delisting")
FINMIND_INDEXES = (0, 3)
MIB = 1048576
BODY_CAPS = (4 * MIB, 4 * MIB, 4 * MIB, 2 * MIB)
RAW_CAP = 12 * MIB
ROOTS_CAP = 48 * MIB
REQUEST_SECONDS = 20
BATCH_SECONDS = 180
MAX_ROWS = 200000
SESSION_ID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
MODEL_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"

CUTOFFS = ("2026-10-05", "2026-10-06")
ACQUISITION_EARLIEST = "2026-10-06"
ACQUISITION_LATEST = "2026-10-31"
TAIPEI = timezone(timedelta(hours=8))
MIDNIGHT_GUARD_SECONDS = BATCH_SECONDS + 30
NAMESPACE_OFFICIAL = "official_industry"
NAMESPACE_THEME = "theme"
REQUIRED_GROUPS = ("Semiconductor", "Optoelectronics", "Cultural Innovation")
# UI support pool only: each must sit in one of the required groups in the official snapshot.
SEVEN_SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
RESIDUAL_RISKS = (
    "non_pit", "classification_effective_dates_unknown", "finmind_service_provider_not_official",
    "inferred_from_post_cutoff_snapshot", "off_cycle_reclassification_not_excluded",
    "delisting_date_semantics_unknown",
)
BOM = b"\xef\xbb\xbf"
_ORDINARY_SYMBOL = re.compile(r"[0-9]{4}")
_OFFICIAL_CODE = re.compile(r"[0-9A-Z]{4,6}")
# Official listing-date grammars are mutually exclusive by character count and separator.
LISTING_FORMATS = ("gregorian8", "roc7", "roc6", "ymd_slash", "unknown")
_YMD_SLASH = re.compile(r"([0-9]{4})/([0-9]{1,2})/([0-9]{1,2})")
# Fixed vocabulary of the seven-stock rejection receipt; raw strings are never copied into it.
UNCOVERED_EXCHANGES = ("TWSE", "TPEx", "absent")
UNCOVERED_CODE_NULL = "<null>"
UNCOVERED_CODE_UNREPRESENTABLE = "<unrepresentable>"
UNCOVERED_GROUP_UNKNOWN = "unknown"
_UNCOVERED_CODE = re.compile(r"[0-9A-Za-z]{1,4}")
_EXCHANGE_OF_TYPE = MappingProxyType({"twse": "TWSE", "tpex": "TPEx"})

# INDUSTRY_CLASSIFICATION section 3 mapper: exchange + exact two-digit code, current ordinary codes only.
# Embedded copy of backend/app/taxonomy.py (a test pins the equality); 91/80/18(TPEx)/34/blank map to None.
_CODE_TO_GROUP = MappingProxyType({
    "TWSE": MappingProxyType({
        "01": "Cement", "02": "Food", "03": "Plastic", "04": "Textile", "05": "Electrical Machinery",
        "06": "Electrical Cable", "08": "Glass", "09": "Paper", "10": "Iron and Steel", "11": "Rubber",
        "12": "Automobile", "14": "Construction", "15": "Shipping", "16": "Tourism", "17": "Financial",
        "18": "Wholesale and Retail", "19": "Composite", "20": "Other", "21": "Chemical",
        "22": "Biotechnology", "23": "Oil, Gas and Electricity", "24": "Semiconductor",
        "25": "Computer and Peripherals", "26": "Optoelectronics", "27": "Communications",
        "28": "Electronic Parts", "29": "Electronic Distribution", "30": "Information Service",
        "31": "Other Electronics", "35": "Green Energy", "36": "Digital Cloud",
        "37": "Sports and Leisure", "38": "Household",
    }),
    "TPEx": MappingProxyType({
        "02": "Food", "03": "Plastic", "04": "Textile", "05": "Electrical Machinery",
        "06": "Electrical Cable", "08": "Glass", "10": "Iron and Steel", "11": "Rubber",
        "14": "Construction", "15": "Shipping", "16": "Tourism", "17": "Financial", "20": "Other",
        "21": "Chemical", "22": "Biotechnology", "23": "Oil, Gas and Electricity",
        "24": "Semiconductor", "25": "Computer and Peripherals", "26": "Optoelectronics",
        "27": "Communications", "28": "Electronic Parts", "29": "Electronic Distribution",
        "30": "Information Service", "31": "Other Electronics", "32": "Cultural Innovation",
        "33": "Agriculture Technology", "35": "Green Energy", "36": "Digital Cloud",
        "37": "Sports and Leisure", "38": "Household",
    }),
})
# INDUSTRY_CLASSIFICATION section 2 official market names (exact strings) -> code, per market.
_NAME_TO_CODE = MappingProxyType({
    "TWSE": MappingProxyType({
        "水泥工業": "01", "食品工業": "02", "塑膠工業": "03", "紡織纖維": "04", "電機機械": "05",
        "電器電纜": "06", "玻璃陶瓷": "08", "造紙工業": "09", "鋼鐵工業": "10", "橡膠工業": "11",
        "汽車工業": "12", "建材營造": "14", "航運業": "15", "觀光餐旅": "16", "金融保險": "17",
        "貿易百貨": "18", "綜合": "19", "其他": "20", "化學工業": "21", "生技醫療業": "22",
        "油電燃氣業": "23", "半導體業": "24", "電腦及週邊設備業": "25", "光電業": "26",
        "通信網路業": "27", "電子零組件業": "28", "電子通路業": "29", "資訊服務業": "30",
        "其他電子業": "31", "綠能環保": "35", "數位雲端": "36", "運動休閒": "37", "居家生活": "38",
    }),
    "TPEx": MappingProxyType({
        "食品工業": "02", "塑膠工業": "03", "紡織纖維": "04", "電機機械": "05", "電器電纜": "06",
        "玻璃陶瓷": "08", "鋼鐵工業": "10", "橡膠工業": "11", "建材營造": "14", "航運業": "15",
        "觀光餐旅": "16", "金融業": "17", "其他": "20", "化學工業": "21", "生技醫療": "22",
        "油電燃氣業": "23", "半導體業": "24", "電腦及週邊設備業": "25", "光電業": "26",
        "通信網路業": "27", "電子零組件業": "28", "電子通路業": "29", "資訊服務業": "30",
        "其他電子業": "31", "文化創意業": "32", "農業科技業": "33", "綠能環保": "35",
        "數位雲端": "36", "運動休閒": "37", "居家生活": "38",
    }),
})
_CANONICAL_GROUPS = frozenset(group for table in _CODE_TO_GROUP.values() for group in table.values())

_SOURCE_SHAPE = {key: str for key in ("dataset", "fields", "format", "id", "method", "provider", "role", "url")}


class _Rows:
    """Schema marker: a list of exactly ``count`` objects of ``schema``."""

    def __init__(self, schema, count):
        self.schema, self.count = schema, count


# A schema, not a bundled policy or a source of expected financial values.
_POLICY_SHAPE = {
    "acquisition": {
        "accept": str, "accept_encoding": str, "artifact_bytes": int, "batch_seconds": int,
        "body_cap_bytes": (int, 4), "deadline": str, "hosts": (str, 3), "max_gets": int,
        "namespace": str, "order": str, "per_source_max_gets": int, "redirects": int,
        "request_seconds": int, "retained_roots_estimate_cap_bytes": int, "retries": int,
        "stop_on_first_failure": bool, "total_raw_cap_bytes": int, "user_agent": str,
    },
    "acquisition_date": {"earliest": str, "latest": str, "rule": str},
    "consumer_version": str,
    "cutoffs": (str, 2),
    "first_availability": str,
    "groups": {"code_basis": str, "namespace": str, "required": (str, 3), "theme_namespace": str},
    "inference": {key: str for key in (
        "board_transfer", "d_set_agreement", "delisting", "identity", "new_listing", "outputs")},
    "instrument_type": str,
    "limitations": (str, 5),
    "market": str,
    "profile": str,
    "publication_time": str,
    "residual_risks": (str, 6),
    "response_shape": {key: str for key in (
        "content_encoding", "content_type", "content_type_official", "duplicate_identity_headers",
        "encoding", "encoding_official", "extra_fields", "framing", "set_cookie", "status")},
    "revision_time": str,
    "rights": {key: str for key in (
        "finmind", "finmind_attribution", "official", "tpex_attribution", "twse_attribution")},
    "schema": str,
    "source_use": str,
    "sources": _Rows(_SOURCE_SHAPE, 4),
    "storage": str,
    "supported_use": (str, 3),
    "unsupported": (str, 19),
    "version": str,
}


class SourceError(ValueError):
    """Diagnostics contain only plain nonfinancial scalar metadata."""

    def __init__(self, code, **diagnostics):
        self.code = code
        self.diagnostics = MappingProxyType({"code": code, **diagnostics})
        super().__init__(code)


def _fail(code, **diagnostics):
    raise SourceError(code, **diagnostics)


def _uncovered_entries(original):
    """Validated per-stock observations of a ``seven_stock_group_not_required`` rejection -> (entries, omitted).

    Each entry is (symbol_index, exchange, code, group). The exchange is a fixed enum, the code is a short ASCII
    alphanumeric string or a fixed marker (any other raw string is replaced by the marker, never copied), and the
    group is a canonical group name or ``unknown``. An entry with an invalid index or exchange is omitted.
    """
    count = original.get("uncovered_count")
    if type(count) is not int or not 1 <= count <= len(SEVEN_SYMBOLS):
        return (), 0
    entries = []
    for item in range(1, count + 1):
        prefix = f"uncovered_{item}_"
        index, exchange, code, group = (original.get(prefix + name) for name in ("symbol_index", "exchange", "code", "group"))
        if (type(index) is not int or not 0 <= index < len(SEVEN_SYMBOLS)
                or type(exchange) is not str or exchange not in UNCOVERED_EXCHANGES):
            continue
        if type(code) is not str or not (_UNCOVERED_CODE.fullmatch(code) or code == UNCOVERED_CODE_NULL):
            code = UNCOVERED_CODE_UNREPRESENTABLE
        if type(group) is not str or group not in _CANONICAL_GROUPS:
            group = UNCOVERED_GROUP_UNKNOWN
        entries.append((index, exchange, code, group))
    return tuple(entries), count - len(entries)


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
    entries, omitted = _uncovered_entries(original)
    if entries or omitted:
        values["uncovered_count"] = len(entries)
        for item, (index, exchange, code_value, group) in enumerate(entries, 1):
            values[f"uncovered_{item}_symbol_index"] = index
            values[f"uncovered_{item}_exchange"] = exchange
            values[f"uncovered_{item}_code"] = code_value
            values[f"uncovered_{item}_group"] = group
        if omitted:
            values["uncovered_omitted"] = omitted
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


def _json(text):
    invalid = False
    try:
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_float=float, parse_constant=_nonfinite)
    except SourceError:
        raise
    except (ValueError, RecursionError):
        invalid = True
    if invalid:
        _fail("json_invalid")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _shape(value, schema):
    if isinstance(schema, dict):
        if type(value) is not dict or value.keys() != schema.keys():
            _fail("policy_keys")
        for key in schema:
            _shape(value[key], schema[key])
    elif isinstance(schema, _Rows):
        if type(value) is not list or len(value) != schema.count:
            _fail("policy_list")
        for item in value:
            _shape(item, schema.schema)
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


def _bind_policy(policy):
    """Tripwire only: the pinned policy must agree with every product constant."""
    acquisition = policy["acquisition"]
    if (policy["version"] != POLICY_VERSION or policy["schema"] != POLICY_SCHEMA
            or acquisition["namespace"] != NAMESPACE or policy["source_use"] != PURPOSE
            or policy["consumer_version"] != CONSUMER_VERSION or policy["cutoffs"] != list(CUTOFFS)
            or policy["storage"] != "process_RAM" or policy["profile"] != "free_public_local"):
        _fail("policy_binding")
    sources = policy["sources"]
    if [source["url"] for source in sources] != list(URLS) or [source["id"] for source in sources] != list(SOURCE_IDS):
        _fail("policy_url_binding")
    if any(source["method"] != "GET" for source in sources):
        _fail("policy_url_binding")
    expected = {"accept": ACCEPT, "accept_encoding": "identity", "artifact_bytes": 0, "batch_seconds": BATCH_SECONDS,
                "body_cap_bytes": list(BODY_CAPS), "deadline": "cooperative", "hosts": list(HOSTS), "max_gets": 4,
                "per_source_max_gets": 1, "redirects": 0, "request_seconds": REQUEST_SECONDS,
                "retained_roots_estimate_cap_bytes": ROOTS_CAP, "retries": 0, "stop_on_first_failure": True,
                "total_raw_cap_bytes": RAW_CAP, "user_agent": USER_AGENT}
    if any(acquisition[key] != value or type(acquisition[key]) is not type(value) for key, value in expected.items()):
        _fail("policy_caps_binding")
    window = policy["acquisition_date"]
    if (window["earliest"], window["latest"]) != (ACQUISITION_EARLIEST, ACQUISITION_LATEST):
        _fail("policy_date_binding")
    groups = policy["groups"]
    if (groups["namespace"] != NAMESPACE_OFFICIAL or groups["required"] != list(REQUIRED_GROUPS)
            or policy["residual_risks"] != list(RESIDUAL_RISKS)):
        _fail("policy_group_binding")


def validate_policy(policy_canonical, policy_sha256):
    """Require the independently supplied exact canonical bytes and external pin."""
    if type(policy_canonical) is not bytes or type(policy_sha256) is not str:
        _fail("policy_input_type")
    if not POLICY_SHA256 or not POLICY_BYTES:
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
    _bind_policy(policy)
    return _freeze(policy)


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
    if (start.version != FINANCIAL_START_VERSION or not POLICY_SHA256
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
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in (binding.loaded_source_sha256, binding.script_sha256)):
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
        return tuple(range(len(self._attempted), len(URLS)))

    def begin(self):
        if self._begun or self._attempted:
            _fail("quota_spent")
        self._begun = True

    def charge(self, index):
        if not self._begun or type(index) is not int or index != len(self._attempted) or index >= len(URLS):
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
    """Direct HTTPS to the three fixed hosts and four fixed URLs only: no proxy/env/token/cookie handlers, redirects or retry."""

    def open(self, url, timeout):
        parsed = urlsplit(url)
        if (url not in URLS or parsed.scheme != "https" or parsed.hostname not in HOSTS
                or parsed.port is not None or parsed.username is not None):
            _fail("transport_url")
        target = parsed.path + ("?" + parsed.query if parsed.query else "")
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
            connection.request("GET", target,
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
    source_index: int
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
    bom_present: bool
    namespace: str
    policy_sha256: str

    @property
    def canonical_sha256(self):
        return hashlib.sha256(_canonical({f.name: getattr(self, f.name) for f in fields(self)})).hexdigest()


@dataclass(frozen=True, slots=True)
class Capture:
    body: bytes
    receipt: Receipt


class Member(NamedTuple):
    exchange: str
    symbol: str


@dataclass(frozen=True, slots=True)
class OfficialRow:
    exchange: str
    symbol: str
    industry: str
    group: object
    listing: object
    listing_format: str = "unknown"


@dataclass(frozen=True, slots=True)
class InfoRow:
    date: str
    stock_id: str
    type: str
    industry: str


@dataclass(frozen=True, slots=True)
class DelistRow:
    date: str
    stock_id: str


@dataclass(frozen=True, slots=True)
class GroupOutcome:
    cutoff: str
    group: str
    members: tuple
    flags: tuple
    rejected: bool
    reasons: tuple


@dataclass(frozen=True, slots=True)
class OracleAdmission:
    """Independent source-oracle assertion: expected status and members of every cutoff x group.

    ``expected`` holds exactly six ``(cutoff, group, status, members)`` tuples, status
    ``members`` or ``rejected``, members a tuple of ``(exchange, symbol)`` string pairs
    (empty for rejected). The oracle rebuilds them from the original bytes, never from
    this module's helpers.
    """
    namespace: str
    policy_sha256: str
    holder_thread_id: str
    candidate_sha: str
    script_sha256: str
    receipt_sha256s: tuple
    acquisition_date: str
    twse_report_date: str
    tpex_report_date: str
    info_rows: int
    twse_rows: int
    tpex_rows: int
    delisting_rows: int
    expected: tuple
    independent: bool


def retained_roots_estimate(*roots):
    """Deduplicated declared supported roots; not OS/RSS/peak measurement.

    Supports containers, our objects/dataclasses and exception traceback frame
    locals/cause/context. Modules/functions/classes/sockets/transports outside those
    declared containers are shallow leaves.
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
        elif is_dataclass(value) and not isinstance(value, type):
            pending.extend(getattr(value, item.name) for item in fields(value))
        elif type(value).__module__ == __name__ and hasattr(value, "__dict__"):
            pending.append(value.__dict__)
    return total


def _iso_date(value, code):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _fail(code)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        _fail(code)


def _roc7_date(value, code):
    """Official report date: exactly seven digits ROC yyyMMdd."""
    if type(value) is not str or not re.fullmatch(r"[0-9]{7}", value):
        _fail(code)
    try:
        return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:])).isoformat()
    except ValueError:
        _fail(code)


def _listing_date_format(value):
    """Official listing date -> (ISO date, format label); (None, "unknown") when missing or invalid.

    The grammars are mutually exclusive by character count and separator: 8 ASCII digits are Gregorian
    yyyyMMdd (``gregorian8``), 7 digits are ROC yyyMMdd (``roc7``), 6 digits are ROC yyMMdd (``roc6``), and
    ``Y/M/D`` with a 4-digit Gregorian year and ``/`` only is ``ymd_slash`` (month and day one or two digits).
    Each must be a real calendar date. Nothing is trimmed, padded or guessed; any other shape, including a
    3-digit ROC year with separators or ``-`` separators, is ``unknown`` and the caller rejects the group.
    """
    if type(value) is not str:
        return None, "unknown"
    try:
        if re.fullmatch(r"[0-9]{8}", value):
            return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat(), "gregorian8"
        if re.fullmatch(r"[0-9]{7}", value):
            return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:])).isoformat(), "roc7"
        if re.fullmatch(r"[0-9]{6}", value):
            return date(int(value[:2]) + 1911, int(value[2:4]), int(value[4:])).isoformat(), "roc6"
        match = _YMD_SLASH.fullmatch(value)
        if match:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat(), "ymd_slash"
    except ValueError:
        pass
    return None, "unknown"


def _listing_date(value):
    return _listing_date_format(value)[0]


def _group_of_code(exchange, code):
    """Section 3 mapper: exchange + exact two-digit code; everything else is unknown (None)."""
    if type(code) is not str or not re.fullmatch(r"[0-9]{2}", code) or exchange not in _CODE_TO_GROUP:
        return None
    return _CODE_TO_GROUP[exchange].get(code)


def _group_of_name(exchange, name):
    """FinMind Chinese industry name -> canonical group via the exact section 2 market name (None if not listed)."""
    code = _NAME_TO_CODE.get(exchange, {}).get(name) if type(name) is str else None
    return None if code is None else _CODE_TO_GROUP[exchange][code]


def _finmind_rows(document):
    if type(document) is not dict or set(document) != {"status", "msg", "data"}:
        _fail("finmind_document")
    if (type(document["status"]) is not int or document["status"] != 200
            or type(document["msg"]) is not str or document["msg"] != "success"):
        _fail("finmind_document_status")
    rows = document["data"]
    if type(rows) is not list or not rows or len(rows) > MAX_ROWS:
        _fail("finmind_rows")
    return rows


def _nullable_text(value):
    """Non-identity text columns: a string, or null/absent meaning unknown (fails closed per group); anything else is a schema error."""
    if value is None:
        return ""
    if type(value) is not str:
        _fail("row_schema_type")
    return value


def _parse_info(document, acquisition_date):
    """TaiwanStockInfo rows; extra columns are ignored. ``date`` and ``stock_id`` must be strings; the type and
    industry columns may be null (unknown), so an unexpected null cannot spend the whole batch."""
    result = []
    for row in _finmind_rows(document):
        if type(row) is not dict or any(type(row.get(key)) is not str for key in ("date", "stock_id")):
            _fail("info_row_schema")
        day = _iso_date(row["date"], "info_date")
        if day > acquisition_date:
            _fail("info_date_after_acquisition")
        if not row["stock_id"] or len(row["stock_id"]) > 32:
            _fail("info_stock_id")
        result.append(InfoRow(day, row["stock_id"], _nullable_text(row.get("type")), _nullable_text(row.get("industry_category"))))
    return tuple(result)


def _parse_delisting(document):
    result = []
    for row in _finmind_rows(document):
        if type(row) is not dict or any(type(row.get(key)) is not str for key in ("date", "stock_id")):
            _fail("delisting_row_schema")
        if not row["stock_id"] or len(row["stock_id"]) > 32:
            _fail("delisting_stock_id")
        result.append(DelistRow(_iso_date(row["date"], "delisting_date"), row["stock_id"]))
    return tuple(result)


_OFFICIAL_FIELDS = {
    "TWSE": ("出表日期", "公司代號", "產業別", "上市日期"),
    "TPEx": ("Date", "SecuritiesCompanyCode", "SecuritiesIndustryCode", "DateOfListing"),
}


def _parse_official(document, exchange, acquisition_date):
    """Official listed-company master -> (rows, report_date). Report date must be one value in [earliest, D].

    Code and report date must be strings. The industry and listing-date columns may be null/absent (unknown/missing,
    which rejects only the affected group); a listing-date value of any other type is invalid and counts as missing.
    """
    if type(document) is not list or not document or len(document) > MAX_ROWS:
        _fail("official_rows")
    report_key, code_key, industry_key, listing_key = _OFFICIAL_FIELDS[exchange]
    seen = set()
    report = None
    rows = []
    for row in document:
        if type(row) is not dict or any(type(row.get(key)) is not str for key in (report_key, code_key)):
            _fail("official_row_schema")
        code = row[code_key]
        if not _OFFICIAL_CODE.fullmatch(code):
            _fail("official_symbol")
        if code in seen:
            _fail("official_duplicate_symbol")
        seen.add(code)
        row_report = _roc7_date(row[report_key], "official_report_date")
        if report is None:
            report = row_report
        elif row_report != report:
            _fail("official_report_date_not_uniform")
        industry = _nullable_text(row.get(industry_key))
        listing, listing_format = _listing_date_format(row.get(listing_key))
        rows.append(OfficialRow(exchange, code, industry, _group_of_code(exchange, industry), listing, listing_format))
    if not ACQUISITION_EARLIEST <= report <= acquisition_date:
        _fail("official_report_date_out_of_range")
    return tuple(rows), report


def check_seven_symbols_covered(official):
    """The UI support pool must sit in the required groups; otherwise the required group set is wrong.

    All seven are scanned before the whole batch is rejected. The rejection carries, per uncovered stock,
    ``symbol_index``, the observed exchange (``TWSE``/``TPEx``/``absent``), the official raw industry code
    (``<null>`` when null, missing or empty, ``<unrepresentable>`` unless 1-4 ASCII letters or digits) and
    the mapper result (a canonical group or ``unknown``); see ``_uncovered_entries`` for the whitelist.
    """
    by_identity = {(row.exchange, row.symbol): row for row in official}
    uncovered = []
    for index, symbol in enumerate(SEVEN_SYMBOLS):
        row = by_identity.get(("TPEx", symbol)) or by_identity.get(("TWSE", symbol))
        if row is not None and row.group in REQUIRED_GROUPS:
            continue
        if row is None:
            uncovered.append((index, "absent", UNCOVERED_CODE_NULL, UNCOVERED_GROUP_UNKNOWN))
            continue
        if row.industry == "":
            code = UNCOVERED_CODE_NULL
        elif _UNCOVERED_CODE.fullmatch(row.industry):
            code = row.industry
        else:
            code = UNCOVERED_CODE_UNREPRESENTABLE
        group = row.group if row.group in _CANONICAL_GROUPS else UNCOVERED_GROUP_UNKNOWN
        uncovered.append((index, row.exchange, code, group))
    if uncovered:
        diagnostics = {"uncovered_count": len(uncovered)}
        for item, (index, exchange, code, group) in enumerate(uncovered, 1):
            diagnostics.update({f"uncovered_{item}_symbol_index": index, f"uncovered_{item}_exchange": exchange,
                                f"uncovered_{item}_code": code, f"uncovered_{item}_group": group})
        _fail("seven_stock_group_not_required", **diagnostics)


def infer_memberships(official, info, delisting, acquisition_date, cutoffs=CUTOFFS):
    """Pure inference over validated rows -> {(cutoff, group): GroupOutcome}; no I/O.

    Fail-closed: any difference or ambiguity rejects the group (or, where the AC says
    so, all three groups of that cutoff). See the policy ``inference`` section.

    Non-ordinary identities (a symbol or ``stock_id`` that is not exactly four ASCII digits) are excluded
    from both sources before any set, delisting or board-transfer decision: they are never members and
    never raise a rejection. The row grammars that reject the whole batch run earlier, in the parsers.
    """
    official = tuple(row for row in official if _ORDINARY_SYMBOL.fullmatch(row.symbol))
    info = tuple(row for row in info if _ORDINARY_SYMBOL.fullmatch(row.stock_id))
    by_id = {}
    for row in info:
        by_id.setdefault(row.stock_id, []).append(row)
    latest, ambiguous = {}, {}
    for stock_id, rows in by_id.items():
        top = max(row.date for row in rows)
        newest = [row for row in rows if row.date == top]
        if len({(row.type, row.industry) for row in newest}) == 1:
            latest[stock_id] = newest[0]
        else:
            ambiguous[stock_id] = tuple(newest)
    official_by_symbol = {}
    for row in official:
        official_by_symbol.setdefault(row.symbol, []).append(row)
    official_set = {group: set() for group in REQUIRED_GROUPS}
    for row in official:
        if row.group in official_set:
            official_set[row.group].add(Member(row.exchange, row.symbol))
    finmind_set = {group: set() for group in REQUIRED_GROUPS}
    for stock_id, row in latest.items():
        exchange = _EXCHANGE_OF_TYPE.get(row.type)
        if exchange is not None:
            group = _group_of_name(exchange, row.industry)
            if group in finmind_set:
                finmind_set[group].add(Member(exchange, stock_id))
    ambiguous_groups = set()
    for stock_id, rows in ambiguous.items():
        for row in rows:
            exchange = _EXCHANGE_OF_TYPE.get(row.type)
            group = _group_of_name(exchange, row.industry) if exchange else None
            if group in official_set:
                ambiguous_groups.add(group)
        for row in official_by_symbol.get(stock_id, ()):
            if row.group in official_set:
                ambiguous_groups.add(row.group)
    outcomes = {}
    for cutoff in cutoffs:
        reasons = {group: set() for group in REQUIRED_GROUPS}
        all_reasons = set()
        members = {group: {} for group in REQUIRED_GROUPS}
        explained = set()

        def add(group, member, flag):
            if member in members[group]:
                reasons[group].add("duplicate_identity")
            else:
                members[group][member] = flag
        seen_delisting = set()
        for row in delisting:
            if not cutoff <= row.date <= acquisition_date or (row.date, row.stock_id) in seen_delisting:
                continue
            seen_delisting.add((row.date, row.stock_id))
            if not _ORDINARY_SYMBOL.fullmatch(row.stock_id):
                continue  # non-ordinary identity (ETF, warrant, ...) never belongs to a required group
            official_rows = official_by_symbol.get(row.stock_id)
            if official_rows:
                for official_row in official_rows:
                    if official_row.group in reasons and row.date == cutoff:
                        reasons[official_row.group].add("delisting_date_equals_cutoff")
                continue
            candidates = [item for item in by_id.get(row.stock_id, ()) if item.type in _EXCHANGE_OF_TYPE]
            if not candidates:
                all_reasons.add("delisted_industry_undeterminable")
                continue
            top = max(item.date for item in candidates)
            newest = {(item.type, item.industry) for item in candidates if item.date == top}
            if len(newest) != 1:
                all_reasons.add("delisted_record_ambiguous")
                continue
            kind, industry = next(iter(newest))
            exchange = _EXCHANGE_OF_TYPE[kind]
            group = _group_of_name(exchange, industry)
            if group is None:
                all_reasons.add("delisted_industry_undeterminable")
                continue
            explained.add(row.stock_id)
            if group in reasons:
                if row.date == cutoff:
                    reasons[group].add("delisting_date_equals_cutoff")
                else:
                    add(group, Member(exchange, row.stock_id), "finmind_only_delisted_member")
        for group in REQUIRED_GROUPS:
            if official_set[group] != {m for m in finmind_set[group] if m.symbol not in explained}:
                reasons[group].add("cross_source_mismatch")
        for row in official:
            group = row.group
            if group not in members:
                continue
            if row.listing is None:
                reasons[group].add("listing_date_missing_or_invalid")
            elif row.listing <= cutoff:
                add(group, Member(row.exchange, row.symbol), None)
            else:
                other = "tpex" if row.exchange == "TWSE" else "twse"
                older = [item for item in by_id.get(row.symbol, ()) if item.type == other]
                if not older:
                    continue  # a new listing after the cutoff
                if row.exchange != "TWSE":
                    reasons[group].add("board_transfer_reverse_direction")
                    continue
                top = max(item.date for item in older)
                names = {item.industry for item in older if item.date == top}
                if len(names) != 1:
                    reasons[group].add("board_transfer_ambiguous")
                elif top < cutoff:
                    reasons[group].add("board_transfer_evidence_before_cutoff")
                else:
                    old_group = _group_of_name("TPEx", next(iter(names)))
                    if old_group is None:
                        all_reasons.add("board_transfer_old_industry_unknown")
                    elif old_group != group:
                        reasons[group].add("board_transfer_industry_conflict")
                        if old_group in reasons:
                            reasons[old_group].add("board_transfer_industry_conflict")
                    else:
                        add(group, Member("TPEx", row.symbol), "board_transfer_old_tpex_identity")
        for group in ambiguous_groups:
            reasons[group].add("finmind_multiple_valid_records")
        owners, symbol_owners = {}, {}
        for group in REQUIRED_GROUPS:
            for member in members[group]:
                owners.setdefault(member, set()).add(group)
                symbol_owners.setdefault(member.symbol, set()).add(member.exchange)
        for member, groups in owners.items():
            if len(groups) > 1:
                for group in groups:
                    reasons[group].add("identity_in_multiple_groups")
            if len(symbol_owners[member.symbol]) > 1:
                for group in groups:
                    reasons[group].add("symbol_on_two_exchanges")
        for group in REQUIRED_GROUPS:
            final = all_reasons | reasons[group]
            if final:
                outcomes[(cutoff, group)] = GroupOutcome(cutoff, group, (), (), True, tuple(sorted(final)))
            else:
                ordered = tuple(sorted(members[group]))
                outcomes[(cutoff, group)] = GroupOutcome(
                    cutoff, group, ordered,
                    tuple((member, members[group][member]) for member in ordered if members[group][member] is not None),
                    False, ())
    return outcomes


@dataclass(frozen=True, slots=True)
class MembershipSet:
    """Revocable handle: every read re-checks the snapshot, so release/expiry rejects held handles."""
    _snapshot: MembershipSource
    cutoff: str
    group: str

    @property
    def members(self):
        self._snapshot._usable()
        return self._snapshot._outcomes[(self.cutoff, self.group)].members

    @property
    def flags(self):
        self._snapshot._usable()
        return self._snapshot._outcomes[(self.cutoff, self.group)].flags

    @property
    def provenance(self):
        self._snapshot._usable()
        return self._snapshot.set_provenance(self.cutoff, self.group)


class MembershipSource:
    """Only snapshot object; pending/failed/expired/released are consumer-inert."""

    def __init__(self, *, policy_canonical, policy_sha256, purpose=PURPOSE, transport=None, ledger=None,
                 financial_start=None, execution_binding=None, clock=time.monotonic, utc_now=None,
                 lease_seconds=180, observer_roots=None):
        self._policy = validate_policy(policy_canonical, policy_sha256)
        self._policy_canonical = policy_canonical
        if type(purpose) is not str or purpose != PURPOSE:
            _fail("unsupported_purpose")
        if type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds) or not 0 < lease_seconds <= 180:
            _fail("lease_seconds")
        if not callable(clock) or (utc_now is not None and not callable(utc_now)) or (
                observer_roots is not None and not callable(observer_roots)):
            _fail("clock_or_roots_type")
        self._real = transport is None
        if self._real or isinstance(transport, _HTTPSTransport):
            _financial_start(financial_start, execution_binding)
            if transport is not None or ledger is not None:
                _fail("default_transport_required_for_financial")
            if clock is not time.monotonic or utc_now is not None:
                _fail("default_clock_required_for_financial")
        elif financial_start is not None or execution_binding is not None:
            _fail("financial_start_with_boundary_transport")
        if not self._real and (type(ledger) is not AttemptLedger or ledger.namespace != NAMESPACE):
            _fail("boundary_ledger_required")
        self._binding = execution_binding
        self._transport = _HTTPSTransport() if self._real else transport
        self._ledger = ledger
        self._clock = clock
        self._utc_now = utc_now if utc_now is not None else (lambda: datetime.now(timezone.utc))
        self._observer_roots = observer_roots
        self._lease_seconds = lease_seconds
        self._last_clock = None
        self._batch_deadline = self._request_deadline = None
        self._expiry = None
        self._state = "new"
        self._raw_bytes = 0
        self._captures = []
        self._info = self._twse = self._tpex = self._delisting = ()
        self._report_dates = {}
        self._acquisition_date = None
        self._outcomes = {}
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

    def _taipei_now(self):
        moment = self._utc_now()
        if type(moment) is not datetime or moment.tzinfo is None or moment.utcoffset() is None:
            _fail("invalid_utc_clock")
        return moment.astimezone(TAIPEI)

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

    def _capture(self, index):
        url = URLS[index]
        body_cap = BODY_CAPS[index]
        self._remaining()
        self._request_deadline = self._now() + REQUEST_SECONDS
        self._ledger.charge(index)
        response = None
        capture_buffer = self._capture_buffer
        capture_buffer.clear()
        request_started = self._taipei_now()
        full_body = receipt = None
        primary_failure = None
        stage = "capture_open"
        try:
            response = self._transport.open(url, self._remaining())
            stage = "capture_headers"
            self._remaining()
            if type(response.status) is not int or response.status != 200:
                _fail("http_auth_or_payment_stop" if response.status in (401, 402, 403) else "http_status",
                      source_index=index)
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
                if not re.fullmatch(r"0|[1-9][0-9]{0,15}", length_text):
                    _fail("content_length")
                declared_length = int(length_text)
                if declared_length > body_cap or declared_length > RAW_CAP - self._raw_bytes:
                    _fail("declared_body_cap")
            transfer = header_values.get("transfer-encoding", "").strip().lower()
            if transfer not in ("", "chunked") or (transfer and declared_length is not None):
                _fail("ambiguous_framing")
            content_type = header_values.get("content-type", "").strip()
            # FinMind keeps the #32 v3 gate; the official feeds only record the value (the strict body parse gates instead).
            if index in FINMIND_INDEXES and not re.fullmatch(r"application/json(?:\s*;\s*charset=utf-8)?", content_type, re.I):
                _fail("content_type")
            stage = "capture_body"
            while True:
                self._remaining()
                if response.known_eof is True:
                    break
                available = min(body_cap - len(capture_buffer), RAW_CAP - self._raw_bytes)
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
            observed = self._taipei_now()
            if observed.date() != request_started.date() or (
                    self._acquisition_date is not None and observed.date().isoformat() != self._acquisition_date):
                _fail("acquisition_date_changed")
            receipt = Receipt(SOURCE_IDS[index], index, POLICY_VERSION, "GET", url, 200,
                              request_started.astimezone(timezone.utc).isoformat(),
                              observed.astimezone(timezone.utc).isoformat(),
                              len(full_body), hashlib.sha256(full_body).hexdigest(), True,
                              content_type, encoding, full_body.startswith(BOM), NAMESPACE, POLICY_SHA256)
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
            body = full_body
            if full_body.startswith(BOM):
                if index in FINMIND_INDEXES:
                    _fail("finmind_bom")
                body = full_body[len(BOM):]
            try:
                decoded_text = body.decode("utf-8")
            except UnicodeDecodeError:
                pass
            if decoded_text is None:
                _fail("utf8_decode")
            self._check_roots(full_body, receipt, decoded_text, document, parse_results, diagnostics)
            self._remaining()
            document = _json(decoded_text)
            self._check_roots(full_body, receipt, decoded_text, document, diagnostics)
            self._remaining()
            if index == 0:
                parse_results = _parse_info(document, self._acquisition_date)
            elif index == 3:
                parse_results = _parse_delisting(document)
            else:
                exchange = "TWSE" if index == 1 else "TPEx"
                parse_results = _parse_official(document, exchange, self._acquisition_date)
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
        pending = self
        try:
            # Pre-spend gates: nothing below is charged to the ledger yet.
            taipei = self._taipei_now()
            today = taipei.date().isoformat()
            if not ACQUISITION_EARLIEST <= today <= ACQUISITION_LATEST:
                _fail("acquisition_date_out_of_range")
            seconds_of_day = taipei.hour * 3600 + taipei.minute * 60 + taipei.second
            if 86400 - seconds_of_day < MIDNIGHT_GUARD_SECONDS:
                _fail("acquisition_too_close_to_midnight")
        except BaseException as exception:
            primary_failure = _failure_values(exception, "acquire_gate")
            self._state = "failed"
            self._diagnostics = MappingProxyType({"stage": "acquire_gate", **primary_failure})
            _raise_failure(primary_failure)
        if self._real:
            if _REAL_LEDGER is None:
                _REAL_LEDGER = AttemptLedger(NAMESPACE)
            self._ledger = _REAL_LEDGER
        self._ledger.begin()
        self._state = "acquiring"
        self._acquisition_date = today
        self._batch_deadline = self._now() + BATCH_SECONDS
        try:
            self._info = self._parse_capture(self._capture(0), 0)
            self._twse, twse_report = self._parse_capture(self._capture(1), 1)
            self._tpex, tpex_report = self._parse_capture(self._capture(2), 2)
            self._report_dates = {"TWSE": twse_report, "TPEx": tpex_report}
            check_seven_symbols_covered(self._twse + self._tpex)  # before the last GET
            self._delisting = self._parse_capture(self._capture(3), 3)
            self._check_roots(pending)
            self._remaining()
            self._outcomes.update(infer_memberships(self._twse + self._tpex, self._info, self._delisting, today))
            self._check_roots(pending, self._outcomes)
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
            self._check_failure_roots(primary_failure, "batch_failure_roots", pending, diagnostics, exception)
            diagnostics.update(primary_failure)
            _raise_failure(primary_failure)
        finally:
            self._capture_buffer.clear()
            self._request_deadline = None

    def _listing_format_counts(self):
        """Per exchange, how many official rows used each listing-date format (``unknown`` includes null/missing)."""
        counts = {exchange: dict.fromkeys(LISTING_FORMATS, 0) for exchange in ("TWSE", "TPEx")}
        for row in self._twse + self._tpex:
            counts[row.exchange][row.listing_format] += 1
        return MappingProxyType({exchange: MappingProxyType(per_format) for exchange, per_format in counts.items()})

    def _excluded_counts(self):
        """Rows left out of every set as non-ordinary (identity not exactly four ASCII digits): counts only.

        Official rows are counted per exchange; ``TaiwanStockInfo`` rows per ``type`` (``twse``/``tpex``, any other
        type is ``other``). ``TaiwanStockDelisting`` has no exchange and its non-ordinary ids were always ignored,
        so it is not counted. No raw symbol or ``stock_id`` string is recorded.
        """
        official = {"TWSE": 0, "TPEx": 0}
        for row in self._twse + self._tpex:
            if not _ORDINARY_SYMBOL.fullmatch(row.symbol):
                official[row.exchange] += 1
        finmind = {"TWSE": 0, "TPEx": 0, "other": 0}
        for row in self._info:
            if not _ORDINARY_SYMBOL.fullmatch(row.stock_id):
                finmind[_EXCHANGE_OF_TYPE.get(row.type, "other")] += 1
        return MappingProxyType({"official": MappingProxyType(official), "finmind": MappingProxyType(finmind)})

    def inspection(self):
        if self.state not in ("pending", "available", "failed"):
            _fail("inspection_unavailable")
        return MappingProxyType({
            "captures": tuple(self._captures),
            "acquisition_date": self._acquisition_date,
            "report_dates": MappingProxyType(dict(self._report_dates)),
            "row_counts": (len(self._info), len(self._twse), len(self._tpex), len(self._delisting)),
            "listing_date_formats": self._listing_format_counts(),
            "excluded_non_ordinary": self._excluded_counts(),
            "outcomes": MappingProxyType(dict(self._outcomes)),
            "diagnostics": self._diagnostics,
            "retained_roots_estimate_bytes": self._roots_estimate})

    def admit_independent_verification(self, admission):
        if self.state != "pending" or type(admission) is not OracleAdmission:
            _fail("oracle_pending_required")
        for item in fields(admission):
            value = getattr(admission, item.name)
            expected_type = (tuple if item.name in ("receipt_sha256s", "expected") else bool if item.name == "independent"
                             else int if item.name.endswith("_rows") else str)
            if type(value) is not expected_type:
                _fail("oracle_type")
        if admission.independent is not True or (admission.namespace, admission.policy_sha256) != (NAMESPACE, POLICY_SHA256):
            _fail("oracle_scope")
        if any(type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value) for value in admission.receipt_sha256s):
            _fail("oracle_receipt_type")
        hashes = tuple(capture.receipt.canonical_sha256 for capture in self._captures)
        if len(hashes) != len(URLS) or admission.receipt_sha256s != hashes:
            _fail("oracle_capture_binding")
        if (admission.acquisition_date, admission.twse_report_date, admission.tpex_report_date) != (
                self._acquisition_date, self._report_dates["TWSE"], self._report_dates["TPEx"]):
            _fail("oracle_dates")
        if (admission.info_rows, admission.twse_rows, admission.tpex_rows, admission.delisting_rows) != (
                len(self._info), len(self._twse), len(self._tpex), len(self._delisting)):
            _fail("oracle_complete_scope")
        if self._real and (admission.holder_thread_id, admission.candidate_sha, admission.script_sha256) != (
                self._binding.holder_thread_id, self._binding.candidate_sha, self._binding.script_sha256):
            _fail("oracle_qa_binding")
        claimed = {}
        for entry in admission.expected:
            if type(entry) is not tuple or len(entry) != 4:
                _fail("oracle_expected_shape")
            cutoff, group, status, members = entry
            if (type(cutoff) is not str or type(group) is not str or status not in ("members", "rejected")
                    or type(members) is not tuple):
                _fail("oracle_expected_shape")
            if any(type(item) is not tuple or len(item) != 2 or any(type(part) is not str for part in item) for item in members):
                _fail("oracle_expected_shape")
            if (cutoff, group) in claimed or (status == "rejected" and members):
                _fail("oracle_expected_shape")
            claimed[(cutoff, group)] = (status, tuple(sorted(members)))
        if set(claimed) != set(self._outcomes):
            _fail("oracle_expected_scope")
        for key, (status, members) in claimed.items():
            outcome = self._outcomes[key]
            if status != ("rejected" if outcome.rejected else "members") or members != outcome.members:
                # No oracle shopping: a mismatching assertion ends the snapshot.
                self._state = "failed"
                self._outcomes.clear()
                self._diagnostics = MappingProxyType({"code": "oracle_set_mismatch", "stage": "oracle"})
                _fail("oracle_set_mismatch")
        self._check_roots(admission)
        self._state = "available"

    def _usable(self):
        if self.state != "available":
            _fail("consumer_unavailable")
        self._check_roots()

    @property
    def provenance(self):
        self._usable()
        return MappingProxyType({
            "namespace": NAMESPACE, "policy_sha256": POLICY_SHA256, "consumer_version": CONSUMER_VERSION,
            "market": "TW/TWSE+TPEx", "instrument_type": "ordinary_stock",
            "inferred_from_post_cutoff_snapshot": True, "effective_from": "unknown", "effective_to": "unknown",
            "pit": False, "residual_risk_codes": RESIDUAL_RISKS, "acquisition_date": self._acquisition_date,
            "official_report_dates": MappingProxyType(dict(self._report_dates)),
            "source_digests": MappingProxyType({
                capture.receipt.source_id: capture.receipt.body_sha256 for capture in self._captures}),
            "receipts": tuple(capture.receipt for capture in self._captures),
            "rights": self._policy["rights"], "limitations": self._policy["limitations"],
            "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
            "unsupported": self._policy["unsupported"], "storage": "process_RAM",
            "lease_expires_monotonic": self._expiry, "deadline": "cooperative",
            "retained_roots_estimate_bytes": self._roots_estimate,
            "retained_roots_estimate_is_rss_or_peak": False,
        })

    def set_provenance(self, cutoff, group):
        base = dict(self.provenance)
        base.update(cutoff=cutoff, group=group, namespace_scope=NAMESPACE_OFFICIAL)
        return MappingProxyType(base)

    def lookup(self, cutoff, group, *, namespace=NAMESPACE_OFFICIAL):
        self._usable()
        if type(namespace) is not str or namespace != NAMESPACE_OFFICIAL:
            _fail("theme_namespace_unverified" if namespace == NAMESPACE_THEME else "unsupported_namespace")
        if type(cutoff) is not str or cutoff not in CUTOFFS:
            _fail("unsupported_cutoff")
        if type(group) is not str or group not in REQUIRED_GROUPS:
            _fail("unsupported_group")
        outcome = self._outcomes[(cutoff, group)]
        if outcome.rejected:
            _fail("group_rejected", reasons=",".join(outcome.reasons))
        handle = MembershipSet(self, cutoff, group)
        self._check_roots(handle)
        return handle

    def release(self, *, expired=False):
        self._capture_buffer.clear()
        self._captures.clear()
        self._outcomes.clear()
        self._report_dates.clear()
        self._info = self._twse = self._tpex = self._delisting = ()
        self._transport = None
        self._observer_roots = None
        self._state = "expired" if expired else "released"
        # The one-shot ledger is deliberately retained and never reset.


def lookup_inferred_membership(snapshot, cutoff, group, namespace=NAMESPACE_OFFICIAL):
    if type(snapshot) is not MembershipSource:
        _fail("snapshot_required")
    return snapshot.lookup(cutoff, group, namespace=namespace)
