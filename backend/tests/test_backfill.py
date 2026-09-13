from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import app.api as api_module
import app.main as main_module
import worker.backfill as backfill
import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    NewsItem,
    PortfolioPosition,
    RawPayload,
    Signal,
    ThemeGroup,
)


@pytest.fixture
def backfill_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", raw_dir)
    yield factory
    engine.dispose()


def _batch_for(trading_date: date, close: float = 100.0) -> sources.OfficialBatch:
    payload = sources.capture_payload(
        "twse",
        sources.TWSE_LISTED_ENDPOINT,
        {"date": trading_date.isoformat(), "fixture": "backfill"},
        trading_date.isoformat(),
    )
    instruments = [
        sources.InstrumentRecord(
            "TAIEX",
            "TAIEX",
            exchange="TWSE",
            instrument_type="index",
            industry="Index",
            payload_sha256=payload.sha256,
        ),
        sources.InstrumentRecord(
            "AAA",
            "Alpha",
            exchange="TWSE",
            instrument_type="stock",
            industry="24",
            payload_sha256=payload.sha256,
        ),
    ]
    bars = [
        sources.BarRecord(
            symbol=symbol,
            trading_date=trading_date,
            open=close,
            high=close + 2,
            low=close - 2,
            close=close,
            volume=1000,
            turnover=100000,
            exchange="TWSE",
            source="twse_fixture" if symbol != "TAIEX" else "twse_index_fixture",
            data_as_of=trading_date.isoformat(),
            payload_sha256=payload.sha256,
        )
        for symbol in ("TAIEX", "AAA")
    ]
    return sources.OfficialBatch(
        instruments=instruments,
        bars=bars,
        payloads=[payload],
        data_as_of=trading_date.isoformat(),
    )


def _no_data_batch_for(trading_date: date) -> sources.OfficialBatch:
    batch = _batch_for(trading_date)
    return sources.OfficialBatch(
        instruments=batch.instruments,
        bars=[],
        payloads=batch.payloads,
        data_as_of=trading_date.isoformat(),
        no_data_dates=[trading_date],
    )


def test_backfill_plan_is_bounded_for_phase3_targets():
    start = date(2026, 6, 10)
    end = date(2026, 9, 8)
    requested = backfill.calendar_weekday_dates(start, end)
    metadata = backfill._initial_metadata(
        {
            "scope": "market",
            "target_instruments": ["TWSE:AAA", "TPEx:BBB"],
            "target_count": 2,
            "target_type_counts": {"stock": 1, "etf": 1},
            "target_etf_categories": ["bond"],
            "all_market_count": 2,
        },
        start,
        end,
        requested,
    )
    assert len(requested) == 65
    assert metadata["coverage_targets"] == {
        "ohlcv_taiex_sessions": 65,
        "chips_events_sessions": 20,
        "max_calendar_days": 93,
    }
    assert all(item["batch_size"] <= 5 for item in metadata["batch_plan"])
    assert all(len(item["requested_dates"]) <= 5 for item in metadata["batch_plan"])
    assert metadata["retry_policy"] == {
        "immediate_attempts": 3,
        "targeted_retry_attempts": 2,
        "total_attempts_per_date": 5,
        "backoff": "delegated to official adapter; no unbounded retry",
    }
    assert {item["exchange"] for item in metadata["batch_plan"]} == {"TWSE", "TPEx"}
    assert {item["domain"] for item in metadata["batch_plan"]} == set(backfill.BACKFILL_DOMAINS)


