"""tools/research/round14_research.py: the registered K1～K3 (#978).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十四輪：K1～K3.  The features and the accounts are
checked on hand-made series (the expected numbers worked out in the test);
the gate ("each once") and the reports run on a synthetic copy on a
compressed calendar (``compressed``): the segments, the floors and K1's
3-year windows are moved into the fixture's 700 sessions, everything else is
the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
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
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/978#issuecomment-1"
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
r5 = _tool("round5_research")
r10 = _tool("round10_research")
r12 = _tool("round12_research")
r13 = _tool("round13_research")
tool = _tool("round14_research")
NAMES = ("K1", "K2", "K3")
OTC_INST = date(2014, 12, 1)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in (
        "mainstream_research",
        *(f"round{n}_research" for n in range(4, 14)),
    ):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    k1, k2, k3 = (h[name] for name in NAMES)
    assert (k1["engine"], k2["engine"], k3["engine"]) == (
        "portfolio",
        "events",
        "portfolio",
    )
    assert k1["conditions"] == (("div_initiation", "is", True),)
    assert (k1["top"], k1["hold"], k1["start"]) == (
        20,
        240,
        ("date", date(2010, 12, 2)),
    )
    assert (k1["weight"], k1["benchmark"]) == (
        "1/n",
        "the population on the event days only",
    )
    assert k2["conditions"] == (("eps_turn", "is", True),)
    assert (k2["top"], k2["hold"], k2["start"]) == (
        20, "next_event", ("date", date(2014, 5, 15)),
    )  # fmt: skip
    assert k3["conditions"] == (("inst_sell_5q", "is", True),)
    assert (k3["top"], k3["hold"], k3["start"]) == (20, 120, ("session", OTC_INST, 300))
    for spec in h.values():
        assert spec["order"] == "the hash only" and spec["short"] == "cash, not filled"
        assert "keys" not in spec


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        14,
        3,
        55,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.317
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(55), 3) == 3.317
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "50528962" and tool.DESIGN == "978"
    assert (tool.GAP_DAYS, tool.LISTED_DAYS, tool.MIN_FILL_DAYS) == (1095, 1095, 60)
    assert tool.DEADLINES == (
        (3, 31, 12, -1),
        (5, 15, 3, 0),
        (8, 14, 6, 0),
        (11, 14, 9, 0),
    )
    assert (tool.BLOCK, tool.BLOCKS) == (60, 5)
    assert tool.FLOW_COLUMNS == ("foreign_buy", "trust_buy")
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    names = tool.load.__code__.co_names
    for imported in ("load_context", "load_actions", "actions_of", "cash_dividends",
                     "market_gaps"):  # fmt: skip
        assert imported in names, imported
    assert "_quarter_eps" in tool.eps_turn.__code__.co_names
    assert "window_of" in tool.inst_sell_5q.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "r12.cash_div_ex(" in inspect.getsource(tool.j3_overlap)
    assert "_rank" in tool.x4_names.__code__.co_names
    assert "rank_u1" in tool.u1_names.__code__.co_names


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#978 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.317
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.302),
        # K1
        (tool, "GAP_DAYS", 1094),
        (tool, "LISTED_DAYS", 1096),
        (tool, "CASH_MIN", 0.01),
        (tool, "SAME_DAY", "several rows on T: the first"),
        (tool, "ROW_CASH", "the three fields null count 0"),
        (tool, "NULL_RULE", "a row with the three fields null is ignored"),
        (tool, "WEIGHT", "each 1/20 of the account's cash"),
        (tool, "BENCHMARK", "the population every day"),
        (tool, "MIN_FILL_DAYS", 59),
        (tool, "FILL_RULE", "a signal date with a list"),
        (r5, "VERSION", r5.VERSION + 1),
        (tool, "HYPOTHESES", _swap("K1", "weight", "1/20")),
        (tool, "HYPOTHESES", _swap("K1", "benchmark", "the population every day")),
        (tool, "HYPOTHESES", _swap("K1", "top", 19)),
        (tool, "HYPOTHESES", _swap("K1", "hold", 120)),
        (tool, "HYPOTHESES", _swap("K1", "start", ("date", date(2010, 12, 3)))),
        # K2
        (
            tool,
            "DEADLINES",
            ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0)),
        ),
        (tool, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0))),
        (tool, "EPS_MIN", 0.01),
        (tool, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        (tool, "LATEST_RULE", "the latest quarter within 200 days"),
        (tool, "SALE", "at T'+1's open"),
        (features, "SHARED_VERSION", features.SHARED_VERSION + 1),
        (tool, "HYPOTHESES", _swap("K2", "top", 19)),
        (tool, "HYPOTHESES", _swap("K2", "hold", 60)),
        (tool, "HYPOTHESES", _swap("K2", "start", ("date", date(2014, 8, 14)))),
        # K3
        (tool, "BLOCK", 59),
        (tool, "BLOCKS", 4),
        (tool, "FLOW_COLUMNS", ("foreign_buy", "trust_buy", "dealer_buy")),
        (tool, "SELL_MAX", 1.0),
        (tool, "FLOW_NULL", "a null column makes it missing"),
        (tool, "WINDOW_RULE", "a suspended bar counts 0"),
        (r13, "NO_TRADING", "no chip row only"),
        (r13, "MARKET_GAP", "a market gap is ignored"),
        (tool, "HYPOTHESES", _swap("K3", "top", 19)),
        (tool, "HYPOTHESES", _swap("K3", "hold", 60)),
        (tool, "HYPOTHESES", _swap("K3", "start", ("session", OTC_INST, 301))),
        # the three: the hash, the short lists
        (tool, "ORDER", "ranked by the feature"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "HYPOTHESES", _swap("K1", "order", "cash_dividend high first")),
        (tool, "HYPOTHESES", _swap("K2", "short", "filled")),
        (tool, "HYPOTHESES", _swap("K3", "conditions", ())),
        # the overlaps' lists
        (
            r12,
            "HYPOTHESES",
            {**r12.HYPOTHESES, "J3": {**r12.HYPOTHESES["J3"], "hold": 19}},
        ),
        (r12, "YIELD_MIN", 0.04),
        (ex, "HYPOTHESES", {**ex.HYPOTHESES, "X4": {**ex.HYPOTHESES["X4"], "top": 19}}),
        (
            r13,
            "HYPOTHESES",
            {**r13.HYPOTHESES, "U1": {**r13.HYPOTHESES["U1"], "top": 19}},
        ),
        # common
        (tool, "MIN_LOTS", 500),
        (er, "LIMIT_BEFORE_WIDENING", Fraction(1, 10)),
        (er, "LIMIT_WIDENED_ON", date(2015, 6, 2)),
        (er, "LIMIT", Fraction(1, 20)),
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
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master 50528962 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash; K1～K3's overlaps read round12's,
# explore_research's and round13's.
FROZEN = {
    "explore_research": (2, "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"),
    "trade_research": (1, "80329d4669123683783a2153a132931fe90eecfbbe8fbfa382cfed345d8cfbfb"),
    "mainstream_research": (1, "5e776480b0fa7d023c9f217671c856ac81ea8d4115d7ff94aac7446a263371f2"),
    "round4_research": (1, "2fa7f1826fc1b1b962eb63b45b6a238122d74fd4912e0a14c8eed0a0cf63aa56"),
    "round5_research": (1, "a3409f1b9dd24a8e32c04148f5d1e36a5e8282e96df975bd0b36a21101993d75"),
    "round6_research": (1, "b8e1eb89a20b9ea97db4d6ba38a1461d5ff5bf05b26eb9619c353db7020ac51e"),
    "round7_research": (1, "180c21a4307b5cfd16db0b246478f5da3406a9779b0956dfc13cb32dc0cd47d7"),
    "round8_research": (1, "cd00cd2d201893370ec706168af5a30cb8e1e684c47ba30fc91356447876d757"),
    "round9_research": (1, "1a79970f76ed6e92884000623ab38e61eae3f201ff10a457d5dead96b5858680"),
    "round10_research": (1, "453f65124f86b5643ef1ce79dd079530a603e9434ed719a5f942090eeaf85dd9"),
    "round11_research": (1, "5c326147823f78ca203db3b127b6369a63305e3b62839479bf39f2ac161b67bb"),
    "round12_research": (1, "12f24befd44c279118ade14460c722f968849a00c48a27b4def7690ca3f0954f"),
    "round13_research": (1, "cb2415931db08b31d37318b164056bd30c35c9ff53b6d01627c54c7bab88bc21"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name", ["round13_research", "round12_research", "round10_research", None]
)
def test_the_overlaps_tools_are_the_ledgers(name):
    """AC-1: the four hashes the overlaps and forward_watch read are the ones
    in the public ledger (explore_research's entries have no ``tool``)."""

    entries = json.loads(
        (ROOT / "tools" / "research" / "explore_ledger.json").read_text(
            encoding="utf-8"
        )
    )["entries"]
    module = ex if name is None else sys.modules[name]
    found = {
        e["definitions_sha256"]
        for e in entries
        if e.get("tool") == name and e.get("version") == module.VERSION
    }
    assert found == {module.definitions_sha256()}


# AC-1: portfolio_research.ranking_key's source on master 50528962
RANKING_KEY_SHA256 = "65054614e007a2baa499baa6253d01e411b9b6f7b24d2acc0d50107d000291e0"


def test_the_ranking_key_is_unchanged():
    import ast

    path = ROOT / "tools" / "research" / "portfolio_research.py"
    text = path.read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.parse(text).body
        if isinstance(n, ast.FunctionDef) and n.name == "ranking_key"
    )
    source = ast.get_source_segment(text, node)
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == RANKING_KEY_SHA256


