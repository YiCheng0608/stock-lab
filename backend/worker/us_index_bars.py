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
stored row (2024-09-30 when there is none) to ``coed`` = D − 1: every US
session is before D.  A response that is not that series' CSV, has a
malformed line or a date outside the request is rejected whole (a
``us index bars`` non-core warning; the raw is kept).  A stored row keeps its
close (a different close is a conflict) unless ``force``.
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
HISTORY_START = date(2024, 9, 30)
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
    """collect's US index step for Taipei session ``session``; non-core.

    One request per series.  The raw is stored even when the answer is
    rejected; a rejected or failed series writes no bar, records the reason in
    its ``data_quality`` row and adds one warning.  Other series go on.
    """

    result: dict[str, Any] = {}
    for series in SERIES:
        start, end = request_window(latest_stored(db, series), session)
        url = request_url(series, start, end)
        checks: dict[str, Any] = {
            "series_id": series.series_id,
            "endpoint": url,
            "requested": [start.isoformat(), end.isoformat()],
        }
        try:
            text = fetch(url)
        except Exception as exc:
            warnings.append(us_index_warning(series, exc))
            checks["error"] = f"{type(exc).__name__}: {exc}"
            _upsert_quality(db, series, session, "failed", checks)
            result[series.symbol] = {**checks, "status": "failed"}
            continue
        parsed: ParsedSeries | None = None
        error: Exception | None = None
        try:
            parsed = parse_csv(text, series, start=start, end=end)
        except Exception as exc:
            error = exc
        captured = capture_payload(
            RAW_SOURCE,
            url,
            {
                "series_id": series.series_id,
                "csv": text if isinstance(text, str) else None,
            },
            parsed.latest.isoformat() if parsed and parsed.latest else None,
        )
        raw = upsert_raw(db, run, captured)
        checks["raw_payload_id"] = raw.id
        if parsed is None:
            assert error is not None
            warnings.append(us_index_warning(series, error))
            checks["error"] = f"{type(error).__name__}: {error}"
            _upsert_quality(db, series, session, "failed", checks)
            result[series.symbol] = {**checks, "status": "failed"}
            continue
        checks["latest_observation"] = (
            parsed.latest.isoformat() if parsed.latest else None
        )
        checks["closed_dates"] = [day.isoformat() for day in parsed.closed_dates]
        try:
            with db.begin_nested():
                written = store_us_index_bars(
                    db, series, parsed.bars, raw.id, force=force
                )
        except Exception as exc:
            warnings.append(us_index_warning(series, exc))
            checks["error"] = f"{type(exc).__name__}: {exc}"
            _upsert_quality(db, series, session, "failed", checks)
            result[series.symbol] = {**checks, "status": "failed"}
            continue
        if written.conflicts:
            warnings.append(
                f"{WARNING_PREFIX} kept {len(written.conflicts)} stored {EXCHANGE} "
                f"{series.symbol} close(s) that differ from FRED {series.series_id}"
            )
        checks["counts"] = dict(written.counts)
        _upsert_quality(db, series, session, "complete", checks)
        result[series.symbol] = {
            **checks,
            "status": "complete",
            "conflicts": written.conflicts,
        }
    db.flush()
    return result
