"""tools/research/trade_research.py: round 2 (S1～S3, R1～R2) trade by trade (#726).

The registered numbers are asserted as written in docs/spec/evidence.md
(第二輪：S1～S3、R1～R2).  The rules (AC-2) are tested on hand-made bars; the
golden fixture (AC-3) is a small research copy on a compressed calendar whose
S1 trades are computed by hand below; R1／R2 are compared with the product's
own signal writer (``worker.pipeline._generate_signals``) on a fixture with
every edge case of decision 6882515208 (AC-4); the gate and the shared
ledger follow ``explore_research``.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import random
import shutil
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    Base,
    ChipSnapshot,
    CorporateAction,
    IngestionRun,
    Instrument,
    MarginList,
    MarketBar,
    MonthlyRevenue,
    RawPayload,
    Signal,
    StrategyVersion,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/726#issuecomment-1"


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
er = _tool("exit_research")
ex = _tool("explore_research")
tool = _tool("trade_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}

BUY = 1.0005
SELL = 0.9995
COST = 0.00585


def net(sold: float, bought: float) -> float:
    return sold * SELL / (bought * BUY) - 1.0 - COST


# --- the registration, as written ------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == ["S1", "S2", "S3", "R1", "R2"]
    zone = {
        name: (
            s["market_filter"],
            s["top"],
            s["entry_days"],
            s["zone_atr"],
            s["stop_atr"],
            s["target_atr"],
            s["hold"],
        )
        for name, s in h.items()
        if s["kind"] == "zone"
    }
    assert zone == {
        "S1": (True, 10, 3, 1.0, 2.0, 4.0, 20),
        "S2": (False, 10, 3, 1.0, 2.0, 4.0, 20),
        "S3": (True, 10, 3, 1.0, 1.0, 4.0, 20),  # R stays 2×ATR14: the target too
    }
    assert h["R1"]["strategy"] == ("breakout_v3", "group")
    assert h["R2"]["strategy"] == ("pullback_v4", "group")
    assert {h[n]["entry_days"] for n in ("R1", "R2")} == {20}
    assert {h[n]["hold"] for n in ("R1", "R2")} == {20}
    assert {s["start"] for s in h.values()} == {("session", date(2014, 12, 1), 20)}
    assert tool.SCORE_KEYS == ("trust_buy_days", "institutional_flow_20")
    assert tool.ATR_WINDOW == 14 and tool.MA_WINDOW == 60


def test_the_segments_thresholds_and_counts_are_the_decision():
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == {"exploration": 500, "validation": 250}
    assert (tool.MIN_T, tool.MIN_DAYS, tool.OVERLAP) == (2.0, 60, 20)
    assert (tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (2, 5, 13)
    assert ex.validation_min_t(tool.CUMULATIVE) == 2.0
    assert (tool.SLIPPAGE, tool.COST_BPS) == (5.0 / 10_000.0, 58.5)
    assert tool.REGISTRATION_COMMIT == "64a5efe1" and tool.DESIGN == "726"
    assert tool.GROUP_PLACEHOLDER == 0.0


def test_the_r_rules_are_the_ablations_without_the_group_condition():
    from app.strategies.ablation import ablated_strategy

    for name, base in (("R1", "breakout_v3"), ("R2", "pullback_v4")):
        strategy = tool.strategy_of(name)
        assert strategy.config == ablated_strategy(base, "group").config
        assert "group_relative_strength" not in strategy.config["confirmations"]


def test_the_definitions_hash_covers_the_r_configurations(monkeypatch):
    before = tool.definitions_sha256()
    original = tool.strategy_of

    def changed(name):
        strategy = original(name)
        strategy.config = {**strategy.config, "extra": 1}
        return strategy

    monkeypatch.setattr(tool, "strategy_of", changed)
    assert tool.definitions_sha256() != before


# --- the rules on hand-made bars (AC-2) -----------------------------------------

D0 = date(2020, 1, 6)


def bar(k, o, h, low, c, **extra):
    return er.Bar(D0 + timedelta(days=k), o, h, low, c, **extra)


def flat(k, price=100.0):
    return bar(k, price, price + 1, price - 1, price)


def test_the_zone_fills_at_the_upper_edge_or_a_lower_open():
    above = [bar(0, 101.0, 102.0, 99.5, 100.0)]
    entry, below = tool.enter_zone(above, 100.0, 98.0, 3)
    assert (entry.session, entry.price, below) == (1, pytest.approx(100.0 * BUY), False)
    inside = [bar(0, 99.0, 100.5, 98.5, 99.5)]
    entry, below = tool.enter_zone(inside, 100.0, 98.0, 3)
    assert entry.price == pytest.approx(99.0 * BUY) and not below
    gap = [bar(0, 97.0, 98.0, 96.5, 97.5)]  # opens under the lower edge
    entry, below = tool.enter_zone(gap, 100.0, 98.0, 3)
    assert entry.price == pytest.approx(97.0 * BUY) and below


def test_the_zone_is_abandoned_after_three_sessions():
    high = [bar(k, 101.0, 102.0, 100.5, 101.0) for k in range(3)] + [flat(3)]
    entry, _ = tool.enter_zone(high, 100.0, 98.0, 3)
    assert (entry.session, entry.reason) == (None, "not_triggered")
    # a suspended session counts in the three and does not extend them
    halted = [
        bar(0, 101.0, 102.0, 100.5, 101.0),
        er.Bar(D0, 0.0, 0.0, 0.0, 0.0, suspended=True),
        bar(2, 101.0, 102.0, 100.5, 101.0),
        flat(3),
    ]
    assert tool.enter_zone(halted, 100.0, 98.0, 3)[0].reason == "not_triggered"


def test_the_zone_does_not_fill_a_session_locked_at_limit_up():
    locked = bar(0, 99.0, 99.0, 99.0, 99.0, limit_up=99.0)
    entry, _ = tool.enter_zone([locked, flat(1)], 100.0, 98.0, 3)
    assert (entry.session, entry.limit_blocked) == (2, 1)
    entry, _ = tool.enter_zone([locked] * 3 + [flat(3)], 100.0, 98.0, 3)
    assert (entry.reason, entry.limit_blocked) == ("not_triggered", 3)


def filled(price=100.0, session=1):
    return er.Entry(session, price * BUY, "filled")


def test_settle_stops_at_the_stop_or_the_open_below_it():
    bars = [flat(0), bar(1, 97.0, 97.5, 95.0, 96.0), *map(flat, range(2, 25))]
    out = tool.settle(bars, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.holding, out.gapped) == (
        "stop",
        pytest.approx(96.0 * SELL),
        2,
        False,
    )
    assert out.net == pytest.approx(net(96.0, 100.0))
    gap = [flat(0), bar(1, 94.0, 95.0, 93.0, 94.5), *map(flat, range(2, 25))]
    out = tool.settle(gap, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.gapped) == (
        "stop",
        pytest.approx(94.0 * SELL),
        True,
    )


def test_settle_takes_the_target_and_the_stop_first_when_both_touch():
    bars = [flat(0), bar(1, 104.0, 109.0, 103.0, 108.5), *map(flat, range(2, 25))]
    out = tool.settle(bars, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price) == ("target", pytest.approx(108.0 * SELL))
    both = [flat(0), bar(1, 100.0, 109.0, 95.0, 100.0), *map(flat, range(2, 25))]
    out = tool.settle(both, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.both_touched) == (
        "stop",
        pytest.approx(96.0 * SELL),
        True,
    )


def test_settle_checks_the_fill_session_at_the_levels():
    day = [bar(0, 100.0, 109.0, 99.0, 108.0), *map(flat, range(1, 25))]
    out = tool.settle(day, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.holding, out.gapped) == (
        "target",
        pytest.approx(108.0 * SELL),
        1,
        False,
    )


def test_settle_holds_to_the_limit_and_closes():
    bars = [*map(flat, range(19)), bar(19, 100.0, 101.0, 99.5, 101.0), flat(20)]
    out = tool.settle(bars, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.holding) == (
        "time",
        pytest.approx(101.0 * SELL),
        20,
    )


def test_settle_delays_a_sale_locked_at_limit_down():
    locked = bar(1, 90.0, 90.0, 90.0, 90.0, limit_down=90.0)
    bars = [flat(0), locked, bar(2, 88.0, 89.0, 87.0, 88.0), *map(flat, range(3, 25))]
    out = tool.settle(bars, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.holding, out.limit_delayed) == (
        "stop",
        pytest.approx(88.0 * SELL),
        3,
        True,
    )


def halted(k):
    return er.Bar(D0 + timedelta(days=k), 100.0, 100.0, 100.0, 100.0, suspended=True)


def test_settle_moves_a_due_sale_past_a_suspension():
    bars = [
        *map(flat, range(19)),
        halted(19),
        halted(20),
        bar(21, 99.0, 100.0, 98.0, 99.5),
    ]
    done = tool.settle(bars, filled(), 96.0, 108.0, 19)
    assert (done.exit.reason, done.exit.price, done.exit.holding) == (
        "time",
        pytest.approx(99.0 * SELL),
        22,
    )
    assert done.suspension_delayed


def test_settle_does_not_check_a_suspended_session_and_gaps_on_the_resume():
    bars = [
        flat(0),
        halted(1),
        bar(2, 93.0, 94.0, 92.0, 93.5),
        *map(flat, range(3, 25)),
    ]
    done = tool.settle(bars, filled(), 96.0, 108.0, 19)
    assert (done.exit.reason, done.exit.price, done.exit.gapped) == (
        "stop",
        pytest.approx(93.0 * SELL),
        True,
    )
    assert not done.suspension_delayed


@pytest.mark.parametrize("status", ["delisted", "transferred"])
def test_settle_sells_a_delisted_or_transferred_stock_at_its_last_close(status):
    bars = [flat(0), bar(1, 99.0, 100.0, 98.0, 98.5), halted(2), halted(3)]
    out = tool.settle(bars, filled(), 96.0, 108.0, 19, ended=(1, status)).exit
    assert (out.reason, out.price, out.holding) == (
        status,
        pytest.approx(98.5 * SELL),
        2,
    )


def test_settle_takes_the_stop_when_the_fill_session_touches_both():
    day = [bar(0, 100.0, 109.0, 95.0, 100.0), *map(flat, range(1, 25))]
    out = tool.settle(day, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.holding, out.both_touched, out.gapped) == (
        "stop",
        pytest.approx(96.0 * SELL),
        1,
        True,
        False,
    )


def test_settle_settles_at_the_segment_end():
    bars = [*map(flat, range(5)), bar(5, 100.0, 101.0, 99.0, 100.5)]
    out = tool.settle(bars, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.holding) == (
        "segment_end",
        pytest.approx(100.5 * SELL),
        6,
    )


class Bars(list):
    """A list with TradeBars.last_close: the last bar with a close."""

    def last_close(self, key):
        for k in range(key, -1, -1):
            if self[k].close == self[k].close and self[k].close > 0:
                return k, self[k].close
        return None


def test_settle_at_a_suspended_segment_end_takes_the_last_close():
    bars = Bars(
        [
            flat(0),
            bar(1, 100.0, 101.0, 99.0, 100.7),
            er.Bar(D0, *[lib.NAN] * 4, suspended=True),
        ]
    )
    out = tool.settle(bars, filled(), 96.0, 108.0, 19).exit
    assert (out.reason, out.price, out.session) == (
        "segment_end",
        pytest.approx(100.7 * SELL),
        3,
    )


def random_bars(seed: int, count: int = 30) -> list:
    rng = random.Random(seed)
    price, out = 100.0, []
    for k in range(count):
        o = price * (1 + rng.uniform(-0.03, 0.03))
        c = o * (1 + rng.uniform(-0.04, 0.04))
        h, low = (
            max(o, c) * (1 + rng.uniform(0, 0.02)),
            min(o, c) * (1 - rng.uniform(0, 0.02)),
        )
        locked = rng.random() < 0.08
        out.append(bar(k, o, h, low, c, limit_down=h if locked else None))
        price = c
    return out


def test_settle_is_exit_trade_without_suspensions_delistings_and_the_segment_end():
    """docs 第二輪「和 #673 的 E0 只差三點」: elsewhere it is the same exit."""

    e0 = next(rule for rule in er.RULES if rule.key == "E0")
    h20 = next(rule for rule in er.RULES if rule.key == "H20")
    compared = 0
    for seed in range(400):
        bars = random_bars(seed)
        levels = er.Levels("breakout", 100.5, None, None, 95.0, 106.0, 110.0)
        entry = er.enter(levels, bars)
        if entry.session is None:
            continue
        for rule, target, last in (
            (e0, levels.target_1, er.WINDOW - 1),
            (h20, None, entry.session - 1 + 19),
        ):
            mine = tool.settle(bars, entry, levels.invalid_price, target, last).exit
            theirs = er.exit_trade(levels, bars, entry, rule)
            if not theirs.comparable or mine.reason == "segment_end":
                continue  # not matured: the segment's end is a difference
            compared += 1
            reason = {"window_end": "time"}.get(theirs.reason, theirs.reason)
            assert (mine.reason, mine.session, mine.trading_date) == (
                reason,
                theirs.session,
                theirs.trading_date,
            ), seed
            assert mine.price == pytest.approx(theirs.price, abs=1e-12)
            assert mine.net == pytest.approx(theirs.net, abs=1e-12)
            assert (mine.both_touched, mine.gapped, mine.limit_delayed) == (
                theirs.both_touched,
                theirs.gapped,
                theirs.limit_delayed,
            )
    assert compared > 300


