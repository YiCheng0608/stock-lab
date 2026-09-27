from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
import worker.sources as sources
from app.db import Base, enable_sqlite_foreign_keys
from app.domain import (
    LEGACY_SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    signal_confidence_semantics,
)
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    DataQuality,
    Event,
    GroupDailyScore,
    GroupMembership,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
    Signal,
    SignalEvaluation,
    SignalSettlement,
    TechnicalFeature,
    ThemeGroup,
)


@pytest.fixture
def pipeline_env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


def _fixture_payload() -> sources.FetchedPayload:
    return sources.capture_payload(
        "twse",
        sources.TWSE_LISTED_ENDPOINT,
        {"fixture": "official", "version": 1},
        "2026-09-04",
        collected_at=datetime(2026, 9, 4, 1),
    )


def test_turnover_status_survives_upsert_and_gates_both_ratios_in_memory():
    from app.api import bar_dict

    engine = create_engine("sqlite:///:memory:")
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    score_date = date(2026, 9, 4)
    days = pipeline.business_days(score_date, 20)
    try:
        with sessionmaker(bind=engine, autoflush=False)() as db:
            instrument = Instrument(
                market="TW", exchange="TWSE", symbol="STATUS", name="Status fixture",
                instrument_type="stock", status="active",
            )
            db.add(instrument)
            db.flush()
            for trading_date in days:
                db.add(MarketBar(
                    instrument_id=instrument.id, trading_date=trading_date,
                    open=100, high=105, low=98, close=103, adj_close=103,
                    volume=1000, turnover=100, turnover_status="available", source="fixture",
                ))
            for trading_date in days[-5:]:
                db.add(ChipSnapshot(
                    instrument_id=instrument.id, trading_date=trading_date,
                    foreign_buy=10, trust_buy=10, dealer_buy=10, source="fixture",
                ))
            db.flush()
            assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is not None
            assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is not None

            positive_bar = db.scalar(select(MarketBar).where(
                MarketBar.instrument_id == instrument.id,
                MarketBar.trading_date == score_date,
            ))
            assert positive_bar is not None and positive_bar.turnover == 100
            for status, reason in (("unavailable", "invalid"), ("unknown", "legacy_zero_ambiguous")):
                positive_bar.turnover_status = status
                positive_bar.turnover_reason = reason
                db.flush()
                assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is None
                assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is None
            positive_bar.turnover_status = "available"
            positive_bar.turnover_reason = None
            db.flush()
            assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is not None
            assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is not None

            row = {
                "Code": "STATUS", "Date": score_date.isoformat(),
                "OpeningPrice": "100", "HighestPrice": "105", "LowestPrice": "98", "ClosingPrice": "103",
                "TradeVolume": "1000",
            }
            missing = sources.parse_twse_daily_rows([row])[0]
            bar = pipeline._upsert_official_bar(db, instrument, missing, None)
            db.flush()
            bar_id = bar.id
            db.expire_all()
            bar = db.get(MarketBar, bar_id)
            assert bar is not None
            assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (100, 105, 98, 103, 1000)
            assert (bar.turnover, bar.turnover_status, bar.turnover_reason) == (0, "unavailable", "missing")
            assert (bar_dict(bar)["turnover_status"], bar_dict(bar)["turnover_reason"]) == (
                "unavailable", "missing"
            )
            assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is None
            assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is None

            explicit_zero = sources.parse_twse_daily_rows([{**row, "TradeValue": "0"}])[0]
            pipeline._upsert_official_bar(db, instrument, explicit_zero, None)
            db.flush()
            db.expire_all()
            bar = db.get(MarketBar, bar_id)
            assert bar is not None
            assert (bar.turnover, bar.turnover_status, bar.turnover_reason) == (0, "available", None)
            assert (bar_dict(bar)["turnover_status"], bar_dict(bar)["turnover_reason"]) == (
                "available", None
            )
            assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is None
            assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is None

            bar.turnover_status = "unknown"
            bar.turnover_reason = "legacy_zero_ambiguous"
            db.flush()
            assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is None
            assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is None
    finally:
        engine.dispose()


def test_empty_short_backtest_summary_stays_insufficient_sample(pipeline_env):
    with pipeline_env() as db:
        run = IngestionRun(
            run_type="backtest",
            source="technical_backtest",
            run_date=date(2026, 9, 4),
            status="success",
            request_key="technical-backtest:v1:2026-06-03:2026-09-04",
            data_as_of="2026-09-04",
            metadata_json={
                "workflow": "technical_backtest_v1",
                "start_date": "2026-06-03",
                "end_date": "2026-09-04",
                "score_session_count": 68,
            },
        )
        db.add(run)
        db.commit()

        summary = pipeline.summarize_backtest(db, run.id)

    assert summary["groups"] == []
    assert summary["assessment"] == "insufficient_sample"
    assert summary["zero_actionable_count"] == 0
    assert summary["run"]["assessment"] == "insufficient_sample"
    assert summary["run"]["zero_actionable_count"] == 0


