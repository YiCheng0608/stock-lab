"""Monthly revenue of delisted and transferred companies in the research database (Issue #782).

The MOPS 營業收入統計表 pages (``monthly_revenue``) list today's companies
only (#781 AC-1), so the research history has no month of a company that left
the lists.  Two ways fill part of that:

* **Transfers, no request** (``transfer_revenues``).  A company that moved
  from TPEx to TWSE is two instruments; today's TWSE page lists its OTC years,
  so they sit on the TWSE instrument, before its first TWSE bar.  The months of
  the old instrument's range (``revenue_months``) are copied to it with
  ``source = SOURCE_TRANSFER`` and ``data_json.copied_from``; the TWSE rows
  stay (decision 6894566253 1: a move would leave ``revenue_high_12`` without
  its year after the transfer).  The two must be one company: the same name
  (a trailing ``*`` aside) and bars that meet (``ADJACENT_DAYS``).  A rerun
  copies a corrected TWSE row again.
* **The single-company page** ``ajax_t05st10_ifrs``, one request per company
  and month.  It answers for a company still 公開發行 after it delisted, and
  「不繼續公開發行」 for one that is not (bankrupt, merged away; #781 AC-2).
  ``classify_companies`` asks once per delisted instrument, for its last month
  with a bar; ``backfill_companies`` asks the rest of the range of the ones
  found.  A page naming another company (a code given to a later one) is
  skipped: neither name contains the other.

Every answer is kept in ``raw_payloads`` under the key ``company_endpoint``
(the code and month) and read back instead of asked again, so either command
resumes where it stopped and the classification needs no table of its own.
Availability is the statutory deadline, as the other backfilled months.

Requests (decision 6894566253): at least ``INTERVAL_SECONDS`` apart, none in
``QUIET_HOURS`` (the run stops, ``partial``; a rerun goes on), no retry, and
three failures in a row stop the run.  All three refuse a database without
the research marker (``refusal``).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import IngestionRun, Instrument, MarketBar, MonthlyRevenue, RawPayload
from app.raw_paths import payload_file
from worker import pipeline
from worker.monthly_revenue import BLOCK_MARKERS, Month, nominal_deadline
from worker.quarterly_fundamentals import availability, roll_to_session
from worker.sources import (
    OfficialDataError,
    _throttle_official_host,
    capture_payload,
    month_end,
    parse_number,
)

ENDPOINT = "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs"
SOURCE_TRANSFER = "mops_t21sc03_transfer"
SOURCE_COMPANY = "mops_t05st10"
RAW_SOURCE = "mops"
RUN_TRANSFER = "revenue_transfer_copy"
RUN_CLASSIFY = "revenue_company_classify"
RUN_BACKFILL = "revenue_company_backfill"
# The MOPS monthly revenue history starts here (t21sc03; t05st10 answers
# 102/01 too, #781 request 18).
FIRST_MONTH = Month(2013, 1)
# Months before the first bar: the longest look-back of the tools/research
# features on monthly revenue, ``feature_evidence.revenue_high_12`` (the
# latest month against the 11 before it).  A listed company has those months
# (#782 decision 2), so a delisted one gets them too.
LOOKBACK_MONTHS = 12
# #702 and #781 ask MOPS too (task file of #782).
INTERVAL_SECONDS = 5.0
# Taipei: the production daily and the morning collect (decision 6894566253 4).
QUIET_HOURS = (
    (clock_time(20, 30), clock_time(23, 30)),
    (clock_time(8, 0), clock_time(9, 0)),
)
ABORT_AFTER_FAILURES = 3
# The new instrument's first bar within this many days of the old one's last.
ADJACENT_DAYS = 7
TAIPEI = timezone(timedelta(hours=8))
MARKER_NAME = "research-db.json"
MARKER_PURPOSE = "research_history"
NOT_PUBLIC_MARKER = "公開發行公司不繼續公開發行"
NO_DATA_MARKER = "查無資料"
FOUND, NOT_PUBLIC, NO_DATA = "found", "not_public", "no_data"
NAME_MISMATCH = "name_mismatch"
# The table's row labels in order and the data_json key of each value.
ROWS = (
    ("本月", "本月"),
    ("去年同期", "去年同期"),
    ("增減金額", "本月增減金額"),
    ("增減百分比", "本月增減百分比"),
    ("本年累計", "本年累計"),
    ("去年累計", "去年累計"),
    ("增減金額", "累計增減金額"),
    ("增減百分比", "累計增減百分比"),
)
TABLE_HEADER = ("項目", "營業收入淨額")
NOTE_LABEL = "備註 / 營收變化原因說明"
_PROVIDER = re.compile(r"本資料由(?:\((?P<kind>[^)]*)\))?(?P<name>.+?)公司提供")


# --- the research marker -------------------------------------------------------


def refusal(db_path: Path) -> str | None:
    """Why these commands may not run on ``db_path``; None for the research DB.

    Inside a container the research and production databases are both
    ``/data/stock.db``; only the research volume has ``MARKER_NAME`` beside it
    (docs/ops/RESEARCH_DB.md), as ``tools/research/history_backfill.py`` checks.
    """

    marker = db_path.parent / MARKER_NAME
    try:
        purpose = json.loads(marker.read_text(encoding="utf-8")).get("purpose")
    except (OSError, ValueError, AttributeError):
        purpose = None
    if purpose != MARKER_PURPOSE:
        return (
            f"{marker} is missing or not a research marker "
            f'(expected {{"purpose": "{MARKER_PURPOSE}"}}): not a research database'
        )
    return None


# --- months ---------------------------------------------------------------------


def _month(day: date) -> Month:
    return Month(day.year, day.month)


def _taipei(value: datetime) -> datetime:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI)


def revenue_months(first_bar: date, last_bar: date, today: date) -> list[Month]:
    """The months to fill for bars from ``first_bar`` to ``last_bar``, oldest first.

    ``LOOKBACK_MONTHS`` before the first bar's month through the last bar's,
    from ``FIRST_MONTH`` on and only months that have ended by ``today``.
    """

    start = _month(first_bar)
    for _ in range(LOOKBACK_MONTHS):
        start = start.previous()
    start = max(start, FIRST_MONTH)
    end = min(_month(last_bar), _month(today).previous())
    months: list[Month] = []
    month = start
    while month <= end:
        months.append(month)
        month = month.next()
    return months


def _bar_span(db: Session, instrument: Instrument) -> tuple[date, date] | None:
    first, last = db.execute(
        select(
            func.min(MarketBar.trading_date), func.max(MarketBar.trading_date)
        ).where(MarketBar.instrument_id == instrument.id)
    ).one()
    return None if first is None else (first, last)


def _stored_months(db: Session, instrument: Instrument) -> dict[date, MonthlyRevenue]:
    return {
        row.revenue_month: row
        for row in db.scalars(
            select(MonthlyRevenue).where(MonthlyRevenue.instrument_id == instrument.id)
        )
    }


def same_company(one: str, other: str) -> bool:
    """Whether two names are one company's: either contains the other.

    A trailing ``*`` (TWSE's mark on a name) does not count.
    """

    first, second = one.strip().rstrip("*").strip(), other.strip().rstrip("*").strip()
    return bool(first and second) and (first in second or second in first)


# --- transfers ------------------------------------------------------------------


def _new_run(db: Session, run_type: str, metadata: dict[str, Any]) -> IngestionRun:
    now = utcnow()
    run = IngestionRun(
        run_type=run_type,
        source="official",
        run_date=_taipei(now).date(),
        status="running",
        started_at=now,
        metadata_json=metadata,
    )
    db.add(run)
    db.flush()
    return run


def _copy_values(source: MonthlyRevenue, exchange: str) -> dict[str, Any]:
    return {
        "revenue": source.revenue,
        "prior_year_revenue": source.prior_year_revenue,
        "yoy": source.yoy,
        "cumulative_revenue": source.cumulative_revenue,
        "announcement_date": source.announcement_date,
        "raw_payload_id": source.raw_payload_id,
        "data_as_of": source.data_as_of,
        "data_json": {
            **(source.data_json or {}),
            "copied_from": {
                "instrument_id": source.instrument_id,
                "exchange": exchange,
                "source": source.source,
            },
        },
    }


def transfer_revenues(db: Session, *, apply: bool = False) -> dict[str, Any]:
    """Copy each transferred company's months from its listing on the other exchange.

    Without ``apply`` nothing is written: the plan per code.  With it, one
    ``RUN_TRANSFER`` run; a month the old instrument has from another source
    is kept (``kept``), a copy whose source row changed is updated.
    """

    today = _taipei(utcnow()).date()
    moved = db.scalars(
        select(Instrument)
        .where(Instrument.status == "transferred")
        .order_by(Instrument.symbol, Instrument.exchange)
    ).all()
    run = _new_run(db, RUN_TRANSFER, {"apply": apply}) if apply else None
    companies: list[dict[str, Any]] = []
    totals = dict.fromkeys(
        ("inserted", "updated", "unchanged", "kept", "no_source_row"), 0
    )
    for old in moved:
        item: dict[str, Any] = {
            "symbol": old.symbol,
            "exchange": old.exchange,
            "instrument_id": old.id,
            "name": old.name,
        }
        companies.append(item)
        twin = db.scalar(
            select(Instrument).where(
                Instrument.exchange == pipeline.OTHER_EXCHANGE[old.exchange],
                Instrument.symbol == old.symbol,
            )
        )
        if twin is None:
            item["skipped"] = "no instrument on the other exchange"
            continue
        item.update(twin_id=twin.id, twin_exchange=twin.exchange, twin_name=twin.name)
        if (
            old.name.strip().rstrip("*").strip()
            != twin.name.strip().rstrip("*").strip()
        ):
            item["skipped"] = "the names differ"
            continue
        span, twin_span = _bar_span(db, old), _bar_span(db, twin)
        if span is None or twin_span is None:
            item["skipped"] = "no bars on one of the two"
            continue
        gap = (twin_span[0] - span[1]).days
        item.update(bars=[span[0].isoformat(), span[1].isoformat()])
        item.update(twin_first_bar=twin_span[0].isoformat())
        if not 0 < gap <= ADJACENT_DAYS:
            item["skipped"] = f"the bars do not meet ({gap} days apart)"
            continue
        months = revenue_months(span[0], span[1], today)
        sources_rows = _stored_months(db, twin)
        stored = _stored_months(db, old)
        counts = dict.fromkeys(totals, 0)
        for month in months:
            source = sources_rows.get(month.first_day)
            if source is None:
                counts["no_source_row"] += 1
                continue
            values = _copy_values(source, twin.exchange)
            row = stored.get(month.first_day)
            if row is not None and row.source != SOURCE_TRANSFER:
                counts["kept"] += 1
                continue
            if row is not None and all(
                getattr(row, name) == value for name, value in values.items()
            ):
                counts["unchanged"] += 1
                continue
            outcome = "inserted" if row is None else "updated"
            counts[outcome] += 1
            if not apply:
                continue
            if row is None:
                row = MonthlyRevenue(
                    instrument_id=old.id, revenue_month=month.first_day
                )
                db.add(row)
            for name, value in values.items():
                setattr(row, name, value)
            row.source = SOURCE_TRANSFER
            row.collected_at = utcnow()
        item.update(
            months=[months[0].label, months[-1].label] if months else None,
            **counts,
        )
        for name, value in counts.items():
            totals[name] += value
    status = "success"
    if run is not None:
        db.flush()
        run.status = status
        run.records = totals["inserted"] + totals["updated"]
        run.finished_at = utcnow()
        run.metadata_json = {**run.metadata_json, "companies": companies, **totals}
        db.commit()
    else:
        db.rollback()
    return {
        "status": status,
        "apply": apply,
        "run_id": run.id if run is not None else None,
        **totals,
        "skipped": [item for item in companies if "skipped" in item],
        "companies": companies,
    }


# --- the single-company page ----------------------------------------------------


class _PageParser(HTMLParser):
    """The text, the hidden inputs and the cells of the ``hasBorder`` table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.inputs: dict[str, str] = {}
        self.cells: list[str] = []
        self._table = 0
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "input" and values.get("type") == "hidden" and "name" in values:
            self.inputs.setdefault(values["name"], values.get("value", ""))
        elif tag == "table":
            if self._table or "hasBorder" in values.get("class", "").split():
                self._table += 1
        elif tag in ("th", "td") and self._table:
            self._finish_cell()
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("th", "td") and self._table:
            self._finish_cell()
        elif tag == "table" and self._table:
            self._finish_cell()
            self._table -= 1

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def _finish_cell(self) -> None:
        if self._cell is not None:
            self.cells.append(" ".join("".join(self._cell).split()))
            self._cell = None


@dataclass(frozen=True)
class CompanyPage:
    """One answer: ``kind`` is ``FOUND``, ``NOT_PUBLIC`` or ``NO_DATA``."""

    kind: str
    name: str | None = None
    company_kind: str | None = None
    revenue: float | None = None
    prior_year_revenue: float | None = None
    yoy: float | None = None
    cumulative_revenue: float | None = None
    cells: dict[str, str] | None = None


def roc_form(code: str, month: Month) -> dict[str, str]:
    """The POST form of one company and month (#781 AC-2 requests 1～3, 13, 18)."""

    return {
        "encodeURIComponent": "1",
        "run": "Y",
        "step": "0",
        "firstin": "true",
        "off": "1",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": "all",
        "isnew": "false",
        "co_id": code,
        "year": str(month.year - 1911),
        "month": f"{month.month:02d}",
    }


def company_endpoint(code: str, month: Month) -> str:
    """The ``raw_payloads.endpoint`` of one company and month: the resume key."""

    return f"{ENDPOINT}?co_id={code}&year={month.year - 1911}&month={month.month:02d}"


def parse_company_page(html: str, code: str, month: Month) -> CompanyPage:
    """Read one ``t05st10_ifrs`` answer; raise ``OfficialDataError`` when it cannot be trusted.

    A found page must be the asked code and month (the hidden ``Q1V``/``Q2V``
    and the printed 民國 month) and have the table's eight rows in order.
    """

    label = f"MOPS t05st10 {code} {month.label}"
    upper = html.upper()
    if any(marker.upper() in upper for marker in BLOCK_MARKERS):
        raise OfficialDataError(f"{label} was refused by the source")
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    text = "".join("".join(parser.text).split())
    if f"該{code}{NOT_PUBLIC_MARKER}" in text:
        return CompanyPage(kind=NOT_PUBLIC)
    if not parser.cells:
        if NO_DATA_MARKER in text:
            return CompanyPage(kind=NO_DATA)
        raise OfficialDataError(f"{label} has no revenue table")
    roc = f"{month.year - 1911}{month.month:02d}"
    if parser.inputs.get("Q1V") != code or parser.inputs.get("Q2V") != roc:
        raise OfficialDataError(
            f"{label} answered {parser.inputs.get('Q1V')!r} {parser.inputs.get('Q2V')!r}"
        )
    printed = f"民國{month.year - 1911}年{month.month:02d}月"
    if printed not in text:
        raise OfficialDataError(f"{label} does not print {printed}")
    provider = _PROVIDER.search(text)
    if provider is None:
        raise OfficialDataError(f"{label} does not name the company")
    cells = parser.cells
    expected = len(TABLE_HEADER) + 2 * len(ROWS) + 2
    if (
        len(cells) != expected
        or tuple(cells[:2]) != TABLE_HEADER
        or tuple(cells[2 : 2 + 2 * len(ROWS) : 2]) != tuple(name for name, _ in ROWS)
        or cells[-2] != NOTE_LABEL
    ):
        raise OfficialDataError(f"{label} columns changed: {cells[:4]!r}")
    values = {key: cells[3 + 2 * index] for index, (_, key) in enumerate(ROWS)}
    if parse_number(values["本月"]) is None:
        raise OfficialDataError(f"{label} has no 本月 value")
    return CompanyPage(
        kind=FOUND,
        name=provider.group("name"),
        company_kind=provider.group("kind"),
        revenue=parse_number(values["本月"]),
        prior_year_revenue=parse_number(values["去年同期"]),
        yoy=parse_number(values["本月增減百分比"]),
        cumulative_revenue=parse_number(values["本年累計"]),
        cells={**values, "備註": cells[-1]},
    )


def fetch_company_page(form: dict[str, str], *, timeout_seconds: float = 60.0) -> bytes:
    """POST one form; the answer's bytes.  No retry (decision 6894566253)."""

    _throttle_official_host(ENDPOINT)
    try:
        response = httpx.post(
            ENDPOINT,
            data=form,
            timeout=timeout_seconds,
            headers={"User-Agent": "taiwan-stock-research/0.1"},
        )
    except httpx.TransportError as exc:
        raise OfficialDataError(f"official endpoint failed: {exc}") from exc
    if response.status_code != 200:
        raise OfficialDataError(
            f"official endpoint answered {response.status_code}: {ENDPOINT}"
        )
    return response.content


# --- requests -------------------------------------------------------------------


def quiet_hour(moment: datetime) -> bool:
    """Whether ``moment`` (UTC) falls in Taipei's ``QUIET_HOURS``."""

    now = _taipei(moment).time()
    return any(start <= now < end for start, end in QUIET_HOURS)


def _stored_answer(
    db: Session, code: str, month: Month
) -> tuple[RawPayload, str] | None:
    """The latest kept answer of this code and month that still reads; else None."""

    key = company_endpoint(code, month)
    rows = db.scalars(
        select(RawPayload)
        .join(IngestionRun, IngestionRun.id == RawPayload.ingestion_run_id)
        .where(
            RawPayload.source == RAW_SOURCE,
            RawPayload.endpoint == key,
            IngestionRun.run_type.in_((RUN_CLASSIFY, RUN_BACKFILL)),
        )
        .order_by(RawPayload.id.desc())
    ).all()
    for row in rows:
        try:
            payload = json.loads(payload_file(row.payload_path).read_text("utf-8"))
            html = payload["html"]
            parse_company_page(html, code, month)
        except (OSError, ValueError, KeyError, TypeError, OfficialDataError):
            continue
        return row, html
    return None


class _Requests:
    """The request rules of one run: interval, quiet hours, failures, a cap."""

    def __init__(
        self,
        fetcher: Callable[[dict[str, str]], bytes],
        sleep: Callable[[float], None],
        interval_seconds: float,
        max_requests: int | None,
    ) -> None:
        self.fetcher = fetcher
        self.sleep = sleep
        self.interval_seconds = interval_seconds
        self.max_requests = max_requests
        self.sent = 0
        self.failures_in_a_row = 0
        self.aborted: str | None = None

    def stop_before(self, key: str) -> bool:
        if self.max_requests is not None and self.sent >= self.max_requests:
            self.aborted = f"--max-requests {self.max_requests} reached before {key}"
        elif quiet_hour(utcnow()):
            self.aborted = f"quiet hours (Taipei) before {key}"
        return self.aborted is not None

    def ask(self, form: dict[str, str]) -> bytes:
        if self.sent:
            self.sleep(self.interval_seconds)
        self.sent += 1
        answer = self.fetcher(form)
        if not answer:
            raise OfficialDataError("empty answer")
        return answer

    def failed(self, key: str) -> None:
        self.failures_in_a_row += 1
        if self.failures_in_a_row >= ABORT_AFTER_FAILURES:
            self.aborted = f"stopped after {self.failures_in_a_row} failures at {key}"


def _answer(
    db: Session,
    run: IngestionRun,
    requests: _Requests,
    code: str,
    month: Month,
) -> dict[str, Any]:
    """One company and month: the kept answer or a new request; its manifest entry.

    ``page`` holds the ``CompanyPage``; ``status`` is ``stored``, ``fetched``
    or ``failed``.  Every non-empty answer is kept in ``raw_payloads``.
    """

    stored = _stored_answer(db, code, month)
    if stored is not None:
        raw, html = stored
        return {
            "status": "stored",
            "raw_payload_id": raw.id,
            "fetched_on": _taipei(raw.collected_at).date(),
            "page": parse_company_page(html, code, month),
        }
    key = company_endpoint(code, month)
    form = roc_form(code, month)
    try:
        content = requests.ask(form)
        html = content.decode("utf-8")
    except (OfficialDataError, UnicodeDecodeError) as exc:
        requests.failed(key)
        return {"status": "failed", "error": str(exc)}
    except Exception as exc:  # a fetcher failure is the source's, never a crash
        requests.failed(key)
        return {"status": "failed", "error": f"official endpoint failed: {exc}"}
    captured = capture_payload(
        RAW_SOURCE,
        key,
        {"endpoint": ENDPOINT, "method": "POST", "form": form, "html": html},
        month.last_day.isoformat(),
    )
    raw = pipeline._upsert_raw_payload(db, run, captured)
    db.flush()
    try:
        page = parse_company_page(html, code, month)
    except OfficialDataError as exc:
        requests.failed(key)
        return {"status": "failed", "error": str(exc), "raw_payload_id": raw.id}
    requests.failures_in_a_row = 0
    return {
        "status": "fetched",
        "raw_payload_id": raw.id,
        "fetched_on": _taipei(captured.collected_at).date(),
        "page": page,
    }


def _write_month(
    db: Session,
    instrument: Instrument,
    month: Month,
    page: CompanyPage,
    raw_id: int,
    fetched_on: date,
    code: str,
) -> str:
    """Insert one found month; ``inserted``, or ``exists`` when the month has a row."""

    exists = db.scalar(
        select(MonthlyRevenue.id).where(
            MonthlyRevenue.instrument_id == instrument.id,
            MonthlyRevenue.revenue_month == month.first_day,
        )
    )
    if exists is not None:
        return "exists"
    deadline, calendar = roll_to_session(db, nominal_deadline(month))
    available, basis = availability(deadline, fetched_on)
    details = {
        **(page.cells or {}),
        "co_id": code,
        "公司名稱": page.name,
        "公司類別": page.company_kind,
        "announcement_basis": basis,
        "statutory_deadline": deadline.isoformat(),
        "deadline_calendar": calendar,
    }
    db.add(
        MonthlyRevenue(
            instrument_id=instrument.id,
            revenue_month=month.first_day,
            revenue=page.revenue,
            prior_year_revenue=page.prior_year_revenue,
            yoy=page.yoy,
            cumulative_revenue=page.cumulative_revenue,
            announcement_date=available,
            source=SOURCE_COMPANY,
            raw_payload_id=raw_id,
            data_json=details,
            data_as_of=month_end(month.first_day).isoformat(),
            collected_at=utcnow(),
        )
    )
    db.flush()
    return "inserted"


@dataclass
class _Company:
    instrument: Instrument
    first_bar: date
    last_bar: date

    @property
    def last_month(self) -> Month:
        return _month(self.last_bar)


def delisted_companies(db: Session) -> tuple[list[_Company], dict[str, int]]:
    """The delisted stocks and IPOs whose last bar is from ``FIRST_MONTH`` on."""

    skipped = {"no_bars": 0, "before_first_month": 0}
    companies: list[_Company] = []
    for instrument in db.scalars(
        select(Instrument)
        .where(
            Instrument.status == "delisted",
            Instrument.instrument_type.in_(("stock", "ipo")),
        )
        .order_by(Instrument.exchange, Instrument.symbol)
    ):
        span = _bar_span(db, instrument)
        if span is None:
            skipped["no_bars"] += 1
        elif _month(span[1]) < FIRST_MONTH:
            skipped["before_first_month"] += 1
        else:
            companies.append(_Company(instrument, *span))
    return companies, skipped


def _classification(page: CompanyPage, instrument: Instrument) -> str:
    if page.kind == FOUND and not same_company(page.name or "", instrument.name):
        return NAME_MISMATCH
    return page.kind


def _finish(
    db: Session,
    run: IngestionRun,
    requests: _Requests,
    manifest: dict[str, Any],
    totals: dict[str, int],
    failed: int,
) -> str:
    status = "partial" if requests.aborted or failed else "success"
    run.status = status
    run.error = requests.aborted
    run.records = totals.get("inserted", 0)
    run.finished_at = utcnow()
    run.metadata_json = {
        **run.metadata_json,
        "manifest": manifest,
        "totals": dict(totals),
        "requests": requests.sent,
        "aborted": requests.aborted,
    }
    db.commit()
    return status


def _entry(answer: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "status": answer["status"],
        **(
            {"raw_payload_id": answer["raw_payload_id"]}
            if "raw_payload_id" in answer
            else {}
        ),
        **({"error": answer["error"]} if "error" in answer else {}),
        **extra,
    }


def classify_companies(
    db: Session,
    *,
    plan: bool = False,
    max_requests: int | None = None,
    fetcher: Callable[[dict[str, str]], bytes] = fetch_company_page,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Ask each delisted company's last month with a bar; ``found`` ones are written.

    ``plan`` sends nothing: the companies and how many have no kept answer.
    """

    companies, skipped = delisted_companies(db)
    if plan:
        pending = [
            company
            for company in companies
            if _stored_answer(db, company.instrument.symbol, company.last_month) is None
        ]
        db.rollback()
        return {
            "status": "success",
            "plan": True,
            "companies": len(companies),
            "requests": len(pending),
            "skipped": skipped,
            "by_exchange": _by_exchange(pending),
        }
    run = _new_run(db, RUN_CLASSIFY, {"companies": len(companies), "skipped": skipped})
    db.commit()
    requests = _Requests(fetcher, sleep, interval_seconds, max_requests)
    manifest: dict[str, Any] = {}
    totals: dict[str, int] = {}
    classes: dict[str, list[str]] = {}
    failed = 0
    for company in companies:
        instrument, month = company.instrument, company.last_month
        key = f"{instrument.exchange}:{instrument.symbol}:{month.label}"
        if _stored_answer(
            db, instrument.symbol, month
        ) is None and requests.stop_before(key):
            break
        answer = _answer(db, run, requests, instrument.symbol, month)
        if answer["status"] == "failed":
            failed += 1
            manifest[key] = _entry(answer)
        else:
            page = answer["page"]
            kind = _classification(page, instrument)
            extra: dict[str, Any] = {"class": kind, "page_name": page.name}
            if kind == FOUND:
                outcome = _write_month(
                    db,
                    instrument,
                    month,
                    page,
                    answer["raw_payload_id"],
                    answer["fetched_on"],
                    instrument.symbol,
                )
                extra["write"] = outcome
                totals[outcome] = totals.get(outcome, 0) + 1
            classes.setdefault(kind, []).append(
                f"{instrument.exchange}:{instrument.symbol}"
            )
            manifest[key] = _entry(answer, **extra)
        run.metadata_json = {**run.metadata_json, "manifest": manifest}
        db.commit()
        if requests.aborted:
            break
    status = _finish(db, run, requests, manifest, totals, failed)
    return {
        "status": status,
        "run_id": run.id,
        "requests": requests.sent,
        "failed": failed,
        "aborted": requests.aborted,
        "classes": {name: len(codes) for name, codes in sorted(classes.items())},
        "listed": {
            name: codes for name, codes in sorted(classes.items()) if name != FOUND
        },
        **totals,
    }


def _by_exchange(companies: list[_Company]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for company in companies:
        name = f"{company.instrument.exchange} {company.instrument.instrument_type}"
        counts[name] = counts.get(name, 0) + 1
    return counts


def backfill_companies(
    db: Session,
    *,
    plan: bool = False,
    max_requests: int | None = None,
    fetcher: Callable[[dict[str, str]], bytes] = fetch_company_page,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Ask the rest of each ``found`` company's months (``revenue_months``).

    A company is ``found`` by the kept answer of ``classify_companies``; one
    without it is ``unclassified`` and waits.  Months the instrument has are
    not asked; a page naming another company is skipped (``name_mismatch``).
    """

    today = _taipei(utcnow()).date()
    companies, _skipped = delisted_companies(db)
    work: list[tuple[_Company, list[Month]]] = []
    classes: dict[str, int] = {}
    for company in companies:
        instrument = company.instrument
        stored = _stored_answer(db, instrument.symbol, company.last_month)
        kind = (
            "unclassified"
            if stored is None
            else _classification(
                parse_company_page(stored[1], instrument.symbol, company.last_month),
                instrument,
            )
        )
        classes[kind] = classes.get(kind, 0) + 1
        if kind != FOUND:
            continue
        have = _stored_months(db, instrument)
        months = [
            month
            for month in revenue_months(company.first_bar, company.last_bar, today)
            if month.first_day not in have
        ]
        work.append((company, months))
    if plan:
        pending = sum(
            1
            for company, months in work
            for month in months
            if _stored_answer(db, company.instrument.symbol, month) is None
        )
        db.rollback()
        return {
            "status": "success",
            "plan": True,
            "classes": classes,
            "companies": len(work),
            "months": sum(len(months) for _company, months in work),
            "requests": pending,
        }
    run = _new_run(db, RUN_BACKFILL, {"classes": classes, "companies": len(work)})
    db.commit()
    requests = _Requests(fetcher, sleep, interval_seconds, max_requests)
    manifest: dict[str, Any] = {}
    totals: dict[str, int] = {}
    failed = 0
    for company, months in work:
        instrument = company.instrument
        for month in months:
            key = f"{instrument.exchange}:{instrument.symbol}:{month.label}"
            if _stored_answer(
                db, instrument.symbol, month
            ) is None and requests.stop_before(key):
                break
            answer = _answer(db, run, requests, instrument.symbol, month)
            if answer["status"] == "failed":
                failed += 1
                manifest[key] = _entry(answer)
            else:
                page = answer["page"]
                kind = _classification(page, instrument)
                if kind == FOUND:
                    outcome = _write_month(
                        db,
                        instrument,
                        month,
                        page,
                        answer["raw_payload_id"],
                        answer["fetched_on"],
                        instrument.symbol,
                    )
                else:
                    outcome = kind
                totals[outcome] = totals.get(outcome, 0) + 1
                manifest[key] = _entry(answer, write=outcome, page_name=page.name)
            run.metadata_json = {**run.metadata_json, "manifest": manifest}
            db.commit()
            if requests.aborted:
                break
        if requests.aborted:
            break
    status = _finish(db, run, requests, manifest, totals, failed)
    return {
        "status": status,
        "run_id": run.id,
        "classes": classes,
        "requests": requests.sent,
        "failed": failed,
        "aborted": requests.aborted,
        **totals,
    }


# --- commands -------------------------------------------------------------------


def _run(db_path: Path, work: Callable[[Session], dict[str, Any]]) -> dict[str, Any]:
    reason = refusal(db_path)
    if reason is not None:
        return {"status": "refused", "error": reason}
    from app.db import SessionLocal

    with SessionLocal() as db:
        return work(db)


def run_revenue_transfers(apply: bool, db_path: Path) -> dict[str, Any]:
    return _run(db_path, lambda db: transfer_revenues(db, apply=apply))


def run_revenue_company_classify(
    plan: bool, max_requests: int | None, db_path: Path
) -> dict[str, Any]:
    return _run(
        db_path,
        lambda db: classify_companies(db, plan=plan, max_requests=max_requests),
    )


def run_revenue_company_backfill(
    plan: bool, max_requests: int | None, db_path: Path
) -> dict[str, Any]:
    return _run(
        db_path,
        lambda db: backfill_companies(db, plan=plan, max_requests=max_requests),
    )
