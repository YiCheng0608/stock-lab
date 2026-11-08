"""TX near-month history from the TAIFEX website download ``futDataDown`` (Issue #563).

The daily TX bar comes from the open-data ``DailyMarketReportFut`` (#552,
``worker.futures_bars``), which has the latest session only.  The sessions
before it were collected come from the website's 期貨每日交易行情下載:
``POST https://www.taifex.com.tw/cht/3/futDataDown`` with ``down_type=1``,
``commodity_id=TX`` and ``queryStartDate``/``queryEndDate`` (``YYYY/MM/DD``),
one calendar month per request (a longer range answers an HTML error page).
The answer is a cp950 CSV of 19 columns (#552 source registration
6715531445); the TAIFEX terms ask for prior written consent for website
content, which the user accepted for local personal research only (#1
6723720803): nothing of it may be published or shared.

The near-month rule, fields and null rules are ``worker.futures_bars``':
``契約=TX``, ``交易時段=一般``, ``到期月份(週別)`` equal to the session's near
month; spreads (``202410/202411``) and the after-hours rows are never taken.
The rows are written with their own ``source`` (``taifex_futdatadown``) and
raw source (``taifex_web``), and only for days before the first OpenAPI row,
so the two never overlap: the open-data report stays the daily source.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import Instrument, MarketBar

from .futures_bars import (
    CONTRACT,
    EXCHANGE,
    REGULAR_SESSION,
    SOURCE as OPENAPI_SOURCE,
    SOURCE_MISSING_OHLC,
    SYMBOL,
    FuturesBar,
    _count,
    _price,
    near_month,
    store_futures_bars,
)
from .index_bars import MAX_MONTHS, Month, month_range, rebuild_derived, taipei_today
from .sources import FetchedPayload, OfficialDataError, capture_payload

ENDPOINT = "https://www.taifex.com.tw/cht/3/futDataDown"
SOURCE = "taifex_futdatadown"
RAW_SOURCE = "taifex_web"
RUN_TYPE = "futures_bar_backfill"
# The index history start (worker.index_bars.HISTORY_START, Issue #563).
HISTORY_START = date(2023, 9, 1)
DEFAULT_FIRST_MONTH = "2023-09"
ENCODING = "cp950"
WARNING_PREFIX = "futures history"
FIELDS = (
    "交易日期",
    "契約",
    "到期月份(週別)",
    "開盤價",
    "最高價",
    "最低價",
    "收盤價",
    "漲跌價",
    "漲跌%",
    "成交量",
    "結算價",
    "未沖銷契約數",
    "最後最佳買價",
    "最後最佳賣價",
    "歷史最高價",
    "歷史最低價",
    "是否因訊息面暫停交易",
    "交易時段",
    "價差對單式委託成交量",
)


@dataclass(frozen=True)
class Request:
    month: Month
    start: date
    end: date

    @property
    def form(self) -> dict[str, str]:
        return {
            "down_type": "1",
            "commodity_id": CONTRACT,
            "queryStartDate": f"{self.start:%Y/%m/%d}",
            "queryEndDate": f"{self.end:%Y/%m/%d}",
        }

    @property
    def endpoint(self) -> str:
        """The raw endpoint: the URL with the form, so each month's capture is named."""

        query = "&".join(f"{key}={value}" for key, value in self.form.items())
        return f"{ENDPOINT}?{query}"


def request_for(month: Month, today: date) -> Request:
    """One calendar month, not past ``today`` (a range over a month is refused)."""

    return Request(month, month.first_day, min(month.last_day, today))


@dataclass(frozen=True)
class ParsedMonth:
    bars: list[FuturesBar]
    # Sessions listed in the CSV without a usable near-month regular row.
    unusable_dates: list[str]


def decode(content: Any) -> str:
    """The cp950 CSV as text; OfficialDataError for an undecodable answer."""

    if isinstance(content, str):
        return content
    if not isinstance(content, (bytes, bytearray)):
        raise OfficialDataError("TAIFEX futDataDown answer is not bytes")
    try:
        return bytes(content).decode(ENCODING)
    except UnicodeDecodeError as exc:
        raise OfficialDataError(
            f"TAIFEX futDataDown answer is not {ENCODING}: {exc}"
        ) from exc