def test_collect_is_official_only_idempotent_and_links_raw_payloads(pipeline_env, monkeypatch):
    payload = _fixture_payload()
    etf_payload = sources.capture_payload("twse", sources.TWSE_ETF_ENDPOINT, {"fixture": "ETF"}, "2026-09-04", collected_at=datetime(2026, 9, 4, 1))
    score_date = date(2026, 9, 4)
    instruments = [
        sources.InstrumentRecord("TAIEX", "TAIEX", exchange="TWSE", instrument_type="index", industry="Index", payload_sha256=payload.sha256),
        sources.InstrumentRecord("AAA", "Alpha Corp", exchange="TWSE", industry="24", payload_sha256=payload.sha256),
        sources.InstrumentRecord("0050", "Taiwan 50", exchange="TWSE", instrument_type="etf", etf_category="broad_market", payload_sha256=etf_payload.sha256),
    ]
    bars = [
        sources.BarRecord(symbol=item.symbol, trading_date=score_date, open=100, high=105, low=98, close=103, volume=1000, turnover=103000, exchange="TWSE", source="twse_index" if item.symbol == "TAIEX" else "twse", data_as_of=score_date.isoformat(), payload_sha256=payload.sha256, turnover_status="available")
        for item in instruments
    ]
    actions = [sources.ActionRecord("AAA", date(2026, 8, 20), "ex_dividend", cash_dividend=1.0, exchange="TWSE", payload_sha256=payload.sha256)]
    fundamentals = [sources.FundamentalRecord("AAA", date(2026, 6, 30), "Q2", eps=2.0, exchange="TWSE", payload_sha256=payload.sha256)]
    events = [sources.EventRecord("AAA", score_date, "material_information", "fixture event", exchange="TWSE", payload_sha256=payload.sha256)]
    chips = [sources.ChipRecord("AAA", score_date, foreign_buy=10.0, trust_buy=2.0, dealer_buy=1.0, margin_balance=100.0, margin_change=3.0, exchange="TWSE", source="twse_fixture", data_as_of=score_date.isoformat(), payload_sha256=payload.sha256)]
    batch = sources.OfficialBatch(instruments=instruments, bars=bars, chips=chips, actions=actions, fundamentals=fundamentals, events=events, payloads=[payload, etf_payload], data_as_of=score_date.isoformat())

    class FakeAdapter:
        calls = 0

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            self.calls += 1
            return batch

    adapter = FakeAdapter()
    result = pipeline.collect(score_date, adapter=adapter)
    assert result["status"] == "success"
    assert result["records"] == 3
    assert result["raw_payloads"] == 2
    assert adapter.calls == 1

    with pipeline_env() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.id == result["run_id"]))
        raw = db.scalar(select(RawPayload).where(RawPayload.ingestion_run_id == run.id)) if run else None
        bar = db.scalar(select(MarketBar).where(MarketBar.instrument_id == db.scalar(select(Instrument.id).where(Instrument.symbol == "AAA")), MarketBar.trading_date == score_date))
        action = db.scalar(select(CorporateAction))
        chip = db.scalar(select(ChipSnapshot))
        index_bar = db.scalar(select(MarketBar).where(MarketBar.trading_date == score_date, MarketBar.instrument_id == db.scalar(select(Instrument.id).where(Instrument.symbol == "TAIEX"))))
        assert run and run.status == "success" and run.records == 3
        assert raw and raw.sha256 == payload.sha256 and raw.endpoint == payload.endpoint and raw.ingestion_run_id == run.id
        assert raw.payload_path and raw.data_as_of == payload.data_as_of
        assert bar and bar.raw_payload_id == raw.id
        assert index_bar and index_bar.raw_payload_id == raw.id
        assert action and action.raw_payload_id == raw.id
        assert chip and chip.raw_payload_id == raw.id and chip.foreign_buy == 10.0 and chip.margin_change == 3.0

    reused = pipeline.collect(score_date, adapter=adapter)
    assert reused["status"] == "success"
    assert reused["raw_payloads"] == 2
    assert reused["chips"] == 1
    assert reused["actions"] == 1
    assert reused["events"] == 1
    assert reused["fundamentals"] == 1
    assert reused["idempotent_reuse"] is True
    assert adapter.calls == 1


def test_collect_marks_official_source_warning_partial(pipeline_env):
    payload = _fixture_payload()
    score_date = date(2026, 9, 4)
    instruments = [
        sources.InstrumentRecord("TAIEX", "TAIEX", exchange="TWSE", instrument_type="index", industry="Index", payload_sha256=payload.sha256),
        sources.InstrumentRecord("AAA", "Alpha Corp", exchange="TWSE", industry="24", payload_sha256=payload.sha256),
    ]
    bars = [
        sources.BarRecord(
            symbol=item.symbol,
            trading_date=score_date,
            open=100,
            high=105,
            low=98,
            close=103,
            volume=1000,
            turnover=103000,
            turnover_status="available",
            exchange="TWSE",
            source="twse_index" if item.symbol == "TAIEX" else "twse",
            data_as_of=score_date.isoformat(),
            payload_sha256=payload.sha256,
        )
        for item in instruments
    ]
    batch = sources.OfficialBatch(
        instruments=instruments,
        bars=bars,
        payloads=[payload],
        warnings=["TWSE MI_INDEX unavailable for 2026-09-03 endpoint=fixture"],
        data_as_of=score_date.isoformat(),
    )

    class WarningAdapter:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            return batch

    result = pipeline.collect(score_date, adapter=WarningAdapter())
    assert result["status"] == "partial"
    assert result["warnings"] == batch.warnings
    with pipeline_env() as db:
        run = db.get(IngestionRun, result["run_id"])
        quality = db.scalar(
            select(DataQuality).where(
                DataQuality.entity_type == "ingestion_run",
                DataQuality.entity_key == f"official-ohlcv:{score_date.isoformat()}:{score_date.isoformat()}",
            )
        )
        assert run and run.status == "partial"
        assert quality and "official_warnings" in quality.missing_fields_json


def test_collect_preserves_raw_capture_when_normalization_fails(pipeline_env):
    payload = _fixture_payload()
    score_date = date(2026, 9, 3)
    batch = sources.OfficialBatch(
        instruments=[sources.InstrumentRecord("AAA", "Alpha", exchange="TWSE", industry="24", payload_sha256=payload.sha256)],
        bars=[sources.BarRecord("NOT_IN_UNIVERSE", score_date, 1, 1, 1, 1, 1, 1, exchange="TWSE", source="twse", payload_sha256=payload.sha256, turnover_status="available")],
        payloads=[payload],
    )

    class BadAdapter:
        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            return batch

    result = pipeline.collect(score_date, adapter=BadAdapter())
    assert result["status"] == "failed"
    with pipeline_env() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.id == result["run_id"]))
        raw = db.scalar(select(RawPayload).where(RawPayload.ingestion_run_id == result["run_id"]))
        assert run and run.status == "failed" and run.records == 0
        assert raw and raw.sha256 == payload.sha256


def test_collect_persists_captures_when_official_adapter_fails_mid_fetch(pipeline_env):
    payload = _fixture_payload()
    score_date = date(2026, 9, 2)

    class FailingAdapter:
        captured_payloads = [payload]

        def fetch(self, start: date, end: date) -> sources.OfficialBatch:
            raise sources.OfficialDataError("fixture endpoint unavailable")

    result = pipeline.collect(score_date, adapter=FailingAdapter())
    assert result["status"] == "failed"
    assert result["raw_payloads"] == 1
    with pipeline_env() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.id == result["run_id"]))
        raw = db.scalar(select(RawPayload).where(RawPayload.ingestion_run_id == result["run_id"]))
        assert run and run.status == "failed" and run.records == 0
        assert raw and raw.sha256 == payload.sha256


def test_analyze_uses_latest_official_collect_not_newer_backtest(pipeline_env):
    with pipeline_env() as db:
        db.add_all(
            [
                IngestionRun(
                    run_type="collect",
                    source="official",
                    run_date=date(2026, 9, 4),
                    status="success",
                    records=1,
                    data_as_of="2026-09-04",
                ),
                IngestionRun(
                    run_type="backtest",
                    source="technical_backtest",
                    run_date=date(2026, 9, 8),
                    status="success",
                    records=999,
                    data_as_of="2026-09-08",
                ),
            ]
        )
        db.commit()

    result = pipeline.analyze()

    assert result["status"] == "success"
    assert result["date"] == "2026-09-04"