def test_the_docs_tool_section_says_what_the_code_judges():
    """The degenerate cases in the tool section are the code's own strings,
    and coverage.md／summary.md print the same (PR #913 review)."""

    text = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    section = text.split("**第十四輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.317 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round14_research.py" in section
    assert "本輪 3 個、累計 55 個" in section


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


def context_for(items, sessions=None, symbols=None, actions=None):
    """``round14_research.Context`` on hand-made items (the market gaps and
    the first cash computed from them, as ``load`` does)."""

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
    return tool.Context(base, actions or {})


def row(day: date, cash, stock=None, split=None):
    return SimpleNamespace(
        action_date=day,
        cash_dividend=cash,
        stock_dividend_ratio=stock,
        split_ratio=split,
    )


# --- K1: div_initiation -----------------------------------------------------------

K1_DAYS = weekdays(date(2012, 1, 2), 1200)  # 2012-01-02 .. 2016-08
MONDAY_AT = 1100  # 2016-03-21, a Monday: the weekend before rolls to it
T_AT = 1103  # a Thursday: the day before is a session
T = K1_DAYS[T_AT]


def k1_ctx(rows, first_bar: date | None = None):
    days = [d for d in K1_DAYS if first_bar is None or d >= first_bar]
    item = make_item([10.0] * len(days), dates=days)
    item.session = array("i", [K1_DAYS.index(d) for d in days])
    ctx = context_for([item], sessions=K1_DAYS, actions={1: r5.actions_of(rows)})
    return ctx, item


def initiation(rows, s=T_AT, first_bar=None):
    ctx, item = k1_ctx(rows, first_bar)
    return tool.div_initiation(ctx, item, s, K1_DAYS[s])


def test_div_initiation_needs_a_cash_dividend_going_ex_on_t():
    assert initiation([row(T, 1.0)]).qualifies
    assert not initiation([row(T, 0.0)]).candidate  # > 0, strictly
    assert not initiation([row(T, None, stock=0.1)]).candidate  # stock only
    assert not initiation([row(T - timedelta(days=1), 1.0)]).candidate  # not on T
    several = initiation([row(T, 0.5), row(T, 1.5), row(T, None)])
    assert several.qualifies and several.cash == 1.5  # the largest of the day


def test_div_initiation_rolls_a_date_that_is_no_session_to_the_next():
    monday = K1_DAYS[MONDAY_AT]
    saturday = monday - timedelta(days=2)
    assert monday.weekday() == 0 and K1_DAYS[MONDAY_AT - 1] < saturday
    parts = initiation([row(saturday, 1.0)], s=MONDAY_AT)
    assert parts.qualifies and parts.day == saturday
    assert not initiation([row(saturday, 1.0)]).candidate  # not T's session
    # d is the Saturday: a row on the Friday before it is in [d − 1,095, d)
    rows = [row(saturday, 1.0), row(saturday - timedelta(days=1), 0.2)]
    assert not initiation(rows, s=MONDAY_AT).qualifies


@pytest.mark.parametrize(
    "offset, qualifies",
    [(1096, True), (1095, False), (1, False), (0, True)],  # d − 1,095 is in, d is out
)
def test_div_initiation_reads_no_cash_in_the_3_years_before_d(offset, qualifies):
    rows = [row(T - timedelta(days=offset), 2.0), row(T, 1.0)]
    parts = initiation(rows)
    assert parts.qualifies is qualifies
    assert parts.paid is (not qualifies)


def test_div_initiation_a_stock_dividend_only_is_no_cash_and_three_nulls_fail():
    year = T - timedelta(days=400)
    assert initiation([row(year, None, stock=0.05), row(T, 1.0)]).qualifies
    assert initiation([row(year, None, split=0.5), row(T, 1.0)]).qualifies
    assert initiation([row(year, 0.0), row(T, 1.0)]).qualifies
    parts = initiation([row(year, None), row(T, 1.0)])  # the three null: unknown
    assert not parts.qualifies and parts.null and not parts.paid
    edge = initiation([row(T - timedelta(days=1096), None), row(T, 1.0)])
    assert edge.qualifies  # outside the window


def test_div_initiation_first_bar_boundary_on_a_session():
    sessions = [d for d in K1_DAYS if (T - d).days in (1094, 1095)]
    assert sessions, "the fixture has a session 1,095 days before T"
    for d in sessions:
        parts = initiation([row(T, 1.0)], first_bar=d)
        assert parts.qualifies is ((T - d).days >= 1095)
        assert parts.young is ((T - d).days < 1095)


# --- K1: the lists and the account --------------------------------------------------


def fake_plan(monkeypatch, events: dict[int, list[int]], sessions, j3=None):
    """``plan_k1`` with each signal date's qualified events given by index."""

    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 40)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in range(1, 40)]
    )

    def initiation(ctx, item, s, day):
        on = item.instrument_id in events.get(s, [])
        return tool.Initiation(on, on, cash=1.0, day=day)

    monkeypatch.setattr(tool, "div_initiation", initiation)
    monkeypatch.setattr(
        tool, "j3_overlap", lambda ctx, s, chosen: len([1 for item, _ in chosen
                                                        if item.instrument_id in (j3 or {}).get(s, ())])
    )  # fmt: skip
    ctx = SimpleNamespace(
        panel=SimpleNamespace(sessions=sessions, symbols={}),
        seconds=__import__("collections").Counter(),
    )
    return tool.plan_k1(ctx, tool.HYPOTHESES["K1"], 1, len(sessions) - 1)


