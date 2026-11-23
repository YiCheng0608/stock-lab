"""tools/research/round16_research.py: the registered N1～N3 (#994).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十六輪：N1～N3.  The features and the accounts are
checked on hand-made series (the expected numbers worked out in the test);
the gate ("each once") and the reports run on a synthetic copy on a
compressed calendar (``compressed``): the segments and the floors are moved
into the fixture's 700 sessions, everything else is the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
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
from dataclasses import replace
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
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/994#issuecomment-1"
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
ms = _tool("mainstream_research")
im = sys.modules.get("industry_members") or _tool("industry_members")
r5 = _tool("round5_research")
r7 = _tool("round7_research")
r8 = _tool("round8_research")
r10 = _tool("round10_research")
r12 = _tool("round12_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
tool = _tool("round16_research")
NAMES = ("N1", "N2", "N3")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 16))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    n1, n2, n3 = (h[name] for name in NAMES)
    assert (n1["engine"], n2["engine"], n3["engine"]) == (
        "portfolio",
        "events",
        "events",
    )
    assert n1["keys"] == (("st_20", "low"),)
    assert (n1["top"], n1["hold"], n1["start"]) == (20, 20, ("session", OTC, 21))
    assert n2["keys"] == (("tax_mom", "high"),)
    assert (n2["top"], n2["hold"], n2["start"]) == (
        20,
        "next_event",
        ("date", date(2014, 5, 15)),
    )
    assert n3["keys"] == (("trust_flow_60", "high"),)
    assert (n3["top"], n3["hold"], n3["start"]) == (
        20,
        "quarter_end",
        ("session", date(2014, 12, 1), 60),
    )
    for spec in h.values():
        assert spec["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        16,
        3,
        61,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.346
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(61), 3) == 3.346
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "0eade4ce" and tool.DESIGN == "994"
    assert (tool.RETURNS, tool.THETA, tool.DELTA) == (20, 0.1, 0.7)
    assert (tool.REVENUE, tool.TAX, tool.REPORT_FORMAT) == (
        "營業收入",
        "所得稅費用（利益）",
        "general",
    )
    assert (tool.LAG, tool.REVENUE_MIN) == (4, 0.0)
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    assert tool.QUARTER_MONTHS == (3, 6, 9, 12)
    assert (tool.WINDOW_SESSIONS, tool.TRUST_WINDOW, tool.TRUST_COLUMNS) == (
        10,
        60,
        ("trust_buy",),
    )
    assert r14.DEADLINES == (
        (3, 31, 12, -1),
        (5, 15, 3, 0),
        (8, 14, 6, 0),
        (11, 14, 9, 0),
    )
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool.window_excess is r15.window_excess
    assert tool.single_quarter is r15.single_quarter
    assert "load_context" in tool.load.__code__.co_names
    assert {"build_context", "read_members", "load_statements", "load_statuses"} <= set(
        tool.load.__code__.co_names
    )
    assert "quarter_events" in tool.plan_n2.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "universe" in tool.market_means.__code__.co_names
    assert "_flow" in inspect.getsource(tool).split("TRUST_FLOW_60 =")[1].split("\n")[0]
    assert "r5.rank(" in inspect.getsource(tool.v2_names)
    assert "r7.rank(" in inspect.getsource(tool.y4_names)
    assert "r8.rank(" in inspect.getsource(tool.z2_names)
    assert "r15.margins_up(" in inspect.getsource(tool.p2_names)
    assert "r15.k2_names(" in inspect.getsource(tool.k2_names)
    assert "r15.x4_names(" in inspect.getsource(tool.x4_names)
    assert "r12.rank_j2(" in inspect.getsource(tool.j2_names)
    assert "r5.momentum_20(" in inspect.getsource(tool.plan_n1)
    assert "r12.trust_flow_20(" in inspect.getsource(tool.plan_n3)
    assert "order_key" in inspect.getsource(tool.plan_n1)
    assert "ranking_key" in inspect.getsource(tool.plan_n2)
    assert "ranking_key" in inspect.getsource(tool.plan_n3)


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def _other(module, name: str, key: str, value):
    return {**module.HYPOTHESES, name: {**module.HYPOTHESES[name], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#994 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.346
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.332),
        # N1: 20 returns, θ, δ, m_s, the ranks and ties, the weights, the
        # covariance, the missing cases, small first, N 20, K 20
        (tool, "RETURNS", 21),
        (tool, "THETA", 0.2),
        (tool, "DELTA", 0.8),
        (tool, "MARKET_RULE", "m_s of T's population"),
        (tool, "SALIENCE", "sigma_s = |r_s - m_s|"),
        (tool, "RANK_RULE", "equal values the later date first"),
        (tool, "WEIGHT_RULE", "omega_s = DELTA ** k_s"),
        (tool, "COVARIANCE_RULE", "the sample covariance, / 19"),
        (tool, "ST_MISSING", "a suspended bar is skipped"),
        (tool, "HYPOTHESES", _swap("N1", "keys", (("st_20", "high"),))),
        (tool, "HYPOTHESES", _swap("N1", "top", 19)),
        (tool, "HYPOTHESES", _swap("N1", "hold", 21)),
        (tool, "HYPOTHESES", _swap("N1", "start", ("session", OTC, 22))),
        # N2: the two fields, the format, the latest quarter, the formula,
        # rev(q − 4) ≤ 0, high first, N 20, the next event, the reference
        (tool, "REVENUE", "營業收入合計"),
        (tool, "TAX", "所得稅（費用）利益"),
        (tool, "FIELDS", ("tax", "revenue")),
        (tool, "REPORT_FORMAT", "other"),
        (tool, "LAG", 1),
        (tool, "REVENUE_MIN", -1.0),
        (tool, "TAX_MOM", "(tax(q) - tax(q-4)) / rev(q)"),
        (tool, "NUMBER_RULE", "float()"),
        (tool, "STATEMENT_RULE", "the latest with an EPS"),
        (tool, "SALE", "at T'+1's open"),
        (tool, "REFERENCE_RULE", "less every delisted instrument"),
        (tool, "REFERENCE_STATUSES", ("delisted",)),
        (tool, "HYPOTHESES", _swap("N2", "keys", (("tax_mom", "low"),))),
        (tool, "HYPOTHESES", _swap("N2", "top", 19)),
        (tool, "HYPOTHESES", _swap("N2", "hold", 60)),
        (tool, "HYPOTHESES", _swap("N2", "start", ("date", date(2014, 8, 14)))),
        # N3: the months, the quarter end, the window, the sale, the 60 bars,
        # the missing rule, high first, N 20, the cash between
        (tool, "QUARTER_MONTHS", (3, 6, 9, 11)),
        (tool, "QUARTER_END_RULE", "the panel's last session of the month"),
        (tool, "WINDOW_SESSIONS", 9),
        (tool, "WINDOW_RULE", "held to the next window"),
        (tool, "WINDOW_DAYS", "the sessions from T"),
        (tool, "TRUST_COLUMNS", ("foreign_buy", "trust_buy")),
        (tool, "TRUST_WINDOW", 20),
        (tool, "TRUST_MISSING", "a missing trust counts 0"),
        (tool, "SPLIT_MONTHS", ((12,), (3, 6, 9))),
        (tool, "HYPOTHESES", _swap("N3", "keys", (("trust_flow_60", "low"),))),
        (tool, "HYPOTHESES", _swap("N3", "top", 19)),
        (tool, "HYPOTHESES", _swap("N3", "hold", "next_event")),
        (tool, "HYPOTHESES", _swap("N3", "start", ("session", date(2014, 12, 1), 61))),
        # the three: the hash and the order, the event days, the single quarters
        (tool, "ORDER", "N1 high first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        (tool, "SINGLE_QUARTER", "the cumulative figure"),
        (features, "VERSION", features.VERSION + 1),
        # the overlaps' lists
        (r5, "HYPOTHESES", _other(r5, "V2", "top", 19)),
        (r7, "HYPOTHESES", _other(r7, "Y4", "top", 19)),
        (r8, "HYPOTHESES", _other(r8, "Z2", "top", 19)),
        (r15, "HYPOTHESES", _other(r15, "P2", "top", 19)),
        (r15, "LAGS", (4,)),
        (r14, "HYPOTHESES", _other(r14, "K2", "top", 19)),
        (ex, "HYPOTHESES", _other(ex, "X4", "top", 19)),
        (r12, "HYPOTHESES", _other(r12, "J2", "top", 19)),
        (r12, "TRUST_MIN", 0.01),
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
    ):  # fmt: skip
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


# AC-1: measured on master 0eade4ce before this tool existed.  forward_watch's
# F2 row reads round10_research's hash and its P2 row round15_research's; the
# overlaps read round5 (V2), round7 (Y4), round8 (Z2), round15 (P2),
# round14 (K2), explore_research (X4) and round12 (J2).
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
    "round14_research": (1, "3c8cf489dd99778e71d29215b1bd7e8b8d63607c902500c9e9ac122bbe0a0044"),
    "round15_research": (1, "dbbeb3e2626bbd4642c7b8732da3f376c9905e50575bee8f2dbed60273ea824e"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    [
        "round5_research",
        "round7_research",
        "round8_research",
        "round10_research",
        "round12_research",
        "round14_research",
        "round15_research",
        None,
    ],
)
def test_the_overlaps_tools_are_the_ledgers(name):
    """AC-1: the hashes the overlaps and forward_watch read are the ones in
    the public ledger (explore_research's entries have no ``tool``)."""

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


# AC-1: portfolio_research.ranking_key's source on master 0eade4ce
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
    section = text.split("**第十六輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.346 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round16_research.py" in section
    assert "本輪 3 個、累計 61 個" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(
    closes, opens=None, suspended=(), instrument_id=1, dates=None, volume=None
):
    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2016, 1, 4), len(closes))
    opens = opens if opens is not None else closes
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at)
        item.open.append(opens[at])
        item.high.append(max(opens[at], close))
        item.low.append(min(opens[at], close))
        item.close.append(close)
        item.volume.append(2_000_000.0 if volume is None else volume[at])
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    return item


