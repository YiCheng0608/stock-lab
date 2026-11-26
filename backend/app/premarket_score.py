"""Scoring the pre-market AI readings against what happened (Issue #1043).

The rules are ``premarket_score_v1`` (docs/spec/premarket_ai.md 對答案), fixed
before the first reading was scored; any change is a new ``SCORE_VERSION``
(``RULES`` and the spec section are pinned by a snapshot test).  Pure
functions only: no database and no clock, so the tests can work every number
by hand.  ``worker.premarket_score`` loads the bars and writes the rows.

``reprice`` is the only computation of the levels "re-priced at the open":
the invalid price and the first target stay, the entry becomes D's open, and
the gap and the risk/reward are worked out from it.  Anything that shows a
re-priced level calls it instead of computing its own.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from datetime import date
from typing import Any, Iterable, Sequence

from .tracking import (
    ROUND_TRIP_TRANSACTION_COST_BPS,
    TRACKING_RULES_V2,
    TrackBar,
    TrackLevels,
    buy_fill_with_slippage,
    sell_fill_with_slippage,
)

SCORE_VERSION = "premarket_score_v1"
MARKET = "market"
STOCK = "stock"
OVERALL = "overall"
SCOPES = (MARKET, STOCK, OVERALL)
# Horizons: name -> the trading session it ends on (D is session 1).
MARKET_HORIZONS = {"d0": 1, "t5": 5}
STOCK_HORIZONS = {"t5": 5, "t20": 20}
# |return| at or inside the band is flat.
MARKET_FLAT_BAND = {"d0": 0.005, "t5": 0.015}
STANCE_REALIZED = {"bullish": "up", "bearish": "down", "neutral": "flat"}
KEEP = "keep"
REPRICE = "reprice"
DEFER = "defer"
ACTIONS = (KEEP, REPRICE, DEFER)
# The population: these instrument types (candidate_pool.INSTRUMENT_TYPES),
# listed and OTC, no liquidity floor.
POPULATION_TYPES = ("stock", "ipo")
# Done readings with fewer scored trading days are insufficient_sample.
REPORT_MIN_DAYS = 60
SHADOW_MIN_DAYS = 20
INSUFFICIENT_SAMPLE = "insufficient_sample"

# Reason codes.
NO_DATA = "no_data"
NO_SESSION = "no_session"
NO_OPEN = "no_open"
NO_CLOSE = "no_close"
MISSING_BAR = "missing_bar"
SUSPENDED_IN_WINDOW = "suspended_in_window"
NO_PRICE = "no_price"
NO_LIST = "no_list"
EMPTY_SIDE = "empty_side"
# Re-pricing: the conditions, in the order they are checked.
OPEN_AT_OR_BELOW_INVALID = "open_at_or_below_invalid"
OPEN_AT_OR_ABOVE_TARGET = "open_at_or_above_target"
GAP_UP_OVER_MAX = "gap_up_over_max"
GAP_DOWN_OVER_MAX = "gap_down_over_max"
RISK_REWARD_UNDER_MIN = "risk_reward_under_min"
NO_PREVIOUS_CLOSE = "no_previous_close"
REPRICED = "repriced"
REPRICE_DEFERRED = "reprice_deferred"
BREAKOUT_EPSILON = 1e-9

# Everything a score depends on.  The snapshot test pins this dict and the
# spec section for SCORE_VERSION: a change without a new version fails it.
RULES: dict[str, Any] = {
    "score_version": SCORE_VERSION,
    "readings": "done reading of each session_date + prompt_version + role",
    "sessions": "worker.pipeline.taiwan_bar_dates after list_date; D is session 1",
    "market_horizons": MARKET_HORIZONS,
    "market_flat_band": MARKET_FLAT_BAND,
    "market_price": "TAIEX daily K: D open to the close of the horizon session",
    "market_open_missing": "open null, price_reason set or source twse_index -> no_data",
    "stance_realized": STANCE_REALIZED,
    "stock_horizons": STOCK_HORIZONS,
    "open_hold": "buy D open +5 bps, sell T+N close -5 bps, minus 30 bps; factor to list_date basis",
    "open_hold_incomparable": [MISSING_BAR, SUSPENDED_IN_WINDOW, NO_PRICE],
    "levels_rules": TRACKING_RULES_V2,
    "levels_original": "levels_json as the input had them; breakout at entry_zone.low",
    "reprice": "invalid_price and target_1 stay; entry = D open; gap vs list_date close; rr = (target_1 - O) / (O - invalid_price)",
    "reprice_conditions": [
        OPEN_AT_OR_BELOW_INVALID,
        OPEN_AT_OR_ABOVE_TARGET,
        GAP_UP_OVER_MAX,
        GAP_DOWN_OVER_MAX,
        RISK_REWARD_UNDER_MIN,
    ],
    "effective_action": "keep; reprice not deferred; defer and reprice_deferred are defer",
    "population": "stock/ipo with a D bar not suspended; equal-weight open_hold; no liquidity floor",
    "ai_version": "effective keep/reprice, open_hold, equal weight",
    "rule_version": "on_today_list, open_hold, equal weight; no stock -> no_list",
    "excess": "version mean - population mean (open_hold only)",
    "value_open_hold": "effective keep/reprice mean - effective defer mean, whole pool (the D switch condition, t5)",
    "value_levels": "keep original + reprice repriced mean - defer/reprice_deferred original mean, today list only (reference)",
    "write": "a horizon is written once its session exists, never rewritten",
    "cost_bps": ROUND_TRIP_TRANSACTION_COST_BPS,
    "report_min_days": REPORT_MIN_DAYS,
    "shadow_min_days": SHADOW_MIN_DAYS,
}


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 8)


# --- market ---------------------------------------------------------------------------


def realized_direction(change: float, band: float) -> str:
    if abs(change) <= band:
        return "flat"
    return "up" if change > 0 else "down"


def market_outcome(
    stance: str | None,
    confidence: str | None,
    horizon: str,
    open_price: float | None,
    close_price: float | None,
    close_date: date | None,
    *,
    missing: str | None = None,
) -> dict[str, Any]:
    """The reading's market stance against TAIEX from D's open."""

    band = MARKET_FLAT_BAND[horizon]
    out: dict[str, Any] = {
        "stance": stance,
        "confidence": confidence,
        "open": open_price,
        "close": close_price,
        "close_date": close_date.isoformat() if close_date else None,
        "band": band,
        "return": None,
        "realized": None,
        "hit": None,
        "status": "scored",
        "reason": None,
    }
    opened = _finite(open_price)
    closed = _finite(close_price)
    if missing is None and (opened is None or opened <= 0):
        missing = NO_OPEN
    if missing is None and (closed is None or closed <= 0):
        missing = NO_CLOSE
    if missing is not None:
        out.update(status=NO_DATA, reason=missing)
        return out
    change = closed / opened - 1.0
    realized = realized_direction(change, band)
    out.update(
        **{
            "return": _round(change),
            "realized": realized,
            "hit": STANCE_REALIZED.get(stance or "") == realized,
        }
    )
    return out


# --- one stock ------------------------------------------------------------------------


def open_hold(
    tracked: Sequence[TrackBar], sessions: Sequence[date], horizon: int
) -> dict[str, Any]:
    """D's open to the close of session ``horizon``, net of slippage and cost.

    ``tracked`` are the stock's bars after the list date with their factors
    (``pipeline._tracking_inputs``); ``sessions`` the market sessions from D.
    The stock needs a bar on each of the first ``horizon`` sessions, none
    suspended.
    """

    out: dict[str, Any] = {
        "status": "comparable",
        "reason": None,
        "entry_date": sessions[0].isoformat() if sessions else None,
        "exit_date": sessions[horizon - 1].isoformat()
        if len(sessions) >= horizon
        else None,
        "entry_price": None,
        "exit_price": None,
        "return": None,
    }
    window = list(tracked[:horizon])
    if len(sessions) < horizon or [bar.trading_date for bar in window] != list(
        sessions[:horizon]
    ):
        out.update(status="incomparable", reason=MISSING_BAR)
        return out
    if any(suspended(bar) for bar in window):
        out.update(status="incomparable", reason=SUSPENDED_IN_WINDOW)
        return out
    first, last = window[0], window[-1]
    entry_raw = buy_fill_with_slippage(_finite(first.open))
    exit_raw = sell_fill_with_slippage(_finite(last.close))
    if entry_raw is None or exit_raw is None or not first.factor or not last.factor:
        out.update(status="incomparable", reason=NO_PRICE)
        return out
    entry = entry_raw / first.factor
    exit_ = exit_raw / last.factor
    out.update(
        entry_price=_round(entry),
        exit_price=_round(exit_),
        **{
            "return": _round(
                exit_ / entry - 1.0 - ROUND_TRIP_TRANSACTION_COST_BPS / 10_000.0
            )
        },
    )
    return out


def suspended(bar: TrackBar) -> bool:
    """``app.tracking``'s suspended session."""

    return bool(
        bar.is_suspended
        or (bar.volume == 0 and bar.open == bar.high == bar.low == bar.close)
        or bar.suspension_gap
    )


