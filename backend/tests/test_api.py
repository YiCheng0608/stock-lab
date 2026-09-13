from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.main import app
from app.models import (
    DataQuality,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    PortfolioPosition,
    RawPayload,
    Signal,
    StrategyVersion,
    ThemeGroup,
)


@pytest.fixture(autouse=True)
def avoid_formal_database_initialization(monkeypatch):
    # HTTP behavior tests bypass readiness; dedicated startup tests exercise
    # the real boundary against isolated databases.
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)


@pytest.fixture
def isolated_api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[api_module.get_db] = override_get_db
    yield factory
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signal_api_exposes_non_probability_semantics_for_new_and_legacy_rows(isolated_api):
    with isolated_api() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="SEM", name="Semantics", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        strategy = StrategyVersion(name="breakout_v1", version="1.0.0", kind="breakout")
        db.add(strategy)
        db.flush()
        db.add_all(
            [
                Signal(
                    signal_key="legacy-sem",
                    signal_date=date(2026, 9, 4),
                    instrument_id=instrument.id,
                    status="conditional",
                    entry_type="breakout",
                    strategy_version_id=strategy.id,
                    confidence=0.75,
                    rule_evidence_json={
                        "strategy": "breakout_v1",
                        "strategy_version": "1.0.0",
                        "legacy_marker": "keep",
                        "confidence_semantics": {
                            "version": "signal-confidence/v1-fixed",
                            "kind": "prediction",
                            "is_calibrated": True,
                            "is_probability": True,
                            "display_label_zh": "75% 勝率",
                        },
                    },
                ),
                Signal(
                    signal_key="new-sem",
                    signal_date=date(2026, 9, 5),
                    instrument_id=instrument.id,
                    status="observation",
                    entry_type="pullback",
                    confidence=None,
                    rule_evidence_json={"strategy": "pullback_v1", "strategy_version": "1.0.0"},
                ),
                Signal(
                    signal_key="unknown-sem",
                    signal_date=date(2026, 9, 6),
                    instrument_id=instrument.id,
                    status="conditional",
                    entry_type="breakout",
                    confidence=0.80,
                    rule_evidence_json={"strategy": "other_strategy", "strategy_version": "1.0.0"},
                ),
            ]
        )
        db.commit()
        signal_ids = {row.signal_key: row.id for row in db.scalars(select(Signal)).all()}

    with TestClient(app) as client:
        signals = client.get("/api/signals?instrument_symbol=SEM&page_size=10")
        dashboard = client.get("/api/dashboard")
        detail = client.get(f"/api/signals/{signal_ids['legacy-sem']}")
        tracking = client.get("/api/tracking/legacy-sem")
        stock = client.get("/api/instruments/SEM?exchange=TWSE")

    assert signals.status_code == 200
    by_key = {item["signal_key"]: item for item in signals.json()["items"]}
    assert by_key["legacy-sem"]["confidence"] == pytest.approx(0.75)
    assert by_key["legacy-sem"]["level_semantics"]["kind"] == "rule_reference"
    assert by_key["legacy-sem"]["level_semantics"]["version"] == "signal-level-semantics/v1"
    assert by_key["legacy-sem"]["level_semantics"]["formula"]["version"] == "legacy-risk-levels/v1"
    assert by_key["legacy-sem"]["level_semantics"]["price_basis"]["value"] is None
    assert by_key["legacy-sem"]["level_semantics"]["generated_at"]["value"] is None
    assert by_key["legacy-sem"]["rule_evidence"]["level_semantics"]["kind"] == "rule_reference"
    assert by_key["legacy-sem"]["confidence_semantics"] == {
        "version": "signal-confidence/v1-fixed",
        "kind": "legacy_fixed_value",
        "is_calibrated": False,
        "is_probability": False,
        "display_label_zh": "舊版固定規則值（未經機率校準；非勝率）",
    }
    assert by_key["new-sem"]["confidence"] is None
    assert by_key["new-sem"]["confidence_semantics"]["version"] == "signal-confidence/v2"
    assert by_key["new-sem"]["confidence_semantics"]["is_probability"] is False
    assert by_key["new-sem"]["confidence_semantics"]["is_calibrated"] is False
    assert by_key["unknown-sem"]["confidence_semantics"]["kind"] == "unknown_numeric"
    assert by_key["unknown-sem"]["confidence_semantics"]["is_probability"] is False

    assert dashboard.status_code == 200
    compact = {item["signal_key"]: item for item in dashboard.json()["signals"]}
    assert compact["legacy-sem"]["confidence"] == pytest.approx(0.75)
    assert compact["legacy-sem"]["confidence_semantics"]["is_probability"] is False
    assert "rule_evidence" not in compact["legacy-sem"]
    assert compact["legacy-sem"]["level_semantics"]["kind"] == "rule_reference"
    assert detail.status_code == 200
    assert detail.json()["signal"]["level_semantics"]["kind"] == by_key["legacy-sem"]["level_semantics"]["kind"]
    assert detail.json()["signal"]["level_semantics"]["strategy"] == by_key["legacy-sem"]["level_semantics"]["strategy"]
    assert tracking.status_code == 200
    assert tracking.json()["signal"]["level_semantics"]["version"] == "signal-level-semantics/v1"
    assert stock.status_code == 200
    stock_signals = {item["signal_key"]: item for item in stock.json()["signals"]}
    assert stock_signals["legacy-sem"]["level_semantics"]["version"] == "signal-level-semantics/v1"
    assert by_key["unknown-sem"]["level_semantics"]["kind"] == "unknown"
    assert by_key["unknown-sem"]["level_semantics"]["reason"] == "strategy_or_version_not_allowlisted"


