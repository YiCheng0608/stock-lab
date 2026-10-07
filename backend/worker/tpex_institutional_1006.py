"""Independently pinned, explicit 2026-10-06 TPEx windows in process memory.

The W8 module is immutable. Only its invariant CSV/numeric primitives are
reused; its policy, captures, receipts, URL gates and cache are never reused.
Only MemoryWindowCache1006.load performs HTTP. Observation is not PIT.
"""
from __future__ import annotations

from collections import defaultdict
import copy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import sys
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from worker.tpex_institutional_window import (
    DAILY_HEADER, INDEX_HEADER, INVESTORS, WindowEvidenceError,
    _rows, _market_date, _financial_row, _decimal,
)

VERSION = "tpex-institutional-window/chips-1006-v1"
SUMMARY_SCHEMA = "tpex-institutional-window-summary/chips-1006-v1"
CAPTURE_SCHEMA = "tpex-institutional-memory-capture/chips-1006-v1"
CALENDAR_SCHEMA = "tpex-observed-calendar/chips-1006-v1"
POLICY_VERSION = "m1-chips-cutoff-tpex-2026-10-06.1"
PROFILE = "free_public_local"
CALENDAR_VERSION = "tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1"
CALCULATION_VERSION = "independent-net-sum/expected-session-inclusive-v1"
DAILY_SOURCE_ID = "tpex_government_institutional_csv"
INDEX_SOURCE_ID = "tpex_government_index_csv"
DAILY_BASE_URL = "https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data"
INDEX_BASE_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data"
START, CUTOFF = date(2026, 9, 1), date(2026, 10, 6)
SYMBOLS = ("3105", "6488")
CLOSED_DATES = (date(2026, 9, 25), date(2026, 9, 28))
MONTH_REQUESTS = (date(2026, 9, 1), date(2026, 10, 1))
# The complete positive set accepted by the coordinator, not an inferred list.
EXPECTED_SESSIONS = tuple(date.fromisoformat("2026-" + value) for value in (
    "09-01", "09-02", "09-03", "09-04", "09-07", "09-08", "09-09", "09-10",
    "09-11", "09-14", "09-15", "09-16", "09-17", "09-18", "09-21", "09-22",
    "09-23", "09-24", "09-29", "09-30", "10-01", "10-02", "10-05", "10-06",
))
WINDOW_DATES = {horizon: EXPECTED_SESSIONS[-horizon:] for horizon in (5, 20)}
DAILY_REQUESTS = WINDOW_DATES[20]
MAX_DAILY_BYTES, MAX_INDEX_BYTES = 2 * 1024 * 1024, 1024 * 1024
MAX_TOTAL_BYTES, MAX_REQUESTS = 42 * 1024 * 1024, 22
TIMEOUT_SECONDS, BATCH_DEADLINE_SECONDS = 15.0, 180.0
MAX_RETAINED_ESTIMATE_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_HEADER_BYTES = 16 * 1024


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise WindowEvidenceError(reason)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