def context_for(items=(), sessions=None, statements=None, statuses=None):
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
    symbols = {i: ("TWSE", f"S{i}", "") for i in series}
    panel = lib.Panel(sessions or [], series, {}, {}, symbols)
    base = ex.Context(pr.Market(panel, raw_rows, {}, None))
    return tool.Context(base, statements or {}, {}, statuses or {})


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


# --- N1: st_20 --------------------------------------------------------------------


def closes_of(returns: list[float], start: float = 10.0) -> list[float]:
    out = [start]
    for r in returns:
        out.append(out[-1] * (1 + r))
    return out


def weight(k: int) -> float:
    """ω for rank k by hand: 0.7^k ÷ (Σ_{j=1..20} 0.7^j ÷ 20)."""

    total = 0.7 * (1 - 0.7**20) / (1 - 0.7)  # 2.331471...
    return 0.7**k / (total / 20)


def salience(returns, means=None):
    item = make_item(closes_of(returns))
    means = means if means is not None else [0.0] * len(item.dates)
    return tool.st_20(item, len(item.dates) - 1, means)


def test_st_20_by_hand():
    """N1 第 1～3 點: one return 0.1 among 19 zeros, m_s = 0: σ is 0.5 there
    and 0 elsewhere, so it ranks 1st and the 19 zeros 2..20 by date; Σ(ω − 1)
    is 0, so the covariance is (ω_1 − 1)·0.1 ÷ 20."""

    returns = [0.1] + [0.0] * 19
    got = salience(returns)
    assert weight(1) == pytest.approx(6.004791, abs=1e-6)
    assert got.value == pytest.approx((weight(1) - 1) * 0.1 / 20)
    assert got.value == pytest.approx(0.025024, abs=1e-6)
    # the weights' mean is 1 whichever ranks they take
    assert statistics.fmean(weight(k) for k in range(1, 21)) == pytest.approx(1.0)
    # m_s takes the rank away: 0.03 on a day the population also rose 0.03 has
    # σ 0; the same 0.03 on a day the population was flat has σ 0.03 ÷ 0.13
    returns = [0.0] * 20
    returns[2] = returns[5] = 0.03
    closes = closes_of(returns)
    means = [0.0] * 21
    means[3] = closes[3] / closes[2] - 1  # r_s at bar first + 3 is returns[2], exactly
    got = tool.st_20(make_item(closes), 20, means)
    # bar of returns[5] ranks 1st; returns[2]'s σ is 0 and ties the zeros:
    # by date it is the 3rd of the 19 (returns[0], [1], [2]): rank 4
    expected = ((weight(1) - 1) * 0.03 + (weight(4) - 1) * 0.03) / 20
    assert got.value == pytest.approx(expected)


def test_st_20_ties_take_the_earlier_date_first():
    """The same σ (|r| equal, m 0): the earlier bar takes the smaller rank."""

    returns = [0.0] * 20
    returns[3], returns[10] = 0.05, -0.05
    got = salience(returns)
    mean = sum(returns) / 20
    expected = ((weight(1) - 1) * (0.05 - mean) + (weight(2) - 1) * (-0.05 - mean)
                + sum((weight(k) - 1) * (0.0 - mean) for k in range(3, 21))) / 20  # fmt: skip
    assert got.value == pytest.approx(expected)
    assert got.value > 0  # the later one first would give the negative
    returns[3], returns[10] = -0.05, 0.05
    assert salience(returns).value == pytest.approx(-expected)


def test_st_20_is_0_when_the_20_returns_are_equal_and_missing_otherwise():
    item = make_item([2.0**k for k in range(21)])  # every return exactly 1.0
    got = tool.st_20(item, 20, [0.3] * 21)
    assert (got.value, got.reason) == (0.0, None)
    flat = make_item([10.0] * 21)
    assert tool.st_20(flat, 20, [0.01] * 21).value == 0.0
    # fewer than 21 bars
    assert tool.st_20(flat, 19, [0.0] * 21).reason == "short"
    # a suspended bar among at − 20 .. at; one before them does not matter
    for bar in (0, 10, 20):
        item = make_item([10.0] * 21, suspended=(bar,))
        assert tool.st_20(item, 20, [0.0] * 21).reason == "suspended", bar
    item = make_item([10.0] * 22, suspended=(0,))
    assert tool.st_20(item, 21, [0.0] * 22).value == 0.0
    # a close missing or ≤ 0 (at − 20 and at count)
    for bar in (0, 20):
        for bad in (0.0, -1.0, NAN):
            closes = [10.0] * 21
            closes[bar] = bad
            got = tool.st_20(make_item(closes), 20, [0.0] * 21)
            assert got.reason == "price", (bar, bad)
    # an m_s missing on any of the 20 return days; the 21st close's day (at − 20) not read
    means = [0.0] * 21
    means[20] = None
    assert tool.st_20(flat, 20, means).reason == "market"
    means = [0.0] * 21
    means[0] = None
    assert tool.st_20(flat, 20, means).value == 0.0


def test_market_means_take_each_days_own_population_with_a_return(monkeypatch):
    """第十六輪實作釋義 N1 的 m_s (#994 決定 7099966724): the day's population
    (not T's), each member counted only with a non-suspended bar on the
    market's session before and both closes > 0; a day with none is missing."""

    days = weekdays(date(2016, 1, 4), 4)
    a = make_item([10.0, 11.0, 12.1, 12.1], instrument_id=1)  # +10%, +10%, 0
    b = make_item(
        [10.0, 9.0, 9.0, 9.9], instrument_id=2, suspended=(1,)
    )  # bar 1 suspended
    c = make_item([20.0, 30.0], instrument_id=3, dates=[days[0], days[2]])
    c.session = array("i", [0, 2])  # no bar on day 1: a gap
    d = make_item([20.0, 21.0], instrument_id=4, dates=days[2:])
    d.session = array("i", [2, 3])  # first bar on day 2
    by_day = {
        days[0]: [(a, 0)],  # no session before: none
        days[1]: [(a, 1)],  # b's bar 1 is suspended itself: not in a universe
        days[2]: [(a, 2), (b, 2), (c, 1), (d, 0)],  # b's bar before suspended, c's gap
        days[3]: [(a, 3), (b, 3), (d, 1)],  # a 0, b +10%, d +5%
    }
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: by_day[day])
    panel = SimpleNamespace(sessions=days)
    excluded = Counter()
    got = tool.market_means(panel, 3, excluded)
    assert got[0] is None
    assert got[1] == pytest.approx(0.1)
    assert got[2] == pytest.approx(0.1)  # a only: c's +50% over two sessions is out
    assert got[3] == pytest.approx((0.0 + 0.1 + 0.05) / 3)
    assert excluded == Counter({"2016": 1 + 3})
    assert tool.daily_return(c, 1) is None and tool.daily_return(d, 1) == pytest.approx(
        0.05
    )
    assert len(tool.market_means(panel, 1)) == 2  # to ``last`` only
    # a close ≤ 0 has no return either
    bad = make_item([10.0, 0.0, 10.0], instrument_id=5)
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(bad, days.index(day))]
    )
    assert tool.market_means(SimpleNamespace(sessions=days[:3]), 2) == [None] * 3


