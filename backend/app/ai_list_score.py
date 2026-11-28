"""Scoring the AI list against what happened (Issue #1147).

The rules are ``ai_list_score_v1`` (docs/spec/ai_list.md 對答案), fixed before
the first reading was scored; any change is a new ``SCORE_VERSION`` (``RULES``
and the spec section are pinned by a snapshot test).  Pure functions only: no
database and no clock, so the tests can work every number by hand.
``worker.ai_list_score`` loads the bars and writes the rows;
``worker.ai_list_score_report`` groups them by the reading's method.

The returns, the population and the market stance are ``premarket_score_v1``'s
own functions (``app.premarket_score``), called and not copied, so the two
versions cannot drift apart; nothing of ``premarket_score_v1`` is changed.

``open_check`` is the only computation of 今日不適用 on the official daily K
(#1142 2/4 開盤後檢查, #1147 決定 7238340331): the page's evening mark (#1148)
calls it too.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Iterable, Sequence

from . import premarket_score as v1
from .tracking import (
    EXECUTION_SLIPPAGE_BPS,
    ROUND_TRIP_TRANSACTION_COST_BPS,
    TRACKING_RULES_V2,
    TRACKING_WINDOW_SESSIONS,
    TrackLevels,
)

SCORE_VERSION = "ai_list_score_v1"
MARKET, STOCK, OVERALL = v1.MARKET, v1.STOCK, v1.OVERALL
SCOPES = (MARKET, STOCK, OVERALL)
MARKET_HORIZONS = v1.MARKET_HORIZONS
STOCK_HORIZONS = v1.STOCK_HORIZONS
# The horizon the method groups read ai_levels at (the tracking window's end).
LEVELS_HORIZON = "t20"
# A group with fewer comparable results is 樣本不足: counts only (#1142 3/4 Q3-4 A).
MIN_GROUP_COMPARABLE = 20
INSUFFICIENT_SAMPLE = "insufficient_sample"

# Reason codes of a pick without a result of a kind.
LEVELS_CHECK_FAILED = "levels_check_failed"
NO_RULE_LEVELS = "no_rule_levels"
NO_LIST = v1.NO_LIST
EMPTY_SIDE = v1.EMPTY_SIDE
NO_DATA = v1.NO_DATA
NO_OPEN = v1.NO_OPEN
# 今日不適用 (#1142 2/4): the conditions, in the order they are checked.
OPEN_AT_OR_BELOW_STOP = "open_at_or_below_stop"
OPEN_AT_OR_ABOVE_TARGET = "open_at_or_above_target"
GAP_ABOVE_ENTRY_HIGH = "gap_above_entry_high"
OPEN_CHECK_CONDITIONS = (
    OPEN_AT_OR_BELOW_STOP,
    OPEN_AT_OR_ABOVE_TARGET,
    GAP_ABOVE_ENTRY_HIGH,
)
# tracking_v2's first trigger of a comparable result; None is neither.
TARGET_HIT = "target_1_hit"
STOP_HIT = "invalidated"
TRIGGERS = (TARGET_HIT, STOP_HIT, None)

# Everything a score depends on.  The snapshot test pins this dict and the
# spec section for SCORE_VERSION: a change without a new version fails it.
RULES: dict[str, Any] = {
    "score_version": SCORE_VERSION,
    "readings": "done ai_list_readings of each session_date + prompt_version + role",
    "sessions": "worker.pipeline.taiwan_bar_dates after list_date; D is session 1",
    "closed_d": "premarket_score_v1: a confirmed closure is no_session, else wait",
    "market_horizons": MARKET_HORIZONS,
    "market_flat_band": v1.MARKET_FLAT_BAND,
    "market": "premarket_score_v1 market_outcome; basis = market_method_json",
    "stock_horizons": STOCK_HORIZONS,
    "open_hold": "premarket_score_v1 open_hold, every pick (levels passed or not)",
    "open_hold_excess": "pick open_hold return - population mean of the reading and horizon",
    "ai_levels": "display_levels_json (levels passed): tracking_v2 track_path + settle; breakout at entry.low, pullback entry.low..high, invalid = stop, target_1",
    "ai_levels_missing": LEVELS_CHECK_FAILED,
    "rule_levels": "rule_levels_json with premarket_score_v1 has_levels: original_levels, tracking_v2",
    "rule_levels_missing": NO_RULE_LEVELS,
    "levels_window": TRACKING_WINDOW_SESSIONS,
    "levels_rules": TRACKING_RULES_V2,
    "basis": "list_date basis: pipeline._tracking_inputs factors, corporate_action_on_session kept, not excluded",
    "open_check": "levels passed: D official open / factor; first of the conditions",
    "open_check_conditions": list(OPEN_CHECK_CONDITIONS),
    "open_check_no_open": "no D bar, suspended, or no factor -> no_data no_open",
    "not_applicable": "ai_levels still tracked; a group of its own in the report",
    "population": "premarket_score_v1 population",
    "rule_list": "the list date's today list (input pool.today_list_run_id): open_hold and tracking_v2 on its input strategy_levels; none -> no_list",
    "excess": "ai list open_hold mean - population mean",
    "ai_vs_rule_levels": "picks with both ai_levels and rule_levels comparable: ai mean - rule mean",
    "ai_vs_rule_picks": "ai list open_hold mean - rule list open_hold mean",
    "empty": "no comparable on a side -> null, empty_side",
    "write": "a horizon is written once its session exists, never rewritten",
    "cost_bps": ROUND_TRIP_TRANSACTION_COST_BPS,
    "slippage_bps": EXECUTION_SLIPPAGE_BPS,
    "groups": [
        "setup",
        "basis_primary",
        "basis",
        "confidence",
        "setup_confidence",
        "state",
    ],
    "group_levels_horizon": LEVELS_HORIZON,
    "group_win": "comparable ai_levels return > 0",
    "group_min_comparable": MIN_GROUP_COMPARABLE,
    "group_open_hold_min": "open_hold excess shown only with MIN_GROUP_COMPARABLE comparable holds",
    "market_groups": "basis_primary of market_method_json; stance hit rate d0, t5",
}


def _finite(value: Any) -> float | None:
    return v1._finite(value)


def _round(value: float | None) -> float | None:
    return v1._round(value)


# --- one pick ------------------------------------------------------------------------


def levels_passed(display: dict[str, Any] | None) -> bool:
    """The pick's levels passed every check (``display_levels_json`` is set)."""

    if not display:
        return False
    entry = display.get("entry") or {}
    return (
        entry.get("type") in {"breakout", "pullback"}
        and _finite(entry.get("low")) is not None
        and _finite(entry.get("high")) is not None
        and _finite(display.get("stop")) is not None
        and _finite(display.get("target_1")) is not None
    )