def test_the_rule_entry_reports_the_session_it_ends_on():
    levels = er.Levels("breakout", 103.0, None, None, 95.0, 106.0, 110.0)
    bars = [
        flat(0),
        flat(1),
        bar(2, 107.0, 108.0, 106.5, 107.5),
        *map(flat, range(3, 25)),
    ]
    entry, ends = tool.rule_entry(levels, bars)
    assert (entry.reason, ends) == ("gap_above_target", 2)
    entry, ends = tool.rule_entry(levels, [*map(flat, range(25))])
    assert (entry.reason, ends) == ("not_triggered", 19)
    entry, ends = tool.rule_entry(levels, [*map(flat, range(4))])
    assert (entry.reason, ends) == ("not_triggered", 3)  # the segment ends first


def index_ctx(closes: dict[date, float]):
    panel = SimpleNamespace(index_close=closes)
    return SimpleNamespace(panel=panel, index_days=sorted(closes))


def test_the_market_filter_is_the_close_above_its_ma60():
    days = [D0 + timedelta(days=k) for k in range(70)]
    closes = {day: 10_000.0 for day in days}
    ctx = index_ctx(closes)
    assert tool.market_filter(ctx, days[65]) is False  # equal is not above
    closes[days[66]] = 10_050.0
    assert tool.market_filter(index_ctx(closes), days[66]) is True
    assert tool.market_filter(index_ctx(closes), days[58]) is None  # 59 closes
    assert tool.market_filter(index_ctx(closes), D0 + timedelta(days=100)) is None


