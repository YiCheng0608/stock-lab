"""tools/research/round18_research.py: the registered G1, G2 (#1029).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十八輪：G1、G2.  The features and the accounts are
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
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1029#issuecomment-1"
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
r8 = _tool("round8_research")
r10 = _tool("round10_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
r16 = _tool("round16_research")
r17 = _tool("round17_research")
tool = _tool("round18_research")
NAMES = ("G1", "G2")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 18))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    g1, g2 = (h[name] for name in NAMES)
    assert (g1["engine"], g2["engine"]) == ("events", "portfolio")
    assert g1["keys"] == (("nonop_q", "low"),)
    assert (g1["top"], g1["hold"], g1["start"], g1["rule"]) == (
        20, "next_event", ("date", date(2013, 5, 15)), "quarterly",
    )  # fmt: skip
    assert g2["keys"] == (("coskew_240", "low"),)
    assert (g2["top"], g2["hold"], g2["start"], g2["rule"]) == (
        20, 60, ("session", OTC, 241), "daily",
    )  # fmt: skip
    for spec in h.values():
        assert spec["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        18,
        2,
        66,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.368
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(66), 3) == 3.368
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "c985ca64" and tool.DESIGN == "1029"
    assert (tool.NONOP, tool.REVENUE, tool.REPORT_FORMAT) == (
        "營業外收入及支出", "營業收入", "general",
    )  # fmt: skip
    assert tool.REVENUE_MIN == 0.0
    assert (tool.COSKEW_SESSIONS, tool.COSKEW_DAYS) == (241, 240)
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool._known is r15._known
    assert tool.single_quarter is r15.single_quarter
    assert tool.SINGLE_QUARTER == r15.SINGLE_QUARTER
    assert "load_context" in tool.load.__code__.co_names
    assert {
        "load_statuses", "load_nonop_statements", "load_statements",
        "load_tax_statements", "load_share_statements", "load_stock_dividends",
    } <= set(tool.load.__code__.co_names)  # fmt: skip
    assert "quarter_events" in tool.plan_g1.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "_rows" in tool.load_nonop_statements.__code__.co_names
    assert {"closes_of", "_suspended_in"} <= set(tool.coskew_240.__code__.co_names)
    assert "r16.p2_names(" in inspect.getsource(tool.p2_names)
    assert "r16.tax_mom(" in inspect.getsource(tool.n2_names)
    assert "r17.net_issue(" in inspect.getsource(tool.a1_names)
    assert "x4_names" in tool.x4_names.__code__.co_names
    assert "r8.rank(" in inspect.getsource(tool.z_names)
    for plan in (tool.plan_g1, tool.plan_g2):
        assert "r5.order_key(" in inspect.getsource(plan)
    source = inspect.getsource(tool.plan_g2)
    assert "r8.skew_240(" in source and "r8.beta_240(" in source


def _swap(spec_name: str, key: str, value):
    return {**tool.HYPOTHESES, spec_name: {**tool.HYPOTHESES[spec_name], key: value}}


def _other(module, name: str, key: str, value):
    return {**module.HYPOTHESES, name: {**module.HYPOTHESES[name], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1029 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.368
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.359),
        # G1: the two fields, general, the latest quarter, the single
        # quarters (Q1 cumulative, Q2～Q4 less the quarter before), rev ≤ 0
        # missing, nonop 0 not missing, small first, N 20, the next event,
        # the reference
        (tool, "NONOP", "營業外損益"),
        (tool, "REVENUE", "淨收益"),
        (tool, "FIELDS", ("revenue", "nonop")),
        (tool, "REPORT_FORMAT", "holding"),
        (tool, "LATEST_RULE", "the latest quarter with an EPS"),
        (tool, "NEEDED_RULE", "q only"),
        (tool, "SINGLE_QUARTER", "the cumulative figures"),
        (features, "VERSION", features.VERSION + 1),
        (tool, "REVENUE_MIN", -1.0),
        (tool, "NONOP_Q", "nonop(q) / rev(q); nonop(q) 0: missing"),
        (tool, "NUMBER_RULE", "float()"),
        (tool, "STATEMENT_RULE", "the rows with an EPS"),
        (tool, "G1_REFERENCE", "less every delisted instrument"),
        (tool, "HYPOTHESES", _swap("G1", "keys", (("nonop_q", "high"),))),
        (tool, "HYPOTHESES", _swap("G1", "top", 19)),
        (tool, "HYPOTHESES", _swap("G1", "hold", 60)),
        (tool, "HYPOTHESES", _swap("G1", "start", ("date", date(2014, 5, 15)))),
        # G2: 241 sampling days, the regression with an intercept and no
        # lag, the standardisation (the means over 240), the missing cases,
        # the market part, small first, N 20, K 60
        (tool, "COSKEW_SESSIONS", 242),
        (tool, "COSKEW_DAYS", 239),
        (tool, "REGRESSION", "r_j = b m_j, no intercept"),
        (tool, "REGRESSION", "r_j = a + b0 m_j + b1 m_{j-1}"),
        (tool, "COSKEW_RULE", "each mean over 239 days"),
        (tool, "COSKEW_SAMPLE", "the item's own last 241 bars"),
        (tool, "COSKEW_MISSING", "a suspended bar is skipped"),
        (tool, "COSKEW_MISSING", "sum d_j^2 near 0: missing"),
        (tool, "MARKET_RULE", "by stock"),
        (tool, "HYPOTHESES", _swap("G2", "keys", (("coskew_240", "high"),))),
        (tool, "HYPOTHESES", _swap("G2", "top", 19)),
        (tool, "HYPOTHESES", _swap("G2", "hold", 20)),
        (tool, "HYPOTHESES", _swap("G2", "start", ("session", OTC, 242))),
        # the two: the hash and the order, the start, the event days
        (tool, "ORDER", "high first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "SALE", "at T'+1's open"),
        (tool, "REFERENCE_STATUSES", ("delisted",)),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        # the overlaps' lists
        (r15, "HYPOTHESES", _other(r15, "P2", "top", 19)),
        (r16, "HYPOTHESES", _other(r16, "N2", "top", 19)),
        (r17, "HYPOTHESES", _other(r17, "A1", "top", 19)),
        (r17, "EPS_MIN", 0.4),
        (ex, "HYPOTHESES", _other(ex, "X4", "top", 19)),
        (r8, "HYPOTHESES", _other(r8, "Z2", "top", 19)),
        (r8, "HYPOTHESES", _other(r8, "Z3", "top", 19)),
        (r8, "SKEW_RETURNS", 239),
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


# AC-1: measured on master c985ca64 (43ed1339) before this tool existed.
# forward_watch's F2 row reads round10_research's hash, its P2 row
# round15_research's and its A1 row round17_research's; the overlaps read
# round15 (P2), round16 (N2), round17 (A1), explore_research (X4) and round8
# (Z2, Z3).
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
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round8_research", "round10_research", "round15_research", "round16_research",
     "round17_research", None],
)  # fmt: skip
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


# AC-1: portfolio_research.ranking_key's source on master c985ca64
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
    section = text.split("**第十八輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.368 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round18_research.py" in section
    assert "本輪 2 個、累計 66 個" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(
    closes, opens=None, suspended=(), instrument_id=1, dates=None, sessions=None
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
    return item


def context_for(items=(), sessions=None, statements=None, statuses=None, index=None):
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
    return tool.Context(base, statements or {}, statuses or {})


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


# --- G1: nonop_q ------------------------------------------------------------------

ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731
DUES = lambda y: [date(y, 5, 15), date(y, 8, 14), date(y, 11, 14), date(y + 1, 3, 31)]  # noqa: E731


def nonop_rows(year, nonop, revenue, fmt="general"):
    """One year's rows from the cumulative figures, as the source writes them."""

    return [
        tool.NonopStatement(due, end, fmt, n, r)
        for end, due, n, r in zip(ENDS(year), DUES(year), nonop, revenue)
    ]


