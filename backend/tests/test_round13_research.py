"""tools/research/round13_research.py: the registered U1～U3 (#968).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十三輪：U1～U3.  The features are checked on hand-made
series (the expected numbers worked out in the test); the gate ("each once")
and the reports run on a synthetic copy on a compressed calendar
(``compressed``): the segments and floors are moved into the fixture's 420
sessions, everything else is the registered one.
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
from datetime import date, timedelta
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
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/968#issuecomment-1"
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
features = _tool("feature_evidence")
im = _tool("industry_members")
ms = _tool("mainstream_research")
r5 = _tool("round5_research")
r6 = _tool("round6_research")
r10 = _tool("round10_research")
tool = _tool("round13_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("U1", "U2", "U3")
OTC_INST = date(2014, 12, 1)
SEMI = im.group_id(im.GROUP_LABELS["TWSE"]["24"])
PARTS = im.group_id(im.GROUP_LABELS["TWSE"]["28"])
PCS = im.group_id(im.GROUP_LABELS["TWSE"]["25"])
CODE_OF = {SEMI: "24", PARTS: "28", PCS: "25"}


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in (
        "mainstream_research",
        *(f"round{n}_research" for n in range(4, 13)),
    ):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    u1, u2, u3 = (h[name] for name in NAMES)
    assert {spec["engine"] for spec in h.values()} == {"portfolio"}
    assert u1["keys"] == (("inst_quiet_60", "high"),)
    assert (u1["top"], u1["hold"], u1["start"]) == (20, 60, ("session", OTC_INST, 60))
    assert u2["keys"] == (("ind_flow_20", "high"),)
    assert (u2["top"], u2["hold"], u2["start"]) == (20, 20, ("session", OTC_INST, 20))
    assert u3["conditions"] == (("cash_paid_5y", "is", True),)
    assert u3["short"] == "cash, not filled" and "keys" not in u3
    assert (u3["top"], u3["hold"], u3["start"]) == (20, 120, ("date", date(2013, 1, 2)))


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        13,
        3,
        52,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.302
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(52), 3) == 3.302
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "7d2705c3" and tool.DESIGN == "968"
    assert (tool.QUIET_WINDOW, tool.FLOW_WINDOW, tool.MIN_VALID) == (60, 20, 5)
    assert tool.MIN_VALID == ms.MIN_MEMBERS  # M1's rank_groups floor
    assert (tool.PAID_YEARS, tool.CASH_MIN) == (5, 0.0)
    assert tool.INSTITUTIONS == ("foreign_buy", "trust_buy", "dealer_buy")
    # imported, not rewritten
    assert tool.order_key is r5.order_key
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool.vol_i.__code__.co_names.count("_mean_volume")  # feature_evidence's
    assert tool.load.__code__.co_names.count("load_context")  # explore_research's
    assert tool.load.__code__.co_names.count("load_actions")  # research_report's
    assert tool.industry_day.__code__.co_names.count("group_members")
    assert tool.m1_groups.__code__.co_names.count("signal_day")


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#968 範圍第 1 項: each value that changes a verdict changes the hash —
    the windows 60 and 20, the 5 calendar years, N and K (20; 60, 20, 120),
    the industries' floor 5, the orders, the rules of no trading and of a
    market gap, U2's null column, own missing value and several industries,
    U3's null and T rule."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.302
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.285),
        (tool, "QUIET_WINDOW", 59),
        (tool, "FLOW_WINDOW", 19),
        (tool, "PAID_YEARS", 4),
        (tool, "CASH_MIN", 0.01),
        (tool, "MIN_VALID", 6),
        (tool, "INSTITUTIONS", ("foreign_buy", "trust_buy")),
        (tool, "NO_TRADING", "no chip row only"),
        (tool, "MARKET_GAP", "a market gap is ignored"),
        (tool, "FLOW_NULL", "a null column makes flow_i missing"),
        (tool, "OWN_MISSING", "own flow_i missing takes the industry's value"),
        (tool, "SEVERAL_GROUPS", "the key is the best group's"),
        (tool, "PAID_RULE", "a null cash_dividend is paid"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "MIN_LOTS", 500),
        (features, "SHARED_VERSION", features.SHARED_VERSION + 1),
        (ms, "MEMBERS_SHA256", "0" * 64),
        (er, "LIMIT_BEFORE_WIDENING", Fraction(1, 10)),
        (er, "LIMIT_WIDENED_ON", date(2015, 6, 2)),
        (er, "LIMIT", Fraction(1, 20)),
        (tool, "HYPOTHESES", _swap("U1", "keys", (("inst_quiet_60", "low"),))),
        (tool, "HYPOTHESES", _swap("U2", "keys", (("ind_flow_20", "low"),))),
        (tool, "HYPOTHESES", _swap("U3", "conditions", ())),
        (tool, "HYPOTHESES", _swap("U3", "order", "cash_yield_12m high first")),
        (tool, "HYPOTHESES", _swap("U3", "short", "filled")),
        (tool, "HYPOTHESES", _swap("U1", "top", 19)),
        (tool, "HYPOTHESES", _swap("U2", "top", 19)),
        (tool, "HYPOTHESES", _swap("U3", "top", 19)),
        (tool, "HYPOTHESES", _swap("U1", "hold", 59)),
        (tool, "HYPOTHESES", _swap("U2", "hold", 21)),
        (tool, "HYPOTHESES", _swap("U3", "hold", 60)),
        (tool, "HYPOTHESES", _swap("U1", "start", ("session", OTC_INST, 61))),
        (tool, "HYPOTHESES", _swap("U2", "start", ("session", OTC_INST, 21))),
        (tool, "HYPOTHESES", _swap("U3", "start", ("date", date(2013, 1, 3)))),
        (r6, "HYPOTHESES", {**r6.HYPOTHESES, "W1": {**r6.HYPOTHESES["W1"], "top": 19}}),
        (r5, "HYPOTHESES", {**r5.HYPOTHESES, "V3": {**r5.HYPOTHESES["V3"], "top": 19}}),
        (ms, "GROUP_COUNT", 4),
        (tool, "LOAD_RULE", "the warm-up before a later segment"),
        (tool, "LOAD_FROM", date(2004, 1, 1)),
        (tool, "MIN_T", 1.96),
        (
            tool,
            "SEGMENTS",
            {**tool.SEGMENTS, "validation": (date(2020, 1, 3), date(2024, 9, 27))},
        ),
        (tool, "MIN_SEGMENT_DAYS", {"exploration": 400, "validation": 250}),
        (pr, "SLIPPAGE", 0.001),
        (pr, "FEE", 0.001),
        (pr, "TAX", 0.0015),
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
        "--members",
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master 7d2705c3 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash; #964's exploration round12_research's.
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
    "round10_research": (
        1,
        "453f65124f86b5643ef1ce79dd079530a603e9434ed719a5f942090eeaf85dd9",
    ),
    "round11_research": (
        1,
        "5c326147823f78ca203db3b127b6369a63305e3b62839479bf39f2ac161b67bb",
    ),
    "round12_research": (
        1,
        "12f24befd44c279118ade14460c722f968849a00c48a27b4def7690ca3f0954f",
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
    section = text.split("**第十三輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "tools/research/round13_research.py" in section
    assert "本輪 3 個、累計 52 個" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(
    closes, suspended=(), instrument_id=1, dates=None, chips=None, volume=None
):
    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2016, 1, 4), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at)
        for name in ("open", "high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(2_000_000.0 if volume is None else volume[at])
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    item.chips = {name: array("d", values) for name, values in (chips or {}).items()}
    return item


def context_for(items, sessions=None, symbols=None, turnover=None):
    """``round13_research.Context`` on hand-made items (the market gaps
    computed from them, as ``load`` does)."""

    series = {item.instrument_id: item for item in items}
    raw_rows = {
        item.instrument_id: (
            array("d", item.low),
            array("d", item.high),
            array("d", item.close),
            array("d", [0.0] * len(item.close)),
        )
        for item in items
    }
    symbols = symbols or {i: ("TWSE", f"S{i}", "") for i in series}
    panel = lib.Panel(sessions or [], series, {}, {}, symbols)
    base = ex.Context(pr.Market(panel, raw_rows, {}, None))
    for instrument_id, values in (turnover or {}).items():
        base.turnover[instrument_id] = array("d", values)
    return tool.Context(base)


def inst_chips(bars: int, trading=(), value=100.0, columns=("foreign_buy",)):
    """Chips with ``value`` in ``columns`` on the bars ``trading``, 0 elsewhere."""

    out = {name: [0.0] * bars for name in tool.INSTITUTIONS}
    for k in trading:
        for name in columns:
            out[name][k] = value
    return out


# --- 共同: no trading and a market gap ---------------------------------------------


@pytest.mark.parametrize(
    "row, quiet",
    [
        (None, True),  # no chip row: every column NaN
        ((NAN, NAN, NAN), True),
        ((0.0, 0.0, 0.0), True),
        ((NAN, 0.0, NAN), True),  # null and 0 mixed
        ((0.0, NAN, 0.0), True),
        ((NAN, NAN, 5.0), False),  # one not null and not 0
        ((0.0, -3.0, 0.0), False),  # a net sale is trading too
        ((1.0, 0.0, NAN), False),
    ],
)
def test_no_trading_is_each_column_null_or_0(row, quiet):
    values = (NAN, NAN, NAN) if row is None else row
    chips = {name: [v] for name, v in zip(tool.INSTITUTIONS, values)}
    item = make_item([10.0], chips=chips)
    assert tool.no_trading(item, 0) is quiet
    assert tool.no_trading(make_item([10.0]), 0) is True  # no chip column at all


def test_a_market_gap_is_a_session_without_any_value_in_that_market():
    """Session 3: no TWSE item has a value (one is 0, so it counts as data,
    the other NaN); session 4: no TWSE value at all; TPEx has values on both."""

    bars = 8
    a = make_item([10.0] * bars, instrument_id=1, chips=inst_chips(bars))
    a.chips["foreign_buy"][4] = NAN
    a.chips["trust_buy"][4] = NAN
    a.chips["dealer_buy"][4] = NAN
    b = make_item(
        [10.0] * bars,
        instrument_id=2,
        chips={name: [NAN] * bars for name in tool.INSTITUTIONS},
    )
    c = make_item([10.0] * bars, instrument_id=3, chips=inst_chips(bars, range(bars)))
    symbols = {1: ("TWSE", "S1", ""), 2: ("TWSE", "S2", ""), 3: ("TPEx", "S3", "")}
    ctx = context_for([a, b, c], symbols=symbols)
    assert list(ctx.gaps["TWSE"]) == [0, 0, 0, 0, 1, 0, 0, 0]
    assert list(ctx.gaps["TPEx"]) == [0] * bars
    assert tool.window_of(ctx, a, 7, 4).reason == "market_gap"  # bars 4 .. 7
    assert tool.window_of(ctx, a, 7, 3).first == 5  # bars 5 .. 7
    assert tool.window_of(ctx, c, 7, 8).first == 0  # the other market: no gap


# --- U1: inst_quiet_60 -----------------------------------------------------------


def test_inst_quiet_60_by_hand():
    bars = 70
    trading = {0, 5, 10, 11, 30, 64, 69}  # the bars with institutional trading
    item = make_item([10.0] * bars, chips=inst_chips(bars, trading))
    ctx = context_for([item])
    # bars 10 .. 69: 10, 11, 30, 64, 69 traded
    assert tool.inst_quiet_60(ctx, item, 69) == 60 - 5
    # bars 0 .. 59: 0, 5, 10, 11, 30
    assert tool.inst_quiet_60(ctx, item, 59) == 55
    assert tool.inst_quiet_60(ctx, item, 58) is None  # only 59 bars
    # a null bar and a no-row bar are quiet too
    item.chips["foreign_buy"][30] = NAN
    ctx = context_for([item, make_item([10.0] * bars, instrument_id=2,
                                       chips=inst_chips(bars, range(bars)))])  # fmt: skip
    assert tool.inst_quiet_60(ctx, item, 69) == 56


@pytest.mark.parametrize("bad", [10, 69])  # the first and the last of the 60
def test_inst_quiet_60_is_missing_with_a_suspended_bar(bad):
    bars = 70
    item = make_item([10.0] * bars, suspended=(bad,), chips=inst_chips(bars))
    ctx = context_for([item])
    assert tool.inst_quiet_60(ctx, item, 69) is None
    assert tool.window_of(ctx, item, 69, 60).reason == "suspended"
    if bad == 10:  # one bar later the suspended one is out of the window
        longer = make_item([10.0] * 71, suspended=(10,), chips=inst_chips(71))
        assert tool.inst_quiet_60(context_for([longer]), longer, 70) == 60


def test_inst_quiet_60_is_missing_on_a_market_gap_and_the_other_market_is_not():
    bars = 70
    twse = make_item([10.0] * bars, instrument_id=1, chips=inst_chips(bars))
    otc = make_item([10.0] * bars, instrument_id=2, chips=inst_chips(bars, [40]))
    for name in tool.INSTITUTIONS:
        twse.chips[name][40] = NAN  # the only TWSE item: no value on session 40
    symbols = {1: ("TWSE", "S1", ""), 2: ("TPEx", "S2", "")}
    ctx = context_for([twse, otc], symbols=symbols)
    assert tool.inst_quiet_60(ctx, twse, 69) is None
    assert tool.inst_quiet_60(ctx, twse, 39) is None  # bars 0 .. 39: only 40 bars
    longer = 101
    twse2 = make_item([10.0] * longer, instrument_id=1, chips=inst_chips(longer))
    otc2 = make_item([10.0] * longer, instrument_id=2, chips=inst_chips(longer, [40]))
    for name in tool.INSTITUTIONS:
        twse2.chips[name][40] = NAN
    ctx = context_for([twse2, otc2], symbols=symbols)
    assert tool.inst_quiet_60(ctx, twse2, 99) is None  # bars 40 .. 99
    assert tool.inst_quiet_60(ctx, twse2, 100) == 60  # bars 41 .. 100
    assert tool.inst_quiet_60(ctx, otc2, 99) == 59  # TPEx had data on 40: traded


def test_u1_ranks_high_first_ties_by_the_hash_and_missing_last():
    bars = 60
    quiet = {1: 50, 2: 10, 3: 50, 4: None, 5: 60}
    items = []
    for i, q in quiet.items():
        trading = range(60 - q) if q is not None else range(bars)
        suspended = (3,) if q is None else ()
        items.append(make_item([10.0] * bars, instrument_id=i, suspended=suspended,
                               chips=inst_chips(bars, trading)))  # fmt: skip
    ctx = context_for(items)
    day = items[0].dates[-1]
    members = [(item, 59) for item in items]
    ranked = tool.rank_u1(ctx, tool.HYPOTHESES["U1"], day, members)
    ties = sorted((1, 3), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == [5, *ties, 2, 4]
    assert ranked.missing["inst_quiet_60"] == 1 and ranked.missing["suspended"] == 1
    assert ranked.values == {50: 2, 10: 1, 60: 1}


# --- U2: flow_i, vol_i, ind_flow_20 ---------------------------------------------


def test_flow_i_counts_no_trading_and_null_columns_as_0():
    bars = 25
    chips = {
        "foreign_buy": [100.0] * bars,
        "trust_buy": [NAN] * bars,
        "dealer_buy": [-30.0] * bars,
    }
    chips["foreign_buy"][10] = NAN  # bar 10: every column null (no row): 0
    chips["dealer_buy"][10] = NAN
    chips["foreign_buy"][24] = NAN  # bar 24: one null column counts 0
    item = make_item([10.0] * bars, chips=chips)
    other = make_item(
        [10.0] * bars, instrument_id=2, chips=inst_chips(bars, range(bars))
    )
    ctx = context_for([item, other])
    # bars 5 .. 24: 70 on 18 bars (not 10, 24), −30 on 24, 0 on 10
    assert tool.flow_i(ctx, item, 24) == pytest.approx(70.0 * 18 - 30.0)
    assert tool.flow_i(ctx, item, 18) is None  # only 19 bars
    # feature_evidence._flow would call a null missing: not here
    assert features._flow(tool.INSTITUTIONS, 20)(item, 24) is None
    assert tool.vol_i(item, 24) == features._mean_volume(item, 24) == 2_000_000.0
    no_volume = make_item([10.0] * bars, volume=[0.0] * bars)
    assert tool.vol_i(no_volume, 24) is None
    assert tool.vol_i(item, 19) is None  # fewer than 20 bars before T


def test_flow_i_is_missing_with_a_suspended_bar_or_a_market_gap():
    bars = 25
    item = make_item([10.0] * bars, suspended=(5,), chips=inst_chips(bars, range(bars)))
    ctx = context_for([item])
    assert tool.flow_i(ctx, item, 24) is None  # bars 5 .. 24
    gap = make_item([10.0] * bars, instrument_id=1, chips=inst_chips(bars))
    otc = make_item([10.0] * bars, instrument_id=2, chips=inst_chips(bars, [12]))
    for name in tool.INSTITUTIONS:
        gap.chips[name][12] = NAN
    ctx = context_for(
        [gap, otc], symbols={1: ("TWSE", "S1", ""), 2: ("TPEx", "S2", "")}
    )
    assert tool.flow_i(ctx, gap, 24) is None  # session 12: no TWSE value
    assert tool.flow_i(ctx, otc, 24) == 100.0  # the other market is not touched


def member(i: int, code: str) -> ms.Member:
    label = im.GROUP_LABELS["TWSE"][code]
    return ms.Member("TWSE", code, label, im.group_id(label), f"S{i}", False)


def u2_context(flows: dict[int, float | None], groups: list[tuple[int, str]],
               volumes: dict[int, float] | None = None, bars: int = 25):  # fmt: skip
    """Items with a flat flow ``f`` on each of their bars (``None``: a
    suspended bar, flow_i missing; ``"vol"`` in volumes 0: vol_i missing),
    the member rows ``groups`` [(id, code)] on the first day."""

    sessions = weekdays(date(2016, 1, 4), bars)
    items = []
    for i, f in flows.items():
        chips = {name: [0.0] * bars for name in tool.INSTITUTIONS}
        chips["foreign_buy"] = [0.0 if f is None else f / 20.0] * bars
        volume = [(volumes or {}).get(i, 1000.0)] * bars
        items.append(make_item([10.0] * bars, instrument_id=i, dates=sessions,
                               chips=chips, volume=volume,
                               suspended=(bars - 1,) if f is None else ()))  # fmt: skip
    ctx = context_for(items, sessions=sessions)
    ctx.groups = ms.build_context(
        ctx.market, {sessions[0]: [member(i, code) for i, code in groups]}
    )
    members = [(item, bars - 1) for item in items]
    return ctx, sessions[-1], members


def test_ind_flow_20_is_the_sums_over_valued_members_and_needs_5():
    # SEMI: 1～5 valued (5: ranked), 6 flow missing; PARTS: 7～10 (4: not ranked)
    flows = {1: 100.0, 2: 200.0, 3: -50.0, 4: 0.0, 5: 50.0, 6: None}
    flows |= {7: 10.0, 8: 10.0, 9: 10.0, 10: 10.0}
    volumes = {1: 1000.0, 2: 2000.0, 3: 1000.0, 4: 500.0, 5: 500.0}
    groups = [(i, "24") for i in range(1, 7)] + [(i, "28") for i in range(7, 11)]
    ctx, day, members = u2_context(flows, groups, volumes)
    industry = tool.industry_day(ctx, day, members)
    assert industry.valid == {SEMI: 5, PARTS: 4}
    assert set(industry.ranked) == {SEMI}
    assert industry.ranked[SEMI] == pytest.approx((100 + 200 - 50 + 0 + 50) / 5000.0)
    assert industry.keys[1].value == industry.ranked[SEMI]
    assert (industry.keys[6].value, industry.keys[6].reason) == (None, "own")
    assert (industry.keys[7].value, industry.keys[7].reason) == (None, "unranked")
    # a member outside T's population is not summed: 4 of SEMI then
    industry = tool.industry_day(
        ctx, day, [m for m in members if m[0].instrument_id != 1]
    )
    assert industry.valid[SEMI] == 4 and SEMI not in industry.ranked


def test_u2_missing_keys_rank_last_in_three_cases_and_ties_go_by_the_hash():
    flows = {i: 10.0 for i in range(1, 6)} | {6: None}  # SEMI ranked, 6 own missing
    flows |= {i: 99.0 for i in range(7, 11)}  # PARTS: 4, not ranked
    flows |= {11: 999.0}  # no group
    flows |= {i: 50.0 for i in range(12, 17)}  # PCS ranked, higher than SEMI
    groups = [(i, "24") for i in range(1, 7)] + [(i, "28") for i in range(7, 11)]
    groups += [(i, "25") for i in range(12, 17)]
    ctx, day, members = u2_context(flows, groups)
    ranked = tool.rank_u2(ctx, tool.HYPOTHESES["U2"], day, members)
    order = [row[0] for row in ranked.rows]
    by_hash = lambda ids: sorted(ids, key=lambda i: pr.tie_break(day, i))  # noqa: E731
    assert order[:5] == by_hash(range(12, 17))  # PCS 50 ÷ 1000 first
    assert order[5:10] == by_hash(range(1, 6))
    assert sorted(order[10:]) == [6, 7, 8, 9, 10, 11]
    assert order[10:] == by_hash([6, 7, 8, 9, 10, 11])  # all missing: the hash
    assert ranked.missing["own"] == 1 and ranked.missing["unranked"] == 4
    assert ranked.missing["no_group"] == 1 and ranked.missing["ind_flow_20"] == 6
    assert ranked.missing["flow_i"] == 1


@pytest.mark.parametrize("smaller_ranked", [True, False])
def test_u2_a_stock_in_two_industries_counts_in_both_and_keys_on_the_smaller_id(
    smaller_ranked,
):
    """第十三輪實作釋義: 1 is in both; the other industry has 4 more members,
    5 with it (ranked only because it counts there too).  Its key is the
    smaller id's, missing when that one is not ranked."""

    smaller, larger = sorted((SEMI, PARTS))
    other, alone = larger, smaller  # larger: 4 others + 1; smaller: 4 + 1 or 3 + 1
    flows = {1: 40.0} | {i: 10.0 for i in range(2, 6)} | {i: 20.0 for i in range(6, 10)}
    groups = [(1, CODE_OF[other])] + [(i, CODE_OF[other]) for i in range(2, 6)]
    groups += [(1, CODE_OF[alone])]
    count = 4 if smaller_ranked else 3  # the smaller group ranked or not
    groups += [(i, CODE_OF[alone]) for i in range(6, 6 + count)]
    ctx, day, members = u2_context(flows, groups)
    industry = tool.industry_day(ctx, day, members)
    assert industry.valid[other] == 5 and other in industry.ranked
    assert industry.ranked[other] == pytest.approx((40 + 40) / 5000.0)
    key = industry.keys[1]
    assert (key.group, key.groups) == (smaller, 2)
    if smaller_ranked:
        assert industry.ranked[smaller] == pytest.approx((40 + 80) / 5000.0)
        assert key.value == industry.ranked[smaller] and key.reason is None
    else:
        assert smaller not in industry.ranked
        assert (key.value, key.reason) == (None, "unranked")  # not the other's
    ranked = tool.rank_u2(ctx, tool.HYPOTHESES["U2"], day, members)
    assert ranked.missing["several_groups"] == 1