def state_with(trades):
    state = tool.State("S1", REGISTERED["S1"])
    state.trades = trades
    state.signal_days = len({trade["signal_date"] for trade in trades})
    return state


def trade(day, value, excess, taiex=None, reason="time", **extra):
    return {
        "signal_date": day,
        "net": value,
        "excess": excess,
        "taiex_excess": taiex,
        "exit_reason": reason,
        "entry_reason": "filled" if value is not None else "not_triggered",
        "fill_date": day,
        "exit_date": day,
        "holding": 5,
        "both_touched": False,
        "gapped": False,
        "limit_delayed": False,
        "suspension_delayed": False,
        "limit_blocked": 0,
        "population_unbought": 0,
        **extra,
    }


def test_the_signal_dates_are_averaged_before_the_mean_and_the_t():
    d1, d2, d3 = D0, D0 + timedelta(days=1), D0 + timedelta(days=2)
    trades = [
        trade(d1, 0.02, 0.01),
        trade(d1, 0.04, 0.03),
        trade(d2, -0.01, -0.02),
        trade(d3, 0.03, 0.04),
        trade(d3, None, None),  # abandoned: no day of its own
    ]
    numbers = tool.stats(state_with(trades))
    days = [0.02, -0.02, 0.04]
    assert numbers["excess"]["days"] == 3
    assert numbers["excess"]["mean"] == pytest.approx(statistics.fmean(days))
    assert numbers["excess"]["t"] == lib.t_stat(days, overlap=20)
    assert numbers["absolute"]["mean"] == pytest.approx(
        statistics.fmean([0.03, -0.01, 0.03])
    )
    assert numbers["abandon_rate"] == pytest.approx(0.2)
    assert numbers["win_rate"] == pytest.approx(0.75)


def test_a_zero_return_is_neither_won_nor_lost():
    numbers = tool.stats(
        state_with([trade(D0, 0.0, 0.0), trade(D0, 0.01, 0.0), trade(D0, -0.01, 0.0)])
    )
    assert (numbers["zero"], numbers["won"], numbers["lost"]) == (1, 1, 1)
    assert numbers["win_rate"] == pytest.approx(1 / 3)


# --- the golden fixture (AC-3) ---------------------------------------------------

SESSIONS = 130
INDEX_ID = 90
A, B, C, D, E, F = 1, 2, 3, 4, 5, 6
# G is transferred (its last bar on its exchange at 92), H is suspended on the
# fill session 86, J is suspended on 87 (A's exit) and resumes on 88.
G, H, J = 7, 8, 9
GOLDEN = (A, B, C, D, E, F, G, H, J)
PICKED = (A, B, C, D, E, G)  # revenue up; F, H and J are only in the population
T = 85  # the one session the market filter passes
DELISTED_LAST = 90
TRANSFERRED_LAST = 92
STATUS = {E: "delisted", G: "transferred"}
HALTED_AT = {H: 86, J: 87}


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def days_() -> list[date]:
    return weekdays(date(2014, 1, 1), SESSIONS)


# (o, h, l, c) per stock and session; every other bar is flat at 100 ± 1.
PRICES = {
    A: {86: (99.0, 100.5, 98.5, 99.5), 87: (96.0, 96.5, 94.0, 95.0)},
    B: {86: (100.5, 101.0, 99.5, 100.8), 88: (104.0, 109.0, 103.5, 108.5)},
    C: {86: (100.0, 100.5, 99.0, 100.0), 105: (100.0, 101.5, 99.5, 101.0)},
    D: {k: (101.0, 102.0, 100.5, 101.0) for k in (86, 87, 88)},
    E: {
        86: (97.0, 98.0, 96.5, 97.5),
        **{k: (97.5, 98.0, 97.0, 97.5) for k in range(87, DELISTED_LAST + 1)},
    },
    G: {86: (99.5, 100.0, 99.0, 99.5)},
    H: {86: (100.0, 100.0, 100.0, 100.0)},
    J: {87: (100.0, 100.0, 100.0, 100.0), 88: (102.0, 103.0, 101.0, 102.5)},
}


def ohlc(i: int, t: int) -> tuple[float, float, float, float]:
    return PRICES.get(i, {}).get(t, (100.0, 101.0, 99.0, 100.0))


def build_golden(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = days_()
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE",
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": STATUS.get(i, "active"),
                }
                for i in GOLDEN
            ]
            + [
                {
                    "id": INDEX_ID,
                    "exchange": "TWSE",
                    "symbol": "TAIEX",
                    "name": "加權指數",
                    "instrument_type": "index",
                    "status": "active",
                }
            ],
        )
        bars, chips = [], []
        for i in GOLDEN:
            for t, day in enumerate(days):
                if (i == E and t > DELISTED_LAST) or (i == G and t > TRANSFERRED_LAST):
                    break
                halted = HALTED_AT.get(i) == t
                o, h, low, c = ohlc(i, t)
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": o,
                        "high": h,
                        "low": low,
                        "close": c,
                        "adj_close": c,
                        "volume": 0 if halted else 2_000_000,
                        "turnover": c * 2_000_000,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": halted,
                    }
                )
                # trust_buy_days at any T: 5, 4, 3, 2, 1 for A..E, 0 for F
                trust = 1000.0 if t % 5 < (6 - i) else -1000.0
                chips.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "foreign_buy": 0.0,
                        "trust_buy": trust,
                        "dealer_buy": 0.0,
                        "margin_balance": 100_000.0,
                    }
                )
        for t, day in enumerate(days):
            close = 10_100.0 if t == T else 10_000.0
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adj_close": close,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(ChipSnapshot), chips)
        db.execute(
            insert(MonthlyRevenue),
            [
                {
                    "instrument_id": i,
                    "revenue_month": date(2014, 4, 1),
                    "revenue": 110.0 if i in PICKED else 90.0,
                    "prior_year_revenue": 100.0,
                    "announcement_date": days[60],
                    "source": "test",
                    "raw_payload_id": 1,
                    "data_as_of": "test",
                }
                for i in GOLDEN
            ],
        )
        # margin lists before and after the exploration's end (days[110])
        db.execute(
            insert(MarginList),
            [
                {
                    "exchange": "TWSE",
                    "trading_date": days[k],
                    "source": "test",
                    "endpoint": "test",
                    "data_as_of": days[k].isoformat(),
                    "collected_at": datetime(2014, 1, 1),
                    "raw_payload_id": 1,
                    "member_count": 0,
                    "members_json": {},
                }
                for k in (100, 120)
            ],
        )
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def golden_db(tmp_path_factory) -> Path:
    return build_golden(tmp_path_factory.mktemp("trade") / "stock.db")


