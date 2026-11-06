"""Monthly revenue: the daily snapshot write and the MOPS ``t21sc03`` backfill (Issue #530).

collect reads the OpenAPI snapshots ``t187ap05_L``／``mopsfin_t187ap05_O``
(``sources.parse_monthly_revenue_rows``); they carry only the latest month and
one 出表日期 for the whole table.  ``store_monthly_revenues`` writes them, and
a failure there is a non-core warning like a failed fetch.

The backfill reads the MOPS 營業收入統計表 static pages, one per market, month
and page: ``_0`` lists domestic companies, ``_1`` foreign ones (``-KY``,
``-DR``); the two do not overlap and together cover the snapshot's companies.
Each page is Big5 HTML, one table per industry, with the snapshot's columns
(``PAGE_HEADER``) in NT$ thousands; percentages are truncated to two decimals.
The page's own 出表日期 is the day it was generated, not when a company filed.

A backfilled month has no filing time.  Its availability is the statutory
deadline, the 10th of the next month (證券交易法第 36 條), rolled forward to a
session, ``data_json.announcement_basis = statutory_deadline``; while the
deadline is ahead it is the Taipei date the page was fetched (``first_seen``).
Two sources meet on one month as in #529: a snapshot row keeps its values and
source and only takes an earlier date from the backfill; a backfilled row takes
the snapshot's values and keeps the earlier date.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import IngestionRun, Instrument, MonthlyRevenue
from worker import pipeline
from worker.quarterly_fundamentals import availability, over_budget, roll_to_session
from worker.sources import (
    MonthlyRevenueRecord,
    OfficialDataError,
    _throttle_official_host,
    capture_payload,
    month_end,
    monthly_revenue_warning,
    parse_number,
)

PAGE_URL = (
    "https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{year}_{month}_{page}.html"
)
ENDPOINT_NAME = "MOPS t21sc03 營業收入統計表"
SOURCE = "mops_t21sc03"
RAW_SOURCE = "mops"
RUN_TYPE = "revenue_backfill"
MARKETS = {"sii": "TWSE", "otc": "TPEx"}
MARKET_TITLES = {"sii": "上市", "otc": "上櫃"}
# ``_0`` domestic companies, ``_1`` foreign ones; the footer names which.
PAGES = {0: "國內", 1: "國外"}
DEFAULT_MONTHS = 24
MAX_MONTHS = 60
DEADLINE_DAY = 10
# Failed pages in a row that stop a run (the source is likely blocking).
ABORT_AFTER_FAILURES = 3
TAIPEI = timezone(timedelta(hours=8))
PAGE_ENCODING = "cp950"
# Waits before the second, third and fourth try of one page (review of PR #533).
RETRY_DELAYS_SECONDS = (5.0, 10.0, 20.0)
BLOCK_MARKERS = ("FOR SECURITY REASONS", "查詢過於頻繁", "THE PAGE CANNOT BE ACCESSED")
PAGE_HEADER = (
    "公司代號",
    "公司名稱",
    "當月營收",
    "上月營收",
    "去年當月營收",
    "上月比較增減(%)",
    "去年同月增減(%)",
    "當月累計營收",
    "去年累計營收",
    "前期比較增減(%)",
)
_CODE = re.compile(r"[0-9A-Z]{4,6}")
OUTCOMES = ("inserted", "updated", "dated", "unchanged")


# --- months -------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Month:
    year: int
    month: int

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return month_end(self.first_day)

    @property
    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    def previous(self) -> Month:
        if self.month == 1:
            return Month(self.year - 1, 12)
        return Month(self.year, self.month - 1)

    def next(self) -> Month:
        if self.month == 12:
            return Month(self.year + 1, 1)
        return Month(self.year, self.month + 1)

    @classmethod
    def parse(cls, text: str) -> Month:
        match = re.fullmatch(r"(\d{4})-(\d{2})", text.strip())
        if not match or not 1 <= int(match.group(2)) <= 12:
            raise ValueError(f"month {text!r} is not YYYY-MM")
        return cls(int(match.group(1)), int(match.group(2)))

    @classmethod
    def latest_ended(cls, today: date) -> Month:
        """The month before ``today``'s: the last one that has ended."""

        return cls(today.year, today.month).previous()


def month_range(end: Month, count: int) -> list[Month]:
    months = [end]
    while len(months) < count:
        months.append(months[-1].previous())
    return sorted(months)


def page_url(market: str, month: Month, page: int) -> str:
    return PAGE_URL.format(
        market=market, year=month.year - 1911, month=month.month, page=page
    )


