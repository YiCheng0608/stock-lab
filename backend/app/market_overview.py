"""``dashboard.market_overview``: stored market summaries of the dashboard date.

Only reads ``market_summaries`` written by collect and ``worker.cli
market-summary`` (Issue #275).  Each exchange is shown for ``dashboard.as_of``
alone; a row of another date is never shown in its place.

``foreign_indices`` (Issues #547, #568) reads the daily bars of the ``US`` index
instruments (``worker.us_index_bars``) and their ``data_quality`` rows: the
newest close of each, its change from the stored close before it, and whether
it is the expected US session (the weekday before the reference date).  Since
#681 the dashboard no longer carries them: ``overnight_us`` gives them to
``/api/candidates`` (the today page's 隔夜美股 line).

``taiex_ma60`` (Issue #561) reads TAIEX's ``market_bars`` close and the stored
``technical_indicators`` ``ma60`` (``indicators/v1``) of the dashboard date:
whether the close is above its 60-session average, as the research filter R3
defines it (``app.strategies.regime``: close strictly above MA60, 60 closes
needed), and the latest runs of sessions above it.  Display only: no strategy,
candidate or group reads it.

``indexes`` (Issue #564) is the market page's index table: TAIEX, TPEX and the
TX near month (the four US rows left in #633's page and #681's API), each with
its close, change, data date and its close against its own stored MA60, judged
as ``taiex_ma60`` judges it.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from .clock import utcnow
from .domain import (
    US_INDEX_EXCHANGE,
    US_INDEX_GROUP_LINKS,
    US_INDEX_QUALITY_ENTITY,
    US_INDEXES,
    UsIndex,
)
from .indicators import INDICATOR_VERSION, PRICE_BASIS, REQUIRED_BARS
from .market_change import adjacent_change
from .models import (
    DataQuality,
    Instrument,
    MarketBar,
    MarketSummary,
    TechnicalIndicator,
)

EXCHANGES = ("TWSE", "TPEx")
INDEX_LABELS = {"TWSE": "加權指數", "TPEx": "櫃買指數"}
SOURCE_LABELS = {
    "twse_mi_index": "臺灣證券交易所 MI_INDEX",
    "tpex_mainborad_highlight": "櫃買中心 tpex_mainborad_highlight",
}
TURNOVER_SCOPE_LABELS = {
    "twse_all_securities": "集中市場總計（含 ETF、權證等）",
    "tpex_stocks": "上櫃股票",
}


def _collected_at(row: MarketSummary) -> str | None:
    value = row.collected_at
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _available(row: MarketSummary) -> dict[str, Any]:
    return {
        "exchange": row.exchange,
        "status": "available",
        "index": {
            "name": INDEX_LABELS.get(row.exchange, row.index_name),
            "close": row.index_close,
            "change": row.index_change,
            "change_pct": row.index_change_pct,
            "change_pct_method": row.change_pct_method,
        },
        "turnover": {
            "value": row.turnover,
            "scope": row.turnover_scope,
            "scope_label": TURNOVER_SCOPE_LABELS.get(row.turnover_scope),
        },
        "breadth": {
            "advancers": row.advancers,
            "decliners": row.decliners,
            "unchanged": row.unchanged,
            "limit_up": row.limit_up,
            "limit_down": row.limit_down,
            "unmatched": row.unmatched,
            "not_comparable": row.not_comparable,
            "scope": row.breadth_scope,
        },
        "source": {
            "label": SOURCE_LABELS.get(row.source, row.source),
            "collected_at": _collected_at(row),
            "data_as_of": row.data_as_of,
            "raw_payload_id": row.raw_payload_id,
        },
    }


def market_overview(db: Session, as_of: str | None) -> dict[str, Any]:
    """Both exchanges for ``as_of`` (``dashboard.as_of``), each on its own.

    ``unavailable`` reasons: ``no_verified_session`` (the dashboard has no
    date), ``row_date_mismatch`` (the exchange's newest row is of another
    date, given as ``latest_trading_date``) and ``not_collected`` (no row).
    """

    session = date.fromisoformat(as_of) if as_of else None
    exchanges: list[dict[str, Any]] = []
    for exchange in EXCHANGES:
        if session is None:
            exchanges.append(
                {
                    "exchange": exchange,
                    "status": "unavailable",
                    "reason": "no_verified_session",
                }
            )
            continue
        row = db.scalar(
            select(MarketSummary).where(
                MarketSummary.exchange == exchange,
                MarketSummary.trading_date == session,
            )
        )
        if row is not None:
            exchanges.append(_available(row))
            continue
        latest = db.scalar(
            select(MarketSummary.trading_date)
            .where(MarketSummary.exchange == exchange)
            .order_by(desc(MarketSummary.trading_date))
            .limit(1)
        )
        exchanges.append(
            {
                "exchange": exchange,
                "status": "unavailable",
                "reason": "row_date_mismatch" if latest else "not_collected",
                "latest_trading_date": latest.isoformat() if latest else None,
            }
        )
    return {
        "trading_date": as_of,
        "exchanges": exchanges,
        "taiex_ma60": taiex_ma60(db, as_of),
        "indexes": index_rows(db, as_of),
    }


# --- TAIEX against its MA60 (Issue #561) ---------------------------------------

MA60_REQUIRED_CLOSES = REQUIRED_BARS["ma60"]
# Runs above MA60 are looked for in the last SEGMENT_SESSIONS TAIEX sessions
# through the dashboard date; the newest MAX_SEGMENTS of them are returned.
SEGMENT_SESSIONS = 250
MAX_SEGMENTS = 3
TAIEX_SOURCE_LABEL = "臺灣證券交易所"


def _taiex_instrument(db: Session) -> Instrument | None:
    # The benchmark the research run reads (worker.pipeline._benchmark_instrument).
    return db.scalar(
        select(Instrument)
        .where(
            Instrument.symbol == "TAIEX",
            Instrument.instrument_type == "index",
            Instrument.status == "active",
        )
        .limit(1)
    )


def _above(close: float | None, ma60: float | None) -> bool:
    """R3 on one day: the close strictly above the stored MA60."""

    return (
        ma60 is not None
        and close is not None
        and math.isfinite(close)
        and close > 0
        and close > ma60
    )


def _segments(rows: list[Any], earlier_above: bool) -> list[dict[str, Any]]:
    """Runs of consecutive TAIEX sessions above MA60 in ``rows`` (oldest first), newest first.

    ``earlier_above``: the session before ``rows`` was above too, so the first
    run started before the window (``starts_before_window``).
    """

    runs: list[list[Any]] = []
    current: list[Any] | None = None
    for row in rows:
        if _above(row.close, row.ma60):
            if current is None:
                current = []
                runs.append(current)
            current.append(row)
        else:
            current = None
    last = rows[-1].trading_date if rows else None
    result = [
        {
            "start": run[0].trading_date.isoformat(),
            "end": run[-1].trading_date.isoformat(),
            "sessions": len(run),
            "ongoing": run[-1].trading_date == last,
            "starts_before_window": earlier_above and run[0] is rows[0],
        }
        for run in runs
    ]
    return list(reversed(result))[:MAX_SEGMENTS]


def _ma60_rows(
    db: Session, instrument: Instrument | None, session: date, limit: int
) -> list[Any]:
    """The instrument's newest ``limit`` bars through ``session`` with their ``indicators/v1`` row, newest first."""

    if instrument is None:
        return []
    return list(
        db.execute(
            select(
                MarketBar.trading_date,
                MarketBar.close,
                MarketBar.source,
                TechnicalIndicator.id.label("indicator_id"),
                TechnicalIndicator.ma60,
                TechnicalIndicator.bar_count,
                TechnicalIndicator.null_reasons,
                TechnicalIndicator.computed_at,
            )
            .outerjoin(
                TechnicalIndicator,
                and_(
                    TechnicalIndicator.instrument_id == MarketBar.instrument_id,
                    TechnicalIndicator.trading_date == MarketBar.trading_date,
                    TechnicalIndicator.formula_version == INDICATOR_VERSION,
                    TechnicalIndicator.price_basis == PRICE_BASIS,
                ),
            )
            .where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date <= session,
            )
            .order_by(desc(MarketBar.trading_date))
            .limit(limit)
        ).all()
    )