# 2017's cumulative figures: single quarters nonop −50, 30, 0, −20 and
# revenue 1,000, 1,200, 800, 1,000
YEAR = nonop_rows(2017, [-50.0, -20.0, -20.0, -40.0], [1000.0, 2200.0, 3000.0, 4000.0])
CASES = {  # deadline, quarter, nonop(q), rev(q)
    "Q1": (date(2017, 5, 15), date(2017, 3, 31), -50.0, 1000.0),
    "Q2": (date(2017, 8, 14), date(2017, 6, 30), 30.0, 1200.0),
    "Q3": (date(2017, 11, 14), date(2017, 9, 30), 0.0, 800.0),
    "Q4": (date(2018, 3, 31), date(2017, 12, 31), -20.0, 1000.0),
}


def nonop(rows, day, quarter):
    ctx = context_for(statements={1: rows})
    return tool.nonop_q(ctx, make_item([10.0]), day, quarter)


@pytest.mark.parametrize("case", sorted(CASES))
def test_nonop_q_by_hand(case):
    """G1 第 2、4 點: Q1 the cumulative figure, Q2 and Q3 less the same
    year's quarter before, Q4 (the annual report) less Q3's; negative,
    positive and 0 alike by value."""

    day, quarter, expected_nonop, expected_revenue = CASES[case]
    got = nonop(YEAR, day, quarter)
    assert got.reason is None
    assert (got.nonop, got.revenue) == (expected_nonop, expected_revenue)
    assert got.value == expected_nonop / expected_revenue
    if case == "Q3":
        assert got.value == 0.0  # 0 is a value, not missing
    # the year before is not read
    previous = nonop_rows(2016, [999.0, 1.0, 5.0, 7.0], [1.0, 2.0, 3.0, 4.0])
    assert nonop([*previous, *YEAR], day, quarter) == got


def test_nonop_q_is_missing_stale_format_fields_or_revenue():
    rows = YEAR
    day, quarter = CASES["Q2"][:2]
    assert nonop(rows, day, quarter).value == 0.025
    late = [r if r.period_end != quarter else replace(r, announced=day + timedelta(days=1))
            for r in rows]  # fmt: skip
    assert nonop(late, day, quarter).reason == "stale"  # q not known on T
    assert nonop([], day, quarter).reason == "stale"
    # the latest known is not the deadline's quarter (Q3 announced early)
    early = [r if r.period_end != date(2017, 9, 30) else replace(r, announced=day)
             for r in rows]  # fmt: skip
    assert nonop(early, day, quarter).reason == "stale"
    for end in (quarter, date(2017, 3, 31)):
        other = [r if r.period_end != end else replace(r, report_format="holding")
                 for r in rows]  # fmt: skip
        assert nonop(other, day, quarter).reason == "format", end
        for name in ("nonop", "revenue"):
            gone = [
                r if r.period_end != end else replace(r, **{name: None}) for r in rows
            ]
            assert nonop(gone, day, quarter).reason == "fields", (end, name)
        blank = [r if r.period_end != end else replace(r, report_format=None)
                 for r in rows]  # fmt: skip
        assert nonop(blank, day, quarter).reason == "fields", end
    # the same year's quarter before not known: no single quarter
    assert nonop([r for r in rows if r.period_end != date(2017, 3, 31)], day,
                 quarter).reason == "fields"  # fmt: skip
    # a Q1 needs no quarter before; another year's format is not read
    q1_day, q1 = CASES["Q1"][:2]
    previous = nonop_rows(2016, [1.0] * 4, [1.0] * 4, fmt="holding")
    assert nonop([*previous, *rows], q1_day, q1).reason is None
    # rev(q) ≤ 0
    for revenue in (1000.0, 500.0):  # rev(q) 0 and −500
        bad = [
            r if r.period_end != quarter else replace(r, revenue=revenue) for r in rows
        ]
        got = nonop(bad, day, quarter)
        assert (got.value, got.reason) == (None, "revenue"), revenue
    # a positive rev(q) with the cumulative negative before is fine
    odd = [r if r.period_end != date(2017, 3, 31) else replace(r, revenue=-100.0)
           for r in rows]  # fmt: skip
    assert nonop(odd, day, quarter).revenue == 2300.0