def compressed(monkeypatch, tmp_path: Path) -> None:
    """The segments, floors and the start moved into the fixture's 130 sessions."""

    days = days_()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[110]),
            "validation": (days[111], days[129]),
            "used": (days[129], days[129]),
        },
    )
    floors = {"exploration": 20, "validation": 10}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(tool, "MIN_DAYS", 1)
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], 80)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path, name: str = "copy") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    return Path(shutil.copy(db, folder / "stock.db"))


APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def explore(db: Path, out: Path, hypotheses: str | None = "S1") -> int:
    chosen = [] if hypotheses is None else ["--hypotheses", hypotheses]
    return one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "exploration",
                "--min-free-gb",
                "0",
                *chosen,
            ]
        )  # fmt: skip
    )


def validate(db: Path, out: Path, report: Path, sha: str | None = None, url=URL) -> int:
    sha = sha if sha is not None else ex.file_sha256(report)
    return one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "validation",
                "--min-free-gb",
                "0",
                "--exploration-report",
                str(report),
                "--exploration-sha256",
                sha,
                "--exploration-url",
                url,
            ]
        )  # fmt: skip
    )


@pytest.fixture
def explored(golden_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path)
    db = copy_of(golden_db, tmp_path)
    out = tmp_path / "exploration"
    assert explore(db, out) == 0
    return db, out


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def by_hand() -> dict[str, dict]:
    """S1's trades on the fixture, from the price table above.

    The population of T is every stock: H cannot be bought on the fill
    session (suspended) and is left out; J cannot be sold on 87 (suspended)
    and sells at 88's open; E and G have no bar after 90 and 92 and sell at
    their last close.
    """

    members = [i for i in GOLDEN if i != H]
    buy = {i: ohlc(i, 86)[0] for i in members}

    def sold(i: int, x: int) -> float:
        if i == E:
            return ohlc(i, min(x, DELISTED_LAST))[3]
        if i == G:
            return ohlc(i, min(x, TRANSFERRED_LAST))[3]
        if HALTED_AT.get(i) == x:
            return ohlc(i, x + 1)[0]  # the next session's open
        return ohlc(i, x)[3]

    def population(x: int) -> float:
        return statistics.fmean(net(sold(i, x), buy[i]) for i in members)

    taiex = 10_000.0 / 10_100.0 - 1.0
    rows = {
        "S1": ("stop", 87, net(96.0 - 1.0, 99.0), 2, 99.0, 95.0),  # stop 99 − 4 = 95
        "S2": ("target", 88, net(108.0, 100.0), 3, 100.0, 108.0),
        "S3": ("time", 105, net(101.0, 100.0), 20, 100.0, 101.0),
        "S5": ("delisted", DELISTED_LAST, net(97.5, 97.0), 5, 97.0, 97.5),
        "S7": ("transferred", TRANSFERRED_LAST, net(100.0, 99.5), 7, 99.5, 100.0),
    }
    out = {}
    for symbol, (reason, x, value, holding, fill, price) in rows.items():
        base = population(x)
        out[symbol] = {
            "exit_reason": reason,
            "exit_day": x,
            "net": value,
            "holding": holding,
            "fill_price": fill,
            "exit_price": price,
            "population": base,
            "population_members": len(members),
            "excess": value - base,
            "taiex_excess": value - taiex,
        }
    return out


FILLED = ("S1", "S2", "S3", "S5", "S7")


def test_the_golden_s1_trades_are_the_hand_computed_ones(explored):
    db, out = explored
    days = days_()
    trades = {row["symbol"]: row for row in read_csv(out / "S1" / "trades.csv")}
    assert set(trades) == {"S1", "S2", "S3", "S4", "S5", "S7"}
    assert {row["signal_date"] for row in trades.values()} == {days[T].isoformat()}
    assert [trades[s]["rank"] for s in ("S1", "S2", "S3", "S4", "S5", "S7")] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]
    expected = by_hand()
    # the two population rules are not idle: J's sale moved, H left out
    assert expected["S1"]["population"] != pytest.approx(
        statistics.fmean(net(ohlc(i, 87)[3], ohlc(i, 86)[0]) for i in GOLDEN if i != H)
    )
    for symbol, want in expected.items():
        row = trades[symbol]
        assert row["entry_reason"] == "filled"
        assert row["fill_date"] == days[86].isoformat()
        assert row["exit_date"] == days[want["exit_day"]].isoformat()
        assert row["exit_reason"] == want["exit_reason"]
        assert int(row["holding"]) == want["holding"]
        assert int(row["population_members"]) == want["population_members"]
        assert row["population_unbought"] == "1"  # H, suspended on 86
        for key in (
            "fill_price",
            "exit_price",
            "net",
            "population",
            "excess",
            "taiex_excess",
        ):
            assert float(row[key]) == pytest.approx(want[key], abs=1e-9), (symbol, key)
        assert float(row["atr14"]) == pytest.approx(2.0)
        assert float(row["zone_high"]) == pytest.approx(100.0)
        assert float(row["zone_low"]) == pytest.approx(98.0)
    assert float(trades["S1"]["stop"]) == pytest.approx(95.0)
    assert float(trades["S1"]["target"]) == pytest.approx(107.0)
    assert trades["S5"]["below_lower"] == "1"  # opened at 97 under 98
    assert trades["S4"]["entry_reason"] == "not_triggered"
    assert trades["S4"]["abandoned_date"] == days[88].isoformat()
    assert trades["S4"]["net"] == ""
    # the day series and the listed numbers
    tables = read_json(out / "S1" / "tables.json")
    nets = [expected[s]["net"] for s in FILLED]
    excesses = [expected[s]["excess"] for s in FILLED]
    assert tables["absolute"]["mean"] == pytest.approx(statistics.fmean(nets))
    assert tables["excess"]["mean"] == pytest.approx(statistics.fmean(excesses))
    assert tables["excess"]["days"] == 1 and tables["excess"]["t"] is None
    assert (tables["signals"], tables["trades"], tables["trade_days"]) == (6, 5, 1)
    won = [value for value in nets if value > 0]
    lost = [value for value in nets if value < 0]
    assert (len(won), len(lost)) == (2, 3)
    assert tables["win_rate"] == pytest.approx(0.4)
    assert tables["won_mean"] == pytest.approx(statistics.fmean(won))
    assert tables["lost_mean"] == pytest.approx(statistics.fmean(lost))
    assert tables["holding_mean"] == pytest.approx(statistics.fmean([2, 3, 20, 5, 7]))
    assert tables["abandon_rate"] == pytest.approx(1 / 6)
    assert tables["abandon_reasons"] == {"not_triggered": 1}
    assert tables["exit_share"] == {
        "stop": 0.2,
        "target": 0.2,
        "time": 0.2,
        "segment_end": 0.0,
        "delisted": 0.2,
        "transferred": 0.2,
    }
    assert tables["exits"]["transferred"] == 1
    assert tables["below_lower"] == 1
    assert tables["population_unbought"] == 5  # H in each of the five (T, e, x)
    assert (tables["filter_blocked_days"], tables["filter_missing_days"]) == (30, 0)
    assert tables["window"]["days"] == 31
    day = read_csv(out / "S1" / "days.csv")
    assert [row["signal_date"] for row in day] == [days[T].isoformat()]
    assert float(day[0]["excess"]) == pytest.approx(statistics.fmean(excesses))


