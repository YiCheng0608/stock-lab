"""US stock index daily bars from FinMind (Issues #547, #568).

Source: FinMind v4 ``USStockPrice`` (``https://api.finmindtrade.com/api/v4/data``,
anonymous, the Free plan), one GET per index with ``data_id``, ``start_date``
and ``end_date``, decided in #568 (comments 6728959423, 6729020253): S&P 500
(``^GSPC``), NASDAQ Composite (``^IXIC``), Dow Jones Industrial Average
(``^DJI``) and PHLX Semiconductor (``^SOX``).  FinMind's Free plan allows
personal, non-commercial use with "FinMind" credited and no redistribution of
the raw; the series stay display-only (never strategy, candidate, group or
tracking input).  FRED (#547) is no longer asked: its rows, where a database
has them (``fred_close``), are kept and never overwritten (#568 decision
6729023767).

Each index is one ``index`` instrument (``US``/``SPX``, ``IXIC``, ``DJI``,
``SOX``) with one ``market_bars`` row per US session (the US Eastern date),
whatever the source: FinMind's open, high, low, close and volume as given,
turnover ``unavailable``/``not_published``.  An index's volume is the data
vendor's sum over its members, not a trade of the index; a 0 is no published
volume, never a zero: an answer whose every volume is 0 (``^SOX`` today) is
stored NULL, and a single 0 among real volumes is NULL with a warning (#568
decision 6729139244).  FinMind returns no row for a US
market holiday; a weekday of the request without a row, before the newest row
returned, is a holiday and is kept in the series' ``data_quality`` row
(``closed_dates``) so the market page can say 美股休市.  A missing newest
weekday is not called a holiday: FinMind may not have published it yet.

``worker.cli index-bars us-collect`` (``collect_us_indexes``) runs on its own
(serve's ``us`` job, Taipei Tuesday to Saturday): for Taipei day D it asks
``start_date`` = 10 days before the newest stored row (``HISTORY_START``,
2023-09-01, when the series has no row or its oldest row is later than that)
to ``end_date`` = D − 1.  An answer that is not that index's rows, has a
malformed row or a date outside the request is rejected whole (a ``us index
bars`` warning; the raw is kept).  A stored FinMind row takes the values of a
later capture (``revised``, old and new in the run's ``value_revision_rows``);
another source's row (FRED) is never overwritten (a conflict).  When every index
already has D − 1 the run asks nothing (``already_complete``) unless ``force``.  One ``us_index_collect`` run per call; the indicator
and feature rows of the series it changed are rebuilt at the end.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

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

SOURCE = "finmind_us_index"
RAW_SOURCE = "finmind"
DATASET = "USStockPrice"
EXCHANGE = US_INDEX_EXCHANGE
MARKET = "US"
ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
NO_TURNOVER = "not_published"
WARNING_PREFIX = "us index bars"
QUALITY_ENTITY = US_INDEX_QUALITY_ENTITY
# About a year before the stock history (2024-09-30), so the 240-session
# average exists on the stocks' first day (#1 6723720803, Issue #563).
HISTORY_START = date(2023, 9, 1)
RUN_TYPE = "us_index_collect"
# Re-read this many days before the newest stored row, so a late or revised
# session is still picked up.
LOOKBACK_DAYS = 10
RETRY_DELAY_SECONDS = 5.0
# DATA_SOURCES FinMind 補缺口規則: these answers stop the run, never retried.
REFUSED_STATUSES = frozenset({401, 402, 403})

SERIES = US_INDEXES
SERIES_BY_SYMBOL = {item.symbol: item for item in SERIES}


class FinMindRefused(OfficialDataError):
    """FinMind answered 401/402/403 (a limit, a login or a paid plan): stop asking."""


@dataclass(frozen=True)
class UsIndexBar:
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    # None: the source has no volume for the index (^SOX answers 0).
    volume: int | None


@dataclass(frozen=True)
class ParsedSeries:
    bars: list[UsIndexBar]
    # Weekdays of the request without a row, before the newest row: US holidays.
    closed_dates: list[date]
    # Every volume of the answer was 0: the source publishes none for the index.
    no_volume: bool = False
    # Days at 0 among real volumes (stored NULL, warned).
    zero_volume_dates: list[date] = field(default_factory=list)

    @property
    def latest(self) -> date | None:
        return max((bar.trading_date for bar in self.bars), default=None)


def data_id(series: UsIndex) -> str:
    """FinMind's data_id of the index (``app.domain.US_INDEXES``, DATA_SOURCES 美股指數)."""

    return series.series_id


