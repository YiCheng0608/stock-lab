"""tools/research/round19_research.py: the registered D1, D2 (#1047).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十九輪：D1、D2.  The features and the accounts are
checked on hand-made series (the expected numbers worked out in the test);
the gate ("each once") and the reports run on a synthetic copy on a
compressed calendar (``compressed``): the segments and the floors are moved
into the fixture's 1,500 sessions, everything else is the registered one.
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
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import (
    Base,
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1047#issuecomment-1"
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
r6 = _tool("round6_research")
r8 = _tool("round8_research")
r10 = _tool("round10_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
r16 = _tool("round16_research")
tool = _tool("round19_research")
NAMES = ("D1", "D2")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 19))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    d1, d2 = (h[name] for name in NAMES)
    assert (d1["engine"], d2["engine"]) == ("portfolio", "events")
    assert d1["keys"] == (("tk_60", "low"),)
    assert (d1["top"], d1["hold"], d1["start"], d1["rule"]) == (
        20, 60, ("session", OTC, 1201), "daily",
    )  # fmt: skip
    assert d2["conditions"] == (("eps_streak_4", "is", True),)
    assert d2["order"] == "the hash only"
    assert (d2["top"], d2["hold"], d2["start"], d2["rule"]) == (
        20, "next_event", ("date", date(2015, 3, 31)), "quarterly",
    )  # fmt: skip
    for spec in h.values():
        assert spec["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        19,
        2,
        68,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.376
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(68), 3) == 3.376
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "e064372b" and tool.DESIGN == "1047"
    assert (tool.TK_SESSIONS, tool.TK_STEP, tool.TK_SEGMENTS) == (61, 20, 60)
    assert (tool.ALPHA, tool.LAMBDA, tool.GAMMA, tool.DELTA) == (0.88, 2.25, 0.61, 0.69)
    assert (tool.EPS_FIELD, tool.STREAK_QUARTERS, tool.YEAR_LAG) == ("eps", 4, 4)
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool.single_quarter is r15.single_quarter
    assert tool.SINGLE_QUARTER == r15.SINGLE_QUARTER
    assert "load_context" in tool.load.__code__.co_names
    assert {"load_statuses", "load_statements"} <= set(tool.load.__code__.co_names)
    assert "quarter_events" in tool.plan_d2.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "r14.eps_turn(" in inspect.getsource(tool.eps_streak_4)
    assert "r8.rank(" in inspect.getsource(tool.z2_names)
    assert "r6.rank(" in inspect.getsource(tool.w2_names)
    assert "r5.rank(" in inspect.getsource(tool.v1_names)
    assert "r14.x4_names(" in inspect.getsource(tool.x4_names)
    assert "r15.k2_names(" in inspect.getsource(tool.k2_names)
    assert "r16.p2_names(" in inspect.getsource(tool.p2_names)
    assert "r5.order_key(" in inspect.getsource(tool.plan_d1)
    source = inspect.getsource(tool.plan_d1)
    for name in ("r8.skew_240(", "r5.vol_60(", "r6.reversal_720_240("):
        assert name in source, name


def _swap(spec_name: str, key: str, value):
    return {**tool.HYPOTHESES, spec_name: {**tool.HYPOTHESES[spec_name], key: value}}


def _other(module, name: str, key: str, value):
    return {**module.HYPOTHESES, name: {**module.HYPOTHESES[name], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1047 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.376
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.368),
        # D1: 61 sampling days 20 apart from Panel.sessions, the excess over
        # the TAIEX, α λ γ δ, the zero a gain, the cumulative weights, the
        # missing rules, small first, N 20, K 60
        (tool, "TK_SESSIONS", 62),
        (tool, "TK_STEP", 21),
        (tool, "TK_SEGMENTS", 61),
        (tool, "TK_SAMPLE", "the item's own last 1,201 bars"),
        (tool, "TK_SAMPLE", "every session T-1200 .. T with a bar"),
        (tool, "TK_RETURNS", "x_k = r_k, the raw returns"),
        (tool, "ALPHA", 0.5),
        (tool, "LAMBDA", 1.0),
        (tool, "GAMMA", 0.65),
        (tool, "DELTA", 0.6),
        (tool, "ZERO_SIDE", "loss"),
        (tool, "TK_VALUE", "v(x) = x"),
        (tool, "TK_WEIGHT", "w(P) = P"),
        (tool, "TK_RULE", "the losses cumulated from the least bad"),
        (tool, "TK_RULE", "the gains cumulated from the worst"),
        (tool, "TK_MISSING", "a suspended bar on a sampling day: missing"),
        (tool, "TK_MISSING", "a TAIEX close missing: the stock's own return"),
        (tool, "MARKET_RULE", "by stock"),
        (tool, "HYPOTHESES", _swap("D1", "keys", (("tk_60", "high"),))),
        (tool, "HYPOTHESES", _swap("D1", "top", 19)),
        (tool, "HYPOTHESES", _swap("D1", "hold", 20)),
        (tool, "HYPOTHESES", _swap("D1", "start", ("session", OTC, 1200))),
        # D2: eps, K2's latest quarter, the deadline's quarter, the single
        # quarters, the four strict >, the 8 quarters, the hash's 20, the next
        # event
        (tool, "EPS_FIELD", "eps_diluted"),
        (tool, "STREAK_QUARTERS", 3),
        (tool, "YEAR_LAG", 1),
        (tool, "LATEST_RULE", "P2's reading: an EPS null row too"),
        (tool, "LATEST_RULE", "any quarter known"),
        (tool, "STREAK_RULE", "e(q-k) >= e(q-k-4)"),
        (tool, "STREAK_MISSING", "a missing quarter is skipped"),
        (tool, "SINGLE_QUARTER", "the cumulative figures"),
        (features, "VERSION", features.VERSION + 1),
        (tool, "HYPOTHESES", _swap("D2", "conditions", (("eps_streak_4", "is", False),))),
        (tool, "HYPOTHESES", _swap("D2", "order", "by eps")),
        (tool, "HYPOTHESES", _swap("D2", "top", 19)),
        (tool, "HYPOTHESES", _swap("D2", "hold", 60)),
        (tool, "HYPOTHESES", _swap("D2", "start", ("date", date(2015, 5, 15)))),
        (r14, "HYPOTHESES", _other(r14, "K2", "top", 19)),  # K2's reading's tool
        # the two: the hash and the order, the start, the event days
        (tool, "ORDER", "high first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "SALE", "at T'+1's open"),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        # the overlaps' lists
        (r8, "HYPOTHESES", _other(r8, "Z2", "top", 19)),
        (r8, "SKEW_RETURNS", 239),
        (r6, "HYPOTHESES", _other(r6, "W2", "top", 19)),
        (r5, "HYPOTHESES", _other(r5, "V1", "top", 19)),
        (ex, "HYPOTHESES", _other(ex, "X4", "top", 19)),
        (r15, "HYPOTHESES", _other(r15, "P2", "top", 19)),
        # common
        (tool, "MIN_LOTS", 500),
        (er, "LIMIT_BEFORE_WIDENING", Fraction(1, 10)),
        (er, "LIMIT_WIDENED_ON", date(2015, 6, 2)),
        (er, "LIMIT", Fraction(1, 20)),
        (tool, "LOAD_RULE", "the warm-up before a later segment"),
        (tool, "LOAD_FROM", date(2004, 1, 1)),
        (tool, "MIN_T", 1.96),
        (tool, "SEGMENTS", {**tool.SEGMENTS, "validation": (date(2020, 1, 3), date(2024, 9, 27))}),
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
        "-h", "--help", "--db", "--out", "--segment", "--min-free-gb", "--coverage-only",
        "--hypotheses", "--exploration-report", "--exploration-sha256", "--exploration-url",
    }  # fmt: skip


# AC-1: measured on master e064372b before this tool existed.  forward_watch's
# F2 row reads round10_research's hash, its P2 row round15_research's and its
# A1 row round17_research's; the overlaps read round8 (Z2), round6 (W2),
# round5 (V1), explore_research (X4), round14 (K2) and round15 (P2).
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
    "round16_research": (1, "28c4651b1574b8ecc3cd60757c067322532c3ddf62d27291c6e5579ac4016edc"),
    "round17_research": (1, "505666ec2537fdb6b77086ce6b633bd6b58b4a61de8b7aa5f6213ef18d4c95df"),
    "round18_research": (1, "5e840aa8361f40ae87e783caa907b86ea5daafbd02c741e5aeb50df8a25adc73"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round5_research", "round6_research", "round8_research", "round10_research",
     "round14_research", "round15_research", "round17_research", "round18_research",
     None],
)  # fmt: skip
def test_the_overlaps_tools_are_the_ledgers(name):
    """AC-1: the hashes the overlaps and forward_watch read are the ones in
    the public ledger (explore_research's entries have no ``tool``)."""

    entries = json.loads(
        (ROOT / "tools" / "research" / "explore_ledger.json").read_text(
            encoding="utf-8"
        )
    )["entries"]
    module = ex if name is None else (sys.modules.get(name) or _tool(name))
    found = {
        e["definitions_sha256"]
        for e in entries
        if e.get("tool") == name and e.get("version") == module.VERSION
    }
    assert found == {module.definitions_sha256()}


# AC-1: portfolio_research.ranking_key's source on master e064372b
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
    section = text.split("**第十九輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.376 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round19_research.py" in section
    assert "本輪 2 個、累計 68 個" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(
    closes,
    opens=None,
    suspended=(),
    instrument_id=1,
    dates=None,
    sessions=None,
    quarters=(),
):
    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2016, 1, 4), len(closes))
    opens = opens if opens is not None else closes
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at if sessions is None else sessions[at])
        item.open.append(opens[at])
        item.high.append(max(opens[at], close))
        item.low.append(min(opens[at], close))
        item.close.append(close)
        item.volume.append(2_000_000.0)
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    item.quarters = sorted(quarters, key=lambda row: (row[0], row[1]))
    return item


