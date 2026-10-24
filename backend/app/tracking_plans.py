"""Create and cancel user tracking plans (V1_SPEC 使用者追蹤計畫).

A plan copies one conditional signal's strategy, versions and levels.  It can
only be made from the latest data date of its stock: a signal of an earlier
date would start tracking on sessions that are already known.  The daily
``plan_tracking`` step (worker.plan_tracking) updates the plan afterwards.

These functions flush but never commit; the caller owns the transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .domain import (
    PLAN_OPEN_STATUSES,
    PLAN_TRACKING_VERSION,
    validate_signal_levels,
)
from .models import DailyCandidate, MarketBar, Signal, StrategyVersion, TrackingPlan
from .tracking import TRACKING_WINDOW_SESSIONS


class PlanRequestError(Exception):
    """A plan request the rules refuse; ``code`` is stable, ``status_code`` is HTTP."""

    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def open_plan_for_signal(db: Session, signal_id: int) -> TrackingPlan | None:
    """The signal's plan that is not cancelled (at most one, by a unique index)."""

    return db.scalar(
        select(TrackingPlan).where(
            TrackingPlan.signal_id == signal_id,
            TrackingPlan.cancelled_at.is_(None),
        )
    )


def create_plan(
    db: Session,
    signal_id: int,
    *,
    daily_candidate_id: int | None = None,
    now: datetime | None = None,
) -> tuple[TrackingPlan, bool]:
    """Return ``(plan, created)``; an existing open plan of the signal is reused.

    Refuses (PlanRequestError) a missing signal or candidate, a candidate of
    another signal, a signal that is not conditional or whose levels are not
    legal, and a signal older than its stock's latest stored bar
    (``stale_signal``).
    """

    signal = db.get(Signal, signal_id)
    if signal is None:
        raise PlanRequestError("signal_not_found", 404)
    candidate = None
    if daily_candidate_id is not None:
        candidate = db.get(DailyCandidate, daily_candidate_id)
        if candidate is None:
            raise PlanRequestError("candidate_not_found", 404)
        if candidate.signal_id != signal.id:
            raise PlanRequestError("candidate_signal_mismatch", 422)
    existing = open_plan_for_signal(db, signal.id)
    if existing is not None:
        return existing, False
    if signal.status != "conditional":
        raise PlanRequestError("signal_not_conditional", 422)
    levels = validate_signal_levels(
        entry_type=signal.entry_type,
        reference_entry=signal.reference_entry,
        breakout_price=signal.breakout_price,
        invalid_price=signal.invalid_price,
        target_1=signal.target_1,
        target_2=signal.target_2,
    )
    pullback_zone_missing = signal.entry_type == "pullback" and (
        signal.pullback_low is None or signal.pullback_high is None
    )
    if not levels.valid or pullback_zone_missing:
        raise PlanRequestError("invalid_levels", 422)
    latest_bar_date = db.scalar(
        select(func.max(MarketBar.trading_date)).where(
            MarketBar.instrument_id == signal.instrument_id
        )
    )
    # Between a day's collect and its analyze the stock already has the new
    # bar but no signal of that date yet, so the previous signals are stale.
    if latest_bar_date is None or signal.signal_date != latest_bar_date:
        raise PlanRequestError("stale_signal", 409)
    strategy = (
        db.get(StrategyVersion, signal.strategy_version_id)
        if signal.strategy_version_id is not None
        else None
    )
    created_at = now or datetime.utcnow()
    plan = TrackingPlan(
        instrument_id=signal.instrument_id,
        signal_id=signal.id,
        daily_candidate_id=candidate.id if candidate else None,
        source_kind="candidate" if candidate else "stock",
        strategy=strategy.name if strategy else signal.entry_type,
        strategy_version_id=signal.strategy_version_id,
        formula_version=strategy.formula_version if strategy else None,
        score_version=candidate.score_version if candidate else None,
        tracking_version=PLAN_TRACKING_VERSION,
        plan_date=signal.signal_date,
        earliest_execution_date=signal.earliest_execution_date,
        entry_type=signal.entry_type,
        reference_entry=signal.reference_entry,
        pullback_low=signal.pullback_low,
        pullback_high=signal.pullback_high,
        breakout_price=signal.breakout_price,
        invalid_price=signal.invalid_price,
        target_1=signal.target_1,
        target_2=signal.target_2,
        window_sessions=TRACKING_WINDOW_SESSIONS,
        status="pending",
        status_reason="awaiting_entry",
        sessions_observed=0,
        data_quality="complete",
        created_at=created_at,
        updated_at=created_at,
    )
    nested = db.begin_nested()
    db.add(plan)
    try:
        nested.commit()
    except IntegrityError:
        # Another request created the signal's plan first.
        nested.rollback()
        existing = open_plan_for_signal(db, signal.id)
        if existing is None:
            raise
        return existing, False
    return plan, True


def cancel_plan(
    db: Session, plan_id: int, *, now: datetime | None = None
) -> TrackingPlan:
    """Cancel an open plan; its sessions and simulated values are kept.

    Cancelling a cancelled plan returns it unchanged; a plan that already
    ended (``plan_already_closed``) cannot be cancelled.
    """

    plan = db.get(TrackingPlan, plan_id)
    if plan is None:
        raise PlanRequestError("plan_not_found", 404)
    if plan.status == "cancelled":
        return plan
    if plan.status not in PLAN_OPEN_STATUSES:
        raise PlanRequestError("plan_already_closed", 409)
    cancelled_at = now or datetime.utcnow()
    plan.status_reason = f"cancelled_while_{plan.status}"
    plan.status = "cancelled"
    plan.cancelled_at = cancelled_at
    plan.updated_at = cancelled_at
    db.flush()
    return plan
