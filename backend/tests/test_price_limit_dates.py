"""The research engine's daily price limit by trading date (#922).

±7% to 2015-05-29 and ±10% from 2015-06-01, worked by hand on the portfolio
engine (``portfolio_research.Market`` / ``simulate``) and on the trade by
trade evaluation (``trade_research.TradeBars`` with ``exit_research.enter``).
"""

from __future__ import annotations

import importlib.util
import sys
from array import array
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest

from app.strategies import levels

ROOT = Path(__file__).resolve().parents[2]


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
er = _tool("exit_research")
pr = _tool("portfolio_research")
tr = _tool("trade_research")

THU = date(2015, 5, 28)
FRI = date(2015, 5, 29)  # the last session at ±7%
MON = date(2015, 6, 1)  # the first at ±10%
TUE = date(2015, 6, 2)
SESSIONS = [THU, FRI, MON, TUE]
A = 1


def series(bars: dict[date, tuple[float, float, float, float]]) -> lib.Series:
    """One instrument's (open, high, low, close) by session, no actions."""

    item = lib.Series(A)
    item.suspended.append(0)
    for at, day in enumerate(sorted(bars)):
        o, h, low, c = bars[day]
        item.position[day] = at
        item.dates.append(day)
        item.session.append(SESSIONS.index(day))
        for name, value in (("open", o), ("high", h), ("low", low), ("close", c)):
            getattr(item, name).append(value)
        item.volume.append(1_000_000.0)
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1])
    return item


def market(item: lib.Series) -> pr.Market:
    listed = {day: [A] if day in item.position else [] for day in SESSIONS}
    panel = lib.Panel(SESSIONS, {A: item}, listed, {}, {A: ("TWSE", "A", "")})
    unsuspended = array("d", [0.0] * len(item.dates))
    raw = {A: (item.low, item.high, item.close, unsuspended)}  # no actions: scale 1
    return pr.Market(panel, raw, {A: "stock"}, levels)


def flat(price: float) -> tuple[float, float, float, float]:
    return (price, price, price, price)


# --- the limit and its rounding ---------------------------------------------------


def test_the_limit_widens_on_2015_06_01():
    assert er.LIMIT_WIDENED_ON == MON
    assert er.daily_limit(FRI) == Fraction(7, 100)
    assert er.daily_limit(MON) == er.LIMIT == Fraction(1, 10)
    assert er.daily_limit(date(2004, 2, 11)) == Fraction(7, 100)


def test_limits_before_the_widening_are_7_percent_on_the_tick():
    # 100 * 1.07 = 107 (tick 0.5); 100 * 0.93 = 93 (tick 0.1)
    assert er.price_limits(100.0, "stock", levels, on=FRI) == (93.0, 107.0)
    # 50.5 * 1.07 = 54.035 -> floor 54.0 (tick 0.1); 50.5 * 0.93 = 46.965 -> ceil 47.0
    assert er.price_limits(50.5, "stock", levels, on=FRI) == pytest.approx((47.0, 54.0))
    # 10.05 * 1.07 = 10.7535 -> 10.75 (tick 0.05); 10.05 * 0.93 = 9.3465 -> 9.35
    assert er.price_limits(10.05, "stock", levels, on=FRI) == pytest.approx(
        (9.35, 10.75)
    )
    assert er.price_limits(100.0, "etf", levels, on=FRI) is None


@pytest.mark.parametrize("on", [MON, date(2020, 1, 2), date(2026, 11, 13)])
@pytest.mark.parametrize("reference", [100.0, 101.0, 10.05, 50.5, 9.99, 499.5, 1234.0])
def test_limits_from_the_widening_on_are_the_old_10_percent(on, reference):
    """2015-06-01 and later: the same numbers as before #922."""

    base = Fraction(str(round(reference, 6)))
    old = (
        levels.tick_ceil(float(base * Fraction(9, 10)), "stock"),
        levels.tick_floor(float(base * Fraction(11, 10)), "stock"),
    )
    assert er.price_limits(reference, "stock", levels, on=on) == old


# --- the portfolio engine: buys -----------------------------------------------------


def buy(bars, s: int) -> pr.Simulation:
    m = market(series(bars))
    return pr.simulate({s: [A]}, m.quote, s, s, hold=1, top=1)


def test_a_bar_locked_at_7_percent_on_2015_05_29_is_not_bought():
    result = buy({THU: flat(100.0), FRI: flat(107.0)}, 1)
    assert result.counts["limit_up"] == 1 and result.counts["bought"] == 0


