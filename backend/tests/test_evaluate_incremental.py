"""The daily evaluate skips only signals whose rows cannot change (#841).

A settled signal (20-session window, current-rule settlements, unchanged
inputs; ``pipeline._settled_signal_ids`` R1-R8) keeps its rows.  Each input
change below must make the incremental evaluate recompute the signal, so its
rows equal ``evaluate(force=True)``'s on an identical database; removing any
one rule from ``_settled_signal_ids`` turns its case red.  ``force=True``
recomputes what the rules cannot see (a level rewritten by a re-analysis).
"""

from __future__ import annotations

import itertools
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
from app.tracking import TrackBar, TrackLevels, TRACKING_RULES, track_path

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


def r1_settlement_missing(db) -> None:
    db.execute(
        delete(SignalSettlement).where(
            SignalSettlement.signal_id == signal_id(db),
            SignalSettlement.horizon == 5,
        )
    )


def r2_evaluation_missing(db) -> None:
    db.execute(
        delete(SignalEvaluation).where(
            SignalEvaluation.signal_id == signal_id(db),
            SignalEvaluation.session_date == WINDOW[7],
        )
    )


def r2_bar_inserted(db) -> None:
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


def r2_bar_removed(db) -> None:
    db.delete(bar(db, WINDOW[12]))


def r3_close_corrected(db) -> None:
    bar(db, WINDOW[4]).close = 101.25


def r3_adj_close_corrected(db) -> None:
    bar(db, WINDOW[4]).adj_close = 100.75


def r3_volume_corrected(db) -> None:
    bar(db, WINDOW[4]).volume = 4321


def r3_source_changed(db) -> None:
    bar(db, WINDOW[4]).source = "fixture-refetch"


def r3_data_as_of_changed(db) -> None:
    bar(db, WINDOW[4]).data_as_of = datetime(2026, 9, 9, 15, 0, 0)


def r3_marked_suspended(db) -> None:
    bar(db, WINDOW[4]).is_suspended = True


def r4_corporate_action(db) -> None:
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


def r5_suspension_event(db) -> None:
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


def r6_chip_arrived(db) -> None:
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


def r7_group_changed(db) -> None:
    GROUP["available"] = True


def r8_prior_volume_corrected(db) -> None:
    bar(db, PRIOR[3]).volume = 9999


INPUT_CHANGES = [
    r1_settlement_missing,
    r2_evaluation_missing,
    r2_bar_inserted,
    r2_bar_removed,
    r3_close_corrected,
    r3_adj_close_corrected,
    r3_volume_corrected,
    r3_source_changed,
    r3_data_as_of_changed,
    r3_marked_suspended,
    r4_corporate_action,
    r5_suspension_event,
    r6_chip_arrived,
    r7_group_changed,
    r8_prior_volume_corrected,
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

    tracked.clear()
    forced = pipeline.evaluate(init_schema=False, force=True)
    assert sorted(tracked) == sorted([KEY, OPEN_KEY])
    assert forced["signals_skipped"] == 0
    assert forced["evaluations_written"] == 25


def test_force_recomputes_a_level_the_rules_cannot_see(make_factory, monkeypatch):
    """A re-analysis that rewrote an old signal's levels needs ``--force``."""

    sessions = make_factory("force.db")
    settle_once(monkeypatch, sessions)
    with sessions() as db:
        db.execute(
            update(Signal).where(Signal.signal_key == KEY).values(target_1=101.4)
        )
        db.commit()
    before = tracked_rows(sessions)
    assert pipeline.evaluate(init_schema=False)["signals_skipped"] == 1
    assert tracked_rows(sessions) == before
    pipeline.evaluate(init_schema=False, force=True)
    after = tracked_rows(sessions)
    assert after["signals"][KEY][0] == "target_1_hit"
    assert after != before


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


def test_the_settled_check_reads_suspension_like_track_path():
    """``_session_suspended`` is ``track_path``'s flag without a gap event."""

    for is_suspended, volume, flat in itertools.product(
        (False, True), (0, 1000, None), (False, True)
    ):
        o, h, low, c = (100.0, 100.0, 100.0, 100.0) if flat else (100, 101, 99, 100)
        session = track_path(
            TrackLevels(
                entry_type="breakout",
                breakout_price=None,
                pullback_low=None,
                pullback_high=None,
                invalid_price=None,
                target_1=None,
            ),
            [
                TrackBar(
                    trading_date=SESSIONS[0],
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    adj_close=c,
                    volume=volume,
                    is_suspended=is_suspended,
                    source="fixture",
                    data_time=None,
                    factor=1.0,
                    action_applied=False,
                    suspension_gap=False,
                )
            ],
            rules=TRACKING_RULES,
        ).sessions[0]
        assert session.suspended == pipeline._session_suspended(
            is_suspended=is_suspended, volume=volume, open_=o, high=h, low=low, close=c
        )


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
