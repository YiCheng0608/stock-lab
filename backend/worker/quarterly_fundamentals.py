"""Quarterly EPS and revenue backfill from MOPS ``t163sb04`` (Issue #529).

The OpenAPI snapshots ``t187ap14_L``／``mopsfin_t187ap14_O`` only carry the
latest quarter, so ``fundamental_snapshots`` had one or two quarters.  MOPS
「彙總報表－綜合損益表」``t163sb04`` answers one market and one quarter for
every company:

- the new MOPS site has no data API for it: its page asks ``redirectToOld``
  for an encrypted ``mopsov`` URL and opens it.  This module posts the old
  site's form directly (``ENDPOINT``), one request per market and quarter;
- the answer is HTML, one ``table.hasBorder`` per report format (general,
  bank, financial holding, securities, insurance, other; insurers used a
  營業收入 format before IFRS 17, ``insurance_legacy``).  The first two
  columns are 公司代號 and 公司名稱, the last is 基本每股盈餘; amounts are
  cumulative from the start of the year to the quarter end, in thousand NTD,
  the same basis as the snapshots;
- revenue is the column the snapshots call 營業收入 for each format
  (``REVENUE_FIELDS``); the IFRS 17 insurance format has none and stays empty.  A table whose
  header matches no known format fails the whole market-quarter.

The quarter has no announcement time.  Its availability is the statutory
filing deadline of the format's industry (``DEADLINES``, rolled forward to a
session), ``data_json.announcement_basis = statutory_deadline``; while the
deadline is still ahead it is the Taipei date the quarter was first fetched
(``first_seen``), so no row carries a future date.  Rows the snapshots wrote
keep their values and source; the backfill only moves their availability
earlier when the deadline is earlier (``pipeline.first_seen_announcement``).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import FundamentalSnapshot, IngestionRun, Instrument
from app.trading_calendar import next_session
from worker import pipeline
from worker.sources import (
    FundamentalRecord,
    OfficialDataError,
    _throttle_official_host,
    capture_payload,
    parse_number,
)

ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_t163sb04"
ENDPOINT_NAME = "MOPS t163sb04 彙總報表－綜合損益表"
SOURCE = "mops_t163sb04"
RAW_SOURCE = "mops"
RUN_TYPE = "fundamental_backfill"
MARKETS = {"sii": "TWSE", "otc": "TPEx"}
MARKET_TITLES = {"sii": "上市", "otc": "上櫃"}
DEFAULT_QUARTERS = 8
MAX_QUARTERS = 20
# Failed market-quarters in a row that stop a run (the source is likely blocking).
ABORT_AFTER_FAILURES = 3
TAIPEI = timezone(timedelta(hours=8))
# The fixed fields of the old site's query form (from the page's hidden keys).
FORM_FIELDS = {
    "encodeURIComponent": "1",
    "step": "1",
    "firstin": "1",
    "off": "1",
    "isQuery": "Y",
}
# A page with no report table but one of these is an answered empty quarter.
NO_DATA_MARKERS = ("查無資料", "查詢無資料", "無符合條件")
BLOCK_MARKERS = ("FOR SECURITY REASONS", "查詢過於頻繁", "THE PAGE CANNOT BE ACCESSED")
QUARTER_TITLES = {1: ("第一季",), 2: ("第二季",), 3: ("第三季",), 4: ("第四季", "年度")}

# Report formats by header columns; exactly one must match a table.
FORMAT_SIGNATURES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # format: (columns that must be present, columns that must be absent)
    "general": (frozenset({"營業收入", "營業毛利（毛損）"}), frozenset()),
    # Insurers before IFRS 17 (through 2025Q4): 營業收入 without a gross profit.
    "insurance_legacy": (
        frozenset({"營業收入", "繼續營業單位稅前純益（純損）"}),
        frozenset({"營業毛利（毛損）"}),
    ),
    "bank": (
        frozenset({"利息淨收益", "利息以外淨損益"}),
        frozenset({"淨收益", "營業收入"}),
    ),
    "holding": (
        frozenset({"利息淨收益", "利息以外淨收益", "淨收益"}),
        frozenset({"營業收入"}),
    ),
    "securities": (frozenset({"收益", "支出及費用"}), frozenset({"營業收入"})),
    "insurance": (frozenset({"保險服務結果", "財務結果"}), frozenset({"營業收入"})),
    "other": (frozenset({"收入", "支出"}), frozenset({"營業收入"})),
}
# The columns that make up the snapshots' 營業收入 for each format: banks have
# no total, so it is the sum of the two net revenue lines (2801 115Q2:
# 15,221,502 + 10,607,584 = 25,829,086, the t187ap14_L value).
REVENUE_FIELDS: dict[str, tuple[str, ...]] = {
    "general": ("營業收入",),
    "bank": ("利息淨收益", "利息以外淨損益"),
    "holding": ("淨收益",),
    "securities": ("收益",),
    "insurance": (),
    "insurance_legacy": ("營業收入",),
    "other": ("收入",),
}
# Statutory filing deadlines (month, day) for Q1–Q3 by format, from the page's
# 註1 (證券交易法第36條); the annual report (Q4) is due 3/31 of the next year
# for every industry.  The "other" format is used by general companies.
_GENERAL = {1: (5, 15), 2: (8, 14), 3: (11, 14)}
_FINANCIAL = {1: (5, 15), 2: (8, 31), 3: (11, 14)}
DEADLINES: dict[str, dict[int, tuple[int, int]]] = {
    "general": _GENERAL,
    "other": _GENERAL,
    "holding": {1: (5, 30), 2: (8, 31), 3: (11, 29)},
    "bank": _FINANCIAL,
    "insurance": _FINANCIAL,
    "insurance_legacy": _FINANCIAL,
    "securities": _FINANCIAL,
}
ANNUAL_DEADLINE = (3, 31)


# --- quarters -----------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    quarter: int

    @property
    def period_end(self) -> date:
        return {
            1: date(self.year, 3, 31),
            2: date(self.year, 6, 30),
            3: date(self.year, 9, 30),
            4: date(self.year, 12, 31),
        }[self.quarter]

    @property
    def label(self) -> str:
        return f"{self.year}Q{self.quarter}"

    def previous(self) -> Quarter:
        if self.quarter == 1:
            return Quarter(self.year - 1, 4)
        return Quarter(self.year, self.quarter - 1)

    @classmethod
    def parse(cls, text: str) -> Quarter:
        match = re.fullmatch(r"(\d{4})Q([1-4])", text.strip().upper())
        if not match:
            raise ValueError(f"quarter {text!r} is not YYYYQn")
        return cls(int(match.group(1)), int(match.group(2)))

    @classmethod
    def latest_ended(cls, today: date) -> Quarter:
        """The last quarter whose period ended before ``today``."""

        quarter = cls(today.year, (today.month - 1) // 3 + 1)
        while quarter.period_end >= today:
            quarter = quarter.previous()
        return quarter


def quarter_range(end: Quarter, count: int) -> list[Quarter]:
    quarters = [end]
    while len(quarters) < count:
        quarters.append(quarters[-1].previous())
    return sorted(quarters)


def request_form(market: str, quarter: Quarter) -> dict[str, str]:
    return {
        **FORM_FIELDS,
        "TYPEK": market,
        "year": str(quarter.year - 1911),
        "season": f"{quarter.quarter:02d}",
    }


# --- statutory deadline and availability -------------------------------------


def nominal_deadline(report_format: str, quarter: Quarter) -> date:
    if quarter.quarter == 4:
        return date(quarter.year + 1, *ANNUAL_DEADLINE)
    return date(quarter.year, *DEADLINES[report_format][quarter.quarter])


def roll_to_session(db: Session, day: date) -> tuple[date, str]:
    """``day`` or the first session after it, and the calendar that decided.

    A deadline on a closed day moves to the next business day (註1 第 6 點).
    The stored TWSE holiday schedule decides when it covers the walk; years
    it does not cover (the backfill reaches two years back) only skip weekends.
    """

    session = next_session(db, day - timedelta(days=1))
    if session.date is not None:
        return session.date, "twse_holiday_schedule"
    rolled = day
    while rolled.weekday() >= 5:
        rolled += timedelta(days=1)
    return rolled, "weekend_only"


def availability(deadline: date, first_seen: date) -> tuple[date, str]:
    """The availability date and its basis; never later than the fetch date."""

    if deadline <= first_seen:
        return deadline, "statutory_deadline"
    return first_seen, "first_seen"


# --- HTML report --------------------------------------------------------------


@dataclass
class _Table:
    css_class: str
    rows: list[list[str]] = field(default_factory=list)


class _ReportParser(HTMLParser):
    """Tables (cell text with whitespace collapsed) and the page's h2 titles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.titles: list[str] = []
        self._stack: list[_Table] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._title: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._stack.append(_Table(dict(attrs).get("class") or ""))
        elif tag == "tr" and self._stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag == "h2":
            self._title = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._stack:
            self._stack[-1].rows.append(self._row)
            self._row = None
        elif tag == "table" and self._stack:
            self.tables.append(self._stack.pop())
        elif tag == "h2" and self._title is not None:
            self.titles.append(" ".join("".join(self._title).split()))
            self._title = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
        if self._title is not None:
            self._title.append(data)


