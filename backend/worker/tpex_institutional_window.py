"""Bounded TPEx CSV evidence and exact institutional windows, held in memory.

Only ``MemoryWindowCache.load`` can make requests, and callers must explicitly
select the pinned policy/profile. ``summarize_window_captures`` and cache reads
never fetch, write, discover files, import the application, or infer closed days.
This contract covers two securities and seven retrospective data-date cutoffs;
observation time is not publication, first availability, or historical PIT.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

VERSION = "tpex-institutional-window/w7-v1"
POLICY_VERSION = "m1-w7-tpex-window-2026-10-05.1"
PROFILE = "free_public_local"
CALENDAR_VERSION = "tpex-2026-08-26_2026-10-02-weekdays-11503027221/v1"
CALCULATION_VERSION = "independent-net-sum/expected-session-inclusive-v1"
DAILY_SOURCE_ID = "tpex_government_institutional_csv"
INDEX_SOURCE_ID = "tpex_government_index_csv"
DAILY_BASE_URL = "https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data"
INDEX_BASE_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data"
START = date(2026, 8, 26)
CUTOFF = date(2026, 10, 2)
CUTOFFS = (date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1), CUTOFF)
SYMBOLS = ("3105", "6488")
CLOSED_DATES = (date(2026, 9, 25), date(2026, 9, 28))
MONTH_REQUESTS = (date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1))
MAX_DAILY_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 55 * 1024 * 1024
MAX_REQUESTS = 29
TIMEOUT_SECONDS = 15.0
MAX_DAILY_SHARES = 9223372036854775807
INVESTORS = ("foreign", "trust", "dealer")
INVESTOR_LABELS = {"foreign": "外資及陸資（不含外資自營商）", "trust": "投信", "dealer": "自營商"}
DAILY_HEADER = (
    "資料日期", "代號", "名稱",
    "外資及陸資不含外資自營商買進股數", "外資及陸資不含外資自營商賣出股數", "外資及陸資不含外資自營商買賣超股數",
    "外資自營商買進股數", "外資自營商賣出股數", "外資自營商買賣超股數",
    "外資及陸資買進股數", "外資及陸資賣出股數", "外資及陸資買賣超股數",
    "投信買進股數", "投信賣出股數", "投信買賣超股數",
    "自營商自行買賣買進股數", "自營商自行買賣賣出股數", "自營商自行買賣買賣超股數",
    "自營商避險買進股數", "自營商避險賣出股數", "自營商避險買賣超股數",
    "自營商買進股數", "自營商賣出股數", "自營商買賣超股數", "三大法人買賣超股數合計",
)
INDEX_HEADER = ("資料日期", "開市", "最高價", "最低價", "收市", "漲跌")
EXPECTED_SESSIONS = tuple(
    START + timedelta(days=offset)
    for offset in range((CUTOFF - START).days + 1)
    if (START + timedelta(days=offset)).weekday() < 5
    and START + timedelta(days=offset) not in CLOSED_DATES
)
WINDOW_DATES_BY_CUTOFF = {
    cutoff: {horizon: tuple(day for day in EXPECTED_SESSIONS if day <= cutoff)[-horizon:]
             for horizon in (5, 20)}
    for cutoff in CUTOFFS
}
WINDOW_DATES = WINDOW_DATES_BY_CUTOFF[CUTOFF]
DAILY_REQUESTS = EXPECTED_SESSIONS


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


_POLICY = {
    "version": POLICY_VERSION, "profile": PROFILE,
    "scope": {"exchange": "TPEx", "symbols": list(SYMBOLS), "supported_cutoffs": [day.isoformat() for day in CUTOFFS],
              "calendar_from": START.isoformat(), "calendar_to": CUTOFF.isoformat()},
    "sources": {
        DAILY_SOURCE_ID: {"source_version": "dataset-11856-dated-csv-observed-2026-10-05/v6",
                          "government_dataset": "https://data.gov.tw/dataset/11856", "exact_url": DAILY_BASE_URL,
                          "method": "GET", "date_parameter": "d=ROC_YYY/MM/DD", "header": list(DAILY_HEADER),
                          "max_body_bytes": MAX_DAILY_BYTES,
                          "purposes": {**{purpose: "admitted" for purpose in ("local_fetch", "raw_store", "summarize")},
                                       "historical_pit": "unsupported"}},
        INDEX_SOURCE_ID: {"source_version": "dataset-11391-month-csv-observed-2026-10-05/v5",
                          "government_dataset": "https://data.gov.tw/dataset/11391", "exact_url": INDEX_BASE_URL,
                          "method": "GET", "date_parameter": "date=YYYY/MM/01", "header": list(INDEX_HEADER),
                          "max_body_bytes": MAX_INDEX_BYTES,
                          "row_validation_scope": "all_returned_month_rows",
                          "calendar_adoption": "bounded_dates_only; pre_calendar_rows_validated_not_adopted",
                          "purposes": {**{purpose: "admitted" for purpose in ("local_fetch", "raw_store", "summarize")},
                                       "historical_pit": "unsupported"}},
    },
    "calendar": {"version": CALENDAR_VERSION,
                 "weekday_rule": "https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html",
                 "closed_notice": "https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html",
                 "closed_dates": [day.isoformat() for day in CLOSED_DATES],
                 "expected_sessions": [day.isoformat() for day in EXPECTED_SESSIONS],
                 "completeness": "bounded_expected_weekdays_minus_explicit_closures_and_positive_index_rows"},
    "execution": {"max_requests": MAX_REQUESTS, "max_total_bytes": MAX_TOTAL_BYTES,
                  "timeout_seconds": TIMEOUT_SECONDS, "retries": 0, "redirects": 0,
                  "storage": "process_memory", "numeric_rate_limit": "unknown", "historical_pit": "unsupported"},
    "attribution": {"source_owner": "Taipei Exchange (TPEx)", "license": "Government Data Open License v1.0",
                    "license_url": "https://data.gov.tw/license",
                    "access_basis": "government-linked resources; TPEx disclaimer section 7; only the checked queries"},
    "statistical_basis": {"description": "original trade executions, before broker account corrections",
                          "documentation": "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html",
                          "download_revision_guarantee": "unknown"},
}
# External pin for this reviewed policy version. Editing the policy cannot
# silently change the expected digest; a new policy needs explicit repinning.
POLICY_DIGEST = "sha256:4ef122b1cc391f9faa85bf72b3441d993a037ccd0a18a31afe2ae2f0e6986c90"


class WindowEvidenceError(ValueError):
    """A stable source/evidence reason, without local paths or OS error text."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise WindowEvidenceError(reason)