def test_the_list_industries_and_the_m1_share_by_hand():
    rows = [(1, {"group": SEMI}, ""), (2, {"group": SEMI}, ""),
            (3, {"group": PARTS}, ""), (4, {"group": None}, "")]  # fmt: skip
    assert tool.industry_share(rows, {SEMI, PCS}) == (2, 2 / 4)
    assert tool.industry_share(rows, set()) == (2, None)  # M1 without a list
    assert tool.industry_share([], {SEMI}) == (0, None)


def test_u2_plan_lists_the_industries_and_the_m1_share_skipping_empty_days(
    monkeypatch,
):
    sessions = weekdays(date(2016, 1, 4), 5)
    lists = {
        0: [(1, SEMI), (2, SEMI), (3, PARTS)],
        1: [],
        2: [(4, PCS), (5, PCS)],
        3: [(6, SEMI)],
    }
    chosen = {0: {SEMI}, 1: {SEMI}, 2: {SEMI, PARTS}, 3: set()}
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [])

    def rank(ctx, spec, day, members):
        at = sessions.index(day)
        rows = [(i, {"ind_flow_20": 1.0, "group": g}, f"{i}") for i, g in lists[at]]
        return tool.Ranked(rows, industry=tool.IndustryDay())

    monkeypatch.setattr(tool, "rank_u2", rank)
    monkeypatch.setattr(tool, "m1_groups", lambda ctx, at: chosen[at])
    ctx = SimpleNamespace(
        panel=SimpleNamespace(sessions=sessions, symbols={}), gaps={}, seconds={}
    )
    planned = tool.plan(ctx, tool.HYPOTHESES["U2"], "U2", 1, 4)
    # day 1: no list; day 3: M1 without groups (its industries still count)
    assert planned.overlap == {"2016": [2 / 3, 0.0]}
    assert planned.industries == {"2016": [2, 1, 1]}


