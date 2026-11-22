"""tools/research/round11_research.py: the registered L1～L4 (#953).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十一輪：L1～L4.  The features are checked on hand-made
series (the expected numbers worked out in the test); L1's trades and the
gate ("each once") run on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 400 sessions, everything else is the registered one.
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
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)
from app.strategies import levels

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/953#issuecomment-1"
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
tr = _tool("trade_research")
im = _tool("industry_members")
ms = _tool("mainstream_research")
r5 = _tool("round5_research")
r7 = _tool("round7_research")
r9 = _tool("round9_research")
r10 = _tool("round10_research")
tool = _tool("round11_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("L1", "L2", "L3", "L4")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in (
        "mainstream_research",
        *(f"round{n}_research" for n in range(4, 11)),
    ):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    l1, l2, l3, l4 = (h[name] for name in NAMES)
    assert (l1["engine"], l1["kind"], l1["event"], l1["hold"]) == (
        "trade",
        "event",
        "limit_down_close",
        5,
    )
    assert (l1["stop"], l1["target"], l1["market_filter"], l1["entry_days"]) == (
        None,
        None,
        False,
        1,
    )
    assert l1["start"] == ("date", date(2015, 6, 1))
    assert l2["engine"] == "portfolio"
    assert l2["conditions"] == (
        ("institutional_flow_20", ">", 0.0),
        ("margin_flow_20", "<", 0.0),
    )
    assert l2["ranks"] == (("institutional_flow_20", "high"), ("margin_flow_20", "low"))
    assert l2["score"] == "low"
    assert (l2["top"], l2["hold"], l2["start"]) == (
        20,
        20,
        ("session", date(2014, 12, 1), 20),
    )
    assert (l3["engine"], l3["keys"]) == ("portfolio", (("price_raw", "high"),))
    assert (l3["top"], l3["hold"], l3["start"]) == (20, 60, ("session", OTC, 20))
    assert (l4["engine"], l4["keys"], l4["leaders"]) == (
        "portfolio",
        (("lead_ret_5", "high"),),
        (("turnover_60", "high"),),
    )
    assert (l4["top"], l4["hold"], l4["start"]) == (20, 20, ("date", date(2013, 2, 1)))


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        11,
        4,
        45,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.261
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(45), 3) == 3.261
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.MIN_DAYS == 60 and tool.OVERLAP == 20
    assert tool.REGISTRATION_COMMIT == "5353b141"
    assert (tool.FLOW_MIN, tool.MARGIN_MAX, tool.RANK_WEIGHTS) == (0.0, 0.0, (1, 1))
    assert (tool.RET_WINDOW, tool.LEADERS, tool.MIN_MEMBERS) == (5, 3, 6)
    assert tool.LIMIT_EPS == er.EPS == 1e-9
    # the exit without a stop or a target is round9_research's
    assert tool.NO_STOP == r9.NO_STOP and tool.enter_next_open is r9.enter_next_open
    # L3's overlap with H2 is round10_research's
    assert tool.overlap_summary is r10.overlap_summary


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """PR #930 review 7057395065: each value that changes a verdict changes
    the hash — thresholds, windows, the leaders, the industries' floor, the
    orders, the composite rule, the member table."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.261
    otc = ("session", OTC, 21)
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.234),
        (tool, "LIMIT_EPS", 1e-6),
        (tool, "FLOW_MIN", 0.01),
        (tool, "MARGIN_MAX", -0.01),
        (tool, "RANK_WEIGHTS", (2, 1)),
        (tool, "RET_WINDOW", 4),
        (tool, "LEADERS", 2),
        (tool, "MIN_MEMBERS", 5),
        (tool, "SEVERAL_GROUPS", "largest group id"),
        (tool, "LEADER_RULE", "left out"),
        (tool, "NO_STOP", -1e9),
        (tool, "MIN_DAYS", 50),
        (tool, "MIN_LOTS", 500),
        (r7, "MARGIN_WINDOW", 19),
        (r7, "LOT_SHARES", 1),
        (features, "INSTITUTIONS", ("foreign_buy", "trust_buy")),
        (ex, "TURNOVER_WINDOW", 59),
        (ms, "MEMBERS_SHA256", "0" * 64),
        (er, "LIMIT_BEFORE_WIDENING", Fraction(1, 10)),
        (er, "LIMIT_WIDENED_ON", date(2015, 6, 2)),
        (er, "LIMIT", Fraction(1, 20)),
        (
            tool,
            "HYPOTHESES",
            _swap(
                "L2",
                "conditions",
                (("institutional_flow_20", ">", 0.0), ("margin_flow_20", ">", 0.0)),
            ),
        ),
        (
            tool,
            "HYPOTHESES",
            _swap(
                "L2",
                "ranks",
                (("institutional_flow_20", "high"), ("margin_flow_20", "high")),
            ),
        ),
        (tool, "HYPOTHESES", _swap("L2", "score", "high")),
        (tool, "HYPOTHESES", _swap("L3", "keys", (("price_raw", "low"),))),
        (tool, "HYPOTHESES", _swap("L4", "keys", (("lead_ret_5", "low"),))),
        (tool, "HYPOTHESES", _swap("L4", "leaders", (("turnover_60", "low"),))),
        (tool, "HYPOTHESES", _swap("L1", "hold", 6)),
        (tool, "HYPOTHESES", _swap("L2", "hold", 21)),
        (tool, "HYPOTHESES", _swap("L3", "hold", 59)),
        (tool, "HYPOTHESES", _swap("L4", "hold", 21)),
        (tool, "HYPOTHESES", _swap("L2", "top", 19)),
        (tool, "HYPOTHESES", _swap("L3", "top", 19)),
        (tool, "HYPOTHESES", _swap("L4", "top", 19)),
        (tool, "HYPOTHESES", _swap("L1", "start", ("date", date(2015, 6, 2)))),
        (
            tool,
            "HYPOTHESES",
            _swap("L2", "start", ("session", date(2014, 12, 1), 21)),
        ),
        (tool, "HYPOTHESES", _swap("L3", "start", otc)),
        (tool, "HYPOTHESES", _swap("L4", "start", ("date", date(2013, 2, 4)))),
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
        "--members",
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master 5353b141 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash.
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
}


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