def _future_business_days(start: date, count: int) -> list[date]:
    values: list[date] = []
    cursor = start + timedelta(days=1)
    while len(values) < count:
        if cursor.weekday() < 5:
            values.append(cursor)
        cursor += timedelta(days=1)
    return values


def test_hot_groups_require_three_members_and_keep_etfs_separate(pipeline_env):
    score_date = date(2026, 9, 4)
    dates = pipeline.business_days(score_date, 21)
    with pipeline_env() as db:
        benchmark = Instrument(market="TW", exchange="TWSE", symbol="TAIEX", name="TAIEX", instrument_type="index", status="active")
        stocks = [Instrument(market="TW", exchange="TWSE", symbol=f"S{i}", name=f"Stock {i}", instrument_type="stock", industry="Industry") for i in range(3)]
        etfs = [Instrument(market="TW", exchange="TWSE", symbol=f"00{i}E", name=f"ETF {i}", instrument_type="etf", etf_category="sector", industry="ETF") for i in range(3)]
        db.add_all([benchmark, *stocks, *etfs])
        db.flush()
        equity_group = ThemeGroup(id="equity-group", name="Equity group", group_type="official_industry", active=True)
        etf_group = ThemeGroup(id="etf-group", name="Sector ETF", group_type="etf", active=True)
        small_group = ThemeGroup(id="small-group", name="Too small", group_type="official_industry", active=True)
        db.add_all([equity_group, etf_group, small_group])
        db.flush()
        for instrument in stocks:
            db.add(GroupMembership(group_id=equity_group.id, instrument_id=instrument.id, valid_from=dates[0], source="fixture"))
        for instrument in etfs:
            db.add(GroupMembership(group_id=etf_group.id, instrument_id=instrument.id, valid_from=dates[0], source="fixture"))
        for instrument in stocks[:2]:
            db.add(GroupMembership(group_id=small_group.id, instrument_id=instrument.id, valid_from=dates[0], source="fixture"))
        for index, trading_date in enumerate(dates):
            benchmark_close = 100 + index * 0.25
            db.add(MarketBar(instrument_id=benchmark.id, trading_date=trading_date, open=benchmark_close, high=benchmark_close + 1, low=benchmark_close - 1, close=benchmark_close, adj_close=benchmark_close, volume=0, turnover=0, source="fixture"))
            for instrument in [*stocks, *etfs]:
                base = 100 if instrument.instrument_type == "stock" else 80
                close = base * (1 + (0.004 if instrument.instrument_type == "stock" else 0.003) * index)
                db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=close, high=close + 1, low=close - 1, close=close, adj_close=close, volume=1000, turnover=close * 1000, turnover_status="available", source="fixture"))
                db.add(ChipSnapshot(instrument_id=instrument.id, trading_date=trading_date, foreign_buy=100, trust_buy=20, dealer_buy=10, margin_balance=10000 + index, margin_change=1, source="fixture"))
        for instrument in [*stocks, *etfs]:
            db.add(TechnicalFeature(instrument_id=instrument.id, trading_date=score_date, features_json={"prior_20_volumes": [1000] * 20, "volume": 1300}, source="fixture"))
        db.flush()

        pipeline._calculate_group_scores(db, score_date)
        db.flush()
        rows = {row.group_id: row for row in db.scalars(select(GroupDailyScore)).all()}
        assert rows["equity-group"].eligible_members == 3
        assert rows["equity-group"].score is not None
        assert len(rows["equity-group"].details_json["candidate_symbols"]) == 3
        assert all(symbol.startswith("S") for symbol in rows["equity-group"].details_json["candidate_symbols"])
        assert rows["etf-group"].eligible_members == 3
        assert rows["etf-group"].score is not None
        assert all(symbol.endswith("E") for symbol in rows["etf-group"].details_json["candidate_symbols"])
        assert rows["small-group"].eligible_members == 2
        assert rows["small-group"].score is None
        assert rows["small-group"].details_json["candidate_symbols"] == []

        missing_chip = db.scalar(select(ChipSnapshot).where(ChipSnapshot.instrument_id == stocks[0].id, ChipSnapshot.trading_date == dates[-1]))
        assert missing_chip
        missing_chip.trust_buy = None
        db.flush()
        pipeline._calculate_group_scores(db, score_date)
        db.flush()
        incomplete = db.scalar(select(GroupDailyScore).where(GroupDailyScore.group_id == "equity-group", GroupDailyScore.trading_date == score_date))
        assert incomplete and incomplete.institutional_flow is None
        coverage = incomplete.details_json["institutional_flow_coverage"]
        assert coverage["available"] == 2 and coverage["eligible"] == 3 and coverage["complete"] is False
        assert incomplete.data_quality != "complete"