def test_the_nonop_statement_reads_the_two_fields():
    parse = __import__("worker.sources", fromlist=["parse_number"]).parse_number
    data = {"report_format": "general", "營業外收入及支出": "(1,234)",
            "營業收入": "56,789", "營業外損益": "9"}  # fmt: skip
    row = tool.nonop_statement_of("2017-05-15", "2017-03-31", data, parse)
    assert (row.nonop, row.revenue, row.report_format) == (-1234.0, 56789.0, "general")
    row = tool.nonop_statement_of(
        "2017-05-15",
        "2017-03-31",
        {"report_format": "holding", "營業外損益": "5"},
        parse,
    )
    assert (row.report_format, row.nonop, row.revenue) == ("holding", None, None)
    row = tool.nonop_statement_of(
        "2017-05-15", "2017-03-31", {**data, "營業外收入及支出": "--"}, parse
    )
    assert row.nonop is None and row.revenue == 56789.0


def test_fields_missing_is_point_3s_field_case_on_the_deadlines_quarter():
    item = make_item([10.0])
    day, quarter = CASES["Q2"][:2]

    def missing(rows):
        return tool.fields_missing(
            context_for(statements={1: rows}), item, day, quarter
        )

    assert not missing(YEAR)
    bad = [r if r.period_end != quarter else replace(r, revenue=1000.0) for r in YEAR]
    assert not missing(bad)  # rev(q) ≤ 0 is not a missing field
    assert not missing(
        [replace(r, report_format="holding") for r in YEAR]
    )  # nor the format
    early = [r if r.period_end != date(2017, 9, 30) else replace(r, announced=day)
             for r in YEAR]  # fmt: skip
    assert not missing(early)  # nor the stale quarter
    assert missing([r for r in YEAR if r.period_end != quarter])  # q not known on T
    assert missing([r for r in YEAR if r.period_end != date(2017, 3, 31)])
    assert missing(
        [
            r if r.period_end != date(2017, 3, 31) else replace(r, nonop=None)
            for r in YEAR
        ]
    )
    assert tool.fields_missing(context_for(), item, day, quarter)


def test_g1_ranks_small_first_with_its_reference_overlaps_and_means(monkeypatch):
    """G1 第 5～7 點, 第十八輪實作釋義: small first, 0 by value, the missing
    last; a delisted or transferred member missing a field is out of the
    reference, one with every field or an active one missing a field stays;
    P2's, N2's, A1's and X4's lists on the same T; each rebalance's names,
    mean rev(q) and share of nonop(q) < 0."""

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
    found = {  # value, nonop, revenue
        1: (None, None, None), 2: (0.01, 10.0, 1000.0), 3: (None, None, None),
        4: (None, 5.0, -10.0), 5: (-0.03, -60.0, 2000.0), 6: (0.0, 0.0, 600.0),
    }  # fmt: skip

    def fake(ctx, item, day, q):
        value, n, r = found[item.instrument_id]
        reason = (
            None if value is not None else ("revenue" if r is not None else "fields")
        )
        return tool.Nonop(value, reason, n, r)

    monkeypatch.setattr(tool, "nonop_q", fake)
    s = [
        sessions.index(d) + 1
        for d in (date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15))
    ]
    others = {"p2": {5, 9}, "n2": {2, 5, 6}, "a1": set(), "x4": {1, 2, 3, 4, 5, 6}}
    for key, names in others.items():
        if key == "x4":
            monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: names)
        else:
            monkeypatch.setattr(
                tool, f"{key}_names", lambda ctx, day, members, q, names=names: names
            )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses)  # fmt: skip
    first = s[0]
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_g1(ctx, tool.HYPOTHESES["G1"], first, last)
    assert planned.reference[s[0]] == [1, 2, 5, 6]
    assert planned.population[s[0]] == [1, 2, 3, 4, 5, 6]
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    tail = sorted((1, 3, 4), key=lambda i: pr.tie_break(date(2016, 3, 31), i))
    assert planned.picks[s[0]] == [5, 6, 2, *tail]  # −0.03, 0, 0.01, then the missing
    event = planned.rebalances[0]
    assert (event["delisted"], event["delisted_missing"]) == (3, 2)
    assert (event["valued"], event["names"], event["fields"], event["revenue"]) == (
        3,
        6,
        2,
        1,
    )
    assert (event["zero"], event["negative"]) == (1, 1)
    assert event["p2_overlap"] == pytest.approx(1 / 6)
    assert event["n2_overlap"] == pytest.approx(3 / 6)
    assert event["a1_overlap"] is None  # A1 has no list: not counted
    assert event["x4_overlap"] == 1.0
    # rev(q) of the 4 with one (2 000, 600, 1 000 and −10): 897.5; nonop < 0
    # among the 3 with a nonop_q: 1 of 3
    assert event["revenue_mean"] == pytest.approx((2000 + 600 + 1000 - 10) / 4)
    assert event["negative_share"] == pytest.approx(1 / 3)
    assert planned.overlap["G1_A1"] == {}
    assert planned.overlap["G1_N2"] == {"2016": [pytest.approx(0.5)] * 3}
    assert planned.means["negative"] == {"2016": [pytest.approx(1 / 3)] * 3}
    year = planned.coverage["2016"]
    assert (year["delisted"], year["delisted_missing"], year["valued"]) == (9, 6, 9)
    assert planned.rows[0]["nonop_q"] == -0.03 and planned.rows[0]["revenue"] == 2000.0