def test_full_target_extends_before_range_for_two_no_data_weekdays(backfill_env):
    start = date(2026, 6, 10)
    end = date(2026, 9, 8)
    holidays = {date(2026, 6, 19), date(2026, 7, 10)}

    class HolidayAdapter:
        calls: list[date] = []

        def fetch(self, requested_start: date, requested_end: date) -> sources.OfficialBatch:
            assert requested_start == requested_end
            self.calls.append(requested_start)
            return _no_data_batch_for(requested_start) if requested_start in holidays else _batch_for(requested_start)

    adapter = HolidayAdapter()
    result = backfill.targeted_backfill(start, end, adapter=adapter)
    metadata = result["metadata"]
    assert result["status"] == "partial"
    assert len(metadata["requested_calendar_dates"]) == 65
    assert len(metadata["verified_trading_sessions"]) == 65
    assert metadata["target_met"] is True
    assert metadata["skipped_non_trading"] == sorted(day.isoformat() for day in holidays)
    assert {"2026-06-08", "2026-06-09"}.issubset(set(metadata["extension_dates"]))
    assert all(item["batch_size"] <= 5 for item in metadata["batch_plan"])
    assert set(adapter.calls) == set(backfill.calendar_weekday_dates(start, end)) | {
        date(2026, 6, 8), date(2026, 6, 9)
    }

    with backfill_env() as db:
        before = {
            name: db.query(model).count()
            for name, model in (
                ("bars", MarketBar),
                ("chips", ChipSnapshot),
                ("raw", RawPayload),
            )
        }

    class MustNotRefetch:
        def fetch(self, requested_start: date, requested_end: date) -> sources.OfficialBatch:  # pragma: no cover
            raise AssertionError(f"verified/skipped date was fetched again: {requested_start}")

    resumed = backfill.targeted_backfill(start, end, adapter=MustNotRefetch())
    assert resumed["id"] == result["id"]
    assert resumed["metadata"]["target_met"] is True
    assert resumed["metadata"]["verified_trading_sessions"] == metadata["verified_trading_sessions"]
    with backfill_env() as db:
        after = {
            name: db.query(model).count()
            for name, model in (
                ("bars", MarketBar),
                ("chips", ChipSnapshot),
                ("raw", RawPayload),
            )
        }
    assert after == before


def test_coverage_uses_effective_sessions_for_stock_ipo_and_etf_boundaries(backfill_env):
    sessions: list[date] = []
    cursor = date(2026, 6, 1)
    while len(sessions) < 63:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)

    with backfill_env() as db:
        instruments = [
            Instrument(market="TW", exchange="TWSE", symbol="STOCK", name="Stock", instrument_type="stock", status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="BOND", name="Bond ETF", instrument_type="etf", etf_category="bond", status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="IPO19", name="IPO 19", instrument_type="ipo", listing_date=sessions[-19], status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="IPO20", name="IPO 20", instrument_type="ipo", listing_date=sessions[-20], status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="IPO59", name="IPO 59", instrument_type="ipo", listing_date=sessions[-59], status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="IPO60", name="IPO 60", instrument_type="ipo", listing_date=sessions[-60], status="active"),
            Instrument(market="TW", exchange="TWSE", symbol="TAIEX", name="TAIEX", instrument_type="index", status="active"),
        ]
        db.add_all(instruments)
        db.flush()
        for trading_date in sessions:
            for instrument in instruments:
                if instrument.instrument_type != "index" and instrument.listing_date and trading_date < instrument.listing_date:
                    continue
                db.add(
                    MarketBar(
                        instrument_id=instrument.id,
                        trading_date=trading_date,
                        open=100,
                        high=101,
                        low=99,
                        close=100,
                        adj_close=100,
                        volume=100,
                        turnover=10000,
                        source="fixture",
                    )
                )
                if instrument.instrument_type != "index":
                    db.add(
                        ChipSnapshot(
                            instrument_id=instrument.id,
                            trading_date=trading_date,
                            foreign_buy=1,
                            trust_buy=1,
                            dealer_buy=1,
                            margin_balance=10,
                            margin_change=1,
                            source="fixture",
                        )
                    )
        db.commit()
        report = backfill.coverage_report(
            db,
            sessions[0],
            sessions[-1],
            target_keys={("TWSE", item.symbol) for item in instruments if item.instrument_type != "index"},
        )

    rows = {row["symbol"]: row for row in report["instrument_coverage"]}
    assert rows["STOCK"]["missing_bars_to_60"] == 0
    assert rows["STOCK"]["effective_bar_sessions"] == 63
    assert rows["IPO19"]["missing_bars_to_20"] == 1
    assert rows["IPO19"]["ipo_stage"] == "not_observable"
    assert rows["IPO20"]["missing_bars_to_20"] == 0
    assert rows["IPO20"]["missing_bars_to_60"] == 40
    assert rows["IPO20"]["ipo_stage"] == "observation_only"
    assert rows["IPO59"]["missing_bars_to_60"] == 1
    assert rows["IPO59"]["ipo_stage"] == "observation_only"
    assert rows["IPO60"]["missing_bars_to_60"] == 0
    assert rows["IPO60"]["ipo_stage"] == "actionable_eligible"
    assert rows["BOND"]["missing_bars_to_60"] == 0
    assert "etf_not_general_action_eligible" in rows["BOND"]["coverage_reasons"]
    assert report["summary"]["incomplete_to_60"] == 3
    assert report["summary"]["coverage_reason_counts"]["listed_under_threshold"] >= 3