def window_policy() -> dict:
    """Return the independent policy; does not change the existing JSON registry."""
    return copy.deepcopy(_POLICY)


def _check_policy(policy: Mapping[str, Any], profile: str, version: str, digest: str) -> None:
    _require(profile == PROFILE, "policy_profile_not_supported")
    _require(version == POLICY_VERSION, "policy_version_mismatch")
    _require(digest == POLICY_DIGEST, "policy_digest_mismatch")
    _require(isinstance(policy, Mapping), "policy_required")
    try:
        _require(policy["version"] == version and policy["profile"] == profile, "policy_version_or_profile_mismatch")
        _require(set(policy["sources"]) == {DAILY_SOURCE_ID, INDEX_SOURCE_ID}, "policy_sources_not_supported")
        for source in policy["sources"].values():
            _require(all(source["purposes"].get(purpose) == "admitted"
                         for purpose in ("local_fetch", "raw_store", "summarize")), "policy_purpose_not_admitted")
        _require(_digest(policy) == digest, "policy_digest_mismatch")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, WindowEvidenceError):
            raise
        raise WindowEvidenceError("policy_invalid") from exc


def source_url(source_id: str, requested_date: date) -> str:
    """Only the two approved government URLs and bounded, observed query forms."""
    _require(type(requested_date) is date, "request_date_invalid")
    if source_id == DAILY_SOURCE_ID:
        _require(requested_date in DAILY_REQUESTS, "daily_request_outside_scope")
        value = f"{requested_date.year - 1911:03d}/{requested_date.month:02d}/{requested_date.day:02d}"
        return DAILY_BASE_URL + "&" + urlencode({"d": value})
    if source_id == INDEX_SOURCE_ID:
        _require(requested_date in MONTH_REQUESTS, "index_request_outside_scope")
        return INDEX_BASE_URL + "&" + urlencode({"date": requested_date.strftime("%Y/%m/%d")})
    raise WindowEvidenceError("source_not_supported")


