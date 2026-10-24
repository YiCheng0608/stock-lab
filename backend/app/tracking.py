"""Session-by-session tracking of one set of rule levels (V1_SPEC tracking).

Shared by the system signal tracking (``worker.pipeline._evaluate_signal_tracking``)
and the user tracking plans (``worker.plan_tracking``), so both apply the same
fill, exit, suspension and corporate-action rules.  Pure functions only: no
database, no clock and no ``app.config`` import (that import creates the data
directories), so the verify fixture can compute tracked rows with it too.

``track_path`` walks at most the first sessions after the level date, already
loaded by the caller with each bar's corporate-action factor and whether an
official suspension interval hid a missing session before it.  ``settle``
turns a path into the T+N result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

# Explicit modelling assumptions, not market observations.  They are persisted in signal evidence so a backtest/review can
# distinguish a net-of-cost result from a raw price return.
EXECUTION_SLIPPAGE_BPS = 5.0
ROUND_TRIP_TRANSACTION_COST_BPS = 30.0
# Sessions after the level date a signal or a plan is tracked for.
TRACKING_WINDOW_SESSIONS = 20

AMBIGUOUS_REASON = "same-session stop and target both touched; order is unknowable"


@dataclass(frozen=True)
class TrackLevels:
    """Entry, invalidation and first target on the level date's price basis."""

    entry_type: str
    breakout_price: float | None
    pullback_low: float | None
    pullback_high: float | None
    invalid_price: float | None
    target_1: float | None


@dataclass(frozen=True)
class TrackBar:
    """One stored session after the level date, as the caller loaded it.

    ``factor`` maps the level-date price basis to this session's raw basis
    (for a 2-for-1 split, level 100 -> raw level 50 and factor=0.5).
    ``suspension_gap`` is true when an official suspension interval contains a
    missing market session between the previous observed bar and this one.
    """

    trading_date: date
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None
    volume: int | None
    is_suspended: bool
    source: str | None
    data_time: str | None
    factor: float
    action_applied: bool
    suspension_gap: bool


@dataclass(frozen=True)
class TrackSession:
    session_no: int
    trading_date: date
    status: str
    reason: str
    breakout_trigger: bool
    pullback_trigger: bool
    target_trigger: bool
    invalid_trigger: bool
    suspended: bool
    comparable: bool
    execution_date: date | None
    execution_price: float | None
    adjusted: dict[str, Any]
    action_applied: bool
    trigger_order: str
    source: str | None
    data_time: str | None


@dataclass(frozen=True)
class TrackPath:
    sessions: tuple[TrackSession, ...]
    executed: bool
    execution_date: date | None
    execution_price: float | None
    execution_factor: float | None
    first_outcome: str | None
    outcome_session_no: int | None
    outcome_price: float | None
    outcome_factor: float | None
    ambiguous: bool


def buy_fill_with_slippage(price: float | None) -> float | None:
    """Model a documented adverse fill for a long position.

    The source OHLC remains untouched.  The adjusted execution price is only
    used for tracking returns and is recorded in the signal evidence so a
    reviewer can reproduce the net result.
    """

    if price is None or not math.isfinite(price) or price <= 0:
        return None
    return round(price * (1.0 + EXECUTION_SLIPPAGE_BPS / 10_000.0), 8)


def sell_fill_with_slippage(price: float | None) -> float | None:
    """Model an adverse sell fill for a long position."""

    if price is None or not math.isfinite(price) or price <= 0:
        return None
    return round(price * (1.0 - EXECUTION_SLIPPAGE_BPS / 10_000.0), 8)