def ai_track_levels(display: dict[str, Any]) -> TrackLevels:
    """The AI's checked levels as ``app.tracking`` tracks them."""

    entry = display["entry"]
    breakout = entry["type"] == "breakout"
    return TrackLevels(
        entry_type=entry["type"],
        breakout_price=_finite(entry["low"]) if breakout else None,
        pullback_low=None if breakout else _finite(entry["low"]),
        pullback_high=None if breakout else _finite(entry["high"]),
        invalid_price=_finite(display["stop"]),
        target_1=_finite(display["target_1"]),
    )


def open_check(display: dict[str, Any], open_price: float | None) -> dict[str, Any]:
    """今日不適用 from D's official open on the list date's basis.

    D's open at or below the stop, at or above the first target, or (a
    breakout) above the entry's upper bound, the no-chase price: not
    applicable today.  A pullback opening above its zone still is: the price
    may come back within the valid sessions.  All conditions that hold are
    listed; ``reason`` is the first.
    """

    opened = _finite(open_price)
    out: dict[str, Any] = {
        "status": "checked",
        "applicable": None,
        "reason": None,
        "conditions": [],
        "open": _round(opened),
    }
    if opened is None or opened <= 0:
        out.update(status=NO_DATA, reason=NO_OPEN)
        return out
    entry = display["entry"]
    conditions = []
    if opened <= float(display["stop"]):
        conditions.append(OPEN_AT_OR_BELOW_STOP)
    if opened >= float(display["target_1"]):
        conditions.append(OPEN_AT_OR_ABOVE_TARGET)
    if entry["type"] == "breakout" and opened > float(entry["high"]):
        conditions.append(GAP_ABOVE_ENTRY_HIGH)
    out.update(
        applicable=not conditions,
        reason=conditions[0] if conditions else None,
        conditions=conditions,
    )
    return out


def not_applicable(outcome: dict[str, Any]) -> bool:
    check = outcome.get("open_check") or {}
    return check.get("applicable") is False


