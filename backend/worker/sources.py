from __future__ import annotations

import hashlib
import json
import math
import re
import time
from calendar import monthrange
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

import httpx

from app.config import OFFICIAL_MAX_BACKFILL_DAYS, RAW_DIR
from app.domain import ETF_CATEGORIES


class OfficialDataError(RuntimeError):
    """Raised when an official source cannot provide a trustworthy payload."""


@dataclass(frozen=True)
class EndpointSpec:
    name: str
    url: str
    layer: str
    notes: str


@dataclass(frozen=True)
class FetchedPayload:
    source: str
    endpoint: str
    payload: Any
    data_as_of: str | None
    collected_at: datetime
    payload_path: Path
    sha256: str


@dataclass(frozen=True)
class InstrumentRecord:
    symbol: str
    name: str
    market: str = "TW"
    exchange: str = "TWSE"
    instrument_type: str = "stock"
    etf_category: str | None = None
    listing_date: date | None = None
    industry: str | None = None
    status: str = "active"
    payload_sha256: str | None = None


@dataclass(frozen=True)
class BarRecord:
    symbol: str
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    turnover: float
    market: str = "TW"
    exchange: str = "TWSE"
    adj_close: float | None = None
    source: str = "official"
    data_as_of: str | None = None
    is_suspended: bool = False
    payload_sha256: str | None = None


@dataclass(frozen=True)
class ChipRecord:
    """One official same-day institutional/margin observation."""

    symbol: str
    trading_date: date
    foreign_buy: float | None = None
    trust_buy: float | None = None
    dealer_buy: float | None = None
    total_buy_sell: float | None = None
    margin_balance: float | None = None
    margin_change: float | None = None
    exchange: str = "TWSE"
    source: str = "official"
    data_as_of: str | None = None
    payload_sha256: str | None = None


@dataclass(frozen=True)
class ActionRecord:
    symbol: str
    action_date: date
    action_type: str
    cash_dividend: float | None = None
    stock_dividend_ratio: float | None = None
    split_ratio: float | None = None
    reference_price: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    exchange: str = "TWSE"
    payload_sha256: str | None = None


@dataclass(frozen=True)
class FundamentalRecord:
    symbol: str
    period_end: date
    fiscal_period: str
    announcement_date: date | None = None
    revenue: float | None = None
    eps: float | None = None
    roe: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    exchange: str = "TWSE"
    source: str = "mops_fundamental"
    payload_sha256: str | None = None


@dataclass(frozen=True)
class EventRecord:
    symbol: str
    event_date: date
    event_type: str
    title: str
    description: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    endpoint: str | None = None
    exchange: str = "TWSE"
    source: str = "mops_material_information"
    payload_sha256: str | None = None


@dataclass
class OfficialBatch:
    instruments: list[InstrumentRecord] = field(default_factory=list)
    bars: list[BarRecord] = field(default_factory=list)
    chips: list[ChipRecord] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
    fundamentals: list[FundamentalRecord] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    payloads: list[FetchedPayload] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_as_of: str | None = None
    # Dates for which the official endpoint explicitly reported no matching
    # market data.  This is deliberately separate from ``warnings``: a
    # verified non-trading day may be skipped, while a missing or wrong-date
    # payload must remain fail-closed.
    no_data_dates: list[date] = field(default_factory=list)
    # Event feeds are not necessarily date-scoped.  Keep their denominator
    # explicit instead of inferring coverage from the number of Event rows.
    # ``status`` may be complete, verified_empty, partial, unsupported, or
    # missing; verified/empty dates are the only dates counted as queried.
    event_coverage: dict[str, Any] = field(default_factory=dict)


def _merge_event_coverage(values: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge exchange event-feed audit without treating event rows as sessions."""

    items = [item for item in values if item]
    verified = sorted({
        str(day)
        for item in items
        for day in item.get("verified_dates", [])
    })
    empty = sorted({
        str(day)
        for item in items
        for day in item.get("empty_dates", [])
    })
    unsupported = sorted({
        str(day)
        for item in items
        for day in item.get("unsupported_dates", [])
    })
    partial = sorted({
        str(day)
        for item in items
        for day in item.get("partial_dates", [])
    })
    observed = sorted({
        str(day)
        for item in items
        for day in item.get("observed_event_dates", [])
    })
    if verified or empty:
        status = "complete" if not (unsupported or partial) else "partial"
    elif partial:
        status = "partial"
    elif unsupported:
        status = "unsupported"
    else:
        status = "missing"
    return {
        "status": status,
        "denominator": "date_scoped_event_queries",
        "verified_dates": verified,
        "empty_dates": empty,
        "unsupported_dates": unsupported,
        "partial_dates": partial,
        "observed_event_dates": observed,
        "sources": [item.get("source") for item in items if item.get("source")],
        "reason": "; ".join(
            str(item.get("reason")) for item in items if item.get("reason")
        ) or None,
    }


OFFICIAL_ENDPOINT_CATALOG = (
    EndpointSpec(
        name="twse_openapi",
        url="https://openapi.twse.com.tw/",
        layer="raw",
        notes="TWSE official OpenAPI catalog: https://openapi.twse.com.tw/v1/swagger.json",
    ),
    EndpointSpec(
        name="tpex_openapi",
        url="https://www.tpex.org.tw/openapi/",
        layer="raw",
        notes="TPEx official OpenAPI catalog: https://www.tpex.org.tw/openapi/swagger.json",
    ),
    EndpointSpec(
        name="twse_historical",
        url="https://www.twse.com.tw/exchangeReport/STOCK_DAY",
        layer="raw",
        notes="Official TWSE historical daily trading page/API used for month backfill.",
    ),
    EndpointSpec(
        name="twse_daily_history_all",
        url="https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
        layer="raw",
        notes="Official TWSE one-day all-security daily report used for bounded backfill.",
    ),
    EndpointSpec(
        name="twse_holiday_schedule",
        url="https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule",
        layer="raw",
        notes="Official TWSE holiday schedule used to avoid requesting known non-trading sessions.",
    ),
    EndpointSpec(
        name="tpex_historical",
        url="https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
        layer="raw",
        notes="Official TPEx dailyQuotes POST endpoint used for date backfill.",
    ),
    EndpointSpec(
        name="tpex_etf_allowlist",
        url="https://info.tpex.org.tw/api/etfFilter",
        layer="raw",
        notes="Official TPEx ETF message-center POST feed used as the ETF allowlist.",
    ),
)


TWSE_API = "https://openapi.twse.com.tw/v1"
TPEX_API = "https://www.tpex.org.tw/openapi/v1"
TWSE_HISTORY_API = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TWSE_INDEX_HISTORY_API = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_HISTORY_API = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"

TWSE_LISTED_ENDPOINT = f"{TWSE_API}/opendata/t187ap03_L"
TWSE_ETF_ENDPOINT = f"{TWSE_API}/opendata/t187ap47_L"
TWSE_NEW_LISTING_ENDPOINT = f"{TWSE_API}/company/newlisting"
TWSE_DAILY_ENDPOINT = f"{TWSE_API}/exchangeReport/STOCK_DAY_ALL"
# The official TWSE report exposes one day's all-security table.  It
# is used for bounded historical backfill so the collector does not issue a
# per-symbol request for every month of the universe.
TWSE_DAILY_HISTORY_ENDPOINT = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_HOLIDAY_ENDPOINT = f"{TWSE_API}/holidaySchedule/holidaySchedule"
TWSE_MI_INDEX_PAGE = "https://www.twse.com.tw/zh/trading/exchange/MI_INDEX.html"
TWSE_INDEX_ENDPOINT = f"{TWSE_API}/exchangeReport/MI_INDEX"
TWSE_ACTION_ENDPOINT = f"{TWSE_API}/exchangeReport/TWT48U_ALL"
TWSE_SUSPEND_ENDPOINT = f"{TWSE_API}/company/suspendListingCsvAndHtml"
TWSE_EVENT_ENDPOINT = f"{TWSE_API}/opendata/t187ap04_L"
TWSE_FUNDAMENTAL_ENDPOINT = f"{TWSE_API}/opendata/t187ap14_L"
TWSE_CHIP_ENDPOINT = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_MARGIN_ENDPOINT = f"{TWSE_API}/exchangeReport/MI_MARGN"
TWSE_MARGIN_HISTORY_ENDPOINT = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"

TPEX_LISTED_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap03_O"
TPEX_DAILY_ENDPOINT = f"{TPEX_API}/tpex_mainboard_daily_close_quotes"
# ETF classification is sourced from the official TPEx information-center
# allowlist, not inferred from the mixed quote feed.
TPEX_ETF_ENDPOINT = "https://info.tpex.org.tw/api/etfFilter"
TPEX_CHIP_ENDPOINT = f"{TPEX_API}/tpex_3insti_daily_trading"
TPEX_MARGIN_ENDPOINT = f"{TPEX_API}/tpex_mainboard_margin_balance"
TPEX_CHIP_HISTORY_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
TPEX_MARGIN_HISTORY_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/margin/balance"
# Kept as a catalog reference only.  The official ESB feed is deliberately
# not used to construct the listed/OTC universe.
TPEX_EMERGING_ENDPOINT = f"{TPEX_API}/tpex_esb_latest_statistics"
TPEX_ACTION_ENDPOINT = f"{TPEX_API}/tpex_exright_daily"
TPEX_SUSPEND_ENDPOINT = f"{TPEX_API}/tpex_spendi_today"
TPEX_SUSPEND_HISTORY_ENDPOINT = f"{TPEX_API}/tpex_spendi_history"
TPEX_EVENT_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap04_O"
TPEX_FUNDAMENTAL_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap14_O"


def fetch_json(
    url: str,
    *,
    timeout_seconds: float = 30.0,
    method: str = "GET",
    data: Any = None,
) -> Any:
    headers = {"User-Agent": "taiwan-stock-research/0.1"}
    retry_limit = 3
    redirect_retry_limit = 6
    for attempt in range(redirect_retry_limit):
        try:
            if method.upper() == "POST":
                response = httpx.post(url, data=data, timeout=timeout_seconds, headers=headers)
            else:
                response = httpx.get(url, timeout=timeout_seconds, headers=headers)
        except httpx.TransportError as exc:
            if attempt + 1 >= retry_limit:
                raise OfficialDataError(
                    f"official endpoint transport retry exhausted: {url}"
                ) from exc
            time.sleep(min(2.0, 0.25 * (2**attempt)))
            continue
        # TWSE's CDN has intermittently emitted a body-bearing 307 without a
        # Location header for the date-scoped MI_INDEX endpoint.  It is not a
        # usable redirect and must never be treated as a successful payload;
        # retry it as a bounded transient response so a later CDN edge can
        # return either the requested report or the explicit no-data JSON.
        retryable_redirect = response.status_code == 307 and not response.headers.get("location")
        if retryable_redirect and attempt >= 2 and url.startswith(TWSE_DAILY_HISTORY_ENDPOINT):
            # A short page warm-up gives TWSE's CDN a valid report context.  A
            # request made on the same Client then often receives the JSON
            # report even when the first edge response was a body-bearing 307.
            # The page itself is not ingested as market data.
            try:
                with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
                    client.get(TWSE_MI_INDEX_PAGE)
                    primed_response = client.get(url)
                if primed_response.status_code != 307 or primed_response.headers.get("location"):
                    response = primed_response
                    retryable_redirect = False
            except httpx.TransportError:
                pass
        if response.status_code == 429 or response.status_code >= 500 or retryable_redirect:
            status_retry_limit = redirect_retry_limit if retryable_redirect else retry_limit
            if attempt + 1 >= status_retry_limit:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise OfficialDataError(
                        f"official endpoint retry exhausted ({response.status_code}): {url}"
                    ) from exc
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(0.0, min(2.0, float(retry_after))) if retry_after else 0.25 * (2**attempt)
            except (TypeError, ValueError):
                delay = 0.25 * (2**attempt)
            time.sleep(delay)
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Non-retryable 4xx responses fail immediately, with the same
            # source-level exception as retry exhaustion so optional feeds can
            # be recorded as warnings without masking the main OHLCV batch.
            raise OfficialDataError(
                f"official endpoint rejected request ({response.status_code}): {url}"
            ) from exc
        try:
            return response.json()
        except ValueError as exc:
            raise OfficialDataError(f"official endpoint returned non-JSON: {url}") from exc
    raise OfficialDataError(f"official endpoint retry budget exhausted: {url}")


def _encode_payload(payload: Any) -> bytes:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OfficialDataError("official payload is not JSON serializable") from exc


def persist_raw_payload(
    source: str,
    endpoint: str,
    payload: Any,
    data_as_of: str | None = None,
    *,
    collected_at: datetime | None = None,
) -> Path:
    collected = collected_at or datetime.utcnow()
    encoded = _encode_payload(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    target_dir = RAW_DIR / source / collected.strftime("%Y/%m/%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest}.json"
    if not target.exists():
        target.write_bytes(encoded)
    metadata = target.with_suffix(".meta.json")
    if not metadata.exists():
        metadata.write_text(
            json.dumps(
                {
                    "source": source,
                    "endpoint": endpoint,
                    "sha256": digest,
                    "data_as_of": data_as_of,
                    "collected_at": collected.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return target


def capture_payload(
    source: str,
    endpoint: str,
    payload: Any,
    data_as_of: str | None = None,
    *,
    collected_at: datetime | None = None,
) -> FetchedPayload:
    collected = collected_at or datetime.utcnow()
    encoded = _encode_payload(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    path = persist_raw_payload(
        source,
        endpoint,
        payload,
        data_as_of,
        collected_at=collected,
    )
    return FetchedPayload(source, endpoint, payload, data_as_of, collected, path, digest)


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize official list, table, and fields/data JSON shapes."""

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    fields = payload.get("fields")
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, list) and isinstance(fields, list):
        return [
            {str(key): value for key, value in zip(fields, row)}
            for row in data
            if isinstance(row, (list, tuple))
        ]
    tables = payload.get("tables")
    if isinstance(tables, list):
        result: list[dict[str, Any]] = []
        for table in tables:
            if isinstance(table, dict):
                result.extend(_rows(table))
        return result
    for key in ("rows", "items", "result"):
        if isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
    return [payload]