def _ma60_on(rows: list[Any], session: date) -> dict[str, Any]:
    """The close of ``session`` against its stored MA60: the one judgement of
    ``taiex_ma60`` and every ``indexes`` row (``rows`` from ``_ma60_rows``)."""

    if not rows:
        return {"status": "unavailable", "reason": "not_collected"}
    latest = rows[0]
    if latest.trading_date != session:
        return {
            "status": "unavailable",
            "reason": "row_date_mismatch",
            "latest_trading_date": latest.trading_date.isoformat(),
        }
    if latest.indicator_id is None:
        return {"status": "unavailable", "reason": "indicator_not_computed"}
    if latest.ma60 is None:
        null_reason = (latest.null_reasons or {}).get("ma60")
        if null_reason == "insufficient_bars":
            return {
                "status": "insufficient",
                "reason": "insufficient_closes",
                "close_count": latest.bar_count,
            }
        return {
            "status": "unavailable",
            "reason": "ma60_unavailable",
            "null_reason": null_reason,
        }
    close, ma60 = latest.close, latest.ma60
    above = _above(close, ma60)
    return {
        "status": "available",
        "close": close,
        "ma60": ma60,
        "above": above,
        "position": "above" if above else "equal" if close == ma60 else "below",
        "close_count": latest.bar_count,
    }


