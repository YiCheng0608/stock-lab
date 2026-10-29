"""Daily update of the user tracking plans (V1_SPEC 使用者追蹤計畫, plan_tracking_v1).

The ``plan_tracking`` step of ``worker.cli daily`` (after a successful collect;
it needs no analyze because a plan keeps its own copy of the levels) and
``worker.cli track-plans``.  Every open plan is recomputed from its plan date
with the shared tracking rules (``app.tracking.track_path``, the same as the
system signal tracking): the window is the stock's own first 20 bars after the
plan date, as for a signal.  A stock that still has fewer bars once the market
has had MARKET_SESSION_LIMIT sessions after the plan date ends as
``incomparable`` (``insufficient_sessions``).  No bar after the target date, or
after that last market session, is read, so the same stored data gives the
same result whichever day the step runs and however many daily runs were
missed.  The same target date gives the same rows: values are written, and
``updated_at`` moved, only when they change.  An ended or cancelled plan is never recomputed, and a
recomputed status the plan may not move to (a corrected bar would take it
back) keeps the stored state and marks ``transition_conflict``.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain import PLAN_OPEN_STATUSES, validate_plan_status_transition
from app.models import MarketBar, TrackingPlan, TrackingPlanSession
from app.tracking import AMBIGUOUS_REASON, TrackPath, settle, track_path
from app.tracking_plans import claim_plan
from worker import pipeline

TRANSITION_CONFLICT = "transition_conflict"
# Market sessions after the plan date within which the stock must have its 20
# bars (twice the window); later bars are never read.
MARKET_SESSION_LIMIT = 40


def _assign(row: Any, values: dict[str, Any]) -> bool:
    """Set only the values that differ; True when anything changed."""

    changed = False
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    return changed


def _market_dates_after(
    db: Session, start_after: date, cutoff: date, limit: int
) -> list[date]:
    """The first ``limit`` market sessions (any stored bar) after ``start_after``."""

    return db.scalars(
        select(MarketBar.trading_date)
        .where(MarketBar.trading_date > start_after, MarketBar.trading_date <= cutoff)
        .distinct()
        .order_by(MarketBar.trading_date)
        .limit(limit)
    ).all()


def plan_outcome(
    path: TrackPath, bars: list[MarketBar], window: int, market_limit_reached: bool
) -> dict[str, Any]:
    """The plan's status and simulated result for one tracked path.

    ``market_limit_reached``: the market has had MARKET_SESSION_LIMIT sessions
    after the plan date (up to the target date).
    """

    sessions = path.sessions
    count = len(sessions)
    result: dict[str, Any] = {
        "sessions_observed": count,
        "last_session_date": sessions[-1].trading_date if sessions else None,
        "execution_date": path.execution_date if path.executed else None,
        "execution_price": path.execution_price if path.executed else None,
        "outcome_date": None,
        "outcome_price": None,
        "result_return": None,
        "result_comparable": None,
        "incomparable_reason": None,
    }
    settled_at: int | None = None
    if path.ambiguous:
        first = next(item for item in sessions if item.status == "ambiguous")
        result.update(
            status="incomparable",
            status_reason="same_session_stop_and_target",
            outcome_date=first.trading_date,
            result_comparable=False,
            incomparable_reason=AMBIGUOUS_REASON,
        )
    elif path.first_outcome == "target_1_hit":
        result.update(status="target_hit", status_reason="target_1_touched")
        settled_at = path.outcome_session_no
    elif path.first_outcome == "invalidated":
        result.update(status="invalidated", status_reason="invalid_price_touched")
        settled_at = path.outcome_session_no
    elif count >= window and path.executed:
        result.update(status="closed", status_reason="window_ended_after_entry")
        settled_at = window
    elif count >= window:
        result.update(status="expired", status_reason="window_ended_without_entry")
    elif market_limit_reached:
        # Long suspension, delisting or missing bars: the stock did not get
        # its window within the market sessions allowed.
        result.update(
            status="incomparable",
            status_reason="insufficient_sessions",
            result_comparable=False,
            incomparable_reason=(
                f"only {count} of {window} bars within {MARKET_SESSION_LIMIT} "
                "market sessions"
            ),
        )
    elif path.executed:
        result.update(status="triggered", status_reason="entry_filled")
    else:
        result.update(status="pending", status_reason="awaiting_entry")
    if settled_at is not None:
        settlement = settle(path, settled_at)
        exit_session = sessions[settled_at - 1]
        result.update(
            outcome_date=exit_session.trading_date,
            outcome_price=(
                path.outcome_price
                if result["status"] in {"target_hit", "invalidated"}
                else bars[settled_at - 1].close
            ),
            result_return=settlement["return_or_risk"],
            result_comparable=settlement["comparable"],
            incomparable_reason=settlement["incomparable_reason"],
        )
    non_comparable = path.ambiguous or any(not item.comparable for item in sessions)
    result["data_quality"] = "incomplete" if non_comparable else "complete"
    return result


def _write_sessions(
    db: Session, plan: TrackingPlan, bars: list[MarketBar], path: TrackPath
) -> int:
    """Upsert the plan's session rows; returns how many were added or changed."""

    stored = {
        row.session_date: row
        for row in db.scalars(
            select(TrackingPlanSession).where(TrackingPlanSession.plan_id == plan.id)
        ).all()
    }
    written = 0
    for bar, session in zip(bars, path.sessions):
        values = {
            "session_no": session.session_no,
            "status": session.status,
            "reason": session.reason,
            "ohlc_json": {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "adj_close": bar.adj_close,
            },
            "adjusted_ohlc_json": session.adjusted,
            "entry_trigger": session.breakout_trigger or session.pullback_trigger,
            "target_trigger": session.target_trigger,
            "invalid_trigger": session.invalid_trigger,
            "suspended": session.suspended,
            "comparable": session.comparable,
            "execution_price": session.execution_price,
            "source": session.source,
            "data_time": session.data_time,
        }
        row = stored.pop(session.trading_date, None)
        if row is None:
            db.add(
                TrackingPlanSession(
                    plan_id=plan.id, session_date=session.trading_date, **values
                )
            )
            written += 1
        elif _assign(row, values):
            written += 1
    # A bar that is no longer stored is no longer a tracked session.
    for row in stored.values():
        db.delete(row)
        written += 1
    return written