def context_for(items=(), sessions=None, statuses=None, index=None):
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
    panel = lib.Panel(sessions or [], series, {}, index or {}, symbols)
    base = ex.Context(pr.Market(panel, raw_rows, {}, None))
    return tool.Context(base, statuses or {})


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


# --- D1: tk_60 --------------------------------------------------------------------


def w(p: float, c: float) -> float:
    """Tversky & Kahneman's weight, written out again (not the tool's)."""

    return p**c / (p**c + (1 - p) ** c) ** (1 / c)


def v(x: float) -> float:
    return x**0.88 if x >= 0 else -2.25 * (-x) ** 0.88


def tk_by_the_formula(xs: list[float]) -> float:
    """docs D1 第 3 點 with its own indices: x₍₋ₘ₎ < … < x₍₋₁₎ < 0 ≤ x₍₁₎ < … < x₍ₙ₎."""

    losses = sorted((x for x in xs if x < 0), reverse=True)  # x₍₋₁₎, x₍₋₂₎, …
    gains = sorted(x for x in xs if x >= 0)  # x₍₁₎, x₍₂₎, …
    m, n = len(losses), len(gains)
    total = 0.0
    for i in range(1, m + 1):
        total += v(losses[i - 1]) * (w((m - i + 1) / 60, 0.69) - w((m - i) / 60, 0.69))
    for i in range(1, n + 1):
        total += v(gains[i - 1]) * (w((n - i + 1) / 60, 0.61) - w((n - i) / 60, 0.61))
    return total


def test_the_value_function_and_the_two_weights_by_hand():
    """D1 第 3 點: v(0.1) = 0.1^0.88 = 0.131826, v(−0.1) = −2.25 × 0.131826;
    w⁺(½) with γ 0.61: ½^0.61 = 0.65520, (2 × 0.65520)^(1/0.61) = 1.5576,
    0.42064; w⁻(½) with δ 0.69 is 0.45399; w(0) = 0, w(1) = 1."""

    assert tool.probability_weight(0.5, tool.GAMMA) == pytest.approx(0.42064, abs=1e-5)
    assert tool.probability_weight(0.5, tool.DELTA) == pytest.approx(0.45399, abs=1e-5)
    assert tool.probability_weight(1 / 6, tool.GAMMA) == pytest.approx(
        0.23876, abs=1e-5
    )
    for c in (tool.GAMMA, tool.DELTA):
        assert tool.probability_weight(0.0, c) == 0.0
        assert tool.probability_weight(1.0, c) == 1.0
    minus, plus = tool.decision_weights(tool.GAMMA, tool.DELTA, 60)
    assert len(minus) == len(plus) == 60
    assert math.fsum(minus) == pytest.approx(1.0) == math.fsum(plus)
    assert minus[0] == pytest.approx(w(1 / 60, 0.69))  # the worst loss: w⁻(1/60)
    assert plus[0] == pytest.approx(w(1 / 60, 0.61))  # the best gain: w⁺(1/60)
    assert plus[59] == pytest.approx(1 - w(59 / 60, 0.61))
    assert tool.tk_value([0.1] + [0.0] * 59) == pytest.approx(
        0.131826 * w(1 / 60, 0.61), rel=1e-5
    )
    assert tool.tk_value([-0.1] + [0.0] * 59) == pytest.approx(
        -2.25 * 0.131826 * w(1 / 60, 0.69), rel=1e-5
    )


