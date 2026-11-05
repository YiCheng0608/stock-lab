"""Stored daily action tiers: equal to live, fallback, invalidation (Issue #476).

The market of ``test_action_tiers`` (every tier, holdings, the watchlist, a
recent event, short bars) is stored by ``worker.action_tiers`` and read back
through ``app.action_tier_store``.  The stored part must give the same rows
as the live computation, and a change of any input the day was computed from
must make the pages compute live again.

The store is imported inside each test so that, on code without it, every
test fails on its own instead of the module failing to collect.
"""

import importlib
from dataclasses import asdict
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.decision as decision
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
import worker.pipeline as pipeline
from app.domain import STRATEGY_LEVELS_VERSION
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    DailyCandidate,
    Event,
    GroupDailyScore,
    GroupMembership,
    Instrument,
    MarketBar,
    PortfolioPosition,
    Signal,
    StrategyLevel,
)
from test_action_tiers import AS_OF, HOLDING_STATES, build_market

# Fields every call answers with its own instant.
TIME_KEYS = {"generated_at", "response_generated_at", "computed_at"}


@pytest.fixture
def factory(tmp_path, monkeypatch):
    """test_action_tiers' database, with the API on it."""

    engine = create_engine(f"sqlite:///{tmp_path / 'tiers.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield make
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


@pytest.fixture
def stub_summaries(monkeypatch):
    """test_action_tiers' stub of the decision builder (a fixed action state)."""

    def fake(db, instrument, as_of=None):
        return {
            "instrument": {
                "id": instrument.id,
                "exchange": instrument.exchange,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "instrument_type": instrument.instrument_type,
            },
            "as_of": as_of.isoformat() if as_of else None,
            "action_state": HOLDING_STATES.get(instrument.symbol, "no_condition"),
            "held": instrument.symbol in HOLDING_STATES or instrument.symbol == "HE",
        }

    monkeypatch.setattr(decision, "build_decision_summary", fake)


def store():
    return importlib.import_module("app.action_tier_store")


def write(factory, day=AS_OF):
    worker = importlib.import_module("worker.action_tiers")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pipeline, "SessionLocal", factory)
        return worker.run_action_tiers(day)


def live(db, day=AS_OF):
    return [asdict(row) for row in decision.action_tier_rows(db, day)]


def read(db, day=AS_OF):
    rows, source = store().read_action_tier_rows(db, day)
    return [asdict(row) for row in rows], source


def masked(value, drop=()):
    if isinstance(value, dict):
        return {
            key: masked(item, drop)
            for key, item in value.items()
            if key not in TIME_KEYS and key not in drop
        }
    if isinstance(value, list):
        return [masked(item, drop) for item in value]
    return value


def test_the_stored_day_gives_the_live_rows(factory):
    with factory() as db:
        build_market(db)
        expected = live(db)
    result = write(factory)
    assert result["status"] == "success" and result["date"] == AS_OF.isoformat()
    with factory() as db:
        rows, source = read(db)
        assert source["source"] == "precomputed" and source["reason"] is None
        assert source["trading_date"] == AS_OF.isoformat()
        # Every tier of the fixture is in the stored rows.
        assert {row["tier"] for row in rows} == {0, 1, 2, 4, 5}
        assert rows == expected == live(db)


def test_without_a_stored_day_the_pages_compute_live_and_say_so(
    factory, stub_summaries
):
    with factory() as db:
        build_market(db)
    with TestClient(app) as client:
        before = client.get("/api/actions", params={"view": "all"}).json()
        dashboard = client.get("/api/dashboard").json()
        assert before["summary"]["tier_source"] == {
            "trading_date": AS_OF.isoformat(),
            "source": "live",
            "reason": "missing",
            "computed_at": None,
        }
        assert dashboard["action_tier_source"]["reason"] == "missing"
        write(factory)
        after = client.get("/api/actions", params={"view": "all"}).json()
        stored_dashboard = client.get("/api/dashboard").json()
    assert after["summary"]["tier_source"]["source"] == "precomputed"
    assert after["summary"]["tier_source"]["computed_at"].endswith("Z")
    assert stored_dashboard["action_tier_source"]["source"] == "precomputed"
    # The same page either way; only where the tiers came from differs.
    assert masked(after, {"tier_source"}) == masked(before, {"tier_source"})
    assert masked(stored_dashboard, {"action_tier_source"}) == masked(
        dashboard, {"action_tier_source"}
    )


def test_a_day_without_its_own_row_is_computed_live(factory):
    with factory() as db:
        build_market(db)
    write(factory, AS_OF - timedelta(days=1))
    with factory() as db:
        rows, source = read(db)
        assert source["reason"] == "missing"
        assert rows == live(db)
        assert store().read_action_tier_rows(db, None)[1]["reason"] == "no_as_of"


def _signal(db, symbol):
    return db.scalar(
        select(Signal)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Instrument.symbol == symbol)
    )


def _id(db, symbol):
    return db.scalar(select(Instrument.id).where(Instrument.symbol == symbol))


# Each change is one way the day's inputs move after the daily stored it.
def daily_rerun_changes_a_status(db):
    # A rerun of the daily (or a manual analyze) rewrites signals in place.
    _signal(db, "O3").status = "conditional"