@dataclass(frozen=True)
class CapturedCSV:
    """Immutable process-memory raw version and observation metadata.

    Offline construction verifies local consistency only. It cannot authenticate
    the claimed HTTP source, and synthetic captures are not source acceptance.
    """
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
    http_status: int = 200
    content_type: str = "application/csv;charset=utf-8"
    method: str = "GET"
    content_encoding: str = "identity"

    def receipt(self) -> dict:
        _capture_shape(self)
        return {"schema_version": "tpex-window-memory-capture/v1", "source_id": self.source_id,
                "source_version": _POLICY["sources"].get(self.source_id, {}).get("source_version"),
                "requested_date": self.requested_date.isoformat(), "url": self.url, "method": self.method,
                "body_sha256": self.body_sha256, "body_bytes": len(self.body),
                "request_started_at": self.request_started_at.isoformat(), "captured_at": self.captured_at.isoformat(),
                "policy_version": self.policy_version, "policy_digest": self.policy_digest, "profile": self.profile,
                "http_status": self.http_status, "content_type": self.content_type,
                "content_encoding": self.content_encoding, "storage": "process_memory",
                "published_time": "unknown", "first_available_time": "unknown", "revision_time": "unknown",
                "historical_pit": "unsupported", "request_count": 1}


def _capture_shape(capture: CapturedCSV) -> None:
    """Gate caller-controlled dataclass fields before grouping or formatting."""
    _require(type(capture) is CapturedCSV, "capture_type_invalid")
    _require(type(capture.requested_date) is date, "capture_request_date_invalid")
    _require(type(capture.body) is bytes, "capture_body_type_invalid")
    _require(all(type(value) is str for value in (capture.source_id, capture.url, capture.body_sha256,
             capture.policy_version, capture.policy_digest, capture.profile, capture.content_type,
             capture.method, capture.content_encoding)), "capture_metadata_type_invalid")
    _require(type(capture.http_status) is int, "capture_http_status_invalid")
    for instant in (capture.request_started_at, capture.captured_at):
        _require(type(instant) is datetime and type(instant.tzinfo) is timezone
                 and instant.utcoffset() == timedelta(0), "capture_timestamp_not_utc")


def _safe_observation(capture: CapturedCSV) -> dict:
    receipt = capture.receipt()
    try:
        if capture.url != source_url(capture.source_id, capture.requested_date):
            receipt["url"] = None
    except WindowEvidenceError:
        receipt["url"] = None
    return receipt


def _check_capture(capture: CapturedCSV) -> dict:
    _capture_shape(capture)
    expected_url = source_url(capture.source_id, capture.requested_date)
    _require(capture.url == expected_url and capture.method == "GET", "capture_url_or_method_mismatch")
    _require(capture.policy_version == POLICY_VERSION and capture.policy_digest == POLICY_DIGEST
             and capture.profile == PROFILE, "capture_policy_mismatch")
    _require(type(capture.body) is bytes, "capture_body_type_invalid")
    limit = MAX_DAILY_BYTES if capture.source_id == DAILY_SOURCE_ID else MAX_INDEX_BYTES
    _require(0 < len(capture.body) <= limit, "capture_body_size_limit")
    _require(capture.body_sha256 == hashlib.sha256(capture.body).hexdigest(), "capture_body_hash_mismatch")
    _require(type(capture.http_status) is int and 200 <= capture.http_status < 300, "capture_http_status_invalid")
    _require(capture.content_encoding.lower().strip() in {"", "identity"}, "capture_content_encoding_invalid")
    parts = [part.strip().lower() for part in capture.content_type.split(";")]
    _require(parts[0] in {"application/csv", "text/csv"}
             and all(part in {"charset=utf-8", 'charset="utf-8"'} for part in parts[1:]), "capture_content_type_invalid")
    for instant in (capture.request_started_at, capture.captured_at):
        _require(type(instant) is datetime and instant.utcoffset() == timedelta(0), "capture_timestamp_not_utc")
    _require(capture.request_started_at <= capture.captured_at, "capture_timestamps_nonmonotonic")
    receipt = capture.receipt()
    receipt.update(source_version=_POLICY["sources"][capture.source_id]["source_version"],
                   receipt_sha256=_digest(receipt), verification="local_evidence_consistent",
                   attribution={**_POLICY["attribution"],
                                "government_dataset": _POLICY["sources"][capture.source_id]["government_dataset"],
                                "source_url": expected_url})
    return receipt