def test_k1_takes_at_most_20_by_the_hash_and_buys_only_on_event_days(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 6)
    events = {0: list(range(1, 26)), 2: [3, 7], 4: []}
    planned = fake_plan(monkeypatch, events, sessions, j3={0: range(1, 4), 2: (7,)})
    day0 = sessions[0]
    expected = sorted(range(1, 26), key=lambda i: pr.tie_break(day0, i))[:20]
    assert planned.picks == {
        1: expected,
        3: sorted([3, 7], key=lambda i: pr.tie_break(sessions[2], i)),
    }
    assert set(planned.population) == {1, 3}  # the population on the event days only
    assert len(planned.population[1]) == 39
    assert planned.event_days == 2 and planned.flags == [1, 0, 1, 0, 0]
    assert planned.events == {"2016": [25, 2]}  # before the 20 cap
    # J3 among the 20 taken: 1..3 if they made the cut, 7 on day 2
    assert planned.overlap == {"2016": [len({1, 2, 3} & set(expected)), 1]}
    year = planned.coverage["2016"]
    assert (year["events"], year["event_days"], year["capped_days"], year["max_events"]) == (
        27, 2, 1, 25,
    )  # fmt: skip
    assert [r["rank"] for r in planned.rows] == [*range(1, 21), 1, 2]


def test_k1_invested_estimate_by_hand(monkeypatch):
    monkeypatch.setattr(tool, "HYPOTHESES", _swap("K1", "hold", 3))
    sessions = weekdays(date(2016, 1, 4), 7)
    planned = fake_plan(monkeypatch, {0: [1], 1: [2], 3: [3]}, sessions)
    # flags 1 1 0 1 0 0; held sessions 1..6: 1/3, 2/3, 2/3, 2/3, 1/3, 1/3
    year = planned.coverage["2016"]
    assert year["invested_days"] == 6
    assert year["invested_sum"] == pytest.approx((1 + 2 + 2 + 2 + 1 + 1) / 3)


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


def test_k1_weights_each_name_1_over_n_and_the_population_the_same_way():
    """T's account: 1/240 of the equity; n names 1/n of it, a name not bought
    leaves its share in cash; the population on the same day, same account."""

    hold = tool.HYPOTHESES["K1"]["hold"]
    prices = {(i, 1): (10.0, 10.0) for i in (1, 3, 4, 5)}  # 2 has no bar
    planned = SimpleNamespace(
        picks={1: [1, 2]}, population={1: [1, 2, 3, 4, 5]}, dues={}
    )
    ctx = SimpleNamespace(quote=quote_of(prices))
    mine, population = tool.engines(ctx, "K1", planned, 1, 1)
    account = 1.0 / hold
    assert [p.cost for p in mine.positions] == pytest.approx(
        [account / 2]
    )  # 1/n, n = 2
    assert mine.counts["not_tradable"] == 1
    assert [p.cost for p in population.positions] == pytest.approx([account / 5] * 4)
    # all bought: both put the whole account in
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 3, 4, 5]}, dues={})
    mine, population = tool.engines(ctx, "K1", planned, 1, 1)
    assert sum(p.cost for p in mine.positions) == pytest.approx(account)
    assert sum(p.cost for p in population.positions) == pytest.approx(account)
    assert mine.invested[0] == pytest.approx(population.invested[0])


def test_k1_rotates_240_accounts_and_the_population_too(monkeypatch):
    calls = []
    real = pr.simulate

    def spy(picks, quote, first, last, hold, top):
        calls.append((hold, top))
        return real(picks, quote, first, last, hold, top)

    monkeypatch.setattr(pr, "simulate", spy)
    planned = SimpleNamespace(picks={}, population={}, dues={})
    ctx = SimpleNamespace(quote=lambda i, s: None)
    tool.engines(ctx, "K1", planned, 1, 3)
    tool.engines(ctx, "K3", planned, 1, 3)
    assert calls == [(240, None), (240, None), (120, 20), (120, None)]


def test_a_fill_day_has_at_least_one_name_bought():
    prices = {(1, 1): (10.0, 10.0), (1, 3): (10.0, 10.0), (3, 3): (10.0, 10.0)}
    picks = {1: [1], 2: [2], 3: [1, 3]}  # session 2: nothing tradable
    simulation = pr.simulate(picks, quote_of(prices), 1, 4, 240, None)
    assert tool.fill_days(simulation) == 2