def test_official_groups_merge_exchanges_but_preserve_membership_provenance(pipeline_env):
    score_date = date(2026, 9, 4)
    with pipeline_env() as db:
        twse = Instrument(market="TW", exchange="TWSE", symbol="2330", name="TWSE Semi", instrument_type="stock", industry="24", status="active")
        tpex = Instrument(market="TW", exchange="TPEx", symbol="6488", name="TPEx Semi", instrument_type="stock", industry="24", status="active")
        twse_etf = Instrument(market="TW", exchange="TWSE", symbol="0050", name="TWSE ETF", instrument_type="etf", etf_category="broad_market", status="active")
        tpex_etf = Instrument(market="TW", exchange="TPEx", symbol="00679B", name="TPEx ETF", instrument_type="etf", etf_category="broad_market", status="active")
        db.add_all([twse, tpex, twse_etf, tpex_etf])
        db.flush()
        records = [
            sources.InstrumentRecord("2330", "TWSE Semi", exchange="TWSE", industry="24", payload_sha256="a"),
            sources.InstrumentRecord("6488", "TPEx Semi", exchange="TPEx", industry="24", payload_sha256="b"),
            sources.InstrumentRecord("0050", "TWSE ETF", exchange="TWSE", instrument_type="etf", etf_category="broad_market", payload_sha256="c"),
            sources.InstrumentRecord("00679B", "TPEx ETF", exchange="TPEx", instrument_type="etf", etf_category="broad_market", payload_sha256="d"),
        ]
        instrument_map = {(item.exchange, item.symbol): item for item in (twse, tpex, twse_etf, tpex_etf)}
        payloads = [
            sources.FetchedPayload(source, endpoint, {}, "2026-09-04", datetime(2026, 9, 4, 1), sources.RAW_DIR / "fixture.json", digest)
            for source, endpoint, digest in [("twse", sources.TWSE_LISTED_ENDPOINT, "a"), ("tpex", sources.TPEX_LISTED_ENDPOINT, "b"), ("twse", sources.TWSE_ETF_ENDPOINT, "c"), ("tpex", sources.TPEX_ETF_ENDPOINT, "d")]
        ]
        pipeline._ensure_official_groups(db, records, instrument_map, score_date, score_date, payloads=payloads, observed_now=datetime(2026, 9, 4, 2))
        industry_groups = db.scalars(select(ThemeGroup).where(ThemeGroup.group_type == "official_industry")).all()
        etf_groups = db.scalars(select(ThemeGroup).where(ThemeGroup.group_type == "etf")).all()
        assert len(industry_groups) == 1
        assert industry_groups[0].name == "Industry · Semiconductor"
        assert len(etf_groups) == 1
        assert etf_groups[0].name == "ETF · broad_market"
        industry_members = db.scalars(select(GroupMembership).where(GroupMembership.group_id == industry_groups[0].id)).all()
        etf_members = db.scalars(select(GroupMembership).where(GroupMembership.group_id == etf_groups[0].id)).all()
        assert {item.instrument_id for item in industry_members} == {twse.id, tpex.id}
        assert {item.source for item in industry_members} == {
            "TWSE/TPEx official OpenAPI; exchange=TWSE",
            "TWSE/TPEx official OpenAPI; exchange=TPEx",
        }
        assert {item.instrument_id for item in etf_members} == {twse_etf.id, tpex_etf.id}


def test_institutional_flow_ratios_use_canonical_hot_group_and_strategy_denominators(pipeline_env):
    score_date = date(2026, 9, 4)
    dates = pipeline.business_days(score_date, 20)
    with pipeline_env() as db:
        instrument = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="RATIO",
            name="Ratio fixture",
            instrument_type="stock",
            status="active",
        )
        db.add(instrument)
        db.flush()
        for trading_date in dates:
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=trading_date,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=1000,
                    turnover=100,
                    turnover_status="available",
                    source="fixture",
                )
            )
        for trading_date in dates[-5:]:
            db.add(
                ChipSnapshot(
                    instrument_id=instrument.id,
                    trading_date=trading_date,
                    foreign_buy=10,
                    trust_buy=10,
                    dealer_buy=10,
                    source="fixture",
                )
            )
        db.flush()

        hot_group_ratio = pipeline._hot_group_institutional_flow_ratio(
            db,
            instrument.id,
            score_date,
        )
        strategy_ratio = pipeline._strategy_institutional_flow_to_average_turnover_ratio(
            db,
            instrument.id,
            score_date,
        )

        # Five-day flow is 150; sum(turnover, 20d) is 2,000 while
        # average_daily_turnover_20d is 100, making the denominator error
        # observable as exactly a 20x difference.
        assert hot_group_ratio == pytest.approx(0.075)
        assert strategy_ratio == pytest.approx(1.5)
        assert strategy_ratio == pytest.approx(hot_group_ratio * 20)


def test_institutional_flow_ratios_fail_closed_for_one_missing_chip_component(pipeline_env):
    score_date = date(2026, 9, 4)
    dates = pipeline.business_days(score_date, 20)
    with pipeline_env() as db:
        instrument = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="NULLCHIP",
            name="Missing chip component fixture",
            instrument_type="stock",
            status="active",
        )
        db.add(instrument)
        db.flush()
        for trading_date in dates:
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=trading_date,
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    adj_close=100,
                    volume=1000,
                    turnover=100,
                    turnover_status="available",
                    source="fixture",
                )
            )
        for index, trading_date in enumerate(dates[-5:]):
            db.add(
                ChipSnapshot(
                    instrument_id=instrument.id,
                    trading_date=trading_date,
                    foreign_buy=10,
                    trust_buy=None if index == 2 else 10,
                    dealer_buy=10,
                    source="fixture",
                )
            )
        db.add(
            TechnicalFeature(
                instrument_id=instrument.id,
                trading_date=score_date,
                features_json={
                    "bar_count_60d": 60,
                    "prior_20_highs": [99] * 20,
                    "prior_20_volumes": [1000] * 20,
                    "volume": 2000,
                    "ma20": 100,
                    "ma60": 90,
                    "atr14": 2,
                },
                source="fixture",
            )
        )
        db.flush()

        assert pipeline._hot_group_institutional_flow_ratio(db, instrument.id, score_date) is None
        assert pipeline._strategy_institutional_flow_to_average_turnover_ratio(db, instrument.id, score_date) is None

        strategies = pipeline._ensure_strategies(db)
        pipeline._upsert_signal(
            db,
            instrument=instrument,
            signal_date=score_date,
            strategies=strategies,
        )
        db.flush()
        signal = db.scalar(select(Signal).where(Signal.instrument_id == instrument.id))
        assert signal and signal.status == "data_incomplete"
        assert signal.rule_evidence_json["inputs"]["institutional_flow_to_turnover_ratio_5d"] is None
        assert "institutional_flow_to_turnover_ratio_5d_missing_or_non_finite" in signal.rationale


def test_signal_gate_uses_domain_inputs_and_missing_etf_category_fails_closed(pipeline_env):
    score_date = date(2026, 9, 4)
    with pipeline_env() as db:
        stock = Instrument(market="TW", exchange="TWSE", symbol="AAA", name="Alpha", instrument_type="stock", status="active")
        etf = Instrument(market="TW", exchange="TWSE", symbol="00BAD", name="Missing category ETF", instrument_type="etf", etf_category=None, status="active")
        db.add_all([stock, etf])
        db.flush()
        for instrument in (stock, etf):
            db.add(MarketBar(instrument_id=instrument.id, trading_date=score_date, open=100, high=101, low=99, close=100, adj_close=100, volume=2000, turnover=200000, source="fixture"))
            db.add(TechnicalFeature(instrument_id=instrument.id, trading_date=score_date, features_json={"bar_count_60d": 60, "prior_20_highs": [99] * 20, "prior_20_volumes": [1000] * 20, "volume": 2000, "ma20": 100, "ma60": 90, "atr14": 2}, source="fixture"))
        db.flush()
        strategies = pipeline._ensure_strategies(db)
        pipeline._upsert_signal(db, instrument=stock, signal_date=score_date, strategies=strategies)
        pipeline._upsert_signal(db, instrument=etf, signal_date=score_date, strategies=strategies)
        db.flush()
        stock_signal = db.scalar(select(Signal).where(Signal.instrument_id == stock.id))
        etf_signal = db.scalar(select(Signal).where(Signal.instrument_id == etf.id))
        assert stock_signal and stock_signal.status == "data_incomplete"
        assert stock_signal.invalid_price is None and stock_signal.target_1 is None
        assert "group_excess_return_20d" in stock_signal.rule_evidence_json["inputs"]
        assert etf_signal and etf_signal.status == "data_incomplete"
        assert "unsupported_or_missing_etf_category" in (etf_signal.rationale or "")