def _rows(body: bytes, header: tuple[str, ...]) -> list[list[str]]:
    try:
        text = body.decode("utf-8", errors="strict")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise WindowEvidenceError("csv_encoding_or_structure_invalid") from exc
    _require(bool(rows) and tuple(rows[0]) == header, "csv_header_mismatch")
    _require(len(rows) > 1, "csv_data_rows_missing")
    _require(all(len(row) == len(header) for row in rows[1:]), "csv_column_count_mismatch")
    return rows[1:]


def _market_date(value: str, *, roc: bool) -> date:
    length = 7 if roc else 8
    _require(re.fullmatch(r"[0-9]{" + str(length) + r"}", value) is not None, "csv_date_invalid")
    try:
        year = int(value[:-4]) + (1911 if roc else 0)
        return date(year, int(value[-4:-2]), int(value[-2:]))
    except ValueError as exc:
        raise WindowEvidenceError("csv_date_invalid") from exc


def _shares(value: str, *, gross: bool = False) -> int:
    _require(len(value) <= 20 and re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value) is not None, "share_quantity_invalid")
    quantity = int(value)
    _require(abs(quantity) <= MAX_DAILY_SHARES, "share_quantity_outside_int64")
    _require(not gross or quantity >= 0, "negative_buy_or_sell")
    return quantity


def _financial_row(row: list[str], ordinal: int) -> dict:
    groups = {}
    for name, offset in (("foreign", 3), ("foreign_dealer", 6), ("foreign_total", 9), ("trust", 12),
                         ("dealer_self", 15), ("dealer_hedge", 18), ("dealer", 21)):
        values = (_shares(row[offset], gross=True), _shares(row[offset + 1], gross=True), _shares(row[offset + 2]))
        _require(values[2] == values[0] - values[1], "daily_net_mismatch:" + name)
        groups[name] = values
    _require(groups["foreign_total"] == tuple(a + b for a, b in zip(groups["foreign"], groups["foreign_dealer"])),
             "daily_foreign_components_mismatch")
    _require(groups["dealer"] == tuple(a + b for a, b in zip(groups["dealer_self"], groups["dealer_hedge"])),
             "daily_dealer_components_mismatch")
    total = _shares(row[24])
    _require(total == sum(groups[key][2] for key in INVESTORS), "daily_three_investor_total_mismatch")
    return {"symbol": row[1], "company_name": row[2], "date": _market_date(row[0], roc=True).isoformat(),
            "source_date": row[0], "row_ordinal": ordinal,
            "investors": {key: {"label": INVESTOR_LABELS[key], "buy": str(groups[key][0]),
                                "sell": str(groups[key][1]), "net": str(groups[key][2]),
                                "source_fields": dict(zip(("buy", "sell", "net"), DAILY_HEADER[offset:offset + 3]))}
                          for key, offset in (("foreign", 3), ("trust", 12), ("dealer", 21))},
            "total_net": str(total)}


