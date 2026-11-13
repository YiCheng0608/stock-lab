"""tools/research/exit_research.py: the exit rules, worked by hand (#673)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import tracking
from app.models import (
    Base,
    CorporateAction,
    Event,
    IngestionRun,
    Instrument,
    MarketBar,
    Signal,
    SignalSettlement,
    StrategyVersion,
)

ROOT = Path(__file__).resolve().parents[2]


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
tool = _tool("exit_research")

BUY = 1.0005
SELL = 0.9995
COST = 0.00585
DAY0 = date(2025, 3, 3)
RULES = {rule.key: rule for rule in tool.RULES}

# invalid 90, target_1 = 90 + 1.6R... with R = 10: entry 100, t1 116, t2 130.
BREAKOUT = tool.Levels("breakout", 100.0, None, None, 90.0, 116.0, 130.0)
PULLBACK = tool.Levels("pullback", None, 98.0, 102.0, 90.0, 116.0, 130.0)


def day(n: int) -> date:
    return DAY0 + timedelta(days=n)


def bar(n: int, o: float, h: float, low: float, c: float, **extra) -> tool.Bar:
    return tool.Bar(day(n), o, h, low, c, **extra)


def flat(n: int, price: float = 105.0, **extra) -> tool.Bar:
    return bar(n, price, price + 1, price - 1, price, **extra)


def run(levels, bars, key):
    entry = tool.enter(levels, bars)
    return entry, tool.exit_trade(levels, bars, entry, RULES[key])


def net(sold_level: float, bought: float) -> float:
    return sold_level * SELL / (bought * BUY) - 1.0 - COST


# --- fixed constants -----------------------------------------------------------


def test_the_window_and_costs_are_the_products_and_the_evidence_tools():
    assert tool.WINDOW == tracking.TRACKING_WINDOW_SESSIONS
    assert tool.SLIPPAGE * 10_000 == tracking.EXECUTION_SLIPPAGE_BPS
    assert tool.PRODUCT_COST_BPS == tracking.ROUND_TRIP_TRANSACTION_COST_BPS
    assert tool.COST_BPS == lib.DEFAULT_COST_BPS == 58.5
    assert (
        tool.MAX_SESSIONS
        >= tool.WINDOW
        + max(rule.hold for rule in tool.RULES if rule.kind == "hold")
        - 1
    )


def test_the_rules_are_fixed_before_the_run():
    assert [rule.key for rule in tool.RULES] == [
        "E0",
        "E1",
        "T1",
        "T2",
        "T3",
        "H5",
        "H10",
        "H20",
    ]
    assert [RULES[key].k for key in ("T1", "T2", "T3")] == [1.0, 1.5, 2.0]
    assert [RULES[key].hold for key in ("H5", "H10", "H20")] == [5, 10, 20]
    assert tool.ALTERNATIVES == ("E1", "T1", "T2", "T3", "H5", "H10", "H20")


def test_r_is_the_risk_of_risk_levels():
    from app.strategies.base import risk_levels

    entry, invalid, target_1, _target_2 = risk_levels(100.0, 4.0)
    levels = tool.Levels("breakout", entry, None, None, invalid, target_1, None)
    assert levels.risk == pytest.approx(4.0)


# --- the entry -----------------------------------------------------------------


def test_breakout_fills_at_the_trigger_or_a_higher_open():
    entry = tool.enter(BREAKOUT, [flat(1, 95), bar(2, 97, 101, 96, 100)])
    assert (entry.session, entry.reason) == (2, "filled")
    assert entry.price == pytest.approx(100 * BUY)
    entry = tool.enter(BREAKOUT, [bar(1, 103, 105, 102, 104)])
    assert entry.price == pytest.approx(103 * BUY)


def test_pullback_fills_at_the_open_inside_or_the_zone_edge():
    assert tool.enter(PULLBACK, [bar(1, 101, 103, 99, 100)]).price == pytest.approx(
        101 * BUY
    )
    assert tool.enter(PULLBACK, [bar(1, 104, 105, 100, 101)]).price == pytest.approx(
        102 * BUY
    )


def test_entries_not_taken_on_a_gap_beyond_the_levels():
    assert (
        tool.enter(BREAKOUT, [bar(1, 117, 118, 110, 112)]).reason == "gap_above_target"
    )
    pullback = tool.Levels("pullback", None, 88.0, 92.0, 90.0, 116.0, 130.0)
    assert tool.enter(pullback, [bar(1, 89, 91, 88, 90)]).reason == "gap_below_invalid"
    assert (
        tool.enter(BREAKOUT, [flat(n, 95) for n in range(1, 21)]).reason
        == "not_triggered"
    )


def test_a_session_locked_at_limit_up_cannot_be_bought():
    locked = bar(1, 104.5, 104.5, 104.5, 104.5, limit_up=104.5)
    entry = tool.enter(BREAKOUT, [locked, bar(2, 106, 108, 105, 107)])
    assert (entry.session, entry.limit_blocked) == (2, 1)
    assert entry.price == pytest.approx(106 * BUY)
    # Touching the limit up during the day is not a lock.
    entry = tool.enter(BREAKOUT, [bar(1, 101, 104.5, 100, 104.5, limit_up=104.5)])
    assert (entry.session, entry.limit_blocked) == (1, 0)


def test_suspended_sessions_do_not_fill_and_the_window_is_twenty():
    bars = [flat(1, 105, suspended=True)] + [flat(n, 95) for n in range(2, 21)]
    bars.append(bar(21, 101, 102, 100, 101))
    assert tool.enter(BREAKOUT, bars).reason == "not_triggered"


# --- the exits -----------------------------------------------------------------


def test_e0_exits_at_the_first_target():
    bars = [bar(1, 99, 101, 98, 100), bar(2, 104, 117, 103, 115)]
    entry, exit_ = run(BREAKOUT, bars, "E0")
    assert (exit_.reason, exit_.session, exit_.holding) == ("target", 2, 2)
    assert exit_.net == pytest.approx(net(116, 100))
    assert not exit_.gapped


def test_a_gap_beyond_a_level_fills_at_the_open():
    up = [bar(1, 99, 101, 98, 100), bar(2, 120, 121, 119, 120)]
    _entry, exit_ = run(BREAKOUT, up, "E0")
    assert (exit_.reason, exit_.gapped) == ("target", True)
    assert exit_.net == pytest.approx(net(120, 100))
    down = [bar(1, 99, 101, 98, 100), bar(2, 85, 86, 84, 85)]
    _entry, exit_ = run(BREAKOUT, down, "E0")
    assert (exit_.reason, exit_.gapped) == ("stop", True)
    assert exit_.net == pytest.approx(net(85, 100))


def test_a_session_touching_both_is_the_stop_first():
    bars = [bar(1, 99, 101, 98, 100), bar(2, 100, 117, 89, 110)]
    _entry, exit_ = run(BREAKOUT, bars, "E0")
    assert (exit_.reason, exit_.both_touched) == ("stop", True)
    assert exit_.net == pytest.approx(net(90, 100))


def test_the_fill_session_can_exit_at_the_level():
    bars = [bar(1, 99, 101, 89, 95)]
    _entry, exit_ = run(BREAKOUT, bars, "E0")
    assert (exit_.reason, exit_.session, exit_.gapped) == ("stop", 1, False)
    assert exit_.net == pytest.approx(net(90, 100))


def test_e0_and_e1_end_at_the_close_of_session_twenty():
    bars = [bar(1, 99, 101, 98, 100)] + [flat(n, 110) for n in range(2, 21)]
    for key in ("E0", "E1", "T3"):
        _entry, exit_ = run(BREAKOUT, bars, key)
        assert (exit_.reason, exit_.session, exit_.holding) == ("window_end", 20, 20)
        assert exit_.net == pytest.approx(net(110, 100))
    # A fill on session 20 ends the same day.
    late = [flat(n, 95) for n in range(1, 20)] + [bar(20, 99, 101, 98, 99), flat(21)]
    _entry, exit_ = run(BREAKOUT, late, "E0")
    assert (exit_.session, exit_.holding) == (20, 1)


def test_e1_waits_for_the_second_target():
    bars = [
        bar(1, 99, 101, 98, 100),
        bar(2, 104, 117, 103, 115),
        bar(3, 120, 131, 119, 125),
    ]
    _entry, exit_ = run(BREAKOUT, bars, "E1")
    assert (exit_.reason, exit_.session) == ("target", 3)
    assert exit_.net == pytest.approx(net(130, 100))


def test_the_trailing_stop_moves_from_the_next_session():
    # R = 10, k = 1.0: after a close of 112 the stop is 102 from the next bar.
    bars = [
        bar(1, 99, 101, 98, 100),
        bar(2, 104, 113, 101, 112),  # low 101 is under 102, but 102 is not live yet
        bar(3, 110, 111, 101, 103),
    ]
    _entry, exit_ = run(BREAKOUT, bars, "T1")
    assert (exit_.reason, exit_.session) == ("trail", 3)
    assert exit_.net == pytest.approx(net(102, 100))
    # k = 2.0: the stop stays at the invalid price (112 - 20 = 92 > 90).
    _entry, exit_ = run(BREAKOUT, bars + [bar(4, 92, 93, 91.5, 92)], "T3")
    assert (exit_.reason, exit_.session) == ("trail", 4)
    assert exit_.net == pytest.approx(net(92, 100))


def test_trailing_ignores_the_targets_and_never_lowers_the_stop():
    bars = [
        bar(1, 99, 101, 98, 100),
        bar(2, 110, 125, 109, 120),  # through the first target: no exit
        bar(3, 115, 116, 111, 112),  # stop 110 (max close 120 - 10)
        bar(4, 111, 112, 109, 110),
    ]
    _entry, exit_ = run(BREAKOUT, bars, "T1")
    assert (exit_.reason, exit_.session) == ("trail", 4)
    assert exit_.net == pytest.approx(net(110, 100))


def test_a_time_exit_counts_the_fill_session_as_one():
    bars = [flat(1, 95), bar(2, 99, 101, 98, 100)] + [
        flat(n, 108) for n in range(3, 30)
    ]
    _entry, exit_ = run(BREAKOUT, bars, "H5")
    assert (exit_.reason, exit_.session, exit_.holding) == ("time", 6, 5)
    assert exit_.net == pytest.approx(net(108, 100))
    _entry, exit_ = run(BREAKOUT, bars, "H20")
    assert (exit_.reason, exit_.session, exit_.holding) == ("time", 21, 20)
    # The stop still applies; the target does not.
    stopped = bars[:3] + [bar(4, 95, 96, 89, 91)]
    _entry, exit_ = run(BREAKOUT, stopped, "H10")
    assert exit_.reason == "stop"
    through = bars[:3] + [bar(4, 110, 125, 109, 120)] + bars[4:]
    _entry, exit_ = run(BREAKOUT, through, "H5")
    assert exit_.reason == "time"


def test_too_few_bars_is_not_matured():
    bars = [bar(1, 99, 101, 98, 100)] + [flat(n, 108) for n in range(2, 8)]
    _entry, exit_ = run(BREAKOUT, bars, "H10")
    assert (exit_.comparable, exit_.reason) == (False, "not_matured")
    _entry, exit_ = run(BREAKOUT, bars, "E0")
    assert exit_.reason == "not_matured"


def test_a_suspension_after_the_fill_is_not_comparable():
    bars = [bar(1, 99, 101, 98, 100), flat(2, 105, suspended=True), flat(3)]
    _entry, exit_ = run(BREAKOUT, bars, "E0")
    assert (exit_.comparable, exit_.reason) == (False, "suspended")
    missing = [bar(1, 99, 101, 98, 100), flat(3, 105, missing_before=True)]
    _entry, exit_ = run(BREAKOUT, missing, "E0")
    assert exit_.reason == "suspended"


def test_a_session_locked_at_limit_down_moves_the_exit_to_the_next_open():
    locked = dict(limit_down=88.0)
    bars = [
        bar(1, 99, 101, 98, 100),
        bar(2, 88, 88, 88, 88, **locked),
        bar(3, 80, 80, 80, 80, limit_down=80.0),
        bar(4, 78, 82, 77, 81),
    ]
    _entry, exit_ = run(BREAKOUT, bars, "E0")
    assert (exit_.reason, exit_.session, exit_.limit_delayed) == ("stop", 4, True)
    assert exit_.net == pytest.approx(net(78, 100))
    # A time exit on a locked day sells at the next open too.
    held = [bar(1, 99, 101, 98, 100)] + [flat(n, 104) for n in range(2, 5)]
    held += [bar(5, 95, 95, 95, 95, limit_down=95.0), bar(6, 93, 94, 92, 93)]
    _entry, exit_ = run(BREAKOUT, held, "H5")
    assert (exit_.reason, exit_.session, exit_.holding) == ("time", 6, 6)
    assert exit_.net == pytest.approx(net(93, 100))


def test_price_limits_round_to_the_tick():
    from app.strategies import levels

    assert tool.price_limits(100.0, "stock", levels) == (90.0, 110.0)
    assert tool.price_limits(10.05, "stock", levels) == (9.05, 11.05)
    assert tool.price_limits(50.0, "etf", levels) is None


# --- the statistics and the verdict ------------------------------------------


def test_max_drawdown_of_the_running_sum():
    trades = [
        (day(1), 1, 0.05),
        (day(2), 2, -0.03),
        (day(3), 3, -0.04),
        (day(4), 4, 0.10),
    ]
    assert tool.max_drawdown(trades) == pytest.approx(0.07)
    assert tool.max_drawdown([(day(1), 1, -0.02)]) == pytest.approx(0.02)
    assert tool.max_drawdown([]) is None


def test_daily_means_average_a_signal_date_first():
    assert tool.daily_means([(day(2), 0.03), (day(1), 0.01), (day(1), 0.03)]) == [
        pytest.approx(0.02),
        pytest.approx(0.03),
    ]


def seg(days, mean, t):
    return {"days": days, "mean": mean, "t": t}


@pytest.mark.parametrize(
    ("exploration", "validation", "verdict"),
    [
        (seg(59, 0.01, 5.0), seg(80, 0.01, 5.0), "cannot_tell"),
        (seg(80, 0.01, 5.0), seg(59, 0.01, 5.0), "cannot_tell"),
        (seg(80, 0.01, 2.0), seg(80, 0.02, 2.5), "better"),
        (seg(80, -0.01, -2.0), seg(80, -0.02, -3.0), "worse"),
        (seg(80, 0.01, 1.9), seg(80, 0.02, 3.0), "no_difference"),
        (seg(80, 0.01, None), seg(80, 0.02, 3.0), "no_difference"),
        (seg(80, 0.01, 2.5), seg(80, -0.01, -0.5), "reversed"),
        (seg(80, -0.01, -2.5), seg(80, 0.01, 2.5), "reversed"),
        (seg(80, 0.01, 2.5), seg(80, 0.0, None), "reversed"),
        (seg(80, 0.01, 2.5), seg(80, 0.01, 1.0), "weak"),
        (seg(80, -0.01, -2.5), seg(80, -0.01, -1.0), "weak"),
    ],
)
def test_judge_follows_the_table(exploration, validation, verdict):
    assert tool.judge(exploration, validation) == verdict


def test_the_run_cutoff_is_the_request_keys_end():
    key = "technical-backtest:v2:2024-09-30:2026-11-13:research:breakout_v3,pullback_v4"
    assert tool.run_cutoff(key) == date(2026, 11, 13)
    with pytest.raises(ValueError):
        tool.run_cutoff("daily:2026-11-13")


# --- a run on a copy ---------------------------------------------------------------


SESSIONS = 70
RUN_ID = 7
STOCK, SPLIT, PAUSED = 1, 2, 3


def sessions() -> list[date]:
    days, current = [], date(2025, 11, 3)
    while len(days) < SESSIONS:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _signal(db, version, instrument_id, signal_date, levels, n):
    db.add(
        Signal(
            signal_key=f"backtest-{RUN_ID}-{version.name}-{instrument_id}-{n}",
            signal_date=signal_date,
            instrument_id=instrument_id,
            strategy_version_id=version.id,
            status="conditional",
            entry_type=levels.entry_type,
            breakout_price=levels.breakout_price,
            pullback_low=levels.pullback_low,
            pullback_high=levels.pullback_high,
            invalid_price=levels.invalid_price,
            target_1=levels.target_1,
            target_2=levels.target_2,
            rule_evidence_json={"actionable": True},
        )
    )


@pytest.fixture(scope="module")
def copy_db(tmp_path_factory) -> Path:
    """Three stocks and signals across the 2025-12-31 split, tracked by the pipeline.

    STOCK climbs one a day with a ±2 range and a wick of −12 every seventh
    session (stops, and stop-and-target sessions); SPLIT is the same path with a
    2:1 split on session 30; PAUSED is suspended on session 25.  Signals are
    written as a backtest run's and tracked with ``_track_backtest_signals``,
    so their T+20 settlements are the product's.
    """

    from worker.pipeline import _track_backtest_signals

    path = tmp_path_factory.mktemp("copy") / "stock.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = sessions()
    with Session(engine) as db:
        for instrument_id in (STOCK, SPLIT, PAUSED):
            db.add(
                Instrument(
                    id=instrument_id,
                    exchange="TWSE",
                    symbol=f"S{instrument_id}",
                    name=f"N{instrument_id}",
                    instrument_type="stock",
                )
            )
        for instrument_id in (STOCK, SPLIT, PAUSED):
            for index, current in enumerate(days):
                price = 100.0 + index
                s = 0.5 if instrument_id == SPLIT and index >= 30 else 1.0
                db.add(
                    MarketBar(
                        instrument_id=instrument_id,
                        trading_date=current,
                        open=(price - 0.5) * s,
                        high=(price + 2) * s,
                        low=(price - (12 if index % 7 == 0 else 2)) * s,
                        close=price * s,
                        adj_close=price * s,
                        volume=1_000_000,
                        source="test",
                        is_suspended=instrument_id == PAUSED and index == 25,
                    )
                )
        db.add(
            CorporateAction(
                instrument_id=SPLIT,
                action_date=days[30],
                action_type="split",
                details_json={"price_factor": 0.5},
                source="test",
            )
        )
        db.add(
            Event(
                instrument_id=PAUSED,
                event_date=days[40],
                event_type="suspension",
                title="halt",
                details_json={"resumed_date": days[41].isoformat()},
                source="test",
            )
        )
        breakout = StrategyVersion(
            name="breakout_v3", version="3.0.0", formula_version="test", kind="breakout"
        )
        pullback = StrategyVersion(
            name="pullback_v4", version="4.0.0", formula_version="test", kind="pullback"
        )
        db.add_all([breakout, pullback])
        db.flush()
        n = 0
        for instrument_id in (STOCK, SPLIT, PAUSED):
            for at in range(10, 60, 3):
                # Levels on the signal date's basis: SPLIT's halve with its prices.
                s = 0.5 if instrument_id == SPLIT and at >= 30 else 1.0
                close = 100.0 + at
                n += 1
                _signal(
                    db,
                    breakout,
                    instrument_id,
                    days[at],
                    tool.Levels(
                        "breakout",
                        (close + 1) * s,
                        None,
                        None,
                        (close - 4) * s,
                        (close + 7.4) * s,
                        (close + 13) * s,
                    ),
                    n,
                )
                n += 1
                _signal(
                    db,
                    pullback,
                    instrument_id,
                    days[at],
                    tool.Levels(
                        "pullback",
                        None,
                        (close - 1) * s,
                        (close + 1) * s,
                        (close - 30) * s,
                        (close + 2) * s,
                        (close + 20) * s,
                    ),
                    n,
                )
        cutoff = days[-1]
        db.add(
            IngestionRun(
                id=RUN_ID,
                run_type="backtest",
                source="test",
                run_date=cutoff,
                status="success",
                request_key=f"technical-backtest:v2:{days[10]}:{cutoff}:research:breakout_v3,pullback_v4",
            )
        )
        db.commit()
        _track_backtest_signals(db, RUN_ID, cutoff)
        db.commit()
    engine.dispose()
    return path


def measured(copy_db, tmp_path):
    copy = tool.load_copy(copy_db, RUN_ID)
    factor_of, actions, modules = tool._modules(copy_db, copy, tmp_path / "raw")
    return copy, tool.measure(copy, factor_of, actions, modules)


def test_the_product_conventions_give_the_runs_settlements_back(copy_db, tmp_path):
    copy, result = measured(copy_db, tmp_path)
    assert result["signals"] == len(copy.signals) == 102
    assert result["reproduction"] == {"checked": 102, "mismatches": 0}
    comparable = [value for value in copy.settlements.values() if value[0]]
    assert comparable and len(comparable) < len(copy.settlements)
    statuses = {value[2] for value in copy.settlements.values()}
    assert {"invalidated", "target_1_hit", "incomparable"} <= statuses
    exits = [trade["exits"]["E0"] for trade in result["trades"] if trade["exits"]]
    assert any(exit_.reason == "stop" for exit_ in exits)
    assert any(exit_.both_touched for exit_ in exits)


def test_e0_research_matches_the_product_on_a_plain_path(copy_db, tmp_path):
    _copy, result = measured(copy_db, tmp_path)
    plain = [
        trade
        for trade in result["trades"]
        if trade["instrument_id"] == STOCK
        and trade["exits"]
        and trade["exits"]["E0"].comparable
        and trade["product_net"] is not None
        and not trade["exits"]["E0"].gapped
        and not trade["exits"]["E0"].both_touched
    ]
    assert plain
    for trade in plain:
        assert trade["exits"]["E0"].net == pytest.approx(trade["product_net"], abs=1e-7)


def test_a_split_does_not_change_the_return(copy_db, tmp_path):
    _copy, result = measured(copy_db, tmp_path)
    by_key = {
        (trade["strategy"], trade["instrument_id"], trade["signal_date"]): trade
        for trade in result["trades"]
    }
    across = [
        (trade, by_key[(trade["strategy"], SPLIT, trade["signal_date"])])
        for trade in result["trades"]
        if trade["instrument_id"] == STOCK and trade["exits"]
    ]
    assert across
    for plain, split in across:
        for key in RULES:
            assert split["exits"][key].reason == plain["exits"][key].reason
            if plain["exits"][key].comparable:
                assert split["exits"][key].net == pytest.approx(
                    plain["exits"][key].net, abs=1e-6
                )


def test_tables_pair_every_alternative_with_e0(copy_db, tmp_path):
    _copy, result = measured(copy_db, tmp_path)
    tables = tool.tables(result["trades"])
    assert set(tables) == {"breakout_v3", "pullback_v4"}
    for part in tables.values():
        assert set(part["paired"]) == set(tool.ALTERNATIVES)
        for key in tool.ALTERNATIVES:
            # 18 signal days at most per segment: under MIN_DAYS.
            assert part["paired"][key]["verdict"] == "cannot_tell"
        assert part["rules"]["E0"]["all"]["n"] > 0
        assert part["conventions"]["all"]["n"] > 0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_command_writes_reports_and_not_the_database(
    copy_db, tmp_path, monkeypatch, capsys
):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path / "production"))
    before = digest(copy_db)
    out = tmp_path / "out"
    code = tool.main(
        [
            "--db",
            str(copy_db),
            "--run-id",
            str(RUN_ID),
            "--out",
            str(out),
            "--min-free-gb",
            "0",
        ]
    )
    assert code == 0
    assert digest(copy_db) == before
    assert not list(copy_db.parent.glob("stock.db-*"))
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["reproduction"]["mismatches"] == 0
    assert tables["comparisons"] == 14
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "E0 研究慣例 − E0 產品慣例" in summary and "## 樣本限制" in summary
    header = (out / "trades.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("signal_id,strategy") and "H20_net" in header
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["out"]


def test_a_mismatch_stops_before_the_alternatives(
    copy_db, tmp_path, monkeypatch, capsys
):
    changed = tmp_path / "changed" / "stock.db"
    changed.parent.mkdir()
    changed.write_bytes(copy_db.read_bytes())
    engine = create_engine(f"sqlite:///{changed}")
    with Session(engine) as db:
        row = db.scalars(
            select(SignalSettlement).where(
                SignalSettlement.horizon == 20, SignalSettlement.comparable.is_(True)
            )
        ).first()
        row.return_or_risk += 0.01
        db.commit()
    engine.dispose()
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    out = tmp_path / "out"
    code = tool.main(
        [
            "--db",
            str(changed),
            "--run-id",
            str(RUN_ID),
            "--out",
            str(out),
            "--min-free-gb",
            "0",
        ]
    )
    assert code == 4
    mismatches = json.loads((out / "mismatches.json").read_text(encoding="utf-8"))
    assert len(mismatches) == 1
    assert not (out / "summary.md").exists() and not (out / "trades.csv").exists()
    assert json.loads(capsys.readouterr().out)["stopped"]


def test_the_command_refuses_production_and_the_daily_window(
    copy_db, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("STOCK_DATA_DIR", str(copy_db.parent))
    code = tool.main(
        ["--db", str(copy_db), "--run-id", str(RUN_ID), "--out", str(tmp_path / "out")]
    )
    assert code == 2
    assert "refused" in json.loads(capsys.readouterr().out)
    assert not (tmp_path / "out").exists()
    from datetime import datetime, timezone

    late = datetime(2026, 11, 13, 14, 0, tzinfo=timezone.utc)  # 22:00 Taipei
    problems = tool.refusals(copy_db, 0.0, late)
    assert any("daily job" in problem for problem in problems)