def judged_with_fills(monkeypatch, fills: int, segment="exploration", unsold=0):
    """``run_portfolio`` on K1 with a winning curve and ``fills`` fill days."""

    sessions = weekdays(date(2011, 1, 3), 700)
    first, last = 1, 600
    monkeypatch.setattr(tool, "segment_window", lambda s, seg, spec: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_k1", lambda *a, **k: tool.Plan())
    days = last - first + 1

    def curve(step):
        out, value = [], 1.0
        for k in range(days):
            value *= 1 + step + (0.001 if k % 2 else -0.001)
            out.append(value)
        return out

    positions = [
        pr.Position(0, 1, 1.0, first + k, first + k, 0.1, 1.0) for k in range(fills)
    ]
    mine = pr.Simulation(curve(0.002), [0.5] * days, [0.0] * days, positions=positions)
    mine.counts["unsold"] = unsold
    population = pr.Simulation(curve(0.0005), [0.5] * days, [0.0] * days)
    monkeypatch.setattr(tool, "engines", lambda *a: (mine, population))
    ctx = SimpleNamespace(
        panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
        seconds=__import__("collections").Counter(),
    )
    min_t = tool.VALIDATION_MIN_T if segment == "validation" else tool.MIN_T
    return tool.run_portfolio(ctx, Path("unused"), "K1", segment, min_t=min_t)


@pytest.mark.parametrize("segment", ["exploration", "validation"])
def test_k1_with_59_fill_days_is_undecided_and_60_is_judged(monkeypatch, segment):
    low = judged_with_fills(monkeypatch, 59, segment)
    assert (low["verdict"], low["reason"]) == ("無法判定", "too_few_event_days")
    assert low["fill_days"] == {"days": 59, "min_days": 60}
    high = judged_with_fills(monkeypatch, 60, segment)
    assert high["verdict"] == ("探索通過" if segment == "exploration" else "通過")
    assert high["reason"] is None


def test_k1_unsold_share_by_hand(monkeypatch):
    result = judged_with_fills(monkeypatch, 4, unsold=1)  # 1 of the 4 bought
    assert result["unsold_share"] == pytest.approx(1 / 4)


# --- K2: eps_turn and the event days ------------------------------------------------


def test_the_event_days_are_the_4_deadlines_or_the_next_session():
    sessions = weekdays(date(2016, 1, 4), 600)  # 2016-01-04 .. 2018-04
    found = [(sessions[at], quarter) for at, quarter in tool.quarter_events(sessions)]
    assert found[:5] == [
        (date(2016, 3, 31), date(2015, 12, 31)),
        (date(2016, 5, 16), date(2016, 3, 31)),  # the 15th is a Sunday
        (date(2016, 8, 15), date(2016, 6, 30)),  # the 14th is a Sunday
        (date(2016, 11, 14), date(2016, 9, 30)),
        (date(2017, 3, 31), date(2016, 12, 31)),
    ]


def test_a_deadline_on_a_saturday_make_up_session_moves_to_the_next_weekday():
    """#978 決定 7086393113: 2018-03-31 was a Saturday make-up session; the
    copy's 2017 annual reports are dated 2018-04-02."""

    holidays = {date(2018, 5, 15), date(2018, 11, 14)}  # made holidays here
    sessions = sorted(
        [d for d in weekdays(date(2018, 3, 26), 180) if d not in holidays]
        + [date(2018, 3, 31)]  # the Saturday make-up session
    )
    found = [(sessions[at], quarter) for at, quarter in tool.quarter_events(sessions)]
    assert found == [
        (date(2018, 4, 2), date(2017, 12, 31)),  # not the Saturday 03-31
        (date(2018, 5, 16), date(2018, 3, 31)),  # 05-15 no session: the next one
        (date(2018, 8, 14), date(2018, 6, 30)),  # a weekday session: itself
        (date(2018, 11, 15), date(2018, 9, 30)),
    ]
    # a Saturday make-up session that is no deadline changes nothing
    plain = sorted([*weekdays(date(2018, 8, 13), 5), date(2018, 8, 18)])
    events = {plain[at]: q for at, q in tool.quarter_events(plain)}
    assert events[date(2018, 8, 14)] == date(2018, 6, 30)
    assert date(2018, 8, 18) not in events


def quarters_item(rows, day=date(2017, 5, 15)):
    item = make_item([10.0], dates=[day])
    item.quarters = sorted(rows)
    return item


def cumulative(year: int, own: list[float], announced=None) -> list[tuple]:
    ends = [date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)]
    dues = announced or [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                         date(year + 1, 3, 31)]  # fmt: skip
    out, total = [], 0.0
    for end, due, value in zip(ends, dues, own):
        total += value
        out.append((due, end, total))
    return out


def test_eps_turn_by_hand():
    q1 = date(2017, 3, 31)
    loss = cumulative(2016, [-0.5, -0.2, 0.1, 0.3])
    item = quarters_item([*loss, *cumulative(2017, [0.4])])
    turn = tool.eps_turn(item, 0, q1)
    assert turn.qualifies and (turn.now, turn.before) == pytest.approx((0.4, -0.5))
    zero = quarters_item([*loss, *cumulative(2017, [0.0])])
    assert not tool.eps_turn(zero, 0, q1).qualifies  # = 0 is not > 0
    flat = quarters_item([*cumulative(2016, [0.0]), *cumulative(2017, [0.4])])
    assert not tool.eps_turn(flat, 0, q1).qualifies  # the year before = 0
    both = quarters_item([*cumulative(2016, [0.5]), *cumulative(2017, [0.4])])
    assert not tool.eps_turn(both, 0, q1).qualifies
    # Q2 own = cumulative difference: 2016 Q2 own −0.2, 2017 Q2 own 0.3
    item = quarters_item([*loss, *cumulative(2017, [-0.1, 0.3])], day=date(2017, 8, 14))
    turn = tool.eps_turn(item, 0, date(2017, 6, 30))
    assert turn.qualifies and (turn.now, turn.before) == pytest.approx((0.3, -0.2))


def test_eps_turn_needs_the_deadlines_quarter_and_both_single_values():
    q1 = date(2017, 3, 31)
    loss = cumulative(2016, [-0.5, -0.2, 0.1, 0.3])
    late = quarters_item(
        [*loss, *cumulative(2017, [0.4], announced=[date(2017, 5, 31)])]
    )
    assert tool.eps_turn(late, 0, q1).reason == "stale"  # a financial's later deadline
    old = quarters_item(loss)  # 2017 Q1 not out yet: the latest is 2016 Q4
    assert tool.eps_turn(old, 0, q1).reason == "stale"
    assert tool.eps_turn(quarters_item([]), 0, q1).reason == "stale"
    no_before = quarters_item(cumulative(2017, [0.4]))
    assert tool.eps_turn(no_before, 0, q1).reason == "no_single"
    gap = [r for r in loss if r[1] != date(2016, 3, 31)]  # 2016 Q2's own unknown
    item = quarters_item([*gap, *cumulative(2017, [-0.1, 0.3])], day=date(2017, 8, 14))
    assert tool.eps_turn(item, 0, date(2017, 6, 30)).reason == "no_single"