def test_the_overlaps_lists_are_the_other_tools_own(monkeypatch):
    """P2 through ``round16_research.p2_names``; N2's ``tax_mom`` high first
    and A1's ``net_issue`` small first, the missing last and filled by the
    hash, the first 20; on the contexts built on the same base."""

    day, quarter = date(2017, 5, 15), date(2017, 3, 31)
    items = [make_item([10.0], instrument_id=i) for i in range(1, 31)]
    members = [(item, 0) for item in items]
    ctx = context_for(items)
    assert ctx.n2.base is ctx.base is ctx.a1.base is ctx.z.base
    assert ctx.p2 is ctx.n2.p2 and ctx.n2.z2 is ctx.z
    calls = []
    monkeypatch.setattr(
        r16, "p2_names", lambda c, d, m, q: calls.append((c, d, q)) or {7}
    )
    assert tool.p2_names(ctx, day, members, quarter) == {7}
    assert calls == [(ctx.n2, day, quarter)]
    values = {i: (None if i % 7 == 0 else float(i % 11)) for i in range(1, 31)}
    monkeypatch.setattr(r16, "tax_mom", lambda c, item, d, q: SimpleNamespace(
        value=values[item.instrument_id]) if c is ctx.n2 else None)  # fmt: skip
    monkeypatch.setattr(r17, "net_issue", lambda c, item, d, q: SimpleNamespace(
        value=values[item.instrument_id]) if c is ctx.a1 else None)  # fmt: skip

    def expected(high):
        order = sorted(
            range(1, 31),
            key=lambda i: (
                values[i] is None,
                0.0 if values[i] is None else (-values[i] if high else values[i]),
                pr.tie_break(day, i),
            ),
        )
        return set(order[:20])

    assert tool.n2_names(ctx, day, members, quarter) == expected(True)
    assert tool.a1_names(ctx, day, members, quarter) == expected(False)
    assert {"p2_order", "n2_order", "a1_order"} <= set(ctx.seconds)


def test_z2_and_z3_names_are_round8s_own(monkeypatch):
    day = date(2016, 3, 1)
    rows = [(i, {}, "") for i in range(30, 0, -1)]
    calls = []

    def rank(ctx, spec, d, members):
        calls.append((ctx, spec, d))
        return SimpleNamespace(rows=rows)

    monkeypatch.setattr(r8, "rank", rank)
    ctx = SimpleNamespace(seconds=Counter(), z="z")
    top = set(range(30, 10, -1))
    assert tool.z_names(ctx, "Z2", day, []) == top == tool.z_names(ctx, "Z3", day, [])
    assert calls == [("z", r8.HYPOTHESES["Z2"], day), ("z", r8.HYPOTHESES["Z3"], day)]
    assert set(ctx.seconds) == {"z2_order", "z3_order"}