def test_event_coverage_counts_verified_empty_not_event_date_rows(backfill_env):
    first = date(2026, 9, 3)
    second = date(2026, 9, 4)
    third = date(2026, 9, 7)
    with backfill_env() as db:
        taiex = Instrument(market="TW", exchange="TWSE", symbol="TAIEX", name="TAIEX", instrument_type="index", status="active")
        stock = Instrument(market="TW", exchange="TWSE", symbol="AAA", name="Alpha", instrument_type="stock", status="active")
        db.add_all([taiex, stock])
        db.flush()
        for trading_date in (first, second):
            db.add_all([
                MarketBar(instrument_id=taiex.id, trading_date=trading_date, open=100, high=101, low=99, close=100, adj_close=100, volume=1, turnover=1, source="fixture"),
                MarketBar(instrument_id=stock.id, trading_date=trading_date, open=100, high=101, low=99, close=100, adj_close=100, volume=1, turnover=1, source="fixture"),
            ])
        db.add_all([
            Event(instrument_id=stock.id, event_date=second, event_type="official", title="Observed event", source="official"),
            Event(instrument_id=stock.id, event_date=third, event_type="official", title="Observed event", source="official"),
        ])
        db.commit()
        report = backfill.coverage_report(
            db,
            first,
            third,
            target_keys={("TWSE", "AAA")},
            event_coverage_by_date={
                first.isoformat(): {"status": "verified_empty", "empty_dates": [first.isoformat()]},
                second.isoformat(): {"status": "unsupported", "unsupported_dates": [second.isoformat()]},
            },
        )

    event_coverage = report["summary"]["event_coverage"]
    assert event_coverage["verified_sessions"] == 1
    assert event_coverage["verified_empty_sessions"] == 1
    assert event_coverage["unsupported_sessions"] == 1
    assert event_coverage["observed_event_dates"] == 2
    assert event_coverage["observed_event_dates"] != event_coverage["verified_sessions"]
    assert report["date_coverage"][0]["event_coverage_status"] == "verified_empty"
    assert report["date_coverage"][1]["event_coverage_status"] == "unsupported"