def report_format(headers: list[str]) -> str:
    columns = set(headers)
    matches = [
        name
        for name, (present, absent) in FORMAT_SIGNATURES.items()
        if present <= columns and not absent & columns
    ]
    if len(matches) != 1:
        raise OfficialDataError(
            f"MOPS t163sb04 table format not recognized ({matches!r}): {headers[:6]!r}"
        )
    return matches[0]


@dataclass(frozen=True)
class QuarterRow:
    symbol: str
    name: str
    report_format: str
    revenue: float | None
    eps: float | None
    cells: dict[str, str]


def _revenue(report_format: str, cells: dict[str, str]) -> float | None:
    fields = REVENUE_FIELDS[report_format]
    if not fields:
        return None
    values = [parse_number(cells.get(name)) for name in fields]
    if any(value is None for value in values):
        return None
    return float(sum(values))  # type: ignore[arg-type]


def parse_report(html: str, market: str, quarter: Quarter) -> list[QuarterRow]:
    """Every company row of one ``t163sb04`` page; raise when it cannot be trusted."""

    label = f"MOPS t163sb04 {market} {quarter.label}"
    upper = html.upper()
    if any(marker.upper() in upper for marker in BLOCK_MARKERS):
        raise OfficialDataError(f"{label} was refused by the source")
    parser = _ReportParser()
    parser.feed(html)
    parser.close()
    title = " ".join(parser.titles)
    reports = [table for table in parser.tables if "hasBorder" in table.css_class]
    if not reports:
        if any(marker in html for marker in NO_DATA_MARKERS):
            return []
        raise OfficialDataError(f"{label} has no report table")
    if MARKET_TITLES[market] not in title:
        raise OfficialDataError(f"{label} answered another market: {title!r}")
    named = [
        number
        for number, words in QUARTER_TITLES.items()
        if any(w in title for w in words)
    ]
    if named and quarter.quarter not in named:
        raise OfficialDataError(f"{label} answered another quarter: {title!r}")
    result: list[QuarterRow] = []
    seen: set[str] = set()
    for table in reports:
        if not table.rows:
            raise OfficialDataError(f"{label} has an empty table")
        headers = table.rows[0]
        if headers[:2] != ["公司代號", "公司名稱"] or not headers[-1].startswith(
            "基本每股盈餘"
        ):
            raise OfficialDataError(f"{label} columns changed: {headers[:3]!r}")
        kind = report_format(headers)
        for cells in table.rows[1:]:
            if len(cells) != len(headers):
                raise OfficialDataError(f"{label} has a malformed row: {cells[:2]!r}")
            row = dict(zip(headers, cells))
            symbol = row["公司代號"].strip()
            if not symbol:
                raise OfficialDataError(f"{label} has a row without a code")
            if symbol in seen:
                raise OfficialDataError(f"{label} lists {symbol} twice")
            seen.add(symbol)
            result.append(
                QuarterRow(
                    symbol=symbol,
                    name=row["公司名稱"],
                    report_format=kind,
                    revenue=_revenue(kind, row),
                    eps=parse_number(row[headers[-1]]),
                    cells=row,
                )
            )
    return result


