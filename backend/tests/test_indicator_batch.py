"""Indicator batch and bars API on an in-memory SQLite database."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import indicators as ind
from app.api import get_db, router
from app.db import Base, enable_sqlite_foreign_keys
from app.indicators import IndicatorBar, aggregate_weekly, compute_indicators
from app.models import CorporateAction, Instrument, MarketBar, TechnicalIndicator
from worker import indicator_batch
from worker.indicator_batch import compute_market_indicators


def _weekdays(end: date, count: int) -> list[date]:
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


END = date(2026, 9, 4)
DAYS = _weekdays(END, 80)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _close(index: int, offset: float) -> float:
    return round(50 + offset + (index % 7) * 0.8 - (index % 3) * 0.5 + index * 0.1, 2)


def _seed(db, *, exchange="TWSE", symbol="2330", offset=0.0, days=DAYS, suspended=()):
    instrument = Instrument(
        exchange=exchange,
        symbol=symbol,
        name=symbol,
        instrument_type="stock",
        status="active",
    )
    db.add(instrument)
    db.flush()
    for index, day in enumerate(days):
        close = _close(index, offset)
        if day in suspended:
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=day,
                    open=0,
                    high=0,
                    low=0,
                    close=0,
                    adj_close=0,
                    volume=0,
                    turnover=0,
                    source="fixture",
                    is_suspended=True,
                )
            )
        else:
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=day,
                    open=close - 0.3,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    adj_close=close,
                    volume=1000 + index,
                    turnover=close * 1000,
                    source="fixture",
                )
            )
    db.flush()
    return instrument


def _expected(db, instrument):
    bars = db.scalars(
        select(MarketBar)
        .where(MarketBar.instrument_id == instrument.id)
        .order_by(MarketBar.trading_date)
    ).all()
    return compute_indicators(
        IndicatorBar(
            b.trading_date, b.open, b.high, b.low, b.close, b.volume, b.is_suspended
        )
        for b in bars
    )


def _rows(db, instrument):
    return db.scalars(
        select(TechnicalIndicator)
        .where(TechnicalIndicator.instrument_id == instrument.id)
        .order_by(TechnicalIndicator.trading_date)
    ).all()


def test_first_run_writes_history_and_daily_run_writes_only_new_day(db):
    twse = _seed(db)
    tpex = _seed(db, exchange="TPEx", symbol="6488", offset=30, suspended={DAYS[40]})
    first = compute_market_indicators(db, as_of=DAYS[-2])
    assert (
        first["status"] == "success"
        and first["formula_version"] == ind.INDICATOR_VERSION
    )
    assert first["rows_written"] == 2 * 79 and first["latest_day_rows"] == 2
    db.flush()
    for instrument in (twse, tpex):
        rows = _rows(db, instrument)
        expected = _expected(db, instrument)[:79]
        assert [r.trading_date for r in rows] == DAYS[:79]
        for row, point in zip(rows, expected):
            assert (
                row.bar_count == point.bar_count and row.null_reasons == point.reasons
            )
            assert {name: getattr(row, name) for name in ind.FIELDS} == point.values
            assert (
                row.formula_version == ind.INDICATOR_VERSION
                and row.source == "derived:market_bars"
            )
    suspended_row = next(r for r in _rows(db, tpex) if r.trading_date == DAYS[40])
    assert (
        suspended_row.ma5 is None and suspended_row.null_reasons["ma5"] == ind.SUSPENDED
    )
    assert (
        _rows(db, twse)[-1].ma120 is None
        and _rows(db, twse)[-1].null_reasons["ma120"] == ind.INSUFFICIENT_BARS
    )

    daily = compute_market_indicators(db)
    db.flush()
    assert daily["date"] == END.isoformat()
    assert (
        daily["rows_written"],
        daily["instruments_rewritten"],
        daily["latest_day_rows"],
    ) == (2, 0, 2)
    again = compute_market_indicators(db)
    assert again["rows_written"] == 0
    assert db.scalar(select(func.count(TechnicalIndicator.id))) == 160


def test_changed_history_rewrites_instrument_and_rebuild_rewrites_all(db):
    instrument = _seed(db)
    other = _seed(db, symbol="2317", offset=10)
    compute_market_indicators(db)
    db.flush()
    bar = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id, MarketBar.trading_date == DAYS[70]
        )
    )
    bar.close = bar.close + 3
    db.flush()
    result = compute_market_indicators(db)
    db.flush()
    assert result["instruments_rewritten"] == 1 and result["rows_written"] == 80
    stored = {name: getattr(_rows(db, instrument)[-1], name) for name in ind.FIELDS}
    assert stored == _expected(db, instrument)[-1].values
    rebuilt = compute_market_indicators(db, rebuild=True)
    db.flush()
    assert rebuilt["mode"] == "rebuild" and rebuilt["rows_written"] == 160
    assert len(_rows(db, other)) == 80


def test_batch_applies_corporate_action_basis(db):
    instrument = _seed(db)
    split = DAYS[60]
    for bar in db.scalars(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument.id, MarketBar.trading_date >= split
        )
    ):
        for name in ("open", "high", "low", "close", "adj_close"):
            setattr(bar, name, getattr(bar, name) / 2)
    db.add(
        CorporateAction(
            instrument_id=instrument.id,
            action_date=split,
            action_type="split",
            details_json={"price_factor": 0.5},
            source="fixture",
        )
    )
    db.flush()
    compute_market_indicators(db)
    db.flush()
    rows = {r.trading_date: r for r in _rows(db, instrument)}
    # Day after the split: MA5 mixes four pre-split closes, each halved to the post-split basis.
    closes = [_close(i, 0) for i in range(80)]
    assert rows[DAYS[61]].ma5 == pytest.approx(sum(closes[57:62]) / 5 / 2, abs=1e-6)
    assert rows[DAYS[59]].ma5 == pytest.approx(sum(closes[55:60]) / 5, abs=1e-6)


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(router)

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client


def _prefix():
    return router.prefix


def test_bars_api_day_returns_stored_indicators_and_reasons(db, client):
    _seed(db)
    db.commit()
    before = client.get(
        f"{_prefix()}/stocks/TWSE/2330/bars", params={"limit": 3}
    ).json()
    assert before["count"] == 3 and all(item["ma5"] is None for item in before["bars"])
    assert before["bars"][-1]["reasons"]["ma5"] == "not_computed"
    compute_market_indicators(db)
    db.commit()
    body = client.get(
        f"{_prefix()}/stocks/TWSE/2330/bars", params={"interval": "day", "limit": 70}
    ).json()
    assert (
        body["interval"] == "day"
        and body["count"] == 70
        and body["data_as_of"] == END.isoformat()
    )
    assert body["sources"] == ["fixture"]
    meta = body["indicators"]
    assert (
        meta["formula_version"] == ind.INDICATOR_VERSION
        and meta["required_bars"]["ma120"] == 120
    )
    assert meta["fields"] == list(ind.FIELDS) and meta["computed_at"]
    first, last = body["bars"][0], body["bars"][-1]
    assert first["date"] == DAYS[10].isoformat() and last["date"] == END.isoformat()
    assert {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "is_suspended",
        "bar_count",
        "reasons",
    } <= set(last)
    expected = _expected(
        db, db.scalar(select(Instrument).where(Instrument.symbol == "2330"))
    )[-1]
    assert {name: last[name] for name in ind.FIELDS} == expected.values
    assert last["ma120"] is None and last["reasons"] == {"ma120": "insufficient_bars"}
    assert (
        first["ma20"] is None
        and first["reasons"]["ma20"] == "insufficient_bars"
        and first["bar_count"] == 11
    )


def test_bars_api_week_aggregates_and_recomputes(db, client):
    instrument = _seed(db, exchange="TPEx", symbol="6488", suspended={DAYS[-3]})
    db.commit()
    body = client.get(
        f"{_prefix()}/stocks/TPEx/6488/bars", params={"interval": "week", "limit": 5}
    ).json()
    assert body["interval"] == "week" and body["count"] == 5
    bars = db.scalars(
        select(MarketBar)
        .where(MarketBar.instrument_id == instrument.id)
        .order_by(MarketBar.trading_date)
    ).all()
    daily = [
        IndicatorBar(
            b.trading_date, b.open, b.high, b.low, b.close, b.volume, b.is_suspended
        )
        for b in bars
    ]
    weeks = aggregate_weekly(daily)
    points = compute_indicators(w.calc for w in weeks)
    last_week, last_item = weeks[-1], body["bars"][-1]
    assert (
        last_item["week_start"] == last_week.week_start.isoformat()
        and last_item["date"] == END.isoformat()
    )
    assert last_item["trading_days"] == 4  # one suspended session left out
    used = [
        b
        for b in bars
        if last_week.week_start <= b.trading_date <= END and not b.is_suspended
    ]
    assert (last_item["open"], last_item["close"]) == (used[0].open, used[-1].close)
    assert last_item["high"] == max(b.high for b in used) and last_item["low"] == min(
        b.low for b in used
    )
    assert last_item["volume"] == sum(b.volume for b in used)
    assert {name: last_item[name] for name in ind.FIELDS} == points[-1].values
    assert (
        last_item["ma20"] is None
        and last_item["reasons"]["ma20"] == "insufficient_bars"
    )
    assert last_item["ma5"] is not None and last_item["sources"] == ["fixture"]
    assert body["indicators"]["source"].endswith("weekly_on_request")


def test_bars_api_errors(db, client):
    _seed(db)
    db.commit()
    assert client.get(f"{_prefix()}/stocks/TPEx/2330/bars").status_code == 404
    assert (
        client.get(
            f"{_prefix()}/stocks/TWSE/2330/bars", params={"interval": "month"}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{_prefix()}/stocks/TWSE/2330/bars", params={"limit": 0}
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"{_prefix()}/stocks/TWSE/2330/bars", params={"limit": 1501}
        ).status_code
        == 422
    )
    empty = Instrument(
        exchange="TWSE",
        symbol="9999",
        name="none",
        instrument_type="stock",
        status="active",
    )
    db.add(empty)
    db.commit()
    body = client.get(f"{_prefix()}/stocks/TWSE/9999/bars").json()
    assert body["count"] == 0 and body["bars"] == [] and body["data_as_of"] is None


def test_run_without_migrated_table_reports_failure(monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from worker import indicator_batch

    engine = create_engine("sqlite://", poolclass=StaticPool)
    monkeypatch.setattr(indicator_batch, "SessionLocal", sessionmaker(bind=engine))
    result = indicator_batch.run_indicator_batch()
    assert (
        result["status"] == "failed"
        and result["reason"] == "technical_indicators_table_missing_run_init_db"
    )
    engine.dispose()


def test_run_commits_through_session_factory(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    from worker import indicator_batch

    _seed(db)
    db.commit()
    monkeypatch.setattr(
        indicator_batch, "SessionLocal", sessionmaker(bind=db.get_bind())
    )
    result = indicator_batch.run_indicator_batch()
    assert result["status"] == "success" and result["rows_written"] == 80
    assert db.scalar(select(func.count(TechnicalIndicator.id))) == 80


@pytest.fixture
def daily_db(monkeypatch):
    """run_daily writes schedule_runs, so it needs a migrated (in-memory) DB."""
    from sqlalchemy.orm import sessionmaker

    from worker import pipeline

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        pipeline,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield engine
    engine.dispose()


def _daily_stubs(monkeypatch, *, collect="success", analyze="success", indicators=None):
    from worker import indicator_batch, pipeline

    calls = []
    monkeypatch.setattr(
        pipeline,
        "collect",
        lambda end, months_back=0, **_kwargs: calls.append(("collect", end))
        or {"status": collect, "records": 1},
    )
    monkeypatch.setattr(
        pipeline,
        "analyze",
        lambda **_kwargs: calls.append(("analyze",)) or {"status": analyze},
    )
    monkeypatch.setattr(
        pipeline,
        "evaluate",
        lambda **_kwargs: calls.append(("evaluate",)) or {"status": "success"},
    )

    def batch(run_date=None, *, rebuild=False):
        calls.append(("indicators", run_date))
        if indicators is not None:
            raise indicators
        return {"status": "success"}

    monkeypatch.setattr(indicator_batch, "run_indicator_batch", batch)
    # Catch-up of earlier sessions has its own tests (test_daily_schedule).
    from worker import schedule_runs

    monkeypatch.setattr(
        schedule_runs,
        "_catchup_step",
        lambda *_args: {"status": "success", "records": 0},
    )
    return pipeline, calls


def test_run_daily_runs_indicators_after_evaluate_with_run_date(daily_db, monkeypatch):
    pipeline, calls = _daily_stubs(monkeypatch)
    result = pipeline.run_daily(END)
    assert calls == [("collect", END), ("analyze",), ("evaluate",), ("indicators", END)]
    assert result["indicators"] == {"status": "success"}
    assert result["status"] == "success"


def test_run_daily_indicator_failure_does_not_stop_evaluate(daily_db, monkeypatch):
    pipeline, calls = _daily_stubs(monkeypatch, indicators=RuntimeError("disk full"))
    result = pipeline.run_daily(END)
    assert ("evaluate",) in calls and calls[-1] == ("indicators", END)
    assert result["evaluate"] == {"status": "success"}
    assert result["indicators"]["status"] == "failed"
    assert result["indicators"]["error"] == "RuntimeError: disk full"
    # The failure is visible on the run itself, not only in the step result.
    assert result["status"] == "failed"


def test_run_daily_skips_indicators_when_collect_fails_and_runs_them_when_analyze_fails(
    daily_db,
    monkeypatch,
):
    pipeline, calls = _daily_stubs(monkeypatch, collect="failed")
    result = pipeline.run_daily(END)
    assert calls == [("collect", END)]
    assert result["indicators"] == {
        "status": "skipped",
        "reason": "official_collection_incomplete",
    }
    pipeline, calls = _daily_stubs(monkeypatch, analyze="skipped")
    result = pipeline.run_daily(END)
    assert calls == [("collect", END), ("analyze",), ("indicators", END)]
    assert result["evaluate"]["reason"] == "analyze_not_successful" and result[
        "indicators"
    ] == {"status": "success"}


# Timestamps written below (#376). `frozen_utcnow` (conftest) makes app.clock answer one
# instant to every caller, so a stamp taken from local time or the real clock stores a
# value other than the one asserted here.


def test_indicator_rows_are_computed_at_the_clock(db, frozen_utcnow, monkeypatch):
    # The batch reads the UTC clock through the module's own datetime.
    monkeypatch.setattr(indicator_batch, "datetime", frozen_utcnow.datetime_class())
    instrument = _seed(db)
    compute_market_indicators(db)
    db.flush()
    rows = _rows(db, instrument)
    assert rows and {row.computed_at for row in rows} == {frozen_utcnow.at}