def test_tk_60_by_hand_with_ties():
    """30 × −0.1, 20 × 0.05 and 10 × 0.2: the tied losses take w⁻(30/60) in
    all, the best 10 gains w⁺(10/60), the next 20 w⁺(30/60) − w⁺(10/60):
    −2.25 × 0.131826 × 0.453988 + 0.242609 × 0.238761 + 0.071630 ×
    (0.420639 − 0.238761) = −0.063702; any order of the 60."""

    xs = [-0.1] * 30 + [0.05] * 20 + [0.2] * 10
    expected = (
        -2.25 * 0.1**0.88 * w(0.5, 0.69)
        + 0.2**0.88 * w(1 / 6, 0.61)
        + 0.05**0.88 * (w(0.5, 0.61) - w(1 / 6, 0.61))
    )
    assert expected == pytest.approx(-0.063702, abs=1e-6)
    got = tool.tk_value(xs)
    assert got == pytest.approx(expected, rel=1e-12)
    assert tool.tk_value(xs[::-1]) == pytest.approx(got, rel=1e-12)
    assert tool.tk_value(xs[::3] + xs[1::3] + xs[2::3]) == pytest.approx(got, rel=1e-12)
    # distinct values, both sides: each its own weight, by the docs' indices
    distinct = [(k - 37) / 400 + (0.0003 if k % 7 == 0 else 0.0) for k in range(60)]
    assert tool.tk_value(distinct) == pytest.approx(
        tk_by_the_formula(distinct), rel=1e-12
    )


def test_tk_60_zero_is_a_gain_all_zero_all_gains_all_losses():
    """第十九輪實作釋義: x = 0 is on the gains' side; 60 zeros are 0, not
    missing; all gains (m = 0) or all losses (n = 0) only their side."""

    assert tool.tk_value([0.0] * 60) == 0.0
    assert tool.tk_value([-0.0] * 60) == 0.0
    # 59 losses and a zero: the losses' weights from the worst sum to w⁻(59/60)
    xs = [-0.1] * 59 + [0.0]
    assert tool.tk_value(xs) == pytest.approx(-2.25 * 0.1**0.88 * w(59 / 60, 0.69))
    # all gains: the weights sum to w⁺(1) = 1
    assert tool.tk_value([0.02] * 60) == pytest.approx(0.02**0.88)
    assert tool.tk_value([-0.02] * 60) == pytest.approx(-2.25 * 0.02**0.88)
    gains = [k / 1000 for k in range(1, 61)]
    assert tool.tk_value(gains) == pytest.approx(tk_by_the_formula(gains), rel=1e-12)
    losses = [-k / 1000 for k in range(1, 61)]
    assert tool.tk_value(losses) == pytest.approx(tk_by_the_formula(losses), rel=1e-12)


def d1_context(stocks: dict[int, dict[int, float]], index: list[float | None], **kw):
    """Each stock's bars on the sessions given (session -> close)."""

    sessions = weekdays(date(2016, 1, 4), len(index))
    items = []
    for i, closes in stocks.items():
        at = sorted(closes)
        items.append(
            make_item([closes[s] for s in at], instrument_id=i,
                      dates=[sessions[s] for s in at], sessions=at, **kw)
        )  # fmt: skip
    closes = {day: close for day, close in zip(sessions, index) if close is not None}
    return context_for(items, sessions, index=closes), items


def tk(stock: dict[int, float], index: list[float | None], **kw):
    ctx, (item,) = d1_context({1: stock}, index, **kw)
    return tool.tk_60(ctx, item, len(item.dates) - 1)


SAMPLES = list(range(0, 1201, 20))


def sampled(values: list[float], fill: float = 7.0) -> dict[int, float]:
    """Closes on the 61 sampling sessions of T = 1200, ``fill`` between."""

    out = {s: fill for s in range(1201)}
    out.update(dict(zip(SAMPLES, values)))
    return out


def test_tk_60_on_a_series_by_hand():
    """D1 第 1、2 點: only the 61 closes T − 1200, …, T are read; the excess
    is the stock's return less the TAIEX's on the same days."""

    # the TAIEX 1 % a segment, the stock 3 %: x = 0.0203 − 0.01 … all gains
    index = [1000.0] * 1201
    for k, s in enumerate(SAMPLES):
        index[s] = 1000.0 * 1.01**k
    closes = [10.0 * 1.03**k for k in range(61)]
    got = tk(sampled(closes), index)
    assert got.reason is None
    assert got.value == pytest.approx((0.03 - 0.01) ** 0.88, rel=1e-9)
    # alternating: +10 %, −5 % against a flat TAIEX, 30 of each
    flat = [500.0] * 1201
    alternating = [10.0]
    for k in range(60):
        alternating.append(alternating[-1] * (1.10 if k % 2 == 0 else 0.95))
    xs = [alternating[k] / alternating[k - 1] - 1 for k in range(1, 61)]
    got = tk(sampled(alternating), flat)
    assert got.value == pytest.approx(tk_by_the_formula(xs), rel=1e-9)
    # the closes between the sampling days are not read
    other = tk(sampled(alternating, fill=NAN), flat)
    assert other.value == pytest.approx(got.value, rel=1e-12)
    # neither the bars before T − 1200
    shifted = {s + 5: c for s, c in sampled(alternating).items()}
    shifted.update({s: 1.0 + s for s in range(5)})
    ctx, (item,) = d1_context({1: shifted}, [9.0] * 5 + flat)
    assert tool.tk_60(ctx, item, len(item.dates) - 1).value == pytest.approx(got.value)