def test_k2_sells_at_the_next_event_days_close_and_buys_at_its_next_open():
    """#978 決定 7086070149: X7's account — T′'s close, the new list at T′+1."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              dues={1: 3, 4: 8})  # fmt: skip
    mine, population = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "K2", planned, 1, 7
    )
    first, second = mine.positions
    assert (first.instrument_id, first.sold, first.how) == (1, 3, "close")
    assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 13.0))
    assert (second.instrument_id, second.bought) == (2, 4)
    cash_after_sale = 1.0 - first.cost + first.proceeds
    assert second.cost == pytest.approx(cash_after_sale / 20)  # 1/20, the rest cash
    assert second.how == "unsold"  # due after the segment: its last close
    assert len(population.positions) == 4  # the population on the same days
    # T′ locked at limit down: sold at T′+1's open, its cash in that day's buys
    locked = tool.engines(
        SimpleNamespace(quote=quote_of(prices, locked={(1, 3)})), "K2", planned, 1, 7
    )[0]
    first, second = locked.positions
    assert (first.sold, first.how) == (4, "delayed")
    assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)


def test_k2_sells_a_suspended_t_prime_at_the_next_open_and_spends_it_that_day():
    """「X7 的金額與順延」: T′ suspended (not tradable, or no bar) sells at the
    first open after it; on T′+1 its proceeds are in that day's buys."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              dues={1: 3, 4: 8})  # fmt: skip
    for suspended in ("not_tradable", "no_bar"):
        quote = quote_of(prices)

        def on(instrument_id, s, quote=quote, suspended=suspended):
            if (instrument_id, s) == (1, 3):
                return None if suspended == "no_bar" else pr.Quote(10.0, 13.0, False)
            return quote(instrument_id, s)

        mine = tool.engines(SimpleNamespace(quote=on), "K2", planned, 1, 7)[0]
        first, second = mine.positions
        assert (first.sold, first.how) == (4, "delayed"), suspended
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        assert second.bought == 4
        assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)


def test_k2_lists_each_rebalances_invested_share_at_the_buy_days_close(monkeypatch):
    """K2 第 7 點: each rebalance's invested share is the positions' value ÷
    the equity at the close of its buy day (T+1), worked out by hand."""

    sessions = weekdays(date(2016, 3, 28), 9)
    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 9)}
    first, last = 1, 7
    plan = tool.Plan(
        picks={1: [1], 4: [2, 3]},
        population={1: [1, 2, 3], 4: [1, 2, 3]},
        dues={1: 3, 4: 8},
        rebalances=[
            {"signal_date": sessions[0].isoformat(), "x4_overlap": None},
            {"signal_date": sessions[3].isoformat(), "x4_overlap": None},
        ],
    )
    monkeypatch.setattr(tool, "segment_window", lambda s, seg, spec: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_k2", lambda *a, **k: plan)
    ctx = SimpleNamespace(
        panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
        seconds=__import__("collections").Counter(),
        quote=quote_of(prices),
    )
    result = tool.run_portfolio(ctx, Path("unused"), "K2", "exploration")
    # buy day 1: 1/20 of 1.0 into S1 at 10 (with costs), its close 11
    units = pr.buy_units(0.05, 10.0)
    value = units * 11.0
    expected_1 = value / (0.95 + value)
    # sold at session 3's close 13; buy day 4: S2 and S3, each 1/20 of the cash
    cash = 0.95 + pr.sale_proceeds(units, 13.0)
    share = cash / 20
    value = 2 * pr.buy_units(share, 10.0) * 14.0
    expected_4 = value / (cash - 2 * share + value)
    got = [event["invested"] for event in result["rebalances"]]
    assert got == pytest.approx([expected_1, expected_4])


def test_k2_has_no_equity_before_its_first_event_day():
    sessions = weekdays(date(2014, 1, 2), 1700)
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["K2"])
    assert sessions[first - 1] == date(2014, 5, 15)
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["K2"])
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report


def test_k2_plan_takes_20_by_the_hash_overlaps_x4_and_dues_the_next_event(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 250)  # 2016 events: 3/31, 5/16, 8/15, 11/14
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    hits = {date(2016, 3, 31): range(1, 26), date(2016, 5, 16): (4, 5),
            date(2016, 8, 15): ()}  # fmt: skip

    def turn(item, at, quarter):
        day = {date(2015, 12, 31): date(2016, 3, 31), date(2016, 3, 31): date(2016, 5, 16),
               date(2016, 6, 30): date(2016, 8, 15)}[quarter]  # fmt: skip
        if item.instrument_id in hits[day]:
            return tool.Turn(True, None, 1.0, -1.0)
        return tool.Turn(False, "stale" if item.instrument_id > 28 else None)

    monkeypatch.setattr(tool, "eps_turn", turn)
    monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: {4, 9})
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=__import__("collections").Counter())  # fmt: skip
    last = sessions.index(date(2016, 8, 31))
    first = sessions.index(date(2016, 3, 31)) + 1
    planned = tool.plan_k2(ctx, tool.HYPOTHESES["K2"], first, last)
    s1, s2, s3 = (sessions.index(d) + 1 for d in hits)
    assert planned.dues == {s1: s2 - 1, s2: s3 - 1, s3: last + 1}
    expected = sorted(range(1, 26), key=lambda i: pr.tie_break(date(2016, 3, 31), i))[
        :20
    ]
    assert planned.picks[s1] == expected and len(planned.picks[s2]) == 2
    assert planned.picks[s3] == [] and len(planned.population[s3]) == 30
    assert [e["names"] for e in planned.rebalances] == [20, 2, 0]
    assert [e["stale"] for e in planned.rebalances] == [2, 2, 2]
    assert planned.overlap == {"2016": [len({4, 9} & set(expected)) / 20, 1 / 2]}
    assert planned.hits == {"2016": [20, 2, 0]}


# --- K3: inst_sell_5q -------------------------------------------------------------


def k3_item(foreign, trust=None, dealer=None, suspended=(), instrument_id=1, n=300):
    chips = {
        "foreign_buy": foreign,
        "trust_buy": trust if trust is not None else [0.0] * n,
        "dealer_buy": dealer if dealer is not None else [0.0] * n,
    }
    return make_item([10.0] * n, suspended, instrument_id, chips=chips)


