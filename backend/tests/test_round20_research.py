"""tools/research/round20_research.py: the registered AB1, AB2 (#1057).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第二十輪：AB1、AB2.  The features and the accounts are
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
    Event,
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1057#issuecomment-1"
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
im = sys.modules.get("industry_members") or _tool("industry_members")
ms = _tool("mainstream_research")
r5 = _tool("round5_research")
r7 = _tool("round7_research")
r10 = _tool("round10_research")
r11 = _tool("round11_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
r16 = _tool("round16_research")
r18 = _tool("round18_research")
tool = _tool("round20_research")
NAMES = ("AB1", "AB2")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 20))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    ab1, ab2 = (h[name] for name in NAMES)
    assert (ab1["engine"], ab2["engine"]) == ("events", "portfolio")
    assert ab1["keys"] == (("op_margin_4q", "high"),)
    assert (ab1["top"], ab1["hold"], ab1["start"], ab1["rule"]) == (
        20, "next_event", ("date", date(2014, 3, 31)), "quarterly",
    )  # fmt: skip
    assert ab2["condition"] == "no_news_20"
    assert ab2["keys"] == (("momentum_20", "low"),)
    assert (ab2["top"], ab2["hold"], ab2["start"], ab2["rule"]) == (
        20, 20, ("session", OTC, 21), "daily",
    )  # fmt: skip
    for spec in h.values():
        assert spec["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        20,
        2,
        70,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.384
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(70), 3) == 3.384
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "eb8df844" and tool.DESIGN == "1057"
    assert (tool.OPERATING, tool.REVENUE, tool.REPORT_FORMAT) == (
        "營業利益（損失）", "營業收入", "general",
    )  # fmt: skip
    assert (tool.REVENUE_MIN, tool.QUARTERS, tool.NEWS_SESSIONS) == (0.0, 4, 20)
    assert (tool.NEWS_SOURCE, tool.NEWS_EVENT_TYPE) == (
        "mops_material_information", "material_information",
    )  # fmt: skip
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    assert tool.DELISTED_STATUS == "delisted"
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool.industries_summary is r11.industries_summary
    assert tool._known is r15._known
    assert tool.single_quarter is r15.single_quarter
    assert tool.SINGLE_QUARTER == r15.SINGLE_QUARTER
    assert "load_context" in tool.load.__code__.co_names
    assert {"load_statements", "load_statuses", "load_nonop_statements",
            "build_context", "read_members"} <= set(tool.load.__code__.co_names)  # fmt: skip
    assert "quarter_events" in tool.plan_ab1.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "r16.p2_names(" in inspect.getsource(tool.p2_names)
    assert "r18.nonop_q(" in inspect.getsource(tool.g1_names)
    assert "x4_names" in tool.x4_names.__code__.co_names
    assert "r5.rank(" in inspect.getsource(tool.v2_names)
    assert "r7.rank(" in inspect.getsource(tool.y4_names)
    assert "r11.industry_count(" in inspect.getsource(tool.industry_count)
    assert "ms.group_members(" in inspect.getsource(tool.groups_of)
    assert "r5.momentum_20(" in inspect.getsource(tool.plan_ab2)
    assert "r15.columns_2013(" in inspect.getsource(tool.columns_2013)
    for plan in (tool.plan_ab1, tool.plan_ab2):
        assert "r5.order_key(" in inspect.getsource(plan)
    assert "announcements" in inspect.getsource(tool.news_days)


def _swap(spec_name: str, key: str, value):
    return {**tool.HYPOTHESES, spec_name: {**tool.HYPOTHESES[spec_name], key: value}}


def _other(module, name: str, key: str, value):
    return {**module.HYPOTHESES, name: {**module.HYPOTHESES[name], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1057 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.384
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.376),
        # AB1: the two fields, general only, the 4 quarters' sums, the latest
        # quarter (P2's reading, the deadline's quarter), the single
        # quarters (Q1 cumulative, Q2～Q4 less the quarter before), the
        # missing cases, Σrev ≤ 0, Σop 0 not missing, high first, N 20, the
        # next event, the reference
        (tool, "OPERATING", "營業毛利（毛損）"),
        (tool, "REVENUE", "淨收益"),
        (tool, "FIELDS", ("revenue", "operating")),
        (tool, "REPORT_FORMAT", "holding"),
        (tool, "QUARTERS", 1),
        (tool, "LATEST_RULE", "the latest quarter with an EPS (K2's)"),
        (tool, "LATEST_RULE", "the latest quarter, any quarter"),
        (tool, "NEEDED_RULE", "q only"),
        (tool, "SINGLE_QUARTER", "the cumulative figures"),
        (features, "VERSION", features.VERSION + 1),
        (tool, "REVENUE_MIN", -1.0),
        (tool, "OP_MARGIN", "sum op / sum rev; a single rev <= 0: missing"),
        (tool, "OP_MARGIN", "sum op / sum rev; sum op 0: missing"),
        (tool, "STATEMENT_RULE", "the rows with an EPS"),
        (r15, "NUMBER_RULE", "float()"),
        (tool, "AB1_REFERENCE", "less every delisted instrument"),
        (tool, "HYPOTHESES", _swap("AB1", "keys", (("op_margin_4q", "low"),))),
        (tool, "HYPOTHESES", _swap("AB1", "top", 19)),
        (tool, "HYPOTHESES", _swap("AB1", "hold", 60)),
        (tool, "HYPOTHESES", _swap("AB1", "start", ("date", date(2014, 5, 15)))),
        # AB2: the source, the 20 sessions, the calendar window (T in, T −
        # 20 out, weekends), any title, momentum_20 small first, missing
        # last, N 20, K 20
        (tool, "NEWS_SOURCE", "mops_other"),
        (tool, "NEWS_EVENT_TYPE", "treasury_stock"),
        (tool, "NEWS_SESSIONS", 19),
        (tool, "NEWS_RULE", "the sessions (T-20, T), not T"),
        (tool, "NEWS_RULE", "the item's own last 20 bars"),
        (tool, "NEWS_MISSING", "no row in the copy's gap: missing"),
        (tool, "MOMENTUM_RULE", "momentum_20 small first, missing dropped"),
        (r5, "MOMENTUM_WINDOW", 21),
        (tool, "HYPOTHESES", _swap("AB2", "keys", (("momentum_20", "high"),))),
        (tool, "HYPOTHESES", _swap("AB2", "condition", None)),
        (tool, "HYPOTHESES", _swap("AB2", "top", 19)),
        (tool, "HYPOTHESES", _swap("AB2", "hold", 60)),
        (tool, "HYPOTHESES", _swap("AB2", "start", ("session", OTC, 22))),
        # the two: the hash and the order, the start, the event days
        (tool, "ORDER", "high first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "SALE", "at T'+1's open"),
        (tool, "REFERENCE_STATUSES", ("delisted",)),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        # the overlaps' lists and the listed parts
        (r15, "HYPOTHESES", _other(r15, "P2", "top", 19)),
        (r18, "HYPOTHESES", _other(r18, "G1", "top", 19)),
        (r18, "NONOP", "營業外損益"),
        (ex, "HYPOTHESES", _other(ex, "X4", "top", 19)),
        (r5, "HYPOTHESES", _other(r5, "V2", "top", 19)),
        (r7, "HYPOTHESES", _other(r7, "Y4", "top", 19)),
        (tool, "INDUSTRY_RULE", "the largest group id"),
        (tool, "DELISTED_STATUS", "transferred"),
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
            assert tool.definitions_sha256() != before, (module.__name__, name, value)
    assert tool.definitions_sha256() == before


def test_the_command_has_no_parameter_flags():
    flags = {
        option for action in tool._parser()._actions for option in action.option_strings
    }
    assert flags == {
        "-h", "--help", "--db", "--out", "--segment", "--min-free-gb", "--members",
        "--coverage-only", "--hypotheses", "--exploration-report", "--exploration-sha256",
        "--exploration-url",
    }  # fmt: skip


# AC-1: measured on master eb8df844 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash, its P2 row round15_research's and its
# A1 row round17_research's; the overlaps read round15 (P2), round18 (G1),
# explore_research (X4), round5 (V2, momentum_20) and round7 (Y4).
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
    "round19_research": (1, "f54483a3ad84d6a3d97215bdfb64834c8b94d175effab458795a49ff3def233e"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round5_research", "round7_research", "round10_research", "round11_research",
     "round14_research", "round15_research", "round17_research", "round18_research",
     "round19_research", None],
)  # fmt: skip
def test_the_overlaps_tools_are_the_ledgers(name):
    """AC-1: the hashes the overlaps, the listed parts and forward_watch read
    are the ones in the public ledger (explore_research's entries have no
    ``tool``)."""

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


# AC-1: portfolio_research.ranking_key's source on master eb8df844
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
    section = text.split("**第二十輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.384 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round20_research.py" in section
    assert "本輪 2 個、累計 70 個" in section


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


def context_for(items=(), sessions=None, statements=None, statuses=None, news=()):
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
    base.announcements.extend(news)
    return tool.Context(base, statements=statements or {}, statuses=statuses or {})


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


# --- AB1: op_margin_4q ------------------------------------------------------------

ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731
DUES = lambda y: [date(y, 5, 15), date(y, 8, 14), date(y, 11, 14), date(y + 1, 3, 31)]  # noqa: E731


def statement_rows(year, operating, revenue, fmt="general"):
    """One year's rows from the cumulative figures, as the source writes them
    (``round15_research.Statement``, the gross and net margins unread)."""

    return [
        r15.Statement(due, end, fmt, r, None, o, None)
        for end, due, o, r in zip(ENDS(year), DUES(year), operating, revenue)
    ]


# single quarters: 2016 op 10, 20, 30, 40 and rev 100, 200, 300, 400;
# 2017 op −50, 30, 0, 60 and rev 1,000, 1,200, 800, 1,000
Y2016 = statement_rows(2016, [10.0, 30.0, 60.0, 100.0], [100.0, 300.0, 600.0, 1000.0])
Y2017 = statement_rows(
    2017, [-50.0, -20.0, -20.0, 40.0], [1000.0, 2200.0, 3000.0, 4000.0]
)
ROWS = [*Y2016, *Y2017]
CASES = {  # deadline, quarter, [op(q−k)], [rev(q−k)], k = 0 .. 3
    "Q1": (date(2017, 5, 15), date(2017, 3, 31), [-50.0, 40.0, 30.0, 20.0],
           [1000.0, 400.0, 300.0, 200.0]),
    "Q2": (date(2017, 8, 14), date(2017, 6, 30), [30.0, -50.0, 40.0, 30.0],
           [1200.0, 1000.0, 400.0, 300.0]),
    "Q3": (date(2017, 11, 14), date(2017, 9, 30), [0.0, 30.0, -50.0, 40.0],
           [800.0, 1200.0, 1000.0, 400.0]),
    "Q4": (date(2018, 3, 31), date(2017, 12, 31), [60.0, 0.0, 30.0, -50.0],
           [1000.0, 800.0, 1200.0, 1000.0]),
}  # fmt: skip


def margin(rows, day, quarter):
    ctx = context_for(statements={1: rows})
    return tool.op_margin_4q(ctx, make_item([10.0]), day, quarter)


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_single_quarters_and_op_margin_4q_by_hand(case):
    """AB1 第 2 點: Q1 the cumulative figure, Q2 and Q3 less the same year's
    quarter before, Q4 (the annual report) less Q3's; the 4 quarters' sums."""

    day, quarter, operating, revenue = CASES[case]
    known = tool._known(ROWS, day)
    assert tool._singles(known, quarter) == (operating, revenue)
    got = margin(ROWS, day, quarter)
    assert got.reason is None
    assert (got.operating, got.revenue) == (sum(operating), sum(revenue))
    assert got.value == sum(operating) / sum(revenue)
    # the year before the 4 quarters is not read
    previous = statement_rows(2015, [999.0, 1.0, 5.0, 7.0], [1.0, 2.0, 3.0, 4.0])
    assert margin([*previous, *ROWS], day, quarter) == got


def test_op_margin_4q_by_hand_ratio():
    # 2017 Q2: (30 − 50 + 40 + 30) ÷ (1,200 + 1,000 + 400 + 300) = 50 ÷ 2,900
    day, quarter = CASES["Q2"][:2]
    assert margin(ROWS, day, quarter).value == pytest.approx(50 / 2900)


def test_a_negative_or_0_numerator_is_a_value():
    """AB1 第 4 點: Σop < 0 and Σop = 0 are values, ranked by value."""

    day, quarter = CASES["Q2"][:2]
    loss = [replace(r, operating=-r.operating - 100.0) if r.operating else r
            for r in ROWS]  # fmt: skip
    got = margin(loss, day, quarter)
    assert got.reason is None and got.value < 0
    # 2016 Q3 op 30 → −20: q−3 .. q is 30 − 50 + 40 − 20 = 0
    zero = [r if r.period_end != date(2016, 9, 30) else replace(r, operating=10.0)
            for r in ROWS]  # fmt: skip
    zero = [r if r.period_end != date(2016, 12, 31) else replace(r, operating=50.0)
            for r in zero]  # fmt: skip
    got = margin(zero, day, quarter)
    assert (got.value, got.reason, got.operating) == (0.0, None, 0.0)


def test_op_margin_4q_is_missing_stale_format_fields_or_revenue():
    day, quarter = CASES["Q2"][:2]
    assert margin(ROWS, day, quarter).reason is None
    late = [r if r.period_end != quarter else replace(r, announced=day + timedelta(days=1))
            for r in ROWS]  # fmt: skip
    assert margin(late, day, quarter).reason == "stale"  # q not known on T
    assert margin([], day, quarter).reason == "stale"
    # the latest known is not the deadline's quarter (Q3 announced early)
    early = [r if r.period_end != date(2017, 9, 30) else replace(r, announced=day)
             for r in ROWS]  # fmt: skip
    assert margin(early, day, quarter).reason == "stale"
    # every row q .. q − 3 and the quarters before them read for the single
    # quarters: 2017 Q2, Q1, 2016 Q4, Q3 and Q2
    needed = [date(2017, 6, 30), date(2017, 3, 31), date(2016, 12, 31),
              date(2016, 9, 30), date(2016, 6, 30)]  # fmt: skip
    assert tool._needed(quarter) == needed
    for end in needed:
        other = [r if r.period_end != end else replace(r, report_format="holding")
                 for r in ROWS]  # fmt: skip
        assert margin(other, day, quarter).reason == "format", end
        for name in ("operating", "revenue"):
            gone = [
                r if r.period_end != end else replace(r, **{name: None}) for r in ROWS
            ]
            got = margin(gone, day, quarter)
            assert (got.value, got.reason) == (None, "fields"), (end, name)
        blank = [r if r.period_end != end else replace(r, report_format=None)
                 for r in ROWS]  # fmt: skip
        assert margin(blank, day, quarter).reason == "fields", end
        gone_row = margin([r for r in ROWS if r.period_end != end], day, quarter)
        assert gone_row.reason == ("stale" if end == quarter else "fields"), end
    # 2016 Q1 is not read for q = 2017 Q2 (q − 3 is 2016 Q3)
    assert margin([r for r in ROWS if r.period_end != date(2016, 3, 31)], day,
                  quarter).reason is None  # fmt: skip
    # another year's format is not read
    previous = statement_rows(2015, [1.0] * 4, [1.0] * 4, fmt="holding")
    assert margin([*previous, *ROWS], day, quarter).reason is None
    # Σrev ≤ 0: 0 and negative; a single quarter's rev ≤ 0 with Σ > 0 is a value
    for single in (-1700.0, -2700.0):  # rev(q) 1,200 → −1,700, −2,700: Σ 0, −1,000
        bad = [r if r.period_end != quarter else replace(r, revenue=1000.0 + single)
               for r in ROWS]  # fmt: skip
        got = margin(bad, day, quarter)
        assert (got.value, got.reason, got.revenue) == (
            None,
            "revenue",
            single + 1700.0,
        )
    odd = [r if r.period_end != quarter else replace(r, revenue=1000.0 - 100.0)
           for r in ROWS]  # fmt: skip
    got = margin(odd, day, quarter)  # rev(q) −100, Σ 1,600
    assert got.reason is None and got.revenue == 1600.0


def test_the_statements_are_round15s_reading():
    parse = __import__("worker.sources", fromlist=["parse_number"]).parse_number
    data = {"report_format": "general", "營業利益（損失）": "(1,234)",
            "營業收入": "56,789", "營業外收入及支出": "9"}  # fmt: skip
    row = r15.statement_of("2017-05-15", "2017-03-31", data, parse)
    assert (row.operating, row.revenue, row.report_format) == (
        -1234.0,
        56789.0,
        "general",
    )
    assert [getattr(row, name) for name in tool.FIELDS] == [-1234.0, 56789.0]
    row = r15.statement_of("2017-05-15", "2017-03-31",
                           {**data, "營業利益（損失）": "--"}, parse)  # fmt: skip
    assert row.operating is None and row.revenue == 56789.0


def test_fields_missing_is_point_3s_field_case_on_the_deadlines_quarter():
    item = make_item([10.0])
    day, quarter = CASES["Q2"][:2]

    def missing(rows):
        return tool.fields_missing(
            context_for(statements={1: rows}), item, day, quarter
        )

    assert not missing(ROWS)
    bad = [r if r.period_end != quarter else replace(r, revenue=-2000.0) for r in ROWS]
    assert margin(bad, day, quarter).reason == "revenue"
    assert not missing(bad)  # Σrev ≤ 0 is not a missing field
    assert not missing(
        [replace(r, report_format="holding") for r in ROWS]
    )  # nor format
    early = [r if r.period_end != date(2017, 9, 30) else replace(r, announced=day)
             for r in ROWS]  # fmt: skip
    assert not missing(early)  # nor the stale quarter
    assert missing([r for r in ROWS if r.period_end != quarter])  # q not known on T
    assert missing(
        [r for r in ROWS if r.period_end != date(2016, 6, 30)]
    )  # q−3's before
    assert missing([r if r.period_end != date(2016, 9, 30) else replace(r, operating=None)
                    for r in ROWS])  # fmt: skip
    assert tool.fields_missing(context_for(), item, day, quarter)


def test_ab1_ranks_high_first_with_its_reference_overlaps_and_industries(monkeypatch):
    """AB1 第 5～8 點, 第二十輪實作釋義: high first, 0 and negative by value,
    the missing last; a delisted or transferred member missing a field is out
    of the reference, one with every field or an active one missing a field
    stays; P2's, G1's and X4's lists on the same T; each rebalance's names,
    valued members and industries."""

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
    found = {  # value, Σop, Σrev, reason
        1: (None, None, None, "fields"), 2: (0.01, 10.0, 1000.0, None),
        3: (None, None, None, "stale"), 4: (None, 5.0, -10.0, "revenue"),
        5: (-0.03, -60.0, 2000.0, None), 6: (0.0, 0.0, 600.0, None),
    }  # fmt: skip

    def fake(ctx, item, day, q):
        value, o, r, reason = found[item.instrument_id]
        return tool.Margin(value, reason, o, r)

    monkeypatch.setattr(tool, "op_margin_4q", fake)
    s = [
        sessions.index(d) + 1
        for d in (date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15))
    ]
    others = {"p2": {5, 9}, "g1": {2, 5, 6}, "x4": {1, 2, 3, 4, 5, 6}}
    monkeypatch.setattr(tool, "p2_names", lambda ctx, day, members, q: others["p2"])
    monkeypatch.setattr(tool, "g1_names", lambda ctx, day, members, q: others["g1"])
    monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: others["x4"])
    groups = {2: "b", 5: "a", 6: "a", 1: "c"}  # 3 and 4 not in the table
    monkeypatch.setattr(tool, "groups_of", lambda ctx, day: groups)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses)  # fmt: skip
    first = s[0]
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_ab1(ctx, tool.HYPOTHESES["AB1"], first, last)
    assert planned.reference[s[0]] == [1, 2, 5, 6]
    assert planned.population[s[0]] == [1, 2, 3, 4, 5, 6]
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    tail = sorted((1, 3, 4), key=lambda i: pr.tie_break(date(2016, 3, 31), i))
    assert planned.picks[s[0]] == [2, 6, 5, *tail]  # 0.01, 0, −0.03, then the missing
    event = planned.rebalances[0]
    assert (event["delisted"], event["delisted_missing"]) == (3, 2)
    assert (event["valued"], event["names"], event["fields"], event["stale"],
            event["revenue"], event["format"]) == (3, 6, 1, 1, 1, 0)  # fmt: skip
    assert (event["zero"], event["negative"]) == (1, 1)
    assert event["p2_overlap"] == pytest.approx(1 / 6)
    assert event["g1_overlap"] == pytest.approx(3 / 6)
    assert event["x4_overlap"] == 1.0
    assert event["industries"] == 3  # a, b, c; 3 and 4 not counted
    assert planned.overlap["AB1_G1"] == {"2016": [pytest.approx(0.5)] * 3}
    assert planned.industries == {"2016": [3, 3, 3]}
    year = planned.coverage["2016"]
    assert (year["delisted"], year["delisted_missing"], year["valued"]) == (9, 6, 9)
    row = planned.rows[0]
    assert (row["op_margin_4q"], row["operating_4q"], row["revenue_4q"]) == (
        0.01,
        10.0,
        1000.0,
    )


def test_ab1_takes_20_and_leaves_cash_below_20(monkeypatch):
    """AB1 第 5 點: the first 20 by the value high first (the missing last,
    filled by the hash); a population under 20 leaves the rest in cash."""

    sessions = weekdays(date(2016, 1, 4), 120)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    values = {i: (None if i % 4 == 0 else float(i % 9)) for i in items}
    size = {"n": 30}
    monkeypatch.setattr(lib, "universe", lambda panel, day, lots: [
        (items[i], 0) for i in list(items)[: size["n"]]])  # fmt: skip
    monkeypatch.setattr(tool, "op_margin_4q", lambda ctx, item, day, q: tool.Margin(
        values[item.instrument_id], None if values[item.instrument_id] is not None
        else "fields"))  # fmt: skip
    monkeypatch.setattr(tool, "fields_missing", lambda *a: False)
    for name in ("p2_names", "g1_names"):
        monkeypatch.setattr(tool, name, lambda *a: set())
    monkeypatch.setattr(tool, "x4_names", lambda *a: set())
    monkeypatch.setattr(tool, "groups_of", lambda ctx, day: None)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=Counter(), statuses={})  # fmt: skip
    first = sessions.index(date(2016, 3, 31)) + 1
    planned = tool.plan_ab1(ctx, tool.HYPOTHESES["AB1"], first, first + 5)
    day = date(2016, 3, 31)
    order = sorted(
        items,
        key=lambda i: (values[i] is None, -(values[i] or 0), pr.tie_break(day, i)),
    )
    assert planned.picks[first] == order[:20]
    assert planned.rebalances[0]["industries"] is None and planned.industries == {}
    size["n"] = 7
    planned = tool.plan_ab1(ctx, tool.HYPOTHESES["AB1"], first, first + 5)
    assert len(planned.picks[first]) == 7
    mine = tool.engines(
        SimpleNamespace(quote=quote_of({(i, s): (10.0, 10.0) for i in items
                                        for s in range(first, first + 6)})),
        "AB1", planned, first, first + 5,
    )[0]  # fmt: skip
    assert len(mine.positions) == 7
    assert mine.positions[0].cost == pytest.approx(0.05)  # 1/20 each
    assert mine.invested[0] == pytest.approx(
        7 * pr.buy_units(0.05, 10.0) * 10.0 / mine.equity[0]
    )  # 13/20 in cash


def test_the_overlaps_lists_are_the_other_tools_own(monkeypatch):
    """P2 through ``round16_research.p2_names`` on P2's context; G1's
    ``nonop_q`` small first on G1's own statements, the missing last and
    filled by the hash, the first 20; on the contexts built on the same base."""

    day, quarter = date(2017, 5, 15), date(2017, 3, 31)
    items = [make_item([10.0], instrument_id=i) for i in range(1, 31)]
    members = [(item, 0) for item in items]
    ctx = context_for(items)
    assert ctx.p2.base is ctx.base is ctx.v2.base is ctx.y4.base
    assert ctx.p2.statements is ctx.statements  # one reading for AB1 and P2
    calls = []
    monkeypatch.setattr(
        r16, "p2_names", lambda c, d, m, q: calls.append((c, d, q)) or {7}
    )
    assert tool.p2_names(ctx, day, members, quarter) == {7}
    assert calls == [(ctx, day, quarter)]
    values = {i: (None if i % 7 == 0 else float(i % 11)) for i in range(1, 31)}
    seen = []

    def nonop(c, item, d, q):
        seen.append(c.statements is ctx.nonop_statements)
        return SimpleNamespace(value=values[item.instrument_id])

    monkeypatch.setattr(r18, "nonop_q", nonop)
    order = sorted(
        range(1, 31),
        key=lambda i: (values[i] is None, values[i] or 0.0, pr.tie_break(day, i)),
    )
    assert tool.g1_names(ctx, day, members, quarter) == set(order[:20])
    assert all(seen) and len(seen) == 30
    assert "g1_order" in ctx.seconds


def test_v2_and_y4_names_are_round5s_and_round7s_own(monkeypatch):
    day = date(2016, 3, 1)
    rows = [(i, {}, "") for i in range(30, 0, -1)]
    calls = []

    def rank(name):
        def run(ctx, spec, d, members):
            calls.append((name, ctx, spec, d))
            return SimpleNamespace(rows=rows)

        return run

    monkeypatch.setattr(r5, "rank", rank("r5"))
    monkeypatch.setattr(r7, "rank", rank("r7"))
    ctx = SimpleNamespace(seconds=Counter(), v2="v2", y4="y4")
    top = set(range(30, 10, -1))
    assert tool.v2_names(ctx, day, []) == top == tool.y4_names(ctx, day, [])
    assert calls == [("r5", "v2", r5.HYPOTHESES["V2"], day),
                     ("r7", "y4", r7.HYPOTHESES["Y4"], day)]  # fmt: skip
    assert set(ctx.seconds) == {"v2_order", "y4_order"}


def test_groups_of_takes_the_smallest_group_id(monkeypatch):
    day = date(2016, 3, 1)
    monkeypatch.setattr(
        ms,
        "group_members",
        lambda groups, d: ({"b": {1, 2}, "a": {2, 3}}, set(), set()),
    )
    ctx = SimpleNamespace(groups="table", industries={}, seconds=Counter())
    assert tool.groups_of(ctx, day) == {1: "b", 2: "a", 3: "a"}
    assert tool.industry_count(ctx, day, [1, 2, 3, 9]) == 2  # 9 not in the table
    assert tool.industry_count(ctx, day, []) is None
    assert tool.groups_of(SimpleNamespace(groups=None), day) is None


def test_the_event_account_sells_at_the_next_event_days_close():
    """「K2 的賣出時點」(AB1): T′'s close, the new list at T′+1; fewer than 20
    cash; T′ suspended or locked: sold at the next open, its cash in that
    day's buys; the population and the reference 1/n of the cash."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              reference={1: [3], 4: [3]}, dues={1: 3, 4: 8})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "AB1", planned, 1, 7
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

        mine = tool.engines(SimpleNamespace(quote=on), "AB1", planned, 1, 7)[0]
        first, second = mine.positions
        assert (first.sold, first.how) == (4, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    # T+1 not tradable (suspended, no bar): skipped, not filled
    gone = {k: v for k, v in prices.items() if k != (1, 1)}
    mine = tool.engines(SimpleNamespace(quote=quote_of(gone)), "AB1", planned, 1, 7)[0]
    assert [p.instrument_id for p in mine.positions] == [2]
    assert mine.counts["not_tradable"] == 1


def test_invested_shares_and_the_excess_over_the_reference_by_hand(monkeypatch):
    """AB1 第 6、8 點 (#979 review 7087182701): one account; the reference on
    the same rule and event days; each rebalance's invested share at its T+1
    close; a sale put off by a suspension, by hand."""

    sessions = weekdays(date(2016, 3, 28), 7)
    prices = {
        (1, s): (10.0, (11.0, 12.0, 12.0, 13.0, 14.0)[s - 1]) for s in (1, 2, 3, 4, 5)
    }
    prices.update({(2, s): (10.0, 10.0) for s in (1, 2, 3, 4, 5)})
    # 3: bought at 1, its sale day 2 suspended, sold at 3's open (10.5)
    prices.update({(3, 1): (10.0, 10.0), (3, 3): (10.5, 10.5), (3, 4): (10.5, 10.5),
                   (3, 5): (10.5, 10.5)})  # fmt: skip
    first, last = 1, 5
    events = [{"signal_date": sessions[0].isoformat(), "names": 2, "valued": 5},
              {"signal_date": sessions[2].isoformat(), "names": 1, "valued": 4}]  # fmt: skip
    plan = tool.Plan(picks={1: [1, 3], 3: [1]}, population={1: [1, 2], 3: [1, 2]},
                     reference={1: [2], 3: [2]}, dues={1: 2, 3: 6}, rebalances=events)  # fmt: skip
    monkeypatch.setattr(tool, "segment_window", lambda *a: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_ab1", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "AB1", "exploration")
    units1 = pr.buy_units(0.05, 10.0)
    units3 = pr.buy_units(0.05, 10.0)
    cash1 = 0.90
    eq1 = cash1 + units1 * 11.0 + units3 * 10.0  # 3's close at 1 is 10
    cash2 = cash1 + pr.sale_proceeds(units1, 12.0)
    eq2 = cash2 + units3 * 10.0  # 3 suspended at 2: held at its last close
    # session 3: 3 sold at the open (10.5), its cash in that day's buy
    cash3 = cash2 + pr.sale_proceeds(units3, 10.5)
    units2 = pr.buy_units(cash3 / 20, 10.0)
    cash3 -= cash3 / 20
    eq3 = cash3 + units2 * 12.0
    assert result["rebalances"][0]["invested"] == pytest.approx(
        (units1 * 11 + units3 * 10) / eq1
    )
    assert result["rebalances"][1]["invested"] == pytest.approx(units2 * 12 / eq3)
    mine = [eq1, eq2, eq3, cash3 + units2 * 13.0, cash3 + units2 * 14.0]
    sales = {p.instrument_id: (p.sold, p.how) for p in result["_positions"]}
    assert sales[3] == (3, "delayed")
    ref_units = pr.buy_units(1.0, 10.0)
    ref_cash = pr.sale_proceeds(ref_units, 10.0)
    ref_units2 = pr.buy_units(ref_cash, 10.0)
    ref = [ref_units * 10.0, ref_cash, ref_units2 * 10.0, ref_units2 * 10.0,
           ref_units2 * 10.0]  # fmt: skip
    differences = [a - b for a, b in zip(pr.daily_returns(mine), pr.daily_returns(ref))]
    got = result["excess"]["reference"]
    assert got["days"] == 5
    assert got["mean"] == pytest.approx(statistics.fmean(differences))
    assert got["t"] == pytest.approx(lib.t_stat(differences))
    row = tool._row(result)
    assert (row["names"], row["valued"]) == (1.5, 4.5) and row[
        "reference_excess"
    ] == got


# --- AB2: no_news_20 --------------------------------------------------------------


def news_on(*days: date, instrument_id: int = 1, title: str = "x"):
    return [(0, instrument_id, title, day) for day in days]


SESSIONS = weekdays(date(2016, 1, 4), 30)  # sessions[4] Fri 01-08, [24] Fri 02-05
S = 24


def quiet(news, s=S, sessions=SESSIONS, instrument_id=1) -> bool:
    ctx = context_for(sessions=sessions, news=news)
    return tool.no_news_20(ctx, instrument_id, s)


def test_no_news_20_window_by_hand():
    """AB2 第 2 點, 第二十輪實作釋義: (session T − 20, T] by calendar day."""

    t, before = SESSIONS[S], SESSIONS[S - 20]
    assert (before, t) == (date(2016, 1, 8), date(2016, 2, 5))
    assert quiet([])
    assert quiet(news_on(before))  # T − 20 itself is out
    assert quiet(news_on(before - timedelta(days=3)))
    assert not quiet(news_on(date(2016, 1, 9)))  # the weekend after it is in
    assert not quiet(news_on(date(2016, 1, 10)))
    assert not quiet(news_on(SESSIONS[S - 19]))
    assert not quiet(news_on(t))  # T itself (after the close too) is in
    assert quiet(news_on(t + timedelta(days=1)))  # after T, its weekend too
    assert quiet(news_on(t + timedelta(days=2), SESSIONS[S + 1]))
    # another instrument's news does not count
    assert quiet(news_on(t, instrument_id=2))
    # any title; several on one day once
    assert not quiet(news_on(t, title="") + news_on(t, title="庫藏股"))
    ctx = context_for(sessions=SESSIONS, news=news_on(t, t, t - timedelta(days=1)))
    assert tool.news_days(ctx) == {1: [t - timedelta(days=1), t]}


def test_no_news_20_counts_holidays_and_the_market_sessions():
    """A holiday's announcement is in; the window counts the market's
    sessions, not the item's bars (a suspension does not widen it)."""

    holiday = date(2016, 1, 20)
    sessions = [d for d in weekdays(date(2016, 1, 4), 31) if d != holiday]
    s = sessions.index(date(2016, 2, 5))
    assert sessions[s - 20] == date(2016, 1, 7)
    assert not quiet(news_on(holiday), s=s, sessions=sessions)
    assert not quiet(news_on(date(2016, 1, 8)), s=s, sessions=sessions)
    assert quiet(news_on(date(2016, 1, 7)), s=s, sessions=sessions)
    # fewer than 20 sessions before T: from the first one
    assert not quiet(news_on(SESSIONS[0]), s=5)
    assert quiet(news_on(SESSIONS[0] - timedelta(days=1)), s=5)


def test_ab2_plan_uses_t_s_session_and_ranks_momentum_small_first(monkeypatch):
    """AB2 第 2～5、7 點: the members with no_news_20 on T's session (not the
    item's bar), momentum_20 small first, missing last, ties by the hash, the
    first 20; fewer than 20: what qualifies; the counts, the overlaps and the
    later delisted names by year."""

    sessions = weekdays(date(2016, 1, 4), 30)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    seen = []

    def no_news(ctx, instrument_id, s):
        seen.append(s)
        return instrument_id % 6 != 0 if s == 1 else instrument_id <= 5

    values = {i: (None if i % 5 == 0 else float(i % 4) - 1.0) for i in items}
    monkeypatch.setattr(tool, "no_news_20", no_news)
    monkeypatch.setattr(
        r5, "momentum_20", lambda ctx, item, at: values[item.instrument_id]
    )
    monkeypatch.setattr(tool, "v2_names", lambda ctx, day, members: {1, 2, 7})
    monkeypatch.setattr(tool, "y4_names", lambda ctx, day, members: set())
    statuses = {i: "delisted" for i in (2, 3, 12)}
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=Counter(), statuses=statuses, v2=None)  # fmt: skip
    planned = tool.plan_ab2(ctx, tool.HYPOTHESES["AB2"], 2, 3)
    assert set(seen) == {1, 2}  # the sessions, the members' bar is 0
    day = sessions[1]
    found = [i for i in items if i % 6 != 0]
    order = sorted(
        found, key=lambda i: (values[i] is None, values[i] or 0, pr.tie_break(day, i))
    )
    assert planned.picks[2] == order[:20]
    assert planned.picks[3] == sorted(
        range(1, 6),
        key=lambda i: (values[i] is None, values[i] or 0, pr.tie_break(sessions[2], i)),
    )  # 5 qualify: 5 names, the rest in cash
    chosen = order[:20]
    assert planned.overlap["AB2_V2"]["2016"][0] == pytest.approx(
        len({1, 2, 7} & set(chosen)) / 20
    )
    assert planned.overlap["AB2_Y4"] == {}
    gone = len({2, 3, 12} & set(chosen)) + 2  # 2 and 3 on the second day
    assert planned.delisted == {"2016": [25, gone]}
    year = planned.coverage["2016"]
    assert (year["days"], year["members"], year["hits"]) == (2, 60, 25 + 5)
    assert year["hits_delisted"] == 2 + 2  # 12 has news on the first day
    assert year["momentum_missing"] == sum(1 for i in found if values[i] is None) + 1
    assert (year["names"], year["short_days"], year["empty_days"]) == (25, 1, 0)
    assert planned.rows[0]["no_news_20"] is True
    summary = tool.delisted_summary(planned.delisted)
    assert summary["share"] == pytest.approx(gone / 25)
    assert summary["years"]["2016"] == {"names": 25, "delisted": gone,
                                        "share": pytest.approx(gone / 25)}  # fmt: skip


def test_news_by_year_counts_rows_instruments_and_the_later_delisted():
    news = [(0, 1, "a", date(2013, 5, 1)), (0, 1, "b", date(2013, 5, 1)),
            (0, 2, "c", date(2013, 7, 1)), (0, 2, "d", date(2014, 1, 3))]  # fmt: skip
    ctx = context_for(news=news, statuses={2: "delisted"})
    assert tool.news_by_year(ctx) == {
        "2013": {"rows": 3, "instruments": 2, "delisted": 1},
        "2014": {"rows": 1, "instruments": 1, "delisted": 1},
    }


def test_ab2_rotates_20_accounts_and_the_population_too(monkeypatch):
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    monkeypatch.setattr(pr, "simulate", simulate)
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]})
    _m, _p, reference = tool.engines(SimpleNamespace(quote=None), "AB2", planned, 1, 5)
    assert calls == [({1: [1]}, 20, 20), ({1: [1, 2]}, 20, None)] and reference is None


