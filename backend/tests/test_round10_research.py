"""tools/research/round10_research.py: the registered F1～F4 (#936).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十輪：F1～F4.  The features are checked on hand-made
series (the expected numbers worked out in the test); F1 and F4's trades and
the gate ("each once") run on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 400 sessions, everything else is the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import statistics
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
    CorporateAction,
    IngestionRun,
    Instrument,
    MarginList,
    MarketBar,
    RawPayload,
)
from app.strategies import levels

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/936#issuecomment-1"
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
r9 = _tool("round9_research")
tool = _tool("round10_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("F1", "F2", "F3", "F4")


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in (
        "mainstream_research",
        *(f"round{n}_research" for n in range(4, 10)),
    ):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    otc = date(2007, 12, 3)
    f1, f2, f3, f4 = (h[name] for name in NAMES)
    for spec, event, hold in ((f1, "stock_div_ex", 60), (f4, "margin_first", 20)):
        assert (spec["engine"], spec["kind"], spec["event"], spec["hold"]) == (
            "trade",
            "event",
            event,
            hold,
        )
        assert (spec["stop"], spec["target"], spec["market_filter"]) == (
            None,
            None,
            False,
        )
        assert spec["entry_days"] == 1 and spec["start"] == ("session", otc, 20)
    assert (f2["engine"], f2["half"], f2["ranks"], f2["score"]) == (
        "portfolio",
        ("vol_720", "low"),
        (("cash_yield_12m", "high"), ("mom_240_20", "high")),
        "low",
    )
    assert (f2["top"], f2["hold"], f2["start"]) == (20, 60, ("session", otc, 721))
    assert (f3["engine"], f3["conditions"], f3["keys"]) == (
        "portfolio",
        ("drawdown_60", "margin_drop_5"),
        (("margin_drop_5", "low"),),
    )
    assert (f3["top"], f3["hold"], f3["start"]) == (20, 20, ("session", otc, 60))


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        10,
        4,
        41,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.234
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(41), 3) == 3.234
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.MIN_DAYS == 60 and tool.OVERLAP == 20
    assert tool.REGISTRATION_COMMIT == "e495fa70"
    assert (tool.STOCK_DIV_MIN, tool.VOL_WINDOW, tool.MOM_FAR, tool.MOM_NEAR) == (
        0.05,
        720,
        240,
        20,
    )
    assert (tool.DRAWDOWN_WINDOW, tool.DRAWDOWN_MAX, tool.MARGIN_LAG) == (60, -0.22, 5)
    assert (tool.MARGIN_DROP_MAX, tool.MIN_BARS) == (-0.10, 20)
    assert tool.LOW_VOL_SHARE == Fraction(1, 2) and tool.RANK_WEIGHTS == (1, 1)
    # the exit without a stop or a target is round9_research's
    assert tool.NO_STOP == r9.NO_STOP and tool.enter_next_open is r9.enter_next_open


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """PR #930 review 7057395065: each value that changes a verdict changes
    the hash — thresholds, windows, exchanges, orders, the composite rule."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.234
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.205),
        (tool, "STOCK_DIV_MIN", 0.04),
        (tool, "VOL_WINDOW", 719),
        (tool, "VOL_DDOF", 0),
        (tool, "LOW_VOL_SHARE", Fraction(1, 3)),
        (tool, "RANK_WEIGHTS", (2, 1)),
        (tool, "MOM_FAR", 250),
        (tool, "MOM_NEAR", 21),
        (tool, "DRAWDOWN_WINDOW", 59),
        (tool, "DRAWDOWN_MAX", -0.2),
        (tool, "MARGIN_LAG", 4),
        (tool, "MARGIN_DROP_MAX", -0.11),
        (tool, "MIN_BARS", 19),
        (tool, "MARKETS", {"TWSE": "上市"}),
        (tool, "NO_STOP", -1e9),
        (tool, "MIN_DAYS", 50),
        (tool, "MIN_LOTS", 500),
        (r5, "YIELD_CALENDAR_DAYS", 366),
        (er, "LIMIT_BEFORE_WIDENING", Fraction(1, 10)),
        (er, "LIMIT_WIDENED_ON", date(2015, 6, 2)),
        (er, "LIMIT", Fraction(1, 20)),
        (tool, "HYPOTHESES", _swap("F2", "half", ("vol_720", "high"))),
        (
            tool,
            "HYPOTHESES",
            _swap("F2", "ranks", (("cash_yield_12m", "low"), ("mom_240_20", "high"))),
        ),
        (tool, "HYPOTHESES", _swap("F2", "score", "high")),
        (tool, "HYPOTHESES", _swap("F3", "keys", (("margin_drop_5", "high"),))),
        (tool, "HYPOTHESES", _swap("F1", "hold", 59)),
        (tool, "HYPOTHESES", _swap("F4", "hold", 21)),
        (tool, "HYPOTHESES", _swap("F2", "top", 19)),
        (tool, "HYPOTHESES", _swap("F3", "top", 19)),
        (tool, "HYPOTHESES", _swap("F1", "start", ("session", date(2007, 12, 3), 21))),
        (tool, "HYPOTHESES", _swap("F2", "start", ("session", date(2007, 12, 3), 720))),
        (tool, "HYPOTHESES", _swap("F3", "start", ("session", date(2007, 12, 3), 61))),
        (tool, "HYPOTHESES", _swap("F4", "start", ("session", date(2007, 12, 4), 20))),
        (tool, "NEAR", 0.0),
        (tool, "LOAD_RULE", "the warm-up before a later segment"),
        (tool, "LOAD_FROM", date(2004, 1, 1)),
        (tool, "MIN_T", 1.96),
        (
            tool,
            "SEGMENTS",
            {**tool.SEGMENTS, "validation": (date(2020, 1, 3), date(2024, 9, 27))},
        ),
        (tool, "MIN_SEGMENT_DAYS", {"exploration": 400, "validation": 250}),
        (tool, "OVERLAP", 10),
        (pr, "SLIPPAGE", 0.001),
        (pr, "FEE", 0.001),
        (pr, "TAX", 0.0015),
        (tr, "SLIPPAGE", 0.001),
        (tr, "COST_BPS", 60.0),
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