# --- U3: cash_paid_5y ------------------------------------------------------------


def action(day: date, cash, instrument_id: int = 1):
    return SimpleNamespace(
        instrument_id=instrument_id,
        action_date=day,
        cash_dividend=cash,
        stock_dividend_ratio=None,
        split_ratio=None,
    )


def u3_ctx(rows: list) -> tuple:
    holder = SimpleNamespace(actions=rows)
    item = make_item([10.0])
    ctx = context_for([item])
    ctx.paid = tool.paid_years({1: holder})
    return ctx, item


def test_cash_paid_5y_needs_each_of_the_5_years_before_ts():
    years = [date(y, 7, 15) for y in range(2011, 2016)]
    ctx, item = u3_ctx([action(d, 1.5) for d in years])
    assert tool.cash_paid_5y(ctx, item, date(2016, 3, 1)) is True  # 2011 .. 2015
    assert tool.cash_paid_5y(ctx, item, date(2016, 12, 30)) is True
    assert tool.cash_paid_5y(ctx, item, date(2017, 1, 3)) is False  # 2016 not paid
    assert tool.cash_paid_5y(ctx, item, date(2015, 12, 31)) is False  # 2010 not paid
    missing = [action(d, 1.5) for d in years if d.year != 2013]
    ctx, item = u3_ctx(missing)
    assert tool.cash_paid_5y(ctx, item, date(2016, 3, 1)) is False