# --- fetch --------------------------------------------------------------------


def fetch_html(url: str, form: dict[str, str], *, timeout_seconds: float = 60.0) -> str:
    """POST the form and return the decoded page; transient failures retry."""

    headers = {"User-Agent": "taiwan-stock-research/0.1"}
    retry_limit = 3
    for attempt in range(retry_limit):
        _throttle_official_host(url)
        try:
            response = httpx.post(
                url, data=form, timeout=timeout_seconds, headers=headers
            )
        except httpx.TransportError as exc:
            if attempt + 1 >= retry_limit:
                raise OfficialDataError(
                    f"official endpoint transport retry exhausted: {url}"
                ) from exc
            time.sleep(min(2.0, 0.25 * (2**attempt)))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt + 1 >= retry_limit:
                raise OfficialDataError(
                    f"official endpoint retry exhausted ({response.status_code}): {url}"
                )
            time.sleep(0.25 * (2**attempt))
            continue
        if response.status_code != 200:
            raise OfficialDataError(
                f"official endpoint rejected request ({response.status_code}): {url}"
            )
        return response.text
    raise OfficialDataError(f"official endpoint retry budget exhausted: {url}")


# --- writes -------------------------------------------------------------------


def _record(
    row: QuarterRow,
    market: str,
    quarter: Quarter,
    available: date,
    basis: str,
    deadline: date,
    calendar: str,
    payload_sha256: str,
) -> FundamentalRecord:
    details: dict[str, Any] = {
        **row.cells,
        "TYPEK": market,
        "year": str(quarter.year - 1911),
        "season": f"{quarter.quarter:02d}",
        "report_format": row.report_format,
        "revenue_fields": list(REVENUE_FIELDS[row.report_format]),
        "announcement_basis": basis,
        "statutory_deadline": deadline.isoformat(),
        "deadline_calendar": calendar,
    }
    return FundamentalRecord(
        symbol=row.symbol,
        period_end=quarter.period_end,
        fiscal_period=f"Q{quarter.quarter}",
        announcement_date=available,
        revenue=row.revenue,
        eps=row.eps,
        roe=None,
        details=details,
        exchange=MARKETS[market],
        source=SOURCE,
        payload_sha256=payload_sha256,
    )