def blocks(values: list[float]) -> list[float]:
    """Each block's sum on the block's first bar, 0 elsewhere."""

    out = [0.0] * 300
    for j, value in enumerate(values):
        out[60 * j] = value
    return out


def selling(item, other=None) -> tool.Selling:
    items = [item, *([other] if other else [])]
    symbols = {item.instrument_id: ("TPEx", "A", "")}
    if other:
        symbols[other.instrument_id] = ("TWSE", "B", "")
    ctx = context_for(items, symbols=symbols)
    return tool.inst_sell_5q(ctx, item, 299)


def test_inst_sell_5q_needs_each_of_the_5_blocks_below_0():
    got = selling(k3_item(blocks([-1, -2, -3, -4, -5])))
    assert got.qualifies and got.blocks == (-1, -2, -3, -4, -5)
    for j, value in ((0, 0.0), (4, 0.0), (2, 7.0)):
        values = [-1.0] * 5
        values[j] = value
        assert not selling(k3_item(blocks(values))).qualifies, (j, value)


def test_inst_sell_5q_adds_trust_and_ignores_the_dealer_and_null_columns():
    foreign = blocks([-1, -1, -1, -1, 5])
    trust = blocks([0, 0, 0, 0, -6])  # the last block −1 in all
    assert selling(k3_item(foreign, trust)).qualifies
    dealer = blocks([1000] * 5)
    assert selling(k3_item(blocks([-1] * 5), dealer=dealer)).qualifies
    null = blocks([-1] * 5)
    null[1] = NAN  # a null column counts 0
    assert selling(k3_item(null)).qualifies
    no_trading = blocks([-1] * 5)
    no_trading[61] = NAN  # a bar with every column null (no trading) counts 0
    item = k3_item(no_trading, [NAN if k == 61 else 0.0 for k in range(300)],
                   [NAN if k == 61 else 0.0 for k in range(300)])  # fmt: skip
    other = k3_item(blocks([1] * 5), instrument_id=2)  # the market has a value that day
    ctx = context_for(
        [item, other], symbols={1: ("TPEx", "A", ""), 2: ("TPEx", "B", "")}
    )
    assert tool.inst_sell_5q(ctx, item, 299).qualifies


@pytest.mark.parametrize("bad", [0, 299])
def test_inst_sell_5q_is_missing_with_a_suspended_bar(bad):
    got = selling(k3_item(blocks([-1] * 5), suspended=(bad,)))
    assert (got.qualifies, got.reason) == (False, "suspended")


def test_inst_sell_5q_is_missing_short_or_on_a_market_gap_and_the_other_market_is_not():
    short = k3_item(blocks([-1] * 5)[:299], n=299)
    ctx = context_for([short])
    assert tool.inst_sell_5q(ctx, short, 298).reason == "short"
    foreign = blocks([-1] * 5)
    nulls = [0.0] * 300
    gap = 150
    item = k3_item(
        [NAN if k == gap else v for k, v in enumerate(foreign)],
        [NAN if k == gap else v for k, v in enumerate(nulls)],
        [NAN if k == gap else v for k, v in enumerate(nulls)],
    )
    # the TPEx item alone: no TPEx value on session 150, a market gap
    assert selling(item).reason == "market_gap"
    # a TWSE item with a value that day does not lift the TPEx gap
    other = k3_item(blocks([1] * 5), instrument_id=2)
    assert selling(item, other).reason == "market_gap"
    # and a TPEx item with a value that day does
    tpex = k3_item(blocks([1] * 5), instrument_id=3)
    ctx = context_for(
        [item, tpex], symbols={1: ("TPEx", "A", ""), 3: ("TPEx", "C", "")}
    )
    assert tool.inst_sell_5q(ctx, item, 299).qualifies


def test_k3_takes_20_by_the_hash_lists_the_hits_and_overlaps_u1(monkeypatch):
    sessions = weekdays(date(2016, 12, 29), 4)  # 2 in 2016, 2 in 2017
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    hits = {0: range(1, 26), 1: (3, 7), 2: ()}
    state = {"at": 0}

    def sell(ctx, item, at):
        on = item.instrument_id in hits[state["at"]]
        return tool.Selling(
            on, None if item.instrument_id < 29 else "suspended", (-1.0,) * 5
        )

    def u1(ctx, day, members):
        at = sessions.index(day)
        state["at"] = at + 1 if at + 1 in hits else at
        return {3, 9} if at < 2 else set()

    monkeypatch.setattr(tool, "inst_sell_5q", sell)
    monkeypatch.setattr(tool, "u1_names", u1)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=__import__("collections").Counter())  # fmt: skip
    planned = tool.plan_k3(ctx, tool.HYPOTHESES["K3"], 1, 3)
    expected = sorted(range(1, 26), key=lambda i: pr.tie_break(sessions[0], i))[:20]
    assert planned.picks[1] == expected
    assert sorted(planned.picks[2]) == [3, 7] and planned.picks[3] == []
    assert planned.hits == {"2016": [25, 2], "2017": [0]}
    # the denominator is K3's list; day 2: no list, not counted
    assert planned.overlap == {"2016": [len({3, 9} & set(expected)) / 20, 1 / 2]}
    year = planned.coverage["2016"]
    assert (year["min_hits"], year["max_hits"], year["short_days"]) == (2, 25, 1)
    assert year["missing"] == {"inst_sell_5q": 4, "suspended": 4}
    assert planned.coverage["2017"]["zero_days"] == 1


def test_the_overlap_lists_are_round12s_j3_explores_x4_and_round13s_u1(monkeypatch):
    calls = []
    monkeypatch.setattr(
        r12, "cash_div_ex", lambda ctx, item, s, at: calls.append(("J3", ctx)) or True
    )
    monkeypatch.setattr(
        ex,
        "_rank",
        lambda ctx, spec, day, members: (
            calls.append(("X4", spec, ctx)) or ([(i, {}, "") for i in range(30)], {})
        ),
    )
    monkeypatch.setattr(r13, "rank_u1", lambda ctx, spec, day, members: (
        calls.append(("U1", spec, ctx)) or SimpleNamespace(rows=[(i, {}, "") for i in range(30)])))  # fmt: skip
    ctx = context_for([make_item([10.0])])
    item = ctx.panel.series[1]
    assert tool.j3_overlap(ctx, 0, [(item, 0), (item, 0)]) == 2
    assert tool.x4_names(ctx, date(2016, 1, 4), []) == set(range(20))
    assert tool.u1_names(ctx, date(2016, 1, 4), []) == set(range(20))
    assert calls[0] == ("J3", ctx.j3)
    assert calls[2][:2] == ("X4", ex.HYPOTHESES["X4"]) and calls[2][2] is ctx.base
    assert calls[3][:2] == ("U1", r13.HYPOTHESES["U1"]) and calls[3][2] is ctx.u1
    assert ctx.j3.base is ctx.base and ctx.u1.base is ctx.base


