"""Daily/weekly K-line payload with technical indicators for one instrument.

Daily indicators are read from technical_indicators (written by the batch);
weekly bars are aggregated from the stored daily bars and their indicators are
recomputed on the weekly series with the same formulas (app.indicators).
"""

from __future__ import annotations

from datetime import timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from worker.indicator_batch import SOURCE as INDICATOR_SOURCE
from worker.indicator_batch import load_indicator_bars

from .indicators import (
    FIELDS,
    INDICATOR_VERSION,
    PARAMETERS,
    PRICE_BASIS,
    REQUIRED_BARS,
    aggregate_weekly,
    compute_indicators,
)
from .models import CorporateAction, Instrument, MarketBar, TechnicalIndicator

NOT_COMPUTED = "not_computed"
DEFAULT_LIMIT = 250
MAX_LIMIT = 1500


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _daily(
    db: Session, instrument: Instrument, limit: int
) -> tuple[list[dict[str, Any]], str | None]:
    bars = list(
        reversed(
            db.scalars(
                select(MarketBar)
                .where(MarketBar.instrument_id == instrument.id)
                .order_by(desc(MarketBar.trading_date))
                .limit(limit)
            ).all()
        )
    )
    if not bars:
        return [], None
    stored = {
        row.trading_date: row
        for row in db.scalars(
            select(TechnicalIndicator).where(
                TechnicalIndicator.instrument_id == instrument.id,
                TechnicalIndicator.formula_version == INDICATOR_VERSION,
                TechnicalIndicator.trading_date >= bars[0].trading_date,
                TechnicalIndicator.trading_date <= bars[-1].trading_date,
            )
        ).all()
    }
    computed_at = max((row.computed_at for row in stored.values()), default=None)
    items = []
    for bar in bars:
        row = stored.get(bar.trading_date)
        item: dict[str, Any] = {
            "date": bar.trading_date.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "source": bar.source,
            "is_suspended": bool(bar.is_suspended),
            "bar_count": row.bar_count if row else None,
        }
        for name in FIELDS:
            item[name] = getattr(row, name) if row else None
        item["reasons"] = (
            dict(row.null_reasons or {})
            if row
            else {name: NOT_COMPUTED for name in FIELDS}
        )
        items.append(item)
    # computed_at is UTC-naive (worker.indicator_batch); send it with its offset.
    if computed_at is not None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    return items, _iso(computed_at)


def _weekly(
    db: Session, instrument: Instrument, limit: int
) -> tuple[list[dict[str, Any]], list[str]]:
    has_actions = (
        db.scalar(
            select(CorporateAction.id)
            .where(CorporateAction.instrument_id == instrument.id)
            .limit(1)
        )
        is not None
    )
    daily = load_indicator_bars(db, instrument.id, None, with_actions=has_actions)
    weeks = aggregate_weekly(daily)
    points = compute_indicators(week.calc for week in weeks)
    week_sources: dict[tuple[int, int], set[str]] = {}
    for trading_date, source in db.execute(
        select(MarketBar.trading_date, MarketBar.source).where(
            MarketBar.instrument_id == instrument.id
        )
    ).all():
        week_sources.setdefault(trading_date.isocalendar()[:2], set()).add(source)
    items = []
    for week, point in list(zip(weeks, points))[-limit:]:
        item: dict[str, Any] = {
            "date": week.week_end.isoformat(),
            "week_start": week.week_start.isoformat(),
            "week_end": week.week_end.isoformat(),
            "trading_days": week.trading_days,
            "open": week.open,
            "high": week.high,
            "low": week.low,
            "close": week.close,
            "volume": week.volume,
            "sources": sorted(week_sources.get(week.week_end.isocalendar()[:2], ())),
            "bar_count": point.bar_count,
            **point.values,
            "reasons": dict(point.reasons),
        }
        items.append(item)
    return items, sorted({source for item in items for source in item["sources"]})


def build_stock_bars(
    db: Session, instrument: Instrument, *, interval: str, limit: int
) -> dict[str, Any]:
    if interval == "week":
        items, sources = _weekly(db, instrument, limit)
        computed_at = None
        indicator_source = f"{INDICATOR_SOURCE}:weekly_on_request"
    else:
        items, computed_at = _daily(db, instrument, limit)
        sources = sorted({item["source"] for item in items})
        indicator_source = f"{INDICATOR_SOURCE}:technical_indicators"
    return {
        "instrument": {
            "id": instrument.id,
            "exchange": instrument.exchange,
            "symbol": instrument.symbol,
            "name": instrument.name,
            "instrument_type": instrument.instrument_type,
        },
        "interval": interval,
        "limit": limit,
        "count": len(items),
        "data_as_of": items[-1]["date"] if items else None,
        "sources": sources,
        "indicators": {
            "formula_version": INDICATOR_VERSION,
            "price_basis": PRICE_BASIS,
            "parameters": PARAMETERS,
            "required_bars": REQUIRED_BARS,
            "fields": list(FIELDS),
            "source": indicator_source,
            "computed_at": computed_at,
        },
        "bars": items,
    }
