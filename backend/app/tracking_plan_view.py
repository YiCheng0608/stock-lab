"""Read model of the user tracking plans (``/api/tracking``, V1_SPEC 使用者追蹤計畫).

Only reads ``tracking_plans`` / ``tracking_plan_sessions`` written by
``app.tracking_plans`` and ``worker.plan_tracking``; every fill and result is
a simulation under the tracking assumptions in ``meta``, never a real trade.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from .candidate_view import _levels
from .domain import PLAN_OPEN_STATUSES, PLAN_TRACKING_VERSION
from .models import Instrument, TrackingPlan, TrackingPlanSession
from .tracking import (
    EXECUTION_SLIPPAGE_BPS,
    ROUND_TRIP_TRANSACTION_COST_BPS,
    TRACKING_WINDOW_SESSIONS,
)

PlanScope = Literal["open", "closed", "all"]


def _instant(value: datetime | None) -> str | None:
    # Stored UTC-naive; the instant carries its offset.
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def _day(value: Any) -> str | None:
    return value.isoformat() if value else None


def plan_dict(db: Session, plan: TrackingPlan) -> dict[str, Any]:
    instrument = db.get(Instrument, plan.instrument_id)
    return {
        "id": plan.id,
        "instrument": {
            "id": instrument.id,
            "exchange": instrument.exchange,
            "symbol": instrument.symbol,
            "name": instrument.name,
        },
        "source_kind": plan.source_kind,
        "signal_id": plan.signal_id,
        "daily_candidate_id": plan.daily_candidate_id,
        "strategy": plan.strategy,
        "versions": {
            "strategy_version_id": plan.strategy_version_id,
            "formula_version": plan.formula_version,
            "score_version": plan.score_version,
            "tracking_version": plan.tracking_version,
        },
        "plan_date": _day(plan.plan_date),
        # The same level fields as a candidate card (entry zone, RR).
        "levels": _levels(plan),
        "window_sessions": plan.window_sessions,
        "status": plan.status,
        "status_reason": plan.status_reason,
        "open": plan.status in PLAN_OPEN_STATUSES,
        "sessions_observed": plan.sessions_observed,
        "last_session_date": _day(plan.last_session_date),
        "execution_date": _day(plan.execution_date),
        "execution_price": plan.execution_price,
        "outcome_date": _day(plan.outcome_date),
        "outcome_price": plan.outcome_price,
        "result_return": plan.result_return,
        "result_comparable": plan.result_comparable,
        "incomparable_reason": plan.incomparable_reason,
        "data_quality": plan.data_quality,
        "simulated": True,
        "created_at": _instant(plan.created_at),
        "updated_at": _instant(plan.updated_at),
        "cancelled_at": _instant(plan.cancelled_at),
    }


def session_dict(row: TrackingPlanSession) -> dict[str, Any]:
    return {
        "session_date": _day(row.session_date),
        "session_no": row.session_no,
        "status": row.status,
        "reason": row.reason,
        "ohlc": row.ohlc_json,
        "adjusted_ohlc": row.adjusted_ohlc_json,
        "entry_trigger": row.entry_trigger,
        "target_trigger": row.target_trigger,
        "invalid_trigger": row.invalid_trigger,
        "suspended": row.suspended,
        "comparable": row.comparable,
        "execution_price": row.execution_price,
        "source": row.source,
        "data_time": row.data_time,
    }


def tracking_meta() -> dict[str, Any]:
    return {
        "tracking_version": PLAN_TRACKING_VERSION,
        "window_sessions": TRACKING_WINDOW_SESSIONS,
        "slippage_bps": EXECUTION_SLIPPAGE_BPS,
        "round_trip_cost_bps": ROUND_TRIP_TRANSACTION_COST_BPS,
        "simulated": True,
    }


def plan_list_query(scope: PlanScope):
    """The plans of ``scope`` and their order: open first, then the latest ended.

    Open plans by plan date; ended (or cancelled) ones by the date they ended,
    else the last tracked session, else the plan date; newest first.
    """

    is_open = TrackingPlan.status.in_(PLAN_OPEN_STATUSES)
    query = select(TrackingPlan)
    if scope == "open":
        query = query.where(is_open)
    elif scope == "closed":
        query = query.where(~is_open)
    order_by = (
        case((is_open, 0), else_=1),
        desc(
            case(
                (is_open, TrackingPlan.plan_date),
                else_=func.coalesce(
                    TrackingPlan.outcome_date,
                    TrackingPlan.last_session_date,
                    TrackingPlan.plan_date,
                ),
            )
        ),
        desc(TrackingPlan.id),
    )
    return query, order_by


def plan_summary(db: Session) -> dict[str, int]:
    counts = dict(
        db.execute(
            select(
                TrackingPlan.status.in_(PLAN_OPEN_STATUSES),
                func.count(TrackingPlan.id),
            ).group_by(TrackingPlan.status.in_(PLAN_OPEN_STATUSES))
        ).all()
    )
    return {"open": counts.get(True, 0), "closed": counts.get(False, 0)}


def plan_sessions(db: Session, plan: TrackingPlan) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(TrackingPlanSession)
        .where(TrackingPlanSession.plan_id == plan.id)
        .order_by(TrackingPlanSession.session_date)
    ).all()
    return [session_dict(row) for row in rows]
