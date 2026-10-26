"""Shared pieces of ``strategy_levels_v1`` (V1_SPEC strategy_levels_v1).

Pure calculation.  Each strategy solves its own conditions for the next
session's close and volume (``Strategy.observation_levels``); this module
holds what they share: the tick ladder, the daily price limit, the reasons a
strategy gives no levels, and the confirmation conditions that cannot be
solved for a price.  The formulas and TICK_LADDERS are pinned by tests under
STRATEGY_LEVELS_VERSION.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from fractions import Fraction
from typing import Any

from app.domain import RuleEvaluation, instrument_eligibility

from .base import (
    COMMON_CONFIRMATIONS,
    Condition,
    NextSessionInputs,
    ObservationLevels,
    Strategy,
    StrategyInputs,
    finite_number,
    risk_levels,
)

PRICE_BASIS_SIGNAL_DAY = "score_date_raw_basis"
PRICE_BASIS_NEXT_SESSION = "next_session_raw_basis"

# TWSE/TPEx tick sizes: (band upper bound exclusive, tick); None is open-ended.
# Stocks and IPOs use "stock".  Strings keep the ladder exact and JSON-safe.
TICK_LADDERS: dict[str, tuple[tuple[str | None, str], ...]] = {
    "stock": (
        ("10", "0.01"),
        ("50", "0.05"),
        ("100", "0.1"),
        ("500", "0.5"),
        ("1000", "1"),
        (None, "5"),
    ),
    "etf": (("50", "0.01"), (None, "0.05")),
}
# Stocks and IPOs move at most this much from the previous close.  ETF limits
# differ by product (a bond ETF's LimitUp can be 9999.95), so they are not
# judged: reachable_next_session is null.
DAILY_PRICE_LIMIT = Fraction(1, 10)

ETF_EXCLUDED_PREFIX = "etf_category_excluded_from_actionable_signals:"


def _ladder(instrument_type: str) -> tuple[tuple[str | None, str], ...]:
    return TICK_LADDERS["etf" if instrument_type == "etf" else "stock"]


def _price(value: float) -> Decimal:
    # Six places, as the stored prior highs: float noise below that must not
    # move a bound past a tick.
    return Decimal(str(round(value, 6)))


def _band(price: Decimal, instrument_type: str) -> tuple[Decimal | None, Decimal]:
    for upper, tick in _ladder(instrument_type):
        if upper is None or price < Decimal(upper):
            return (Decimal(upper) if upper is not None else None), Decimal(tick)
    raise AssertionError("the last band is open-ended")


def tick_ceil(value: float, instrument_type: str, *, strict: bool = False) -> float:
    """The lowest legal price at or above ``value`` (above it when ``strict``)."""

    price = _price(value)
    upper, tick = _band(price, instrument_type)
    candidate = (price / tick).to_integral_value(ROUND_CEILING) * tick
    if strict and candidate == price:
        candidate += tick
    if upper is not None and candidate >= upper:
        # Every band's upper bound is a legal price of the next band.
        candidate = upper
    return float(candidate)


def tick_floor(value: float, instrument_type: str) -> float:
    """The highest legal price at or below ``value``."""

    price = _price(value)
    _upper, tick = _band(price, instrument_type)
    return float((price / tick).to_integral_value(ROUND_FLOOR) * tick)


def price_limits(inputs: NextSessionInputs) -> tuple[float, float] | None:
    """(limit down, limit up) around T's close; None for an ETF."""

    if inputs.instrument_type == "etf" or not inputs.close:
        return None
    reference = Fraction(str(round(inputs.close, 6)))
    return (
        tick_ceil(float(reference * (1 - DAILY_PRICE_LIMIT)), inputs.instrument_type),
        tick_floor(float(reference * (1 + DAILY_PRICE_LIMIT)), inputs.instrument_type),
    )


def positive_window(values: Sequence[float] | None, window: int) -> list[float] | None:
    """The last ``window`` values when there are that many and all are positive."""

    if values is None or len(values) < window:
        return None
    trailing = [finite_number(value) for value in values[-window:]]
    if not all(value is not None and value > 0 for value in trailing):
        return None
    return trailing  # type: ignore[return-value]


def average_volume(volumes: Sequence[int] | None) -> Fraction | None:
    """Exact 20-session average volume (shares) of the next session's window."""

    window = positive_window(volumes, 20)
    if window is None:
        return None
    return Fraction(sum(int(value) for value in window), len(window))