def test_n1_rotates_20_accounts_and_the_population_too(monkeypatch):
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    monkeypatch.setattr(pr, "simulate", simulate)
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]})
    tool.engines(SimpleNamespace(quote=None), "N1", planned, 1, 5)
    assert calls == [({1: [1]}, 20, 20), ({1: [1, 2]}, 20, None)]


def test_n1_k20_accounts_by_hand():
    """K＝20 (``portfolio_research.simulate``): account s mod 20 buys on s with
    1/20 of its cash per name and sells at the close of its 20th session."""

    prices = {(i, s): (10.0, 10.0) for i in (1, 2) for s in range(1, 30)}
    mine, population, _ = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "N1",
        SimpleNamespace(picks={1: [1], 2: [2]}, population={1: [1, 2], 2: [1, 2]}), 1, 29,
    )  # fmt: skip
    first, second = mine.positions[:2]
    assert (first.bought, first.due, second.bought, second.due) == (1, 20, 2, 21)
    assert first.cost == pytest.approx(1 / 20 / 20) == second.cost  # 1/20 of 1/20
    assert first.account != second.account
    third = population.positions[0]
    assert third.cost == pytest.approx(1 / 20 / 2)  # the population: 1/n of the account


def test_n1_plan_ranks_small_first_overlaps_v2_y4_z2_and_lists_momentum(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 30)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 26)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    values = {i: (None if i <= 3 else float(i % 5)) for i in items}
    monkeypatch.setattr(tool, "st_20", lambda item, at, means: tool.Salience(
        values[item.instrument_id], None if values[item.instrument_id] is not None else "short"))  # fmt: skip
    monkeypatch.setattr(
        tool, "market_means", lambda panel, last, excluded: [0.0, None, 0.0, None]
    )
    monkeypatch.setattr(tool, "v2_names", lambda ctx, day, members: {5, 10, 1})
    monkeypatch.setattr(tool, "y4_names", lambda ctx, day, members: set())
    monkeypatch.setattr(tool, "z2_names", lambda ctx, day, members: {4})
    moves = {i: (None if i == 5 else i / 100) for i in items}
    monkeypatch.setattr(
        r5, "momentum_20", lambda ctx, item, at: moves[item.instrument_id]
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=Counter(), market_mean=None)  # fmt: skip
    planned = tool.plan_n1(ctx, tool.HYPOTHESES["N1"], 1, 2)
    day = sessions[0]
    order = sorted(
        items, key=lambda i: (values[i] is None, values[i] or 0, pr.tie_break(day, i))
    )
    assert planned.picks[1] == order[:20]
    assert {1, 2, 3} & set(order[:20]) == set()  # 22 valued: the missing last
    assert all(values[i] == 0.0 for i in order[:4])  # 5, 10, 15, 20 first
    chosen = order[:20]
    overlap = planned.overlap
    assert overlap["N1_V2"]["2016"][0] == pytest.approx(len({5, 10} & set(chosen)) / 20)
    assert overlap["N1_Y4"] == {}  # Y4 has no list: not counted
    assert overlap["N1_Z2"]["2016"][0] == pytest.approx(1 / 20)
    expected = statistics.fmean(moves[i] for i in chosen if moves[i] is not None)
    assert planned.momentum["2016"][0] == pytest.approx(expected)
    year = planned.coverage["2016"]
    assert (year["valued"], year["missing"]["st_20"], year["missing"]["short"]) == (
        44,
        6,
        6,
    )
    assert planned.coverage["_market"] == Counter({"2016": 1})  # session 1 (to last)
    assert (
        planned.rows[0]["st_20"] == 0.0
        and planned.rows[0]["momentum_20"] == moves[order[0]]
    )


def test_the_overlap_lists_are_the_other_tools_own(monkeypatch):
    """V2, Y4, Z2 and J2 are the first 20 of the other tools' rank on the same
    T; P2 the first 20 by the hash of ``round15_research.margins_up``."""

    day = date(2016, 3, 1)
    rows = [(i, {}, "") for i in range(30, 0, -1)]
    calls = []

    def ranked(name):
        def rank(ctx, spec, d, members):
            calls.append((name, spec["top"], d))
            return SimpleNamespace(rows=rows)

        return rank

    monkeypatch.setattr(r5, "rank", ranked("V2"))
    monkeypatch.setattr(r7, "rank", ranked("Y4"))
    monkeypatch.setattr(r8, "rank", ranked("Z2"))
    monkeypatch.setattr(r12, "rank_j2", ranked("J2"))
    ctx = SimpleNamespace(seconds=Counter(), v2=None, y4=None, z2=None)
    top = set(range(30, 10, -1))
    for names in (tool.v2_names, tool.y4_names, tool.z2_names, tool.j2_names):
        assert names(ctx, day, []) == top
    assert calls == [(n, 20, day) for n in ("V2", "Y4", "Z2", "J2")]
    assert set(ctx.seconds) == {"v2_order", "y4_order", "z2_order", "j2_order"}
    members = [(make_item([10.0], instrument_id=i), 0) for i in range(1, 31)]
    monkeypatch.setattr(r15, "margins_up", lambda c, item, d, q: SimpleNamespace(
        qualifies=item.instrument_id % 2 == 0))  # fmt: skip
    ctx = SimpleNamespace(seconds=Counter(), p2=None)
    got = tool.p2_names(ctx, day, members, date(2015, 12, 31))
    evens = sorted(range(2, 31, 2), key=lambda i: pr.tie_break(day, i))
    assert got == set(evens[:20]) == set(range(2, 31, 2))  # 15 qualify: all


# --- N2: tax_mom ------------------------------------------------------------------


def tax_rows(year, revenue, tax, fmt="general", announced=None):
    """One year's rows from the single quarters (cumulative, as the source)."""

    ends = [date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)]
    dues = announced or [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                         date(year + 1, 3, 31)]  # fmt: skip
    rows, totals = [], [0.0, 0.0]
    for k, (end, due) in enumerate(zip(ends, dues)):
        if k >= len(revenue):
            break
        values = []
        for j, own in enumerate((revenue, tax)):
            totals[j] = (
                None if totals[j] is None or own[k] is None else totals[j] + own[k]
            )
            values.append(totals[j])
        rows.append(tool.TaxStatement(due, end, fmt, *values))
    return rows


DAY, Q = date(2017, 5, 15), date(2017, 3, 31)


def momentum(rows, day=DAY, quarter=Q):
    ctx = context_for(statements={1: rows})
    return tool.tax_mom(ctx, make_item([10.0]), day, quarter)


def q1_rows(tax_q=12.0, tax_q4=8.0, revenue_q4=200.0):
    return [*tax_rows(2016, [revenue_q4, 300.0, 300.0, 300.0], [tax_q4, 9.0, 9.0, 9.0]),
            *tax_rows(2017, [250.0], [tax_q])]  # fmt: skip


def test_tax_mom_by_hand():
    """N2 第 2 點: Q1 is the cumulative figure: (12 − 8) ÷ 200 = 0.02."""

    got = momentum(q1_rows())
    assert (got.value, got.reason) == (pytest.approx(0.02), None)
    assert (got.tax_q, got.tax_q4, got.revenue_q4) == (12.0, 8.0, 200.0)
    # Q3: single quarters by the difference; 2017 tax 5, 6, 9 (cum 5, 11, 20),
    # 2016 tax 3, 4, 3, revenue 2016 Q3 own 150: (9 − 3) ÷ 150 = 0.04
    rows = [*tax_rows(2016, [100.0, 200.0, 150.0, 100.0], [3.0, 4.0, 3.0, 1.0]),
            *tax_rows(2017, [100.0, 100.0, 100.0], [5.0, 6.0, 9.0])]  # fmt: skip
    got = momentum(rows, date(2017, 11, 14), date(2017, 9, 30))
    assert got.value == pytest.approx(0.04)
    assert (got.tax_q, got.tax_q4, got.revenue_q4) == (9.0, 3.0, 150.0)
    # a tax benefit (negative) counts as it is: (−5 − 3) ÷ 100
    assert momentum(q1_rows(-5.0, 3.0, 100.0)).value == pytest.approx(-0.08)
    assert momentum(q1_rows(-5.0, -9.0, 100.0)).value == pytest.approx(0.04)
    # tax(q) = tax(q − 4): exactly 0, ranked by its value
    got = momentum(q1_rows(8.0, 8.0))
    assert (got.value, got.reason) == (0.0, None)