# AC-1: measured on master e495fa70 before this tool existed.
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
    "round8_research": (
        1,
        "cd00cd2d201893370ec706168af5a30cb8e1e684c47ba30fc91356447876d757",
    ),
    "round9_research": (
        1,
        "1a79970f76ed6e92884000623ab38e61eae3f201ff10a457d5dead96b5858680",
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
    section = text.split("**第十輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    assert tool.OVERLAP_NOTE in section
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "tools/research/round10_research.py" in section
    assert "本輪 4 個、累計 41 個" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes, suspended=(), instrument_id=1, chips=None):
    item = lib.Series(instrument_id)
    days = weekdays(date(2016, 1, 4), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at)
        for name in ("open", "high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(2_000_000.0)
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    item.chips = {name: array("d", values) for name, values in (chips or {}).items()}
    return item


def bare_ctx(**extra):
    return SimpleNamespace(prefix={}, seconds=Counter(), **extra)


# --- F1: stock_div_ex --------------------------------------------------------------


def action(day: date, ratio):
    return SimpleNamespace(action_date=day, stock_dividend_ratio=ratio)


def test_stock_div_ex_is_t_with_a_ratio_of_at_least_0_05():
    sessions = weekdays(date(2016, 3, 7), 10)  # Monday 2016-03-07 ..
    holders = {
        1: SimpleNamespace(actions=[action(sessions[2], 0.05)]),  # exactly 50 per 1,000
        2: SimpleNamespace(actions=[action(sessions[2], 0.0499)]),
        3: SimpleNamespace(actions=[action(sessions[2], None)]),
        # two rows on one day: the largest; a null among them does not hide it
        4: SimpleNamespace(
            actions=[
                action(sessions[2], 0.03),
                action(sessions[2], None),
                action(sessions[2], 0.06),
            ]
        ),
        # a Saturday counts on the next session (Monday 2016-03-14)
        5: SimpleNamespace(actions=[action(date(2016, 3, 12), 0.1)]),
    }
    ctx = SimpleNamespace(stock_div=tool.stock_dividends(sessions, holders))
    item = {i: make_item([10.0], instrument_id=i) for i in holders}
    assert tool.stock_div_ex(ctx, item[1], 2) is True
    assert tool.stock_div_ex(ctx, item[2], 2) is False
    assert tool.stock_div_ex(ctx, item[3], 2) is None  # null: does not qualify
    assert ctx.stock_div[4][2] == 0.06 and tool.stock_div_ex(ctx, item[4], 2) is True
    assert sessions[5] == date(2016, 3, 14)
    assert tool.stock_div_ex(ctx, item[5], 5) is True
    assert tool.stock_div_ex(ctx, item[5], 4) is False  # no row on that session
    assert tool.stock_div_ex(ctx, item[1], 3) is False


def test_the_coverage_lists_the_rows_with_all_three_fields_null_apart():
    sessions = weekdays(date(2016, 3, 7), 5)

    def row(cash, ratio, split=None):
        return SimpleNamespace(
            action_date=sessions[1],
            cash_dividend=cash,
            stock_dividend_ratio=ratio,
            split_ratio=split,
        )

    holders = {
        1: SimpleNamespace(actions=[row(None, None)]),  # all three null
        2: SimpleNamespace(actions=[row(1.5, None)]),  # cash only: ratio null too
        3: SimpleNamespace(actions=[row(None, 0.05)]),
    }
    assert tool.blank_actions(sessions, holders) == {(1, 1)}
    div = tool.stock_dividends(sessions, holders)
    assert div == {1: {1: None}, 2: {1: None}, 3: {1: 0.05}}


# --- F2: vol_720, mom_240_20, the composite order, the overlap ----------------------


def closes_of(count: int, salt: str = "") -> list[float]:
    out, price = [], 50.0
    for k in range(count):
        digest = hashlib.sha256(f"{salt}{k}".encode()).digest()
        price *= 1 + (digest[0] / 255.0 - 0.5) * 0.04
        out.append(round(price, 2))
    return out


def test_vol_720_is_the_sample_deviation_of_720_returns():
    closes = closes_of(730)
    item = make_item(closes)
    at = 725
    window = closes[at - 720 : at + 1]
    returns = [window[k] / window[k - 1] - 1 for k in range(1, 721)]
    assert len(returns) == 720
    expected = statistics.stdev(returns)  # ddof 1
    assert tool.vol_720(bare_ctx(), item, at) == pytest.approx(expected, rel=1e-9)
    assert tool.vol_720(bare_ctx(), item, 720) == pytest.approx(
        statistics.stdev([closes[k] / closes[k - 1] - 1 for k in range(1, 721)]),
        rel=1e-9,
    )
    assert tool.vol_720(bare_ctx(), item, 719) is None  # 720 closes only


@pytest.mark.parametrize("bad", [5, 300, 725])  # first, middle and T of the 721
def test_vol_720_is_missing_with_a_suspended_bar_or_a_missing_close(bad):
    closes = closes_of(730)
    at = 725
    assert tool.vol_720(bare_ctx(), make_item(closes, suspended=(bad,)), at) is None
    holed = list(closes)
    holed[bad] = NAN
    assert tool.vol_720(bare_ctx(), make_item(holed), at) is None
    holed[bad] = 0.0
    assert tool.vol_720(bare_ctx(), make_item(holed), at) is None
    # outside the window it does not matter
    assert tool.vol_720(bare_ctx(), make_item(closes, suspended=(4,)), at) is not None


def test_mom_240_20_is_the_12_1_month_return():
    closes = [10.0 + 0.01 * k for k in range(300)]
    item = make_item(closes)
    at = 290
    assert tool.mom_240_20(item, at) == pytest.approx(closes[270] / closes[50] - 1)
    assert tool.mom_240_20(item, 240) == pytest.approx(closes[220] / closes[0] - 1)
    assert tool.mom_240_20(item, 239) is None


@pytest.mark.parametrize("bad", [50, 270])
def test_mom_240_20_is_missing_with_either_end_suspended_missing_or_not_positive(bad):
    closes = [10.0 + 0.01 * k for k in range(300)]
    assert tool.mom_240_20(make_item(closes, suspended=(bad,)), 290) is None
    for value in (NAN, 0.0, -1.0):
        holed = list(closes)
        holed[bad] = value
        assert tool.mom_240_20(make_item(holed), 290) is None
    # a bar between the ends does not matter
    assert tool.mom_240_20(make_item(closes, suspended=(100,)), 290) is not None


def f2_rank(monkeypatch, values: dict[int, tuple], day=date(2016, 3, 1)):
    """``values``: id -> (vol_720, cash_yield_12m, mom_240_20)."""

    monkeypatch.setattr(
        tool, "vol_720", lambda ctx, item, at: values[item.instrument_id][0]
    )
    monkeypatch.setattr(
        r5,
        "cash_yield_parts",
        lambda ctx, item, at: r5.Yield(values[item.instrument_id][1], False, False),
    )
    monkeypatch.setattr(
        tool, "mom_240_20", lambda item, at: values[item.instrument_id][2]
    )
    members = [(make_item([10.0], instrument_id=i), 0) for i in values]
    ctx = bare_ctx(yields=None)
    return tool.rank_f2(ctx, tool.HYPOTHESES["F2"], day, members)


def test_the_low_volatility_half_is_ceil_n_over_2_of_those_with_a_value(monkeypatch):
    # 5 with vol_720, 2 missing: the half is the 3 smallest (⌈5 ÷ 2⌉)
    values = {
        1: (0.010, 0.05, 0.1),
        2: (0.030, 0.01, 0.1),
        3: (0.020, 0.02, 0.1),
        4: (0.050, 0.09, 0.9),
        5: (0.040, 0.08, 0.8),
        6: (None, 0.99, 0.99),
        7: (None, 0.99, 0.99),
    }
    ranked = f2_rank(monkeypatch, values)
    assert ranked.half == 3
    assert {row[0] for row in ranked.rows} == {1, 2, 3}
    assert ranked.missing["vol_720"] == 2
    even = f2_rank(monkeypatch, {i: (0.01 * i, 0.0, 0.0) for i in range(1, 5)})
    assert even.half == 2 and {row[0] for row in even.rows} == {1, 2}


def test_the_ranks_are_in_the_half_and_the_mean_rank_is_small_first(monkeypatch):
    day = date(2016, 3, 1)
    # the half (vol smallest 4 of 7): 1, 2, 3, 4
    values = {
        1: (0.01, 0.04, 0.10),  # cash rank 2, mom rank 3 → 2.5
        2: (0.02, 0.05, None),  # cash 1, mom missing → 4 (the half's size) → 2.5
        3: (0.03, None, 0.30),  # cash missing → 4, mom 1 → 2.5
        4: (0.04, 0.01, 0.20),  # cash 3, mom 2 → 2.5
        5: (0.05, 0.99, 0.99),  # outside the half: not ranked at all
        6: (0.06, 0.99, 0.99),
        7: (0.07, 0.99, 0.99),
    }
    ranked = f2_rank(monkeypatch, values, day)
    assert ranked.half == 4
    got = {row[0]: (row[1]["r1"], row[1]["r2"], row[1]["score"]) for row in ranked.rows}
    assert got == {1: (2, 3, 2.5), 2: (1, 4, 2.5), 3: (4, 1, 2.5), 4: (3, 2, 2.5)}
    # all 2.5: the hash decides
    assert [row[0] for row in ranked.rows] == sorted(
        (1, 2, 3, 4), key=lambda i: pr.tie_break(day, i)
    )
    clear = {
        1: (0.01, 0.09, 0.9),  # 1, 1 → 1
        2: (0.02, 0.08, 0.1),  # 2, 3 → 2.5
        3: (0.03, 0.01, 0.8),  # 3, 2 → 2.5
        4: (0.04, 0.99, 0.99),  # 4～6 are outside the half (⌈6 ÷ 2⌉ = 3)
        5: (0.05, 0.99, 0.99),
        6: (0.06, 0.99, 0.99),
    }
    ranked = f2_rank(monkeypatch, clear, day)
    assert ranked.half == 3
    tied = sorted((2, 3), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == [1, *tied]
    assert [row[1]["score"] for row in ranked.rows] == [1.0, 2.5, 2.5]


def test_the_overlap_is_over_f2s_names_and_skips_days_without_a_list():
    assert tool.overlap_share([1, 2, 3], {2, 3, 9}) == pytest.approx(2 / 3)
    assert tool.overlap_share([1, 2], {1, 2, 3, 4}) == 1.0  # F2's 2, not 20
    assert tool.overlap_share([], {1}) is None
    assert tool.overlap_share([1], set()) is None
    summary = tool.overlap_summary({"2016": [0.5, 1.0], "2017": [0.0]})
    assert summary["days"] == 3 and summary["mean"] == pytest.approx(0.5)
    assert summary["years"]["2016"] == {"days": 2, "mean": 0.75}


def test_x2s_list_is_explore_researchs_definition(monkeypatch):
    calls = []

    def fake(ctx, spec, day, members):
        calls.append(spec)
        return [(i, {}, "") for i in range(30)], {}

    monkeypatch.setattr(ex, "_rank", fake)
    ctx = SimpleNamespace(base=None, seconds=Counter())
    names = tool.x2_names(ctx, date(2016, 3, 1), [])
    assert calls == [ex.HYPOTHESES["X2"]] and names == set(range(20))


# --- F3: drawdown_60, margin_drop_5 -------------------------------------------------


def f3_item(closes, margins):
    return make_item(closes, chips={"margin_balance": margins})


def test_drawdown_60_and_margin_drop_5_by_hand():
    closes = [100.0] * 30 + [120.0] + [100.0] * 28 + [90.0]  # 60 bars, peak 120
    item = f3_item(closes, [1000.0] * 55 + [800.0] * 5)
    assert tool.drawdown_60(bare_ctx(), item, 59) == pytest.approx(90 / 120 - 1)
    assert tool.margin_drop_5(item, 59) == pytest.approx(800 / 1000 - 1)
    assert tool.drawdown_60(bare_ctx(), item, 58) is None  # 59 bars
    # the peak 61 bars back is out of the window
    longer = f3_item([200.0] + closes, [1000.0] * 61)
    assert tool.drawdown_60(bare_ctx(), longer, 60) == pytest.approx(90 / 120 - 1)


def test_both_conditions_at_exactly_minus_0_22_and_minus_0_10_qualify():
    closes = [100.0] * 59 + [78.0]  # 78 ÷ 100 − 1 is −0.22 (the float is −0.21999…)
    assert 78.0 / 100.0 - 1 != -0.22
    margins = [1000.0] * 55 + [900.0] * 5  # 900 ÷ 1000 − 1 = −0.1
    ok, dd, md = tool.f3_qualifies(bare_ctx(), f3_item(closes, margins), 59)
    assert ok and dd == pytest.approx(-0.22) and md == pytest.approx(-0.10)
    above = tool.f3_qualifies(bare_ctx(), f3_item(closes[:-1] + [78.01], margins), 59)
    assert above[0] is False
    margins_above = [1000.0] * 55 + [901.0] * 5
    assert tool.f3_qualifies(bare_ctx(), f3_item(closes, margins_above), 59)[0] is False


@pytest.mark.parametrize(
    "now, before",
    [(NAN, 1000.0), (800.0, NAN), (800.0, 0.0), (0.0, 0.0), (800.0, -1.0)],
)
def test_margin_drop_5_is_missing_without_a_row_a_balance_or_with_m5_not_positive(
    now, before
):
    margins = [1000.0] * 54 + [before] + [1000.0] * 4 + [now]
    item = f3_item([100.0] * 59 + [70.0], margins)
    assert tool.margin_drop_5(item, 59) is None
    ok, dd, md = tool.f3_qualifies(bare_ctx(), item, 59)
    assert (ok, md) == (False, None) and dd is not None


def test_margin_drop_5_is_missing_without_the_chip_arrays():
    assert tool.margin_drop_5(make_item([100.0] * 60), 59) is None


def test_drawdown_60_is_missing_with_a_close_missing():
    closes = [100.0] * 59 + [70.0]
    closes[10] = NAN
    item = f3_item(closes, [1000.0] * 55 + [800.0] * 5)
    assert tool.drawdown_60(bare_ctx(), item, 59) is None
    assert tool.f3_qualifies(bare_ctx(), item, 59)[0] is False


def test_f3_is_margin_drop_small_first_and_fewer_than_20_leave_cash():
    day = date(2016, 3, 2)
    closes = [100.0] * 59 + [70.0]
    drops = {i: 900.0 - 10 * i for i in range(1, 6)}  # 5 qualify
    items = [
        make_item(
            closes, instrument_id=i, chips={"margin_balance": [1000.0] * 55 + [m] * 5}
        )
        for i, m in drops.items()
    ]
    flat = make_item(
        [100.0] * 60,
        instrument_id=9,
        chips={"margin_balance": [1000.0] * 55 + [500.0] * 5},
    )
    ctx = bare_ctx()
    ranked = tool.rank_f3(
        ctx, tool.HYPOTHESES["F3"], day, [(i, 59) for i in [*items, flat]]
    )
    assert [row[0] for row in ranked.rows] == [5, 4, 3, 2, 1]  # the largest drop first
    assert ranked.hits == 5
    picks = {1: [row[0] for row in ranked.rows]}
    quote = lambda i, s: pr.Quote(70.0, 70.0, True)  # noqa: E731
    spec = tool.HYPOTHESES["F3"]
    simulated = pr.simulate(picks, quote, 1, 1, spec["hold"], spec["top"])
    # the account of the day holds 1/20 of the equity; 5 of its 20 shares bought
    assert simulated.bought[0] == pytest.approx(5 * (1 / 20) / 20)


# --- F4: margin_first ---------------------------------------------------------------

LD = weekdays(date(2016, 1, 4), 60)


def runs_ctx(lists: dict[tuple[str, str], list[tuple[int, int]]], present=None, **life):
    """Hand-made runs on LD (index pairs), TWSE's first list on LD[0]."""

    out = tool.MarginRuns()
    for exchange in ("TWSE", "TPEx"):
        out.first_day[exchange] = LD[0]
        for k, day in enumerate(LD):
            if present is None or (exchange, k) in present:
                out.present.add((exchange, day))
    out.runs = {key: [(LD[a], LD[b]) for a, b in runs] for key, runs in lists.items()}
    symbols = {1: ("TWSE", "A", ""), 2: ("TWSE", "B", ""), 3: ("TWSE", "C", "")}
    symbols |= {4: ("TPEx", "D", ""), 5: ("TWSE", "D", "")}
    panel = SimpleNamespace(sessions=LD, symbols=symbols)
    starts = {i: LD[k] for i, k in life.get("life", {}).items()}
    return SimpleNamespace(panel=panel, lists=out, life_start=starts, entries={})


def series_from(first: int, instrument_id: int) -> lib.Series:
    item = make_item([10.0] * (len(LD) - first), instrument_id=instrument_id)
    item.dates = LD[first:]
    item.position = {day: k for k, day in enumerate(item.dates)}
    return item


def test_margin_first_is_the_first_list_with_20_bars_before():
    ctx = runs_ctx(
        {
            ("TWSE", "A"): [(30, 59)],
            ("TWSE", "B"): [(0, 59)],
            ("TWSE", "C"): [(15, 59)],
        },
        life={1: 0, 2: 0, 3: 0},
    )
    a, b, c = (series_from(0, i) for i in (1, 2, 3))
    assert tool.margin_first(ctx, a, 30, 30) is True
    assert tool.margin_first(ctx, a, 31, 31) is False  # only the first day
    assert tool.margin_first(ctx, a, 29, 29) is False
    assert tool.margin_first(ctx, b, 0, 0) is None  # no list the session before
    assert tool.margin_first(ctx, b, 30, 30) is False  # on the exchange's first list
    # 15 bars before T: not
    assert tool.margin_first(ctx, c, 15, 15) is False
    ctx20 = runs_ctx({("TWSE", "C"): [(20, 59)]}, life={3: 0})
    assert tool.margin_first(ctx20, c, 20, 20) is True  # exactly 20 bars before
    ctx19 = runs_ctx({("TWSE", "C"): [(19, 59)]}, life={3: 0})
    assert tool.margin_first(ctx19, c, 19, 19) is False


def test_margin_first_does_not_count_a_return_to_the_list():
    ctx = runs_ctx({("TWSE", "A"): [(25, 30), (40, 59)]}, life={1: 0})
    a = series_from(0, 1)
    assert tool.margin_first(ctx, a, 25, 25) is True
    assert tool.margin_first(ctx, a, 40, 40) is False


def test_margin_first_makes_no_signal_without_ts_or_the_session_befores_list():
    present = {(ex_, k) for ex_ in ("TWSE", "TPEx") for k in range(60)} - {("TWSE", 29)}
    ctx = runs_ctx({("TWSE", "A"): [(30, 59)]}, present=present, life={1: 0})
    a = series_from(0, 1)
    assert tool.margin_first(ctx, a, 30, 30) is None  # 29 has no list
    present -= {("TWSE", 30)}
    ctx = runs_ctx({("TWSE", "A"): [(31, 59)]}, present=present, life={1: 0})
    assert tool.margin_first(ctx, a, 31, 31) is None  # T's list missing the day before


def test_margin_first_counts_a_transferred_companys_bars_from_the_transfer():
    # D on TPEx from the first list (instrument 4) to 20; on TWSE (instrument 5,
    # first bar 21) from 35: 14 bars before T on the new instrument, not 35
    ctx = runs_ctx(
        {("TPEx", "D"): [(0, 20)], ("TWSE", "D"): [(35, 59)]}, life={4: 0, 5: 21}
    )
    new = series_from(21, 5)
    assert tool.first_entry(ctx, new) == LD[35]
    assert tool.margin_first(ctx, new, 35, new.position[LD[35]]) is False
    later = runs_ctx({("TWSE", "D"): [(45, 59)]}, life={5: 21})
    assert tool.margin_first(later, new, 45, new.position[LD[45]]) is True  # 24 bars


def test_margin_first_ignores_another_companys_runs_before_the_first_bar():
    # symbol A was used by another company (on 5～10), this instrument's bars
    # start on 20 and it is first on the list on 45
    ctx = runs_ctx({("TWSE", "A"): [(5, 10), (45, 59)]}, life={1: 20})
    item = series_from(20, 1)
    assert tool.first_entry(ctx, item) == LD[45]
    on_at_start = runs_ctx({("TWSE", "A"): [(5, 59)]}, life={1: 20})
    assert tool.first_entry(on_at_start, item) is None  # already on it


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
        (3.205, "前瞻觀察"),  # round 9's threshold is not this round's
        (3.233, "前瞻觀察"),
        (3.234, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_234(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


def test_the_starts_are_the_registered_sessions_from_the_otc_2007_12_03():
    sessions = weekdays(date(2007, 11, 26), 900)
    otc = weekdays(date(2007, 12, 3), 721)
    for name, n in (("F1", 20), ("F2", 721), ("F3", 60), ("F4", 20)):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == otc[n - 1], name


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 400
STOCKS = range(1, 25)
DELISTED = {25: 120, 27: 300}  # the last bar's index
TRANSFERRED = {26: 180}
NEW = {31: 100, 33: 100, 36: 181}  # the first bar's index
NEW_SYMBOLS = {36: "S26"}  # 26 moved from TPEx to TWSE
INDEX_ID = 90
NO_CHIPS = 4  # a TPEx stock without any chip row
CRASH = 12  # F3: flat to 199, −9% on 200～202, its margin 800 from 198
# F1: (stock, signal index, ratio, action_type); 3 is occupied on 130
ACTIONS = [
    (3, 100, 0.05, "stock_dividend"),
    (3, 130, 0.08, "stock_dividend"),
    (5, 100, 0.0499, "stock_dividend"),  # below
    (7, 100, None, "stock_dividend"),  # null
    (9, 105, 0.03, "stock_dividend"),
    (9, 105, 0.06, "capital_reserve"),  # the largest of the day
    (13, 120, 0.05, "stock_dividend"),  # T+1 suspended
    (15, 140, 0.05, "stock_dividend"),  # T+1 locked at limit up
    (17, 150, 0.05, "stock_dividend"),  # the 60th session locked at limit down
    (19, 230, 0.05, "stock_dividend"),  # the exploration ends on 249
    (25, 80, 0.05, "stock_dividend"),  # delisted after 120
    (6, 110, 0.05, "stock_dividend"),  # TPEx
]
SATURDAY = (11, 0.07)  # an action on a Saturday: T is the Monday after
SUSPENDED = (13, 121)
LOCKED_UP = (15, 141)
LOCKED_DOWN = (17, 210)
# F4: the sessions each stock is on its exchange's list (all others from 0)
OFF_LIST = {
    21: lambda t: t >= 150,  # first on 150
    23: lambda t: 120 <= t <= 130 or t >= 140,  # first on 120, back on 140
    31: lambda t: t >= 110,  # 10 bars before: no
    33: lambda t: t >= 125,  # 25 bars before
    36: lambda t: t >= 205,  # the transferred one: 24 bars on TWSE
    8: lambda t: t >= 161,  # TPEx: no list on 160, so 161 has none before it
    10: lambda t: t >= 170,  # TPEx
    26: lambda t: t <= 180,
}
TPEX_MISSING = 160


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), SESSIONS)


def saturday_index() -> int:
    days = trading_days()
    return next(t for t in range(160, 200) if days[t].weekday() == 0)


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
        if i == CRASH:
            close = round(previous * 0.91, 2) if 200 <= t <= 202 else previous
            out.append(
                (previous, previous, close, close) if close < previous else (close,) * 4
            )
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
    if i == CRASH:
        return 800.0 if t >= 198 else 1000.0 + t
    return 1000.0 + t


def exchange_of(i: int) -> str:
    if i in NEW_SYMBOLS:
        return "TWSE"
    return "TWSE" if i % 2 else "TPEx"


def symbol_of(i: int) -> str:
    return NEW_SYMBOLS.get(i, f"S{i}")


def build(path_: Path) -> Path:
    engine = create_engine(f"sqlite:///{path_}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ends = {**DELISTED, **TRANSFERRED}
    ids = [*STOCKS, *ends, *NEW]
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
                    "symbol": symbol_of(i),
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
                if t < NEW.get(i, 0):
                    continue
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
                            "short_balance": 10.0,
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
        actions = [
            {
                "instrument_id": i,
                "action_date": days[t],
                "action_type": kind,
                "stock_dividend_ratio": ratio,
                "cash_dividend": None,
                "source": "test",
            }
            for i, t, ratio, kind in ACTIONS
        ]
        saturday = days[saturday_index()] - timedelta(days=2)
        actions.append(
            {
                "instrument_id": SATURDAY[0],
                "action_date": saturday,
                "action_type": "stock_dividend",
                "stock_dividend_ratio": SATURDAY[1],
                "cash_dividend": None,
                "source": "test",
            }
        )
        # a cash dividend only: its ratio is null too (listed apart from S7's row)
        actions.append(
            {
                "instrument_id": 1,
                "action_date": days[90],
                "action_type": "cash_dividend",
                "cash_dividend": 1.0,
                "stock_dividend_ratio": None,
                "source": "test",
            }
        )
        db.execute(insert(CorporateAction), actions)
        rows = []
        for exchange in ("TWSE", "TPEx"):
            mine = [i for i in ids if exchange_of(i) == exchange]
            for t, day in enumerate(days):
                if exchange == "TPEx" and t == TPEX_MISSING:
                    continue
                members = {
                    symbol_of(i): ""
                    for i in mine
                    if OFF_LIST.get(i, lambda _t: True)(t)
                }
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
    return build(tmp_path_factory.mktemp("round10") / "stock.db")


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
    assert loaded.yields.base is loaded.base
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw-tr")
    other = one_process(lambda: tr.load(fixture_db, date(1990, 1, 1), days[-1], raw))
    assert loaded.trade.statuses == other.statuses
    assert loaded.trade.last_bar == other.last_bar
    assert loaded.trade.last_bar[25] == days[120]


def test_the_actions_and_the_lists_are_read(loaded):
    days = trading_days()
    div = loaded.stock_div
    assert div[3] == {100: 0.05, 130: 0.08}
    assert div[9] == {105: 0.06} and div[7] == {100: None}
    assert div[SATURDAY[0]] == {saturday_index(): SATURDAY[1]}
    runs = loaded.lists.runs
    assert runs[("TWSE", "S23")] == [(days[120], days[130]), (days[140], days[-1])]
    assert runs[("TWSE", "S1")] == [(days[0], days[-1])]
    assert runs[("TPEx", "S26")] == [(days[0], days[180])]
    assert runs[("TWSE", "S26")] == [(days[205], days[-1])]
    assert not loaded.lists.has("TPEx", days[TPEX_MISSING])
    assert loaded.lists.first_day == {"TWSE": days[0], "TPEx": days[0]}
    assert loaded.life_start[36] == days[181] and loaded.life_start[1] == days[0]


def used_run(loaded, monkeypatch, name: str) -> dict:
    """``name`` on the signal dates 59 .. 248, the last session 249 (the used
    segment's rules: no floor, no delisted check; nothing else differs)."""

    days = trading_days()
    monkeypatch.setattr(
        tool, "SEGMENTS", {**tool.SEGMENTS, "used": (days[60], days[249])}
    )
    loaded.trade.baselines.clear()
    loaded.trade.universes.clear()
    return tool.run_trades(loaded, Path("unused"), name, "used")


def net(sold: float, bought: float) -> float:
    return sold * (1 - 5e-4) / (bought * (1 + 5e-4)) - 1 - 58.5e-4


def test_f1_trades_by_hand(loaded, monkeypatch):
    d = trading_days()
    result = used_run(loaded, monkeypatch, "F1")
    trades = {(t["signal_date"], t["symbol"]): t for t in result["_trades"]}
    monday = saturday_index()
    assert sorted(trades) == sorted(
        [
            (d[80], "S25"),
            (d[100], "S3"),  # exactly 0.05; S5 below, S7 null
            (d[105], "S9"),  # the larger of the day's two rows
            (d[110], "S6"),
            (d[120], "S13"),
            (d[140], "S15"),
            (d[150], "S17"),
            (d[monday], "S11"),  # the Saturday's action
            (d[230], "S19"),
        ]
    )  # S3 on 130 is occupied (held 101 .. 160)
    s3 = loaded.panel.series[3]
    first = trades[(d[100], "S3")]
    assert (first["fill_date"], first["exit_date"], first["exit_reason"]) == (
        d[101],
        d[160],  # the fill is day 1, the 60th session's close
        "time",
    )
    assert first["holding"] == 60 and first["stop"] is None and first["target"] is None
    assert first["net"] == pytest.approx(
        net(s3.close[s3.position[d[160]]], s3.open[s3.position[d[101]]]), rel=1e-12
    )
    assert first["stock_dividend_ratio"] == 0.05
    halted, locked = trades[(d[120], "S13")], trades[(d[140], "S15")]
    assert (halted["net"], halted["entry_reason"]) == (None, "not_tradable")
    assert (locked["net"], locked["entry_reason"]) == (None, "limit_up")
    assert halted["abandoned_date"] == d[121] and locked["abandoned_date"] == d[141]
    delayed = trades[(d[150], "S17")]
    assert (delayed["exit_date"], delayed["exit_reason"], delayed["limit_delayed"]) == (
        d[211],
        "time",
        True,
    )
    assert delayed["holding"] == 61
    s17 = loaded.panel.series[17]
    assert delayed["net"] == pytest.approx(
        net(s17.open[s17.position[d[211]]], s17.open[s17.position[d[151]]]), rel=1e-12
    )
    gone = trades[(d[80], "S25")]
    assert (gone["exit_date"], gone["exit_reason"]) == (d[120], "delisted")
    end = trades[(d[230], "S19")]
    assert (end["exit_date"], end["exit_reason"]) == (d[249], "segment_end")
    assert result["abandon_reasons"] == {"limit_up": 1, "not_tradable": 1}
    assert result["trades"] == 7 and result["signals"] == 9
    assert result["listed"]["years"]["2016"]["signals"] == 9
    assert result["listed"]["years"]["2016"]["TPEx:signals"] == 1


def test_f4_trades_by_hand(loaded, monkeypatch):
    d = trading_days()
    result = used_run(loaded, monkeypatch, "F4")
    trades = {(t["signal_date"], t["symbol"]): t for t in result["_trades"]}
    assert sorted(trades) == sorted(
        [
            (d[120], "S23"),  # back on 140: not a first time
            (d[125], "S33"),  # 25 bars before; S31 had 10
            (d[150], "S21"),
            (d[170], "S10"),  # TPEx; S8 came on the day after a missing list
            (d[205], "S26"),  # the TWSE instrument, 24 bars from the transfer
        ]
    )
    first = trades[(d[150], "S21")]
    assert (first["fill_date"], first["exit_date"], first["exit_reason"]) == (
        d[151],
        d[170],  # the 20th session counting the fill
        "time",
    )
    assert first["holding"] == 20 and first["bars_before"] == 150
    assert trades[(d[205], "S26")]["bars_before"] == 24
    assert trades[(d[125], "S33")]["bars_before"] == 25
    assert result["listed"]["missing_list_days"] == {"TWSE": 0, "TPEx": 2}
    assert result["exits"]["stop"] == result["exits"]["target"] == 0


def test_the_excess_is_over_the_population_of_t(loaded, monkeypatch):
    days = trading_days()
    result = used_run(loaded, monkeypatch, "F4")
    first = next(t for t in result["_trades"] if t["signal_date"] == days[150])
    expected = tr.baseline(loaded.trade, 150, 151, 170, 249)
    assert first["population"] == expected["mean"]
    assert first["excess"] == pytest.approx(first["net"] - expected["mean"])
    assert first["population_members"] == len(
        lib.universe(loaded.panel, days[150], 1000)
    )


def test_f3_takes_the_crash_with_the_margin_drop(loaded):
    days = trading_days()
    item = loaded.panel.series[CRASH]
    at = item.position[days[202]]
    ok, dd, md = tool.f3_qualifies(loaded, item, at)
    assert (
        ok
        and dd == pytest.approx(46.72 / 62 - 1)
        and md == pytest.approx(800 / 1197 - 1)
    )
    for t in (201, 203):
        assert tool.f3_qualifies(loaded, item, item.position[days[t]])[0] is False, t


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[249]),
            "validation": (days[250], days[339]),
            "used": (days[340], days[399]),
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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "F1,F2,F3,F4"
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
        "round10_research",
        "936",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (10, 4, 41)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.234)
    assert report["read_until"] == trading_days()[249].isoformat()
    for name in ("F1", "F4"):
        assert report["hypotheses"][name]["engine"] == "trade"
        assert report["hypotheses"][name]["reason"] == "too_few_trade_days"
    assert report["hypotheses"]["F1"]["trades"] == 7
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 4 個、累計 41 個" in text and "驗證段 t ≥ 3.234" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round10_research", 10, "exploration", 1) for name in NAMES]
    for name, files in (
        ("F1", ("summary.md", "tables.json", "trades.csv", "days.csv")),
        ("F2", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("F3", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("F4", ("summary.md", "tables.json", "trades.csv", "days.csv")),
    ):
        for file in files:
            assert (out / name / file).is_file(), (name, file)
        summary = (out / name / "summary.md").read_text(encoding="utf-8")
        assert tool.DEGENERATE[name] in summary
    picks = (out / "F3" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == "signal_date,rank,exchange,symbol,drawdown_60,margin_drop_5,tie"
    assert [line.split(",")[:4] for line in picks[1:]] == [
        [trading_days()[202].isoformat(), "1", "TWSE" if CRASH % 2 else "TPEx", "S12"]
    ]
    f4 = (out / "F4" / "summary.md").read_text(encoding="utf-8")
    assert "| 放棄：T+1 漲停鎖死 | 0 |" in f4 and "| 上櫃名單缺列" in f4
    f2 = (out / "F2" / "summary.md").read_text(encoding="utf-8")
    assert "## 和 H2 的重疊（F2 第 6 點）" in f2 and tool.OVERLAP_NOTE in f2


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="F2") == 2
    assert any("F2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_repository_ledger_refuses_the_exploration_too(copied, tmp_path, capsys):
    ex.write_ledger(
        ex.REPO_LEDGER,
        [
            {
                "hypothesis": "F3",
                "tool": "round10_research",
                "segment": "exploration",
                "version": 1,
            }
        ],
    )
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="F3") == 2
    assert any("F3 already in" in line for line in refused(capsys))


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="F1,B1") == 2
    assert any("B1 not registered" in line for line in refused(capsys))


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
    data["design"] = "926"
    data["hypotheses"]["F2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_234(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "F2", "F4")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [
        ("F2", "round10_research", "finished"),
        ("F4", "round10_research", "finished"),
    ]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["F2", "F4"]
    assert validation["min_t"] == 3.234
    for name in ("F2", "F4"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["min_t"] == 3.234, name
    assert validation["read_until"] == trading_days()[339].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.234" in text
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
    """Only one panel at a time: the validation's has no reference left when
    the used segment is loaded (PR #905 review 7053124013), and the used
    segment of the passed hypothesis is written."""

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
    report = passed_report(out, tmp_path, "F3")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    # every segment from the copy's start (PR #939 review 7059380651)
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[339]),
        (tool.LOAD_FROM, days[399]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["F3"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["F3"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "F3" / "used" / file).is_file(), file
    assert "## 已用段" in (tmp_path / "validation" / "explore.md").read_text(
        encoding="utf-8"
    )


def test_f2_has_a_list_from_the_validations_first_signal_date(
    copied, tmp_path, monkeypatch
):
    """PR #939 review 7059380651 必修 1: a later segment reads the copy from
    its start, so vol_720's window is there on the segment's first signal
    date (with 730 calendar days of warm-up the 721 bars were not, and F2 kept
    cash for its first ~230 signal dates).  The window is shortened to fit the
    fixture's 400 sessions; the old warm-up is shortened alike, so a tool
    that still read a warm-up only would find no list here."""

    monkeypatch.setattr(tool, "VOL_WINDOW", 200)
    monkeypatch.setattr(tool, "WARMUP_CALENDAR_DAYS", 30, raising=False)
    out = tmp_path / "exploration"
    assert explore(copied, out, hypotheses="F2") == 0
    report = passed_report_of(out, tmp_path, "F2")
    assert validate(copied, tmp_path / "validation", report) == 0
    days = trading_days()
    first = days[249].isoformat()  # the session before 250, the first buy on 250
    lines = (
        (tmp_path / "validation" / "F2" / "picks.csv")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert lines[0] == (
        "signal_date,rank,exchange,symbol,vol_720,cash_yield_12m,mom_240_20,"
        "r1,r2,score,tie"
    )
    rows = [line.split(",") for line in lines[1:] if line.startswith(first)]
    assert rows and all(row[4] for row in rows)  # vol_720 has a value
    scores = [float(row[9]) for row in rows]
    assert scores == sorted(scores)  # the mean rank, small first
    tables = read_json(tmp_path / "validation" / "F2" / "tables.json")
    assert tables["counts"]["F2"]["bought"] > 0
    # the overlap with X2's real list (explore_research 第 2 版), every signal date
    assert tables["overlap"]["days"] == 90
    assert 0.0 <= tables["overlap"]["mean"] <= 1.0
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["F2"]["overlap_x2"]["days"] == 90


def passed_report_of(out: Path, tmp_path: Path, *names: str) -> Path:
    """``passed_report`` for a run of only some hypotheses."""

    data = read_json(out / "explore.json")
    for name in data["hypotheses"]:
        data["hypotheses"][name]["verdict"] = (
            ex.EXPLORATION_PASSED if name in names else ex.EXPLORATION_FAILED
        )
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_coverage_only_computes_no_return(copied, tmp_path):
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity", '"net"', "overlap"):
        assert word not in text
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    hyp = body["hypotheses"]
    days = 189  # signal dates 60 .. 248, all in 2016
    f1 = hyp["F1"]["coverage"]["years"]["2016"]
    # no occupancy: S3 on 130 counts; 3, 3, 9, 13, 15, 17, 19, 25, 11 and TPEx 6
    assert (f1["days"], f1["signals"], f1["signal_days"]) == (days, 10, 10)
    assert f1["markets"]["TPEx"]["signals"] == 1 and f1["null_ratio"] == 2
    assert f1["blank_rows"] == 1  # S7; S1 on 90 has a cash dividend only
    f2 = hyp["F2"]["coverage"]["2016"]
    assert (
        f2["days"] == days and f2["missing"]["vol_720"] == f2["members"]
    )  # < 721 bars
    assert f2["half"] == 0
    f3 = hyp["F3"]["coverage"]["2016"]
    assert (f3["hits"], f3["hit_days"], f3["max_hits"]) == (1, 1, 1)
    assert f3["missing"]["margin_drop_5"] >= days  # stock 4 has no chip row
    f4 = hyp["F4"]["coverage"]["years"]["2016"]
    twse, tpex = f4["markets"]["TWSE"], f4["markets"]["TPEx"]
    assert (twse["signals"], tpex["signals"]) == (4, 1)  # 23, 33, 21, 26; 10
    assert (twse["missing_list_days"], tpex["missing_list_days"]) == (0, 2)
    entries = f4["entries"]
    # TWSE: 23 (120 bars), 31 (10), 33 (25), 21 (150), 36 (24); TPEx: 8 (161), 10 (170)
    assert entries["TWSE"]["count"] == 5 and entries["TWSE"]["median"] == 25
    assert entries["TWSE"]["under_min_bars"] == 1
    assert (entries["TWSE"]["q1"], entries["TWSE"]["q3"]) == (24, 120)
    assert entries["TPEx"]["count"] == 2 and entries["TPEx"]["max_day_entries"] == 1
    assert entries["TPEx"]["max_day"] == trading_days()[161].isoformat()
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["F1"] == {"plan", "stock_div_ex"}
    assert seconds["F4"] == {"plan", "margin_first"}
    assert {
        "plan",
        "vol_720",
        "cash_yield_12m",
        "mom_240_20",
        "f2_order",
        "x2_order",
    } == (seconds["F2"])
    assert seconds["F3"] == {"plan", "drawdown_60+margin_drop_5"}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "actions", "margin_lists"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert "### F4 第 5、6 點：依年、依交易所" in md
    assert "### F1：依年的訊號數與訊號日數" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "F1"]
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


def test_an_unwritable_ledger_refuses_the_exploration_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    """On any platform: the gate's ledger check is the one #899 added."""

    problem = "x/explore-ledger.json is not writable"
    monkeypatch.setattr(ex, "ledger_write_problem", lambda db: problem)
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    assert explore(copied, tmp_path / "out", hypotheses="F1") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "F1")
    problem = "x/explore-ledger.json is not writable"
    monkeypatch.setattr(ex, "ledger_write_problem", lambda db: problem)
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "v").exists()


@READ_ONLY
def test_a_read_only_ledger_folder_refuses_the_exploration_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    opened = no_reads(monkeypatch)
    out = tmp_path / "out"
    copied.parent.chmod(0o555)
    try:
        assert explore(copied, out, hypotheses="F1") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "F1")
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


def test_vol_720_on_the_panel_matches_the_direct_computation(loaded):
    """The prefix sums give the direct stdev on real panel arrays too (a 300
    bar window via the module's constant would change the hash; this checks
    the arithmetic with VOL_WINDOW as is on a long hand-made series)."""

    closes = closes_of(1500, salt="long")
    item = make_item(closes)
    ctx = bare_ctx()
    for at in (720, 900, 1499):
        window = closes[at - 720 : at + 1]
        expected = statistics.stdev(
            window[k] / window[k - 1] - 1 for k in range(1, 721)
        )
        assert tool.vol_720(ctx, item, at) == pytest.approx(expected, rel=1e-9)
    assert math.isfinite(tool.vol_720(ctx, item, 1499))