# --- the verdict ----------------------------------------------------------------


def judged(stage, t):
    excess = {"mean": 0.001, "t": t}
    return ex.explore_judge(
        stage, 2000, True, excess, 0.0005,
        tool.VALIDATION_MIN_T if stage == "validation" else tool.MIN_T,
    )  # fmt: skip


@pytest.mark.parametrize(
    "t, verdict",
    [
        (2.0, "前瞻觀察"),
        (2.5, "前瞻觀察"),
        (3.302, "前瞻觀察"),  # round 13's threshold is not this round's
        (3.316, "前瞻觀察"),
        (3.317, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_317(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


def test_the_starts_are_the_registered_sessions():
    sessions = weekdays(date(2010, 11, 29), 2800)
    for name, rule in (
        ("K1", date(2010, 12, 2)),
        ("K2", date(2014, 5, 15)),
        ("K3", weekdays(OTC_INST, 300)[-1]),
    ):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == rule, name


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 700
STOCKS = range(1, 25)
DELISTED = {25: 120, 26: 450, 27: 560}  # the last bar's index
INDEX_ID = 90
GAP = 350  # no TPEx value on this session (K3 missing for TPEx windows on it)
SELLERS = range(1, 9)  # foreign −100 on every bar: inst_sell_5q from bar 299
TURNERS = (2, 4, 6)  # 2016 losses, 2017 profits: eps_turn on 2017's deadlines
LATE = 8  # a later deadline (a financial's): never the deadline's quarter
PAYER_DAY = date(2016, 7, 15)


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


def dividend_rows() -> list[dict]:
    def one(i, day, cash, stock=None):
        return {"instrument_id": i, "action_date": day, "action_type": "cash",
                "cash_dividend": cash, "stock_dividend_ratio": stock,
                "reference_price": 60.0, "source": "test"}  # fmt: skip

    rows = []
    for i in range(10, 16):  # events on 2016-07-15 (K1, 30-day windows)
        rows.append(one(i, PAYER_DAY, 0.5))
    rows.append(one(11, PAYER_DAY - timedelta(days=10), 0.3))  # paid in the window
    rows.append(one(12, PAYER_DAY - timedelta(days=10), None, 0.1))  # stock only: 0
    rows.append(one(13, PAYER_DAY - timedelta(days=10), None))  # three null
    for k in range(1, 12):  # 16: an event every 5 weeks (fill days for K1)
        rows.append(one(16, date(2016, 3, 1) + timedelta(days=35 * k), 0.2))
    return rows


def fundamental_rows() -> list[dict]:
    rows = []
    for i in STOCKS:
        for year in (2015, 2016, 2017, 2018):
            own = -0.5 if i in TURNERS and year <= 2016 else 0.5
            dues = [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                    date(year + 1, 3, 31)]  # fmt: skip
            if i == LATE:
                dues = [d + timedelta(days=16) for d in dues]
            ends = [
                date(year, 3, 31),
                date(year, 6, 30),
                date(year, 9, 30),
                date(year, 12, 31),
            ]
            for q, (end, due) in enumerate(zip(ends, dues), 1):
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": due, "eps": own * q, "source": "test"})  # fmt: skip
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
                {"id": i, "exchange": exchange_of(i), "symbol": f"S{i}", "name": f"N{i}",
                 "instrument_type": "stock",
                 "status": "delisted" if i in DELISTED else "active"}
                for i in ids
            ]
            + [{"id": INDEX_ID, "exchange": "TWSE", "symbol": "TAIEX", "name": "加權指數",
                "instrument_type": "index", "status": "active"}],
        )  # fmt: skip
        bars, chips = [], []
        for i in ids:
            prices = path(i)
            for t, day in enumerate(days):
                if t > DELISTED.get(i, SESSIONS):
                    break
                open_, high, low, close = prices[t]
                volume = 2_000_000 + 10_000 * i + 5_000 * (t % 7)
                bars.append(
                    {"instrument_id": i, "trading_date": day, "open": open_, "high": high,
                     "low": low, "close": close, "adj_close": close, "volume": volume,
                     "turnover": close * volume, "turnover_status": "available",
                     "source": "test", "is_suspended": False}
                )  # fmt: skip
                gap = t == GAP and exchange_of(i) == "TPEx"
                flow = -100.0 if i in SELLERS else 100.0 * (t % 3 - 1)
                chips.append(
                    {"instrument_id": i, "trading_date": day,
                     "foreign_buy": None if gap else flow,
                     "trust_buy": None if gap else 0.0,
                     "dealer_buy": None if gap else 500.0,
                     "margin_balance": 1000.0, "short_balance": 10.0, "source": "test"}
                )  # fmt: skip
        for t, day in enumerate(days):
            level = 9000.0 + 5 * t
            bars.append(
                {"instrument_id": INDEX_ID, "trading_date": day, "open": level,
                 "high": level, "low": level, "close": level, "adj_close": level,
                 "volume": 0, "turnover": 0.0, "turnover_status": "unknown",
                 "source": "twse_index", "is_suspended": False}
            )  # fmt: skip
        db.execute(insert(MarketBar), bars)
        db.execute(insert(ChipSnapshot), chips)
        db.execute(insert(CorporateAction), dividend_rows())
        db.execute(insert(FundamentalSnapshot), fundamental_rows())
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round14") / "stock.db")


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


@pytest.fixture
def short_windows(monkeypatch):
    """K1's 3-year windows as 30 days: the fixture has under 3 years."""

    monkeypatch.setattr(tool, "GAP_DAYS", 30)
    monkeypatch.setattr(tool, "LISTED_DAYS", 30)


@pytest.fixture
def loaded(fixture_db, tmp_path, short_windows):
    days = trading_days()
    return one_process(
        lambda: tool.load(fixture_db, date(1990, 1, 1), days[-1], tmp_path / "raw")
    )


def test_one_panel_serves_the_actions_and_the_overlaps(loaded):
    assert loaded.j3.base is loaded.base and loaded.u1.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "market_gaps", "actions"}
    assert [s for s, v in enumerate(loaded.u1.gaps["TPEx"]) if v] == [GAP]
    assert loaded.actions[13].cash == [None, 0.5]  # row_cash: three null unknown
    assert loaded.actions[12].cash == [0.0, 0.5]  # stock only: 0
    s = loaded.panel.sessions.index(PAYER_DAY)
    assert loaded.j3.cash_div[10][s] == 0.5  # J3's rows: the same actions


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    s = days.index(PAYER_DAY)

    def k1(i):
        item = loaded.panel.series[i]
        return tool.div_initiation(loaded, item, s, PAYER_DAY)

    assert k1(10).qualifies and k1(12).qualifies and k1(14).qualifies
    assert k1(11).paid and not k1(11).qualifies
    assert k1(13).null and not k1(13).qualifies
    q = date(2017, 3, 31)
    at = days.index(date(2017, 5, 15))
    assert tool.eps_turn(loaded.panel.series[2], at, q).qualifies
    assert not tool.eps_turn(loaded.panel.series[1], at, q).qualifies
    assert tool.eps_turn(loaded.panel.series[LATE], at, q).reason == "stale"
    at = days.index(date(2018, 5, 15))
    assert not tool.eps_turn(loaded.panel.series[2], at, date(2018, 3, 31)).qualifies
    seller = loaded.panel.series[1]  # TWSE: not touched by the TPEx gap
    assert tool.inst_sell_5q(loaded, seller, 298).reason == "short"
    got = tool.inst_sell_5q(loaded, seller, 299)
    assert got.qualifies and got.blocks == (-6000.0,) * 5  # no dealer
    tpex = loaded.panel.series[2]
    assert tool.inst_sell_5q(loaded, tpex, GAP).reason == "market_gap"
    assert tool.inst_sell_5q(loaded, tpex, GAP + 300).qualifies
    assert not tool.inst_sell_5q(loaded, loaded.panel.series[9], 400).qualifies


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[499]),
            "validation": (days[500], days[599]),
            "used": (days[600], days[699]),
        },
    )
    floors = {"exploration": 30, "validation": 50}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(tool, "MIN_FILL_DAYS", 2)
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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "K1,K2,K3"
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
def copied(fixture_db, tmp_path, monkeypatch, short_windows) -> Path:
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
        "round14_research", "978", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (14, 3, 55)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.317)
    assert report["read_until"] == days[499].isoformat()
    hyp = report["hypotheses"]
    assert hyp["K1"]["engine"] == "portfolio" and hyp["K2"]["engine"] == "events"
    assert hyp["K1"]["fill_days"]["days"] >= 2 and hyp["K1"]["events"]["days"] > 0
    assert hyp["K2"]["hits"]["days"] == len(
        [d for d in days[:499] if d in {date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15),
                                        date(2016, 11, 14), date(2017, 3, 31), date(2017, 5, 15),
                                        date(2017, 8, 14), date(2017, 11, 14)}]
    )  # fmt: skip
    assert hyp["K3"]["hits"]["days"] > 0 and "overlap_u1" in hyp["K3"]
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 55 個" in text and "驗證段 t ≥ 3.317" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round14_research", 14, "exploration", 1) for name in NAMES]
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
    k2_md = (out / "K2" / "summary.md").read_text(encoding="utf-8")
    assert "## 每次調倉（K2 第 7 點" in k2_md
    assert "N＝20、持有到下一個事件日" in k2_md and "next_event" not in k2_md
    assert "N＝20、K＝240" in (out / "K1" / "summary.md").read_text(encoding="utf-8")
    picks = (out / "K2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == "signal_date,rank,exchange,symbol,eps_now,eps_year_before,tie"
    assert {line.split(",")[0] for line in picks[1:]} == {
        "2017-05-15",
        "2017-08-14",
        "2017-11-14",
    }  # 2017-03-31's 2016 Q4 has a loss the year before too; 2018-03-31 is after
    assert sorted(line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")) == [
        "S2", "S4", "S6",
    ]  # fmt: skip
    k1_picks = (out / "K1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    on_payer = sorted(
        line.split(",")[3] for line in k1_picks if line.startswith("2016-07-15")
    )
    assert on_payer == ["S10", "S12", "S14", "S15"]  # 11 paid, 13 a null row


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="K2") == 2
    assert any("K2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="K1,U2") == 2
    assert any("U2 not registered" in line for line in refused(capsys))


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
    data["design"] = "968"
    data["hypotheses"]["K2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_317(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "K1", "K3")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("K1", "round14_research", "finished"),
                       ("K3", "round14_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["K1", "K3"]
    assert validation["min_t"] == 3.317
    for name in ("K1", "K3"):
        assert (
            read_json(tmp_path / "validation" / name / "tables.json")["min_t"] == 3.317
        )
    assert validation["read_until"] == trading_days()[599].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.317（沒有 t 下限）" in text
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
    the used segment is loaded (PR #905 review 7053124013)."""

    db, out = explored
    real_judge, real_load = ex.explore_judge, tool.load

    def judge(stage, *args, **kwargs):
        verdict = real_judge(stage, *args, **kwargs)
        return ex.PASSED if stage == "validation" else verdict

    loads: list[tuple] = []

    def spy(db, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    report = passed_report(out, tmp_path, "K3")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[599]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["K3"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["K3"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "K3" / "used" / file).is_file(), file


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
    k1 = hyp["K1"]["coverage"]["2016"]
    # 2016-07-15: 10..15 candidates; 11 paid, 13 a null row only
    assert k1["paid"] >= 1 and k1["null_only"] == 1 and k1["null"] == 1
    assert k1["events"] >= 4 and k1["event_days"] >= 2
    assert 0 < k1["invested_sum"] / k1["invested_days"] < 1
    estimate = body["k1_event_days"]
    assert estimate["exploration"] == sum(
        row.get("event_days", 0) for row in hyp["K1"]["coverage"].values()
    )
    k2 = [e for row in hyp["K2"]["coverage"].values() for e in row["events"]]
    may = next(e for e in k2 if e["signal_date"] == "2017-05-15")
    assert may["hits"] == 3 and may["stale"] >= 1  # LATE's quarter is late
    k3 = hyp["K3"]["coverage"]
    assert k3["2017"]["missing"]["market_gap"] > 0  # TPEx windows with session 350
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["K1"] == {"plan", "div_initiation", "cash_div_ex"}
    assert seconds["K2"] == {"plan", "eps_turn", "x4_order"}
    assert seconds["K3"] == {"plan", "inst_sell_5q", "u1_order"}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "market_gaps", "actions"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "## K1 的事件日" in md
    assert "窗口內有三欄都是 null 的列" in md and "最新一季不是對應的那一季" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "K1"]
        )  # fmt: skip


# --- the ledger must be writable (#899) -------------------------------------------

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
    assert explore(copied, tmp_path / "out", hypotheses="K3") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "K3")
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
        assert explore(copied, out, hypotheses="K3") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "K3")
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