def test_the_report_lists_the_taiex_excess_first_and_hashes_the_json(explored):
    _db, out = explored
    text = (out / "explore.md").read_text(encoding="utf-8")
    sha = ex.file_sha256(out / "explore.json")
    assert text.splitlines()[0] == f"explore.json 的 sha256：`{sha}`"
    table = text[text.index("## 判定") :]
    assert table.index("對加權指數超額") < table.index("對母體超額")
    summary = (out / "S1" / "summary.md").read_text(encoding="utf-8")
    assert summary.index("對加權指數") < summary.index("對母體")
    report = read_json(out / "explore.json")
    assert (report["design"], report["tool"], report["segment"]) == (
        "726",
        "trade_research",
        "exploration",
    )
    assert report["definitions_sha256"] == tool.definitions_sha256()
    assert report["selected"] == ["S1"]
    assert report["hypotheses"]["S1"]["verdict"] == ex.EXPLORATION_FAILED  # t is None


def test_the_exploration_reads_nothing_after_its_end(golden_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path)
    seen = []
    original = tool.load

    def spy(db, start, end, raw_dir):
        seen.append(end)
        return original(db, start, end, raw_dir)

    monkeypatch.setattr(tool, "load", spy)
    assert explore(copy_of(golden_db, tmp_path), tmp_path / "out") == 0
    assert seen == [days_()[110]]
    ctx = original(golden_db, date(2013, 1, 1), days_()[110], tmp_path / "raw")
    assert max(ctx.panel.sessions) == days_()[110]
    # the margin list of days[120] is after the end: not read
    assert sorted(day for _exchange, day in ctx.margin_lists) == [days_()[100]]


def test_occupied_stocks_are_skipped_and_the_next_one_fills_in(
    golden_db, tmp_path, monkeypatch
):
    compressed(monkeypatch, tmp_path)
    hypotheses = dict(tool.HYPOTHESES)
    hypotheses["S2"] = {**hypotheses["S2"], "top": 2}
    monkeypatch.setattr(tool, "HYPOTHESES", hypotheses)
    out = tmp_path / "s2"
    assert explore(copy_of(golden_db, tmp_path), out, "S2") == 0
    rows = read_csv(out / "S2" / "trades.csv")
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], []).append(row)
    exit_day_signals = 0
    for own in by_symbol.values():
        for before, after in zip(own, own[1:]):
            end = before["exit_date"] or before["abandoned_date"]
            if before["exit_date"]:
                assert after["signal_date"] >= end  # the exit day's close counts
                exit_day_signals += after["signal_date"] == end
            else:
                assert after["signal_date"] > end  # the abandonment day is occupied
    assert exit_day_signals > 0
    days = days_()
    first = [row for row in rows if row["signal_date"] == days[79].isoformat()]
    assert [row["symbol"] for row in first] == ["S1", "S2"]
    later = [row for row in rows if row["signal_date"] == days[80].isoformat()]
    # S1 and S2 are occupied on the next day: the third and fourth fill in
    assert [row["symbol"] for row in later] == ["S3", "S4"]
    assert all(row["rank"] in ("1", "2") for row in rows)


# --- the gate and the ledger (AC-4) ----------------------------------------------


def refused(capsys) -> list[str]:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]


def test_the_exploration_runs_once_and_records_it(explored, capsys):
    db, out = explored
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["segment"], e["version"]) for e in entries
    ] == [("S1", "trade_research", "exploration", 1)]
    assert entries[0]["report_sha256"] == ex.file_sha256(out / "explore.json")
    assert read_json(out / "ledger-entries.json")["entries"] == entries
    capsys.readouterr()
    assert explore(db, out.parent / "again") == 2
    assert any("already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_exploration_needs_registered_hypotheses(
    golden_db, tmp_path, monkeypatch, capsys
):
    compressed(monkeypatch, tmp_path)
    db = copy_of(golden_db, tmp_path)
    assert explore(db, tmp_path / "o1", None) == 2
    assert refused(capsys) == ["--segment exploration needs --hypotheses (e.g. S1,S2)"]
    assert explore(db, tmp_path / "o2", "S1,X1,S1") == 2
    problems = refused(capsys)
    assert any("X1 not registered" in line for line in problems)
    assert any("S1 given more than once" in line for line in problems)


def passed_report(out: Path, names=("S1",)) -> Path:
    """An exploration report of this tool in which ``names`` passed."""

    out.mkdir(parents=True, exist_ok=True)
    path = out / "explore.json"
    body = {
        "design": tool.DESIGN,
        "segment": "exploration",
        "definitions_sha256": tool.definitions_sha256(),
        "hypotheses": {name: {"verdict": ex.EXPLORATION_PASSED} for name in names},
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_validation_refuses_before_the_exploration_report_is_public(
    explored, tmp_path, capsys
):
    db, out = explored
    report = passed_report(tmp_path / "passed")
    # not the published report (another sha), not a public link, no report at all
    assert validate(db, tmp_path / "v1", report, sha="0" * 64) == 2
    assert any("not the published one" in line for line in refused(capsys))
    assert validate(db, tmp_path / "v2", report, url="https://example.com/x") == 2
    assert any("not an Issue comment" in line for line in refused(capsys))
    assert (
        one_process(
            lambda: tool.main(
                [
                    "--db",
                    str(db),
                    "--out",
                    str(tmp_path / "v3"),
                    "--segment",
                    "validation",
                    "--min-free-gb",
                    "0",
                ]
            )  # fmt: skip
        )
        == 2
    )
    assert any("needs --exploration-report" in line for line in refused(capsys))
    # the real exploration report passed nothing
    assert validate(db, tmp_path / "v4", out / "explore.json") == 2
    assert any("nothing to validate" in line for line in refused(capsys))
    # an explore_research report is not this tool's
    other = tmp_path / "other.json"
    other.write_text(
        json.dumps(
            {
                "design": ex.DESIGN,
                "segment": "exploration",
                "definitions_sha256": ex.definitions_sha256(),
                "hypotheses": {"X1": {"verdict": ex.EXPLORATION_PASSED}},
            }
        ),
        encoding="utf-8",
    )
    assert validate(db, tmp_path / "v5", other) == 2
    assert any(
        "not an exploration report of this tool" in line for line in refused(capsys)
    )
    for name in ("v1", "v2", "v3", "v4", "v5"):
        assert not (tmp_path / name).exists()
    assert [e["segment"] for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)] == [
        "exploration"
    ]


def test_the_validation_needs_the_research_marker(
    golden_db, tmp_path, monkeypatch, capsys
):
    compressed(monkeypatch, tmp_path)
    folder = tmp_path / "bare"
    folder.mkdir()
    db = Path(shutil.copy(golden_db, folder / "stock.db"))
    report = passed_report(tmp_path / "passed")
    assert validate(db, tmp_path / "v", report) == 2
    assert any("research marker" in line for line in refused(capsys))