def has_levels(levels: dict[str, Any] | None) -> bool:
    if not levels or levels.get("status") == "no_levels":
        return False
    zone = levels.get("entry_zone") or {}
    return (
        levels.get("entry_type") in {"breakout", "pullback"}
        and _finite(zone.get("low")) is not None
        and _finite(zone.get("high")) is not None
    )


def original_levels(levels: dict[str, Any]) -> TrackLevels:
    """The rule levels of ``levels_json`` as ``app.tracking`` tracks them."""

    zone = levels.get("entry_zone") or {}
    breakout = levels.get("entry_type") == "breakout"
    return TrackLevels(
        entry_type=levels["entry_type"],
        breakout_price=_finite(zone.get("low")) if breakout else None,
        pullback_low=None if breakout else _finite(zone.get("low")),
        pullback_high=None if breakout else _finite(zone.get("high")),
        invalid_price=_finite(levels.get("invalid_price")),
        target_1=_finite(levels.get("target_1")),
    )


def reprice(
    levels: dict[str, Any],
    rule: dict[str, Any] | None,
    open_price: float | None,
    previous_close: float | None,
) -> dict[str, Any]:
    """The levels re-priced at D's open, and whether the reading's rule defers them.

    All prices on the list date's basis (D's raw open divided by its
    corporate-action factor).  The invalid price and the first target stay;
    the entry is the open, ``gap = open / previous_close - 1`` and
    ``risk_reward = (target_1 - open) / (open - invalid_price)``.  Deferred
    when any condition of ``RULES['reprice_conditions']`` holds (all of them
    are listed, ``reason`` is the first).
    """

    rule = rule or {}
    opened = _finite(open_price)
    previous = _finite(previous_close)
    invalid = _finite(levels.get("invalid_price"))
    target = _finite(levels.get("target_1"))
    out: dict[str, Any] = {
        "status": REPRICED,
        "reason": None,
        "conditions": [],
        "entry": _round(opened),
        "invalid_price": invalid,
        "target_1": target,
        "previous_close": previous,
        "gap": None,
        "stop_distance": None,
        "risk_reward": None,
        "rule": {
            "max_gap_pct": rule.get("max_gap_pct"),
            "max_gap_down_pct": rule.get("max_gap_down_pct"),
            "min_risk_reward": rule.get("min_risk_reward"),
        },
    }
    if opened is None or opened <= 0:
        out.update(status=NO_DATA, reason=NO_OPEN)
        return out
    if previous is None or previous <= 0:
        out.update(status=NO_DATA, reason=NO_PREVIOUS_CLOSE)
        return out
    if invalid is None or target is None:
        out.update(status=NO_DATA, reason=NO_PRICE)
        return out
    gap = opened / previous - 1.0
    out["gap"] = _round(gap)
    conditions: list[str] = []
    if opened <= invalid:
        conditions.append(OPEN_AT_OR_BELOW_INVALID)
    else:
        out["stop_distance"] = _round(opened - invalid)
        out["risk_reward"] = _round((target - opened) / (opened - invalid))
    if opened >= target:
        conditions.append(OPEN_AT_OR_ABOVE_TARGET)
    max_up = _finite(rule.get("max_gap_pct"))
    if max_up is not None and gap > max_up:
        conditions.append(GAP_UP_OVER_MAX)
    max_down = _finite(rule.get("max_gap_down_pct"))
    if max_down is not None and -gap > max_down:
        conditions.append(GAP_DOWN_OVER_MAX)
    min_rr = _finite(rule.get("min_risk_reward"))
    if (
        min_rr is not None
        and out["risk_reward"] is not None
        and out["risk_reward"] < min_rr
    ):
        conditions.append(RISK_REWARD_UNDER_MIN)
    if conditions:
        out.update(status=REPRICE_DEFERRED, reason=conditions[0], conditions=conditions)
    return out


