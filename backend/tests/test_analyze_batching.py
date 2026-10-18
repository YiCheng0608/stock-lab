import json
import random
import sqlite3
from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import moving_average
from app.migrations import upgrade_database
from app.models import (
    CorporateAction,
    IngestionRun,
    Instrument,
    MarketBar,
    TechnicalFeature,
)


@pytest.fixture
def analyze_env(tmp_path, monkeypatch):
    db_path = tmp_path / "analyze.db"
    engine = create_engine(f"sqlite:///{db_path}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory, db_path
    engine.dispose()


def _reference_features(bars: list[MarketBar], factors: list[float]) -> list[dict]:
    """The pre-#184 per-bar rebuild of the whole normalized prefix (O(n^2))."""

    rows = []
    for index, bar in enumerate(bars):
        score_factor = factors[index] if factors else 1.0
        normalized = [
            {
                "high": item.high * score_factor / (factors[position] or 1.0),
                "low": item.low * score_factor / (factors[position] or 1.0),
                "close": item.close * score_factor / (factors[position] or 1.0),
            }
            for position, item in enumerate(bars[: index + 1])
        ]
        closes = [item["close"] for item in normalized]
        highs = [item["high"] for item in normalized]
        lows = [item["low"] for item in normalized]
        volumes = [item.volume for item in bars[: index + 1]]
        prior_volumes = volumes[:index]
        prior_highs = highs[:index]
        prior_lows = lows[:index]
        prior_20_volumes = prior_volumes[-20:] if len(prior_volumes) >= 20 else []
        ma20 = moving_average(closes, 20)
        ma60 = moving_average(closes, 60)
        atr_values = [item["high"] - item["low"] for item in normalized[-14:]]
        ma5 = moving_average(closes, 5)
        rows.append(
            {
                "return_1d": round(closes[index] / closes[index - 1] - 1, 8)
                if index >= 1 and closes[index - 1]
                else None,
                "return_5d": round(closes[index] / closes[index - 5] - 1, 8)
                if index >= 5 and closes[index - 5]
                else None,
                "return_20d": round(closes[index] / closes[index - 20] - 1, 8)
                if index >= 20 and closes[index - 20]
                else None,
                "ma5": round(ma5, 6) if ma5 is not None else None,
                "ma20": round(ma20, 6) if ma20 is not None else None,
                "ma60": round(ma60, 6) if ma60 is not None else None,
                "high_20d": round(max(highs[-20:]), 6) if highs else None,
                "low_20d": round(min(lows[-20:]), 6) if lows else None,
                "prior_high_20d": round(max(prior_highs[-20:]), 6)
                if len(prior_highs) >= 20
                else None,
                "prior_low_20d": round(min(prior_lows[-20:]), 6)
                if len(prior_lows) >= 20
                else None,
                "atr14": round(sum(atr_values) / len(atr_values), 6)
                if atr_values
                else None,
                "volume": int(bar.volume),
                "volume_ratio_20d": (
                    round(
                        bar.volume / (sum(prior_20_volumes) / len(prior_20_volumes)), 6
                    )
                    if prior_20_volumes and sum(prior_20_volumes) > 0
                    else None
                ),
                "bar_count": index + 1,
                "bar_count_60d": index + 1,
                "source": bar.source,
                "price_basis": "score_date_raw_basis",
                "corporate_action_factor_signal_to_score_raw": score_factor,
                "corporate_actions_applied_through": bar.trading_date.isoformat(),
            }
        )
    return rows


def _add_instrument(db, symbol: str, dates: list[date], seed: int) -> Instrument:
    rng = random.Random(seed)
    instrument = Instrument(
        market="TW",
        exchange="TWSE",
        symbol=symbol,
        name=symbol,
        instrument_type="stock",
        status="active",
    )
    db.add(instrument)
    db.flush()
    close = 87.3
    for position, trading_date in enumerate(dates):
        close = round(max(1.0, close * (1 + rng.uniform(-0.04, 0.04))), 2)
        high = round(close * (1 + rng.uniform(0, 0.03)), 2)
        low = round(close * (1 - rng.uniform(0, 0.03)), 2)
        volume = 0 if position in (3, 30) else rng.randint(1, 50_000) * 1000
        db.add(
            MarketBar(
                instrument_id=instrument.id,
                trading_date=trading_date,
                open=close,
                high=high,
                low=low,
                close=close,
                adj_close=close,
                volume=volume,
                turnover=volume * close,
                source="fixture",
            )
        )
    return instrument


def test_windowed_features_equal_full_prefix_rebuild_across_corporate_actions(
    analyze_env,
):
    factory, _db_path = analyze_env
    dates = pipeline.business_days(date(2026, 9, 30), 140)
    with factory() as db:
        instrument = _add_instrument(db, "WIN", dates, seed=184)
        db.add_all(
            [
                CorporateAction(
                    instrument_id=instrument.id,
                    action_date=dates[45],
                    action_type="split",
                    details_json={"price_factor": 0.5},
                    source="fixture",
                ),
                CorporateAction(
                    instrument_id=instrument.id,
                    action_date=dates[70],
                    action_type="ex_dividend",
                    cash_dividend=1.7,
                    source="fixture",
                ),
                CorporateAction(
                    instrument_id=instrument.id,
                    action_date=dates[100],
                    action_type="ex_dividend",
                    cash_dividend=0.9,
                    stock_dividend_ratio=0.1,
                    reference_price=40.0,
                    source="fixture",
                ),
            ]
        )
        db.flush()
        bars = db.scalars(
            select(MarketBar)
            .where(MarketBar.instrument_id == instrument.id)
            .order_by(MarketBar.trading_date)
        ).all()
        expected = _reference_features(
            bars, pipeline._action_factor_by_bar(db, instrument.id, bars)
        )
        assert (
            len(
                {row["corporate_action_factor_signal_to_score_raw"] for row in expected}
            )
            == 4
        )

        pipeline._calculate_features(db, instrument)
        db.flush()
        stored = db.scalars(
            select(TechnicalFeature)
            .where(TechnicalFeature.instrument_id == instrument.id)
            .order_by(TechnicalFeature.trading_date)
        ).all()

        assert [feature.trading_date for feature in stored] == dates
        assert [
            json.dumps(feature.features_json, sort_keys=True) for feature in stored
        ] == [json.dumps(row, sort_keys=True) for row in expected]

        # A rerun over unchanged bars marks no row dirty, so the session does
        # not hold the instrument's whole history until the next flush.
        pipeline._calculate_features(db, instrument)
        assert not db.dirty and not db.new


def _seed_market(factory, symbols: int) -> date:
    dates = pipeline.business_days(date(2026, 9, 30), 30)
    with factory() as db:
        for number in range(symbols):
            _add_instrument(db, f"B{number}", dates, seed=number)
        db.add(
            IngestionRun(
                run_type="collect",
                source="official",
                run_date=dates[-1],
                status="success",
                records=symbols,
                data_as_of=dates[-1].isoformat(),
            )
        )
        db.commit()
    return dates[-1]


def _write_lock_free(db_path) -> bool:
    probe = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.execute("ROLLBACK")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        probe.close()


def test_analyze_commits_feature_batches_and_holds_no_write_lock_while_computing(
    analyze_env, monkeypatch
):
    factory, db_path = analyze_env
    score_date = _seed_market(factory, 5)
    monkeypatch.setattr(pipeline, "ANALYZE_COMMIT_BATCH", 2)
    observed: list[tuple[str, int, bool]] = []

    def committed_features() -> int:
        probe = sqlite3.connect(db_path)
        try:
            return probe.execute("select count(*) from technical_features").fetchone()[
                0
            ]
        finally:
            probe.close()

    def spy(name):
        original = getattr(pipeline, name)

        def wrapper(*args, **kwargs):
            observed.append((name, committed_features(), _write_lock_free(db_path)))
            return original(*args, **kwargs)

        monkeypatch.setattr(pipeline, name, wrapper)

    for name in ("_calculate_features", "_calculate_group_scores", "_generate_signals"):
        spy(name)

    result = pipeline.analyze()

    assert result["status"] == "success" and result["date"] == score_date.isoformat()
    # Features of every finished batch of two are committed before the next
    # instrument starts, and no phase starts while a write lock is held.
    assert observed == [
        ("_calculate_features", 0, True),
        ("_calculate_features", 0, True),
        ("_calculate_features", 60, True),
        ("_calculate_features", 60, True),
        ("_calculate_features", 120, True),
        ("_calculate_group_scores", 150, True),
        ("_generate_signals", 150, True),
    ]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(TechnicalFeature)) == 150