def _row_bar(row: dict[str, str], day: date, contract: str) -> FuturesBar | None:
    close = _price(row["收盤價"])
    volume = _count(row["成交量"])
    if close is None or volume is None:
        return None
    open_, high, low = (_price(row[key]) for key in ("開盤價", "最高價", "最低價"))
    reason = None
    if (
        open_ is None
        or high is None
        or low is None
        or not low <= min(open_, close)
        or not max(open_, close) <= high
    ):
        open_ = high = low = None
        reason = SOURCE_MISSING_OHLC
    return FuturesBar(
        trading_date=day,
        contract_month=contract,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        settlement_price=_price(row["結算價"]),
        open_interest=_count(row["未沖銷契約數"]),
        price_reason=reason,
    )


def parse_month(text: Any, request: Request) -> ParsedMonth:
    """The near-month regular-session bar of every session in one month's CSV.

    The header must be the 19 ``FIELDS``; every row a TX row dated inside the
    request.  An HTML page (the error answer), another header, a short row,
    an unreadable date or a date outside the request rejects the whole month
    (OfficialDataError).  A session with no single readable near-month
    regular row is listed in ``unusable_dates`` and gets no bar.
    """

    if not isinstance(text, str):
        raise OfficialDataError("TAIFEX futDataDown answer is not text")
    body = text.lstrip("﻿")
    if body.lstrip().startswith("<"):
        raise OfficialDataError("TAIFEX futDataDown answered an HTML page, not CSV")
    lines = [line for line in body.splitlines() if line.strip()]
    if not lines:
        raise OfficialDataError("TAIFEX futDataDown answered nothing")
    reader = csv.reader(io.StringIO("\n".join(lines)))
    header = [cell.strip() for cell in next(reader)]
    if tuple(header[: len(FIELDS)]) != FIELDS or any(header[len(FIELDS) :]):
        raise OfficialDataError(
            f"TAIFEX futDataDown header is not the 19 fields: {header[:5]}"
        )
    candidates: dict[date, list[dict[str, str]]] = {}
    for cells in reader:
        if len(cells) < len(FIELDS):
            raise OfficialDataError(
                f"TAIFEX futDataDown row has {len(cells)} columns: {cells[:3]}"
            )
        row = {name: cells[i].strip() for i, name in enumerate(FIELDS)}
        try:
            day = datetime.strptime(row["交易日期"], "%Y/%m/%d").date()
        except ValueError as exc:
            raise OfficialDataError(
                f"TAIFEX futDataDown has an unreadable date {row['交易日期']!r}"
            ) from exc
        if not request.start <= day <= request.end:
            raise OfficialDataError(
                f"TAIFEX futDataDown reports {day.isoformat()} outside "
                f"{request.start.isoformat()}..{request.end.isoformat()}"
            )
        if row["契約"] != CONTRACT:
            raise OfficialDataError(
                f"TAIFEX futDataDown has contract {row['契約']!r}, not {CONTRACT}"
            )
        rows = candidates.setdefault(day, [])
        if row["交易時段"] == REGULAR_SESSION and row["到期月份(週別)"] == near_month(
            day
        ):
            rows.append(row)
    bars: list[FuturesBar] = []
    unusable: list[str] = []
    for day in sorted(candidates):
        rows = candidates[day]
        bar = _row_bar(rows[0], day, near_month(day)) if len(rows) == 1 else None
        if bar is None:
            unusable.append(day.isoformat())
        else:
            bars.append(bar)
    return ParsedMonth(bars, unusable)