def nominal_deadline(month: Month) -> date:
    following = month.next()
    return date(following.year, following.month, DEADLINE_DAY)


# --- writes -------------------------------------------------------------------


def _same_values(row: MonthlyRevenue, record: MonthlyRevenueRecord) -> bool:
    return (
        row.revenue == record.revenue
        and row.prior_year_revenue == record.prior_year_revenue
        and row.yoy == record.yoy
        and row.cumulative_revenue == record.cumulative_revenue
    )


def _insert(
    db: Session, record: MonthlyRevenueRecord, instrument: Instrument, raw_id: int
) -> str:
    db.add(
        MonthlyRevenue(
            instrument_id=instrument.id,
            revenue_month=record.revenue_month,
            revenue=record.revenue,
            prior_year_revenue=record.prior_year_revenue,
            yoy=record.yoy,
            cumulative_revenue=record.cumulative_revenue,
            announcement_date=record.announcement_date,
            source=record.source,
            raw_payload_id=raw_id,
            data_json=record.details,
            data_as_of=month_end(record.revenue_month).isoformat(),
            collected_at=utcnow(),
        )
    )
    return "inserted"


def _basis_keys(details: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: (details or {})[key]
        for key in pipeline.ANNOUNCEMENT_KEYS
        if key in (details or {})
    }


def _write_values(
    row: MonthlyRevenue,
    record: MonthlyRevenueRecord,
    announcement: date,
    details: dict[str, Any],
    raw_id: int,
) -> str:
    """Take the record's values, or ``unchanged`` when nothing would change.

    The details, raw payload id and ``collected_at`` change only with the
    values, the source or the availability date and its basis, so a row points
    at the capture its values came from, and a rerun, or a snapshot republished
    with a new 出表日期 and the same numbers, changes nothing.
    """

    if (
        row.announcement_date == announcement
        and _same_values(row, record)
        and row.source == record.source
        and _basis_keys(row.data_json) == _basis_keys(details)
    ):
        return "unchanged"
    row.announcement_date = announcement
    row.revenue = record.revenue
    row.prior_year_revenue = record.prior_year_revenue
    row.yoy = record.yoy
    row.cumulative_revenue = record.cumulative_revenue
    row.source = record.source
    row.data_json = details
    row.raw_payload_id = raw_id
    row.data_as_of = month_end(record.revenue_month).isoformat()
    row.collected_at = utcnow()
    return "updated"


def _existing(
    db: Session, record: MonthlyRevenueRecord, instrument: Instrument
) -> MonthlyRevenue | None:
    return db.scalar(
        select(MonthlyRevenue).where(
            MonthlyRevenue.instrument_id == instrument.id,
            MonthlyRevenue.revenue_month == record.revenue_month,
        )
    )


def apply_snapshot(
    db: Session, record: MonthlyRevenueRecord, instrument: Instrument, raw_id: int
) -> str:
    """Write one snapshot month; ``inserted``, ``updated`` or ``unchanged``.

    The values are the snapshot's, the availability date the earlier of the
    stored and the new one (``pipeline.first_seen_announcement``): the feed
    restamps 出表日期 when it is published again, and a backfilled row's
    deadline is usually earlier.
    """

    row = _existing(db, record, instrument)
    if row is None:
        return _insert(db, record, instrument, raw_id)
    announcement, details = pipeline.first_seen_announcement(
        row, record.announcement_date, record.details
    )
    assert announcement is not None
    return _write_values(row, record, announcement, details, raw_id)


def _basis(details: dict[str, Any] | None) -> str | None:
    return (details or {}).get("announcement_basis")


def apply_backfill(
    db: Session, record: MonthlyRevenueRecord, instrument: Instrument, raw_id: int
) -> str:
    """Write one backfilled month; ``inserted``, ``updated``, ``dated`` or ``unchanged``.

    A row the snapshot wrote keeps its values and source; only an earlier
    availability date is taken, with its basis.  A stored statutory deadline is
    recomputed rather than kept, so a holiday calendar loaded later corrects it.
    """

    row = _existing(db, record, instrument)
    if row is None:
        return _insert(db, record, instrument, raw_id)
    if (
        _basis(row.data_json) == "statutory_deadline"
        and _basis(record.details) == "statutory_deadline"
    ):
        announcement, details = record.announcement_date, record.details
    else:
        found, details = pipeline.first_seen_announcement(
            row, record.announcement_date, record.details
        )
        assert found is not None
        announcement = found
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
    return _write_values(row, record, announcement, details, raw_id)


