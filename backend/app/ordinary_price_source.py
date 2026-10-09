"""Explicit, one-shot, process-RAM ordinary close windows.

No application configuration, database, environment or source is read on import.
The external policy is Issue #7 comment 6081459941, not a financial QA grant.
The caller must obtain a separate QA-start receipt binding the actual command,
candidate, loaded source hash and independent runtime session before acquiring.
This module checks that binding; it does not authenticate GitHub or runtime IDs.

Usage: with acquire_once(...) as bundle: independently parse the observed bodies,
confirm_independent_oracle(bundle, evidence, use), then call the pure consumers.
Neither the product's evidence checks nor synthetic tests certify independent QA.
All readers require the live lease. Caller-owned immutable results cannot be
physically revoked; the caller's release callback must clear its retained roots.
Time and retained-object caps are cooperative estimates, not OS deadlines/RSS.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import http.client
import json
import re
import sys
from threading import Lock
import time
from typing import Callable, Iterator
from urllib.parse import urlsplit
from uuid import UUID


SYMBOLS = ("3105", "3293", "5274", "5347", "6488", "6510", "8069")
AS_OF = "2026-10-06"
DATES = (
    "2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10",
    "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17",
    "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24",
    "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05",
    "2026-10-06",
)
CALENDAR_VERSION = "tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1"
POLICY_VERSION = "issue7-ordinary-close-source-use-v1"
CONSUMER_VERSION = "ordinary-close-window-summary-v1"
SOURCE_USE = "local_personal_noncommercial_observed_nominal_close_window"
UNIT_POLICY_VERSION = "finmind-tpex-reported-close-composite-twd-per-share-v1"
EXPECTED_POLICY_SHA256 = "97938e771f08b2a1c338916ad6afd9ae1e4174e58fadf0f4eaddf6b35f919601"
QA_NAMESPACE = "issue7-seven-ordinary-close-1006-v1/qa1"
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
ANCHOR_VERSION = "stock-lab/master:d8918bc6491ec8ef65874979cf88d1322df2da43:SOURCE_REGISTRY/32.2:2026-10-06"
# Accepted public canonical facts, not the private saved files or this bundle.
# QA must separately read the exact formal master section and supply its oracle.
LATEST_CLOSE_ANCHORS = tuple(zip(SYMBOLS, map(Decimal, ("592", "780", "18985", "191", "1205", "3055", "149"))))
BODY_CAP = 1_048_576
TOTAL_RAW_CAP = 7_340_032
RETAINED_CAP = 33_554_432
REQUEST_SECONDS = 20
LEASE_SECONDS = 180


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


_POLICY = {
    "version": POLICY_VERSION,
    "scope": {"market": "TW/TPEx", "symbols": list(SYMBOLS), "as_of": AS_OF,
              "start_date": DATES[0], "end_date": AS_OF, "calendar_version": CALENDAR_VERSION},
    "provider": "FinMind", "dataset": "TaiwanStockPrice", "method": "GET",
    "source_use": SOURCE_USE, "consumer_version": CONSUMER_VERSION,
    "unit_policy": {
        "version": UNIT_POLICY_VERSION, "unit": "TWD/share", "basis": "provider_reported_nominal_close",
        "evidence": "FinMind llms-full.txt lines170-178 + master d8918bc SOURCE_REGISTRY section32.2 actual TPEx OHLC canonical unit contract",
        "provider_literal_unit_annotation": False, "inference": True,
        "requires_independent_qa_latest_close_anchor_match": True,
    },
    "rights": "FinMind attribution; no raw redistribution, mirror, commercial use or deployment",
    "unsupported": ["historical_pit", "publication_time", "first_availability", "revision_history",
                    "adjustment_verified", "whole_window_historical_membership_verified", "strategy_or_trading_use", "other_cutoff"],
    "network": {"qa_namespace": QA_NAMESPACE, "max_gets": 7, "per_symbol_max_gets": 1,
                "body_cap_bytes": BODY_CAP, "total_raw_cap_bytes": TOTAL_RAW_CAP,
                "retained_roots_estimate_cap_bytes": RETAINED_CAP, "request_seconds": REQUEST_SECONDS,
                "batch_lease_seconds": LEASE_SECONDS, "deadline": "cooperative", "accept_encoding": "identity",
                "redirects": 0, "retries": 0, "stop_on_first_failure": True},
    "lifecycle": "QA sole process; full body/hash -> independent oracle -> positive getter/consumer -> finally release and exit; artifact0B",
}
POLICY_CANONICAL_BYTES = canonical_bytes(_POLICY)
del _POLICY
_SEALED_NAMESPACES: set[str] = set()
_SEAL_LOCK = Lock()


class OrdinaryPriceSourceError(ValueError):
    """Bounded diagnostics; do not publish raw financial values in Issue receipts."""

    def __init__(self, code: str, *, symbol: str | None = None, ordinal: int | None = None,
                 field: str | None = None, observed: object = None):
        super().__init__(code)
        self.code, self.symbol, self.ordinal, self.field = code, symbol, ordinal, field
        self.observed_repr = repr(observed)[:160] if observed is not None else None
        self.cleanup_error: str | None = None


@dataclass(frozen=True, slots=True)
class ExplicitUse:
    expected_policy_sha256: str
    source_use: str
    consumer_version: str
    market: str
    symbols: tuple[str, ...]
    as_of: str
    calendar_version: str
    unit_policy_version: str
    basis: str
    required_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QAReadGrant:
    authorization_kind: str
    approval_receipt: str
    candidate_sha: str
    module_sha256: str
    qa_session_id: str
    implementer_session_id: str
    command: str
    namespace: str
    expected_policy_sha256: str
    consumer_version: str
    anchor_version: str


@dataclass(frozen=True, slots=True)
class RetainedRoots:
    """Caller declares all original, independent-oracle and consumer result roots."""
    originals: object
    oracle: object
    results: object


@dataclass(frozen=True, slots=True)
class CloseObservation:
    date: str
    close: Decimal
    row_ordinal: int


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    provider: str
    dataset: str
    method: str
    url: str
    symbol: str
    source_version: str
    requested_start: str
    requested_end: str
    observed_started_at: str
    observed_ended_at: str
    body_sha256: str
    body_bytes: int
    eof: bool
    http_status: int
    namespace: str
    policy_sha256: str
    candidate_sha: str
    module_sha256: str


@dataclass(frozen=True, slots=True)
class _Capture:
    body: bytes
    receipt: SourceReceipt
    observations: tuple[CloseObservation, ...]


@dataclass(frozen=True, slots=True)
class SymbolOracle:
    symbol: str
    body_sha256: str
    observations: tuple[CloseObservation, ...]
    latest_close_anchor: Decimal


@dataclass(frozen=True, slots=True)
class IndependentOracleEvidence:
    qa_session_id: str
    candidate_sha: str
    module_sha256: str
    namespace: str
    policy_sha256: str
    consumer_version: str
    anchor_version: str
    symbols: tuple[SymbolOracle, ...]


@dataclass(frozen=True, slots=True)
class Provenance:
    receipt: SourceReceipt
    policy_version: str
    consumer_version: str
    calendar_version: str
    date_timezone: str
    source_use: str
    attribution: str
    market: str
    instrument_type: str
    identity_as_of: str
    unit: str
    basis: str
    unit_policy_version: str
    unit_mapping_inference: bool
    provider_literal_unit_annotation: bool
    anchor_version: str
    independent_oracle_session: str
    publication_time: str
    first_availability: str
    revision_time: str
    adjustment_verified: bool
    whole_window_historical_membership_verified: bool
    unsupported: tuple[str, ...]
    storage: str
    rights: str


@dataclass(frozen=True, slots=True)
class CloseSeries:
    symbol: str
    observations: tuple[CloseObservation, ...]
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class SymbolWindowSummary:
    series: CloseSeries
    window_dates: tuple[str, ...]
    count: int
    mean: Decimal
    latest_close: Decimal
    previous_close: Decimal
    latest_minus_previous: Decimal


@dataclass(frozen=True, slots=True)
class OrdinaryCloseWindowSummary:
    consumer_version: str
    as_of: str
    symbols: tuple[SymbolWindowSummary, ...]


def _valid_sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _valid_git_sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _validate_use(use: ExplicitUse) -> None:
    if type(use) is not ExplicitUse:
        raise OrdinaryPriceSourceError("explicit_use_required")
    expected = (EXPECTED_POLICY_SHA256, SOURCE_USE, CONSUMER_VERSION, "TW/TPEx", SYMBOLS, AS_OF,
                CALENDAR_VERSION, UNIT_POLICY_VERSION, "provider_reported_nominal_close")
    actual = (use.expected_policy_sha256, use.source_use, use.consumer_version, use.market,
              use.symbols, use.as_of, use.calendar_version, use.unit_policy_version, use.basis)
    if (actual != expected or type(use.symbols) is not tuple
            or any(type(item) is not str for item in actual[:4] + actual[5:])
            or any(type(item) is not str for item in use.symbols)):
        raise OrdinaryPriceSourceError("source_use_not_admitted")
    if type(use.required_capabilities) is not tuple or use.required_capabilities:
        raise OrdinaryPriceSourceError("required_capability_not_supported")


def _validate_grant(grant: QAReadGrant) -> None:
    if type(grant) is not QAReadGrant:
        raise OrdinaryPriceSourceError("explicit_qa_grant_required")
    if any(type(getattr(grant, field.name)) is not str for field in fields(grant)):
        raise OrdinaryPriceSourceError("qa_grant_binding_invalid")
    if (grant.authorization_kind != "issue7-explicit-qa-start"
            or type(grant.approval_receipt) is not str
            or not re.fullmatch(r"https://github\.com/YiCheng0608/stock-lab/issues/7#issuecomment-[0-9]+", grant.approval_receipt)
            or int(grant.approval_receipt.rsplit("-", 1)[1]) <= 6081657709
            or not _valid_git_sha(grant.candidate_sha) or not _valid_sha(grant.module_sha256)
            or type(grant.command) is not str or not grant.command.strip() or len(grant.command) > 16_384
            or "-B" not in grant.command or "-X utf8" not in grant.command
            or grant.namespace != QA_NAMESPACE or grant.expected_policy_sha256 != EXPECTED_POLICY_SHA256
            or grant.consumer_version != CONSUMER_VERSION or grant.anchor_version != ANCHOR_VERSION):
        raise OrdinaryPriceSourceError("qa_grant_binding_invalid")
    try:
        for session in (grant.qa_session_id, grant.implementer_session_id):
            if type(session) is not str or str(UUID(session)) != session:
                raise ValueError()
        if grant.qa_session_id == grant.implementer_session_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise OrdinaryPriceSourceError("qa_session_not_independent") from None


def _validate_policy(policy_bytes: bytes, expected_sha256: str) -> None:
    if (type(policy_bytes) is not bytes or expected_sha256 != EXPECTED_POLICY_SHA256
            or len(policy_bytes) != 1665 or hashlib.sha256(policy_bytes).hexdigest() != expected_sha256
            or policy_bytes != POLICY_CANONICAL_BYTES):
        raise OrdinaryPriceSourceError("external_policy_pin_mismatch")


def _estimate_roots(roots: object) -> int:
    """Deduplicate declared graphs, not process RSS or construction peak."""
    seen: set[int] = set()
    stack = [roots]
    total = 0
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        total += sys.getsizeof(value)
        if total > RETAINED_CAP:
            raise OrdinaryPriceSourceError("retained_roots_cap_exceeded")
        if type(value) is dict:
            stack.extend(value.keys())
            stack.extend(value.values())
        elif type(value) in (tuple, list, set, frozenset):
            stack.extend(value)
        elif is_dataclass(value) and not isinstance(value, type):
            stack.extend(getattr(value, field.name) for field in fields(value))
        elif type(value) not in (str, bytes, bytearray, int, float, bool, type(None), Decimal, date, datetime):
            raise OrdinaryPriceSourceError("retained_root_type_unsupported")
    return total


class LeaseBudget:
    """Check every boundary, including roots held by the independent caller."""

    def __init__(self, roots: Callable[[], RetainedRoots], clock: Callable[[], float]):
        self._roots, self._clock = roots, clock
        self._started = clock()
        self._owned: list[object] = []
        self.released = False
        self._release_on_failure: Callable[[], None] | None = None
        self.estimated_high_water_bytes = 0

    def checkpoint(self, *extra_roots: object) -> float:
        try:
            return self._checkpoint(*extra_roots)
        except OrdinaryPriceSourceError as error:
            if not self.released and self._release_on_failure is not None:
                try:
                    self._release_on_failure()
                except Exception as cleanup:
                    error.cleanup_error = str(cleanup)
                    error.add_note("Observer release: " + str(cleanup))
            raise

    def _checkpoint(self, *extra_roots: object) -> float:
        if self.released:
            raise OrdinaryPriceSourceError("lease_released")
        remaining = LEASE_SECONDS - (self._clock() - self._started)
        if remaining <= 0 or remaining > LEASE_SECONDS:
            raise OrdinaryPriceSourceError("lease_expired")
        try:
            external = self._roots()
        except Exception as error:
            raise OrdinaryPriceSourceError("retained_roots_callback_failed") from error
        if type(external) is not RetainedRoots or any(
            type(root) not in (tuple, list, dict) for root in (external.originals, external.oracle, external.results)
        ):
            raise OrdinaryPriceSourceError("retained_roots_required")
        estimate = _estimate_roots((self._owned, external, extra_roots))
        self.estimated_high_water_bytes = max(self.estimated_high_water_bytes, estimate)
        return remaining


class SourceBundle:
    """Atomic seven-symbol source; never available before independent evidence."""

    __slots__ = ("_budget", "_grant", "_captures", "_capture_builders", "_evidence", "_release_observer", "_release_called",
                 "request_count", "cleanup_error")

    def __init__(self, budget: LeaseBudget, grant: QAReadGrant, release_observer: Callable[[], None]):
        self._budget, self._grant, self._release_observer = budget, grant, release_observer
        self._captures: tuple[_Capture, ...] = ()
        self._capture_builders: list[_Capture] = []
        self._evidence: IndependentOracleEvidence | None = None
        self._release_called = False
        self.request_count = 0
        self.cleanup_error: str | None = None
        budget._release_on_failure = self.release

    @property
    def state(self) -> str:
        if self._budget.released:
            return "released"
        return "available" if self._evidence is not None else "pending_oracle"

    @property
    def estimated_retained_bytes(self) -> int:
        return self._budget.estimated_high_water_bytes

    @property
    def receipts(self) -> tuple[SourceReceipt, ...]:
        self._budget.checkpoint()
        return tuple(capture.receipt for capture in self._captures)

    def release(self) -> None:
        if self._release_called:
            return
        self._release_called = True
        self._budget.released = True
        self._captures, self._evidence = (), None
        self._capture_builders.clear()
        self._budget._owned.clear()
        try:
            self._release_observer()
            roots = self._budget._roots()
            if type(roots) is not RetainedRoots or any((roots.originals, roots.oracle, roots.results)):
                raise OrdinaryPriceSourceError("external_roots_not_released")
        except Exception as error:
            self.cleanup_error = error.code if type(error) is OrdinaryPriceSourceError else "observer_release_failed"
            raise OrdinaryPriceSourceError(self.cleanup_error) from error


class _HTTPResponse:
    def __init__(self, response: http.client.HTTPResponse, connection: http.client.HTTPSConnection, url: str):
        self._response, self._connection = response, connection
        self.status, self.headers, self.url = response.status, response.headers, url

    def read(self, size: int) -> bytes:
        return self._response.read(size)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()


def _open_response(url: str, timeout: float, headers: dict[str, str]) -> _HTTPResponse:
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection("api.finmindtrade.com", timeout=timeout)
    try:
        connection.request("GET", parsed.path + "?" + parsed.query, headers=headers)
        return _HTTPResponse(connection.getresponse(), connection, url)
    except BaseException:
        connection.close()
        raise


def source_url(symbol: str) -> str:
    if type(symbol) is not str or symbol not in SYMBOLS:
        raise OrdinaryPriceSourceError("symbol_not_admitted")
    return ENDPOINT + "?dataset=TaiwanStockPrice&data_id=" + symbol + "&start_date=2026-09-04&end_date=2026-10-06"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise OrdinaryPriceSourceError("json_duplicate_key", field=key)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise OrdinaryPriceSourceError("json_nonfinite_number", observed=value)


def _positive_close(value: object, *, symbol: str, ordinal: int) -> Decimal:
    if type(value) not in (int, Decimal):
        raise OrdinaryPriceSourceError("close_not_numeric", symbol=symbol, ordinal=ordinal, field="close", observed=value)
    close = Decimal(value)
    if not close.is_finite() or close <= 0:
        raise OrdinaryPriceSourceError("close_not_finite_positive", symbol=symbol, ordinal=ordinal, field="close", observed=value)
    # Refuse arithmetic representations whose expanded precision alone exceeds
    # the bounded source body; do not rescale, round or repair reported values.
    if len(close.as_tuple().digits) + abs(close.as_tuple().exponent) > BODY_CAP:
        raise OrdinaryPriceSourceError("close_numeric_budget", symbol=symbol, ordinal=ordinal, field="close")
    return close


def _parse_body(body: bytes, symbol: str, budget: LeaseBudget) -> tuple[CloseObservation, ...]:
    try:
        text = body.decode("utf-8", errors="strict")
        document = json.loads(text, parse_float=Decimal, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        if type(error) is OrdinaryPriceSourceError:
            raise
        raise OrdinaryPriceSourceError("body_json_invalid", symbol=symbol) from error
    budget.checkpoint(body, text, document)
    if (type(document) is not dict or type(document.get("status")) is not int or document["status"] != 200
            or document.get("msg") != "success" or type(document.get("data")) is not list):
        raise OrdinaryPriceSourceError("provider_schema_invalid", symbol=symbol)
    rows = document["data"]
    if len(rows) != 21:
        raise OrdinaryPriceSourceError("window_row_count", symbol=symbol, observed=len(rows))
    observations: list[CloseObservation] = []
    seen: set[str] = set()
    for ordinal, row in enumerate(rows, 1):
        if type(row) is not dict or not {"date", "stock_id", "close"} <= row.keys():
            raise OrdinaryPriceSourceError("row_schema_invalid", symbol=symbol, ordinal=ordinal)
        day = row["date"]
        if type(day) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day) is None:
            raise OrdinaryPriceSourceError("row_date_shape", symbol=symbol, ordinal=ordinal, field="date", observed=day)
        try:
            date.fromisoformat(day)
        except ValueError:
            raise OrdinaryPriceSourceError("row_date_invalid", symbol=symbol, ordinal=ordinal, field="date", observed=day) from None
        if type(row["stock_id"]) is not str or row["stock_id"] != symbol:
            raise OrdinaryPriceSourceError("row_symbol_invalid", symbol=symbol, ordinal=ordinal, field="stock_id", observed=row["stock_id"])
        if day in seen:
            raise OrdinaryPriceSourceError("row_date_duplicate", symbol=symbol, ordinal=ordinal, field="date", observed=day)
        seen.add(day)
        if day not in DATES:
            raise OrdinaryPriceSourceError("row_date_not_in_calendar", symbol=symbol, ordinal=ordinal, field="date", observed=day)
        observations.append(CloseObservation(day, _positive_close(row["close"], symbol=symbol, ordinal=ordinal), ordinal))
    if tuple(item.date for item in observations) != DATES:
        raise OrdinaryPriceSourceError("window_date_order_or_missing", symbol=symbol)
    budget.checkpoint(body, document, observations)
    return tuple(observations)


def _utc_text(now: Callable[[], datetime]) -> str:
    value = now()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise OrdinaryPriceSourceError("observation_utc_required")
    return value.isoformat()


def _capture(symbol: str, bundle: SourceBundle, transport: Callable, now: Callable[[], datetime],
             observer: Callable[[bytes, SourceReceipt, LeaseBudget], None], total_raw: int) -> _Capture:
    budget, grant = bundle._budget, bundle._grant
    remaining = budget.checkpoint()
    started_tick = budget._clock()
    started_utc = _utc_text(now)
    url = source_url(symbol)
    response = None
    buffer = bytearray()
    body = b""
    failure: BaseException | None = None
    try:
        # Increment before the transport call: connect/HTTP/parse failures SPEND.
        bundle.request_count += 1
        response = transport(url, min(REQUEST_SECONDS, remaining), {"Accept-Encoding": "identity", "Accept": "application/json"})
        budget.checkpoint(buffer)
        if type(response.status) is not int or response.status != 200 or response.url != url:
            raise OrdinaryPriceSourceError("http_status_or_redirect", symbol=symbol, observed=response.status)
        encoding = response.headers.get("Content-Encoding", "identity")
        if encoding not in ("", "identity"):
            raise OrdinaryPriceSourceError("content_encoding_not_identity", symbol=symbol)
        content_type = response.headers.get("Content-Type")
        if type(content_type) is not str:
            raise OrdinaryPriceSourceError("content_type_not_json_utf8", symbol=symbol)
        media, *parameters = (part.strip().lower() for part in content_type.split(";"))
        charsets = [parameter.partition("=")[2].strip().strip('"') for parameter in parameters
                    if parameter.partition("=")[0].strip() == "charset"]
        if media != "application/json" or any(charset not in ("utf-8", "utf8") for charset in charsets):
            raise OrdinaryPriceSourceError("content_type_not_json_utf8", symbol=symbol)
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            if type(content_length) is not str or re.fullmatch(r"[0-9]+", content_length) is None:
                raise OrdinaryPriceSourceError("content_length_invalid", symbol=symbol)
            if len(content_length) > 10 or int(content_length) > BODY_CAP:
                raise OrdinaryPriceSourceError("body_cap_exceeded", symbol=symbol)
        while True:
            budget.checkpoint(buffer)
            if budget._clock() - started_tick >= REQUEST_SECONDS:
                raise OrdinaryPriceSourceError("request_deadline", symbol=symbol)
            chunk = response.read(min(65_536, BODY_CAP + 1 - len(buffer)))
            if type(chunk) is not bytes:
                raise OrdinaryPriceSourceError("transport_chunk_invalid", symbol=symbol)
            if len(buffer) + len(chunk) > BODY_CAP or total_raw + len(buffer) + len(chunk) > TOTAL_RAW_CAP:
                raise OrdinaryPriceSourceError("body_cap_exceeded", symbol=symbol)
            buffer.extend(chunk)
            budget.checkpoint(buffer, chunk)
            if budget._clock() - started_tick >= REQUEST_SECONDS:
                raise OrdinaryPriceSourceError("request_deadline", symbol=symbol)
            if not chunk:
                break
        body = bytes(buffer)
        if content_length is not None and len(body) != int(content_length):
            raise OrdinaryPriceSourceError("body_length_or_eof", symbol=symbol)
        digest = hashlib.sha256(body).hexdigest()  # Full EOF body before decode.
        ended_utc = _utc_text(now)
        if datetime.fromisoformat(ended_utc) < datetime.fromisoformat(started_utc):
            raise OrdinaryPriceSourceError("observation_time_order", symbol=symbol)
        receipt = SourceReceipt("FinMind", "TaiwanStockPrice", "GET", url, symbol,
                                "finmind-taiwan-stock-price/" + symbol + "/2026-09-04_2026-10-06/observed-" + digest,
                                DATES[0], AS_OF, started_utc, ended_utc, digest, len(body), True, 200,
                                grant.namespace, EXPECTED_POLICY_SHA256, grant.candidate_sha, grant.module_sha256)
        observations = _parse_body(body, symbol, budget)
        capture = _Capture(body, receipt, observations)
        budget.checkpoint(buffer, capture)
        observer(body, receipt, budget)
        budget.checkpoint(buffer, capture)
        return capture
    except OrdinaryPriceSourceError as error:
        failure = error
        raise
    except Exception as error:
        failure = OrdinaryPriceSourceError("source_acquisition_failed", symbol=symbol)
        raise failure from error
    finally:
        buffer.clear()
        body = b""
        if response is not None:
            try:
                response.close()
            except Exception as cleanup:
                if failure is None:
                    raise OrdinaryPriceSourceError("response_close_failed", symbol=symbol) from cleanup
                failure.add_note("Response close: " + type(cleanup).__name__)


@contextmanager
def acquire_once(grant: QAReadGrant, explicit_use: ExplicitUse,
                 original_observer: Callable[[bytes, SourceReceipt, LeaseBudget], None],
                 retained_roots: Callable[[], RetainedRoots], release_observer: Callable[[], None], *,
                 policy_bytes: bytes, expected_policy_sha256: str,
                 transport: Callable | None = None, monotonic: Callable[[], float] = time.monotonic,
                 utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Iterator[SourceBundle]:
    """No implicit grant, fallback, refresh, retry or cross-process quota reset.

    ``transport`` is solely a network-zero boundary-test seam. Real QA must use
    the default product transport and independently verify the exact command.
    The RAM namespace seal is not a cross-process technical authorization lock.
    """
    _validate_use(explicit_use)  # Unsupported requested capabilities BEFORE GET.
    _validate_policy(policy_bytes, expected_policy_sha256)
    _validate_grant(grant)
    if not all(callable(callback) for callback in (original_observer, retained_roots, release_observer, monotonic, utc_now)):
        raise OrdinaryPriceSourceError("observer_and_roots_required")
    budget = LeaseBudget(retained_roots, monotonic)
    bundle = SourceBundle(budget, grant, release_observer)
    budget._owned.extend((grant, explicit_use, policy_bytes))
    failure = None
    try:
        budget.checkpoint()
        with _SEAL_LOCK:
            if grant.namespace in _SEALED_NAMESPACES:
                raise OrdinaryPriceSourceError("qa_namespace_spent")
            _SEALED_NAMESPACES.add(grant.namespace)
        total_raw = 0
        captures = bundle._capture_builders
        budget._owned.append(captures)
        for symbol in SYMBOLS:
            capture = _capture(symbol, bundle, _open_response if transport is None else transport,
                               utc_now, original_observer, total_raw)
            captures.append(capture)
            total_raw += len(capture.body)
            budget.checkpoint()
        bundle._captures = tuple(captures)
        capture = None
        budget.checkpoint(bundle._captures)
        yield bundle  # Pending oracle: neither positive getter nor consumer yet.
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            bundle.release()
        except Exception as cleanup:
            if failure is None:
                raise
            if isinstance(failure, OrdinaryPriceSourceError):
                failure.cleanup_error = bundle.cleanup_error
            failure.add_note("Observer release: " + str(cleanup))


def _validate_evidence(bundle: SourceBundle, evidence: IndependentOracleEvidence) -> None:
    grant = bundle._grant
    _validate_grant(grant)
    if type(evidence) is not IndependentOracleEvidence:
        raise OrdinaryPriceSourceError("independent_oracle_required")
    expected = (grant.qa_session_id, grant.candidate_sha, grant.module_sha256, grant.namespace,
                EXPECTED_POLICY_SHA256, CONSUMER_VERSION, ANCHOR_VERSION)
    actual = (evidence.qa_session_id, evidence.candidate_sha, evidence.module_sha256, evidence.namespace,
              evidence.policy_sha256, evidence.consumer_version, evidence.anchor_version)
    if (actual != expected or any(type(value) is not str for value in actual)
            or type(evidence.symbols) is not tuple or len(evidence.symbols) != 7):
        raise OrdinaryPriceSourceError("independent_oracle_binding_invalid")
    if type(bundle._captures) is not tuple or len(bundle._captures) != 7:
        raise OrdinaryPriceSourceError("complete_seven_symbol_bundle_required")
    for capture, oracle, (symbol, anchor) in zip(bundle._captures, evidence.symbols, LATEST_CLOSE_ANCHORS):
        if (type(capture) is not _Capture or type(capture.body) is not bytes or type(capture.receipt) is not SourceReceipt
                or type(oracle) is not SymbolOracle or oracle.symbol != symbol or capture.receipt.symbol != symbol
                or type(oracle.symbol) is not str or type(oracle.body_sha256) is not str
                or oracle.body_sha256 != capture.receipt.body_sha256
                or hashlib.sha256(capture.body).hexdigest() != oracle.body_sha256
                or type(oracle.observations) is not tuple or len(oracle.observations) != 21
                or type(capture.observations) is not tuple or len(capture.observations) != 21):
            raise OrdinaryPriceSourceError("independent_oracle_source_mismatch", symbol=symbol)
        receipt = capture.receipt
        if (any(type(getattr(receipt, field.name)) is not str for field in fields(receipt)
                if field.name not in ("body_bytes", "eof", "http_status"))
                or receipt.policy_sha256 != EXPECTED_POLICY_SHA256 or receipt.candidate_sha != grant.candidate_sha
                or receipt.module_sha256 != grant.module_sha256 or receipt.namespace != grant.namespace
                or receipt.provider != "FinMind" or receipt.dataset != "TaiwanStockPrice" or receipt.method != "GET"
                or receipt.url != source_url(symbol) or receipt.requested_start != DATES[0] or receipt.requested_end != AS_OF
                or type(receipt.eof) is not bool or not receipt.eof or type(receipt.body_bytes) is not int
                or receipt.body_bytes != len(capture.body) or type(receipt.http_status) is not int or receipt.http_status != 200
                or receipt.source_version != "finmind-taiwan-stock-price/" + symbol + "/2026-09-04_2026-10-06/observed-" + oracle.body_sha256):
            raise OrdinaryPriceSourceError("source_receipt_binding_invalid", symbol=symbol)
        try:
            started, ended = map(datetime.fromisoformat, (receipt.observed_started_at, receipt.observed_ended_at))
            if (started.tzinfo is None or ended.tzinfo is None or started.utcoffset().total_seconds() != 0
                    or ended.utcoffset().total_seconds() != 0 or not 0 <= (ended - started).total_seconds() <= REQUEST_SECONDS):
                raise ValueError()
        except (ValueError, AttributeError):
            raise OrdinaryPriceSourceError("source_receipt_utc_invalid", symbol=symbol) from None
        # Rebind every read to the unchanged original bytes. Comparing two
        # caller-visible projections alone would permit mutually changed data.
        raw_observations = _parse_body(capture.body, symbol, bundle._budget)
        if raw_observations != capture.observations:
            raise OrdinaryPriceSourceError("source_projection_not_bound_to_raw", symbol=symbol)
        for ordinal, (day, expected_row, actual_row) in enumerate(zip(DATES, oracle.observations, capture.observations), 1):
            if (type(expected_row) is not CloseObservation or type(expected_row.date) is not str or expected_row.date != day
                    or type(expected_row.close) is not Decimal or not expected_row.close.is_finite() or expected_row.close <= 0
                    or type(expected_row.row_ordinal) is not int or expected_row.row_ordinal != ordinal
                    or type(actual_row) is not CloseObservation or type(actual_row.date) is not str
                    or type(actual_row.close) is not Decimal or type(actual_row.row_ordinal) is not int
                    or expected_row != actual_row):
                raise OrdinaryPriceSourceError("independent_oracle_sequence_mismatch", symbol=symbol, ordinal=ordinal)
        if (type(oracle.latest_close_anchor) is not Decimal or not oracle.latest_close_anchor.is_finite()
                or oracle.latest_close_anchor != anchor or oracle.observations[-1].close != anchor):
            raise OrdinaryPriceSourceError("independent_latest_close_anchor_mismatch", symbol=symbol)


def confirm_independent_oracle(bundle: SourceBundle, evidence: IndependentOracleEvidence, explicit_use: ExplicitUse) -> None:
    """Bind externally supplied full oracle and formal anchors; not an AC verdict."""
    _validate_use(explicit_use)
    if type(bundle) is not SourceBundle:
        raise OrdinaryPriceSourceError("live_source_bundle_required")
    bundle._budget.checkpoint(evidence)
    if bundle._evidence is not None:
        raise OrdinaryPriceSourceError("independent_oracle_already_bound")
    try:
        _validate_evidence(bundle, evidence)
    except OrdinaryPriceSourceError as error:
        _release_failed_bundle(bundle, error)
        raise
    bundle._evidence = evidence
    bundle._budget._owned.append(evidence)
    bundle._budget.checkpoint()


def _read_gate(bundle: SourceBundle, explicit_use: ExplicitUse) -> IndependentOracleEvidence:
    _validate_use(explicit_use)
    if type(bundle) is not SourceBundle:
        raise OrdinaryPriceSourceError("live_source_bundle_required")
    bundle._budget.checkpoint()
    if bundle._evidence is None:
        raise OrdinaryPriceSourceError("independent_oracle_required")
    try:
        _validate_evidence(bundle, bundle._evidence)
    except OrdinaryPriceSourceError as error:
        _release_failed_bundle(bundle, error)
        raise
    return bundle._evidence


def _release_failed_bundle(bundle: SourceBundle, error: OrdinaryPriceSourceError) -> None:
    try:
        bundle.release()
    except Exception as cleanup:
        error.cleanup_error = bundle.cleanup_error
        error.add_note("Observer release: " + str(cleanup))


def get_21_closes(bundle: SourceBundle, symbol: str, as_of: str, explicit_use: ExplicitUse) -> CloseSeries:
    evidence = _read_gate(bundle, explicit_use)
    if type(symbol) is not str or symbol not in SYMBOLS or type(as_of) is not str or as_of != AS_OF:
        raise OrdinaryPriceSourceError("symbol_or_cutoff_not_admitted")
    capture = bundle._captures[SYMBOLS.index(symbol)]
    provenance = Provenance(
        capture.receipt, POLICY_VERSION, CONSUMER_VERSION, CALENDAR_VERSION, "Asia/Taipei", SOURCE_USE, "FinMind",
        "TW/TPEx", "ordinary_stock", AS_OF, "TWD/share", "provider_reported_nominal_close", UNIT_POLICY_VERSION,
        True, False, ANCHOR_VERSION, evidence.qa_session_id, "unknown", "unknown", "unknown", False, False,
        ("historical_pit", "publication_time", "first_availability", "revision_history", "adjustment_verified",
         "whole_window_historical_membership_verified", "strategy_or_trading_use", "other_cutoff"), "process_RAM",
        "FinMind attribution; no raw redistribution, mirror, commercial use or deployment",
    )
    result = CloseSeries(symbol, capture.observations, provenance)
    bundle._budget.checkpoint(result)
    return result


def _exact_arithmetic(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    precision = max(value.adjusted() for value in values) - min(value.as_tuple().exponent for value in values) + 8
    if precision > BODY_CAP:
        raise OrdinaryPriceSourceError("summary_numeric_budget")
    with localcontext() as context:
        context.prec = max(28, precision)
        context.Emax = max(context.Emax, max(value.adjusted() for value in values) + 8)
        context.Emin = min(context.Emin, min(value.as_tuple().exponent for value in values) - 8)
        return sum(values[1:], Decimal(0)) / Decimal(20), values[-1] - values[-2]


def summarize_ordinary_close_window(bundle: SourceBundle, explicit_request: ExplicitUse) -> OrdinaryCloseWindowSummary:
    _read_gate(bundle, explicit_request)
    summaries: list[SymbolWindowSummary] = []
    for symbol in SYMBOLS:
        series = get_21_closes(bundle, symbol, AS_OF, explicit_request)
        values = tuple(item.close for item in series.observations)
        try:
            mean, change = _exact_arithmetic(values)
        except (ArithmeticError, OrdinaryPriceSourceError) as failure:
            error = failure if type(failure) is OrdinaryPriceSourceError else OrdinaryPriceSourceError("summary_arithmetic_failed", symbol=symbol)
            _release_failed_bundle(bundle, error)
            raise error
        summaries.append(SymbolWindowSummary(series, DATES[1:], 20, mean, values[-1], values[-2], change))
        bundle._budget.checkpoint(summaries)
    result = OrdinaryCloseWindowSummary(CONSUMER_VERSION, AS_OF, tuple(summaries))
    bundle._budget.checkpoint(result)
    return result
