"""``dashboard.market_overview``: stored market summaries of the dashboard date.

Only reads ``market_summaries`` written by collect and ``worker.cli
market-summary`` (Issue #275).  Each exchange is shown for ``dashboard.as_of``
alone; a row of another date is never shown in its place.

``foreign_indices`` (Issue #547) reads the FRED closes of the ``US`` index
instruments (``worker.us_index_bars``) and their ``data_quality`` rows: the
newest close of each, its change from the stored close before it, and whether
it is the expected US session (the weekday before the dashboard date).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .clock import utcnow
from .domain import US_INDEX_EXCHANGE, US_INDEX_QUALITY_ENTITY, US_INDEXES, UsIndex
from .models import DataQuality, Instrument, MarketBar, MarketSummary

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
        "foreign_indices": foreign_indices(db, as_of),
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
