"""A stock's close on a trading date and its change from the previous session.

Shared by the candidate ``market`` (#276) and the theme member table (#280) so
both pages show the same change for the same stock and day.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .coverage import verified_taiex_sessions
from .models import MarketBar


def traded_close(bar: MarketBar | None) -> float | None:
    if bar is None or bar.is_suspended:
        return None
    close = bar.close
    return close if close is not None and math.isfinite(close) and close > 0 else None


def adjacent_change(
    db: Session,
    instrument_id: int,
    trading_date: date,
    bar: MarketBar | None,
    sessions: dict[date, list[date]],
) -> dict[str, Any]:
    """The close of ``trading_date`` and its change.

    The change is ``known`` only against the stock's bar on the previous
    verified TAIEX session from the same source (UI_COPY_SPEC §8.2); a holiday
    gap, missing or suspended bar, or another source is ``unverified``.
    ``missing`` means no traded bar on the day. ``sessions`` caches the TAIEX
    lookup across the stocks of one response.
    """

    close = traded_close(bar)
    market: dict[str, Any] = {
        "trading_date": trading_date.isoformat(),
        "close": close,
        "change": None,
        "change_pct": None,
        "change_status": "missing" if close is None else "unverified",
        "source": bar.source if bar is not None else None,
    }
    if close is None:
        return market
    if trading_date not in sessions:
        sessions[trading_date] = verified_taiex_sessions(
            db, end_date=trading_date, limit=2
        )
    days = sessions[trading_date]
    if len(days) < 2 or days[-1] != trading_date:
        return market
    previous = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument_id,
            MarketBar.trading_date == days[-2],
        )
    )
    previous_close = traded_close(previous)
    if previous_close is None or previous.source != bar.source:
        return market
    change = round(close - previous_close, 6)
    market.update(
        change=change,
        change_pct=change / previous_close,
        change_status="known",
    )
    return market