def test_strategy_group_return_does_not_require_complete_hot_group_score(pipeline_env, monkeypatch):
    score_date = date(2026, 9, 4)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="PARTIAL", name="Partial group", instrument_type="stock", status="active")
        group = ThemeGroup(
            id="partial-group",
            name="Industry: Partial",
            group_type="official_industry",
            active=True,
            display_name_zh="部分族群",
            name_status="official",
        )
        db.add_all([instrument, group])
        db.flush()
        db.add(GroupMembership(group_id=group.id, instrument_id=instrument.id, valid_from=score_date, source="fixture"))
        db.add(
            GroupDailyScore(
                group_id=group.id,
                trading_date=score_date,
                score=None,
                rank=None,
                data_quality="partial",
                eligible_members=3,
                relative_return_20d=-0.02,
                details_json={
                    "benchmark": "TAIEX",
                    "member_returns": [{"symbol": instrument.symbol, "excess_return_20d": -0.02}],
                },
            )
        )
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=score_date,
                open=100,
                high=101,
                low=99,
                close=100,
                adj_close=100,
                volume=2000,
                turnover=200000,
                source="fixture",
            )
        )
        db.add(
            TechnicalFeature(
                instrument_id=instrument.id,
                trading_date=score_date,
                features_json={
                    "bar_count_60d": 60,
                    "prior_20_highs": [99] * 20,
                    "prior_20_volumes": [1000] * 20,
                    "volume": 2000,
                    "ma20": 100,
                    "ma60": 90,
                    "atr14": 2,
                },
                source="fixture",
            )
        )
        db.flush()
        monkeypatch.setattr(pipeline, "_strategy_institutional_flow_to_average_turnover_ratio", lambda *_args, **_kwargs: 0.0)
        monkeypatch.setattr(pipeline, "_margin_change_ratio", lambda *_args, **_kwargs: 0.0)

        strategies = pipeline._ensure_strategies(db)
        assert pipeline._upsert_signal(db, instrument=instrument, signal_date=score_date, strategies=strategies)
        db.flush()
        signals = db.scalars(select(Signal).where(Signal.instrument_id == instrument.id).order_by(Signal.signal_key)).all()

        assert len(signals) == 2
        assert {item.status for item in signals} == {"observation"}
        assert {item.data_quality for item in signals} == {"complete"}
        assert all(item.rule_evidence_json["inputs"]["group_excess_return_20d"] == pytest.approx(-0.02) for item in signals)
        assert all("group_excess_return_20d_missing_or_non_finite" not in (item.rationale or "") for item in signals)


def test_signal_results_are_distinct_per_strategy_and_rejected_rules_are_observation(pipeline_env, monkeypatch):
    score_date = date(2026, 9, 4)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="OBS", name="Observation", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        db.add(MarketBar(instrument_id=instrument.id, trading_date=score_date, open=100, high=101, low=99, close=100, adj_close=100, volume=1000, turnover=100000, source="fixture"))
        db.add(TechnicalFeature(instrument_id=instrument.id, trading_date=score_date, features_json={"bar_count_60d": 60, "prior_20_highs": [110] * 20, "prior_20_volumes": [1000] * 20, "volume": 1000, "ma20": 100, "ma60": 100, "atr14": 2}, source="fixture"))
        db.flush()
        monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args, **_kwargs: GroupDailyScore(group_id="fixture-group", trading_date=score_date, score=50, eligible_members=3, details_json={"member_return_identity_version": "instrument-id-v1", "member_returns": [{"instrument_id": instrument.id, "exchange": instrument.exchange, "symbol": "OBS", "excess_return_20d": 0.1}]}))
        rejected = SimpleNamespace(passed=False, state="rejected", reasons=("rule_not_met",))
        monkeypatch.setattr(pipeline, "evaluate_breakout_v1", lambda **_kwargs: rejected)
        monkeypatch.setattr(pipeline, "evaluate_pullback_v1", lambda **_kwargs: rejected)
        strategies = pipeline._ensure_strategies(db)
        assert pipeline._upsert_signal(db, instrument=instrument, signal_date=score_date, strategies=strategies)
        db.flush()
        signals = db.scalars(select(Signal).where(Signal.instrument_id == instrument.id).order_by(Signal.signal_key)).all()
        assert len(signals) == 2
        assert {item.strategy_version_id for item in signals} == {strategies["breakout_v1"].id, strategies["pullback_v1"].id}
        assert {item.entry_type for item in signals} == {"breakout", "pullback"}
        assert all(item.status == "observation" for item in signals)
        assert all(item.confidence is None for item in signals)
        assert all(item.rule_evidence_json["confidence_semantics"]["version"] == SIGNAL_CONFIDENCE_SEMANTICS_VERSION for item in signals)
        assert all("rule_not_met" in (item.rationale or "") for item in signals)
        assert pipeline._upsert_signal(db, instrument=instrument, signal_date=score_date, strategies=strategies)
        db.flush()
        assert db.scalar(select(func.count(Signal.id)).where(Signal.instrument_id == instrument.id)) == 2


