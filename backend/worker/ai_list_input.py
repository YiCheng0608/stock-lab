"""The input of the AI list (Issue #1145, docs/spec/ai_list.md).

``premarket_input.build`` (the same snapshot as ``premarket_v1``: nothing after D
08:15, the candidate pool and its news), plus each candidate's ``level_facts``
(``ai_list_facts_v1``, #1142 2/4 「輸入要補的事實」): the price facts the AI's
levels must cite, all on the list date T and before, nothing of D.

- **Basis**: T's raw prices.  A bar before a corporate action inside the window
  is put on T's basis with the factor ``pipeline._corporate_action_factor`` gives
  the tracking (the actions after the bar through T; without an official
  reference price, the close before the action).  ``corporate_action_in_window``
  marks a window with one; ``corporate_action_on_session`` an action dated after
  T through D (D's limits then differ from the ones here).
- **Facts**: ``ma5``/``ma10``/``ma20``/``ma60`` of the closes; ``high_20``,
  ``low_20``, ``high_60``, ``low_60`` (high or low, else close) with their dates;
  ``atr14``, the simple mean of 14 true ranges; ``volume_node_60``, the band of
  the 60-bar range cut in VOLUME_BINS with the most volume, each bar's volume put
  at its typical price (H+L+C)/3; D's ``limit_up``/``limit_down``
  (``levels.price_limits``, null for an ETF) and ``tick`` at T's close on D's
  ladder, with ``instrument_type`` (the ladder's kind).  A fact without enough bars is null; a stock without T's bar is
  ``{"status": "missing"}`` and cannot be picked.

The previous AI list is not given (#1142 2/4 Q2-1 A): each day is read on its own.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CorporateAction, Instrument, MarketBar
from app.strategies import levels as lv

from . import premarket_input
from .pipeline import _corporate_action_factor
from .premarket_input import Snapshot

FACT_VERSION = "ai_list_facts_v1"
BARS = 61  # T and the 60 sessions before it (ATR needs one before its 14)
VOLUME_BINS = 20
MA_WINDOWS = (5, 10, 20, 60)
EXTREME_WINDOWS = (20, 60)
ATR_WINDOW = 14
NODE_WINDOW = 60
# The price fields a level may cite as its base (refs[0]): the list date's bar and
# the price facts.  Not the moves, ratios or lots.
PRICE_FIELDS = ("open", "high", "low", "close")
FACT_PRICE_FIELDS = (
    "close",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "high_20",
    "low_20",
    "high_60",
    "low_60",
    "volume_node_60.low",
    "volume_node_60.high",
    "limit_up",
    "limit_down",
)


def _r(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


class _Bar:
    """One bar on T's basis (newest first in a window)."""

    __slots__ = ("day", "high", "low", "close", "volume")

    def __init__(self, bar: MarketBar, factor: float) -> None:
        close = bar.close
        self.day = bar.trading_date
        self.close = close * factor
        self.high = (bar.high if bar.high is not None else close) * factor
        self.low = (bar.low if bar.low is not None else close) * factor
        self.volume = bar.volume or 0


def rebased(
    raw: list[MarketBar], actions: list[CorporateAction]
) -> tuple[list[_Bar], bool]:
    """RAW (newest first, T first) on T's basis, and whether an action applied."""

    fallback: dict[date, float] = {}
    for action in actions:
        if action.reference_price is None:
            before = next(
                (bar for bar in raw if bar.trading_date < action.action_date), None
            )
            if before is not None and before.close and before.close > 0:
                fallback[action.action_date] = before.close
    out: list[_Bar] = []
    applied = False
    for bar in raw:
        later = [action for action in actions if action.action_date > bar.trading_date]
        factor, own = (
            _corporate_action_factor(later, fallback_reference_prices=fallback)
            if later
            else (1.0, False)
        )
        applied = applied or own
        out.append(_Bar(bar, factor))
    return out, applied


def moving_average(bars: list[_Bar], window: int) -> float | None:
    if len(bars) < window:
        return None
    return _r(sum(bar.close for bar in bars[:window]) / window)


def extreme(bars: list[_Bar], window: int, kind: str) -> dict[str, Any] | None:
    if len(bars) < window:
        return None
    part = bars[:window]
    # The latest bar of an equal extreme: max/min keep the first, the newest.
    bar = (
        max(part, key=lambda b: b.high)
        if kind == "high"
        else min(part, key=lambda b: b.low)
    )
    return {
        "price": _r(bar.high if kind == "high" else bar.low),
        "date": bar.day.isoformat(),
    }