def volume_at_least(ratio: float, average: Fraction) -> int:
    """The smallest whole share volume whose ratio to ``average`` is >= ``ratio``."""

    return math.ceil(Fraction(str(ratio)) * average)


def volume_at_most(ratio: float, average: Fraction) -> int:
    """The largest whole share volume whose ratio to ``average`` is <= ``ratio``."""

    return math.floor(Fraction(str(ratio)) * average)


def unavailable(inputs: NextSessionInputs) -> ObservationLevels | None:
    """No levels: T suspended, or not eligible for an actionable signal next session."""

    if inputs.is_suspended:
        return ObservationLevels("suspended", ("signal_day_suspended",))
    eligible, reason = instrument_eligibility(
        inputs.instrument_type, inputs.bar_count + 1, inputs.etf_category
    )
    if eligible:
        return None
    if reason and reason.startswith(ETF_EXCLUDED_PREFIX):
        return ObservationLevels("not_applicable", (reason,))
    return ObservationLevels("data_incomplete", (reason or "not_eligible",))


def missing_confirmations(inputs: NextSessionInputs) -> list[str]:
    """The evaluators' reason codes for confirmation inputs T did not have."""

    values = {
        "group_excess_return_20d": inputs.group_excess_return_20d,
        "institutional_flow_to_turnover_ratio_5d": inputs.institutional_flow_ratio_5d,
        "margin_balance_change_ratio_5d": inputs.margin_change_ratio_5d,
    }
    return [
        f"{key}_missing_or_non_finite"
        for key, value in values.items()
        if finite_number(value) is None
    ]


def reference_levels(entry: float, atr: float | None) -> dict[str, float]:
    """Stop, targets and reward/risk of a reference entry (legacy-risk-levels/v1)."""

    reference_entry, invalid_price, target_1, target_2 = risk_levels(entry, atr)
    risk = reference_entry - invalid_price
    return {
        "reference_entry": reference_entry,
        "invalid_price": invalid_price,
        "target_1": target_1,
        "target_2": target_2,
        "risk_reward": round((target_1 - reference_entry) / risk, 2)
        if risk > 0
        else None,
    }


def satisfied(evaluation: RuleEvaluation, reasons: Iterable[str]) -> bool | None:
    """T's result of one condition from the stored evaluation; None without data."""

    if evaluation.state == "data_incomplete":
        return None
    return not any(reason in evaluation.reasons for reason in reasons)


def confirmation_conditions(
    inputs: StrategyInputs, evaluation: RuleEvaluation
) -> list[Condition]:
    """Group, institutional flow and margin: shown with T's value, not solved."""

    confirmations = COMMON_CONFIRMATIONS
    group = confirmations["group_relative_strength"]
    flow = confirmations["institutional_flow"]
    margin = confirmations["margin_financing"]
    return [
        Condition(
            "group_relative_strength",
            "confirmation",
            satisfied(evaluation, ("group_relative_strength_not_positive",)),
            actual=finite_number(inputs.group_excess_return_20d),
            threshold=group["minimum_excess_return"],
            operator=group["operator"],
        ),
        Condition(
            "institutional_flow",
            "confirmation",
            satisfied(evaluation, ("institutional_flow_materially_adverse",)),
            actual=finite_number(inputs.institutional_flow_ratio_5d),
            threshold=flow["minimum_net_flow_to_turnover_ratio"],
            operator=flow["operator"],
        ),
        Condition(
            "margin_financing",
            "confirmation",
            satisfied(evaluation, ("margin_financing_increase_abnormal",)),
            actual=finite_number(inputs.margin_change_ratio_5d),
            threshold=margin["maximum_balance_change_ratio"],
            operator=margin["operator"],
        ),
    ]


def common_conditions(
    *,
    instrument_type: str,
    etf_category: str | None,
    bar_count: int,
    is_suspended: bool,
    evaluation: RuleEvaluation,
) -> list[Condition]:
    """Eligibility and data completeness on T, shared by every strategy."""

    eligible, reason = instrument_eligibility(instrument_type, bar_count, etf_category)
    reasons = tuple(
        item
        for item in (reason, "signal_day_suspended" if is_suspended else None)
        if item
    )
    return [
        Condition(
            "eligibility",
            "eligibility",
            eligible and not is_suspended,
            reasons=reasons,
        ),
        Condition(
            "required_inputs",
            "data",
            evaluation.state != "data_incomplete",
            reasons=evaluation.reasons if evaluation.state == "data_incomplete" else (),
        ),
    ]