def test_cash_paid_5y_a_null_or_0_row_is_not_paid_and_one_row_of_several_is():
    years = [date(y, 7, 15) for y in range(2011, 2016)]
    rows = [action(d, 1.5) for d in years if d.year != 2014]
    ctx, item = u3_ctx([*rows, action(date(2014, 7, 15), None)])
    assert tool.cash_paid_5y(ctx, item, date(2016, 3, 1)) is False  # null: not paid
    ctx, item = u3_ctx([*rows, action(date(2014, 7, 15), 0.0)])
    assert tool.cash_paid_5y(ctx, item, date(2016, 3, 1)) is False
    several = [
        action(date(2014, 1, 15), None),
        action(date(2014, 4, 15), 0.0),
        action(date(2014, 10, 15), 0.25),  # quarterly: one row > 0 is enough
    ]
    ctx, item = u3_ctx([*rows, *several])
    assert tool.cash_paid_5y(ctx, item, date(2016, 3, 1)) is True


def test_cash_paid_5y_does_not_read_ts_year_nor_the_row_on_t():
    rows = [action(date(y, 7, 15), 1.0) for y in range(2012, 2016)]  # 2011 missing
    t = date(2016, 7, 15)
    ctx, item = u3_ctx([*rows, action(t, 1.0), action(date(2016, 1, 4), 2.0)])
    assert tool.cash_paid_5y(ctx, item, t) is False  # T's year (and T) not read
    ctx, item = u3_ctx([*rows, action(date(2011, 12, 31), 1.0)])
    assert tool.cash_paid_5y(ctx, item, date(2016, 1, 4)) is True


