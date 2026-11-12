"""The daily evaluate tracks open signals one committed batch at a time (#640).

Before #640 it loaded every open signal and held all their evaluations and
settlements in one transaction (the session does not autoflush), which outgrew
the 2 GB scheduler container.  These tests fail when ``evaluate`` loads all
signals at once or commits only at the end, and check that the batched result
equals one batch over all signals.
"""

from __future__ import annotations

import gc
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Instrument, MarketBar, Signal, SignalEvaluation, SignalSettlement

SIGNAL_DAY = date(2026, 9, 1)  # a Tuesday
BATCH = 2
OPEN = ["A1", "A2", "A3", "A4", "A5"]  # three batches of at most BATCH


def sessions_after(day: date, count: int) -> list[date]:
    days, cursor = [], day
    while len(days) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    return days


DAYS = sessions_after(SIGNAL_DAY, 6)


@pytest.fixture
def make_factory(tmp_path, monkeypatch):
    engines = []
    monkeypatch.setattr(pipeline, "init_db", lambda: None)

    def make(name: str):
        engine = create_engine(f"sqlite:///{tmp_path / name}")
        enable_sqlite_foreign_keys(engine)
        upgrade_database(engine)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with sessions() as db:
            seed(db)
            db.commit()
        monkeypatch.setattr(pipeline, "SessionLocal", sessions)
        return sessions

    yield make
    for engine in engines:
        engine.dispose()


def seed(db) -> None:
    strategy_id = pipeline._ensure_strategies(db)["breakout_v3"].id
    # A fills on the first session and holds; B gaps over the target.
    paths = {
        "A": [(100.5, 101.0, 99.5, 100.8)] + [(100.8, 101.5, 100.2, 101.0)] * 5,
        "B": [(104.0, 105.0, 103.5, 104.5)] + [(104.0, 104.5, 103.0, 104.0)] * 5,
    }
    for number, symbol in enumerate([*OPEN, "DONE", "BT"]):
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
        rows = [(SIGNAL_DAY, (99.0, 99.5, 98.5, 99.0))]
        rows += list(zip(DAYS, paths["AB"[number % 2]]))
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
                    source="fixture",
                )
            )
        key = (
            f"backtest-1-TWSE-{symbol}-{SIGNAL_DAY}-breakout_v3"
            if symbol == "BT"
            else f"analysis-TWSE-{symbol}-{SIGNAL_DAY}-breakout_v3"
        )
        db.add(
            Signal(
                signal_key=key,
                signal_date=SIGNAL_DAY,
                instrument_id=instrument.id,
                strategy_version_id=strategy_id,
                status="expired" if symbol == "DONE" else "conditional",
                earliest_execution_date=DAYS[0],
                data_quality="complete",
                source_report="fixture",
                rule_evidence_json={"strategy": "breakout_v3", "actionable": True},
                entry_type="breakout",
                breakout_price=100.0,
                invalid_price=98.0,
                target_1=103.2,
                target_2=106.0,
            )
        )
        db.flush()


def tracked_rows(sessions) -> dict:
    with sessions() as db:
        signals = {
            row.signal_key: (
                row.status,
                row.data_quality,
                row.execution_date,
                row.execution_price,
            )
            for row in db.scalars(select(Signal))
        }
        settlements = {
            (row.signal_id, row.horizon): tuple(
                getattr(row, column.key)
                for column in SignalSettlement.__table__.columns
                if column.key not in {"id", "created_at", "updated_at"}
            )
            for row in db.scalars(select(SignalSettlement))
        }
        evaluations = {
            (row.signal_id, row.session_date): tuple(
                getattr(row, column.key)
                for column in SignalEvaluation.__table__.columns
                if column.key not in {"id", "created_at", "updated_at"}
            )
            for row in db.scalars(select(SignalEvaluation))
        }
    return {"signals": signals, "settlements": settlements, "evaluations": evaluations}


def test_evaluate_never_holds_more_than_one_batch_of_signals(make_factory, monkeypatch):
    sessions = make_factory("batches.db")
    monkeypatch.setattr(pipeline, "EVALUATE_TRACKING_BATCH", BATCH, raising=False)
    loaded, committed = [], []
    original = pipeline._evaluate_signal_tracking

    def spy(db, signal, **kwargs):
        gc.collect()
        loaded.append(sum(isinstance(row, Signal) for row in db.identity_map.values()))
        with sessions() as probe:  # another connection sees only committed rows
            committed.append(probe.scalar(select(func.count(SignalSettlement.id))))
        return original(db, signal, **kwargs)

    monkeypatch.setattr(pipeline, "_evaluate_signal_tracking", spy)
    result = pipeline.evaluate(init_schema=False)

    assert result["status"] == "success"
    assert result["signals_checked"] == len(OPEN)
    assert result["settlements_written"] == 2 * len(OPEN)
    assert len(loaded) == len(OPEN)
    # Loading every open signal at once holds all five in the session.
    assert max(loaded) <= BATCH
    # Settlements are committed batch by batch: 0, 0, then 4, 4, then 8.
    assert committed == [0, 0, 2 * BATCH, 2 * BATCH, 4 * BATCH]


def test_batched_evaluate_writes_what_one_batch_writes(make_factory, monkeypatch):
    monkeypatch.setattr(pipeline, "EVALUATE_TRACKING_BATCH", 10_000, raising=False)
    whole = make_factory("whole.db")
    expected = pipeline.evaluate(init_schema=False)
    monkeypatch.setattr(pipeline, "EVALUATE_TRACKING_BATCH", BATCH, raising=False)
    batched = make_factory("batched.db")
    assert pipeline.evaluate(init_schema=False) == expected

    rows = tracked_rows(batched)
    assert rows == tracked_rows(whole)
    # Both kinds of path ran: one fills and stays active, one is not entered.
    statuses = {key: row[0] for key, row in rows["signals"].items()}
    assert statuses[f"analysis-TWSE-A1-{SIGNAL_DAY}-breakout_v3"] == "active"
    assert statuses[f"analysis-TWSE-A2-{SIGNAL_DAY}-breakout_v3"] == "expired"
    # The ended and the backtest signal are not tracked by the daily step.
    assert statuses[f"analysis-TWSE-DONE-{SIGNAL_DAY}-breakout_v3"] == "expired"
    assert statuses[f"backtest-1-TWSE-BT-{SIGNAL_DAY}-breakout_v3"] == "conditional"
    assert len(rows["settlements"]) == 2 * len(OPEN)