def fetch_month(request: Request, *, timeout_seconds: float = 30.0) -> bytes:
    """POST one month; one retry after 5 seconds on a transport error, 429 or 5xx."""

    import httpx

    headers = {"User-Agent": "taiwan-stock-research/0.1"}
    for attempt in range(2):
        try:
            response = httpx.post(
                ENDPOINT, data=request.form, timeout=timeout_seconds, headers=headers
            )
        except httpx.TransportError as exc:
            if attempt:
                raise OfficialDataError(
                    f"TAIFEX futDataDown transport failed: {request.endpoint}"
                ) from exc
            time.sleep(5.0)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt:
                raise OfficialDataError(
                    f"TAIFEX futDataDown answered {response.status_code}"
                )
            time.sleep(5.0)
            continue
        if response.status_code != 200:
            raise OfficialDataError(
                f"TAIFEX futDataDown answered {response.status_code}"
            )
        return response.content
    raise OfficialDataError("TAIFEX futDataDown request failed")  # pragma: no cover


def first_openapi_day(db: Session) -> date | None:
    """The oldest TX row of the open-data report: the history stops before it."""

    return db.scalar(
        select(func.min(MarketBar.trading_date))
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            Instrument.exchange == EXCHANGE,
            Instrument.symbol == SYMBOL,
            MarketBar.source == OPENAPI_SOURCE,
        )
    )


@dataclass
class MonthFetch:
    request: Request
    captured: FetchedPayload | None = None
    parsed: ParsedMonth | None = None
    error: Exception | None = None
    raw_ids: list[int] = field(default_factory=list)


def history_warning(month: Month, exc: Exception) -> str:
    return (
        f"{WARNING_PREFIX} unavailable for TAIFEX TX {month.label}: "
        f"{type(exc).__name__}: {exc}"
    )