def test_u3_takes_20_by_the_hash_and_fewer_leave_cash():
    items = [make_item([10.0], instrument_id=i) for i in range(1, 31)]
    ctx = context_for(items)
    day = items[0].dates[0]
    paid = frozenset(range(day.year - 5, day.year))
    ctx.paid = {i: paid for i in range(1, 26)}  # 25 qualify, 26～30 not
    ctx.paid[26] = frozenset(range(day.year - 4, day.year))  # 4 years only
    members = [(item, 0) for item in items]
    ranked = tool.rank_u3(ctx, tool.HYPOTHESES["U3"], day, members)
    assert ranked.hits == 25
    expected = sorted(range(1, 26), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == expected
    ctx.paid = {i: paid for i in (3, 7)}
    ranked = tool.rank_u3(ctx, tool.HYPOTHESES["U3"], day, members)
    assert sorted(row[0] for row in ranked.rows) == [3, 7]  # nothing filled up


def test_u3_rotates_120_accounts_and_the_population_too(monkeypatch):
    calls = []
    real = pr.simulate

    def spy(picks, quote, first, last, hold, top):
        calls.append((hold, top))
        return real(picks, quote, first, last, hold, top)

    monkeypatch.setattr(pr, "simulate", spy)
    sessions = weekdays(date(2016, 1, 4), 130)
    item = make_item([10.0] * 130, dates=sessions)
    ctx = context_for([item], sessions=sessions)
    monkeypatch.setattr(
        tool, "SEGMENTS", {**tool.SEGMENTS, "used": (sessions[1], sessions[-1])}
    )
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [])
    result = tool.run_portfolio(ctx, Path("unused"), "U3", "used")
    assert calls == [(120, 20), (120, None)]  # K = 120 accounts, the population too
    assert "excess" in result


def test_the_u3_hits_are_listed_by_year(monkeypatch):
    sessions = weekdays(date(2016, 12, 28), 5)  # 3 in 2016, 2 in 2017
    hits = {0: 25, 1: 3, 2: 0, 3: 40}
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [])

    def rank(ctx, spec, day, members):
        at = sessions.index(day)
        rows = [(i, {"cash_paid_5y": True}, f"{i}") for i in range(hits[at])]
        return tool.Ranked(rows, hits=hits[at])

    monkeypatch.setattr(tool, "rank_u3", rank)
    monkeypatch.setitem(tool.overlap_with, "U3", lambda ctx, day, members: {1})
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), gaps={})
    planned = tool.plan(ctx, tool.HYPOTHESES["U3"], "U3", 1, 4)
    assert planned.hits == {"2016": [25, 3, 0], "2017": [40]}
    summary = tool.overlap_summary(planned.hits)
    assert summary["mean"] == pytest.approx(68 / 4)
    c = planned.coverage
    assert (c["2016"]["short_days"], c["2016"]["zero_days"]) == (2, 1)
    assert (c["2016"]["min_hits"], c["2016"]["max_hits"]) == (0, 25)


# --- the overlaps (listed only) ---------------------------------------------------


def plan_with(
    monkeypatch, name: str, lists: dict[int, list[int]], others: dict[int, set],
    sessions=None,
):  # fmt: skip
    """``plan`` with the day's list and the other hypothesis's list given by
    signal date index: the overlap only."""

    sessions = sessions or weekdays(date(2016, 1, 4), 6)
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [])

    def rank(ctx, spec, day, members):
        at = sessions.index(day)
        return tool.Ranked([(i, {}, f"{i}") for i in lists[at]])

    monkeypatch.setattr(tool, f"rank_{name.lower()}", rank)
    monkeypatch.setitem(
        tool.overlap_with, name, lambda ctx, day, members: others[sessions.index(day)]
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), gaps={})
    return tool.plan(ctx, tool.HYPOTHESES[name], name, 1, len(sessions) - 1)


@pytest.mark.parametrize("name", ["U1", "U3"])
def test_the_overlap_is_over_the_days_list_and_skips_days_without_a_list(
    monkeypatch, name
):
    lists = {0: [1, 2, 3, 4], 1: [], 2: [5, 6], 3: [7, 8], 4: [9]}
    others = {0: {1, 2, 9}, 1: {1}, 2: {5}, 3: set(), 4: {9, 10}}
    planned = plan_with(monkeypatch, name, lists, others)
    # day 1: no list of ours; day 3: none of the other's; both not counted
    assert planned.overlap == {"2016": [2 / 4, 1 / 2, 1 / 1]}
    summary = tool.overlap_summary(planned.overlap)
    assert summary["days"] == 3 and summary["mean"] == pytest.approx(
        (0.5 + 0.5 + 1) / 3
    )