def atr(bars: list[_Bar], window: int = ATR_WINDOW) -> float | None:
    """The simple mean of the last WINDOW true ranges (each needs the close before)."""

    if len(bars) < window + 1:
        return None
    ranges = []
    for index in range(window):
        bar, previous = bars[index], bars[index + 1]
        ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous.close),
                abs(bar.low - previous.close),
            )
        )
    return _r(sum(ranges) / window, 3)


def volume_node(bars: list[_Bar], window: int = NODE_WINDOW) -> dict[str, Any] | None:
    if len(bars) < window:
        return None
    part = bars[:window]
    low = min(bar.low for bar in part)
    high = max(bar.high for bar in part)
    if high <= low:
        return None
    step = (high - low) / VOLUME_BINS
    sums = [0] * VOLUME_BINS
    for bar in part:
        typical = (bar.high + bar.low + bar.close) / 3
        sums[min(int((typical - low) / step), VOLUME_BINS - 1)] += bar.volume
    best = max(range(VOLUME_BINS), key=lambda index: sums[index])
    total = sum(sums) or 1
    return {
        "low": _r(low + best * step),
        "high": _r(low + (best + 1) * step),
        "share": round(sums[best] / total, 3),
        "window": window,
    }


def level_facts(
    db: Session, instrument: Instrument, list_date: date, session_date: date
) -> dict[str, Any]:
    """The price facts of INSTRUMENT on LIST_DATE for the session SESSION_DATE."""

    raw = list(
        db.scalars(
            select(MarketBar)
            .where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date <= list_date,
            )
            .order_by(desc(MarketBar.trading_date))
            .limit(BARS)
        )
    )
    if not raw or raw[0].trading_date != list_date or not raw[0].close:
        return {"status": "missing"}
    actions = list(
        db.scalars(
            select(CorporateAction).where(
                CorporateAction.instrument_id == instrument.id,
                CorporateAction.action_date > raw[-1].trading_date,
                CorporateAction.action_date <= session_date,
            )
        )
    )
    in_window = [action for action in actions if action.action_date <= list_date]
    bars, _applied = rebased(raw, in_window)
    close = raw[0].close
    kind = instrument.instrument_type or "stock"
    inputs = SimpleNamespace(
        instrument_type=kind,
        close=close,
        exchange=instrument.exchange,
        next_session_date=session_date,
    )
    limits = lv.price_limits(inputs)
    _upper, tick = lv._band(
        lv._price(close), lv._ladder(kind, instrument.exchange, session_date)
    )
    facts: dict[str, Any] = {
        "version": FACT_VERSION,
        "basis": "list_date_raw",
        "as_of": list_date.isoformat(),
        "instrument_type": kind,
        "close": close,
    }
    for window in MA_WINDOWS:
        facts[f"ma{window}"] = moving_average(bars, window)
    for window in EXTREME_WINDOWS:
        facts[f"high_{window}"] = extreme(bars, window, "high")
        facts[f"low_{window}"] = extreme(bars, window, "low")
    facts["atr14"] = atr(bars)
    facts["volume_node_60"] = volume_node(bars)
    facts["limit_up"] = limits[1] if limits else None
    facts["limit_down"] = limits[0] if limits else None
    facts["tick"] = float(tick)
    facts["corporate_action_in_window"] = bool(in_window)
    facts["corporate_action_on_session"] = len(actions) > len(in_window)
    return facts


def build(
    db: Session, session_date: date, list_date: date, assembled_at: datetime
) -> Snapshot:
    """``premarket_input.build`` with each candidate's ``level_facts``."""

    snapshot = premarket_input.build(db, session_date, list_date, assembled_at)
    by_symbol = {meta.symbol: meta.instrument_id for meta in snapshot.stocks}
    for item in snapshot.payload["candidates"]:
        instrument = db.get(Instrument, by_symbol[item["symbol"]])
        item["level_facts"] = level_facts(db, instrument, list_date, session_date)
    snapshot.payload["level_facts_version"] = FACT_VERSION
    return snapshot


def facts_value(item: dict[str, Any], field: str) -> float | None:
    """The number of a price field FIELD of a candidate ITEM, or None.

    FIELD is one of PRICE_FIELDS (the list date's bar) or FACT_PRICE_FIELDS; a fact
    that is ``{"price", "date"}`` gives its price.  ``close`` is the same in both.
    """

    if field in FACT_PRICE_FIELDS:
        value: Any = item.get("level_facts") or {}
        for key in field.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, dict):
            value = value.get("price")
    elif field in PRICE_FIELDS:
        value = (item.get("price") or {}).get(field)
    else:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