def test_tax_mom_is_missing_stale_format_fields_or_revenue():
    rows = q1_rows()
    late = [
        r if r.period_end != Q else replace(r, announced=date(2017, 5, 16))
        for r in rows
    ]
    assert momentum(late).reason == "stale"  # 2017 Q1 not known on T
    assert momentum(rows[:4]).reason == "stale"
    assert momentum([]).reason == "stale"
    later = [
        *rows,
        tool.TaxStatement(date(2017, 5, 10), date(2017, 6, 30), "general", 1.0, 1.0),
    ]
    assert momentum(later).reason == "stale"  # the latest is not the deadline's quarter
    bank = [r if r.period_end != date(2016, 3, 31) else replace(r, report_format="bank")
            for r in rows]  # fmt: skip
    assert momentum(bank).reason == "format"
    bank_q = [
        r if r.period_end != Q else replace(r, report_format="bank") for r in rows
    ]
    assert momentum(bank_q).reason == "format"
    for end in (Q, date(2016, 3, 31)):
        for name in ("tax", "revenue"):
            gone = [
                r if r.period_end != end else replace(r, **{name: None}) for r in rows
            ]
            assert momentum(gone).reason == "fields", (end, name)
        assert momentum([r for r in rows if r.period_end != end]).reason in (
            "fields", "stale",
        )  # fmt: skip
    assert (
        momentum([r for r in rows if r.period_end != date(2016, 3, 31)]).reason
        == "fields"
    )
    no_format = [r if r.period_end != date(2016, 3, 31) else replace(r, report_format=None)
                 for r in rows]  # fmt: skip
    assert (
        momentum(no_format).reason == "fields"
    )  # a null report_format is a missing field
    eps_only = [r if r.period_end != Q else tool.TaxStatement(r.announced, Q, None, None, None)
                for r in rows]  # fmt: skip
    assert momentum(eps_only).reason == "fields"  # a delisted company's XBRL row
    # a Q3 needs the Q2 of both years (the cumulative before it)
    rows3 = [*tax_rows(2016, [100.0, 200.0, 150.0, 100.0], [3.0, 4.0, 3.0, 1.0]),
             *tax_rows(2017, [100.0, 100.0, 100.0], [5.0, 6.0, 9.0])]  # fmt: skip
    q3 = (date(2017, 11, 14), date(2017, 9, 30))
    for end in (date(2017, 6, 30), date(2016, 6, 30)):
        gone = [r if r.period_end != end else replace(r, tax=None) for r in rows3]
        assert momentum(gone, *q3).reason == "fields", end
    # rev(q − 4) ≤ 0
    for revenue in (0.0, -5.0):
        assert momentum(q1_rows(revenue_q4=revenue)).reason == "revenue"
    # rev(q) ≤ 0 is not a missing case (only rev(q − 4) divides)
    rows = [*tax_rows(2016, [200.0] * 4, [8.0] * 4), *tax_rows(2017, [-1.0], [12.0])]
    assert momentum(rows).value == pytest.approx(0.02)


def test_the_tax_statement_reads_the_two_fields():
    parse = __import__("worker.sources", fromlist=["parse_number"]).parse_number
    data = {"report_format": "general", "營業收入": "1,000", "所得稅費用（利益）": "(20)",
            "所得稅（費用）利益": "99"}  # fmt: skip
    row = tool.tax_statement_of("2017-05-15", "2017-03-31", data, parse)
    assert (row.revenue, row.tax, row.report_format) == (1000.0, -20.0, "general")
    row = tool.tax_statement_of(
        "2017-05-15", "2017-03-31", {"所得稅（費用）利益": "5"}, parse
    )
    assert (row.report_format, row.revenue, row.tax) == (
        None,
        None,
        None,
    )  # not general's name
    row = tool.tax_statement_of("2017-05-15", "2017-03-31", {**data, "所得稅費用（利益）": "--"},
                                parse)  # fmt: skip
    assert row.tax is None


def test_fields_missing_is_point_3s_field_case_on_the_deadlines_quarter():
    item = make_item([10.0])
    rows = q1_rows()
    assert not tool.fields_missing(context_for(statements={1: rows}), item, DAY, Q)
    ctx = context_for(statements={1: q1_rows(revenue_q4=0.0)})
    assert not tool.fields_missing(ctx, item, DAY, Q)  # rev ≤ 0 is not a missing field
    bank = [replace(r, report_format="bank") for r in rows]
    assert not tool.fields_missing(context_for(statements={1: bank}), item, DAY, Q)
    later = [
        *rows,
        tool.TaxStatement(date(2017, 5, 10), date(2017, 6, 30), "general", 1.0, 1.0),
    ]
    assert not tool.fields_missing(
        context_for(statements={1: later}), item, DAY, Q
    )  # stale
    ctx = context_for(statements={1: rows[:4]})  # q not known on T: its fields missing
    assert tool.fields_missing(ctx, item, DAY, Q)
    eps_only = [
        tool.TaxStatement(r.announced, r.period_end, None, None, None) for r in rows
    ]
    assert tool.fields_missing(context_for(statements={1: eps_only}), item, DAY, Q)
    assert tool.fields_missing(context_for(), item, DAY, Q)


def test_the_reference_takes_out_only_delisted_or_transferred_missing_a_field(
    monkeypatch,
):
    """N2 第 7 點, 第十六輪實作釋義: a delisted or transferred instrument
    missing a field on T is taken out; one with every field, or an active one
    missing a field, stays."""

    sessions = weekdays(date(2016, 1, 4), 250)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 7)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    statuses = {1: "active", 2: "delisted", 3: "delisted", 4: "transferred", 5: "active",
                6: "suspended"}  # fmt: skip
    missing = {1, 3, 4, 6}
    monkeypatch.setattr(
        tool, "fields_missing", lambda ctx, item, day, q: item.instrument_id in missing
    )
    values = {1: None, 2: 0.01, 3: None, 4: None, 5: 0.03, 6: -0.02}
    monkeypatch.setattr(tool, "tax_mom", lambda ctx, item, day, q: tool.TaxMomentum(
        values[item.instrument_id], None if values[item.instrument_id] is not None else "fields"))  # fmt: skip
    monkeypatch.setattr(tool, "p2_names", lambda ctx, day, members, q: {2})
    monkeypatch.setattr(tool, "k2_names", lambda ctx, day, members, q: {5})
    monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: {2, 6})
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses, statements={})  # fmt: skip
    first = sessions.index(date(2016, 3, 31)) + 1
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_n2(ctx, tool.HYPOTHESES["N2"], first, last)
    s = [
        sessions.index(d) + 1
        for d in (date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15))
    ]
    assert planned.reference[s[0]] == [1, 2, 5, 6]
    assert planned.population[s[0]] == [1, 2, 3, 4, 5, 6]
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    # high first, the missing last (by the hash): 5, 2, 6, then 1, 3, 4
    tail = sorted((1, 3, 4), key=lambda i: pr.tie_break(date(2016, 3, 31), i))
    assert planned.picks[s[0]] == [5, 2, 6, *tail]
    event = planned.rebalances[0]
    assert (event["delisted"], event["delisted_missing"]) == (3, 2)
    assert (event["valued"], event["names"], event["fields"]) == (3, 6, 3)
    assert (event["p2_overlap"], event["k2_overlap"], event["x4_overlap"]) == (
        1 / 6, 1 / 6, 2 / 6,
    )  # fmt: skip
    assert planned.overlap["N2_X4"] == {"2016": [pytest.approx(1 / 3)] * 3}
    year = planned.coverage["2016"]
    assert (year["delisted"], year["delisted_missing"], year["valued"]) == (9, 6, 9)
    assert planned.rows[0]["tax_mom"] == 0.03