def test_tk_60_is_missing_on_a_sampling_day_only():
    """D1 第 4 點, 第十九輪實作釋義「D1 的取樣」: a sampling day without the
    bar, a close missing or ≤ 0, a TAIEX close missing or ≤ 0 or before the
    copy is missing; a suspended bar with a close counts; a gap or a bad
    close between the sampling days does not matter."""

    flat = [500.0] * 1201
    closes = [10.0 + (k % 3) for k in range(61)]
    full = sampled(closes)
    good = tk(full, flat)
    assert good.reason is None and good.value is not None
    for s in (0, 600, 1180):
        gap = {k: c for k, c in full.items() if k != s}
        assert tk(gap, flat).reason == "bar", s
        for bad in (0.0, -1.0, NAN):
            assert tk({**full, s: bad}, flat).reason == "price", (s, bad)
        for bad in (None, 0.0, -5.0):
            index = list(flat)
            index[s] = bad
            assert tk(full, index).reason == "index", (s, bad)
    # the TAIEX's own gap between the sampling days does not matter
    index = list(flat)
    index[7] = None
    assert tk(full, index).value == pytest.approx(good.value)
    # T is the 1,200th session: T − 1200 before the copy
    short = {s - 20: c for s, c in full.items() if s >= 20}
    assert tk(short, flat[20:]).reason == "index"
    # bars and closes between the sampling days: no matter
    between = {k: c for k, c in full.items() if k in SAMPLES or k % 3}
    assert tk(between, flat).value == pytest.approx(good.value)
    assert tk({**full, 601: NAN, 602: 0.0}, flat).value == pytest.approx(good.value)
    # a suspended bar with a close on a sampling day counts (W2's 數法)
    ctx, (item,) = d1_context({1: full}, flat)
    sus = make_item([full[s] for s in sorted(full)], instrument_id=1,
                    dates=item.dates, sessions=sorted(full), suspended=(600, 1180))  # fmt: skip
    ctx = context_for([sus], ctx.panel.sessions, index=ctx.panel.index_close)
    assert tool.tk_60(ctx, sus, 1200).value == pytest.approx(good.value)
    # the reasons in order: the TAIEX before the stock's bar and close
    index = list(flat)
    index[20] = None
    gap = {k: c for k, c in full.items() if k != 40}
    assert tk({**gap, 60: 0.0}, index).reason == "index"
    assert tk({**gap, 60: 0.0}, flat).reason == "bar"


def test_the_market_part_is_once_per_t_and_shared():
    index = [1000.0 + (s % 9) for s in range(1201)]
    full = sampled([10.0 + (k % 4) for k in range(61)])
    ctx, items = d1_context({1: full, 2: {s: c * 2 for s, c in full.items()}}, index)
    a = tool.tk_60(ctx, items[0], 1200)
    b = tool.tk_60(ctx, items[1], 1200)
    assert a.value == pytest.approx(b.value) and list(ctx.markets) == [1200]
    market = ctx.markets[1200]
    assert market.samples == tuple(SAMPLES) and len(market.m) == 60
    assert market.m[0] == pytest.approx(index[20] / index[0] - 1)


def test_d1_rotates_60_accounts_and_the_population_too(monkeypatch):
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    monkeypatch.setattr(pr, "simulate", simulate)
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]})
    tool.engines(SimpleNamespace(quote=None), "D1", planned, 1, 5)
    assert calls == [({1: [1]}, 60, 20), ({1: [1, 2]}, 60, None)]


def test_d1_k60_accounts_by_hand():
    prices = {(i, s): (10.0, 10.0) for i in (1, 2) for s in range(1, 70)}
    mine, population = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "D1",
        SimpleNamespace(picks={1: [1], 2: [2]}, population={1: [1, 2], 2: [1, 2]}), 1, 69,
    )  # fmt: skip
    first, second = mine.positions[:2]
    assert (first.bought, first.due, second.bought, second.due) == (1, 60, 2, 61)
    assert first.cost == pytest.approx(1 / 60 / 20) == second.cost
    assert first.account != second.account
    assert population.positions[0].cost == pytest.approx(1 / 60 / 2)


def test_d1_plan_ranks_small_first_overlaps_and_lists_the_means(monkeypatch):
    """D1 第 5、7 點: small first, the missing last; Z2's, W2's and V1's
    lists on the same T; the list's mean skew_240, vol_60 and
    reversal_720_240; a day the TAIEX is missing counted."""

    sessions = weekdays(date(2016, 1, 4), 30)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 26)}
    monkeypatch.setattr(
        lib, "universe",
        lambda panel, day, lots: [(items[i], sessions.index(day)) for i in items],
    )  # fmt: skip
    values = {i: (None if i <= 3 else float(i % 5) - 2.0) for i in items}
    index_day = 2  # the signal session the TAIEX is missing on

    def market(ctx, s):
        return "index" if s == index_day else SimpleNamespace()

    def fake(ctx, item, at):
        if at == index_day:
            return tool.Tk(None, "index")
        value = values[item.instrument_id]
        return tool.Tk(value, None if value is not None else "bar")

    monkeypatch.setattr(tool, "tk_market", market)
    monkeypatch.setattr(tool, "tk_60", fake)
    lists = {"z2": {5, 10, 1}, "w2": set(), "v1": set(items)}
    for key, names in lists.items():
        monkeypatch.setattr(
            tool, f"{key}_names", lambda ctx, day, members, names=names: names
        )
    skews = {i: (None if i == 5 else i / 100) for i in items}
    monkeypatch.setattr(r8, "skew_240", lambda ctx, item, at: skews[item.instrument_id])
    monkeypatch.setattr(r5, "vol_60", lambda ctx, item, at: 0.02)
    monkeypatch.setattr(
        r6, "reversal_720_240", lambda ctx, item, at: item.instrument_id / 10
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          z=None, v1=None, w2=None)  # fmt: skip
    planned = tool.plan_d1(ctx, tool.HYPOTHESES["D1"], 1, 3)
    day = sessions[0]
    order = sorted(
        items, key=lambda i: (values[i] is None, values[i] or 0, pr.tie_break(day, i))
    )
    assert planned.picks[1] == order[:20]
    assert {1, 2, 3} & set(order[:20]) == set()
    chosen = order[:20]
    assert planned.overlap["D1_Z2"]["2016"][0] == pytest.approx(
        len({5, 10} & set(chosen)) / 20
    )
    assert planned.overlap["D1_W2"] == {}  # W2 has no list: not counted
    assert planned.overlap["D1_V1"]["2016"] == [1.0, 1.0, 1.0]
    expected = statistics.fmean(skews[i] for i in chosen if skews[i] is not None)
    assert planned.means["skew_240"]["2016"][0] == pytest.approx(expected)
    assert planned.means["vol_60"]["2016"] == [pytest.approx(0.02)] * 3
    assert planned.means["reversal_720_240"]["2016"][0] == pytest.approx(
        statistics.fmean(i / 10 for i in chosen)
    )
    year = planned.coverage["2016"]
    assert (year["index_days"], year["empty_days"], year["days"]) == (1, 1, 3)
    missing = year["missing"]
    assert (year["valued"], missing["tk_60"], missing["bar"], missing["index"]) == (
        44, 31, 6, 25,
    )  # fmt: skip
    assert planned.rows[0]["tk_60"] == -2.0 and planned.rows[0]["vol_60"] == 0.02
    assert set(planned.rows[0]) >= set(tool.PICK_FIELDS["D1"])