def test_primary_api_routes_use_isolated_source_of_truth(isolated_api):
    with isolated_api() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="AAA", name="Alpha", instrument_type="stock", industry="Technology", status="active")
        same_symbol_tpex = Instrument(market="TW", exchange="TPEx", symbol="AAA", name="Alpha OTC", instrument_type="stock", industry="Technology", status="active")
        group = ThemeGroup(id="fixture-group", name="Fixture Group", group_type="official_industry", active=True)
        db.add_all([instrument, same_symbol_tpex, group])
        db.flush()
        db.add(GroupMembership(group_id=group.id, instrument_id=instrument.id, valid_from=date(2026, 1, 1), source="fixture"))
        db.add(MarketBar(instrument_id=instrument.id, trading_date=date(2026, 9, 4), open=100, high=105, low=98, close=103, adj_close=103, volume=1000, turnover=103000, source="fixture"))
        db.add(GroupDailyScore(group_id=group.id, trading_date=date(2026, 9, 4), relative_return=0.02, relative_return_1d=0.01, relative_return_5d=0.03, relative_return_20d=0.05, breadth=1, volume_strength=0.6, institutional_flow=0.7, catalyst=None, score=72, rank=1, eligible_members=3, data_quality="partial", details_json={"benchmark": "TAIEX", "candidate_symbols": ["AAA"], "leaderboard": "equity"}))
        db.add(Signal(signal_key="fixture-signal", signal_date=date(2026, 9, 4), instrument_id=instrument.id, status="observation", entry_type="pullback", data_quality="incomplete", rule_evidence_json={"inputs": {"group_excess_return_20d": None}}))
        db.add(IngestionRun(run_type="collect", source="official", run_date=date(2026, 9, 4), status="partial", records=1, data_as_of="2026-09-03"))
        db.add(DataQuality(entity_type="instrument", entity_key="TWSE:AAA", as_of_date=date(2026, 9, 4), status="partial", missing_fields_json=["chips"], checks_json={"bars": 1}, source="fixture"))
        db.commit()

    with TestClient(app) as client:
        dashboard = client.get("/api/dashboard")
        groups = client.get("/api/groups")
        group = client.get("/api/groups/fixture-group")
        instruments = client.get("/api/instruments?q=AAA")
        instrument = client.get("/api/instruments/AAA")
        instrument_tpex = client.get("/api/instruments/AAA?exchange=TPEx")
        signals = client.get("/api/signals?instrument_symbol=AAA&limit=1")
        tracking = client.get("/api/tracking")
        portfolio = client.get("/api/portfolio")
        quality = client.get("/api/data-quality")
        raw_payloads = client.get("/api/raw-payloads")
        runs = client.get("/api/ingestion-runs")
        events = client.get("/api/events")
        backtest = client.get("/api/backtest/summary")
        saved = client.post("/api/portfolio", json={"symbol": "AAA", "shares": 10, "average_cost": 100})

    assert dashboard.status_code == 200 and dashboard.json()["mode"] == "official_partial"
    assert dashboard.json()["scan_scope"].startswith("official")
    assert groups.status_code == 200 and groups.json()["items"][0]["candidates"] == ["AAA"]
    assert group.status_code == 200 and group.json()["members"][0]["symbol"] == "AAA"
    assert instruments.status_code == 200 and {item["exchange"] for item in instruments.json()["items"]} == {"TWSE", "TPEx"}
    assert instrument.status_code == 200 and instrument.json()["data_quality"][0]["missing_fields"] == ["chips"]
    assert instrument_tpex.status_code == 200 and instrument_tpex.json()["instrument"]["exchange"] == "TPEx"
    assert signals.status_code == 200 and len(signals.json()["items"]) == 1
    assert tracking.status_code == 200 and tracking.json()["summary"]["horizons"] == [5, 20]
    assert portfolio.status_code == 200 and portfolio.json()["items"] == []
    assert quality.status_code == 200 and quality.json()["items"][0]["entity_key"] == "TWSE:AAA"
    assert raw_payloads.status_code == 200 and raw_payloads.json()["items"] == []
    assert runs.status_code == 200 and runs.json()["items"][0]["data_as_of"] == "2026-09-03"
    assert events.status_code == 200 and events.json()["items"] == []
    assert backtest.status_code == 200
    assert backtest.json() == {
        "run": None,
        "groups": [],
        "assessment": "no_run",
        "zero_actionable_count": 0,
    }
    assert saved.status_code == 200 and saved.json()["shares"] == 10


