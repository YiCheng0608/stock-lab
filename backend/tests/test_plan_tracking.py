"""User tracking plans (V1_SPEC 使用者追蹤計畫): shared rules, creation and daily update."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, enable_sqlite_foreign_keys
from app.domain import (
    PLAN_OPEN_STATUSES,
    PLAN_STATUS_TRANSITIONS,
    validate_plan_status_transition,
)
from app.models import (
    CandidateRun,
    CorporateAction,
    DailyCandidate,
    Instrument,
    MarketBar,
    Signal,
    SignalEvaluation,
    TrackingPlan,
    TrackingPlanSession,
)
from app.tracking import (
    ROUND_TRIP_TRANSACTION_COST_BPS,
    TrackBar,
    TrackLevels,
    settle,
    track_path,
)
from app.tracking_plans import PlanRequestError, cancel_plan, create_plan
from worker import pipeline, plan_tracking
from worker.plan_tracking import run_plan_tracking, track_open_plans

PLAN_DAY = date(2026, 9, 1)  # a Tuesday
CREATED = datetime(2026, 9, 1, 13, 0)
RUN_AT = datetime(2026, 9, 30, 13, 0)
COST = ROUND_TRIP_TRANSACTION_COST_BPS / 10_000.0
BUY = 1.0005  # 5 bps adverse fill
SELL = 0.9995

# (open, high, low, close) against breakout 100, invalid 98, target 103.2.
FLAT = (99.0, 99.5, 98.5, 99.0)  # neither the entry nor the invalid price
FILL = (99.5, 100.5, 99.2, 100.2)  # reaches the breakout price only
INSIDE = (100.0, 101.0, 99.0, 101.0)  # after a fill: no exit
TARGET = (101.0, 103.5, 100.5, 103.0)
STOP = (99.0, 99.5, 97.5, 98.0)
BOTH = (100.0, 104.0, 97.0, 100.0)  # stop and target in the same session

LEVELS = TrackLevels(
    entry_type="breakout",
    breakout_price=100.0,
    pullback_low=None,
    pullback_high=None,
    invalid_price=98.0,
    target_1=103.2,
)


def sessions_after(day: date, count: int) -> list[date]:
    days, cursor = [], day
    while len(days) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    return days


def track_bar(day, ohlc, *, factor=1.0, suspended=False, gap=False, volume=1000):
    o, h, low, c = ohlc
    return TrackBar(
        trading_date=day,
        open=o,
        high=h,
        low=low,
        close=c,
        adj_close=c,
        volume=volume,
        is_suspended=suspended,
        source="fixture-bars",
        data_time=None,
        factor=factor,
        action_applied=factor != 1.0,
        suspension_gap=gap,
    )


def path_of(*ohlcs, levels=LEVELS, **kwargs):
    days = sessions_after(PLAN_DAY, len(ohlcs))
    return track_path(levels, [track_bar(d, o, **kwargs) for d, o in zip(days, ohlcs)])


# ---- app.tracking: the shared session rules ----


def test_a_path_that_never_reaches_the_entry_is_not_triggered():
    path = path_of(FLAT, FLAT)
    assert [s.status for s in path.sessions] == ["not_triggered", "not_triggered"]
    assert not path.executed and path.execution_price is None
    # The invalid price only counts after a fill.
    assert not path_of(STOP).executed


def test_a_breakout_fills_at_the_level_or_the_gap_open_with_slippage():
    at_level = path_of(FLAT, FILL)
    assert [s.status for s in at_level.sessions] == ["not_triggered", "active"]
    assert at_level.execution_date == sessions_after(PLAN_DAY, 2)[1]
    assert at_level.execution_price == pytest.approx(100.0 * BUY)
    gap_open = path_of((101.0, 102.0, 100.8, 101.5))
    assert gap_open.execution_price == pytest.approx(101.0 * BUY)


def test_a_pullback_fills_at_the_open_inside_the_zone_or_the_nearest_edge():
    zone = TrackLevels("pullback", None, 99.0, 101.0, 97.0, 104.0)
    assert path_of((100.0, 100.5, 99.5, 100.2), levels=zone).execution_price == (
        pytest.approx(100.0 * BUY)
    )
    assert path_of((102.0, 102.5, 100.5, 101.0), levels=zone).execution_price == (
        pytest.approx(101.0 * BUY)
    )
    assert not path_of((102.0, 103.0, 101.5, 102.0), levels=zone).executed


def test_the_first_outcome_is_kept_by_later_sessions():
    target = path_of(FILL, TARGET, STOP)
    assert [s.status for s in target.sessions] == [
        "active",
        "target_1_hit",
        "target_1_hit",
    ]
    assert target.first_outcome == "target_1_hit" and target.outcome_session_no == 2
    assert target.outcome_price == pytest.approx(103.2 * SELL)
    stop = path_of(FILL, STOP, TARGET)
    assert [s.status for s in stop.sessions] == ["active", "invalidated", "invalidated"]
    assert stop.outcome_price == pytest.approx(98.0 * SELL)


def test_stop_and_target_in_one_session_is_ambiguous():
    path = path_of(FILL, BOTH, TARGET)
    assert [s.status for s in path.sessions] == ["active", "ambiguous", "ambiguous"]
    assert path.ambiguous and path.first_outcome is None
    assert [s.comparable for s in path.sessions] == [True, False, False]


def test_a_suspended_session_infers_no_trigger():
    days = sessions_after(PLAN_DAY, 3)
    bars = [
        track_bar(days[0], FILL, suspended=True),
        track_bar(days[1], (100.0, 100.0, 100.0, 100.0), volume=0),  # zero-volume flat
        track_bar(days[2], FILL, gap=True),  # an official interval hid a session
    ]
    path = track_path(LEVELS, bars)
    assert [s.status for s in path.sessions] == ["suspended"] * 3
    assert not path.executed and not any(s.comparable for s in path.sessions)
    assert "missing market session" in path.sessions[2].reason


def test_a_split_factor_scales_the_levels_and_keeps_the_return_basis():
    # 2-for-1 split before the first session: raw levels are halved.
    path = path_of((49.8, 50.3, 49.6, 50.1), (50.5, 51.7, 50.2, 51.5), factor=0.5)
    assert path.execution_price == pytest.approx(50.0 * BUY)
    assert path.first_outcome == "target_1_hit"
    result = settle(path, 2)
    assert result["return_or_risk"] == pytest.approx(
        (103.2 * SELL) / (100.0 * BUY) - 1 - COST
    )


def test_settle_nets_the_cost_and_marks_short_or_suspended_windows_incomparable():
    path = path_of(FILL, INSIDE, TARGET)
    early = settle(path, 3)
    assert early["comparable"] and early["final_status"] == "target_1_hit"
    assert early["return_or_risk"] == pytest.approx(
        (103.2 * SELL) / (100.0 * BUY) - 1 - COST
    )
    at_close = settle(path, 2)
    assert at_close["return_or_risk"] == pytest.approx(101.0 / (100.0 * BUY) - 1 - COST)
    short = settle(path, 5)
    assert short["final_status"] == "incomparable" and short["return_or_risk"] is None
    days = sessions_after(PLAN_DAY, 2)
    suspended = track_path(
        LEVELS, [track_bar(days[0], FILL), track_bar(days[1], FLAT, suspended=True)]
    )
    assert settle(suspended, 2)["incomparable_reason"] == (
        "suspended or otherwise non-comparable session in horizon"
    )


# ---- app.domain: plan_tracking_v1 transitions ----


def test_plan_transitions_only_move_forward():
    assert PLAN_OPEN_STATUSES == {"pending", "triggered"}
    for terminal in ("target_hit", "invalidated", "incomparable", "expired", "closed"):
        assert PLAN_STATUS_TRANSITIONS[terminal] == frozenset()
        assert not validate_plan_status_transition(terminal, "pending").valid
    assert PLAN_STATUS_TRANSITIONS["cancelled"] == frozenset()
    assert validate_plan_status_transition("pending", "target_hit").valid
    assert validate_plan_status_transition("triggered", "triggered").valid
    assert validate_plan_status_transition("triggered", "pending").errors == (
        "illegal_plan_status_transition",
    )
    assert validate_plan_status_transition("pending", "closed").valid
    assert not validate_plan_status_transition("triggered", "expired").valid
    assert validate_plan_status_transition("unknown", "pending").errors == (
        "unsupported_current_status",
    )


# ---- database: creation, daily update, cancellation ----


@contextmanager
def fresh_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        session.info["strategies"] = pipeline._ensure_strategies(session)
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def db():
    with fresh_session() as session:
        yield session


def stock(db, symbol="9101"):
    instrument = Instrument(
        exchange="TWSE", symbol=symbol, name=f"名{symbol}", status="active"
    )
    db.add(instrument)
    db.flush()
    add_bars(db, instrument, [(PLAN_DAY, FLAT)])
    return instrument


def add_bars(db, instrument, rows, *, suspended=False):
    for day, (o, h, low, c) in rows:
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=day,
                open=o,
                high=h,
                low=low,
                close=c,
                adj_close=c,
                volume=1000,
                turnover=c * 1000,
                source="fixture-bars",
                is_suspended=suspended,
            )
        )
    db.flush()


def follow(db, instrument, *ohlcs, start=PLAN_DAY):
    """Store one bar per session after ``start``; returns their dates."""

    days = sessions_after(start, len(ohlcs))
    add_bars(db, instrument, list(zip(days, ohlcs)))
    return days


def signal(db, instrument, *, status="conditional", day=PLAN_DAY, **levels):
    version = db.info["strategies"]["breakout_v1"]
    values = {
        "breakout_price": 100.0,
        "invalid_price": 98.0,
        "target_1": 103.2,
        "target_2": 106.0,
    }
    values.update(levels)
    row = Signal(
        signal_key=f"analysis-TWSE-{instrument.symbol}-{day.isoformat()}-breakout",
        signal_date=day,
        instrument_id=instrument.id,
        strategy_version_id=version.id,
        status=status,
        entry_type="breakout",
        earliest_execution_date=sessions_after(day, 1)[0],
        source_report="fixture-bars",
        **values,
    )
    db.add(row)
    db.flush()
    return row


def candidate(db, instrument, sig):
    run = CandidateRun(trading_date=sig.signal_date, score_version="candidate_score_v1")
    db.add(run)
    db.flush()
    row = DailyCandidate(
        candidate_run_id=run.id,
        trading_date=sig.signal_date,
        instrument_id=instrument.id,
        signal_id=sig.id,
        strategy="breakout_v1",
        score_version="candidate_score_v1",
        total_score=80.0,
        weight_coverage=1.0,
        rank=1,
        data_as_of=sig.signal_date,
    )
    db.add(row)
    db.flush()
    return row


def new_plan(db, symbol="9101", **levels):
    instrument = stock(db, symbol)
    plan, created = create_plan(db, signal(db, instrument, **levels).id, now=CREATED)
    assert created
    db.commit()
    return instrument, plan


def run(db, target):
    result = track_open_plans(db, target, now=RUN_AT)
    db.commit()
    return result


def session_rows(db, plan):
    return db.scalars(
        select(TrackingPlanSession)
        .where(TrackingPlanSession.plan_id == plan.id)
        .order_by(TrackingPlanSession.session_date)
    ).all()


def test_a_plan_copies_the_signal_levels_and_versions(db):
    instrument = stock(db)
    sig = signal(db, instrument)
    row = candidate(db, instrument, sig)
    plan, created = create_plan(db, sig.id, daily_candidate_id=row.id, now=CREATED)
    assert created
    version = db.info["strategies"]["breakout_v1"]
    assert (
        plan.source_kind,
        plan.strategy,
        plan.strategy_version_id,
        plan.formula_version,
        plan.score_version,
        plan.tracking_version,
    ) == (
        "candidate",
        "breakout_v1",
        version.id,
        version.formula_version,
        "candidate_score_v1",
        "plan_tracking_v1",
    )
    assert (plan.plan_date, plan.earliest_execution_date) == (
        PLAN_DAY,
        sessions_after(PLAN_DAY, 1)[0],
    )
    assert (
        plan.breakout_price,
        plan.invalid_price,
        plan.target_1,
        plan.target_2,
    ) == (100.0, 98.0, 103.2, 106.0)
    assert (plan.status, plan.window_sessions, plan.created_at) == (
        "pending",
        20,
        CREATED,
    )
    # A later rewrite of the signal leaves the snapshot alone.
    sig.target_1 = 110.0
    db.flush()
    db.refresh(plan)
    assert plan.target_1 == 103.2


def test_adding_the_same_signal_again_returns_its_open_plan(db):
    instrument = stock(db)
    sig = signal(db, instrument)
    first, _ = create_plan(db, sig.id, now=CREATED)
    again, created = create_plan(db, sig.id, now=CREATED)
    assert (again.id, created) == (first.id, False)
    assert first.source_kind == "stock" and first.daily_candidate_id is None
    cancel_plan(db, first.id, now=CREATED)
    renewed, created = create_plan(db, sig.id, now=CREATED)
    assert created and renewed.id != first.id
    assert db.scalar(
        select(TrackingPlan).where(TrackingPlan.id == first.id)
    ).status == ("cancelled")


@pytest.mark.parametrize(
    "case, code, status_code",
    [
        ("missing", "signal_not_found", 404),
        ("observation", "signal_not_conditional", 422),
        ("bad_levels", "invalid_levels", 422),
        ("stale", "stale_signal", 409),
        ("other_candidate", "candidate_signal_mismatch", 422),
        ("missing_candidate", "candidate_not_found", 404),
    ],
)
def test_a_plan_needs_the_latest_conditional_signal_with_legal_levels(
    db, case, code, status_code
):
    instrument = stock(db)
    sig = signal(
        db,
        instrument,
        status="observation" if case == "observation" else "conditional",
        **({"invalid_price": 101.0} if case == "bad_levels" else {}),
    )
    signal_id, candidate_id = sig.id, None
    if case == "missing":
        signal_id = sig.id + 100
    if case == "stale":
        # 18:30 collect stored the next bar; 21:30 analyze has not written
        # that day's signal yet, so the shown signal is an earlier date's.
        follow(db, instrument, FLAT)
    if case == "other_candidate":
        other = signal(db, stock(db, "9102"))
        candidate_id = candidate(db, instrument, other).id
    if case == "missing_candidate":
        candidate_id = 999
    with pytest.raises(PlanRequestError) as error:
        create_plan(db, signal_id, daily_candidate_id=candidate_id, now=CREATED)
    assert (error.value.code, error.value.status_code) == (code, status_code)
    assert db.scalars(select(TrackingPlan)).all() == []


def test_without_any_plan_the_step_succeeds_with_zero_rows(db):
    assert run(db, PLAN_DAY) == {
        "status": "success",
        "date": PLAN_DAY.isoformat(),
        "plans_checked": 0,
        "sessions_written": 0,
        "transition_conflicts": 0,
        "transitions": {},
        "records": 0,
    }


def test_a_new_plan_waits_without_sessions_and_then_is_triggered(db):
    instrument, plan = new_plan(db)
    assert run(db, PLAN_DAY)["transitions"] == {}
    assert (plan.status, plan.sessions_observed, plan.updated_at) == (
        "pending",
        0,
        CREATED,
    )
    days = follow(db, instrument, FLAT, FILL)
    result = run(db, days[1])
    assert result["transitions"] == {"pending->triggered": 1}
    assert result["sessions_written"] == 2
    assert (plan.status, plan.status_reason) == ("triggered", "entry_filled")
    assert (plan.execution_date, plan.execution_price) == (
        days[1],
        pytest.approx(100.0 * BUY),
    )
    assert (plan.sessions_observed, plan.last_session_date) == (2, days[1])
    assert plan.result_return is None and plan.outcome_date is None
    rows = session_rows(db, plan)
    assert [(r.session_no, r.status, r.entry_trigger) for r in rows] == [
        (1, "not_triggered", False),
        (2, "active", True),
    ]
    assert rows[1].ohlc_json["high"] == 100.5 and rows[1].comparable


def test_target_and_invalid_outcomes_end_the_plan_with_a_simulated_result(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FILL, INSIDE, TARGET)
    assert run(db, days[-1])["transitions"] == {"pending->target_hit": 1}
    assert (plan.status, plan.outcome_date) == ("target_hit", days[2])
    assert plan.outcome_price == pytest.approx(103.2 * SELL)
    assert plan.result_comparable is True
    assert plan.result_return == pytest.approx(
        (103.2 * SELL) / (100.0 * BUY) - 1 - COST
    )

    other, stopped = new_plan(db, "9102")
    days = follow(db, other, FILL, STOP)
    assert run(db, days[-1])["transitions"] == {"pending->invalidated": 1}
    assert (stopped.status, stopped.status_reason) == (
        "invalidated",
        "invalid_price_touched",
    )
    assert stopped.result_return == pytest.approx(
        (98.0 * SELL) / (100.0 * BUY) - 1 - COST
    )


def test_a_fill_and_its_target_in_one_session_jump_straight_to_target_hit(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, (100.0, 103.5, 99.5, 103.0))
    assert run(db, days[0])["transitions"] == {"pending->target_hit": 1}
    assert plan.execution_date == plan.outcome_date == days[0]


def test_twenty_sessions_without_a_fill_expire_and_with_a_fill_close(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, *[FLAT] * 19)
    run(db, days[-1])
    assert (plan.status, plan.sessions_observed) == ("pending", 19)
    days = follow(db, instrument, FLAT, start=days[-1])
    assert run(db, days[0])["transitions"] == {"pending->expired": 1}
    assert (plan.status, plan.status_reason) == (
        "expired",
        "window_ended_without_entry",
    )
    assert plan.result_return is None and plan.result_comparable is None

    other, closed = new_plan(db, "9102")
    days = follow(db, other, FILL, *[INSIDE] * 19)
    assert run(db, days[-1])["transitions"] == {"pending->closed": 1}
    assert (closed.status, closed.outcome_date, closed.outcome_price) == (
        "closed",
        days[19],
        101.0,
    )
    assert closed.result_return == pytest.approx(101.0 / (100.0 * BUY) - 1 - COST)
    # An ended plan is not tracked past its window.
    later = follow(db, other, STOP, start=days[-1])
    assert run(db, later[0])["plans_checked"] == 0
    assert closed.status == "closed" and len(session_rows(db, closed)) == 20


def test_stop_and_target_in_one_session_make_the_plan_incomparable(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FILL, BOTH)
    assert run(db, days[-1])["transitions"] == {"pending->incomparable": 1}
    assert (plan.status, plan.status_reason, plan.outcome_date) == (
        "incomparable",
        "same_session_stop_and_target",
        days[1],
    )
    assert plan.result_comparable is False and plan.result_return is None
    assert plan.data_quality == "incomplete"


def test_a_suspension_keeps_the_status_and_makes_the_result_incomparable(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FILL)
    run(db, days[0])
    suspended_day = sessions_after(days[0], 1)
    add_bars(db, instrument, [(suspended_day[0], TARGET)], suspended=True)
    assert run(db, suspended_day[0])["transitions"] == {}
    assert plan.status == "triggered" and plan.data_quality == "incomplete"
    assert session_rows(db, plan)[-1].status == "suspended"
    days = follow(db, instrument, TARGET, start=suspended_day[0])
    run(db, days[0])
    assert plan.status == "target_hit"
    assert (plan.result_comparable, plan.result_return) == (False, None)
    assert plan.incomparable_reason == (
        "suspended or otherwise non-comparable session in horizon"
    )


def market_days(db, count):
    """Another stock trades every session; returns the market session dates."""

    return follow(db, stock(db, "9999"), *[FLAT] * count)


def test_the_window_is_the_stock_own_bars_not_the_market_sessions(db):
    instrument, plan = new_plan(db)
    days = market_days(db, 21)
    # The stock has no bar on the 10th market session (no suspension event).
    stored = [day for i, day in enumerate(days) if i != 9]
    add_bars(db, instrument, [(stored[0], FILL)] + [(d, INSIDE) for d in stored[1:]])
    run(db, days[19])
    assert (plan.status, plan.sessions_observed) == ("triggered", 19)
    assert run(db, days[20])["transitions"] == {"triggered->closed": 1}
    assert (plan.outcome_date, plan.sessions_observed) == (days[20], 20)
    assert plan.result_return == pytest.approx(101.0 / (100.0 * BUY) - 1 - COST)


def plan_result(run_days, build):
    """The plan and its sessions after running the step on ``run_days``."""

    with fresh_session() as db:
        _instrument, plan = new_plan(db)
        days = build(db, _instrument)
        for index in run_days:
            run(db, days[index])
        return snapshot(db, plan)


def one_missing_bar(db, instrument):
    days = market_days(db, 25)
    stored = [day for i, day in enumerate(days) if i != 9]
    add_bars(db, instrument, [(stored[0], FILL)] + [(d, INSIDE) for d in stored[1:]])
    return days


def nineteen_bars_in_forty_sessions(db, instrument):
    days = market_days(db, 45)
    add_bars(db, instrument, [(d, FLAT) for d in days[:19]] + [(days[44], FLAT)])
    return days


@pytest.mark.parametrize(
    "build, skipped, status",
    [
        (one_missing_bar, (19, 20), "closed"),
        (nineteen_bars_in_forty_sessions, tuple(range(4, 44)), "incomparable"),
    ],
)
def test_missed_daily_runs_give_the_same_result(build, skipped, status):
    sessions = 45 if build is nineteen_bars_in_forty_sessions else 25
    every_day = plan_result(range(sessions), build)
    with_gaps = plan_result([i for i in range(sessions) if i not in skipped], build)
    assert every_day == with_gaps
    assert every_day[0]["status"] == status


def test_too_few_bars_within_forty_market_sessions_is_incomparable(db):
    instrument, plan = new_plan(db)
    days = market_days(db, 45)
    add_bars(db, instrument, [(d, FLAT) for d in days[:19]] + [(days[44], FLAT)])
    run(db, days[38])
    assert (plan.status, plan.sessions_observed) == ("pending", 19)
    assert run(db, days[39])["transitions"] == {"pending->incomparable": 1}
    assert (plan.status_reason, plan.result_comparable) == (
        "insufficient_sessions",
        False,
    )
    assert plan.incomparable_reason == "only 19 of 20 bars within 40 market sessions"
    # The bar on the 45th market session is never read.
    assert len(session_rows(db, plan)) == 19


def test_the_forty_session_cap_never_reads_a_later_bar():
    # Run first on the 45th session: the 20th bar there must not complete the
    # window, or the result would depend on when the step ran.
    result = plan_result([44], nineteen_bars_in_forty_sessions)
    assert (result[0]["status"], result[0]["sessions_observed"]) == (
        "incomparable",
        19,
    )


def test_cancelling_stops_the_updates_and_keeps_the_history(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FILL)
    run(db, days[0])
    cancelled_at = datetime(2026, 9, 2, 14, 0)
    cancel_plan(db, plan.id, now=cancelled_at)
    db.commit()
    assert (plan.status, plan.status_reason, plan.cancelled_at) == (
        "cancelled",
        "cancelled_while_triggered",
        cancelled_at,
    )
    assert cancel_plan(db, plan.id).cancelled_at == cancelled_at  # idempotent
    days = follow(db, instrument, TARGET, start=days[0])
    assert run(db, days[0])["plans_checked"] == 0
    assert plan.status == "cancelled" and len(session_rows(db, plan)) == 1
    assert plan.execution_price == pytest.approx(100.0 * BUY)

    other, ended = new_plan(db, "9102")
    days = follow(db, other, FILL, TARGET)
    run(db, days[-1])
    with pytest.raises(PlanRequestError) as error:
        cancel_plan(db, ended.id)
    assert (error.value.code, error.value.status_code) == ("plan_already_closed", 409)
    with pytest.raises(PlanRequestError) as error:
        cancel_plan(db, 999)
    assert error.value.code == "plan_not_found"


def snapshot(db, plan):
    db.expire_all()
    stored = db.get(TrackingPlan, plan.id)
    columns = [c.name for c in TrackingPlan.__table__.columns]
    session_columns = [c.name for c in TrackingPlanSession.__table__.columns]
    return (
        {name: getattr(stored, name) for name in columns},
        [
            {name: getattr(row, name) for name in session_columns}
            for row in session_rows(db, stored)
        ],
    )


def test_rerunning_the_same_target_date_changes_nothing(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FLAT, FILL, INSIDE)
    first = run(db, days[-1])
    before = snapshot(db, plan)
    again = track_open_plans(db, days[-1], now=RUN_AT + timedelta(days=1))
    db.commit()
    assert first["sessions_written"] == 3
    assert (again["sessions_written"], again["transitions"]) == (0, {})
    after = snapshot(db, plan)
    assert after == before
    assert after[0]["updated_at"] == RUN_AT


def test_bars_after_the_target_date_are_not_used(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FLAT, FILL)
    run(db, days[0])
    assert (plan.status, plan.sessions_observed) == ("pending", 1)


def test_an_ended_plan_is_not_recomputed_for_an_earlier_date(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FILL, TARGET)
    run(db, days[-1])
    before = snapshot(db, plan)
    assert run(db, days[0])["plans_checked"] == 0
    assert snapshot(db, plan) == before


def test_a_correction_that_would_move_back_keeps_the_stored_state(db):
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FILL)
    run(db, days[0])
    before_rows = snapshot(db, plan)[1]
    corrected = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id, MarketBar.trading_date == days[0]
        )
    )
    corrected.high = 99.5  # the fill no longer happened
    db.commit()
    result = run(db, days[0])
    assert result["transition_conflicts"] == 1 and result["transitions"] == {}
    plan = db.get(TrackingPlan, plan.id)
    assert plan.status == "triggered"
    assert (plan.data_quality, plan.status_reason) == (
        "transition_conflict",
        "transition_conflict:triggered->pending",
    )
    assert snapshot(db, plan)[1] == before_rows
    # Still open, so later runs keep recomputing; once the bars allow the
    # stored state again the plan is updated and the mark is cleared.
    assert run(db, days[0])["transition_conflicts"] == 1
    corrected = db.get(MarketBar, corrected.id)
    corrected.high = 100.5
    db.commit()
    later = follow(db, instrument, TARGET, start=days[0])
    result = run(db, later[0])
    assert (result["transition_conflicts"], result["transitions"]) == (
        0,
        {"triggered->target_hit": 1},
    )
    plan = db.get(TrackingPlan, plan.id)
    assert (plan.status, plan.data_quality, plan.status_reason) == (
        "target_hit",
        "complete",
        "target_1_touched",
    )


def test_plans_and_system_signals_share_the_tracking_rules(db):
    instrument, plan = new_plan(db)
    sig = db.get(Signal, plan.signal_id)
    db.add(
        CorporateAction(
            instrument_id=instrument.id,
            action_date=sessions_after(PLAN_DAY, 1)[0],
            action_type="split",
            split_ratio=2.0,
            source="fixture",
        )
    )
    days = follow(db, instrument, (49.8, 50.3, 49.6, 50.1), (50.5, 51.7, 50.2, 51.5))
    run(db, days[-1])
    pipeline._evaluate_signal_tracking(db, sig)
    db.flush()
    evaluations = db.scalars(
        select(SignalEvaluation)
        .where(SignalEvaluation.signal_id == sig.id)
        .order_by(SignalEvaluation.session_date)
    ).all()
    rows = session_rows(db, plan)
    assert (
        [e.status for e in evaluations]
        == [r.status for r in rows]
        == [
            "active",
            "target_1_hit",
        ]
    )
    assert [e.adjusted_ohlc_json for e in evaluations] == [
        r.adjusted_ohlc_json for r in rows
    ]
    assert sig.execution_price == plan.execution_price == pytest.approx(50.0 * BUY)
    assert (sig.status, plan.status) == ("target_1_hit", "target_hit")


def test_run_plan_tracking_defaults_to_the_latest_stored_session(db, monkeypatch):
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: _Borrowed(db))
    assert run_plan_tracking()["status"] == "no_data"
    instrument, plan = new_plan(db)
    days = follow(db, instrument, FLAT, FILL)
    db.commit()
    result = run_plan_tracking()
    assert (result["status"], result["date"]) == ("success", days[-1].isoformat())
    assert db.get(TrackingPlan, plan.id).status == "triggered"
    assert plan_tracking.TRANSITION_CONFLICT == "transition_conflict"


class _Borrowed:
    """A context manager that lends the test session without closing it."""

    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False


# Timestamps written below (#376). `frozen_utcnow` (conftest) makes app.clock answer one
# instant to every caller, so a stamp taken from local time or the real clock stores a
# value other than the one asserted here.


def test_plans_are_stamped_with_the_clock(db, frozen_utcnow):
    first = frozen_utcnow.at
    instrument = stock(db)
    plan, created = create_plan(db, signal(db, instrument).id)
    db.commit()
    assert created and (plan.created_at, plan.updated_at) == (first, first)

    # The daily update takes the clock when it moves a plan.
    days = follow(db, instrument, FLAT, FILL)
    later = first + timedelta(hours=3)
    frozen_utcnow.at = later
    result = track_open_plans(db, days[1])
    db.commit()
    assert result["transitions"] == {"pending->triggered": 1}
    assert plan.updated_at == later

    latest = later + timedelta(hours=3)
    frozen_utcnow.at = latest
    cancel_plan(db, plan.id)
    db.refresh(plan)
    assert plan.status == "cancelled"
    assert (plan.cancelled_at, plan.updated_at) == (latest, latest)