def test_the_overlaps_lists_are_the_other_tools_own(monkeypatch):
    """Z2, W2 and V1 through their own tools' ``rank`` on the contexts built
    on the same base, the first 20; X4, K2 and P2 through
    ``round14_research.x4_names``, ``round15_research.k2_names`` and
    ``round16_research.p2_names`` on this context (its ``p2`` is
    ``round15_research``'s)."""

    ctx = context_for([make_item([10.0], instrument_id=i) for i in range(1, 4)])
    assert ctx.z.base is ctx.base is ctx.w2.base is ctx.v1.base is ctx.p2.base
    assert isinstance(ctx.p2, r15.Context) and ctx.p2.z4 is ctx.z
    day = date(2016, 3, 1)
    rows = [(i, {}, "") for i in range(30, 0, -1)]
    calls = []

    def ranker(name):
        def rank(c, spec, d, members):
            calls.append((name, c, spec, d))
            return SimpleNamespace(rows=rows)

        return rank

    for module in (r8, r6, r5):
        monkeypatch.setattr(module, "rank", ranker(module.__name__))
    top = set(range(30, 10, -1))
    assert tool.z2_names(ctx, day, []) == top
    assert tool.w2_names(ctx, day, []) == top
    assert tool.v1_names(ctx, day, []) == top
    assert calls == [
        ("round8_research", ctx.z, r8.HYPOTHESES["Z2"], day),
        ("round6_research", ctx.w2, r6.HYPOTHESES["W2"], day),
        ("round5_research", ctx.v1, r5.HYPOTHESES["V1"], day),
    ]
    assert {"z2_order", "w2_order", "v1_order"} <= set(ctx.seconds)
    seen = []
    monkeypatch.setattr(r14, "x4_names", lambda c, d, m: seen.append(("x4", c)) or {1})
    monkeypatch.setattr(
        r15, "k2_names", lambda c, d, m, q: seen.append(("k2", c)) or {2}
    )
    monkeypatch.setattr(
        r16, "p2_names", lambda c, d, m, q: seen.append(("p2", c)) or {3}
    )
    q = date(2015, 12, 31)
    assert tool.x4_names(ctx, day, []) == {1}
    assert tool.k2_names(ctx, day, [], q) == {2}
    assert tool.p2_names(ctx, day, [], q) == {3}
    assert seen == [("x4", ctx), ("k2", ctx), ("p2", ctx)]


# --- D2: eps_streak_4 -------------------------------------------------------------

ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731
DUES = lambda y: [date(y, 5, 15), date(y, 8, 14), date(y, 11, 14), date(y + 1, 3, 31)]  # noqa: E731
# single quarters in multiples of 0.25 (exact): 2015 0.5, 1.0, 1.5, 2.0;
# 2016 0.75, 1.25, 1.75, 2.25; 2017 Q1 1.0
SINGLES = {
    2015: [0.5, 1.0, 1.5, 2.0],
    2016: [0.75, 1.25, 1.75, 2.25],
    2017: [1.0],
}


def quarters_of(singles: dict[int, list[float]], shift=0.0, drop=(), late=()):
    """(announcement_date, period_end, cumulative EPS) rows, announced on
    the deadline (a day later for the ends in ``late``)."""

    rows = []
    for year, values in singles.items():
        total = 0.0
        for end, due, value in zip(ENDS(year), DUES(year), values):
            total += value + shift
            if end in drop:
                continue
            rows.append((due + timedelta(days=1) if end in late else due, end, total))
    return rows


def streak(quarters, day=date(2017, 5, 15), quarter=date(2017, 3, 31)):
    item = make_item([10.0], dates=[day], quarters=quarters)
    return tool.eps_streak_4(item, 0, quarter)


def test_the_single_quarters_by_hand():
    """共同 單季值: Q1 the cumulative, Q2 and Q3 less the quarter before's
    cumulative, Q4 (the annual report) less Q3's; e(q) … e(q − 7)."""

    got = streak(quarters_of(SINGLES))
    # q = 2017Q1 (cumulative 1.0), 2016Q4 = 6.0 − 3.75, Q3 = 3.75 − 2.0,
    # Q2 = 2.0 − 0.75, Q1 = 0.75, 2015Q4 = 5.0 − 3.0, Q3 = 3.0 − 1.5, Q2 = 1.5 − 0.5
    assert got.singles == (1.0, 2.25, 1.75, 1.25, 0.75, 2.0, 1.5, 1.0)
    assert got.qualifies and got.reason is None


def test_eps_streak_4_needs_four_strict_year_on_year_rises():
    """D2 第 3 點: e(q − k) > e(q − k − 4), k = 0 … 3; an equal pair fails;
    the sign does not matter."""

    assert streak(quarters_of(SINGLES)).qualifies
    for year, k in ((2017, 0), (2016, 3), (2016, 2), (2016, 1)):
        singles = {y: list(vs) for y, vs in SINGLES.items()}
        before = singles[year - 1][k] if year == 2016 else singles[2016][0]
        singles[year][k] = before  # e(q − j) = e(q − j − 4)
        got = streak(quarters_of(singles))
        assert not got.qualifies and got.reason is None, (year, k)
    # every quarter 10 lower: losses all along, still rising
    negative = streak(quarters_of(SINGLES, shift=-10.0))
    assert negative.qualifies and all(value < 0 for value in negative.singles)
    falling = {y: [-x for x in vs] for y, vs in SINGLES.items()}
    assert not streak(quarters_of(falling)).qualifies


def test_eps_streak_4_is_missing_stale_or_a_quarter_short():
    """D2 第 4 點, 第十九輪實作釋義「D2 的最新一季」: q's row with a null EPS
    (not in the rows K2 reads: the latest is q − 1), a row announced after
    T, a quarter of q … q − 7 missing, the quarter before in the same year
    missing (2015Q1 for 2015Q2's single) each fail."""

    q = date(2017, 3, 31)
    assert streak(quarters_of(SINGLES, drop=(q,))).reason == "stale"
    assert streak(quarters_of(SINGLES, late=(q,))).reason == "stale"
    assert streak([]).reason == "stale"
    for end in (date(2016, 6, 30), date(2015, 9, 30), date(2015, 6, 30)):
        assert streak(quarters_of(SINGLES, drop=(end,))).reason == "missing", end
    # 2015Q1 is not one of the 8, but 2015Q2's single needs its cumulative
    assert streak(quarters_of(SINGLES, drop=(date(2015, 3, 31),))).reason == "missing"
    for got in (streak(quarters_of(SINGLES, drop=(q,))),):
        assert not got.qualifies
    # a later announcement of the same quarter replaces the earlier
    rows = quarters_of(SINGLES) + [(date(2017, 5, 10), date(2016, 12, 31), 3.75 + 1.0)]
    assert streak(rows).singles[1] == 1.0 and not streak(rows).qualifies


