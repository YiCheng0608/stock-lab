"""Optional sections of the stock detail, coverage and dashboard GETs (#601).

A section the pages do not read is neither built nor returned unless the
request names it with ``include=``; the navbar reads its date from /data-date.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import api
from app.api import get_db, router
from app.models import ChipSnapshot, IngestionRun
from test_plan_tracking import PLAN_DAY, add_bars, fresh_session, sessions_after
from test_plan_tracking import signal as add_signal
from test_plan_tracking import stock as add_stock

DAYS = 40  # more than the 30 rows the stock page shows
STOCK = "/api/stocks/TWSE/9101"
STOCK_OPTIONAL = {
    "signals",
    "news",
    "features",
    "feature_snapshot",
    "strategy_conditions",
    "corporate_actions",
}


@pytest.fixture
def db():
    with fresh_session() as session:
        instrument = add_stock(session)
        days = sessions_after(PLAN_DAY, DAYS - 1)
        add_bars(session, instrument, [(day, (99.0, 99.5, 98.5, 99.0)) for day in days])
        for day in [PLAN_DAY, *days]:
            session.add(
                ChipSnapshot(
                    instrument_id=instrument.id,
                    trading_date=day,
                    foreign_buy=1.0,
                    source="fixture-chips",
                )
            )
        add_signal(session, instrument)
        session.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=days[-1],
                status="success",
                records=1,
                data_as_of=days[-1].isoformat(),
            )
        )
        session.commit()
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


def _fail(name):
    def fail(*args, **kwargs):
        raise AssertionError(f"{name} ran without include")

    return fail


# ---- stock detail ----


def test_the_stock_detail_leaves_the_unread_sections_out(client, monkeypatch):
    # Not returned and not computed: the signal rows and the news query never run.
    monkeypatch.setattr(api, "signal_dict", _fail("signal_dict"))
    monkeypatch.setattr(api, "_stock_news_cutoff_filter", _fail("news query"))
    body = client.get(STOCK).json()
    assert STOCK_OPTIONAL.isdisjoint(body)
    # The page reads the cutoff date and the newest 30 bars and chips.
    assert body["news_cutoff"]["as_of"] == body["bars"][-1]["date"]
    assert len(body["bars"]) == len(body["chips"]) == api.STOCK_DETAIL_ROWS == 30
    assert (
        body["bars"][-1]["date"] == sessions_after(PLAN_DAY, DAYS - 1)[-1].isoformat()
    )
    for key in ("instrument", "decision_summary", "strategy_board", "quality_summary"):
        assert key in body


def test_the_stock_detail_builds_a_section_on_include(client):
    body = client.get(STOCK, params={"include": ["signals", "news"]}).json()
    assert [row["signal_key"] for row in body["signals"]] == [
        f"analysis-TWSE-9101-{PLAN_DAY.isoformat()}-breakout"
    ]
    assert body["news"] == []
    assert {"features", "strategy_conditions", "corporate_actions"}.isdisjoint(body)
    every = client.get(
        STOCK, params={"include": "features,strategy_conditions,corporate_actions"}
    ).json()
    assert {"features", "feature_snapshot", "corporate_actions"} <= set(every)
    assert every["strategy_conditions"]


def test_an_unknown_include_is_refused(client):
    for path in (STOCK, "/api/coverage", "/api/dashboard"):
        response = client.get(path, params={"include": "everything"})
        assert response.status_code == 422, path
        assert "unsupported include: everything" in response.json()["detail"]


def test_the_stock_detail_builds_the_decision_summary_once(client, monkeypatch):
    calls = []
    build = api.build_decision_summary

    def counted(*args, **kwargs):
        calls.append(args[2] if len(args) > 2 else kwargs.get("as_of"))
        return build(*args, **kwargs)

    monkeypatch.setattr(api, "build_decision_summary", counted)
    body = client.get(STOCK).json()
    assert body["decision_summary"] is not None
    assert len(calls) == 1


def test_the_instrument_detail_keeps_its_full_payload(client):
    body = client.get("/api/instruments/9101", params={"exchange": "TWSE"}).json()
    assert {"signals", "features", "strategy_conditions", "corporate_actions"} <= set(
        body
    )
    assert len(body["bars"]) == len(body["chips"]) == DAYS


# ---- coverage ----


def test_coverage_ships_the_instrument_rows_on_include(client, monkeypatch):
    default = client.get("/api/coverage").json()
    assert "instrument_coverage" not in default
    assert {"summary", "baseline"} <= set(default)
    full = client.get("/api/coverage", params={"include": "instrument_coverage"}).json()
    assert full["instrument_coverage"] == []  # a snapshot without provenance
    assert full["summary"] == default["summary"]

    # The rows the report builds are the rows include=instrument_coverage ships.
    def report(*args, **kwargs):
        return {"summary": {}, "instrument_coverage": [{"symbol": "9101"}]}

    monkeypatch.setattr(api, "coverage_report", report)
    full = client.get("/api/coverage", params={"include": "instrument_coverage"}).json()
    assert full["instrument_coverage"] == [{"symbol": "9101"}]
    assert "instrument_coverage" not in client.get("/api/coverage").json()


# ---- dashboard and the navbar date ----


def test_the_dashboard_leaves_groups_and_signals_out(client, monkeypatch):
    monkeypatch.setattr(api, "latest_scores", _fail("latest_scores"))
    monkeypatch.setattr(api, "signal_dict", _fail("signal_dict"))
    body = client.get("/api/dashboard").json()
    assert {"groups", "signals"}.isdisjoint(body)
    assert body["as_of"] is not None


def test_the_dashboard_builds_groups_and_signals_on_include(client):
    body = client.get(
        "/api/dashboard", params={"include": ["groups", "signals"]}
    ).json()
    assert body["groups"] == []
    assert len(body["signals"]) == 1


def test_the_data_date_is_the_dashboard_as_of(client, db):
    day = sessions_after(PLAN_DAY, DAYS - 1)[-1].isoformat()
    assert client.get("/api/data-date").json() == {"as_of": day}
    assert client.get("/api/dashboard").json()["as_of"] == day
    # A newer failed attempt does not blank the date (#249), on both routes.
    db.add(
        IngestionRun(
            run_type="collect",
            source="official",
            run_date=date(2030, 1, 2),
            status="failed",
            records=0,
        )
    )
    db.commit()
    db.info.pop("_decision_official", None)
    assert client.get("/api/data-date").json() == {"as_of": day}
    assert client.get("/api/dashboard").json()["as_of"] == day


def test_without_an_official_run_the_data_date_is_empty():
    with fresh_session() as session:
        assert api.data_date(db=session) == {"as_of": None}
        assert api.dashboard(db=session)["as_of"] is None