def _basis(details: dict[str, Any] | None) -> str | None:
    return (details or {}).get("announcement_basis")


def apply_record(
    db: Session, record: FundamentalRecord, instrument: Instrument, raw_payload_id: int
) -> str:
    """Write one quarter; ``inserted``, ``updated``, ``dated`` or ``unchanged``.

    A row another source wrote (the snapshots) keeps its values and source;
    only an earlier availability date is taken, with its basis.  A stored
    statutory deadline is recomputed rather than kept, so a holiday calendar
    loaded later corrects it.  The raw
    payload id and ``collected_at`` change only with the values, so the row
    points at the capture its values came from and a rerun changes nothing.
    """

    row = db.scalar(
        select(FundamentalSnapshot).where(
            FundamentalSnapshot.instrument_id == instrument.id,
            FundamentalSnapshot.period_end == record.period_end,
            FundamentalSnapshot.fiscal_period == record.fiscal_period,
        )
    )
    if row is None:
        db.add(
            FundamentalSnapshot(
                instrument_id=instrument.id,
                period_end=record.period_end,
                fiscal_period=record.fiscal_period,
                announcement_date=record.announcement_date,
                revenue=record.revenue,
                eps=record.eps,
                roe=record.roe,
                data_json=record.details,
                source=record.source,
                raw_payload_id=raw_payload_id,
                data_as_of=record.period_end.isoformat(),
                collected_at=utcnow(),
            )
        )
        return "inserted"
    if (
        _basis(row.data_json) == "statutory_deadline"
        and _basis(record.details) == "statutory_deadline"
    ):
        # Both dates are the deadline rule's answer; the new one read the
        # calendar as it is now (a year loaded since can move it later).
        announcement, details = record.announcement_date, record.details
    else:
        announcement, details = pipeline.first_seen_announcement(
            row, record.announcement_date, record.details
        )
    if row.source != record.source:
        if announcement == row.announcement_date:
            return "unchanged"
        row.announcement_date = announcement
        row.data_json = {
            **(row.data_json or {}),
            **{
                key: details[key]
                for key in pipeline.ANNOUNCEMENT_KEYS
                if key in details
            },
        }
        return "dated"
    if (
        row.announcement_date == announcement
        and row.revenue == record.revenue
        and row.eps == record.eps
        and row.roe == record.roe
        and row.data_json == details
    ):
        return "unchanged"
    row.announcement_date = announcement
    row.revenue = record.revenue
    row.eps = record.eps
    row.roe = record.roe
    row.data_json = details
    row.raw_payload_id = raw_payload_id
    row.data_as_of = record.period_end.isoformat()
    row.collected_at = utcnow()
    return "updated"