def taiex_ma60(db: Session, as_of: str | None) -> dict[str, Any]:
    """TAIEX's close against its stored MA60 on ``as_of`` (module docstring).

    ``status``: ``available`` (``above`` is R3; ``position`` is ``above``,
    ``below`` or ``equal``), ``insufficient`` (fewer than 60 usable closes
    through ``as_of``: ``close_count``) or ``unavailable`` with ``reason``
    ``no_verified_session``, ``not_collected`` (no TAIEX bar), ``row_date_mismatch``
    (TAIEX's newest bar is of another date: ``latest_trading_date``),
    ``indicator_not_computed`` (no ``indicators/v1`` row for the bar) or
    ``ma60_unavailable`` (MA60 is null for another reason: ``null_reason``).
    """

    base: dict[str, Any] = {
        "trading_date": as_of,
        "required_closes": MA60_REQUIRED_CLOSES,
    }
    if not as_of:
        return {**base, "status": "unavailable", "reason": "no_verified_session"}
    session = date.fromisoformat(as_of)
    instrument = _taiex_instrument(db)
    # One more than the window: whether its first run started earlier.
    rows = _ma60_rows(db, instrument, session, SEGMENT_SESSIONS + 1)
    state = _ma60_on(rows, session)
    if state["status"] != "available":
        return {**base, **state}
    latest = rows[0]
    window = list(reversed(rows[:SEGMENT_SESSIONS]))
    earlier = rows[SEGMENT_SESSIONS] if len(rows) > SEGMENT_SESSIONS else None
    return {
        **base,
        **state,
        "segments": _segments(
            window, earlier is not None and _above(earlier.close, earlier.ma60)
        ),
        "segment_window": {
            "start": window[0].trading_date.isoformat(),
            "end": as_of,
            "sessions": len(window),
            "max_segments": MAX_SEGMENTS,
        },
        "source": {
            "label": TAIEX_SOURCE_LABEL,
            "bar_source": latest.source,
            "formula_version": INDICATOR_VERSION,
            "computed_at": _iso_utc(latest.computed_at),
            "data_as_of": as_of,
        },
    }


# --- US indexes (Issue #547) ----------------------------------------------------

# Quality rows read for closed US dates (us-collect's closed_dates); each covers the ten days
# before its run's newest stored row onward.
_QUALITY_ROWS = 5