def test_the_event_account_sells_at_the_next_event_days_close():
    """「K2 的賣出時點」(G1): T′'s close, the new list at T′+1; fewer than 20
    cash; T′ suspended or locked: sold at the next open, its cash in that
    day's buys; the population and the reference 1/n of the cash."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              reference={1: [3], 4: [3]}, dues={1: 3, 4: 8})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "G1", planned, 1, 7
    )
    first, second = mine.positions
    assert (first.sold, first.how, second.bought) == (3, "close", 4)
    assert first.cost == pytest.approx(0.05)  # 1/20 of the cash, 19/20 in cash
    assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    assert [p.instrument_id for p in reference.positions] == [3, 3]
    assert reference.positions[0].cost == pytest.approx(1.0)
    assert population.positions[0].cost == pytest.approx(0.5)
    quote = quote_of(prices)
    for case in ("suspended", "locked"):

        def on(instrument_id, s, case=case):
            if case == "suspended" and (instrument_id, s) == (1, 3):
                return pr.Quote(10.0, 13.0, False)
            if case == "locked" and (instrument_id, s) == (1, 3):
                return pr.Quote(10.0, 13.0, True, locked_down=True)
            return quote(instrument_id, s)

        mine = tool.engines(SimpleNamespace(quote=on), "G1", planned, 1, 7)[0]
        first, second = mine.positions
        assert (first.sold, first.how) == (4, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    # T+1 not tradable (suspended, no bar): skipped, not filled
    gone = {k: v for k, v in prices.items() if k != (1, 1)}
    mine = tool.engines(SimpleNamespace(quote=quote_of(gone)), "G1", planned, 1, 7)[0]
    assert [p.instrument_id for p in mine.positions] == [2]
    assert mine.counts["not_tradable"] == 1


def test_invested_shares_and_the_excess_over_the_reference_by_hand(monkeypatch):
    """G1 第 6、7 點: one account; the reference on the same rule and event
    days; each rebalance's invested share at its T+1 close."""

    sessions = weekdays(date(2016, 3, 28), 6)
    prices = {(1, s): (10.0, (11.0, 12.0, 12.0, 13.0)[s - 1]) for s in (1, 2, 3, 4)}
    prices.update({(2, s): (10.0, 10.0) for s in (1, 2, 3, 4)})
    first, last = 1, 4
    events = [{"signal_date": sessions[0].isoformat(), "names": 1},
              {"signal_date": sessions[2].isoformat(), "names": 1}]  # fmt: skip
    plan = tool.Plan(picks={1: [1], 3: [1]}, population={1: [1, 2], 3: [1, 2]},
                     reference={1: [2], 3: [2]}, dues={1: 2, 3: 5}, rebalances=events)  # fmt: skip
    monkeypatch.setattr(tool, "segment_window", lambda *a: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_g1", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "G1", "exploration")
    units1 = pr.buy_units(0.05, 10.0)
    cash1 = 0.95
    eq1 = cash1 + units1 * 11.0
    cash2 = cash1 + pr.sale_proceeds(units1, 12.0)
    units2 = pr.buy_units(cash2 / 20, 10.0)
    cash3 = cash2 - cash2 / 20
    eq3 = cash3 + units2 * 12.0
    assert result["rebalances"][0]["invested"] == pytest.approx(units1 * 11 / eq1)
    assert result["rebalances"][1]["invested"] == pytest.approx(units2 * 12 / eq3)
    mine = [eq1, cash2, eq3, cash3 + units2 * 13.0]
    ref_units = pr.buy_units(1.0, 10.0)
    ref_cash = pr.sale_proceeds(ref_units, 10.0)
    ref_units2 = pr.buy_units(ref_cash, 10.0)
    ref = [ref_units * 10.0, ref_cash, ref_units2 * 10.0, ref_units2 * 10.0]
    differences = [a - b for a, b in zip(pr.daily_returns(mine), pr.daily_returns(ref))]
    got = result["excess"]["reference"]
    assert got["days"] == 4
    assert got["mean"] == pytest.approx(statistics.fmean(differences))
    assert got["t"] == pytest.approx(lib.t_stat(differences))
    assert result["unsold_share"] == 0.5  # the second due after the segment
    row = tool._row(result)
    assert row["names"] == 1 and row["reference_excess"] == got


# --- G2: coskew_240 ---------------------------------------------------------------


def closes_from(returns: list[float], start: float = 10.0) -> list[float]:
    out = [start]
    for r in returns:
        out.append(out[-1] * (1 + r))
    return out


def g2_context(stocks: dict[int, list[float]], index: list[float | None], **kw):
    sessions = weekdays(date(2016, 1, 4), len(index))
    items = [
        make_item(closes, instrument_id=i, dates=sessions[-len(closes):],
                  sessions=list(range(len(index) - len(closes), len(index))), **kw)
        for i, closes in stocks.items()
    ]  # fmt: skip
    closes = {day: close for day, close in zip(sessions, index) if close is not None}
    return context_for(items, sessions, index=closes), items


def coskew(stock: list[float], index: list[float | None], **kw):
    ctx, (item,) = g2_context({1: stock}, index, **kw)
    return tool.coskew_240(ctx, item, len(stock) - 1)


A = 0.01
M = [A, -A, 2 * A, -2 * A] * 60  # mean 0; m² − 2.5a² is orthogonal to m


def test_coskew_240_by_hand():
    """G2 第 1、2 點: r = 0.02 + 0.5m + γ(m² − 2.5a²) on m cycling a, −a, 2a,
    −2a: the regression's b is 0.5, ε = γ(m² − 2.5a²), so mean(εd²) =
    2.25γa⁴, √mean(ε²) = 1.5|γ|a², mean(d²) = 2.5a² and ``coskew_240`` =
    2.25 ÷ (1.5 × 2.5) = 0.6 with γ's sign, whatever a, b and the
    intercept."""

    index = closes_from(M, 1000.0)
    for gamma, expected in ((50.0, 0.6), (-50.0, -0.6)):
        r = [0.02 + 0.5 * m + gamma * (m * m - 2.5 * A * A) for m in M]
        got = coskew(closes_from(r), index)
        assert got.reason is None and got.value == pytest.approx(expected, rel=1e-6)
    # an independent fit (statistics.linear_regression) on returns that wiggle
    r = [0.003 * math.sin(k * 1.3) + 0.8 * m + 40 * m * m for k, m in enumerate(M)]
    closes = closes_from(r)
    actual = [closes[k + 1] / closes[k] - 1 for k in range(240)]
    market = [index[k + 1] / index[k] - 1 for k in range(240)]
    slope, intercept = statistics.linear_regression(market, actual)
    e = [y - intercept - slope * x for x, y in zip(market, actual)]
    mean = statistics.fmean(market)
    d2 = [(x - mean) ** 2 for x in market]
    expected = statistics.fmean(a * b for a, b in zip(e, d2)) / (
        math.sqrt(statistics.fmean(v * v for v in e)) * statistics.fmean(d2)
    )
    got = coskew(closes, index)
    assert got.value == pytest.approx(expected, rel=1e-9)
    # the bars before T − 240 are not read
    longer = coskew([99.0, 1.0, *closes], [5.0, 7.0, *index])
    assert longer.value == pytest.approx(expected, rel=1e-9)


def test_coskew_240_is_0_when_the_comoment_is_0_and_missing_otherwise():
    """G2 第 3 點, 第十八輪實作釋義: mean(εd²) = 0 is 0, not missing; each
    missing case; Σd² and Σε² not > 0."""

    index = [1.0, 2.0] * 120 + [1.0]  # m: 1, −0.5; d ±0.75, d² 0.5625 constant
    # r: 1, −0.5, −0.5, 1: b 0 exactly, ε = r − 0.25 sums to 0, so Σεd² is 0
    stock = [1.0, 2.0, 1.0, 0.5] * 60 + [1.0]
    got = coskew(stock, index)
    assert (got.value, got.reason) == (0.0, None)
    # the stock is the index: on the regression line, Σε² 0
    assert coskew(list(index), index).reason == "flat"
    assert coskew(stock[1:], index).reason == "short"  # 240 bars
    for bar in (0, 120, 240):
        assert coskew(stock, index, suspended=(bar,)).reason == "suspended", bar
    for bar in (0, 240):
        for bad in (0.0, -1.0, NAN):
            closes = list(stock)
            closes[bar] = bad
            assert coskew(closes, index).reason == "price", (bar, bad)
    for bar in (0, 100, 240):
        for bad in (None, 0.0, -5.0):
            closes = list(index)
            closes[bar] = bad
            assert coskew(stock, closes).reason == "index", (bar, bad)
    assert coskew(stock, [100.0] * 241).reason == "degenerate"  # every m_j 0
    # a session of the 241 without the stock's bar: its first of the last 241
    # bars is before T − 240
    sessions = weekdays(date(2016, 1, 4), 242)
    item = make_item(stock, dates=[*sessions[:100], *sessions[101:]],
                     sessions=[*range(100), *range(101, 242)])  # fmt: skip
    ctx = context_for([item], sessions, index=dict(zip(sessions, [1.0, *index])))
    assert tool.coskew_240(ctx, item, 240).reason == "gap"


def test_the_market_part_is_once_per_t_and_shared():
    index = closes_from(M, 1000.0)
    r = [0.5 * m + 50.0 * (m * m - 2.5 * A * A) for m in M]
    ctx, items = g2_context({1: closes_from(r), 2: closes_from(r, 20.0)}, index)
    a = tool.coskew_240(ctx, items[0], 240)
    b = tool.coskew_240(ctx, items[1], 240)
    assert a.value == pytest.approx(b.value) and list(ctx.markets) == [240]
    market = ctx.markets[240]
    assert market.first == 0 and len(market.d) == len(market.d2) == 240
    assert market.sdd == pytest.approx(600 * A * A)
    assert math.fsum(market.d) == pytest.approx(0.0, abs=1e-15)


def test_g2_rotates_60_accounts_and_the_population_too(monkeypatch):
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    monkeypatch.setattr(pr, "simulate", simulate)
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]})
    _m, _p, reference = tool.engines(SimpleNamespace(quote=None), "G2", planned, 1, 5)
    assert calls == [({1: [1]}, 60, 20), ({1: [1, 2]}, 60, None)] and reference is None