def test_n2_sells_at_the_next_event_days_close_and_buys_at_its_next_open():
    """「K2 的賣出時點」: T′'s close, the new list at T′+1; fewer than 20 cash;
    T′ suspended or locked: sold at the next open, its cash in that day's buys."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              reference={1: [3], 4: [3]}, dues={1: 3, 4: 8})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "N2", planned, 1, 7
    )
    first, second = mine.positions
    assert (first.sold, first.how, second.bought) == (3, "close", 4)
    assert first.cost == pytest.approx(0.05)  # 1/20 of the cash, 19/20 left in cash
    assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    assert [p.instrument_id for p in reference.positions] == [3, 3]
    assert reference.positions[0].cost == pytest.approx(1.0)  # 1/n of the cash, n = 1
    assert population.positions[0].cost == pytest.approx(0.5)
    quote = quote_of(prices)
    for case in ("suspended", "locked"):

        def on(instrument_id, s, case=case):
            if case == "suspended" and (instrument_id, s) == (1, 3):
                return pr.Quote(10.0, 13.0, False)
            if case == "locked" and (instrument_id, s) == (1, 3):
                return pr.Quote(10.0, 13.0, True, locked_down=True)
            return quote(instrument_id, s)

        mine = tool.engines(SimpleNamespace(quote=on), "N2", planned, 1, 7)[0]
        first, second = mine.positions
        assert (first.sold, first.how) == (4, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)


def test_n2_invested_shares_and_the_excess_over_the_reference_by_hand(monkeypatch):
    """N2 第 7、8 點: one account; the reference on the same rule and event
    days; each rebalance's invested share at its T+1 close."""

    sessions = weekdays(date(2016, 3, 28), 6)
    prices = {(1, s): (10.0, (11.0, 12.0, 12.0, 13.0)[s - 1]) for s in (1, 2, 3, 4)}
    prices.update({(2, s): (10.0, 10.0) for s in (1, 2, 3, 4)})
    first, last = 1, 4
    events = [{"signal_date": sessions[0].isoformat(), "names": 1, "p2_overlap": None,
               "k2_overlap": None, "x4_overlap": None},
              {"signal_date": sessions[2].isoformat(), "names": 1, "p2_overlap": None,
               "k2_overlap": None, "x4_overlap": None}]  # fmt: skip
    plan = tool.Plan(picks={1: [1], 3: [1]}, population={1: [1, 2], 3: [1, 2]},
                     reference={1: [2], 3: [2]}, dues={1: 2, 3: 5}, rebalances=events)  # fmt: skip
    monkeypatch.setattr(tool, "segment_window", lambda *a: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_n2", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "N2", "exploration")
    units1 = pr.buy_units(0.05, 10.0)
    cash1 = 0.95
    eq1, eq2 = cash1 + units1 * 11.0, None
    proceeds = pr.sale_proceeds(units1, 12.0)
    cash2 = cash1 + proceeds
    units2 = pr.buy_units(cash2 / 20, 10.0)
    cash3 = cash2 - cash2 / 20
    eq2 = cash2
    eq3 = cash3 + units2 * 12.0
    eq4 = cash3 + units2 * 13.0
    assert result["rebalances"][0]["invested"] == pytest.approx(units1 * 11 / eq1)
    assert result["rebalances"][1]["invested"] == pytest.approx(units2 * 12 / eq3)
    mine = [eq1, eq2, eq3, eq4]
    ref_units = pr.buy_units(1.0, 10.0)
    ref1 = ref_units * 10.0
    ref_cash = pr.sale_proceeds(ref_units, 10.0)
    ref_units2 = pr.buy_units(ref_cash, 10.0)
    ref = [ref1, ref_cash, ref_units2 * 10.0, ref_units2 * 10.0]
    differences = [a - b for a, b in zip(pr.daily_returns(mine), pr.daily_returns(ref))]
    got = result["excess"]["reference"]
    assert got["days"] == 4
    assert got["mean"] == pytest.approx(statistics.fmean(differences))
    assert got["t"] == pytest.approx(lib.t_stat(differences))
    assert result["unsold_share"] == 0.5  # the second due after the segment


def test_k2_and_x4_names_are_round15s_on_the_same_t(monkeypatch):
    seen = []
    monkeypatch.setattr(r15, "k2_names", lambda *a: seen.append("k2") or {1})
    monkeypatch.setattr(r15, "x4_names", lambda *a: seen.append("x4") or {2})
    assert tool.k2_names(None, DAY, [], Q) == {1}
    assert tool.x4_names(None, DAY, []) == {2}
    assert seen == ["k2", "x4"]


# --- N3: the windows --------------------------------------------------------------


def test_the_quarter_ends_are_the_last_session_of_3_6_9_12():
    """N3 第 1 點: a Saturday make-up session that is a quarter's last session
    is its quarter end; the year's closing day before the holidays is December's;
    a month without a session after it in the calendar is no quarter end yet."""

    plain = weekdays(date(2016, 1, 4), 300)  # to 2017-02-24
    assert tool.quarter_ends(plain) == [
        date(2016, 3, 31), date(2016, 6, 30), date(2016, 9, 30), date(2016, 12, 30),
    ]  # fmt: skip
    saturday = sorted([*weekdays(date(2016, 12, 1), 30), date(2016, 12, 31)])
    assert tool.quarter_ends(saturday) == [date(2016, 12, 31)]
    closing = [d for d in weekdays(date(2017, 12, 1), 30)
               if d not in (date(2017, 12, 28), date(2017, 12, 29))]  # fmt: skip
    assert tool.quarter_ends(closing) == [date(2017, 12, 27)]
    assert tool.quarter_ends(weekdays(date(2018, 9, 3), 20)) == []  # no October yet


def test_t_is_the_11th_session_back_and_the_window_10_sessions():
    calendar = weekdays(date(2016, 1, 4), 200)
    windows = tool.windows_of(calendar, calendar)
    first = windows[0]
    assert first.quarter_end == date(2016, 3, 31)
    assert calendar[first.signal] == date(2016, 3, 17)
    assert first.due - first.signal == 10  # T+1 .. the quarter end: 10 sessions
    window = calendar[first.signal + 1 : first.due + 1]
    assert len(window) == 10 and window[0] == date(2016, 3, 18)
    # a holiday inside the window moves T one session further back
    holiday = [d for d in calendar if d != date(2016, 6, 23)]
    w = next(w for w in tool.windows_of(holiday, holiday) if w.quarter_end.month == 6)
    assert holiday[w.signal] == date(2016, 6, 15)
    # a Saturday make-up session in the window counts
    make_up = sorted([*calendar, date(2016, 9, 24)])
    w = next(w for w in tool.windows_of(make_up, make_up) if w.quarter_end.month == 9)
    assert make_up[w.signal] == date(2016, 9, 19)


def test_a_quarter_end_after_the_panel_keeps_its_own_t():
    """第十六輪實作釋義: 2024Q3's quarter end 2024-09-30 is after the
    validation (2024-09-27); T is still counted from it (2024-09-13), and the
    window runs to the segment's last close."""

    calendar = [d for d in weekdays(date(2024, 9, 2), 30) if d != date(2024, 9, 17)]
    panel = [d for d in calendar if d <= date(2024, 9, 27)]
    (window,) = tool.windows_of(calendar, panel)
    assert window.quarter_end == date(2024, 9, 30)
    assert panel[window.signal] == date(2024, 9, 13) and window.due is None
    # only the panel's own sessions: T would be 2024-09-12, the wrong one
    assert tool.windows_of(panel, panel) == []  # September not over in the panel


def test_the_starts_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2007, 11, 26), 4800)  # to 2026
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["N1"])
    assert sessions[first - 1] == weekdays(OTC, 21)[-1]
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["N2"])
    assert sessions[first - 1] == date(2014, 5, 15)
    # N3: the 60th session from 2014-12-01, then the first window: 2015Q1's T
    sixtieth = weekdays(date(2014, 12, 1), 60)[-1]
    assert sixtieth == date(2015, 2, 20)
    first, last = tool.segment_window(
        sessions, "exploration", tool.HYPOTHESES["N3"], sessions
    )
    assert sessions[first - 1] == date(2015, 3, 17)  # 10 sessions before 03-31
    assert sessions[last] == date(2019, 12, 31)
    windows = [
        w
        for w in tool.windows_of(sessions, sessions)
        if first - 1 <= w.signal <= last - 1
    ]
    assert len(windows) == 20 and windows[-1].quarter_end == date(2019, 12, 31)
    # the validation: equity from the segment's first session, the first window 2020Q1
    first, last = tool.segment_window(
        sessions, "validation", tool.HYPOTHESES["N3"], sessions
    )
    assert sessions[first] == date(2020, 1, 2)
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["N2"])
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["N1"])
    assert sessions[first] == date(2020, 1, 2)


