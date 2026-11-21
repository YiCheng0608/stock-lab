"""tools/research/round9_research.py: the registered B1～B3 (#926).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第九輪：B1～B3.  The features are checked on hand-made
series (the expected numbers worked out in the test); B2's trades and the
gate ("each once") run on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 330 sessions, everything else is the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import weakref
from array import array
from collections import Counter
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import (
    Base,
    ChipSnapshot,
    IngestionRun,
    Instrument,
    MarginList,
    MarketBar,
    RawPayload,
)
from app.strategies import levels

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/926#issuecomment-1"
NAN = float("nan")


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
pr = _tool("portfolio_research")
er = _tool("exit_research")
ex = _tool("explore_research")
tr = _tool("trade_research")
r5 = _tool("round5_research")
tool = _tool("round9_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("B1", "B2", "B3")


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", "round4_research", "round5_research"):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    otc = date(2007, 12, 3)
    b1, b2, b3 = h["B1"], h["B2"], h["B3"]
    assert (b1["engine"], b1["keys"], b1["condition"], b1["top"], b1["hold"]) == (
        "portfolio",
        (("short_margin_ratio", "high"),),
        None,
        20,
        20,
    )
    assert b1["start"] == ("session", otc, 20)
    assert (b2["engine"], b2["min_ratio"], b2["entry_days"], b2["hold"]) == (
        "trade",
        0.3,
        1,
        5,
    )
    assert (b2["stop"], b2["target"], b2["market_filter"]) == (None, None, False)
    assert b2["start"] == ("session", otc, 20)
    assert (b3["engine"], b3["keys"], b3["condition"], b3["top"], b3["hold"]) == (
        "portfolio",
        (),
        "limit_up_close",
        20,
        5,
    )
    assert b3["start"] == ("date", date(2015, 6, 1))


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (1, 9, 3, 37)
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.205
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(37), 3) == 3.205
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.MIN_DAYS == 60 and tool.OVERLAP == 20
    assert tool.REGISTRATION_COMMIT == "00be010c"
    assert (tool.MIN_RATIO, tool.X_NOTE) == (0.3, "X")


def test_the_definitions_hash_holds_the_threshold_and_the_rules(monkeypatch):
    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.205
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.180),
        (tool, "MIN_RATIO", 0.25),
        (tool, "X_NOTE", "O"),
        (tool, "MIN_DAYS", 50),
        (tool, "LIMIT_EPS", 0.0),
        (tool, "MARKET_WIDE_SHARE", 0.9),
    ):
        with monkeypatch.context() as m:
            m.setattr(module, name, value)
            assert tool.definitions_sha256() != before, name
    assert tool.definitions_sha256() == before


def test_the_command_has_no_parameter_flags():
    flags = {
        option for action in tool._parser()._actions for option in action.option_strings
    }
    assert flags == {
        "-h",
        "--help",
        "--db",
        "--out",
        "--segment",
        "--min-free-gb",
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master 00be010c before this tool existed.
FROZEN = {
    "explore_research": (
        2,
        "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63",
    ),
    "trade_research": (
        1,
        "80329d4669123683783a2153a132931fe90eecfbbe8fbfa382cfed345d8cfbfb",
    ),
    "mainstream_research": (
        1,
        "5e776480b0fa7d023c9f217671c856ac81ea8d4115d7ff94aac7446a263371f2",
    ),
    "round4_research": (
        1,
        "2fa7f1826fc1b1b962eb63b45b6a238122d74fd4912e0a14c8eed0a0cf63aa56",
    ),
    "round5_research": (
        1,
        "a3409f1b9dd24a8e32c04148f5d1e36a5e8282e96df975bd0b36a21101993d75",
    ),
    "round6_research": (
        1,
        "b8e1eb89a20b9ea97db4d6ba38a1461d5ff5bf05b26eb9619c353db7020ac51e",
    ),
    "round7_research": (
        1,
        "180c21a4307b5cfd16db0b246478f5da3406a9779b0956dfc13cb32dc0cd47d7",
    ),
}


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


def test_the_docs_tool_section_says_what_the_code_judges():
    """The degenerate cases in the tool section are the code's own strings,
    and coverage.md／summary.md print the same (PR #913 review)."""

    text = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    section = text.split("**第九輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in (*NAMES, "B2_market_wide"):
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    rule = text.split("#### 第九輪實作釋義", 1)[1].split("## 隔夜美股條件研究", 1)[0]
    assert "7056755897" in rule and "80%" in rule and "2008-09-30" in rule
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "tools/research/round9_research.py" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes, suspended=(), instrument_id=1, raw=None, chips=None, days=None):
    """A series on weekdays from 2016-01-04 (±10% limits); ``raw`` the
    unadjusted closes (the adjusted ones by default)."""

    item = lib.Series(instrument_id)
    days = days or weekdays(date(2016, 1, 4), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at)
        for name in ("open", "high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(2_000_000.0)
        scale = 1.0 if raw is None or not raw[at] else close / raw[at]
        item.scale.append(scale)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    item.chips = {name: array("d", values) for name, values in (chips or {}).items()}
    return item


def market_for(items, raws=None):
    raws = raws or {}
    series = {item.instrument_id: item for item in items}
    raw = {}
    for item in items:
        closes = raws.get(item.instrument_id, list(item.close))
        flags = [item.is_suspended(k) for k in range(len(item.dates))]
        raw[item.instrument_id] = (
            array("d", closes),
            array("d", closes),
            array("d", closes),
            array("d", flags),
        )
    sessions = sorted({day for item in items for day in item.dates})
    panel = lib.Panel(sessions, series, {}, {}, {})
    return pr.Market(
        panel, raw, {item.instrument_id: "stock" for item in items}, levels
    )


# --- B1 -------------------------------------------------------------------------


def b1(short, margin):
    return make_item(
        [10.0], chips={"short_balance": [short], "margin_balance": [margin]}
    )


def test_short_margin_ratio_is_the_two_balances_in_lots():
    assert tool.short_margin_ratio(b1(345.0, 1150.0), 0) == 0.3
    assert tool.short_margin_ratio(b1(123.0, 4567.0), 0) == pytest.approx(
        0.0269323407050580, rel=1e-12
    )


def test_short_margin_ratio_of_no_short_is_0_not_missing():
    value = tool.short_margin_ratio(b1(0.0, 500.0), 0)
    assert value == 0.0 and value is not None


@pytest.mark.parametrize(
    "short, margin",
    [(NAN, 1000.0), (100.0, NAN), (NAN, NAN), (100.0, 0.0), (100.0, -5.0), (0.0, 0.0)],
)
def test_short_margin_ratio_is_missing_without_a_row_a_balance_or_a_margin(
    short, margin
):
    assert tool.short_margin_ratio(b1(short, margin), 0) is None


def test_short_margin_ratio_is_missing_without_the_chip_arrays():
    assert tool.short_margin_ratio(make_item([10.0]), 0) is None


def test_b1_is_high_first_with_a_missing_value_last():
    day = date(2016, 3, 1)
    values = {
        1: (300.0, 1000.0),
        2: (NAN, 1000.0),
        3: (100.0, 1000.0),
        4: (300.0, 1000.0),
    }
    values |= {5: (0.0, 1000.0), 6: (10.0, 0.0)}
    members = [(b1(s, m), 0) for s, m in values.values()]
    for (item, _at), instrument_id in zip(members, values):
        item.instrument_id = instrument_id
    ctx = SimpleNamespace(seconds=Counter())
    ranked = tool.rank(ctx, tool.HYPOTHESES["B1"], day, members)
    tied = sorted((1, 4), key=lambda i: pr.tie_break(day, i))
    missing = sorted((2, 6), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == [*tied, 3, 5, *missing]
    assert (ranked.missing, ranked.zero) == (2, 1)


# --- B2: x_start ------------------------------------------------------------------

D0, D1 = date(2016, 3, 1), date(2016, 3, 2)


def lists(**days):
    out = tool.MarginLists()
    for key, members in days.items():
        day = {"d0": D0, "d1": D1}[key]
        out.present.add(("TWSE", day))
        out.x[("TWSE", day)] = frozenset(
            symbol for symbol, note in members.items() if "X" in note
        )
    return out


def test_x_start_is_x_on_t_and_not_on_the_session_before():
    first = lists(d0={"1101": "", "1102": "O"}, d1={"1101": "X", "1102": "OX"})
    assert first.has("TWSE", D1) and not first.has("TPEx", D1)
    assert tool.x_start(first, "TWSE", "1101", D1, D0) is True
    assert tool.x_start(first, "TWSE", "1102", D1, D0) is True  # "OX" contains X
    new = lists(d0={}, d1={"1101": "X"})  # not on the list the session before
    assert tool.x_start(new, "TWSE", "1101", D1, D0) is True
    again = lists(d0={"1101": "X"}, d1={"1101": "X"})
    assert tool.x_start(again, "TWSE", "1101", D1, D0) is False
    off = lists(d0={}, d1={"1101": "O"})
    assert tool.x_start(off, "TWSE", "1101", D1, D0) is False


def test_x_start_is_missing_without_either_list():
    only_t = lists(d1={"1101": "X"})
    assert tool.x_start(only_t, "TWSE", "1101", D1, D0) is None
    only_before = lists(d0={})
    assert tool.x_start(only_before, "TWSE", "1101", D1, D0) is None
    assert tool.x_start(lists(d0={}, d1={"1101": "X"}), "TPEx", "1101", D1, D0) is None
    assert tool.x_start(lists(d1={"1101": "X"}), "TWSE", "1101", D1, None) is None


def wide(new: int, size: int, other: int = 1) -> tool.MarginLists:
    """TWSE adds X to ``new`` of its ``size`` on D1; TPEx to ``other`` of 100."""

    out = tool.MarginLists()
    for exchange, count, total in (("TWSE", new, size), ("TPEx", other, 100)):
        for day in (D0, D1):
            out.present.add((exchange, day))
            out.members[(exchange, day)] = total
        out.x[(exchange, D0)] = frozenset()
        out.x[(exchange, D1)] = frozenset(f"{exchange}{k}" for k in range(count))
    return out


def test_a_market_wide_day_is_80_percent_of_the_list():
    """#926 decision 7056755897: ≥ 80% of the day's list adding X."""

    assert tool.MARKET_WIDE_SHARE == 0.8
    assert tool.market_wide(wide(80, 100), "TWSE", D1, D0) is True
    assert tool.market_wide(wide(79, 100), "TWSE", D1, D0) is False
    assert tool.market_wide(wide(4, 5), "TWSE", D1, D0) is True  # exactly 80%
    lists_ = wide(80, 100)
    assert tool.market_wide(lists_, "TPEx", D1, D0) is False  # the other exchange
    # X already on the session before is not new
    lists_.x[("TWSE", D0)] = lists_.x[("TWSE", D1)]
    assert tool.market_wide(lists_, "TWSE", D1, D0) is False
    assert tool.market_wide(wide(80, 100), "TWSE", D1, None) is False


def test_the_entry_is_t_plus_1s_open_or_abandoned():
    plain = SimpleNamespace(suspended=False, locked_up=False, open=50.0)
    entry = tool.enter_next_open([plain])
    assert (entry.session, entry.reason) == (1, "filled")
    assert entry.price == pytest.approx(50.0 * (1 + 5 / 10_000))
    halted = tool.enter_next_open([SimpleNamespace(suspended=True, locked_up=False)])
    assert (halted.session, halted.reason, halted.limit_blocked) == (
        None,
        "not_tradable",
        0,
    )
    locked = tool.enter_next_open(
        [SimpleNamespace(suspended=False, locked_up=True, open=55.0)]
    )
    assert (locked.session, locked.reason, locked.limit_blocked) == (
        None,
        "limit_up",
        1,
    )


# --- B3 -------------------------------------------------------------------------


def b3(closes, raw=None, suspended=()):
    item = make_item(closes, suspended=suspended, raw=raw)
    return market_for([item], {1: raw} if raw else None), item


def test_limit_up_close_is_the_close_at_the_limit_rounded_down_to_the_tick():
    # 99.95 × 1.1 = 109.945; 100～500 has 0.5 ticks: tick_floor → 109.5
    market, item = b3([99.95, 109.5])
    assert tool.limit_up_price(market, item, 1) == (109.5, 109.5)
    assert tool.limit_up_close(market, item, 1) is True
    market, item = b3([99.95, 109.9])  # above the legal limit: still at it
    assert tool.limit_up_close(market, item, 1) is True
    market, item = b3([99.95, 109.4])
    assert tool.limit_up_close(market, item, 1) is False
    # 50～100 has 0.1 ticks: 60 × 1.1 = 66.0 exactly
    market, item = b3([60.0, 66.0])
    assert tool.limit_up_close(market, item, 1) is True
    market, item = b3([60.0, 65.9])
    assert tool.limit_up_close(market, item, 1) is False


def test_limit_up_close_puts_the_previous_close_on_ts_basis_on_an_ex_date():
    # raw 100 then 99 ex-dividend: the adjusted 90 is 90 on T's basis
    # (scale 0.9 before, 1 on T), so the limit is tick_floor(99.0) = 99.0
    market, item = b3([90.0, 99.0], raw=[100.0, 99.0])
    assert item.scale[0] == pytest.approx(0.9)
    assert tool.limit_up_price(market, item, 1) == (99.0, 99.0)
    assert tool.limit_up_close(market, item, 1) is True
    # on the raw previous close the limit would be 110: not at it
    assert levels.tick_floor(100.0 * 1.1, "stock") == 110.0


@pytest.mark.parametrize("suspended", [(0,), (1,)])
def test_limit_up_close_is_missing_with_t_or_the_bar_before_suspended(suspended):
    market, item = b3([60.0, 66.0], suspended=suspended)
    assert tool.limit_up_close(market, item, 1) is None


@pytest.mark.parametrize(
    "closes, raw",
    [([NAN, 66.0], None), ([60.0, NAN], None), ([60.0, 66.0], [60.0, 0.0])],
)
def test_limit_up_close_is_missing_with_a_close_missing_or_not_positive(closes, raw):
    market, item = b3(closes, raw=raw)
    assert tool.limit_up_close(market, item, 1) is None


def test_limit_up_close_needs_a_bar_before():
    market, item = b3([60.0])
    assert tool.limit_up_close(market, item, 0) is None


def test_b3_takes_the_first_20_by_the_hash_and_leaves_the_rest_to_cash():
    day = date(2016, 3, 2)
    hits = [make_item([60.0, 66.0], instrument_id=i) for i in range(1, 26)]
    misses = [make_item([60.0, 65.0], instrument_id=i) for i in range(26, 30)]
    market = market_for(hits + misses)
    ctx = SimpleNamespace(seconds=Counter(), market=market)
    spec = tool.HYPOTHESES["B3"]
    ranked = tool.rank(ctx, spec, day, [(item, 1) for item in hits + misses])
    by_hash = sorted(range(1, 26), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == by_hash  # the misses are not there
    assert (ranked.hits, ranked.missing) == (25, 0)
    few = tool.rank(ctx, spec, day, [(item, 1) for item in hits[:3] + misses])
    assert [row[0] for row in few.rows] == sorted(
        (1, 2, 3), key=lambda i: pr.tie_break(day, i)
    )  # 3 names: 17 of the 20 shares stay cash in simulate
    picks = {1: [row[0] for row in few.rows]}
    quote = lambda i, s: pr.Quote(66.0, 66.0, True)  # noqa: E731
    simulated = pr.simulate(picks, quote, 1, 1, spec["hold"], spec["top"])
    # the account of the day holds 1/5 of the equity; 3 of its 20 shares bought
    assert simulated.bought[0] == pytest.approx(3 * (1 / 5) / 20)


def test_b3_starts_on_2015_06_01():
    sessions = weekdays(date(2015, 5, 25), 600)
    first, _last = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["B3"])
    assert sessions[first - 1] == date(2015, 6, 1)


def test_b1_and_b2_start_on_the_20th_session_from_the_otc_2007_12_03():
    sessions = weekdays(date(2007, 11, 26), 300)
    for name in ("B1", "B2"):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == weekdays(date(2007, 12, 3), 20)[-1]


# --- the verdict ----------------------------------------------------------------


def judged(stage, t):
    excess = {"mean": 0.001, "t": t}
    return ex.explore_judge(
        stage,
        2000,
        True,
        excess,
        0.0005,
        tool.VALIDATION_MIN_T if stage == "validation" else tool.MIN_T,
    )


@pytest.mark.parametrize(
    "t, verdict",
    [
        (2.0, "前瞻觀察"),
        (2.5, "前瞻觀察"),
        (3.180, "前瞻觀察"),  # round 8's threshold is not this round's
        (3.204, "前瞻觀察"),
        (3.205, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_205(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 330
STOCKS = range(1, 25)
DELISTED = {25: 120, 27: 250}  # the last bar's index
TRANSFERRED = {26: 280}
INDEX_ID = 90
NO_CHIPS = 4  # a TPEx stock without any chip row
ZERO_MARGIN = 12  # margin 0, short 50: missing
ZERO_SHORT = 14  # no short: 0
NULL_SHORT = (16, 100)  # (id, session): a null short_balance
# B2: the sessions each stock is on its list with X (TWSE odd, TPEx even)
X_DAYS = {
    3: {100, 101, 103, 105, 106, 107},  # signals 100 and 105; 103 is occupied
    5: set(range(120, 126)),  # T+1 = 121 suspended
    9: set(range(130, 136)),  # T+1 = 131 locked at limit up
    11: set(range(140, 146)),  # the 5th session 145 locked at limit down
    13: set(range(150, 156)),  # ratio 344 ÷ 1150, below 0.3
    15: set(range(150, 156)),  # ratio 345 ÷ 1150 = 0.3
    17: set(range(150, 156)),  # a null short_balance on 150
    19: {197, 198, 199},  # the exploration ends on 199: segment end
    25: set(range(117, 121)),  # delisted after 120
    23: {175},  # "OX"
    6: set(range(160, 166)),  # TPEx: no list on 160
    8: set(range(161, 166)),  # its session before is 160
}
# A market-wide day (#926 decision 7056755897): 12 of the 14 TWSE members add X
# on 185 (≥ 80%), so TWSE makes no signal; TPEx's S8 that day still signals.
MARKET_WIDE = 185
for _i in range(1, 24, 2):
    X_DAYS.setdefault(_i, set()).add(MARKET_WIDE)
X_DAYS[8] = X_DAYS[8] | {MARKET_WIDE}
O_DAYS = {21: set(range(170, 176))}  # "O" only: no signal
TPEX_MISSING = 160
SUSPENDED = (5, 121)
LOCKED_UP = (9, 131)
LOCKED_DOWN = (11, 145)
LIMIT_UP_CLOSE = (10, 90)  # B3: closes at limit up, not locked
SHORTS = {i: 400.0 for i in (3, 5, 9, 11, 17, 19, 25, 6, 8)} | {
    13: 344,
    15: 345,
    23: 500,
}
NULL_RATIO = (17, 150)


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def limit(previous: float, up: bool) -> float:
    """``exit_research.price_limits`` by hand (±10% from 2015-06-01)."""

    base = Fraction(str(round(previous, 6)))
    if up:
        return levels.tick_floor(float(base * Fraction(11, 10)), "stock")
    return levels.tick_ceil(float(base * Fraction(9, 10)), "stock")


def path(i: int) -> list[tuple[float, float, float, float]]:
    out, previous = [], 50.0 + i
    for t in range(SESSIONS):
        if (i, t) == SUSPENDED:
            out.append((previous,) * 4)
            continue
        if (i, t) in (LOCKED_UP, LOCKED_DOWN):
            price = limit(previous, (i, t) == LOCKED_UP)
            out.append((price,) * 4)
            previous = price
            continue
        if (i, t) == LIMIT_UP_CLOSE:
            close = limit(previous, True)
            open_ = round(previous * 1.02, 2)
            out.append((open_, close, round(open_ * 0.996, 2), close))
            previous = close
            continue
        close = round(previous * (1 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def margin(i: int, t: int) -> float:
    return 0.0 if i == ZERO_MARGIN else 1000.0 + t


def short(i: int, t: int) -> float | None:
    if (i, t) in (NULL_SHORT, NULL_RATIO):
        return None
    if i == ZERO_SHORT:
        return 0.0
    if i == ZERO_MARGIN:
        return 50.0
    return float(SHORTS.get(i, 10.0 * i))


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


def build(path_: Path) -> Path:
    engine = create_engine(f"sqlite:///{path_}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ends = {**DELISTED, **TRANSFERRED}
    ids = [*STOCKS, *ends]
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
                    "exchange": exchange_of(i),
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": "delisted"
                    if i in DELISTED
                    else "transferred"
                    if i in TRANSFERRED
                    else "active",
                }
                for i in ids
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
        for i in ids:
            prices = path(i)
            for t, day in enumerate(days):
                if t > ends.get(i, SESSIONS):
                    break
                open_, high, low, close = prices[t]
                halted = (i, t) == SUSPENDED
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "adj_close": close,
                        "volume": 0 if halted else 2_000_000 + 10_000 * i,
                        "turnover": close * 2_000_000,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": halted,
                    }
                )
                if i != NO_CHIPS:
                    chips.append(
                        {
                            "instrument_id": i,
                            "trading_date": day,
                            "margin_balance": margin(i, t),
                            "short_balance": short(i, t),
                            "source": "test",
                        }
                    )
        for t, day in enumerate(days):
            level = 9000.0 + 5 * t
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": level,
                    "high": level,
                    "low": level,
                    "close": level,
                    "adj_close": level,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(ChipSnapshot), chips)
        rows = []
        for exchange in ("TWSE", "TPEx"):
            mine = [i for i in ids if exchange_of(i) == exchange]
            for t, day in enumerate(days):
                if exchange == "TPEx" and t == TPEX_MISSING:
                    continue
                members = {}
                for i in mine:
                    note = ""
                    if t in O_DAYS.get(i, ()):
                        note = "O"
                    if t in X_DAYS.get(i, ()):
                        note = "OX" if i == 23 else "X"
                    members[f"S{i}"] = note
                rows.append(
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
        db.execute(insert(MarginList), rows)
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round9") / "stock.db")


APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    """research_report.load_actions points these at the copy for app.config."""

    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def loaded(fixture_db, tmp_path_factory):
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw")
    return one_process(lambda: tool.load(fixture_db, date(1990, 1, 1), days[-1], raw))


def test_one_panel_serves_both_engines(loaded, fixture_db, tmp_path_factory):
    assert loaded.trade.market is loaded.base.market
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw-tr")
    other = one_process(lambda: tr.load(fixture_db, date(1990, 1, 1), days[-1], raw))
    assert loaded.trade.statuses == other.statuses
    assert loaded.trade.last_bar == other.last_bar
    assert loaded.trade.last_bar[25] == days[120]
    assert loaded.trade.index_days == other.index_days


def test_b1_reads_both_balances_of_t(loaded):
    days = trading_days()
    item = loaded.panel.series[3]
    assert tool.short_margin_ratio(item, item.position[days[100]]) == 400 / 1100
    zero = loaded.panel.series[ZERO_SHORT]
    assert tool.short_margin_ratio(zero, zero.position[days[100]]) == 0.0
    for i in (NO_CHIPS, ZERO_MARGIN):
        item = loaded.panel.series[i]
        assert tool.short_margin_ratio(item, item.position[days[100]]) is None
    null = loaded.panel.series[NULL_SHORT[0]]
    for t, missing in ((99, False), (100, True), (101, False)):
        value = tool.short_margin_ratio(null, null.position[days[t]])
        assert (value is None) is missing, t


def test_the_margin_lists_keep_the_x_symbols(loaded):
    days = trading_days()
    lists = loaded.lists
    assert lists.x[("TWSE", days[100])] == {"S3"}
    assert lists.x[("TWSE", days[150])] == {"S13", "S15", "S17"}
    assert lists.x[("TWSE", days[175])] == {"S23"}  # "OX"
    assert not lists.has("TPEx", days[TPEX_MISSING])
    assert lists.members[("TWSE", days[0])] == 14 and lists.notes["O"] == 6


def b2_run(loaded, monkeypatch) -> dict:
    """B2 on the signal dates 59 .. 198, the last session 199 (the used
    segment's rules: no floor, no delisted check; nothing else differs)."""

    days = trading_days()
    monkeypatch.setattr(
        tool, "SEGMENTS", {**tool.SEGMENTS, "used": (days[60], days[199])}
    )
    loaded.trade.baselines.clear()
    loaded.trade.universes.clear()
    return tool.run_trades(loaded, Path("unused"), "B2", "used")


def test_b2_trades_by_hand(loaded, monkeypatch):
    days = trading_days()
    result = b2_run(loaded, monkeypatch)
    trades = {(t["signal_date"], t["symbol"]): t for t in result["_trades"]}
    d = days
    assert sorted(trades, key=lambda key: (key[0], key[1])) == [
        (d[100], "S3"),
        (d[105], "S3"),  # the exit day's close may signal again
        (d[117], "S25"),
        (d[120], "S5"),
        (d[130], "S9"),
        (d[140], "S11"),
        (d[150], "S15"),  # exactly 0.3; S13 below, S17 missing
        (d[175], "S23"),
        (d[185], "S8"),  # TPEx; TWSE's 12 that day are a market-wide measure
        (d[197], "S19"),
    ]  # S3 on 103 is occupied; S6, S8 have no list; S21 is "O" only
    prices = {i: path(i) for i in (3, 11)}

    def net(sold: float, bought: float) -> float:
        return sold * (1 - 5e-4) / (bought * (1 + 5e-4)) - 1 - 58.5e-4

    first = trades[(d[100], "S3")]
    assert (first["fill_date"], first["exit_date"], first["exit_reason"]) == (
        d[101],
        d[105],  # the fill is day 1, the 5th session's close
        "time",
    )
    assert first["holding"] == 5 and first["stop"] is None and first["target"] is None
    assert first["net"] == pytest.approx(
        net(prices[3][105][3], prices[3][101][0]), rel=1e-12
    )
    assert first["short_margin_ratio"] == 400 / 1100
    assert trades[(d[105], "S3")]["fill_date"] == d[106]
    halted, locked = trades[(d[120], "S5")], trades[(d[130], "S9")]
    assert (halted["net"], halted["entry_reason"]) == (None, "not_tradable")
    assert (locked["net"], locked["entry_reason"]) == (None, "limit_up")
    assert halted["abandoned_date"] == d[121] and locked["abandoned_date"] == d[131]
    delayed = trades[(d[140], "S11")]
    assert (delayed["exit_date"], delayed["exit_reason"], delayed["limit_delayed"]) == (
        d[146],
        "time",
        True,
    )
    assert delayed["holding"] == 6
    assert delayed["net"] == pytest.approx(
        net(prices[11][146][0], prices[11][141][0]), rel=1e-12
    )
    gone = trades[(d[117], "S25")]
    assert (gone["exit_date"], gone["exit_reason"]) == (d[120], "delisted")
    end = trades[(d[197], "S19")]
    assert (end["exit_date"], end["exit_reason"]) == (d[199], "segment_end")
    assert result["abandon_reasons"] == {"limit_up": 1, "not_tradable": 1}
    assert result["entry_limit_blocked"] == 1
    assert result["listed"]["missing_list_days"] == {"TWSE": 0, "TPEx": 2}
    assert result["listed"]["years"] == {"2016": {"TWSE:signals": 9, "TPEx:signals": 1}}
    assert result["listed"]["market_wide"] == [
        {
            "date": d[185].isoformat(),
            "exchange": "TWSE",
            "new_x": 12,
            "list_members": 14,
        }
    ]
    assert result["exits"]["stop"] == result["exits"]["target"] == 0
    assert result["trades"] == 8 and result["signals"] == 10


def test_b2_excess_is_over_the_population_of_t(loaded, monkeypatch):
    days = trading_days()
    result = b2_run(loaded, monkeypatch)
    first = next(t for t in result["_trades"] if t["signal_date"] == days[100])
    s, e, x, last = 100, 101, 105, 199
    expected = tr.baseline(loaded.trade, s, e, x, last)
    assert first["population"] == expected["mean"]
    assert first["excess"] == pytest.approx(first["net"] - expected["mean"])
    members = lib.universe(loaded.panel, days[100], 1000)
    assert first["population_members"] == len(members)


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[199]),
            "validation": (days[200], days[279]),
            "used": (days[280], days[329]),
        },
    )
    floors = {"exploration": 100, "validation": 60}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], 61)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "B1,B2,B3"
) -> int:
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
                *extra,
            ]
        )  # fmt: skip
    )


