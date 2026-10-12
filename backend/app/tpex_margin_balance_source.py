"""Issue 31's bounded, nondurable FinMind margin snapshot adapter for seven TPEx stocks.

No application/worker/config imports, import-time I/O, automatic fetching, DB,
disk persistence, or strategy integration. A reviewed external financial-start
seal is a trust assertion, not something this module can issue or authenticate.
Its caller must independently verify the actual runtime and GitHub authorization.
The seal carries every role identity (global/owner/engineer/QA session IDs,
Claude model and effort, Orca runtime and terminal); none is defaulted or fixed
here, and the caller compares them with the Issue receipts. The QA must differ
from the other three roles, which must differ from each other, and the live
process must expose the same CLAUDE_CODE_SESSION_ID and CLAUDE_EFFORT (a missing
or different value refuses). The model is not in the environment: it is only
format-checked and compared with the QA-read RuntimeIdentity.
Transport: the default path builds the stdlib connection through
``native_connection``. The stdlib class rebinds itself by its module-global name
in ``__init__``, so replacing ``http.client.HTTPSConnection`` (even to wrap it)
breaks the original class with an opaque TypeError; that state is refused with
``transport_class_replaced`` before anything is spent, with or without a
``connection_factory``. An auditor wraps the connection by composition through
``connection_factory`` instead. Requests carry exactly Accept-Encoding: identity
and one fixed User-Agent, never a cookie, token or credential.
Only ``run`` opens the source lifecycle; the independent oracle and positive
consumer execute immediately in that same RAM process. The launcher must then
exit, including on failure. Caller aliases must be registered in ``RamRoots``;
Python cannot erase undisclosed references or immutable objects in other code.
Request/batch time limits are cooperative: remaining socket timeouts are
refreshed between blocking phases and elapsed budgets are checked afterwards.
DNS/OS/native operations cannot be forcibly interrupted by this RAM adapter.

Single source (AC revision 2): seven FinMind ``TaiwanStockMarginPurchaseShortSale``
requests, no TPEx official CSV and no official anchor. Rows follow the documented
16-column schema: fifteen required columns (``date`` and ``stock_id`` strings, thirteen
non-bool int64) with no extra key, plus the optional ``Note`` (absent, null or a string of
at most 256 characters; it never enters a computation). Instead of an anchor the
batch is checked internally: per symbol the sorted rows chain
(Yesterday[i+1] == Today[i]), the dates through 2026-10-06 are exactly the seven
verified calendar days, at least one row follows 2026-10-06 (chain check only, never
the formula), and all seven symbols have the same date set. Any failure rejects the
whole batch. The unit (lots) is an explicit provider inference, not an official
verification. The real response shape was observed once in the qa3 batch on
2026-10-11 UTC; any other shape still STOPs.
"""

from __future__ import annotations

import builtins
import hashlib
import http.client
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


