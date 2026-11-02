"""User tracking plan API (V1_SPEC 使用者追蹤計畫, #253) and cancel/daily races."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import get_db, router
from app.db import Base, enable_sqlite_concurrent_writes, enable_sqlite_foreign_keys
from app.models import MarketBar, TrackingPlan, TrackingPlanSession
from app.tracking_plans import PlanRequestError, cancel_plan, create_plan
from test_plan_tracking import (
    BUY,
    FILL,
    FLAT,
    INSIDE,
    PLAN_DAY,
    STOP,
    TARGET,
    candidate,
    follow,
    fresh_session,
    run,
    sessions_after,
    signal,
    stock,
)
from worker import pipeline, plan_tracking
from worker.plan_tracking import track_open_plans


@pytest.fixture
def db():
    with fresh_session() as session:
        yield session


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def add(client, signal_id, **body):
    return client.post("/api/tracking", json={"signal_id": signal_id, **body})


# ---- POST /tracking ----


def test_adding_a_candidate_creates_a_pending_plan_once(db, client):
    instrument = stock(db)
    sig = signal(db, instrument)
    row = candidate(db, instrument, sig)
    db.commit()

    first = add(client, sig.id, daily_candidate_id=row.id)
    assert first.status_code == 200
    body = first.json()
    plan = body["plan"]
    assert body["created"] is True
    assert (plan["source_kind"], plan["status"], plan["open"]) == (
        "candidate",
        "pending",
        True,
    )
    assert plan["instrument"] == {
        "id": instrument.id,
        "exchange": "TWSE",
        "symbol": "9101",
        "name": "名9101",
    }
    assert (plan["signal_id"], plan["daily_candidate_id"]) == (sig.id, row.id)
    assert plan["plan_date"] == PLAN_DAY.isoformat()
    assert plan["versions"]["tracking_version"] == "plan_tracking_v1"
    assert plan["versions"]["score_version"] == "candidate_score_v1"
    assert plan["levels"]["entry_zone"] == {"low": 100.0, "high": 100.0}
    assert (plan["levels"]["invalid_price"], plan["levels"]["target_1"]) == (
        98.0,
        103.2,
    )
    assert plan["levels"]["risk_reward"] == pytest.approx(1.6)
    assert plan["sessions_observed"] == 0 and plan["result_return"] is None

    again = add(client, sig.id, daily_candidate_id=row.id).json()
    assert again["created"] is False and again["plan"]["id"] == plan["id"]
    # The stock page adds the same signal without the candidate: still one plan.
    assert add(client, sig.id).json()["plan"]["id"] == plan["id"]
    assert len(db.scalars(select(TrackingPlan)).all()) == 1


@pytest.mark.parametrize(
    ("build", "status", "code"),
    [
        (
            lambda db, i: signal(db, i, status="observation").id,
            422,
            "signal_not_conditional",
        ),
        (lambda db, i: signal(db, i, target_1=99.0).id, 422, "invalid_levels"),
        (lambda db, i: (follow(db, i, FLAT), signal(db, i).id)[1], 409, "stale_signal"),
        (lambda db, i: 999, 404, "signal_not_found"),
    ],
)
def test_a_refused_plan_returns_the_rule_code(db, client, build, status, code):
    signal_id = build(db, stock(db))
    db.commit()
    response = add(client, signal_id)
    assert (response.status_code, response.json()["detail"]) == (status, code)
    assert db.scalars(select(TrackingPlan)).all() == []


def test_a_candidate_of_another_signal_or_a_bad_body_is_refused(db, client):
    first, second = stock(db, "9101"), stock(db, "9102")
    sig, other = signal(db, first), signal(db, second)
    row = candidate(db, second, other)
    db.commit()
    mismatch = add(client, sig.id, daily_candidate_id=row.id)
    assert (mismatch.status_code, mismatch.json()["detail"]) == (
        422,
        "candidate_signal_mismatch",
    )
    missing = add(client, sig.id, daily_candidate_id=999)
    assert (missing.status_code, missing.json()["detail"]) == (
        404,
        "candidate_not_found",
    )
    assert client.post("/api/tracking", json={}).status_code == 422
    assert client.post("/api/tracking", json={"signal_id": "1"}).status_code == 422


# ---- cancel ----


def test_cancelling_keeps_the_plan_and_is_idempotent(db, client):
    instrument = stock(db)
    plan_id = add(client, signal(db, instrument).id).json()["plan"]["id"]
    days = follow(db, instrument, FILL)
    run(db, days[0])

    first = client.post(f"/api/tracking/plans/{plan_id}/cancel")
    assert first.status_code == 200
    plan = first.json()["plan"]
    assert (plan["status"], plan["status_reason"], plan["open"]) == (
        "cancelled",
        "cancelled_while_triggered",
        False,
    )
    assert plan["cancelled_at"] is not None
    assert plan["execution_price"] == pytest.approx(100.0 * BUY)
    again = client.post(f"/api/tracking/plans/{plan_id}/cancel").json()["plan"]
    assert again["cancelled_at"] == plan["cancelled_at"]
    # Detail keeps the session written before the cancel.
    detail = client.get(f"/api/tracking/plans/{plan_id}").json()
    assert [s["session_date"] for s in detail["sessions"]] == [days[0].isoformat()]
    assert client.post("/api/tracking/plans/999/cancel").status_code == 404


def test_an_ended_plan_cannot_be_cancelled(db, client):
    instrument = stock(db)
    plan_id = add(client, signal(db, instrument).id).json()["plan"]["id"]
    days = follow(db, instrument, FILL, TARGET)
    run(db, days[-1])
    response = client.post(f"/api/tracking/plans/{plan_id}/cancel")
    assert (response.status_code, response.json()["detail"]) == (
        409,
        "plan_already_closed",
    )
    assert db.get(TrackingPlan, plan_id).status == "target_hit"


# ---- GET /tracking and /tracking/plans/{id} ----


def four_plans(db, client):
    """pending (9101), triggered (9102), invalidated (9103), target_hit (9104)."""

    ids = {}
    instruments = {}
    for symbol in ("9101", "9102", "9103", "9104"):
        instruments[symbol] = stock(db, symbol)
        ids[symbol] = add(client, signal(db, instruments[symbol]).id).json()["plan"][
            "id"
        ]
    days = sessions_after(PLAN_DAY, 3)
    follow(db, instruments["9101"], FLAT, FLAT, FLAT)
    follow(db, instruments["9102"], FLAT, FLAT, FILL)
    follow(db, instruments["9103"], FILL, STOP, FLAT)  # ends on day 2
    follow(db, instruments["9104"], FILL, INSIDE, TARGET)  # ends on day 3
    run(db, days[-1])
    return ids, days


def test_the_list_puts_open_plans_first_then_the_latest_ended(db, client):
    ids, days = four_plans(db, client)
    body = client.get("/api/tracking").json()
    assert [item["id"] for item in body["items"]] == [
        ids["9102"],
        ids["9101"],
        ids["9104"],
        ids["9103"],
    ]
    assert [item["status"] for item in body["items"]] == [
        "triggered",
        "pending",
        "target_hit",
        "invalidated",
    ]
    assert body["summary"] == {"open": 2, "closed": 2}
    assert body["pagination"]["total"] == 4
    meta = body["meta"]
    assert meta["tracking_version"] == "plan_tracking_v1"
    assert (
        meta["window_sessions"],
        meta["slippage_bps"],
        meta["round_trip_cost_bps"],
    ) == (
        20,
        5.0,
        30.0,
    )
    assert meta["simulated"] is True
    ended = body["items"][2]
    assert ended["outcome_date"] == days[2].isoformat()
    assert ended["result_comparable"] is True
    assert ended["result_return"] == pytest.approx(
        (103.2 * 0.9995) / (100.0 * BUY) - 1 - 0.003
    )
    assert ended["last_session_date"] == days[2].isoformat()
    assert ended["sessions_observed"] == 3


def test_the_list_filters_by_open_or_closed_and_pages(db, client):
    ids, _ = four_plans(db, client)
    opened = client.get("/api/tracking", params={"status": "open"}).json()
    assert [item["id"] for item in opened["items"]] == [ids["9102"], ids["9101"]]
    assert opened["pagination"]["total"] == 2 and opened["summary"] == {
        "open": 2,
        "closed": 2,
    }
    closed = client.get("/api/tracking", params={"status": "closed"}).json()
    assert [item["id"] for item in closed["items"]] == [ids["9104"], ids["9103"]]
    second = client.get("/api/tracking", params={"page": 2, "page_size": 3}).json()
    assert [item["id"] for item in second["items"]] == [ids["9103"]]
    assert second["pagination"] == {
        "page": 2,
        "page_size": 3,
        "total": 4,
        "total_pages": 2,
        "has_previous": True,
        "has_next": False,
    }
    assert client.get("/api/tracking", params={"status": "done"}).status_code == 422
    assert client.get("/api/tracking", params={"page_size": 101}).status_code == 422


def test_a_cancelled_plan_is_listed_with_the_ended_ones(db, client):
    ids, _ = four_plans(db, client)
    client.post(f"/api/tracking/plans/{ids['9101']}/cancel")
    closed = client.get("/api/tracking", params={"status": "closed"}).json()
    assert ids["9101"] in [item["id"] for item in closed["items"]]
    assert client.get("/api/tracking").json()["summary"] == {"open": 1, "closed": 3}


def test_the_empty_list(client):
    body = client.get("/api/tracking").json()
    assert body["items"] == [] and body["summary"] == {"open": 0, "closed": 0}
    assert body["pagination"]["total"] == 0


def test_the_detail_has_one_row_per_tracked_session(db, client):
    ids, days = four_plans(db, client)
    detail = client.get(f"/api/tracking/plans/{ids['9103']}").json()
    assert detail["plan"]["status"] == "invalidated"
    sessions = detail["sessions"]
    assert [s["session_no"] for s in sessions] == [1, 2, 3]
    assert [s["session_date"] for s in sessions] == [d.isoformat() for d in days]
    assert [s["status"] for s in sessions] == ["active", "invalidated", "invalidated"]
    first = sessions[0]
    assert first["ohlc"] == {
        "open": 99.5,
        "high": 100.5,
        "low": 99.2,
        "close": 100.2,
        "adj_close": 100.2,
    }
    assert (first["entry_trigger"], first["invalid_trigger"]) == (True, False)
    assert sessions[1]["invalid_trigger"] is True
    assert first["execution_price"] == pytest.approx(100.0 * BUY)
    assert first["source"] == "fixture-bars"
    assert client.get("/api/tracking/plans/999").status_code == 404


def test_a_transition_conflict_keeps_the_stored_status_in_the_list(db, client):
    instrument = stock(db)
    plan_id = add(client, signal(db, instrument).id).json()["plan"]["id"]
    days = follow(db, instrument, FILL)
    run(db, days[0])
    # A correction removes the fill: the plan may not move back to pending.
    bar = db.scalars(select(MarketBar).where(MarketBar.trading_date == days[0])).one()
    bar.high = 99.5
    db.commit()
    run(db, days[0])
    item = client.get("/api/tracking").json()["items"][0]
    assert (item["id"], item["status"], item["data_quality"]) == (
        plan_id,
        "triggered",
        "transition_conflict",
    )
    assert item["status_reason"] == "transition_conflict:triggered->pending"


# ---- the open plan on candidate and strategy rows ----


def test_candidates_and_stock_strategies_carry_the_open_plan(client, db):
    from test_candidates import T, group
    from test_candidates import signal as candidate_signal
    from test_candidates import stock as candidate_stock
    from worker.candidates import compute_daily_candidates

    a = candidate_stock(db, "1101", flow=(30.0, 20.0, 0.0))
    candidate_signal(db, a, volume_ratio=2.0)
    group(db, "ind-1", [a], rank=1)
    db.commit()
    compute_daily_candidates(db, T)

    item = client.get("/api/candidates").json()["items"][0]
    assert item["open_plan_id"] is None and item["candidate_id"] is not None
    detail = client.get("/api/stocks/TWSE/1101").json()
    strategies = detail["decision_summary"]["strategies"]
    assert strategies and all(row["open_plan_id"] is None for row in strategies)

    plan_id = add(
        client, item["signal_id"], daily_candidate_id=item["candidate_id"]
    ).json()["plan"]["id"]
    assert client.get("/api/candidates").json()["items"][0]["open_plan_id"] == plan_id
    detail = client.get("/api/stocks/TWSE/1101").json()
    assert detail["candidate"]["open_plan_id"] == plan_id
    tracked = [
        row
        for row in detail["decision_summary"]["strategies"]
        if row["signal_id"] == item["signal_id"]
    ]
    assert [row["open_plan_id"] for row in tracked] == [plan_id]

    client.post(f"/api/tracking/plans/{plan_id}/cancel")
    assert client.get("/api/candidates").json()["items"][0]["open_plan_id"] is None


# ---- cancel and the daily update on one SQLite file (#255 review L2) ----


@pytest.fixture
def file_sessions(tmp_path):
    """Two sessions on separate connections to one SQLite file, as API and daily."""

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'race.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    enable_sqlite_foreign_keys(engine)
    enable_sqlite_concurrent_writes(engine)
    Base.metadata.create_all(engine)
    sessions = [
        Session(engine, autoflush=False, expire_on_commit=False) for _ in range(2)
    ]
    sessions[0].info["strategies"] = pipeline._ensure_strategies(sessions[0])
    sessions[0].commit()
    try:
        yield sessions
    finally:
        for session in sessions:
            session.close()
        engine.dispose()


def stored(session, plan_id):
    session.expire_all()
    plan = session.get(TrackingPlan, plan_id)
    rows = session.scalars(
        select(TrackingPlanSession).where(TrackingPlanSession.plan_id == plan_id)
    ).all()
    return plan, len(rows)


def test_a_cancel_during_the_daily_update_is_kept(file_sessions, monkeypatch):
    daily, api = file_sessions
    instrument = stock(daily)
    plan, _ = create_plan(daily, signal(daily, instrument).id)
    days = follow(daily, instrument, FILL)
    daily.commit()

    real_track_path = plan_tracking.track_path
    cancelled_at = datetime(2026, 9, 2, 14, 0)

    def cancel_meanwhile(levels, bars):
        # The API cancels after the daily read the plan and before it writes.
        cancel_plan(api, plan.id, now=cancelled_at)
        api.commit()
        return real_track_path(levels, bars)

    monkeypatch.setattr(plan_tracking, "track_path", cancel_meanwhile)
    result = track_open_plans(daily, days[0])
    daily.commit()

    after, sessions = stored(api, plan.id)
    assert (after.status, after.status_reason, after.cancelled_at) == (
        "cancelled",
        "cancelled_while_pending",
        cancelled_at,
    )
    assert after.execution_price is None and sessions == 0
    assert result["transitions"] == {}


def test_a_cancel_read_before_the_daily_update_sees_the_new_status(file_sessions):
    daily, api = file_sessions
    instrument = stock(daily)
    plan, _ = create_plan(daily, signal(daily, instrument).id)
    daily.commit()
    stale = api.get(TrackingPlan, plan.id)  # the API read it while pending (kept)
    assert stale.status == "pending"

    days = follow(daily, instrument, FILL, TARGET)
    daily.commit()
    track_open_plans(daily, days[-1])
    daily.commit()

    with pytest.raises(PlanRequestError) as error:
        cancel_plan(api, plan.id)
    assert error.value.code == "plan_already_closed"
    api.commit()
    after, sessions = stored(daily, plan.id)
    assert (after.status, after.cancelled_at, sessions) == ("target_hit", None, 2)


def test_a_cancel_read_while_pending_cancels_the_triggered_plan(file_sessions):
    daily, api = file_sessions
    instrument = stock(daily)
    plan, _ = create_plan(daily, signal(daily, instrument).id)
    daily.commit()
    stale = api.get(TrackingPlan, plan.id)  # kept: the identity map holds it weakly
    assert stale.status == "pending"

    days = follow(daily, instrument, FILL)
    daily.commit()
    track_open_plans(daily, days[-1])
    daily.commit()

    cancelled = cancel_plan(api, plan.id)
    api.commit()
    assert (cancelled.status, cancelled.status_reason) == (
        "cancelled",
        "cancelled_while_triggered",
    )
    after, sessions = stored(daily, plan.id)
    assert (after.status, after.execution_price, sessions) == (
        "cancelled",
        pytest.approx(100.0 * BUY),
        1,
    )


def test_a_cancel_that_cannot_be_written_returns_plan_changed(db, client):
    # A row left by the race before #253: cancelled_at is set but the status is open.
    plan_id = add(client, signal(db, stock(db)).id).json()["plan"]["id"]
    plan = db.get(TrackingPlan, plan_id)
    plan.cancelled_at = datetime(2026, 9, 2, 14, 0)
    db.commit()
    response = client.post(f"/api/tracking/plans/{plan_id}/cancel")
    assert (response.status_code, response.json()["detail"]) == (409, "plan_changed")
    db.expire_all()
    assert db.get(TrackingPlan, plan_id).status == "pending"