def test_the_validation_runs_once(explored, tmp_path, capsys):
    db, _out = explored
    report = passed_report(tmp_path / "passed")
    assert validate(db, tmp_path / "v", report) == 0
    entries = [
        e
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert [(e["hypothesis"], e["tool"], e["status"]) for e in entries] == [
        ("S1", "trade_research", "finished")
    ]
    result = read_json(tmp_path / "v" / "explore.json")
    assert result["segment"] == "validation" and "S1" in result["hypotheses"]
    capsys.readouterr()
    assert validate(db, tmp_path / "again", report) == 2
    assert any("the validation runs once" in line for line in refused(capsys))


def test_the_explore_research_rows_of_the_shared_ledger_do_not_block(
    explored, tmp_path
):
    """Condition 4: X rows in the shared ledgers leave this tool's checks alone."""

    db, _out = explored
    ledger = db.parent / ex.LEDGER_NAME
    rows = ex.read_ledger(ledger)
    x_rows = [
        {"hypothesis": "X3", "segment": "exploration", "version": ex.VERSION},
        {"hypothesis": "X3", "segment": "validation", "version": ex.VERSION},
        {"hypothesis": "X1"},  # an old row without a segment counts as a validation
    ]
    ex.write_ledger(ledger, rows + x_rows)
    ex.write_ledger(ex.REPO_LEDGER, x_rows)
    problems, names = ex.exploration_problems(
        db, "S2,R1", tool.HYPOTHESES, tool.VERSION
    )
    assert (problems, names) == ([], ["S2", "R1"])
    problems, _names = ex.exploration_problems(db, "S1", tool.HYPOTHESES, tool.VERSION)
    assert len(problems) == 1 and "S1 already in" in problems[0]  # its own row still
    report = passed_report(tmp_path / "passed")
    problems, passed, _ = ex.validation_problems(
        db,
        str(report),
        ex.file_sha256(report),
        URL,
        tool.HYPOTHESES,
        tool.DESIGN,
        tool.definitions_sha256(),
    )
    assert (problems, passed) == ([], ["S1"])


# --- R1／R2 against the product (AC-4, condition 3) ------------------------------

RULE_SESSIONS = 150
EVAL_FROM = 90  # the signal dates compared: sessions 90..149
STOCKS = list(range(1, 41))
NOT_APPLICABLE = 41  # no margin balance; the lists do not hold it
ZERO_BASE = 42  # a margin balance of 0 five sessions before
CHIP_GAP = 43  # one session without the trust figure
HALTED = 44  # suspended sessions in the windows
IPO = 45  # 40 bars only
SPLIT = 46  # a split inside the windows
DIVIDEND = 47  # a cash dividend inside the windows (no reference price: the fallback)
EDGES = [NOT_APPLICABLE, ZERO_BASE, CHIP_GAP, HALTED, IPO, SPLIT, DIVIDEND]
RULE_INDEX = 99


def rule_days() -> list[date]:
    return weekdays(date(2021, 1, 4), RULE_SESSIONS)


def path_of(i: int) -> list[tuple[float, float, float, float, int]]:
    """(o, h, l, c, volume): an up-drift with pullbacks and breakouts, by id."""

    rng = random.Random(1000 + i)
    price, out = 50.0 + i, []
    drift = 0.002 + 0.0004 * (i % 7)
    for t in range(RULE_SESSIONS):
        swing = 0.025 if (t // 9 + i) % 4 == 0 else -0.004
        o = price * (1 + rng.uniform(-0.01, 0.01))
        c = o * (1 + drift + swing * rng.random() + rng.uniform(-0.015, 0.015))
        h = max(o, c) * (1 + rng.uniform(0.001, 0.012))
        low = min(o, c) * (1 - rng.uniform(0.001, 0.012))
        volume = int(2_000_000 * (1.6 if swing > 0 and rng.random() < 0.6 else 1.0))
        volume = int(volume * rng.uniform(0.7, 1.1))
        out.append((round(o, 2), round(h, 2), round(low, 2), round(c, 2), volume))
        price = c
    return out


def build_rules(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = rule_days()
    ids = STOCKS + EDGES
    with Session(engine) as db:
        run = IngestionRun(run_type="collect", source="test", run_date=days[-1])
        db.add(run)
        db.flush()
        payload = RawPayload(ingestion_run_id=run.id, source="test", endpoint="test")
        db.add(payload)
        db.flush()
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"{1000 + i}",
                    "name": f"N{i}",
                    "instrument_type": "ipo" if i == IPO else "stock",
                    "status": "active",
                }
                for i in ids
            ]
            + [
                {
                    "id": RULE_INDEX,
                    "exchange": "TWSE",
                    "symbol": "TAIEX",
                    "name": "加權指數",
                    "instrument_type": "index",
                    "status": "active",
                }
            ],
        )
        bars, chips = [], []
        for i in ids:
            series = path_of(i)
            for t, day in enumerate(days):
                if i == IPO and t < RULE_SESSIONS - 40:
                    continue
                o, h, low, c, volume = series[t]
                scale = 0.5 if i == SPLIT and t >= 120 else 1.0
                if i == DIVIDEND and t >= 125:  # ex-dividend: 2.0 off the prices
                    o, h, low, c = (value - 2.0 for value in (o, h, low, c))
                halted = i == HALTED and t in (100, 118, 131)
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": round(o * scale, 2),
                        "high": round(h * scale, 2),
                        "low": round(low * scale, 2),
                        "close": round(c * scale, 2),
                        "adj_close": round(c * scale, 2),
                        "volume": 0 if halted else int(volume / scale),
                        "turnover": 0.0,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": halted,
                    }
                )
                rng = random.Random(i * 1000 + t)
                margin = (
                    0.0 if i == ZERO_BASE and t % 10 < 6 else 50_000.0 + 1000 * (t % 7)
                )
                chips.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "foreign_buy": rng.uniform(-40_000, 60_000),
                        "trust_buy": None
                        if i == CHIP_GAP and t % 15 == 0
                        else rng.uniform(-5_000, 8_000),
                        "dealer_buy": rng.uniform(-3_000, 3_000),
                        "margin_balance": None if i == NOT_APPLICABLE else margin,
                    }
                )
        for t, day in enumerate(days):
            close = 15_000.0 + 10 * t
            bars.append(
                {
                    "instrument_id": RULE_INDEX,
                    "trading_date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "adj_close": close,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(ChipSnapshot), chips)
        db.add(
            CorporateAction(
                instrument_id=SPLIT,
                action_date=days[120],
                action_type="split",
                details_json={"price_factor": 0.5},
                source="test",
            )
        )
        db.add(
            CorporateAction(
                instrument_id=DIVIDEND,
                action_date=days[125],
                action_type="dividend",
                cash_dividend=2.0,
                source="test",
            )
        )
        lists = []
        for exchange in ("TWSE", "TPEx"):
            members = {
                f"{1000 + i}": ""
                for i in ids
                if (i % 2 == 1) == (exchange == "TWSE") and i != NOT_APPLICABLE
            }
            for day in days:
                lists.append(
                    {
                        "exchange": exchange,
                        "trading_date": day,
                        "source": "test",
                        "endpoint": "test",
                        "data_as_of": day.isoformat(),
                        "collected_at": datetime(2021, 1, 1),
                        "raw_payload_id": payload.id,
                        "member_count": len(members),
                        "members_json": members,
                    }
                )
        db.execute(insert(MarginList), lists)
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def rules_db(tmp_path_factory) -> Path:
    return build_rules(tmp_path_factory.mktemp("rules") / "stock.db")


@pytest.fixture(scope="module")
def product_signals(rules_db, tmp_path_factory):
    """The product's signal rows of the two ablations on every compared day.

    The group score is given to every stock (a stub): without it the product
    writes ``data_incomplete`` for every row, which Q1 sets aside.
    """

    import worker.pipeline as pipeline
    from app.strategies.ablation import research_registry

    copy = Path(shutil.copy(rules_db, tmp_path_factory.mktemp("product") / "stock.db"))
    engine = create_engine(f"sqlite:///{copy.as_posix()}")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    patch = pytest.MonkeyPatch()
    patch.setattr(
        pipeline,
        "_best_group_for_signal",
        lambda db, instrument_id, signal_date: SimpleNamespace(group_id="stub"),
    )
    patch.setattr(
        pipeline,
        "_resolve_group_member_return",
        lambda group_score, instrument, signal_date: (tool.GROUP_PLACEHOLDER, {}),
    )
    registry = research_registry(
        [("breakout_v3", "group"), ("pullback_v4", "group")], canonical=False
    )
    days = rule_days()
    try:
        with factory() as db:
            for instrument in db.scalars(
                select(Instrument).where(
                    Instrument.instrument_type.in_(("stock", "ipo"))
                )
            ):
                pipeline._calculate_features(db, instrument, as_of_date=days[-1])
            db.flush()
            db.commit()
            strategies = pipeline._ensure_strategies(db, registry)
            for day in days[EVAL_FROM:]:
                pipeline._generate_signals(
                    db, day, strategies, namespace="t726", registry=registry
                )
                db.flush()
                db.commit()
            names = {row.id: row.name for row in db.scalars(select(StrategyVersion))}
            rows = {}
            for signal in db.scalars(select(Signal)):
                rows[
                    (
                        names[signal.strategy_version_id],
                        signal.instrument_id,
                        signal.signal_date,
                    )
                ] = signal
                db.expunge(signal)
    finally:
        patch.undo()
        engine.dispose()
    return rows


def test_r1_r2_are_the_product_signals_and_levels(rules_db, product_signals, tmp_path):
    ctx = one_process(
        lambda: tool.load(rules_db, rule_days()[0], rule_days()[-1], tmp_path)
    )
    sessions = ctx.panel.sessions
    compared = []
    for name in ("R1", "R2"):
        strategy = tool.strategy_of(name)
        for s in range(EVAL_FROM, len(sessions)):
            for item, at in ctx.universe(s):
                theirs = product_signals[
                    (strategy.key, item.instrument_id, sessions[s])
                ]
                mine = tool.rule_signal(ctx, strategy, item, at)
                assert mine.status == theirs.status, (
                    name,
                    item.instrument_id,
                    sessions[s],
                )
                levels = (
                    mine.levels.reference_entry,
                    mine.levels.breakout_price,
                    mine.levels.pullback_low,
                    mine.levels.pullback_high,
                    mine.levels.invalid_price,
                    mine.levels.target_1,
                    mine.levels.target_2,
                )
                stored = (
                    theirs.reference_entry,
                    theirs.breakout_price,
                    theirs.pullback_low,
                    theirs.pullback_high,
                    theirs.invalid_price,
                    theirs.target_1,
                    theirs.target_2,
                )
                assert [value is None for value in levels] == [
                    value is None for value in stored
                ], (name, item.instrument_id)
                assert [
                    value for value in levels if value is not None
                ] == pytest.approx(
                    [value for value in stored if value is not None], abs=1e-9
                ), (name, item.instrument_id, sessions[s])
                compared.append((name, item, at, mine, theirs))
    # every edge case of condition 3 is in the comparison, not only in the fixture
    raw = ctx.market.raw

    def has(test):
        return any(test(*row) for row in compared)

    assert has(
        lambda n, item, at, mine, theirs: mine.inputs.margin_financing
        == "not_applicable"
    )
    assert has(
        lambda n, item, at, mine, theirs: mine.inputs.margin_zero_base is not None
    )
    assert has(
        lambda n, item, at, mine, theirs: item.instrument_id == CHIP_GAP
        and mine.inputs.institutional_flow_ratio_5d is None
        and theirs.status == "data_incomplete"
    )
    assert has(
        lambda n, item, at, mine, theirs: item.instrument_id == HALTED
        and any(raw[HALTED][3][k] for k in range(at - 19, at))
    )
    assert has(
        lambda n, item, at, mine, theirs: item.instrument_id == IPO
        and mine.inputs.bar_count < 60
        and theirs.status == "data_incomplete"
    )
    assert has(
        lambda n, item, at, mine, theirs: item.instrument_id == SPLIT
        and item.scale[at - 20] != item.scale[at]
    )
    assert has(
        lambda n, item, at, mine, theirs: item.instrument_id == DIVIDEND
        and item.scale[at - 20] != item.scale[at]
    )
    assert has(
        lambda n, item, at, mine, theirs: n == "R2"
        and theirs.status == "invalid_levels"
    )
    assert has(
        lambda n, item, at, mine, theirs: theirs.status == "data_incomplete"
        and "missing" in ",".join(mine.reasons)
    )
    for name in ("R1", "R2"):
        assert has(lambda n, item, at, mine, theirs: n == name and mine.actionable)


def test_r1_r2_trade_from_the_signal_to_the_exit(
    rules_db, product_signals, tmp_path, monkeypatch
):
    """The holding limit counts from the signal date, and the levels are the
    product's on T's basis times ``scale[T]`` (0.5 before the split)."""

    days = rule_days()
    last = days[-1]
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {"exploration": (None, last), "validation": (last, last), "used": (last, last)},
    )
    floors = {"exploration": 20, "validation": 10}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(tool, "MIN_DAYS", 1)
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], EVAL_FROM + 1)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    monkeypatch.setattr(ex, "delisted_count", lambda db, first, last: 1)  # none here
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    out = tmp_path / "rules"
    assert explore(copy_of(rules_db, tmp_path), out, "R1,R2") == 0
    index = {day.isoformat(): k for k, day in enumerate(days)}
    held = 0
    for name, field in (("R1", "breakout_price"), ("R2", "pullback_low")):
        rows = read_csv(out / name / "trades.csv")
        assert min(row["signal_date"] for row in rows) >= days[EVAL_FROM].isoformat()
        for row in rows:
            s = index[row["signal_date"]]
            if row["exit_reason"] == "time":
                assert row["exit_date"] == days[s + 20].isoformat()
                held += row["fill_date"] != days[s + 1].isoformat()
        strategy = tool.strategy_of(name)
        split = [
            row
            for row in rows
            if row["symbol"] == f"{1000 + SPLIT}" and index[row["signal_date"]] < 120
        ]
        assert split or name == "R2", name  # R1 has some; R2 checked when it has
        for row in split:
            theirs = product_signals[
                (strategy.key, SPLIT, days[index[row["signal_date"]]])
            ]
            assert float(row[field]) == pytest.approx(getattr(theirs, field) * 0.5)
            assert float(row["stop"]) == pytest.approx(theirs.invalid_price * 0.5)
            assert float(row["target"]) == pytest.approx(theirs.target_1 * 0.5)
    assert held > 0  # filled after T+1 and still out on the 20th session