ISSUE = "YiCheng0608/stock-lab#31"
# Runtime identity is never defaulted here: every actor, model and effort value
# comes from the reviewed seal, and the live Claude Code process must match it.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
EFFORT_ENV = "CLAUDE_EFFORT"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MODEL_PATTERN = r"claude-[a-z0-9][a-z0-9.-]{0,62}"
TERMINAL_PATTERN = r"term_[A-Za-z0-9_-]{1,80}"
# Fixed, non-personal; the one TPEx batch that succeeded (Issue 36) also identified itself this way.
REQUEST_USER_AGENT = "stock-lab-issue31-local-ram/1"
# Response media type (same parameter rule as the Issue 36 batch that succeeded against TPEx).
FINMIND_MEDIA = ("application/json",)
CHARSETS = ("charset=utf-8", 'charset="utf-8"')
# qa1 and qa2 are both SPENT / NO-RETRY and are never re-armed (qa1: constructor
# failure, no request; qa2: the official CSV answered ``application/csv`` and was
# refused before its body was read). qa3 is the new one-time source-use quota the
# user granted in https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111567857
# and narrowed to FinMind only (seven GET) in
# https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111752011.
# POLICY_* pin the canonical external policy v2 (``ordinary-margin-source-policy/v2``, 2886 bytes) exactly as the
# global published it in https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6112134098 .
NAMESPACE = "issue31-margin-seven-cutoffs-1005-1006-v1/qa3"
POLICY_SHA256 = "7d8cd5b1835b84138e2bc982d86a93d4b3b4a3bba809842341c279fe566a9ceb"
POLICY_BYTES = 2886
VERSION = "ordinary-margin-cutoffs-1005-1006-v2"
CONSUMER = "ordinary-margin-change-ratio-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
WINDOWS = (
    ("2026-10-05", ("2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05")),
    ("2026-10-06", ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")),
)
DAYS = ("2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
RANGE_FIRST, RANGE_LAST = "2026-09-24", "2026-10-09"
CUTOFF_LAST = DAYS[-1]  # 2026-10-06; rows after it are chain evidence only.
URLS = tuple(
    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id="
    + symbol + "&start_date=" + RANGE_FIRST + "&end_date=" + RANGE_LAST for symbol in SYMBOLS
)
INT64_MAX = (1 << 63) - 1
# The 16 columns documented by FinMind for this dataset (finmind.github.io, Chip page, DataFrameSchema), in
# the documented order. date, stock_id and Note are strings; the other thirteen are int64.
FINMIND_FIELDS = (
    "date", "stock_id", "MarginPurchaseBuy", "MarginPurchaseCashRepayment", "MarginPurchaseLimit",
    "MarginPurchaseSell", "MarginPurchaseTodayBalance", "MarginPurchaseYesterdayBalance", "Note",
    "OffsetLoanAndShort", "ShortSaleBuy", "ShortSaleCashRepayment", "ShortSaleLimit", "ShortSaleSell",
    "ShortSaleTodayBalance", "ShortSaleYesterdayBalance",
)
STRING_FIELDS = ("date", "stock_id", "Note")
# Note is documented but does not enter any computation, so it is optional (absent, str or null): a shape
# difference there must not spend the one-time quota. Every other documented column is required and strict.
OPTIONAL_FIELDS = ("Note",)
REQUIRED_FIELDS = tuple(name for name in FINMIND_FIELDS if name not in OPTIONAL_FIELDS)
NOTE_MAX_CHARS = 256  # A policy bound (global decision 6112016286), not a FinMind documentation fact.
UNKNOWN = ("publication_time", "first_availability", "revision_history", "historical_eligibility", "historical_membership")
ATTRIBUTION = (
    "FinMind: TaiwanStockMarginPurchaseShortSale; local personal noncommercial RAM snapshot only; "
    "no raw redistribution/mirror. FinMind is the service provider; this is not an official direct feed "
    "and the lot unit is an explicit provider inference, not an official verification."
)
RIGHTS_RECEIPTS = (
    "https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6084167671",
    "https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6077922990",
    "https://github.com/YiCheng0608/stock-lab/issues/21#issuecomment-6083237569",
    "https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111752011",
    "https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111788122",
)


class MarginSourceError(ValueError):
    """Only bounded static codes, never source or arbitrary exception text."""

    def __init__(self, code: str):
        self.code = code if type(code) is str and re.fullmatch(r"[a-z0-9_]{1,80}", code) else "invalid_error_code"
        super().__init__(self.code)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MarginSourceError(code)


def _sha(value: str, size: int = 64) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(size) + r"}", value) is not None


def _uuid(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value) is not None


def _matches(value: object, pattern: str) -> bool:
    return type(value) is str and re.fullmatch(pattern, value) is not None


# Captured at import: the stdlib class is only valid while http.client still
# binds this very object under its own name (see native_connection).
_NATIVE_HTTPS_CONNECTION = http.client.HTTPSConnection


def _native_transport_intact() -> bool:
    # Also check the class identity itself: a replacement installed before this
    # module was imported would otherwise be captured and compare equal to itself.
    current = http.client.HTTPSConnection
    return (current is _NATIVE_HTTPS_CONNECTION and getattr(current, "__module__", None) == "http.client"
            and getattr(current, "__qualname__", None) == "HTTPSConnection")


def native_connection(host: str, timeout: float) -> http.client.HTTPSConnection:
    """Direct stdlib HTTPS connection; construction never connects.

    An auditor composes this inside a ``connection_factory`` wrapper. Replacing
    ``http.client.HTTPSConnection`` with a wrapper makes the original class fail
    in ``__init__`` (``super(HTTPSConnection, self)`` resolves the replaced name),
    which in the sealed run surfaced only after the request slot was SPENT.
    """
    _require(_native_transport_intact(), "transport_class_replaced")
    return _NATIVE_HTTPS_CONNECTION(host, timeout=timeout)


def _check_live_runtime(holder_actual: str, effort: str) -> None:
    """The live Claude Code process must be the sealed QA; nothing is defaulted."""
    session, live_effort = os.environ.get(SESSION_ENV), os.environ.get(EFFORT_ENV)
    _require(bool(session) and bool(live_effort), "runtime_env_missing")
    _require(session == holder_actual, "actual_binding_conflict")
    _require(live_effort == effort, "runtime_effort_conflict")


def _day(value: str) -> str:
    """ISO ``YYYY-MM-DD`` only (ASCII digits); no other date grammar is accepted."""
    _require(type(value) is str, "date_type")
    _require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is not None, "date_grammar")
    try:
        return date(int(value[:4]), int(value[5:7]), int(value[8:])).isoformat()
    except ValueError:
        raise MarginSourceError("date_invalid") from None


def _integer(value: object) -> int:
    _require(type(value) is int and 0 <= value <= INT64_MAX, "integer_int64")
    return value


@dataclass(frozen=True)
class Caps:
    body_bytes: int = 1_048_576
    total_raw_bytes: int = 8_388_608
    retained_roots_estimate_bytes: int = 33_554_432
    request_seconds: int = 20
    batch_cooperative_seconds: int = 180
    max_requests: int = 7
    redirects: int = 0
    retries: int = 0


CAPS = Caps()


@dataclass(frozen=True)
class UseRequest:
    market: str = "TPEx"
    instrument: str = "ordinary_stock"
    symbols: tuple[str, ...] = SYMBOLS
    cutoffs: tuple[str, ...] = tuple(item[0] for item in WINDOWS)
    purpose: str = "margin5_balance_change_ratio"
    local_personal_noncommercial: bool = True
    process_ram_snapshot: bool = True
    historical_pit: bool = False

    def validate(self) -> None:
        _require(type(self) is UseRequest and all(type(v) is str for v in (self.market, self.instrument, self.purpose)),
                 "unsupported_use")
        _require(type(self.symbols) is tuple and type(self.cutoffs) is tuple
                 and all(type(v) is str for v in self.symbols + self.cutoffs), "unsupported_use")
        _require(all(type(v) is bool for v in (self.local_personal_noncommercial, self.process_ram_snapshot, self.historical_pit)),
                 "unsupported_use")
        _require(self == UseRequest(), "unsupported_use")