def test_portfolio_accepts_explicit_lots_and_odd_lot_shares(isolated_api):
    with isolated_api() as db:
        db.add(Instrument(market="TW", exchange="TWSE", symbol="LOT", name="Lot ETF", instrument_type="etf", etf_category="bond", status="active"))
        db.commit()

    with TestClient(app) as client:
        lot = client.post("/api/portfolio", json={"symbol": "LOT", "unit": "lot", "quantity": 1})
        odd = client.post("/api/portfolio", json={"symbol": "LOT", "unit": "odd_lot", "quantity": 1500})
        zero = client.post("/api/portfolio", json={"symbol": "LOT", "unit": "lot", "quantity": 0})
        non_integer = client.post("/api/portfolio", json={"symbol": "LOT", "unit": "lot", "quantity": 1.5})

    assert lot.status_code == 200
    assert lot.json()["shares"] == 1000
    assert lot.json()["quantity"]["display"] == "1 張"
    assert odd.status_code == 200
    assert odd.json()["shares"] == 1500
    assert odd.json()["quantity"]["display"] == "1 張 500 股"
    assert zero.status_code == 422
    assert non_integer.status_code == 422


def test_dashboard_does_not_present_stale_bars_as_failed_official_data(isolated_api):
    with isolated_api() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="STALE", name="Stale", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        db.add(MarketBar(instrument_id=instrument.id, trading_date=date(2026, 1, 2), open=10, high=11, low=9, close=10, adj_close=10, volume=100, turnover=1000, source="legacy"))
        db.add(IngestionRun(run_type="collect", source="official", run_date=date(2026, 9, 4), status="failed", records=0, error="fixture unavailable"))
        db.commit()

    with TestClient(app) as client:
        dashboard = client.get("/api/dashboard")

    assert dashboard.status_code == 200
    assert dashboard.json()["mode"] == "official_partial"
    assert dashboard.json()["as_of"] is None
    assert dashboard.json()["data_quality"]["latest_run_records"] == 0