def test_the_u1_list_quiet_is_listed_by_hand(monkeypatch):
    """#968 決定 7083548336: each day's list's inst_quiet_60 mean, minimum and
    names at 0, by year and over the segment (listed only)."""

    def rows(values):
        return [(i, {"inst_quiet_60": v}, f"{i}") for i, v in enumerate(values)]

    assert tool.list_quiet(rows([0, 3, 60, None])) == (21.0, 0, 1, 3)
    assert tool.list_quiet(rows([None])) is None and tool.list_quiet([]) is None
    sessions = weekdays(date(2016, 12, 29), 5)  # 2 in 2016, 3 in 2017
    lists = {0: [5, 1, 0], 1: [10, 10], 2: [], 3: [0, 0, 6, None]}
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [])

    def rank(ctx, spec, day, members):
        return tool.Ranked(rows(lists[sessions.index(day)]))

    monkeypatch.setattr(tool, "rank_u1", rank)
    monkeypatch.setitem(tool.overlap_with, "U1", lambda ctx, day, members: set())
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), gaps={})
    planned = tool.plan(ctx, tool.HYPOTHESES["U1"], "U1", 1, 4)
    assert planned.quiet_lists == {
        "2016": [(2.0, 0, 1, 3), (10.0, 10, 0, 2)],
        "2017": [(2.0, 0, 2, 3)],  # day 2: no list, not counted
    }
    got = tool.list_quiet_summary(planned.quiet_lists)
    assert got["days"] == 3
    assert got["mean"] == pytest.approx((2 + 10 + 2) / 3)
    assert got["min_mean"] == pytest.approx(10 / 3) and got["min"] == 0
    assert got["zero_share"] == pytest.approx(3 / 8)
    assert got["years"]["2016"] == {
        "days": 2, "mean": 6.0, "min_mean": 5.0, "min": 0, "zero_share": 1 / 5,
    }  # fmt: skip
    assert tool.list_quiet_summary({})["mean"] is None


def test_the_u1_saturdays_are_counted_by_hand(monkeypatch):
    days = [date(2016, 1, 4), date(2016, 1, 5), date(2016, 1, 30),  # a Saturday
            date(2016, 2, 1), date(2016, 6, 4), date(2016, 6, 6)]  # fmt: skip
    assert [d.weekday() for d in days] == [0, 1, 5, 0, 5, 0]
    lists = {at: [1] for at in range(6)}
    planned = plan_with(monkeypatch, "U1", lists, {at: {1} for at in range(6)}, days)
    # signal dates 0 .. 4: Saturdays 2 and 4
    assert planned.saturdays == 2
    assert planned.coverage["2016"]["saturdays"] == 2