def track_path(levels: TrackLevels, bars: list[TrackBar]) -> TrackPath:
    """Fill from T+1 at the first executable price, then the first exit."""

    sessions: list[TrackSession] = []
    executed = False
    execution_date: date | None = None
    execution_price: float | None = None
    first_outcome: str | None = None
    outcome_session_no: int | None = None
    outcome_price: float | None = None
    execution_factor: float | None = None
    outcome_factor: float | None = None
    ambiguous = False
    for session_no, bar in enumerate(bars, start=1):
        factor = bar.factor
        # Keep raw OHLC untouched for execution and trigger checks;
        # ``adjusted`` is explicitly the inverse mapping, normalized back to
        # the level-date basis for return comparison.
        adjusted = {
            "basis": "signal_date_normalized",
            "factor_signal_to_raw": factor,
            "open": round(bar.open / factor, 8),
            "high": round(bar.high / factor, 8),
            "low": round(bar.low / factor, 8),
            "close": round(bar.close / factor, 8),
            "adj_close": round((bar.adj_close or bar.close) / factor, 8),
        }
        suspended = bool(
            bar.is_suspended
            or (bar.volume == 0 and bar.open == bar.high == bar.low == bar.close)
            or bar.suspension_gap
        )
        breakout_level_raw = (
            levels.breakout_price * factor
            if levels.breakout_price is not None
            else None
        )
        pullback_low_level_raw = (
            levels.pullback_low * factor if levels.pullback_low is not None else None
        )
        pullback_high_level_raw = (
            levels.pullback_high * factor if levels.pullback_high is not None else None
        )
        invalid_level_raw = (
            levels.invalid_price * factor if levels.invalid_price is not None else None
        )
        target_level_raw = (
            levels.target_1 * factor if levels.target_1 is not None else None
        )
        breakout_trigger = False
        pullback_trigger = False
        target_trigger = False
        invalid_trigger = False
        status = "pending"
        reason = ""
        comparable = not suspended
        current_execution_price = execution_price
        if suspended:
            status = "suspended"
            reason = (
                "official suspension interval contains a missing market session; "
                "no price trigger inferred"
                if bar.suspension_gap
                else "trading suspended; no price trigger inferred"
            )
            comparable = False
        else:
            if not executed:
                if (
                    levels.entry_type == "breakout"
                    and levels.breakout_price is not None
                ):
                    breakout_trigger = (
                        breakout_level_raw is not None
                        and bar.high >= breakout_level_raw
                    )
                    if breakout_trigger:
                        raw_execution_price = (
                            max(bar.open, breakout_level_raw)
                            if bar.open >= breakout_level_raw
                            else breakout_level_raw
                        )
                        current_execution_price = buy_fill_with_slippage(
                            raw_execution_price
                        )
                elif (
                    levels.entry_type == "pullback"
                    and levels.pullback_low is not None
                    and levels.pullback_high is not None
                ):
                    pullback_trigger = (
                        pullback_low_level_raw is not None
                        and pullback_high_level_raw is not None
                        and bar.low <= pullback_high_level_raw
                        and bar.high >= pullback_low_level_raw
                    )
                    if pullback_trigger:
                        raw_execution_price = (
                            bar.open
                            if pullback_low_level_raw
                            <= bar.open
                            <= pullback_high_level_raw
                            else min(
                                max(bar.open, pullback_low_level_raw),
                                pullback_high_level_raw,
                            )
                        )
                        current_execution_price = buy_fill_with_slippage(
                            raw_execution_price
                        )
                if breakout_trigger or pullback_trigger:
                    executed = True
                    execution_date = bar.trading_date
                    execution_price = current_execution_price
                    execution_factor = factor
                    status = "active"
                    reason = "earliest executable fill from T+1"
                else:
                    status = "not_triggered"
                    reason = "conditional entry was not reached"
            if executed and execution_price is not None:
                if ambiguous:
                    status = "ambiguous"
                    reason = AMBIGUOUS_REASON
                    comparable = False
                elif first_outcome is not None:
                    # Once an exit is observed, later bars cannot overwrite
                    # the first outcome or introduce look-ahead bias.
                    status = first_outcome
                    reason = "position already closed on first observed outcome"
                else:
                    invalid_trigger = (
                        invalid_level_raw is not None and bar.low <= invalid_level_raw
                    )
                    target_trigger = (
                        target_level_raw is not None and bar.high >= target_level_raw
                    )
                    if invalid_trigger and target_trigger:
                        status = "ambiguous"
                        reason = AMBIGUOUS_REASON
                        comparable = False
                        ambiguous = True
                    elif invalid_trigger:
                        status = "invalidated"
                        reason = "invalid price touched"
                        first_outcome = "invalidated"
                        outcome_session_no = session_no
                        outcome_price = sell_fill_with_slippage(invalid_level_raw)
                        outcome_factor = factor
                    elif target_trigger:
                        status = "target_1_hit"
                        reason = "first target touched"
                        first_outcome = "target_1_hit"
                        outcome_session_no = session_no
                        outcome_price = sell_fill_with_slippage(target_level_raw)
                        outcome_factor = factor
                    else:
                        status = "active"
                        reason = "position remains within defined levels"
        sessions.append(
            TrackSession(
                session_no=session_no,
                trading_date=bar.trading_date,
                status=status,
                reason=reason,
                breakout_trigger=breakout_trigger,
                pullback_trigger=pullback_trigger,
                target_trigger=target_trigger,
                invalid_trigger=invalid_trigger,
                suspended=suspended,
                comparable=comparable,
                execution_date=execution_date,
                execution_price=execution_price,
                adjusted=adjusted,
                action_applied=bar.action_applied,
                trigger_order="ambiguous" if ambiguous else (first_outcome or "none"),
                source=bar.source,
                data_time=bar.data_time,
            )
        )
    return TrackPath(
        sessions=tuple(sessions),
        executed=executed,
        execution_date=execution_date,
        execution_price=execution_price,
        execution_factor=execution_factor,
        first_outcome=first_outcome,
        outcome_session_no=outcome_session_no,
        outcome_price=outcome_price,
        outcome_factor=outcome_factor,
        ambiguous=ambiguous,
    )


