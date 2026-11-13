from __future__ import annotations

import hashlib
import html
import inspect
import json
import math
import re
import time
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode, urlsplit

import httpx

from app.clock import utcnow
from app.config import OFFICIAL_MAX_BACKFILL_DAYS, RAW_DIR
from app.domain import ETF_CATEGORIES
from app.trading_calendar import classify


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
    # A numeric amount alone cannot prove that the source supplied it.
    # Parsers and validated direct producers must state availability explicitly.
    turnover_status: str = "unknown"
    turnover_reason: str | None = None


@dataclass(frozen=True)
class NoTradeRecord:
    """An official quote-table row whose open, high, low and close are all blank.

    TWSE ``MI_INDEX`` and TPEx ``dailyQuotes`` list a security on a day it had
    no regular-session trade, with every price field blank (``--``/``---``).
    That row is evidence of an official no-trade day, not a price: it is kept
    apart from ``BarRecord`` and never becomes a bar (Issue #454).
    """

    symbol: str
    trading_date: date
    exchange: str
    source: str
    data_as_of: str | None = None
    payload_sha256: str | None = None


@dataclass(frozen=True)
class ChipRecord:
    """One official same-day institutional/margin observation.

    ``source``, ``data_as_of`` and ``payload_sha256`` describe the record's
    first file: the institutional file, or the margin file for a margin-only
    record.  The ``margin_*`` fields describe the margin file whenever the
    record has one (Issue #395), so a merged record keeps both captures.
    """

    symbol: str
    trading_date: date
    foreign_buy: float | None = None
    trust_buy: float | None = None
    dealer_buy: float | None = None
    total_buy_sell: float | None = None
    margin_balance: float | None = None
    margin_change: float | None = None
    short_balance: float | None = None
    exchange: str = "TWSE"
    source: str = "official"
    data_as_of: str | None = None
    payload_sha256: str | None = None
    margin_source: str | None = None
    margin_data_as_of: str | None = None
    margin_payload_sha256: str | None = None


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


@dataclass(frozen=True)
class MarketSummaryRecord:
    """One exchange's official market summary for a session (Issue #275).

    A value the source did not supply, or supplied in a shape that cannot be
    read without guessing, is None; nothing is filled with 0.
    """

    exchange: str
    trading_date: date
    index_name: str
    index_close: float | None
    index_change: float | None
    # A ratio: -0.0181 is -1.81%.
    index_change_pct: float | None
    change_pct_method: str
    # Yuan.
    turnover: int | None
    turnover_scope: str
    advancers: int | None
    decliners: int | None
    unchanged: int | None
    limit_up: int | None
    limit_down: int | None
    unmatched: int | None
    not_comparable: int | None
    breadth_scope: str
    source: str
    data_as_of: str | None = None
    payload_sha256: str | None = None


@dataclass(frozen=True)
class EmergingIssuerRecord:
    """One company of the TPEx emerging-market roster (興櫃, Issue #512).

    ``as_of_date`` is the roster's own ``Date`` (資料日期), not the collect
    date.  Names only: no quote, universe or strategy reads it.
    """

    symbol: str
    name: str
    as_of_date: date
    payload_sha256: str | None = None


@dataclass(frozen=True)
class MonthlyRevenueRecord:
    """One company's revenue for one month (Issue #530).

    Amounts are NT$ thousands; ``yoy`` is the source's 去年同月增減(%) as
    reported (None when blank).  ``revenue_month`` is the month's first day;
    ``announcement_date`` is the availability date (``details`` names its
    basis).
    """

    symbol: str
    exchange: str
    revenue_month: date
    revenue: float | None
    prior_year_revenue: float | None
    yoy: float | None
    cumulative_revenue: float | None
    announcement_date: date
    details: dict[str, Any] = field(default_factory=dict)
    source: str = "mops_t187ap05"
    payload_sha256: str | None = None


@dataclass(frozen=True)
class TradingHaltRecord:
    """One official capital-reduction stop of trading (Issue #582).

    The stopped sessions run from ``halt_start`` up to, not including,
    ``resume_date``.  TWSE names the last trading day (``halt_start`` is the
    calendar day after it); TPEx names the first stopped day and no last
    trading day.  ``details`` is the official row as published.
    """

    symbol: str
    exchange: str
    halt_start: date
    resume_date: date
    last_trade_date: date | None
    reason_detail: str | None
    endpoint: str
    source: str
    reason: str = "capital_reduction"
    details: dict[str, Any] = field(default_factory=dict)
    payload_sha256: str | None = None


@dataclass(frozen=True)
class TradingHaltWindow:
    """A readable answer for one exchange's range of resumption days.

    The answer is complete for the range: worker.trading_halts rebuilds that
    exchange's stored rows whose resumption day falls in it.  ``rejected``
    lists the rows left out because their own dates disagree.
    """

    exchange: str
    source: str
    endpoint: str
    start: date
    end: date
    payload_sha256: str | None
    rejected: tuple[str, ...] = ()


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
    # Informational source observations that do not reduce coverage of the
    # requested session (for example a non-empty TPEx notice feed whose raw
    # payload is retained without changing bar flags).  Unlike ``warnings``
    # they never downgrade a collect run to partial.
    notices: list[str] = field(default_factory=list)
    # False for a historical batch fetched without the current-only snapshot
    # feeds; the collector then records no current industry observation for
    # the historical session.
    snapshot_feeds: bool = True
    # Display-only market summaries; a failure is a non-core warning.
    market_summaries: list[MarketSummaryRecord] = field(default_factory=list)
    # The TPEx emerging-market roster (names only, Issue #512); a failure is a
    # non-core warning.
    emerging_issuers: list[EmergingIssuerRecord] = field(default_factory=list)
    # The latest month of the monthly revenue snapshots (display only, Issue
    # #530); a failure is a non-core warning.
    monthly_revenues: list[MonthlyRevenueRecord] = field(default_factory=list)
    # The capital reduction stops of trading around the collect day and the
    # ranges answered (worker.trading_halts, Issue #582); a failure is a
    # non-core warning.
    trading_halts: list[TradingHaltRecord] = field(default_factory=list)
    trading_halt_windows: list[TradingHaltWindow] = field(default_factory=list)
    # Real index daily K bars of the collect month (worker.index_bars, Issue
    # #552); a failure is a non-core warning.
    index_daily_bars: list[Any] = field(default_factory=list)
    # The TX near-month bar of the collect day (worker.futures_bars, Issue
    # #552); a failure is a non-core warning.
    futures_bars: list[Any] = field(default_factory=list)
    # Per exchange, which endpoint each core feed was read from and why
    # (Issue #579: the TPEx quotes, institutional and margin feeds); run
    # metadata ``feed_sources``.
    feed_sources: dict[str, Any] = field(default_factory=dict)


