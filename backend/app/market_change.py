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


def _source_has_day(
    db: Session, source: str, day: date, sessions: dict[Any, Any]
) -> bool:
    """Whether ``source`` has a traded bar of any stock on ``day`` (cached in ``sessions``)."""

    key = ("source_day", source, day)
    if key not in sessions:
        sessions[key] = (
            db.scalar(
                select(MarketBar.id)
                .where(
                    MarketBar.source == source,
                    MarketBar.trading_date == day,
                    MarketBar.is_suspended.is_not(True),
                )
                .limit(1)
            )
            is not None
        )
    return sessions[key]


def no_close_status(
    db: Session,
    source: str | None,
    previous_day: date,
    listing_date: date | None,
    sessions: dict[Any, Any],
) -> str:
    """Why a stock has no traded close on ``previous_day``, the session before its bar.

    ``first_trading_day`` (#475): the master lists it after ``previous_day``,
    so the day is its first session and there was nothing to trade.
    ``no_previous_close`` (#465): ``source`` has traded bars of other stocks
    on ``previous_day``, so the day was collected, but none for this stock (no
    trade or suspended; the collector keeps no row without a close, and the
    page names no cause).  Otherwise the day may not be collected:
    ``unverified``.
    """

    if listing_date is not None and listing_date > previous_day:
        return "first_trading_day"
    if source and _source_has_day(db, source, previous_day, sessions):
        return "no_previous_close"
    return "unverified"


def adjacent_change(
    db: Session,
    instrument_id: int,
    trading_date: date,
    bar: MarketBar | None,
    sessions: dict[Any, Any],
    *,
    listing_date: date | None,
) -> dict[str, Any]:
    """The close of ``trading_date`` and its change.

    The change is ``known`` only against the stock's bar on the previous
    verified TAIEX session from the same source (UI_COPY_SPEC §8.2); a holiday
    gap, missing or suspended bar, or another source is ``unverified``.
    Without a traded close on the previous session the status says why
    (``no_close_status``: ``first_trading_day`` for a stock the master lists
    only from ``trading_date``, ``no_previous_close`` when the source has the
    day). No earlier close stands in: the exchange's reference price is not
    the last traded close.
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
    if previous is not None and previous.source != bar.source:
        return market
    if previous_close is None:
        market["change_status"] = no_close_status(
            db, bar.source, days[-2], listing_date, sessions
        )
        return market
    change = round(close - previous_close, 6)
    market.update(
        change=change,
        change_pct=change / previous_close,
        change_status="known",
    )
    return market
