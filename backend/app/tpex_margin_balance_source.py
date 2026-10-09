"""Issue 31's bounded, nondurable TPEx margin snapshot adapter.

No application/worker/config imports, import-time I/O, automatic fetching, DB,
disk persistence, or strategy integration. A reviewed external financial-start
seal is a trust assertion, not something this module can issue or authenticate.
Its caller must independently verify the actual runtime and GitHub authorization.
Only ``run`` opens the source lifecycle; the independent oracle and positive
consumer execute immediately in that same RAM process. The launcher must then
exit, including on failure. Caller aliases must be registered in ``RamRoots``;
Python cannot erase undisclosed references or immutable objects in other code.
Request/batch time limits are cooperative: remaining socket timeouts are
refreshed between blocking phases and elapsed budgets are checked afterwards.
DNS/OS/native operations cannot be forcibly interrupted by this RAM adapter.

Predeclared official CSV layout: exactly OFFICIAL_FIELDS, first CSV record is
the header, subsequent records are all 21 columns including an explicit source
date. UTF-8 with optional initial BOM; no preamble/footer/blank records, aliases,
header repair, or title-date inference. Source dates: YYYY-MM-DD, YYYY/MM/DD,
YYYYMMDD, ROCYYY/MM/DD, or ROCYYYMMDD; month/day always two digits. Unknown actual
layout/date grammar STOPs without adapting to the observed body. Metadata only
suggested this layout; it does not prove the actual financial CSV has it.
"""

from __future__ import annotations

import csv
import hashlib
import http.client
import io
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