def test_backfill_partial_retry_and_idempotent_resume(backfill_env):
    first = date(2026, 9, 3)
    second = date(2026, 9, 4)

    class FirstAttempt:
        calls: list[date] = []

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls.append(start)
            if start == second:
                raise sources.OfficialDataError("fixture transient failure")
            return _batch_for(start)

    initial_adapter = FirstAttempt()
    initial = backfill.targeted_backfill(first, second, adapter=initial_adapter)
    assert initial["status"] == "partial"
    assert initial["metadata"]["completed_dates"] == [first.isoformat()]
    assert initial["metadata"]["failed_dates"] == [second.isoformat()]
    assert initial["metadata"]["coverage_manifest"][first.isoformat()]["raw_payload_ids"]
    assert initial["metadata"]["next_retry"] == {
        "start_date": second.isoformat(),
        "end_date": second.isoformat(),
        "dates": [second.isoformat()],
    }

    class RetryAttempt:
        calls: list[date] = []

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls.append(start)
            assert start == second
            return _batch_for(start, close=101.0)

    retry_adapter = RetryAttempt()
    resumed = backfill.targeted_backfill(first, second, adapter=retry_adapter)
    assert resumed["status"] == "success"
    assert resumed["metadata"]["completed_dates"] == [first.isoformat(), second.isoformat()]
    assert resumed["metadata"]["failed_dates"] == []
    assert retry_adapter.calls == [second]
    assert resumed["metadata"]["coverage_manifest"][second.isoformat()]["raw_payload_ids"]

    reused = backfill.targeted_backfill(first, second, adapter=RetryAttempt())
    assert reused["status"] == "success"
    assert reused["id"] == resumed["id"]

    with backfill_env() as db:
        assert db.scalar(select(func.count(IngestionRun.id)).where(IngestionRun.run_type == "backfill")) == 1
        assert db.scalar(select(func.count(IngestionRun.id)).where(IngestionRun.run_type == "collect")) == 2
        assert db.scalar(select(func.count(MarketBar.id))) == 4
        assert db.scalar(select(func.count(RawPayload.id))) == 2
        assert db.scalar(
            select(func.count(RawPayload.id)).where(RawPayload.ingestion_run_id.is_(None))
        ) == 0
        coverage = backfill.coverage_report(db, first, second)
        assert coverage["session_basis"] == "taiex_observed"
        assert coverage["session_count"] == 2
        aaa = next(row for row in coverage["instrument_coverage"] if row["symbol"] == "AAA")
        assert aaa["missing_bars_to_20"] == 18
        assert coverage["date_coverage"][0]["taiex_rows"] == 1


def test_backfill_retries_existing_collect_without_verified_taiex(backfill_env):
    """A security-only successful collect must not satisfy the session target."""

    trading_date = date(2026, 9, 8)
    request_key = f"official-ohlcv:{trading_date.isoformat()}:{trading_date.isoformat()}"
    with backfill_env() as db:
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=trading_date,
                status="success",
                records=1,
                data_as_of=trading_date.isoformat(),
                request_key=request_key,
                metadata_json={"records": 1, "taiex_records": 0},
            )
        )
        db.commit()

    class RecoveryAdapter:
        calls: list[date] = []

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls.append(start)
            return _batch_for(start)

    adapter = RecoveryAdapter()
    recovered = backfill.targeted_backfill(
        trading_date,
        trading_date,
        adapter=adapter,
    )

    assert recovered["metadata"]["verified_trading_sessions"] == [
        trading_date.isoformat()
    ]
    assert recovered["metadata"]["completed_dates"] == [trading_date.isoformat()]
    assert recovered["metadata"]["partial_dates"] == []
    assert adapter.calls == [trading_date]

    class MustNotRefetch:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:  # pragma: no cover
            raise AssertionError("verified date was fetched again")

    resumed = backfill.targeted_backfill(
        trading_date,
        trading_date,
        adapter=MustNotRefetch(),
    )
    assert resumed["id"] == recovered["id"]
    assert resumed["status"] == "success"
    assert resumed["metadata"]["target_met"] is True


def test_backfill_does_not_complete_security_bars_without_taiex(backfill_env):
    trading_date = date(2026, 9, 8)
    full_batch = _batch_for(trading_date)
    security_only = sources.OfficialBatch(
        instruments=full_batch.instruments,
        bars=[bar for bar in full_batch.bars if bar.symbol != "TAIEX"],
        payloads=full_batch.payloads,
        data_as_of=full_batch.data_as_of,
    )

    class PartialAdapter:
        calls = 0

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls += 1
            return security_only

    partial_adapter = PartialAdapter()
    partial = backfill.targeted_backfill(
        trading_date,
        trading_date,
        adapter=partial_adapter,
    )
    assert partial["metadata"]["completed_dates"] == []
    assert partial["metadata"]["partial_dates"] == [trading_date.isoformat()]
    assert partial["metadata"]["verified_trading_sessions"] == []
    assert partial_adapter.calls == 3