def test_the_overlap_lists_are_round6s_w1_and_round5s_v3(monkeypatch):
    calls = []

    def spy(module, label):
        def rank(ctx, spec, day, members):
            calls.append((label, spec, ctx))
            return SimpleNamespace(rows=[(i, {}, "") for i in range(30)])

        monkeypatch.setattr(module, "rank", rank)

    spy(r6, "W1")
    spy(r5, "V3")
    ctx = context_for([make_item([10.0])])
    assert tool.w1_names(ctx, date(2016, 1, 4), []) == set(range(20))
    assert tool.v3_names(ctx, date(2016, 1, 4), []) == set(range(20))
    assert calls[0][:2] == ("W1", r6.HYPOTHESES["W1"]) and calls[0][2] is ctx.w1
    assert calls[1][:2] == ("V3", r5.HYPOTHESES["V3"]) and calls[1][2] is ctx.v3
    assert ctx.w1.base is ctx.base and ctx.v3.base is ctx.base


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
        (3.285, "前瞻觀察"),  # round 12's threshold is not this round's
        (3.301, "前瞻觀察"),
        (3.302, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_302(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


def test_the_starts_are_the_registered_sessions():
    sessions = weekdays(date(2012, 11, 26), 2400)
    for name, rule in (
        ("U1", weekdays(OTC_INST, 60)[-1]),
        ("U2", weekdays(OTC_INST, 20)[-1]),
        ("U3", date(2013, 1, 2)),
    ):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == rule, name


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 420
STOCKS = range(1, 25)
DELISTED = {25: 120, 26: 340}  # the last bar's index
INDEX_ID = 90
NO_CHIPS = 4  # no chip row at all: quiet on every bar
GAP = 150  # no TPEx value on this session (U1, U2 missing for TPEx windows on it)
SEMI_IDS = range(1, 9)  # 8 members
PARTS_IDS = (1, *range(9, 13))  # 5 members, 1 in both
PAID_IDS = range(1, 13)  # a cash dividend each year 2011 .. 2016
LATE_PAYER = 15  # 2012 .. 2016: only 2017's signal dates qualify


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def path(i: int) -> list[tuple[float, float, float, float]]:
    out, previous = [], 50.0 + i
    for t in range(SESSIONS):
        close = round(previous * (1 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


def trades_on(i: int, t: int) -> bool:
    """Institutional trading on stock i's bar t: every (i % 5 + 1)-th bar."""

    return (t + i) % (i % 5 + 1) == 0


def member_rows() -> list[list]:
    day = trading_days()[0].isoformat()
    rows = []
    for ids, code in ((SEMI_IDS, "24"), (PARTS_IDS, "28")):
        label = im.GROUP_LABELS["TWSE"][code]
        for i in ids:
            rows.append(
                [day, "TWSE", code, "", label, im.group_id(label), f"S{i}", f"N{i}",
                 im.retroactive("TWSE", code, day)]
            )  # fmt: skip
    rows.sort()
    return rows


def write_members(folder: Path) -> Path:
    target = folder.joinpath(*ms.MEMBERS_DIR, ms.MEMBERS_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(im.table_bytes(member_rows(), "2016-01", "2016-01"))
    return target


def dividend_rows() -> list[dict]:
    rows = []
    for i, years in [*((i, range(2011, 2017)) for i in PAID_IDS),
                     (LATE_PAYER, range(2012, 2017)), (13, range(2011, 2016))]:  # fmt: skip
        for year in years:
            rows.append(
                {"instrument_id": i, "action_date": date(year, 7, 15),
                 "action_type": "cash", "cash_dividend": 0.5,
                 "reference_price": 60.0, "source": "test"}
            )  # fmt: skip
    rows.append(  # 14: 2013 null only
        {"instrument_id": 14, "action_date": date(2013, 7, 15), "action_type": "cash",
         "cash_dividend": None, "reference_price": 60.0, "source": "test"}
    )  # fmt: skip
    for year in (2011, 2012, 2014, 2015):
        rows.append(
            {"instrument_id": 14, "action_date": date(year, 7, 15), "action_type": "cash",
             "cash_dividend": 0.5, "reference_price": 60.0, "source": "test"}
        )  # fmt: skip
    return rows


def build(path_: Path) -> Path:
    engine = create_engine(f"sqlite:///{path_}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ids = [*STOCKS, *DELISTED]
    with Session(engine) as db:
        run = IngestionRun(run_type="collect", source="test", run_date=days[-1])
        db.add(run)
        db.flush()
        db.add(RawPayload(ingestion_run_id=run.id, source="test", endpoint="test"))
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
                    "status": "delisted" if i in DELISTED else "active",
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
                if t > DELISTED.get(i, SESSIONS):
                    break
                open_, high, low, close = prices[t]
                volume = 2_000_000 + 10_000 * i + 5_000 * (t % 7)
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "adj_close": close,
                        "volume": volume,
                        "turnover": close * volume,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": False,
                    }
                )
                if i == NO_CHIPS:
                    continue
                gap = t == GAP and exchange_of(i) == "TPEx"
                flow = 100.0 * (i % 3 - 1) if trades_on(i, t) else 0.0
                chips.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "foreign_buy": None if gap else flow,
                        "trust_buy": None if gap else 0.0,
                        "dealer_buy": None,
                        "margin_balance": 1000.0,
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
        db.execute(insert(CorporateAction), dividend_rows())
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round13")
    write_members(folder)
    return build(folder / "stock.db")


APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    """research_report points these at the copy for app.config."""

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
    members = ms.members_path(fixture_db)
    return one_process(
        lambda: tool.load(fixture_db, members, date(1990, 1, 1), days[-1], raw)
    )


def test_one_panel_serves_the_members_the_actions_and_the_overlaps(loaded):
    assert loaded.groups.market is loaded.base.market
    assert loaded.w1.base is loaded.base and loaded.v3.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "market_gaps", "members", "actions"}
    gaps = loaded.gaps
    assert [s for s, v in enumerate(gaps["TPEx"]) if v] == [GAP]
    assert not any(gaps["TWSE"])
    assert loaded.paid[1] == frozenset(range(2011, 2017))
    assert loaded.paid[14] == frozenset({2011, 2012, 2014, 2015})  # 2013 null
    assert loaded.v3.actions[1].cash == [0.5] * 6  # V3's actions, the same rows


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    item = loaded.panel.series[NO_CHIPS]  # TPEx, no chip row: quiet when data
    at = item.position[days[100]]
    assert tool.inst_quiet_60(loaded, item, at) == 60
    for t in (GAP, GAP + 59):  # windows with the TPEx gap
        assert tool.inst_quiet_60(loaded, item, item.position[days[t]]) is None
    assert tool.inst_quiet_60(loaded, item, item.position[days[GAP + 60]]) == 60
    odd = loaded.panel.series[3]  # TWSE: not touched by the TPEx gap
    t = GAP + 10
    expected = sum(not trades_on(3, k) or 100.0 * (3 % 3 - 1) == 0
                   for k in range(t - 59, t + 1))  # fmt: skip
    assert tool.inst_quiet_60(loaded, odd, odd.position[days[t]]) == expected
    five = loaded.panel.series[5]  # TWSE, flow 100 × (5 % 3 − 1) = +100
    t = 200
    assert tool.flow_i(loaded, five, t) == 100.0 * sum(
        trades_on(5, k) for k in range(t - 19, t + 1)
    )
    day = days[100]
    assert tool.cash_paid_5y(loaded, loaded.panel.series[1], day) is True
    assert tool.cash_paid_5y(loaded, loaded.panel.series[LATE_PAYER], day) is False
    assert tool.cash_paid_5y(loaded, loaded.panel.series[LATE_PAYER], days[300]) is True
    assert tool.cash_paid_5y(loaded, loaded.panel.series[13], days[300]) is False
    assert tool.cash_paid_5y(loaded, loaded.panel.series[14], day) is False


def test_u2_on_the_copy_by_hand(loaded):
    days = trading_days()
    day = days[100]
    members = lib.universe(loaded.panel, day, 1000)
    ranked = tool.rank_u2(loaded, tool.HYPOTHESES["U2"], day, members)
    industry = ranked.industry
    at_of = {item.instrument_id: (item, at) for item, at in members}

    def sums(ids):
        flow = sum(tool.flow_i(loaded, *at_of[i]) for i in ids)
        volume = sum(tool.vol_i(*at_of[i]) for i in ids)
        return flow / volume

    assert industry.ranked[SEMI] == pytest.approx(sums(SEMI_IDS))
    assert industry.ranked[PARTS] == pytest.approx(sums(PARTS_IDS))
    assert industry.keys[1].group == min(SEMI, PARTS)
    assert ranked.missing["several_groups"] == 1
    assert ranked.missing["no_group"] == len(members) - 12
    keys = [values["ind_flow_20"] for _i, values, _t in ranked.rows]
    valued = [k for k in keys if k is not None]
    assert valued == sorted(valued, reverse=True) and len(valued) == 12
    assert keys[: len(valued)] == valued  # the missing ones last
    for instrument_id, values, _tie in ranked.rows[:12]:
        assert values["ind_flow_20"] == industry.ranked[values["group"]]
        assert values["group"] == industry.keys[instrument_id].group


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[299]),
            "validation": (days[300], days[359]),
            "used": (days[360], days[419]),
        },
    )
    floors = {"exploration": 30, "validation": 50}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(ms, "MEMBERS_SHA256", ex.file_sha256(ms.members_path(db)))
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    shutil.copytree(db.parent / ms.MEMBERS_DIR[0], folder / ms.MEMBERS_DIR[0])
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "U1,U2,U3"
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
    compressed(monkeypatch, tmp_path, db)
    return db


@pytest.fixture
def explored(copied, tmp_path):
    out = tmp_path / "exploration"
    assert explore(copied, out) == 0
    return copied, out