def settle(path: TrackPath, horizon: int) -> dict[str, Any]:
    """The T+``horizon`` result of a non-empty path, net of the cost assumption."""

    sessions = path.sessions
    execution_price = path.execution_price
    if len(sessions) < horizon:
        return {
            "settlement_date": sessions[-1].trading_date,
            "final_status": "incomparable",
            "first_trigger": path.first_outcome,
            "return_or_risk": None,
            "incomparable_reason": f"only {len(sessions)} trading sessions available; {horizon} required",
            "source": sessions[-1].source,
            "data_time": sessions[-1].data_time,
            "execution_date": path.execution_date,
            "execution_price": execution_price,
            "comparable": False,
            "data_quality": "incomplete",
        }
    horizon_session = sessions[horizon - 1]
    window_has_non_comparable_session = any(
        item.comparable is False for item in sessions[:horizon]
    )
    comparable = bool(
        horizon_session.comparable
        and execution_price
        and not path.ambiguous
        and not window_has_non_comparable_session
    )
    return_value = None
    if comparable and execution_price:
        has_early_outcome = (
            path.outcome_session_no is not None and path.outcome_session_no <= horizon
        )
        entry_factor = path.execution_factor or 1.0
        # Execution/outcome prices are actual raw fills.  Convert both to the
        # level-date basis (raw / factor) before the return calculation; a
        # split must not manufacture a loss.
        comparable_entry = execution_price / entry_factor
        if has_early_outcome and path.outcome_price is not None:
            exit_factor = path.outcome_factor or 1.0
            comparable_exit = path.outcome_price / exit_factor
        else:
            comparable_exit = (horizon_session.adjusted or {}).get("close")
        if comparable_exit is not None and comparable_entry > 0:
            gross_return = comparable_exit / comparable_entry - 1.0
            return_value = gross_return - ROUND_TRIP_TRANSACTION_COST_BPS / 10_000.0
    final_status = horizon_session.status if comparable else "incomparable"
    incomparable_reason = None
    if not comparable:
        incomparable_reason = (
            "suspended or otherwise non-comparable session in horizon"
            if window_has_non_comparable_session
            else horizon_session.reason or "price path is not comparable"
        )
    return {
        "settlement_date": horizon_session.trading_date,
        "final_status": final_status,
        "first_trigger": path.first_outcome,
        "return_or_risk": return_value,
        "incomparable_reason": incomparable_reason,
        "source": horizon_session.source,
        "data_time": horizon_session.data_time,
        "execution_date": path.execution_date,
        "execution_price": execution_price,
        "comparable": comparable,
        "data_quality": "complete" if comparable else "incomplete",
    }