# --- backfill run -------------------------------------------------------------

OUTCOMES = ("inserted", "updated", "dated", "unchanged")


def _taipei_day(value: datetime) -> date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI).date()


def backfill_quarterly_fundamentals(
    db: Session,
    *,
    quarters: int = DEFAULT_QUARTERS,
    end: Quarter | None = None,
    fetcher: Callable[[str, dict[str, str]], str] = fetch_html,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 3.0,
) -> dict[str, Any]:
    """Fetch ``quarters`` quarters up to ``end`` for both markets and store them.

    One ``fundamental_backfill`` ingestion run; ``coverage_manifest`` holds
    each market-quarter's counts.  Quarters run oldest first, listed before
    OTC; each market-quarter is committed, so an interrupted run keeps what
    it finished.  A quarter that has not ended, a count outside
    1..``MAX_QUARTERS`` or an unknown quarter are refused before any request.
    """

    today = _taipei_day(utcnow())
    if not 1 <= quarters <= MAX_QUARTERS:
        raise ValueError(f"quarters must be 1..{MAX_QUARTERS}")
    end = end or Quarter.latest_ended(today)
    if end.period_end >= today:
        raise ValueError(f"{end.label} has not ended on {today.isoformat()}")
    targets = quarter_range(end, quarters)
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        # The Taipei day, as the other runs (review of PR #533).
        run_date=_taipei_day(now),
        status="running",
        started_at=now,
        data_as_of=end.period_end.isoformat(),
        metadata_json={
            "start_quarter": targets[0].label,
            "end_quarter": end.label,
            "endpoint": ENDPOINT,
        },
    )
    db.add(run)
    db.flush()
    instruments = {
        (item.exchange, item.symbol): item for item in db.scalars(select(Instrument))
    }
    db.commit()
    manifest: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    totals = dict.fromkeys((*OUTCOMES, "outside_universe"), 0)
    failures_in_a_row = 0
    aborted: str | None = None
    key = ""

    def summarize(status: str) -> None:
        run.status = status
        run.records = totals["inserted"] + totals["updated"] + totals["dated"]
        run.metadata_json = {
            **run.metadata_json,
            "coverage_manifest": manifest,
            "totals": dict(totals),
            "warnings": warnings,
            "aborted": aborted,
        }

    first = True
    try:
        for quarter in targets:
            for market, exchange in MARKETS.items():
                key = f"{quarter.label}:{market}"
                if not first:
                    sleep(interval_seconds)
                first = False
                item = _fetch_and_store(
                    db, run, market, exchange, quarter, fetcher, instruments
                )
                manifest[key] = item
                if item["status"] == "failed":
                    warnings.append(f"{key}: {item['error']}")
                    failures_in_a_row += 1
                else:
                    failures_in_a_row = 0
                    for name in totals:
                        totals[name] += item[name]
                summarize("running")
                db.commit()
                if failures_in_a_row >= ABORT_AFTER_FAILURES:
                    aborted = f"stopped after {failures_in_a_row} failures at {key}"
                    break
            if aborted:
                break
    except Exception as exc:
        db.rollback()
        manifest.pop(key, None)
        aborted = f"error at {key}: {exc}"
        summarize("failed")
        run.error = aborted
        run.finished_at = utcnow()
        db.commit()
        raise
    summarize("partial" if warnings or aborted else "success")
    run.error = aborted
    run.finished_at = utcnow()
    db.commit()
    return {
        "status": run.status,
        "run_id": run.id,
        "start_quarter": targets[0].label,
        "end_quarter": end.label,
        "requests": len(manifest),
        "changed": run.records,
        **totals,
        "aborted": aborted,
        "warnings": warnings,
        "quarters": {
            name: {
                field_name: value
                for field_name, value in item.items()
                if field_name not in {"raw_sha256"}
            }
            for name, item in manifest.items()
        },
    }


