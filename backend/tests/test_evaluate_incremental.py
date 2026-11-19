"""The daily evaluate skips only signals whose rows would not change (#841).

A settled signal (``pipeline._settled_signal_ids`` R1-R4: full window, no
corporate action, no suspension event, and tracking it now gives exactly the
stored rows) keeps its rows.  Each change below makes a full evaluate write
different rows; the incremental evaluate must then track the signal too, so
both databases end equal.  Removing any one rule turns a case red
(AC-1).  ``force=True`` tracks every selected signal (AC-3).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.migrations import upgrade_database
from app.models import (
    ChipSnapshot,
    CorporateAction,
    Event,
    Instrument,
    MarketBar,
    Signal,
    SignalEvaluation,
    SignalSettlement,
)
from app.tracking import TRACKING_RULES

SIGNAL_DAY = date(2026, 9, 1)  # a Tuesday
KEY = f"analysis-TWSE-AAA-{SIGNAL_DAY}-breakout_v3"
OPEN_KEY = f"analysis-TWSE-BBB-{SIGNAL_DAY}-breakout_v3"


def weekdays(start: date, count: int, step: int) -> list[date]:
    days, cursor = [], start
    while len(days) < count:
        cursor += timedelta(days=step)
        if cursor.weekday() < 5:
            days.append(cursor)
    return days


PRIOR = sorted([SIGNAL_DAY, *weekdays(SIGNAL_DAY, 19, -1)])
AFTER = weekdays(SIGNAL_DAY, 25, 1)
# A weekday inside the window with no bar, so a bar can be inserted there.
GAP = AFTER[9]
SESSIONS = [day for day in AFTER if day != GAP]  # 24 bars, window = first 20
WINDOW = SESSIONS[:20]
GROUP = {"available": False}


@pytest.fixture
def make_factory(tmp_path, monkeypatch):
    engines = []
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(
        pipeline,
        "_best_group_for_signal",
        lambda *_args: object() if GROUP["available"] else None,
    )
    GROUP["available"] = False

    def make(name: str):
        engine = create_engine(f"sqlite:///{tmp_path / name}")
        enable_sqlite_foreign_keys(engine)
        upgrade_database(engine)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with sessions() as db:
            seed(db)
            db.commit()
        return sessions

    yield make
    for engine in engines:
        engine.dispose()


def use(monkeypatch, sessions) -> None:
    monkeypatch.setattr(pipeline, "SessionLocal", sessions)


def seed(db) -> None:
    strategy_id = pipeline._ensure_strategies(db)["breakout_v3"].id
    for symbol, key in (("AAA", KEY), ("BBB", OPEN_KEY)):
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
        days = PRIOR + (SESSIONS if symbol == "AAA" else SESSIONS[:5])
        for number, day in enumerate(days):
            if day <= SIGNAL_DAY:
                o, h, low, c = 99.0, 99.5, 98.5, 99.0
            elif day == SESSIONS[0]:
                o, h, low, c = 100.5, 101.0, 99.5, 100.8  # fills the breakout
            else:
                o, h, low, c = 100.8, 101.5, 100.2, 101.0  # stays active
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    trading_date=day,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    adj_close=c,
                    # One empty prior volume: no 20-day ratio until R8 fills it.
                    volume=0 if day == PRIOR[3] else 1000 + number,
                    turnover=c * 1000,
                    source="fixture",
                    data_as_of=datetime(2026, 9, 1, 14, 0, 0),
                )
            )
        db.add(
            Signal(
                signal_key=key,
                signal_date=SIGNAL_DAY,
                instrument_id=instrument.id,
                strategy_version_id=strategy_id,
                status="conditional",
                earliest_execution_date=SESSIONS[0],
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


def instrument_id(db, symbol: str = "AAA") -> int:
    return db.scalar(select(Instrument.id).where(Instrument.symbol == symbol))


def signal_id(db) -> int:
    return db.scalar(select(Signal.id).where(Signal.signal_key == KEY))


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
                if column.key != "id"
            )
            for row in db.scalars(select(SignalSettlement))
        }
        evaluations = {
            (row.signal_id, row.session_date): tuple(
                getattr(row, column.key)
                for column in SignalEvaluation.__table__.columns
                if column.key != "id"
            )
            for row in db.scalars(select(SignalEvaluation))
        }
    return {"signals": signals, "settlements": settlements, "evaluations": evaluations}


def settle_once(monkeypatch, sessions) -> None:
    """Two daily runs: the first tracks, the second finds the signal settled."""

    use(monkeypatch, sessions)
    pipeline.evaluate(init_schema=False)
    before = tracked_rows(sessions)
    result = pipeline.evaluate(init_schema=False)
    assert result["signals_checked"] == 2
    assert result["signals_skipped"] == 1  # AAA; BBB's window is open
    assert tracked_rows(sessions) == before


def bar(db, day: date) -> MarketBar:
    return db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == instrument_id(db),
            MarketBar.trading_date == day,
        )
    )


def settlement_missing(db) -> None:
    db.execute(
        delete(SignalSettlement).where(
            SignalSettlement.signal_id == signal_id(db),
            SignalSettlement.horizon == 5,
        )
    )


def settlement_from_older_rules(db) -> None:
    db.execute(
        update(SignalSettlement)
        .where(
            SignalSettlement.signal_id == signal_id(db),
            SignalSettlement.horizon == 5,
        )
        .values(tracking_rules="tracking_v0")
    )


def evaluation_missing(db) -> None:
    db.execute(
        delete(SignalEvaluation).where(
            SignalEvaluation.signal_id == signal_id(db),
            SignalEvaluation.session_date == WINDOW[7],
        )
    )


def bar_inserted(db) -> None:
    db.add(
        MarketBar(
            instrument_id=instrument_id(db),
            trading_date=GAP,
            open=100.8,
            high=101.5,
            low=100.2,
            close=101.0,
            adj_close=101.0,
            volume=1500,
            turnover=101000.0,
            source="fixture",
            data_as_of=datetime(2026, 9, 1, 14, 0, 0),
        )
    )


def bar_removed(db) -> None:
    db.delete(bar(db, WINDOW[12]))


def close_corrected(db) -> None:
    bar(db, WINDOW[4]).close = 101.25


def adj_close_corrected(db) -> None:
    bar(db, WINDOW[4]).adj_close = 100.75


def high_reaches_the_target(db) -> None:
    bar(db, WINDOW[4]).high = 103.5


def volume_corrected(db) -> None:
    bar(db, WINDOW[4]).volume = 4321


def source_changed(db) -> None:
    bar(db, WINDOW[4]).source = "fixture-refetch"


def data_as_of_changed(db) -> None:
    bar(db, WINDOW[4]).data_as_of = datetime(2026, 9, 9, 15, 0, 0)


def marked_suspended(db) -> None:
    bar(db, WINDOW[4]).is_suspended = True


def corporate_action_added(db) -> None:
    db.add(
        CorporateAction(
            instrument_id=instrument_id(db),
            action_date=WINDOW[6],
            action_type="cash_dividend",
            cash_dividend=2.0,
            reference_price=101.0,
            source="fixture",
        )
    )


def suspension_event_added(db) -> None:
    db.add(
        Event(
            instrument_id=instrument_id(db),
            event_date=WINDOW[6],
            event_type="suspension",
            title="fixture suspension",
            details_json={"resumed_date": WINDOW[8].isoformat()},
            source="fixture",
        )
    )


def chip_arrived(db) -> None:
    db.add(
        ChipSnapshot(
            instrument_id=instrument_id(db),
            trading_date=WINDOW[3],
            foreign_buy=10.0,
            trust_buy=5.0,
            dealer_buy=1.0,
            margin_balance=100.0,
        )
    )


def group_changed(db) -> None:
    GROUP["available"] = True


def prior_volume_corrected(db) -> None:
    bar(db, PRIOR[3]).volume = 9999


def level_rewritten(db) -> None:
    # A re-analysis of the signal day rewrote the target (_write_strategy_signal).
    db.execute(update(Signal).where(Signal.signal_key == KEY).values(target_1=101.4))


def status_reset(db) -> None:
    # A re-analysis of the signal day set the lifecycle back (_set_signal_status).
    db.execute(
        update(Signal).where(Signal.signal_key == KEY).values(status="conditional")
    )


# Each change makes the next full evaluate write different rows for KEY.  The
# rule that must see it: R1 window (open_window_bar_added), R2 corporate
# action, R3 suspension event, R4 same result (all the others).
INPUT_CHANGES = [
    settlement_missing,
    settlement_from_older_rules,
    evaluation_missing,
    bar_inserted,
    bar_removed,
    close_corrected,
    adj_close_corrected,
    high_reaches_the_target,
    volume_corrected,
    source_changed,
    data_as_of_changed,
    marked_suspended,
    corporate_action_added,
    suspension_event_added,
    chip_arrived,
    group_changed,
    prior_volume_corrected,
    level_rewritten,
    status_reset,
]


@pytest.mark.parametrize("change", INPUT_CHANGES, ids=lambda change: change.__name__)
def test_a_changed_input_is_recomputed_as_a_full_evaluate_would(
    make_factory, monkeypatch, change
):
    incremental = make_factory("incremental.db")
    full = make_factory("full.db")
    for sessions in (incremental, full):
        settle_once(monkeypatch, sessions)
    for sessions in (incremental, full):
        with sessions() as db:
            change(db)
            db.commit()
    settled_rows = tracked_rows(full)

    use(monkeypatch, full)
    forced = pipeline.evaluate(init_schema=False, force=True)
    use(monkeypatch, incremental)
    result = pipeline.evaluate(init_schema=False)

    assert forced["force"] is True and forced["signals_skipped"] == 0
    assert result["force"] is False
    # The change matters: the full recomputation rewrites the signal's rows.
    assert tracked_rows(full) != settled_rows
    assert result["signals_skipped"] == 0
    assert tracked_rows(incremental) == tracked_rows(full)


def test_a_reset_data_quality_is_recomputed(make_factory, monkeypatch):
    """A settled signal whose data quality a re-analysis reset is tracked again."""

    sessions = make_factory("quality.db")
    use(monkeypatch, sessions)
    with sessions() as db:
        marked_suspended(db)
        db.commit()
    pipeline.evaluate(init_schema=False)
    assert pipeline.evaluate(init_schema=False)["signals_skipped"] == 1
    with sessions() as db:
        assert db.scalar(
            select(Signal.data_quality).where(Signal.signal_key == KEY)
        ) == ("incomplete")
        db.execute(
            update(Signal)
            .where(Signal.signal_key == KEY)
            .values(data_quality="complete")
        )
        db.commit()
    assert pipeline.evaluate(init_schema=False)["signals_skipped"] == 0
    with sessions() as db:
        assert db.scalar(
            select(Signal.data_quality).where(Signal.signal_key == KEY)
        ) == ("incomplete")


def test_an_open_window_gets_its_new_session(make_factory, monkeypatch):
    """R1: a window under 20 sessions is tracked even if its rows still match."""

    sessions = make_factory("open.db")
    settle_once(monkeypatch, sessions)
    with sessions() as db:
        bbb = instrument_id(db, "BBB")
        db.add(
            MarketBar(
                instrument_id=bbb,
                trading_date=SESSIONS[5],
                open=100.8,
                high=101.5,
                low=100.2,
                close=101.0,
                adj_close=101.0,
                volume=1500,
                turnover=101000.0,
                source="fixture",
                data_as_of=datetime(2026, 9, 1, 14, 0, 0),
            )
        )
        db.commit()
    result = pipeline.evaluate(init_schema=False)
    assert result["signals_skipped"] == 1  # AAA only
    with sessions() as db:
        open_id = db.scalar(select(Signal.id).where(Signal.signal_key == OPEN_KEY))
        dates = db.scalars(
            select(SignalEvaluation.session_date).where(
                SignalEvaluation.signal_id == open_id
            )
        ).all()
    assert sorted(dates) == SESSIONS[:6]


def test_a_settled_signal_is_not_tracked_again(make_factory, monkeypatch):
    sessions = make_factory("settled.db")
    settle_once(monkeypatch, sessions)
    tracked = []
    original = pipeline._evaluate_signal_tracking

    def spy(db, signal, **kwargs):
        tracked.append(signal.signal_key)
        return original(db, signal, **kwargs)

    monkeypatch.setattr(pipeline, "_evaluate_signal_tracking", spy)
    result = pipeline.evaluate(init_schema=False)
    assert tracked == [OPEN_KEY]
    assert result["signals_checked"] == 2
    assert result["signals_skipped"] == 1
    # Only the open signal's rows are counted as written.
    assert result["evaluations_written"] == 5
    assert result["settlements_written"] == 2

    # AC-3: --force tracks every selected signal again.
    tracked.clear()
    forced = pipeline.evaluate(init_schema=False, force=True)
    assert sorted(tracked) == sorted([KEY, OPEN_KEY])
    assert forced["signals_skipped"] == 0
    assert forced["evaluations_written"] == 25


def test_the_incremental_and_the_full_evaluate_write_the_same_rows(
    make_factory, monkeypatch
):
    incremental = make_factory("a.db")
    full = make_factory("b.db")
    use(monkeypatch, incremental)
    first = pipeline.evaluate(init_schema=False)
    second = pipeline.evaluate(init_schema=False)
    use(monkeypatch, full)
    pipeline.evaluate(init_schema=False, force=True)
    pipeline.evaluate(init_schema=False, force=True)
    assert first["signals_skipped"] == 0 and second["signals_skipped"] == 1
    assert tracked_rows(incremental) == tracked_rows(full)
    with incremental() as db:
        rules = set(db.scalars(select(SignalSettlement.tracking_rules)))
    assert rules == {TRACKING_RULES}


@pytest.mark.parametrize(("argv", "force"), [([], False), (["--force"], True)])
def test_the_cli_passes_force_to_evaluate(monkeypatch, capsys, argv, force):
    import worker.cli as cli

    calls = []

    def fake_evaluate(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "force": kwargs.get("force")}

    monkeypatch.setattr(cli, "evaluate", fake_evaluate)
    monkeypatch.setattr("sys.argv", ["worker.cli", "evaluate", *argv])
    cli.main()
    assert calls == [{"force": force}]
    assert json.loads(capsys.readouterr().out)["force"] is force
