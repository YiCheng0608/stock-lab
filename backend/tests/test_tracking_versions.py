"""Tracking rule versions on a database (#444, docs/spec/tracking.md 口徑版本).

A technical backtest with the v2 key writes tracking_v2 rows and leaves an older
run's rows alone, the daily ``evaluate`` never re-tracks backtest signals, an
open analysis signal is recomputed (and recorded) as tracking_v2 while an ended
one keeps its tracking_v1 rows, and rerunning the v2 backtest changes nothing.

The setup writes no column the tracking_v1 schema lacks, so the old program
fails these tests by assertion.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
import worker.sources as sources
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import Instrument, IngestionRun, MarketBar, Signal, SignalSettlement

SIGNAL_DAY = date(2026, 9, 1)  # a Tuesday
LEVELS = {
    "entry_type": "breakout",
    "breakout_price": 100.0,
    "invalid_price": 98.0,
    "target_1": 103.2,
    "target_2": 106.0,
}
# The first session gaps over the first target (open 104 >= 103.2), then holds.
GAP = (104.0, 105.0, 103.5, 104.5)
HOLD = (104.0, 104.5, 103.0, 104.0)
SETTLED = (
    "settlement_date",
    "final_status",
    "first_trigger",
    "return_or_risk",
    "incomparable_reason",
    "execution_date",
    "execution_price",
    "comparable",
    "data_quality",
)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'versions.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", sessions)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(pipeline, "_calculate_features", lambda *_a, **_k: None)
    monkeypatch.setattr(pipeline, "_calculate_group_scores", lambda *_a, **_k: None)
    yield sessions
    engine.dispose()


def sessions_after(day: date, count: int) -> list[date]:
    days, cursor = [], day
    while len(days) < count:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    return days


DAYS = sessions_after(SIGNAL_DAY, 6)
END = DAYS[-1]


def stock(db, symbol: str) -> Instrument:
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
    rows = [(SIGNAL_DAY, (99.0, 99.5, 98.5, 99.0)), (DAYS[0], GAP)]
    rows += [(day, HOLD) for day in DAYS[1:]]
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
    db.flush()
    return instrument


def add_signal(db, instrument, key, status, strategy_id) -> Signal:
    row = Signal(
        signal_key=key,
        signal_date=SIGNAL_DAY,
        instrument_id=instrument.id,
        strategy_version_id=strategy_id,
        status=status,
        earliest_execution_date=DAYS[0],
        data_quality="complete",
        source_report="fixture",
        rule_evidence_json={"strategy": "breakout_v3", "actionable": True},
        **LEVELS,
    )
    db.add(row)
    db.flush()
    return row


def stored_v1_settlements(db, signal: Signal) -> None:
    """Rows as tracking_v1 wrote them: the gap fill exits at the first target."""

    for horizon in (5, 20):
        db.add(
            SignalSettlement(
                signal_id=signal.id,
                horizon=horizon,
                settlement_date=DAYS[4],
                final_status="target_1_hit",
                first_trigger="target_1_hit",
                return_or_risk=-0.0109,
                execution_date=DAYS[0],
                execution_price=104.052,
                comparable=True,
                data_quality="complete",
            )
        )
    db.flush()


def settled(db, signal_id: int) -> dict[int, tuple]:
    rows = db.scalars(
        select(SignalSettlement).where(SignalSettlement.signal_id == signal_id)
    ).all()
    return {row.horizon: tuple(getattr(row, name) for name in SETTLED) for row in rows}


def rules(db, signal_id: int) -> set[str]:
    return set(
        db.scalars(
            select(SignalSettlement.tracking_rules).where(
                SignalSettlement.signal_id == signal_id
            )
        )
    )


def old_backtest(db, strategy_id) -> tuple[int, int]:
    """A finished technical-backtest:v1 run with one tracked signal."""

    run = IngestionRun(
        run_type="backtest",
        source="technical_backtest",
        run_date=END,
        status="success",
        request_key=f"technical-backtest:v1:{SIGNAL_DAY}:{END}",
        metadata_json={"workflow": "technical_backtest_v1"},
    )
    db.add(run)
    db.flush()
    signal = add_signal(
        db,
        stock(db, "OLD"),
        f"backtest-{run.id}-TWSE-OLD-{SIGNAL_DAY}-breakout_v3",
        # Not an ended status, so the daily step used to pick it up.
        "target_1_hit",
        strategy_id,
    )
    stored_v1_settlements(db, signal)
    return run.id, signal.id


def strategy_id(db) -> int:
    return pipeline._ensure_strategies(db)["breakout_v3"].id


def test_the_daily_evaluate_never_rewrites_a_backtest_settlement(factory):
    with factory() as db:
        _run_id, signal_id = old_backtest(db, strategy_id(db))
        db.commit()
        before = settled(db, signal_id)
    pipeline.evaluate(init_schema=False)
    with factory() as db:
        assert settled(db, signal_id) == before
        assert db.get(Signal, signal_id).status == "target_1_hit"


def test_an_open_analysis_signal_is_recomputed_as_v2_and_an_ended_one_keeps_v1(
    factory,
):
    with factory() as db:
        sid = strategy_id(db)
        open_signal = add_signal(
            db,
            stock(db, "OPEN"),
            f"analysis-TWSE-OPEN-{SIGNAL_DAY}-breakout_v3",
            "target_1_hit",
            sid,
        )
        ended = add_signal(
            db,
            stock(db, "DONE"),
            f"analysis-TWSE-DONE-{SIGNAL_DAY}-breakout_v3",
            "expired",
            sid,
        )
        for row in (open_signal, ended):
            stored_v1_settlements(db, row)
        db.commit()
        ended_before = settled(db, ended.id)
        open_id, ended_id = open_signal.id, ended.id
    pipeline.evaluate(init_schema=False)
    with factory() as db:
        recomputed = settled(db, open_id)
        assert recomputed[5][1:] == (
            "incomparable",
            None,
            None,
            "gap_above_target",
            None,
            None,
            False,
            "incomplete",
        )
        assert rules(db, open_id) == {"tracking_v2"}
        signal = db.get(Signal, open_id)
        assert signal.execution_date is None and signal.execution_price is None
        # An ended signal is not tracked again: its tracking_v1 rows stay.
        assert settled(db, ended_id) == ended_before
        assert rules(db, ended_id) == {"tracking_v1"}


def fake_generate(db, score_date, strategies, *, namespace="analysis", registry=None):
    if score_date != SIGNAL_DAY:
        return 0
    instrument = db.scalar(select(Instrument).where(Instrument.symbol == "NEW"))
    key = f"{namespace}-TWSE-NEW-{SIGNAL_DAY}-breakout_v3"
    if db.scalar(select(Signal).where(Signal.signal_key == key)) is None:
        add_signal(db, instrument, key, "conditional", strategies["breakout_v3"].id)
    return 1


def v2_rows(db, run_id: int) -> dict[tuple[str, int], tuple]:
    signals = db.scalars(
        select(Signal).where(Signal.signal_key.like(f"backtest-{run_id}-%"))
    ).all()
    rows = {}
    for signal in signals:
        for item in db.scalars(
            select(SignalSettlement).where(SignalSettlement.signal_id == signal.id)
        ):
            rows[(signal.signal_key, item.horizon)] = (
                item.id,
                item.tracking_rules,
                *(getattr(item, name) for name in SETTLED),
            )
    return rows


def test_a_v2_backtest_leaves_the_v1_run_alone_and_reruns_idempotently(
    factory, monkeypatch
):
    monkeypatch.setattr(pipeline, "_generate_signals", fake_generate)
    with factory() as db:
        old_run, old_signal = old_backtest(db, strategy_id(db))
        stock(db, "NEW")
        db.commit()
        old_before = settled(db, old_signal)

    first = pipeline.backtest(SIGNAL_DAY, END)
    assert first["run"]["status"] == "success"
    assert first["run"]["request_key"] == f"technical-backtest:v2:{SIGNAL_DAY}:{END}"
    assert first["run"]["tracking_version"] == "v2"
    assert first["run"]["metadata"]["tracking_rules"] == "tracking_v2"
    run_id = first["run"]["id"]
    assert run_id != old_run
    with factory() as db:
        rows = v2_rows(db, run_id)
        assert {key[1] for key in rows} == {5, 20}
        t5 = rows[(f"backtest-{run_id}-TWSE-NEW-{SIGNAL_DAY}-breakout_v3", 5)]
        assert t5[1] == "tracking_v2"
        assert t5[3:] == (
            "incomparable",
            None,
            None,
            "gap_above_target",
            None,
            None,
            False,
            "incomplete",
        )
        assert settled(db, old_signal) == old_before
        assert rules(db, old_signal) == {"tracking_v1"}
        old = pipeline.summarize_backtest(db, old_run)
        assert old["run"]["tracking_version"] == "v1"

    # The same request again reuses the run; a forced rerun writes the same rows.
    again = pipeline.backtest(SIGNAL_DAY, END)
    assert again["idempotent_reuse"] is True and again["run"]["id"] == run_id
    forced = pipeline.backtest(SIGNAL_DAY, END, force=True)
    assert forced["run"]["id"] == run_id
    pipeline.evaluate(init_schema=False)
    with factory() as db:
        assert v2_rows(db, run_id) == rows
        assert settled(db, old_signal) == old_before