def test_g2_k60_accounts_by_hand():
    prices = {(i, s): (10.0, 10.0) for i in (1, 2) for s in range(1, 70)}
    mine, population, _ = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "G2",
        SimpleNamespace(picks={1: [1], 2: [2]}, population={1: [1, 2], 2: [1, 2]}), 1, 69,
    )  # fmt: skip
    first, second = mine.positions[:2]
    assert (first.bought, first.due, second.bought, second.due) == (1, 60, 2, 61)
    assert first.cost == pytest.approx(1 / 60 / 20) == second.cost
    assert first.account != second.account
    assert population.positions[0].cost == pytest.approx(1 / 60 / 2)


def test_g2_plan_ranks_small_first_overlaps_z2_z3_and_lists_the_means(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 30)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 26)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    values = {i: (None if i <= 3 else float(i % 5) - 2.0) for i in items}
    degenerate = {1: "degenerate", 2: "index"}  # signal sessions 1 and 2

    def market(ctx, s):
        return degenerate.get(s, SimpleNamespace())

    def fake(ctx, item, at):
        if at in degenerate:
            return tool.Coskew(None, degenerate[at])
        value = values[item.instrument_id]
        return tool.Coskew(value, None if value is not None else "short")

    monkeypatch.setattr(tool, "coskew_market", market)
    monkeypatch.setattr(tool, "coskew_240", lambda ctx, item, k: fake(ctx, item, k))
    monkeypatch.setattr(
        tool,
        "z_names",
        lambda ctx, name, day, members: {5, 10, 1} if name == "Z2" else set(),
    )
    skews = {i: (None if i == 5 else i / 100) for i in items}
    monkeypatch.setattr(r8, "skew_240", lambda ctx, item, at: skews[item.instrument_id])
    monkeypatch.setattr(r8, "beta_240", lambda ctx, item, at: 1.0)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          z=None)  # fmt: skip
    # members' bar 0 stands for the day: the fake keys on the signal session
    monkeypatch.setattr(
        lib, "universe",
        lambda panel, day, lots: [(items[i], sessions.index(day)) for i in items],
    )  # fmt: skip
    planned = tool.plan_g2(ctx, tool.HYPOTHESES["G2"], 1, 3)
    day = sessions[0]
    order = sorted(
        items, key=lambda i: (values[i] is None, values[i] or 0, pr.tie_break(day, i))
    )
    assert planned.picks[1] == order[:20]
    assert {1, 2, 3} & set(order[:20]) == set()
    chosen = order[:20]
    assert planned.overlap["G2_Z2"]["2016"][0] == pytest.approx(
        len({5, 10} & set(chosen)) / 20
    )
    assert planned.overlap["G2_Z3"] == {}
    expected = statistics.fmean(skews[i] for i in chosen if skews[i] is not None)
    assert planned.means["skew_240"]["2016"][0] == pytest.approx(expected)
    assert planned.means["beta_240"]["2016"] == [1.0, 1.0, 1.0]
    year = planned.coverage["2016"]
    assert (year["degenerate_days"], year["index_days"], year["days"]) == (1, 1, 3)
    missing = year["missing"]
    assert (year["valued"], missing["coskew_240"], missing["short"]) == (22, 53, 3)
    assert (missing["degenerate"], missing["index"]) == (25, 25)
    assert planned.rows[0]["coskew_240"] == -2.0 and planned.rows[0]["beta_240"] == 1.0