def store_monthly_revenues(
    db: Session,
    records: list[MonthlyRevenueRecord],
    instruments: dict[tuple[str, str], Instrument],
    raw_id: Callable[[str | None], int | None],
    warnings: list[str],
) -> dict[str, int]:
    """collect's write step for the snapshot month; counts by outcome.

    Each exchange is written in its own savepoint: a failure there becomes that
    exchange's non-core warning and writes none of its rows.  A code that is not
    a collected instrument is counted ``outside_universe``.
    """

    counts: dict[str, int] = {}
    for exchange in sorted({record.exchange for record in records}):
        mine = [record for record in records if record.exchange == exchange]
        outcome: dict[str, int] = {}
        try:
            with db.begin_nested():
                for record in mine:
                    instrument = instruments.get((record.exchange, record.symbol))
                    if instrument is None:
                        name = "outside_universe"
                    else:
                        identifier = raw_id(record.payload_sha256)
                        if identifier is None:
                            raise ValueError(
                                f"no raw payload for the monthly revenue of {record.symbol}"
                            )
                        name = apply_snapshot(db, record, instrument, identifier)
                    outcome[name] = outcome.get(name, 0) + 1
                db.flush()
        except Exception as exc:
            warnings.append(monthly_revenue_warning(exchange, exc))
            outcome = {"failed": len(mine)}
        for name, value in outcome.items():
            counts[name] = counts.get(name, 0) + value
    return counts


# --- MOPS t21sc03 page --------------------------------------------------------