_POLICY = {
    "version": POLICY_VERSION, "profile": PROFILE,
    "summary_schema": SUMMARY_SCHEMA, "capture_schema": CAPTURE_SCHEMA,
    "scope": {"exchange": "TPEx", "symbols": list(SYMBOLS), "supported_cutoffs": [CUTOFF.isoformat()],
              "calendar_from": START.isoformat(), "calendar_to": CUTOFF.isoformat(),
              "financial_dates": [day.isoformat() for day in DAILY_REQUESTS], "selection": "explicit_requested_as_of_only"},
    "sources": {
        DAILY_SOURCE_ID: {"source_version": "dataset-11856-dated-csv-observed-2026-10-07/chips-v1",
                          "government_dataset": "https://data.gov.tw/dataset/11856", "exact_url": DAILY_BASE_URL,
                          "method": "GET", "date_parameter": "d=ROC_YYY/MM/DD", "header": list(DAILY_HEADER),
                          "max_body_bytes": MAX_DAILY_BYTES,
                          "purposes": {"local_fetch": "admitted", "raw_store": "admitted", "summarize": "admitted", "historical_pit": "unsupported"}},
        INDEX_SOURCE_ID: {"source_version": "dataset-11391-month-csv-observed-2026-10-07/chips-v1",
                          "government_dataset": "https://data.gov.tw/dataset/11391", "exact_url": INDEX_BASE_URL,
                          "method": "GET", "date_parameter": "date=YYYY/MM/01", "header": list(INDEX_HEADER),
                          "max_body_bytes": MAX_INDEX_BYTES, "row_validation_scope": "all_returned_month_rows",
                          "calendar_adoption": "all_24_observed_rows; post_cutoff_rows_rejected",
                          "purposes": {"local_fetch": "admitted", "raw_store": "admitted", "summarize": "admitted", "historical_pit": "unsupported"}},
    },
    "calendar": {"schema_version": CALENDAR_SCHEMA, "version": CALENDAR_VERSION,
                 "weekday_rule": "https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html",
                 "closed_notice": "https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html",
                 "closed_dates": [day.isoformat() for day in CLOSED_DATES],
                 "expected_sessions": [day.isoformat() for day in EXPECTED_SESSIONS],
                 "completeness": "full_observed_month_rows_equal_explicit_bounded_expected_sessions"},
    "execution": {"max_requests": MAX_REQUESTS, "max_total_bytes": MAX_TOTAL_BYTES,
                  "timeout_seconds": TIMEOUT_SECONDS, "batch_deadline_seconds": BATCH_DEADLINE_SECONDS,
                  "deadline_scope": "checked_at_response_and_chunk_boundaries; timeout_at_request_start_min_15_seconds_remaining; not_OS_preemption",
                  "max_response_header_bytes": MAX_RESPONSE_HEADER_BYTES,
                  "retries": 0, "redirects": 0, "storage": "process_memory",
                  "max_retained_graph_estimate_bytes": MAX_RETAINED_ESTIMATE_BYTES,
                  "numeric_rate_limit": "unknown", "historical_pit": "unsupported"},
    "attribution": {"source_owner": "Taipei Exchange (TPEx)", "license": "Government Data Open License v1.0",
                    "license_url": "https://data.gov.tw/license",
                    "access_basis": "government-linked resources; TPEx disclaimer section 7 open-platform exception; checked exact queries only"},
    "statistical_basis": {"description": "original trade executions, before broker account corrections",
                          "documentation": "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html",
                          "download_revision_guarantee": "unknown"},
}
# Independently reviewed external pin; never calculated as the expected pin.
POLICY_DIGEST = "sha256:36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5"


def window_policy() -> dict:
    return copy.deepcopy(_POLICY)


def retained_graph_estimate(value: Any) -> int:
    """Deduplicated sys.getsizeof graph estimate; neither RSS nor peak memory."""
    seen: set[int] = set()
    def size(item):
        if id(item) in seen:
            return 0
        seen.add(id(item))
        total = sys.getsizeof(item)
        if isinstance(item, Mapping):
            return total + sum(size(key) + size(child) for key, child in item.items())
        if isinstance(item, (tuple, list, set, frozenset)):
            return total + sum(size(child) for child in item)
        if isinstance(item, CapturedCSV1006):
            return total + size(vars(item))
        return total
    return size(value)


def _check_policy(policy, profile, version, digest):
    _require(profile == PROFILE and version == POLICY_VERSION, "chips_policy_version_or_profile_mismatch")
    _require(digest == POLICY_DIGEST, "chips_policy_digest_mismatch")
    try:
        _require(isinstance(policy, Mapping) and canonical_bytes(policy) == canonical_bytes(_POLICY)
                 and _digest(policy) == digest, "chips_policy_digest_mismatch")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, WindowEvidenceError):
            raise
        raise WindowEvidenceError("chips_policy_invalid") from exc


