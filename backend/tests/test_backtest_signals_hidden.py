"""No product page reads a technical backtest's signals (#484).

A backtest run commits its signals (``backtest-<run>-...``) as it goes, so they exist
while it runs and after it fails. They use the same strategy rows as the analysis
signals; only the backtest summary reads them.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.migrations import upgrade_database
from app.models import Instrument, Signal, StrategyVersion
from app.signal_versions import readable_signal
from app.strategies import REGISTRY

DAY = date(2026, 9, 4)
STRATEGY = next(iter(REGISTRY))


@pytest.fixture
def factory(tmp_path, monkeypatch):
    # HTTP behavior only: startup readiness has its own tests (test_api.py).
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    with session_factory() as db:
        instrument = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="HIDE",
            name="Hide",
            instrument_type="stock",
            status="active",
        )
        strategy = StrategyVersion(
            name=STRATEGY, version=REGISTRY[STRATEGY].version, kind="breakout"
        )
        db.add_all([instrument, strategy])
        db.flush()
        for key, status in (
            (f"analysis-{STRATEGY}-HIDE-{DAY}", "conditional"),
            # A running or failed run's row, newer and with a larger id.
            (f"backtest-2286-{STRATEGY}-HIDE-{DAY}", "active"),
        ):
            db.add(
                Signal(
                    signal_key=key,
                    signal_date=DAY,
                    instrument_id=instrument.id,
                    strategy_version_id=strategy.id,
                    status=status,
                    entry_type="breakout",
                    rule_evidence_json={"strategy": STRATEGY},
                )
            )
        db.commit()
    yield session_factory
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


ANALYSIS_KEY = f"analysis-{STRATEGY}-HIDE-{DAY}"


def _keys(items) -> list[str]:
    return [item["signal_key"] for item in items]


def test_the_dashboard_lists_and_counts_no_backtest_signal(factory):
    with TestClient(app) as client:
        payload = client.get("/api/dashboard").json()
    assert _keys(payload["signals"]) == [ANALYSIS_KEY]
    assert payload["signal_status_counts"] == {"conditional": 1}


def test_the_instrument_page_shows_no_backtest_signal(factory):
    with TestClient(app) as client:
        response = client.get("/api/instruments/HIDE")
    assert response.status_code == 200
    assert _keys(response.json()["signals"]) == [ANALYSIS_KEY]


def test_the_signal_list_and_its_search_show_no_backtest_signal(factory):
    with TestClient(app) as client:
        listed = client.get("/api/signals").json()
        searched = client.get("/api/signals", params={"q": "backtest"}).json()
    assert _keys(listed["items"]) == [ANALYSIS_KEY]
    assert listed["pagination"]["total"] == 1
    assert searched["items"] == [] and searched["pagination"]["total"] == 0


def test_the_readable_signals_of_the_action_pages_leave_out_backtests(factory):
    # decision.py (action center, instrument decision) and theme_member_view
    # read signals through readable_signal(); a backtest row of the same day
    # would win there on its larger id.
    with factory() as db:
        keys = db.scalars(
            select(Signal.signal_key)
            .join(StrategyVersion, StrategyVersion.id == Signal.strategy_version_id)
            .where(readable_signal())
        ).all()
    assert keys == [ANALYSIS_KEY]


def test_a_product_signal_keeps_its_tracking_under_newer_backtest_evaluations(factory):
    # _tracking_rows read the newest 1,000 evaluations of every signal and only
    # then kept the asked one: a backtest run's newer rows pushed it out.
    from datetime import timedelta

    from app.models import SignalEvaluation

    with factory() as db:
        ids = {
            key: signal_id
            for key, signal_id in db.execute(select(Signal.signal_key, Signal.id))
        }
        backtest_id = next(v for k, v in ids.items() if k.startswith("backtest-"))
        db.add(
            SignalEvaluation(
                signal_id=ids[ANALYSIS_KEY],
                session_date=DAY + timedelta(days=1),
                session_no=1,
                status="未觸發",
            )
        )
        db.add_all(
            SignalEvaluation(
                signal_id=backtest_id,
                session_date=DAY + timedelta(days=2 + day),
                session_no=day + 1,
                status="未觸發",
            )
            for day in range(1001)
        )
        db.commit()
    with TestClient(app) as client:
        response = client.get(f"/api/tracking/{ANALYSIS_KEY}")
    assert response.status_code == 200
    rows = response.json()["evaluations"]
    assert [row["signal"]["signal_key"] for row in rows] == [ANALYSIS_KEY]
    assert rows[0]["evaluation"]["session_date"] == str(DAY + timedelta(days=1))