def request_url(series: UsIndex, start: date, end: date) -> str:
    query = urlencode(
        {
            "dataset": DATASET,
            "data_id": data_id(series),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    )
    return f"{ENDPOINT}?{query}"


def request_window(
    earliest_stored: date | None, latest_stored: date | None, session: date
) -> tuple[date, date]:
    """``start_date``/``end_date`` of Taipei day ``session``'s request.

    From ``HISTORY_START`` when the series has no row, or its oldest row is
    more than ``LOOKBACK_DAYS`` after it (one request reaches the whole
    history); else from ``LOOKBACK_DAYS`` before the newest row.  Always to
    the day before ``session``: every US session of Taipei day D is before D.
    """

    end = session - timedelta(days=1)
    if (
        latest_stored is None
        or earliest_stored is None
        or earliest_stored > HISTORY_START + timedelta(days=LOOKBACK_DAYS)
    ):
        return HISTORY_START, end
    start = max(HISTORY_START, latest_stored - timedelta(days=LOOKBACK_DAYS))
    return min(start, end), end


def _price(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _volume(value: Any) -> int | None:
    """A whole volume of 0 or more, or None when unreadable."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0 or float(value) != int(value):
        return None
    return int(value)


def _closed_weekdays(start: date, latest: date, seen: set[date]) -> list[date]:
    out = []
    day = start
    while day < latest:
        if day.weekday() < 5 and day not in seen:
            out.append(day)
        day += timedelta(days=1)
    return out


def parse_rows(
    payload: Any, series: UsIndex, *, start: date, end: date
) -> ParsedSeries:
    """The sessions of one ``USStockPrice`` answer, or OfficialDataError.

    The answer must be FinMind's ``{"status": 200, "msg": "success", "data":
    [...]}``; every row this index's ``stock_id``, a date inside
    ``start``..``end`` seen once, positive open/high/low/close with the high
    and low around open and close, and a whole volume of 0 or more.  An answer
    without any row is rejected: a ten-day window always has sessions.
    """

    label = f"FinMind {DATASET} {data_id(series)}"
    if not isinstance(payload, dict):
        raise OfficialDataError(f"{label} answer is not a JSON object")
    status = payload.get("status")
    if status in REFUSED_STATUSES:
        raise FinMindRefused(f"{label} answered status {status}: {payload.get('msg')}")
    if status != 200 or not isinstance(payload.get("data"), list):
        raise OfficialDataError(
            f"{label} answer is not a success (status {status!r}, "
            f"msg {str(payload.get('msg'))[:80]!r})"
        )
    bars: list[UsIndexBar] = []
    seen: set[date] = set()
    for row in payload["data"]:
        if not isinstance(row, dict):
            raise OfficialDataError(f"{label} has a row that is not an object")
        if row.get("stock_id") != data_id(series):
            raise OfficialDataError(
                f"{label} has a row of {str(row.get('stock_id'))[:20]!r}"
            )
        try:
            day = date.fromisoformat(str(row.get("date")))
        except ValueError as exc:
            raise OfficialDataError(
                f"{label} has an invalid date {str(row.get('date'))[:20]!r}"
            ) from exc
        if not start <= day <= end:
            raise OfficialDataError(
                f"{label} reports {day.isoformat()} outside "
                f"{start.isoformat()}..{end.isoformat()}"
            )
        if day in seen:
            raise OfficialDataError(f"{label} reports {day.isoformat()} twice")
        seen.add(day)
        prices = [_price(row.get(key)) for key in ("Open", "High", "Low", "Close")]
        if any(value is None for value in prices):
            raise OfficialDataError(
                f"{label} has an unreadable price on {day.isoformat()}"
            )
        opened, high, low, close = prices
        if low > min(opened, close) or high < max(opened, close):
            raise OfficialDataError(
                f"{label} has a high/low outside open/close on {day.isoformat()}"
            )
        volume = _volume(row.get("Volume"))
        if volume is None:
            raise OfficialDataError(
                f"{label} has an unreadable volume on {day.isoformat()}"
            )
        bars.append(UsIndexBar(day, opened, high, low, close, volume))
    if not bars:
        raise OfficialDataError(
            f"{label} has no row in {start.isoformat()}..{end.isoformat()}"
        )
    bars.sort(key=lambda bar: bar.trading_date)
    # A 0 is no published volume, never a zero (#568 decision 6729139244): the
    # whole answer at 0 is an index without volume (^SOX today), stored NULL; a
    # 0 among real volumes is NULL too, and named (a warning).
    zeros = [bar.trading_date for bar in bars if bar.volume == 0]
    bars = [
        UsIndexBar(b.trading_date, b.open, b.high, b.low, b.close, b.volume or None)
        for b in bars
    ]
    return ParsedSeries(
        bars,
        _closed_weekdays(start, bars[-1].trading_date, seen),
        no_volume=len(zeros) == len(bars),
        zero_volume_dates=[] if len(zeros) == len(bars) else zeros,
    )


def fetch_json(url: str, *, timeout_seconds: float = 30.0) -> Any:
    """GET one FinMind answer, anonymously.

    One retry after ``RETRY_DELAY_SECONDS`` on a transport error, 429 or 5xx;
    401/402/403 raise ``FinMindRefused`` at once (no retry, DATA_SOURCES).
    A 200 whose body is not JSON comes back as its text: ``parse_rows``
    rejects it and the caller keeps it as raw.
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
                raise OfficialDataError(f"FinMind transport failed: {url}") from exc
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        if response.status_code in REFUSED_STATUSES:
            raise FinMindRefused(f"FinMind answered {response.status_code}: {url}")
        if response.status_code == 429 or response.status_code >= 500:
            if attempt:
                raise OfficialDataError(
                    f"FinMind answered {response.status_code}: {url}"
                )
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        if response.status_code != 200:
            raise OfficialDataError(f"FinMind answered {response.status_code}: {url}")
        try:
            return response.json()
        except ValueError:
            # Not JSON (a block page, an HTML error): the text itself, so the
            # caller rejects it and still keeps it as raw (#568 review item 5).
            return response.text
    raise OfficialDataError(f"FinMind request failed: {url}")  # pragma: no cover


def us_index_warning(series: UsIndex, exc: Exception) -> str:
    """The warning text (pipeline.NONCORE_WARNING_PATTERN's ``us index bars``)."""

    return (
        f"{WARNING_PREFIX} unavailable for {EXCHANGE} {series.symbol} "
        f"({data_id(series)}): {type(exc).__name__}: {exc}"
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


def stored_range(db: Session, series: UsIndex) -> tuple[date | None, date | None]:
    item = find_instrument(db, series)
    if item is None:
        return None, None
    row = db.execute(
        select(
            func.min(MarketBar.trading_date), func.max(MarketBar.trading_date)
        ).where(MarketBar.instrument_id == item.id)
    ).one()
    return row[0], row[1]


@dataclass
class SeriesWriteResult:
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "inserted": 0,
            "revised": 0,
            "unchanged": 0,
            "conflict": 0,
        }
    )
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    # FinMind's own rows whose values a later capture changed (#568 review item 1).
    revisions: list[dict[str, Any]] = field(default_factory=list)