ISSUE = "YiCheng0608/stock-lab#31"
GLOBAL = "01a12102-9891-7293-8c66-a342094e0990"
NAMESPACE = "issue31-margin-seven-cutoffs-1005-1006-v1/qa1"
POLICY_SHA256 = "47ea789e4bac27cf736f9294f5c0563425b15cd5541748567f985ae262f224d7"
VERSION = "ordinary-margin-cutoffs-1005-1006-v1"
CONSUMER = "ordinary-margin-change-ratio-v1"
SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
WINDOWS = (
    ("2026-10-05", ("2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05")),
    ("2026-10-06", ("2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")),
)
DAYS = ("2026-09-24", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06")
ANCHOR_DATES = ("2026-10-08", "2026-10-09")
OFFICIAL_URL = "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data"
FINMIND_URLS = tuple(
    "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockMarginPurchaseShortSale&data_id="
    + symbol + "&start_date=2026-09-24&end_date=2026-10-09" for symbol in SYMBOLS
)
URLS = (OFFICIAL_URL,) + FINMIND_URLS
INT64_MAX = (1 << 63) - 1
OFFICIAL_FIELDS = (
    "資料日期", "代號", "名稱", "前資餘額", "資買", "資賣", "現償", "資餘額", "資屬證金",
    "資使用率", "資限額", "前券餘額", "券賣", "券買", "券償", "券餘額", "券屬證金",
    "券使用率", "券限額", "資券相抵", "備註",
)
FINMIND_FIELDS = (
    "date", "stock_id", "MarginPurchaseBuy", "MarginPurchaseCashRepayment", "MarginPurchaseLimit",
    "MarginPurchaseSell", "MarginPurchaseTodayBalance", "MarginPurchaseYesterdayBalance", "ShortSaleBuy",
    "ShortSaleCashRepayment", "ShortSaleLimit", "ShortSaleSell", "ShortSaleTodayBalance",
    "ShortSaleYesterdayBalance", "OffsetLoanAndShort",
)
UNKNOWN = ("publication_time", "first_availability", "revision_history", "historical_eligibility", "historical_membership")
ATTRIBUTION = (
    "FinMind: TaiwanStockMarginPurchaseShortSale; local personal noncommercial RAM snapshot only; "
    "no raw redistribution/mirror. TPEx / Financial Supervisory Commission Securities and Futures Bureau "
    "[2026]: 上櫃股票融資融券餘額 (dataset11387, exact current CSV); Open Government Data License 1.0 "
    "https://data.gov.tw/license; original fields and integrity preserved. FinMind is the service provider; "
    "this is not an official direct feed."
)
RIGHTS_RECEIPTS = (
    "https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6084167671",
    "https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6077922990",
    "https://github.com/YiCheng0608/stock-lab/issues/21#issuecomment-6083237569",
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


def _day(value: str, *, official: bool = False) -> str:
    _require(type(value) is str, "date_type")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        parts = (int(value[:4]), int(value[5:7]), int(value[8:]))
    elif official and re.fullmatch(r"[0-9]{4}/[0-9]{2}/[0-9]{2}", value):
        parts = (int(value[:4]), int(value[5:7]), int(value[8:]))
    elif official and re.fullmatch(r"[0-9]{8}", value):
        parts = (int(value[:4]), int(value[4:6]), int(value[6:]))
    elif official and re.fullmatch(r"[0-9]{3}/[0-9]{2}/[0-9]{2}", value):
        parts = (int(value[:3]) + 1911, int(value[4:6]), int(value[7:]))
    elif official and re.fullmatch(r"[0-9]{7}", value):
        parts = (int(value[:3]) + 1911, int(value[3:5]), int(value[5:]))
    else:
        raise MarginSourceError("date_grammar")
    try:
        return date(*parts).isoformat()
    except ValueError:
        raise MarginSourceError("date_invalid") from None


def _integer(value: object, *, csv_text: bool = False) -> int:
    if csv_text:
        _require(type(value) is str and re.fullmatch(r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)", value) is not None,
                 "integer_grammar")
        value = int(value.replace(",", ""))
    _require(type(value) is int and 0 <= value <= INT64_MAX, "integer_int64")
    return value


@dataclass(frozen=True)
class Caps:
    body_bytes: int = 1_048_576
    total_raw_bytes: int = 8_388_608
    retained_roots_estimate_bytes: int = 33_554_432
    request_seconds: int = 20
    batch_cooperative_seconds: int = 180
    max_requests: int = 8
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
    thread_id: str
    session_id: str
    parent_thread_id: str | None
    model: str
    reasoning: str
    candidate_sha: str


@dataclass(frozen=True)
class FinancialStartSeal:
    """Externally reviewed assertion; constructing it never establishes a grant."""

    issuer_actual: str
    receipt_url: str
    issue: str
    namespace: str
    holder_actual: str
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
        if isinstance(current, BaseExceptionGroup):
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
            elif type(value) in (OfficialOracleApproval, OracleApproval):
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
        if type(value) in (OfficialOracleApproval, OracleApproval):
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


@dataclass
class Original:
    buffer: bytearray = field(default_factory=bytearray)
    receipt: Receipt | None = None
    text: str | None = None
    document: object = None
    parsed: object = None


@dataclass(frozen=True)
class OfficialOracleApproval:
    """Independent full official-body audit, required before seven FinMind GETs.

    Anchors are seven ordered (symbol, source date, previous, current, 1-based
    CSV record ordinal) tuples. The caller must independently validate the full
    header, every row, date/identity/numerics and anchors from the original body.
    """

    holder_actual: str
    body_sha256: str
    fields: tuple[str, ...]
    anchors: tuple[tuple[str, str, int, int, int], ...]


@dataclass(frozen=True)
class OracleApproval:
    """QA builds every value independently from all eight fresh originals.

    Ordered balances: (symbol, source date, TodayBalance), all 49 points.
    Ordered ratios: (symbol, cutoff, numerator, positive denominator), all 14.
    Ordered anchors: (symbol, official source date, previous, current), all 7.
    This explicit caller assertion is compared to product results; it cannot
    prove independence by itself. QA must not derive it from product projections.
    """

    holder_actual: str
    body_sha256: tuple[str, ...]
    balances: tuple[tuple[str, str, int], ...]
    ratios: tuple[tuple[str, str, int, int], ...]
    anchors: tuple[tuple[str, str, int, int], ...]


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


class OriginalView:
    """Pending-oracle-only checked access; release also invalidates saved views."""

    def __init__(self, capture: MarginCapture, ordinal: int):
        self._capture, self._ordinal = capture, ordinal

    def _original(self) -> Original:
        self._capture._oracle_live(self._ordinal)
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
        item = capture._originals[SYMBOLS.index(self.symbol) + 1]
        official = capture._originals[0]
        return {
            "provider": "FinMind", "source_dataset": "TaiwanStockMarginPurchaseShortSale", "version": VERSION,
            "market": "TPEx", "instrument": "ordinary_stock", "symbol": self.symbol, "cutoff": self.cutoff,
            "unit": "lots", "unit_kind": "conditional_combination_inference", "provider_literal_unit": False,
            "historical_unit_extension": "explicit_limited_snapshot_inference", "numeric_scale": 1,
            "source_field": "MarginPurchaseTodayBalance", "receipt": item.receipt,
            "raw_row_ordinals": tuple(capture._ordinals[(self.symbol, day)] for day in dict(WINDOWS)[self.cutoff]),
            "official_receipt": official.receipt, "official_source_date": capture._anchor_date,
            "official_original_fields": OFFICIAL_FIELDS, "official_record_ordinal": capture._anchors[self.symbol][2],
            "official_previous_field_ordinal": 3, "official_current_field_ordinal": 7,
            "official_previous_current": capture._anchors[self.symbol][:2],
            "anchor_relation": "same_date_both_exact_each_symbol_at_least_one_nonzero",
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
                 runtime: RuntimeIdentity, full_script_utf8: bytes, full_command: str):
        use.validate()  # Reject unsupported uses before even considering a source operation.
        _require(type(external_policy_utf8) is bytes and len(external_policy_utf8) == 2399
                 and hashlib.sha256(external_policy_utf8).hexdigest() == POLICY_SHA256, "external_policy_pin")
        _require(type(seal) is FinancialStartSeal and type(runtime) is RuntimeIdentity, "seal_type")
        _require(all(type(getattr(seal, name)) is str for name in (
            "issuer_actual", "receipt_url", "issue", "namespace", "holder_actual", "candidate_sha", "module_sha256",
            "full_script_sha256", "full_command_sha256", "policy_sha256", "expires_at_utc")), "seal_field_type")
        _require(all(type(getattr(runtime, name)) is str for name in (
            "thread_id", "session_id", "model", "reasoning", "candidate_sha")), "runtime_field_type")
        _require(seal.issuer_actual == GLOBAL and seal.issue == ISSUE and seal.namespace == NAMESPACE
                 and seal.policy_sha256 == POLICY_SHA256, "seal_authority")
        _require(type(seal.receipt_url) is str and re.fullmatch(
            r"https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-[0-9]+", seal.receipt_url), "seal_receipt")
        _require(_uuid(seal.holder_actual) and _uuid(runtime.thread_id) and _uuid(runtime.session_id)
                 and runtime.parent_thread_id is None and runtime.thread_id == runtime.session_id == seal.holder_actual
                 and runtime.model == "gpt-6.1-sol" and runtime.reasoning == "xhigh", "sole_qa_runtime")
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
        self.roots = RamRoots()
        self._originals: list[Original] = []
        self._balances: dict[tuple[str, str], int] = {}
        self._ordinals: dict[tuple[str, str], int] = {}
        self._anchors: dict[str, tuple[int, int, int]] = {}
        self._anchor_date: str | None = None
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

    def _oracle_live(self, ordinal: int) -> None:
        _require(self._state == "pending_independent_oracle"
                 or (self._state == "pending_official_oracle" and ordinal == 0), "read_unavailable")
        self._clock()

    def _measure(self) -> None:
        self._clock()
        measured = retained_estimate(self._originals, self._balances, self._ordinals, self._anchors, self.roots.values)
        self._high_water = max(self._high_water, measured)
        _require(measured <= CAPS.retained_roots_estimate_bytes, "retained_roots_cap")

    def _trace(self, frame: object, event: str, _argument: object) -> Callable:
        # Never retain a frame, argument, locals, exception or response. Only
        # static module function name + line; no str(exception) at any layer.
        if event == "exception" and frame.f_code.co_filename == __file__ and len(self._events) < 128:
            self._events.append((self._stage, frame.f_code.co_name, frame.f_lineno))
        return self._trace

    def _fetch(self, ordinal: int) -> Original:
        self._clock()
        url = URLS[ordinal]
        _require(len(self._attempted) == ordinal and ordinal < CAPS.max_requests, "request_order")
        self._attempted.append(url)  # Attempted is irrevocably SPENT, even if connect fails.
        original = Original()
        self._originals.append(original)
        start = datetime.now(timezone.utc).isoformat()
        status, content_type, full_eof = None, "", False
        completed, close_failed = False, False
        response = connection = None
        try:
            split = urlsplit(url)
            seconds = min(CAPS.request_seconds, self._deadline - time.monotonic())
            _require(seconds > 0, "expired")
            request_deadline = time.monotonic() + seconds
            connection = http.client.HTTPSConnection(split.hostname, timeout=seconds)
            # Native direct HTTPS: no proxy/cookie/token environment or redirect handler.
            connection.request("GET", split.path + "?" + split.query, headers={"Accept-Encoding": "identity"})
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
            _require(len(raw_content_type) <= 128 and re.fullmatch(
                r"[a-z]+/[a-z0-9.+-]+(?:;[ ]*charset=(?:utf-8|\"utf-8\"))?", raw_content_type) is not None,
                "http_content_type")
            media = raw_content_type.split(";", 1)[0]
            _require(media in (("text/csv", "text/plain", "application/octet-stream") if ordinal == 0
                               else ("application/json",)), "http_content_type")
            content_type = raw_content_type  # Only prevalidated, bounded metadata reaches a receipt.
            raw_content_type = None
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
            original.receipt = Receipt(url, "TPEx" if ordinal == 0 else "FinMind",
                "dataset11387-current-csv" if ordinal == 0 else "TaiwanStockMarginPurchaseShortSale", start,
                datetime.now(timezone.utc).isoformat(), len(original.buffer),
                hashlib.sha256(original.buffer).hexdigest() if full_eof else None, full_eof, status, content_type,
                OFFICIAL_FIELDS if ordinal == 0 else FINMIND_FIELDS)
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

    def _decode(self, original: Original, *, csv_body: bool = False) -> str:
        _require(original.receipt.full_eof and _sha(original.receipt.body_sha256), "original_not_complete")
        try:
            original.text = original.buffer.decode("utf-8-sig" if csv_body else "utf-8", errors="strict")
        except UnicodeDecodeError:
            raise MarginSourceError("utf8_invalid") from None
        self._measure()
        return original.text

    def _official(self, original: Original) -> None:
        stream = io.StringIO(self._decode(original, csv_body=True), newline="")
        rows: list[list[str]] = []
        original.document = rows
        anchors: dict[str, tuple[int, int, int]] = {}
        original.parsed = anchors
        seen, report_day = set(), None
        try:
            reader = csv.reader(stream, strict=True)
            for ordinal, row in enumerate(reader, 1):
                self._clock()
                rows.append(row)
                self._measure()
                _require(len(row) == 21 and all(not any(ord(c) < 32 for c in cell) for cell in row), "csv_row_shape")
                if ordinal == 1:
                    _require(tuple(row) == OFFICIAL_FIELDS, "csv_header")
                    continue
                _require(ordinal <= 10_001, "csv_row_limit")
                day = _day(row[0], official=True)
                _require(day in ANCHOR_DATES and (report_day is None or report_day == day), "official_source_date")
                report_day = day
                code = row[1]
                _require(re.fullmatch(r"[0-9A-Z]{4,6}", code) is not None and code not in seen, "official_identity")
                _require(bool(row[2].strip()) and row[2] == row[2].strip(), "official_name")
                seen.add(code)
                values = {}
                for index in range(3, 20):
                    if index in (9, 17):
                        _require(re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?%?", row[index]) is not None, "csv_rate")
                        _require(Decimal(row[index].removesuffix("%")) <= 100, "csv_rate")
                    else:
                        values[index] = _integer(row[index], csv_text=True)
                if code in SYMBOLS:
                    previous, current = values[3], values[7]
                    _require(previous != 0 or current != 0, "ambiguous_zero_scale")
                    anchors[code] = (previous, current, ordinal)
            _require(set(anchors) == set(SYMBOLS), "official_selected_missing")
            self._anchors, self._anchor_date = anchors, report_day
            original.receipt = replace(original.receipt, schema_validated=True)
        except csv.Error:
            raise MarginSourceError("csv_invalid") from None
        finally:
            stream.close()
            stream = reader = None

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
            _require(type(row) is dict and set(row) == set(FINMIND_FIELDS), "finmind_schema")
            day = _day(row["date"])
            _require("2026-09-24" <= day <= "2026-10-09", "finmind_date_range")
            _require(type(row["stock_id"]) is str and row["stock_id"] == symbol and day not in by_day, "finmind_identity")
            for name in FINMIND_FIELDS[2:]:
                _integer(row[name])
            by_day[day] = (row["MarginPurchaseYesterdayBalance"], row["MarginPurchaseTodayBalance"], ordinal)
            self._measure()
        _require(set(DAYS) <= set(by_day), "required_day_missing")
        _require(self._anchor_date in by_day, "anchor_day_missing")
        previous, current, _ = by_day[self._anchor_date]
        _require((previous, current) == self._anchors[symbol][:2], "anchor_exact_mismatch")
        # No rescaling and no inferred post-cutoff calendar. Only the seven
        # externally pinned dates are admitted to the historical computation.
        for day in DAYS:
            self._balances[(symbol, day)] = by_day[day][1]
            self._ordinals[(symbol, day)] = by_day[day][2]
        for _cutoff, days in WINDOWS:
            _require(self._balances[(symbol, days[0])] > 0, "zero_denominator")
        original.receipt = replace(original.receipt, schema_validated=True)
        self._measure()

    def _approve(self, approval: OracleApproval) -> None:
        self._live("pending_independent_oracle")
        _require(type(approval) is OracleApproval and _uuid(approval.holder_actual)
                 and approval.holder_actual == self._seal.holder_actual, "oracle_holder")
        self.roots.hold("oracle.approval", approval)
        self._measure()
        _require(type(approval.body_sha256) is tuple and len(approval.body_sha256) == 8
                 and all(_sha(v) for v in approval.body_sha256)
                 and approval.body_sha256 == tuple(item.receipt.body_sha256 for item in self._originals), "oracle_hashes")
        balances = tuple((symbol, day, self._balances[(symbol, day)]) for symbol in SYMBOLS for day in DAYS)
        ratios = tuple((symbol, cutoff, self._balances[(symbol, days[-1])] - self._balances[(symbol, days[0])],
                        abs(self._balances[(symbol, days[0])])) for symbol in SYMBOLS for cutoff, days in WINDOWS)
        anchors = tuple((symbol, self._anchor_date, *self._anchors[symbol][:2]) for symbol in SYMBOLS)
        _require(type(approval.balances) is tuple and len(approval.balances) == 49
                 and all(type(row) is tuple and len(row) == 3 and type(row[0]) is str and type(row[1]) is str
                         and type(row[2]) is int and 0 <= row[2] <= INT64_MAX for row in approval.balances)
                 and approval.balances == balances, "oracle_balances")
        _require(type(approval.ratios) is tuple and len(approval.ratios) == 14
                 and all(type(row) is tuple and len(row) == 4 and type(row[0]) is str and type(row[1]) is str
                         and type(row[2]) is int and type(row[3]) is int and -INT64_MAX <= row[2] <= INT64_MAX
                         and 0 < row[3] <= INT64_MAX for row in approval.ratios) and approval.ratios == ratios, "oracle_ratios")
        _require(type(approval.anchors) is tuple and all(type(row) is tuple and len(row) == 4
                 and type(row[0]) is str and type(row[1]) is str and type(row[2]) is int and type(row[3]) is int
                 and 0 <= row[2] <= INT64_MAX and 0 <= row[3] <= INT64_MAX for row in approval.anchors)
                 and approval.anchors == anchors, "oracle_anchors")
        self._state = "available"

    def _approve_official(self, approval: OfficialOracleApproval) -> None:
        self._live("pending_official_oracle")
        _require(type(approval) is OfficialOracleApproval and _uuid(approval.holder_actual)
                 and approval.holder_actual == self._seal.holder_actual, "official_oracle_holder")
        self.roots.hold("oracle.official_approval", approval)
        self._measure()
        _require(_sha(approval.body_sha256) and approval.body_sha256 == self._originals[0].receipt.body_sha256,
                 "official_oracle_hash")
        _require(type(approval.fields) is tuple and len(approval.fields) == 21
                 and all(type(v) is str for v in approval.fields) and approval.fields == OFFICIAL_FIELDS,
                 "official_oracle_fields")
        expected = tuple((symbol, self._anchor_date, *self._anchors[symbol]) for symbol in SYMBOLS)
        _require(type(approval.anchors) is tuple and len(approval.anchors) == 7
                 and all(type(row) is tuple and len(row) == 5 and type(row[0]) is str and type(row[1]) is str
                         and type(row[2]) is int and type(row[3]) is int and type(row[4]) is int
                         and 0 <= row[2] <= INT64_MAX and 0 <= row[3] <= INT64_MAX
                         and (row[2] != 0 or row[3] != 0) and 2 <= row[4] <= 10_001 for row in approval.anchors)
                 and approval.anchors == expected, "official_oracle_anchors")
        self._state = "capturing"

    def originals(self) -> tuple[OriginalView, ...]:
        self._oracle_live(0)
        count = 1 if self._state == "pending_official_oracle" else 8
        return tuple(OriginalView(self, ordinal) for ordinal in range(count))

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
            self.roots.hold("capture.parsed_anchors", self._anchors)
        return self.roots.clear()

    def _oracle_call(self, callback: Callable) -> OfficialOracleApproval | OracleApproval:
        # A new traced module frame also records exceptions raised in the
        # independent caller, without inspecting/saving that caller's frame.
        return callback(self)

    def _consumer_call(self, callback: Callable) -> None:
        return callback(self)

    def run(self, independent_oracle: Callable[[MarginCapture], OracleApproval],
            positive_consumer: Callable[[MarginCapture], None], *,
            independent_official_oracle: Callable[[MarginCapture], OfficialOracleApproval]) -> CaptureReport:
        _require(self._state == "new", "capture_once")
        _require(sys.gettrace() is None, "trace_already_active")
        _require(NAMESPACE not in _SPENT_NAMESPACES, "namespace_already_spent")
        _require(callable(independent_official_oracle) and callable(independent_oracle)
                 and callable(positive_consumer), "callbacks_required")
        self._clock()
        _SPENT_NAMESPACES.add(NAMESPACE)
        self._deadline = time.monotonic() + CAPS.batch_cooperative_seconds
        success, primary, failure_stage, receipts, cleared = False, None, None, (), ()
        self._state = "capturing"
        sys.settrace(self._trace)  # Before any transport/decode/parse/oracle.
        try:
            self._stage = "official_capture"
            original = self._fetch(0)
            self._stage = "official_parse"
            self._official(original)
            self._state, self._stage = "pending_official_oracle", "independent_official_oracle"
            approval = self._oracle_call(independent_official_oracle)
            self._approve_official(approval)
            approval = None
            for ordinal, symbol in enumerate(SYMBOLS, 1):
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
            independent_official_oracle = independent_oracle = positive_consumer = None
        return CaptureReport(success, self._state, tuple(self._attempted), URLS[len(self._attempted):], receipts,
            failure_stage, primary, tuple(self._diagnostics[:32]), tuple(self._events), cleared,
            self._high_water, self._getter_count, self._consumer_count)