def test_d2_picks_20_by_the_hash_and_counts_the_events(monkeypatch):
    """D2 第 5、7 點: the qualifying members by the hash, the first 20, not
    ranked; held to the next event day; the counts of each event day and
    the overlaps with X4, K2, P2 on the same T."""

    sessions = weekdays(date(2016, 1, 4), 250)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    statuses = {25: "delisted", 26: "transferred", 27: "delisted", 28: "suspended"}

    def fake(item, at, quarter):
        i = item.instrument_id
        if i in (27, 29):
            return tool.Streak(False, "stale")
        if i == 30:
            return tool.Streak(False, "missing")
        if i in (26, 28):
            return tool.Streak(False, None, (1.0,) * 8)
        return tool.Streak(True, None, tuple(float(i + k) for k in range(8)))

    monkeypatch.setattr(tool, "eps_streak_4", fake)
    others = {"x4": {1, 2, 3, 4}, "k2": set(), "p2": set(range(1, 31))}
    monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: others["x4"])
    for key in ("k2", "p2"):
        monkeypatch.setattr(
            tool, f"{key}_names", lambda ctx, day, m, q, key=key: others[key]
        )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses)  # fmt: skip
    s = [
        sessions.index(d) + 1
        for d in (date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15))
    ]
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_d2(ctx, tool.HYPOTHESES["D2"], s[0], last)
    day = date(2016, 3, 31)
    hits = [i for i in range(1, 26)]
    expected = sorted(hits, key=lambda i: pr.tie_break(day, i))[:20]
    assert planned.picks[s[0]] == expected
    assert planned.population[s[0]] == list(range(1, 31))
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    event = planned.rebalances[0]
    assert (event["hits"], event["names"], event["not"], event["stale"], event["missing"]) == (
        25, 20, 2, 2, 1,
    )  # fmt: skip
    assert (event["delisted"], event["delisted_missing"]) == (3, 1)  # 25, 26, 27; 27
    assert event["quarter"] == "2015-12-31"
    assert event["x4_overlap"] == pytest.approx(len({1, 2, 3, 4} & set(expected)) / 20)
    assert event["k2_overlap"] is None and event["p2_overlap"] == 1.0
    assert planned.overlap["D2_K2"] == {} and planned.overlap["D2_P2"] == {
        "2016": [1.0] * 3
    }
    year = planned.coverage["2016"]
    assert (year["hits"], year["delisted"], year["delisted_missing"]) == (75, 9, 3)
    assert [e["signal_date"] for e in year["events"]] == [
        "2016-03-31",
        "2016-05-16",
        "2016-08-15",
    ]
    assert planned.rows[0]["quarter"] == "2015-12-31"
    assert set(planned.rows[0]) >= set(tool.PICK_FIELDS["D2"])
    # fewer than 20: what qualifies, the rest of the cash kept
    few = {i for i in range(1, 6)}
    monkeypatch.setattr(
        tool, "eps_streak_4",
        lambda item, at, q: tool.Streak(item.instrument_id in few, None, (0.0,) * 8),
    )  # fmt: skip
    planned = tool.plan_d2(ctx, tool.HYPOTHESES["D2"], s[0], last)
    assert sorted(planned.picks[s[0]]) == sorted(few)


