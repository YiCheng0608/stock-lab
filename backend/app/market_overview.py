"""``dashboard.market_overview``: stored market summaries of the dashboard date.

Only reads ``market_summaries`` written by collect and ``worker.cli
market-summary`` (Issue #275).  Each exchange is shown for ``dashboard.as_of``
alone; a row of another date is never shown in its place.

``foreign_indices`` (Issue #547) reads the FRED closes of the ``US`` index
instruments (``worker.us_index_bars``) and their ``data_quality`` rows: the
newest close of each, its change from the stored close before it, and whether
it is the expected US session (the weekday before the dashboard date).

``taiex_ma60`` (Issue #561) reads TAIEX's ``market_bars`` close and the stored
``technical_indicators`` ``ma60`` (``indicators/v1``) of the dashboard date:
whether the close is above its 60-session average, as the research filter R3
defines it (``app.strategies.regime``: close strictly above MA60, 60 closes
needed), and the latest runs of sessions above it.  Display only: no strategy,
candidate or group reads it.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from .clock import utcnow
from .domain import US_INDEX_EXCHANGE, US_INDEX_QUALITY_ENTITY, US_INDEXES, UsIndex
from .indicators import INDICATOR_VERSION, PRICE_BASIS, REQUIRED_BARS
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
        "foreign_indices": foreign_indices(db, as_of),
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
    rows = (
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
            # One more than the window: whether its first run started earlier.
            .limit(SEGMENT_SESSIONS + 1)
        ).all()
        if instrument is not None
        else []
    )
    if not rows:
        return {**base, "status": "unavailable", "reason": "not_collected"}
    latest = rows[0]
    if latest.trading_date != session:
        return {
            **base,
            "status": "unavailable",
            "reason": "row_date_mismatch",
            "latest_trading_date": latest.trading_date.isoformat(),
        }
    if latest.indicator_id is None:
        return {**base, "status": "unavailable", "reason": "indicator_not_computed"}
    if latest.ma60 is None:
        null_reason = (latest.null_reasons or {}).get("ma60")
        if null_reason == "insufficient_bars":
            return {
                **base,
                "status": "insufficient",
                "reason": "insufficient_closes",
                "close_count": latest.bar_count,
            }
        return {
            **base,
            "status": "unavailable",
            "reason": "ma60_unavailable",
            "null_reason": null_reason,
        }
    window = list(reversed(rows[:SEGMENT_SESSIONS]))
    earlier = rows[SEGMENT_SESSIONS] if len(rows) > SEGMENT_SESSIONS else None
    close, ma60 = latest.close, latest.ma60
    above = _above(close, ma60)
    return {
        **base,
        "status": "available",
        "close": close,
        "ma60": ma60,
        "above": above,
        "position": "above" if above else "equal" if close == ma60 else "below",
        "close_count": latest.bar_count,
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

# Quality rows read for closed (blank) FRED dates; each covers the ten days
# before its collect's newest stored row onward.
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
    """``latest``, ``us_market_closed`` (the expected day is a FRED blank and
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
        # Against the stored close before it (FRED has no change column).
        "change_pct_method": "derived",
        "previous_trading_date": previous.trading_date.isoformat()
        if previous
        else None,
        "source": {
            "label": f"FRED {series.series_id}",
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