_BLANK_CONDITION = Condition("", "", None).as_json()


def condition_defaults(strategy: Strategy) -> dict[str, dict[str, Any]]:
    """Each condition of ``strategy`` as it reads without any input.

    Kind, operator, the configured thresholds and the empty values are the
    same on every row of one strategy version; ``conditions_json`` stores only
    what differs from this (#274 review L3).  Pinned by tests: a change here
    changes how stored rows read back.
    """

    empty = RuleEvaluation(False, "data_incomplete")
    inputs = StrategyInputs(
        bar_count=0,
        close=None,
        volume=None,
        ma20=None,
        ma60=None,
        atr14=None,
        prior_highs=None,
        prior_volumes=None,
        group_excess_return_20d=None,
        institutional_flow_ratio_5d=None,
        margin_change_ratio_5d=None,
    )
    conditions = [
        *common_conditions(
            instrument_type="stock",
            etf_category=None,
            bar_count=0,
            is_suspended=False,
            evaluation=empty,
        ),
        *strategy.conditions(inputs, empty, ObservationLevels("data_incomplete")),
    ]
    return {item.code: item.as_json() for item in conditions}


def judged_conditions(
    strategy: Strategy, evaluation: RuleEvaluation, *, bar_count: int
) -> list[dict[str, Any]]:
    """T's strategy conditions as a stored evaluation alone judges them.

    The strategy maps its reason codes to its conditions, so a reader of a
    signal's ``rule_evidence_json`` needs no list of its own; values are
    empty.  ``bar_count`` is the signal's stored ``bar_count_60d``.
    """

    inputs = StrategyInputs(
        bar_count=bar_count,
        close=None,
        volume=None,
        ma20=None,
        ma60=None,
        atr14=None,
        prior_highs=None,
        prior_volumes=None,
        group_excess_return_20d=None,
        institutional_flow_ratio_5d=None,
        margin_change_ratio_5d=None,
    )
    return [
        item.as_json()
        for item in strategy.conditions(
            inputs, evaluation, ObservationLevels("data_incomplete")
        )
    ]


def compact_conditions(
    strategy: Strategy, conditions: Iterable[Condition]
) -> list[dict[str, Any]]:
    """The stored ``conditions_json``: each condition without its default fields."""

    defaults = condition_defaults(strategy)
    stored = []
    for condition in conditions:
        item = condition.as_json()
        default = defaults.get(item["code"], {})
        stored.append(
            {
                key: value
                for key, value in item.items()
                if key == "code" or key not in default or default[key] != value
            }
        )
    return stored


def expand_conditions(
    strategy: Strategy,
    stored: Any,
    defaults: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Full condition dicts from ``conditions_json`` (compact or not).

    ``defaults`` is ``condition_defaults(strategy)`` computed once by a caller
    expanding many rows of the same strategy.
    """

    if defaults is None:
        defaults = condition_defaults(strategy)
    return [
        {**_BLANK_CONDITION, **defaults.get(item.get("code"), {}), **item}
        for item in (stored if isinstance(stored, list) else [])
        if isinstance(item, dict)
    ]


def gap(target: float, close: float | None) -> float | None:
    """Relative distance from T's close to a next-session price (0.021 = 2.1%)."""

    if not close:
        return None
    return round(target / close - 1, 6)


def as_json(levels: ObservationLevels) -> dict[str, Any]:
    """The stored columns of one result (strategy_levels)."""

    return {
        "availability": levels.availability,
        "trigger_price": levels.trigger_price,
        "zone_low": levels.zone_low,
        "zone_high": levels.zone_high,
        "min_volume": levels.min_volume,
        "max_volume": levels.max_volume,
        "reference_entry": levels.reference_entry,
        "entry_low": levels.entry_low,
        "entry_high": levels.entry_high,
        "invalid_price": levels.invalid_price,
        "target_1": levels.target_1,
        "target_2": levels.target_2,
        "risk_reward": levels.risk_reward,
        "reachable_next_session": levels.reachable_next_session,
        "missing_inputs_json": list(levels.missing_inputs),
    }