def test_n3_buys_at_t1_open_sells_at_the_quarter_ends_close_and_holds_cash_between():
    """N3 第 2 點 (X7's account): the quarter end has no new list, so both sides
    hold cash until the next window's T+1 open; the invested shares by hand."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 10)}
    planned = SimpleNamespace(picks={1: [1, 2], 6: [3]}, population={1: [1, 2, 3], 6: [1, 2, 3]},
                              dues={1: 3, 6: 8})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "N3", planned, 1, 9
    )
    assert reference is None
    a, b, c = mine.positions
    assert [(p.instrument_id, p.bought, p.sold, p.how) for p in (a, b, c)] == [
        (1, 1, 3, "close"), (2, 1, 3, "close"), (3, 6, 8, "close"),
    ]  # fmt: skip
    assert a.cost == pytest.approx(0.05) and b.cost == pytest.approx(0.05)
    cash = 1.0 - a.cost - b.cost + a.proceeds + b.proceeds
    assert a.proceeds == pytest.approx(pr.sale_proceeds(a.units, 13.0))
    assert c.cost == pytest.approx(cash / 20)
    assert mine.equity[4 - 1] == pytest.approx(cash) == mine.equity[5 - 1]
    assert mine.invested[4 - 1] == 0.0 and population.invested[4 - 1] == 0.0
    returns = pr.daily_returns(mine.equity)
    assert returns[4 - 1] == 0.0 and returns[5 - 1] == 0.0
    assert len(population.positions) == 6
    assert population.positions[0].cost == pytest.approx(1 / 3)
    assert {p.sold for p in population.positions[:3]} == {3}
    units = pr.buy_units(0.05, 10.0)
    assert mine.invested[0] == pytest.approx(2 * units * 11 / (0.9 + 2 * units * 11))
    third = pr.buy_units(1 / 3, 10.0)
    assert population.invested[0] == pytest.approx(1.0)
    assert population.equity[0] == pytest.approx(3 * third * 11)


def test_n3_a_locked_or_suspended_quarter_end_sells_at_the_next_open_and_waits():
    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 10)}
    planned = SimpleNamespace(picks={1: [1], 6: [3]}, population={1: [1], 6: [3]},
                              dues={1: 3, 6: 8})  # fmt: skip
    for case in ("locked", "suspended"):
        quote = quote_of(prices, locked={(1, 3)} if case == "locked" else ())

        def on(instrument_id, s, quote=quote, case=case):
            if case == "suspended" and (instrument_id, s) in ((1, 3), (1, 4)):
                return pr.Quote(10.0, 10.0 + s, False)
            return quote(instrument_id, s)

        mine = tool.engines(SimpleNamespace(quote=on), "N3", planned, 1, 9)[0]
        first, second = mine.positions
        sold = 4 if case == "locked" else 5
        assert (first.sold, first.how) == (sold, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        cash = 1.0 - first.cost + first.proceeds
        assert mine.equity[5 - 1] == pytest.approx(cash)
        assert second.cost == pytest.approx(cash / 20)


def trust_item(trust, volume=None, n=None):
    n = n or len(trust)
    item = make_item([10.0] * n, volume=volume)
    item.chips["trust_buy"] = array("d", trust)
    return item


def test_trust_flow_60_by_hand():
    """N3 第 3 點: the sum of the 60 bars' trust_buy over _flow's mean volume
    (the 20 bars before T); ≤ 0 kept, by its value."""

    trust = [1000.0] * 80
    item = trust_item(trust)
    assert tool.trust_flow_60(item, 79) == pytest.approx(60_000 / 2_000_000)
    trust = [0.0] * 80
    trust[20], trust[79] = -5000.0, 1000.0  # bar 20 is at − 59
    assert tool.trust_flow_60(trust_item(trust), 79) == pytest.approx(-4000 / 2_000_000)
    trust[19] = 99999.0  # at − 60: outside
    assert tool.trust_flow_60(trust_item(trust), 79) == pytest.approx(-4000 / 2_000_000)
    assert tool.trust_flow_60(trust_item([0.0] * 80), 79) == 0.0
    volume = [2_000_000.0] * 59 + [1_000_000.0] * 20 + [9e9]  # T's own volume not read
    assert tool.trust_flow_60(trust_item([1000.0] * 80, volume), 79) == pytest.approx(
        0.06
    )
    assert tool.TRUST_FLOW_60.__qualname__ == features._flow(("x",), 1).__qualname__


def test_trust_flow_60_is_missing_without_a_trust_bar_or_a_mean_volume():
    trust = [1000.0] * 80
    for bar in (20, 50, 79):
        gone = list(trust)
        gone[bar] = NAN  # the official table did not list it: missing, not 0
        assert tool.trust_flow_60(trust_item(gone), 79) is None, bar
    gone = list(trust)
    gone[19] = NAN
    assert tool.trust_flow_60(trust_item(gone), 79) is not None
    assert tool.trust_flow_60(trust_item(trust[:59]), 58) is None  # 59 bars
    assert tool.trust_flow_60(trust_item(trust[:60]), 59) is not None
    for bad in (0.0, NAN):
        volume = [2_000_000.0] * 59 + [bad] * 21  # at − 20 .. at
        assert tool.trust_flow_60(trust_item(trust, volume), 79) is None, bad
    item = make_item([10.0] * 80)
    item.chips = {}
    assert tool.trust_flow_60(item, 79) is None


def test_n3_window_only_excess_and_the_split_by_hand():
    windows = [{"first": 2, "last": 4, "quarter_end": "2016-03-31"},
               {"first": 7, "last": 8, "quarter_end": "2016-06-30"}]  # fmt: skip
    differences = [
        0.01,
        0.02,
        -0.01,
        0.03,
        0.0,
        0.0,
        0.04,
        -0.02,
        0.0,
    ]  # sessions 1 .. 9
    parts = tool.window_parts(windows, 1, differences)
    picked = [0.02, -0.01, 0.03, 0.04, -0.02]
    mean = sum(picked) / 5
    sd = math.sqrt(sum((v - mean) ** 2 for v in picked) / 4)
    assert parts["all"]["days"] == 5 and parts["all"]["mean"] == pytest.approx(0.012)
    assert parts["all"]["t"] == pytest.approx(mean / (sd / math.sqrt(5)))
    june = [0.04, -0.02]
    assert parts["6/12"]["days"] == 2 and parts["6/12"]["mean"] == pytest.approx(0.01)
    sd = math.sqrt(sum((v - 0.01) ** 2 for v in june) / 1)
    assert parts["6/12"]["t"] == pytest.approx(0.01 / (sd / math.sqrt(2)))
    assert parts["3/9"]["days"] == 3 and parts["3/9"]["mean"] == pytest.approx(0.04 / 3)
    assert windows[0]["excess"]["mean"] == pytest.approx(0.04 / 3)
    assert windows[1]["excess"]["days"] == 2


def test_n3_plan_takes_20_high_first_and_lists_j2_and_trust_flow_20(monkeypatch):
    calendar = weekdays(date(2016, 1, 4), 200)  # to 2016-10-07
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    values = {i: (None if i > 27 else float(i % 4) - 1.0) for i in items}  # −1 .. 2
    monkeypatch.setattr(
        tool, "trust_flow_60", lambda item, at: values[item.instrument_id]
    )
    monkeypatch.setattr(tool, "j2_names", lambda ctx, day, members: {3, 7, 30})
    flows = {i: (None if i == 3 else i / 1000) for i in items}
    monkeypatch.setattr(
        r12, "trust_flow_20", lambda item, at: flows[item.instrument_id]
    )
    sessions = calendar[:190]  # the panel ends 2016-09-23: 2016Q3's window crosses it
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=Counter(), calendar=calendar)  # fmt: skip
    first = calendar.index(date(2016, 3, 17)) + 1
    last = len(sessions) - 1
    planned = tool.plan_n3(ctx, tool.HYPOTHESES["N3"], first, last)
    signals = [date(2016, 3, 17), date(2016, 6, 16), date(2016, 9, 16)]
    s = [calendar.index(d) + 1 for d in signals]
    ends = [calendar.index(date(2016, 3, 31)), calendar.index(date(2016, 6, 30))]
    assert planned.dues == {s[0]: ends[0], s[1]: ends[1], s[2]: last + 1}
    day = signals[0]
    order = sorted(items, key=lambda i: (values[i] is None, -(values[i] or 0),
                                         pr.tie_break(day, i)))  # fmt: skip
    assert planned.picks[s[0]] == order[:20]
    assert all(values[i] == 2.0 for i in order[:7])  # 3, 7, .., 27
    assert [values[i] for i in order[14:27]] == [0.0] * 7 + [-1.0] * 6  # ≤ 0 by value
    assert [values[i] for i in order[27:]] == [None] * 3  # the missing last
    windows = planned.coverage["windows"]
    assert [w["days"] for w in windows] == [10, 10, last - (s[2] - 1)]
    assert [w["valued"] for w in windows] == [27] * 3
    assert [w["names"] for w in windows] == [20] * 3
    assert windows[2]["quarter_end"] == "2016-09-30"
    chosen = order[:20]
    assert planned.windows[0]["j2_overlap"] == pytest.approx(
        len({3, 7} & set(chosen)) / 20
    )
    expected = statistics.fmean(flows[i] for i in chosen if flows[i] is not None)
    assert planned.windows[0]["trust_flow_20"] == pytest.approx(expected)
    assert planned.trust20["2016"][0] == pytest.approx(expected)
    assert planned.overlap["N3_J2"]["2016"] == [pytest.approx(2 / 20)] * 3
    year = planned.coverage["2016"]
    assert (year["days"], year["members"], year["valued"]) == (3, 90, 81)


def test_n3_runs_its_windows_and_the_last_one_to_the_segments_close(monkeypatch):
    """The validation's last window crosses the segment's end: its positions
    are valued at the last close (unsold); the window-only excess and each
    window's numbers come from the same differences."""

    sessions = weekdays(date(2016, 3, 1), 8)
    prices = {(i, s): (10.0, 10.0 + s / 10) for i in (1, 2) for s in range(0, 8)}
    windows = [{"signal_date": sessions[0].isoformat(), "quarter_end": "2016-03-03", "members": 2,
                "valued": 2, "missing": 0, "names": 1, "days": 2, "first": 1, "last": 2,
                "j2_overlap": None, "trust_flow_20": None},
               {"signal_date": sessions[4].isoformat(), "quarter_end": "2016-03-31", "members": 2,
                "valued": 2, "missing": 0, "names": 1, "days": 2, "first": 5, "last": 6,
                "j2_overlap": None, "trust_flow_20": None}]  # fmt: skip
    plan = tool.Plan(picks={1: [1], 5: [1]}, population={1: [1, 2], 5: [1, 2]},
                     dues={1: 2, 5: 7}, windows=windows)  # fmt: skip
    monkeypatch.setattr(tool, "segment_window", lambda *a: (1, 6))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_n3", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "N3", "validation", min_t=3.346)
    assert result["unsold_share"] == 0.5 and result["counts"]["N3"]["unsold"] == 1
    assert result["window_days"] == 4 and result["window_excess"]["days"] == 4
    assert [w["excess"]["days"] for w in result["windows"]] == [2, 2]
    assert set(result["window_split"]) == {"6/12", "3/9"}
    assert result["window_split"]["6/12"]["days"] == 0
    assert result["windows"][0]["invested"] == pytest.approx(
        pr.buy_units(0.05, 10.0) * 10.1 / (0.95 + pr.buy_units(0.05, 10.0) * 10.1)
    )
    assert result["min_t"] == 3.346