def test_ab2_k20_accounts_by_hand():
    prices = {(i, s): (10.0, 10.0) for i in (1, 2) for s in range(1, 30)}
    mine, population, _ = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "AB2",
        SimpleNamespace(picks={1: [1], 2: [2], 21: [1]},
                        population={1: [1, 2], 2: [1, 2]}), 1, 29,
    )  # fmt: skip
    first, second, third = mine.positions[:3]
    assert (first.bought, first.due, second.bought, second.due) == (1, 20, 2, 21)
    assert first.cost == pytest.approx(1 / 20 / 20) == second.cost
    assert first.account != second.account
    assert third.account == first.account  # the account is reused after 20
    assert population.positions[0].cost == pytest.approx(1 / 20 / 2)


def test_the_starts_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2007, 11, 26), 4800)  # to 2026
    first, last = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["AB2"])
    assert sessions[first - 1] == weekdays(OTC, 21)[-1]
    assert sessions[last] == date(2019, 12, 31)
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["AB1"])
    assert sessions[first - 1] == date(2014, 3, 31)
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["AB1"])
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["AB2"])
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
        (3.376, "前瞻觀察"),  # round 19's threshold is not this round's
        (3.383, "前瞻觀察"),
        (3.384, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_384(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

DAYS = 700
STOCKS = range(1, 25)
# the last bar's index; 25 EPS only, 26 every field
DELISTED = {25: 570, 26: 450}
TRANSFERRED = 27  # EPS only
INDEX_ID = 90
HOLDING = 9  # report_format holding: 營業外損益, never an op_margin_4q
NO_REVENUE = 13  # cumulative revenue 0: Σrev ≤ 0
GAP = 11  # no 營業利益（損失） for 2016 Q2: q − 3 .. q through 2016 Q3 missing
NEWS = {3: 15, 6: 25, 25: 10}  # an announcement every n sessions (25 too)


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), DAYS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def index_level(t: int) -> float:
    return 9000.0 * (1 + 0.004 * math.sin(t * 0.7)) + 5 * t


def path(i: int) -> list[tuple[float, float, float, float]]:
    out, previous = [], 50.0 + i
    for t in range(DAYS):
        m = index_level(t) / index_level(t - 1) - 1 if t else 0.0
        drift = (i - 12) * 0.0002 + 0.7 * m
        close = round(previous * (1 + drift + 0.004 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        high = round(max(open_, close) * 1.004, 2)
        low = round(min(open_, close) * 0.996, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def exchange_of(i: int) -> str:
    return "TWSE" if i % 2 else "TPEx"


def margin_of(i: int) -> float:
    """op_margin_4q of i: (i − 12) ÷ 100, rising with i."""

    return (i - 12) / 100


def fundamental_rows() -> list[dict]:
    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        for year in range(2012, 2019):
            for q, (end, due) in enumerate(zip(ENDS(year), DUES(year)), 1):
                eps = 1.0 * q
                revenue = 0.0 if i == NO_REVENUE else 1000.0 * (1 + i / 100) * q
                data: dict = {}
                if i not in (25, TRANSFERRED):  # the XBRL rows: EPS only
                    data = {"report_format": "general", tool.REVENUE: f"{revenue:,.3f}",
                            tool.OPERATING: f"{revenue * margin_of(i):,.3f}",
                            "營業毛利（毛損）淨額": f"{revenue * 0.3:,.3f}",
                            "本期淨利（淨損）": f"{revenue * 0.08:,.3f}",
                            r18.NONOP: f"{(i - 12) * 5.0 * q:,.3f}"}  # fmt: skip
                    if i == GAP and end == date(2016, 6, 30):
                        del data[tool.OPERATING]
                    if i == HOLDING:
                        data = {"report_format": "holding", "營業外損益": "12",
                                "淨收益": f"{revenue:,.3f}"}  # fmt: skip
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": due, "eps": eps, "data_json": data,
                             "source": "test"})  # fmt: skip
    return rows


def event_rows() -> list[dict]:
    days = trading_days()
    rows = []
    for i, step in NEWS.items():
        for t in range(3, DAYS, step):
            if t > DELISTED.get(i, DAYS):
                break
            rows.append({"instrument_id": i, "event_date": days[t],
                         "event_type": ex.MOPS_EVENT_TYPE, "title": f"公告 {t}",
                         "source": ex.MOPS_SOURCE})  # fmt: skip
    # a Saturday's announcement and another source's row
    rows.append(
        {
            "instrument_id": 1,
            "event_date": date(2017, 5, 13),
            "event_type": ex.MOPS_EVENT_TYPE,
            "title": "週六",
            "source": ex.MOPS_SOURCE,
        }
    )
    rows.append(
        {
            "instrument_id": 2,
            "event_date": date(2017, 5, 12),
            "event_type": "treasury_stock",
            "title": "其他",
            "source": "other",
        }
    )
    return rows


def member_rows() -> list[list]:
    day = trading_days()[0].isoformat()
    out = []
    for code, ids in (("24", range(1, 9)), ("25", range(9, 17))):
        label = im.GROUP_LABELS["TWSE"][code]
        out += [[day, "TWSE", code, "", label, im.group_id(label), f"S{i}", f"N{i}",
                 im.retroactive("TWSE", code, day)] for i in ids]  # fmt: skip
    return sorted(out)


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
        bars = []
        for i in ids:
            prices = path(i)
            for t, day in enumerate(days):
                if t > DELISTED.get(i, DAYS):
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
        db.execute(insert(Event), event_rows())
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round20")
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


def test_one_panel_serves_the_statements_the_news_and_the_overlaps(loaded):
    assert loaded.groups.market is loaded.base.market
    for part in (loaded.p2, loaded.v2, loaded.y4):
        assert part.base is loaded.base
    assert loaded.y4.groups is loaded.groups
    assert loaded.p2.statements is loaded.statements
    assert set(loaded.load_seconds) == {"panel", "statements", "lists", "members"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    row = loaded.statements[1][0]
    assert (row.operating, row.revenue) == (
        pytest.approx(1010.0 * margin_of(1)),
        1010.0,
    )
    assert loaded.statements[25][0].operating is None  # EPS only
    assert loaded.statements[HOLDING][0].operating is None  # under another name
    assert loaded.nonop_statements[1][0].nonop == -55.0  # G1's own reading
    end = trading_days()[499]
    assert all(d <= end for item in loaded.panel.series.values() for d in item.dates)
    assert all(r.announced <= end for rows in loaded.statements.values() for r in rows)
    listed = {(i, day) for _at, i, _t, day in loaded.base.announcements}
    assert (1, date(2017, 5, 13)) in listed  # the Saturday's date, not Monday's
    assert all(i != 2 for i, _d in listed)  # another source's row is not read
    assert all(day <= end for _i, day in listed)


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    series = loaded.panel.series
    day, quarter = date(2017, 5, 15), date(2017, 3, 31)
    for i in (1, 5, 12, 20, 26):
        got = tool.op_margin_4q(loaded, series[i], day, quarter)
        assert got.value == pytest.approx(margin_of(i), abs=1e-9), i
    assert tool.op_margin_4q(loaded, series[12], day, quarter).value == 0.0
    assert tool.op_margin_4q(loaded, series[HOLDING], day, quarter).reason == "format"
    assert (
        tool.op_margin_4q(loaded, series[NO_REVENUE], day, quarter).reason == "revenue"
    )
    assert tool.op_margin_4q(loaded, series[25], day, quarter).reason == "fields"
    # GAP: 2016 Q2 is read until q − 3 is 2016 Q4 (q = 2017 Q3)
    assert tool.op_margin_4q(loaded, series[GAP], date(2017, 8, 14),
                             date(2017, 6, 30)).reason == "fields"  # fmt: skip
    assert tool.op_margin_4q(loaded, series[GAP], date(2017, 11, 14),
                             date(2017, 9, 30)).reason is None  # fmt: skip
    assert tool.fields_missing(loaded, series[25], day, quarter)
    assert not tool.fields_missing(loaded, series[26], day, quarter)
    s = days.index(date(2017, 5, 15))  # 2017-05-13 (Saturday) is in its window
    assert not tool.no_news_20(loaded, 1, s)
    assert tool.no_news_20(loaded, 2, s)


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[479]),
            # AB1's 2017-11-14 event
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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "AB1,AB2"
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
        "round20_research", "1057", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (20, 2, 70)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.384)
    assert report["read_until"] == days[479].isoformat()
    assert report["members_sha256"] == ms.MEMBERS_SHA256
    hyp = report["hypotheses"]
    assert [hyp[n]["engine"] for n in NAMES] == ["events", "portfolio"]
    ab1, ab2 = hyp["AB1"], hyp["AB2"]
    assert ab1["reference_excess"]["days"] > 0
    assert ab1["names"] == 20 and ab1["valued"] > 20
    assert ab1["overlap_g1"]["days"] > 0
    # no P2 list (flat margins) and no X4 list (no monthly revenue): no day
    assert ab1["overlap_p2"]["days"] == ab1["overlap_x4"]["days"] == 0
    assert ab1["industries"]["mean"] == 2.0  # the table's two industries
    assert ab2["overlap_v2"]["days"] > 0 and "overlap_y4" in ab2
    assert 0.8 < ab2["hits_share"] < 1.0
    assert ab2["delisted"]["names"] > 0 and ab2["delisted"]["delisted"] > 0
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 2 個、累計 70 個" in text and "驗證段 t ≥ 3.384" in text
    for key in ("AB1_survivor", "AB1_proxy", "AB2_survivor", "summary_only"):
        assert tool.OVERLAP_NOTE[key] in text, key
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round20_research", 20, "exploration", 1) for name in NAMES]
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
        assert tool.DEGENERATE[name] in summary and tool.LIMITS[name] in summary
        lines = summary.splitlines()
        assert (
            lines[2] == "- " + tool.OVERLAP_NOTE["summary_only"]
        )  # the report's start
    ab1_lines = (out / "AB1" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert ab1_lines[3] == tool.OVERLAP_NOTE["AB1_survivor"]
    assert ab1_lines[4] == "- " + tool.OVERLAP_NOTE["AB1_proxy"]
    ab1_text = "\n".join(ab1_lines)
    assert "超額（對對照基準，只列出）" in ab1_text
    assert tool.OVERLAP_NOTE["AB1_reference"] in ab1_text
    for key in ("AB1_P2", "AB1_G1", "AB1_X4", "AB1_listed", "AB1_industries"):
        assert tool.OVERLAP_NOTE[key] in ab1_text, key
    assert "## 每次調倉（AB1 第 8 點" in ab1_text and "## 名單涉及的產業數" in ab1_text
    ab2_lines = (out / "AB2" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert ab2_lines[3] == tool.OVERLAP_NOTE["AB2_survivor"]
    ab2_text = "\n".join(ab2_lines)
    for key in ("AB2_V2", "AB2_Y4", "AB2_listed", "AB2_delisted"):
        assert tool.OVERLAP_NOTE[key] in ab2_text, key
    assert (
        "## 名單裡之後下市的比例" in ab2_text and "`no_news_20` 成立的檔次" in ab2_text
    )
    picks = (out / "AB1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == (
        "signal_date,rank,exchange,symbol,quarter,op_margin_4q,operating_4q,revenue_4q,tie"
    )
    on = [line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")]
    assert on[:4] == ["S26", "S24", "S23", "S22"]  # op_margin_4q rises with i
    ab2_picks = (out / "AB2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert ab2_picks[0] == "signal_date,rank,exchange,symbol,no_news_20,momentum_20,tie"


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="AB2") == 2
    assert any("AB2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="AB1,G1") == 2
    assert any("G1 not registered" in line for line in refused(capsys))


def test_the_member_table_must_be_779s(copied, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ms, "MEMBERS_SHA256", "0" * 64)
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", "--coverage-only", hypotheses=None) == 2
    assert any("not the member table's" in line for line in refused(capsys))
    assert not (tmp_path / "x").exists()


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
    data["design"] = "1047"
    data["hypotheses"]["AB2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_384(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "AB1", "AB2")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("AB1", "round20_research", "finished"),
                       ("AB2", "round20_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["AB1", "AB2"]
    assert validation["min_t"] == 3.384
    for name in NAMES:
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["reason"] is None, (
            name,
            tables["reason"],
            tables["prerequisites"],
        )
        assert tables["min_t"] == 3.384
    assert validation["hypotheses"]["AB1"]["reference_excess"]["days"] > 0
    days = trading_days()
    assert validation["read_until"] == days[580].isoformat()
    ab1 = read_json(tmp_path / "validation" / "AB1" / "tables.json")
    assert ab1["window"]["first_signal"] == "2017-11-14"
    ab2 = read_json(tmp_path / "validation" / "AB2" / "tables.json")
    assert ab2["window"]["first_session"] == days[480].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.384（沒有 t 下限）" in text
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
    report = passed_report(out, tmp_path, "AB2")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[580]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["AB2"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["AB2"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "AB2" / "used" / file).is_file(), file


def test_a_failed_validation_loads_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    real_load = tool.load
    loads = []
    monkeypatch.setattr(tool, "load", lambda *a: loads.append(a[3]) or real_load(*a))
    monkeypatch.setattr(ex, "explore_judge", lambda *a, **k: ex.FORWARD_WATCH)
    assert (
        validate(db, tmp_path / "validation", passed_report(out, tmp_path, "AB1")) == 0
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
    events = [e for row in hyp["AB1"]["coverage"].values() for e in row["events"]]
    may = next(e for e in events if e["signal_date"] == "2017-05-15")
    # HOLDING; 25, 27 (EPS only) and GAP; NO_REVENUE
    assert (may["format"], may["fields"], may["revenue"], may["stale"]) == (1, 3, 1, 0)
    assert may["valued"] == may["members"] - 5 == 22
    assert (may["delisted"], may["delisted_missing"]) == (3, 2)  # 25, 26, 27; 26 kept
    assert (may["zero"], may["negative"]) == (1, 9)  # i = 12; i < 12 less 9 and 11
    fields = {e["signal_date"]: e["fields"] for e in events}
    # GAP: 2016 Q2 is not among 2016 Q1's 4 quarters, it is among 2016 Q2's
    assert (fields["2016-05-16"], fields["2016-08-15"]) == (2, 3)
    assert [e["signal_date"] for e in events][:2] == ["2016-03-31", "2016-05-16"]
    ab2 = hyp["AB2"]["coverage"]
    members = sum(row["members"] for row in ab2.values())
    hits = sum(row.get("hits", 0) for row in ab2.values())
    assert 0 < hits < members
    assert sum(row.get("hits_delisted", 0) for row in ab2.values()) > 0
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["AB1"] == {"plan", "op_margin_4q", "reference", "p2_order", "g1_order",
                              "x4_order"}  # fmt: skip
    assert {"plan", "no_news_20", "momentum_20", "v2_order", "y4_order"} <= seconds[
        "AB2"
    ]
    news = body["news"]
    assert sorted(news) == ["2016", "2017"]
    rows = event_rows()
    end = trading_days()[479]
    mops = [r for r in rows if r["source"] == ex.MOPS_SOURCE and r["event_date"] <= end]
    assert sum(row["rows"] for row in news.values()) == len(mops)
    assert news["2016"]["instruments"] == 3 and news["2016"]["delisted"] == 1  # 25
    columns = body["columns_2013"]
    assert sorted(columns) == ["2013-03-31", "2013-06-30", "2013-09-30", "2013-12-31"]
    general = columns["2013-03-31"]["general"]
    assert general["fields"][tool.OPERATING] == general["rows"] == 23 + 1  # 26 too
    holding = columns["2013-03-31"]["holding"]
    assert (
        holding["fields"][tool.OPERATING] == 0 and holding["fields"][tool.REVENUE] == 0
    )
    assert "淨收益" in holding["columns"]
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {
        "panel",
        "statements",
        "lists",
        "members",
    }
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "## AB1：2013 年各季的欄名" in md
    assert "最新一季不是對應的那一季" in md and "分母 ≤ 0" in md
    assert "`no_news_20` 成立的檔次" in md and "## AB2：重大訊息依年" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "AB1"])  # fmt: skip


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
    assert explore(copied, tmp_path / "out", hypotheses="AB2") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "AB2")
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
        assert explore(copied, out, hypotheses="AB2") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "AB2")
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
