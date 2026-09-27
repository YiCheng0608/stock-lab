"""Caller-supplied, post-session hypothetical long-plan calculation; no I/O.

The caller supplies the tick, costs, observations, and an earliest *legal*
execution instant.  This module cannot establish exchange calendar, official
fee/tick schedules, data availability, or a broker fill.  Decimal prices and
rates are required so binary floats cannot silently alter boundary decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Underflow,
    localcontext,
)


TRADE_PLAN_VERSION = "caller-trade-plan/v1"
EXECUTION_VERSION = "caller-execution/v1"
EVALUATION_SCOPE = "post_session_hypothetical"

# All accepted decimals have exponent -8..12 and magnitude <= 10^12.
# Counts are bounded so every intermediate fits the fixed 50-digit context.
_MAX_DECIMAL = Decimal("1000000000000")
_MAX_COUNT = 1_000_000_000_000
_MAX_SLIPPAGE_TICKS = 1_000_000
_CALC_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=-100,
    Emax=100,
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, FloatOperation],
)


class TradePlanInputError(ValueError):
    """A missing, ill-typed, non-finite, or unsupported caller input."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


_PLAN_FIELDS = frozenset({
    "side", "trigger_rule", "trigger_price", "confirmation_rule",
    "confirmation_price", "entry_rule", "entry_min", "entry_max",
    "no_chase_cap", "invalidation_rule", "invalid_price", "target_1",
    "target_2", "tick_rule", "tick_size", "entry_fee_rate",
    "exit_fee_rate", "exit_tax_rate", "entry_slippage_ticks",
    "exit_slippage_ticks", "minimum_volume", "minimum_turnover",
    "decision_at", "earliest_execution_at", "expires_at",
    "invalidation_event_key",
})
_OBSERVATION_FIELDS = frozenset({
    "trigger_high", "trigger_at", "confirmation_close", "confirmation_at",
    "session_open_reference_price", "session_started_at", "session_ended_at",
    "assessed_at", "session_high", "session_low", "volume", "turnover",
    "halted", "event_state", "event_at",
})