def source_url(source_id: str, requested_date: date) -> str:
    _require(type(requested_date) is date, "chips_request_date_invalid")
    if source_id == DAILY_SOURCE_ID:
        _require(requested_date in DAILY_REQUESTS, "chips_daily_request_outside_scope")
        return DAILY_BASE_URL + "&" + urlencode({"d": f"{requested_date.year - 1911:03d}/{requested_date.month:02d}/{requested_date.day:02d}"})
    _require(source_id == INDEX_SOURCE_ID and requested_date in MONTH_REQUESTS, "chips_index_request_outside_scope")
    return INDEX_BASE_URL + "&" + urlencode({"date": requested_date.strftime("%Y/%m/%d")})


@dataclass(frozen=True)
class CapturedCSV1006:
    source_id: str
    requested_date: date
    url: str
    body: bytes
    body_sha256: str
    request_started_at: datetime
    captured_at: datetime
    policy_version: str
    policy_digest: str
    profile: str
    source_version: str
    http_status: int = 200
    content_type: str = "application/csv;charset=utf-8"
    method: str = "GET"
    content_encoding: str = "identity"

    def receipt(self) -> dict:
        _shape(self)
        return {"schema_version": CAPTURE_SCHEMA, "source_id": self.source_id, "source_version": self.source_version,
                "requested_date": self.requested_date.isoformat(), "url": self.url, "method": self.method,
                "body_sha256": self.body_sha256, "body_bytes": len(self.body),
                "request_started_at": self.request_started_at.isoformat(), "captured_at": self.captured_at.isoformat(),
                "policy_version": self.policy_version, "policy_digest": self.policy_digest, "profile": self.profile,
                "http_status": self.http_status, "content_type": self.content_type, "content_encoding": self.content_encoding,
                "storage": "process_memory", "published_time": "unknown", "first_available_time": "unknown",
                "revision_time": "unknown", "historical_pit": "unsupported", "request_count": 1}


def _shape(capture):
    _require(type(capture) is CapturedCSV1006, "chips_capture_type_invalid")
    _require(type(capture.requested_date) is date and type(capture.body) is bytes, "chips_capture_body_or_date_type_invalid")
    _require(all(type(value) is str for value in (capture.source_id, capture.url, capture.body_sha256,
             capture.policy_version, capture.policy_digest, capture.profile, capture.source_version,
             capture.content_type, capture.method, capture.content_encoding)), "chips_capture_metadata_type_invalid")
    _require(type(capture.http_status) is int, "chips_capture_http_status_invalid")
    for instant in (capture.request_started_at, capture.captured_at):
        _require(type(instant) is datetime and type(instant.tzinfo) is timezone
                 and instant.utcoffset() == timedelta(0), "chips_capture_timestamp_not_utc")


def _checked_capture(capture):
    _shape(capture)
    _require(capture.url == source_url(capture.source_id, capture.requested_date) and capture.method == "GET", "chips_capture_url_or_method_mismatch")
    _require(capture.policy_version == POLICY_VERSION and capture.policy_digest == POLICY_DIGEST and capture.profile == PROFILE,
             "chips_capture_policy_mismatch")
    _require(capture.source_version == _POLICY["sources"][capture.source_id]["source_version"], "chips_capture_source_version_mismatch")
    limit = MAX_DAILY_BYTES if capture.source_id == DAILY_SOURCE_ID else MAX_INDEX_BYTES
    _require(0 < len(capture.body) <= limit, "chips_capture_body_size_limit")
    _require(capture.body_sha256 == hashlib.sha256(capture.body).hexdigest(), "chips_capture_body_hash_mismatch")
    _require(200 <= capture.http_status < 300, "chips_capture_http_status_invalid")
    _require(capture.content_encoding.lower().strip() in {"", "identity"}, "chips_capture_content_encoding_invalid")
    parts = [part.strip().lower() for part in capture.content_type.split(";")]
    _require(parts[0] in {"application/csv", "text/csv"} and all(part in {"charset=utf-8", 'charset="utf-8"'} for part in parts[1:]),
             "chips_capture_content_type_invalid")
    _require(capture.request_started_at <= capture.captured_at, "chips_capture_timestamps_nonmonotonic")
    receipt = capture.receipt()
    receipt.update(receipt_sha256=_digest(receipt), verification="local_evidence_consistent")
    return receipt