# --- the verdicts -----------------------------------------------------------------


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
        (3.332, "前瞻觀察"),  # round 15's threshold is not this round's
        (3.345, "前瞻觀察"),
        (3.346, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_346(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 700
STOCKS = range(1, 25)
# the last bar's index (26 in the exploration, 25 in the validation); 25 EPS only,
# 26 every field
DELISTED = {25: 570, 26: 450}
TRANSFERRED = 27  # EPS only
INDEX_ID = 90
TAX_UP = range(1, 7)  # tax rising every quarter: tax_mom > 0, i high first
BANK = 9  # report_format bank: never a tax_mom
NO_TRUST = 11  # no institutional row every 7th session: trust_flow_60 missing
SEMI = range(1, 9)  # the member table's semiconductor industry


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


def fundamental_rows() -> list[dict]:
    """2012～2018: revenue 1,000 a quarter; TAX_UP's tax rises 0.5·i a quarter,
    the others' stays 20 (tax_mom 0); EPS 1 a quarter."""

    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        k = 0
        for year in range(2012, 2019):
            totals, eps = [0.0, 0.0], 0.0
            ends = [date(year, 3, 31), date(year, 6, 30), date(year, 9, 30),
                    date(year, 12, 31)]  # fmt: skip
            dues = [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                    date(year + 1, 3, 31)]  # fmt: skip
            for q, (end, due) in enumerate(zip(ends, dues), 1):
                k += 1
                eps += 1.0
                own = (1000.0, 20.0 + (0.5 * i * k if i in TAX_UP else 0.0))
                totals = [a + b for a, b in zip(totals, own)]
                data: dict = {}
                if i not in (25, TRANSFERRED):  # the XBRL rows: EPS only
                    data = {"report_format": "bank" if i == BANK else "general",
                            "營業收入": f"{totals[0]:,.0f}",
                            "所得稅費用（利益）": f"{totals[1]:.1f}"}  # fmt: skip
                    if i == BANK:
                        data = {"report_format": "bank", "營業收入": f"{totals[0]:,.0f}",
                                "所得稅（費用）利益": f"({totals[1]:.1f})"}  # fmt: skip
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": due, "eps": eps, "data_json": data,
                             "source": "test"})  # fmt: skip
    return rows


def member_rows() -> list[list]:
    day = trading_days()[0].isoformat()
    label = im.GROUP_LABELS["TWSE"]["24"]
    return sorted(
        [day, "TWSE", "24", "", label, im.group_id(label), f"S{i}", f"N{i}",
         im.retroactive("TWSE", "24", day)]
        for i in SEMI
    )  # fmt: skip


def write_members(folder: Path) -> Path:
    target = folder.joinpath(*ms.MEMBERS_DIR, ms.MEMBERS_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(im.table_bytes(member_rows(), "2016-01", "2016-01"))
    return target


def build(path_: Path) -> Path:
    engine = create_engine(f"sqlite:///{path_}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ids = [*STOCKS, *DELISTED, TRANSFERRED]
    status = {**{i: "delisted" for i in DELISTED}, TRANSFERRED: "transferred"}
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
                 "instrument_type": "stock", "status": status.get(i, "active")}
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
                if i == NO_TRUST and t % 7 == 3:
                    continue
                chips.append({"instrument_id": i, "trading_date": day,
                              "trust_buy": float((i - 12) * 100 + 50 * noise(i, t, "trust")),
                              "source": "test"})  # fmt: skip
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
        db.execute(insert(FundamentalSnapshot), fundamental_rows())
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round16")
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
        lambda: tool.load(fixture_db, members, date(1990, 1, 1), days[499], raw)
    )