def _daily(capture: CapturedCSV) -> tuple[dict, dict]:
    _require(capture.source_id == DAILY_SOURCE_ID, "daily_source_mismatch")
    receipt = _check_capture(capture)
    rows = _rows(capture.body, DAILY_HEADER)
    selected, seen = {}, set()
    for ordinal, row in enumerate(rows, 1):
        _require(_market_date(row[0], roc=True) == capture.requested_date, "daily_payload_date_mismatch")
        _require(re.fullmatch(r"[0-9A-Z]{4,6}", row[1]) is not None, "daily_security_code_invalid")
        _require(row[1] not in seen, "daily_security_code_duplicate")
        seen.add(row[1])
        _require(bool(row[2].strip()), "daily_company_name_missing")
        if row[1] in SYMBOLS:
            selected[row[1]] = _financial_row(row, ordinal)
    _require(set(selected) == set(SYMBOLS), "daily_selected_symbol_missing")
    receipt.update(candidate_count=len(rows), selected_count=2,
                   validation_scope="all_row_structure_dates_unique_codes_names; selected_two_all_financial_fields")
    return selected, receipt


def _decimal(value: str, *, positive: bool) -> Decimal:
    _require(bool(value) and len(value) <= 64 and value == value.strip(), "index_numeric_invalid")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise WindowEvidenceError("index_numeric_invalid") from exc
    _require(parsed.is_finite() and (not positive or parsed > 0), "index_numeric_invalid")
    return parsed


def _index(capture: CapturedCSV) -> tuple[dict, dict]:
    """Validate every returned monthly row before adopting the bounded dates."""
    _require(capture.source_id == INDEX_SOURCE_ID, "index_source_mismatch")
    receipt = _check_capture(capture)
    selected, seen, pre_calendar_count = {}, set(), 0
    rows = _rows(capture.body, INDEX_HEADER)
    for ordinal, row in enumerate(rows, 1):
        day = _market_date(row[0], roc=False)
        _require(day <= CUTOFF and (day.year, day.month) == (capture.requested_date.year, capture.requested_date.month),
                 "index_date_outside_scope")
        _require(day not in seen, "index_date_duplicate")
        seen.add(day)
        _require(day.weekday() < 5, "index_closed_date_conflict")
        opening, high, low, close = (_decimal(value, positive=True) for value in row[1:5])
        _decimal(row[5], positive=False)
        _require(low <= min(opening, close) <= max(opening, close) <= high, "index_ohlc_bounds_invalid")
        if day < START:
            _require(capture.requested_date == MONTH_REQUESTS[0], "index_date_outside_scope")
            pre_calendar_count += 1
            continue
        _require(day in EXPECTED_SESSIONS, "index_closed_date_conflict")
        selected[day] = {"date": day.isoformat(), "row_ordinal": ordinal, "source_values": dict(zip(INDEX_HEADER, row)),
                         "body_sha256": receipt["body_sha256"]}
    receipt.update(candidate_count=len(rows), adopted_count=len(selected),
                   pre_calendar_row_count=pre_calendar_count, validation_scope="all_returned_month_rows")
    return selected, receipt


def _blank(reason: str, as_of: date | None = CUTOFF) -> dict:
    dates = WINDOW_DATES_BY_CUTOFF.get(as_of, {}) if type(as_of) is date else {}
    return {"version": VERSION, "status": "unavailable", "as_of": as_of.isoformat() if type(as_of) is date else None, "unit": "shares",
            "quantity_encoding": "canonical_integer_string", "historical_pit": "unsupported", "reasons": [reason],
            "calendar": {"version": CALENDAR_VERSION, "status": "unavailable", "reasons": [reason]},
            "stocks": {symbol: {"symbol": symbol, "windows": {
                str(horizon): {"status": "unavailable", "horizon": horizon, "values": None,
                                "required_dates": [day.isoformat() for day in expected],
                                "valid_dates": [], "missing_dates": [day.isoformat() for day in expected],
                                "invalid_dates": [], "reasons": [reason]}
                for horizon, expected in dates.items()}} for symbol in SYMBOLS}}