def with_excess(hold: dict[str, Any], population_mean: float | None) -> dict[str, Any]:
    """``hold`` with its excess over the population (None when either is missing)."""

    value = hold.get("return") if hold.get("status") == "comparable" else None
    return {**hold, "excess": v1.difference(value, population_mean)}


# --- overall --------------------------------------------------------------------------


def summary(results: Iterable[dict[str, Any] | None]) -> dict[str, Any]:
    return v1.summary(results)


def _comparable(result: dict[str, Any] | None) -> bool:
    return bool(result) and result.get("status") == "comparable"


def overall_outcome(
    picks: Sequence[dict[str, Any]],
    rule_list: Sequence[dict[str, Any]] | None,
    population: dict[str, Any],
    *,
    pool_phase: str | None,
) -> dict[str, Any]:
    """One reading's picks against the population and the rule list, one horizon.

    ``picks`` are the stock outcomes (``worker.ai_list_score.pick_outcome``);
    ``rule_list`` the outcomes of the list date's rule list (``open_hold`` and
    ``levels``), None or empty without one.
    """

    population_mean = population.get("mean")
    ai_hold = summary(row["open_hold"] for row in picks)
    ai_hold["excess"] = v1.difference(ai_hold["mean"], population_mean)
    ai_levels = summary(row.get("ai_levels") for row in picks)
    if rule_list:
        rule: dict[str, Any] = {
            "status": "scored",
            "open_hold": summary(row["open_hold"] for row in rule_list),
            "levels": summary(row.get("levels") for row in rule_list),
            "stocks": list(rule_list),
        }
        rule["open_hold"]["excess"] = v1.difference(
            rule["open_hold"]["mean"], population_mean
        )
    else:
        rule = {
            "status": NO_LIST,
            "open_hold": {"n": 0, "mean": None, "excess": None},
            "levels": {"n": 0, "mean": None},
            "stocks": [],
        }
    pairs = [
        row
        for row in picks
        if _comparable(row.get("ai_levels")) and _comparable(row.get("rule_levels"))
    ]
    pair_ai = summary(row["ai_levels"] for row in pairs)
    pair_rule = summary(row["rule_levels"] for row in pairs)
    levels_value = v1.difference(pair_ai["mean"], pair_rule["mean"])
    picks_value = v1.difference(ai_hold["mean"], rule["open_hold"]["mean"])
    return {
        "pool_phase": pool_phase,
        "population": population,
        "ai_list": {"open_hold": ai_hold, "ai_levels": ai_levels},
        "rule_list": rule,
        "ai_vs_rule_levels": {
            "pairs": len(pairs),
            "ai_mean": pair_ai["mean"],
            "rule_mean": pair_rule["mean"],
            "value": levels_value,
            "reason": None if levels_value is not None else EMPTY_SIDE,
        },
        "ai_vs_rule_picks": {
            "value": picks_value,
            "reason": None if picks_value is not None else EMPTY_SIDE,
        },
        "counts": {
            "picks": len(picks),
            "levels_check_failed": sum(1 for row in picks if not row["levels_passed"]),
            "not_applicable": sum(1 for row in picks if not_applicable(row)),
            "no_rule_levels": sum(1 for row in picks if row.get("rule_levels") is None),
            "corporate_action_on_session": sum(
                1 for row in picks if row.get("corporate_action_on_session")
            ),
        },
    }


# --- the method groups ---------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return _round(statistics.fmean(values)) if values else None


def _median(values: list[float]) -> float | None:
    return _round(statistics.median(values)) if values else None