def backfill_futures_history(
    db: Session,
    *,
    first: Month,
    last: Month,
    get: Callable[[Request], Any] = fetch_month,
    sleep: Callable[[float], None] | None = None,
    interval_seconds: float = 3.0,
    force: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Fetch ``first``..``last`` from ``futDataDown`` and write the TX history.

    One ``futures_bar_backfill`` run, as ``worker.index_bars`` does it: every
    month is fetched first (oldest first, ``interval_seconds`` apart), then
    the raws, bars, rebuilt indicators and features and the run's status are
    committed together, so a run stopped midway changes no row.  Only days
    from ``HISTORY_START`` up to the day before the first OpenAPI row (or
    ``today`` without one) are written.  A month after the current Taipei
    month or more than ``MAX_MONTHS`` months are refused before any request.
    """

    from app.models import IngestionRun

    from .pipeline import _upsert_raw_payload

    sleep = sleep or time.sleep
    today = today or taipei_today()
    months = month_range(first, last)
    if not months:
        raise ValueError(f"{first.label} is after {last.label}")
    if (last.year, last.month) > (today.year, today.month):
        raise ValueError(f"{last.label} is after the current month {today:%Y-%m}")
    if len(months) > MAX_MONTHS:
        raise ValueError(f"at most {MAX_MONTHS} months per run")
    cutoff = first_openapi_day(db)
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=today,
        status="running",
        started_at=utcnow(),
        data_as_of=min(last.last_day, today).isoformat(),
        metadata_json={
            "first_month": first.label,
            "last_month": last.label,
            "force": force,
            "trigger": "manual",
            "openapi_first_day": cutoff.isoformat() if cutoff else None,
        },
    )
    db.add(run)
    db.commit()
    fetched: list[MonthFetch] = []
    requests_made = 0
    manifest: dict[str, dict[str, Any]] = {}
    try:
        for month in months:
            item = MonthFetch(request_for(month, today))
            if requests_made:
                sleep(interval_seconds)
            requests_made += 1
            try:
                content = get(item.request)
            except Exception as exc:
                item.error = exc
                fetched.append(item)
                continue
            text: str | None = None
            try:
                text = decode(content)
                item.parsed = parse_month(text, item.request)
            except OfficialDataError as exc:
                item.error = exc
            latest = (
                max(bar.trading_date for bar in item.parsed.bars)
                if item.parsed and item.parsed.bars
                else month.last_day
            )
            item.captured = capture_payload(
                RAW_SOURCE,
                item.request.endpoint,
                {"form": item.request.form, "encoding": ENCODING, "csv": text},
                latest.isoformat(),
            )
            fetched.append(item)
        db.commit()  # the cutoff read above: the writes start a new transaction
        total_counts = {"inserted": 0, "replaced": 0, "unchanged": 0, "conflict": 0}
        conflicts: list[dict[str, Any]] = []
        warnings: list[str] = []
        changed: set[int] = set()
        for item in fetched:
            month = item.request.month
            entry: dict[str, Any] = {"endpoint": item.request.endpoint}
            if item.captured is not None:
                entry["raw_payload_id"] = _upsert_raw_payload(db, run, item.captured).id
            if item.parsed is None:
                error = item.error or OfficialDataError("no answer")
                warnings.append(history_warning(month, error))
                entry.update(status="failed", error=f"{type(error).__name__}: {error}")
                manifest[month.label] = entry
                continue
            bars = [
                bar
                for bar in item.parsed.bars
                if HISTORY_START <= bar.trading_date <= today
                and (cutoff is None or bar.trading_date < cutoff)
            ]
            raw_id = entry["raw_payload_id"]
            written = store_futures_bars(
                db, bars, lambda _sha: raw_id, force=force, source=SOURCE
            )
            for name, value in written.counts.items():
                total_counts[name] += value
            conflicts.extend(written.conflicts)
            changed.update(instrument_id for instrument_id, _ in written.written)
            entry.update(
                status="complete",
                sessions=len(item.parsed.bars),
                written_range=(
                    [
                        bars[0].trading_date.isoformat(),
                        bars[-1].trading_date.isoformat(),
                    ]
                    if bars
                    else None
                ),
                from_openapi_day=sum(
                    cutoff is not None and bar.trading_date >= cutoff
                    for bar in item.parsed.bars
                ),
                unusable_dates=item.parsed.unusable_dates,
                counts={k: v for k, v in written.counts.items() if v},
            )
            if item.parsed.unusable_dates:
                warnings.append(
                    f"{WARNING_PREFIX} has no usable TX near-month row on "
                    + ", ".join(item.parsed.unusable_dates)
                )
            manifest[month.label] = entry
        if conflicts:
            warnings.append(
                f"{WARNING_PREFIX} kept {len(conflicts)} stored TX session(s) that differ from the report"
            )
        indicators = rebuild_derived(db, changed)
        failed = [
            label for label, entry in manifest.items() if entry["status"] != "complete"
        ]
        run.status = "partial" if failed else "success"
        run.records = total_counts["inserted"] + total_counts["replaced"]
        run.finished_at = utcnow()
        run.metadata_json = {
            **run.metadata_json,
            "coverage_manifest": manifest,
            "counts": total_counts,
            "conflicts": conflicts,
            "warnings": warnings,
            "requests": requests_made,
            "indicators": indicators,
        }
        db.commit()
    except BaseException as exc:
        db.rollback()
        failed_run = db.get(IngestionRun, run.id)
        if failed_run is not None and isinstance(exc, Exception):
            failed_run.status = "failed"
            failed_run.error = f"{type(exc).__name__}: {exc}"
            failed_run.finished_at = utcnow()
            failed_run.metadata_json = {
                **(failed_run.metadata_json or {}),
                "requests": requests_made,
            }
            db.commit()
        raise
    return {
        "status": run.status,
        "run_id": run.id,
        "months": [month.label for month in months],
        "requests": requests_made,
        "openapi_first_day": cutoff.isoformat() if cutoff else None,
        "counts": total_counts,
        "conflicts": len(conflicts),
        "indicators": indicators,
        "warnings": warnings,
    }


def run_futures_history(
    first: str | None, last: str | None, *, force: bool = False
) -> dict[str, Any]:
    from app.db import SessionLocal

    today = taipei_today()
    try:
        first_month = Month.parse(first or DEFAULT_FIRST_MONTH)
        last_month = Month.parse(last) if last else Month.of(today)
    except ValueError as exc:
        return {"status": "failed", "error": str(exc)}
    with SessionLocal() as db:
        try:
            return backfill_futures_history(
                db, first=first_month, last=last_month, force=force, today=today
            )
        except ValueError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc)}