def summarize_window_captures(
    captures: Sequence[CapturedCSV], *, policy: Mapping[str, Any], profile: str,
    expected_policy_version: str, expected_policy_digest: str, as_of: date,
    calendar_version: str, failures: Sequence[Mapping[str, Any]] = (),
) -> dict:
    """Revalidate immutable memory evidence; each horizon keeps its exact dates.

    A bad daily body invalidates that date for both selected securities. Other
    dates remain inspectable; missing dates never select earlier replacement
    rows. Any calendar defect rejects all horizons.
    """
    try:
        _check_policy(policy, profile, expected_policy_version, expected_policy_digest)
        _require(type(as_of) is date and as_of in CUTOFFS, "cutoff_not_supported")
        _require(calendar_version == CALENDAR_VERSION, "calendar_version_not_supported")
        _require(not isinstance(captures, (str, bytes)) and len(captures) <= MAX_REQUESTS, "capture_count_limit")
        for capture in captures:
            _capture_shape(capture)
        _require(sum(len(capture.body) for capture in captures) <= MAX_TOTAL_BYTES, "capture_total_size_limit")
        _require(all(capture.source_id in {DAILY_SOURCE_ID, INDEX_SOURCE_ID} for capture in captures), "source_not_supported")
    except (WindowEvidenceError, TypeError, AttributeError) as exc:
        return _blank(str(exc) if isinstance(exc, WindowEvidenceError) else "capture_input_invalid", as_of)
    window_dates = WINDOW_DATES_BY_CUTOFF[as_of]
    by_source = {source_id: defaultdict(list) for source_id in (DAILY_SOURCE_ID, INDEX_SOURCE_ID)}
    for capture in captures:
        by_source[capture.source_id][capture.requested_date].append(capture)
    observed, calendar_evidence = {}, []
    try:
        _require(set(by_source[INDEX_SOURCE_ID]) == set(MONTH_REQUESTS), "calendar_month_evidence_missing")
        for month in MONTH_REQUESTS:
            entries = by_source[INDEX_SOURCE_ID][month]
            _require(len(entries) == 1, "calendar_competing_revision")
            days, receipt = _index(entries[0])
            _require(not set(days).intersection(observed), "calendar_date_duplicate")
            observed.update(days)
            calendar_evidence.append(receipt)
        _require(set(observed) == set(EXPECTED_SESSIONS), "calendar_expected_dates_missing")
    except (WindowEvidenceError, TypeError, ValueError, AttributeError) as exc:
        result = _blank(str(exc) if isinstance(exc, WindowEvidenceError) else "calendar_evidence_invalid", as_of)
        result["calendar"].update(expected_dates=[day.isoformat() for day in EXPECTED_SESSIONS],
                                  valid_dates=[day.isoformat() for day in sorted(observed)],
                                  missing_dates=[day.isoformat() for day in EXPECTED_SESSIONS if day not in observed],
                                  evidence=calendar_evidence)
        result["failures"] = [dict(item) for item in failures]
        return result
    result = _blank("institutional_evidence_missing", as_of)
    result.update(policy={"version": expected_policy_version, "digest": expected_policy_digest, "profile": profile},
                  scope={"exchange": "TPEx", "symbols": list(SYMBOLS), "calendar_from": START.isoformat(),
                          "calendar_to": CUTOFF.isoformat(), "supported_cutoffs": [day.isoformat() for day in CUTOFFS]},
                  calculation_version=CALCULATION_VERSION, verification="local_evidence_consistent",
                  published_time="unknown", first_available_time="unknown", revision_time="unknown",
                  attribution=copy.deepcopy(_POLICY["attribution"]), storage="process_memory",
                  statistical_basis=copy.deepcopy(_POLICY["statistical_basis"]),
                  limitations=["bounded_calendar_and_two_selected_securities_only", "data_date_retrospective_not_historical_pit",
                               "observation_not_publication_or_first_availability", "source_authentication_not_proven",
                                "no_strategy_condition_or_trend_calculation", "no_cross_process_rate_limit",
                                "captured_versions_describe_full_batch_not_window_adoption"],
                  calendar={"version": CALENDAR_VERSION, "status": "available", "reasons": [],
                            "from": START.isoformat(), "to": CUTOFF.isoformat(),
                            "basis": copy.deepcopy(_POLICY["calendar"]),
                            "expected_dates": [day.isoformat() for day in EXPECTED_SESSIONS],
                            "valid_dates": [day.isoformat() for day in sorted(observed)], "missing_dates": [],
                            "rows": [observed[day] for day in sorted(observed)], "evidence": calendar_evidence})
    valid, invalid, receipts, errors = {}, {}, {}, [dict(item) for item in failures]
    for day, entries in by_source[DAILY_SOURCE_ID].items():
        try:
            _require(day in DAILY_REQUESTS, "daily_date_outside_scope")
            _require(len(entries) == 1, "daily_competing_revision")
            selected, receipt = _daily(entries[0])
            valid[day], receipts[day] = selected, receipt
        except (WindowEvidenceError, TypeError, ValueError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, WindowEvidenceError) else "daily_evidence_invalid"
            invalid[day] = reason
            errors.append({"source_id": DAILY_SOURCE_ID, "requested_date": day.isoformat(), "reason": reason,
                           "observations": [_safe_observation(capture) for capture in entries]})
    for symbol in SYMBOLS:
        for horizon, expected in window_dates.items():
            known = [day for day in expected if day in valid]
            missing = [day for day in expected if day not in valid]
            complete = not missing
            result["stocks"][symbol]["windows"][str(horizon)] = {
                "horizon": horizon, "status": "available" if complete else "unavailable",
                "values": {key: str(sum(int(valid[day][symbol]["investors"][key]["net"]) for day in expected))
                           for key in INVESTORS} if complete else None,
                "required_dates": [day.isoformat() for day in expected], "valid_dates": [day.isoformat() for day in known],
                "missing_dates": [day.isoformat() for day in missing],
                "invalid_dates": [{"date": day.isoformat(), "reason": invalid[day]} for day in expected if day in invalid],
                "from": expected[0].isoformat(), "to": expected[-1].isoformat(),
                "reasons": [] if complete else ["institutional_window_expected_dates_missing"],
                "daily_evidence": [{"row": valid[day][symbol], "provenance": receipts[day]} for day in known],
            }
    result.update(status="available" if all(day in valid for day in window_dates[20]) else "unavailable",
                  reasons=[] if all(day in valid for day in window_dates[20]) else ["institutional_window_expected_dates_missing"],
                  failures=errors, captured_versions=[_safe_observation(capture) for capture in captures])
    return result