def _daily(capture):
    _require(capture.source_id == DAILY_SOURCE_ID, "chips_daily_source_mismatch")
    receipt = _checked_capture(capture)
    rows = _rows(capture.body, DAILY_HEADER)
    selected, seen = {}, set()
    for ordinal, row in enumerate(rows, 1):
        _require(_market_date(row[0], roc=True) == capture.requested_date, "chips_daily_payload_date_mismatch")
        _require(re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) is not None and row[1] not in seen, "chips_daily_code_invalid_or_duplicate")
        seen.add(row[1])
        _require(bool(row[2].strip()), "chips_daily_company_name_missing")
        if row[1] in SYMBOLS:
            selected[row[1]] = {**_financial_row(row, ordinal), "source_values": dict(zip(DAILY_HEADER, row))}
    _require(set(selected) == set(SYMBOLS), "chips_daily_selected_symbol_missing")
    receipt.update(candidate_count=len(rows), selected_count=2,
                   validation_scope="all_row_structure_dates_unique_codes_names; selected_two_all_22_financial_fields")
    return selected, receipt


def _index(capture):
    _require(capture.source_id == INDEX_SOURCE_ID, "chips_index_source_mismatch")
    receipt = _checked_capture(capture)
    selected, seen = {}, set()
    rows = _rows(capture.body, INDEX_HEADER)
    for ordinal, row in enumerate(rows, 1):
        day = _market_date(row[0], roc=False)
        _require(START <= day <= CUTOFF and (day.year, day.month) == (capture.requested_date.year, capture.requested_date.month),
                 "chips_index_date_outside_scope")
        _require(day not in seen, "chips_index_date_duplicate")
        seen.add(day)
        _require(day.weekday() < 5 and day not in CLOSED_DATES and day in EXPECTED_SESSIONS, "chips_index_closed_date_conflict")
        opening, high, low, close = (_decimal(value, positive=True) for value in row[1:5])
        _decimal(row[5], positive=False)
        _require(low <= min(opening, close) <= max(opening, close) <= high, "chips_index_ohlc_bounds_invalid")
        selected[day] = {"date": day.isoformat(), "row_ordinal": ordinal, "source_values": dict(zip(INDEX_HEADER, row)), "body_sha256": receipt["body_sha256"]}
    receipt.update(candidate_count=len(rows), adopted_count=len(selected), pre_calendar_row_count=0,
                   validation_scope="all_returned_month_rows")
    return selected, receipt


def _blank(reason: str, as_of: date | None = CUTOFF) -> dict:
    return {"schema_version": SUMMARY_SCHEMA, "version": VERSION, "status": "unavailable",
            "as_of": as_of.isoformat() if type(as_of) is date else None, "unit": "shares",
            "quantity_encoding": "canonical_integer_string", "historical_pit": "unsupported", "reasons": [reason],
            "calendar": {"schema_version": CALENDAR_SCHEMA, "version": CALENDAR_VERSION, "status": "unavailable", "reasons": [reason]},
            "stocks": {symbol: {"symbol": symbol, "windows": {str(horizon): {
                "status": "unavailable", "horizon": horizon, "values": None, "required_dates": [day.isoformat() for day in expected],
                "valid_dates": [], "missing_dates": [day.isoformat() for day in expected], "invalid_dates": [], "reasons": [reason],
            } for horizon, expected in WINDOW_DATES.items()}} for symbol in SYMBOLS}}