def test_conditional_signal_has_no_uncalibrated_probability_and_legacy_value_survives_same_key_rerun(pipeline_env, monkeypatch):
    score_date = date(2026, 9, 4)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="COND", name="Conditional", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        db.add(MarketBar(instrument_id=instrument.id, trading_date=score_date, open=100, high=101, low=99, close=100, adj_close=100, volume=2000, turnover=200000, source="fixture"))
        db.add(TechnicalFeature(instrument_id=instrument.id, trading_date=score_date, features_json={"bar_count_60d": 60, "prior_20_highs": [99] * 20, "prior_20_volumes": [1000] * 20, "volume": 2000, "ma20": 100, "ma60": 90, "atr14": 2}, source="fixture"))
        db.flush()
        monkeypatch.setattr(pipeline, "_best_group_for_signal", lambda *_args, **_kwargs: GroupDailyScore(group_id="fixture-group", trading_date=score_date, score=50, eligible_members=3, details_json={"member_return_identity_version": "instrument-id-v1", "member_returns": [{"instrument_id": instrument.id, "exchange": instrument.exchange, "symbol": "COND", "excess_return_20d": 0.1}]}))
        monkeypatch.setattr(pipeline, "_strategy_institutional_flow_to_average_turnover_ratio", lambda *_args, **_kwargs: 0.0)
        monkeypatch.setattr(pipeline, "_margin_change_ratio", lambda *_args, **_kwargs: 0.0)

        strategies = pipeline._ensure_strategies(db)
        assert pipeline._upsert_signal(db, instrument=instrument, signal_date=score_date, strategies=strategies)
        db.flush()
        breakout = db.scalar(select(Signal).where(Signal.instrument_id == instrument.id, Signal.entry_type == "breakout"))
        assert breakout and breakout.status == "conditional"
        assert breakout.confidence is None
        assert breakout.rule_evidence_json["confidence_semantics"] == {
            "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
            "kind": "not_calibrated",
            "is_calibrated": False,
            "is_probability": False,
            "display_label_zh": "未校準；非預測勝率",
        }

        # Simulate an existing v1 row before the semantic marker existed.
        breakout.confidence = 0.75
        breakout.rule_evidence_json = {
            **breakout.rule_evidence_json,
            "legacy_signal_confidence_version": LEGACY_SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
        }
        breakout.rule_evidence_json.pop("confidence_semantics", None)
        db.commit()

        assert pipeline._upsert_signal(db, instrument=instrument, signal_date=score_date, strategies=strategies)
        db.flush()
        rerun = db.scalar(select(Signal).where(Signal.id == breakout.id))
        assert rerun and rerun.confidence == pytest.approx(0.75)
        assert rerun.rule_evidence_json["legacy_signal_confidence_version"] == LEGACY_SIGNAL_CONFIDENCE_SEMANTICS_VERSION
        assert rerun.rule_evidence_json["confidence_semantics"]["version"] == LEGACY_SIGNAL_CONFIDENCE_SEMANTICS_VERSION
        assert rerun.rule_evidence_json["confidence_semantics"]["is_probability"] is False
        assert rerun.rule_evidence_json["confidence_semantics"]["is_calibrated"] is False


def test_legacy_confidence_detection_requires_known_strategy_version_and_value():
    known = signal_confidence_semantics(
        0.75,
        {"strategy": "breakout_v1", "strategy_version": "1.0.0"},
    )
    assert known["kind"] == "legacy_fixed_value"

    for value in (0.74, 0.80):
        semantics = signal_confidence_semantics(
            value,
            {"strategy": "breakout_v1", "strategy_version": "1.0.0"},
        )
        assert semantics["kind"] == "unknown_numeric"
        assert semantics["is_probability"] is False
        assert semantics["is_calibrated"] is False

    unknown_strategy = signal_confidence_semantics(
        0.75,
        {"strategy": "other_strategy", "strategy_version": "1.0.0"},
    )
    assert unknown_strategy["kind"] == "unknown_numeric"
    forged_marker = signal_confidence_semantics(
        0.75,
        {
            "strategy": "breakout_v1",
            "strategy_version": "1.0.0",
            "confidence_semantics": {
                "version": "signal-confidence/v1-fixed",
                "kind": "prediction",
                "is_calibrated": True,
                "is_probability": True,
                "display_label_zh": "75% 勝率",
            },
        },
    )
    assert forged_marker["kind"] == "legacy_fixed_value"
    assert forged_marker["is_probability"] is False
    assert forged_marker["is_calibrated"] is False
    assert "75%" not in forged_marker["display_label_zh"]


def test_tracking_is_t_plus_one_idempotent_5_20_day_and_marks_ambiguous_path(pipeline_env):
    signal_date = date(2026, 1, 2)
    future_dates = _future_business_days(signal_date, 20)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="TRACK", name="Tracking", instrument_type="stock", status="active")
        ambiguous_instrument = Instrument(market="TW", exchange="TWSE", symbol="AMBIG", name="Ambiguous", instrument_type="stock", status="active")
        db.add_all([instrument, ambiguous_instrument])
        db.flush()
        signal = Signal(signal_key="fixture-track", signal_date=signal_date, instrument_id=instrument.id, status="conditional", entry_type="breakout", breakout_price=100, invalid_price=90, target_1=110, target_2=120, data_quality="complete")
        ambiguous = Signal(signal_key="fixture-ambiguous", signal_date=signal_date, instrument_id=ambiguous_instrument.id, status="conditional", entry_type="breakout", breakout_price=100, invalid_price=90, target_1=110, target_2=120, data_quality="complete")
        db.add_all([signal, ambiguous])
        db.flush()
        for index, trading_date in enumerate(future_dates):
            if index == 0:
                open_price = 101
                high_price, low_price = 102, 100
                close_price = 101.5
            else:
                # A 2-for-1 split is reflected in the official raw OHLC: the
                # post-action market trades around 50, not around 100.
                open_price = 50.5 + index * 0.05
                high_price, low_price = open_price + 0.5, open_price - 0.5
                close_price = open_price + 0.25
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=open_price, high=high_price, low=low_price, close=close_price, adj_close=close_price, volume=1000, turnover=100000, source="fixture"))
            if index == 0:
                high, low = 112, 88
            else:
                high, low = 104 + index * 0.1, 99 + index * 0.1
            db.add(MarketBar(instrument_id=ambiguous_instrument.id, trading_date=trading_date, open=101, high=high, low=low, close=102, adj_close=102, volume=1000, turnover=100000, source="fixture"))
        db.add(CorporateAction(instrument_id=instrument.id, action_date=future_dates[1], action_type="split", details_json={"price_factor": 0.5}, source="fixture"))
        db.flush()

        evaluation_count, settlement_count = pipeline._evaluate_signal_tracking(db, signal)
        db.flush()
        assert evaluation_count == 20 and settlement_count == 2
        assert signal.execution_date == future_dates[0]
        assert signal.execution_price == pytest.approx(101 * 1.0005, rel=1e-8)
        evaluations = db.scalars(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id).order_by(SignalEvaluation.session_no)).all()
        settlements = db.scalars(select(SignalSettlement).where(SignalSettlement.signal_id == signal.id).order_by(SignalSettlement.horizon)).all()
        assert len(evaluations) == 20
        assert evaluations[0].execution_date == future_dates[0]
        assert any(item.corporate_action_applied for item in evaluations)
        split_evaluation = evaluations[1]
        assert split_evaluation.corporate_action_applied is True
        assert split_evaluation.invalid_price_trigger is False
        assert split_evaluation.adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(0.5)
        assert split_evaluation.adjusted_ohlc_json["close"] > 90
        assert [item.horizon for item in settlements] == [5, 20]
        assert all(item.comparable is True for item in settlements)
        assert settlements[0].return_or_risk is not None
        # A split changes the price basis, not the economic return.  The
        # settlement must not report a spurious ~50% loss from comparing a
        # post-split close with the pre-split fill.
        assert settlements[1].return_or_risk > -0.10

        ambiguous_count, ambiguous_settlements = pipeline._evaluate_signal_tracking(db, ambiguous)
        db.flush()
        first_ambiguous = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == ambiguous.id, SignalEvaluation.session_no == 1))
        assert ambiguous_count == 20 and ambiguous_settlements == 2
        assert ambiguous.status == "incomparable"
        assert first_ambiguous and first_ambiguous.status == "ambiguous" and first_ambiguous.comparable is False


