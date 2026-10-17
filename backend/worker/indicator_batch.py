"""Daily batch: derive scalar technical indicators from stored daily bars.

The default (daily) mode writes, per instrument, every bar date after the last
stored row of the current formula version, which is normally just the latest
session.  When the recomputed value for that last stored row no longer matches
(an earlier bar was backfilled or corrected, or a corporate action arrived
late), the instrument's rows are rewritten.  ``rebuild=True`` rewrites every
instrument's full history.  Formulas live in app.indicators.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, insert, inspect, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.indicators import (
    FIELDS,
    INDICATOR_VERSION,
    PRICE_BASIS,
    IndicatorBar,
    IndicatorPoint,
    compute_indicators,
)
from app.models import CorporateAction, Instrument, MarketBar, TechnicalIndicator

from .pipeline import _action_factor_by_bar

SOURCE = "derived:market_bars"


def load_indicator_bars(
    db: Session, instrument_id: int, as_of: date | None, *, with_actions: bool = True
) -> list[IndicatorBar]:
    """Stored daily bars up to ``as_of`` with the corporate-action factor of each date."""
    bars = db.execute(
        select(
            MarketBar.trading_date,
            MarketBar.open,
            MarketBar.high,
            MarketBar.low,
            MarketBar.close,
            MarketBar.volume,
            MarketBar.is_suspended,
        )
        .where(
            MarketBar.instrument_id == instrument_id,
            *([MarketBar.trading_date <= as_of] if as_of is not None else []),
        )
        .order_by(MarketBar.trading_date)
    ).all()
    factors = (
        _action_factor_by_bar(db, instrument_id, bars)
        if with_actions and bars
        else [1.0] * len(bars)
    )
    return [
        IndicatorBar(
            bar.trading_date,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bool(bar.is_suspended),
            factor,
        )
        for bar, factor in zip(bars, factors)
    ]


def _row(
    instrument_id: int, point: IndicatorPoint, computed_at: datetime
) -> dict[str, Any]:
    return {
        "instrument_id": instrument_id,
        "trading_date": point.trading_date,
        "formula_version": INDICATOR_VERSION,
        "price_basis": PRICE_BASIS,
        "bar_count": point.bar_count,
        **point.values,
        "null_reasons": point.reasons,
        "source": SOURCE,
        "computed_at": computed_at,
    }


def _same(stored: TechnicalIndicator, point: IndicatorPoint) -> bool:
    if (
        stored.bar_count != point.bar_count
        or (stored.null_reasons or {}) != point.reasons
    ):
        return False
    for name in FIELDS:
        old, new = getattr(stored, name), point.values[name]
        if (old is None) != (new is None):
            return False
        if old is not None and not math.isclose(old, new, rel_tol=1e-9, abs_tol=1e-9):
            return False
    return True


def compute_market_indicators(
    db: Session, *, as_of: date | None = None, rebuild: bool = False
) -> dict[str, Any]:
    """Compute and stage indicator rows in the caller's transaction."""
    started = time.perf_counter()
    if as_of is None:
        as_of = db.scalar(select(func.max(MarketBar.trading_date)))
        if as_of is None:
            return {
                "status": "no_data",
                "formula_version": INDICATOR_VERSION,
                "rows_written": 0,
            }
    instrument_ids = db.scalars(
        select(Instrument.id)
        .where(Instrument.status == "active")
        .order_by(Instrument.id)
    ).all()
    with_actions = set(
        db.scalars(
            select(CorporateAction.instrument_id)
            .where(CorporateAction.action_date <= as_of)
            .distinct()
        ).all()
    )
    computed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    written = rewritten = latest_day_rows = 0
    for instrument_id in instrument_ids:
        bars = load_indicator_bars(
            db, instrument_id, as_of, with_actions=instrument_id in with_actions
        )
        if not bars:
            continue
        stored = (
            None
            if rebuild
            else db.scalar(
                select(TechnicalIndicator)
                .where(
                    TechnicalIndicator.instrument_id == instrument_id,
                    TechnicalIndicator.formula_version == INDICATOR_VERSION,
                    TechnicalIndicator.trading_date <= as_of,
                )
                .order_by(TechnicalIndicator.trading_date.desc())
                .limit(1)
            )
        )
        points = compute_indicators(
            bars, since=stored.trading_date if stored is not None else None
        )
        if (
            stored is not None
            and points
            and points[0].trading_date == stored.trading_date
            and _same(stored, points[0])
        ):
            fresh = points[1:]
        else:
            if stored is not None:
                points = compute_indicators(bars)
            if rebuild or stored is not None:
                db.execute(
                    delete(TechnicalIndicator).where(
                        TechnicalIndicator.instrument_id == instrument_id,
                        TechnicalIndicator.formula_version == INDICATOR_VERSION,
                        TechnicalIndicator.trading_date <= as_of,
                    )
                )
                rewritten += stored is not None
            fresh = points
        if fresh:
            db.execute(
                insert(TechnicalIndicator),
                [_row(instrument_id, point, computed_at) for point in fresh],
            )
            written += len(fresh)
            latest_day_rows += fresh[-1].trading_date == as_of
    return {
        "status": "success",
        "date": as_of.isoformat(),
        "formula_version": INDICATOR_VERSION,
        "mode": "rebuild" if rebuild else "daily",
        "instruments": len(instrument_ids),
        "latest_day_rows": latest_day_rows,
        "instruments_rewritten": rewritten,
        "rows_written": written,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def run_indicator_batch(
    as_of: date | None = None, *, rebuild: bool = False
) -> dict[str, Any]:
    # No init_db here: run_daily has already migrated, and on a multi-year DB
    # its integrity checks cost more than the batch itself.  Run init-db first
    # when the table is missing.
    with SessionLocal() as db:
        if not inspect(db.get_bind()).has_table(TechnicalIndicator.__tablename__):
            return {
                "status": "failed",
                "reason": "technical_indicators_table_missing_run_init_db",
                "formula_version": INDICATOR_VERSION,
                "rows_written": 0,
            }
        result = compute_market_indicators(db, as_of=as_of, rebuild=rebuild)
        db.commit()
        return result