def test_dashboard_ignores_newer_backtest_run_for_official_state(isolated_api):
    with isolated_api() as db:
        db.add_all(
            [
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=date(2026, 9, 4),
                    status="success",
                    records=2308,
                    data_as_of="2026-09-04",
                ),
                IngestionRun(
                    run_type="backtest",
                    source="technical_backtest",
                    run_date=date(2026, 9, 8),
                    status="success",
                    records=9999,
                    data_as_of="2026-09-08",
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "official"
    assert payload["as_of"] == "2026-09-04"
    assert payload["data_quality"]["latest_run_source"] == "official"
    assert payload["data_quality"]["latest_run_records"] == 2308


def test_paginated_collections_support_search_and_boundaries(isolated_api):
    with isolated_api() as db:
        instruments = [
            Instrument(market="TW", exchange="TWSE", symbol="AAA", name="Alpha", instrument_type="stock", status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="BBB", name="Beta", instrument_type="stock", status="active"),
            Instrument(market="TW", exchange="TPEx", symbol="CCC", name="Gamma", instrument_type="etf", etf_category="bond", status="active"),
        ]
        groups = [
            ThemeGroup(id="group-alpha", name="Alpha Theme", group_type="official_industry", active=True),
            ThemeGroup(id="group-beta", name="Beta Theme", group_type="official_industry", active=True),
        ]
        db.add_all([*instruments, *groups])
        db.flush()
        db.add_all(
            [
                Signal(signal_key="signal-alpha", signal_date=date(2026, 9, 4), instrument_id=instruments[0].id, status="conditional", entry_type="breakout"),
                Signal(signal_key="signal-beta", signal_date=date(2026, 9, 3), instrument_id=instruments[1].id, status="observation", entry_type="pullback"),
                Event(instrument_id=instruments[0].id, event_date=date(2026, 9, 4), event_type="suspension", title="Alpha suspension", source="tpex_suspension_history"),
                Event(instrument_id=instruments[1].id, event_date=date(2026, 9, 3), event_type="announcement", title="Beta announcement", source="official_fixture"),
                RawPayload(source="twse", endpoint="/fixture/alpha", payload_path="alpha.json", sha256="a" * 64, data_as_of="2026-09-04"),
                RawPayload(source="tpex", endpoint="/fixture/beta", payload_path="beta.json", sha256="b" * 64, data_as_of="2026-09-03"),
                IngestionRun(run_type="collect", source="official", run_date=date(2026, 9, 4), status="success", records=3, request_key="collect-alpha"),
                IngestionRun(run_type="backtest", source="technical_backtest", run_date=date(2026, 9, 5), status="success", records=2, request_key="backtest-beta"),
                PortfolioPosition(instrument_id=instruments[0].id, shares=10, average_cost=100),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        instruments_page = client.get("/api/instruments?page=1&page_size=2")
        instruments_next = client.get("/api/instruments?page=2&page_size=2")
        instruments_empty = client.get("/api/instruments?page=3&page_size=2")
        instruments_search = client.get("/api/instruments?q=beta&page=1&page_size=2")
        groups_page = client.get("/api/groups?page=1&page_size=1")
        signals_page = client.get("/api/signals?q=beta&page=1&page_size=2")
        events_page = client.get("/api/events?q=Alpha&page=1&page_size=2")
        portfolio_page = client.get("/api/portfolio?q=alpha&page=1&page_size=2")
        raw_page = client.get("/api/raw-payloads?q=beta&page=1&page_size=2")
        runs_page = client.get("/api/ingestion-runs?q=backtest&page=1&page_size=2")
        quality_page = client.get("/api/data-quality?page=1&page_size=2")
        strategies_page = client.get("/api/strategies?page=1&page_size=2")

        for response in (
            instruments_page,
            instruments_next,
            instruments_empty,
            instruments_search,
            groups_page,
            signals_page,
            events_page,
            portfolio_page,
            raw_page,
            runs_page,
            quality_page,
            strategies_page,
        ):
            assert response.status_code == 200
            assert set(response.json()) == {"items", "pagination"}
            assert {"page", "page_size", "total", "total_pages", "has_previous", "has_next"} <= set(response.json()["pagination"])

    assert len(instruments_page.json()["items"]) == 2
    assert len(instruments_next.json()["items"]) == 1
    assert instruments_empty.json()["items"] == []
    assert instruments_page.json()["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total": 3,
        "total_pages": 2,
        "has_previous": False,
        "has_next": True,
    }
    assert [item["symbol"] for item in instruments_search.json()["items"]] == ["BBB"]
    assert groups_page.json()["pagination"]["total"] == 2
    assert signals_page.json()["items"][0]["instrument"]["symbol"] == "BBB"
    assert events_page.json()["items"][0]["title"] == "Alpha suspension"
    assert portfolio_page.json()["items"][0]["instrument"]["symbol"] == "AAA"
    assert raw_page.json()["items"][0]["source"] == "tpex"
    assert runs_page.json()["items"][0]["request_key"] == "backtest-beta"
    assert quality_page.json()["items"] == []
    assert strategies_page.json()["items"] == []

    with TestClient(app) as client:
        assert client.get("/api/instruments?page_size=101").status_code == 422
        assert client.get("/api/instruments?page_size=0").status_code == 422
        assert client.get("/api/instruments?page=0").status_code == 422


def test_portfolio_delete_is_idempotently_reported(isolated_api):
    with isolated_api() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="DEL", name="Delete Me", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        position = PortfolioPosition(instrument_id=instrument.id, shares=5)
        db.add(position)
        db.commit()
        position_id = position.id

    with TestClient(app) as client:
        deleted = client.delete(f"/api/portfolio/{position_id}")
        repeated = client.delete(f"/api/portfolio/{position_id}")
        missing = client.delete("/api/portfolio/999999")
        remaining = client.get("/api/portfolio")

    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "id": position_id}
    assert repeated.status_code == 404
    assert missing.status_code == 404
    assert remaining.status_code == 200 and remaining.json()["items"] == []