def analyze_writes_a_new_signal(db):
    signal = _signal(db, "D0")
    db.add(
        Signal(
            signal_key="analysis-D0-pullback_v3",
            signal_date=AS_OF,
            instrument_id=signal.instrument_id,
            strategy_version_id=signal.strategy_version_id,
            status="observation",
            data_quality="complete",
            entry_type="conditional",
        )
    )


def analyze_completes_a_signal(db):
    db.execute(
        update(Signal)
        .where(Signal.id == _signal(db, "D2").id)
        .values(data_quality="complete", status="observation")
    )


def strategy_levels_rerun(db):
    db.add(
        StrategyLevel(
            signal_id=_signal(db, "O3").id,
            levels_version=STRATEGY_LEVELS_VERSION,
            availability="levels",
            conditions_json=[],
            price_basis="next_session_raw_basis",
        )
    )


def strategy_levels_change_a_condition(db):
    level = db.scalar(
        select(StrategyLevel).where(StrategyLevel.signal_id == _signal(db, "O1").id)
    )
    level.conditions_json = [
        dict(item, satisfied=True) for item in level.conditions_json
    ]
    level.computed_at = level.computed_at + timedelta(seconds=1)


def candidates_rerun(db):
    db.execute(
        update(DailyCandidate)
        .where(DailyCandidate.instrument_id == _id(db, "C1"))
        .values(rank=7)
    )


def group_scores_rerun(db):
    db.execute(
        update(GroupDailyScore)
        .where(GroupDailyScore.group_id == "g-rank5")
        .values(rank=0)
    )


def membership_change(db):
    db.add(
        GroupMembership(
            group_id="g-rank1",
            instrument_id=_id(db, "K3"),
            valid_from=AS_OF - timedelta(days=400),
            source="official",
        )
    )


def instrument_change(db):
    db.execute(
        update(Instrument)
        .where(Instrument.symbol == "K1")
        .values(listing_date=AS_OF - timedelta(days=3))
    )


def a_new_event(db):
    db.add(
        Event(
            instrument_id=_id(db, "O1"),
            event_date=AS_OF,
            event_type="material",
            title="later event",
            source="mops",
        )
    )


def a_backfilled_bar(db):
    db.add(
        MarketBar(
            instrument_id=_id(db, "B1"),
            trading_date=AS_OF - timedelta(days=59),
            open=10,
            high=10,
            low=10,
            close=10,
            adj_close=10,
            volume=1000,
            turnover=10000,
            source="official-fixture",
        )
    )


CHANGES = [
    daily_rerun_changes_a_status,
    analyze_writes_a_new_signal,
    analyze_completes_a_signal,
    strategy_levels_rerun,
    strategy_levels_change_a_condition,
    candidates_rerun,
    group_scores_rerun,
    membership_change,
    instrument_change,
    a_new_event,
    a_backfilled_bar,
]


@pytest.mark.parametrize("change", CHANGES, ids=[item.__name__ for item in CHANGES])
def test_a_changed_input_makes_the_stored_day_stale(factory, change):
    with factory() as db:
        build_market(db)
    write(factory)
    with factory() as db:
        change(db)
        db.commit()
    with factory() as db:
        rows, source = read(db)
        assert (source["source"], source["reason"]) == ("live", "stale")
        assert rows == live(db)
    # Rewriting the day (the next daily, or worker.cli action-tiers) stores it again.
    write(factory)
    with factory() as db:
        rows, source = read(db)
        assert source["source"] == "precomputed"
        assert rows == live(db)


@pytest.mark.parametrize(
    "name",
    [
        "ACTION_TIER_STORE_VERSION",
        "ACTION_TIER_VERSION",
        "STRATEGY_LEVELS_VERSION",
        "CANDIDATE_SCORE_VERSION",
    ],
)
def test_a_version_bump_makes_the_stored_day_stale(factory, monkeypatch, name):
    with factory() as db:
        build_market(db)
    write(factory)
    monkeypatch.setattr(store(), name, getattr(store(), name) + "-next")
    with factory() as db:
        assert read(db)[1]["reason"] in {"stale", "missing"}


def test_holdings_and_the_watchlist_are_read_live_over_the_stored_day(factory):
    with factory() as db:
        build_market(db)
    write(factory)
    with factory() as db:
        db.add(PortfolioPosition(instrument_id=_id(db, "K1"), shares=5, average_cost=1))
        db.execute(
            update(PortfolioPosition)
            .where(PortfolioPosition.instrument_id == _id(db, "H1"))
            .values(shares=0, shares_integer=0)
        )
        db.execute(
            update(Instrument)
            .where(Instrument.symbol == "O3")
            .values(is_watchlisted=True)
        )
        db.execute(
            update(Instrument).where(Instrument.symbol == "K2").values(name="Renamed")
        )
        db.commit()
    with factory() as db:
        rows, source = read(db)
        # A position, the watchlist and a name are not inputs of the stored day.
        assert source["source"] == "precomputed"
        assert rows == live(db)
        by_symbol = {row["symbol"]: row for row in rows}
        assert by_symbol["K1"]["tier"] == 0
        assert by_symbol["H1"]["tier"] != 0
        assert by_symbol["O3"]["watchlisted"] is True


def test_rewriting_a_day_keeps_one_row(factory):
    with factory() as db:
        build_market(db)
    first = write(factory)
    second = write(factory)
    models = importlib.import_module("app.models")
    with factory() as db:
        rows = db.scalars(select(models.ActionTierSnapshot)).all()
        assert len(rows) == 1
        assert rows[0].row_count == first["records"] == second["records"] > 0