@dataclass(frozen=True)
class RuntimeIdentity:
    """What the QA read back from its own Claude Code runtime (its Issue receipt).

    session_id is CLAUDE_CODE_SESSION_ID and effort is CLAUDE_EFFORT; the model
    is the ``claude-*`` id of the assistant entries in the QA transcript.
    ``parent_session_id`` is the caller's assertion that this is a top-level
    session (None); it cannot be proven from inside the process.
    """

    session_id: str
    parent_session_id: str | None
    model: str
    effort: str
    candidate_sha: str


@dataclass(frozen=True)
class FinancialStartSeal:
    """Externally reviewed assertion; constructing it never establishes a grant.

    Every identity field is supplied by the seal and compared with the Issue
    receipts by the owner/global, never fixed in this module. ``holder_actual``
    is the sole QA's CLAUDE_CODE_SESSION_ID; ``global_actual`` issues the seal;
    ``owner_actual`` and ``engineer_actual`` are the task coordinator and
    engineer sessions. ``runtime_id`` is the Orca runtime (``_meta.runtimeId``
    of ``orca terminal show --json``) and ``terminal_handle`` the QA's visible
    terminal; both are format-checked only.
    """

    global_actual: str
    owner_actual: str
    engineer_actual: str
    holder_actual: str
    model: str
    effort: str
    runtime_id: str
    terminal_handle: str
    receipt_url: str
    issue: str
    namespace: str
    candidate_sha: str
    module_sha256: str
    full_script_sha256: str
    full_command_sha256: str
    policy_sha256: str
    caps: Caps
    expires_at_utc: str


def _json_pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "json_duplicate_key")
        result[key] = value
    return result


def _json_constant(_value: str) -> None:
    raise MarginSourceError("json_nonfinite")


def _strict_json(text: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_json_pairs, parse_constant=_json_constant)
    except (json.JSONDecodeError, RecursionError):
        raise MarginSourceError("json_invalid") from None


def _scrub_exception(exc: BaseException) -> None:
    """Drop traceback, cause/context and arbitrary args across the full chain."""
    stack, seen = [exc], set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                stack.append(linked)
        if isinstance(current, builtins.BaseExceptionGroup):
            stack.extend(current.exceptions)
        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)
        current.__traceback__ = current.__cause__ = current.__context__ = None
        current.args = ("scrubbed_exception",)
        # JSON/Unicode/HTTP exceptions can retain doc/object/response attributes.
        current.__dict__.clear()
        for attr in ("object", "doc", "response"):
            if hasattr(current, attr):
                try:
                    setattr(current, attr, None)
                except (AttributeError, TypeError):
                    pass


class RamRoots:
    """Caller-declared aliases; no frame/f_locals introspection or saving."""

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def hold(self, name: str, value: object) -> object:
        _require(type(name) is str and re.fullmatch(r"[a-z0-9_.]{1,64}", name) is not None, "root_name")
        _require(name not in self.values, "root_duplicate")
        self.values[name] = value
        return value

    def clear(self) -> tuple[str, ...]:
        names = tuple(self.values)
        seen, buffers, containers = set(), [], []

        def visit(value: object) -> None:
            if id(value) in seen:
                return
            seen.add(id(value))
            if isinstance(value, memoryview):
                value.release()
            elif isinstance(value, BaseException):
                _scrub_exception(value)
            elif type(value) is bytearray:
                buffers.append(value)
            elif type(value) in (dict, list, set):
                children = list(value.values()) if type(value) is dict else list(value)
                for item in children:
                    visit(item)
                containers.append(value)
            elif type(value) is tuple:
                for item in value:
                    visit(item)
            elif isinstance(value, Original):
                visit(value.buffer)
                visit(value.document)
                visit(value.parsed)
                value.text = value.document = value.parsed = None
            elif type(value) is OracleApproval:
                # A declared alias of the same approval is cleared as well;
                # do not merely delete one reference to its numeric tuples.
                for child in value.__dict__.values():
                    visit(child)
                for name in tuple(value.__dict__):
                    object.__setattr__(value, name, None)

        for value in self.values.values():
            visit(value)
        for container in reversed(containers):
            container.clear()
        for buffer in buffers:
            buffer[:] = b"\x00" * len(buffer)
            buffer.clear()
        self.values.clear()
        return names


def retained_estimate(*values: object) -> int:
    """Deduplicated declared-roots estimate; not RSS, allocator or peak memory."""
    seen = set()

    def size(value: object) -> int:
        if id(value) in seen:
            return 0
        seen.add(id(value))
        total = sys.getsizeof(value)
        if type(value) is dict:
            return total + sum(size(k) + size(v) for k, v in value.items())
        if isinstance(value, memoryview):
            return total + size(value.obj)
        if type(value) in (tuple, list, set):
            return total + sum(size(item) for item in value)
        if isinstance(value, Original):
            return total + size(value.__dict__)
        if type(value) is OracleApproval:
            return total + size(value.__dict__)
        return total

    return sum(size(value) for value in values)


@dataclass(frozen=True)
class Receipt:
    url: str
    provider: str
    dataset: str
    utc_start: str
    utc_end: str
    body_bytes: int
    body_sha256: str | None
    full_eof: bool
    status: int | None
    content_type: str
    declared_schema: tuple[str, ...]
    schema_validated: bool = False
    version: str = VERSION
    timezone: str = "Asia/Taipei"
    method: str = "GET"
    # True once the product entered connection.request(); False means the slot
    # was SPENT (attempted) but the connection was never asked to send anything.
    request_started: bool = False