def _same(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return first is None and second is None
    return round(float(first), 4) == round(float(second), 4)


def _same_bar(row: MarketBar, bar: UsIndexBar) -> bool:
    return (
        row.source == SOURCE
        and _same(row.open, bar.open)
        and _same(row.high, bar.high)
        and _same(row.low, bar.low)
        and _same(row.close, bar.close)
        and _same(row.volume, bar.volume)
    )


def _values(row_or_bar: Any) -> dict[str, Any]:
    return {
        key: getattr(row_or_bar, key)
        for key in ("open", "high", "low", "close", "volume")
    }


def _is_later(row: MarketBar, captured_at: datetime | None) -> bool:
    """Whether a capture at ``captured_at`` is newer than the stored row's."""

    if captured_at is None or row.collected_at is None:
        return True
    return row.collected_at <= captured_at


def store_us_index_bars(
    db: Session,
    series: UsIndex,
    bars: Iterable[UsIndexBar],
    raw_payload_id: int,
    *,
    captured_at: datetime | None = None,
) -> SeriesWriteResult:
    """Insert new sessions and take FinMind's later values of its own rows.

    As the institutional revisions of the Taiwan chips: a stored FinMind row
    (``finmind_us_index``) whose values differ from a capture taken after it
    gets the new values (``revised``; old and new values in ``revisions``),
    so a first value of D − 1 revised within the 10-day re-read, or a single
    day's volume first published as 0 (NULL) and later given, is picked up
    (#568 review item 1).  A row of another source (a FRED close, #547) is
    never overwritten and is a conflict (#568 decision 6729023767).
    """

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
        if row is not None and _same_bar(row, bar):
            result.counts["unchanged"] += 1
            continue
        if row is not None and (
            row.source != SOURCE or not _is_later(row, captured_at)
        ):
            result.counts["conflict"] += 1
            result.conflicts.append(
                {
                    "symbol": series.symbol,
                    "trading_date": bar.trading_date.isoformat(),
                    "stored": {**_values(row), "source": row.source},
                    "incoming": {**_values(bar), "source": SOURCE},
                    "raw_payload_id": raw_payload_id,
                }
            )
            continue
        if row is None:
            outcome = "inserted"
            row = MarketBar(instrument_id=instrument.id, trading_date=bar.trading_date)
            db.add(row)
        else:
            outcome = "revised"
            result.revisions.append(
                {
                    "symbol": series.symbol,
                    "trading_date": bar.trading_date.isoformat(),
                    "old": {
                        **_values(row),
                        "raw_payload_id": row.raw_payload_id,
                        "collected_at": row.collected_at.isoformat()
                        if row.collected_at
                        else None,
                    },
                    "new": {**_values(bar), "raw_payload_id": raw_payload_id},
                }
            )
        row.open, row.high, row.low = bar.open, bar.high, bar.low
        row.close = row.adj_close = bar.close
        # MarketBar.volume defaults to 0 on insert: NULL is no volume, never a zero.
        row.volume = null() if bar.volume is None else bar.volume
        row.turnover, row.turnover_status, row.turnover_reason = (
            0.0,
            "unavailable",
            NO_TURNOVER,
        )
        row.price_reason = None
        row.is_suspended = False
        row.source = SOURCE
        row.data_as_of = datetime.combine(bar.trading_date, datetime.min.time())
        row.collected_at = captured_at or utcnow()
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
    row.missing_fields_json = checks.pop("_missing", None) or (
        [] if status == "complete" else ["close"]
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
    """One index's answer, fetched and parsed before anything is written."""

    request: SeriesRequest
    # The raw capture (file written, no DB row yet); None when the GET failed.
    captured: Any = None
    parsed: ParsedSeries | None = None
    error: Exception | None = None


def us_index_requests(db: Session, session: date) -> list[SeriesRequest]:
    """The four requests of Taipei day ``session`` (reads only)."""

    return [
        SeriesRequest(series, *request_window(*stored_range(db, series), session))
        for series in SERIES
    ]


def fetch_us_index_series(
    requests: Iterable[SeriesRequest], fetch: Callable[[str], Any]
) -> list[FetchedSeries]:
    """GET and parse every index; no database access.

    A failed GET or a rejected answer is kept with its error; an answer is
    captured as a raw file either way.  After a ``FinMindRefused`` the rest is
    not asked (DATA_SOURCES: stop, no retry within the run).
    """

    fetched: list[FetchedSeries] = []
    refused: Exception | None = None
    for request in requests:
        item = FetchedSeries(request)
        fetched.append(item)
        if refused is not None:
            item.error = OfficialDataError(f"not asked: {refused}")
            continue
        try:
            payload = fetch(request.url)
        except FinMindRefused as exc:
            item.error = refused = exc
            continue
        except Exception as exc:
            item.error = exc
            continue
        try:
            item.parsed = parse_rows(
                payload, request.series, start=request.start, end=request.end
            )
        except FinMindRefused as exc:
            item.error = refused = exc
        except Exception as exc:
            item.error = exc
        item.captured = capture_payload(
            RAW_SOURCE,
            request.url,
            {
                "dataset": DATASET,
                "data_id": data_id(request.series),
                "answer": payload,
            },
            item.parsed.latest.isoformat()
            if item.parsed and item.parsed.latest
            else None,
        )
    return fetched


def _write_series(
    db: Session,
    run: Any,
    session: date,
    item: FetchedSeries,
    upsert_raw: Callable[[Session, Any, Any], Any],
    warnings: list[str],
) -> dict[str, Any]:
    series, request = item.request.series, item.request
    checks: dict[str, Any] = {
        "dataset": DATASET,
        "data_id": data_id(series),
        "endpoint": request.url,
        "requested": [request.start.isoformat(), request.end.isoformat()],
    }
    if item.captured is not None:
        checks["raw_payload_id"] = upsert_raw(db, run, item.captured).id
    if item.parsed is None:
        error = item.error or OfficialDataError("no answer")
        warnings.append(us_index_warning(series, error))
        checks["error"] = f"{type(error).__name__}: {error}"
        _upsert_quality(db, series, session, "failed", dict(checks))
        return {**checks, "status": "failed"}
    parsed = item.parsed
    checks["first_observation"] = parsed.bars[0].trading_date.isoformat()
    checks["latest_observation"] = parsed.latest.isoformat()
    checks["closed_dates"] = [day.isoformat() for day in parsed.closed_dates]
    checks["volume"] = "not_published" if parsed.no_volume else "published"
    if parsed.zero_volume_dates:
        days = [day.isoformat() for day in parsed.zero_volume_dates]
        checks["zero_volume_dates"] = days
        warnings.append(
            f"{WARNING_PREFIX} stored no volume for {EXCHANGE} {series.symbol} on "
            f"{len(days)} day(s) FinMind {data_id(series)} gave 0: {', '.join(days[:10])}"
        )
    try:
        with db.begin_nested():
            written = store_us_index_bars(
                db,
                series,
                parsed.bars,
                checks["raw_payload_id"],
                captured_at=item.captured.collected_at,
            )
    except Exception as exc:
        warnings.append(us_index_warning(series, exc))
        checks["error"] = f"{type(exc).__name__}: {exc}"
        _upsert_quality(db, series, session, "failed", dict(checks))
        return {**checks, "status": "failed"}
    if written.conflicts:
        warnings.append(
            f"{WARNING_PREFIX} kept {len(written.conflicts)} stored {EXCHANGE} "
            f"{series.symbol} row(s) that differ from FinMind {data_id(series)}"
        )
    checks["counts"] = dict(written.counts)
    if written.revisions:
        checks["value_revision_rows"] = written.revisions
    missing = ["volume"] if parsed.no_volume else []
    _upsert_quality(db, series, session, "complete", {**checks, "_missing": missing})
    return {**checks, "status": "complete", "conflicts": written.conflicts}


def write_us_index_series(
    db: Session,
    run: Any,
    session: date,
    fetched: Iterable[FetchedSeries],
    upsert_raw: Callable[[Session, Any, Any], Any],
    warnings: list[str],
) -> dict[str, Any]:
    """Write the fetched indexes: raw rows, bars and data_quality.

    Each index is one savepoint: a database error in its raw, bars or quality
    row rolls back that index only and becomes a warning.  A rejected or
    failed index writes no bar and records the reason in its quality row.
    """

    result: dict[str, Any] = {}
    for item in fetched:
        series = item.request.series
        series_warnings: list[str] = []
        try:
            with db.begin_nested():
                result[series.symbol] = _write_series(
                    db, run, session, item, upsert_raw, series_warnings
                )
        except Exception as exc:
            series_warnings = [us_index_warning(series, exc)]
            result[series.symbol] = {
                "data_id": data_id(series),
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        warnings.extend(series_warnings)
    return result


# --- us-collect (Issue #568) ----------------------------------------------------


def expected_session(session: date) -> date:
    """The US session Taipei day ``session`` waits for: the weekday before it.

    The same rule as the market page's ``expected_date``
    (``app.market_overview.expected_us_session``).
    """

    day = session - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def collect_us_indexes(
    db: Session,
    *,
    session: date,
    fetch: Callable[[str], Any] = fetch_json,
    force: bool = False,
    trigger: str = "manual",
    skip_reason: str | None = None,
) -> dict[str, Any]:
    """``index-bars us-collect``: the four indexes to Taipei day ``session`` − 1.

    One ``us_index_collect`` run.  The request windows are read first and
    that read transaction is ended before the GETs (no write lock is held
    while FinMind answers); each index is written in its own savepoint.  The
    run is ``success`` when every index is complete, ``partial`` when some
    are, ``failed`` when none is.  With ``skip_reason`` (the job's
    ``low_memory``/``git_busy``, as daily records its skips) nothing is asked
    and the run is ``skipped``.  The indicator and feature rows of the
    indexes whose bars changed are rebuilt at the end.
    """

    from app.models import IngestionRun

    from .index_bars import rebuild_derived
    from .pipeline import _upsert_raw_payload

    run = IngestionRun(
        run_type=RUN_TYPE,
        source=RAW_SOURCE,
        run_date=session,
        status="running",
        started_at=utcnow(),
        metadata_json={
            "dataset": DATASET,
            "history_start": HISTORY_START.isoformat(),
            "force": force,
            "trigger": trigger,
        },
    )
    db.add(run)
    db.commit()
    if skip_reason:
        run.status = "skipped"
        run.records = 0
        run.finished_at = utcnow()
        run.metadata_json = {
            **run.metadata_json,
            "skip_reason": skip_reason,
            "requests": 0,
        }
        db.commit()
        return {
            "status": "skipped",
            "run_id": run.id,
            "skip_reason": skip_reason,
            "requests": 0,
        }
    try:
        expected = expected_session(session)
        latest = {series.symbol: stored_range(db, series)[1] for series in SERIES}
        if not force and all(
            day is not None and day >= expected for day in latest.values()
        ):
            # Serve's 09:30 after a 06:30 that got D − 1 (#568 decision 6729065016).
            run.status = "already_complete"
            run.records = 0
            run.finished_at = utcnow()
            run.metadata_json = {
                **run.metadata_json,
                "requests": 0,
                "latest_stored": {k: v.isoformat() for k, v in latest.items()},
            }
            db.commit()
            return {
                "status": "already_complete",
                "run_id": run.id,
                "session": session.isoformat(),
                "requests": 0,
            }
        requests = us_index_requests(db, session)
        db.commit()  # only reads: end the transaction before the HTTP calls
        fetched = fetch_us_index_series(requests, fetch)
        warnings: list[str] = []
        results = write_us_index_series(
            db, run, session, fetched, _upsert_raw_payload, warnings
        )
        changed = [
            find_instrument(db, SERIES_BY_SYMBOL[symbol]).id
            for symbol, entry in results.items()
            if entry.get("counts", {}).get("inserted")
            or entry.get("counts", {}).get("revised")
        ]
        indicators = rebuild_derived(db, changed)
        complete = [s for s, e in results.items() if e["status"] == "complete"]
        run.status = (
            "success"
            if len(complete) == len(results)
            else "partial"
            if complete
            else "failed"
        )
        run.records = sum(
            entry.get("counts", {}).get("inserted", 0)
            + entry.get("counts", {}).get("revised", 0)
            for entry in results.values()
        )
        run.finished_at = utcnow()
        run.metadata_json = {
            **run.metadata_json,
            "series": results,
            "requests": sum(
                1
                for item in fetched
                if not str(item.error or "").startswith("not asked")
            ),
            "warnings": warnings,
            "indicators": indicators,
            # FinMind's own rows a later capture changed: old and new values.
            "value_revision_rows": [
                revision
                for entry in results.values()
                for revision in entry.get("value_revision_rows", [])
            ],
        }
        if run.status == "failed":
            run.error = "; ".join(warnings)[:2000]
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
        "session": session.isoformat(),
        "requests": run.metadata_json["requests"],
        "series": {
            symbol: {
                key: entry.get(key)
                for key in (
                    "status",
                    "requested",
                    "counts",
                    "first_observation",
                    "latest_observation",
                    "error",
                )
                if key in entry
            }
            for symbol, entry in results.items()
        },
        "indicators": indicators,
        "value_revision_rows": len(run.metadata_json["value_revision_rows"]),
        "warnings": warnings,
    }


def run_us_collect(
    *,
    session: date | None = None,
    force: bool = False,
    trigger: str = "manual",
    skip_reason: str | None = None,
) -> dict[str, Any]:
    from app.db import SessionLocal

    from .index_bars import taipei_today

    with SessionLocal() as db:
        return collect_us_indexes(
            db,
            session=session or taipei_today(),
            force=force,
            trigger=trigger,
            skip_reason=skip_reason,
        )