def test_backfill_explicit_no_data_is_skipped_and_not_retried(backfill_env):
    trading_date = date(2026, 9, 4)

    class NoDataAdapter:
        calls: list[date] = []

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls.append(start)
            return _no_data_batch_for(start)

    adapter = NoDataAdapter()
    initial = backfill.targeted_backfill(trading_date, trading_date, adapter=adapter)
    assert initial["status"] == "partial"
    assert initial["metadata"]["skipped_dates"] == [trading_date.isoformat()]
    assert initial["metadata"]["coverage"]["skipped_non_trading_dates"] == [
        trading_date.isoformat()
    ]
    assert initial["metadata"]["coverage_manifest"][trading_date.isoformat()]["no_data"] is True
    assert initial["metadata"]["coverage_manifest"][trading_date.isoformat()]["status"] == "skipped_non_trading"
    assert adapter.calls == [trading_date]

    class MustNotRetry:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:  # pragma: no cover
            raise AssertionError("explicit no-data dates must be resumable without a refetch")

    resumed = backfill.targeted_backfill(trading_date, trading_date, adapter=MustNotRetry())
    assert resumed["id"] == initial["id"]
    assert resumed["metadata"]["reused_dates"] == [trading_date.isoformat()]


def test_backfill_retry_budget_is_three_immediate_plus_two_targeted(backfill_env):
    trading_date = date(2026, 9, 4)

    class AlwaysFail:
        calls = 0

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls += 1
            raise sources.OfficialDataError("fixture retry exhausted")

    first_adapter = AlwaysFail()
    first = backfill.targeted_backfill(trading_date, trading_date, adapter=first_adapter)
    assert first["status"] == "failed"
    assert first_adapter.calls == 3
    assert first["metadata"]["attempts"] == {trading_date.isoformat(): 3}
    assert first["metadata"]["next_retry"]["dates"] == [trading_date.isoformat()]

    second_adapter = AlwaysFail()
    second = backfill.targeted_backfill(trading_date, trading_date, adapter=second_adapter)
    assert second["status"] == "failed"
    assert second_adapter.calls == 2
    assert second["metadata"]["attempts"] == {trading_date.isoformat(): 5}
    assert second["metadata"]["retry_exhausted_dates"] == [trading_date.isoformat()]
    assert second["metadata"]["next_retry"] is None

    third_adapter = AlwaysFail()
    third = backfill.targeted_backfill(trading_date, trading_date, adapter=third_adapter)
    assert third["id"] == second["id"]
    assert third_adapter.calls == 0


def test_failed_force_retry_does_not_overwrite_verified_row(backfill_env):
    trading_date = date(2026, 9, 4)
    good = _batch_for(trading_date, close=123.0)

    class GoodAdapter:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            return good

    first = pipeline.collect(trading_date, adapter=GoodAdapter())
    assert first["status"] == "success"

    class BadAdapter:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            raise sources.OfficialDataError("fixture retry exhausted")

    failed = pipeline.collect(trading_date, adapter=BadAdapter(), force=True)
    assert failed["status"] == "failed"
    with backfill_env() as db:
        instrument_id = db.scalar(select(Instrument.id).where(Instrument.symbol == "AAA"))
        row = db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument_id, MarketBar.trading_date == trading_date))
        assert row and row.close == 123.0