def test_the_starts_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2007, 11, 26), 4800)  # to 2026
    first, last = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["G2"])
    assert sessions[first - 1] == weekdays(OTC, 241)[-1]
    assert sessions[last] == date(2019, 12, 31)
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["G1"])
    assert sessions[first - 1] == date(2013, 5, 15)
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["G1"])
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["G2"])
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
        (3.359, "前瞻觀察"),  # round 17's threshold is not this round's
        (3.367, "前瞻觀察"),
        (3.368, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_368(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 700
STOCKS = range(1, 25)
# the last bar's index; 25 EPS only, 26 every field
DELISTED = {25: 570, 26: 450}
TRANSFERRED = 27  # EPS only
INDEX_ID = 90
HOLDING = 9  # report_format holding: 營業外損益, never a nonop_q
NO_REVENUE = 13  # cumulative revenue 0: rev(q) ≤ 0
GAP = 11  # no 營業外收入及支出 for 2016 Q2: Q2 and Q3 of 2016 missing


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def index_level(t: int) -> float:
    return 9000.0 * (1 + 0.004 * math.sin(t * 0.7)) + 5 * t


def path(i: int) -> list[tuple[float, float, float, float]]:
    out, previous = [], 50.0 + i
    for t in range(SESSIONS):
        m = index_level(t) / index_level(t - 1) - 1 if t else 0.0
        drift = (i - 12) * 0.0002 + (i % 5 - 2) * 20 * m * m + 0.7 * m
        close = round(previous * (1 + drift + 0.002 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


def nonop_single(i: int) -> float:
    """nonop(q) of i: (i − 12) × 5, so nonop_q rises with i."""

    return (i - 12) * 5.0


def fundamental_rows() -> list[dict]:
    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        for year in range(2012, 2019):
            for q, (end, due) in enumerate(zip(ENDS(year), DUES(year)), 1):
                eps = 1.0 * q
                revenue = 0.0 if i == NO_REVENUE else 1000.0 * (1 + i / 100) * q
                data: dict = {}
                if i not in (25, TRANSFERRED):  # the XBRL rows: EPS only
                    data = {"report_format": "general", tool.NONOP: f"{nonop_single(i) * q:,.3f}",
                            tool.REVENUE: f"{revenue:,.3f}",
                            "營業毛利（毛損）淨額": f"{revenue * 0.3:,.3f}",
                            "營業利益（損失）": f"{revenue * 0.1:,.3f}",
                            "本期淨利（淨損）": f"{revenue * 0.08:,.3f}",
                            "所得稅費用（利益）": f"{revenue * 0.02:,.3f}",
                            r17.NET: f"{revenue * 0.08:,.3f}", r17.EPS: f"{eps:.2f}"}  # fmt: skip
                    if i == GAP and end == date(2016, 6, 30):
                        del data[tool.NONOP]
                    if i == HOLDING:
                        data = {"report_format": "holding", "營業外損益": "12",
                                "淨收益": f"{revenue:,.3f}", r17.EPS: f"{eps:.2f}"}  # fmt: skip
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": due, "eps": eps, "data_json": data,
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
    return build(tmp_path_factory.mktemp("round18") / "stock.db")


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
    return one_process(lambda: tool.load(fixture_db, date(1990, 1, 1), days[499], raw))


def test_one_panel_serves_the_statements_and_the_overlaps(loaded):
    for part in (loaded.n2, loaded.a1, loaded.z, loaded.p2):
        assert part.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "statements", "lists"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    row = loaded.statements[1][0]
    assert (row.nonop, row.revenue) == (nonop_single(1), 1010.0)
    assert loaded.statements[25][0].nonop is None  # EPS only
    assert loaded.statements[HOLDING][0].nonop is None  # under another name
    assert loaded.p2.statements[1][0].gross == pytest.approx(303.0)
    assert loaded.n2.statements[1][0].tax == pytest.approx(20.2)
    assert loaded.a1.statements[1][0].eps == 1.0
    end = trading_days()[499]
    assert all(d <= end for item in loaded.panel.series.values() for d in item.dates)
    assert all(r.announced <= end for rows in loaded.statements.values() for r in rows)


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    series = loaded.panel.series
    day, quarter = date(2017, 5, 15), date(2017, 3, 31)
    for i in (1, 5, 12, 20):
        got = tool.nonop_q(loaded, series[i], day, quarter)
        assert got.value == pytest.approx(nonop_single(i) / (1000 * (1 + i / 100))), i
    assert tool.nonop_q(loaded, series[12], day, quarter).value == 0.0
    assert tool.nonop_q(loaded, series[HOLDING], day, quarter).reason == "format"
    assert tool.nonop_q(loaded, series[NO_REVENUE], day, quarter).reason == "revenue"
    assert tool.nonop_q(loaded, series[25], day, quarter).reason == "fields"
    q3 = (date(2016, 11, 14), date(2016, 9, 30))
    assert tool.nonop_q(loaded, series[GAP], *q3).reason == "fields"  # Q2 cumulative
    assert tool.fields_missing(loaded, series[25], day, quarter)
    assert not tool.fields_missing(loaded, series[26], day, quarter)
    at = days.index(date(2017, 5, 15))
    got = tool.coskew_240(loaded, series[1], series[1].position[days[at]])
    assert got.reason is None and -1 < got.value < 1
    # T − 240 before the copy's first session: no TAIEX close to read
    assert tool.coskew_240(loaded, series[1], 239).reason == "index"


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[479]),
            # G1's 2017-11-14 event
            "validation": (days[480], days[580]),
            "used": (days[581], days[699]),
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


def explore(db: Path, out: Path, *extra: str, hypotheses: str | None = "G1,G2") -> int:
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
        "round18_research", "1029", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (18, 2, 66)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.368)
    assert report["read_until"] == days[479].isoformat()
    hyp = report["hypotheses"]
    assert [hyp[n]["engine"] for n in NAMES] == ["events", "portfolio"]
    g1, g2 = hyp["G1"], hyp["G2"]
    assert g1["reference_excess"]["days"] > 0
    assert g1["names"] == 20
    assert g1["overlap_a1"]["days"] > 0 and g1["overlap_n2"]["days"] > 0
    # no P2 list (flat margins) and no X4 list (no monthly revenue): no day
    assert g1["overlap_p2"]["days"] == g1["overlap_x4"]["days"] == 0
    assert g1["mean_revenue"]["days"] > 0 and 0.4 < g1["mean_negative"]["mean"] <= 0.5
    for key in ("overlap_z2", "overlap_z3", "mean_skew_240", "mean_beta_240"):
        assert g2[key]["days"] > 0, key
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 2 個、累計 66 個" in text and "驗證段 t ≥ 3.368" in text
    for key in ("G1_survivor", "G1_proxy", "summary_only"):
        assert tool.OVERLAP_NOTE[key] in text, key
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round18_research", 18, "exploration", 1) for name in NAMES]
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
    g1_lines = (out / "G1" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert g1_lines[3] == tool.OVERLAP_NOTE["G1_survivor"]
    assert g1_lines[4] == "- " + tool.OVERLAP_NOTE["G1_proxy"]
    g1_text = "\n".join(g1_lines)
    assert "超額（對對照基準，只列出）" in g1_text
    assert tool.OVERLAP_NOTE["G1_reference"] in g1_text
    for key in ("G1_P2", "G1_N2", "G1_A1", "G1_X4", "G1_listed"):
        assert tool.OVERLAP_NOTE[key] in g1_text, key
    assert "## 每次調倉（G1 第 7 點" in g1_text and "## 名單裡業外為負的比例" in g1_text
    g2_text = (out / "G2" / "summary.md").read_text(encoding="utf-8")
    for key in ("G2_Z2", "G2_Z3", "G2_listed"):
        assert tool.OVERLAP_NOTE[key] in g2_text, key
    assert (
        "## 名單的平均 `skew_240`" in g2_text and "## 名單的平均 `beta_240`" in g2_text
    )
    picks = (out / "G1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        picks[0] == "signal_date,rank,exchange,symbol,quarter,nonop_q,nonop,revenue,tie"
    )
    on = [line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")]
    assert on[:4] == ["S1", "S2", "S3", "S4"]  # nonop_q rises with i
    g2_picks = (out / "G2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        g2_picks[0]
        == "signal_date,rank,exchange,symbol,coskew_240,skew_240,beta_240,tie"
    )


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="G2") == 2
    assert any("G2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="G1,A1") == 2
    assert any("A1 not registered" in line for line in refused(capsys))


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
    data["design"] = "1008"
    data["hypotheses"]["G2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_368(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "G1", "G2")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("G1", "round18_research", "finished"),
                       ("G2", "round18_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["G1", "G2"]
    assert validation["min_t"] == 3.368
    for name in NAMES:
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["reason"] is None, (
            name,
            tables["reason"],
            tables["prerequisites"],
        )
        assert tables["min_t"] == 3.368
    assert validation["hypotheses"]["G1"]["reference_excess"]["days"] > 0
    days = trading_days()
    assert validation["read_until"] == days[580].isoformat()
    g1 = read_json(tmp_path / "validation" / "G1" / "tables.json")
    assert g1["window"]["first_signal"] == "2017-11-14"
    g2 = read_json(tmp_path / "validation" / "G2" / "tables.json")
    assert g2["window"]["first_session"] == days[480].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.368（沒有 t 下限）" in text
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
    report = passed_report(out, tmp_path, "G2")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[580]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["G2"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["G2"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "G2" / "used" / file).is_file(), file


def test_a_failed_validation_loads_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    real_load = tool.load
    loads = []
    monkeypatch.setattr(tool, "load", lambda *a: loads.append(a[2]) or real_load(*a))
    monkeypatch.setattr(ex, "explore_judge", lambda *a, **k: ex.FORWARD_WATCH)
    assert (
        validate(db, tmp_path / "validation", passed_report(out, tmp_path, "G1")) == 0
    )
    assert loads == [trading_days()[580]]
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
    events = [e for row in hyp["G1"]["coverage"].values() for e in row["events"]]
    may = next(e for e in events if e["signal_date"] == "2017-05-15")
    # HOLDING; 25, 27 (EPS only); NO_REVENUE
    assert (may["format"], may["fields"], may["revenue"], may["stale"]) == (1, 2, 1, 0)
    assert may["valued"] == may["members"] - 4 == 23
    assert (may["delisted"], may["delisted_missing"]) == (3, 2)  # 25, 26, 27; 26 kept
    assert (may["zero"], may["negative"]) == (1, 10)  # i = 12; i < 12 less GAP's none
    august = next(e for e in events if e["signal_date"] == "2016-08-15")
    assert august["fields"] == 3  # GAP too
    assert [e["signal_date"] for e in events][:2] == ["2016-03-31", "2016-05-16"]
    g2 = hyp["G2"]["coverage"]
    assert sum(row.get("valued", 0) for row in g2.values()) > 0
    assert all(row.get("degenerate_days", 0) == 0 for row in g2.values())
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["G1"] == {"plan", "nonop_q", "reference", "p2_order", "n2_order",
                             "a1_order", "x4_order"}  # fmt: skip
    assert {"plan", "coskew_240", "z2_order", "z3_order"} <= seconds["G2"]
    columns = body["columns_2013"]
    assert sorted(columns) == ["2013-03-31", "2013-06-30", "2013-09-30", "2013-12-31"]
    general = columns["2013-03-31"]["general"]
    assert general["fields"][tool.NONOP] == general["rows"] == 23 + 1  # 26 too
    holding = columns["2013-03-31"]["holding"]
    assert holding["fields"] == {tool.NONOP: 0, tool.REVENUE: 0}
    assert "營業外損益" in holding["columns"]
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "statements", "lists"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "## G1：2013 年各季的欄名" in md
    assert "最新一季不是對應的那一季" in md and "大盤欄退化的訊號日" in md
    assert "有 `coskew_240` 的檔次" in md and "rev(q) ≤ 0" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "G1"])  # fmt: skip


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
    assert explore(copied, tmp_path / "out", hypotheses="G2") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "G2")
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
        assert explore(copied, out, hypotheses="G2") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "G2")
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
