"""tools/research/round12_research.py: the registered J1～J4 (#962).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十二輪：J1～J4.  The features are checked on hand-made
series (the expected numbers worked out in the test); J3's trades and the
gate ("each once") run on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 420 sessions and J2's large-cap line into its 26 stocks, everything
else is the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import statistics
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
    CorporateAction,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)
from app.strategies import levels

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/962#issuecomment-1"
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
r5 = _tool("round5_research")
r8 = _tool("round8_research")
r9 = _tool("round9_research")
r10 = _tool("round10_research")
tool = _tool("round12_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}
NAMES = ("J1", "J2", "J3", "J4")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in (
        "mainstream_research",
        *(f"round{n}_research" for n in range(4, 12)),
    ):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    j1, j2, j3, j4 = (h[name] for name in NAMES)
    assert j1["engine"] == "portfolio"
    assert j1["state"] == ("margin_sent_60", ">", 0.0)
    assert j1["keys"] == {"high": (("vol_60", "low"),), "low": (("vol_60", "high"),)}
    assert (j1["top"], j1["hold"], j1["start"]) == (20, 20, ("session", OTC, 61))
    assert j2["engine"] == "portfolio"
    assert j2["exclude"] == ("turnover_60", 150)
    assert j2["conditions"] == (("trust_flow_20", ">", 0.0),)
    assert j2["keys"] == (("trust_flow_20", "high"),)
    assert (j2["top"], j2["hold"], j2["start"]) == (
        20,
        20,
        ("session", date(2014, 12, 1), 60),
    )
    assert (j3["engine"], j3["kind"], j3["event"], j3["hold"]) == (
        "trade",
        "event",
        "cash_div_ex",
        20,
    )
    assert (j3["stop"], j3["target"], j3["market_filter"], j3["entry_days"]) == (
        None,
        None,
        False,
        1,
    )
    assert j3["start"] == ("session", OTC, 20)
    assert (j4["engine"], j4["keys"]) == ("portfolio", (("liq_shock_20", "high"),))
    assert (j4["top"], j4["hold"], j4["start"]) == (20, 60, ("session", OTC, 261))


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        12,
        4,
        49,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.285
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(49), 3) == 3.285
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.MIN_DAYS == 60 and tool.OVERLAP == 20
    assert tool.REGISTRATION_COMMIT == "24d700c3"
    assert (tool.SENT_WINDOW, tool.SENT_MIN) == (60, 0.0)
    assert (tool.LARGE_CAP, tool.TRUST_COLUMNS, tool.TRUST_WINDOW, tool.TRUST_MIN) == (
        150,
        ("trust_buy",),
        20,
        0.0,
    )
    assert tool.YIELD_MIN == 0.03
    assert (tool.ILLIQ_RECENT, tool.ILLIQ_BASE) == (20, 240)
    # imported, not rewritten
    assert tool.order_key is r5.order_key
    assert tool.enter_next_open is r9.enter_next_open and tool.NO_STOP == r9.NO_STOP
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool.load.__code__.co_names.count("load_context")  # explore_research's


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#962 範圍第 1 項: each value that changes a verdict changes the hash —
    the windows (60, 20, 240), the thresholds (0, 0.03), the large-cap line
    150, the orders and J1's two directions, J2's cash rule, J3's hold."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.285
    otc = ("session", OTC, 21)
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.261),
        (tool, "SENT_WINDOW", 59),
        (tool, "SENT_MIN", 0.01),
        (tool, "SENT_MEMBERS", "every instrument"),
        (tool, "STATE_OF_DAY", "the state of the equity session"),
        (tool, "LARGE_CAP", 149),
        (tool, "TRUST_COLUMNS", ("trust_buy", "dealer_buy")),
        (tool, "TRUST_WINDOW", 19),
        (tool, "TRUST_MIN", 0.01),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "YIELD_MIN", 0.025),
        (tool, "NEAR", 1e-6),
        (tool, "SAME_DAY", "the first row"),
        (tool, "ILLIQ_RECENT", 21),
        (tool, "ILLIQ_BASE", 250),
        (tool, "NO_STOP", -1e9),
        (tool, "MIN_DAYS", 50),
        (tool, "MIN_LOTS", 500),
        (r5, "VOL_WINDOW", 59),
        (r5, "VOL_DDOF", 0),
        (ex, "TURNOVER_WINDOW", 59),
        (features, "VERSION", features.VERSION + 1),
        (er, "LIMIT_BEFORE_WIDENING", Fraction(1, 10)),
        (er, "LIMIT_WIDENED_ON", date(2015, 6, 2)),
        (er, "LIMIT", Fraction(1, 20)),
        (
            tool,
            "HYPOTHESES",
            _swap(
                "J1",
                "keys",
                {"high": (("vol_60", "high"),), "low": (("vol_60", "low"),)},
            ),
        ),
        (
            tool,
            "HYPOTHESES",
            _swap(
                "J1",
                "keys",
                {"high": (("vol_60", "low"),), "low": (("vol_60", "low"),)},
            ),
        ),
        (tool, "HYPOTHESES", _swap("J1", "state", ("margin_sent_60", ">=", 0.0))),
        (tool, "HYPOTHESES", _swap("J1", "missing_state", "the population")),
        (tool, "HYPOTHESES", _swap("J2", "exclude", ("turnover_60", 100))),
        (tool, "HYPOTHESES", _swap("J2", "conditions", ())),
        (tool, "HYPOTHESES", _swap("J2", "keys", (("trust_flow_20", "low"),))),
        (tool, "HYPOTHESES", _swap("J2", "short", "filled")),
        (tool, "HYPOTHESES", _swap("J3", "hold", 19)),
        (tool, "HYPOTHESES", _swap("J4", "keys", (("liq_shock_20", "low"),))),
        (tool, "HYPOTHESES", _swap("J1", "hold", 21)),
        (tool, "HYPOTHESES", _swap("J2", "hold", 21)),
        (tool, "HYPOTHESES", _swap("J4", "hold", 59)),
        (tool, "HYPOTHESES", _swap("J1", "top", 19)),
        (tool, "HYPOTHESES", _swap("J2", "top", 19)),
        (tool, "HYPOTHESES", _swap("J4", "top", 19)),
        (tool, "HYPOTHESES", _swap("J1", "start", ("session", OTC, 60))),
        (
            tool,
            "HYPOTHESES",
            _swap("J2", "start", ("session", date(2014, 12, 1), 61)),
        ),
        (tool, "HYPOTHESES", _swap("J3", "start", otc)),
        (tool, "HYPOTHESES", _swap("J4", "start", ("session", OTC, 262))),
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


# AC-1: measured on master 24d700c3 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash; #955's exploration round11_research's.
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
}


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


def test_the_docs_tool_section_says_what_the_code_judges():
    """The degenerate cases in the tool section are the code's own strings,
    and coverage.md／summary.md print the same (PR #913 review)."""

    text = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    section = text.split("**第十二輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "tools/research/round12_research.py" in section
    assert "本輪 4 個、累計 49 個" in section


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


def context_for(items, sessions=None, raw=None, turnover=None, symbols=None):
    """``round12_research.Context`` on hand-made items: ``raw`` {id: unadjusted
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
    return tool.Context(base)


# --- J1: margin_sent_60 and the switch --------------------------------------------


def margin_item(instrument_id: int, then: float, now: float, bars: int = 61):
    """``bars`` bars, margin_balance ``then`` on bar bars − 61 and ``now`` on
    the last one (1 elsewhere)."""

    margin = [1.0] * bars
    margin[bars - 61] = then
    margin[-1] = now
    return make_item(
        [10.0] * bars, instrument_id=instrument_id, chips={"margin_balance": margin}
    )


def test_margin_sent_60_by_hand():
    a, b = margin_item(1, 100.0, 150.0), margin_item(2, 200.0, 100.0)
    # at − 60 missing: neither sum takes it
    c = margin_item(3, NAN, 1000.0)
    d = margin_item(4, 500.0, NAN)  # at missing: neither either
    e = make_item([10.0] * 61, instrument_id=5)  # no chip column at all
    got = tool.margin_sent_60([(x, 60) for x in (a, b, c, d, e)])
    assert got.members == 2
    assert got.value == pytest.approx(250.0 / 300.0 - 1.0)
    assert got.high is False


def test_margin_sent_60_is_missing_without_a_usable_member_or_with_sums_then_le_0():
    assert tool.margin_sent_60([]).value is None
    short = margin_item(1, 100.0, 150.0, bars=61)
    got = tool.margin_sent_60([(short, 59)])  # at − 60 < 0
    assert (got.value, got.high, got.members) == (None, None, 0)
    zero = tool.margin_sent_60([(margin_item(1, 0.0, 5.0), 60)])
    assert (zero.value, zero.high, zero.members) == (None, None, 1)


def j1_rank(monkeypatch, margins: dict[int, tuple], vols: dict[int, float | None]):
    monkeypatch.setattr(tool, "vol_60", lambda ctx, item, at: vols[item.instrument_id])
    members = [(margin_item(i, *margins.get(i, (NAN, NAN))), 60) for i in sorted(vols)]
    ctx = SimpleNamespace(seconds=Counter())
    return tool.rank_j1(ctx, tool.HYPOTHESES["J1"], date(2016, 3, 1), members)


VOLS = {1: 0.02, 2: 0.01, 3: None, 4: 0.03}


def test_j1_above_0_ranks_vol_60_small_first(monkeypatch):
    ranked = j1_rank(monkeypatch, {1: (100.0, 101.0)}, VOLS)
    assert ranked.sentiment.high is True
    assert [row[0] for row in ranked.rows] == [2, 1, 4, 3]  # missing last
    assert {row[1]["state"] for row in ranked.rows} == {"high"}


def test_j1_exactly_0_goes_with_le_0_and_ranks_vol_60_high_first(monkeypatch):
    ranked = j1_rank(monkeypatch, {1: (100.0, 150.0), 2: (200.0, 150.0)}, VOLS)
    assert ranked.sentiment.value == 0.0 and ranked.sentiment.high is False
    assert [row[0] for row in ranked.rows] == [4, 1, 2, 3]  # missing last too
    below = j1_rank(monkeypatch, {1: (100.0, 99.0)}, VOLS)
    assert [row[0] for row in below.rows] == [4, 1, 2, 3]


def test_j1_without_margin_sent_60_has_an_empty_list(monkeypatch):
    ranked = j1_rank(monkeypatch, {}, VOLS)
    assert ranked.sentiment.value is None and ranked.rows == []
    assert ranked.missing["vol_60"] == 1  # still counted for the coverage


def test_j1_reads_round5s_vol_60():
    closes = [10.0 * (1.01 if k % 2 else 0.99) ** (k % 3) for k in range(61)]
    item = make_item(closes)
    ctx = context_for([item])
    assert tool.vol_60(ctx, item, 60) == r5.vol_60(ctx.v1, item, 60)
    assert tool.vol_60(ctx, item, 59) is None


def test_switches_skip_the_missing_days():
    assert tool.switches(["high", "high", None, "low", "low", "high"]) == 2
    assert tool.switches(["low", None, "low"]) == 0
    assert tool.switches([None, None]) == 0


def test_the_excess_by_state_goes_by_the_signal_date():
    first = 10
    differences = [0.01, 0.02, -0.01, 0.03]
    # equity session first + i is bought on the list of signal date first + i − 1
    states = {9: "high", 10: "high", 11: None, 12: "low"}
    got = tool.state_excess(differences, states, first)
    assert got["high"] == pr.excess_metrics([0.01, 0.02])
    assert got["missing"] == pr.excess_metrics([-0.01])
    assert got["low"] == pr.excess_metrics([0.03])


def test_the_state_summary_by_hand():
    sessions = [date(2015, 12, 30), date(2015, 12, 31), date(2016, 1, 4),
                date(2016, 1, 5), date(2016, 1, 6)]  # fmt: skip
    states = {0: "high", 1: "low", 2: None, 3: "low", 4: "high"}
    got = tool.state_summary(states, sessions)
    assert got["days"] == 5 and got["switches"] == 2
    assert got["high"] == {"days": 2, "share": 0.4}
    assert got["low"] == {"days": 2, "share": 0.4}
    assert got["missing"] == {"days": 1, "share": 0.2}
    assert got["years"]["2015"]["high"] == {"days": 1, "share": 0.5}
    assert got["years"]["2016"]["missing"] == {"days": 1, "share": 1 / 3}


def plan_with(
    monkeypatch, name: str, lists: dict[int, list[int]], others: dict[int, set]
):
    """``plan`` with the day's list and the other hypothesis's list given by
    signal date index: the overlap only."""

    sessions = weekdays(date(2016, 1, 4), 6)
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [])

    def rank(ctx, spec, day, members):
        at = sessions.index(day)
        rows = [(i, {}, f"{i}") for i in lists[at]]
        return tool.Ranked(rows, sentiment=tool.Sentiment(None, None, 0))

    monkeypatch.setattr(tool, f"rank_{name.lower()}", rank)
    monkeypatch.setitem(
        tool.overlap_with, name, lambda ctx, day, members: others[sessions.index(day)]
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}))
    return tool.plan(ctx, tool.HYPOTHESES[name], name, 1, 5)


@pytest.mark.parametrize("name", ["J1", "J4"])
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


def test_the_overlap_lists_are_round5s_v1_and_round8s_z1(monkeypatch):
    calls = []

    def spy(module, label):
        def rank(ctx, spec, day, members):
            calls.append((label, spec, ctx))
            return SimpleNamespace(rows=[(i, {}, "") for i in range(30)])

        monkeypatch.setattr(module, "rank", rank)

    spy(r5, "V1")
    spy(r8, "Z1")
    ctx = context_for([make_item([10.0])])
    assert tool.v1_names(ctx, date(2016, 1, 4), []) == set(range(20))
    assert tool.z1_names(ctx, date(2016, 1, 4), []) == set(range(20))
    assert calls[0][:2] == ("V1", r5.HYPOTHESES["V1"]) and calls[0][2] is ctx.v1
    assert calls[1][:2] == ("Z1", r8.HYPOTHESES["Z1"]) and calls[1][2] is ctx.z1
    assert ctx.v1.base is ctx.base and ctx.z1.base is ctx.base


# --- J2: the complement of the large caps and the trusts --------------------------


def test_trust_flow_20_is_feature_evidences_flow_by_hand():
    trust = [1000.0] * 35
    item = make_item([10.0] * 35, chips={"trust_buy": trust})
    # the 20 trusts of bars 5..24 over the mean volume of bars 4..23
    assert tool.trust_flow_20(item, 24) == pytest.approx(20_000.0 / 2_000_000.0)
    assert tool.trust_flow_20(item, 24) == features._flow(("trust_buy",), 20)(item, 24)
    assert tool.trust_flow_20(item, 19) is None  # no 20 bars before T
    trust[10] = NAN  # one missing trust in the 20 bars: missing
    item = make_item([10.0] * 35, chips={"trust_buy": trust})
    assert tool.trust_flow_20(item, 24) is None
    assert tool.trust_flow_20(item, 29) is None  # bars 10 .. 29
    assert tool.trust_flow_20(item, 30) is not None  # bar 10 out of the window
    no_volume = make_item(
        [10.0] * 25, chips={"trust_buy": [1.0] * 25}, volume=[0.0] * 25
    )
    assert tool.trust_flow_20(no_volume, 24) is None
    assert tool.trust_flow_20(make_item([10.0] * 25), 24) is None  # no chip column


def j2_rank(
    monkeypatch, turnovers: dict[int, float | None], trusts: dict[int, float | None]
):
    monkeypatch.setattr(
        tool, "turnover_60", lambda ctx, item, at: turnovers[item.instrument_id]
    )
    monkeypatch.setattr(
        tool, "trust_flow_20", lambda item, at: trusts.get(item.instrument_id)
    )
    members = [(make_item([10.0], instrument_id=i), 0) for i in sorted(turnovers)]
    ctx = SimpleNamespace(seconds=Counter())
    return tool.rank_j2(ctx, tool.HYPOTHESES["J2"], date(2016, 3, 1), members)


def test_j2_leaves_out_the_top_150_and_the_missing_turnovers(monkeypatch):
    turnovers = {i: 1000.0 + i for i in range(1, 155)}  # 5 .. 154 are the top 150
    turnovers[155] = None
    trusts = {1: 0.5, 2: 0.0, 3: None, 4: 0.2, 154: 9.9, 155: 5.0}
    ranked = j2_rank(monkeypatch, turnovers, trusts)
    assert [row[0] for row in ranked.rows] == [1, 4]  # trust_flow_20 high first
    assert ranked.excluded == 150 and ranked.hits == 2
    assert ranked.positive == 4  # 1, 4, 154, 155: counted in the population
    assert ranked.missing["turnover_60"] == 1
    assert ranked.missing["trust_flow_20"] == 150  # 3 and the 149 without a value


def test_j2_ties_at_the_150th_go_by_the_hash(monkeypatch):
    day = date(2016, 3, 1)
    turnovers = {i: 1000.0 + i for i in range(1, 155)}
    turnovers[4] = turnovers[5]  # 4 and 5 tie for the 150th
    trusts = {4: 1.0, 5: 1.0}
    ranked = j2_rank(monkeypatch, turnovers, trusts)
    inside = 4 if pr.tie_break(day, 4) < pr.tie_break(day, 5) else 5
    assert [row[0] for row in ranked.rows] == [9 - inside]


def test_j2_with_fewer_than_20_leaves_cash(monkeypatch):
    turnovers = {i: 1000.0 + i for i in range(1, 181)}
    trusts = {i: 0.01 * i for i in range(1, 31)}  # 1 .. 30 outside the top 150
    trusts.update({i: 0.0 for i in range(1, 21)})  # 20 of them exactly 0
    ranked = j2_rank(monkeypatch, turnovers, trusts)
    assert [row[0] for row in ranked.rows] == list(range(30, 20, -1))  # only 10
    assert ranked.hits == 10
    coverage: dict = {}
    for hits in (25, 20, 19, 0):
        tool._coverage_add(
            coverage, "J2", date(2016, 3, 1), 30, tool.Ranked([], hits=hits)
        )
    assert tool.short_summary(coverage) == {
        "short_days": 2,
        "zero_days": 1,
        "years": {"2016": {"days": 4, "short_days": 2, "zero_days": 1}},
    }
    picks = pr.simulate(
        {1: [row[0] for row in ranked.rows]},
        lambda i, s: pr.Quote(10.0, 10.0, True, False, False),
        1,
        1,
        20,
        20,
    )
    # one account of 20 holds 10 names at 1/20 of its cash each: half of it
    assert picks.invested[0] == pytest.approx(0.5 / 20, rel=1e-2)


# --- J3: cash_div_ex --------------------------------------------------------------


def j3_ctx(raw_before: float, cash, adjusted_before: float | None = None, **flags):
    adjusted = raw_before if adjusted_before is None else adjusted_before
    closes = [adjusted, adjusted * 0.97]
    if flags.get("missing"):
        closes[0] = NAN
    suspended = (0,) if flags.get("suspended") else ()
    item = make_item(closes, suspended=suspended)
    raw = [raw_before if not flags.get("missing") else NAN, raw_before * 0.97]
    ctx = context_for([item], raw={1: raw})
    ctx.cash_div = {1: {1: cash}}
    return ctx, item


def test_cash_div_ex_is_3_percent_of_the_bar_befores_unadjusted_close():
    ctx, item = j3_ctx(50.0, 1.5)
    assert tool.cash_div_ex(ctx, item, 1, 1) is True  # exactly 3%
    ctx, item = j3_ctx(50.0, 1.49)
    assert tool.cash_div_ex(ctx, item, 1, 1) is False
    # the adjusted close before (40) would make 3.5%: the unadjusted 50 makes 2.8%
    ctx, item = j3_ctx(50.0, 1.4, adjusted_before=40.0)
    assert tool.cash_div_ex(ctx, item, 1, 1) is False
    parts = tool.cash_div_parts(ctx, item, 1, 1)
    assert (parts.cash, parts.close) == (1.4, 50.0)


def test_cash_div_ex_at_exactly_3_percent_compares_the_decimals():
    assert 2.01 / 67.0 < 0.03  # the float falls short of 3%
    ctx, item = j3_ctx(67.0, 2.01)
    assert tool.cash_div_ex(ctx, item, 1, 1) is True
    ctx, item = j3_ctx(67.0, 2.0)
    assert tool.cash_div_ex(ctx, item, 1, 1) is False


@pytest.mark.parametrize(
    "cash, flags, expected",
    [
        (None, {}, None),  # cash_dividend null
        (2.0, {"suspended": True}, None),  # the bar before suspended
        (2.0, {"missing": True}, None),  # the bar before's close missing
        (0.0, {}, False),
        (-1.0, {}, False),
    ],
)
def test_cash_div_ex_does_not_qualify_without_a_cash_dividend_or_a_bar_before(
    cash, flags, expected
):
    ctx, item = j3_ctx(50.0, cash, **flags)
    assert tool.cash_div_ex(ctx, item, 1, 1) is expected
    assert tool._signals(ctx, 1, [(item, 1)]) == []


def test_cash_div_ex_without_a_row_on_t_or_a_bar_before():
    ctx, item = j3_ctx(50.0, 2.0)
    assert tool.cash_div_ex(ctx, item, 0, 0) is False  # no row on session 0
    ctx.cash_div = {1: {0: 2.0}}
    assert tool.cash_div_ex(ctx, item, 0, 0) is None  # no bar before


def action(day: date, cash, ratio=None):
    return SimpleNamespace(
        action_date=day, cash_dividend=cash, stock_dividend_ratio=ratio
    )


def test_cash_dividends_take_the_largest_row_and_the_next_session():
    sessions = weekdays(date(2016, 1, 4), 10)  # Mon 4 .. Fri 15
    holders = {
        1: SimpleNamespace(
            actions=[
                action(sessions[2], 1.0),
                action(sessions[2], 2.5),
                action(sessions[2], None),
            ]
        ),  # fmt: skip
        2: SimpleNamespace(
            actions=[action(sessions[3], None), action(sessions[3], None)]
        ),
        3: SimpleNamespace(actions=[action(date(2016, 1, 9), 3.0)]),  # a Saturday
        4: SimpleNamespace(actions=[action(date(2016, 1, 16), 3.0)]),  # after the last
    }
    got = tool.cash_dividends(sessions, holders)
    assert got == {1: {2: 2.5}, 2: {3: None}, 3: {5: 3.0}}


# --- J4: liq_shock_20 -------------------------------------------------------------


def liq_series(bars: int = 262):
    closes = [100.0 * (1.0 + 0.01 * ((k * 7) % 5 - 2)) for k in range(bars)]
    turnover = [1e6 * (1 + (k % 4)) for k in range(bars)]
    return closes, turnover


def a_of(closes, turnover, k):
    return abs(closes[k] / closes[k - 1] - 1.0) / turnover[k]


def liq(closes, turnover, at=261, suspended=()):
    item = make_item(closes, suspended=suspended)
    ctx = context_for([item], turnover={1: turnover})
    return tool.liq_shock_20(ctx, item, at)


def test_liq_shock_20_by_hand():
    closes, turnover = liq_series()
    at = 261
    recent = statistics.fmean(a_of(closes, turnover, k) for k in range(at - 19, at + 1))
    base = statistics.fmean(a_of(closes, turnover, k) for k in range(at - 259, at - 19))
    assert liq(closes, turnover) == pytest.approx(1.0 - recent / base, rel=1e-9)
    assert liq(closes, turnover, at=259) is None  # 260 closes, not 261
    assert liq(closes, turnover, at=260) is not None


def test_liq_shock_20_is_missing_with_a_bad_bar_among_the_261():
    closes, turnover = liq_series()
    t = list(turnover)
    t[1] = 0.0  # at − 260: its turnover is not one of the 260
    assert liq(closes, t) is not None
    t = list(turnover)
    t[2] = 0.0  # at − 259
    assert liq(closes, t) is None
    t = list(turnover)
    t[261] = NAN  # not available (explore_research leaves it NaN)
    assert liq(closes, t) is None
    c = list(closes)
    c[1] = 0.0
    assert liq(c, turnover) is None
    c = list(closes)
    c[200] = NAN
    assert liq(c, turnover) is None
    assert liq(closes, turnover, suspended=(1,)) is None  # the first of the 261
    assert liq(closes, turnover, suspended=(0,)) is not None  # before them
    assert liq(closes, turnover, suspended=(261,)) is None
    item = make_item(closes)
    assert tool.liq_shock_20(context_for([item]), item, 261) is None  # no turnover


def test_liq_shock_20_is_missing_when_illiq_base_is_0():
    closes, turnover = liq_series()
    flat = [100.0] * 242 + closes[242:]  # every a of k = 2 .. 241 is 0
    assert liq(flat, turnover) is None
    almost = list(flat)
    almost[100] = 100.5  # one a in the base: a value again
    assert liq(almost, turnover) is not None
    still = [100.0] * 262  # the recent ones 0 too: 1 − 0 ÷ base is not reached
    assert liq(still, turnover) is None


def test_j4_ranks_liq_shock_20_high_first_and_missing_last(monkeypatch):
    values = {1: 0.2, 2: None, 3: 0.5, 4: -0.1}
    monkeypatch.setattr(
        tool, "liq_shock_20", lambda ctx, item, at: values[item.instrument_id]
    )
    members = [(make_item([10.0], instrument_id=i), 0) for i in values]
    ctx = SimpleNamespace(seconds=Counter())
    ranked = tool.rank_j4(ctx, tool.HYPOTHESES["J4"], date(2016, 3, 1), members)
    assert [row[0] for row in ranked.rows] == [3, 1, 4, 2]
    assert ranked.missing["liq_shock_20"] == 1


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
        (3.261, "前瞻觀察"),  # round 11's threshold is not this round's
        (3.284, "前瞻觀察"),
        (3.285, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_285(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


def test_the_starts_are_the_registered_sessions():
    sessions = weekdays(date(2007, 11, 26), 2400)
    for name, rule in (
        ("J1", weekdays(OTC, 61)[-1]),
        ("J2", weekdays(date(2014, 12, 1), 60)[-1]),
        ("J3", weekdays(OTC, 20)[-1]),
        ("J4", weekdays(OTC, 261)[-1]),
    ):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == rule, name


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 420
STOCKS = range(1, 25)
DELISTED = {25: 120, 26: 340, 27: 290}  # the last bar's index
INDEX_ID = 90
NO_CHIPS = 4
TRUST_HITS = (2, 3, 5, 8, 11, 24)  # trust_buy > 0; 24 is a large cap
LARGE = 5  # J2's line in the compressed copy (26 stocks)
# the bar's kind: (stock, session)
PRICES = {
    (7, 131): "suspended",  # T+1 not tradable: abandoned
    (9, 141): "lock_up",  # T+1 locked at limit up: abandoned
    (11, 151): "lock_down",  # T+1 locked at limit down: filled at its open
    (13, 180): "lock_down",  # the 20th session locked: sold at 181's open
    (21, 199): "suspended",  # the bar before T suspended: no signal
}
# J3: (stock, session of T) -> the kind of the day's rows
DIVIDENDS = {
    (3, 100): "ok",  # held 101 .. 120
    (3, 110): "ok",  # occupied: no signal
    (5, 100): "low",  # 2.9%
    (7, 130): "ok",
    (9, 140): "ok",
    (11, 150): "ok",
    (13, 160): "ok",
    (15, 170): "saturday",  # dated the Saturday before session 170
    (17, 180): "two",  # a null row and a 3.1% one with a stock dividend (F1's too)
    (19, 190): "null",
    (21, 200): "ok",
    (25, 110): "ok",  # delisted after 120
    (6, 210): "ok",  # TPEx
    (23, 290): "ok",  # the used run ends on 299
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
        kind = PRICES.get((i, t))
        if kind == "suspended":
            out.append((previous,) * 4)
            continue
        if kind in ("lock_up", "lock_down"):
            price = limit(previous, kind == "lock_up")
            out.append((price,) * 4)
            previous = price
            continue
        close = round(previous * (1 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def margin(i: int, t: int) -> float:
    """J1: up to 200, down to 300, up again; each stock the same shape, so
    the sums of T and T − 60 are equal on 230 and 330 (exactly 0: low)."""

    if t < 200:
        m = t
    elif t < 300:
        m = 400 - t
    else:
        m = t - 200
    return 1000.0 + 10 * i + m


def state_on(t: int) -> str:
    return "high" if margin(1, t) > margin(1, t - 60) else "low"


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


def dividend_rows(days: list[date]) -> list[dict]:
    rows = []
    for (i, t), kind in DIVIDENDS.items():
        before = path(i)[t - 1][3]
        cash = round(before * (0.029 if kind == "low" else 0.031), 2)
        day = days[t]
        if kind == "saturday":
            day = days[t - 1] + timedelta(days=1)
            assert day.weekday() == 5
        common = {"instrument_id": i, "action_date": day, "source": "test"}
        if kind == "two":
            rows.append({**common, "action_type": "cash", "cash_dividend": None})
            rows.append(
                {**common, "action_type": "both", "cash_dividend": cash,
                 "stock_dividend_ratio": 0.1}
            )  # fmt: skip
        elif kind == "null":
            rows.append({**common, "action_type": "cash", "cash_dividend": None})
        else:
            rows.append({**common, "action_type": "cash", "cash_dividend": cash})
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
                halted = PRICES.get((i, t)) == "suspended"
                volume = 0 if halted else 2_000_000 + 10_000 * i + 5_000 * (t % 7)
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
                        "is_suspended": halted,
                    }
                )
                if i != NO_CHIPS:
                    chips.append(
                        {
                            "instrument_id": i,
                            "trading_date": day,
                            "foreign_buy": 100.0,
                            "trust_buy": 100.0 * i if i in TRUST_HITS else 0.0,
                            "dealer_buy": 0.0,
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
        db.execute(insert(CorporateAction), dividend_rows(days))
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round12") / "stock.db")


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
    return one_process(lambda: tool.load(fixture_db, date(1990, 1, 1), days[-1], raw))


def test_one_panel_serves_both_engines_and_the_actions(
    loaded, fixture_db, tmp_path_factory
):
    assert loaded.trade.market is loaded.base.market
    assert loaded.v1.base is loaded.base and loaded.z1.base is loaded.base
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw-tr")
    other = one_process(lambda: tr.load(fixture_db, date(1990, 1, 1), days[-1], raw))
    assert loaded.trade.statuses == other.statuses
    assert loaded.trade.last_bar == other.last_bar
    assert loaded.trade.last_bar[25] == days[120]
    assert set(loaded.load_seconds) == {"panel", "trade", "actions"}
    assert loaded.cash_div[15] == {
        170: pytest.approx(round(path(15)[169][3] * 0.031, 2))
    }
    assert loaded.cash_div[19] == {190: None}
    assert loaded.stock_div[17] == {180: 0.1}


def used_run(loaded, monkeypatch, name: str) -> dict:
    """``name`` on the signal dates 59 .. 298, the last session 299 (the used
    segment's rules: no floor, no delisted check; nothing else differs)."""

    days = trading_days()
    monkeypatch.setattr(
        tool, "SEGMENTS", {**tool.SEGMENTS, "used": (days[60], days[299])}
    )
    loaded.trade.baselines.clear()
    loaded.trade.universes.clear()
    return tool.run_trades(loaded, Path("unused"), name, "used")


def net(sold: float, bought: float) -> float:
    return sold * (1 - 5e-4) / (bought * (1 + 5e-4)) - 1 - 58.5e-4


def test_j3_trades_by_hand(loaded, monkeypatch):
    d = trading_days()
    result = used_run(loaded, monkeypatch, "J3")
    trades = {(t["signal_date"], t["symbol"]): t for t in result["_trades"]}
    assert sorted(trades) == sorted(
        [
            (d[100], "S3"),  # S5 at 2.9%; S3 on 110 occupied
            (d[110], "S25"),
            (d[130], "S7"),
            (d[140], "S9"),
            (d[150], "S11"),
            (d[160], "S13"),
            (d[170], "S15"),  # dated the Saturday before
            (d[180], "S17"),
            (d[210], "S6"),
            (d[290], "S23"),
        ]
    )  # S19 on 190: a null cash dividend; S21 on 200: the bar before suspended
    s3 = loaded.panel.series[3]
    first = trades[(d[100], "S3")]
    assert (first["fill_date"], first["exit_date"], first["exit_reason"]) == (
        d[101],
        d[120],  # the fill is day 1, the 20th session's close
        "time",
    )
    assert first["holding"] == 20 and first["stop"] is None and first["target"] is None
    assert first["net"] == pytest.approx(
        net(s3.close[s3.position[d[120]]], s3.open[s3.position[d[101]]]), rel=1e-12
    )
    before = path(3)[99][3]
    assert first["close_before_raw"] == before
    assert first["cash_dividend"] == pytest.approx(round(before * 0.031, 2))
    assert first["cash_yield"] == pytest.approx(first["cash_dividend"] / before)
    assert first["t1_locked_down"] is False and first["stock_div_ex"] is False
    halted, locked = trades[(d[130], "S7")], trades[(d[140], "S9")]
    assert (halted["net"], halted["entry_reason"]) == (None, "not_tradable")
    assert (locked["net"], locked["entry_reason"]) == (None, "limit_up")
    down = trades[(d[150], "S11")]
    s11 = loaded.panel.series[11]
    assert down["t1_locked_down"] is True and down["fill_date"] == d[151]
    assert down["fill_price"] == s11.open[s11.position[d[151]]]
    assert (down["exit_date"], down["exit_reason"]) == (d[170], "time")
    delayed = trades[(d[160], "S13")]
    assert (delayed["exit_date"], delayed["exit_reason"], delayed["limit_delayed"]) == (
        d[181],
        "time",
        True,
    )
    assert delayed["holding"] == 21
    s13 = loaded.panel.series[13]
    assert delayed["net"] == pytest.approx(
        net(s13.open[s13.position[d[181]]], s13.open[s13.position[d[161]]]), rel=1e-12
    )
    assert trades[(d[180], "S17")]["stock_div_ex"] is True
    gone = trades[(d[110], "S25")]
    assert (gone["exit_date"], gone["exit_reason"]) == (d[120], "delisted")
    end = trades[(d[290], "S23")]
    assert (end["exit_date"], end["exit_reason"]) == (d[299], "segment_end")
    assert result["abandon_reasons"] == {"limit_up": 1, "not_tradable": 1}
    assert result["trades"] == 8 and result["signals"] == 10
    assert result["listed"]["t1_locked_down_fills"] == 1
    assert result["listed"]["f1_both"] == 1
    years = result["listed"]["years"]  # session 260 is 2017's first
    assert (years["2016"]["signals"], years["2017"]["signals"]) == (9, 1)
    assert years["2016"]["TPEx:signals"] == 1
    assert result["exits"]["stop"] == result["exits"]["target"] == 0


def test_j3_excess_is_over_the_population_of_t(loaded, monkeypatch):
    days = trading_days()
    result = used_run(loaded, monkeypatch, "J3")
    first = next(t for t in result["_trades"] if t["signal_date"] == days[100])
    expected = tr.baseline(loaded.trade, 100, 101, 120, 299)
    assert first["population"] == expected["mean"]
    assert first["excess"] == pytest.approx(first["net"] - expected["mean"])


def test_j1_and_j2_on_the_copy(loaded, monkeypatch):
    days = trading_days()
    # 230 and 330: the sums of T and T − 60 are equal, exactly 0 is low
    expected = {
        100: "high",
        229: "high",
        230: "low",
        250: "low",
        330: "low",
        331: "high",
    }
    for t, state in expected.items():
        assert state_on(t) == state, t
        day = days[t]
        members = lib.universe(loaded.panel, day, 1000)
        j1 = tool.rank_j1(loaded, tool.HYPOTHESES["J1"], day, members)
        assert tool.state_of(j1.sentiment) == state, t
        assert j1.sentiment.members == len(members) - 1  # S4 has no chip row
        if t in (230, 330):
            assert j1.sentiment.value == 0.0
    day = days[100]
    members = lib.universe(loaded.panel, day, 1000)
    monkeypatch.setitem(tool.HYPOTHESES["J2"], "exclude", ("turnover_60", LARGE))
    j2 = tool.rank_j2(loaded, tool.HYPOTHESES["J2"], day, members)
    valued = sorted(
        (
            (
                -tool.turnover_60(loaded, item, at),
                pr.tie_break(day, item.instrument_id),
            ),
            item.instrument_id,
        )
        for item, at in members
    )
    large = {i for _key, i in valued[:LARGE]}
    assert 24 in large  # a trust hit, left out
    hits = [i for i in sorted(TRUST_HITS, reverse=True) if i not in large]
    assert [row[0] for row in j2.rows] == hits


def compressed(monkeypatch, tmp_path: Path) -> None:
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
    starts = {"J4": ("session", days[0], 262)}
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {
                **spec,
                "start": starts.get(name, ("session", days[0], 61)),
                **({"exclude": ("turnover_60", LARGE)} if name == "J2" else {}),
            }
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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "J1,J2,J3,J4"
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
        "round12_research",
        "962",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (12, 4, 49)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.285)
    assert report["read_until"] == days[299].isoformat()
    j3 = report["hypotheses"]["J3"]
    assert (j3["engine"], j3["reason"], j3["trades"]) == (
        "trade",
        "too_few_trade_days",
        8,
    )
    assert (j3["t1_locked_down_fills"], j3["f1_both"]) == (1, 1)
    j1 = report["hypotheses"]["J1"]
    assert j1["overlap_v1"]["days"] > 0
    # signal dates 60 .. 298: high to 229, low from 230
    assert (j1["states"]["high"]["days"], j1["states"]["low"]["days"]) == (170, 69)
    assert j1["states"]["switches"] == 1 and j1["states"]["missing"]["days"] == 0
    assert set(j1["state_excess"]) == {"high", "low", "missing"}
    assert (
        j1["state_excess"]["high"]["days"] + j1["state_excess"]["low"]["days"]
        == (j1["excess"]["days"])
    )
    assert report["hypotheses"]["J2"]["short"]["short_days"] == 239
    assert report["hypotheses"]["J4"]["overlap_z1"]["days"] > 0
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 4 個、累計 49 個" in text and "驗證段 t ≥ 3.285" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round12_research", 12, "exploration", 1) for name in NAMES]
    for name, files in (
        ("J1", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("J2", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
        ("J3", ("summary.md", "tables.json", "trades.csv", "days.csv")),
        ("J4", ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")),
    ):
        for file in files:
            assert (out / name / file).is_file(), (name, file)
        summary = (out / name / "summary.md").read_text(encoding="utf-8")
        assert tool.DEGENERATE[name] in summary
    picks = (out / "J2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == "signal_date,rank,exchange,symbol,turnover_60,trust_flow_20,tie"
    first_day = [line for line in picks[1:] if line.startswith(days[60].isoformat())]
    assert len(first_day) == len(TRUST_HITS) - 1  # fewer than 20: the rest is cash
    j1_md = (out / "J1" / "summary.md").read_text(encoding="utf-8")
    assert "## 兩種狀態（J1 第 6 點，只列出、不判定）" in j1_md
    assert "## 和 V1 的重疊（J1 第 6 點）" in j1_md and tool.OVERLAP_NOTE["J1"] in j1_md
    j1_picks = (out / "J1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        j1_picks[0]
        == "signal_date,rank,exchange,symbol,state,margin_sent_60,vol_60,tie"
    )
    j2_md = (out / "J2" / "summary.md").read_text(encoding="utf-8")
    assert "## 符合的檔數（J2 第 6 點，只列出、不判定）" in j2_md
    j3_md = (out / "J3" / "summary.md").read_text(encoding="utf-8")
    assert "| T+1 跌停鎖死、照常以開盤價成交 | 1 |" in j3_md
    assert "| 同一天也符合 F1 `stock_div_ex` 的訊號 | 1 |" in j3_md
    assert "| 放棄：T+1 漲停鎖死 | 1 |" in j3_md
    j4_md = (out / "J4" / "summary.md").read_text(encoding="utf-8")
    assert "## 和 Z1 的重疊（J4 第 7 點）" in j4_md and tool.OVERLAP_NOTE["J4"] in j4_md
    header = (out / "J3" / "trades.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith(
        "signal_date,exchange,symbol,cash_dividend,close_before_raw,cash_yield,"
        "stock_div_ex,t1_locked_down,"
    )


def test_the_j1_list_is_v1s_on_the_high_days(explored, loaded):
    _db, out = explored
    days = trading_days()
    picks = (out / "J1" / "picks.csv").read_text(encoding="utf-8").splitlines()[1:]
    for t, same in ((100, True), (250, False)):
        day = days[t]
        mine = {
            line.split(",")[3] for line in picks if line.startswith(day.isoformat())
        }
        members = lib.universe(loaded.panel, day, 1000)
        v1 = {f"S{i}" for i in tool.v1_names(loaded, day, members)}
        assert (mine == v1) is same, t


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="J2") == 2
    assert any("J2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="J1,L2") == 2
    assert any("L2 not registered" in line for line in refused(capsys))


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
    data["design"] = "953"
    data["hypotheses"]["J2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_285(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "J1", "J3")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [
        ("J1", "round12_research", "finished"),
        ("J3", "round12_research", "finished"),
    ]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["J1", "J3"]
    assert validation["min_t"] == 3.285
    for name in ("J1", "J3"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["min_t"] == 3.285, name
    assert validation["read_until"] == trading_days()[359].isoformat()
    # the validation's J1 starts again: signal dates 299 .. 358, high from 331
    states = validation["hypotheses"]["J1"]["states"]
    assert (states["low"]["days"], states["high"]["days"], states["switches"]) == (
        32,
        28,
        1,
    )
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.285" in text
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
    report = passed_report(out, tmp_path, "J4")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[359]),
        (tool.LOAD_FROM, days[419]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["J4"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["J4"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "J4" / "used" / file).is_file(), file
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
    days = 239  # signal dates 60 .. 298: 60 .. 259 in 2016, 260 .. 298 in 2017
    j1 = hyp["J1"]["coverage"]
    assert (j1["2016"]["days"], j1["2017"]["days"]) == (200, 39)
    assert total(j1, "state_high") == 170 and total(j1, "state_low") == 69
    assert total(j1, "state_missing") == 0
    assert j1["2016"]["switches"] == 1 and hyp["J1"]["switches"] == 1
    j2 = hyp["J2"]["coverage"]
    # S4 has no chip row: its trust_flow_20 is missing every day
    assert j2["2016"]["missing"]["trust_flow_20"] >= 200
    assert total(j2, "short_days") == days and total(j2, "zero_days") == 0
    assert j2["2016"]["max_positive"] == len(TRUST_HITS)
    j3 = hyp["J3"]["coverage"]["years"]
    # no occupancy: S3 on 110 counts too; S19 (null) and S21 (bar before
    # suspended) cannot be told, S5 is below 3%; S23 on 290 is 2017's
    assert (total(j3, "signals"), total(j3, "signal_days"), total(j3, "f1_both")) == (
        11,
        10,
        1,
    )
    assert (total(j3, "rows"), total(j3, "unknown"), total(j3, "below")) == (14, 2, 1)
    assert j3["2016"]["markets"]["TPEx"]["signals"] == 1
    j4 = hyp["J4"]["coverage"]
    assert list(j4) == ["2017"] and j4["2017"]["days"] == 300 - 262
    assert 0 < j4["2017"]["missing"]["liq_shock_20"] < j4["2017"]["members"]
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["J1"] == {"plan", "margin_sent_60", "vol_60", "v1_order"}
    assert seconds["J2"] == {"plan", "turnover_60", "trust_flow_20", "j2_order"}
    assert seconds["J3"] == {"plan", "cash_div_ex"}
    assert seconds["J4"] == {"plan", "liq_shock_20", "z1_order"}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "trade", "actions"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert "### J3：依年的訊號數與訊號日數" in md
    assert "符合的不足 20 檔的訊號日" in md and "狀態切換（全段）：1 次。" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "J1"]
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
    assert explore(copied, tmp_path / "out", hypotheses="J3") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "J3")
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
        assert explore(copied, out, hypotheses="J3") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "J3")
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