def test_one_panel_serves_the_statements_the_members_and_the_overlaps(loaded):
    assert loaded.groups.market is loaded.base.market
    for part in (loaded.v2, loaded.y4, loaded.z2, loaded.p2):
        assert part.base is loaded.base
    assert loaded.y4.groups is loaded.groups and loaded.p2.z4 is loaded.z2
    assert set(loaded.load_seconds) == {"panel", "statements", "members", "calendar"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    rows = loaded.statements[1]
    assert rows[0].revenue == 1000.0 and rows[0].tax == pytest.approx(20.5)
    assert loaded.statements[25][0].tax is None  # EPS only
    assert loaded.statements[BANK][0].tax is None  # bank's tax is under another name
    assert loaded.p2_statements[1][0].revenue == 1000.0  # round15's own reading
    # the calendar runs past the panel (dates only)
    assert loaded.panel.sessions[-1] == trading_days()[499]
    assert loaded.calendar == trading_days()
    # nothing but the dates after the segment: no bar, chip or statement row
    end = trading_days()[499]
    assert all(d <= end for item in loaded.panel.series.values() for d in item.dates)
    assert all(r.announced <= end for rows in loaded.statements.values() for r in rows)
    assert all(isinstance(d, date) for d in loaded.calendar)


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    at = days.index(date(2017, 5, 15))
    series = loaded.panel.series
    q = date(2017, 3, 31)
    for i in TAX_UP:  # (tax(q) − tax(q − 4)) ÷ 1,000 = 0.5·i·4 ÷ 1,000
        got = tool.tax_mom(loaded, series[i], days[at], q)
        assert got.value == pytest.approx(0.002 * i), i
    assert tool.tax_mom(loaded, series[10], days[at], q).value == 0.0
    assert tool.tax_mom(loaded, series[BANK], days[at], q).reason == "format"
    assert tool.tax_mom(loaded, series[25], days[at], q).reason == "fields"
    assert tool.fields_missing(loaded, series[25], days[at], q)
    assert not tool.fields_missing(loaded, series[26], days[at], q)
    means = tool.market_means(loaded.panel, 100)
    assert means[0] is None and all(m is not None for m in means[30:])
    got = tool.st_20(series[1], 60, means)
    assert got.value is not None and tool.st_20(series[1], 19, means).reason == "short"
    assert tool.trust_flow_60(series[1], 59) is not None
    assert tool.trust_flow_60(series[1], 58) is None
    assert tool.trust_flow_60(series[NO_TRUST], 100) is None


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[479]),
            # N2's 2017-11-14 event; N3's 2018Q1 window (T 2018-03-16, quarter
            # end 2018-03-30) crosses the end
            "validation": (days[480], days[580]),
            "used": (days[581], days[699]),
        },
    )
    floors = {"exploration": 30, "validation": 10}
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
    write_members(folder)
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "N1,N2,N3"
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
        "round16_research", "994", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (16, 3, 61)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.346)
    assert report["read_until"] == days[479].isoformat()
    hyp = report["hypotheses"]
    assert [hyp[n]["engine"] for n in NAMES] == ["portfolio", "events", "events"]
    for key in ("overlap_v2", "overlap_z2", "momentum_20"):
        assert hyp["N1"][key]["days"] > 0, key
    assert hyp["N2"]["reference_excess"]["days"] > 0
    for key in ("overlap_p2", "overlap_k2", "overlap_x4"):
        assert key in hyp["N2"], key
    # N3: the windows 2016Q2 .. 2017Q3 (2016Q1's T is before the 60th session)
    assert hyp["N3"]["windows"] == 6 and hyp["N3"]["window_days"] == 60
    assert set(hyp["N3"]["window_split"]) == {"6/12", "3/9"}
    assert hyp["N3"]["window_split"]["6/12"]["days"] == 30
    assert "overlap_j2" in hyp["N3"] and hyp["N3"]["trust_flow_20"]["days"] == 6
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 61 個" in text and "驗證段 t ≥ 3.346" in text
    assert tool.OVERLAP_NOTE["N2_survivor"] in text
    assert tool.OVERLAP_NOTE["summary_only"] in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round16_research", 16, "exploration", 1) for name in NAMES]
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
        assert tool.DEGENERATE[name] in summary
    n1 = (out / "N1" / "summary.md").read_text(encoding="utf-8")
    assert n1.splitlines()[2] == "- " + tool.OVERLAP_NOTE["summary_only"]
    for key in ("N1_V2", "N1_Y4", "N1_Z2"):
        assert tool.OVERLAP_NOTE[key] in n1
    assert "## 名單的平均 `momentum_20`" in n1
    n2 = (out / "N2" / "summary.md").read_text(encoding="utf-8")
    assert n2.splitlines()[2] == tool.OVERLAP_NOTE["N2_survivor"]  # the report's start
    assert n2.splitlines()[4] == "- " + tool.OVERLAP_NOTE["summary_only"]
    assert (
        "超額（對對照基準，只列出）" in n2 and tool.OVERLAP_NOTE["N2_reference"] in n2
    )
    for key in ("N2_P2", "N2_K2", "N2_X4"):
        assert tool.OVERLAP_NOTE[key] in n2
    assert "## 每次調倉（N2 第 8 點" in n2
    n3 = (out / "N3" / "summary.md").read_text(encoding="utf-8")
    assert tool.OVERLAP_NOTE["summary_only"] not in n3
    assert "## 每個窗口（N3 第 7 點" in n3 and tool.OVERLAP_NOTE["N3_window"] in n3
    assert "只算6 月與 12 月窗口" in n3 and tool.OVERLAP_NOTE["N3_J2"] in n3
    assert "持有到季底收盤，窗口之間留現金" in n3
    picks = (out / "N2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        picks[0]
        == "signal_date,rank,exchange,symbol,quarter,tax_mom,tax_q,tax_q4,revenue_q4,tie"
    )
    on = [line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")]
    assert on[:6] == [f"S{i}" for i in (6, 5, 4, 3, 2, 1)]  # tax_mom high first
    n3_picks = (out / "N3" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        n3_picks[0]
        == "signal_date,rank,exchange,symbol,quarter_end,trust_flow_60,trust_flow_20,tie"
    )
    assert {line.split(",")[0] for line in n3_picks[1:]} == {
        d.isoformat() for d in (date(2016, 6, 16), date(2016, 9, 16), date(2016, 12, 16),
                                date(2017, 3, 17), date(2017, 6, 16), date(2017, 9, 15))
    }  # fmt: skip
    first = [line.split(",") for line in n3_picks[1:] if line.startswith("2016-06-16")]
    assert first[0][3] == "S27" and len(first) == 20  # the largest trust_buy


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="N2") == 2
    assert any("N2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="N1,P2") == 2
    assert any("P2 not registered" in line for line in refused(capsys))


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
    data["design"] = "984"
    data["hypotheses"]["N2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_346(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "N2", "N3")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("N2", "round16_research", "finished"),
                       ("N3", "round16_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["N2", "N3"]
    assert validation["min_t"] == 3.346
    for name in ("N2", "N3"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["reason"] is None, (
            name,
            tables["reason"],
            tables["prerequisites"],
        )
        assert tables["min_t"] == 3.346
    days = trading_days()
    assert validation["read_until"] == days[580].isoformat()
    assert validation["hypotheses"]["N2"]["reference_excess"]["days"] > 0
    # N3: equity from the segment's first session; 2017Q4's window and 2018Q1's,
    # which crosses the end (2018-03-30 after 2018-03-26): valued at its close
    n3 = read_json(tmp_path / "validation" / "N3" / "tables.json")
    assert n3["window"]["first_session"] == days[480].isoformat()
    assert [w["signal_date"] for w in n3["windows"]] == ["2017-12-15", "2018-03-16"]
    assert [w["quarter_end"] for w in n3["windows"]] == ["2017-12-29", "2018-03-30"]
    assert [w["days"] for w in n3["windows"]] == [10, 580 - 574]
    assert validation["hypotheses"]["N3"]["unsold_share"] > 0
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.346（沒有 t 下限）" in text
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

    def spy(db, members, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, members, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    report = passed_report(out, tmp_path, "N1")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[580]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["N1"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["N1"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "N1" / "used" / file).is_file(), file


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
    n1 = hyp["N1"]["coverage"]
    assert sum(row.get("valued", 0) for key, row in n1.items() if key != "_market") > 0
    assert n1["_market"] == {"2016": 19}  # no member before the 20-session volume
    assert n1["_market_days"]["2016"] == 260
    assert n1["_excluded"]["2016"] == 0  # no gap nor suspended bar in the copy
    may = next(e for row in hyp["N2"]["coverage"].values() for e in row["events"]
               if e["signal_date"] == "2017-05-15")  # fmt: skip
    assert may["format"] == 1 and may["fields"] == 2  # BANK; 25 and 27 (EPS only)
    assert may["valued"] == may["members"] - 3
    assert (may["delisted"], may["delisted_missing"]) == (3, 2)  # 25, 26, 27; 26 kept
    windows = hyp["N3"]["coverage"]["windows"]
    assert [w["signal_date"] for w in windows][:2] == ["2016-06-16", "2016-09-16"]
    assert all(w["missing"] == 1 and w["valued"] == w["members"] - 1 for w in windows)
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["N1"] == {"plan", "m_s", "st_20", "v2_order", "y4_order", "z2_order"}
    assert seconds["N2"] == {
        "plan",
        "tax_mom",
        "reference",
        "p2_order",
        "k2_order",
        "x4_order",
    }
    # J2's own rank times its turnover_60 and trust_flow_20 too
    assert seconds["N3"] == {
        "plan",
        "trust_flow_60",
        "j2_order",
        "turnover_60",
        "trust_flow_20",
    }
    columns = body["columns_2013"]
    assert sorted(columns) == ["2013-03-31", "2013-06-30", "2013-09-30", "2013-12-31"]
    general = columns["2013-03-31"]["general"]
    assert (
        general["fields"]["所得稅費用（利益）"] == general["rows"] == 23 + 1
    )  # 26 too
    assert general["signs"] == {"positive": 24}
    assert columns["2013-03-31"]["bank"]["fields"] == {
        "營業收入": 1,
        "所得稅費用（利益）": 0,
    }
    assert "所得稅（費用）利益" in columns["2013-03-31"]["bank"]["columns"]
    assert body["tax_signs"]["2013"] == {"positive": 4 * 24}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {
        "panel",
        "statements",
        "members",
        "calendar",
    }
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "## N2：2013 年各季的欄名" in md
    assert "最新一季不是對應的那一季" in md and "m_s 缺的天數" in md
    assert "不計入 m_s 的檔次（每日平均）" in md
    assert "有 `trust_flow_60` 的檔數" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "N1"]
        )  # fmt: skip


def test_a_member_table_that_is_not_779s_is_refused(
    copied, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(ms, "MEMBERS_SHA256", "0" * 64)
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", "--coverage-only", hypotheses=None) == 2
    assert any("not the member table's" in line for line in refused(capsys))


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
    assert explore(copied, tmp_path / "out", hypotheses="N3") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "N3")
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
        assert explore(copied, out, hypotheses="N3") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "N3")
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