def test_the_bar_count_counts_the_bars_before_the_load(
    rules_db, product_signals, tmp_path
):
    """Q2: an IPO listed before the load's first day keeps its bar count."""

    days = rule_days()
    ctx = one_process(lambda: tool.load(rules_db, days[120], days[-1], tmp_path))
    assert ctx.bars_before[IPO] == 10  # its bars start on session 110
    strategy = tool.strategy_of("R1")
    item = ctx.panel.series[IPO]
    for day in days[130:]:
        mine = tool.strategy_inputs(ctx, item, item.position[day])
        theirs = product_signals[(strategy.key, IPO, day)]
        assert mine.bar_count == theirs.rule_evidence_json["inputs"]["bar_count_60d"]
        assert mine.bar_count < 60


def test_too_little_free_memory_is_refused(golden_db, tmp_path, monkeypatch, capsys):
    compressed(monkeypatch, tmp_path)
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "free_memory_gb", lambda: 0.5)
    db = copy_of(golden_db, tmp_path)
    out = tmp_path / "out"
    code = one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "exploration",
                "--hypotheses",
                "S1",
            ]
        )  # fmt: skip
    )
    assert code == 2
    assert any("free memory 0.5 GB" in line for line in refused(capsys))
    assert not out.exists()
    assert not (db.parent / ex.LEDGER_NAME).exists()