def test_a_bar_at_7_percent_on_2015_05_29_with_a_lower_low_is_bought():
    result = buy({THU: flat(100.0), FRI: (105.0, 107.0, 106.5, 107.0)}, 1)
    assert result.counts["limit_up"] == 0 and result.counts["bought"] == 1


def test_on_2015_06_01_a_bar_locked_at_10_percent_is_not_bought():
    result = buy({FRI: flat(100.0), MON: flat(110.0)}, 2)
    assert result.counts["limit_up"] == 1 and result.counts["bought"] == 0


def test_on_2015_06_01_a_bar_flat_at_7_percent_is_bought():
    result = buy({FRI: flat(100.0), MON: flat(107.0)}, 2)
    assert result.counts["limit_up"] == 0 and result.counts["bought"] == 1


# --- the portfolio engine: sales ----------------------------------------------------


def test_a_sale_locked_at_minus_7_percent_on_2015_05_29_waits_a_session():
    m = market(series({THU: flat(100.0), FRI: flat(93.0), MON: flat(95.0)}))
    result = pr.simulate({1: [A]}, m.quote, 1, 2, hold=1, top=1)
    assert result.counts["limit_down"] == 1
    assert result.positions[0].how == "delayed" and result.positions[0].sold == 2


def test_on_2015_06_01_a_sale_locked_at_minus_10_percent_waits_and_7_does_not():
    m = market(series({FRI: flat(100.0), MON: flat(90.0), TUE: flat(92.0)}))
    result = pr.simulate({2: [A]}, m.quote, 2, 3, hold=1, top=1)
    assert result.counts["limit_down"] == 1 and result.positions[0].sold == 3
    m = market(series({FRI: flat(100.0), MON: flat(93.0), TUE: flat(92.0)}))
    result = pr.simulate({2: [A]}, m.quote, 2, 3, hold=1, top=1)
    assert result.counts["limit_down"] == 0 and result.positions[0].sold == 2


# --- the trade by trade evaluation -----------------------------------------------------


def trade_bars(bars, signal: int) -> tr.TradeBars:
    item = series(bars)
    ctx = tr.Context(market(item), Path("unused.sqlite"), SESSIONS[-1])
    return tr.TradeBars(ctx, item, signal, signal + 1)


BREAKOUT = er.Levels("breakout", 104.0, None, None, 95.0, 120.0, 130.0)


def test_a_breakout_locked_at_7_percent_on_2015_05_29_is_abandoned():
    bars = trade_bars({THU: flat(100.0), FRI: flat(107.0)}, 0)
    assert bars[0].limit_up == 107.0 and bars[0].locked_up
    entry = er.enter(BREAKOUT, bars[:])
    assert (entry.session, entry.reason, entry.limit_blocked) == (
        None,
        "not_triggered",
        1,
    )
    zone, _gap = tr.enter_zone(bars, 110.0, 100.0, 1)
    assert (zone.reason, zone.limit_blocked) == ("not_triggered", 1)


def test_a_breakout_at_7_percent_on_2015_05_29_with_a_lower_low_fills():
    bars = trade_bars({THU: flat(100.0), FRI: (105.0, 107.0, 106.5, 107.0)}, 0)
    entry = er.enter(BREAKOUT, bars[:])
    assert (entry.session, entry.reason) == (1, "filled")


def test_on_2015_06_01_the_evaluation_locks_at_10_percent_only():
    locked = trade_bars({FRI: flat(100.0), MON: flat(110.0)}, 1)
    assert locked[0].limit_up == 110.0
    assert er.enter(BREAKOUT, locked[:]).reason == "not_triggered"
    open_ = trade_bars({FRI: flat(100.0), MON: flat(107.0)}, 1)
    assert not open_[0].locked_up
    assert er.enter(BREAKOUT, open_[:]).session == 1


def test_the_evaluation_locks_at_minus_7_percent_on_2015_05_29_only():
    friday = trade_bars({THU: flat(100.0), FRI: flat(93.0)}, 0)
    assert friday[0].limit_down == 93.0 and friday[0].locked_down
    monday = trade_bars({FRI: flat(100.0), MON: flat(93.0)}, 1)
    assert monday[0].limit_down == 90.0 and not monday[0].locked_down
    assert trade_bars({FRI: flat(100.0), MON: flat(90.0)}, 1)[0].locked_down