@dataclass
class Original:
    buffer: bytearray = field(default_factory=bytearray)
    receipt: Receipt | None = None
    text: str | None = None
    document: object = None
    parsed: object = None


@dataclass(frozen=True)
class OracleApproval:
    """QA builds every value independently from all seven fresh originals.

    Ordered balances: (symbol, date, TodayBalance), all 49 points.
    Ordered ratios: (symbol, cutoff, numerator, positive denominator), all 14.
    Ordered chain links: (symbol, previous date, next date, previous Today,
    next Yesterday) for every adjacent pair of every symbol's date-sorted rows,
    symbol-major in SYMBOLS order, including the rows after the last cutoff.
    This explicit caller assertion is compared to product results; it cannot
    prove independence by itself. QA must not derive it from product projections.
    """

    holder_actual: str
    body_sha256: tuple[str, ...]
    balances: tuple[tuple[str, str, int], ...]
    ratios: tuple[tuple[str, str, int, int], ...]
    chain_links: tuple[tuple[str, str, str, int, int], ...]


@dataclass(frozen=True)
class CaptureReport:
    success: bool
    state: str
    attempted_spent: tuple[str, ...]
    unattempted_not_spent: tuple[str, ...]
    receipts: tuple[Receipt, ...]
    failure_stage: str | None
    primary_error: str | None
    secondary_diagnostics: tuple[str, ...]
    trace_events: tuple[tuple[str, str, int], ...]
    cleared_roots: tuple[str, ...]
    retained_estimate_high_water: int
    getter_count: int
    consumer_count: int
    artifact_bytes: int = 0
    requires_process_exit: bool = True
    # "native_direct" (stdlib via native_connection) or "caller_factory" (an
    # auditor-supplied connection_factory, e.g. a composed audit wrapper).
    transport: str = "native_direct"


class OriginalView:
    """Pending-oracle-only checked access; release also invalidates saved views."""

    def __init__(self, capture: MarginCapture, ordinal: int):
        self._capture, self._ordinal = capture, ordinal

    def _original(self) -> Original:
        self._capture._oracle_live()
        return self._capture._originals[self._ordinal]

    @property
    def receipt(self) -> Receipt:
        return self._original().receipt

    def body(self, root_name: str) -> memoryview:
        value = memoryview(self._original().buffer).toreadonly()
        self._capture.roots.hold(root_name, value)
        self._capture._measure()
        return value


class SixSessionWindow:
    """A revocable handle; it never caches detached observations."""

    def __init__(self, capture: MarginCapture, symbol: str, cutoff: str):
        self._capture, self.symbol, self.cutoff = capture, symbol, cutoff

    def _read(self) -> tuple:
        self._capture._live("available")
        days = dict(WINDOWS)[self.cutoff]
        return tuple((day, self._capture._balances[(self.symbol, day)]) for day in days)

    @property
    def observations(self) -> tuple[tuple[str, int], ...]:
        return self._read()

    @property
    def provenance(self) -> dict:
        self._read()
        capture = self._capture
        item = capture._originals[SYMBOLS.index(self.symbol)]
        return {
            "provider": "FinMind", "source_dataset": "TaiwanStockMarginPurchaseShortSale", "version": VERSION,
            "market": "TPEx", "instrument": "ordinary_stock", "symbol": self.symbol, "cutoff": self.cutoff,
            "unit": "lots", "unit_kind": "explicit_provider_inference", "provider_literal_unit": False,
            "official_anchor_verified": False, "numeric_scale": 1,
            "source_field": "MarginPurchaseTodayBalance", "receipt": item.receipt,
            "raw_row_ordinals": tuple(capture._ordinals[(self.symbol, day)] for day in dict(WINDOWS)[self.cutoff]),
            "internal_consistency": ("chain", "calendar_through_cutoff", "post_cutoff_row", "same_date_set"),
            "policy_sha256": POLICY_SHA256, "canonical_calendar": "d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md#31.2",
            "supported_use": "local_personal_noncommercial_process_ram_snapshot_margin5_only",
            "historical_pit": False, "unknown": UNKNOWN, "attribution": ATTRIBUTION, "rights_receipts": RIGHTS_RECEIPTS,
        }


class MarginRatio:
    """Exact ratio and rule gate for a snapshot input, not an actionable signal."""

    def __init__(self, window: SixSessionWindow):
        self._window = window

    @property
    def numerator(self) -> int:
        observations = self._window.observations
        return observations[-1][1] - observations[0][1]

    @property
    def positive_denominator(self) -> int:
        denominator = abs(self._window.observations[0][1])
        _require(denominator > 0, "zero_denominator")
        return denominator

    @property
    def exact_ratio(self) -> Fraction:
        return Fraction(self.numerator, self.positive_denominator)

    @property
    def at_most_five_percent(self) -> bool:
        return 20 * self.numerator <= self.positive_denominator

    @property
    def provenance(self) -> dict:
        return {**self._window.provenance, "consumer": CONSUMER, "formula": "(B[T]-B[T-5])/abs(B[T-5])",
                "ratio_representation": "exact_numerator_positive_denominator", "threshold": "0.05"}


_SPENT_NAMESPACES: set[str] = set()