def _table_arrays(payload: Any) -> list[tuple[list[str], list[Any]]]:
    """Preserve duplicate table headers for official multi-level reports."""

    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables")
    candidates = tables if isinstance(tables, list) else [payload]
    result: list[tuple[list[str], list[Any]]] = []
    for table in candidates:
        if not isinstance(table, dict):
            continue
        fields = table.get("fields")
        data = table.get("data")
        if isinstance(fields, list) and isinstance(data, list):
            result.extend(
                (
                    [str(field) for field in fields],
                    list(row),
                )
                for row in data
                if isinstance(row, (list, tuple))
            )
    return result


def _text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text_value = str(value).strip().replace(",", "")
    if not text_value or text_value in {"--", "-", "X", "N/A", "無"}:
        return None
    text_value = text_value.replace("＋", "+").replace("－", "-")
    if text_value.startswith("(") and text_value.endswith(")"):
        text_value = "-" + text_value[1:-1]
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text_value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_integer(value: Any) -> int | None:
    number = parse_number(value)
    return int(number) if number is not None else None


def parse_roc_date(value: Any) -> date | None:
    if value is None:
        return None
    text_value = str(value).strip().replace("-", "/")
    if not text_value:
        return None
    parts = text_value.split("/")
    try:
        if len(parts) == 3:
            year, month, day = (int(part) for part in parts)
        else:
            digits = re.sub(r"\D", "", text_value)
            if len(digits) == 8:
                year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
            elif len(digits) == 7:
                year, month, day = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:])
            else:
                return None
        if year < 1000:
            year += 1911
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


def _require_reported_date(payload: Any, requested_date: date, endpoint: str) -> None:
    """Reject date-report responses that silently fall back to the latest day."""

    if isinstance(payload, list) and not payload:
        # TPEx may return an empty list for a weekday with no historical
        # quote rows; its caller applies the range-level no-prior-session
        # guard.  A non-empty list still lacks a report date and fails below.
        return
    if not isinstance(payload, dict):
        raise OfficialDataError(
            f"official date report omitted its reported date: {endpoint}"
        )
    reported_value = None
    for key in ("date", "reportedDate", "reported_date", "tradeDate", "tradingDate"):
        if payload.get(key) not in (None, ""):
            reported_value = payload.get(key)
            break
    if reported_value in (None, ""):
        raise OfficialDataError(
            f"official date report omitted its reported date: {endpoint}"
        )
    reported_date = parse_roc_date(reported_value)
    if reported_date != requested_date:
        raise OfficialDataError(
            f"official date report mismatch for {endpoint}: "
            f"requested {requested_date.isoformat()}, reported {reported_value}"
        )


