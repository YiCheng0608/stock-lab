"""Issue33 standalone, bounded, nominal TAIEX observation adapter (stdlib only).

AC revision 2: FinMind only. One GET of TaiwanStockPrice data_id=TAIEX; the
government TWSE index CSV path is gone. No network or filesystem action occurs
at import or construction. Real acquisition requires the externally published
canonical policy (pinned here by SHA-256 and byte length, like Issue 32), the exact
public formal blob d8918bc...:docs/SOURCE_REGISTRY.md supplied by the caller (bytes
and SHA-256 are checked before any request) and a separately reviewed external
financial-start seal. This module does not fetch any control-plane authorization.

Seal v1 has exact keys shown by SEAL_FIELDS. It binds candidate SHA, module/script/
loader/command hashes, actual independent top-level QA identity, owner, canonical
policy, use, URL, cutoffs, consumer, caps, command argv and UTC validity. These are
the predeclared format, not an authorization or an actual financial-start seal.

OracleHooks.finmind independently parses the ENTIRE original bytearray and returns
the entire normalized row list of every returned row (all columns, numbers as
Decimal), not a boolean or sampled rows. Hooks must put all retained copies/aliases
in hooks.owner, including declared native StringIO backing text. The observer runs
after EOF/hash and before parsing.

Unit limitation: with the second source removed the index scale (points, scale 1,
no x1000) has no independent anchor. Oracle/consumer comparisons are internal
consistency of one body only; they do not prove adjusted/index-divisor history or
the complete TWSE calendar. The 22 provider dates equal the formal-blob derivation,
which proves the provider observation set only.

Exported price results are revocable handles. Inspect them only with visit(callback,
RootOwner); that owner declares every retained alias/copy. Supported source roots
are traversable, estimated with bounded work and cleared on release. Immutable
copies are dereferenced, not physically wiped; this is not an RSS/peak guarantee.
Every public result-operation failure, including pending use, terminally releases
the source even if caught inside a with block. Pending-negative tests therefore
need a distinct boundary source; the real positive source must use fresh external
objects and default real clocks. The single wire interval has a cumulative 20s cap.
Arbitrary Python callbacks are trusted to declare their roots; this is a cooperative
in-process lifecycle contract, not a sandbox against malicious Python introspection.
The caller must clear its own exception graph and exit the RAM-only QA process.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import http.client
import io
import json
import re
import ssl
import sys
import time
from urllib.parse import urlsplit


# Pins of the externally published canonical policy (sorted keys, compact JSON, no
# trailing LF). The product never builds expected values from the policy under test.
POLICY_SHA256 = "04be101a61b6eba5ae6ba5773c24314718765c37ae7c67eacfd8813efb64d9dc"
POLICY_BYTES = 5038
POLICY_VERSION = "issue33-taiex-nominal-observed-window-finmind-v2"
FORMAL_BLOB = "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md"
FORMAL_BYTES = 268729
FORMAL_SHA256 = "b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde"
NAMESPACE = "issue33-taiex-nominal-observation-cutoffs-1005-1006-v1/qa2"
CONSUMER = "taiex-nominal-price-index-window-summary-v1"
SUPPORTED_USE = "local_personal_noncommercial_process_ram_nominal_observation_snapshot"
HOST = "api.finmindtrade.com"
URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=TAIEX&start_date=2026-09-03&end_date=2026-10-06"
URLS = (URL,)
CUTOFFS = ("2026-10-05", "2026-10-06")
WINDOW_START = "2026-09-03"
WINDOW_END = "2026-10-06"
USER_AGENT = "stock-lab-issue33-local-ram/1"
ACCEPT = "application/json"
REQUEST_HEADERS = {"Accept-Encoding": "identity", "Connection": "close", "User-Agent": USER_AGENT, "Accept": ACCEPT}
# The two fixed 21-observation windows of AC-3, literally. The 22 observed dates are
# their union (AC-2) and must also equal the formal-blob derivation.
WINDOWS = {
    "2026-10-05": ("2026-09-03", "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
                   "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
                   "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-29", "2026-09-30",
                   "2026-10-01", "2026-10-02", "2026-10-05"),
    "2026-10-06": ("2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
                   "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-21",
                   "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01",
                   "2026-10-02", "2026-10-05", "2026-10-06"),
}
OBSERVED_DATES = tuple(sorted(set(WINDOWS["2026-10-05"]) | set(WINDOWS["2026-10-06"])))
BODY_CAP = 1_048_576
RAW_CAP = 1_048_576
ROOTS_CAP = 33_554_432
REQUEST_SECONDS = 20
BATCH_SECONDS = 180
CAPS = {"max_gets": 1, "body_cap_bytes": BODY_CAP, "total_raw_cap_bytes": RAW_CAP,
        "retained_roots_estimate_cap_bytes": ROOTS_CAP, "request_seconds": REQUEST_SECONDS,
        "batch_seconds": BATCH_SECONDS, "redirects": 0, "retries": 0, "artifact_bytes": 0}
POLICY_PIN_PATTERN = r"https://github\.com/YiCheng0608/stock-lab/issues/[0-9]+#issuecomment-[0-9]+"
SEAL_PIN_PATTERN = r"https://github\.com/YiCheng0608/stock-lab/issues/33#issuecomment-([0-9]+)"
SEAL_COMMENT_FLOOR = 6123688628  # AC revision 2 comment; any older (qa1-era) seal location is refused
SEAL_FIELDS = {
    "schema", "issue", "namespace", "policy_sha256", "policy_pin", "candidate_sha",
    "module_sha256", "script_sha256", "loader_sha256", "command_sha256", "command",
    "qa_thread", "qa_session", "parent_thread", "owner_thread", "authorized_by",
    "financial_start", "issued_at_utc", "expires_at_utc", "consumer", "supported_use",
    "urls", "cutoffs", "caps",
}
BINDING_FIELDS = {"candidate_sha", "module_sha256", "script_sha256", "loader_sha256", "command_sha256", "command", "qa_thread", "qa_session", "owner_thread"}
REQUIRED_ROW_KEYS = frozenset({"date", "stock_id", "open", "max", "min", "close"})
UNADOPTED_ROW_KEYS = frozenset({"Trading_Volume", "Trading_money", "spread", "Trading_turnover"})
OHLC_KEYS = ("open", "max", "min", "close")
IDENTITY_HEADERS = frozenset({"content-length", "content-encoding", "transfer-encoding", "content-type"})
NUMERIC_LEXICAL_LIMIT = 64
NUMERIC_EXPONENT_LIMIT = 18
ROOT_NODE_LIMIT = 200_000
DIAGNOSTIC_LIMIT = 64
MAX_RETURNED_ROWS = 20_000

# A schema, not a bundled policy or a source of expected financial values.
_RESPONSE_SHAPE_KEYS = ("content_encoding", "content_type", "document", "duplicate_identity_headers",
                        "encoding", "framing", "set_cookie", "status", "zero_price_rows")
_POLICY_SHAPE = {
    "acquisition": {
        "accept": str, "accept_encoding": str, "artifact_bytes": int, "batch_seconds": int,
        "body_cap_bytes": int, "deadline": str, "max_gets": int, "namespace": str, "order": str,
        "redirects": int, "request_seconds": int, "retained_roots_estimate_cap_bytes": int,
        "retries": int, "stop_on_first_failure": bool, "total_raw_cap_bytes": int, "user_agent": str,
    },
    "arithmetic": {"interval_count": int, "observation_count": int, "ratio": str, "windows": str},
    "calendar_basis": str, "consumer_version": str, "cutoffs": (str, 2), "first_availability": str,
    "formal_calendar": {"blob": str, "bytes": int, "expected_scope": str, "section": str, "sha256": str},
    "identity_as_of": str, "instrument_type": str, "market": str, "price_basis": str,
    "price_source": {
        "basis": str, "data_id": str, "data_id_evidence": str, "dataset": str, "documentation": str,
        "end_date": str, "endpoint": str, "fields": {"close": str, "high": str, "low": str, "open": str},
        "known_unadopted_fields": (str, 4), "method": str, "ohlc_rule": str, "provider": str,
        "query_order": (str, 4), "required_row_keys": (str, 6), "rights": str, "start_date": str, "url": str,
    },
    "profile": str, "publication_time": str,
    "response_shape": {key: str for key in _RESPONSE_SHAPE_KEYS},
    "revision_time": str, "schema": str, "source_use": str, "storage": str, "symbol": str,
    "unit_policy": {"OHLC": str, "independent_anchor": str, "provider_literal_unit_annotation": bool,
                    "scale": int, "unit_mapping_inference": bool, "version": str},
    "unsupported": (str, 19),
    "version": str,
}


class TaiexSourceError(Exception):
    """Only static bounded codes are retained; provider text is never diagnostic."""

    def __init__(self, code: str, phase: str = "guard"):
        self.code = code[:64]
        self.phase = phase[:48]
        super().__init__(self.code)


def fail(code, phase="guard"):
    raise TaiexSourceError(code, phase)


def _cleanup_note(notes, code):
    if notes is not None and code not in notes and len(notes) < 16:
        notes.append(code)


def clear_error_graph(error, *, notes=None):
    """Detach supported exception/payload aliases and slots without reading frames.

    Custom dict/slot payloads and builtin UnicodeError.object/OSError.filename etc.
    are included. Unknown payload owners are detached and explicitly reported.
    Immutable copies are dereferenced; no physical-wipe guarantee is made.
    """
    todo, seen, containers, views, buffers, cleanup = [error], set(), [], [], [], []
    while todo:
        current = todo.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        kind = type(current)
        if isinstance(current, BaseException):
            todo.extend((current.__cause__, current.__context__, current.args, current.__dict__))
            current.__traceback__ = None
            current.__cause__ = None
            current.__context__ = None
            current.args = ()
            attributes = {"object", "reason", "encoding", "filename", "filename2", "text", "msg", "code"}
            for base in kind.__mro__:
                slots = base.__dict__.get("__slots__", ())
                attributes.update((slots,) if type(slots) is str else slots)
            for name in attributes - {"__dict__", "__weakref__"}:
                try:
                    value = getattr(current, name)
                except AttributeError:
                    continue
                except BaseException as attribute_error:
                    cleanup.append("exception_attribute_read")
                    attribute_error.__traceback__ = attribute_error.__cause__ = attribute_error.__context__ = None
                    attribute_error.args = ()
                    continue
                todo.append(value)
                try:
                    setattr(current, name, b"" if name == "object" and type(value) is bytes else None)
                except BaseException as attribute_error:
                    cleanup.append("exception_slot_release")
                    attribute_error.__traceback__ = attribute_error.__cause__ = attribute_error.__context__ = None
                    attribute_error.args = ()
        elif kind is dict:
            todo.extend(current.keys())
            todo.extend(current.values())
            containers.append(current)
        elif kind in (list, tuple, set, frozenset):
            todo.extend(current)
            if kind in (list, set):
                containers.append(current)
        elif kind is memoryview:
            try:
                todo.append(current.obj)
            except ValueError:
                _cleanup_note(notes, "memoryview_already_released")
            else:
                views.append(current)
        elif kind is bytearray:
            buffers.append(current)
        elif kind is io.StringIO:
            current.close()
        elif kind not in (str, bytes, int, float, bool, type(None), Decimal, Fraction, date, datetime):
            cleanup.append("opaque_exception_payload_detached")
    for view in views:
        try:
            view.release()
        except (BufferError, ValueError):
            cleanup.append("exception_view_release")
    for buffer in buffers:
        try:
            buffer[:] = b"\0" * len(buffer)
            buffer.clear()
        except BufferError:
            cleanup.append("exception_buffer_release")
    for container in reversed(containers):
        container.clear()
    todo.clear()
    seen.clear()
    return cleanup[:16]


def _decimal(value):
    if type(value) is bool or type(value) not in (str, int, Decimal):
        fail("numeric_type", "numeric")
    text = str(value)
    if len(text) > NUMERIC_LEXICAL_LIMIT:
        fail("numeric_lexical_limit", "numeric")
    try:
        result = Decimal(text)
    except InvalidOperation:
        fail("numeric_invalid", "numeric")
    parts = result.as_tuple()
    if (not result.is_finite() or not isinstance(parts.exponent, int)
            or abs(parts.exponent) > NUMERIC_EXPONENT_LIMIT
            or len(parts.digits) > NUMERIC_LEXICAL_LIMIT
            or abs(result.adjusted()) > NUMERIC_EXPONENT_LIMIT):
        fail("numeric_range", "numeric")
    return result


def _integer_literal(text):
    if len(text) > NUMERIC_LEXICAL_LIMIT:
        fail("integer_lexical_limit", "json")
    value = int(text)
    if abs(value) > 10 ** NUMERIC_EXPONENT_LIMIT:
        fail("integer_range", "json")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key", "json")
        result[key] = value
    return result


def strict_json(text):
    if type(text) is not str or len(text) > 1_048_576:
        fail("json_size", "json")
    # Bound nesting before the stdlib parser: strings/escapes do not affect depth.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 16:
                fail("json_depth", "json")
        elif char in "]}":
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_int=_integer_literal,
                          parse_float=_decimal,
                          parse_constant=lambda value: fail("json_nonfinite", "json"))
    except (ValueError, RecursionError):
        fail("json_invalid", "json")


def _string_list(value, *, length=None):
    if type(value) is not list or (length is not None and len(value) != length):
        fail("policy_list_type", "policy")
    if not all(type(item) is str and 0 < len(item) <= 1024 for item in value):
        fail("policy_list_member", "policy")


def _shape(value, schema):
    if isinstance(schema, dict):
        if type(value) is not dict or value.keys() != schema.keys():
            fail("policy_keys", "policy")
        for key in schema:
            _shape(value[key], schema[key])
    elif isinstance(schema, tuple):
        item_type, count = schema
        if type(value) is not list or len(value) != count:
            fail("policy_list", "policy")
        for item in value:
            if type(item) is not item_type:
                fail("policy_type", "policy")
    elif type(value) is not schema:
        fail("policy_type", "policy")


def _typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def _bind_policy(policy):
    """Tripwire only: the pinned policy must agree with every product constant."""
    acquisition, source = policy["acquisition"], policy["price_source"]
    if (policy["version"] != POLICY_VERSION or acquisition["namespace"] != NAMESPACE
            or policy["source_use"] != SUPPORTED_USE or policy["consumer_version"] != CONSUMER
            or policy["cutoffs"] != list(CUTOFFS) or policy["symbol"] != "TAIEX"):
        fail("policy_binding", "policy")
    if (source["url"] != URL or source["endpoint"] != URL.split("?", 1)[0] or source["dataset"] != "TaiwanStockPrice"
            or source["data_id"] != "TAIEX" or source["method"] != "GET" or source["provider"] != "FinMind"
            or source["start_date"] != WINDOW_START or source["end_date"] != WINDOW_END
            or source["query_order"] != ["dataset", "data_id", "start_date", "end_date"]
            or source["required_row_keys"] != sorted(REQUIRED_ROW_KEYS)
            or source["known_unadopted_fields"] != sorted(UNADOPTED_ROW_KEYS)):
        fail("policy_query_binding", "policy")
    if (acquisition["accept"] != ACCEPT or acquisition["accept_encoding"] != "identity"
            or acquisition["user_agent"] != USER_AGENT or acquisition["stop_on_first_failure"] is not True
            or any(acquisition[key] != value for key, value in CAPS.items())):
        fail("policy_caps_binding", "policy")
    calendar = policy["formal_calendar"]
    if (calendar["blob"], calendar["bytes"], calendar["sha256"], calendar["section"]) != (FORMAL_BLOB, FORMAL_BYTES, FORMAL_SHA256, "31.2"):
        fail("policy_formal_binding", "policy")
    unit = policy["unit_policy"]
    if (unit["scale"] != 1 or unit["provider_literal_unit_annotation"] is not False
            or policy["calendar_basis"] != "cross_market_candidate_inference"
            or policy["price_basis"] != "nominal_index_level"
            or policy["arithmetic"]["observation_count"] != 21 or policy["arithmetic"]["interval_count"] != 20):
        fail("policy_unit_binding", "policy")


def _utc(text):
    if type(text) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", text):
        fail("seal_utc_grammar", "seal")
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        fail("seal_utc_invalid", "seal")


class ExternalPolicy:
    def __init__(self, raw, document, pin):
        self.raw = raw
        self.document = document
        self.sha256 = POLICY_SHA256
        self.pin = pin

    @classmethod
    def from_external(cls, raw_utf8, external_sha256, external_pin):
        if (type(raw_utf8) is not bytes or len(raw_utf8) != POLICY_BYTES
                or type(external_sha256) is not str or external_sha256 != POLICY_SHA256
                or type(external_pin) is not str or not re.fullmatch(POLICY_PIN_PATTERN, external_pin)
                or hashlib.sha256(raw_utf8).hexdigest() != external_sha256):
            fail("external_policy_pin", "policy")
        try:
            document = strict_json(raw_utf8.decode("utf-8"))
        except UnicodeDecodeError:
            fail("external_policy_utf8", "policy")
        _shape(document, _POLICY_SHAPE)
        canonical = json.dumps(document, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        if canonical != raw_utf8:
            fail("policy_canonical_mismatch", "policy")
        _string_list(document["unsupported"], length=19)
        _bind_policy(document)
        # The hash authenticates ALL literal values; the full external document is retained.
        return cls(raw_utf8, document, external_pin)


class FinancialStartSeal:
    def __init__(self, raw, document, pin, sha256):
        self.raw, self.document, self.pin, self.sha256 = raw, document, pin, sha256

    @classmethod
    def from_external(cls, raw_utf8, external_sha256, external_pin, policy, binding):
        if type(policy) is not ExternalPolicy:
            fail("seal_policy_type", "seal")
        canonical = ExternalPolicy.from_external(policy.raw, policy.sha256, policy.pin)
        if not _typed_equal(canonical.document, policy.document):
            fail("seal_policy_mutated", "seal")
        if (type(raw_utf8) is not bytes or not 0 < len(raw_utf8) <= 32768
                or type(external_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", external_sha256)
                or hashlib.sha256(raw_utf8).hexdigest() != external_sha256
                or type(external_pin) is not str):
            fail("external_seal_pin", "seal")
        match = re.fullmatch(SEAL_PIN_PATTERN, external_pin)
        if match is None:
            fail("external_seal_pin", "seal")
        if int(match[1]) <= SEAL_COMMENT_FLOOR:
            fail("financial_new_explicit_seal_required", "seal")
        try:
            document = strict_json(raw_utf8.decode("utf-8"))
        except UnicodeDecodeError:
            fail("external_seal_utf8", "seal")
        if type(document) is not dict or document.keys() != SEAL_FIELDS:
            fail("seal_full_keys", "seal")
        if type(binding) is not dict or binding.keys() != BINDING_FIELDS:
            fail("binding_full_keys", "seal")
        for key in BINDING_FIELDS:
            if not _typed_equal(document[key], binding[key]):
                fail("seal_execution_binding", "seal")
        for key in ("module_sha256", "script_sha256", "loader_sha256", "command_sha256"):
            if type(document[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", document[key]):
                fail("seal_hash_type", "seal")
        if type(document["candidate_sha"]) is not str or not re.fullmatch(r"[0-9a-f]{40}", document["candidate_sha"]):
            fail("seal_candidate_type", "seal")
        _string_list(document["command"])
        if hashlib.sha256(json.dumps(document["command"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest() != document["command_sha256"]:
            fail("seal_command_hash", "seal")
        for key in ("qa_thread", "qa_session", "owner_thread", "authorized_by"):
            if type(document[key]) is not str or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", document[key]):
                fail("seal_identity_type", "seal")
        if (document["parent_thread"] is not None or document["qa_thread"] != document["qa_session"]
                or document["qa_thread"] == document["owner_thread"]
                or document["qa_thread"] == document["authorized_by"]):
            fail("seal_independent_top_qa", "seal")
        expected = {"schema": "issue33-financial-start-seal/v1", "issue": "YiCheng0608/stock-lab#33",
                    "namespace": NAMESPACE, "policy_sha256": policy.sha256, "policy_pin": policy.pin,
                    "financial_start": True, "consumer": CONSUMER, "supported_use": SUPPORTED_USE,
                    "urls": list(URLS), "cutoffs": list(CUTOFFS), "caps": dict(CAPS)}
        for key, value in expected.items():
            if not _typed_equal(document[key], value):
                fail("seal_policy_binding", "seal")
        if _utc(document["issued_at_utc"]) >= _utc(document["expires_at_utc"]):
            fail("seal_validity_order", "seal")
        return cls(raw_utf8, document, external_pin, external_sha256)


def _section(text, heading):
    match = re.search(r"^" + re.escape(heading) + r"[^\n]*\n", text, re.M)
    if match is None:
        fail("formal_section", "formal")
    level = len(heading) - len(heading.lstrip("#"))
    tail = text[match.end():]
    stop = re.search(r"^#{1," + str(level) + r"} ", tail, re.M)
    return tail[:stop.start()] if stop else tail


def formal_observed_dates(formal_blob):
    """The 22 observed dates and both windows derived from the exact formal blob.

    Section 31.2 lists Sep20 and Oct4 (24 sessions). The dates on or after
    2026-09-03 are the 22 dates; each window is the last 21 at or before its
    cutoff. The result must equal the literal AC-3 sets; nothing is inferred from
    missing provider rows and no window is shrunk.
    """
    if type(formal_blob) is not bytes or len(formal_blob) != FORMAL_BYTES or hashlib.sha256(formal_blob).hexdigest() != FORMAL_SHA256:
        fail("formal_blob_pin", "formal")
    try:
        text = formal_blob.decode("utf-8")
    except UnicodeDecodeError:
        fail("formal_blob_utf8", "formal")
    calendar = _section(text, "### 31.2")

    def public_days(label, month):
        match = re.search(r"^- " + label + r"：[^/]+/([^。]+)。", calendar, re.M)
        if match is None:
            fail("formal_calendar_evidence", "formal")
        days = []
        for part in match.group(1).split("、"):
            if not re.fullmatch(r"[0-9]{1,2}", part):
                fail("formal_calendar_evidence", "formal")
            try:
                days.append(date(2026, month, int(part)).isoformat())
            except ValueError:
                fail("formal_calendar_evidence", "formal")
        return tuple(days)

    september, october = public_days("Sep20", 9), public_days("Oct4", 10)
    sessions = september + october
    if (len(september), len(october)) != (20, 4):
        fail("formal_calendar_count", "formal")
    if len(set(sessions)) != 24 or tuple(sorted(sessions)) != sessions or any(date.fromisoformat(day).weekday() >= 5 for day in sessions):
        fail("formal_calendar_order", "formal")
    observed = tuple(day for day in sessions if day >= WINDOW_START)
    windows = {cutoff: tuple([day for day in observed if day <= cutoff][-21:]) for cutoff in CUTOFFS}
    if observed != OBSERVED_DATES or len(observed) != 22 or windows != WINDOWS:
        fail("formal_calendar_mismatch", "formal")
    return observed, windows


class NativeText:
    """Explicit StringIO owner + original immutable backing + native estimate."""

    def __init__(self, stream, backing_text):
        if type(stream) is not io.StringIO or type(backing_text) is not str:
            fail("native_text_owner", "roots")
        self.stream, self.backing = stream, backing_text
        self.native_bytes = 4 * len(backing_text) + 256


class NativeTransport:
    """Declared stdlib response/socket backing estimate; closed before root release.

    The allowance covers the HTTP buffered reader and TLS record buffers. It is a
    declared native backing estimate, not a measurement of all native allocations.
    Injected boundary transports must declare their own source buffers separately.
    """

    def __init__(self, response=None):
        self.response = response
        self.native_bytes = 262_144


class NativeParseReservation:
    """Conservative declared estimate for transient stdlib parser allocations.

    Raw text remains separately tracked. Input is <=1MiB/depth16; row/schema and
    lexical bounds then constrain retained documents. This 8MiB allowance covers
    transient decoder cells prior to registration, and is not an RSS claim.
    """

    def __init__(self):
        self.native_bytes = 8_388_608


class NativeReadReservation:
    """Separate declared maximum one-read bytes allocation; not TLS/parser storage."""

    def __init__(self):
        self.native_bytes = 65_536


class NativeAuditReservation:
    """Bounded temporary non-price audit copies/serialization allowance."""

    def __init__(self):
        self.native_bytes = 65_536


class RootOwner:
    def __init__(self, name):
        if type(name) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", name):
            fail("root_owner_name", "roots")
        self.name, self.roots = name, {}

    def track(self, name, value):
        if type(name) is not str or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", name):
            fail("root_name", "roots")
        self.roots[name] = value
        return value

    def stringio(self, name, backing_text):
        stream = io.StringIO(backing_text, newline="")
        self.track(name, NativeText(stream, backing_text))
        return stream

    def declared_roots(self):
        return self.roots


def estimate_roots(owners, *, notes=None):
    """Bounded supported union estimate, including memoryview.obj/native backing."""
    stack = [owner.roots for owner in owners]
    seen, total, nodes = set(), 0, 0
    native_stream_owners, native_stream_aliases = set(), set()
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        nodes += 1
        if nodes > ROOT_NODE_LIMIT:
            fail("root_work_limit", "roots")
        total += sys.getsizeof(value)
        kind = type(value)
        if kind is dict:
            if len(value) > ROOT_NODE_LIMIT:
                fail("root_container_limit", "roots")
            stack.extend(value.keys())
            stack.extend(value.values())
        elif kind in (list, tuple, set, frozenset):
            if len(value) > ROOT_NODE_LIMIT:
                fail("root_container_limit", "roots")
            stack.extend(value)
        elif kind is memoryview:
            try:
                stack.append(value.obj)
            except ValueError:
                _cleanup_note(notes, "memoryview_already_released")
        elif kind is NativeText:
            stack.append(value.backing)
            native_stream_owners.add(id(value.stream))
            if id(value.stream) not in seen:
                total += sys.getsizeof(value.stream)
                seen.add(id(value.stream))
            total += value.native_bytes
        elif kind is io.StringIO:
            # A normal alias can precede its NativeText owner in graph traversal.
            # Resolve it against the complete declared union, never an opaque shell.
            native_stream_aliases.add(id(value))
        elif kind is NativeTransport:
            total += sys.getsizeof(value.response) + value.native_bytes
            if value.response is not None:
                stack.append(value.response.headers)
        elif kind in (NativeParseReservation, NativeReadReservation, NativeAuditReservation):
            total += value.native_bytes
        elif kind is Fraction:
            stack.extend((value.numerator, value.denominator))
        elif kind is Decimal:
            total += len(value.as_tuple().digits) * 8 + 64
        elif kind not in (str, bytes, bytearray, int, float, bool, type(None), date, datetime):
            fail("opaque_source_root", "roots")
        if total > ROOTS_CAP:
            fail("root_bytes_limit", "roots")
    if not native_stream_aliases <= native_stream_owners:
        fail("opaque_source_root", "roots")
    return total, nodes


def _release_roots(owners, *, notes=None):
    stack = [owner.roots for owner in owners]
    seen, containers, buffers, views, natives, native_streams, errors = set(), [], [], [], [], [], []
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        kind = type(value)
        if kind is dict:
            stack.extend(value.keys())
            stack.extend(value.values())
            containers.append(value)
        elif kind in (list, tuple, set, frozenset):
            stack.extend(value)
            if kind in (list, set):
                containers.append(value)
        elif kind is memoryview:
            try:
                stack.append(value.obj)
            except ValueError:
                _cleanup_note(notes, "memoryview_already_released")
            else:
                views.append(value)
        elif kind is bytearray:
            buffers.append(value)
        elif kind is NativeText:
            natives.append(value)
        elif kind is io.StringIO:
            native_streams.append(value)
        elif kind is NativeTransport:
            value.response = None
            value.native_bytes = 0
        elif kind in (NativeParseReservation, NativeReadReservation, NativeAuditReservation):
            value.native_bytes = 0
        elif isinstance(value, BaseException):
            errors.extend(clear_error_graph(value, notes=notes))
    for view in views:
        try:
            view.release()
        except BaseException as error:
            errors.append("memoryview_release")
            clear_error_graph(error)
    for native in natives:
        try:
            native.stream.close()
        except BaseException as error:
            errors.append("stringio_close")
            clear_error_graph(error)
        native.backing, native.native_bytes = "", 0
    for stream in native_streams:
        try:
            stream.close()
        except BaseException as error:
            errors.append("stringio_alias_close")
            errors.extend(clear_error_graph(error, notes=notes))
    for buffer in buffers:
        try:
            buffer[:] = b"\0" * len(buffer)
            buffer.clear()
        except BaseException as error:
            errors.append("buffer_release")
            clear_error_graph(error)
    for container in reversed(containers):
        container.clear()
    return errors[:16]


class OracleHooks:
    def __init__(self, observer, finmind, owner):
        if not all(callable(item) for item in (observer, finmind)) or type(owner) is not RootOwner:
            fail("oracle_hooks", "constructor")
        self.observer, self.finmind, self.owner = observer, finmind, owner


class AttemptLedger:
    def __init__(self):
        self.attempted_urls = []

    @property
    def spent(self):
        return bool(self.attempted_urls)


_REAL_LEDGER = AttemptLedger()


class _HTTPSResponse:
    def __init__(self, connection, response):
        self.connection, self.response = connection, response
        self.status = response.status
        self.headers = list(response.getheaders())
        # http.client hands the socket to a will_close response; keep the first non-None.
        self.socket = connection.sock
        if self.socket is None and response.fp is not None:
            self.socket = getattr(getattr(response.fp, "raw", None), "_sock", None)

    def read(self, count, timeout):
        if type(count) is not int or count <= 0:
            fail("zero_read_forbidden", "transport")
        if self.socket is None:
            fail("transport_timeout_socket", "transport")
        self.socket.settimeout(timeout)
        return self.response.read(count)

    @property
    def framing_eof(self):
        return self.response.isclosed() and self.response.length in (None, 0)

    def close(self):
        failures = []
        for closer in (self.response.close, self.connection.close):
            try:
                closer()
            except BaseException as error:
                failures.append(error)
        self.socket = None
        if failures:
            for later in failures[1:]:
                clear_error_graph(later)
            raise failures[0]


class HTTPSOneShot:
    """Real stdlib HTTPS, identity, system CA, no redirect/retry/cookie/proxy/auth.

    Socket waits get the remaining cumulative open budget. Checks are cooperative;
    DNS/SSL/library calls are not OS-hard preempted.
    """

    def open(self, url, timeout):
        parts = urlsplit(url)
        if (url != URL or parts.scheme != "https" or parts.hostname != HOST or parts.port is not None
                or parts.username is not None or parts.password is not None):
            fail("transport_url", "transport")
        connection = http.client.HTTPSConnection(parts.hostname, timeout=timeout, context=ssl.create_default_context())
        response = None
        deadline = time.monotonic() + timeout

        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                fail("cooperative_deadline", "transport")
            return budget

        try:
            connection.timeout = remaining()
            connection.connect()
            connection.sock.settimeout(remaining())
            connection.request("GET", parts.path + "?" + parts.query, headers=dict(REQUEST_HEADERS))
            connection.sock.settimeout(remaining())
            response = connection.getresponse()
            remaining()
            return _HTTPSResponse(connection, response)
        except BaseException:
            for closer in (() if response is None else (response.close,)) + (connection.close,):
                try:
                    closer()
                except BaseException as cleanup_error:
                    cleanup_error.__context__ = None  # keep the primary failure out of the cleanup graph
                    clear_error_graph(cleanup_error)
            raise


class RevocableHandle:
    def __init__(self, batch, key):
        self._batch, self._key = batch, key

    def visit(self, callback, owner):
        return self._batch._result_operation("result_visit", "RevocableHandle.visit",
                                             lambda: self._visit(callback, owner))

    def _visit(self, callback, owner):
        batch = self._batch
        batch._guard("handle_visit", available=True)
        if type(owner) is not RootOwner or owner not in batch.owners:
            fail("unregistered_result_owner", "consumer")
        if not callable(callback):
            fail("result_callback", "consumer")
        # Callback aliases/copies must be tracked by owner; no immutable result is exported.
        batch._callback("result_visit", callback, batch.product.roots[self._key])
        batch._measure("result_visit")
        batch._guard("handle_visit_done", available=True)

    def declared_roots(self):
        return self._batch._result_operation("handle_roots", "RevocableHandle.declared_roots", self._declared_roots)

    def _declared_roots(self):
        self._batch._guard("handle_roots", available=True)
        return {self._key: self._batch.product.roots[self._key]}


class TaiexNominalSource:
    """Use as a context manager; acquisition is atomic after the full oracle."""

    def __init__(self, policy, seal, hooks, *, binding, formal_blob, supported_use=SUPPORTED_USE,
                 consumer=CONSUMER, transport=None, boundary_only=False, ledger=None,
                 monotonic=time.monotonic, utc_now=None):
        if type(policy) is not ExternalPolicy or type(seal) is not FinancialStartSeal or type(hooks) is not OracleHooks:
            fail("typed_source_inputs", "constructor")
        if type(formal_blob) is not bytes:
            fail("formal_blob_type", "constructor")
        if type(boundary_only) is not bool:
            fail("boundary_flag_type", "constructor")
        if (transport is not None or ledger is not None) and not boundary_only:
            fail("injected_transport_requires_boundary", "constructor")
        if boundary_only and transport is None:
            fail("boundary_transport_required", "constructor")
        self.policy, self.seal, self.hooks = policy, seal, hooks
        self.binding, self.supported_use, self.consumer = binding, supported_use, consumer
        self.formal_blob = formal_blob
        self.transport = transport if transport is not None else HTTPSOneShot()
        self.boundary_only = boundary_only
        self.ledger = ledger if ledger is not None else _REAL_LEDGER
        self.monotonic = monotonic
        self.utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self.product = RootOwner("product")
        self.owners = [self.product, hooks.owner]
        self.product.track("policy_raw", policy.raw)
        self.product.track("policy_document", policy.document)
        self.product.track("seal_raw", seal.raw)
        self.product.track("seal_document", seal.document)
        self.product.track("binding", binding)
        self.product.track("formal_blob", formal_blob)
        self.state, self.batch_start = "pending", None
        self.raw_total, self.responses = 0, []
        self.request_seconds_used, self.active_request_started = 0.0, None
        self.receipts, self.diagnostics = [], []
        self.first_failure, self.secondary, self.cleanup_failures = None, [], []
        self.cleanup_notes = []
        self.product.track("capture_receipts", self.receipts)
        self.product.track("diagnostics", self.diagnostics)
        self.product.track("secondary", self.secondary)
        self.product.track("cleanup_failures", self.cleanup_failures)
        self.product.track("cleanup_notes", self.cleanup_notes)
        self.windows = None
        self._final_audit = None
        self.high_water, self.measure_seconds, self.measure_calls = 0, 0.0, 0
        self._acquired = False

    def register_owner(self, owner):
        if self.state != "pending" or self.batch_start is not None or type(owner) is not RootOwner:
            fail("late_root_owner", "roots")
        if owner not in self.owners:
            if any(item.name == owner.name for item in self.owners) or len(self.owners) >= 8:
                fail("root_owner_duplicate_or_limit", "roots")
            self.owners.append(owner)

    def _event(self, code, phase, location):
        if len(self.diagnostics) < DIAGNOSTIC_LIMIT:
            self.diagnostics.append({"code": code[:64], "phase": phase[:48], "location": location,
                                     "elapsed_seconds": 0.0 if self.batch_start is None else max(0.0, self.monotonic() - self.batch_start)})

    def _failure(self, code, phase, location):
        current_request = 0.0 if self.active_request_started is None else max(0.0, self.monotonic() - self.active_request_started)
        entry = {"code": code[:64], "phase": phase[:48], "location": location,
                 "elapsed_seconds": 0.0 if self.batch_start is None else max(0.0, self.monotonic() - self.batch_start),
                 "cumulative_request_elapsed_seconds": self.request_seconds_used + current_request,
                 "request_deadline_seconds": REQUEST_SECONDS, "batch_deadline_seconds": BATCH_SECONDS}
        if self.first_failure is None:
            self.first_failure = entry
            self.product.track("first_failure", entry)
        elif len(self.secondary) < 16:
            self.secondary.append(entry)

    def _guard(self, phase, *, available=False):
        if self.state in ("released", "failed", "expired"):
            fail("lease_" + self.state, phase)
        if available and self.state != "available":
            fail("lease_pending", phase)
        if self.batch_start is not None:
            elapsed = self.monotonic() - self.batch_start
            now = self.utc_now()
            if type(now) is not datetime or now.tzinfo is None:
                fail("clock_utc_type", phase)
            if elapsed < 0 or elapsed >= BATCH_SECONDS or now >= _utc(self.seal.document["expires_at_utc"]):
                self.state = "expired"
                fail("lease_expired", phase)
            if now < _utc(self.seal.document["issued_at_utc"]):
                fail("seal_not_yet_valid", phase)

    def _measure(self, phase):
        started = time.perf_counter()
        size, nodes = estimate_roots(self.owners, notes=self.cleanup_notes)
        elapsed = max(0.0, time.perf_counter() - started)
        self.measure_seconds += elapsed
        self.measure_calls += 1
        self.high_water = max(self.high_water, size)
        self._event("root_measure", phase, "TaiexNominalSource._measure")
        self._guard(phase)
        return size, nodes

    def _callback(self, phase, callback, *args):
        self._guard(phase)
        try:
            return callback(*args)
        except BaseException as error:
            code = error.code if type(error) is TaiexSourceError else "callback_failure"
            self._failure(code, phase, "TaiexNominalSource._callback")
            self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
            raise TaiexSourceError(code, phase) from None

    def _result_operation(self, phase, location, operation):
        """Any public result-operation failure terminally revokes the whole batch.

        Catching a callback/measurement error inside the consumer's with block must
        never let that caller resume getters, summaries or previously issued handles.
        """
        try:
            return operation()
        except BaseException as error:
            code = error.code if type(error) is TaiexSourceError else "result_operation_failure"
            origin_phase = error.phase if type(error) is TaiexSourceError else phase
            if self._final_audit is None:
                self._failure(code, origin_phase, location)
                self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
                self.release(failed=True)
            else:
                # Refusal after terminal release preserves the original audit and
                # cannot recreate a declared source root or replace the first cause.
                clear_error_graph(error)
            raise TaiexSourceError(code, origin_phase) from None

    def _preflight(self):
        if self.supported_use != SUPPORTED_USE or self.consumer != CONSUMER:
            fail("unsupported_use_preget", "preflight")
        # Revalidate external bytes and execution bindings, preventing mutable-policy drift.
        policy = ExternalPolicy.from_external(self.policy.raw, self.policy.sha256, self.policy.pin)
        if not _typed_equal(policy.document, self.policy.document):
            fail("policy_mutated", "preflight")
        seal = FinancialStartSeal.from_external(self.seal.raw, self.seal.sha256, self.seal.pin, policy, self.binding)
        if not _typed_equal(seal.document, self.seal.document):
            fail("seal_mutated", "preflight")
        # Exact formal blob and the derived 22 dates/windows are checked before any GET.
        observed, windows = formal_observed_dates(self.formal_blob)
        self.product.track("observed_dates", observed)
        self.windows = self.product.track("windows", windows)
        if self.ledger.spent or self._acquired:
            fail("namespace_spent", "preflight")
        self._guard("preflight")
        self._measure("preflight")

    def _request_remaining(self, started):
        self._guard("request")
        remaining = REQUEST_SECONDS - self.request_seconds_used - (self.monotonic() - started)
        if remaining <= 0:
            self._failure("request_deadline", "request", "TaiexNominalSource._request_remaining")
            fail("request_deadline", "request")
        return min(remaining, BATCH_SECONDS - (self.monotonic() - self.batch_start))

    def _capture(self):
        started = self.monotonic()
        self.active_request_started = started
        try:
            raw, receipt = self._capture_wire(started)
        finally:
            # Count the attempted wire interval, including failures. Parsing, the
            # independent oracle and result use remain under the separate batch
            # lease; they cannot reset or extend the cumulative 20s request budget.
            self.request_seconds_used += max(0.0, self.monotonic() - started)
            self.active_request_started = None
            self._event("request_interval_end", "capture", "TaiexNominalSource._capture")
        if self.request_seconds_used >= REQUEST_SECONDS:
            self._failure("request_deadline", "request", "TaiexNominalSource._capture")
            fail("request_deadline", "request")
        self._measure("captured")
        hook_receipt = self.hooks.owner.track("observer_receipt", dict(receipt))
        self._callback("original_observer", self.hooks.observer, raw, hook_receipt)
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            fail("original_observer_mutated_raw", "observer")
        self._measure("observed")
        return raw, receipt

    def _capture_wire(self, started):
        self._guard("capture")
        if self.ledger.attempted_urls:
            fail("attempt_order", "capture")
        # Attempt is SPENT before opening any transport; first failure never retries.
        self.ledger.attempted_urls.append(URL)
        pending_transport = self.product.track("transport", NativeTransport())
        self._measure("transport_pending")
        request_started_utc = self.utc_now().astimezone(timezone.utc).isoformat()
        response = self.transport.open(URL, self._request_remaining(started))
        self.responses.append(response)
        if type(response) is _HTTPSResponse:
            pending_transport.response = response
        self._request_remaining(started)
        status = response.status
        if type(status) is not int or status != 200:
            # 401/402/403 (or any paid/login layout) is the documented first failure.
            fail("http_auth_or_payment_stop" if status in (401, 402, 403) else "http_status_stop", "capture")
        if type(response.headers) is not list or len(response.headers) > 128:
            fail("http_headers", "capture")
        header_values = {}
        for pair in response.headers:
            if type(pair) is not tuple or len(pair) != 2 or not all(type(item) is str for item in pair):
                fail("http_header_type", "capture")
            key, value = pair[0].lower(), pair[1]
            if key in header_values and key in IDENTITY_HEADERS:
                fail("duplicate_identity_header", "capture")
            header_values[key] = value
        encoding = header_values.get("content-encoding", "identity").strip().lower()
        if encoding != "identity":
            fail("content_encoding", "capture")
        declared_length = None
        if "content-length" in header_values:
            if not re.fullmatch(r"0|[1-9][0-9]{0,15}", header_values["content-length"]):
                fail("content_length", "capture")
            declared_length = int(header_values["content-length"])
            if declared_length > BODY_CAP or declared_length > RAW_CAP - self.raw_total:
                fail("declared_body_cap", "capture")
        transfer = header_values.get("transfer-encoding", "").strip().lower()
        if transfer not in ("", "chunked") or (transfer and declared_length is not None):
            fail("ambiguous_framing", "capture")
        content_type = header_values.get("content-type", "").strip()
        if not re.fullmatch(r"application/json(?:\s*;\s*charset=utf-8)?", content_type, re.I):
            fail("content_type", "capture")
        raw = self.product.track("raw", bytearray())
        digest = hashlib.sha256()
        self.product.track("read_allowance", NativeReadReservation())
        self._measure("read_ready")
        while True:
            self._request_remaining(started)
            if response.framing_eof is True:
                break
            available = min(BODY_CAP - len(raw), RAW_CAP - self.raw_total)
            if available <= 0:
                fail("body_cap_without_known_eof", "capture")
            wanted = min(65_536, available)
            if declared_length is not None:
                wanted = min(wanted, declared_length - len(raw))
                if wanted <= 0:
                    # Everything declared is read. stdlib has closed the response by
                    # now unless nothing was ever declared (length 0: empty_body below).
                    if declared_length and response.framing_eof is not True:
                        fail("missing_known_eof", "capture")
                    break
            block = response.read(wanted, self._request_remaining(started))
            self.product.track("active_read_block", block)
            self._request_remaining(started)
            if type(block) is not bytes or len(block) > wanted:
                fail("invalid_transport_read", "capture")
            if not block:
                if declared_length is not None and len(raw) != declared_length:
                    fail("incomplete_content_length", "capture")
                if response.framing_eof is not True:
                    fail("missing_known_eof", "capture")
                self.product.roots.pop("active_read_block", None)
                break
            raw.extend(block)
            self.raw_total += len(block)
            digest.update(block)
            self.product.roots.pop("active_read_block", None)
            block = None
        if declared_length is not None and declared_length != len(raw):
            fail("incomplete_content_length", "capture")
        if not raw:
            fail("empty_body", "capture")
        now = self.utc_now().astimezone(timezone.utc)
        receipt = {"ordinal": 0, "source_id": "finmind_taiex_price_index", "source_version": POLICY_VERSION,
                   "method": "GET", "url": URL, "status": 200, "request_started_utc": request_started_utc,
                   "observed_utc": now.isoformat(), "body_bytes": len(raw), "sha256": digest.hexdigest(),
                   "eof": True, "content_type": content_type, "content_encoding": encoding,
                   "namespace": NAMESPACE, "policy_sha256": POLICY_SHA256,
                   "request_elapsed_seconds": self.monotonic() - started,
                   "cumulative_request_elapsed_seconds": self.request_seconds_used + self.monotonic() - started,
                   "boundary_only": self.boundary_only}
        self.receipts.append(receipt)
        return raw, receipt

    def _finmind(self, raw):
        self.product.track("finmind_parser_reservation", NativeParseReservation())
        self._measure("finmind_parse_reservation")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            fail("finmind_utf8", "finmind_parse")
        self.product.track("finmind_text", text)
        document = self.product.track("finmind_document", strict_json(text))
        if type(document) is not dict or document.keys() != {"status", "msg", "data"}:
            fail("finmind_document_schema", "finmind_parse")
        if type(document["status"]) is not int or document["status"] != 200 or type(document["msg"]) is not str or document["msg"] != "success":
            fail("finmind_status_msg", "finmind_parse")
        rows = document["data"]
        if type(rows) is not list or not rows or len(rows) > MAX_RETURNED_ROWS:
            fail("finmind_rows", "finmind_parse")
        # EVERY returned row is structurally validated and normalized first; only
        # then are rows outside the requested range discarded.
        normalized = self.product.track("finmind_rows", [])
        previous = None
        for row in rows:
            if type(row) is not dict or not REQUIRED_ROW_KEYS <= row.keys() or not row.keys() <= REQUIRED_ROW_KEYS | UNADOPTED_ROW_KEYS:
                fail("finmind_row_keys", "finmind_parse")
            token = row["date"]
            if type(token) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", token):
                fail("finmind_date_grammar", "finmind_parse")
            try:
                day = date.fromisoformat(token).isoformat()
            except ValueError:
                fail("finmind_invalid_date", "finmind_parse")
            if previous is not None and day <= previous:
                fail("finmind_date_order", "finmind_parse")
            previous = day
            if type(row["stock_id"]) is not str or row["stock_id"] != "TAIEX":
                fail("finmind_stock_id", "finmind_parse")
            result = {"date": day, "stock_id": "TAIEX"}
            for key in row.keys() - {"date", "stock_id"}:
                value = row[key]
                if key in UNADOPTED_ROW_KEYS:
                    # Not adopted and never computed or exported: number, string or null
                    # are kept as parsed (no range or sign check) so they cannot spend the
                    # single GET; bool, list and object stay refused. Document-level
                    # nonfinite/duplicate-key/numeric-lexical gates still apply.
                    if type(value) in (int, Decimal):
                        value = _decimal(value)
                    elif type(value) is not str and value is not None:
                        fail("finmind_unadopted_type", "finmind_parse")
                elif type(value) not in (int, Decimal):
                    fail("finmind_numeric_type", "finmind_parse")
                else:
                    value = _decimal(value)
                result[key] = value
            normalized.append(result)
        in_range = [item for item in normalized if WINDOW_START <= item["date"] <= WINDOW_END]
        if len(in_range) != len(OBSERVED_DATES):
            fail("finmind_in_range_count", "finmind_parse")
        if tuple(item["date"] for item in in_range) != self.product.roots["observed_dates"]:
            fail("finmind_calendar_mismatch", "finmind_parse")
        for item in in_range:
            if any(item[key] <= 0 for key in OHLC_KEYS):
                fail("finmind_positive_ohlc", "finmind_parse")
            if not item["min"] <= min(item["open"], item["close"]) <= max(item["open"], item["close"]) <= item["max"]:
                fail("finmind_ohlc_range", "finmind_parse")
        self.product.track("closes", {item["date"]: item["close"] for item in in_range})
        return normalized

    def acquire(self):
        self._guard("acquire")
        if self.batch_start is not None:
            fail("acquire_once", "preflight")
        self.batch_start = self.monotonic()
        self._event("batch_begin", "preflight", "TaiexNominalSource.acquire")
        try:
            self._preflight()
            raw, receipt = self._capture()
            self._event("parse_begin", "finmind_parse", "TaiexNominalSource._finmind")
            rows = self._finmind(raw)
            oracle_receipt = self.hooks.owner.track("finmind_oracle_receipt", dict(receipt))
            oracle = self._callback("finmind_full_oracle", self.hooks.finmind, raw, oracle_receipt)
            self.hooks.owner.track("finmind_oracle_return", oracle)
            if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
                fail("finmind_oracle_mutated_raw", "finmind_oracle")
            self._measure("finmind_oracle")
            if not _typed_equal(oracle, rows):
                fail("finmind_full_oracle_mismatch", "finmind_oracle")
            self._guard("atomic_available")
            self._measure("atomic_available")
            self.state, self._acquired = "available", True
            self._event("available", "available", "TaiexNominalSource.acquire")
            return self
        except BaseException as error:
            code = error.code if type(error) is TaiexSourceError else "source_failure"
            phase = error.phase if type(error) is TaiexSourceError else "acquire"
            self._failure(code, phase, "TaiexNominalSource.acquire")
            self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
            self.release(failed=True)
            raise TaiexSourceError(code, phase) from None

    def _provenance(self):
        policy = self.policy.document
        return {"symbol": "TAIEX", "policy_pin": self.policy.pin, "policy_sha256": self.policy.sha256,
                "policy_version": POLICY_VERSION, "seal_pin": self.seal.pin, "seal_sha256": self.seal.sha256,
                "namespace": NAMESPACE,
                "sources": ["FinMind TaiwanStockPrice data_id=TAIEX (personal noncommercial; attribution; no mirror/raw redistribution)"],
                "rights": policy["price_source"]["rights"], "data_id_evidence": policy["price_source"]["data_id_evidence"],
                "formal_calendar": {"blob": FORMAL_BLOB, "bytes": FORMAL_BYTES, "sha256": FORMAL_SHA256, "section": "31.2"},
                "external_calendar_basis": policy["calendar_basis"], "external_price_basis": policy["price_basis"],
                "output_alias_mapping": {"calendar_basis": "cross_market_candidate_inference", "price_basis": "nominal_index_level"},
                "unit": "index_points", "provider_literal_unit_annotation": False, "scale": 1,
                "independent_unit_anchor": False, "unit_limitation": policy["unit_policy"]["independent_anchor"],
                "supported_use": SUPPORTED_USE, "unsupported": list(policy["unsupported"]),
                "publication_time": "unknown", "first_availability": "unknown", "revision_time": "unknown",
                "verified_twse_calendar": False, "adjusted_basis": False, "total_return": False,
                "capture_receipts": [dict(item) for item in self.receipts], "boundary_only": self.boundary_only,
                "execution_binding": dict(self.binding)}

    def _cutoff(self, cutoff):
        if type(cutoff) is not str or cutoff not in CUTOFFS:
            fail("unsupported_cutoff", "consumer")

    def get_taiex_nominal21(self, cutoff, *, supported_use=SUPPORTED_USE):
        return self._result_operation("getter", "TaiexNominalSource.get_taiex_nominal21",
                                      lambda: self._get_taiex_nominal21(cutoff, supported_use=supported_use))

    def _get_taiex_nominal21(self, cutoff, *, supported_use):
        self._guard("getter", available=True)
        if supported_use != SUPPORTED_USE:
            fail("unsupported_getter_use", "consumer")
        self._cutoff(cutoff)
        dates = self.windows[cutoff]
        payload = {"cutoff": cutoff, "observations": [{"date": day, "close": self.product.roots["closes"][day]} for day in dates],
                   "first_date": dates[0], "last_date": dates[-1], "observation_count": 21, "interval_count": 20,
                   "calendar_basis": "cross_market_candidate_inference", "price_basis": "nominal_index_level",
                   "benchmark20d_ready": False, "provenance": self._provenance()}
        key = "getter_" + cutoff
        self.product.track(key, payload)
        self._measure("getter")
        return RevocableHandle(self, key)

    def summarize(self, cutoff, *, consumer=CONSUMER, supported_use=SUPPORTED_USE):
        return self._result_operation("summary", "TaiexNominalSource.summarize",
                                      lambda: self._summarize(cutoff, consumer=consumer, supported_use=supported_use))

    def _summarize(self, cutoff, *, consumer, supported_use):
        self._guard("summary", available=True)
        if consumer != CONSUMER or supported_use != SUPPORTED_USE:
            fail("unsupported_consumer_use", "consumer")
        self._cutoff(cutoff)
        dates = self.windows[cutoff]
        first = self.product.roots["closes"][dates[0]]
        last = self.product.roots["closes"][dates[-1]]
        # Numeric lexical/exponent bounds were checked before Fraction construction.
        ratio = (Fraction(last) - Fraction(first)) / Fraction(first)
        payload = {"consumer": CONSUMER, "cutoff": cutoff, "first_date": dates[0], "last_date": dates[-1],
                   "observation_count": 21, "interval_count": 20, "return": ratio,
                   "return_numerator": ratio.numerator, "return_denominator": ratio.denominator,
                   "formula": "(C_end-C_start)/C_start", "calendar_basis": "cross_market_candidate_inference",
                   "price_basis": "nominal_index_level", "benchmark20d_ready": False, "provenance": self._provenance()}
        key = "summary_" + cutoff
        self.product.track(key, payload)
        self._measure("summary")
        return RevocableHandle(self, key)

    def declared_roots(self):
        return {owner.name: owner.declared_roots() for owner in self.owners}

    def _audit_snapshot(self):
        # Bounded, non-price primitives owned by product. No serializer is needed
        # for the retained fallback; its temporary allocation has its own allowance.
        return {"capture_receipts": [dict(item) for item in self.receipts],
                "first_product_failure": None if self.first_failure is None else dict(self.first_failure),
                "secondary": [dict(item) for item in self.secondary],
                "events": [dict(item) for item in self.diagnostics]}

    def release(self, *, failed=False):
        # Trace/profile are turned off FIRST. No frame/f_locals/response is recorded.
        sys.settrace(None)
        sys.setprofile(None)
        if self.state in ("released", "failed") and self._final_audit is not None:
            return
        cleanup, notes, audit = list(self.cleanup_failures), list(self.cleanup_notes), None
        self.product.track("release_audit_allowance", NativeAuditReservation())
        try:
            try:
                audit_text = json.dumps(self._audit_snapshot(), separators=(",", ":"))
                if type(audit_text) is not str or len(audit_text) > 65_536:
                    fail("audit_serialization_contract", "release_audit")
                self.product.track("release_diagnostic_serialization", audit_text)
            except BaseException as error:
                cleanup.append("audit_serialization_failure")
                if len(self.secondary) < 16:
                    self.secondary.append({"code": "audit_serialization_failure", "phase": "release_audit",
                                           "location": "TaiexNominalSource.release", "elapsed_seconds": 0.0 if self.batch_start is None else max(0.0, self.monotonic() - self.batch_start)})
                cleanup.extend(clear_error_graph(error, notes=notes))
            try:
                started = time.perf_counter()
                size, nodes = estimate_roots(self.owners, notes=notes)
                self.measure_seconds += max(0.0, time.perf_counter() - started)
                self.measure_calls += 1
                self.high_water = max(self.high_water, size)
            except BaseException as error:
                self._failure(error.code if type(error) is TaiexSourceError else "release_measure_failure",
                              "release_measure", "TaiexNominalSource.release")
                cleanup.extend(clear_error_graph(error, notes=notes))
            # Independent of json.dumps/json.loads, including serializer failure.
            audit = self._audit_snapshot()
        finally:
            # No audit failure may skip ANY response close or declared-root attempt.
            if audit is None:
                audit = {"capture_receipts": [], "first_product_failure": None if self.first_failure is None else dict(self.first_failure),
                         "secondary": [{"code": "audit_snapshot_failure", "phase": "release_audit", "location": "TaiexNominalSource.release"}], "events": []}
            for response in self.responses:
                try:
                    response.close()
                except BaseException as error:
                    if len(cleanup) < 16:
                        cleanup.append("transport_close")
                    cleanup.extend(clear_error_graph(error, notes=notes))
            self.responses.clear()
            try:
                cleanup.extend(_release_roots(self.owners, notes=notes))
            except BaseException as error:
                cleanup.append("root_release_failure")
                cleanup.extend(clear_error_graph(error, notes=notes))
                # Last-resort detachment still visits every declared owner.
                for owner in self.owners:
                    owner.roots.clear()
            self.cleanup_failures, self.cleanup_notes = cleanup[:16], notes[:16]
            self.policy.raw, self.seal.raw = b"", b""
            self.formal_blob = b""
            self.windows = None
            self.binding = {}
            self.hooks.observer = self.hooks.finmind = None
            self.transport = None
            self.state = "failed" if failed else "released"
            self._final_audit = audit

    def diagnostic_report(self):
        audit = self._final_audit or {"capture_receipts": self.receipts, "first_product_failure": self.first_failure,
                                     "secondary": self.secondary, "events": self.diagnostics}
        return {"state": self.state, "namespace": NAMESPACE, "namespace_spent": self.ledger.spent,
                "attempted_urls": list(self.ledger.attempted_urls), "complete_eof_raw_bytes": self.raw_total,
                "cumulative_request_elapsed_seconds": self.request_seconds_used,
                "capture_receipts": [dict(item) for item in audit["capture_receipts"]], "first_product_failure": audit["first_product_failure"],
                "secondary": list(audit["secondary"]), "cleanup_failures": list(self.cleanup_failures),
                "cleanup_notes": list(self.cleanup_notes),
                "events": list(audit["events"]), "declared_roots_estimate_high_water": self.high_water,
                "measurement_seconds": self.measure_seconds, "measurement_calls": self.measure_calls,
                "declared_roots_empty": all(not owner.roots for owner in self.owners),
                "artifact_bytes": 0, "boundary_only": self.boundary_only}

    def __enter__(self):
        return self.acquire()

    def __exit__(self, kind, error, traceback):
        if error is not None:
            if self._final_audit is None:
                self._failure(error.code if type(error) is TaiexSourceError else "consumer_failure", "consumer", "TaiexNominalSource.__exit__")
                self.cleanup_failures.extend(clear_error_graph(error, notes=self.cleanup_notes))
            else:
                clear_error_graph(error)
        self.release(failed=error is not None)
        return False