def test_the_event_account_sells_at_the_next_event_days_close():
    """「K2 的賣出時點」(D2): T′'s close, the new list at T′+1; fewer than 20
    cash; T′ suspended or locked: sold at the next open, its cash in that
    day's buys; the population 1/n of the cash."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              dues={1: 3, 4: 8})  # fmt: skip
    mine, population = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "D2", planned, 1, 7
    )
    first, second = mine.positions
    assert (first.sold, first.how, second.bought) == (3, "close", 4)
    assert first.cost == pytest.approx(0.05)  # 1/20 of the cash, 19/20 in cash
    assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    assert population.positions[0].cost == pytest.approx(0.5)
    quote = quote_of(prices)
    for case in ("suspended", "locked"):

        def on(instrument_id, s, case=case):
            if case == "suspended" and (instrument_id, s) == (1, 3):
                return pr.Quote(10.0, 13.0, False)
            if case == "locked" and (instrument_id, s) == (1, 3):
                return pr.Quote(10.0, 13.0, True, locked_down=True)
            return quote(instrument_id, s)

        mine = tool.engines(SimpleNamespace(quote=on), "D2", planned, 1, 7)[0]
        first, second = mine.positions
        assert (first.sold, first.how) == (4, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        # the delayed sale's cash is in T′+1's buys: 1/20 of all of it
        assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    # T+1 not tradable (suspended, no bar): skipped, not filled
    gone = {k: v for k, v in prices.items() if k != (1, 1)}
    mine = tool.engines(SimpleNamespace(quote=quote_of(gone)), "D2", planned, 1, 7)[0]
    assert [p.instrument_id for p in mine.positions] == [2]
    assert mine.counts["not_tradable"] == 1


def test_invested_shares_and_a_delayed_sale_by_hand(monkeypatch):
    """D2 第 7 點 (#979 review 7087182701): each rebalance's invested share
    at its T+1 close; the first list's sale on T′ suspended goes at T′+1's
    open, its cash in T′+1's buys."""

    sessions = weekdays(date(2016, 3, 28), 6)
    prices = {
        (1, s): (10.0, (11.0, 12.0, 12.0, 13.0, 13.0)[s - 1]) for s in range(1, 6)
    }
    prices.update({(2, s): (10.0, 10.0) for s in range(1, 6)})
    first, last = 1, 5
    events = [{"signal_date": sessions[0].isoformat(), "names": 1, "hits": 1},
              {"signal_date": sessions[2].isoformat(), "names": 1, "hits": 1}]  # fmt: skip
    plan = tool.Plan(picks={1: [1], 3: [1]}, population={1: [1, 2], 3: [1, 2]},
                     dues={1: 2, 3: 6}, rebalances=events)  # fmt: skip
    quote = quote_of(prices)

    def on(instrument_id, s):
        if (instrument_id, s) == (1, 2):  # T′ = session 2: suspended, no sale
            return pr.Quote(10.0, 12.0, False)
        return quote(instrument_id, s)

    monkeypatch.setattr(tool, "segment_window", lambda *a: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_d2", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=on)  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "D2", "exploration")
    units1 = pr.buy_units(0.05, 10.0)
    cash1 = 0.95
    eq1 = cash1 + units1 * 11.0
    # session 2 suspended: marked at the last close (11), held
    eq2 = cash1 + units1 * 11.0
    # session 3: sold at the open (10), then 1/20 of all the cash bought
    cash3 = cash1 + pr.sale_proceeds(units1, 10.0)
    units2 = pr.buy_units(cash3 / 20, 10.0)
    cash3 -= cash3 / 20
    eq3 = cash3 + units2 * 12.0
    assert result["rebalances"][0]["invested"] == pytest.approx(units1 * 11 / eq1)
    assert result["rebalances"][1]["invested"] == pytest.approx(units2 * 12 / eq3)
    mine = [eq1, eq2, eq3, cash3 + units2 * 13.0, cash3 + units2 * 13.0]
    assert result["_equity"][0] == pytest.approx(mine)
    assert result["counts"]["D2"]["sale_held"] == 1
    row = tool._row(result)
    assert row["names"] == 1 and row["hits"] == 1
    assert result["unsold_share"] == 0.5  # the second due after the segment


def test_the_starts_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2007, 11, 26), 4800)  # to 2026
    first, last = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["D1"])
    assert sessions[first - 1] == weekdays(OTC, 1201)[-1]
    assert sessions[first - 1 - 1200] == OTC
    assert sessions[last] == date(2019, 12, 31)
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["D2"])
    assert sessions[first - 1] == date(2015, 3, 31)  # 2014's annual report
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["D2"])
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["D1"])
    assert sessions[first] == date(2020, 1, 2)
    # a deadline on a Saturday make-up session goes to the next Monday
    saturday = date(2018, 3, 31)
    days = sorted({*weekdays(date(2018, 3, 1), 30), saturday})
    events = dict((days[at], q) for at, q in r14.quarter_events(days))
    assert saturday not in events and events[date(2018, 4, 2)] == date(2017, 12, 31)


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
        (3.368, "前瞻觀察"),  # round 18's threshold is not this round's
        (3.375, "前瞻觀察"),
        (3.376, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_376(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 1500
STOCKS = range(1, 25)
DELISTED = {25: 1250, 26: 1380}  # the last bar's index; 26 has no EPS at all
TRANSFERRED = 27  # EPS to 2015 only
INDEX_ID = 90
STALE = 7  # every row announced a day after the deadline
GAP = 10  # no row for 2016Q2
NO_BAR = (13, 600)  # no bar on session 600, a sampling day of T = 1200, 1220, …
FIRST_DAY = date(2015, 1, 5)


def trading_days() -> list[date]:
    return weekdays(FIRST_DAY, SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def index_level(t: int) -> float:
    return 9000.0 * (1 + 0.004 * math.sin(t * 0.7)) + 5 * t


def path(i: int) -> list[tuple[float, float, float, float]]:
    out, previous = [], 50.0 + i
    for t in range(SESSIONS):
        m = index_level(t) / index_level(t - 1) - 1 if t else 0.0
        drift = (i - 12) * 0.0002 + 0.7 * m
        close = round(previous * (1 + drift + 0.002 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


def single_eps(i: int, year: int, q: int) -> float:
    """Rising a quarter a year (0.25) unless i is a multiple of 3 (flat:
    every pair equal, never qualifies); multiples of 0.25, exact."""

    growth = 0.0 if i % 3 == 0 else 0.25
    return (i % 4) - 1.5 + growth * (year - 2013) + 0.25 * q


def fundamental_rows() -> list[dict]:
    rows = []
    for i in (*STOCKS, 25, TRANSFERRED):
        for year in range(2013, 2021):
            if i == TRANSFERRED and year > 2015:
                break
            total = 0.0
            for q, (end, due) in enumerate(zip(ENDS(year), DUES(year)), 1):
                total += single_eps(i, year, q)
                if i == GAP and end == date(2016, 6, 30):
                    continue
                announced = due + timedelta(days=1) if i == STALE else due
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": announced, "eps": total, "data_json": {},
                             "source": "test"})  # fmt: skip
    return rows


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
        bars = []
        for i in ids:
            prices = path(i)
            for t, day in enumerate(days):
                if t > DELISTED.get(i, SESSIONS):
                    break
                if (i, t) == NO_BAR:
                    continue
                open_, high, low, close = prices[t]
                volume = 2_000_000 + 10_000 * i + 5_000 * (t % 7)
                bars.append(
                    {"instrument_id": i, "trading_date": day, "open": open_, "high": high,
                     "low": low, "close": close, "adj_close": close, "volume": volume,
                     "turnover": close * volume, "turnover_status": "available",
                     "source": "test", "is_suspended": False}
                )  # fmt: skip
        for t, day in enumerate(days):
            level = round(index_level(t), 2)
            bars.append(
                {"instrument_id": INDEX_ID, "trading_date": day, "open": level,
                 "high": level, "low": level, "close": level, "adj_close": level,
                 "volume": 0, "turnover": 0.0, "turnover_status": "unknown",
                 "source": "twse_index", "is_suspended": False}
            )  # fmt: skip
        db.execute(insert(MarketBar), bars)
        db.execute(insert(FundamentalSnapshot), fundamental_rows())
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round19") / "stock.db")


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
    return one_process(lambda: tool.load(fixture_db, date(1990, 1, 1), days[1299], raw))


def test_one_panel_serves_the_overlaps(loaded):
    for part in (loaded.z, loaded.w2, loaded.v1, loaded.p2):
        assert part.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "statuses", "lists"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    assert loaded.p2.statements[1] and loaded.p2.statements is loaded.p2_statements
    end = trading_days()[1299]
    assert all(d <= end for item in loaded.panel.series.values() for d in item.dates)
    assert all(
        a <= end for item in loaded.panel.series.values() for a, _e, _v in item.quarters
    )


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    series = loaded.panel.series
    day, quarter = date(2017, 5, 15), date(2017, 3, 31)
    for i in (1, 2, 4, 5):
        item = series[i]
        got = tool.eps_streak_4(item, item.position[day], quarter)
        assert got.qualifies, i
        assert got.singles[0] == single_eps(i, 2017, 1)
        assert got.singles[1] == single_eps(i, 2016, 4)
    for i, reason in ((3, None), (STALE, "stale"), (GAP, "missing"), (26, "stale"),
                      (TRANSFERRED, "stale")):  # fmt: skip
        item = series[i]
        got = tool.eps_streak_4(item, item.position[day], quarter)
        assert (got.qualifies, got.reason) == (False, reason), i
    at = 1200
    got = tool.tk_60(loaded, series[1], series[1].position[days[at]])
    assert got.reason is None and got.value is not None
    item = series[NO_BAR[0]]
    assert tool.tk_60(loaded, item, item.position[days[1200]]).reason == "bar"
    assert tool.tk_60(loaded, item, item.position[days[1201]]).reason is None
    # T − 1200 before the copy's first session
    assert tool.tk_60(loaded, series[1], 1199).reason == "index"


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[1299]),
            # D2's 2020-03-31 and 2020-05-15 events
            "validation": (days[1300], days[1400]),
            "used": (days[1401], days[1499]),
        },
    )
    floors = {"exploration": 30, "validation": 10}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
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