def test_scope_resolution_prioritizes_portfolio_watchlist_events_and_candidates(backfill_env):
    start = date(2026, 9, 1)
    end = date(2026, 9, 4)
    with backfill_env() as db:
        held = Instrument(market="TW", exchange="TWSE", symbol="HLD", name="Held", instrument_type="stock", status="active")
        watched = Instrument(market="TW", exchange="TPEx", symbol="WAT", name="Watched", instrument_type="stock", is_watchlisted=True, status="active")
        evented = Instrument(market="TW", exchange="TWSE", symbol="EVT", name="Event", instrument_type="stock", status="active")
        candidate = Instrument(market="TW", exchange="TWSE", symbol="CAN", name="Candidate", instrument_type="stock", status="active")
        etf = Instrument(market="TW", exchange="TWSE", symbol="ETF1", name="ETF", instrument_type="etf", etf_category="bond", status="active")
        ipo = Instrument(market="TW", exchange="TPEx", symbol="IPO1", name="IPO", instrument_type="ipo", status="active")
        db.add_all([held, watched, evented, candidate, etf, ipo])
        db.flush()
        db.add(PortfolioPosition(instrument_id=held.id, shares=10))
        db.add(Event(instrument_id=evented.id, event_date=end, event_type="official", title="Event"))
        db.add(Signal(signal_key="candidate-signal", signal_date=end, instrument_id=candidate.id, status="observation"))
        db.commit()

        info = backfill.resolve_backfill_scope(db, "priority", start, end)
        keys = set(info["target_keys"])
        assert ("TWSE", "HLD") in keys
        assert ("TPEx", "WAT") in keys
        assert ("TWSE", "EVT") in keys
        assert ("TWSE", "CAN") in keys
        assert info["target_type_counts"] == {"stock": 4}

        market_info = backfill.resolve_backfill_scope(db, "market", start, end)
        assert market_info["target_type_counts"] == {"etf": 1, "ipo": 1, "stock": 4}
        assert market_info["target_etf_categories"] == ["bond"]


def test_coverage_manifest_reports_events_memberships_and_stale_status(backfill_env):
    trading_date = date(2026, 9, 4)
    later_date = date(2026, 9, 7)
    with backfill_env() as db:
        taiex = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="TAIEX",
            name="TAIEX",
            instrument_type="index",
            status="active",
        )
        aaa = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="AAA",
            name="Alpha",
            instrument_type="stock",
            status="active",
        )
        group = ThemeGroup(
            id="official-industry-test",
            name="Industry: test",
            group_type="official_industry",
            active=True,
            name_status="verified",
        )
        db.add_all([taiex, aaa, group])
        db.flush()
        db.add(
            GroupMembership(
                group_id=group.id,
                instrument_id=aaa.id,
                valid_from=trading_date,
                source="official fixture",
            )
        )
        db.add_all(
            [
                MarketBar(
                    instrument_id=taiex.id,
                    trading_date=trading_date,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=0,
                    turnover=0,
                    source="fixture",
                ),
                MarketBar(
                    instrument_id=aaa.id,
                    trading_date=trading_date,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=100,
                    turnover=10000,
                    source="fixture",
                ),
                ChipSnapshot(
                    instrument_id=aaa.id,
                    trading_date=trading_date,
                    foreign_buy=1,
                    trust_buy=1,
                    dealer_buy=1,
                    margin_balance=10,
                    margin_change=1,
                    source="fixture",
                ),
                Event(
                    instrument_id=aaa.id,
                    event_date=trading_date,
                    event_type="official",
                    title="Fixture event",
                    source="official",
                ),
                CorporateAction(
                    instrument_id=aaa.id,
                    action_date=trading_date,
                    action_type="cash_dividend",
                    source="official",
                ),
            ]
        )
        db.commit()
        report = backfill.coverage_report(
            db,
            trading_date,
            later_date,
            target_keys={("TWSE", "AAA")},
        )

    assert report["date_coverage"][0]["status"] == "success"
    assert report["date_coverage"][0]["event_rows"] == 1
    assert report["date_coverage"][0]["corporate_action_rows"] == 1
    assert report["date_coverage"][0]["membership_instruments"] == 1
    assert report["date_coverage"][1]["status"] == "stale"
    row = report["instrument_coverage"][0]
    assert row["event_rows"] == 1
    assert row["corporate_action_rows"] == 1
    assert row["membership_days"] == 1
    assert report["summary"]["stale_dates"] == [later_date.isoformat()]