def _taipei_today() -> date:
    return (utcnow() + timedelta(hours=8)).date()


def expected_us_session(reference: date) -> date:
    """The weekday before Taipei date ``reference`` (Monday → the Friday before)."""

    day = reference - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _quality_rows(db: Session, series: UsIndex) -> list[DataQuality]:
    return list(
        db.scalars(
            select(DataQuality)
            .where(
                DataQuality.entity_type == US_INDEX_QUALITY_ENTITY,
                DataQuality.entity_key == f"{US_INDEX_EXCHANGE}:{series.symbol}",
            )
            .order_by(desc(DataQuality.as_of_date))
            .limit(_QUALITY_ROWS)
        )
    )


def _closed_dates(rows: list[DataQuality]) -> set[date]:
    closed: set[date] = set()
    for row in rows:
        for value in (row.checks_json or {}).get("closed_dates") or []:
            try:
                closed.add(date.fromisoformat(str(value)))
            except ValueError:
                continue
    return closed


def _freshness(latest: date, expected: date, closed: set[date]) -> str:
    """``latest``, ``us_market_closed`` (the expected day is a recorded US holiday and
    ``latest`` is the session before it) or ``stale``."""

    if latest >= expected:
        return "latest"
    if expected not in closed:
        return "stale"
    target = expected
    for _ in range(15):
        if target.weekday() < 5 and target not in closed:
            break
        target -= timedelta(days=1)
    return "us_market_closed" if latest >= target else "stale"


def _base(series: UsIndex) -> dict[str, Any]:
    return {
        "exchange": US_INDEX_EXCHANGE,
        "symbol": series.symbol,
        "name": series.name,
        "series_id": series.series_id,
    }


def _foreign_index(db: Session, series: UsIndex, expected: date) -> dict[str, Any]:
    quality = _quality_rows(db, series)
    instrument = db.scalar(
        select(Instrument).where(
            Instrument.exchange == US_INDEX_EXCHANGE,
            Instrument.symbol == series.symbol,
        )
    )
    bars = (
        list(
            db.scalars(
                select(MarketBar)
                .where(MarketBar.instrument_id == instrument.id)
                .order_by(desc(MarketBar.trading_date))
                .limit(2)
            )
        )
        if instrument is not None
        else []
    )
    if not bars:
        failed = bool(quality) and quality[0].status == "failed"
        return {
            **_base(series),
            "status": "unavailable",
            "reason": "fetch_failed" if failed else "not_collected",
            "expected_date": expected.isoformat(),
            "last_attempt_date": quality[0].as_of_date.isoformat() if quality else None,
        }
    latest = bars[0]
    previous = bars[1] if len(bars) > 1 else None
    change = change_pct = None
    if previous is not None and previous.close:
        change = round(latest.close - previous.close, 4)
        change_pct = round(change / previous.close, 6)
    return {
        **_base(series),
        "status": "available",
        "trading_date": latest.trading_date.isoformat(),
        "expected_date": expected.isoformat(),
        "freshness": _freshness(latest.trading_date, expected, _closed_dates(quality)),
        "close": latest.close,
        "change": change,
        "change_pct": change_pct,
        # Against the stored close before it (the source has no change column).
        "change_pct_method": "derived",
        "previous_trading_date": previous.trading_date.isoformat()
        if previous
        else None,
        "source": {
            "label": _us_source_detail(latest.source, series),
            "copyright": series.copyright,
            "collected_at": _iso_utc(latest.collected_at),
            "data_as_of": latest.trading_date.isoformat(),
            "raw_payload_id": latest.raw_payload_id,
        },
    }


def foreign_indices(db: Session, as_of: str | None) -> list[dict[str, Any]]:
    """The four US indexes, each on its own (DATA_SOURCES 美股指數).

    The expected session is the weekday before ``as_of`` (the dashboard's
    Taiwan session; Taipei today when there is none), per #547's decision.
    ``unavailable`` reasons: ``not_collected`` (no stored close) and
    ``fetch_failed`` (no stored close and the latest attempt failed).
    """

    reference = date.fromisoformat(as_of) if as_of else _taipei_today()
    expected = expected_us_session(reference)
    return [_foreign_index(db, series, expected) for series in US_INDEXES]