def _merge_event_coverage(values: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge exchange event-feed audit without treating event rows as sessions."""

    items = [item for item in values if item]
    verified = sorted(
        {str(day) for item in items for day in item.get("verified_dates", [])}
    )
    empty = sorted({str(day) for item in items for day in item.get("empty_dates", [])})
    unsupported = sorted(
        {str(day) for item in items for day in item.get("unsupported_dates", [])}
    )
    partial = sorted(
        {str(day) for item in items for day in item.get("partial_dates", [])}
    )
    observed = sorted(
        {str(day) for item in items for day in item.get("observed_event_dates", [])}
    )
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
        )
        or None,
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
# 上市公司每月營業收入彙總表: the latest month only (Issue #530).
TWSE_MONTHLY_REVENUE_ENDPOINT = f"{TWSE_API}/opendata/t187ap05_L"
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
# The collect of the current session reads the three OpenAPI tables first and
# the website reports above only when an OpenAPI table is not of that session
# (Issue #579, #555 決定 B).  Catch-up and backfill read the website reports.
# feed -> (OpenAPI endpoint, website endpoint)
TPEX_CURRENT_FEEDS = {
    "quotes": (TPEX_DAILY_ENDPOINT, TPEX_HISTORY_API),
    "institutional": (TPEX_CHIP_ENDPOINT, TPEX_CHIP_HISTORY_ENDPOINT),
    "margin": (TPEX_MARGIN_ENDPOINT, TPEX_MARGIN_HISTORY_ENDPOINT),
}
# The OpenAPI institutional keys of the website table's columns 4 (外資及陸資
# 不含外資自營商), 13 (投信), 22 (自營商合計) and 23 (三大法人合計).
TPEX_OPENAPI_INSTITUTIONAL_KEYS = {
    "foreign_buy": "Foreign Investors include Mainland Area Investors "
    "(Foreign Dealers excluded)-Difference",
    "trust_buy": "SecuritiesInvestmentTrustCompanies-Difference",
    "dealer_buy": "Dealers-Difference",
    "total_buy_sell": "TotalDifference",
}
# The MOPS issuer master's industry code of 管理股票 (docs/INDUSTRY_CLASSIFICATION.md).
TPEX_MANAGED_INDUSTRY_CODE = "80"
# Kept as a catalog reference only.  The official ESB feed is deliberately
# not used to construct the listed/OTC universe.
TPEX_EMERGING_ENDPOINT = f"{TPEX_API}/tpex_esb_latest_statistics"
TPEX_ACTION_ENDPOINT = f"{TPEX_API}/tpex_exright_daily"
# 除權除息計算結果表 over a date range (Issue #386).  The daily feeds above
# only describe the collection day (TWT48U: that day and announced future
# dates), so a missed day was never recovered; these keep the past.
TWSE_ACTION_HISTORY_ENDPOINT = "https://www.twse.com.tw/rwd/zh/exRight/TWT49U"
# Per-event breakdown of a TWT49U row (cash per share, free shares per
# thousand); TWT49U itself only publishes the combined 權值+息值.
TWSE_ACTION_DETAIL_ENDPOINT = "https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail"
TPEX_ACTION_HISTORY_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ"
TPEX_SUSPEND_ENDPOINT = f"{TPEX_API}/tpex_spendi_today"
TPEX_SUSPEND_HISTORY_ENDPOINT = f"{TPEX_API}/tpex_spendi_history"
# Capital reduction stops of trading (Issue #582): 股票減資恢復買賣參考價格 and
# 減資恢復買賣, website reports queried by a range of resumption days; each
# row names a resumption day and the last trading day (TWSE) or the first
# stopped day (TPEx), published before the stop begins (worker.trading_halts).
TWSE_REDUCTION_ENDPOINT = "https://www.twse.com.tw/rwd/zh/reducation/TWTAUU"
TPEX_REDUCTION_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/bulletin/revivt"
TPEX_EVENT_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap04_O"
TPEX_FUNDAMENTAL_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap14_O"
# 上櫃公司每月營業收入彙總表, same fields as t187ap05_L (Issue #530).
TPEX_MONTHLY_REVENUE_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap05_O"
# 上櫃股票市場現況: the latest session only.  The official path is spelled
# ``mainborad``.
TPEX_HIGHLIGHT_ENDPOINT = f"{TPEX_API}/tpex_mainborad_highlight"
# 興櫃公司基本資料: the current emerging-market roster, same shape as the listed
# issuer master ``mopsfin_t187ap03_O``.  Only codes and names are kept, so an
# AI news candidate on an emerging stock is shown by name (Issue #512); it is
# never a universe, quote, candidate or strategy source.
TPEX_EMERGING_ISSUER_ENDPOINT = f"{TPEX_API}/mopsfin_t187ap03_R"
# Index daily K bars, one month per request (Issue #552; worker.index_bars):
# 發行量加權股價指數歷史資料 (open/high/low/close) and 市場成交資訊 (shares, NT$)
# on the TWSE site, 櫃買指數 月查詢 (open/high/low/close) and 日成交量值指數
# (thousand shares, NT$ thousand) on the TPEx site.
TWSE_INDEX_HISTORY_ENDPOINT = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST"
TWSE_MARKET_TRADING_ENDPOINT = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TPEX_INDEX_HISTORY_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx"
TPEX_INDEX_TRADING_ENDPOINT = (
    "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingIndex"
)
# 期貨每日交易行情 (TAIFEX OpenAPI, data.gov.tw 11319, 政府資料開放授權條款第1版):
# the latest session of every futures contract; the TX near month is kept
# (worker.futures_bars, Issue #552).  No date parameter, so no history.
TAIFEX_DAILY_FUTURES_ENDPOINT = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"


# Minimum spacing between requests to one official host.  TWSE's web
# reports (www.twse.com.tw) temporarily block clients that exceed roughly
# three requests per five seconds; a long backfill must stay below that rate
# instead of relying on retries after the block has started.
OFFICIAL_HOST_MIN_INTERVAL_SECONDS = {
    "www.twse.com.tw": 2.5,
    "openapi.twse.com.tw": 1.0,
    "www.tpex.org.tw": 1.0,
    "info.tpex.org.tw": 1.0,
    "openapi.taifex.com.tw": 1.0,
    # The TAIFEX site's futDataDown (TX history, Issue #563): one month per
    # request, as the TWSE/TPEx monthly report backfill paces itself.
    "www.taifex.com.tw": 3.0,
    # FinMind USStockPrice (US indexes, Issue #568): indexes apart, never a burst.
    "api.finmindtrade.com": 2.0,
    # MOPS blocks fast clients without a published limit; the event-list
    # backfill (Issue #464) stays at one request per three seconds.
    "mops.twse.com.tw": 3.0,
    # The old MOPS site serves the quarterly report pages (Issue #529).
    "mopsov.twse.com.tw": 3.0,
}
_host_last_request: dict[str, float] = {}


def _throttle_official_host(url: str) -> None:
    host = urlsplit(url).hostname or ""
    interval = OFFICIAL_HOST_MIN_INTERVAL_SECONDS.get(host)
    if not interval:
        return
    previous = _host_last_request.get(host)
    now = time.monotonic()
    if previous is not None and now - previous < interval:
        time.sleep(interval - (now - previous))
    _host_last_request[host] = time.monotonic()


def fetch_json(
    url: str,
    *,
    timeout_seconds: float = 30.0,
    method: str = "GET",
    data: Any = None,
    json_body: Any = None,
    text_fallback: bool = False,
) -> Any:
    """GET/POST one official endpoint and decode its JSON.

    ``text_fallback`` returns the bytes of a 200 answer that is not JSON
    instead of failing: TAIFEX ``DailyMarketReportFut`` answers a CSV
    (Issue #586), which its reader decodes.
    """

    headers = {"User-Agent": "taiwan-stock-research/0.1"}
    retry_limit = 3
    redirect_retry_limit = 6
    for attempt in range(redirect_retry_limit):
        _throttle_official_host(url)
        try:
            if method.upper() == "POST" and json_body is not None:
                response = httpx.post(
                    url, json=json_body, timeout=timeout_seconds, headers=headers
                )
            elif method.upper() == "POST":
                response = httpx.post(
                    url, data=data, timeout=timeout_seconds, headers=headers
                )
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
        retryable_redirect = response.status_code == 307 and not response.headers.get(
            "location"
        )
        if (
            retryable_redirect
            and attempt >= 2
            and url.startswith(TWSE_DAILY_HISTORY_ENDPOINT)
        ):
            # A short page warm-up gives TWSE's CDN a valid report context.  A
            # request made on the same Client then often receives the JSON
            # report even when the first edge response was a body-bearing 307.
            # The page itself is not ingested as market data.
            try:
                with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
                    client.get(TWSE_MI_INDEX_PAGE)
                    primed_response = client.get(url)
                if primed_response.status_code != 307 or primed_response.headers.get(
                    "location"
                ):
                    response = primed_response
                    retryable_redirect = False
            except httpx.TransportError:
                pass
        if (
            response.status_code == 429
            or response.status_code >= 500
            or retryable_redirect
        ):
            status_retry_limit = (
                redirect_retry_limit if retryable_redirect else retry_limit
            )
            if attempt + 1 >= status_retry_limit:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise OfficialDataError(
                        f"official endpoint retry exhausted ({response.status_code}): {url}"
                    ) from exc
            retry_after = response.headers.get("Retry-After")
            try:
                delay = (
                    max(0.0, min(2.0, float(retry_after)))
                    if retry_after
                    else 0.25 * (2**attempt)
                )
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
            if text_fallback:
                return response.content
            raise OfficialDataError(
                f"official endpoint returned non-JSON: {url}"
            ) from exc
    raise OfficialDataError(f"official endpoint retry budget exhausted: {url}")


def _encode_payload(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
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
    collected = collected_at or utcnow()
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
    collected = collected_at or utcnow()
    encoded = _encode_payload(payload)
    digest = hashlib.sha256(encoded).hexdigest()
    path = persist_raw_payload(
        source,
        endpoint,
        payload,
        data_as_of,
        collected_at=collected,
    )
    return FetchedPayload(
        source, endpoint, payload, data_as_of, collected, path, digest
    )


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
                year, month, day = (
                    int(digits[:3]) + 1911,
                    int(digits[3:5]),
                    int(digits[5:]),
                )
            else:
                return None
        if year < 1000:
            year += 1911
        return date(year, month, day)
    except (TypeError, ValueError):
        return None


TAIPEI_TZ = timezone(timedelta(hours=8))


def taipei_today() -> date:
    """Today's date in Taipei, the session a 21:30 daily collect asks for."""

    return datetime.now(TAIPEI_TZ).date()


def openapi_reported_date(payload: Any) -> date | None:
    """The one session a TPEx OpenAPI table reports, else None (Issue #579).

    The OpenAPI feeds have no date parameter and no report-level date: every
    row carries ``Date`` (ROC, ``1151109``).  A table is one session only when
    it has rows and every row names the same, readable date.
    """

    if not isinstance(payload, list):
        return None
    rows = [row for row in payload if isinstance(row, dict)]
    if not rows or len(rows) != len(payload):
        return None
    values = {str(row.get("Date") or "").strip() for row in rows}
    if len(values) != 1:
        return None
    return parse_roc_date(values.pop())


def _require_reported_date(payload: Any, requested_date: date, endpoint: str) -> None:
    """Reject date-report responses that silently fall back to the latest day."""

    if isinstance(payload, list) and not payload:
        # TPEx may return an empty list for a weekday with no historical
        # quote rows; its caller applies the range-level no-prior-session
        # guard.  A non-empty list still lacks a report date and fails below.
        return
    if isinstance(payload, list):
        # A TPEx OpenAPI table (Issue #579): the date is on every row, and
        # the rows must agree on one session.
        reported_date = openapi_reported_date(payload)
        if reported_date is None:
            raise OfficialDataError(
                f"official date report omitted its reported date: {endpoint}"
            )
        if reported_date != requested_date:
            raise OfficialDataError(
                f"official date report mismatch for {endpoint}: "
                f"requested {requested_date.isoformat()}, reported {reported_date.isoformat()}"
            )
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
            if (
                isinstance(table, dict)
                and isinstance(table.get("data"), list)
                and table["data"]
            ):
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


def _date_from_row(
    row: dict[str, Any], *keys: str, default: date | None = None
) -> date | None:
    return parse_roc_date(_text(row, *keys)) or default


def parse_suspended_symbols(payload: Any) -> set[str]:
    """Extract notice identifiers; the legacy name does not imply bar status.

    TPEx's current feed lists suspension/resumption announcements.  Symbol
    membership alone establishes neither an effective suspension interval nor
    a suspended bar, including when collection and bar dates match.
    """

    symbols: set[str] = set()
    for row in _rows(payload):
        symbol = _text(
            row, "SecuritiesCompanyCode", "Code", "Symbol", "霅隞??", "隞??"
        )
        if symbol:
            symbols.add(symbol)
    return symbols


def fetch_index_bar_months(
    source: str,
    exchange: str,
    fetcher: Callable[..., Any],
    end: date,
    captured: list[FetchedPayload],
) -> tuple[list[Any], list[FetchedPayload], list[str]]:
    """The collect's index daily K reports (worker.index_bars, Issue #552).

    The month of ``end`` (and the month before during the first week, so the
    last sessions of a month are read once more after it ends).  Every answer
    is kept as raw in ``captured``; failures are non-core warnings.
    """

    from .index_bars import collect_months, fetch_month

    def get(request: Any) -> Any:
        return _call_fetcher(
            fetcher, request.url, method=request.method, data=request.data
        )

    def capture(request: Any, payload: Any, data_as_of: str) -> FetchedPayload:
        item = capture_payload(source, request.url, payload, data_as_of)
        captured.append(item)
        return item

    bars: list[Any] = []
    payloads: list[FetchedPayload] = []
    warnings: list[str] = []
    for month in collect_months(end):
        result = fetch_month(exchange, month, get, capture)
        bars.extend(bar for bar in result.bars if bar.trading_date <= end)
        payloads.extend(result.payloads)
        warnings.extend(result.warnings)
    return bars, payloads, warnings


def _call_fetcher(
    fetcher: Callable[..., Any],
    url: str,
    *,
    method: str = "GET",
    data: Any = None,
    json_body: Any = None,
) -> Any:
    # ``json_body`` is passed only when given, so fetchers without the keyword
    # (fixtures, older callers) keep working for every other endpoint.
    extra = {} if json_body is None else {"json_body": json_body}
    try:
        return fetcher(url, method=method, data=data, **extra)
    except TypeError as exc:
        if extra:
            # Without its body the request would ask for another date.
            raise OfficialDataError(
                f"official endpoint failed: {url}: fetcher takes no JSON body"
            ) from exc
        # Fixture fetchers often expose a one-argument callable while the
        # production fetch_json also accepts a timeout keyword.
        try:
            return fetcher(url)
        except Exception as exc:
            raise OfficialDataError(f"official endpoint failed: {url}: {exc}") from exc
    except Exception as exc:
        raise OfficialDataError(f"official endpoint failed: {url}: {exc}") from exc


def normalize_etf_category(
    value: Any, *, symbol: str = "", name: str = ""
) -> str | None:
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
    if any(
        token in text_value
        for token in ("leveraged", "槓桿", "正2", "正三", "2x", "3x")
    ):
        return "leveraged"
    if any(token in text_value for token in ("bond", "債券", "債")):
        return "bond"
    if any(token in text_value for token in ("commodity", "商品", "黃金", "原油")):
        return "commodity"
    if any(token in text_value for token in ("dividend", "高股息", "股息", "配息")):
        return "dividend"
    if any(token in text_value for token in ("sector", "產業", "類股")):
        return "sector"
    if any(
        token in text_value
        for token in ("broad", "market", "大盤", "台灣50", "0050", "指數")
    ):
        return "broad_market"
    if "etf" in text_value or symbol.strip().upper().startswith("00"):
        return "thematic"
    return (
        "thematic"
        if any(category in text_value for category in ETF_CATEGORIES)
        else "thematic"
    )


def _is_recent_listing(
    as_of: date, listing_date: date | None, window_days: int = 60
) -> bool:
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
    return (
        len(upper) >= 5
        and upper.startswith("00")
        and upper[-1].isalpha()
        and upper[-1]
        in {
            "A",
            "C",
            "D",
            "K",
            "T",
            "U",
        }
    )


def is_common_stock_code(symbol: str) -> bool:
    """A four-digit code not starting with 0: an ordinary share on TWSE/TPEx.

    The daily quote tables keep a company's rows after it leaves the current
    issuer master (delisting, transfer to the other exchange, a listing the
    master has not propagated yet).  Those rows are not filtered by the
    master; the collector resolves them against stored instruments or records
    them as unmatched.  ETFs start with 0; preferred shares carry a letter;
    warrants, CBs, ETNs and most depositary receipts have five or more
    characters.
    """

    return (
        len(symbol) == 4
        and symbol.isdigit()
        and symbol[0] != "0"
        # TWSE numbers depositary receipts 91xx; they are not ordinary shares.
        and not symbol.startswith("91")
    )


def is_etf_code(symbol: str) -> bool:
    """An ETF code on TWSE/TPEx: ``00`` then digits, optionally one letter suffix.

    0050, 00878, 006208, 00679B, 00981A.  Like ordinary shares, an ETF keeps
    its quote rows after the ETF list drops it (a fund being wound up trades
    until its last day), so those rows are not filtered by the list either
    (Issue #393).  Warrants and ETNs start with 01-09 and are not matched.
    """

    body = symbol[:-1] if symbol[-1:].isalpha() and symbol[-1:].isupper() else symbol
    return 4 <= len(symbol) <= 6 and body.startswith("00") and body.isdigit()


def is_quoted_security_code(symbol: str) -> bool:
    """A quote row the collector keeps without a list entry: share or ETF."""

    return is_common_stock_code(symbol) or is_etf_code(symbol)


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
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


def _weekday_dates(start: date, end: date) -> Iterable[date]:
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            yield cursor
        cursor += timedelta(days=1)


def _official_non_trading_dates(payload: Any, start: date, end: date) -> set[date]:
    """Return only dates the official calendar explicitly marks closed.

    The classification is app.trading_calendar's, the one rule for every
    reader of the schedule; it also knows the make-up holiday rows (#294).
    """

    result: set[date] = set()
    for row in _rows(payload):
        holiday_date = _date_from_row(row, "Date", "\u65e5\u671f")
        if holiday_date is None or not start <= holiday_date <= end:
            continue
        name = _text(row, "Name", "\u540d\u7a31")
        description = _text(row, "Description", "\u8aaa\u660e")
        if classify(name, description) == "closed":
            result.add(holiday_date)
    return result


def _ensure_backfill_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start date must not be after end date")
    if (end - start).days > OFFICIAL_MAX_BACKFILL_DAYS:
        raise ValueError(
            f"official backfill is limited to {OFFICIAL_MAX_BACKFILL_DAYS} days"
        )


def _volume_from_row(row: dict[str, Any], *keys: str) -> int | None:
    """Read an exact nonnegative share count without losing its raw type."""

    for key in keys:
        raw = row.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        # The first nonblank alias owns the value, even when it is invalid.
        # A float has already lost its JSON lexical precision; do not guess.
        if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
            return None
        if isinstance(raw, int):
            return int(raw) if 0 <= raw <= 9223372036854775807 else None
        if isinstance(raw, str):
            raw = raw.strip()
            if not re.fullmatch(
                r"[+]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", raw
            ):
                return None
            raw = raw.replace(",", "")
        try:
            number = Decimal(raw)
            if (
                not number.is_finite()
                or not 0 <= number <= 9223372036854775807
                or number != number.to_integral_value()
            ):
                return None
            return int(number)
        except (InvalidOperation, OverflowError, ValueError):
            return None
    return None


def _turnover_from_row(
    row: dict[str, Any], *keys: str
) -> tuple[float, str, str | None]:
    raw = _text(row, *keys)
    if not raw or raw.upper() in {"--", "-", "X", "N/A", "無"} or set(raw) == {"-"}:
        return 0.0, "unavailable", "missing"
    # Money must be a complete, nonnegative number; parse_number intentionally
    # accepts numeric fragments and therefore cannot establish availability.
    if not re.fullmatch(
        r"\+?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?(?:[eE][+-]?\d+)?", raw
    ):
        return 0.0, "unavailable", "invalid"
    try:
        amount = float(Decimal(raw.replace(",", "")))
    except (InvalidOperation, OverflowError, ValueError):
        return 0.0, "unavailable", "invalid"
    if not math.isfinite(amount) or amount < 0:
        return 0.0, "unavailable", "invalid"
    return amount, "available", None


def parse_twse_daily_rows(
    payload: Any, *, data_as_of: str | None = None, payload_sha256: str | None = None
) -> list[BarRecord]:
    result: list[BarRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "Code", "證券代號", "股票代號")
        trading_date = _date_from_row(row, "Date", "日期")
        open_price = parse_number(_text(row, "OpeningPrice", "開盤價", "開盤"))
        high = parse_number(_text(row, "HighestPrice", "最高價", "最高"))
        low = parse_number(_text(row, "LowestPrice", "最低價", "最低"))
        close = parse_number(_text(row, "ClosingPrice", "收盤價", "收盤"))
        volume = _volume_from_row(row, "TradeVolume", "成交股數", "成交量")
        turnover, turnover_status, turnover_reason = _turnover_from_row(
            row, "TradeValue", "成交金額", "成交值"
        )
        if (
            not symbol
            or not trading_date
            or None in {open_price, high, low, close, volume}
        ):
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
                turnover_status=turnover_status,
                turnover_reason=turnover_reason,
                exchange="TWSE",
                source="twse",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_tpex_daily_rows(
    payload: Any, *, data_as_of: str | None = None, payload_sha256: str | None = None
) -> list[BarRecord]:
    result: list[BarRecord] = []
    for row in _rows(payload):
        symbol = _text(row, "SecuritiesCompanyCode", "證券代號", "代號")
        trading_date = _date_from_row(
            row, "Date", "資料日期", "日期", default=parse_roc_date(data_as_of)
        )
        open_price = parse_number(_text(row, "Open", "開盤"))
        high = parse_number(_text(row, "High", "最高"))
        low = parse_number(_text(row, "Low", "最低"))
        close = parse_number(_text(row, "Close", "收盤"))
        volume = _volume_from_row(row, "TradingShares", "成交股數", "成交量")
        turnover, turnover_status, turnover_reason = _turnover_from_row(
            row, "TransactionAmount", "成交金額", "成交金額(元)", "成交值"
        )
        if (
            not symbol
            or not trading_date
            or None in {open_price, high, low, close, volume}
        ):
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
                turnover_status=turnover_status,
                turnover_reason=turnover_reason,
                exchange="TPEx",
                source="tpex",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


# The price fields the bar parsers read, per exchange: open, high, low, close.
_TWSE_PRICE_KEYS = (
    ("OpeningPrice", "開盤價", "開盤"),
    ("HighestPrice", "最高價", "最高"),
    ("LowestPrice", "最低價", "最低"),
    ("ClosingPrice", "收盤價", "收盤"),
)
_TPEX_PRICE_KEYS = (
    ("Open", "開盤"),
    ("High", "最高"),
    ("Low", "最低"),
    ("Close", "收盤"),
)


def _blank_price(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    """True when the field is present and blank: empty or only dashes."""

    if not any(key in row for key in keys):
        return False
    raw = _text(row, *keys)
    return not raw or set(raw) == {"-"}


def _no_trade_rows(
    rows: Iterable[dict[str, Any]],
    *,
    exchange: str,
    source: str,
    symbol_keys: tuple[str, ...],
    price_keys: tuple[tuple[str, ...], ...],
    date_of: Any,
    data_as_of: str | None,
    payload_sha256: str | None,
) -> list[NoTradeRecord]:
    result: list[NoTradeRecord] = []
    for row in rows:
        symbol = _text(row, *symbol_keys)
        trading_date = date_of(row)
        if not symbol or not trading_date:
            continue
        # All four prices blank; a row with only some of them blank is
        # malformed and stays a gap rather than becoming no-trade evidence.
        if not all(_blank_price(row, keys) for keys in price_keys):
            continue
        result.append(
            NoTradeRecord(
                symbol=symbol,
                trading_date=trading_date,
                exchange=exchange,
                source=source,
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_twse_no_trade_rows(
    payload: Any, *, data_as_of: str | None = None, payload_sha256: str | None = None
) -> list[NoTradeRecord]:
    """The rows ``parse_twse_daily_rows`` drops because every price is blank."""

    return _no_trade_rows(
        _rows(payload),
        exchange="TWSE",
        source="twse",
        symbol_keys=("Code", "證券代號", "股票代號"),
        price_keys=_TWSE_PRICE_KEYS,
        date_of=lambda row: _date_from_row(row, "Date", "日期"),
        data_as_of=data_as_of,
        payload_sha256=payload_sha256,
    )


def parse_tpex_no_trade_rows(
    payload: Any, *, data_as_of: str | None = None, payload_sha256: str | None = None
) -> list[NoTradeRecord]:
    """The rows ``parse_tpex_daily_rows`` drops because every price is blank."""

    default_date = parse_roc_date(data_as_of)
    return _no_trade_rows(
        _rows(payload),
        exchange="TPEx",
        source="tpex",
        symbol_keys=("SecuritiesCompanyCode", "證券代號", "代號"),
        price_keys=_TPEX_PRICE_KEYS,
        date_of=lambda row: _date_from_row(
            row, "Date", "資料日期", "日期", default=default_date
        ),
        data_as_of=data_as_of,
        payload_sha256=payload_sha256,
    )


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
    normalized = {_normalized_field_name(key): value for key, value in row.items()}
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
            exact_keys=(
                "DealerBuySellDifference",
                "DealersBuySellDifference",
                "自營商買賣超股數",
            ),
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
        # array positions are the stable contract: margin previous=5,
        # current=6; short current=12 (Issue #662, 張).
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
                        margin_change=(current - previous)
                        if current is not None and previous is not None
                        else None,
                        short_balance=parse_number(values[12])
                        if len(values) > 12
                        else None,
                        exchange="TWSE",
                        source="twse_margin",
                        data_as_of=data_as_of or trading_date.isoformat(),
                        payload_sha256=payload_sha256,
                        margin_source="twse_margin",
                        margin_data_as_of=data_as_of or trading_date.isoformat(),
                        margin_payload_sha256=payload_sha256,
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
        short = _number_from_row(
            row,
            exact_keys=("ShortSaleBalance", "融券今日餘額"),
            contains=(("融券", "今日", "餘額"),),
        )
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                margin_balance=current,
                margin_change=(current - previous)
                if current is not None and previous is not None
                else None,
                short_balance=short,
                exchange="TWSE",
                source="twse_margin",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
                margin_source="twse_margin",
                margin_data_as_of=data_as_of or trading_date.isoformat(),
                margin_payload_sha256=payload_sha256,
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
        symbol = _text(
            row, "SecuritiesCompanyCode", "Code", "股票代號", "證券代號", "代號"
        )
        if not symbol:
            continue
        if TPEX_OPENAPI_INSTITUTIONAL_KEYS["foreign_buy"] in row:
            # An OpenAPI ``tpex_3insti_daily_trading`` row (Issue #579): the
            # website table's columns 4, 13, 22 and 23, by exact key only.
            # Several of its keys contain both "dealers" and "difference"
            # (the foreign dealers, and the foreign investors "Foreign Dealers
            # excluded"), so the token match below must not decide for it.
            foreign_buy, trust_buy, dealer_buy, total_buy_sell = (
                parse_number(row.get(TPEX_OPENAPI_INSTITUTIONAL_KEYS[name]))
                for name in ("foreign_buy", "trust_buy", "dealer_buy", "total_buy_sell")
            )
        else:
            foreign_buy = _number_from_row(
                row,
                exact_keys=(
                    "ForeignBuySellDifference",
                    "ForeignInvestorsDifference",
                    "Foreign-BuySellDifference",
                ),
                contains=(("foreign", "difference"), ("外資", "差額")),
            )
            trust_buy = _number_from_row(
                row,
                exact_keys=(
                    "SecuritiesInvestmentTrustCompaniesDifference",
                    "SecuritiesInvestmentTrustCompanies-BuySellDifference",
                    "InvestmentTrustDifference",
                ),
                contains=(
                    ("securitiesinvestmenttrustcompanies", "difference"),
                    ("investmenttrust", "difference"),
                    ("投信", "差額"),
                ),
            )
            dealer_buy = _number_from_row(
                row,
                exact_keys=("DealersDifference", "DealerDifference"),
                contains=(
                    ("dealers", "difference"),
                    ("dealer", "difference"),
                    ("自營商", "差額"),
                ),
            )
            total_buy_sell = None
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                foreign_buy=foreign_buy,
                trust_buy=trust_buy,
                dealer_buy=dealer_buy,
                total_buy_sell=total_buy_sell,
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
    # margin-balance values are positions 2 and 6 respectively, and the
    # short-sale balance (券餘額, 張) is position 14 (Issue #662).
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
                        margin_change=(current - previous)
                        if current is not None and previous is not None
                        else None,
                        short_balance=parse_number(values[14])
                        if len(values) > 14
                        else None,
                        exchange="TPEx",
                        source="tpex_margin",
                        data_as_of=data_as_of or trading_date.isoformat(),
                        payload_sha256=payload_sha256,
                        margin_source="tpex_margin",
                        margin_data_as_of=data_as_of or trading_date.isoformat(),
                        margin_payload_sha256=payload_sha256,
                    )
                )
            return result
    result: list[ChipRecord] = []
    for row in _rows(payload):
        symbol = _text(
            row, "SecuritiesCompanyCode", "Code", "股票代號", "證券代號", "代號"
        )
        if not symbol:
            continue
        if "MarginPurchaseBalance" in row or "MarginPurchaseBalancePreviousDay" in row:
            # An OpenAPI ``tpex_mainboard_margin_balance`` row (Issue #579):
            # exact keys only.  "marginpurchasebalance" is also a prefix of
            # the previous-day key, so the token match would read a blank
            # balance as the previous day's.
            previous = parse_number(row.get("MarginPurchaseBalancePreviousDay"))
            current = parse_number(row.get("MarginPurchaseBalance"))
            short = parse_number(row.get("ShortSaleBalance"))
        else:
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
            # Exact keys only: 券餘額 is also part of 前券餘額(張).
            short = _number_from_row(row, exact_keys=("ShortSaleBalance", "券餘額"))
        result.append(
            ChipRecord(
                symbol=symbol,
                trading_date=trading_date,
                margin_balance=current,
                margin_change=(current - previous)
                if current is not None and previous is not None
                else None,
                short_balance=short,
                exchange="TPEx",
                source="tpex_margin",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
                margin_source="tpex_margin",
                margin_data_as_of=data_as_of or trading_date.isoformat(),
                margin_payload_sha256=payload_sha256,
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
    """Merge two official same-day feeds without filling missing fields.

    A merged record keeps the margin capture in its ``margin_*`` fields; its
    ``payload_sha256`` stays the institutional capture's.
    """

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
                short_balance=record.short_balance,
                source=f"{existing.source}+{record.source}",
                margin_source=record.margin_source or record.source,
                margin_data_as_of=record.margin_data_as_of or record.data_as_of,
                margin_payload_sha256=record.margin_payload_sha256
                or record.payload_sha256,
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
            start_text = _text(
                row, "DateOfSuspendedTrading", "SuspendedTradingDate", "停牌日期"
            )
            resume_text = _text(
                row, "DateOfResumedTrading", "ResumedTradingDate", "復牌日期"
            )
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


# ---- capital reduction stops of trading (Issue #582) ----

TRADING_HALT_SOURCES = {"TWSE": "twse_twtauu", "TPEx": "tpex_revivt"}
# Days before and after the collect day whose resumptions the daily query
# covers: a stop of a few sessions that began before the day, and one
# published ahead of it.
TRADING_HALT_DAYS_BEFORE = 10
TRADING_HALT_DAYS_AFTER = 60
_REDUCTION_FIELDS = ("恢復買賣日期", "股票代號", "減資原因", "詳細資料")
_TWSE_REDUCTION_DETAIL = re.compile(r"\s*([0-9A-Z]+)\s*,\s*(\d{8})\s*")
_TPEX_DETAIL_DATE = r"\s*:?\s*(\d{2,3}/\d{1,2}/\d{1,2})"


def trading_halt_warning(exchange: str, exc: Exception) -> str:
    """The non-core warning for a table that could not be fetched, read or stored."""

    return f"{exchange} trading halts unavailable: {type(exc).__name__}: {exc}"


def reduction_query(exchange: str, start: date, end: date) -> str:
    """The endpoint with its range of resumption days."""

    if exchange == "TWSE":
        query = urlencode(
            {
                "startDate": start.strftime("%Y%m%d"),
                "endDate": end.strftime("%Y%m%d"),
                "response": "json",
            }
        )
        return f"{TWSE_REDUCTION_ENDPOINT}?{query}"
    query = urlencode(
        {
            "startDate": start.strftime("%Y/%m/%d"),
            "endDate": end.strftime("%Y/%m/%d"),
            "response": "json",
        }
    )
    return f"{TPEX_REDUCTION_ENDPOINT}?{query}"


def _reduction_columns(fields: Any, exchange: str) -> dict[str, int]:
    if not isinstance(fields, list):
        raise OfficialDataError(f"{exchange} capital reduction table has no fields")
    names = [str(item).strip() for item in fields]
    missing = [name for name in _REDUCTION_FIELDS if name not in names]
    if missing:
        raise OfficialDataError(
            f"{exchange} capital reduction table lacks {missing}: {names!r}"
        )
    return {name: names.index(name) for name in _REDUCTION_FIELDS}


def _reduction_row(row: Any, columns: dict[str, int], exchange: str) -> list[Any]:
    if not isinstance(row, list) or len(row) <= max(columns.values()):
        raise OfficialDataError(
            f"{exchange} capital reduction row is malformed: {row!r}"
        )
    return row


def parse_twse_reduction_payload(
    payload: Any,
    *,
    start: date,
    end: date,
    endpoint: str = TWSE_REDUCTION_ENDPOINT,
    payload_sha256: str | None = None,
) -> tuple[list[TradingHaltRecord], list[str]]:
    """Read TWSE ``TWTAUU`` (股票減資恢復買賣參考價格) for ``start``..``end``.

    ``stat`` 很抱歉，沒有符合條件的資料 is an empty range.  Each row's 詳細資料
    is ``<code>  ,<YYYYMMDD>``, the last trading day of the old shares; the
    stop begins the calendar day after it.  A row whose 詳細資料 names another
    code or no date, or whose last trading day is not before the resumption,
    is left out and named in the second list.  A table with other columns,
    another range or a resumption outside the range is rejected whole.
    """

    if not isinstance(payload, dict):
        raise OfficialDataError("TWSE capital reduction answer is not an object")
    stat = str(payload.get("stat") or "").strip()
    if stat != "OK":
        if "沒有符合條件" in stat:
            return [], []
        raise OfficialDataError(f"TWSE capital reduction stat {stat!r}")
    reported = (str(payload.get("strDate") or ""), str(payload.get("endDate") or ""))
    if reported != (start.strftime("%Y%m%d"), end.strftime("%Y%m%d")):
        raise OfficialDataError(
            f"TWSE capital reduction answered {reported} for {start}..{end}"
        )
    columns = _reduction_columns(payload.get("fields"), "TWSE")
    fields = [str(item).strip() for item in payload["fields"]]
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise OfficialDataError("TWSE capital reduction table has no data list")
    records: dict[tuple[str, date], TradingHaltRecord] = {}
    rejected: list[str] = []
    for raw in rows:
        row = _reduction_row(raw, columns, "TWSE")
        symbol = str(row[columns["股票代號"]] or "").strip()
        resume = parse_roc_date(row[columns["恢復買賣日期"]])
        if resume is None or not start <= resume <= end:
            raise OfficialDataError(
                f"TWSE capital reduction row {symbol} resumes "
                f"{row[columns['恢復買賣日期']]!r}, outside {start}..{end}"
            )
        detail = _TWSE_REDUCTION_DETAIL.fullmatch(str(row[columns["詳細資料"]] or ""))
        last_trade = parse_roc_date(detail.group(2)) if detail else None
        if (
            detail is None
            or detail.group(1) != symbol
            or last_trade is None
            or last_trade >= resume
        ):
            rejected.append(
                f"{symbol} resuming {resume}: 詳細資料 "
                f"{row[columns['詳細資料']]!r} names no earlier last trading day"
            )
            continue
        record = TradingHaltRecord(
            symbol=symbol,
            exchange="TWSE",
            halt_start=last_trade + timedelta(days=1),
            resume_date=resume,
            last_trade_date=last_trade,
            reason_detail=str(row[columns["減資原因"]] or "").strip() or None,
            endpoint=endpoint,
            source=TRADING_HALT_SOURCES["TWSE"],
            details=dict(zip(fields, row)),
            payload_sha256=payload_sha256,
        )
        previous = records.get((symbol, resume))
        if previous is not None and previous.halt_start != record.halt_start:
            raise OfficialDataError(
                f"TWSE capital reduction lists {symbol} resuming {resume} twice"
            )
        records[(symbol, resume)] = record
    return list(records.values()), rejected


def parse_tpex_reduction_payload(
    payload: Any,
    *,
    start: date,
    end: date,
    endpoint: str = TPEX_REDUCTION_ENDPOINT,
    payload_sha256: str | None = None,
) -> tuple[list[TradingHaltRecord], list[str]]:
    """Read TPEx ``revivt`` (減資恢復買賣) for ``start``..``end``.

    The 詳細資料 HTML names the code, 停止買賣日期 and 恢復買賣日期: the first
    and the resumption must be readable, the code and the resumption must
    match the row, and the stop must begin before the resumption, or the row
    is left out and named in the second list.  ``totalCount`` above the rows
    (a truncated answer), another range, other columns or a resumption
    outside the range reject the table whole.
    """

    if not isinstance(payload, dict) or not isinstance(payload.get("tables"), list):
        raise OfficialDataError("TPEx capital reduction answer has no tables")
    reported = str(payload.get("date") or "")
    if reported != f"{start:%Y%m%d}~{end:%Y%m%d}":
        raise OfficialDataError(
            f"TPEx capital reduction answered {reported!r} for {start}..{end}"
        )
    if len(payload["tables"]) != 1 or not isinstance(payload["tables"][0], dict):
        raise OfficialDataError("TPEx capital reduction answer is not one table")
    table = payload["tables"][0]
    columns = _reduction_columns(table.get("fields"), "TPEx")
    fields = [str(item).strip() for item in table["fields"]]
    rows = table.get("data")
    if not isinstance(rows, list):
        raise OfficialDataError("TPEx capital reduction table has no data list")
    total = table.get("totalCount")
    if total is not None and int(total) != len(rows):
        raise OfficialDataError(
            f"TPEx capital reduction totalCount {total} but {len(rows)} rows"
        )
    records: dict[tuple[str, date], TradingHaltRecord] = {}
    rejected: list[str] = []
    for raw in rows:
        row = _reduction_row(raw, columns, "TPEx")
        symbol = str(row[columns["股票代號"]] or "").strip()
        resume = parse_roc_date(row[columns["恢復買賣日期"]])
        if resume is None or not start <= resume <= end:
            raise OfficialDataError(
                f"TPEx capital reduction row {symbol} resumes "
                f"{row[columns['恢復買賣日期']]!r}, outside {start}..{end}"
            )
        text = html.unescape(
            re.sub(r"<[^>]+>", " ", str(row[columns["詳細資料"]] or ""))
        )
        text = text.replace("&nbsp", " ").replace("\xa0", " ")
        code = re.search(r"股票代號/股票名稱\s*:?\s*([0-9A-Z]+)", text)
        stopped = re.search("停止買賣日期" + _TPEX_DETAIL_DATE, text)
        resumed = re.search("恢復買賣日期" + _TPEX_DETAIL_DATE, text)
        halt_start = parse_roc_date(stopped.group(1)) if stopped else None
        detail_resume = parse_roc_date(resumed.group(1)) if resumed else None
        if (
            code is None
            or code.group(1) != symbol
            or halt_start is None
            or detail_resume != resume
            or halt_start >= resume
        ):
            rejected.append(
                f"{symbol} resuming {resume}: 詳細資料 names "
                f"code {code.group(1) if code else None}, 停止買賣日期 {halt_start}, "
                f"恢復買賣日期 {detail_resume}"
            )
            continue
        record = TradingHaltRecord(
            symbol=symbol,
            exchange="TPEx",
            halt_start=halt_start,
            resume_date=resume,
            last_trade_date=None,
            reason_detail=str(row[columns["減資原因"]] or "").strip() or None,
            endpoint=endpoint,
            source=TRADING_HALT_SOURCES["TPEx"],
            details=dict(zip(fields, row)),
            payload_sha256=payload_sha256,
        )
        previous = records.get((symbol, resume))
        if previous is not None and previous.halt_start != record.halt_start:
            raise OfficialDataError(
                f"TPEx capital reduction lists {symbol} resuming {resume} twice"
            )
        records[(symbol, resume)] = record
    return list(records.values()), rejected


def parse_reduction_payload(
    exchange: str,
    payload: Any,
    *,
    start: date,
    end: date,
    endpoint: str,
    payload_sha256: str | None = None,
) -> tuple[list[TradingHaltRecord], list[str]]:
    parse = (
        parse_twse_reduction_payload
        if exchange == "TWSE"
        else parse_tpex_reduction_payload
    )
    return parse(
        payload, start=start, end=end, endpoint=endpoint, payload_sha256=payload_sha256
    )


def fetch_reduction_window(
    fetch: Callable[[str, str | None], FetchedPayload],
    exchange: str,
    start: date,
    end: date,
    *,
    data_as_of: str,
) -> tuple[list[TradingHaltRecord], TradingHaltWindow, FetchedPayload]:
    """One request for the stops resuming ``start``..``end`` on ``exchange``.

    ``fetch(endpoint, data_as_of)`` captures the payload (an adapter's
    ``_fetch``); a failure to fetch or read it raises.
    """

    endpoint = reduction_query(exchange, start, end)
    captured = fetch(endpoint, data_as_of)
    records, rejected = parse_reduction_payload(
        exchange,
        captured.payload,
        start=start,
        end=end,
        endpoint=endpoint,
        payload_sha256=captured.sha256,
    )
    window = TradingHaltWindow(
        exchange=exchange,
        source=TRADING_HALT_SOURCES[exchange],
        endpoint=endpoint,
        start=start,
        end=end,
        payload_sha256=captured.sha256,
        rejected=tuple(rejected),
    )
    return records, window, captured


def collect_reduction_window(
    fetch: Callable[[str, str | None], FetchedPayload],
    exchange: str,
    day: date,
    warnings: list[str],
) -> tuple[list[TradingHaltRecord], list[TradingHaltWindow], list[FetchedPayload]]:
    """collect's request around ``day``; a failure is a non-core warning."""

    try:
        records, window, captured = fetch_reduction_window(
            fetch,
            exchange,
            day - timedelta(days=TRADING_HALT_DAYS_BEFORE),
            day + timedelta(days=TRADING_HALT_DAYS_AFTER),
            data_as_of=day.isoformat(),
        )
    except Exception as exc:
        warnings.append(trading_halt_warning(exchange, exc))
        return [], [], []
    return records, [window], [captured]


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
        return parse_twse_daily_rows(
            rows, data_as_of=data_as_of, payload_sha256=payload_sha256
        )
    return parse_twse_daily_rows(
        payload, data_as_of=data_as_of, payload_sha256=payload_sha256
    )


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

    for rows, report_date in _twse_all_daily_tables(payload, requested_date):
        parsed = parse_twse_daily_rows(
            rows,
            data_as_of=data_as_of or report_date.isoformat(),
            payload_sha256=payload_sha256,
        )
        if parsed:
            return parsed
    return []


def _twse_all_daily_tables(
    payload: Any, requested_date: date
) -> list[tuple[list[dict[str, Any]], date]]:
    """``MI_INDEX`` tables carrying a security-code field, rows dated.

    The table does not repeat the report date on each row, so it is injected.
    """

    if not isinstance(payload, dict):
        return []
    report_date = parse_roc_date(payload.get("date")) or requested_date
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return []
    result = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        fields = {str(field) for field in table.get("fields", []) if field is not None}
        if not fields.intersection({"證券代號", "股票代號", "Code"}):
            continue
        normalized = []
        for row in _rows(table):
            item = dict(row)
            item.setdefault("Date", report_date.isoformat())
            normalized.append(item)
        result.append((normalized, report_date))
    return result


def parse_twse_all_daily_no_trade_payload(
    payload: Any,
    *,
    requested_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> list[NoTradeRecord]:
    """Official no-trade rows of the ``MI_INDEX`` table the bars come from.

    Read from the first security table that yields bars, the same table
    ``parse_twse_all_daily_payload`` returns, so no-trade evidence and bars
    never come from different tables of one report.
    """

    for rows, report_date in _twse_all_daily_tables(payload, requested_date):
        as_of = data_as_of or report_date.isoformat()
        if parse_twse_daily_rows(rows, data_as_of=as_of, payload_sha256=payload_sha256):
            return parse_twse_no_trade_rows(
                rows, data_as_of=as_of, payload_sha256=payload_sha256
            )
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
    price_table_title = (
        "\u50f9\u683c\u6307\u6578(\u81fa\u7063\u8b49\u5238\u4ea4\u6613\u6240)"
    )
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
            turnover_status="unavailable",
            turnover_reason="synthetic_index",
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
            turnover_status="unavailable",
            turnover_reason="synthetic_index",
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
        open_price = parse_number(
            _text(row, "OpeningIndex", "\u958b\u76e4\u6307\u6578", "\u958b\u76e4")
        )
        high = parse_number(
            _text(row, "HighestIndex", "\u6700\u9ad8\u6307\u6578", "\u6700\u9ad8")
        )
        low = parse_number(
            _text(row, "LowestIndex", "\u6700\u4f4e\u6307\u6578", "\u6700\u4f4e")
        )
        close = parse_number(
            _text(row, "ClosingIndex", "\u6536\u76e4\u6307\u6578", "\u6536\u76e4")
        )
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
                turnover_status="unavailable",
                turnover_reason="synthetic_index",
                exchange="TWSE",
                source="twse_index",
                data_as_of=data_as_of or trading_date.isoformat(),
                payload_sha256=payload_sha256,
            )
        )
    return result


# ---- market summaries (Issue #275) ----

TWSE_MARKET_SUMMARY_SOURCE = "twse_mi_index"
TPEX_MARKET_SUMMARY_SOURCE = "tpex_mainborad_highlight"
TWSE_INDEX_NAME = "發行量加權股價指數"
TPEX_INDEX_NAME = "櫃買指數"
_ROC_TITLE_PREFIX = re.compile(r"^\d{3,4}年\d{1,2}月\d{1,2}日")
_HTML_TAG = re.compile(r"<[^>]*>")
_COUNT_TEXT = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
_COUNT = re.compile(_COUNT_TEXT)
_COUNT_WITH_LIMIT = re.compile(rf"({_COUNT_TEXT})\(({_COUNT_TEXT})\)")
_DECIMAL = re.compile(rf"[+-]?{_COUNT_TEXT}(?:\.\d+)?")


def market_summary_warning(exchange: str, trading_date: date, exc: Exception) -> str:
    """The non-core warning for a summary that could not be fetched or read."""

    return (
        f"{exchange} market summary unavailable for {trading_date.isoformat()}: "
        f"{type(exc).__name__}: {exc}"
    )


def _count(value: Any) -> int | None:
    """A non-negative count such as ``1,234``; any other shape is None."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text_value = str(value).strip()
    if not _COUNT.fullmatch(text_value):
        return None
    return int(text_value.replace(",", ""))


def _count_with_limit(value: Any) -> tuple[int | None, int | None]:
    """Split TWSE breadth ``247(3)``: 247 issues, 3 of them at the price limit."""

    text_value = "" if value is None else str(value).strip()
    match = _COUNT_WITH_LIMIT.fullmatch(text_value)
    if match:
        return _count(match.group(1)), _count(match.group(2))
    return _count(text_value), None


def _decimal(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text_value = str(value).strip()
        if not _DECIMAL.fullmatch(text_value):
            return None
        number = float(text_value.replace(",", ""))
    return number if math.isfinite(number) else None


def _positive(value: Any) -> float | None:
    number = _decimal(value)
    return number if number is not None and number > 0 else None


def _twse_signed_change(sign_cell: Any, points_cell: Any) -> float | None:
    """TWSE prints the sign as HTML (``<p style ='color:green'>-</p>``) beside
    unsigned points; an empty mark is a flat close, ``X`` or anything else is
    not a comparable change."""

    points = _decimal(points_cell)
    if sign_cell is None or points is None or points < 0:
        return None
    sign = _HTML_TAG.sub("", str(sign_cell)).strip()
    if sign == "+":
        return points
    if sign == "-":
        return -points
    if sign == "" and points == 0:
        return 0.0
    return None


def _report_table(
    tables: list[dict[str, Any]], title: str
) -> tuple[list[str], list[Any]] | None:
    """The one table with this title (its ROC date prefix removed), or None."""

    matches = [
        table
        for table in tables
        if _ROC_TITLE_PREFIX.sub("", re.sub(r"\s+", "", str(table.get("title") or "")))
        == title
    ]
    if len(matches) != 1:
        return None
    fields = matches[0].get("fields")
    data = matches[0].get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        return None
    return [str(item) for item in fields], data


def _report_row(
    table: tuple[list[str], list[Any]] | None, key_field: str, key: str
) -> dict[str, Any] | None:
    """The one row whose ``key_field`` is ``key``, by field name; None otherwise.

    A field the table repeats is dropped, so it reads as missing.
    """

    if table is None:
        return None
    fields, data = table
    if fields.count(key_field) != 1:
        return None
    position = fields.index(key_field)
    rows = [
        values
        for values in data
        if isinstance(values, (list, tuple))
        and len(values) == len(fields)
        and str(values[position]).strip() == key
    ]
    if len(rows) != 1:
        return None
    return {
        name: value for name, value in zip(fields, rows[0]) if fields.count(name) == 1
    }


def parse_twse_market_summary(
    payload: Any,
    *,
    requested_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> MarketSummaryRecord:
    """Read the TWSE market summary from the date-scoped MI_INDEX report.

    - 價格指數(臺灣證券交易所), row 發行量加權股價指數: close, signed change
      points and the official percentage.
    - 大盤統計資訊, row 總計(1~15): turnover of all securities in yuan.
    - 漲跌證券數合計, column 股票: advancers/decliners with their limit counts
      (``247(3)``), unchanged, unmatched and 無比價.

    Tables are selected by title, rows by label and values by field name, as
    the TAIEX parser does.  A missing or ambiguous table, row or field leaves
    its values None.  A report for another date, or one with none of the
    three tables, raises.
    """

    if not isinstance(payload, dict):
        raise OfficialDataError("TWSE MI_INDEX payload is not a report object")
    if parse_roc_date(payload.get("date")) != requested_date:
        raise OfficialDataError(
            f"TWSE MI_INDEX reported {payload.get('date')!r}, "
            f"requested {requested_date.isoformat()}"
        )
    raw_tables = payload.get("tables")
    tables = (
        [table for table in raw_tables if isinstance(table, dict)]
        if isinstance(raw_tables, list)
        else []
    )
    index_row = _report_row(
        _report_table(tables, "價格指數(臺灣證券交易所)"), "指數", TWSE_INDEX_NAME
    )
    total_row = _report_row(
        _report_table(tables, "大盤統計資訊"), "成交統計", "總計(1~15)"
    )
    breadth_table = _report_table(tables, "漲跌證券數合計")
    breadth_rows = {
        label: _report_row(breadth_table, "類型", label)
        for label in ("上漲(漲停)", "下跌(跌停)", "持平", "未成交", "無比價")
    }
    if index_row is None and total_row is None and not any(breadth_rows.values()):
        raise OfficialDataError(
            "TWSE MI_INDEX has no index, turnover or breadth table for "
            f"{requested_date.isoformat()}"
        )

    index_row = index_row or {}
    change = _twse_signed_change(index_row.get("漲跌(+/-)"), index_row.get("漲跌點數"))
    percent = _decimal(index_row.get("漲跌百分比(%)"))
    change_pct = round(percent / 100, 6) if percent is not None else None
    if change is not None and change_pct is not None and change * change_pct < 0:
        # The sign mark and the percentage disagree; neither is trusted.
        change = change_pct = None

    def stocks(label: str) -> Any:
        return (breadth_rows[label] or {}).get("股票")

    advancers, limit_up = _count_with_limit(stocks("上漲(漲停)"))
    decliners, limit_down = _count_with_limit(stocks("下跌(跌停)"))
    return MarketSummaryRecord(
        exchange="TWSE",
        trading_date=requested_date,
        index_name=TWSE_INDEX_NAME,
        index_close=_positive(index_row.get("收盤指數")),
        index_change=change,
        index_change_pct=change_pct,
        change_pct_method="official",
        turnover=_count((total_row or {}).get("成交金額(元)")),
        turnover_scope="twse_all_securities",
        advancers=advancers,
        decliners=decliners,
        unchanged=_count(stocks("持平")),
        limit_up=limit_up,
        limit_down=limit_down,
        unmatched=_count(stocks("未成交")),
        not_comparable=_count(stocks("無比價")),
        breadth_scope="twse_stocks",
        source=TWSE_MARKET_SUMMARY_SOURCE,
        data_as_of=data_as_of or requested_date.isoformat(),
        payload_sha256=payload_sha256,
    )


def parse_tpex_market_highlight(
    payload: Any,
    *,
    requested_date: date,
    data_as_of: str | None = None,
    payload_sha256: str | None = None,
) -> MarketSummaryRecord:
    """Read TPEx ``tpex_mainborad_highlight`` (上櫃股票市場現況).

    The feed has one row for the latest session.  ``Date`` is ROC
    (``1151022``) and must equal the requested session; an older row (not yet
    updated) is rejected, never mapped to another date.  ``DailyTradingValue``
    is in millions of yuan.  TPEx publishes no percentage, so it is derived
    from the previous close: ``IndexChange / (CloseIndex - IndexChange)``.
    """

    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or not isinstance(payload[0], dict)
    ):
        raise OfficialDataError("TPEx highlight did not contain exactly one row")
    row = payload[0]
    if parse_roc_date(row.get("Date")) != requested_date:
        raise OfficialDataError(
            f"TPEx highlight reported Date {row.get('Date')!r}, "
            f"requested {requested_date.isoformat()}"
        )
    close = _positive(row.get("CloseIndex"))
    change = _decimal(row.get("IndexChange"))
    change_pct = (
        round(change / (close - change), 6)
        if close is not None and change is not None and close - change > 0
        else None
    )
    millions = _count(row.get("DailyTradingValue"))
    return MarketSummaryRecord(
        exchange="TPEx",
        trading_date=requested_date,
        index_name=TPEX_INDEX_NAME,
        index_close=close,
        index_change=change,
        index_change_pct=change_pct,
        change_pct_method="derived",
        turnover=millions * 1_000_000 if millions is not None else None,
        turnover_scope="tpex_stocks",
        advancers=_count(row.get("PriceRiseCompanyNumbers")),
        decliners=_count(row.get("PriceDeclineCompanyNumbers")),
        unchanged=_count(row.get("PriceFlatCompanyNumbers")),
        limit_up=_count(row.get("LimitUpCompanyNumbers")),
        limit_down=_count(row.get("LimitDownCompanyNumbers")),
        unmatched=_count(row.get("UnmatchedCompanyNumbersSuspensionStocksIncluded")),
        not_comparable=None,
        breadth_scope="tpex_stocks",
        source=TPEX_MARKET_SUMMARY_SOURCE,
        data_as_of=data_as_of or requested_date.isoformat(),
        payload_sha256=payload_sha256,
    )


# ---- emerging-market roster (Issue #512) ----

_EMERGING_CODE = re.compile(r"[0-9A-Z]{4,6}")


def emerging_issuer_warning(exc: Exception) -> str:
    """The non-core warning for a roster that could not be fetched or read."""

    return f"TPEx emerging issuers unavailable: {type(exc).__name__}: {exc}"


def emerging_roster_date(payload: Any) -> date | None:
    """The roster's 資料日期: the ROC ``Date`` every row carries, or None.

    None when the payload is not a list of rows or the rows do not agree on
    one readable Date.  The raw capture stores this as its ``data_as_of``.
    """

    if not isinstance(payload, list) or not payload:
        return None
    if not all(isinstance(row, dict) for row in payload):
        return None
    dates = {parse_roc_date(row.get("Date")) for row in payload}
    if len(dates) != 1 or None in dates:
        return None
    (as_of,) = dates
    return as_of


def parse_tpex_emerging_issuers(
    payload: Any, *, requested_date: date, payload_sha256: str | None = None
) -> list[EmergingIssuerRecord]:
    """Read TPEx ``mopsfin_t187ap03_R`` (興櫃公司基本資料).

    Every row carries the roster's ROC ``Date`` (``1151105``); the rows must
    agree on it and it must not be after the requested day.  A row without a
    code of 4～6 digits or capitals, or without a short name, is left out; a
    code listed twice, or a roster with no readable row, is rejected whole.
    """

    rows = payload if isinstance(payload, list) else None
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise OfficialDataError("TPEx emerging roster is not a non-empty list of rows")
    as_of = emerging_roster_date(payload)
    if as_of is None:
        dates = {parse_roc_date(row.get("Date")) for row in rows}
        raise OfficialDataError(
            f"TPEx emerging roster rows do not share one Date: {sorted(map(str, dates))}"
        )
    if as_of > requested_date:
        raise OfficialDataError(
            f"TPEx emerging roster Date {as_of.isoformat()} is after "
            f"{requested_date.isoformat()}"
        )
    records: dict[str, EmergingIssuerRecord] = {}
    for row in rows:
        symbol = _text(row, "SecuritiesCompanyCode")
        name = _text(row, "CompanyAbbreviation")
        if not _EMERGING_CODE.fullmatch(symbol) or not name:
            continue
        if symbol in records:
            raise OfficialDataError(f"TPEx emerging roster lists {symbol} twice")
        records[symbol] = EmergingIssuerRecord(
            symbol=symbol,
            name=name,
            as_of_date=as_of,
            payload_sha256=payload_sha256,
        )
    if not records:
        raise OfficialDataError("TPEx emerging roster contained no readable company")
    return list(records.values())


# ---- monthly revenue snapshots (Issue #530) ----

MONTHLY_REVENUE_SOURCE = "mops_t187ap05"
# The field names of t187ap05_L／mopsfin_t187ap05_O (the MOPS t21sc03 pages
# use the same names without the group prefix).
REVENUE_FIELD = "營業收入-當月營收"
PRIOR_YEAR_REVENUE_FIELD = "營業收入-去年當月營收"
YOY_FIELD = "營業收入-去年同月增減(%)"
CUMULATIVE_REVENUE_FIELD = "累計營業收入-當月累計營收"


def monthly_revenue_warning(exchange: str, exc: Exception) -> str:
    """The non-core warning for a snapshot that could not be fetched, read or stored."""

    return f"{exchange} monthly revenue unavailable: {type(exc).__name__}: {exc}"


def parse_roc_month(value: Any) -> date | None:
    """``11509`` (ROC YYYMM) as the month's first day, or None."""

    digits = str(value or "").strip()
    if not re.fullmatch(r"\d{4,5}", digits):
        return None
    year, month = int(digits[:-2]) + 1911, int(digits[-2:])
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def month_end(month: date) -> date:
    return date(month.year, month.month, monthrange(month.year, month.month)[1])


def parse_monthly_revenue_rows(
    payload: Any,
    *,
    exchange: str,
    requested_date: date,
    payload_sha256: str | None = None,
) -> list[MonthlyRevenueRecord]:
    """Read ``t187ap05_L``／``mopsfin_t187ap05_O`` (每月營業收入彙總表).

    The feed carries one month (``資料年月``) and its table's ROC ``出表日期``,
    the availability date.  The rows must agree on the month; a row without a
    code of 4～6 digits or capitals is left out, one released after the
    requested day (a historical collect reading today's feed) is left out, and
    a code listed twice, a 出表日期 that is unreadable or not after the month,
    or a feed with no readable row is rejected whole.
    """

    rows = payload if isinstance(payload, list) else None
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise OfficialDataError(
            f"{exchange} monthly revenue is not a non-empty list of rows"
        )
    months = {parse_roc_month(row.get("資料年月")) for row in rows}
    if len(months) != 1 or None in months:
        raise OfficialDataError(
            f"{exchange} monthly revenue rows do not share one 資料年月: "
            f"{sorted(map(str, months))}"
        )
    (month,) = months
    assert month is not None
    records: dict[str, MonthlyRevenueRecord] = {}
    for row in rows:
        symbol = _text(row, "公司代號")
        if not _EMERGING_CODE.fullmatch(symbol):
            continue
        if symbol in records:
            raise OfficialDataError(f"{exchange} monthly revenue lists {symbol} twice")
        released = parse_roc_date(row.get("出表日期"))
        if released is None or released <= month_end(month):
            raise OfficialDataError(
                f"{exchange} monthly revenue {symbol} has 出表日期 "
                f"{row.get('出表日期')!r} for {month:%Y-%m}"
            )
        if released > requested_date:
            continue
        records[symbol] = MonthlyRevenueRecord(
            symbol=symbol,
            exchange=exchange,
            revenue_month=month,
            revenue=parse_number(row.get(REVENUE_FIELD)),
            prior_year_revenue=parse_number(row.get(PRIOR_YEAR_REVENUE_FIELD)),
            yoy=parse_number(row.get(YOY_FIELD)),
            cumulative_revenue=parse_number(row.get(CUMULATIVE_REVENUE_FIELD)),
            announcement_date=released,
            details={**row, "announcement_basis": "release_date"},
            source=MONTHLY_REVENUE_SOURCE,
            payload_sha256=payload_sha256,
        )
    if not records and not any(
        _EMERGING_CODE.fullmatch(_text(row, "公司代號")) for row in rows
    ):
        raise OfficialDataError(f"{exchange} monthly revenue contained no company")
    return list(records.values())


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
        symbol = _text(
            row,
            "Code",
            "SecuritiesCompanyCode",
            "\u516c\u53f8\u4ee3\u865f",
            "\u8b49\u5238\u4ee3\u865f",
        )
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
    return _disambiguate_event_titles(result)


def _announcement_time(record: EventRecord) -> str:
    raw = _text(record.details, "SpeechTime", "AnnouncementTime", "發言時間")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) in {5, 6}:
        digits = digits.zfill(6)
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"
    return raw


def _disambiguate_event_titles(records: list[EventRecord]) -> list[EventRecord]:
    """Keep distinct same-day announcements that share one subject line.

    MOPS can publish several different announcements with an identical
    subject for one issuer and day, while ``events`` is unique on
    (instrument, date, type, title).  Exact duplicates collapse to one row; the
    earliest announcement keeps its title and later ones get their
    announcement time appended, so a later re-fetch of the same feed never
    renames a row stored by an earlier run.
    """

    groups: dict[tuple[str, str, date, str, str], list[EventRecord]] = defaultdict(list)
    for record in records:
        groups[
            (
                record.exchange,
                record.symbol,
                record.event_date,
                record.event_type,
                record.title,
            )
        ].append(record)
    result: list[EventRecord] = []
    for group in groups.values():
        unique: dict[tuple[str, str], EventRecord] = {}
        for record in group:
            unique.setdefault(
                (_announcement_time(record), record.description or ""), record
            )
        ordered = sorted(
            unique.values(),
            key=lambda item: (_announcement_time(item), item.description or ""),
        )
        used_titles: set[str] = set()
        for index, record in enumerate(ordered):
            title = record.title
            if index:
                time_text = _announcement_time(record)
                title = (
                    f"{record.title}（發言時間 {time_text}）"
                    if time_text
                    else f"{record.title}（#{index + 1}）"
                )
                if title in used_titles:
                    title = f"{title}（#{index + 1}）"
            used_titles.add(title)
            result.append(
                replace(record, title=title) if title != record.title else record
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
        symbol = _text(
            row,
            "Code",
            "SecuritiesCompanyCode",
            "\u516c\u53f8\u4ee3\u865f",
            "\u8b49\u5238\u4ee3\u865f",
        )
        period_end, fiscal_period = _mops_period_end(row)
        if not symbol or period_end is None:
            continue
        result.append(
            FundamentalRecord(
                symbol=symbol,
                period_end=period_end,
                fiscal_period=fiscal_period,
                announcement_date=_date_from_row(
                    row, "AnnouncementDate", "Date", "\u51fa\u8868\u65e5\u671f"
                ),
                revenue=parse_number(_text(row, "Revenue", "\u71df\u696d\u6536\u5165")),
                eps=parse_number(
                    _text(
                        row,
                        "EPS",
                        "BasicEPS",
                        "\u57fa\u672c\u6bcf\u80a1\u76c8\u9918",
                        "\u57fa\u672c\u6bcf\u80a1\u76c8\u9918(\u5143)",
                    )
                ),
                roe=parse_number(
                    _text(row, "ROE", "\u80a1\u6771\u6b0a\u76ca\u5831\u916c\u7387")
                ),
                details=dict(row),
                exchange=exchange,
                payload_sha256=payload_sha256,
            )
        )
    return result


def _historical_event_coverage(end: date, source: str) -> dict[str, Any]:
    return {
        "status": "unsupported",
        "denominator": "date_scoped_event_queries",
        "verified_dates": [],
        "empty_dates": [],
        "unsupported_dates": [end.isoformat()],
        "observed_event_dates": [],
        "source": source,
        "reason": "historical backfill does not request current-only event feeds",
    }


def _chip_symbols(
    instruments: Iterable[InstrumentRecord], bars: Iterable[BarRecord]
) -> set[str]:
    """Chips are kept for the universe and for every share or ETF quote row."""

    return {item.symbol for item in instruments} | {
        bar.symbol for bar in bars if is_quoted_security_code(bar.symbol)
    }


def twse_universe_records(
    listed_payload: FetchedPayload,
    etf_payload: FetchedPayload,
    new_listing_payload: FetchedPayload,
    as_of: date,
) -> list[InstrumentRecord]:
    """Build the TWSE stock/ETF universe from the three official list captures.

    Also used by ``worker.instrument_repair`` on stored captures, so it does
    no I/O.
    """

    listed_rows = _rows(listed_payload.payload)
    etf_rows = _rows(etf_payload.payload)
    new_rows = _rows(new_listing_payload.payload)
    if not listed_rows and not etf_rows:
        raise OfficialDataError("TWSE universe payloads contained no instruments")

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
        instrument_type = (
            "ipo"
            if symbol in recent_codes
            or (listing_date and (as_of - listing_date).days <= 60)
            else "stock"
        )
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
    # newlisting keeps every listing since 2011; an older row whose company is
    # no longer in the master was delisted or moved, so it is not a listing.
    for row in new_rows:
        symbol = _text(row, "Code", "Symbol")
        listing_date = _date_from_row(row, "ApprovedListingDate", "ListingDate")
        if (
            not symbol
            or not _is_recent_listing(as_of, listing_date)
            or symbol in records
        ):
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
    return normalized_records


class TwseAdapter:
    source = "twse"

    def __init__(
        self,
        fetcher: Callable[..., Any] = fetch_json,
        *,
        stock_day_capture=None,
        holiday_capture=None,
        snapshot_feeds: bool = True,
    ) -> None:
        self.fetcher = fetcher
        # Historical backfill sets snapshot_feeds=False: the current-only
        # feeds (STOCK_DAY_ALL, OpenAPI index, TWT48U, MOPS lists) describe
        # today, not the requested session, so they are not re-fetched for
        # every historical date.  The authoritative universe is then fetched
        # once per adapter instance; it is today's list either way.
        self.snapshot_feeds = snapshot_feeds
        self._universe_cache: (
            tuple[list[InstrumentRecord], list[FetchedPayload]] | None
        ) = None
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
        # Read from the same MI_INDEX captures as the TAIEX bars (Issue #275).
        self.market_summaries: list[MarketSummaryRecord] = []

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

    def fetch_universe(
        self, as_of: date
    ) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        listed_payload = self._fetch(TWSE_LISTED_ENDPOINT, as_of.isoformat())
        etf_payload = self._fetch(TWSE_ETF_ENDPOINT, as_of.isoformat())
        new_listing_payload = self._fetch(TWSE_NEW_LISTING_ENDPOINT, as_of.isoformat())
        return twse_universe_records(
            listed_payload, etf_payload, new_listing_payload, as_of
        ), [listed_payload, etf_payload, new_listing_payload]

    def fetch_bars(
        self, symbols: Iterable[str], start: date, end: date
    ) -> tuple[list[BarRecord], list[FetchedPayload]]:
        _ensure_backfill_window(start, end)
        self.fetch_warnings = []
        self.no_data_dates = []
        self.market_summaries = []
        self.stock_day_unavailable = []
        self.holiday_unknown = []
        self.holiday_closed_dates = set()
        symbol_list = list(dict.fromkeys(symbols))
        if not symbol_list:
            return [], []
        wanted = set(symbol_list)
        payloads: list[FetchedPayload] = []
        bars: list[BarRecord] = []
        # STOCK_DAY_ALL is the official OpenAPI daily all-securities feed.  It
        # includes listed ETFs in practice and is the cheapest current-day
        # request.  For historical dates, the official MI_INDEX report also
        # contains one all-security table; use one request per weekday rather
        # than one STOCK_DAY request per symbol and month.
        daily_payload: FetchedPayload | None = None
        if not self.snapshot_feeds and self.stock_day_capture is None:
            daily_bars = []
        elif self.stock_day_capture is None:
            daily_payload = self._fetch(TWSE_DAILY_ENDPOINT, end.isoformat())
            daily_bars = [
                bar
                for bar in parse_twse_daily_rows(
                    daily_payload.payload,
                    data_as_of=end.isoformat(),
                    payload_sha256=daily_payload.sha256,
                )
                if start <= bar.trading_date <= end
                and (bar.symbol in wanted or is_quoted_security_code(bar.symbol))
            ]
        else:
            daily_bars, daily_payload, self.stock_day_unavailable = (
                self.stock_day_capture.select(symbol_list, end)
            )
            self.captured_payloads.append(daily_payload)
            for unavailable in self.stock_day_unavailable:
                self.fetch_warnings.append(
                    "stock_day_capture_unavailable:"
                    + json.dumps(unavailable, sort_keys=True)
                )
            for bar in daily_bars:
                if bar.turnover_status == "unavailable":
                    self.fetch_warnings.append(
                        "stock_day_capture_turnover_unavailable:"
                        + json.dumps(
                            {"symbol": bar.symbol, "reason": bar.turnover_reason},
                            sort_keys=True,
                        )
                    )
        if daily_payload is not None:
            payloads.append(daily_payload)
        bars.extend(daily_bars)
        closed_dates: set[date] = set()
        if start != end:
            # The official holiday feed is used only as a positive exclusion
            # list.  If it is unavailable, do not infer a holiday; the normal
            # MI_INDEX request remains fail-closed for that date.
            if self.holiday_capture is None:
                try:
                    holiday_payload = self._fetch(
                        TWSE_HOLIDAY_ENDPOINT, end.isoformat()
                    )
                except OfficialDataError as exc:
                    holiday_payload = None
                    self.fetch_warnings.append(
                        "TWSE holiday calendar unavailable; no non-trading date was inferred: "
                        f"{exc}"
                    )
                if holiday_payload is not None:
                    payloads.append(holiday_payload)
                    closed_dates = _official_non_trading_dates(
                        holiday_payload.payload, start, end
                    )
            else:
                closed_dates, holiday_payload, self.holiday_unknown = (
                    self.holiday_capture.select(start, end)
                )
                self.captured_payloads.append(holiday_payload)
                payloads.append(holiday_payload)
                self.holiday_closed_dates = closed_dates
                for unknown in self.holiday_unknown:
                    self.fetch_warnings.append(
                        "holiday_capture_unknown:" + json.dumps(unknown, sort_keys=True)
                    )
                # Check all observed daily rows, including securities outside
                # the selected universe. The calendar cannot erase an already
                # visible valid trading observation for a supposedly closed day.
                if daily_payload is not None:
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
                if start <= bar.trading_date <= end
                and (bar.symbol in wanted or is_quoted_security_code(bar.symbol))
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
            self._read_market_summary(payload, trading_date)

        # Keep the newest occurrence for a symbol/day; a current all-feed row
        # and a month-history row are the same official observation.
        unique = {(bar.exchange, bar.symbol, bar.trading_date): bar for bar in bars}
        return list(unique.values()), payloads

    def _read_market_summary(self, payload: FetchedPayload, trading_date: date) -> None:
        # Display only: a summary that cannot be read is a non-core warning and
        # never holds back the session's bars.
        try:
            self.market_summaries.append(
                parse_twse_market_summary(
                    payload.payload,
                    requested_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=payload.sha256,
                )
            )
        except Exception as exc:
            self.fetch_warnings.append(
                market_summary_warning("TWSE", trading_date, exc)
            )

    def _check_holiday_conflicts(self, bars: Iterable[BarRecord]) -> None:
        for bar in bars:
            if bar.trading_date not in self.holiday_closed_dates:
                continue
            prices = (bar.open, bar.high, bar.low, bar.close)
            valid = all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0
                for value in prices
            )
            if (
                valid
                and bar.low <= bar.open <= bar.high
                and bar.low <= bar.close <= bar.high
            ):
                raise OfficialDataError(
                    "holiday_capture_trading_conflict:"
                    + bar.trading_date.isoformat()
                    + ":"
                    + bar.symbol
                )

    def fetch_actions(
        self, as_of: date
    ) -> tuple[list[ActionRecord], list[FetchedPayload]]:
        payload = self._fetch(TWSE_ACTION_ENDPOINT, as_of.isoformat())
        return parse_twse_action_rows(
            payload.payload, as_of=as_of, payload_sha256=payload.sha256
        ), [payload]

    def fetch_action_history(
        self, start: date, end: date
    ) -> tuple[list[ActionRecord], list[FetchedPayload], list[str]]:
        """Every TWSE ex-right/ex-dividend event dated ``start``..``end`` (#386).

        TWT49U gives the official prices and the combined 權值+息值 of each
        event; a row that is an ex-right (權 or 權息) also needs its
        TWT49UDetail breakdown.  An event whose detail cannot be read is
        left out with a warning instead of being written half known.
        """
        records: list[ActionRecord] = []
        payloads: list[FetchedPayload] = []
        warnings: list[str] = []
        for window_start, window_end in _month_windows(start, end):
            query = urlencode(
                {
                    "startDate": window_start.strftime("%Y%m%d"),
                    "endDate": window_end.strftime("%Y%m%d"),
                    "response": "json",
                }
            )
            payload = self._fetch(
                f"{TWSE_ACTION_HISTORY_ENDPOINT}?{query}",
                _covered_dates(window_start, window_end),
            )
            payloads.append(payload)
            for row in parse_twse_action_history(
                payload.payload, start=window_start, end=window_end
            ):
                detail = None
                detail_sha256 = None
                if "權" in row["kind"]:
                    detail_query = urlencode(
                        {
                            "STK_NO": row["symbol"],
                            "T1": row["action_date"].strftime("%Y%m%d"),
                            "response": "json",
                        }
                    )
                    try:
                        detail_payload = self._fetch(
                            f"{TWSE_ACTION_DETAIL_ENDPOINT}?{detail_query}",
                            row["action_date"].isoformat(),
                        )
                    except OfficialDataError as exc:
                        warnings.append(
                            "TWSE TWT49UDetail unavailable for "
                            f"{row['symbol']} {row['action_date'].isoformat()}: {exc}"
                        )
                        continue
                    payloads.append(detail_payload)
                    detail = parse_twse_action_detail(
                        detail_payload.payload, row["symbol"]
                    )
                    if detail is None:
                        warnings.append(
                            "TWSE TWT49UDetail has no row for "
                            f"{row['symbol']} {row['action_date'].isoformat()}"
                        )
                        continue
                    detail_sha256 = detail_payload.sha256
                records.append(
                    twse_action_history_record(
                        row,
                        detail,
                        payload_sha256=payload.sha256,
                        detail_sha256=detail_sha256,
                    )
                )
        return records, payloads, warnings

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

    def fetch_index_history(
        self, start: date, end: date
    ) -> tuple[list[BarRecord], list[FetchedPayload]]:
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

    def fetch_institutional_file(self, trading_date: date) -> FetchedPayload:
        """One request: the session's T86 institutional file (all securities)."""

        # TWSE RWD reports use compact YYYYMMDD query dates.  TPEx's newer
        # POST pages use slashes and are handled in TpexAdapter.
        query = {
            "date": trading_date.strftime("%Y%m%d"),
            "selectType": "ALL",
            "response": "json",
        }
        return self._fetch(
            f"{TWSE_CHIP_ENDPOINT}?{urlencode(query)}", trading_date.isoformat()
        )

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
            date_text = trading_date.strftime("%Y%m%d")
            margin_endpoint = f"{TWSE_MARGIN_HISTORY_ENDPOINT}?{urlencode({'date': date_text, 'selectType': 'ALL', 'response': 'json'})}"
            try:
                chip_payload = self.fetch_institutional_file(trading_date)
                payloads.append(chip_payload)
                _require_reported_date(
                    chip_payload.payload, trading_date, TWSE_CHIP_ENDPOINT
                )
                parsed = parse_twse_institutional_rows(
                    chip_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=chip_payload.sha256,
                )
                institutional.extend(
                    item for item in parsed if item.symbol in allowed_symbols
                )
                if not parsed:
                    warnings.append(
                        f"TWSE institutional chip feed returned no rows for {trading_date.isoformat()}"
                    )
            except OfficialDataError as exc:
                warnings.append(
                    f"TWSE institutional chips unavailable for {trading_date.isoformat()}: {exc}"
                )
            try:
                margin_payload = self._fetch(margin_endpoint, trading_date.isoformat())
                payloads.append(margin_payload)
                _require_reported_date(
                    margin_payload.payload, trading_date, TWSE_MARGIN_HISTORY_ENDPOINT
                )
                parsed = parse_twse_margin_rows(
                    margin_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=margin_payload.sha256,
                )
                margin.extend(item for item in parsed if item.symbol in allowed_symbols)
                if not parsed:
                    warnings.append(
                        f"TWSE margin feed returned no rows for {trading_date.isoformat()}"
                    )
            except OfficialDataError as exc:
                warnings.append(
                    f"TWSE margin chips unavailable for {trading_date.isoformat()}: {exc}"
                )
        return (
            merge_chip_records(
                institutional, margin, allowed_symbols=allowed_symbols, exchange="TWSE"
            ),
            payloads,
            warnings,
        )

    def _universe(
        self, as_of: date
    ) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        if self.snapshot_feeds:
            return self.fetch_universe(as_of)
        if self._universe_cache is None:
            self._universe_cache = self.fetch_universe(as_of)
        else:
            self.captured_payloads.extend(self._universe_cache[1])
        return self._universe_cache

    def fetch(self, start: date, end: date) -> OfficialBatch:
        self.captured_payloads = []
        self.fetch_warnings = []
        self.no_data_dates = []
        instruments, universe_payloads = self._universe(end)
        bars, bar_payloads = self.fetch_bars(
            (item.symbol for item in instruments), start, end
        )
        chip_dates = {bar.trading_date for bar in bars if bar.symbol != "TAIEX"}
        chips, chip_payloads, chip_warnings = self.fetch_chips(
            chip_dates, _chip_symbols(instruments, bars)
        )
        index_record = InstrumentRecord(
            "TAIEX", "TAIEX", exchange="TWSE", instrument_type="index", industry="Index"
        )
        warnings: list[str] = list(self.fetch_warnings) + list(chip_warnings)
        if not self.snapshot_feeds:
            return OfficialBatch(
                instruments=instruments + [index_record],
                bars=bars,
                chips=chips,
                payloads=universe_payloads + bar_payloads + chip_payloads,
                warnings=warnings,
                data_as_of=end.isoformat(),
                no_data_dates=sorted(set(self.no_data_dates)),
                event_coverage=_historical_event_coverage(
                    end, "TWSE MOPS material-information feed"
                ),
                snapshot_feeds=False,
                market_summaries=list(self.market_summaries),
            )
        actions, action_payloads = self.fetch_actions(end)
        # TAIEX is parsed from each date-validated MI_INDEX payload in
        # fetch_bars.  The current OpenAPI index is only a fallback when that
        # report had no TAIEX row for the end date; it is not requested for a
        # verified no-data date, where it would describe another session.
        index_bars: list[BarRecord] = []
        index_payloads: list[FetchedPayload] = []
        has_end_taiex = any(
            bar.symbol == "TAIEX" and bar.trading_date == end for bar in bars
        )
        if not has_end_taiex and end not in self.no_data_dates:
            index_bars, index_payloads = self.fetch_index(end)
            index_bars = [bar for bar in index_bars if start <= bar.trading_date <= end]
            self._check_holiday_conflicts(index_bars)
        events: list[EventRecord] = []
        fundamentals: list[FundamentalRecord] = []
        mops_payloads: list[FetchedPayload] = []
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
            fundamental_payload = self._fetch(
                TWSE_FUNDAMENTAL_ENDPOINT, end.isoformat()
            )
            mops_payloads.append(fundamental_payload)
            fundamentals = [
                fundamental
                for fundamental in parse_mops_fundamental_rows(
                    fundamental_payload.payload,
                    exchange="TWSE",
                    payload_sha256=fundamental_payload.sha256,
                )
                if not fundamental.announcement_date
                or fundamental.announcement_date <= end
            ]
        except OfficialDataError as exc:
            warnings.append(f"TWSE MOPS fundamentals unavailable: {exc}")
        monthly_revenues: list[MonthlyRevenueRecord] = []
        try:
            revenue_payload = self._fetch(
                TWSE_MONTHLY_REVENUE_ENDPOINT, end.isoformat()
            )
            mops_payloads.append(revenue_payload)
            monthly_revenues = parse_monthly_revenue_rows(
                revenue_payload.payload,
                exchange="TWSE",
                requested_date=end,
                payload_sha256=revenue_payload.sha256,
            )
        except Exception as exc:
            warnings.append(monthly_revenue_warning("TWSE", exc))
        trading_halts, trading_halt_windows, halt_payloads = collect_reduction_window(
            self._fetch, "TWSE", end, warnings
        )
        mops_payloads.extend(halt_payloads)
        index_daily_bars: list[Any] = []
        index_daily_payloads: list[FetchedPayload] = []
        if end not in self.no_data_dates:
            index_daily_bars, index_daily_payloads, index_warnings = (
                fetch_index_bar_months(
                    self.source, "TWSE", self.fetcher, end, self.captured_payloads
                )
            )
            warnings.extend(index_warnings)
        event_coverage = {
            "status": "unsupported",
            "denominator": "date_scoped_event_queries",
            "verified_dates": [],
            "empty_dates": [],
            "unsupported_dates": [end.isoformat()],
            "observed_event_dates": sorted(
                {item.event_date.isoformat() for item in events}
            ),
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
            payloads=universe_payloads
            + bar_payloads
            + chip_payloads
            + action_payloads
            + index_payloads
            + mops_payloads
            + index_daily_payloads,
            warnings=warnings,
            data_as_of=end.isoformat(),
            no_data_dates=sorted(set(self.no_data_dates)),
            event_coverage=event_coverage,
            market_summaries=list(self.market_summaries),
            monthly_revenues=monthly_revenues,
            trading_halts=trading_halts,
            trading_halt_windows=trading_halt_windows,
            index_daily_bars=index_daily_bars,
        )


def tpex_universe_records(
    listed_payload: FetchedPayload, etf_payload: FetchedPayload, as_of: date
) -> list[InstrumentRecord]:
    """Build the TPEx stock/ETF universe from the issuer master and ETF list.

    Also used by ``worker.instrument_repair`` on stored captures; no I/O.
    """

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
            instrument_type="ipo"
            if _is_recent_listing(as_of, listing_date)
            else "stock",
            listing_date=listing_date,
            industry=_text(row, "SecuritiesIndustryCode", "Industry", "產業別") or None,
            payload_sha256=listed_payload.sha256,
        )
    for row in etf_rows:
        symbol = _text(row, "stockNo", "StockNo", "Code", "代號")
        name = _text(row, "stockName", "StockName", "Name", "名稱") or symbol
        if not symbol:
            continue
        listing_date = _date_from_row(
            row, "listingDate", "ListingDate", "DateOfListing", "上市日期"
        )
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
    return list(records.values())


class TpexAdapter:
    source = "tpex"

    def __init__(
        self,
        fetcher: Callable[..., Any] = fetch_json,
        *,
        snapshot_feeds: bool = True,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.captured_payloads: list[FetchedPayload] = []
        self.no_data_dates: list[date] = []
        # See TwseAdapter: historical backfill skips current-only feeds and
        # reuses one universe fetch per adapter instance.
        self.snapshot_feeds = snapshot_feeds
        self._universe_cache: (
            tuple[list[InstrumentRecord], list[FetchedPayload]] | None
        ) = None
        # The Taipei date the OpenAPI tables are expected to report (Issue
        # #579); injectable so a test or a copy rehearsal can name the session.
        self.today = today or taipei_today
        # Per feed of the last fetch: which endpoint was read and why.
        self.feed_sources: dict[str, Any] = {}
        self.current_warnings: list[str] = []
        self._current_quote_payload: FetchedPayload | None = None

    def current_session(self, start: date, end: date) -> date | None:
        """The session whose quotes, institutional and margin come from OpenAPI.

        Only a one-day snapshot collect of today's Taipei date (the daily
        collect and its 23:00 retry): the OpenAPI tables carry the latest
        session only.  Catch-up and backfill (``snapshot_feeds=False``), a
        range, or an earlier date read the website reports (#555 決定 B).
        """

        if self.snapshot_feeds and start == end == self.today():
            return end
        return None

    def _fetch_current(
        self, feed: str, session: date
    ) -> tuple[FetchedPayload | None, bool]:
        """One OpenAPI table of ``session``: (capture, whether it is that session's).

        An unavailable table or one of another session is recorded in
        ``feed_sources`` and the caller reads the website report instead; a
        quote or institutional fallback is also a non-core warning, a margin
        one is not (the OpenAPI margin table is published after 21:30 on most
        days, #555 P1/P2).  The capture is kept either way; its ``data_as_of``
        is the requested session, so a reader's reported-date check rejects
        a table of another session.
        """

        openapi, website = TPEX_CURRENT_FEEDS[feed]
        try:
            captured = self._fetch(openapi, session.isoformat())
        except OfficialDataError as exc:
            self._fallback(feed, session, "openapi_unavailable", error=str(exc))
            return None, False
        reported = openapi_reported_date(captured.payload)
        if reported != session:
            self._fallback(
                feed,
                session,
                "openapi_not_current",
                reported=reported.isoformat() if reported else None,
                payload_sha256=captured.sha256,
            )
            return captured, False
        self.feed_sources[feed] = {
            "source": "openapi",
            "endpoint": openapi,
            "reported_date": reported.isoformat(),
            "payload_sha256": captured.sha256,
        }
        return captured, True

    def _fallback(
        self,
        feed: str,
        session: date,
        reason: str,
        *,
        reported: str | None = None,
        payload_sha256: str | None = None,
        error: str | None = None,
    ) -> None:
        openapi, website = TPEX_CURRENT_FEEDS[feed]
        self.feed_sources[feed] = {
            "source": "website",
            "endpoint": website,
            "reason": reason,
            "openapi_endpoint": openapi,
            "openapi_reported_date": reported,
            "openapi_payload_sha256": payload_sha256,
            "openapi_error": error,
        }
        if feed == "margin":
            return
        detail = (
            f"reported {reported or 'no single date'}"
            if reason == "openapi_not_current"
            else f"unavailable: {error}"
        )
        self.current_warnings.append(
            f"TPEx OpenAPI {feed} not used for {session.isoformat()} ({detail}); "
            f"read {website}"
        )

    def _managed_stock_check(self, universe_payloads: list[FetchedPayload]) -> None:
        """A non-core warning when a 管理股票 is not in the OpenAPI quote table.

        The website report has a separate 管理股票 table; whether the OpenAPI
        table lists those stocks has not been observed (no TPEx stock has been
        in industry 80 since 2024-09, Issue #579).  The source is not changed.
        """

        quotes = self._current_quote_payload
        listed = next(
            (p for p in universe_payloads if p.endpoint == TPEX_LISTED_ENDPOINT), None
        )
        if quotes is None or listed is None:
            return
        managed = sorted(
            code
            for row in _rows(listed.payload)
            if _text(row, "SecuritiesIndustryCode") == TPEX_MANAGED_INDUSTRY_CODE
            and (code := _text(row, "SecuritiesCompanyCode"))
        )
        quoted = {_text(row, "SecuritiesCompanyCode") for row in _rows(quotes.payload)}
        missing = [code for code in managed if code not in quoted]
        self.feed_sources["quotes"]["managed_stocks"] = managed
        self.feed_sources["quotes"]["managed_stocks_missing"] = missing
        if missing:
            self.current_warnings.append(
                "TPEx OpenAPI quotes omit managed stocks (industry "
                f"{TPEX_MANAGED_INDUSTRY_CODE}) listed by {TPEX_LISTED_ENDPOINT}: "
                + ",".join(missing)
            )

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

    def _fetch_authoritative_universe(
        self, as_of: date
    ) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        """Build TPEx scope from MOPS stock master plus the ETF allowlist.

        The daily quote table is intentionally not a universe source: it also
        contains warrants, ETNs, bonds, and other products.  It is fetched by
        ``fetch_bars`` and filtered to these records plus ordinary-share codes
        and ETF codes (``is_quoted_security_code``).
        """

        listed_payload = self._fetch(TPEX_LISTED_ENDPOINT, as_of.isoformat())
        etf_payload = self._fetch(
            TPEX_ETF_ENDPOINT,
            as_of.isoformat(),
            method="POST",
            data={"response": "json"},
        )
        return tpex_universe_records(listed_payload, etf_payload, as_of), [
            listed_payload,
            etf_payload,
        ]

    def fetch_universe(
        self, as_of: date
    ) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        return self._fetch_authoritative_universe(as_of)

    def _universe(
        self, as_of: date
    ) -> tuple[list[InstrumentRecord], list[FetchedPayload]]:
        if self.snapshot_feeds:
            return self.fetch_universe(as_of)
        if self._universe_cache is None:
            self._universe_cache = self.fetch_universe(as_of)
        else:
            self.captured_payloads.extend(self._universe_cache[1])
        return self._universe_cache

    def fetch_bars(
        self,
        symbols: Iterable[str],
        start: date,
        end: date,
        *,
        current_session: date | None = None,
    ) -> tuple[list[BarRecord], list[FetchedPayload]]:
        _ensure_backfill_window(start, end)
        self.no_data_dates = []
        wanted = set(symbols)
        if not wanted:
            return [], []
        bars: list[BarRecord] = []
        payloads: list[FetchedPayload] = []
        historical_bar_dates: set[date] = set()
        if current_session is not None:
            # ``current_session`` is a one-day range (``current_session()``).
            current, usable = self._fetch_current("quotes", current_session)
            if current is not None:
                payloads.append(current)
            if usable:
                self._current_quote_payload = current
                bars = [
                    bar
                    for bar in parse_tpex_daily_rows(
                        current.payload,
                        data_as_of=current_session.isoformat(),
                        payload_sha256=current.sha256,
                    )
                    if (bar.symbol in wanted or is_quoted_security_code(bar.symbol))
                    and bar.trading_date == current_session
                ]
                return list(
                    {(bar.symbol, bar.trading_date): bar for bar in bars}.values()
                ), payloads
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
                if (bar.symbol in wanted or is_quoted_security_code(bar.symbol))
                and start <= bar.trading_date <= end
            ]
            if (
                not parsed_rows
                and isinstance(payload.payload, dict)
                and not _has_tabular_rows(payload.payload)
            ):
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
        return list(
            {(bar.symbol, bar.trading_date): bar for bar in bars}.values()
        ), payloads

    def fetch_institutional_file(self, trading_date: date) -> FetchedPayload:
        """One request: the session's institutional daily-trade file (all securities)."""

        return self._fetch(
            TPEX_CHIP_HISTORY_ENDPOINT,
            trading_date.isoformat(),
            method="POST",
            data={
                "type": "Daily",
                "sect": "EW",
                "date": trading_date.strftime("%Y/%m/%d"),
                "response": "json",
            },
        )

    def fetch_margin_file(self, trading_date: date) -> FetchedPayload:
        """One request: the session's website margin balance report (all securities)."""

        return self._fetch(
            TPEX_MARGIN_HISTORY_ENDPOINT,
            trading_date.isoformat(),
            method="POST",
            data={"date": trading_date.strftime("%Y/%m/%d"), "response": "json"},
        )

    def _chip_file(
        self,
        feed: str,
        trading_date: date,
        current_session: date | None,
        payloads: list[FetchedPayload],
    ) -> FetchedPayload:
        """The session's OpenAPI table when it is current, else the website report.

        Both are date-checked: the OpenAPI one by ``_fetch_current``, the
        website one here (OfficialDataError on another date).
        """

        if trading_date == current_session:
            current, usable = self._fetch_current(feed, trading_date)
            if current is not None:
                payloads.append(current)
            if usable:
                return current
        if feed == "institutional":
            payload = self.fetch_institutional_file(trading_date)
        else:
            payload = self.fetch_margin_file(trading_date)
        payloads.append(payload)
        _require_reported_date(
            payload.payload, trading_date, TPEX_CURRENT_FEEDS[feed][1]
        )
        return payload

    def fetch_chips(
        self,
        trading_dates: Iterable[date],
        allowed_symbols: set[str],
        *,
        current_session: date | None = None,
    ) -> tuple[list[ChipRecord], list[FetchedPayload], list[str]]:
        """Fetch TPEx date-based institutional and margin reports.

        ``current_session`` reads that session's OpenAPI tables first
        (``_chip_file``); every other date reads the website reports.
        """

        institutional: list[ChipRecord] = []
        margin: list[ChipRecord] = []
        payloads: list[FetchedPayload] = []
        warnings: list[str] = []
        for trading_date in sorted(set(trading_dates)):
            try:
                chip_payload = self._chip_file(
                    "institutional", trading_date, current_session, payloads
                )
                parsed = parse_tpex_institutional_rows(
                    chip_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=chip_payload.sha256,
                )
                institutional.extend(
                    item for item in parsed if item.symbol in allowed_symbols
                )
                if not parsed:
                    warnings.append(
                        f"TPEx institutional chip feed returned no rows for {trading_date.isoformat()}"
                    )
            except OfficialDataError as exc:
                warnings.append(
                    f"TPEx institutional chips unavailable for {trading_date.isoformat()}: {exc}"
                )
            try:
                margin_payload = self._chip_file(
                    "margin", trading_date, current_session, payloads
                )
                parsed = parse_tpex_margin_rows(
                    margin_payload.payload,
                    trading_date=trading_date,
                    data_as_of=trading_date.isoformat(),
                    payload_sha256=margin_payload.sha256,
                )
                margin.extend(item for item in parsed if item.symbol in allowed_symbols)
                if not parsed:
                    warnings.append(
                        f"TPEx margin feed returned no rows for {trading_date.isoformat()}"
                    )
            except OfficialDataError as exc:
                warnings.append(
                    f"TPEx margin chips unavailable for {trading_date.isoformat()}: {exc}"
                )
        return (
            merge_chip_records(
                institutional, margin, allowed_symbols=allowed_symbols, exchange="TPEx"
            ),
            payloads,
            warnings,
        )

    def fetch_actions(
        self, as_of: date
    ) -> tuple[list[ActionRecord], list[FetchedPayload]]:
        payload = self._fetch(TPEX_ACTION_ENDPOINT, as_of.isoformat())
        return parse_tpex_action_rows(
            payload.payload, as_of=as_of, payload_sha256=payload.sha256
        ), [payload]

    def fetch_action_history(
        self, start: date, end: date
    ) -> tuple[list[ActionRecord], list[FetchedPayload], list[str]]:
        """Every TPEx ex-right/ex-dividend event dated ``start``..``end`` (#386)."""
        records: list[ActionRecord] = []
        payloads: list[FetchedPayload] = []
        for window_start, window_end in _month_windows(start, end):
            query = urlencode(
                {
                    "startDate": window_start.strftime("%Y/%m/%d"),
                    "endDate": window_end.strftime("%Y/%m/%d"),
                    "response": "json",
                }
            )
            payload = self._fetch(
                f"{TPEX_ACTION_HISTORY_ENDPOINT}?{query}",
                _covered_dates(window_start, window_end),
            )
            payloads.append(payload)
            records.extend(
                parse_tpex_action_history(
                    payload.payload,
                    start=window_start,
                    end=window_end,
                    payload_sha256=payload.sha256,
                )
            )
        return records, payloads, []

    def fetch(self, start: date, end: date) -> OfficialBatch:
        self.captured_payloads = []
        self.no_data_dates = []
        self.feed_sources = {}
        self.current_warnings = []
        self._current_quote_payload = None
        session = self.current_session(start, end)
        instruments, universe_payloads = self._universe(end)
        bars, bar_payloads = self.fetch_bars(
            (item.symbol for item in instruments),
            start,
            end,
            current_session=session,
        )
        chip_dates = {bar.trading_date for bar in bars}
        chips, chip_payloads, chip_warnings = self.fetch_chips(
            chip_dates, _chip_symbols(instruments, bars), current_session=session
        )
        self._managed_stock_check(universe_payloads)
        feed_sources = self._feed_source_record(start, end, session)
        if not self.snapshot_feeds:
            return OfficialBatch(
                instruments=instruments,
                bars=bars,
                chips=chips,
                payloads=universe_payloads + bar_payloads + chip_payloads,
                warnings=list(chip_warnings),
                data_as_of=end.isoformat(),
                no_data_dates=sorted(set(self.no_data_dates)),
                event_coverage=_historical_event_coverage(
                    end, "TPEx suspension-history/MOPS event feeds"
                ),
                snapshot_feeds=False,
                feed_sources=feed_sources,
            )
        actions, action_payloads = self.fetch_actions(end)
        events: list[EventRecord] = []
        fundamentals: list[FundamentalRecord] = []
        mops_payloads: list[FetchedPayload] = []
        suspension_payloads: list[FetchedPayload] = []
        warnings: list[str] = list(chip_warnings) + self.current_warnings
        notices: list[str] = []
        # The highlight has only the latest session, so a historical batch
        # never requests it and a verified no-data day has nothing to read.
        market_summaries: list[MarketSummaryRecord] = []
        highlight_payloads: list[FetchedPayload] = []
        if end not in self.no_data_dates:
            try:
                highlight = self._fetch(TPEX_HIGHLIGHT_ENDPOINT, end.isoformat())
                highlight_payloads.append(highlight)
                market_summaries.append(
                    parse_tpex_market_highlight(
                        highlight.payload,
                        requested_date=end,
                        data_as_of=end.isoformat(),
                        payload_sha256=highlight.sha256,
                    )
                )
            except Exception as exc:
                warnings.append(market_summary_warning("TPEx", end, exc))
        index_daily_bars: list[Any] = []
        index_daily_payloads: list[FetchedPayload] = []
        if end not in self.no_data_dates:
            index_daily_bars, index_daily_payloads, index_warnings = (
                fetch_index_bar_months(
                    self.source, "TPEx", self.fetcher, end, self.captured_payloads
                )
            )
            warnings.extend(index_warnings)
        # The emerging roster is the current list, not a session report, so a
        # snapshot batch reads it once even on a verified no-data day.
        emerging_issuers: list[EmergingIssuerRecord] = []
        emerging_payloads: list[FetchedPayload] = []
        try:
            # The raw's data_as_of is the roster's own Date (資料日期), as
            # emerging_issuers.as_of_date, not the collect day; None when the
            # rows do not agree on one (the parse below then rejects it).
            payload = _call_fetcher(self.fetcher, TPEX_EMERGING_ISSUER_ENDPOINT)
            data_date = emerging_roster_date(payload)
            roster = capture_payload(
                self.source,
                TPEX_EMERGING_ISSUER_ENDPOINT,
                payload,
                data_date.isoformat() if data_date else None,
            )
            self.captured_payloads.append(roster)
            emerging_payloads.append(roster)
            emerging_issuers = parse_tpex_emerging_issuers(
                roster.payload, requested_date=end, payload_sha256=roster.sha256
            )
        except Exception as exc:
            warnings.append(emerging_issuer_warning(exc))
        try:
            suspension_payload = self._fetch(TPEX_SUSPEND_ENDPOINT, end.isoformat())
            suspension_payloads.append(suspension_payload)
            if suspension_payload.payload:
                notices.append(
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
            fundamental_payload = self._fetch(
                TPEX_FUNDAMENTAL_ENDPOINT, end.isoformat()
            )
            mops_payloads.append(fundamental_payload)
            fundamentals = [
                fundamental
                for fundamental in parse_mops_fundamental_rows(
                    fundamental_payload.payload,
                    exchange="TPEx",
                    payload_sha256=fundamental_payload.sha256,
                )
                if not fundamental.announcement_date
                or fundamental.announcement_date <= end
            ]
        except OfficialDataError as exc:
            warnings.append(f"TPEx MOPS fundamentals unavailable: {exc}")
        monthly_revenues: list[MonthlyRevenueRecord] = []
        try:
            revenue_payload = self._fetch(
                TPEX_MONTHLY_REVENUE_ENDPOINT, end.isoformat()
            )
            mops_payloads.append(revenue_payload)
            monthly_revenues = parse_monthly_revenue_rows(
                revenue_payload.payload,
                exchange="TPEx",
                requested_date=end,
                payload_sha256=revenue_payload.sha256,
            )
        except Exception as exc:
            warnings.append(monthly_revenue_warning("TPEx", exc))
        trading_halts, trading_halt_windows, halt_payloads = collect_reduction_window(
            self._fetch, "TPEx", end, warnings
        )
        mops_payloads.extend(halt_payloads)
        event_coverage = {
            "status": "unsupported",
            "denominator": "date_scoped_event_queries",
            "verified_dates": [],
            "empty_dates": [],
            "unsupported_dates": [end.isoformat()],
            "observed_event_dates": sorted(
                {item.event_date.isoformat() for item in events}
            ),
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
            payloads=universe_payloads
            + bar_payloads
            + chip_payloads
            + action_payloads
            + highlight_payloads
            + emerging_payloads
            + suspension_payloads
            + mops_payloads
            + index_daily_payloads,
            warnings=warnings,
            data_as_of=end.isoformat(),
            no_data_dates=sorted(set(self.no_data_dates)),
            event_coverage=event_coverage,
            notices=notices,
            market_summaries=market_summaries,
            emerging_issuers=emerging_issuers,
            monthly_revenues=monthly_revenues,
            trading_halts=trading_halts,
            trading_halt_windows=trading_halt_windows,
            index_daily_bars=index_daily_bars,
            feed_sources=feed_sources,
        )

    def _feed_source_record(
        self, start: date, end: date, session: date | None
    ) -> dict[str, Any]:
        """``{"TPEx": ...}``: which endpoint each core feed read and why (#579)."""

        if session is None:
            return {
                "TPEx": {
                    "session": None,
                    "reason": "not_current_session",
                    "range": [start.isoformat(), end.isoformat()],
                    **{
                        feed: {"source": "website", "endpoint": website}
                        for feed, (_openapi, website) in TPEX_CURRENT_FEEDS.items()
                    },
                }
            }
        # A feed that was not requested (a verified no-data day has no chips)
        # is absent.
        return {"TPEx": {"session": session.isoformat(), **self.feed_sources}}


class OfficialMarketDataAdapter:
    """Combine TWSE and TPEx official feeds into one normalized batch."""

    def __init__(
        self,
        twse: TwseAdapter | None = None,
        tpex: TpexAdapter | None = None,
        *,
        snapshot_feeds: bool = True,
        mops_fetcher: Callable[..., Any] | None = None,
        futures_history_get: Callable[..., Any] | None = None,
    ) -> None:
        # The TX gap fill after a snapshot collect (worker.futures_history,
        # Issue #586) asks the TAIFEX website.  An adapter built on given
        # feeds (fixtures) or for a historical collect (catchup, backfill:
        # snapshot_feeds=False) does not, unless a getter is given too; the
        # collect also asks only after a snapshot batch.
        if futures_history_get is None and twse is None and snapshot_feeds:
            from .futures_history import fetch_month

            futures_history_get = fetch_month
        self.futures_history_get = futures_history_get
        # No US index step: index-bars us-collect asks FinMind on its own (#568).
        self.twse = twse or TwseAdapter(snapshot_feeds=snapshot_feeds)
        self.tpex = tpex or TpexAdapter(snapshot_feeds=snapshot_feeds)
        # The date-scoped MOPS event list (Issue #464) goes through the same
        # fetcher as the TWSE feeds unless one is given.
        self.mops_fetcher = mops_fetcher or getattr(self.twse, "fetcher", fetch_json)
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
        instruments = {
            (item.exchange, item.symbol): item for item in twse_batch.instruments
        }
        instruments.update(
            {(item.exchange, item.symbol): item for item in tpex_batch.instruments}
        )
        bars = {
            (item.exchange, item.symbol, item.trading_date): item
            for item in twse_batch.bars
        }
        bars.update(
            {
                (item.exchange, item.symbol, item.trading_date): item
                for item in tpex_batch.bars
            }
        )
        no_data_dates = sorted(set(twse_batch.no_data_dates + tpex_batch.no_data_dates))
        if not instruments or (not bars and not no_data_dates):
            raise OfficialDataError(
                "official feeds returned no normalized universe or OHLCV"
            )
        # Event coverage is the date-scoped MOPS list for the end date, on the
        # snapshot and the historical path alike.  The snapshot feeds' own
        # (unsupported) record is kept for audit only.
        from worker import mops_events

        mops_records, mops_payloads, event_coverage, mops_warnings = (
            mops_events.fetch_date(end, self.mops_fetcher)
        )
        self.captured_payloads.extend(mops_payloads)
        event_coverage["snapshot_feed_coverage"] = _merge_event_coverage(
            [twse_batch.event_coverage, tpex_batch.event_coverage]
        )
        futures_bars, futures_payloads, futures_warnings = self._fetch_futures(
            end,
            snapshot=twse_batch.snapshot_feeds and tpex_batch.snapshot_feeds,
            no_data=end in no_data_dates,
        )
        return OfficialBatch(
            instruments=list(instruments.values()),
            bars=list(bars.values()),
            chips=twse_batch.chips + tpex_batch.chips,
            actions=twse_batch.actions + tpex_batch.actions,
            fundamentals=twse_batch.fundamentals + tpex_batch.fundamentals,
            events=twse_batch.events + tpex_batch.events + mops_records,
            payloads=twse_batch.payloads
            + tpex_batch.payloads
            + mops_payloads
            + futures_payloads,
            warnings=twse_batch.warnings
            + tpex_batch.warnings
            + mops_warnings
            + futures_warnings,
            data_as_of=max(
                filter(None, [twse_batch.data_as_of, tpex_batch.data_as_of]),
                default=end.isoformat(),
            ),
            no_data_dates=no_data_dates,
            event_coverage=event_coverage,
            notices=twse_batch.notices + tpex_batch.notices,
            snapshot_feeds=twse_batch.snapshot_feeds and tpex_batch.snapshot_feeds,
            market_summaries=twse_batch.market_summaries + tpex_batch.market_summaries,
            emerging_issuers=twse_batch.emerging_issuers + tpex_batch.emerging_issuers,
            monthly_revenues=twse_batch.monthly_revenues + tpex_batch.monthly_revenues,
            trading_halts=twse_batch.trading_halts + tpex_batch.trading_halts,
            trading_halt_windows=twse_batch.trading_halt_windows
            + tpex_batch.trading_halt_windows,
            index_daily_bars=twse_batch.index_daily_bars + tpex_batch.index_daily_bars,
            futures_bars=futures_bars,
            feed_sources={**twse_batch.feed_sources, **tpex_batch.feed_sources},
        )

    def _fetch_futures(
        self, end: date, *, snapshot: bool, no_data: bool
    ) -> tuple[list[Any], list[FetchedPayload], list[str]]:
        """The TX near-month bar the report holds (worker.futures_bars, #552, #586).

        Only a snapshot collect of a session asks: the report has the latest
        session only.  Non-core; the answer is kept as raw even when it is
        another session's.
        """

        if not snapshot or no_data:
            return [], [], []
        bars, payloads, warnings = fetch_latest_futures(
            getattr(self.twse, "fetcher", fetch_json), end
        )
        self.captured_payloads.extend(payloads)
        return bars, payloads, warnings


def _takes_keyword(fn: Callable[..., Any], name: str) -> bool:
    """Whether ``fn`` accepts the keyword ``name`` (by name or ``**kwargs``)."""

    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.name == name
            and parameter.kind
            in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        )
        for parameter in parameters
    )


def fetch_latest_futures(
    fetcher: Callable[..., Any], end: date
) -> tuple[list[Any], list[FetchedPayload], list[str]]:
    """Read ``DailyMarketReportFut`` once: the bar of the session it holds.

    The answer is a CSV or JSON (worker.futures_bars.capture_form); its raw
    (source ``taifex``) is dated by the report.  The bar is of the report's
    own session, which the caller stores only when it is a verified session
    without a TX row (pipeline.store_collect_futures_bars).  A report of a
    session before ``end`` adds the "not yet published" warning for ``end``;
    every warning is non-core (``futures bars ``).
    """

    from .futures_bars import (
        capture_form,
        futures_warning,
        not_published_warning,
        parse_near_month,
        report_date,
    )

    try:
        # fetch_json hands back the bytes of a non-JSON answer (the CSV).  The
        # signature decides, not a TypeError: one raised inside the fetcher
        # must not send the request again (PR #589 review).
        if _takes_keyword(fetcher, "text_fallback"):
            answer = fetcher(TAIFEX_DAILY_FUTURES_ENDPOINT, text_fallback=True)
        else:
            answer = _call_fetcher(fetcher, TAIFEX_DAILY_FUTURES_ENDPOINT)
    except Exception as exc:
        return [], [], [futures_warning(exc)]
    payload = capture_form(answer)
    reported = report_date(payload)
    captured = capture_payload(
        "taifex",
        TAIFEX_DAILY_FUTURES_ENDPOINT,
        payload,
        reported.isoformat() if reported else None,
    )
    try:
        bar = parse_near_month(payload, payload_sha256=captured.sha256)
    except Exception as exc:
        return [], [captured], [futures_warning(exc)]
    warnings = (
        [not_published_warning(end, bar.trading_date)] if bar.trading_date < end else []
    )
    return [bar], [captured], warnings


def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar-month pieces of ``start``..``end``; one request per piece."""
    if start > end:
        raise ValueError("start must be on or before end")
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
        windows.append((cursor, min(last, end)))
        cursor = last + timedelta(days=1)
    return windows


def _covered_dates(start: date, end: date) -> str:
    """``data_as_of`` of a range report: the dates it covers, never one per day.

    One capture is one raw_payloads row whose ``data_as_of`` is the requested
    range (``2026-09-01~2026-09-30``), or the date for a one-day range (#386,
    DB review C3: a snapshot must not be registered once per covered day).
    """
    return start.isoformat() if start == end else f"{start}~{end}"


def _roc_compact(value: date) -> str:
    """``2026-09-08`` -> ``1150908``, the Date format of TWT48U and TPEx OpenAPI."""
    return f"{value.year - 1911:03d}{value.month:02d}{value.day:02d}"


def _stripped(row: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key).strip(): value.strip() if isinstance(value, str) else value
        for key, value in row.items()
    }


def twse_action_type(kind: str) -> str:
    """The stored action_type of a TWSE row whose 權/息 value is ``kind``.

    TWT48U and TWT49U publish 息／權／權息, so this is ``corporate_action``
    for every TWSE row.  The rule is shared so a backfilled TWT49U row keeps
    the identity (instrument, date, type) of the row the daily TWT48U feed
    wrote, and replaces it instead of adding a second row for the same event.
    """
    return "ex_dividend" if "除息" in kind else "corporate_action"


def parse_twse_action_rows(
    payload: Any, *, as_of: date, payload_sha256: str | None
) -> list[ActionRecord]:
    """The TWT48U_ALL rows dated on or before ``as_of`` as ActionRecords."""
    result: list[ActionRecord] = []
    for row in _rows(payload):
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
                action_type=twse_action_type(_text(row, "Exdividend", "除權息")),
                cash_dividend=parse_number(_text(row, "CashDividend", "現金股利")),
                stock_dividend_ratio=parse_number(
                    _text(row, "StockDividendRatio", "無償配股率")
                ),
                split_ratio=parse_number(
                    _text(row, "SplitRatio", "分割比例", "分割率")
                ),
                reference_price=parse_number(
                    _text(
                        row,
                        "ReferencePrice",
                        "OpeningReferencePrice",
                        "開盤參考價",
                        "除權息前收盤價",
                    )
                ),
                details=dict(row),
                exchange="TWSE",
                payload_sha256=payload_sha256,
            )
        )
    return result


def parse_tpex_action_rows(
    payload: Any, *, as_of: date, payload_sha256: str | None
) -> list[ActionRecord]:
    """The tpex_exright_daily rows dated on or before ``as_of`` as ActionRecords."""
    result: list[ActionRecord] = []
    for row in _rows(payload):
        record = tpex_action_record(row, payload_sha256=payload_sha256)
        if record is None or record.action_date > as_of:
            continue
        result.append(record)
    return result


def tpex_action_record(
    row: dict[str, Any], *, payload_sha256: str | None
) -> ActionRecord | None:
    """One TPEx OpenAPI-shaped ex-right/ex-dividend row as an ActionRecord."""
    symbol = _text(row, "SecuritiesCompanyCode", "代號")
    action_date = _date_from_row(row, "Date", "除權息日期")
    if not symbol or not action_date:
        return None
    # TPEx publishes free shares per thousand old shares. StockDividend
    # is a monetary rights value, not a share ratio.
    free_shares = parse_number(
        _text(row, "StockDivdendThousandShares", "每仟股無償配股")
    )
    return ActionRecord(
        symbol=symbol,
        action_date=action_date,
        action_type="ex_dividend"
        if "息" in _text(row, "ExRightsDiviend", "權或息")
        else "corporate_action",
        cash_dividend=parse_number(
            _text(row, "CashDivdend", "CashDividend", "現金股利", "息值")
        ),
        stock_dividend_ratio=free_shares / 1000 if free_shares is not None else None,
        reference_price=parse_number(
            _text(row, "ClosePriceBeforeExRightsDiviend", "除權息前收盤價")
        ),
        details=dict(row),
        exchange="TPEx",
        payload_sha256=payload_sha256,
    )


# exDailyQ column -> the TPEx OpenAPI (tpex_exright_daily) key of the same
# value, so a backfilled row is stored in the shape the daily feed writes.
TPEX_ACTION_HISTORY_FIELDS = {
    "除權息日期": "Date",
    "代號": "SecuritiesCompanyCode",
    "名稱": "CompanyName",
    "除權息前收盤價": "ClosePriceBeforeExRightsDiviend",
    "除權息參考價": "ExRightsDiviendQuote",
    "權值": "StockDividend",
    "息值": "CashDividend",
    "權值+息值": "StockDividendPlusCashDividend",
    "權/息": "ExRightsDiviend",
    "漲停價": "LimitUp",
    "跌停價": "LimitDown",
    "開始交易基準價": "OpeningReferencePrice",
    "減除股利參考價": "DividendDeductedQuote",
    "現金股利": "CashDivdend",
    "每仟股無償配股": "StockDivdendThousandShares",
    "現金增資股數": "CashCapitalIncreaseShares",
    "現金增資認購價": "SubscriptionPricePerShare",
    "公開承銷股數": "AllocatedForPublicUnderwriting",
    "員工認購股數": "SubscribedByEmployees",
    "原股東認購股數": "SubscribedByExistingShareholders",
    "按持股比例仟股認購": "SubscribedProRataThousandShares",
}


def parse_tpex_action_history(
    payload: Any, *, start: date, end: date, payload_sha256: str | None
) -> list[ActionRecord]:
    """Parse one exDailyQ response; anything but the requested range fails."""
    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() != "ok":
        raise OfficialDataError("TPEx exDailyQ did not answer ok")
    expected = f"{start:%Y%m%d}~{end:%Y%m%d}"
    if payload.get("date") != expected:
        raise OfficialDataError(
            f"TPEx exDailyQ reported {payload.get('date')!r}, requested {expected}"
        )
    if not isinstance(payload.get("tables"), list):
        raise OfficialDataError("TPEx exDailyQ has no tables")
    records: list[ActionRecord] = []
    for raw in _rows(payload):
        row = _stripped(raw)
        missing = sorted(set(TPEX_ACTION_HISTORY_FIELDS) - set(row))
        if missing:
            raise OfficialDataError(f"TPEx exDailyQ row lacks {missing}")
        mapped = {
            TPEX_ACTION_HISTORY_FIELDS[key]: value
            for key, value in row.items()
            if key in TPEX_ACTION_HISTORY_FIELDS
        }
        action_date = parse_roc_date(mapped["Date"])
        if action_date is None or not start <= action_date <= end:
            raise OfficialDataError(
                f"TPEx exDailyQ row dated {mapped['Date']!r} outside {expected}"
            )
        mapped["Date"] = _roc_compact(action_date)
        record = tpex_action_record(mapped, payload_sha256=payload_sha256)
        if record is None:
            raise OfficialDataError("TPEx exDailyQ row without a code")
        records.append(record)
    return records


def parse_twse_action_history(
    payload: Any, *, start: date, end: date
) -> list[dict[str, Any]]:
    """Rows of one TWT49U response: symbol, date, 權/息 and the published row."""
    if not isinstance(payload, dict):
        raise OfficialDataError("TWSE TWT49U payload is not an object")
    stat = str(payload.get("stat", ""))
    if "沒有符合條件的資料" in stat and not payload.get("data"):
        # TWSE answers a range without events with only this stat.
        return []
    if stat.upper() != "OK":
        raise OfficialDataError(f"TWSE TWT49U did not answer OK: {stat}")
    if not isinstance(payload.get("fields"), list) or not isinstance(
        payload.get("data"), list
    ):
        raise OfficialDataError("TWSE TWT49U has no fields/data table")
    rows = _rows(payload)
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = _stripped(raw)
        symbol = _text(row, "股票代號")
        action_date = _date_from_row(row, "資料日期")
        if not symbol or action_date is None:
            raise OfficialDataError("TWSE TWT49U row without a code or date")
        if not start <= action_date <= end:
            raise OfficialDataError(
                f"TWSE TWT49U row dated {action_date.isoformat()} outside "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        result.append(
            {
                "symbol": symbol,
                "action_date": action_date,
                "kind": _text(row, "權/息"),
                "row": row,
            }
        )
    return result


def parse_twse_action_detail(payload: Any, symbol: str) -> dict[str, Any] | None:
    """The TWT49UDetail row of ``symbol`` with its keys and values stripped."""
    for raw in _rows(payload):
        row = _stripped(raw)
        if _text(row, "股票代號") == symbol:
            return row
    return None


# TWT49UDetail prints free shares per thousand to one decimal (2442
# 2026-09-08: 71.1 股 where TWT48U has 0.07111516), so the printed ratio is
# off by up to half that step.
TWSE_DETAIL_RATIO_STEP = 0.0001


def _twse_stock_ratio(
    published: dict[str, Any],
    detail: dict[str, Any],
    cash: float | None,
    printed: float | None,
) -> tuple[float | None, dict[str, Any]]:
    """The free-share ratio of a TWT49U ex-right, to the precision TWSE used.

    TWSE computes the reference price from the exact ratio, and TWT49U
    publishes ``權值+息值`` (before close minus the unrounded reference) to six
    decimals, so ``(B - C) / (B - V) - 1`` recovers that ratio.  With a cash
    capital increase that reference includes the subscription; the
    dividend-only 減除股利參考價 (0.01 units) gives ``(B - C) / D - 1``
    instead.  The recovered ratio is used only when the detail's printed
    value agrees with it to the print step; otherwise the printed value is
    kept and the factor check on write decides (6446 2026-07-09: printed
    109.7 股, reference implies 110.36 股).
    """
    source: dict[str, Any] = {"printed": printed}
    before = parse_number(published.get("除權息前收盤價"))
    combined = parse_number(published.get("權值+息值"))
    deducted = parse_number(published.get("減除股利參考價"))
    subscribed = any(
        (parse_number(detail.get(key)) or 0) > 0
        for key in ("C. (有償) 現金增資", "按股東持股比例每千股認購")
    )
    if printed is None or printed <= 0 or not before or cash is None:
        return printed, {**source, "used": "printed"}
    if subscribed:
        base = deducted
        source["from"] = "減除股利參考價"
    else:
        base = before - combined if combined is not None else None
        source["from"] = "權值+息值"
    if not base or base <= 0:
        return printed, {**source, "used": "printed"}
    derived = round((before - cash) / base - 1, 8)
    source["derived"] = derived
    if abs(derived - printed) <= 1e-6:
        return printed, {**source, "used": "printed"}
    if abs(derived - printed) <= TWSE_DETAIL_RATIO_STEP / 2 + 1e-9:
        return derived, {**source, "used": "derived"}
    return printed, {**source, "used": "printed", "disagrees": True}


def twse_action_history_record(
    row: dict[str, Any],
    detail: dict[str, Any] | None,
    *,
    payload_sha256: str | None,
    detail_sha256: str | None,
) -> ActionRecord:
    """A TWT49U row (plus its TWT49UDetail for an ex-right) as an ActionRecord.

    The stored details keep every published TWT49U column and add the
    TWT48U keys Code, Date, Name and Exdividend, which the stock page reads
    to classify a TWSE row.  A 息 row's 權值+息值 is its cash dividend; a
    row with 權 takes cash per share and free shares per thousand from the
    detail.
    """
    published = row["row"]
    symbol, action_date, kind = row["symbol"], row["action_date"], row["kind"]
    if detail is None:
        if "權" in kind:
            raise ValueError("an ex-right TWT49U row needs its TWT49UDetail")
        cash = parse_number(published.get("權值+息值"))
        stock_ratio = None
        ratio_source = None
    else:
        cash = parse_number(detail.get("(每股配發現金股利)除息"))
        free_shares = parse_number(detail.get("A. 按普通股股東持股比例每千股無償配股"))
        printed = free_shares / 1000 if free_shares is not None else None
        stock_ratio, ratio_source = _twse_stock_ratio(published, detail, cash, printed)
    details: dict[str, Any] = {
        "Code": symbol,
        "Date": _roc_compact(action_date),
        "Name": _text(published, "股票名稱"),
        "Exdividend": kind,
        **published,
    }
    if detail is not None:
        details["detail"] = detail
        details["detail_sha256"] = detail_sha256
        details["stock_ratio_source"] = ratio_source
    return ActionRecord(
        symbol=symbol,
        action_date=action_date,
        action_type=twse_action_type(kind),
        cash_dividend=cash,
        stock_dividend_ratio=stock_ratio,
        reference_price=parse_number(published.get("除權息前收盤價")),
        details=details,
        exchange="TWSE",
        payload_sha256=payload_sha256,
    )