def track_plan(
    db: Session,
    plan: TrackingPlan,
    cutoff: date,
    *,
    now: datetime,
    market_limit_reached: bool,
) -> tuple[str | None, int]:
    """Update one open plan with the bars up to ``cutoff``.

    Returns ``(transition or None, session rows written)``.  Nothing is
    written when the stored plan is no longer the one read (a cancel from
    the API committed meanwhile, #253): ``claim_plan`` checks that and holds
    the write lock until the caller commits.
    """

    bars, tracked = pipeline._tracking_inputs(
        db, plan.instrument_id, plan.plan_date, evaluation_cutoff=cutoff
    )
    path = track_path(pipeline.track_levels(plan), tracked)
    outcome = plan_outcome(path, bars, plan.window_sessions, market_limit_reached)
    previous = plan.status
    if not claim_plan(db, plan):
        return None, 0
    if not validate_plan_status_transition(previous, outcome["status"]).valid:
        conflict = {
            "data_quality": TRANSITION_CONFLICT,
            "status_reason": f"{TRANSITION_CONFLICT}:{previous}->{outcome['status']}",
        }
        if _assign(plan, conflict):
            plan.updated_at = now
        return None, 0
    written = _write_sessions(db, plan, bars, path)
    if _assign(plan, outcome) or written:
        plan.updated_at = now
    transition = f"{previous}->{plan.status}" if plan.status != previous else None
    return transition, written


def track_open_plans(
    db: Session, target: date, *, now: datetime | None = None
) -> dict[str, Any]:
    """Update every open plan with the bars up to ``target`` (caller commits).

    A plan reads no bar after the MARKET_SESSION_LIMIT-th market session after
    its plan date either.
    """

    stamp = now or datetime.utcnow()
    plans = db.scalars(
        select(TrackingPlan)
        .where(TrackingPlan.status.in_(PLAN_OPEN_STATUSES))
        .order_by(TrackingPlan.id)
    ).all()
    transitions: Counter[str] = Counter()
    written = 0
    conflicts = 0
    market_dates: dict[date, list[date]] = {}
    for plan in plans:
        if plan.plan_date not in market_dates:
            market_dates[plan.plan_date] = _market_dates_after(
                db, plan.plan_date, target, MARKET_SESSION_LIMIT
            )
        dates = market_dates[plan.plan_date]
        limit_reached = len(dates) >= MARKET_SESSION_LIMIT
        transition, rows = track_plan(
            db,
            plan,
            dates[MARKET_SESSION_LIMIT - 1] if limit_reached else target,
            now=stamp,
            market_limit_reached=limit_reached,
        )
        written += rows
        if transition:
            transitions[transition] += 1
        if plan.data_quality == TRANSITION_CONFLICT:
            conflicts += 1
    db.flush()
    return {
        "status": "success",
        "date": target.isoformat(),
        "plans_checked": len(plans),
        "sessions_written": written,
        "transition_conflicts": conflicts,
        "transitions": dict(sorted(transitions.items())),
        "records": written,
    }


def run_plan_tracking(target: date | None = None) -> dict[str, Any]:
    """Update the open plans for ``target`` (default: the latest stored session)."""

    # pipeline.SessionLocal, like the other daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        day = target or db.scalar(select(func.max(MarketBar.trading_date)))
        if day is None:
            return {
                "status": "no_data",
                "reason": "no_market_bars",
                "plans_checked": 0,
                "sessions_written": 0,
                "records": 0,
            }
        result = track_open_plans(db, day)
        db.commit()
    return result
