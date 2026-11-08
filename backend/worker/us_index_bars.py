"""US stock index daily closes from FRED (Issue #547).

Source: FRED (Federal Reserve Bank of St. Louis) ``fredgraph.csv``, one GET per
series with ``cosd``/``coed`` (no key), decided in #547 (comment 6717082903):
S&P 500 (``SP500``), NASDAQ Composite (``NASDAQCOM``), Dow Jones Industrial
Average (``DJIA``) and PHLX Semiconductor (``NASDAQSOX``).  FRED's terms allow
personal, non-commercial use with the copyright notices kept; the series stay
display-only (never strategy, candidate, group or tracking input).

Each series is one ``index`` instrument (``US``/``SPX``, ``IXIC``, ``DJI``,
``SOX``) with one ``market_bars`` row per observation.  FRED publishes the
close only: open/high/low are NULL with ``price_reason=source_missing_ohlc``,
volume is NULL and turnover ``unavailable``/``not_published`` (the #552 null
rules).  A blank observation (``2024-11-28,``) is a US market holiday: no row,
never a zero; the blank dates of the request are kept in the series'
``data_quality`` row so the market page can say 美股休市.

A collect of Taipei session D asks for ``cosd`` = 10 days before the newest
stored row (``HISTORY_START``, 2023-09-01, when there is none) to ``coed`` =
D − 1: every US session is before D.  A series whose oldest row is later than
``HISTORY_START`` (it was first collected from 2024-09-30) is extended by
``backfill_us_index_history``: one request per series, ``HISTORY_START`` to
the day before its oldest row (Issue #563).  A response that is not that series' CSV, has a
malformed line or a date outside the request is rejected whole (a
``us index bars`` non-core warning; the raw is kept).  A stored row keeps its
close (a different close is a conflict) unless ``force``.

collect fetches in its fetch phase, before it writes anything
(``us_index_requests`` reads, ``fetch_us_index_series`` has no database
access), and writes later in one savepoint per series inside one for the step
(``write_us_index_series``), so a slow FRED never holds the write lock and a
database error stays non-core (PR #558 review).
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable

from sqlalchemy import func, null, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.domain import (
    US_INDEX_EXCHANGE,
    US_INDEX_QUALITY_ENTITY,
    US_INDEXES,
    UsIndex,
)
from app.models import DataQuality, Instrument, MarketBar

from .sources import OfficialDataError, capture_payload

SOURCE = "fred_close"
RAW_SOURCE = "fred"
EXCHANGE = US_INDEX_EXCHANGE
MARKET = "US"
ENDPOINT = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SOURCE_MISSING_OHLC = "source_missing_ohlc"
NO_TURNOVER = "not_published"
WARNING_PREFIX = "us index bars"
QUALITY_ENTITY = US_INDEX_QUALITY_ENTITY
# About a year before the stock history (2024-09-30), so the 240-session
# average exists on the stocks' first day (#1 6723720803, Issue #563).
HISTORY_START = date(2023, 9, 1)
BACKFILL_RUN_TYPE = "us_index_backfill"
# Re-read this many days before the newest stored row, so a blank FRED filled
# in later (or a late close) is still picked up.
LOOKBACK_DAYS = 10
RETRY_DELAY_SECONDS = 5.0
_VALUE = re.compile(r"\d+(?:\.\d+)?")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


SERIES = US_INDEXES
SERIES_BY_SYMBOL = {item.symbol: item for item in SERIES}


@dataclass(frozen=True)
class UsIndexBar:
    trading_date: date
    close: float


@dataclass(frozen=True)
class ParsedSeries:
    bars: list[UsIndexBar]
    # Blank observations of the request: US market holidays.
    closed_dates: list[date]

    @property
    def latest(self) -> date | None:
        return max((bar.trading_date for bar in self.bars), default=None)


def request_url(series: UsIndex, start: date, end: date) -> str:
    return (
        f"{ENDPOINT}?id={series.series_id}"
        f"&cosd={start.isoformat()}&coed={end.isoformat()}"
    )


def request_window(latest_stored: date | None, session: date) -> tuple[date, date]:
    """``cosd``/``coed`` for the collect of Taipei session ``session``."""

    end = session - timedelta(days=1)
    if latest_stored is None:
        return HISTORY_START, end
    start = max(HISTORY_START, latest_stored - timedelta(days=LOOKBACK_DAYS))
    return min(start, end), end


def _close(text: str) -> float | None:
    if not _VALUE.fullmatch(text):
        return None
    try:
        number = float(Decimal(text))
    except InvalidOperation:
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_csv(text: Any, series: UsIndex, *, start: date, end: date) -> ParsedSeries:
    """The observations of one ``fredgraph.csv`` answer, or OfficialDataError.

    The header must be ``observation_date,<series id>``; every line one date
    and one value; every date inside ``start``..``end`` and seen once.  A blank
    or ``.`` value is a closed day.  An answer without any line is rejected:
    a ten-day window always has observations.
    """

    if not isinstance(text, str):
        raise OfficialDataError(f"FRED {series.series_id} answer is not text")
    lines = [line.strip() for line in text.lstrip("﻿").splitlines()]
    lines = [line for line in lines if line]
    expected = f"observation_date,{series.series_id}"
    if not lines or lines[0] != expected:
        head = lines[0][:60] if lines else ""
        raise OfficialDataError(
            f"FRED {series.series_id} answer is not its CSV (first line {head!r})"
        )
    bars: list[UsIndexBar] = []
    closed: list[date] = []
    seen: set[date] = set()
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) != 2 or not _DATE.fullmatch(parts[0]):
            raise OfficialDataError(
                f"FRED {series.series_id} has a malformed line {line[:60]!r}"
            )
        try:
            day = date.fromisoformat(parts[0])
        except ValueError as exc:
            raise OfficialDataError(
                f"FRED {series.series_id} has an invalid date {parts[0]!r}"
            ) from exc
        if not start <= day <= end:
            raise OfficialDataError(
                f"FRED {series.series_id} reports {day.isoformat()} outside "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        if day in seen:
            raise OfficialDataError(
                f"FRED {series.series_id} reports {day.isoformat()} twice"
            )
        seen.add(day)
        value = parts[1].strip()
        if value in {"", "."}:
            closed.append(day)
            continue
        close = _close(value)
        if close is None:
            raise OfficialDataError(
                f"FRED {series.series_id} has an unreadable close {value!r} on "
                f"{day.isoformat()}"
            )
        bars.append(UsIndexBar(day, close))
    if not seen:
        raise OfficialDataError(
            f"FRED {series.series_id} has no observation in "
            f"{start.isoformat()}..{end.isoformat()}"
        )
    return ParsedSeries(sorted(bars, key=lambda bar: bar.trading_date), sorted(closed))


def fetch_csv(url: str, *, timeout_seconds: float = 30.0) -> str:
    """GET one FRED CSV over HTTP/1.1 (FRED cut HTTP/2 streams in #547's probe).

    One retry after ``RETRY_DELAY_SECONDS`` on a transport error, 429 or 5xx;
    nothing more (#547 decision: no retry storms).
    """

    import httpx

    from .sources import _throttle_official_host

    headers = {"User-Agent": "taiwan-stock-research/0.1"}
    for attempt in range(2):
        _throttle_official_host(url)
        try:
            response = httpx.get(url, timeout=timeout_seconds, headers=headers)
        except httpx.TransportError as exc:
            if attempt:
                raise OfficialDataError(f"FRED transport failed: {url}") from exc
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        if response.status_code == 429 or response.status_code >= 500:
            if attempt:
                raise OfficialDataError(f"FRED answered {response.status_code}: {url}")
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        if response.status_code != 200:
            raise OfficialDataError(f"FRED answered {response.status_code}: {url}")
        return response.text
    raise OfficialDataError(f"FRED request failed: {url}")  # pragma: no cover


def us_index_warning(series: UsIndex, exc: Exception) -> str:
    """The non-core warning text (pipeline.NONCORE_WARNING_PATTERN)."""

    return (
        f"{WARNING_PREFIX} unavailable for {EXCHANGE} {series.symbol} "
        f"({series.series_id}): {type(exc).__name__}: {exc}"
    )


def find_instrument(db: Session, series: UsIndex) -> Instrument | None:
    return db.scalar(
        select(Instrument).where(
            Instrument.exchange == EXCHANGE, Instrument.symbol == series.symbol
        )
    )


def us_index_instrument(db: Session, series: UsIndex) -> Instrument:
    item = find_instrument(db, series)
    if item is None:
        item = Instrument(
            market=MARKET,
            exchange=EXCHANGE,
            symbol=series.symbol,
            name=series.name,
            instrument_type="index",
            industry="Index",
            is_watchlisted=False,
            status="active",
        )
        db.add(item)
        db.flush()
    return item


def latest_stored(db: Session, series: UsIndex) -> date | None:
    item = find_instrument(db, series)
    if item is None:
        return None
    return db.scalar(
        select(func.max(MarketBar.trading_date)).where(
            MarketBar.instrument_id == item.id
        )
    )


@dataclass
class SeriesWriteResult:
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "inserted": 0,
            "replaced": 0,
            "unchanged": 0,
            "conflict": 0,
        }
    )
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def _same_close(first: float | None, second: float | None) -> bool:
    # FRED publishes two or three decimals.
    return (
        first is not None
        and second is not None
        and round(float(first), 4) == round(float(second), 4)
    )


def store_us_index_bars(
    db: Session,
    series: UsIndex,
    bars: Iterable[UsIndexBar],
    raw_payload_id: int,
    *,
    force: bool = False,
) -> SeriesWriteResult:
    """Insert new observations; a stored one keeps its close unless ``force``."""

    result = SeriesWriteResult()
    bars = list(bars)
    if not bars:
        return result
    instrument = us_index_instrument(db, series)
    stored = {
        row.trading_date: row
        for row in db.scalars(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date.in_([bar.trading_date for bar in bars]),
            )
        )
    }
    for bar in bars:
        row = stored.get(bar.trading_date)
        if row is not None and not force:
            if _same_close(row.close, bar.close) and row.source == SOURCE:
                result.counts["unchanged"] += 1
            else:
                result.counts["conflict"] += 1
                result.conflicts.append(
                    {
                        "symbol": series.symbol,
                        "trading_date": bar.trading_date.isoformat(),
                        "stored": {"close": row.close, "source": row.source},
                        "incoming": {"close": bar.close, "source": SOURCE},
                        "raw_payload_id": raw_payload_id,
                    }
                )
            continue
        outcome = "replaced" if row is not None else "inserted"
        if row is None:
            row = MarketBar(instrument_id=instrument.id, trading_date=bar.trading_date)
            db.add(row)
        row.open = row.high = row.low = None
        row.close = bar.close
        row.adj_close = bar.close
        # MarketBar.volume defaults to 0 on insert; FRED has no volume.
        row.volume = null()
        row.turnover, row.turnover_status, row.turnover_reason = (
            0.0,
            "unavailable",
            NO_TURNOVER,
        )
        row.price_reason = SOURCE_MISSING_OHLC
        row.is_suspended = False
        row.source = SOURCE
        row.data_as_of = datetime.combine(bar.trading_date, datetime.min.time())
        row.collected_at = utcnow()
        row.raw_payload_id = raw_payload_id
        row.volume_raw_payload_id = None
        row.contract_month = row.open_interest = row.settlement_price = None
        result.counts[outcome] += 1
    db.flush()
    return result


def _upsert_quality(
    db: Session, series: UsIndex, session: date, status: str, checks: dict[str, Any]
) -> None:
    key = f"{EXCHANGE}:{series.symbol}"
    row = db.scalar(
        select(DataQuality).where(
            DataQuality.entity_type == QUALITY_ENTITY,
            DataQuality.entity_key == key,
            DataQuality.as_of_date == session,
        )
    )
    if row is None:
        row = DataQuality(
            entity_type=QUALITY_ENTITY, entity_key=key, as_of_date=session
        )
        db.add(row)
    row.status = status
    row.missing_fields_json = (
        ["open", "high", "low", "volume"] if status == "complete" else ["close"]
    )
    row.checks_json = checks
    row.source = SOURCE
    row.checked_at = utcnow()


@dataclass(frozen=True)
class SeriesRequest:
    series: UsIndex
    start: date
    end: date

    @property
    def url(self) -> str:
        return request_url(self.series, self.start, self.end)


@dataclass
class FetchedSeries:
    """One series' answer, fetched and parsed before collect writes anything."""

    request: SeriesRequest
    # The raw capture (file written, no DB row yet); None when the GET failed.
    captured: Any = None
    parsed: ParsedSeries | None = None
    error: Exception | None = None


def us_index_requests(db: Session, session: date) -> list[SeriesRequest]:
    """The four requests of the collect of Taipei session ``session`` (reads only)."""

    return [
        SeriesRequest(series, *request_window(latest_stored(db, series), session))
        for series in SERIES
    ]


def fetch_us_index_series(
    requests: Iterable[SeriesRequest], fetch: Callable[[str], Any]
) -> list[FetchedSeries]:
    """GET and parse every series; no database access (#558 review item 3).

    collect calls this in its fetch phase, before it writes any row, so a slow
    FRED never holds the SQLite write lock.  A failed GET or a rejected answer
    is kept with its error; an answer is captured as a raw file either way.
    """

    fetched: list[FetchedSeries] = []
    for request in requests:
        item = FetchedSeries(request)
        try:
            text = fetch(request.url)
        except Exception as exc:
            item.error = exc
            fetched.append(item)
            continue
        try:
            item.parsed = parse_csv(
                text, request.series, start=request.start, end=request.end
            )
        except Exception as exc:
            item.error = exc
        item.captured = capture_payload(
            RAW_SOURCE,
            request.url,
            {
                "series_id": request.series.series_id,
                "csv": text if isinstance(text, str) else None,
            },
            item.parsed.latest.isoformat()
            if item.parsed and item.parsed.latest
            else None,
        )
        fetched.append(item)
    return fetched


def _write_series(
    db: Session,
    run: Any,
    session: date,
    item: FetchedSeries,
    upsert_raw: Callable[[Session, Any, Any], Any],
    warnings: list[str],
    *,
    force: bool,
) -> dict[str, Any]:
    series, request = item.request.series, item.request
    checks: dict[str, Any] = {
        "series_id": series.series_id,
        "endpoint": request.url,
        "requested": [request.start.isoformat(), request.end.isoformat()],
    }
    if item.captured is not None:
        checks["raw_payload_id"] = upsert_raw(db, run, item.captured).id
    if item.parsed is None:
        error = item.error or OfficialDataError("no answer")
        warnings.append(us_index_warning(series, error))
        checks["error"] = f"{type(error).__name__}: {error}"
        _upsert_quality(db, series, session, "failed", checks)
        return {**checks, "status": "failed"}
    parsed = item.parsed
    checks["latest_observation"] = parsed.latest.isoformat() if parsed.latest else None
    checks["closed_dates"] = [day.isoformat() for day in parsed.closed_dates]
    try:
        with db.begin_nested():
            written = store_us_index_bars(
                db, series, parsed.bars, checks["raw_payload_id"], force=force
            )
    except Exception as exc:
        warnings.append(us_index_warning(series, exc))
        checks["error"] = f"{type(exc).__name__}: {exc}"
        _upsert_quality(db, series, session, "failed", checks)
        return {**checks, "status": "failed"}
    if written.conflicts:
        warnings.append(
            f"{WARNING_PREFIX} kept {len(written.conflicts)} stored {EXCHANGE} "
            f"{series.symbol} close(s) that differ from FRED {series.series_id}"
        )
    checks["counts"] = dict(written.counts)
    _upsert_quality(db, series, session, "complete", checks)
    return {**checks, "status": "complete", "conflicts": written.conflicts}


def write_us_index_series(
    db: Session,
    run: Any,
    session: date,
    fetched: Iterable[FetchedSeries],
    upsert_raw: Callable[[Session, Any, Any], Any],
    warnings: list[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Write the fetched series: raw rows, bars and data_quality; non-core.

    Each series is one savepoint (#558 review item 2): a database error in
    its raw, bars or quality row rolls back that series only and becomes a
    warning, and the session stays usable for the rest of collect.  A rejected
    or failed series writes no bar and records the reason in its quality row.
    """

    result: dict[str, Any] = {}
    for item in fetched:
        series = item.request.series
        series_warnings: list[str] = []
        try:
            with db.begin_nested():
                result[series.symbol] = _write_series(
                    db, run, session, item, upsert_raw, series_warnings, force=force
                )
        except Exception as exc:
            series_warnings = [us_index_warning(series, exc)]
            result[series.symbol] = {
                "series_id": series.series_id,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        warnings.extend(series_warnings)
    return result


def collect_us_index_bars(
    db: Session,
    run: Any,
    session: date,
    fetch: Callable[[str], Any],
    upsert_raw: Callable[[Session, Any, Any], Any],
    warnings: list[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Requests, fetch and write in one call (tests and one-off runs).

    collect itself fetches in its fetch phase and writes later
    (``pipeline.prefetch_us_index_series``, ``store_collect_us_index_bars``).
    """

    fetched = fetch_us_index_series(us_index_requests(db, session), fetch)
    return write_us_index_series(
        db, run, session, fetched, upsert_raw, warnings, force=force
    )


# --- history (Issue #563) -----------------------------------------------------


def earliest_stored(db: Session, series: UsIndex) -> date | None:
    item = find_instrument(db, series)
    if item is None:
        return None
    return db.scalar(
        select(func.min(MarketBar.trading_date)).where(
            MarketBar.instrument_id == item.id
        )
    )


def history_window(earliest: date | None, session: date) -> tuple[date, date] | None:
    """``cosd``/``coed`` that extend a series back to ``HISTORY_START``, or None.

    None when the series has no row yet (the next collect reads from
    ``HISTORY_START``) or already starts within ``LOOKBACK_DAYS`` of it (US
    holidays right after the start never make it ask again).  Otherwise
    ``HISTORY_START`` to the day before the oldest row: one request.
    """

    if earliest is None or earliest <= HISTORY_START + timedelta(days=LOOKBACK_DAYS):
        return None
    end = min(earliest - timedelta(days=1), session - timedelta(days=1))
    return (HISTORY_START, end) if HISTORY_START <= end else None


def backfill_us_index_history(
    db: Session,
    *,
    session: date,
    fetch: Callable[[str], Any] = fetch_csv,
    force: bool = False,
) -> dict[str, Any]:
    """Extend every series back to ``HISTORY_START`` (one FRED GET per series).

    One ``us_index_backfill`` run.  Each series is fetched (``history_window``)
    and written in its own savepoint like collect: a failed or rejected answer
    writes no bar and is a warning (the raw is kept); a stored day keeps its
    close unless ``force``.  The rows are the collect's (``store_us_index_bars``)
    and point at this run's CSV.  The ``data_quality`` rows stay the collect's:
    a history request says nothing about the latest session.  The indicator and
    feature rows of the extended series are rebuilt at the end.
    """

    from app.models import IngestionRun

    from .index_bars import rebuild_derived
    from .pipeline import _upsert_raw_payload

    run = IngestionRun(
        run_type=BACKFILL_RUN_TYPE,
        source="official",
        run_date=session,
        status="running",
        started_at=utcnow(),
        metadata_json={
            "history_start": HISTORY_START.isoformat(),
            "force": force,
            "trigger": "manual",
        },
    )
    db.add(run)
    db.commit()
    requests = []
    skipped: dict[str, str] = {}
    for series in SERIES:
        earliest = earliest_stored(db, series)
        window = history_window(earliest, session)
        if window is None:
            skipped[series.symbol] = (
                "no_rows_yet" if earliest is None else "already_from_history_start"
            )
            continue
        requests.append(SeriesRequest(series, *window))
    db.commit()  # only reads: end the transaction before the HTTP calls
    fetched = fetch_us_index_series(requests, fetch)
    results: dict[str, Any] = {}
    warnings: list[str] = []
    changed: list[int] = []
    try:
        for item in fetched:
            series, request = item.request.series, item.request
            entry: dict[str, Any] = {
                "series_id": series.series_id,
                "endpoint": request.url,
                "requested": [request.start.isoformat(), request.end.isoformat()],
            }
            if item.captured is not None:
                # Kept as evidence whether or not the answer is used.
                entry["raw_payload_id"] = _upsert_raw_payload(db, run, item.captured).id
            try:
                if item.parsed is None:
                    raise item.error or OfficialDataError("no answer")
                with db.begin_nested():
                    written = store_us_index_bars(
                        db,
                        series,
                        item.parsed.bars,
                        entry["raw_payload_id"],
                        force=force,
                    )
            except Exception as exc:
                warnings.append(us_index_warning(series, exc))
                entry.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                results[series.symbol] = entry
                continue
            if written.conflicts:
                warnings.append(
                    f"{WARNING_PREFIX} kept {len(written.conflicts)} stored "
                    f"{EXCHANGE} {series.symbol} close(s) that differ from FRED "
                    f"{series.series_id}"
                )
            if written.counts["inserted"] or written.counts["replaced"]:
                changed.append(find_instrument(db, series).id)
            entry.update(
                status="complete",
                counts=dict(written.counts),
                conflicts=written.conflicts,
                first_observation=(
                    item.parsed.bars[0].trading_date.isoformat()
                    if item.parsed.bars
                    else None
                ),
                latest_observation=(
                    item.parsed.latest.isoformat() if item.parsed.latest else None
                ),
                closed_dates=len(item.parsed.closed_dates),
            )
            results[series.symbol] = entry
        indicators = rebuild_derived(db, changed)
        failed = [
            symbol for symbol, entry in results.items() if entry["status"] != "complete"
        ]
        run.status = "partial" if failed else "success"
        run.records = sum(
            entry.get("counts", {}).get("inserted", 0)
            + entry.get("counts", {}).get("replaced", 0)
            for entry in results.values()
        )
        run.finished_at = utcnow()
        run.metadata_json = {
            **run.metadata_json,
            "series": results,
            "skipped": skipped,
            "requests": len(requests),
            "warnings": warnings,
            "indicators": indicators,
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        failed_run = db.get(IngestionRun, run.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.error = f"{type(exc).__name__}: {exc}"
            failed_run.finished_at = utcnow()
            db.commit()
        raise
    return {
        "status": run.status,
        "run_id": run.id,
        "requests": len(requests),
        "series": {
            symbol: {
                key: entry.get(key)
                for key in ("status", "requested", "counts", "error")
                if key in entry
            }
            for symbol, entry in results.items()
        },
        "skipped": skipped,
        "indicators": indicators,
        "warnings": warnings,
    }


def run_us_index_history(*, force: bool = False) -> dict[str, Any]:
    from app.db import SessionLocal

    from .index_bars import taipei_today

    with SessionLocal() as db:
        return backfill_us_index_history(db, session=taipei_today(), force=force)