def validate(db: Path, out: Path, report: Path | None, sha: str | None = None, url=URL):
    argv = ["--db", str(db), "--out", str(out), "--segment", "validation",
            "--min-free-gb", "0"]  # fmt: skip
    if report is not None:
        sha = sha if sha is not None else ex.file_sha256(report)
        argv += ["--exploration-report", str(report), "--exploration-sha256", sha]
        argv += ["--exploration-url", url]
    return one_process(lambda: tool.main(argv))


def read_json(path_: Path) -> dict:
    return json.loads(path_.read_text(encoding="utf-8"))


def refused(capsys) -> list[str]:
    return json.loads(capsys.readouterr().out)["refused"]


@pytest.fixture
def copied(fixture_db, tmp_path, monkeypatch) -> Path:
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    return db


@pytest.fixture
def explored(copied, tmp_path):
    out = tmp_path / "exploration"
    assert explore(copied, out) == 0
    return copied, out


def passed_report(out: Path, tmp_path: Path, *names: str) -> Path:
    data = read_json(out / "explore.json")
    for name in NAMES:
        data["hypotheses"][name]["verdict"] = (
            ex.EXPLORATION_PASSED if name in names else ex.EXPLORATION_FAILED
        )
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round9_research",
        "926",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (9, 3, 37)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.205)
    assert report["read_until"] == trading_days()[199].isoformat()
    assert report["hypotheses"]["B2"]["engine"] == "trade"
    assert report["hypotheses"]["B2"]["reason"] == "too_few_trade_days"
    assert report["hypotheses"]["B2"]["trades"] == 8
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 37 個" in text and "驗證段 t ≥ 3.205" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round9_research", 9, "exploration", 1) for name in NAMES]
    for name, files in (
        ("B1", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("B2", ("summary.md", "tables.json", "trades.csv", "days.csv")),
        ("B3", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
    ):
        for file in files:
            assert (out / name / file).is_file(), (name, file)
        summary = (out / name / "summary.md").read_text(encoding="utf-8")
        assert tool.DEGENERATE[name] in summary
    header = (out / "B3" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert header[0] == "signal_date,rank,exchange,symbol,close,limit_up,tie"
    assert [line.split(",")[0] for line in header[1:]] == [
        trading_days()[90].isoformat(),
        trading_days()[131].isoformat(),
    ]
    b2 = (out / "B2" / "summary.md").read_text(encoding="utf-8")
    assert "| 放棄：T+1 漲停鎖死 | 1 |" in b2 and "| 上櫃名單缺列" in b2


def test_b1_picks_the_highest_ratio_first(explored):
    _db, out = explored
    day = trading_days()[150].isoformat()
    lines = (out / "B1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "signal_date,rank,exchange,symbol,short_margin_ratio,tie"
    rows = [line.split(",") for line in lines[1:] if line.startswith(day)]
    values = [float(row[4]) for row in rows if row[4]]
    assert values == sorted(values, reverse=True) and len(rows) == 20
    assert rows[0][3] == "S23"  # 500 ÷ 1150


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="B2") == 2
    assert any("B2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_repository_ledger_refuses_the_exploration_too(copied, tmp_path, capsys):
    ex.write_ledger(
        ex.REPO_LEDGER,
        [
            {
                "hypothesis": "B3",
                "tool": "round9_research",
                "segment": "exploration",
                "version": 1,
            }
        ],
    )
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="B3") == 2
    assert any("B3 already in" in line for line in refused(capsys))


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="B1,Y1") == 2
    assert any("Y1 not registered" in line for line in refused(capsys))


def test_the_validation_needs_a_published_exploration_report(
    explored, tmp_path, capsys
):
    db, out = explored
    capsys.readouterr()
    assert validate(db, tmp_path / "v1", None) == 2
    assert any("needs --exploration-report" in line for line in refused(capsys))
    report = out / "explore.json"
    assert validate(db, tmp_path / "v2", report, sha="0" * 64) == 2
    assert any("not the published one" in line for line in refused(capsys))
    assert validate(db, tmp_path / "v3", report, url="https://example.com/x") == 2
    assert any("--exploration-url" in line for line in refused(capsys))
    for name in ("v1", "v2", "v3"):
        assert not (tmp_path / name).exists()


def test_the_validation_refuses_another_tools_report(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    data["design"] = "912"
    data["hypotheses"]["B1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_205(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "B1", "B2")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [
        ("B1", "round9_research", "finished"),
        ("B2", "round9_research", "finished"),
    ]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["B1", "B2"]
    assert validation["min_t"] == 3.205
    for name in ("B1", "B2"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["min_t"] == 3.205, name
    assert validation["read_until"] == trading_days()[279].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.205" in text
    capsys.readouterr()
    assert validate(db, tmp_path / "validation-2", report) == 2
    assert any("the validation runs once" in line for line in refused(capsys))
    assert not (tmp_path / "validation-2").exists()


def test_the_validation_needs_the_research_marker(explored, tmp_path, capsys):
    db, out = explored
    (db.parent / "research-db.json").unlink()
    capsys.readouterr()
    assert validate(db, tmp_path / "v", out / "explore.json") == 2
    assert any("research marker" in line for line in refused(capsys))


def test_a_passed_validation_lets_its_panel_go_before_the_used_segment(
    explored, tmp_path, monkeypatch
):
    """Only one panel at a time: the validation's is collected before the used
    segment is loaded (PR #905 review 7053124013), and the used segment of the
    passed hypothesis is written."""

    db, out = explored
    real_judge, real_load = ex.explore_judge, tool.load

    def judge(stage, *args, **kwargs):
        verdict = real_judge(stage, *args, **kwargs)
        return ex.PASSED if stage == "validation" else verdict

    loads: list[tuple] = []  # (start, end, weakref to the panel, earlier ones alive)

    def spy(db, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    report = passed_report(out, tmp_path, "B3")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    warmup = timedelta(days=tool.WARMUP_CALENDAR_DAYS)
    assert [(start, end) for start, end, _r, _a in loads] == [
        (days[200] - warmup, days[279]),
        (days[280] - warmup, days[329]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["B3"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["B3"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "B3" / "used" / file).is_file(), file
    assert "## 已用段" in (tmp_path / "validation" / "explore.md").read_text(
        encoding="utf-8"
    )


def test_coverage_only_computes_no_return(copied, tmp_path):
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity", '"net"'):
        assert word not in text
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    hyp = body["hypotheses"]
    days = 139  # signal dates 60 .. 198, all in 2016
    b1 = hyp["B1"]["coverage"]["2016"]
    assert b1["days"] == days
    # stock 4 has no chip row, 12 a margin of 0; 16 and 17 one null short each
    assert b1["missing"] == 2 * days + 2
    assert b1["zero"] == days  # stock 14
    b3 = hyp["B3"]["coverage"]["2016"]
    assert (b3["hits"], b3["max_hits"], b3["over_top_days"]) == (2, 1, 0)
    assert b3["missing"] == 1  # stock 5 on 122: the bar before is suspended
    b2 = hyp["B2"]["coverage"]
    year = b2["years"]["2016"]
    assert year["days"] == days
    twse, tpex = year["markets"]["TWSE"], year["markets"]["TPEx"]
    # the whole list: 3 three times, 5, 9, 11, 13, 15, 17, 19, 25, 23; 12 on 185
    assert (twse["new_x"], twse["max_new_x"], twse["market_wide_days"]) == (24, 12, 1)
    # the population, no occupancy: 3 on 103 counts; 17's ratio missing, 13's low;
    # 185: 12 x_start; 3, 5, 9, 11, 17, 19 (400) and 23 (500) of 1185 qualify,
    # excluded (13, 15 are below 0.3 there; 1, 7, 21 at 10 × id)
    assert (twse["x_start"], twse["ratio_missing"], twse["signals"]) == (24, 1, 10)
    assert twse["market_wide_signals"] == 7
    assert tpex.get("missing_list_days") == 2 and tpex["new_x"] == 1
    assert (tpex["signals"], tpex.get("market_wide_days", 0)) == (1, 0)
    assert b2["top_days"]["TWSE"][:2] == [
        {"date": trading_days()[185].isoformat(), "new_x": 12, "list_members": 14},
        {"date": trading_days()[150].isoformat(), "new_x": 3, "list_members": 14},
    ]
    assert {"", "X", "O", "OX"} <= set(b2["notes"])
    seconds = hyp["B2"]["seconds"]
    assert set(seconds) == {"plan", "x_start"} and seconds["plan"] >= 0
    assert set(hyp["B3"]["seconds"]) == {"plan", "limit_up_close"}
    assert set(hyp["B1"]["seconds"]) == {"plan", "short_margin_ratio"}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "margin_lists"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert "### B2 第 5、6 點：依年、依交易所" in md
    assert "名單新增 X 最多的 5 天" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "B1"]
        )  # fmt: skip


# --- the ledger must be writable (#899) -------------------------------------------

# A directory a non-root POSIX user cannot write, as the research volume
# mounted :ro is in the container; Windows and root ignore the mode (#899).
READ_ONLY = pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0,
    reason="a read-only directory needs a non-root POSIX user (CI's runner)",
)


def no_reads(monkeypatch) -> list:
    """Every sqlite3.connect from here on is recorded and fails."""

    opened: list = []

    def connect(*args, **kwargs):
        opened.append(args)
        raise AssertionError(f"the DB was opened: {args}")

    monkeypatch.setattr(sqlite3, "connect", connect)
    return opened


def unwritable(problems: list[str], db: Path) -> bool:
    # the only refusal: a run refused for another reason proves nothing here
    return len(problems) == 1 and all(
        str(db.parent / ex.LEDGER_NAME) in text
        and "not writable" in text
        and ":ro" in text
        and "第 2 步的工具" in text
        for text in problems
    )


def test_the_ledger_check_runs_through_the_exploration_gate(copied, monkeypatch):
    """Whatever the platform: the exploration's refusals include
    ``ledger_write_problem`` (#899), before anything is read."""

    monkeypatch.setattr(
        ex, "ledger_write_problem", lambda db: "the ledger is not writable"
    )
    opened = no_reads(monkeypatch)
    assert explore(copied, copied.parent / "out", hypotheses="B1") == 2
    assert opened == [] and not (copied.parent / "out").exists()


@READ_ONLY
def test_a_read_only_ledger_folder_refuses_the_exploration_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    opened = no_reads(monkeypatch)
    out = tmp_path / "out"
    copied.parent.chmod(0o555)
    try:
        assert explore(copied, out, hypotheses="B1") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "B1")
    ledger = db.parent / ex.LEDGER_NAME
    before = ledger.read_bytes()
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    db.parent.chmod(0o555)
    ledger.chmod(0o444)
    try:
        assert validate(db, tmp_path / "v", report) == 2
    finally:
        ledger.chmod(0o644)
        db.parent.chmod(0o755)
    assert unwritable(refused(capsys), db)
    assert opened == [] and not (tmp_path / "v").exists()
    assert ledger.read_bytes() == before


@READ_ONLY
def test_coverage_only_runs_on_a_read_only_ledger_folder(copied, tmp_path):
    out = tmp_path / "coverage"
    copied.parent.chmod(0o555)
    try:
        assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    finally:
        copied.parent.chmod(0o755)
    assert (out / "coverage.json").is_file()