def summarize_window_captures(captures: Sequence[CapturedCSV1006], *, policy: Mapping[str, Any], profile: str,
                              expected_policy_version: str, expected_policy_digest: str, as_of: date,
                              calendar_version: str, failures: Sequence[Mapping[str, Any]] = ()) -> dict:
    try:
        _check_policy(policy, profile, expected_policy_version, expected_policy_digest)
        _require(type(as_of) is date and as_of == CUTOFF, "chips_cutoff_not_supported")
        _require(calendar_version == CALENDAR_VERSION, "chips_calendar_version_not_supported")
        _require(not isinstance(captures, (str, bytes)) and len(captures) <= MAX_REQUESTS, "chips_capture_count_limit")
        for capture in captures:
            _shape(capture)
            _require(capture.source_id in {DAILY_SOURCE_ID, INDEX_SOURCE_ID}, "chips_source_not_supported")
        _require(sum(len(capture.body) for capture in captures) <= MAX_TOTAL_BYTES, "chips_capture_total_size_limit")
        _require(retained_graph_estimate((captures, policy, failures)) <= MAX_RETAINED_ESTIMATE_BYTES, "chips_retained_graph_size_limit")
    except (WindowEvidenceError, TypeError, ValueError, AttributeError) as exc:
        return _blank(str(exc) if isinstance(exc, WindowEvidenceError) else "chips_capture_input_invalid", as_of)
    grouped = {source: defaultdict(list) for source in (DAILY_SOURCE_ID, INDEX_SOURCE_ID)}
    for capture in captures:
        grouped[capture.source_id][capture.requested_date].append(capture)
    observed, calendar_evidence = {}, []
    try:
        _require(set(grouped[INDEX_SOURCE_ID]) == set(MONTH_REQUESTS), "chips_calendar_month_evidence_missing")
        for month in MONTH_REQUESTS:
            entries = grouped[INDEX_SOURCE_ID][month]
            _require(len(entries) == 1, "chips_calendar_competing_revision")
            days, receipt = _index(entries[0])
            _require(not set(days).intersection(observed), "chips_calendar_date_duplicate")
            observed.update(days)
            calendar_evidence.append(receipt)
        _require(set(observed) == set(EXPECTED_SESSIONS), "chips_calendar_expected_dates_missing")
    except (WindowEvidenceError, TypeError, ValueError, AttributeError) as exc:
        result = _blank(str(exc) if isinstance(exc, WindowEvidenceError) else "chips_calendar_evidence_invalid", as_of)
        result["calendar"].update(expected_dates=[day.isoformat() for day in EXPECTED_SESSIONS], valid_dates=[day.isoformat() for day in sorted(observed)],
                                  missing_dates=[day.isoformat() for day in EXPECTED_SESSIONS if day not in observed], evidence=calendar_evidence)
        result["failures"] = [dict(item) for item in failures]
        return result
    result = _blank("chips_institutional_evidence_missing", as_of)
    result.update(policy={"version": expected_policy_version, "digest": expected_policy_digest, "profile": profile},
                  scope=copy.deepcopy(_POLICY["scope"]), calculation_version=CALCULATION_VERSION,
                  verification="local_evidence_consistent", storage="process_memory",
                  published_time="unknown", first_available_time="unknown", revision_time="unknown",
                  attribution=copy.deepcopy(_POLICY["attribution"]), statistical_basis=copy.deepcopy(_POLICY["statistical_basis"]),
                  limitations=["bounded_calendar_and_two_selected_securities_only", "observation_not_publication_or_first_availability",
                               "data_date_retrospective_not_historical_pit", "no_strategy_condition_or_trend_calculation",
                               "no_disk_storage_or_cross_process_replay", "deadline_checked_at_http_boundaries_not_os_preemption"],
                  calendar={"schema_version": CALENDAR_SCHEMA, "version": CALENDAR_VERSION, "status": "available", "reasons": [],
                            "from": START.isoformat(), "to": CUTOFF.isoformat(), "basis": copy.deepcopy(_POLICY["calendar"]),
                            "expected_dates": [day.isoformat() for day in EXPECTED_SESSIONS], "valid_dates": [day.isoformat() for day in sorted(observed)],
                            "missing_dates": [], "rows": [observed[day] for day in sorted(observed)], "evidence": calendar_evidence})
    valid, invalid, receipts, errors = {}, {}, {}, [dict(item) for item in failures]
    for day, entries in grouped[DAILY_SOURCE_ID].items():
        try:
            _require(day in DAILY_REQUESTS, "chips_daily_date_outside_scope")
            _require(len(entries) == 1, "chips_daily_competing_revision")
            valid[day], receipts[day] = _daily(entries[0])
        except (WindowEvidenceError, TypeError, ValueError, AttributeError) as exc:
            invalid[day] = str(exc) if isinstance(exc, WindowEvidenceError) else "chips_daily_evidence_invalid"
            errors.append({"source_id": DAILY_SOURCE_ID, "requested_date": day.isoformat(), "reason": invalid[day]})
    for symbol in SYMBOLS:
        for horizon, expected in WINDOW_DATES.items():
            known, missing = [day for day in expected if day in valid], [day for day in expected if day not in valid]
            result["stocks"][symbol]["windows"][str(horizon)] = {
                "horizon": horizon, "status": "available" if not missing else "unavailable",
                "values": {key: str(sum(int(valid[day][symbol]["investors"][key]["net"]) for day in expected)) for key in INVESTORS} if not missing else None,
                "required_dates": [day.isoformat() for day in expected], "valid_dates": [day.isoformat() for day in known],
                "missing_dates": [day.isoformat() for day in missing], "invalid_dates": [{"date": day.isoformat(), "reason": invalid[day]} for day in expected if day in invalid],
                "from": expected[0].isoformat(), "to": expected[-1].isoformat(), "reasons": [] if not missing else ["chips_window_expected_dates_missing"],
                "daily_evidence": [{"row": valid[day][symbol], "provenance": receipts[day]} for day in known],
            }
    complete = all(day in valid for day in DAILY_REQUESTS)
    result.update(status="available" if complete else "unavailable", reasons=[] if complete else ["chips_window_expected_dates_missing"],
                  failures=errors, captured_versions=[capture.receipt() for capture in captures])
    estimate = retained_graph_estimate((captures, policy, failures, result))
    _require(estimate <= MAX_RETAINED_ESTIMATE_BYTES, "chips_retained_graph_size_limit")
    result["memory_estimate"] = {"bytes": estimate, "limit_bytes": MAX_RETAINED_ESTIMATE_BYTES, "basis": "deduplicated_sys_getsizeof_graph; not_RSS_or_peak"}
    return result