def test_the_docs_tool_section_says_what_the_code_judges():
    """The degenerate cases in the tool section are the code's own strings,
    and coverage.md／summary.md print the same (PR #913 review)."""

    text = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    section = text.split("**第十一輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    assert tool.OVERLAP_NOTE in section
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "tools/research/round11_research.py" in section
    assert "本輪 4 個、累計 45 個" in section


def test_the_round_11_notes_hold_the_two_decisions():
    """#953 決定 7073648898、7073649176: written in 第十一輪實作釋義."""

    text = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    notes = text.split("#### 第十一輪實作釋義", 1)[1].split("\n## ", 1)[0]
    for comment in ("7073648898", "7073649176"):
        assert comment in notes


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes, suspended=(), instrument_id=1, dates=None, chips=None):
    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2016, 1, 4), len(closes))
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


def context_for(items, sessions=None, raw=None, turnover=None, symbols=None):
    """``round11_research.Context`` on hand-made items: ``raw`` {id: unadjusted
    closes} (the adjusted ones by default)."""

    series = {item.instrument_id: item for item in items}
    raw_rows = {
        item.instrument_id: (
            array("d", item.low),
            array("d", item.high),
            array("d", (raw or {}).get(item.instrument_id, item.close)),
            array("d", [0.0] * len(item.close)),
        )
        for item in items
    }
    symbols = symbols or {i: ("TWSE", f"S{i}", "") for i in series}
    panel = lib.Panel(sessions or [], series, {}, {}, symbols)
    base = ex.Context(pr.Market(panel, raw_rows, {}, levels))
    for instrument_id, values in (turnover or {}).items():
        base.turnover[instrument_id] = array("d", values)
    return tool.Context(base, None)


# --- L1: limit_down_close ---------------------------------------------------------


def l1_market(previous: float, close: float, day: date, **flags):
    """Two bars, the previous close and T's (adjusted = unadjusted)."""

    days = [day - timedelta(days=3 if day.weekday() == 0 else 1), day]
    closes = [previous, close]
    if flags.get("missing"):
        closes[1] = NAN
    suspended = (0,) if flags.get("previous_suspended") else ()
    if flags.get("suspended"):
        suspended = (1,)
    item = make_item(closes, suspended=suspended, dates=days)
    return context_for([item]).market, item


def tick_above(price: float) -> float:
    return levels.tick_ceil(price + 1e-6, "stock")


def test_limit_down_close_is_the_close_at_the_limit_down_price():
    day = date(2016, 3, 2)
    limit = levels.tick_ceil(float(Fraction("50") * Fraction(9, 10)), "stock")
    assert limit == 45.0
    market, item = l1_market(50.0, 45.0, day)
    assert tool.limit_down_price(market, item, 1) == (45.0, 45.0)
    assert tool.limit_down_close(market, item, 1) is True
    above = tick_above(45.0)
    assert above == pytest.approx(45.05)
    market, item = l1_market(50.0, above, day)
    assert tool.limit_down_close(market, item, 1) is False  # one tick higher
    market, item = l1_market(50.0, 44.0, day)  # below it (a wrong bar): still ≤
    assert tool.limit_down_close(market, item, 1) is True


def test_limit_down_close_uses_7_percent_before_2015_06_01():
    # 2015-05-29: ±7% (#922), 50 × 0.93 = 46.5; from 2015-06-01: ±10%, 45
    market, item = l1_market(50.0, 46.5, date(2015, 5, 29))
    assert tool.limit_down_price(market, item, 1)[1] == 46.5
    assert tool.limit_down_close(market, item, 1) is True
    market, item = l1_market(50.0, 46.5, date(2015, 6, 1))
    assert tool.limit_down_price(market, item, 1)[1] == 45.0
    assert tool.limit_down_close(market, item, 1) is False


@pytest.mark.parametrize(
    "flags", [{"suspended": True}, {"previous_suspended": True}, {"missing": True}]
)
def test_limit_down_close_does_not_qualify_with_a_suspended_bar_or_a_missing_close(
    flags,
):
    market, item = l1_market(50.0, 45.0, date(2016, 3, 2), **flags)
    assert tool.limit_down_price(market, item, 1) is None
    assert tool.limit_down_close(market, item, 1) is None
    assert (
        tool._signals(SimpleNamespace(market=market, seconds=Counter()), 1, [(item, 1)])
        == []
    )


def test_limit_down_close_needs_a_bar_before():
    market, item = l1_market(50.0, 45.0, date(2016, 3, 2))
    assert tool.limit_down_price(market, item, 0) is None


# --- L2: the two conditions and the composite order --------------------------------


def l2_rank(monkeypatch, values: dict[int, tuple], day=date(2016, 3, 1)):
    """``values``: id -> (institutional_flow_20, margin_flow_20)."""

    monkeypatch.setattr(
        tool,
        "institutional_flow_20",
        lambda ctx, item, at: values[item.instrument_id][0],
    )
    monkeypatch.setattr(
        tool, "margin_flow_20", lambda ctx, item, at: values[item.instrument_id][1]
    )
    members = [(make_item([10.0], instrument_id=i), 0) for i in values]
    ctx = SimpleNamespace(seconds=Counter())
    return tool.rank_l2(ctx, tool.HYPOTHESES["L2"], day, members)