class MemoryWindowCache:
    """One explicit load attempt, one immutable raw version, two cached symbols.

    The API can add its own nonblocking operation lock. No cache access initiates
    a request, and a failed load cannot fall back to an earlier successful load.
    """
    def __init__(self, *, policy: Mapping[str, Any], profile: str,
                 expected_policy_version: str, expected_policy_digest: str):
        self._policy = copy.deepcopy(policy)
        self._profile = profile
        self._version = expected_policy_version
        self._digest = expected_policy_digest
        self._captures: tuple[CapturedCSV, ...] = ()
        self._failures: list[dict] = []
        self._attempted = False
        self._fatal: str | None = None
        self.request_count = 0

    @property
    def raw_captures(self) -> tuple[CapturedCSV, ...]:
        return self._captures

    def snapshot(self, as_of: date = CUTOFF) -> dict:
        if self._fatal or not self._attempted:
            return _blank(self._fatal or "window_memory_capture_missing", as_of)
        return summarize_window_captures(self._captures, policy=self._policy, profile=self._profile,
                                         expected_policy_version=self._version, expected_policy_digest=self._digest,
                                         as_of=as_of, calendar_version=CALENDAR_VERSION, failures=self._failures)

    def get(self, exchange: str, symbol: str, as_of: date | None) -> dict:
        if exchange != "TPEx" or symbol not in SYMBOLS:
            return _blank("window_market_or_symbol_not_supported", as_of)
        if type(as_of) is not date or as_of not in CUTOFFS:
            return _blank("cutoff_not_supported", as_of)
        result = self.snapshot(as_of)
        result["stocks"] = {symbol: result["stocks"][symbol]}
        return result

    def load(self, *, as_of: date, calendar_version: str, transport: Any = None) -> dict:
        if self._attempted:
            return _blank("window_load_already_attempted", as_of)
        self._attempted = True
        try:
            _check_policy(self._policy, self._profile, self._version, self._digest)
            _require(type(as_of) is date and as_of in CUTOFFS, "cutoff_not_supported")
            _require(calendar_version == CALENDAR_VERSION, "calendar_version_not_supported")
        except WindowEvidenceError as exc:
            self._fatal = str(exc)
            return self.snapshot(as_of)
        import httpx  # HTTP is available only at the explicit load operation.

        captured, total_bytes = [], 0
        with httpx.Client(transport=transport, trust_env=False, follow_redirects=False, timeout=TIMEOUT_SECONDS) as client:
            for source_id, day in [(INDEX_SOURCE_ID, day) for day in MONTH_REQUESTS] + [
                    (DAILY_SOURCE_ID, day) for day in DAILY_REQUESTS]:
                url = source_url(source_id, day)
                started = datetime.now(timezone.utc)
                body = bytearray()
                status, content_type, content_encoding = None, "", ""
                reason = None
                try:
                    _require(self.request_count < MAX_REQUESTS, "request_count_limit")
                    self.request_count += 1
                    with client.stream("GET", url, headers={"Accept-Encoding": "identity",
                                                            "User-Agent": "taiwan-stock-research/tpex-window-w7"}) as response:
                        status = response.status_code
                        content_type = response.headers.get("Content-Type", "")
                        content_encoding = response.headers.get("Content-Encoding", "identity")
                        _require(200 <= status < 300, "http_status:" + str(status))
                        _require(content_encoding.lower().strip() in {"", "identity"}, "capture_content_encoding_invalid")
                        limit = MAX_DAILY_BYTES if source_id == DAILY_SOURCE_ID else MAX_INDEX_BYTES
                        for chunk in response.iter_raw():
                            _require(len(body) + len(chunk) <= limit, "capture_body_size_limit")
                            _require(total_bytes + len(body) + len(chunk) <= MAX_TOTAL_BYTES, "capture_total_size_limit")
                            body.extend(chunk)
                    observed = datetime.now(timezone.utc)
                    encoded = bytes(body)
                    candidate = CapturedCSV(source_id, day, url, encoded, hashlib.sha256(encoded).hexdigest(),
                                            started, observed, self._version, self._digest, self._profile,
                                            status, content_type, content_encoding=content_encoding)
                    captured.append(candidate)
                    total_bytes += len(encoded)
                    # Preserve a bounded invalid body/hash as evidence of the failed date.
                    (_index if source_id == INDEX_SOURCE_ID else _daily)(candidate)
                except (WindowEvidenceError, httpx.HTTPError, ValueError, TypeError) as exc:
                    reason = str(exc) if isinstance(exc, WindowEvidenceError) else (
                        "request_timeout" if isinstance(exc, httpx.TimeoutException) else "request_or_body_failed")
                    self._failures.append({"source_id": source_id, "requested_date": day.isoformat(), "url": url,
                                           "reason": reason, "http_status": status,
                                           "observed_bytes": len(body), "observed_body_sha256": hashlib.sha256(body).hexdigest(),
                                           "request_started_at": started.isoformat(),
                                           "captured_at": datetime.now(timezone.utc).isoformat(),
                                           "partial_body": not any(c.source_id == source_id and c.requested_date == day for c in captured)})
                if source_id == INDEX_SOURCE_ID and day == MONTH_REQUESTS[-1]:
                    check = summarize_window_captures(captured, policy=self._policy, profile=self._profile,
                                                      expected_policy_version=self._version, expected_policy_digest=self._digest,
                                                      as_of=as_of, calendar_version=CALENDAR_VERSION, failures=self._failures)
                    if check["calendar"]["status"] != "available":
                        break
                if reason == "capture_total_size_limit":
                    break
        self._captures = tuple(captured)
        result = self.snapshot(as_of)
        result["request_count"] = self.request_count
        return result