def repriced_levels(repriced: dict[str, Any]) -> TrackLevels:
    """The re-priced levels as ``app.tracking`` tracks them: a fill at D's open.

    A breakout at the open fills at the open (``max(open, breakout)``); the
    trigger sits a hair under it so that mapping it back to the raw basis
    (``* factor``) cannot round above the open and miss the fill.
    """

    return TrackLevels(
        entry_type="breakout",
        breakout_price=repriced["entry"] * (1.0 - BREAKOUT_EPSILON),
        pullback_low=None,
        pullback_high=None,
        invalid_price=repriced["invalid_price"],
        target_1=repriced["target_1"],
    )


def effective_action(action: str, repriced: dict[str, Any] | None) -> str:
    if (
        action == REPRICE
        and repriced is not None
        and repriced["status"] == REPRICE_DEFERRED
    ):
        return DEFER
    return action


def settled(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """The parts of ``app.tracking.settle`` a score keeps, JSON-ready."""

    if result is None:
        return None

    def iso(value: Any) -> Any:
        return value.isoformat() if isinstance(value, date) else value

    return {
        "status": "comparable" if result["comparable"] else "incomparable",
        "reason": result["incomparable_reason"],
        "final_status": result["final_status"],
        "first_trigger": result["first_trigger"],
        "return": _round(result["return_or_risk"]),
        "execution_date": iso(result["execution_date"]),
        "execution_price": result["execution_price"],
        "settlement_date": iso(result["settlement_date"]),
        "tracking_rules": result["tracking_rules"],
    }


# --- overall --------------------------------------------------------------------------


def summary(results: Iterable[dict[str, Any] | None]) -> dict[str, Any]:
    """Count, comparable count, fills, mean and median of scored results."""

    rows = [row for row in results if row is not None]
    values = [row["return"] for row in rows if row.get("status") == "comparable"]
    values = [value for value in values if value is not None]
    reasons = Counter(
        row.get("reason") or "unknown"
        for row in rows
        if row.get("status") != "comparable"
    )
    out: dict[str, Any] = {
        "n": len(rows),
        "comparable": len(values),
        "mean": _round(statistics.fmean(values)) if values else None,
        "median": _round(statistics.median(values)) if values else None,
        "incomparable": dict(sorted(reasons.items())),
    }
    if any("execution_date" in row for row in rows):
        out["filled"] = sum(1 for row in rows if row.get("execution_date"))
    return out


def difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return _round(left - right)


def overall_outcome(
    stocks: Sequence[dict[str, Any]],
    population: dict[str, Any],
    *,
    pool_phase: str | None,
    today_list_count: int | None,
) -> dict[str, Any]:
    """The reading's versions against the population and the AI's value.

    ``stocks`` are the stock outcomes of one horizon (``stock_outcome``'s
    dicts).  The versions and the open_hold value compare D-open holds; the
    levels value compares tracking_v2 results of the today list.
    """

    def holds(rows):
        return summary(row["open_hold"] for row in rows)

    ai_rows = [row for row in stocks if row["effective_action"] in {KEEP, REPRICE}]
    defer_rows = [row for row in stocks if row["effective_action"] == DEFER]
    list_rows = [row for row in stocks if row["on_today_list"]]
    population_mean = population.get("mean")
    ai_version = holds(ai_rows)
    ai_version["excess"] = difference(ai_version["mean"], population_mean)
    if list_rows:
        rule_version: dict[str, Any] = holds(list_rows)
        rule_version["excess"] = difference(rule_version["mean"], population_mean)
        rule_version["status"] = "scored"
    else:
        rule_version = {"status": NO_LIST, "n": 0, "mean": None, "excess": None}
    defer_hold = holds(defer_rows)
    value_hold = difference(ai_version["mean"], defer_hold["mean"])

    levelled = [row for row in stocks if row.get("levels") is not None]
    ai_levels = []
    defer_levels = []
    for row in levelled:
        if row["effective_action"] == KEEP:
            ai_levels.append(row["levels"]["original"])
        elif row["effective_action"] == REPRICE:
            ai_levels.append(row["levels"].get("repriced_result"))
        else:
            defer_levels.append(row["levels"]["original"])
    ai_level_summary = summary(ai_levels)
    defer_level_summary = summary(defer_levels)
    by_action = {
        action: {
            "open_hold": holds(
                [row for row in stocks if row["effective_action"] == action]
            )
        }
        for action in ACTIONS
    }
    return {
        "pool_phase": pool_phase,
        "today_list_count": today_list_count,
        "population": population,
        "ai_version": ai_version,
        "rule_version": rule_version,
        "defer": defer_hold,
        "by_effective_action": by_action,
        "value_open_hold": {
            "value": value_hold,
            "reason": None if value_hold is not None else EMPTY_SIDE,
        },
        "levels": {
            "ai": ai_level_summary,
            "defer": defer_level_summary,
            "value": difference(ai_level_summary["mean"], defer_level_summary["mean"]),
            "reason": None
            if ai_level_summary["mean"] is not None
            and defer_level_summary["mean"] is not None
            else EMPTY_SIDE,
        },
    }