def _exact_fields(value: object, expected: frozenset[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TradePlanInputError(f"{label}:invalid_mapping")
    keys = set(value)
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        raise TradePlanInputError(f"{label}:fields:missing={missing}:unknown={unknown}")
    return value


def _choice(value: object, field: str, allowed: frozenset[str]) -> str:
    if type(value) is not str or value not in allowed:
        raise TradePlanInputError(f"{field}:unsupported_or_invalid")
    return value


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise TradePlanInputError(f"{field}:finite_decimal_required")
    if not -8 <= value.as_tuple().exponent <= 12 or value > _MAX_DECIMAL:
        raise TradePlanInputError(f"{field}:outside_supported_decimal_range")
    if value < 0 or (positive and value == 0):
        raise TradePlanInputError(f"{field}:out_of_range")
    return value


def _rate(value: object, field: str) -> Decimal:
    rate = _decimal(value, field)
    if rate >= 1:
        raise TradePlanInputError(f"{field}:out_of_range")
    return rate


def _integer(value: object, field: str, *, positive: bool = False, maximum: int = _MAX_COUNT) -> int:
    if type(value) is not int or value < 0 or value > maximum or (positive and value == 0):
        raise TradePlanInputError(f"{field}:nonnegative_integer_required")
    return value


def _instant(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise TradePlanInputError(f"{field}:aware_datetime_required")
    return value


def _tick_round(value: Decimal, tick: Decimal, direction: str) -> Decimal:
    rounding = ROUND_FLOOR if direction == "down" else ROUND_CEILING
    return (value / tick).to_integral_value(rounding=rounding) * tick


def _observed_tick_price(value: Decimal, tick: Decimal, field: str) -> None:
    if value % tick != 0:
        raise TradePlanInputError(f"{field}:off_caller_tick")


def calculate_trade_plan(
    plan: Mapping[str, object], observation: Mapping[str, object]
) -> dict[str, object]:
    """Evaluate a completed caller-supplied session without asserting a fill.

    Decimal work uses a fixed context and bounded input range, independent of
    the caller's active decimal context.  Unsupported arithmetic is rejected.
    """

    with localcontext(_CALC_CONTEXT):
        try:
            return _calculate_trade_plan(plan, observation)
        except DecimalException as exc:
            raise TradePlanInputError("decimal:unsupported_operation") from exc


def _calculate_trade_plan(
    plan: Mapping[str, object], observation: Mapping[str, object]
) -> dict[str, object]:
    """Calculate one long plan against a complete hypothetical session.

    ``high_at_or_above`` and ``close_at_or_above`` refer to observations made
    no later than ``decision_at``.  ``caller_session_open`` uses the supplied
    session opening price as a reference, with adverse slippage added for a
    conservative per-unit feasibility check.  No order or fill is produced.
    The caller must establish that ``earliest_execution_at`` is a legal later
    session; this function only enforces timestamp ordering.  Session extremes,
    volume, and halt state are post-decision observations, so every return is
    explicitly marked hypothetical and point-in-time truth is not asserted.

    Plan levels are rounded conservatively to a single caller-provided tick:
    invalidation, targets, entry maximum and chase cap down; entry minimum,
    trigger and confirmation up.  Unknown tick ladders are unsupported.
    """

    plan = _exact_fields(plan, _PLAN_FIELDS, "plan")
    observation = _exact_fields(observation, _OBSERVATION_FIELDS, "observation")

    _choice(plan["side"], "side", frozenset({"long"}))
    trigger_rule = _choice(plan["trigger_rule"], "trigger_rule", frozenset({"high_at_or_above"}))
    confirmation_rule = _choice(
        plan["confirmation_rule"], "confirmation_rule", frozenset({"close_at_or_above"})
    )
    _choice(plan["entry_rule"], "entry_rule", frozenset({"caller_session_open"}))
    invalidation_rule = _choice(
        plan["invalidation_rule"], "invalidation_rule", frozenset({"session_low_at_or_below"})
    )
    tick_rule = _choice(plan["tick_rule"], "tick_rule", frozenset({"constant_tick"}))
    event_key = plan["invalidation_event_key"]
    if type(event_key) is not str or not event_key.strip():
        raise TradePlanInputError("invalidation_event_key:nonempty_string_required")

    price_names = (
        "trigger_price", "confirmation_price", "entry_min", "entry_max",
        "no_chase_cap", "invalid_price", "target_1", "target_2", "tick_size",
    )
    prices = {name: _decimal(plan[name], name, positive=True) for name in price_names}
    observed_price_names = (
        "trigger_high", "confirmation_close", "session_open_reference_price", "session_high", "session_low"
    )
    observed_prices = {
        name: _decimal(observation[name], name, positive=True) for name in observed_price_names
    }
    tick = prices["tick_size"]
    for name, value in observed_prices.items():
        _observed_tick_price(value, tick, name)
    if not observed_prices["session_low"] <= observed_prices["session_open_reference_price"] <= observed_prices["session_high"]:
        raise TradePlanInputError("session:open_outside_high_low")

    entry_fee = _rate(plan["entry_fee_rate"], "entry_fee_rate")
    exit_fee = _rate(plan["exit_fee_rate"], "exit_fee_rate")
    exit_tax = _rate(plan["exit_tax_rate"], "exit_tax_rate")
    if exit_fee + exit_tax >= 1:
        raise TradePlanInputError("exit_cost_rates:out_of_range")
    entry_slippage = _integer(
        plan["entry_slippage_ticks"], "entry_slippage_ticks", maximum=_MAX_SLIPPAGE_TICKS
    )
    exit_slippage = _integer(
        plan["exit_slippage_ticks"], "exit_slippage_ticks", maximum=_MAX_SLIPPAGE_TICKS
    )
    minimum_volume = _integer(plan["minimum_volume"], "minimum_volume", positive=True)
    volume = _integer(observation["volume"], "volume")
    minimum_turnover = _decimal(plan["minimum_turnover"], "minimum_turnover", positive=True)
    turnover = _decimal(observation["turnover"], "turnover")
    if type(observation["halted"]) is not bool:
        raise TradePlanInputError("halted:boolean_required")
    event_state = _choice(observation["event_state"], "event_state", frozenset({"clear", "occurred", "unknown"}))
    event_at_value = observation["event_at"]
    event_at = None if event_at_value is None else _instant(event_at_value, "event_at")
    if (event_state == "occurred") != (event_at is not None):
        raise TradePlanInputError("event_state:event_at_mismatch")

    decision_at = _instant(plan["decision_at"], "decision_at")
    earliest_at = _instant(plan["earliest_execution_at"], "earliest_execution_at")
    expires_at = _instant(plan["expires_at"], "expires_at")
    trigger_at = _instant(observation["trigger_at"], "trigger_at")
    confirmation_at = _instant(observation["confirmation_at"], "confirmation_at")
    session_started_at = _instant(observation["session_started_at"], "session_started_at")
    session_ended_at = _instant(observation["session_ended_at"], "session_ended_at")
    assessed_at = _instant(observation["assessed_at"], "assessed_at")
    if not trigger_at <= confirmation_at <= decision_at < earliest_at < expires_at:
        raise TradePlanInputError("plan_time:invalid_order")
    if not decision_at < session_started_at < session_ended_at <= assessed_at:
        raise TradePlanInputError("session_time:invalid_order_or_incomplete")
    if event_at is not None and event_at > assessed_at:
        raise TradePlanInputError("event_at:after_assessment")

    rounded = {
        "trigger": _tick_round(prices["trigger_price"], tick, "up"),
        "confirmation": _tick_round(prices["confirmation_price"], tick, "up"),
        "entry_min": _tick_round(prices["entry_min"], tick, "up"),
        "entry_max": _tick_round(prices["entry_max"], tick, "down"),
        "no_chase_cap": _tick_round(prices["no_chase_cap"], tick, "down"),
        "invalid": _tick_round(prices["invalid_price"], tick, "down"),
        "target_1": _tick_round(prices["target_1"], tick, "down"),
        "target_2": _tick_round(prices["target_2"], tick, "down"),
    }
    upper_entry = min(rounded["entry_max"], rounded["no_chase_cap"])
    trigger_met = observed_prices["trigger_high"] >= rounded["trigger"]
    confirmation_met = observed_prices["confirmation_close"] >= rounded["confirmation"]
    opening = observed_prices["session_open_reference_price"]
    hypothetical_entry = opening + entry_slippage * tick

    result: dict[str, object] = {
        "trade_plan_version": TRADE_PLAN_VERSION,
        "execution_version": EXECUTION_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "point_in_time_status": "not_asserted",
        "fill_status": "not_asserted",
        "status": "rejected",
        "reason": None,
        "candidate_feasibility": "not_assessed",
        "decision_at": decision_at,
        "earliest_execution_at": earliest_at,
        "expires_at": expires_at,
        "session_started_at": session_started_at,
        "session_ended_at": session_ended_at,
        "assessed_at": assessed_at,
        "hypothetical_open_reference_at": session_started_at,
        "tick": {"rule": tick_rule, "size": tick},
        "trigger": {"rule": trigger_rule, "price": rounded["trigger"], "observed_high": observed_prices["trigger_high"], "at": trigger_at, "met": trigger_met},
        "confirmation": {"rule": confirmation_rule, "price": rounded["confirmation"], "observed_close": observed_prices["confirmation_close"], "at": confirmation_at, "met": confirmation_met},
        "entry": {"rule": "caller_session_open", "min": rounded["entry_min"], "max": rounded["entry_max"], "no_chase_cap": rounded["no_chase_cap"], "session_open_reference_price": opening, "hypothetical_entry_after_slippage": hypothetical_entry},
        "invalidation": {"rule": invalidation_rule, "price": rounded["invalid"], "event_key": event_key, "event_state": event_state, "event_at": event_at},
        "targets": {"target_1": rounded["target_1"], "target_2": rounded["target_2"]},
        "costs": {"entry_fee_rate": entry_fee, "exit_fee_rate": exit_fee, "exit_tax_rate": exit_tax, "entry_slippage_ticks": entry_slippage, "exit_slippage_ticks": exit_slippage, "hypothetical_target_1_cost_space_per_unit": None},
        "liquidity": {"minimum_volume": minimum_volume, "volume": volume, "minimum_turnover": minimum_turnover, "turnover": turnover, "halted": observation["halted"]},
        "post_session_touches": {"classification": "not_assessed", "invalidation_touched": None, "target_1_touched": None, "target_2_touched": None},
    }

    def finish(status: str, reason: str | None) -> dict[str, object]:
        result["status"] = status
        result["reason"] = reason
        return result

    if not (0 < rounded["invalid"] < rounded["entry_min"] <= upper_entry < rounded["target_1"] < rounded["target_2"]):
        return finish("rejected", "rounded_levels_not_strictly_ordered")
    if event_state == "unknown":
        return finish("rejected", "event_state_unknown")
    if event_at is not None and event_at < session_started_at:
        return finish("rejected", "invalidation_event_before_session")
    if expires_at <= session_started_at:
        return finish("rejected", "plan_expired_before_session")
    if event_at is not None and event_at <= session_ended_at:
        return finish("incomparable", "invalidation_event_within_session_order_unknown")
    if expires_at <= session_ended_at:
        return finish("incomparable", "expiry_within_session_order_unknown")
    if observation["halted"]:
        return finish("rejected", "halted")
    if volume < minimum_volume or turnover < minimum_turnover:
        return finish("rejected", "insufficient_liquidity")
    if not trigger_met:
        return finish("pending", "trigger_not_met")
    if not confirmation_met:
        return finish("pending", "confirmation_not_met")
    if session_started_at < earliest_at:
        return finish("pending", "before_earliest_execution")
    if opening < rounded["entry_min"]:
        return finish("rejected_gap", "opening_below_entry_range")
    if hypothetical_entry > upper_entry:
        return finish("rejected_gap", "opening_plus_slippage_above_entry_cap")
    if not rounded["invalid"] < hypothetical_entry < rounded["target_1"] < rounded["target_2"]:
        return finish("rejected", "effective_entry_levels_not_strictly_ordered")

    hypothetical_exit_target_1 = rounded["target_1"] - exit_slippage * tick
    cost_space = hypothetical_exit_target_1 * (1 - exit_fee - exit_tax) - hypothetical_entry * (1 + entry_fee)
    result["costs"]["hypothetical_target_1_cost_space_per_unit"] = cost_space
    if hypothetical_exit_target_1 <= 0 or cost_space <= 0:
        return finish("rejected", "target_1_cost_space_insufficient")

    result["candidate_feasibility"] = "feasible"
    invalidation_touched = observed_prices["session_low"] <= rounded["invalid"]
    target_1_touched = observed_prices["session_high"] >= rounded["target_1"]
    target_2_touched = observed_prices["session_high"] >= rounded["target_2"]
    if invalidation_touched and target_1_touched:
        touch_classification = "stop_target_order_unknown"
    elif invalidation_touched:
        touch_classification = "invalidation_touched"
    elif target_2_touched:
        touch_classification = "target_1_and_2_touched"
    elif target_1_touched:
        touch_classification = "target_1_touched"
    else:
        touch_classification = "no_level_touched"
    result["post_session_touches"] = {
        "classification": touch_classification,
        "invalidation_touched": invalidation_touched,
        "target_1_touched": target_1_touched,
        "target_2_touched": target_2_touched,
    }
    if invalidation_touched and target_1_touched:
        return finish("incomparable", "same_session_stop_target_order_unknown")
    if invalidation_touched:
        return finish("hypothetical_invalidation_touched", "invalidation_price_touched")
    return finish("hypothetical_candidate_feasible", None)