class _RowParser(HTMLParser):
    """Every table row's cell texts (whitespace collapsed) and the page text.

    Tables nest (industry tables sit in cells of the page table), and the
    page's last row has no ``</tr>``: a ``</table>`` closes the rows and cells
    still open inside it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.text: list[str] = []
        self._rows: list[list[str]] = []
        self._cells: list[list[str]] = []
        self._tables: list[tuple[int, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._tables.append((len(self._rows), len(self._cells)))
        elif tag == "tr":
            self._rows.append([])
        elif tag in {"td", "th"} and self._rows:
            self._cells.append([])

    def _close_cell(self) -> None:
        self._rows[-1].append(" ".join("".join(self._cells.pop()).split()))

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cells and self._rows:
            self._close_cell()
        elif tag == "tr" and self._rows:
            self.rows.append(self._rows.pop())
        elif tag == "table" and self._tables:
            rows, cells = self._tables.pop()
            while len(self._cells) > cells and self._rows:
                self._close_cell()
            while len(self._rows) > rows:
                self.rows.append(self._rows.pop())

    def handle_data(self, data: str) -> None:
        if self._cells:
            self._cells[-1].append(data)
        self.text.append(data)


@dataclass(frozen=True)
class PageRow:
    symbol: str
    name: str
    revenue: float | None
    prior_year_revenue: float | None
    yoy: float | None
    cumulative_revenue: float | None
    cells: dict[str, str]


def parse_page(html: str, market: str, month: Month, page: int) -> list[PageRow]:
    """Every company row of one ``t21sc03`` page; raise when it cannot be trusted.

    The title must name the market and month, the footer total the page's
    domestic or foreign half; every column header must be ``PAGE_HEADER``, every
    company row (a first cell that is a code) must have its eleven cells, and no
    code may appear twice.  Industry 合計 rows are not companies.
    """

    label = f"MOPS t21sc03 {market} {month.label} _{page}"
    upper = html.upper()
    if any(marker.upper() in upper for marker in BLOCK_MARKERS):
        raise OfficialDataError(f"{label} was refused by the source")
    parser = _RowParser()
    parser.feed(html)
    parser.close()
    text = "".join("".join(parser.text).split())
    title = f"{MARKET_TITLES[market]}公司{month.year - 1911}年{month.month}月份"
    if title not in text:
        raise OfficialDataError(f"{label} is not the {title} page")
    footer = f"全部{PAGES[page]}{MARKET_TITLES[market]}公司合計"
    if footer not in text:
        raise OfficialDataError(f"{label} has no {footer} total")
    result: list[PageRow] = []
    seen: set[str] = set()
    for cells in parser.rows:
        if not cells:
            continue
        if cells[0] == "公司代號":
            if tuple(cells) != PAGE_HEADER:
                raise OfficialDataError(f"{label} columns changed: {cells!r}")
            continue
        if not _CODE.fullmatch(cells[0]):
            continue
        if len(cells) != len(PAGE_HEADER) + 1:
            raise OfficialDataError(f"{label} has a malformed row: {cells[:2]!r}")
        if cells[0] in seen:
            raise OfficialDataError(f"{label} lists {cells[0]} twice")
        seen.add(cells[0])
        row = dict(zip((*PAGE_HEADER, "備註"), cells))
        result.append(
            PageRow(
                symbol=cells[0],
                name=row["公司名稱"],
                revenue=parse_number(row["當月營收"]),
                prior_year_revenue=parse_number(row["去年當月營收"]),
                yoy=parse_number(row["去年同月增減(%)"]),
                cumulative_revenue=parse_number(row["當月累計營收"]),
                cells=row,
            )
        )
    return result


# --- fetch --------------------------------------------------------------------


def fetch_page(url: str, *, timeout_seconds: float = 60.0) -> str:
    """GET one page and decode it from Big5 (cp950); transient failures retry.

    MOPS answers an occasional 502 ``Unreachable Server`` (seen while probing,
    #530); a try 10 seconds later succeeded.  A transport error, 429 or 5xx is
    retried after ``RETRY_DELAYS_SECONDS`` (5, 10, 20 s), so a short outage
    does not fail a page of a 96-page run.
    """

    headers = {"User-Agent": "taiwan-stock-research/0.1"}
    attempts = len(RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        _throttle_official_host(url)
        try:
            response = httpx.get(url, timeout=timeout_seconds, headers=headers)
        except httpx.TransportError as exc:
            if attempt + 1 >= attempts:
                raise OfficialDataError(
                    f"official endpoint transport retry exhausted: {url}"
                ) from exc
            time.sleep(RETRY_DELAYS_SECONDS[attempt])
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt + 1 >= attempts:
                raise OfficialDataError(
                    f"official endpoint retry exhausted ({response.status_code}): {url}"
                )
            time.sleep(RETRY_DELAYS_SECONDS[attempt])
            continue
        if response.status_code != 200:
            raise OfficialDataError(
                f"official endpoint rejected request ({response.status_code}): {url}"
            )
        try:
            return response.content.decode(PAGE_ENCODING)
        except UnicodeDecodeError as exc:
            raise OfficialDataError(f"{url} is not {PAGE_ENCODING}: {exc}") from exc
    raise OfficialDataError(f"official endpoint retry budget exhausted: {url}")


# --- backfill run -------------------------------------------------------------


def _taipei_day(value: datetime) -> date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI).date()


def _record(
    row: PageRow,
    market: str,
    page: int,
    month: Month,
    available: date,
    basis: str,
    deadline: date,
    calendar: str,
    payload_sha256: str,
) -> MonthlyRevenueRecord:
    details: dict[str, Any] = {
        **row.cells,
        "TYPEK": market,
        "page": page,
        "announcement_basis": basis,
        "statutory_deadline": deadline.isoformat(),
        "deadline_calendar": calendar,
    }
    return MonthlyRevenueRecord(
        symbol=row.symbol,
        exchange=MARKETS[market],
        revenue_month=month.first_day,
        revenue=row.revenue,
        prior_year_revenue=row.prior_year_revenue,
        yoy=row.yoy,
        cumulative_revenue=row.cumulative_revenue,
        announcement_date=available,
        details=details,
        source=SOURCE,
        payload_sha256=payload_sha256,
    )


def backfill_monthly_revenues(
    db: Session,
    *,
    months: int = DEFAULT_MONTHS,
    end: Month | None = None,
    fetcher: Callable[[str], str] = fetch_page,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 3.0,
    budget_seconds: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Fetch ``months`` months up to ``end`` for both markets and both pages.

    One ``revenue_backfill`` ingestion run; ``coverage_manifest`` holds each
    page's counts.  Months run oldest first, listed before OTC, domestic before
    foreign; each page is committed, so an interrupted run keeps what it
    finished.  A month that has not ended, a count outside 1..``MAX_MONTHS`` or
    an unknown month are refused before any request.  ``budget_seconds``,
    ``clock`` and ``trigger`` as in
    ``quarterly_fundamentals.backfill_quarterly_fundamentals``.
    """

    today = _taipei_day(utcnow())
    if not 1 <= months <= MAX_MONTHS:
        raise ValueError(f"months must be 1..{MAX_MONTHS}")
    end = end or Month.latest_ended(today)
    if end.last_day >= today:
        raise ValueError(f"{end.label} has not ended on {today.isoformat()}")
    targets = month_range(end, months)
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        # The Taipei day, as the other runs (review of PR #533).
        run_date=_taipei_day(now),
        status="running",
        started_at=now,
        data_as_of=end.last_day.isoformat(),
        metadata_json={
            "start_month": targets[0].label,
            "end_month": end.label,
            "endpoint": PAGE_URL,
            "trigger": trigger,
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
    totals = dict.fromkeys((*OUTCOMES, "outside_universe", "duplicate"), 0)
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
    started = clock()
    try:
        for month in targets:
            deadline, calendar = roll_to_session(db, nominal_deadline(month))
            for market in MARKETS:
                # The page each code of this market and month was read from.
                seen: dict[str, int] = {}
                for page in PAGES:
                    key = f"{month.label}:{market}:{page}"
                    aborted = over_budget(budget_seconds, clock() - started, key)
                    if aborted:
                        break
                    if not first:
                        sleep(interval_seconds)
                    first = False
                    item = _fetch_and_store(
                        db,
                        run,
                        market,
                        page,
                        month,
                        (deadline, calendar),
                        fetcher,
                        instruments,
                        seen,
                    )
                    manifest[key] = item
                    if item["status"] == "failed":
                        warnings.append(f"{key}: {item['error']}")
                        failures_in_a_row += 1
                    else:
                        failures_in_a_row = 0
                        if item["duplicate"]:
                            codes = ", ".join(item["duplicate_codes"])
                            warnings.append(
                                f"{key}: {codes} also on another page this month; "
                                "kept the first page's row"
                            )
                        for name in totals:
                            totals[name] += item[name]
                    summarize("running")
                    db.commit()
                    if failures_in_a_row >= ABORT_AFTER_FAILURES:
                        aborted = f"stopped after {failures_in_a_row} failures at {key}"
                        break
                if aborted:
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
        "start_month": targets[0].label,
        "end_month": end.label,
        "requests": len(manifest),
        "changed": run.records,
        **totals,
        "aborted": aborted,
        "warnings": warnings,
        "pages": {
            name: {
                field_name: value
                for field_name, value in item.items()
                if field_name != "raw_sha256"
            }
            for name, item in manifest.items()
        },
    }


def _fetch_and_store(
    db: Session,
    run: IngestionRun,
    market: str,
    page: int,
    month: Month,
    deadline_and_calendar: tuple[date, str],
    fetcher: Callable[[str], str],
    instruments: dict[tuple[str, str], Instrument],
    seen: dict[str, int],
) -> dict[str, Any]:
    """Fetch, keep the raw, parse and write one page; its manifest entry.

    ``seen`` maps each code of this market and month to the page it was read
    from.  The two pages do not overlap; a code the other page already listed
    is not written again (the first page's row stays) and is counted
    ``duplicate``, which the run reports as a warning.
    """

    url = page_url(market, month, page)
    try:
        html = fetcher(url)
    except OfficialDataError as exc:
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:  # a fetcher failure is the source's, never a crash
        return {"status": "failed", "error": f"official endpoint failed: {exc}"}
    captured = capture_payload(
        RAW_SOURCE,
        url,
        {"endpoint": url, "method": "GET", "encoding": PAGE_ENCODING, "html": html},
        month.last_day.isoformat(),
    )
    raw = pipeline._upsert_raw_payload(db, run, captured)
    db.flush()
    item: dict[str, Any] = {"raw_sha256": captured.sha256, "raw_payload_id": raw.id}
    try:
        rows = parse_page(html, market, month, page)
    except OfficialDataError as exc:
        return {**item, "status": "failed", "error": str(exc)}
    deadline, calendar = deadline_and_calendar
    available, basis = availability(deadline, _taipei_day(captured.collected_at))
    counts = dict.fromkeys((*OUTCOMES, "outside_universe", "duplicate"), 0)
    duplicate_codes: list[str] = []
    for row in rows:
        if seen.get(row.symbol, page) != page:
            counts["duplicate"] += 1
            duplicate_codes.append(row.symbol)
            continue
        seen[row.symbol] = page
        instrument = instruments.get((MARKETS[market], row.symbol))
        if instrument is None:
            counts["outside_universe"] += 1
            continue
        record = _record(
            row,
            market,
            page,
            month,
            available,
            basis,
            deadline,
            calendar,
            captured.sha256,
        )
        counts[apply_backfill(db, record, instrument, raw.id)] += 1
    db.flush()
    return {
        **item,
        "status": "success" if rows else "empty",
        "rows": len(rows),
        "deadline": {"date": deadline.isoformat(), "calendar": calendar},
        "availability": {"date": available.isoformat(), "basis": basis},
        **counts,
        "duplicate_codes": duplicate_codes,
    }


def run_revenue_backfill(months: int, end: str | None) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            result = backfill_monthly_revenues(
                db, months=months, end=Month.parse(end) if end else None
            )
        except ValueError as exc:
            # Refused before any request (range, month not ended).
            db.rollback()
            return {"status": "failed", "error": str(exc)}
        return result