def group_stats(picks: Sequence[dict[str, dict[str, Any] | None]]) -> dict[str, Any]:
    """One method group: ``picks`` are ``{horizon: stock outcome}`` per pick.

    ``ai_levels`` is read at ``LEVELS_HORIZON``.  Fewer than
    ``MIN_GROUP_COMPARABLE`` comparable ai_levels results is
    ``insufficient_sample``: the counts stay, the win rate, mean, median and
    trigger shares are None.  The open_hold excess of a horizon needs as many
    comparable holds, else None.
    """

    levels_rows = [item.get(LEVELS_HORIZON) for item in picks]
    with_levels = [
        row["ai_levels"]
        for row in levels_rows
        if row is not None and row.get("ai_levels") is not None
    ]
    filled = sum(1 for result in with_levels if result.get("execution_date"))
    comparable = [result for result in with_levels if _comparable(result)]
    returns = [
        result["return"] for result in comparable if result["return"] is not None
    ]
    reasons: Counter[str] = Counter()
    for row in levels_rows:
        if row is None:
            continue
        result = row.get("ai_levels")
        if result is None:
            reasons[row.get("ai_levels_reason") or LEVELS_CHECK_FAILED] += 1
        elif not _comparable(result):
            reasons[result.get("reason") or "unknown"] += 1
    enough = len(comparable) >= MIN_GROUP_COMPARABLE
    triggers = Counter(result.get("first_trigger") for result in comparable)
    out: dict[str, Any] = {
        "n": len(picks),
        "status": "sufficient" if enough else INSUFFICIENT_SAMPLE,
        "levels_n": len(with_levels),
        "filled": filled,
        "fill_rate": filled / len(with_levels) if with_levels else None,
        "comparable": len(comparable),
        "win_rate": (sum(1 for value in returns if value > 0) / len(returns))
        if enough and returns
        else None,
        "mean": _mean(returns) if enough else None,
        "median": _median(returns) if enough else None,
        "first_trigger": {
            str(trigger): (triggers.get(trigger, 0) if enough else None)
            for trigger in TRIGGERS
        },
        "incomparable": dict(sorted(reasons.items())),
    }
    for horizon in STOCK_HORIZONS:
        excess = [
            row["open_hold"]["excess"]
            for row in (item.get(horizon) for item in picks)
            if row is not None and row["open_hold"].get("excess") is not None
        ]
        out[f"open_hold_{horizon}_n"] = len(excess)
        out[f"open_hold_{horizon}_excess"] = (
            _mean(excess) if len(excess) >= MIN_GROUP_COMPARABLE else None
        )
    return out


def state_of(outcome: dict[str, Any]) -> str:
    """The pick's state group: levels failed, not applicable today, or tradable."""

    if not outcome["levels_passed"]:
        return LEVELS_CHECK_FAILED
    if not_applicable(outcome):
        return "not_applicable"
    return "applicable"


def group_keys(outcome: dict[str, Any]) -> dict[str, list[str]]:
    """The groups one pick counts in (``basis`` once per code it lists)."""

    return {
        "setup": [outcome["setup"]],
        "basis_primary": [outcome["basis_primary"]],
        "basis": list(dict.fromkeys(outcome.get("basis") or [])),
        "confidence": [outcome["confidence"]],
        "setup_confidence": [f"{outcome['setup']}×{outcome['confidence']}"],
        "state": [state_of(outcome)],
    }


def grouped(
    picks: Sequence[dict[str, dict[str, Any] | None]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """``{group: {key: group_stats}}`` over ``picks`` (``{horizon: outcome}`` each).

    A pick's group keys come from any horizon's row (they are the same).
    """

    members: dict[str, dict[str, list]] = {name: {} for name in RULES["groups"]}
    for item in picks:
        sample = next(row for row in item.values() if row is not None)
        for name, keys in group_keys(sample).items():
            for key in keys:
                members[name].setdefault(key, []).append(item)
    return {
        name: {key: group_stats(rows) for key, rows in sorted(found.items())}
        for name, found in members.items()
    }


def market_groups(outcomes: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Market stance hit rates by ``basis_primary``; ``outcomes`` are market rows
    ``{"horizon": ..., **outcome}``.  Fewer scored days than
    ``MIN_GROUP_COMPARABLE`` is ``insufficient_sample``, hit rate None."""

    out: dict[str, dict[str, Any]] = {}
    for row in outcomes:
        key = row.get("basis_primary") or "unknown"
        part = out.setdefault(
            key, {horizon: {"days": 0, "hits": 0} for horizon in MARKET_HORIZONS}
        )
        if row.get("status") == "scored":
            part[row["horizon"]]["days"] += 1
            part[row["horizon"]]["hits"] += 1 if row.get("hit") else 0
    for part in out.values():
        for horizon in MARKET_HORIZONS:
            item = part[horizon]
            enough = item["days"] >= MIN_GROUP_COMPARABLE
            item["status"] = "sufficient" if enough else INSUFFICIENT_SAMPLE
            item["hit_rate"] = item["hits"] / item["days"] if enough else None
            if not enough:
                item["hits"] = None
    return dict(sorted(out.items()))