def test_backfill_status_and_coverage_api(backfill_env, monkeypatch):
    trading_date = date(2026, 9, 4)

    class GoodAdapter:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            return _batch_for(start)

    result = backfill.targeted_backfill(trading_date, trading_date, adapter=GoodAdapter())
    with backfill_env() as db:
        factory = backfill_env
        # The API dependency is replaced below with the same isolated factory
        # used by the backfill worker; this avoids any production DB access.
        _ = factory

    with backfill_env() as db:
        def override_get_db():
            yield db

        monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
        app.dependency_overrides[api_module.get_db] = override_get_db
        try:
            with TestClient(app) as client:
                runs = client.get("/api/backfill-runs?page=1&page_size=10")
                coverage = client.get("/api/coverage?start_date=2026-09-04&end_date=2026-09-04&symbol=AAA")
        finally:
            app.dependency_overrides.pop(api_module.get_db, None)

    assert result["status"] == "success"
    assert runs.status_code == 200
    assert runs.json()["items"][0]["run_type"] == "backfill"
    assert coverage.status_code == 200
    assert coverage.json()["scope"] == "instrument_filter"
    assert coverage.json()["instrument_coverage"][0]["symbol"] == "AAA"


def test_official_snapshot_coverage_fallback_uses_raw_taiex_and_effective_gaps(
    backfill_env,
    monkeypatch,
):
    """An official one-day DB without a backfill manifest remains measurable."""

    as_of = date(2026, 9, 8)
    with backfill_env() as db:
        run = IngestionRun(
            run_type="collect",
            source="official",
            run_date=as_of,
            status="success",
            records=2,
            data_as_of=as_of.isoformat(),
            request_key="official-snapshot-only",
        )
        db.add(run)
        db.flush()
        payload = sources.capture_payload(
            "twse",
            "https://www.twse.com.tw/exchangeReport/MI_INDEX?date=20260908&type=ALLBUT0999",
            {
                "date": "20260908",
                "stat": "OK",
                "tables": [
                    {
                        "title": "115年09月08日 價格指數(臺灣證券交易所)",
                        "fields": ["指數", "收盤指數"],
                        "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "47326.27"]],
                    }
                ],
            },
            as_of.isoformat(),
        )
        raw = RawPayload(
            ingestion_run_id=run.id,
            source=payload.source,
            endpoint=payload.endpoint,
            payload_path=str(payload.payload_path),
            sha256=payload.sha256,
            data_as_of=payload.data_as_of,
        )
        taiex = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="TAIEX",
            name="TAIEX",
            instrument_type="index",
            status="active",
        )
        stock = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="2330",
            name="Fixture stock",
            instrument_type="stock",
            status="active",
        )
        db.add_all([raw, taiex, stock])
        db.flush()
        db.add_all(
            [
                MarketBar(
                    instrument_id=stock.id,
                    trading_date=as_of,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=1000,
                    turnover=100000,
                    source="twse",
                    raw_payload_id=raw.id,
                ),
                ChipSnapshot(
                    instrument_id=stock.id,
                    trading_date=as_of,
                    foreign_buy=1,
                    trust_buy=2,
                    dealer_buy=3,
                    margin_balance=10,
                    margin_change=1,
                    source="twse",
                    raw_payload_id=raw.id,
                ),
            ]
        )
        db.commit()

    def override_get_db():
        with backfill_env() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            coverage = client.get("/api/coverage")
            stock_detail = client.get("/api/stocks/TWSE/2330")
    finally:
        app.dependency_overrides.pop(api_module.get_db, None)

    assert coverage.status_code == 200
    report = coverage.json()
    assert report["session_basis"] == "official_snapshot"
    assert report["summary"]["coverage_status"] == "snapshot"
    assert report["summary"]["verified_taiex_sessions"] == 1
    assert report["summary"]["target_ohlcv_taiex_sessions"] == 65
    assert report["summary"]["target_met"] is False
    assert report["expected_dates"] == [as_of.isoformat()]
    assert len(report["date_coverage"]) == 1
    assert report["date_coverage"][0]["taiex_rows"] == 1

    assert stock_detail.status_code == 200
    stock_coverage = stock_detail.json()["coverage"]
    assert stock_coverage["verified_taiex_sessions"] == 1
    assert stock_coverage["effective_bar_sessions"] == 1
    assert stock_coverage["effective_chip_sessions"] == 1
    assert stock_coverage["missing_bars_to_20"] == 19
    assert stock_coverage["missing_bars_to_60"] == 59
    assert stock_coverage["missing_chips_to_20"] == 19