def test_tracking_does_not_expire_before_twenty_sessions(pipeline_env):
    signal_date = date(2026, 1, 2)
    future_dates = _future_business_days(signal_date, 20)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="WAIT", name="Wait", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        signal = Signal(signal_key="fixture-wait", signal_date=signal_date, instrument_id=instrument.id, status="conditional", entry_type="breakout", breakout_price=200, invalid_price=190, target_1=220, target_2=240)
        db.add(signal)
        db.flush()
        for trading_date in future_dates[:5]:
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=100, high=105, low=95, close=100, adj_close=100, volume=1000, turnover=100000, source="fixture"))
        db.flush()
        pipeline._evaluate_signal_tracking(db, signal)
        db.flush()
        assert signal.status == "conditional"
        assert db.scalar(select(SignalSettlement).where(SignalSettlement.signal_id == signal.id, SignalSettlement.horizon == 20)).comparable is False

        for trading_date in future_dates[5:]:
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=100, high=105, low=95, close=100, adj_close=100, volume=1000, turnover=100000, source="fixture"))
        db.flush()
        pipeline._evaluate_signal_tracking(db, signal)
        assert signal.status == "expired"


def test_derived_features_use_score_date_corporate_action_basis_without_future_leak(pipeline_env):
    score_dates = pipeline.business_days(date(2026, 2, 6), 23)
    split_date = score_dates[20]
    post_split_date = score_dates[21]
    future_action_date = score_dates[22]
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="BASIS", name="Basis", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        for trading_date in score_dates:
            if trading_date < split_date:
                close = 100.0
                high, low = 101.0, 99.0
            elif trading_date == split_date:
                close = 50.0
                high, low = 50.5, 49.5
            elif trading_date == post_split_date:
                close = 51.0
                high, low = 51.5, 50.5
            else:
                close = 25.0
                high, low = 25.5, 24.5
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=close, high=high, low=low, close=close, adj_close=close, volume=1000, turnover=100000, source="fixture"))
        db.add(CorporateAction(instrument_id=instrument.id, action_date=split_date, action_type="split", details_json={"price_factor": 0.5}, source="fixture"))
        db.add(CorporateAction(instrument_id=instrument.id, action_date=future_action_date, action_type="split", details_json={"price_factor": 0.5}, source="fixture"))
        db.flush()

        pipeline._calculate_features(db, instrument)
        db.flush()
        pre_split = db.scalar(select(TechnicalFeature).where(TechnicalFeature.instrument_id == instrument.id, TechnicalFeature.trading_date == score_dates[19]))
        split = db.scalar(select(TechnicalFeature).where(TechnicalFeature.instrument_id == instrument.id, TechnicalFeature.trading_date == split_date))
        post_split = db.scalar(select(TechnicalFeature).where(TechnicalFeature.instrument_id == instrument.id, TechnicalFeature.trading_date == post_split_date))
        assert pre_split and split and post_split
        assert pre_split.features_json["ma20"] == pytest.approx(100.0)
        assert split.features_json["return_1d"] == pytest.approx(0.0)
        assert post_split.features_json["return_1d"] == pytest.approx(0.02)
        assert max(split.features_json["prior_20_highs"]) == pytest.approx(50.5)
        assert max(post_split.features_json["prior_20_highs"]) == pytest.approx(50.5)
        assert pipeline._returns_by_window(db, instrument.id, split_date)[1] == pytest.approx(0.0)
        assert pipeline._returns_by_window(db, instrument.id, post_split_date)[1] == pytest.approx(0.02)


def test_official_suspension_gap_makes_missing_bar_horizons_incomparable(pipeline_env):
    signal_date = date(2026, 1, 2)
    future_dates = _future_business_days(signal_date, 21)
    suspended_date = future_dates[1]
    resumed_date = future_dates[2]
    observed_dates = [future_dates[0], *future_dates[2:]]
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TPEx", symbol="SUSP", name="Suspended", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        signal = Signal(signal_key="fixture-suspension", signal_date=signal_date, instrument_id=instrument.id, status="conditional", entry_type="breakout", breakout_price=200, invalid_price=190, target_1=220, target_2=240, data_quality="complete")
        db.add(signal)
        db.add(Event(instrument_id=instrument.id, event_date=suspended_date, event_type="suspension", title="TPEx suspension interval", details_json={"resumed_date": resumed_date.isoformat(), "interval_end": resumed_date.isoformat()}, source="tpex_suspension_history"))
        db.flush()
        for trading_date in observed_dates:
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=100, high=105, low=95, close=100, adj_close=100, volume=1000, turnover=100000, source="fixture"))
        db.flush()

        evaluations, settlements = pipeline._evaluate_signal_tracking(db, signal)
        db.flush()
        assert evaluations == 20 and settlements == 2
        assert db.scalar(select(MarketBar).where(MarketBar.instrument_id == instrument.id, MarketBar.trading_date == suspended_date)) is None
        gap_evaluation = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id, SignalEvaluation.session_no == 2))
        assert gap_evaluation and gap_evaluation.suspended is True and gap_evaluation.comparable is False
        rows = db.scalars(select(SignalSettlement).where(SignalSettlement.signal_id == signal.id).order_by(SignalSettlement.horizon)).all()
        assert [row.horizon for row in rows] == [5, 20]
        assert all(row.comparable is False for row in rows)
        assert all("suspended" in (row.incomparable_reason or "") for row in rows)