def next_weekday(day: date) -> date:
    """The weekday after ``day`` (Friday → Monday)."""

    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def overnight_us(db: Session, list_date: date | None) -> dict[str, Any]:
    """The today page's 隔夜美股 line (#681): the four ``foreign_indices``.

    The reference is the Taipei day the list is read before the open: Taipei
    today for the latest list (``list_date`` None), else the weekday after the
    asked list's date.  Its expected US session is the weekday before it, and
    each index keeps ``foreign_indices``'s freshness (``latest``, ``stale``,
    ``us_market_closed``) and ``unavailable`` reasons.  ``group_links`` is
    ``app.domain.US_INDEX_GROUP_LINKS``: the groups a candidate row shows the
    index's change for.  Display only: nothing scores or ranks on it.
    """

    reference = next_weekday(list_date) if list_date else _taipei_today()
    return {
        "reference_date": reference.isoformat(),
        "expected_date": expected_us_session(reference).isoformat(),
        "indexes": foreign_indices(db, reference.isoformat()),
        "group_links": {
            symbol: sorted(ids) for symbol, ids in US_INDEX_GROUP_LINKS.items()
        },
    }


# --- The index table of the market page (Issue #564) ---------------------------

# key, exchange, symbol, name and the short source of the rows, in table order
# (no US rows since #681: they are /api/candidates' overnight_us).
TW_INDEX_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    ("taiex", "TWSE", "TAIEX", "加權指數", "臺灣證券交易所"),
    ("tpex", "TPEx", "TPEX", "櫃買指數", "證券櫃檯買賣中心"),
    ("tx", "TAIFEX", "TX", "台指期近月", "臺灣期貨交易所"),
)
US_SOURCE_LABEL = "FinMind"
# market_bars.source of the US rows (worker.us_index_bars): FinMind since #568;
# FRED's close-only rows (#547) where a database still has them.
US_BAR_SOURCE_LABELS = {"finmind_us_index": "FinMind", "fred_close": "FRED"}
US_DATASET = "USStockPrice"


def _us_source_label(bar_source: str | None) -> str:
    return US_BAR_SOURCE_LABELS.get(bar_source or "", US_SOURCE_LABEL)


def _us_source_detail(bar_source: str | None, series: UsIndex) -> str:
    label = _us_source_label(bar_source)
    if label == "FRED":
        return label
    return f"{label} {US_DATASET} {series.series_id}"


def _instrument(db: Session, exchange: str, symbol: str) -> Instrument | None:
    if exchange == "TWSE" and symbol == "TAIEX":
        return _taiex_instrument(db)
    return db.scalar(
        select(Instrument)
        .where(Instrument.exchange == exchange, Instrument.symbol == symbol)
        .limit(1)
    )


def _row_ma60(
    db: Session, instrument: Instrument | None, trading_date: str
) -> dict[str, Any]:
    """The row's close against its stored MA60 on the row's own data date."""

    day = date.fromisoformat(trading_date)
    return {
        "trading_date": trading_date,
        "required_closes": MA60_REQUIRED_CLOSES,
        **_ma60_on(_ma60_rows(db, instrument, day, 1), day),
    }


def _summary_row(db: Session, exchange: str, session: date | None) -> dict[str, Any]:
    """TAIEX / TPEX: the exchange's newest ``market_summaries`` row through
    ``session`` (the numbers of the 大盤概況 widgets); another day is ``stale``."""

    if session is None:
        return {"status": "unavailable", "reason": "no_verified_session"}
    row = db.scalar(
        select(MarketSummary)
        .where(
            MarketSummary.exchange == exchange,
            MarketSummary.trading_date <= session,
        )
        .order_by(desc(MarketSummary.trading_date))
        .limit(1)
    )
    if row is None:
        return {"status": "unavailable", "reason": "not_collected"}
    return {
        "status": "available",
        "trading_date": row.trading_date.isoformat(),
        "expected_date": session.isoformat(),
        "freshness": "latest" if row.trading_date == session else "stale",
        "close": row.index_close,
        "change": row.index_change,
        "change_pct": row.index_change_pct,
        "change_pct_method": row.change_pct_method,
        "source_detail": SOURCE_LABELS.get(row.source, row.source),
    }