class MarginCapture:
    def __init__(self, *, use: UseRequest, external_policy_utf8: bytes, seal: FinancialStartSeal,
                 runtime: RuntimeIdentity, full_script_utf8: bytes, full_command: str,
                 connection_factory: Callable[[str, float], object] | None = None):
        use.validate()  # Reject unsupported uses before even considering a source operation.
        _require(type(external_policy_utf8) is bytes and len(external_policy_utf8) == POLICY_BYTES
                 and hashlib.sha256(external_policy_utf8).hexdigest() == POLICY_SHA256, "external_policy_pin")
        _require(type(seal) is FinancialStartSeal and type(runtime) is RuntimeIdentity, "seal_type")
        _require(all(type(getattr(seal, name)) is str for name in (
            "global_actual", "owner_actual", "engineer_actual", "holder_actual", "model", "effort", "runtime_id",
            "terminal_handle", "receipt_url", "issue", "namespace", "candidate_sha", "module_sha256",
            "full_script_sha256", "full_command_sha256", "policy_sha256", "expires_at_utc")), "seal_field_type")
        _require(all(type(getattr(runtime, name)) is str for name in (
            "session_id", "model", "effort", "candidate_sha"))
            and (runtime.parent_session_id is None or type(runtime.parent_session_id) is str), "runtime_field_type")
        _require(connection_factory is None or callable(connection_factory), "connection_factory_type")
        _require(seal.issue == ISSUE and seal.namespace == NAMESPACE and seal.policy_sha256 == POLICY_SHA256,
                 "seal_authority")
        _require(type(seal.receipt_url) is str and re.fullmatch(
            r"https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-[0-9]+", seal.receipt_url), "seal_receipt")
        # Identity comes from the seal. Formats first, then independence, then
        # the QA-read runtime and the live process must both be that sole QA.
        _require(all(_uuid(getattr(seal, name)) for name in (
            "global_actual", "owner_actual", "engineer_actual", "holder_actual", "runtime_id")), "runtime_identity_invalid")
        _require(_matches(seal.model, MODEL_PATTERN), "model_invalid")
        _require(seal.effort in EFFORTS, "effort_invalid")
        _require(_matches(seal.terminal_handle, TERMINAL_PATTERN), "runtime_binding_invalid")
        _require(seal.holder_actual not in (seal.global_actual, seal.owner_actual, seal.engineer_actual),
                 "qa_not_independent")
        _require(len({seal.global_actual, seal.owner_actual, seal.engineer_actual}) == 3, "role_actors_not_distinct")
        _require(_uuid(runtime.session_id) and runtime.parent_session_id is None
                 and runtime.session_id == seal.holder_actual
                 and runtime.model == seal.model and runtime.effort == seal.effort, "sole_qa_runtime")
        _check_live_runtime(seal.holder_actual, seal.effort)
        _require(_sha(runtime.candidate_sha, 40) and _sha(seal.candidate_sha, 40)
                 and runtime.candidate_sha == seal.candidate_sha, "candidate_binding")
        _require(type(seal.caps) is Caps and seal.caps == CAPS
                 and all(type(v) is int for v in seal.caps.__dict__.values()), "caps_binding")
        _require(type(full_script_utf8) is bytes and _sha(seal.full_script_sha256)
                 and hashlib.sha256(full_script_utf8).hexdigest() == seal.full_script_sha256, "script_binding")
        _require(type(full_command) is str and _sha(seal.full_command_sha256)
                 and hashlib.sha256(full_command.encode("utf-8")).hexdigest() == seal.full_command_sha256, "command_binding")
        _require(_sha(seal.module_sha256) and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
                 == seal.module_sha256, "module_binding")
        _require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+00:00",
                             seal.expires_at_utc) is not None, "seal_expiry")
        try:
            expiry = datetime.fromisoformat(seal.expires_at_utc)
        except (ValueError, TypeError):
            raise MarginSourceError("seal_expiry") from None
        _require(expiry.tzinfo == timezone.utc and expiry > datetime.now(timezone.utc), "seal_expiry")
        self._seal, self._expiry_utc = seal, expiry
        self._connection_factory = connection_factory
        self.roots = RamRoots()
        self._originals: list[Original] = []
        self._balances: dict[tuple[str, str], int] = {}
        self._ordinals: dict[tuple[str, str], int] = {}
        self._links: list[tuple[str, str, str, int, int]] = []
        self._dates: tuple[str, ...] | None = None
        self._attempted: list[str] = []
        self._raw_total = 0
        self._deadline: float | None = None
        self._state, self._stage = "new", "new"
        self._high_water = self._getter_count = self._consumer_count = 0
        self._seen_getters: set[tuple[str, str]] = set()
        self._seen_consumers: set[tuple[str, str]] = set()
        self._events: list[tuple[str, str, int]] = []
        self._diagnostics: list[str] = []

    def _clock(self) -> None:
        _require(datetime.now(timezone.utc) < self._expiry_utc, "expired")
        _require(self._deadline is None or time.monotonic() < self._deadline, "expired")

    def _live(self, state: str) -> None:
        _require(self._state == state, "read_unavailable")
        try:
            self._clock()
        except MarginSourceError:
            self._state = "expired"
            raise

    def _oracle_live(self) -> None:
        _require(self._state == "pending_independent_oracle", "read_unavailable")
        self._clock()

    def _measure(self) -> None:
        self._clock()
        measured = retained_estimate(self._originals, self._balances, self._ordinals, self._links, self.roots.values)
        self._high_water = max(self._high_water, measured)
        _require(measured <= CAPS.retained_roots_estimate_bytes, "retained_roots_cap")

    def _trace(self, frame: object, event: str, _argument: object) -> Callable:
        # Never retain a frame, argument, locals, exception or response. Only
        # static module function name + line; no str(exception) at any layer.
        if event == "exception" and frame.f_code.co_filename == __file__ and len(self._events) < 128:
            self._events.append((self._stage, frame.f_code.co_name, frame.f_lineno))
        return self._trace

    def _open_connection(self, host: str, seconds: float) -> object:
        if self._connection_factory is None:
            return native_connection(host, seconds)
        return self._connection_factory(host, seconds)

    def _fetch(self, ordinal: int) -> Original:
        self._clock()
        url = URLS[ordinal]
        _require(len(self._attempted) == ordinal and ordinal < CAPS.max_requests, "request_order")
        self._attempted.append(url)  # Attempted is irrevocably SPENT, even if connect fails.
        original = Original()
        self._originals.append(original)
        start = datetime.now(timezone.utc).isoformat()
        status, content_type, full_eof = None, "", False
        completed, close_failed, request_started = False, False, False
        response = connection = None
        try:
            split = urlsplit(url)
            seconds = min(CAPS.request_seconds, self._deadline - time.monotonic())
            _require(seconds > 0, "expired")
            request_deadline = time.monotonic() + seconds
            connection = self._open_connection(split.hostname, seconds)
            # Native direct HTTPS: no proxy/cookie/token environment or redirect handler.
            request_started = True  # Constructor failures above never reach this line.
            connection.request("GET", split.path + "?" + split.query, headers={
                "Accept-Encoding": "identity", "User-Agent": REQUEST_USER_AGENT})
            self._clock()
            remaining_seconds = min(request_deadline, self._deadline) - time.monotonic()
            _require(remaining_seconds > 0, "request_timeout")
            _require(connection.sock is not None, "transport_socket")
            connection.sock.settimeout(remaining_seconds)
            response = connection.getresponse()
            self._clock()
            _require(time.monotonic() < request_deadline, "request_timeout")
            status = response.status
            _require(type(status) is int and status == 200, "http_status")
            headers = response.getheaders()
            normalized: dict[str, str] = {}
            for key, value in headers:
                key = key.lower()
                if key in ("content-length", "transfer-encoding", "content-encoding", "content-type", "location"):
                    _require(key not in normalized, "http_duplicate_header")
                    normalized[key] = value
            _require(normalized.get("content-encoding", "identity").lower() == "identity", "http_encoding")
            _require("location" not in normalized, "http_redirect")
            length = normalized.get("content-length")
            transfer = normalized.get("transfer-encoding")
            _require(not (length is not None and transfer is not None), "http_framing")
            _require(transfer is None or transfer.lower() == "chunked", "http_framing")
            if length is not None:
                _require(re.fullmatch(r"(?:0|[1-9][0-9]*)", length) is not None, "http_length")
                declared = int(length)
                _require(0 < declared <= CAPS.body_bytes and declared <= CAPS.total_raw_bytes - self._raw_total,
                         "raw_cap")
            else:
                declared = None
            raw_content_type = normalized.get("content-type", "").lower()
            _require(len(raw_content_type) <= 128, "http_content_type")
            # Same parameter rule as the Issue 36 batch that succeeded against TPEx: the media type, then only
            # charset=utf-8 parameters (whitespace around ';' is ignored).
            parts = [part.strip() for part in raw_content_type.split(";")]
            _require(parts[0] in FINMIND_MEDIA and all(part in CHARSETS for part in parts[1:]), "http_content_type")
            content_type = ";".join(parts)  # Only prevalidated, bounded metadata reaches a receipt.
            raw_content_type = parts = None
            while True:
                self._clock()
                _require(time.monotonic() < request_deadline, "request_timeout")
                body_remaining = CAPS.body_bytes - len(original.buffer)
                aggregate_remaining = CAPS.total_raw_bytes - self._raw_total
                remaining = min(body_remaining, aggregate_remaining)
                # A full cap is acceptable only with already-proven framing EOF.
                # Unknown/chunked exact-cap cannot spend an extra byte to probe.
                if response.isclosed():
                    _require(declared is None or len(original.buffer) == declared, "truncated_body")
                    full_eof = True
                    break
                _require(remaining > 0, "bounded_prefix_no_eof")
                # With Connection: close, HTTPConnection has already detached
                # its socket; HTTPResponse's active file still owns that socket.
                sock = connection.sock
                if sock is None and response.fp is not None:
                    sock = getattr(getattr(response.fp, "raw", None), "_sock", None)
                _require(sock is not None, "transport_socket")
                sock.settimeout(min(request_deadline, self._deadline) - time.monotonic())
                requested = min(65_536, remaining)
                chunk = response.read(requested)
                sock = None
                _require(type(chunk) is bytes and len(chunk) <= requested, "transport_read_contract")
                if not chunk:
                    _require(declared is None or len(original.buffer) == declared, "truncated_body")
                    # An empty read is EOF only with the stdlib framing parser's own closed state (as in Issue 36).
                    _require(response.isclosed(), "framing_eof_missing")
                    full_eof = True
                    break
                original.buffer.extend(chunk)
                self._raw_total += len(chunk)
                chunk = None
                self._clock()
                _require(time.monotonic() < request_deadline, "request_timeout")
                self._measure()
            _require(len(original.buffer) > 0, "empty_body")
            completed = True
            return original
        finally:
            # No complete SHA is reported for a bounded prefix/truncation.
            original.receipt = Receipt(url, "FinMind", "TaiwanStockMarginPurchaseShortSale", start,
                datetime.now(timezone.utc).isoformat(), len(original.buffer),
                hashlib.sha256(original.buffer).hexdigest() if full_eof else None, full_eof, status, content_type,
                FINMIND_FIELDS, request_started=request_started)
            if response is not None:
                try:
                    response.close()
                except Exception:
                    self._diagnostics.append("response_close_failed")
                    close_failed = True
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    self._diagnostics.append("connection_close_failed")
                    close_failed = True
            response = connection = None
            # Preserve an existing transport failure as primary. A new cleanup
            # failure following an otherwise successful request must itself
            # stop the batch rather than allowing the next source operation.
            if completed and close_failed:
                raise MarginSourceError("transport_cleanup_failed")

    def _decode(self, original: Original) -> str:
        _require(original.receipt.full_eof and _sha(original.receipt.body_sha256), "original_not_complete")
        _require(not original.buffer.startswith(b"\xef\xbb\xbf"), "bom_rejected")
        try:
            original.text = original.buffer.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise MarginSourceError("utf8_invalid") from None
        self._measure()
        return original.text

    def _finmind(self, original: Original, symbol: str) -> None:
        original.document = _strict_json(self._decode(original))
        document = original.document
        _require(type(document) is dict and set(document) == {"msg", "status", "data"}, "finmind_envelope")
        _require(type(document["status"]) is int and document["status"] == 200
                 and document["msg"] == "success", "finmind_status")
        rows = document["data"]
        _require(type(rows) is list and 0 < len(rows) <= 10_000, "finmind_rows")
        by_day: dict[str, tuple[int, int, int]] = {}
        original.parsed = by_day
        for ordinal, row in enumerate(rows, 1):
            self._clock()
            # The fifteen required columns, optionally Note, and no other key.
            _require(type(row) is dict and set(REQUIRED_FIELDS) <= set(row) <= set(FINMIND_FIELDS), "finmind_schema")
            day = _day(row["date"])
            _require(RANGE_FIRST <= day <= RANGE_LAST, "finmind_date_range")
            _require(type(row["stock_id"]) is str and row["stock_id"] == symbol and day not in by_day, "finmind_identity")
            note = row.get("Note")
            _require(note is None or (type(note) is str and len(note) <= NOTE_MAX_CHARS), "finmind_schema")
            for name in FINMIND_FIELDS:
                if name not in STRING_FIELDS:
                    _integer(row[name])
            by_day[day] = (row["MarginPurchaseYesterdayBalance"], row["MarginPurchaseTodayBalance"], ordinal)
            self._measure()
        # Internal consistency replaces the official anchor. ISO dates sort chronologically.
        days = sorted(by_day)
        _require(tuple(day for day in days if day <= CUTOFF_LAST) == DAYS, "required_day_set_mismatch")
        _require(days[-1] > CUTOFF_LAST, "post_cutoff_row_missing")
        links = []
        for previous_day, next_day in zip(days, days[1:]):
            today_before, yesterday_after = by_day[previous_day][1], by_day[next_day][0]
            _require(yesterday_after == today_before, "finmind_chain_break")
            links.append((symbol, previous_day, next_day, today_before, yesterday_after))
        _require(self._dates is None or tuple(days) == self._dates, "symbol_date_set_mismatch")
        # Rows after the last cutoff only served the chain; no post-cutoff value enters a window.
        for day in DAYS:
            self._balances[(symbol, day)] = by_day[day][1]
            self._ordinals[(symbol, day)] = by_day[day][2]
        for _cutoff, window in WINDOWS:
            _require(self._balances[(symbol, window[0])] > 0, "zero_denominator")
        self._dates = tuple(days)
        self._links.extend(links)
        original.receipt = replace(original.receipt, schema_validated=True)
        self._measure()

    def _approve(self, approval: OracleApproval) -> None:
        self._live("pending_independent_oracle")
        _require(type(approval) is OracleApproval and _uuid(approval.holder_actual)
                 and approval.holder_actual == self._seal.holder_actual, "oracle_holder")
        self.roots.hold("oracle.approval", approval)
        self._measure()
        _require(type(approval.body_sha256) is tuple and len(approval.body_sha256) == len(SYMBOLS)
                 and all(_sha(v) for v in approval.body_sha256)
                 and approval.body_sha256 == tuple(item.receipt.body_sha256 for item in self._originals), "oracle_hashes")
        balances = tuple((symbol, day, self._balances[(symbol, day)]) for symbol in SYMBOLS for day in DAYS)
        ratios = tuple((symbol, cutoff, self._balances[(symbol, days[-1])] - self._balances[(symbol, days[0])],
                        abs(self._balances[(symbol, days[0])])) for symbol in SYMBOLS for cutoff, days in WINDOWS)
        _require(type(approval.balances) is tuple and len(approval.balances) == 49
                 and all(type(row) is tuple and len(row) == 3 and type(row[0]) is str and type(row[1]) is str
                         and type(row[2]) is int and 0 <= row[2] <= INT64_MAX for row in approval.balances)
                 and approval.balances == balances, "oracle_balances")
        _require(type(approval.ratios) is tuple and len(approval.ratios) == 14
                 and all(type(row) is tuple and len(row) == 4 and type(row[0]) is str and type(row[1]) is str
                         and type(row[2]) is int and type(row[3]) is int and -INT64_MAX <= row[2] <= INT64_MAX
                         and 0 < row[3] <= INT64_MAX for row in approval.ratios) and approval.ratios == ratios, "oracle_ratios")
        _require(type(approval.chain_links) is tuple and len(approval.chain_links) == len(self._links) > 0
                 and all(type(row) is tuple and len(row) == 5 and all(type(v) is str for v in row[:3])
                         and type(row[3]) is int and type(row[4]) is int
                         and 0 <= row[3] <= INT64_MAX and 0 <= row[4] <= INT64_MAX and row[3] == row[4]
                         for row in approval.chain_links)
                 and approval.chain_links == tuple(self._links), "oracle_chain_links")
        self._state = "available"

    def originals(self) -> tuple[OriginalView, ...]:
        self._oracle_live()
        return tuple(OriginalView(self, ordinal) for ordinal in range(len(SYMBOLS)))

    def getter(self, symbol: str, cutoff: str, *, use: UseRequest = UseRequest()) -> SixSessionWindow:
        use.validate()
        _require(type(symbol) is str and symbol in SYMBOLS and type(cutoff) is str and cutoff in dict(WINDOWS), "unsupported_selector")
        self._live("available")
        self._getter_count += 1
        self._seen_getters.add((symbol, cutoff))
        return SixSessionWindow(self, symbol, cutoff)

    def consume(self, symbol: str, cutoff: str, *, consumer: str = CONSUMER, use: UseRequest = UseRequest()) -> MarginRatio:
        _require(type(consumer) is str and consumer == CONSUMER, "unsupported_consumer")
        window = self.getter(symbol, cutoff, use=use)
        self._consumer_count += 1
        self._seen_consumers.add((symbol, cutoff))
        return MarginRatio(window)

    def release(self) -> tuple[str, ...]:
        self._state = "released"  # Deny access before any cleanup attempt.
        if "capture.originals" not in self.roots.values:
            self.roots.hold("capture.originals", self._originals)
            self.roots.hold("capture.parsed_balances", self._balances)
            self.roots.hold("capture.parsed_ordinals", self._ordinals)
            self.roots.hold("capture.parsed_links", self._links)
        self._dates = None
        return self.roots.clear()

    def _oracle_call(self, callback: Callable) -> OracleApproval:
        # A new traced module frame also records exceptions raised in the
        # independent caller, without inspecting/saving that caller's frame.
        return callback(self)

    def _consumer_call(self, callback: Callable) -> None:
        return callback(self)

    def run(self, independent_oracle: Callable[[MarginCapture], OracleApproval],
            positive_consumer: Callable[[MarginCapture], None]) -> CaptureReport:
        _require(self._state == "new", "capture_once")
        _require(sys.gettrace() is None, "trace_already_active")
        _require(NAMESPACE not in _SPENT_NAMESPACES, "namespace_already_spent")
        _require(callable(independent_oracle) and callable(positive_consumer), "callbacks_required")
        # Everything below is checked before the namespace or any URL is spent.
        _check_live_runtime(self._seal.holder_actual, self._seal.effort)
        # An auditor's wrapper composes the native class and must not replace the global either.
        _require(_native_transport_intact(), "transport_class_replaced")
        self._clock()
        _SPENT_NAMESPACES.add(NAMESPACE)
        self._deadline = time.monotonic() + CAPS.batch_cooperative_seconds
        success, primary, failure_stage, receipts, cleared = False, None, None, (), ()
        self._state = "capturing"
        sys.settrace(self._trace)  # Before any transport/decode/parse/oracle.
        try:
            for ordinal, symbol in enumerate(SYMBOLS):
                self._stage = "finmind_capture"
                original = self._fetch(ordinal)
                self._stage = "finmind_parse"
                self._finmind(original, symbol)
            original = None
            self._state, self._stage = "pending_independent_oracle", "independent_oracle"
            approval = self._oracle_call(independent_oracle)
            self._approve(approval)
            approval = None
            self._stage = "positive_consumer"
            result = self._consumer_call(positive_consumer)
            self.roots.hold("results.callback_return", result)
            result = None
            self._live("available")
            expected = {(symbol, cutoff) for symbol in SYMBOLS for cutoff, _days in WINDOWS}
            _require(self._seen_getters == expected and self._seen_consumers == expected, "positive_consumer_incomplete")
            self._measure()
            success = True
        except BaseException as exc:
            failure_stage = self._stage
            primary = exc.code if type(exc) is MarginSourceError else "unexpected_exception"
            self._state = "failed"
            try:
                _scrub_exception(exc)
            except BaseException:
                self._diagnostics.append("primary_exception_cleanup_failed")
        finally:
            sys.settrace(None)
            receipts = tuple(item.receipt for item in self._originals if item.receipt is not None)
            original = approval = result = None
            try:
                cleared = self.release()
            except BaseException as cleanup_exc:
                self._diagnostics.append("roots_cleanup_failed")
                _scrub_exception(cleanup_exc)
                success = False
            independent_oracle = positive_consumer = None
            transport = "native_direct" if self._connection_factory is None else "caller_factory"
            self._connection_factory = None  # Drop the auditor's closure with the other caller references.
        return CaptureReport(success, self._state, tuple(self._attempted), URLS[len(self._attempted):], receipts,
            failure_stage, primary, tuple(self._diagnostics[:32]), tuple(self._events), cleared,
            self._high_water, self._getter_count, self._consumer_count, transport=transport)