def test_coverage_without_verified_baseline_is_unknown_and_compact(backfill_env, monkeypatch):
    with backfill_env() as db:
        run = IngestionRun(
            run_type="collect",
            source="official",
            run_date=date(2026, 9, 8),
            status="success",
            records=1,
            data_as_of="2026-09-08",
            request_key="official-no-index-fixture",
        )
        stock = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="NOBASE",
            name="No baseline",
            instrument_type="stock",
            status="active",
        )
        db.add_all([run, stock])
        db.flush()
        db.add(
            MarketBar(
                instrument_id=stock.id,
                trading_date=date(2026, 9, 8),
                open=10,
                high=11,
                low=9,
                close=10,
                adj_close=10,
                volume=1,
                turnover=10,
                source="official",
            )
        )
        db.commit()
        report = backfill.coverage_report(
            db,
            date(2026, 9, 8),
            date(2026, 9, 8),
            require_provenance=True,
            include_calendar_dates=False,
        )

    def override_get_db():
        with backfill_env() as db:
            yield db

    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/api/coverage")
    finally:
        app.dependency_overrides.pop(api_module.get_db, None)

    assert report["summary"]["coverage_status"] == "unknown"
    assert report["summary"]["instrument_count"] == 0
    assert report["summary"]["coverage_reason_counts"] == {}
    assert report["date_coverage"] == []
    assert response.status_code == 200
    assert response.json()["summary"]["coverage_status"] == "unknown"
    assert response.json()["instrument_coverage"] == []
    assert response.json()["date_coverage"] == []


def test_snapshot_fallback_rejects_raw_payload_with_wrong_reported_date(backfill_env):
    as_of = date(2026, 9, 8)
    with backfill_env() as db:
        run = IngestionRun(
            run_type="collect",
            source="official",
            run_date=as_of,
            status="success",
            records=1,
            data_as_of=as_of.isoformat(),
            request_key="official-wrong-date-fixture",
        )
        db.add(run)
        db.flush()
        payload = sources.capture_payload(
            "twse",
            "https://www.twse.com.tw/exchangeReport/MI_INDEX?date=20260908&type=ALLBUT0999",
            {
                "date": "20260907",
                "stat": "OK",
                "tables": [
                    {
                        "fields": ["指數", "收盤指數"],
                        "data": [["\u767c\u884c\u91cf\u52a0\u6b0a\u80a1\u50f9\u6307\u6578", "47326.27"]],
                    }
                ],
            },
            as_of.isoformat(),
        )
        db.add(
            RawPayload(
                ingestion_run_id=run.id,
                source=payload.source,
                endpoint=payload.endpoint,
                payload_path=str(payload.payload_path),
                sha256=payload.sha256,
                data_as_of=payload.data_as_of,
            )
        )
        db.commit()
        report = backfill.coverage_report(
            db,
            as_of,
            as_of,
            require_provenance=True,
            include_calendar_dates=False,
        )

    assert report["session_count"] == 0
    assert report["summary"]["coverage_status"] == "unknown"
    assert report["summary"]["instrument_count"] == 0