def _has_tabular_rows(payload: Any) -> bool:
    """Detect actual report rows without treating a wrapper dict as a row."""

    if isinstance(payload, list):
        return any(isinstance(row, (dict, list, tuple)) for row in payload)
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if isinstance(data, list) and data:
        return True
    tables = payload.get("tables")
    if isinstance(tables, list):
        for table in tables:
            if isinstance(table, dict) and isinstance(table.get("data"), list) and table["data"]:
                return True
    for key in ("rows", "items", "result"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _is_twse_mi_index_no_data(payload: Any, endpoint: str) -> bool:
    """Recognize TWSE's explicit holiday/no-observation MI_INDEX response.

    MI_INDEX omits ``date`` for a response such as ``沒有符合條件的資料``.
    That exact no-row status is safe to skip for the requested session; an
    arbitrary date-less wrapper must still fail closed in ``_require_reported_date``.
    """

    if endpoint.split("?", 1)[0] != TWSE_DAILY_HISTORY_ENDPOINT:
        return False
    if not isinstance(payload, dict) or _has_tabular_rows(payload):
        return False
    status_text = " ".join(
        str(payload.get(key, ""))
        for key in ("stat", "status", "message", "msg", "error")
    ).lower()
    return any(
        marker in status_text
        for marker in (
            "\u6c92\u6709\u7b26\u5408\u689d\u4ef6\u7684\u8cc7\u6599",
            "no matching data",
            "no data",
        )
    )


def _date_from_row(row: dict[str, Any], *keys: str, default: date | None = None) -> date | None:
    return parse_roc_date(_text(row, *keys)) or default


def parse_suspended_symbols(payload: Any) -> set[str]:
    """Extract notice identifiers; the legacy name does not imply bar status.

    TPEx's current feed lists suspension/resumption announcements.  Symbol
    membership alone establishes neither an effective suspension interval nor
    a suspended bar, including when collection and bar dates match.
    """

    symbols: set[str] = set()
    for row in _rows(payload):
        symbol = _text(row, "SecuritiesCompanyCode", "Code", "Symbol", "霅隞??", "隞??")
        if symbol:
            symbols.add(symbol)
    return symbols


def _call_fetcher(
    fetcher: Callable[..., Any],
    url: str,
    *,
    method: str = "GET",
    data: Any = None,
) -> Any:
    try:
        return fetcher(url, method=method, data=data)
    except TypeError:
        # Fixture fetchers often expose a one-argument callable while the
        # production fetch_json also accepts a timeout keyword.
        try:
            return fetcher(url)
        except Exception as exc:
            raise OfficialDataError(f"official endpoint failed: {url}: {exc}") from exc
    except Exception as exc:
        raise OfficialDataError(f"official endpoint failed: {url}: {exc}") from exc


def normalize_etf_category(value: Any, *, symbol: str = "", name: str = "") -> str | None:
    """Map official ETF descriptions to the domain's finite category set.

    TWSE publishes a free-text fund type and TPEx publishes ETF identifiers
    and names rather than the application's canonical labels.  The mapping is
    deliberately conservative: an unrecognised non-empty description is
    classified as ``thematic`` (rather than persisted as an invalid label),
    while an absent description remains ``None`` and therefore fails closed in
    ``instrument_eligibility``.
    """

    text_value = " ".join(
        str(part).strip().lower()
        for part in (value, symbol, name)
        if part is not None and str(part).strip()
    )
    if not text_value:
        return None
    if any(token in text_value for token in ("inverse", "反向", "反1", "反二", "反三")):
        return "inverse"
    if any(token in text_value for token in ("leveraged", "槓桿", "正2", "正三", "2x", "3x")):
        return "leveraged"
    if any(token in text_value for token in ("bond", "債券", "債")):
        return "bond"
    if any(token in text_value for token in ("commodity", "商品", "黃金", "原油")):
        return "commodity"
    if any(token in text_value for token in ("dividend", "高股息", "股息", "配息")):
        return "dividend"
    if any(token in text_value for token in ("sector", "產業", "類股")):
        return "sector"
    if any(token in text_value for token in ("broad", "market", "大盤", "台灣50", "0050", "指數")):
        return "broad_market"
    if "etf" in text_value or symbol.strip().upper().startswith("00"):
        return "thematic"
    return "thematic" if any(category in text_value for category in ETF_CATEGORIES) else "thematic"


def _is_recent_listing(as_of: date, listing_date: date | None, window_days: int = 60) -> bool:
    if listing_date is None:
        return False
    age = (as_of - listing_date).days
    return 0 <= age <= window_days


def is_tpex_etf_code(symbol: str, name: str = "") -> bool:
    upper = symbol.strip().upper()
    if "ETF" in name.upper() or "指數股票型基金" in name or "交易所交易基金" in name:
        return True
    # TPEx documents ETF suffixes for foreign-currency, futures, active and
    # bond ETFs.  Numeric TWSE ETFs are identified from t187ap47_L instead.
    return len(upper) >= 5 and upper.startswith("00") and upper[-1].isalpha() and upper[-1] in {
        "A",
        "C",
        "D",
        "K",
        "T",
        "U",
    }


def _is_tpex_non_scope_product(symbol: str, name: str) -> bool:
    """Reject products outside the listed/OTC stock + ETF research scope."""

    normalized = f"{symbol} {name}".lower()
    if symbol.isdigit() and len(symbol) > 5:
        # Six-digit numeric quote codes are warrants/structured products in
        # the mixed TPEx daily table, not company stock identifiers.
        return True
    return any(
        token in normalized
        for token in (
            "etn",
            "權證",
            "認購",
            "認售",
            "牛熊證",
            "可轉換債",
            "公司債",
            "興櫃",
        )
    )


def _month_starts(start: date, end: date) -> list[date]:
    cursor = date(start.year, start.month, 1)
    result: list[date] = []
    while cursor <= end:
        result.append(cursor)
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return result


def _weekday_dates(start: date, end: date) -> Iterable[date]:
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            yield cursor
        cursor += timedelta(days=1)


def _official_non_trading_dates(payload: Any, start: date, end: date) -> set[date]:
    """Return only dates the official calendar explicitly marks closed."""

    result: set[date] = set()
    closed_markers = (
        "\u653e\u5047",  # holiday
        "\u7121\u4ea4\u6613",  # no trading
        "\u4f11\u5e02",  # market closed
    )
    for row in _rows(payload):
        holiday_date = _date_from_row(row, "Date", "\u65e5\u671f")
        if holiday_date is None or not start <= holiday_date <= end:
            continue
        text = " ".join(
            str(row.get(key, ""))
            for key in ("Name", "Description", "\u540d\u7a31", "\u8aaa\u660e")
        )
        if any(marker in text for marker in closed_markers):
            result.add(holiday_date)
    return result


def _ensure_backfill_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start date must not be after end date")
    if (end - start).days > OFFICIAL_MAX_BACKFILL_DAYS:
        raise ValueError(f"official backfill is limited to {OFFICIAL_MAX_BACKFILL_DAYS} days")


def parse_twse_daily_rows(payload: Any, *, data_as_of: str | None = None, payload_sha256: str | None = None) -> list[BarRecord]:
    result: list[BarRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "Code", "證券代號", "股票代號")
        trading_date = _date_from_row(row, "Date", "日期")
        open_price = parse_number(_text(row, "OpeningPrice", "開盤價", "開盤"))
        high = parse_number(_text(row, "HighestPrice", "最高價", "最高"))
        low = parse_number(_text(row, "LowestPrice", "最低價", "最低"))
        close = parse_number(_text(row, "ClosingPrice", "收盤價", "收盤"))
        volume = parse_integer(_text(row, "TradeVolume", "成交股數", "成交量"))
        turnover = parse_number(_text(row, "TradeValue", "成交金額", "成交值"))
        if not symbol or not trading_date or None in {open_price, high, low, close, volume}:
            continue
        result.append(
            BarRecord(
                symbol=symbol,
                trading_date=trading_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                adj_close=close,
                volume=volume,
                turnover=turnover or 0.0,
                exchange="TWSE",
                source="twse",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_tpex_daily_rows(payload: Any, *, data_as_of: str | None = None, payload_sha256: str | None = None) -> list[BarRecord]:
    result: list[BarRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "SecuritiesCompanyCode", "證券代號", "代號")
        trading_date = _date_from_row(row, "Date", "資料日期", "日期", default=parse_roc_date(data_as_of))
        open_price = parse_number(_text(row, "Open", "開盤"))
        high = parse_number(_text(row, "High", "最高"))
        low = parse_number(_text(row, "Low", "最低"))
        close = parse_number(_text(row, "Close", "收盤"))
        volume = parse_integer(_text(row, "TradingShares", "成交股數", "成交量"))
        turnover = parse_number(_text(row, "TransactionAmount", "成交金額", "成交金額(元)", "成交值"))
        if not symbol or not trading_date or None in {open_price, high, low, close, volume, turnover}:
            continue
        result.append(
            BarRecord(
                symbol=symbol,
                trading_date=trading_date,
                open=open_price,
                high=high,
                low=low,
                close=close,
                adj_close=close,
                volume=volume,
                turnover=turnover,
                exchange="TPEx",
                source="tpex",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value).strip().lower())


def _number_from_row(
    row: dict[str, Any],
    *,
    exact_keys: tuple[str, ...] = (),
    contains: tuple[tuple[str, ...], ...] = (),
) -> float | None:
    for key in exact_keys:
        value = parse_number(row.get(key))
        if value is not None:
            return value
    normalized = {
        _normalized_field_name(key): value
        for key, value in row.items()
    }
    for required_tokens in contains:
        for key, value in normalized.items():
            if all(_normalized_field_name(token) in key for token in required_tokens):
                parsed = parse_number(value)
                if parsed is not None:
                    return parsed
    return None


def parse_twse_institutional_rows(
    payload: Any,
    *,
    trading_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[ChipRecord]:
    """Parse T86 net institutional flow, excluding foreign dealers."""

    result: list[ChipRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "Code", "股票代號", "證券代號", "霅隞??")
        if not symbol:
            continue
        foreign_buy = _number_from_row(
            row,
            exact_keys=(
                "ForeignBuySellDifferenceExcludingForeignDealer",
                "ForeignInvestorsBuySellDifferenceExcludingDealer",
                "外陸資買賣超股數(不含外資自營商)",
            ),
            contains=(
                ("foreign", "difference", "excluding", "dealer"),
                ("外陸資", "買賣超", "不含", "外資自營商"),
            ),
        )
        trust_buy = _number_from_row(
            row,
            exact_keys=("InvestmentTrustBuySellDifference", "投信買賣超股數"),
            contains=(("investmenttrust", "difference"), ("投信", "買賣超")),
        )
        dealer_buy = _number_from_row(
            row,
            exact_keys=("DealerBuySellDifference", "DealersBuySellDifference", "自營商買賣超股數"),
            contains=(("dealer", "difference"), ("自營商", "買賣超")),
        )
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                foreign_buy=foreign_buy,
                trust_buy=trust_buy,
                dealer_buy=dealer_buy,
                exchange="TWSE",
                source="twse_t86",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_twse_margin_rows(
    payload: Any,
    *,
    trading_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[ChipRecord]:
    if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
        tables = payload["tables"]
        # MI_MARGN's first table is a summary; the individual security table
        # is table[1].  Its headers repeat for margin/short positions, so the
        # array positions (previous=5, current=6) are the stable contract.
        table = tables[1] if len(tables) > 1 else tables[0]
        table_rows = _table_arrays({"tables": [table]})
        margin_headers = {
            "marginpurchasebalancepreviousday",
            "marginpurchasebalance",
            "前日餘額",
            "今日餘額",
            "融資",
        }
        table_rows = [
            (fields, values)
            for fields, values in table_rows
            if any(
                any(token in field.lower() for token in margin_headers)
                for field in fields
            )
        ]
        if table_rows:
            result: list[ChipRecord] = []
            for _fields, values in table_rows:
                if len(values) < 7:
                    continue
                symbol = str(values[0]).strip() if values[0] is not None else ""
                if not symbol:
                    continue
                previous = parse_number(values[5])
                current = parse_number(values[6])
                result.append(
                    ChipRecord(
                        symbol=symbol,
                        trading_date=trading_date,
                        margin_balance=current,
                        margin_change=(current - previous) if current is not None and previous is not None else None,
                        exchange="TWSE",
                        source="twse_margin",
                        data_as_of=data_as_of or trading_date.isoformat(),
                        payload_sha256=payload_sha256,
                    )
                )
            return result
    result: list[ChipRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "Code", "股票代號", "證券代號", "霅隞??")
        if not symbol:
            continue
        previous = _number_from_row(
            row,
            exact_keys=("MarginPurchaseBalancePreviousDay", "融資前日餘額"),
            contains=(("marginpurchasebalancepreviousday",), ("融資", "前日", "餘額")),
        )
        current = _number_from_row(
            row,
            exact_keys=("MarginPurchaseBalance", "融資今日餘額"),
            contains=(("marginpurchasebalance",), ("融資", "今日", "餘額")),
        )
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                margin_balance=current,
                margin_change=(current - previous) if current is not None and previous is not None else None,
                exchange="TWSE",
                source="twse_margin",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_tpex_institutional_rows(
    payload: Any,
    *,
    trading_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[ChipRecord]:
    table_payload = payload
    if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
        table_payload = {"tables": payload["tables"][:1]}
    table_rows = _table_arrays(table_payload)
    if table_rows:
        result: list[ChipRecord] = []
        for _fields, values in table_rows:
            if len(values) < 24:
                continue
            symbol = str(values[0]).strip() if values[0] is not None else ""
            if not symbol:
                continue
            result.append(
                ChipRecord(
                    symbol=symbol,
                    trading_date=trading_date,
                    foreign_buy=parse_number(values[4]),
                    trust_buy=parse_number(values[13]),
                    dealer_buy=parse_number(values[22]),
                    total_buy_sell=parse_number(values[23]),
                    exchange="TPEx",
                    source="tpex_3insti",
                    data_as_of=data_as_of or trading_date.isoformat(),
                    payload_sha256=payload_sha256,
                )
            )
        return result
    result: list[ChipRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "SecuritiesCompanyCode", "Code", "股票代號", "證券代號", "代號")
        if not symbol:
            continue
        foreign_buy = _number_from_row(
            row,
            exact_keys=("ForeignBuySellDifference", "ForeignInvestorsDifference", "Foreign-BuySellDifference"),
            contains=(("foreign", "difference"), ("外資", "差額")),
        )
        trust_buy = _number_from_row(
            row,
            exact_keys=(
                "SecuritiesInvestmentTrustCompaniesDifference",
                "SecuritiesInvestmentTrustCompanies-BuySellDifference",
                "InvestmentTrustDifference",
            ),
            contains=(("securitiesinvestmenttrustcompanies", "difference"), ("investmenttrust", "difference"), ("投信", "差額")),
        )
        dealer_buy = _number_from_row(
            row,
            exact_keys=("DealersDifference", "DealerDifference"),
            contains=(("dealers", "difference"), ("dealer", "difference"), ("自營商", "差額")),
        )
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                foreign_buy=foreign_buy,
                trust_buy=trust_buy,
                dealer_buy=dealer_buy,
                exchange="TPEx",
                source="tpex_3insti",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_tpex_margin_rows(
    payload: Any,
    *,
    trading_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[ChipRecord]:
    # The historical TPEx margin report has a stable array layout.  Do not
    # turn the repeated/translated headers into a dict: the first and second
    # margin-balance values are positions 2 and 6 respectively.
    if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
        table_rows = _table_arrays({"tables": payload["tables"][:1]})
        if table_rows:
            result: list[ChipRecord] = []
            for _fields, values in table_rows:
                if len(values) < 7:
                    continue
                symbol = str(values[0]).strip() if values[0] is not None else ""
                if not symbol:
                    continue
                previous = parse_number(values[2])
                current = parse_number(values[6])
                result.append(
                    ChipRecord(
                        symbol=symbol,
                        trading_date=trading_date,
                        margin_balance=current,
                        margin_change=(current - previous) if current is not None and previous is not None else None,
                        exchange="TPEx",
                        source="tpex_margin",
                        data_as_of=data_as_of or trading_date.isoformat(),
                        payload_sha256=payload_sha256,
                    )
                )
            return result
    result: list[ChipRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "SecuritiesCompanyCode", "Code", "股票代號", "證券代號", "代號")
        if not symbol:
            continue
        previous = _number_from_row(
            row,
            exact_keys=("MarginPurchaseBalancePreviousDay", "前資餘額(張)"),
            contains=(("marginpurchasebalancepreviousday",), ("前資", "餘額")),
        )
        current = _number_from_row(
            row,
            exact_keys=("MarginPurchaseBalance", "資餘額"),
            contains=(("marginpurchasebalance",), ("資餘額",)),
        )
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                margin_balance=current,
                margin_change=(current - previous) if current is not None and previous is not None else None,
                exchange="TPEx",
                source="tpex_margin",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def merge_chip_records(
    institutional: Iterable[ChipRecord],
    margin: Iterable[ChipRecord],
    *,
    allowed_symbols: set[str],
    exchange: str,
) -> list[ChipRecord]:
    """Merge two official same-day feeds without filling missing fields."""

    merged: dict[tuple[str, date], ChipRecord] = {
        (record.symbol, record.trading_date): record
        for record in institutional
        if record.exchange == exchange and record.symbol in allowed_symbols
    }
    for record in margin:
        if record.exchange != exchange or record.symbol not in allowed_symbols:
            continue
        key = (record.symbol, record.trading_date)
        existing = merged.get(key)
        if existing:
            merged[key] = replace(
                existing,
                margin_balance=record.margin_balance,
                margin_change=record.margin_change,
                source=f"{existing.source}+{record.source}",
            )
        else:
            merged[key] = record
    return list(merged.values())


def parse_tpex_suspension_history_rows(
    payload: Any,
    *,
    allowed_symbols: set[str],
    endpoint: str,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[EventRecord]:
    """Normalize TPEx suspension/resumption intervals into auditable events."""

    rows = _rows(payload)
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = _text(row, "SecuritiesCompanyCode", "Code", "證券代號", "代號")
        if symbol and symbol in allowed_symbols:
            by_symbol.setdefault(symbol, []).append(row)

    linked_resumptions: dict[str, tuple[date, dict[str, Any]]] = {}
    for symbol, symbol_rows in by_symbol.items():
        # Count every input row for this identity, including invalid/empty dates.
        # Only a unique split pair can close an interval without guessing cycles.
        if len(symbol_rows) != 2:
            continue
        starts: list[date] = []
        resumptions: list[tuple[date, dict[str, Any]]] = []
        for row in symbol_rows:
            start_text = _text(row, "DateOfSuspendedTrading", "SuspendedTradingDate", "停牌日期")
            resume_text = _text(row, "DateOfResumedTrading", "ResumedTradingDate", "復牌日期")
            start_date = parse_roc_date(start_text)
            resume_date = parse_roc_date(resume_text)
            if start_date and not resume_text:
                starts.append(start_date)
            elif resume_date and not start_text:
                resumptions.append((resume_date, row))
        if len(starts) == 1 and len(resumptions) == 1 and starts[0] < resumptions[0][0]:
            linked_resumptions[symbol] = resumptions[0]

    result: list[EventRecord] = []
    for row in rows:
        # Serial is a row number, not a security identifier.
        symbol = _text(row, "SecuritiesCompanyCode", "Code", "證券代號", "代號")
        if not symbol or symbol not in allowed_symbols:
            continue
        suspended_date = _date_from_row(
            row,
            "DateOfSuspendedTrading",
            "SuspendedTradingDate",
            "停牌日期",
        )
        resumed_date = _date_from_row(
            row,
            "DateOfResumedTrading",
            "ResumedTradingDate",
            "復牌日期",
        )
        details = {
            "suspended_date": suspended_date.isoformat() if suspended_date else None,
            "resumed_date": resumed_date.isoformat() if resumed_date else None,
            "interval_end": resumed_date.isoformat() if resumed_date else None,
            "source_row": dict(row),
            "data_as_of": data_as_of,
        }
        if suspended_date:
            if symbol in linked_resumptions:
                interval_end, resumption_row = linked_resumptions[symbol]
                details.update(
                    resumed_date=interval_end.isoformat(),
                    interval_end=interval_end.isoformat(),
                    resumption_source_row=dict(resumption_row),
                )
            result.append(
                EventRecord(
                    symbol=symbol,
                    event_date=suspended_date,
                    event_type="suspension",
                    title="TPEx suspension interval",
                    description="Official TPEx suspension history; missing bars in this interval are non-comparable.",
                    details=details,
                    endpoint=endpoint,
                    exchange="TPEx",
                    source="tpex_suspension_history",
                    payload_sha256=payload_sha256,
                )
            )
        if resumed_date:
            result.append(
                EventRecord(
                    symbol=symbol,
                    event_date=resumed_date,
                    event_type="resumption",
                    title="TPEx resumption",
                    description="Official TPEx resumption date.",
                    details=details,
                    endpoint=endpoint,
                    exchange="TPEx",
                    source="tpex_suspension_history",
                    payload_sha256=payload_sha256,
                )
            )
    return result


def parse_twse_historical_payload(
    payload: Any,
    *,
    symbol: str,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[BarRecord]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        fields = payload.get("fields") or []
        rows = [
            {
                **{str(key): value for key, value in zip(fields, row)},
                # STOCK_DAY history is per-symbol and therefore omits the
                # symbol column.  Add it before passing through the common
                # parser; otherwise every historical row is discarded.
                "Code": symbol,
            }
            for row in payload["data"]
            if isinstance(row, (list, tuple))
        ]
        return parse_twse_daily_rows(rows, data_as_of=data_as_of, payload_sha256=payload_sha256)
    return parse_twse_daily_rows(payload, data_as_of=data_as_of, payload_sha256=payload_sha256)


def parse_twse_all_daily_payload(
    payload: Any,
    *,
    requested_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[BarRecord]:
    """Parse the official TWSE one-day all-security trading report.

    ``MI_INDEX`` wraps several unrelated tables.  Select the table carrying
    the security-code and daily OHLC fields, then inject the report date
    because that table does not repeat it on every row.
    """

    if not isinstance(payload, dict):
        return []
    report_date = parse_roc_date(payload.get("date")) or requested_date
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = {str(field) for field in table.get("fields", []) if field is not None}
        if not fields.intersection({"證券代號", "股票代號", "Code"}):
            continue
        rows = _rows(table)
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("Date", report_date.isoformat())
            normalized.append(item)
        parsed = parse_twse_daily_rows(
            normalized,
            data_as_of=data_as_of or report_date.isoformat(),
            payload_sha256=payload_sha256,
        )
        if parsed:
            return parsed
    return []


def parse_twse_taiex_from_all_daily_payload(
    payload: Any,
    *,
    requested_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[BarRecord]:
    """Parse the TAIEX row embedded in the date-scoped MI_INDEX report.

    MI_INDEX contains several summary tables before its security table.  The
    TAIEX row is the official daily benchmark in the first summary table, so
    using it avoids the retired monthly index page and keeps the benchmark on
    the same requested-date/provenance path as the security bars.
    """

    if not isinstance(payload, dict):
        return []
    report_date = parse_roc_date(payload.get("date"))
    if report_date != requested_date:
        return []

    # MI_INDEX has several tables with the same-looking first two columns.
    # In particular, the ``報酬指數`` table contains a similarly named row but
    # is not the price index used as the TAIEX benchmark.  Select the exact
    # official table and labels instead of relying on table order or a value
    # position.  Returning no row is deliberately fail-closed; callers treat
    # this as an unverified session and must not persist a guessed benchmark.
    price_table_title = "\u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)"
    index_label = "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578"
    close_label = "\u6536\u76e4\u6307\u6578"
    candidates: list[float] = []
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return []
    for table in tables:
        if not isinstance(table, dict):
            continue
        title = re.sub(r"\s+", "", str(table.get("title") or ""))
        # The report prefixes the title with a ROC date.  Strip only that
        # documented prefix; a different table name must not be accepted.
        title = re.sub(r"^\d{3,4}\u5e74\d{1,2}\u6708\d{1,2}\u65e5", "", title)
        if title != price_table_title:
            continue
        fields = [str(field) for field in table.get("fields", [])]
        if fields.count("\u6307\u6578") != 1 or fields.count(close_label) != 1:
            return []
        name_index = fields.index("\u6307\u6578")
        close_index = fields.index(close_label)
        data = table.get("data")
        if not isinstance(data, list):
            return []
        for values in data:
            if not isinstance(values, (list, tuple)):
                continue
            if max(name_index, close_index) >= len(values):
                continue
            if str(values[name_index]).strip() != index_label:
                continue
            close = parse_number(values[close_index])
            if close is None or not math.isfinite(close) or close <= 0:
                return []
            candidates.append(close)
    if len(candidates) != 1:
        return []
    close = candidates[0]
    return [
        BarRecord(
            symbol="TAIEX",
            trading_date=report_date,
            open=close,
            high=close,
            low=close,
            close=close,
            adj_close=close,
            volume=0,
            turnover=0.0,
            exchange="TWSE",
            source="twse_index",
            data_as_of=data_as_of or report_date.isoformat(),
            payload_sha256=payload_sha256,
        )
    ]


def parse_twse_taiex_from_index_payload(
    payload: Any,
    *,
    requested_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[BarRecord]:
    """Parse the date-labelled TWSE OpenAPI index response.

    The OpenAPI response is a flat list, while the date-scoped MI_INDEX
    response is a table wrapper handled above.  Both contain a price-index
    row and a similarly named return-index row.  Only the exact TAIEX price
    label and exact requested row date are accepted.
    """

    if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
        return parse_twse_taiex_from_all_daily_payload(
            payload,
            requested_date=requested_date,
            data_as_of=data_as_of,
            payload_sha256=payload_sha256,
        )
    rows = _rows(payload)
    if not rows:
        return []
    name_keys = ("\u6307\u6578", "Index", "Name")
    close_keys = ("\u6536\u76e4\u6307\u6578", "Close")
    date_keys = ("\u65e5\u671f", "Date", "reportedDate", "reported_date")
    price_label = "\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578"
    candidates: list[tuple[date, float]] = []
    for row in rows:
        name = _text(row, *name_keys)
        if name not in {price_label, "TAIEX"}:
            continue
        row_date = _date_from_row(row, *date_keys)
        if row_date != requested_date:
            continue
        close = parse_number(_text(row, *close_keys))
        if close is None or not math.isfinite(close) or close <= 0:
            return []
        candidates.append((row_date, close))
    if len(candidates) != 1:
        return []
    report_date, close = candidates[0]
    return [
        BarRecord(
            symbol="TAIEX",
            trading_date=report_date,
            open=close,
            high=close,
            low=close,
            close=close,
            adj_close=close,
            volume=0,
            turnover=0.0,
            exchange="TWSE",
            source="twse_index",
            data_as_of=data_as_of or report_date.isoformat(),
            payload_sha256=payload_sha256,
        )
    ]


def parse_twse_index_history_payload(
    payload: Any,
    *,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[BarRecord]:
    """Parse the official monthly TAIEX history report."""

    rows = _rows(payload)
    result: list[BarRecord] = []
    for row in rows:
        trading_date = _date_from_row(row, "Date", "\u65e5\u671f")
        open_price = parse_number(_text(row, "OpeningIndex", "\u958b\u76e4\u6307\u6578", "\u958b\u76e4"))
        high = parse_number(_text(row, "HighestIndex", "\u6700\u9ad8\u6307\u6578", "\u6700\u9ad8"))
        low = parse_number(_text(row, "LowestIndex", "\u6700\u4f4e\u6307\u6578", "\u6700\u4f4e"))
        close = parse_number(_text(row, "ClosingIndex", "\u6536\u76e4\u6307\u6578", "\u6536\u76e4"))
        if not trading_date or close is None:
            continue
        result.append(
            BarRecord(
                symbol="TAIEX",
                trading_date=trading_date,
                open=open_price if open_price is not None else close,
                high=high if high is not None else close,
                low=low if low is not None else close,
                close=close,
                adj_close=close,
                volume=0,
                turnover=0.0,
                exchange="TWSE",
                source="twse_index",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_mops_event_rows(
    payload: Any,
    *,
    exchange: str,
    endpoint: str,
    payload_sha256: str | None = None,
) -> list[EventRecord]:
    """Normalize the official TWSE/TPEx MOPS material-information feed."""

    result: list[EventRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "Code", "SecuritiesCompanyCode", "\u516c\u53f8\u4ee3\u865f", "\u8b49\u5238\u4ee3\u865f")
        event_date = _date_from_row(
            row,
            "AnnouncementDate",
            "\u767c\u8a00\u65e5\u671f",
            "Date",
            "\u4e8b\u5be6\u767c\u751f\u65e5",
        )
        title = _text(row, "Title", "Subject", "\u4e3b\u65e8")
        if not symbol or event_date is None or not title:
            continue
        result.append(
            EventRecord(
                symbol=symbol,
                event_date=event_date,
                event_type="material_information",
                title=title,
                description=_text(row, "Description", "\u8aaa\u660e") or None,
                details=dict(row),
                endpoint=endpoint,
                exchange=exchange,
                payload_sha256=payload_sha256,
            )
        )
    return result


def _mops_year(value: Any) -> int | None:
    parsed = parse_integer(value)
    if parsed is None:
        return None
    return parsed + 1911 if parsed < 1000 else parsed


def _mops_period_end(row: dict[str, Any]) -> tuple[date | None, str]:
    monthly = _text(row, "DataMonth", "\u8cc7\u6599\u5e74\u6708")
    if monthly:
        digits = re.sub(r"\D", "", monthly)
        if len(digits) == 5:
            year = _mops_year(digits[:3])
            month = int(digits[3:])
            if year and 1 <= month <= 12:
                return date(year, month, monthrange(year, month)[1]), f"M{month:02d}"
    year = _mops_year(_text(row, "Year", "\u5e74\u5ea6"))
    quarter_text = _text(row, "Quarter", "\u5b63\u5225")
    quarter = parse_integer(quarter_text)
    if year and quarter and 1 <= quarter <= 4:
        month = quarter * 3
        return date(year, month, monthrange(year, month)[1]), f"Q{quarter}"
    return None, "unknown"


def parse_mops_fundamental_rows(
    payload: Any,
    *,
    exchange: str,
    payload_sha256: str | None = None,
) -> list[FundamentalRecord]:
    """Normalize official MOPS quarterly EPS/fundamental snapshots."""

    result: list[FundamentalRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "Code", "SecuritiesCompanyCode", "\u516c\u53f8\u4ee3\u865f", "\u8b49\u5238\u4ee3\u865f")
        period_end, fiscal_period = _mops_period_end(row)
        if not symbol or period_end is None:
            continue
        result.append(
            FundamentalRecord(
                symbol=symbol,
                period_end=period_end,
                fiscal_period=fiscal_period,
                announcement_date=_date_from_row(row, "AnnouncementDate", "Date", "\u51fa\u8868\u65e5\u671f"),
                revenue=parse_number(_text(row, "Revenue", "\u71df\u696d\u6536\u5165")),
                eps=parse_number(_text(row, "EPS", "BasicEPS", "\u57fa\u672c\u6bcf\u80a1\u76c8\u9918", "\u57fa\u672c\u6bcf\u80a1\u76c8\u9918(\u5143)")),
                roe=parse_number(_text(row, "ROE", "\u80a1\u6771\u6b0a\u76ca\u5831\u916c\u7387")),
                details=dict(row),
                exchange=exchange,
                payload_sha256=payload_sha256,
            )
        )
    return result


class TwseAdapter:
    source = "twse"

    def __init__(self, fetcher: Callable[..., Any] = fetch_json, *, stock_day_capture=None, holiday_capture=None) -> None:
        self.fetcher = fetcher
        # Local library opt-in only. collect callers must use force=True to
        # bypass reuse of an existing successful run. Other feeds stay legacy.
        self.stock_day_capture = stock_day_capture
        self.stock_day_unavailable: list[dict[str, str]] = []
        # Only multi-day fetch_bars uses the calendar. A single-day request
        # retains its existing date/index gates and does not consult it.
        self.holiday_capture = holiday_capture
        self.holiday_unknown: list[dict[str, str]] = []
        self.holiday_closed_dates: set[date] = set()
        # Keep captures available to the caller even when a later official
        # request fails.  The collector uses these to attach partial raw
        # evidence to the failed ingestion run.
        self.captured_payloads: list[FetchedPayload] = []
        # A historical daily report can be temporarily unavailable at an
        # official CDN edge.  Keep that separate from a payload returned with
        # a missing or wrong date: the former may be skipped as a conservative
        # partial backfill, while the latter must still fail closed below.
        self.fetch_warnings: list[str] = []
        self.no_data_dates: list[date] = []

    def _fetch(
        self,
        endpoint: str,
        data_as_of: str | None = None,
        *,
        method: str = "GET",
        data: Any = None,
    ) -> FetchedPayload:
        payload = _call_fetcher(self.fetcher, endpoint, method=method, data=data)
        captured = capture_payload(self.source, endpoint, payload, data_as_of)
        self.captured_payloads.append(captured)
        return captured

    def fetch_universe(self, as_of: date) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        listed_payload = self._fetch(TWSE_LISTED_ENDPOINT, as_of.isoformat())
        etf_payload = self._fetch(TWSE_ETF_ENDPOINT, as_of.isoformat())
        new_listing_payload = self._fetch(TWSE_NEW_LISTING_ENDPOINT, as_of.isoformat())
        listed_rows = _rows(listed_payload.payload)
        etf_rows = _rows(etf_payload.payload)
        new_rows = _rows(new_listing_payload.payload)
        if not listed_rows and not etf_rows:
            raise OfficialDataError("TWSE universe payloads contained no instruments")

        etf_codes = {_text(row, "基金代號", "FundCode", "代號") for row in etf_rows}
        recent_codes = {
            _text(row, "Code", "公司代號", "證券代號")
            for row in new_rows
            if _date_from_row(row, "ApprovedListingDate", "ListingDate")
        }
        # Restrict IPO classification to approved listings that are already
        # effective as of the requested market date.  Future approved rows
        # must not become actionable IPOs.
        recent_codes = {
            code
            for row in new_rows
            if (code := _text(row, "Code"))
            and _is_recent_listing(
                as_of,
                _date_from_row(row, "ApprovedListingDate", "ListingDate"),
            )
        }
        records: dict[str, InstrumentRecord] = {}
        for row in listed_rows:
            symbol = _text(row, "公司代號", "Code", "證券代號")
            if not symbol:
                continue
            listing_date = _date_from_row(row, "上市日期", "DateOfListing")
            instrument_type = "ipo" if symbol in recent_codes or (listing_date and (as_of - listing_date).days <= 60) else "stock"
            records[symbol] = InstrumentRecord(
                symbol=symbol,
                name=_text(row, "公司簡稱", "公司名稱", "Name") or symbol,
                exchange="TWSE",
                instrument_type=instrument_type,
                listing_date=listing_date,
                industry=_text(row, "產業別", "Industry") or None,
                payload_sha256=listed_payload.sha256,
            )
        for row in etf_rows:
            symbol = _text(row, "基金代號", "FundCode", "代號")
            if not symbol:
                continue
            listing_date = _date_from_row(row, "上市日期", "DateOfListing")
            records[symbol] = InstrumentRecord(
                symbol=symbol,
                name=_text(row, "基金簡稱", "基金中文名稱", "基金名稱", "Name") or symbol,
                exchange="TWSE",
                instrument_type="etf",
                etf_category=_text(row, "基金類型", "FundType") or None,
                listing_date=listing_date,
                industry="ETF",
                payload_sha256=etf_payload.sha256,
            )
        for symbol, record in list(records.items()):
            if record.instrument_type == "ipo" and not (
                symbol in recent_codes or _is_recent_listing(as_of, record.listing_date)
            ):
                records[symbol] = InstrumentRecord(
                    symbol=record.symbol,
                    name=record.name,
                    market=record.market,
                    exchange=record.exchange,
                    instrument_type="stock",
                    etf_category=record.etf_category,
                    listing_date=record.listing_date,
                    industry=record.industry,
                    status=record.status,
                    payload_sha256=record.payload_sha256,
                )

        # Keep approved new listings in the universe even if the issuer master
        # has not propagated the row yet.  Their missing history then remains
        # visible as non-actionable data rather than disappearing silently.
        for row in new_rows:
            symbol = _text(row, "Code", "Symbol")
            listing_date = _date_from_row(row, "ApprovedListingDate", "ListingDate")
            if not symbol or listing_date is None or listing_date > as_of or symbol in records:
                continue
            records[symbol] = InstrumentRecord(
                symbol=symbol,
                name=_text(row, "Name", "CompanyName", "Company") or symbol,
                exchange="TWSE",
                instrument_type="ipo",
                listing_date=listing_date,
                industry=_text(row, "Industry") or None,
                payload_sha256=new_listing_payload.sha256,
            )

        # The OpenAPI ETF feed exposes free-text FundType values.  Normalize
        # them to the finite strategy-contract categories before persistence;
        # a missing description remains None and therefore fails closed.
        normalized_records: list[InstrumentRecord] = []
        for record in records.values():
            if record.instrument_type != "etf":
                normalized_records.append(record)
                continue
            normalized_records.append(
                InstrumentRecord(
                    symbol=record.symbol,
                    name=record.name,
                    market=record.market,
                    exchange=record.exchange,
                    instrument_type=record.instrument_type,
                    etf_category=normalize_etf_category(
                        record.etf_category,
                        symbol=record.symbol,
                        name=record.name,
                    ),
                    listing_date=record.listing_date,
                    industry=record.industry,
                    status=record.status,
                    payload_sha256=record.payload_sha256,
                )
            )
        return normalized_records, [listed_payload, etf_payload, new_listing_payload]

    def fetch_bars(self, symbols: Iterable[str], start: date, end: date) -> tuple[list[BarRecord], list[FetchedPayload]]:
        _ensure_backfill_window(start, end)
        self.fetch_warnings = []
        self.no_data_dates = []
        self.stock_day_unavailable = []
        self.holiday_unknown = []
        self.holiday_closed_dates = set()
        symbol_list = list(dict.fromkeys(symbols))
        if not symbol_list:
            return [], []
        payloads: list[FetchedPayload] = []
        bars: list[BarRecord] = []
        # STOCK_DAY_ALL is the official OpenAPI daily all-securities feed.  It
        # includes listed ETFs in practice and is the cheapest current-day
        # request.  For historical dates, the official MI_INDEX report also
        # contains one all-security table; use one request per weekday rather
        # than one STOCK_DAY request per symbol and month.
        if self.stock_day_capture is None:
            daily_payload = self._fetch(TWSE_DAILY_ENDPOINT, end.isoformat())
            daily_bars = [
                bar
                for bar in parse_twse_daily_rows(daily_payload.payload, data_as_of=end.isoformat(), payload_sha256=daily_payload.sha256)
                if start <= bar.trading_date <= end and bar.symbol in symbol_list
            ]
        else:
            daily_bars, daily_payload, self.stock_day_unavailable = self.stock_day_capture.select(symbol_list, end)
            self.captured_payloads.append(daily_payload)
            for unavailable in self.stock_day_unavailable:
                self.fetch_warnings.append("stock_day_capture_unavailable:" + json.dumps(unavailable, sort_keys=True))
        payloads.append(daily_payload)
        bars.extend(daily_bars)
        closed_dates: set[date] = set()
        if start != end:
            # The official holiday feed is used only as a positive exclusion
            # list.  If it is unavailable, do not infer a holiday; the normal
            # MI_INDEX request remains fail-closed for that date.
            if self.holiday_capture is None:
                try:
                    holiday_payload = self._fetch(TWSE_HOLIDAY_ENDPOINT, end.isoformat())
                except OfficialDataError as exc:
                    holiday_payload = None
                    self.fetch_warnings.append(
                        "TWSE holiday calendar unavailable; no non-trading date was inferred: "
                        f"{exc}"
                    )
                if holiday_payload is not None:
                    payloads.append(holiday_payload)
                    closed_dates = _official_non_trading_dates(holiday_payload.payload, start, end)
            else:
                closed_dates, holiday_payload, self.holiday_unknown = self.holiday_capture.select(start, end)
                self.captured_payloads.append(holiday_payload)
                payloads.append(holiday_payload)
                self.holiday_closed_dates = closed_dates
                for unknown in self.holiday_unknown:
                    self.fetch_warnings.append("holiday_capture_unknown:" + json.dumps(unknown, sort_keys=True))
                # Check all observed daily rows, including securities outside
                # the selected universe. The calendar cannot erase an already
                # visible valid trading observation for a supposedly closed day.
                observed = parse_twse_daily_rows(daily_payload.payload)
                self._check_holiday_conflicts(observed)
        # Do not return early for a one-day current snapshot.  The current
        # all-security feed can provide usable OHLCV while its separate index
        # feed is stale or date-less.  A backfill session is only verified
        # after the date-scoped MI_INDEX response has also been checked and
        # its TAIEX row has been parsed.  The final keyed de-duplication below
        # keeps the current and date-scoped security rows idempotent.

        for trading_date in _weekday_dates(start, end):
            if trading_date in closed_dates:
                continue
            query = urlencode(
                {
                    "date": trading_date.strftime("%Y%m%d"),
                    "type": "ALLBUT0999",
                    "response": "json",
                }
            )
            endpoint = f"{TWSE_DAILY_HISTORY_ENDPOINT}?{query}"
            try:
                payload = self._fetch(endpoint, trading_date.isoformat())
            except OfficialDataError as exc:
                # A transport/5xx/temporary CDN failure has no trustworthy
                # observation. Preserve the exact requested date and
                # endpoint in the warning and continue other sessions. Date
                # validation remains outside this block, so a non-empty
                # wrong-date or date-less response still aborts.
                self.fetch_warnings.append(
                    "TWSE MI_INDEX unavailable for "
                    f"{trading_date.isoformat()} endpoint={endpoint}: {exc}"
                )
                continue
            if _is_twse_mi_index_no_data(payload.payload, endpoint):
                # TWSE uses a date-less, explicit no-match response on
                # holidays/non-trading weekdays.  The raw payload remains
                # captured for provenance, while no OHLC row is inferred.
                payloads.append(payload)
                self.no_data_dates.append(trading_date)
                continue
            _require_reported_date(payload.payload, trading_date, endpoint)
            parsed = parse_twse_all_daily_payload(
                payload.payload,
                requested_date=trading_date,
                data_as_of=trading_date.isoformat(),
                payload_sha256=payload.sha256,
            )
            payloads.append(payload)
            bars.extend(
                bar
                for bar in parsed
                if start <= bar.trading_date <= end and bar.symbol in symbol_list
                # The captured snapshot owns all selected securities on end,
                # including missing/invalid rows; history cannot fill them.
                and not (self.stock_day_capture is not None and trading_date == end)
            )
            taiex_rows = parse_twse_taiex_from_all_daily_payload(
                payload.payload,
                requested_date=trading_date,
                data_as_of=trading_date.isoformat(),
                payload_sha256=payload.sha256,
            )
            if not taiex_rows:
                raise OfficialDataError(
                    "TWSE MI_INDEX did not contain one finite positive "
                    f"price-index TAIEX row for {trading_date.isoformat()}: {endpoint}"
                )
            bars.extend(taiex_rows)

        # Keep the newest occurrence for a symbol/day; a current all-feed row
        # and a month-history row are the same official observation.
        unique = {(bar.exchange, bar.symbol, bar.trading_date): bar for bar in bars}
        return list(unique.values()), payloads

    def _check_holiday_conflicts(self, bars: Iterable[BarRecord]) -> None:
        for bar in bars:
            if bar.trading_date not in self.holiday_closed_dates:
                continue
            prices = (bar.open, bar.high, bar.low, bar.close)
            valid = all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) and value > 0 for value in prices)
            if valid and bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high:
                raise OfficialDataError("holiday_capture_trading_conflict:" + bar.trading_date.isoformat() + ":" + bar.symbol)

    def fetch_actions(self, as_of: date) -> tuple[list[ActionRecord], list[FetchedPayload]]:
        payload = self._fetch(TWSE_ACTION_ENDPOINT, as_of.isoformat())
        result: list[ActionRecord] = []
        for row in _rows(payload.payload):
            symbol = _text(row, "Code", "股票代號", "證券代號")
            action_date = _date_from_row(row, "Date", "除權息日期")
            if not symbol or not action_date:
                continue
            # TWT48U_ALL also contains announced future ex-right/ex-dividend
            # dates.  They are not observable at the requested as-of date and
            # must not leak into historical tracking.
            if action_date > as_of:
                continue
            result.append(
                ActionRecord(
                    symbol=symbol,
                    action_date=action_date,
                    action_type="ex_dividend" if "除息" in _text(row, "Exdividend", "除權息") else "corporate_action",
                    cash_dividend=parse_number(_text(row, "CashDividend", "現金股利")),
                    stock_dividend_ratio=parse_number(_text(row, "StockDividendRatio", "無償配股率")),
                    split_ratio=parse_number(_text(row, "SplitRatio", "分割比例", "分割率")),
                    reference_price=parse_number(
                        _text(row, "ReferencePrice", "OpeningReferencePrice", "開盤參考價", "除權息前收盤價")
                    ),
                    details=dict(row),
                    exchange="TWSE",
                    payload_sha256=payload.sha256,
                )
            )
        return result, [payload]

    def fetch_index(self, as_of: date) -> tuple[list[BarRecord], list[FetchedPayload]]:
        payload = self._fetch(TWSE_INDEX_ENDPOINT, as_of.isoformat())
        result = parse_twse_taiex_from_index_payload(
            payload.payload,
            requested_date=as_of,
            data_as_of=as_of.isoformat(),
            payload_sha256=payload.sha256,
        )
        if not result:
            raise OfficialDataError(
                "TWSE index feed did not contain one finite positive "
                f"price-index TAIEX row for {as_of.isoformat()}: {TWSE_INDEX_ENDPOINT}"
            )
        return result, [payload]

    def fetch_index_history(self, start: date, end: date) -> tuple[list[BarRecord], list[FetchedPayload]]:
        """Fetch date-scoped official TAIEX rows for group benchmarking."""

        _ensure_backfill_window(start, end)
        if start == end:
            return [], []
        bars: list[BarRecord] = []
        payloads: list[FetchedPayload] = []
        for trading_date in _weekday_dates(start, end):
            query = urlencode(
                {
                    "date": trading_date.strftime("%Y%m%d"),
                    "type": "ALLBUT0999",
                    "response": "json",
                }
            )
            endpoint = f"{TWSE_DAILY_HISTORY_ENDPOINT}?{query}"
            payload = self._fetch(endpoint, trading_date.isoformat())
            payloads.append(payload)
            if _is_twse_mi_index_no_data(payload.payload, endpoint):
                continue
            _require_reported_date(payload.payload, trading_date, endpoint)
            taiex_rows = parse_twse_taiex_from_all_daily_payload(
                payload.payload,
                requested_date=trading_date,
                data_as_of=trading_date.isoformat(),
                payload_sha256=payload.sha256,
            )
            if not taiex_rows:
                raise OfficialDataError(
                    "TWSE MI_INDEX did not contain one finite positive "
                    f"price-index TAIEX row for {trading_date.isoformat()}: {endpoint}"
                )
            bars.extend(taiex_rows)
        unique = {(bar.symbol, bar.trading_date): bar for bar in bars}
        return list(unique.values()), payloads

    def fetch_chips(
        self,
        trading_dates: Iterable[date],
        allowed_symbols: set[str],
    ) -> tuple[list[ChipRecord], list[FetchedPayload], list[str]]:
        """Fetch date-scoped TWSE institutional and margin snapshots.

        The request dates come from successfully parsed OHLCV sessions, so a
        weekend or a holiday does not masquerade as a missing official chip
        session.  Chip endpoint failures are retained as warnings because the
        OHLCV run remains useful, but strategy consumers fail closed on the
        missing components.
        """

        institutional: list[ChipRecord] = []
        margin: list[ChipRecord] = []
        payloads: list[FetchedPayload] = []
        warnings: list[str] = []
        for trading_date in sorted(set(trading_dates)):
            # TWSE RWD reports use compact YYYYMMDD query dates.  TPEx's
            # newer POST pages use slashes and are handled separately below.
            date_text = trading_date.strftime("%Y%m%d")
            chip_endpoint = f"{TWSE_CHIP_ENDPOINT}?{urlencode({'date': date_text, 'selectType': 'ALL', 'response': 'json'})}"
            margin_endpoint = f"{TWSE_MARGIN_HISTORY_ENDPOINT}?{urlencode({'date': date_text, 'selectType': 'ALL', 'response': 'json'})}"
            try:
                chip_payload = self._fetch(chip_endpoint, trading_date.isoformat())
                payloads.append(chip_payload)
                _require_reported_date(chip_payload.payload, trading_date, TWSE_CHIP_ENDPOINT)
                parsed = parse_twse_institutional_rows(
                    chip_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=chip_payload.sha256,
                )
                institutional.extend(item for item in parsed if item.symbol in allowed_symbols)
                if not parsed:
                    warnings.append(f"TWSE institutional chip feed returned no rows for {trading_date.isoformat()}")
            except OfficialDataError as exc:
                warnings.append(f"TWSE institutional chips unavailable for {trading_date.isoformat()}: {exc}")
            try:
                margin_payload = self._fetch(margin_endpoint, trading_date.isoformat())
                payloads.append(margin_payload)
                _require_reported_date(margin_payload.payload, trading_date, TWSE_MARGIN_HISTORY_ENDPOINT)
                parsed = parse_twse_margin_rows(
                    margin_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=margin_payload.sha256,
                )
                margin.extend(item for item in parsed if item.symbol in allowed_symbols)
                if not parsed:
                    warnings.append(f"TWSE margin feed returned no rows for {trading_date.isoformat()}")
            except OfficialDataError as exc:
                warnings.append(f"TWSE margin chips unavailable for {trading_date.isoformat()}: {exc}")
        return (
            merge_chip_records(institutional, margin, allowed_symbols=allowed_symbols, exchange="TWSE"),
            payloads,
            warnings,
        )

    def fetch(self, start: date, end: date) -> OfficialBatch:
        self.captured_payloads = []
        self.fetch_warnings = []
        self.no_data_dates = []
        instruments, universe_payloads = self.fetch_universe(end)
        bars, bar_payloads = self.fetch_bars((item.symbol for item in instruments), start, end)
        chip_dates = {bar.trading_date for bar in bars if bar.symbol != "TAIEX"}
        chips, chip_payloads, chip_warnings = self.fetch_chips(
            chip_dates,
            {item.symbol for item in instruments},
        )
        actions, action_payloads = self.fetch_actions(end)
        # For backfills, TAIEX is parsed from each date-validated MI_INDEX
        # payload in fetch_bars.  Keep the current OpenAPI index request for
        # the single-day path, where the all-security feed may be empty while
        # the official index feed still has a row.
        index_bars, index_payloads = self.fetch_index(end)
        index_bars = [bar for bar in index_bars if start <= bar.trading_date <= end]
        self._check_holiday_conflicts(index_bars)
        events: list[EventRecord] = []
        fundamentals: list[FundamentalRecord] = []
        mops_payloads: list[FetchedPayload] = []
        warnings: list[str] = list(self.fetch_warnings) + list(chip_warnings)
        try:
            event_payload = self._fetch(TWSE_EVENT_ENDPOINT, end.isoformat())
            mops_payloads.append(event_payload)
            events = [
                event
                for event in parse_mops_event_rows(
                    event_payload.payload,
                    exchange="TWSE",
                    endpoint=TWSE_EVENT_ENDPOINT,
                    payload_sha256=event_payload.sha256,
                )
                if event.event_date <= end
            ]
        except OfficialDataError as exc:
            warnings.append(f"TWSE MOPS events unavailable: {exc}")
        try:
            fundamental_payload = self._fetch(TWSE_FUNDAMENTAL_ENDPOINT, end.isoformat())
            mops_payloads.append(fundamental_payload)
            fundamentals = [
                fundamental
                for fundamental in parse_mops_fundamental_rows(
                    fundamental_payload.payload,
                    exchange="TWSE",
                    payload_sha256=fundamental_payload.sha256,
                )
                if not fundamental.announcement_date or fundamental.announcement_date <= end
            ]
        except OfficialDataError as exc:
            warnings.append(f"TWSE MOPS fundamentals unavailable: {exc}")
        index_record = InstrumentRecord("TAIEX", "TAIEX", exchange="TWSE", instrument_type="index", industry="Index")
        event_coverage = {
            "status": "unsupported",
            "denominator": "date_scoped_event_queries",
            "verified_dates": [],
            "empty_dates": [],
            "unsupported_dates": [end.isoformat()],
            "observed_event_dates": sorted({item.event_date.isoformat() for item in events}),
            "source": "TWSE MOPS material-information feed",
            "reason": "the official feed is an event-date list, not a date-scoped empty-session response",
        }
        return OfficialBatch(
            instruments=instruments + [index_record],
            bars=bars + index_bars,
            chips=chips,
            actions=actions,
            fundamentals=fundamentals,
            events=events,
            payloads=universe_payloads + bar_payloads + chip_payloads + action_payloads + index_payloads + mops_payloads,
            warnings=warnings,
            data_as_of=end.isoformat(),
            no_data_dates=sorted(set(self.no_data_dates)),
            event_coverage=event_coverage,
        )


class TpexAdapter:
    source = "tpex"

    def __init__(self, fetcher: Callable[..., Any] = fetch_json) -> None:
        self.fetcher = fetcher
        self.captured_payloads: list[FetchedPayload] = []
        self.no_data_dates: list[date] = []

    def _fetch(
        self,
        endpoint: str,
        data_as_of: str | None = None,
        *,
        method: str = "GET",
        data: Any = None,
    ) -> FetchedPayload:
        payload = _call_fetcher(self.fetcher, endpoint, method=method, data=data)
        captured = capture_payload(self.source, endpoint, payload, data_as_of)
        self.captured_payloads.append(captured)
        return captured

    def _fetch_authoritative_universe(self, as_of: date) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        """Build TPEx scope from MOPS stock master plus the ETF allowlist.

        The daily quote table is intentionally not a universe source: it also
        contains warrants, ETNs, bonds, and other products.  It is fetched by
        ``fetch_bars`` and filtered against these records.
        """

        listed_payload = self._fetch(TPEX_LISTED_ENDPOINT, as_of.isoformat())
        etf_payload = self._fetch(
            TPEX_ETF_ENDPOINT,
            as_of.isoformat(),
            method="POST",
            data={"response": "json"},
        )
        listed_rows = _rows(listed_payload.payload)
        etf_rows = _rows(etf_payload.payload)
        records: dict[str, InstrumentRecord] = {}
        for row in listed_rows:
            symbol = _text(row, "SecuritiesCompanyCode", "Code", "證券代號", "代號")
            name = _text(row, "CompanyAbbreviation", "CompanyName", "名稱") or symbol
            if not symbol or _is_tpex_non_scope_product(symbol, name):
                continue
            listing_date = _date_from_row(row, "DateOfListing", "上市日期", "掛牌日期")
            records[symbol] = InstrumentRecord(
                symbol=symbol,
                name=name,
                exchange="TPEx",
                instrument_type="ipo" if _is_recent_listing(as_of, listing_date) else "stock",
                listing_date=listing_date,
                industry=_text(row, "SecuritiesIndustryCode", "Industry", "產業別") or None,
                payload_sha256=listed_payload.sha256,
            )
        for row in etf_rows:
            symbol = _text(row, "stockNo", "StockNo", "Code", "代號")
            name = _text(row, "stockName", "StockName", "Name", "名稱") or symbol
            if not symbol:
                continue
            listing_date = _date_from_row(row, "listingDate", "ListingDate", "DateOfListing", "上市日期")
            index_name = _text(row, "indexName", "IndexName", "指數名稱")
            records[symbol] = InstrumentRecord(
                symbol=symbol,
                name=name,
                exchange="TPEx",
                instrument_type="etf",
                etf_category=normalize_etf_category(index_name, symbol=symbol, name=name),
                listing_date=listing_date,
                industry="ETF",
                payload_sha256=etf_payload.sha256,
            )
        if not records:
            raise OfficialDataError(
                "TPEx authoritative MOPS stock master and ETF allowlist contained no instruments"
            )
        return list(records.values()), [listed_payload, etf_payload]

    def fetch_universe(self, as_of: date) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        return self._fetch_authoritative_universe(as_of)

    def fetch_bars(self, symbols: Iterable[str], start: date, end: date) -> tuple[list[BarRecord], list[FetchedPayload]]:
        _ensure_backfill_window(start, end)
        self.no_data_dates = []
        wanted = set(symbols)
        if not wanted:
            return [], []
        bars: list[BarRecord] = []
        payloads: list[FetchedPayload] = []
        historical_bar_dates: set[date] = set()
        for trading_date in _weekday_dates(start, end):
            payload = self._fetch(
                TPEX_HISTORY_API,
                trading_date.isoformat(),
                method="POST",
                data={
                    "date": trading_date.strftime("%Y/%m/%d"),
                    "response": "json",
                },
            )
            _require_reported_date(payload.payload, trading_date, TPEX_HISTORY_API)
            payloads.append(payload)
            parsed_rows = parse_tpex_daily_rows(
                payload.payload,
                data_as_of=trading_date.isoformat(),
                payload_sha256=payload.sha256,
            )
            historical_rows = [
                bar
                for bar in parsed_rows
                if bar.symbol in wanted and start <= bar.trading_date <= end
            ]
            if not parsed_rows and isinstance(payload.payload, dict):
                # An empty, date-validated TPEx table is explicit no-data
                # evidence.  Do not manufacture a bar or reinterpret it as
                # the latest available session.
                self.no_data_dates.append(trading_date)
            historical_bar_dates.update(
                bar.trading_date for bar in historical_rows if bar.trading_date < end
            )
            bars.extend(historical_rows)
        if start < end and not historical_bar_dates and not self.no_data_dates:
            raise OfficialDataError(
                "TPEx official historical quote endpoint returned no prior-session OHLCV "
                f"for requested range {start.isoformat()}..{end.isoformat()}"
            )
        return list({(bar.symbol, bar.trading_date): bar for bar in bars}.values()), payloads

    def fetch_chips(
        self,
        trading_dates: Iterable[date],
        allowed_symbols: set[str],
    ) -> tuple[list[ChipRecord], list[FetchedPayload], list[str]]:
        """Fetch TPEx date-based institutional and margin reports."""

        institutional: list[ChipRecord] = []
        margin: list[ChipRecord] = []
        payloads: list[FetchedPayload] = []
        warnings: list[str] = []
        for trading_date in sorted(set(trading_dates)):
            date_text = trading_date.strftime("%Y/%m/%d")
            try:
                chip_payload = self._fetch(
                    TPEX_CHIP_HISTORY_ENDPOINT,
                    trading_date.isoformat(),
                    method="POST",
                    data={
                        "type": "Daily",
                        "sect": "EW",
                        "date": date_text,
                        "response": "json",
                    },
                )
                payloads.append(chip_payload)
                _require_reported_date(chip_payload.payload, trading_date, TPEX_CHIP_HISTORY_ENDPOINT)
                parsed = parse_tpex_institutional_rows(
                    chip_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=chip_payload.sha256,
                )
                institutional.extend(item for item in parsed if item.symbol in allowed_symbols)
                if not parsed:
                    warnings.append(f"TPEx institutional chip feed returned no rows for {trading_date.isoformat()}")
            except OfficialDataError as exc:
                warnings.append(f"TPEx institutional chips unavailable for {trading_date.isoformat()}: {exc}")
            try:
                margin_payload = self._fetch(
                    TPEX_MARGIN_HISTORY_ENDPOINT,
                    trading_date.isoformat(),
                    method="POST",
                    data={"date": date_text, "response": "json"},
                )
                payloads.append(margin_payload)
                _require_reported_date(margin_payload.payload, trading_date, TPEX_MARGIN_HISTORY_ENDPOINT)
                parsed = parse_tpex_margin_rows(
                    margin_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=margin_payload.sha256,
                )
                margin.extend(item for item in parsed if item.symbol in allowed_symbols)
                if not parsed:
                    warnings.append(f"TPEx margin feed returned no rows for {trading_date.isoformat()}")
            except OfficialDataError as exc:
                warnings.append(f"TPEx margin chips unavailable for {trading_date.isoformat()}: {exc}")
        return (
            merge_chip_records(institutional, margin, allowed_symbols=allowed_symbols, exchange="TPEx"),
            payloads,
            warnings,
        )

    def fetch_actions(self, as_of: date) -> tuple[list[ActionRecord], list[FetchedPayload]]:
        payload = self._fetch(TPEX_ACTION_ENDPOINT, as_of.isoformat())
        result: list[ActionRecord] = []
        for row in _rows(payload.payload):
            symbol = _text(row, "SecuritiesCompanyCode", "代號")
            action_date = _date_from_row(row, "Date", "除權息日期")
            if not symbol or not action_date:
                continue
            if action_date > as_of:
                continue
            # TPEx publishes free shares per thousand old shares. StockDividend
            # is a monetary rights value, not a share ratio.
            free_shares = parse_number(_text(row, "StockDivdendThousandShares", "每仟股無償配股"))
            result.append(
                ActionRecord(
                    symbol=symbol,
                    action_date=action_date,
                    action_type="ex_dividend" if "息" in _text(row, "ExRightsDiviend", "權或息") else "corporate_action",
                    cash_dividend=parse_number(_text(row, "CashDivdend", "CashDividend", "現金股利", "息值")),
                    stock_dividend_ratio=free_shares / 1000 if free_shares is not None else None,
                    reference_price=parse_number(_text(row, "ClosePriceBeforeExRightsDiviend", "除權息前收盤價")),
                    details=dict(row),
                    exchange="TPEx",
                    payload_sha256=payload.sha256,
                )
            )
        return result, [payload]

    def fetch(self, start: date, end: date) -> OfficialBatch:
        self.captured_payloads = []
        self.no_data_dates = []
        instruments, universe_payloads = self.fetch_universe(end)
        bars, bar_payloads = self.fetch_bars((item.symbol for item in instruments), start, end)
        chip_dates = {bar.trading_date for bar in bars}
        chips, chip_payloads, chip_warnings = self.fetch_chips(
            chip_dates,
            {item.symbol for item in instruments},
        )
        actions, action_payloads = self.fetch_actions(end)
        events: list[EventRecord] = []
        fundamentals: list[FundamentalRecord] = []
        mops_payloads: list[FetchedPayload] = []
        suspension_payloads: list[FetchedPayload] = []
        warnings: list[str] = list(chip_warnings)
        try:
            suspension_payload = self._fetch(TPEX_SUSPEND_ENDPOINT, end.isoformat())
            suspension_payloads.append(suspension_payload)
            if suspension_payload.payload:
                warnings.append(
                    "TPEx suspension/resumption announcements do not establish bar suspension status; "
                    "raw payload retained without changing bar flags"
                )
        except OfficialDataError as exc:
            warnings.append(f"TPEx suspension feed unavailable: {exc}")
        try:
            suspension_history_payload = self._fetch(
                TPEX_SUSPEND_HISTORY_ENDPOINT,
                end.isoformat(),
            )
            suspension_payloads.append(suspension_history_payload)
            events.extend(
                event
                for event in parse_tpex_suspension_history_rows(
                    suspension_history_payload.payload,
                    allowed_symbols={item.symbol for item in instruments},
                    endpoint=TPEX_SUSPEND_HISTORY_ENDPOINT,
                    data_as_of=end.isoformat(),
                    payload_sha256=suspension_history_payload.sha256,
                )
                if event.event_date <= end
            )
        except OfficialDataError as exc:
            warnings.append(f"TPEx suspension history unavailable: {exc}")
        try:
            event_payload = self._fetch(TPEX_EVENT_ENDPOINT, end.isoformat())
            mops_payloads.append(event_payload)
            events.extend(
                event
                for event in parse_mops_event_rows(
                    event_payload.payload,
                    exchange="TPEx",
                    endpoint=TPEX_EVENT_ENDPOINT,
                    payload_sha256=event_payload.sha256,
                )
                if event.event_date <= end
            )
        except OfficialDataError as exc:
            warnings.append(f"TPEx MOPS events unavailable: {exc}")
        try:
            fundamental_payload = self._fetch(TPEX_FUNDAMENTAL_ENDPOINT, end.isoformat())
            mops_payloads.append(fundamental_payload)
            fundamentals = [
                fundamental
                for fundamental in parse_mops_fundamental_rows(
                    fundamental_payload.payload,
                    exchange="TPEx",
                    payload_sha256=fundamental_payload.sha256,
                )
                if not fundamental.announcement_date or fundamental.announcement_date <= end
            ]
        except OfficialDataError as exc:
            warnings.append(f"TPEx MOPS fundamentals unavailable: {exc}")
        event_coverage = {
            "status": "unsupported",
            "denominator": "date_scoped_event_queries",
            "verified_dates": [],
            "empty_dates": [],
            "unsupported_dates": [end.isoformat()],
            "observed_event_dates": sorted({item.event_date.isoformat() for item in events}),
            "source": "TPEx suspension-history/MOPS event feeds",
            "reason": "the official feeds are event-date lists, not date-scoped empty-session responses",
        }
        return OfficialBatch(
            instruments=instruments,
            bars=bars,
            chips=chips,
            actions=actions,
            fundamentals=fundamentals,
            events=events,
            payloads=universe_payloads + bar_payloads + chip_payloads + action_payloads + suspension_payloads + mops_payloads,
            warnings=warnings,
            data_as_of=end.isoformat(),
            no_data_dates=sorted(set(self.no_data_dates)),
            event_coverage=event_coverage,
        )


class OfficialMarketDataAdapter:
    """Combine TWSE and TPEx official feeds into one normalized batch."""

    def __init__(self, twse: TwseAdapter | None = None, tpex: TpexAdapter | None = None) -> None:
        self.twse = twse or TwseAdapter()
        self.tpex = tpex or TpexAdapter()
        self.captured_payloads: list[FetchedPayload] = []

    def fetch(self, start: date, end: date) -> OfficialBatch:
        _ensure_backfill_window(start, end)
        self.captured_payloads = []
        try:
            twse_batch = self.twse.fetch(start, end)
        except Exception:
            self.captured_payloads.extend(getattr(self.twse, "captured_payloads", []))
            raise
        self.captured_payloads.extend(
            getattr(self.twse, "captured_payloads", twse_batch.payloads)
        )
        try:
            tpex_batch = self.tpex.fetch(start, end)
        except Exception:
            self.captured_payloads.extend(getattr(self.tpex, "captured_payloads", []))
            raise
        self.captured_payloads.extend(
            getattr(self.tpex, "captured_payloads", tpex_batch.payloads)
        )
        instruments = {(item.exchange, item.symbol): item for item in twse_batch.instruments}
        instruments.update({(item.exchange, item.symbol): item for item in tpex_batch.instruments})
        bars = {(item.exchange, item.symbol, item.trading_date): item for item in twse_batch.bars}
        bars.update({(item.exchange, item.symbol, item.trading_date): item for item in tpex_batch.bars})
        no_data_dates = sorted(set(twse_batch.no_data_dates + tpex_batch.no_data_dates))
        if not instruments or (not bars and not no_data_dates):
            raise OfficialDataError("official feeds returned no normalized universe or OHLCV")
        return OfficialBatch(
            instruments=list(instruments.values()),
            bars=list(bars.values()),
            chips=twse_batch.chips + tpex_batch.chips,
            actions=twse_batch.actions + tpex_batch.actions,
            fundamentals=twse_batch.fundamentals + tpex_batch.fundamentals,
            events=twse_batch.events + tpex_batch.events,
            payloads=twse_batch.payloads + tpex_batch.payloads,
            warnings=twse_batch.warnings + tpex_batch.warnings,
            data_as_of=max(filter(None, [twse_batch.data_as_of, tpex_batch.data_as_of]), default=end.isoformat()),
            no_data_dates=no_data_dates,
            event_coverage=_merge_event_coverage(
                [twse_batch.event_coverage, tpex_batch.event_coverage]
            ),
        )