# --- version 1 stays version 1 (#878 AC-1) ---------------------------------------
#
# #878 adds the round-4 hook points to ``signal_day``／``ranked`` and moves the
# margin computation of ``strategy_inputs`` into ``margin_state``.  The digests
# below were taken on the code before that change (master a5bdd20a): every
# trade of S1～S3 on the golden fixture, of R1／R2 on the rules fixture, and
# every StrategyInputs R1／R2 read, must stay the same value for value.

V1_DEFINITIONS = "80329d4669123683783a2153a132931fe90eecfbbe8fbfa382cfed345d8cfbfb"
V1_ZONE_TRADES = "bff68c02604798b44970351b9a009d04c0394bf70abbd6a534e99238d5931025"
V1_RULE_TRADES = "20c11c26caea346fed21d155c3f8ad68edf3e345d382c758408943636abf0fd2"
V1_RULE_INPUTS = "71bc91c2c4c6ee13479aaf1ea717e077011a7a579c722cf01545fa3469a2b998"


def digest(value) -> str:
    import hashlib

    text = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def segment_trades(db: Path, names: list[str], tmp_path: Path, start: date, end: date):
    ctx = one_process(lambda: tool.load(db, start, end, tmp_path / "raw"))
    results = tool.run_segment(ctx, db, names, "exploration")
    return {name: results[name]["_trades"] for name in names}


def test_version_1_is_unchanged_trade_by_trade(
    golden_db, rules_db, tmp_path, monkeypatch
):
    got = {"version": tool.VERSION, "definitions": tool.definitions_sha256()}
    compressed(monkeypatch, tmp_path)
    zone = segment_trades(
        golden_db, ["S1", "S2", "S3"], tmp_path, date(2013, 1, 1), days_()[110]
    )
    assert sum(len(rows) for rows in zone.values()) > 20
    got["zone"] = digest(zone)
    days = rule_days()
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], EVAL_FROM + 1)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[-1]),
            "validation": (days[-1], days[-1]),
            "used": (days[-1], days[-1]),
        },
    )
    monkeypatch.setattr(ex, "delisted_count", lambda db, first, last: 1)
    rule = segment_trades(rules_db, ["R1", "R2"], tmp_path, days[0], days[-1])
    assert all(rule.values())
    got["rule"] = digest(rule)
    assert got == {
        "version": 1,
        "definitions": V1_DEFINITIONS,
        "zone": V1_ZONE_TRADES,
        "rule": V1_RULE_TRADES,
    }


def test_the_r1_r2_inputs_are_unchanged(rules_db, tmp_path):
    from dataclasses import asdict

    ctx = one_process(
        lambda: tool.load(rules_db, rule_days()[0], rule_days()[-1], tmp_path)
    )
    inputs = []
    for s in range(EVAL_FROM, len(ctx.panel.sessions)):
        for item, at in ctx.universe(s):
            inputs.append(
                [item.instrument_id, at, asdict(tool.strategy_inputs(ctx, item, at))]
            )
    assert len(inputs) > 2000
    assert digest(inputs) == V1_RULE_INPUTS


# The other two tools whose numbers #878 must not move (AC-1).
OTHER_VERSIONS = {
    "explore_research": (
        2,
        "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63",
    ),
    "mainstream_research": (
        1,
        "5e776480b0fa7d023c9f217671c856ac81ea8d4115d7ff94aac7446a263371f2",
    ),
}


def test_explore_and_mainstream_research_are_unchanged():
    ms = _tool("mainstream_research")
    got = {
        "explore_research": (ex.VERSION, ex.definitions_sha256()),
        "mainstream_research": (ms.VERSION, ms.definitions_sha256()),
    }
    assert got == OTHER_VERSIONS


def test_s1_through_the_round4_hooks_is_version_1_trade_by_trade(
    golden_db, tmp_path, monkeypatch
):
    """S1 run through round4_research's entry (``run_segment`` with its own
    registration and the three hooks, each doing what S1 does) is S1 of
    version 1, trade for trade (#878 AC-1)."""

    compressed(monkeypatch, tmp_path)
    # this file's trade_research (another test file may have loaded its own)
    monkeypatch.setitem(sys.modules, "trade_research", tool)
    monkeypatch.setitem(sys.modules, "round4_research", None)
    r4 = _tool("round4_research")
    assert r4.tr is tool
    ctx = one_process(
        lambda: tool.load(golden_db, date(2013, 1, 1), days_()[110], tmp_path / "raw")
    )
    plain = tool.run_segment(ctx, golden_db, ["S1"], "exploration")["S1"]["_trades"]
    seen = {"select": 0, "keep": 0, "stop": 0}

    def select(c, s):
        seen["select"] += 1

        def keep(item, at):
            seen["keep"] += 1
            return True

        return keep

    def stop(item, at, atr, fill):
        seen["stop"] += 1
        return (None if fill is None else fill - 2.0 * atr), {}

    s1 = {"S1": tool.HYPOTHESES["S1"]}
    hooked = tool.run_segment(
        ctx,
        golden_db,
        ["S1"],
        "exploration",
        hypotheses=s1,
        hooks=lambda name: tool.Hooks(
            select=select,
            first_key=("trust_buy_days", tool.features.trust_buy_days),
            stop=stop,
        ),
    )["S1"]["_trades"]
    assert all(seen.values())  # every hook point ran
    assert plain and digest(hooked) == digest(plain)
    # and the entry's own path: S1's spec, no hooks, through round4's run_segment
    loaded = r4.Loaded(ctx, None)
    monkeypatch.setattr(r4, "HYPOTHESES", s1)
    monkeypatch.setattr(r4, "Run", lambda groups: (lambda name: None))
    monkeypatch.setattr(r4, "listed", lambda name, run, trades: {})
    via = r4.run_segment(loaded, golden_db, ["S1"], "exploration")["S1"]["_trades"]
    assert digest(via) == digest(plain)
    zone = segment_trades(
        golden_db, ["S1", "S2", "S3"], tmp_path, date(2013, 1, 1), days_()[110]
    )
    assert digest(zone) == V1_ZONE_TRADES  # plain is version 1's S1
    assert digest(zone["S1"]) == digest(plain)