def explore(db: Path, out: Path, *extra: str, hypotheses: str | None = "D1,D2") -> int:
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
        "round19_research", "1047", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (19, 2, 68)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.376)
    assert report["read_until"] == days[1299].isoformat()
    hyp = report["hypotheses"]
    assert [hyp[n]["engine"] for n in NAMES] == ["portfolio", "events"]
    d1, d2 = hyp["D1"], hyp["D2"]
    for key in ("overlap_z2", "overlap_w2", "overlap_v1", "mean_skew_240", "mean_vol_60",
                "mean_reversal_720_240"):  # fmt: skip
        assert d1[key]["days"] > 0, key
    assert d2["names"] > 0 and d2["hits"] >= d2["names"]
    assert d2["overlap_p2"]["days"] == d2["overlap_x4"]["days"] == 0  # no lists
    assert "overlap_k2" in d2
    assert d2["invested"] is not None
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 2 個、累計 68 個" in text and "驗證段 t ≥ 3.376" in text
    for key in ("D1_reference", "D2_survivor", "summary_only"):
        assert tool.OVERLAP_NOTE[key] in text, key
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round19_research", 19, "exploration", 1) for name in NAMES]
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
        lines = summary.splitlines()
        assert (
            lines[2] == "- " + tool.OVERLAP_NOTE["summary_only"]
        )  # the report's start
    d1_lines = (out / "D1" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert d1_lines[3] == tool.OVERLAP_NOTE["D1_reference"]
    d1_text = "\n".join(d1_lines)
    for key in ("D1_Z2", "D1_W2", "D1_V1", "D1_listed"):
        assert tool.OVERLAP_NOTE[key] in d1_text, key
    for label in ("skew_240", "vol_60", "reversal_720_240"):
        assert f"## 名單的平均 `{label}`" in d1_text
    d2_lines = (out / "D2" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert d2_lines[3] == tool.OVERLAP_NOTE["D2_survivor"]
    d2_text = "\n".join(d2_lines)
    for key in ("D2_X4", "D2_K2", "D2_P2", "D2_listed"):
        assert tool.OVERLAP_NOTE[key] in d2_text, key
    assert "## 每次調倉（D2 第 7 點" in d2_text
    picks = (out / "D2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == (
        "signal_date,rank,exchange,symbol,quarter,eps_q,eps_q1,eps_q2,eps_q3,"
        "eps_q4,eps_q5,eps_q6,eps_q7,tie"
    )
    on = {line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")}
    qualifying = {f"S{i}" for i in (*STOCKS, 25) if i % 3 and i not in (STALE, GAP)}
    assert on == qualifying  # 15 of them, fewer than 20
    d1_picks = (out / "D1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert d1_picks[0] == (
        "signal_date,rank,exchange,symbol,tk_60,skew_240,vol_60,reversal_720_240,tie"
    )
    assert d1_picks[1].startswith(days[1200].isoformat())


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="D2") == 2
    assert any("D2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="D1,G1") == 2
    assert any("G1 not registered" in line for line in refused(capsys))


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
    data["design"] = "1029"
    data["hypotheses"]["D1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_376(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "D1", "D2")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("D1", "round19_research", "finished"),
                       ("D2", "round19_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["D1", "D2"]
    assert validation["min_t"] == 3.376
    for name in NAMES:
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["reason"] is None, (
            name,
            tables["reason"],
            tables["prerequisites"],
        )
        assert tables["min_t"] == 3.376
    days = trading_days()
    assert validation["read_until"] == days[1400].isoformat()
    d2 = read_json(tmp_path / "validation" / "D2" / "tables.json")
    assert d2["window"]["first_signal"] == "2020-03-31"
    d1 = read_json(tmp_path / "validation" / "D1" / "tables.json")
    assert d1["window"]["first_session"] == days[1300].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.376（沒有 t 下限）" in text
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
    report = passed_report(out, tmp_path, "D1")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[1400]),
        (tool.LOAD_FROM, days[1499]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["D1"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["D1"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "D1" / "used" / file).is_file(), file


def test_a_failed_validation_loads_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    real_load = tool.load
    loads = []
    monkeypatch.setattr(tool, "load", lambda *a: loads.append(a[2]) or real_load(*a))
    monkeypatch.setattr(ex, "explore_judge", lambda *a, **k: ex.FORWARD_WATCH)
    assert (
        validate(db, tmp_path / "validation", passed_report(out, tmp_path, "D2")) == 0
    )
    assert loads == [trading_days()[1400]]
    assert "used" not in read_json(tmp_path / "validation" / "explore.json")


def test_coverage_only_computes_no_return(copied, tmp_path):
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity", "overlap"):
        assert word not in text
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    hyp = body["hypotheses"]
    events = [e for row in hyp["D2"]["coverage"].values() for e in row["events"]]
    assert [e["signal_date"] for e in events][:2] == ["2015-03-31", "2015-05-15"]
    may = next(e for e in events if e["signal_date"] == "2017-05-15")
    # 1..24 less the multiples of 3, STALE and GAP, and 25: 15; the 8 flat;
    # STALE, 26 (no EPS) and 27 (to 2015): stale; GAP: a quarter short
    assert (may["members"], may["hits"], may["not"], may["stale"], may["missing"]) == (
        27, 15, 8, 3, 1,
    )  # fmt: skip
    assert (may["delisted"], may["delisted_missing"]) == (
        3,
        2,
    )  # 25, 26, 27; 25 has EPS
    d1 = hyp["D1"]["coverage"]
    assert list(d1) == ["2019"]
    year = d1["2019"]
    assert year["days"] == 99 and year.get("index_days", 0) == 0
    assert year.get("empty_days", 0) == 0
    # stock 13 lacks session 600: T = 1200, 1220, 1240, 1260, 1280
    assert year["missing"] == {"tk_60": 5, "bar": 5}
    assert year["valued"] == year["members"] - 5
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert {"plan", "tk_60", "z2_order", "w2_order", "v1_order"} <= seconds["D1"]
    assert {"plan", "eps_streak_4", "x4_order", "k2_order", "p2_order"} <= seconds["D2"]
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "statuses", "lists"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md
    assert "最新一季不是對應的那一季" in md and "加權指數缺值的訊號日" in md
    assert "有 `tk_60` 的檔次" in md and "一檔都沒有值的訊號日" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "D1"])  # fmt: skip


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
    assert explore(copied, tmp_path / "out", hypotheses="D1") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "D1")
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
        assert explore(copied, out, hypotheses="D1") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "D1")
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