def _futures_row(
    db: Session, instrument: Instrument | None, session: date | None
) -> dict[str, Any]:
    """TX: the newest near-month bar through ``session``.

    The change is ``adjacent_change`` (the stock page header's, #475): against
    the bar of the previous verified TAIEX session only.  On a roll day that
    bar is another contract, so there is no change
    (``change_status=contract_roll``; bars are not adjusted across a roll).
    """

    if session is None:
        return {"status": "unavailable", "reason": "no_verified_session"}
    bar = (
        db.scalar(
            select(MarketBar)
            .where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date <= session,
            )
            .order_by(desc(MarketBar.trading_date))
            .limit(1)
        )
        if instrument is not None
        else None
    )
    if bar is None:
        return {"status": "unavailable", "reason": "not_collected"}
    change = adjacent_change(
        db, instrument.id, bar.trading_date, bar, {}, listing_date=None
    )
    previous = db.scalar(
        select(MarketBar)
        .where(
            MarketBar.instrument_id == instrument.id,
            MarketBar.trading_date < bar.trading_date,
        )
        .order_by(desc(MarketBar.trading_date))
        .limit(1)
    )
    previous_month = previous.contract_month if previous is not None else None
    status = change["change_status"]
    rolled = (
        status == "known"
        and previous_month is not None
        and bar.contract_month is not None
        and previous_month != bar.contract_month
    )
    if rolled:
        status = "contract_roll"
    return {
        "status": "available",
        "trading_date": bar.trading_date.isoformat(),
        "expected_date": session.isoformat(),
        "freshness": "latest" if bar.trading_date == session else "stale",
        "close": change["close"],
        "change": None if rolled else change["change"],
        "change_pct": None if rolled else change["change_pct"],
        "change_pct_method": "derived",
        "change_status": status,
        "contract_month": bar.contract_month,
        "previous_contract_month": previous_month if rolled else None,
        "open_interest": bar.open_interest,
        "source_detail": bar.source,
    }


def index_rows(db: Session, as_of: str | None) -> list[dict[str, Any]]:
    """The three rows of the market page's index table, in table order.

    Each row has its close, change and data date (``freshness``: ``latest`` or
    ``stale``) and ``ma60``: its close against the stored ``indicators/v1``
    MA60 on the row's own data date, judged by the code ``taiex_ma60`` uses
    (``_ma60_on``), so the TAIEX row of ``as_of`` is ``taiex_ma60``'s
    judgement.  The rows read through ``as_of``.  An ``unavailable`` row has a
    ``reason`` and ``ma60`` null.  The US indexes are not here (#633's page,
    #681's API): ``overnight_us``.
    """

    session = date.fromisoformat(as_of) if as_of else None
    rows: list[dict[str, Any]] = []
    for key, exchange, symbol, name, source in TW_INDEX_ROWS:
        instrument = _instrument(db, exchange, symbol)
        quote = (
            _futures_row(db, instrument, session)
            if exchange == "TAIFEX"
            else _summary_row(db, exchange, session)
        )
        detail = quote.pop("source_detail", None)
        rows.append(
            {
                "key": key,
                "group": "tw",
                "exchange": exchange,
                "symbol": symbol,
                "name": name,
                "instrument_type": "futures" if exchange == "TAIFEX" else "index",
                **quote,
                "ma60": _row_ma60(db, instrument, quote["trading_date"])
                if quote["status"] == "available"
                else None,
                "source": {"label": source, "detail": detail},
            }
        )
    return rows