def test_tracking_cash_dividend_normalizes_raw_ex_date_basis(pipeline_env):
    signal_date = date(2026, 1, 2)
    future_dates = _future_business_days(signal_date, 20)
    ex_date = future_dates[1]
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="DIV", name="Dividend", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        signal = Signal(signal_key="fixture-dividend", signal_date=signal_date, instrument_id=instrument.id, status="conditional", entry_type="breakout", breakout_price=100, invalid_price=90, target_1=120, target_2=130, data_quality="complete")
        db.add(signal)
        db.flush()
        for trading_date in future_dates:
            close = 100 if trading_date < ex_date else 95
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=close, high=close + 1, low=close - 1, close=close, adj_close=close, volume=1000, turnover=100000, source="fixture"))
        db.add(CorporateAction(instrument_id=instrument.id, action_date=ex_date, action_type="ex_dividend", cash_dividend=5, source="fixture"))
        db.flush()

        pipeline._evaluate_signal_tracking(db, signal)
        db.flush()
        ex_evaluation = db.scalar(select(SignalEvaluation).where(SignalEvaluation.signal_id == signal.id, SignalEvaluation.session_date == ex_date))
        settlement = db.scalar(select(SignalSettlement).where(SignalSettlement.signal_id == signal.id, SignalSettlement.horizon == 20))
        assert ex_evaluation and ex_evaluation.corporate_action_applied is True
        assert ex_evaluation.adjusted_ohlc_json["factor_signal_to_raw"] == pytest.approx(0.95)
        assert settlement and settlement.comparable is True and settlement.return_or_risk > -0.02


def test_backtest_failed_first_attempt_is_persisted_and_retry_is_idempotent(pipeline_env, monkeypatch):
    score_date = date(2026, 9, 4)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="RETRY", name="Retry", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        db.add(MarketBar(instrument_id=instrument.id, trading_date=score_date, open=100, high=101, low=99, close=100, adj_close=100, volume=1000, turnover=100000, source="fixture"))
        db.flush()
        db.commit()

    def fail_features(*_args, **_kwargs):
        raise RuntimeError("fixture mid-run failure")

    monkeypatch.setattr(pipeline, "_calculate_features", fail_features)
    failed = pipeline.backtest(score_date, score_date)
    assert failed["run"]["status"] == "failed"
    with pipeline_env() as db:
        failed_run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == f"technical-backtest:v1:{score_date.isoformat()}:{score_date.isoformat()}"))
        assert failed_run and failed_run.status == "failed"
        assert "fixture mid-run failure" in (failed_run.error or "")
        assert failed_run.metadata_json["data_cutoff"].endswith("Asia/Taipei")
        run_id = failed_run.id

    monkeypatch.setattr(pipeline, "_calculate_features", lambda *_args, **_kwargs: None)
    recovered = pipeline.backtest(score_date, score_date)
    assert recovered["run"]["status"] == "success"
    with pipeline_env() as db:
        runs = db.scalars(select(IngestionRun).where(IngestionRun.request_key == f"technical-backtest:v1:{score_date.isoformat()}:{score_date.isoformat()}")).all()
        assert len(runs) == 1 and runs[0].id == run_id and runs[0].status == "success"


def test_backtest_cutoff_and_summary_exclude_future_bars_and_non_actionable_rows(pipeline_env, monkeypatch):
    start_date = date(2026, 1, 2)
    end_date = date(2026, 1, 5)
    future_date = date(2026, 1, 6)
    with pipeline_env() as db:
        instrument = Instrument(market="TW", exchange="TWSE", symbol="BT", name="Backtest", instrument_type="stock", status="active")
        db.add(instrument)
        db.flush()
        for trading_date, high in ((start_date, 101), (end_date, 101), (future_date, 130)):
            db.add(MarketBar(instrument_id=instrument.id, trading_date=trading_date, open=100, high=high, low=99, close=100, adj_close=100, volume=1000, turnover=100000, source="fixture"))
        db.flush()
        db.commit()

    monkeypatch.setattr(pipeline, "_calculate_features", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_calculate_group_scores", lambda *_args, **_kwargs: None)

    def fake_generate(db, score_date, strategies, *, namespace="analysis", data_cutoff=None):
        assert data_cutoff == end_date
        if score_date != start_date:
            return 0
        strategy = strategies["breakout_v1"]
        actionable = Signal(
            signal_key=f"{namespace}-TWSE-BT-{start_date.isoformat()}-breakout_v1-1.0.0",
            signal_date=start_date,
            instrument_id=db.scalar(select(Instrument.id).where(Instrument.symbol == "BT")),
            strategy_version_id=strategy.id,
            status="conditional",
            entry_type="breakout",
            breakout_price=100,
            invalid_price=90,
            target_1=120,
            target_2=130,
            data_quality="complete",
            rule_evidence_json={"strategy": "breakout_v1", "actionable": True},
        )
        observation = Signal(
            signal_key=f"{namespace}-TWSE-BT-{start_date.isoformat()}-pullback_v1-1.0.0",
            signal_date=start_date,
            instrument_id=actionable.instrument_id,
            strategy_version_id=strategy.id,
            status="observation",
            entry_type="pullback",
            data_quality="incomplete",
            rule_evidence_json={"strategy": "pullback_v1", "actionable": False},
        )
        db.add_all([actionable, observation])
        db.flush()
        db.add(SignalSettlement(signal_id=observation.id, horizon=5, settlement_date=end_date, final_status="target_1_hit", return_or_risk=0.2, comparable=True, data_quality="complete"))
        db.flush()
        return 2

    monkeypatch.setattr(pipeline, "_generate_signals", fake_generate)
    result = pipeline.backtest(start_date, end_date)
    assert result["run"]["status"] == "success"
    with pipeline_env() as db:
        actionable = db.scalar(select(Signal).where(Signal.signal_key.like("backtest-%breakout_v1%")))
        observation = db.scalar(select(Signal).where(Signal.signal_key.like("backtest-%pullback_v1%")))
        assert actionable and observation
        evaluations = db.scalars(select(SignalEvaluation).where(SignalEvaluation.signal_id == actionable.id)).all()
        assert evaluations and all(item.session_date <= end_date for item in evaluations)
        assert not any(item.session_date == future_date for item in evaluations)
        settlements = db.scalars(select(SignalSettlement).where(SignalSettlement.signal_id == actionable.id)).all()
        assert {item.horizon for item in settlements} == {5, 20}
        assert all(item.comparable is False for item in settlements)
        summary = pipeline.summarize_backtest(db)
        assert summary["run"]["id"] == result["run"]["id"]
        assert summary["groups"]
        assert {item["sample"] for item in summary["groups"]} == {1}
        assert all(item["assessment"] == "insufficient_sample" for item in summary["groups"])