def test_l2_needs_both_strictly_and_a_missing_value_fails(monkeypatch):
    values = {
        1: (0.5, -0.5),  # qualifies
        2: (0.0, -0.5),  # exactly 0: > 0 fails
        3: (0.5, 0.0),  # exactly 0: < 0 fails
        4: (None, -0.5),
        5: (0.5, None),
        6: (-0.1, -0.5),
        7: (0.5, 0.1),
        8: (1e-12, -1e-12),  # just beyond both
    }
    ranked = l2_rank(monkeypatch, values)
    assert {row[0] for row in ranked.rows} == {1, 8}
    assert ranked.hits == 2
    assert ranked.missing == Counter({"institutional_flow_20": 1, "margin_flow_20": 1})


def test_l2_ranks_among_the_qualified_and_takes_the_mean_rank_small_first(monkeypatch):
    day = date(2016, 3, 1)
    values = {
        1: (0.9, -0.1),  # r1 1, r2 4 → 2.5
        2: (0.5, -0.9),  # r1 3, r2 1 → 2
        3: (0.7, -0.5),  # r1 2, r2 2 → 2
        4: (0.1, -0.3),  # r1 4, r2 3 → 3.5
        # out: their values would change the ranks if ranked over the population
        5: (9.9, 0.5),
        6: (-1.0, -9.9),
    }
    ranked = l2_rank(monkeypatch, values, day)
    got = {row[0]: (row[1]["r1"], row[1]["r2"], row[1]["score"]) for row in ranked.rows}
    assert got == {1: (1, 4, 2.5), 2: (3, 1, 2.0), 3: (2, 2, 2.0), 4: (4, 3, 3.5)}
    tied = sorted((2, 3), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == [*tied, 1, 4]


def test_l2_ties_in_a_rank_go_by_the_hash(monkeypatch):
    day = date(2016, 3, 1)
    values = {1: (0.5, -0.5), 2: (0.5, -0.5)}
    ranked = l2_rank(monkeypatch, values, day)
    first, second = sorted((1, 2), key=lambda i: pr.tie_break(day, i))
    got = {row[0]: (row[1]["r1"], row[1]["r2"]) for row in ranked.rows}
    assert got == {first: (1, 1), second: (2, 2)}
    assert [row[0] for row in ranked.rows] == [first, second]


def test_l2_with_fewer_than_20_leaves_cash(monkeypatch):
    values = {i: (0.1 * i, -0.1 * i) for i in range(1, 6)}
    values |= {i: (0.1, 0.1) for i in range(6, 40)}  # 34 that do not qualify
    ranked = l2_rank(monkeypatch, values)
    assert len(ranked.rows) == 5
    picks = {1: [row[0] for row in ranked.rows]}
    quote = lambda i, s: pr.Quote(70.0, 70.0, True)  # noqa: E731
    spec = tool.HYPOTHESES["L2"]
    simulated = pr.simulate(picks, quote, 1, 1, spec["hold"], spec["top"])
    # the account of the day holds 1/20 of the equity; 5 of its 20 shares bought
    assert simulated.bought[0] == pytest.approx(5 * (1 / 20) / 20)


def test_l2_reads_the_two_existing_features(monkeypatch):
    """L2 第 1、2 點: X3's ``institutional_flow_20`` and Y1's ``margin_flow_20``."""

    days = 41
    chips = {
        "foreign_buy": [1000.0] * days,
        "trust_buy": [0.0] * days,
        "dealer_buy": [500.0] * days,
        "margin_balance": [100.0 + 2 * k for k in range(days)][::-1],
    }
    item = make_item([10.0] * days, chips=chips)
    ctx = context_for([item])
    at = 40
    # 20 sessions × 1,500 shares ÷ the 20-bar mean volume 2,000,000
    assert tool.institutional_flow_20(ctx, item, at) == pytest.approx(
        20 * 1500 / 2_000_000
    )
    # (margin[40] − margin[20]) × 1,000 ÷ 2,000,000, the balance falling 2 a day
    assert tool.margin_flow_20(ctx, item, at) == pytest.approx(-40 * 1000 / 2_000_000)
    calls = []
    real = r7.margin_flow_20
    monkeypatch.setattr(r7, "margin_flow_20", lambda *a: calls.append(a) or real(*a))
    tool.margin_flow_20(ctx, item, at)
    assert calls


# --- L3: price_raw and the overlap with H2 -----------------------------------------


def test_price_raw_is_the_unadjusted_close_and_orders_after_an_ex_dividend():
    day = date(2016, 3, 1)
    # adjusted closes say 2 > 1; the unadjusted say 1 > 2 (2 paid a dividend)
    one = make_item([100.0, 100.0], instrument_id=1)
    two = make_item([150.0, 150.0], instrument_id=2)
    three = make_item([80.0, 80.0], instrument_id=3)
    four = make_item([90.0, 90.0], instrument_id=4)
    raw = {1: [120.0, 120.0], 2: [110.0, 110.0], 3: [NAN, NAN], 4: [0.0, 0.0]}
    ctx = context_for([one, two, three, four], raw=raw)
    assert tool.price_raw(ctx, one, 1) == 120.0 and tool.price_raw(ctx, two, 1) == 110.0
    assert (
        tool.price_raw(ctx, three, 1) is None and tool.price_raw(ctx, four, 1) is None
    )
    members = [(item, 1) for item in (one, two, three, four)]
    ranked = tool.rank_l3(ctx, tool.HYPOTHESES["L3"], day, members)
    missing = sorted((3, 4), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == [1, 2, *missing]
    assert ranked.missing["price_raw"] == 2


def test_the_overlap_is_over_l3s_names_and_skips_days_without_a_list(monkeypatch):
    """L3 第 4 點: |L3 ∩ X2| ÷ L3's names on each T; a day when L3 or X2 has
    no list is not counted.  X2's list is round10_research's x2_names."""

    sessions = weekdays(date(2016, 3, 1), 4)
    items = [
        make_item([10.0 * i] * 4, instrument_id=i, dates=sessions) for i in (1, 2, 3)
    ]
    ctx = context_for(items, sessions=sessions)
    population = {
        sessions[0]: [1, 2, 3],
        sessions[1]: [1, 2],
        sessions[2]: [],  # L3 has no list
    }
    x2 = {sessions[0]: {3, 9}, sessions[1]: set(), sessions[2]: {1}}
    by_id = {item.instrument_id: item for item in items}
    monkeypatch.setattr(
        lib,
        "universe",
        lambda panel, day, lots: [
            (by_id[i], panel.sessions.index(day)) for i in population[day]
        ],
    )
    seen = []

    def names(ctx_, day, members):
        seen.append(day)
        return x2[day]

    monkeypatch.setattr(r10, "x2_names", names)
    planned = tool.plan(ctx, tool.HYPOTHESES["L3"], "L3", 1, 3)
    assert seen == sessions[:3]
    # 2016-03-01: 1 of L3's 3 names (3) in X2's; 03-02: X2 has none; 03-03: L3 none
    assert planned.overlap == {"2016": [pytest.approx(1 / 3)]}
    assert tool.overlap_summary(planned.overlap)["days"] == 1


# --- L4: ret_5, the leaders and the followers --------------------------------------

SEMI = im.group_id(im.GROUP_LABELS["TWSE"]["24"])
PARTS = im.group_id(im.GROUP_LABELS["TWSE"]["28"])
PCS = im.group_id(im.GROUP_LABELS["TWSE"]["25"])
CODE_OF = {SEMI: "24", PARTS: "28", PCS: "25"}


def member(i: int, code: str) -> ms.Member:
    label = im.GROUP_LABELS["TWSE"][code]
    return ms.Member("TWSE", code, label, im.group_id(label), f"S{i}", False)


def test_ret_5_by_hand():
    closes = [100.0, 90.0, 95.0, 97.0, 99.0, 110.0, 121.0]
    item = make_item(closes)
    assert tool.ret_5(item, 5) == pytest.approx(110 / 100 - 1)
    assert tool.ret_5(item, 6) == pytest.approx(121 / 90 - 1)
    assert tool.ret_5(item, 4) is None  # fewer than 6 bars


@pytest.mark.parametrize("bad", [0, 5])  # either end
@pytest.mark.parametrize("how", ["suspended", "missing", "zero"])
def test_ret_5_is_missing_with_either_end_suspended_missing_or_not_positive(bad, how):
    closes = [100.0, 90.0, 95.0, 97.0, 99.0, 110.0]
    suspended = ()
    if how == "suspended":
        suspended = (bad,)
    else:
        closes[bad] = NAN if how == "missing" else 0.0
    item = make_item(closes, suspended=suspended)
    assert tool.ret_5(item, 5) is None
    middle = make_item([100.0, 0.0, NAN, 97.0, 99.0, 110.0], suspended=(3,))
    assert tool.ret_5(middle, 5) == pytest.approx(0.10)  # only the two ends count


def l4_context(rets, turnovers, snapshots, days=61, first=date(2016, 1, 4)):
    """Items with bars on every session: close 100 to at − 5, then 100 × (1 +
    ret) at T (a missing ret: T − 5's close missing); a flat turnover each;
    ``snapshots`` {day: [(id, code), ...]}."""

    sessions = weekdays(first, days)
    items = []
    for i, ret in rets.items():
        closes = [100.0] * days
        if ret is None:
            closes[days - 6] = NAN
        else:
            closes[-1] = 100.0 * (1 + ret)
        items.append(make_item(closes, instrument_id=i, dates=sessions))
    ctx = context_for(
        items,
        sessions=sessions,
        turnover={
            i: [NAN if value is None else value] * days
            for i, value in turnovers.items()
        },
    )
    ctx.groups = ms.build_context(
        ctx.market,
        {day: [member(i, code) for i, code in rows] for day, rows in snapshots.items()},
    )
    return ctx, sessions


def l4_rank(ctx, sessions, at=None):
    day = sessions[-1 if at is None else at]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    ranked = tool.rank_l4(ctx, tool.HYPOTHESES["L4"], day, members)
    return ranked, day


def test_l4_leaders_followers_and_the_order_by_hand():
    # SEMI: 1～6 (6 in the population: usable); PARTS: 7～11 (5: not usable); 12 none
    rets = {1: 0.10, 2: 0.20, 3: -0.05, 4: None, 5: 0.0, 6: 0.03}
    rets |= {7: 0.5, 8: 0.5, 9: 0.5, 10: 0.5, 11: 0.5, 12: 0.9}
    turnovers = {1: 600.0, 2: 500.0, 3: 450.0, 4: 900.0, 5: 300.0, 6: 200.0}
    turnovers |= {i: 1000.0 for i in range(7, 13)}
    rows = [(i, "24") for i in range(1, 7)] + [(i, "28") for i in range(7, 12)]
    ctx, sessions = l4_context(rets, turnovers, {date(2016, 1, 4): rows})
    ranked, day = l4_rank(ctx, sessions)
    industry = tool.industry_day(ctx, tool.HYPOTHESES["L4"], day, [
        (item, item.position[day]) for item in ctx.panel.series.values()
    ])  # fmt: skip
    # 4 has the largest turnover but no ret_5: not a leader; 1, 2, 3 lead
    assert industry.leaders == {SEMI: [1, 2, 3]}
    lead = (0.10 + 0.20 - 0.05) / 3
    assert industry.usable == {SEMI: pytest.approx(lead)}
    follow = industry.follow
    # 4 follows without a ret_5 of its own; 5 and 6 too
    for i in (4, 5, 6):
        assert (follow[i].value, follow[i].group, follow[i].reason) == (
            pytest.approx(lead),
            SEMI,
            None,
        )
    assert all(follow[i].reason == "leader" for i in (1, 2, 3))
    assert all(follow[i].reason == "unusable" for i in range(7, 12))  # 5 members
    assert (follow[12].value, follow[12].group, follow[12].reason) == (
        None,
        None,
        "no_group",
    )
    followers = sorted((4, 5, 6), key=lambda i: pr.tie_break(day, i))
    rest = sorted([1, 2, 3, *range(7, 13)], key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows] == [*followers, *rest]
    assert (ranked.usable, ranked.groups, ranked.valued) == (1, 2, 3)
    assert ranked.missing["lead_ret_5"] == 9
    assert (ranked.missing["leader"], ranked.missing["unusable"]) == (3, 5)
    assert ranked.missing["no_group"] == 1
    # 3 valued: the list takes 9 missing ones in, the 3 leaders apart
    assert ranked.filled == Counter({"leader": 3, "other": 6})


def test_l4_a_group_of_6_is_usable_and_of_5_is_not():
    for size, usable in ((5, False), (6, True)):
        rets = {i: 0.01 * i for i in range(1, size + 1)}
        turnovers = {i: 100.0 * i for i in rets}
        rows = [(i, "24") for i in rets]
        ctx, sessions = l4_context(rets, turnovers, {date(2016, 1, 4): rows})
        ranked, _day = l4_rank(ctx, sessions)
        assert (ranked.usable == 1) is usable, size
        assert ranked.valued == (size - 3 if usable else 0), size


def test_l4_needs_3_valued_leaders():
    # 7 members, only 2 with both turnover_60 and ret_5: no leaders, not usable
    rets = {1: 0.1, 2: 0.2, 3: None, 4: None, 5: None, 6: 0.3, 7: 0.4}
    turnovers = {1: 10.0, 2: 20.0, 3: 30.0, 4: 40.0, 5: 50.0, 6: None, 7: None}
    ctx, sessions = l4_context(
        rets, turnovers, {date(2016, 1, 4): [(i, "24") for i in rets]}
    )
    ranked, _day = l4_rank(ctx, sessions)
    assert ranked.usable == 0 and ranked.missing["unusable"] == 7


def test_l4_leaders_tie_on_turnover_by_the_hash():
    rets = {i: 0.01 * i for i in range(1, 8)}
    turnovers = {1: 900.0, 2: 500.0, 3: 500.0, 4: 500.0, 5: 100.0, 6: 100.0, 7: 100.0}
    ctx, sessions = l4_context(
        rets, turnovers, {date(2016, 1, 4): [(i, "24") for i in rets]}
    )
    day = sessions[-1]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    industry = tool.industry_day(ctx, tool.HYPOTHESES["L4"], day, members)
    tied = sorted((2, 3, 4), key=lambda i: pr.tie_break(day, i))
    assert industry.leaders[SEMI] == [1, *tied[:2]]
    assert industry.follow[tied[2]].reason is None  # the third of the tie follows


def test_l4_followers_of_one_group_tie_by_the_hash_and_groups_order_by_lead():
    # SEMI leads +0.3 (leaders 1～3), PCS +0.1 (leaders 7～9)
    rets = {1: 0.3, 2: 0.3, 3: 0.3, 4: 0.0, 5: 0.0, 6: 0.0}
    rets |= {7: 0.1, 8: 0.1, 9: 0.1, 10: 0.9, 11: 0.9, 12: 0.9}
    turnovers = {i: 1000.0 - 10 * i for i in rets}
    rows = [(i, "24") for i in range(1, 7)] + [(i, "25") for i in range(7, 13)]
    ctx, sessions = l4_context(rets, turnovers, {date(2016, 1, 4): rows})
    ranked, day = l4_rank(ctx, sessions)
    semi = sorted((4, 5, 6), key=lambda i: pr.tie_break(day, i))
    pcs = sorted((10, 11, 12), key=lambda i: pr.tie_break(day, i))
    assert [row[0] for row in ranked.rows][:6] == [*semi, *pcs]
    assert (
        tool.industry_count([row[0] for row in ranked.rows[:20]], ranked.groups_of) == 2
    )
    assert tool.industry_count(semi, ranked.groups_of) == 1
    assert tool.industry_count([1, 2], ranked.groups_of) == 0  # leaders: no industry
    assert tool.industry_count([], ranked.groups_of) is None


def test_l4_takes_the_latest_snapshot_up_to_t():
    rets = {i: 0.01 * i for i in range(1, 8)}
    turnovers = {i: 100.0 * i for i in rets}
    sessions = weekdays(date(2016, 1, 4), 61)
    snapshots = {
        sessions[0]: [(i, "24") for i in rets],
        sessions[60]: [(i, "28") for i in rets],  # T's own snapshot counts
        sessions[60] + timedelta(days=1): [(i, "25") for i in rets],  # after T
    }
    ctx, sessions = l4_context(rets, turnovers, snapshots)
    ranked, _day = l4_rank(ctx, sessions)
    assert set(ranked.groups_of.values()) == {PARTS}
    ranked, _day = l4_rank(ctx, sessions, at=59)
    assert set(ranked.groups_of.values()) == {SEMI}


@pytest.mark.parametrize("leads_in_smaller", [False, True])
def test_l4_a_stock_in_two_groups_counts_in_both_and_follows_the_smaller_id(
    leads_in_smaller,
):
    """#953 決定 7073648898: 1 is in both; the larger-id group has exactly 6
    members with it (usable only because it counts there too).  Its own group
    is the smaller id: a leader there is missing, a follower there takes that
    group's lead_ret_5."""

    smaller, larger = sorted((SEMI, PARTS))
    lead_group = smaller if leads_in_smaller else larger
    follow_group = larger if leads_in_smaller else smaller
    # lead_group: 1 and two others lead; follow_group: three others lead, 1 follows
    rets = {1: 0.05, 2: 0.2, 3: 0.2, 4: 0.0, 5: 0.0, 6: 0.0}
    rets |= {7: -0.1, 8: -0.1, 9: -0.1, 10: 0.0, 11: 0.0}
    turnovers = {1: 800.0, 2: 900.0, 3: 850.0, 4: 10.0, 5: 10.0, 6: 10.0}
    turnovers |= {7: 2000.0, 8: 1900.0, 9: 1800.0, 10: 10.0, 11: 10.0}
    rows = [(i, CODE_OF[lead_group]) for i in (1, 2, 3, 4, 5, 6)]
    rows += [(i, CODE_OF[follow_group]) for i in (1, 7, 8, 9, 10, 11)]
    ctx, sessions = l4_context(rets, turnovers, {date(2016, 1, 4): rows})
    day = sessions[-1]
    members = [(item, item.position[day]) for item in ctx.panel.series.values()]
    industry = tool.industry_day(ctx, tool.HYPOTHESES["L4"], day, members)
    assert set(industry.usable) == {SEMI, PARTS}  # both 6, 1 counted in each
    assert industry.leaders[lead_group] == [2, 3, 1]
    assert industry.leaders[follow_group] == [7, 8, 9]
    one = industry.follow[1]
    assert (one.group, one.groups) == (smaller, 2)
    if leads_in_smaller:
        assert (one.value, one.reason) == (None, "leader")
    else:
        assert one.value == pytest.approx(-0.1) and one.reason is None
    ranked = tool.rank_l4(ctx, tool.HYPOTHESES["L4"], day, members)
    assert ranked.missing["several_groups"] == 1


def test_l4_leaders_rank_after_every_valued_follower():
    """#953 決定 7073649176: a leader is missing, last, not left out."""

    rets = {1: 0.9, 2: 0.9, 3: 0.9, 4: -0.5, 5: -0.5, 6: -0.5, 7: -0.5}
    turnovers = {i: 1000.0 - i for i in rets}
    ctx, sessions = l4_context(
        rets, turnovers, {date(2016, 1, 4): [(i, "24") for i in rets]}
    )
    ranked, day = l4_rank(ctx, sessions)
    order = [row[0] for row in ranked.rows]
    assert set(order[:4]) == {4, 5, 6, 7} and set(order[4:]) == {1, 2, 3}
    assert all(row[1]["lead_ret_5"] is None for row in ranked.rows[4:])
    assert len(order) == 7  # none left out


def test_l4_without_a_group_on_t_is_missing():
    rets = {i: 0.01 for i in range(1, 4)}
    ctx, sessions = l4_context(rets, {i: 1.0 for i in rets}, {date(2016, 6, 1): []})
    ranked, _day = l4_rank(ctx, sessions)
    assert ranked.missing["no_group"] == 3 and ranked.groups == 0


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
        (3.234, "前瞻觀察"),  # round 10's threshold is not this round's
        (3.26, "前瞻觀察"),
        (3.261, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_261(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


def test_the_starts_are_the_registered_sessions():
    sessions = weekdays(date(2007, 11, 26), 2400)
    for name, rule in (
        ("L1", date(2015, 6, 1)),
        ("L2", weekdays(date(2014, 12, 1), 20)[-1]),
        ("L3", weekdays(OTC, 20)[-1]),
        ("L4", date(2013, 2, 1)),
    ):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == rule, name


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 400
STOCKS = range(1, 25)
DELISTED = {25: 120, 27: 300}  # the last bar's index
INDEX_ID = 90
NO_CHIPS = 4  # L2: no chip row
L2_HITS = (1, 2, 3, 5, 6, 7, 8)  # flows in, margin falling
SEMI_IDS = range(1, 9)  # L4: usable (8 members)
PARTS_IDS = range(9, 14)  # L4: 5 members, not usable
# L1: (stock, session) -> the bar's kind
EVENTS = {
    (3, 100): "down_close",  # a signal
    (3, 103): "down_close",  # occupied (held 101 .. 105)
    (5, 100): "near",  # one tick above the limit down
    (7, 110): "down_close",
    (7, 111): "suspended",  # T+1 not tradable: abandoned
    (9, 120): "down_close",
    (9, 121): "lock_up",  # T+1 locked at limit up: abandoned
    (11, 130): "down_close",
    (11, 131): "lock_down",  # T+1 locked at limit down: filled at its open
    (13, 140): "down_close",
    (13, 145): "lock_down",  # the 5th session locked: sold at 146's open
    (15, 149): "suspended",
    (15, 150): "down_close",  # the bar before suspended: no signal
    (25, 118): "down_close",  # delisted after 120
    (6, 160): "down_close",  # TPEx
    (17, 246): "down_close",  # the exploration ends on 249
}


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
        kind = EVENTS.get((i, t))
        if kind == "suspended":
            out.append((previous,) * 4)
            continue
        if kind in ("lock_up", "lock_down"):
            price = limit(previous, kind == "lock_up")
            out.append((price,) * 4)
            previous = price
            continue
        if kind in ("down_close", "near"):
            close = limit(previous, False)
            if kind == "near":
                close = tick_above(close)
            out.append((previous, previous, close, close))
            previous = close
            continue
        close = round(previous * (1 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


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
                halted = EVENTS.get((i, t)) == "suspended"
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
                        "turnover": 0.0 if halted else close * (2_000_000 + 10_000 * i),
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": halted,
                    }
                )
                if i != NO_CHIPS:
                    falling = i in L2_HITS
                    chips.append(
                        {
                            "instrument_id": i,
                            "trading_date": day,
                            "foreign_buy": 100.0,
                            "trust_buy": 0.0,
                            "dealer_buy": 0.0,
                            "margin_balance": 3000.0 - t if falling else 1000.0 + t,
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
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round11")
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


def test_one_panel_serves_both_engines_and_the_members(
    loaded, fixture_db, tmp_path_factory
):
    assert loaded.trade.market is loaded.base.market
    assert loaded.groups.market is loaded.base.market
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw-tr")
    other = one_process(lambda: tr.load(fixture_db, date(1990, 1, 1), days[-1], raw))
    assert loaded.trade.statuses == other.statuses
    assert loaded.trade.last_bar == other.last_bar
    assert loaded.trade.last_bar[25] == days[120]
    assert set(loaded.load_seconds) == {"panel", "trade", "members"}


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


def test_l1_trades_by_hand(loaded, monkeypatch):
    d = trading_days()
    result = used_run(loaded, monkeypatch, "L1")
    trades = {(t["signal_date"], t["symbol"]): t for t in result["_trades"]}
    assert sorted(trades) == sorted(
        [
            (d[100], "S3"),  # S5 one tick above; S3 on 103 occupied
            (d[110], "S7"),
            (d[118], "S25"),
            (d[120], "S9"),
            (d[130], "S11"),
            (d[140], "S13"),
            (d[160], "S6"),
            (d[246], "S17"),
        ]
    )  # S15 on 150: the bar before suspended
    s3 = loaded.panel.series[3]
    first = trades[(d[100], "S3")]
    assert (first["fill_date"], first["exit_date"], first["exit_reason"]) == (
        d[101],
        d[105],  # the fill is day 1, the 5th session's close
        "time",
    )
    assert first["holding"] == 5 and first["stop"] is None and first["target"] is None
    assert first["net"] == pytest.approx(
        net(s3.close[s3.position[d[105]]], s3.open[s3.position[d[101]]]), rel=1e-12
    )
    assert first["t1_locked_down"] is False
    assert first["close_raw"] == first["limit_down"]
    halted, locked = trades[(d[110], "S7")], trades[(d[120], "S9")]
    assert (halted["net"], halted["entry_reason"]) == (None, "not_tradable")
    assert (locked["net"], locked["entry_reason"]) == (None, "limit_up")
    assert halted["abandoned_date"] == d[111] and locked["abandoned_date"] == d[121]
    down = trades[(d[130], "S11")]
    s11 = loaded.panel.series[11]
    assert down["t1_locked_down"] is True and down["fill_date"] == d[131]
    assert (
        down["fill_price"]
        == s11.open[s11.position[d[131]]]
        == limit(s11.close[s11.position[d[130]]], False)
    )
    assert (down["exit_date"], down["exit_reason"]) == (d[135], "time")
    delayed = trades[(d[140], "S13")]
    assert (delayed["exit_date"], delayed["exit_reason"], delayed["limit_delayed"]) == (
        d[146],
        "time",
        True,
    )
    assert delayed["holding"] == 6
    s13 = loaded.panel.series[13]
    assert delayed["net"] == pytest.approx(
        net(s13.open[s13.position[d[146]]], s13.open[s13.position[d[141]]]), rel=1e-12
    )
    gone = trades[(d[118], "S25")]
    assert (gone["exit_date"], gone["exit_reason"]) == (d[120], "delisted")
    end = trades[(d[246], "S17")]
    assert (end["exit_date"], end["exit_reason"]) == (d[249], "segment_end")
    assert result["abandon_reasons"] == {"limit_up": 1, "not_tradable": 1}
    assert result["trades"] == 6 and result["signals"] == 8
    assert result["listed"]["t1_locked_down_fills"] == 1
    assert result["listed"]["years"]["2016"]["signals"] == 8
    assert result["listed"]["years"]["2016"]["TPEx:signals"] == 1
    assert result["exits"]["stop"] == result["exits"]["target"] == 0


def test_l1_excess_is_over_the_population_of_t(loaded, monkeypatch):
    days = trading_days()
    result = used_run(loaded, monkeypatch, "L1")
    first = next(t for t in result["_trades"] if t["signal_date"] == days[100])
    expected = tr.baseline(loaded.trade, 100, 101, 105, 249)
    assert first["population"] == expected["mean"]
    assert first["excess"] == pytest.approx(first["net"] - expected["mean"])


def test_l2_and_l4_on_the_copy(loaded):
    days = trading_days()
    day = days[100]
    members = lib.universe(loaded.panel, day, 1000)
    l2 = tool.rank_l2(loaded, tool.HYPOTHESES["L2"], day, members)
    assert {row[0] for row in l2.rows} == set(L2_HITS)
    l4 = tool.rank_l4(loaded, tool.HYPOTHESES["L4"], day, members)
    assert (l4.usable, l4.groups, l4.valued) == (1, 2, 5)
    assert l4.missing["leader"] == 3 and l4.missing["unusable"] == 5


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "L1,L2,L3,L4"
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
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round11_research",
        "953",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (11, 4, 45)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.261)
    assert report["read_until"] == trading_days()[249].isoformat()
    l1 = report["hypotheses"]["L1"]
    assert (l1["engine"], l1["reason"], l1["trades"]) == (
        "trade",
        "too_few_trade_days",
        6,
    )
    assert l1["t1_locked_down_fills"] == 1
    assert report["hypotheses"]["L3"]["overlap_x2"]["days"] > 0
    assert report["hypotheses"]["L4"]["industries"]["mean"] == 1.0
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 4 個、累計 45 個" in text and "驗證段 t ≥ 3.261" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round11_research", 11, "exploration", 1) for name in NAMES]
    for name, files in (
        ("L1", ("summary.md", "tables.json", "trades.csv", "days.csv")),
        ("L2", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("L3", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("L4", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
    ):
        for file in files:
            assert (out / name / file).is_file(), (name, file)
        summary = (out / name / "summary.md").read_text(encoding="utf-8")
        assert tool.DEGENERATE[name] in summary
    picks = (out / "L2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == (
        "signal_date,rank,exchange,symbol,institutional_flow_20,margin_flow_20,"
        "r1,r2,score,tie"
    )
    first_day = [
        line for line in picks[1:] if line.startswith(trading_days()[60].isoformat())
    ]
    assert len(first_day) == len(L2_HITS)  # fewer than 20: the rest is cash
    l1_md = (out / "L1" / "summary.md").read_text(encoding="utf-8")
    assert "| T+1 跌停鎖死、照常以開盤價成交 | 1 |" in l1_md
    assert "| 放棄：T+1 漲停鎖死 | 1 |" in l1_md
    l3_md = (out / "L3" / "summary.md").read_text(encoding="utf-8")
    assert "## 和 H2 的重疊（L3 第 4 點）" in l3_md and tool.OVERLAP_NOTE in l3_md
    l4_md = (out / "L4" / "summary.md").read_text(encoding="utf-8")
    assert "## 名單涉及的產業數（L4 第 7 點）" in l4_md
    assert "補進名單的龍頭檔次" in l4_md
    header = (out / "L1" / "trades.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith(
        "signal_date,exchange,symbol,close_raw,limit_down,t1_locked_down,"
    )


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="L2") == 2
    assert any("L2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="L1,F2") == 2
    assert any("F2 not registered" in line for line in refused(capsys))


def test_the_member_table_is_checked_before_anything_is_read(
    copied, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ms, "MEMBERS_SHA256", "0" * 64)
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="L4") == 2
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
    data["design"] = "936"
    data["hypotheses"]["L2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_261(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "L1", "L3")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [
        ("L1", "round11_research", "finished"),
        ("L3", "round11_research", "finished"),
    ]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["L1", "L3"]
    assert validation["min_t"] == 3.261
    for name in ("L1", "L3"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["min_t"] == 3.261, name
    assert validation["read_until"] == trading_days()[339].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.261" in text
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
    report = passed_report(out, tmp_path, "L4")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[339]),
        (tool.LOAD_FROM, days[399]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["L4"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["L4"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "L4" / "used" / file).is_file(), file
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
    for word in ("excess", "absolute", "verdict", "equity", '"net"', "overlap"):
        assert word not in text
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    hyp = body["hypotheses"]
    days = 189  # signal dates 60 .. 248, all in 2016
    l1 = hyp["L1"]["coverage"]["years"]["2016"]
    # no occupancy: S3 on 103, S11 on 131 and S13 on 145 (locked at limit down,
    # so closed there) count too; 3, 3, 7, 25, 9, 11, 11, 13, 13, 6, 17
    assert (l1["days"], l1["signals"], l1["signal_days"]) == (days, 11, 11)
    assert l1["markets"]["TPEx"]["signals"] == 1
    assert l1["unknown"] == 2  # the bar before suspended: S7 on 112, S15 on 150
    l2 = hyp["L2"]["coverage"]["2016"]
    # S7 is out of the population on 111 (suspended)
    assert l2["days"] == days and l2["hits"] == len(L2_HITS) * days - 1
    assert (l2["hit_days"], l2["max_hits"], l2["over_top_days"]) == (days, 7, 0)
    assert l2["missing"]["institutional_flow_20"] >= days  # stock 4 has no chip row
    l3 = hyp["L3"]["coverage"]["2016"]
    assert l3["missing"].get("price_raw", 0) == 0
    l4 = hyp["L4"]["coverage"]["2016"]
    assert (l4["usable"], l4["groups"], l4["min_usable"]) == (days, 2 * days, 1)
    assert l4["short_days"] == days  # 5 followers a day (4 on 111, S7 suspended)
    members = l4["members"]
    assert l4["missing"]["lead_ret_5"] == members - (5 * days - 1)
    assert l4["missing"]["leader"] == 3 * days
    assert l4["filled_leader"] + l4["filled_other"] == 15 * days + 1
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["L1"] == {"plan", "limit_down_close"}
    assert seconds["L2"] == {
        "plan",
        "institutional_flow_20",
        "margin_flow_20",
        "l2_order",
    }
    assert seconds["L3"] == {"plan", "price_raw", "x2_order"}
    assert seconds["L4"] == {"plan", "ret_5+turnover_60", "l4_order"}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "trade", "members"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert "### L1：依年的訊號數與訊號日數" in md
    assert "有值的跟隨者不足 20 檔的訊號日" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "L1"]
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
    assert explore(copied, tmp_path / "out", hypotheses="L1") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "L1")
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
        assert explore(copied, out, hypotheses="L1") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "L1")
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


def test_the_population_has_the_expected_members(loaded):
    days = trading_days()
    ids = {
        item.instrument_id for item, _ in lib.universe(loaded.panel, days[100], 1000)
    }
    assert ids == {*STOCKS, *DELISTED}
    on_111 = {
        item.instrument_id for item, _ in lib.universe(loaded.panel, days[111], 1000)
    }
    assert 7 not in on_111  # suspended