def passed_report(out: Path, tmp_path: Path, *names: str) -> Path:
    data = read_json(out / "explore.json")
    for name in data["hypotheses"]:
        data["hypotheses"][name]["verdict"] = (
            ex.EXPLORATION_PASSED if name in names else ex.EXPLORATION_FAILED
        )
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    days = trading_days()
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round13_research",
        "968",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (13, 3, 52)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.302)
    assert report["read_until"] == days[299].isoformat()
    hyp = report["hypotheses"]
    assert hyp["U1"]["overlap_w1"]["days"] > 0 and hyp["U1"]["saturdays"] == 0
    quiet = hyp["U1"]["list_quiet"]
    assert quiet["days"] == hyp["U1"]["overlap_w1"]["days"] == 240
    assert 0 <= quiet["min"] <= quiet["min_mean"] <= quiet["mean"] <= 60
    assert hyp["U2"]["industries"]["days"] > 0
    # M1 needs 241 TAIEX closes: its groups from signal date 240 on
    assert 0 < hyp["U2"]["m1_share"]["days"] <= 299 - 240
    assert hyp["U3"]["overlap_v3"]["days"] > 0
    # 2016's signal dates: PAID_IDS less the delisted ones; 2017's: + LATE_PAYER
    # no population before 20 bars: signal dates 0 .. 18 empty
    assert hyp["U3"]["short"]["zero_days"] == 19
    assert hyp["U3"]["short"]["short_days"] == 299
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 52 個" in text and "驗證段 t ≥ 3.302" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round13_research", 13, "exploration", 1) for name in NAMES]
    for name in NAMES:
        for file in (
            "summary.md",
            "tables.json",
            "equity.csv",
            "picks.csv",
            "trades.csv",
        ):
            assert (out / name / file).is_file(), (name, file)
        summary = (out / name / "summary.md").read_text(encoding="utf-8")
        assert tool.DEGENERATE[name] in summary and tool.OVERLAP_NOTE[name] in summary
    u1_md = (out / "U1" / "summary.md").read_text(encoding="utf-8")
    assert "## 和 W1 的重疊（U1 第 7 點）" in u1_md and "## 週六補班日" in u1_md
    assert "## 每天名單的 `inst_quiet_60`（U1 第 8 點的限制，只列出、不判定）" in u1_md
    assert "U1 每天名單的 `inst_quiet_60`" in text
    u2_md = (out / "U2" / "summary.md").read_text(encoding="utf-8")
    assert "## 落在 M1 前 5 族群的比例（U2 第 8 點）" in u2_md
    assert "## 每天名單的產業數" in u2_md
    u3_md = (out / "U3" / "summary.md").read_text(encoding="utf-8")
    assert "## 和 V3 的重疊（U3 第 6 點）" in u3_md
    picks = (out / "U3" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == "signal_date,rank,exchange,symbol,cash_paid_5y,tie"
    in_2016 = [line for line in picks[1:] if line.startswith(days[100].isoformat())]
    assert len(in_2016) == 13  # PAID_IDS and 13: fewer than 20, the rest is cash
    in_2017 = [line for line in picks[1:] if line.startswith(days[298].isoformat())]
    assert len(in_2017) == 13  # LATE_PAYER joins, 13 (no 2016) drops
    u2_picks = (out / "U2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert u2_picks[0] == "signal_date,rank,exchange,symbol,ind_flow_20,group,tie"


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="U2") == 2
    assert any("U2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="U1,J2") == 2
    assert any("J2 not registered" in line for line in refused(capsys))


def test_the_member_table_is_checked_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ms, "MEMBERS_SHA256", "0" * 64)
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="U2") == 2
    assert any("not the member table's" in line for line in refused(capsys))
    assert opened == [] and not (tmp_path / "x").exists()
    assert explore(copied, tmp_path / "y", "--coverage-only", hypotheses=None) == 2
    assert any("not the member table's" in line for line in refused(capsys))


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
    data["design"] = "962"
    data["hypotheses"]["U2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_302(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "U1", "U3")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [
        ("U1", "round13_research", "finished"),
        ("U3", "round13_research", "finished"),
    ]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["U1", "U3"]
    assert validation["min_t"] == 3.302
    for name in ("U1", "U3"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["min_t"] == 3.302, name
    assert validation["read_until"] == trading_days()[359].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.302" in text
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

    def spy(db, members, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, members, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    report = passed_report(out, tmp_path, "U2")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[359]),
        (tool.LOAD_FROM, days[419]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["U2"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["U2"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "U2" / "used" / file).is_file(), file
    assert "## 已用段" in (tmp_path / "validation" / "explore.md").read_text(
        encoding="utf-8"
    )


def total(coverage: dict, key: str) -> int:
    return sum(row.get(key, 0) for row in coverage.values())


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
    u1 = hyp["U1"]["coverage"]
    # signal dates 59 .. 298: 59 .. 259 in 2016, 260 .. 298 in 2017
    assert (u1["2016"]["days"], u1["2017"]["days"]) == (201, 39)
    assert u1["2016"]["market_gaps"] == {"TPEx": 1, "TWSE": 0}
    assert u1["2017"]["market_gaps"] == {"TPEx": 0, "TWSE": 0}
    # TPEx windows with session 150: signal dates 150 .. 209, 13 TPEx stocks
    # (S26 too, delisted after 340) in the population every day
    tpex = sum(1 for i in [*STOCKS, *DELISTED] if exchange_of(i) == "TPEx")
    assert u1["2016"]["missing"]["market_gap"] == 60 * tpex
    assert u1["2016"]["missing"]["inst_quiet_60"] == 60 * tpex
    assert u1["2016"]["values"]["60"] > 0  # S4 on the other days
    u2 = hyp["U2"]["coverage"]
    # signal dates 150 .. 169: the TPEx members' flow_i missing, SEMI keeps 4
    # valued (1, 3, 5, 7) and PARTS 3 (1, 9, 11): neither ranked
    assert u2["2016"]["max_ranked"] == 2 and u2["2016"]["min_ranked"] == 0
    # and signal date 19: no vol_i (the 20 bars before T)
    assert u2["2016"]["no_ranked_days"] == 21
    # S1 in both industries on every signal date
    assert total(u2, "days") == total({k: v["missing"] for k, v in u2.items()},
                                      "several_groups")  # fmt: skip
    assert u2["2016"]["missing"]["flow_i"] == 20 * tpex  # 150 .. 169
    u3 = hyp["U3"]["coverage"]
    assert (u3["2016"]["min_hits"], u3["2016"]["max_hits"]) == (0, 13)
    assert (u3["2017"]["min_hits"], u3["2017"]["max_hits"]) == (13, 13)
    assert u3["2016"]["zero_days"] == 19
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["U1"] == {"plan", "inst_quiet_60", "w1_order"}
    assert seconds["U2"] == {"plan", "flow_i", "vol_i", "ind_flow_20", "u2_order",
                             "m1_groups"}  # fmt: skip
    assert seconds["U3"] == {"plan", "cash_paid_5y", "v3_order"}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {
        "panel",
        "market_gaps",
        "members",
        "actions",
    }
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert "上櫃整天沒有法人資料的訊號日" in md and "屬於多個產業的檔次" in md
    assert "符合 `cash_paid_5y` 的檔數（每日平均）" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "U1"]
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
    assert explore(copied, tmp_path / "out", hypotheses="U3") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "U3")
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
        assert explore(copied, out, hypotheses="U3") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "U3")
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