class MemoryWindowCache1006:
    def __init__(self, *, policy, profile, expected_policy_version, expected_policy_digest, clock=None):
        self._policy, self._profile = copy.deepcopy(policy), profile
        self._version, self._digest = expected_policy_version, expected_policy_digest
        self._clock = clock or time.monotonic
        self._captures: tuple[CapturedCSV1006, ...] = ()
        self._failures: list[dict] = []
        self._attempted, self._fatal = False, None
        self.request_count, self.elapsed_seconds = 0, 0.0

    @property
    def raw_captures(self):
        return self._captures

    def snapshot(self):
        if self._fatal or not self._attempted:
            return _blank(self._fatal or "chips_memory_capture_missing")
        result = summarize_window_captures(self._captures, policy=self._policy, profile=self._profile,
            expected_policy_version=self._version, expected_policy_digest=self._digest, as_of=CUTOFF,
            calendar_version=CALENDAR_VERSION, failures=self._failures)
        result["execution"] = {"request_count": self.request_count, "elapsed_seconds": self.elapsed_seconds,
                               "batch_deadline_seconds": BATCH_DEADLINE_SECONDS, "deadline_scope": _POLICY["execution"]["deadline_scope"]}
        return result

    def load(self, *, as_of: date, calendar_version: str, transport: Any = None):
        if self._attempted:
            return _blank("chips_window_load_already_attempted", as_of)
        self._attempted = True
        try:
            _check_policy(self._policy, self._profile, self._version, self._digest)
            _require(type(as_of) is date and as_of == CUTOFF, "chips_cutoff_not_supported")
            _require(calendar_version == CALENDAR_VERSION, "chips_calendar_version_not_supported")
        except WindowEvidenceError as exc:
            self._fatal = str(exc)
            return self.snapshot()
        import httpx
        started_batch = self._clock()
        deadline = started_batch + BATCH_DEADLINE_SECONDS
        captured, total_bytes = [], 0
        def remaining():
            seconds = deadline - self._clock()
            _require(seconds > 0, "chips_batch_deadline_exceeded")
            return min(TIMEOUT_SECONDS, seconds)
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
            for source_id, day in [(INDEX_SOURCE_ID, value) for value in MONTH_REQUESTS] + [(DAILY_SOURCE_ID, value) for value in DAILY_REQUESTS]:
                body, status, content_type, encoding = bytearray(), None, "", ""
                started = datetime.now(timezone.utc)
                url = source_url(source_id, day)
                reason = None
                try:
                    timeout = remaining()
                    _require(self.request_count < MAX_REQUESTS, "chips_request_count_limit")
                    self.request_count += 1
                    with client.stream("GET", url, timeout=timeout, headers={"Accept-Encoding": "identity", "User-Agent": "taiwan-stock-research/chips-1006-v1"}) as response:
                        remaining()
                        _require(sum(len(key) + len(value) + 4 for key, value in response.headers.raw) <= MAX_RESPONSE_HEADER_BYTES, "chips_response_header_size_limit")
                        status, content_type = response.status_code, response.headers.get("Content-Type", "")
                        encoding = response.headers.get("Content-Encoding", "identity")
                        _require(200 <= status < 300, "chips_http_status:" + str(status))
                        _require(encoding.lower().strip() in {"", "identity"}, "chips_capture_content_encoding_invalid")
                        limit = MAX_DAILY_BYTES if source_id == DAILY_SOURCE_ID else MAX_INDEX_BYTES
                        for chunk in response.iter_raw():
                            remaining()
                            _require(len(body) + len(chunk) <= limit and total_bytes + len(body) + len(chunk) <= MAX_TOTAL_BYTES, "chips_capture_body_or_total_size_limit")
                            body.extend(chunk)
                        remaining()
                    encoded = bytes(body)
                    candidate = CapturedCSV1006(source_id, day, url, encoded, hashlib.sha256(encoded).hexdigest(),
                        started, datetime.now(timezone.utc), self._version, self._digest, self._profile,
                        _POLICY["sources"][source_id]["source_version"], status, content_type, content_encoding=encoding)
                    captured.append(candidate)
                    total_bytes += len(encoded)
                    _require(retained_graph_estimate((captured, self._policy, self._failures)) <= MAX_RETAINED_ESTIMATE_BYTES, "chips_retained_graph_size_limit")
                    (_index if source_id == INDEX_SOURCE_ID else _daily)(candidate)
                except (WindowEvidenceError, httpx.HTTPError, ValueError, TypeError) as exc:
                    reason = str(exc) if isinstance(exc, WindowEvidenceError) else ("chips_request_timeout" if isinstance(exc, httpx.TimeoutException) else "chips_request_or_body_failed")
                    self._failures.append({"source_id": source_id, "requested_date": day.isoformat(), "url": url, "reason": reason,
                        "http_status": status, "observed_bytes": len(body), "observed_body_sha256": hashlib.sha256(body).hexdigest(),
                        "request_started_at": started.isoformat(), "captured_at": datetime.now(timezone.utc).isoformat()})
                if reason in {"chips_batch_deadline_exceeded", "chips_capture_body_or_total_size_limit", "chips_retained_graph_size_limit"}:
                    self._fatal = reason
                    break
                if source_id == INDEX_SOURCE_ID and day == MONTH_REQUESTS[-1]:
                    calendar = summarize_window_captures(captured, policy=self._policy, profile=self._profile,
                        expected_policy_version=self._version, expected_policy_digest=self._digest,
                        as_of=CUTOFF, calendar_version=CALENDAR_VERSION, failures=self._failures)
                    if calendar["calendar"]["status"] != "available":
                        break
        self._captures = tuple(captured)
        self.elapsed_seconds = max(0.0, self._clock() - started_batch)
        if self.elapsed_seconds >= BATCH_DEADLINE_SECONDS:
            self._fatal = "chips_batch_deadline_exceeded"
        return self.snapshot()