def _fetch_and_store(
    db: Session,
    run: IngestionRun,
    market: str,
    exchange: str,
    quarter: Quarter,
    fetcher: Callable[[str, dict[str, str]], str],
    instruments: dict[tuple[str, str], Instrument],
) -> dict[str, Any]:
    form = request_form(market, quarter)
    try:
        html = fetcher(ENDPOINT, form)
    except OfficialDataError as exc:
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:  # a fetcher failure is the source's, never a crash
        return {"status": "failed", "error": f"official endpoint failed: {exc}"}
    captured = capture_payload(
        RAW_SOURCE,
        ENDPOINT,
        {"endpoint": ENDPOINT, "method": "POST", "form": form, "html": html},
        quarter.period_end.isoformat(),
    )
    raw = pipeline._upsert_raw_payload(db, run, captured)
    db.flush()
    item: dict[str, Any] = {"raw_sha256": captured.sha256, "raw_payload_id": raw.id}
    try:
        rows = parse_report(html, market, quarter)
    except OfficialDataError as exc:
        return {**item, "status": "failed", "error": str(exc)}
    first_seen = _taipei_day(captured.collected_at)
    deadlines: dict[str, tuple[date, str]] = {}
    counts = dict.fromkeys((*OUTCOMES, "outside_universe"), 0)
    formats: dict[str, int] = {}
    for row in rows:
        formats[row.report_format] = formats.get(row.report_format, 0) + 1
        instrument = instruments.get((exchange, row.symbol))
        if instrument is None:
            counts["outside_universe"] += 1
            continue
        if row.report_format not in deadlines:
            deadlines[row.report_format] = roll_to_session(
                db, nominal_deadline(row.report_format, quarter)
            )
        deadline, calendar = deadlines[row.report_format]
        available, basis = availability(deadline, first_seen)
        record = _record(
            row, market, quarter, available, basis, deadline, calendar, captured.sha256
        )
        counts[apply_record(db, record, instrument, raw.id)] += 1
    db.flush()
    return {
        **item,
        "status": "success" if rows else "empty",
        "rows": len(rows),
        "formats": formats,
        "deadlines": {
            name: {"date": value.isoformat(), "calendar": calendar}
            for name, (value, calendar) in sorted(deadlines.items())
        },
        **counts,
    }


def run_fundamental_backfill(quarters: int, end: str | None) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            result = backfill_quarterly_fundamentals(
                db, quarters=quarters, end=Quarter.parse(end) if end else None
            )
        except ValueError as exc:
            # Refused before any request (range, quarter not ended).
            db.rollback()
            return {"status": "failed", "error": str(exc)}
        return result
