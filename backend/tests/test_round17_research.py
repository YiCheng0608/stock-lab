"""tools/research/round17_research.py: the registered A1～A3 (#1008).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十七輪：A1～A3.  The features and the accounts are
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
    CorporateAction,
    Event,
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    MonthlyRevenue,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1008#issuecomment-1"
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
r7 = _tool("round7_research")
r10 = _tool("round10_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
r16 = _tool("round16_research")
tool = _tool("round17_research")
NAMES = ("A1", "A2", "A3")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 17))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    a1, a2, a3 = (h[name] for name in NAMES)
    assert (a1["engine"], a2["engine"], a3["engine"]) == (
        "events",
        "events",
        "portfolio",
    )
    assert a1["keys"] == (("net_issue", "low"),)
    assert (a1["top"], a1["hold"], a1["start"], a1["rule"]) == (
        20, "next_event", ("date", date(2014, 5, 15)), "quarterly",
    )  # fmt: skip
    assert a2["keys"] == (("sales_growth_36", "low"),)
    assert (a2["top"], a2["hold"], a2["start"], a2["rule"]) == (
        20, "next_event", ("date", date(2017, 1, 10)), "monthly",
    )  # fmt: skip
    assert a3["keys"] == (("vov_240", "low"),)
    assert (a3["top"], a3["hold"], a3["start"]) == (20, 20, ("session", OTC, 241))
    for spec in h.values():
        assert spec["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        17,
        3,
        64,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.359
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(64), 3) == 3.359
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "cbcfd002" and tool.DESIGN == "1008"
    assert (tool.NET, tool.EPS, tool.REPORT_FORMAT) == (
        "淨利（淨損）歸屬於母公司業主", "基本每股盈餘（元）", "general",
    )  # fmt: skip
    assert (tool.THOUSANDS, tool.LAG, tool.EPS_MIN, tool.SHARES_MIN) == (
        1000.0, 4, 0.5, 0.0,
    )  # fmt: skip
    assert (tool.RECENT_MONTHS, tool.BASE_MONTHS, tool.BASE_MIN) == (
        (0, 11),
        (36, 47),
        0.0,
    )
    assert (tool.VOV_RETURNS, tool.VOV_PARTS, tool.VOV_PART_RETURNS) == (240, 12, 20)
    assert (tool.PART_DDOF, tool.VOV_DDOF) == (1, 1)
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    assert ex.EVENT_DAY == 10
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool._known is r15._known
    assert "load_context" in tool.load.__code__.co_names
    assert {"load_statuses", "load_share_statements", "load_stock_dividends"} <= set(
        tool.load.__code__.co_names
    )
    assert "quarter_events" in tool.plan_a1.__code__.co_names
    assert "event_days" in tool.plan_a2.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "_revenues_known" in tool._revenue_months.__code__.co_names
    assert "_rows" in tool.load_share_statements.__code__.co_names
    assert "_plan_buyback" in tool.x8_names.__code__.co_names
    assert "_rank" in tool.x7_names.__code__.co_names
    assert "x4_names" in tool.x4_names.__code__.co_names
    assert "rank" in tool.v1_names.__code__.co_names
    assert "rank" in tool.y2_names.__code__.co_names
    assert "vol_60" in tool.plan_a3.__code__.co_names
    for plan in (tool.plan_a1, tool.plan_a2, tool.plan_a3):
        assert "r5.order_key(" in inspect.getsource(plan)


def _swap(spec_name: str, key: str, value):
    return {**tool.HYPOTHESES, spec_name: {**tool.HYPOTHESES[spec_name], key: value}}


def _other(module, name: str, key: str, value):
    return {**module.HYPOTHESES, name: {**module.HYPOTHESES[name], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1008 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.359
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.346),
        # A1: the two fields, thousands, general, the latest quarter, the
        # cumulative figures, g's window (left open, right closed, by
        # announcement_date, action_date, null as none), EPS floor, sh ≤ 0,
        # ln, small first, N 20, the next event, the reference
        (tool, "NET", "本期淨利（淨損）"),
        (tool, "EPS", "基本每股盈餘"),
        (tool, "THOUSANDS", 1.0),
        (tool, "REPORT_FORMAT", "other"),
        (tool, "LATEST_RULE", "the latest quarter with an EPS"),
        (tool, "SHARES", "single quarters' NET / EPS"),
        (tool, "LAG", 1),
        (tool, "DIVIDEND_RULE", "announcement_date(q-4) <= action_date < announcement_date(q)"),
        (tool, "DIVIDEND_RULE", "by the period ends"),
        (tool, "DIVIDEND_RULE", "a null ratio: missing"),
        (tool, "EPS_MIN", 0.4),
        (tool, "SHARES_MIN", -1.0),
        (tool, "NET_ISSUE", "sh(q) / (sh(q-4) * g) - 1"),
        (tool, "NUMBER_RULE", "float()"),
        (tool, "STATEMENT_RULE", "the rows with an EPS"),
        (tool, "A1_REFERENCE", "less every delisted instrument"),
        (tool, "HYPOTHESES", _swap("A1", "keys", (("net_issue", "high"),))),
        (tool, "HYPOTHESES", _swap("A1", "top", 19)),
        (tool, "HYPOTHESES", _swap("A1", "hold", 60)),
        (tool, "HYPOTHESES", _swap("A1", "start", ("date", date(2014, 8, 14)))),
        # A2: 12-month sums, R1, R0, the latest month, 24 months, R0 ≤ 0,
        # small first, N 20, the 10th and its roll, the reference
        (tool, "RECENT_MONTHS", (0, 12)),
        (tool, "BASE_MONTHS", (35, 46)),
        (tool, "GROWTH", "R1 / R0"),
        (tool, "LATEST_MONTH_RULE", "m: the latest month known"),
        (tool, "MONTHS_MISSING", "a missing month counts 0"),
        (tool, "BASE_MIN", -1.0),
        (tool, "MONTHLY_EVENT_RULE", "the 10th, not rolled"),
        (ex, "EVENT_DAY", 11),
        (tool, "A2_REFERENCE", "less every transferred instrument"),
        (tool, "HYPOTHESES", _swap("A2", "keys", (("sales_growth_36", "high"),))),
        (tool, "HYPOTHESES", _swap("A2", "top", 19)),
        (tool, "HYPOTHESES", _swap("A2", "start", ("date", date(2018, 1, 10)))),
        # A3: 240 returns (241 closes), 12 × 20, ddof 19 and 11, the missing
        # cases, small first, N 20, K 20
        (tool, "VOV_RETURNS", 241),
        (tool, "VOV_PARTS", 6),
        (tool, "VOV_PART_RETURNS", 40),
        (tool, "PART_DDOF", 0),
        (tool, "VOV_DDOF", 0),
        (tool, "VOV_RULE", "the parts from the newest"),
        (tool, "VOV_MISSING", "a suspended bar is skipped"),
        (tool, "HYPOTHESES", _swap("A3", "keys", (("vov_240", "high"),))),
        (tool, "HYPOTHESES", _swap("A3", "top", 19)),
        (tool, "HYPOTHESES", _swap("A3", "hold", 21)),
        (tool, "HYPOTHESES", _swap("A3", "start", ("session", OTC, 242))),
        # the three: the hash and the order, the start, the event days
        (tool, "ORDER", "high first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "SALE", "at T'+1's open"),
        (tool, "REFERENCE_STATUSES", ("delisted",)),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        (features, "SHARED_VERSION", features.SHARED_VERSION + 1),
        # the overlaps' lists
        (ex, "HYPOTHESES", _other(ex, "X8", "top", 19)),
        (ex, "BUYBACK_LOOKBACK", 10),
        (ex, "BUYBACK_NONE", ("註銷",)),
        (ex, "HYPOTHESES", _other(ex, "X7", "top", 19)),
        (ex, "HYPOTHESES", _other(ex, "X4", "top", 19)),
        (r5, "HYPOTHESES", _other(r5, "V1", "top", 19)),
        (r5, "VOL_WINDOW", 59),
        (r7, "HYPOTHESES", _other(r7, "Y2", "top", 19)),
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


# AC-1: measured on master cbcfd002 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash and its P2 row round15_research's; the
# overlaps read explore_research (X8, X7, X4), round5 (V1) and round7 (Y2).
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
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round5_research", "round7_research", "round10_research", "round15_research",
     "round16_research", None],
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


# AC-1: portfolio_research.ranking_key's source on master cbcfd002
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
    section = text.split("**第十七輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.359 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round17_research.py" in section
    assert "本輪 3 個、累計 64 個" in section


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


def context_for(
    items=(), sessions=None, statements=None, dividends=None, statuses=None
):
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
    return tool.Context(base, statements or {}, dividends or {}, statuses or {})


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


# --- A1: net_issue ----------------------------------------------------------------

ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731
DUES = lambda y: [date(y, 5, 15), date(y, 8, 14), date(y, 11, 14), date(y + 1, 3, 31)]  # noqa: E731


def share_rows(year, net, eps, fmt="general"):
    """One year's rows from the cumulative figures, as the source writes them."""

    return [
        tool.ShareStatement(due, end, fmt, n, e)
        for end, due, n, e in zip(ENDS(year), DUES(year), net, eps)
    ]


DAY, Q = date(2017, 5, 15), date(2017, 3, 31)


def issue(rows, day=DAY, quarter=Q, dividends=()):
    ctx = context_for(statements={1: rows}, dividends={1: list(dividends)})
    return tool.net_issue(ctx, make_item([10.0]), day, quarter)


def q1_rows(net_q=1800.0, eps_q=2.0, net_q4=2000.0, eps_q4=2.0):
    return [*share_rows(2016, [net_q4, 4000.0, 6000.0, 8000.0], [eps_q4, 4.0, 6.0, 8.0]),
            *share_rows(2017, [net_q], [eps_q])]  # fmt: skip


def test_net_issue_by_hand():
    """A1 第 2、3 點: sh = cumulative NET × 1,000 ÷ cumulative EPS (not single
    quarters).  Q1: 1,800 × 1,000 ÷ 2 = 900,000 against 2,000 × 1,000 ÷ 2 =
    1,000,000: ln 0.9."""

    got = issue(q1_rows())
    assert got.reason is None and got.value == pytest.approx(math.log(0.9))
    assert (got.shares_q, got.shares_q4, got.g) == (900_000.0, 1_000_000.0, 1.0)
    # Q3 from the cumulative figures: 2016 Q3 6,000 ÷ 3 → 2,000,000; 2017 Q3
    # 7,500 ÷ 3 → 2,500,000; a 25% stock dividend between: g 1.25, so
    # sh(q) = sh(q − 4) × g exactly and net_issue is 0, not missing
    rows = [*share_rows(2016, [2000.0, 4000.0, 6000.0, 8000.0], [1.0, 2.0, 3.0, 4.0]),
            *share_rows(2017, [2000.0, 5000.0, 7500.0], [1.0, 2.0, 3.0])]  # fmt: skip
    q3 = (date(2017, 11, 14), date(2017, 9, 30))
    got = issue(rows, *q3, dividends=[(date(2017, 7, 20), 0.25)])
    assert (got.value, got.reason, got.g) == (0.0, None, 1.25)
    assert (got.shares_q, got.shares_q4) == (2_500_000.0, 2_000_000.0)
    # without the dividend: ln 1.25
    assert issue(rows, *q3).value == pytest.approx(math.log(1.25))
    # the Q3 single quarter would have been 2,500 ÷ 1 → 2,500,000 too; a
    # different Q2 changes nothing (only q and q − 4 are read)
    rows2 = [r if r.period_end != date(2017, 6, 30) else replace(r, net=1.0, eps=99.0)
             for r in rows]  # fmt: skip
    assert issue(rows2, *q3).value == pytest.approx(math.log(1.25))
    # same shares, no dividend: 0
    assert issue(q1_rows(net_q=2000.0)).value == 0.0


def test_the_stock_dividend_window_is_left_open_right_closed():
    """A1 第 3 點, 第十七輪實作釋義: (announcement_date(q − 4),
    announcement_date(q)] by ``action_date``; a null ratio is no dividend
    (and counted); the ratios multiply."""

    after, until = date(2016, 5, 15), date(2017, 5, 15)
    g, nulls = tool.dividend_factor([(after, 0.5), (until, 0.1)], after, until)
    assert (g, nulls) == (1.1, 0)  # the left end out, the right end in
    g, _ = tool.dividend_factor([(until + timedelta(days=1), 0.5)], after, until)
    assert g == 1.0
    g, nulls = tool.dividend_factor(
        [(date(2016, 7, 1), 0.1), (date(2016, 8, 1), None), (date(2016, 9, 1), 0.2),
         (date(2016, 10, 1), 0.0), (date(2016, 11, 1), None)], after, until,
    )  # fmt: skip
    assert g == pytest.approx(1.1 * 1.2) and nulls == 2
    # through net_issue: the window is the two rows' announcement dates
    got = issue(q1_rows(), dividends=[(after, 0.5), (date(2016, 9, 1), None),
                                      (until, 0.125)])  # fmt: skip
    assert got.g == 1.125 and got.null_dividends == 1
    assert got.value == pytest.approx(math.log(900_000 / (1_000_000 * 1.125)))


def test_net_issue_is_missing_stale_format_fields_eps_or_shares():
    rows = q1_rows()
    late = [
        r if r.period_end != Q else replace(r, announced=date(2017, 5, 16))
        for r in rows
    ]
    assert issue(late).reason == "stale"  # 2017 Q1 not known on T
    assert issue(rows[:4]).reason == "stale"
    assert issue([]).reason == "stale"
    later = [
        *rows,
        tool.ShareStatement(date(2017, 5, 10), date(2017, 6, 30), "general", 1.0, 1.0),
    ]
    assert issue(later).reason == "stale"  # the latest is not the deadline's quarter
    for end in (Q, date(2016, 3, 31)):
        bank = [
            r if r.period_end != end else replace(r, report_format="bank") for r in rows
        ]
        assert issue(bank).reason == "format", end
        for name in ("net", "eps"):
            gone = [
                r if r.period_end != end else replace(r, **{name: None}) for r in rows
            ]
            assert issue(gone).reason == "fields", (end, name)
        blank = [
            r if r.period_end != end else replace(r, report_format=None) for r in rows
        ]
        assert issue(blank).reason == "fields", end  # a null report_format
    assert (
        issue([r for r in rows if r.period_end != date(2016, 3, 31)]).reason == "fields"
    )
    # |EPS| < 0.5 on either quarter; a loss of 0.5 or more counts
    for eps_q, eps_q4 in ((0.49, 2.0), (2.0, 0.49), (-0.49, 2.0), (0.0, 2.0)):
        assert issue(q1_rows(eps_q=eps_q, eps_q4=eps_q4)).reason == "eps", (
            eps_q,
            eps_q4,
        )
    got = issue(q1_rows(net_q=-500.0, eps_q=-0.5))
    assert got.value == pytest.approx(math.log(1_000_000 / 1_000_000)) == 0.0
    assert issue(q1_rows(net_q=-450.0, eps_q=-0.5)).value == pytest.approx(
        math.log(0.9)
    )
    assert issue(q1_rows(net_q=500.0, eps_q=0.5)).reason is None
    # sh ≤ 0 on either quarter (NET and EPS of opposite signs, or NET 0)
    for net_q, net_q4 in ((-100.0, 2000.0), (2000.0, -100.0), (0.0, 2000.0)):
        assert issue(q1_rows(net_q=net_q, net_q4=net_q4)).reason == "shares", (
            net_q,
            net_q4,
        )


def test_the_share_statement_reads_the_two_fields():
    parse = __import__("worker.sources", fromlist=["parse_number"]).parse_number
    data = {"report_format": "general", "淨利（淨損）歸屬於母公司業主": "1,234",
            "基本每股盈餘（元）": "(0.62)", "本期淨利（淨損）": "9"}  # fmt: skip
    row = tool.share_statement_of("2017-05-15", "2017-03-31", data, parse)
    assert (row.net, row.eps, row.report_format) == (1234.0, -0.62, "general")
    row = tool.share_statement_of(
        "2017-05-15", "2017-03-31", {"本期淨利（淨損）": "5"}, parse
    )
    assert (row.report_format, row.net, row.eps) == (None, None, None)
    row = tool.share_statement_of("2017-05-15", "2017-03-31", {**data, "基本每股盈餘（元）": "--"},
                                  parse)  # fmt: skip
    assert row.eps is None


def test_fields_missing_is_point_5s_field_case_on_the_deadlines_quarter():
    item = make_item([10.0])
    rows = q1_rows()

    def missing(rows):
        return tool.fields_missing(context_for(statements={1: rows}), item, DAY, Q)

    assert not missing(rows)
    assert not missing(q1_rows(eps_q=0.1))  # the EPS floor is not a missing field
    assert not missing(q1_rows(net_q=-100.0))  # nor sh ≤ 0
    assert not missing(
        [replace(r, report_format="bank") for r in rows]
    )  # nor the format
    later = [
        *rows,
        tool.ShareStatement(date(2017, 5, 10), date(2017, 6, 30), "general", 1.0, 1.0),
    ]
    assert not missing(later)  # nor the stale quarter
    assert missing(rows[:4])  # q not known on T: its fields missing
    assert missing(
        [
            tool.ShareStatement(r.announced, r.period_end, None, None, r.eps)
            for r in rows
        ]
    )
    assert missing(
        [r if r.period_end != date(2016, 3, 31) else replace(r, eps=None) for r in rows]
    )
    assert tool.fields_missing(context_for(), item, DAY, Q)


def test_a1_ranks_small_first_with_its_reference_and_x8(monkeypatch):
    """A1 第 6、8、9 點, 第十七輪實作釋義: small first, the missing last; a
    delisted or transferred member missing a field is out of the reference,
    one with every field or an active one missing a field stays; X8's list
    on the same T; each rebalance's names."""

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
    values = {1: None, 2: 0.01, 3: None, 4: None, 5: -0.03, 6: 0.0}
    monkeypatch.setattr(tool, "net_issue", lambda ctx, item, day, q: tool.NetIssue(
        values[item.instrument_id], None if values[item.instrument_id] is not None else "fields",
        g=1.1 if item.instrument_id == 2 else 1.0,
        null_dividends=1 if item.instrument_id == 6 else 0))  # fmt: skip
    s = [
        sessions.index(d) + 1
        for d in (date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15))
    ]
    calls = []

    def x8(ctx, first, last):
        calls.append((first, last))
        return {s[0]: [5, 9], s[2]: [4]}

    monkeypatch.setattr(tool, "x8_names", x8)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses)  # fmt: skip
    first = s[0]
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_a1(ctx, tool.HYPOTHESES["A1"], first, last)
    assert calls == [(first, last)]  # once per segment
    assert planned.reference[s[0]] == [1, 2, 5, 6]
    assert planned.population[s[0]] == [1, 2, 3, 4, 5, 6]
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    tail = sorted((1, 3, 4), key=lambda i: pr.tie_break(date(2016, 3, 31), i))
    assert planned.picks[s[0]] == [5, 6, 2, *tail]  # −0.03, 0, 0.01, then the missing
    event = planned.rebalances[0]
    assert (event["delisted"], event["delisted_missing"]) == (3, 2)
    assert (event["valued"], event["names"], event["fields"]) == (3, 6, 3)
    assert (event["g_not_1"], event["null_dividends"], event["tenfold"]) == (1, 1, 0)
    assert event["x8_overlap"] == pytest.approx(1 / 6)
    assert planned.rebalances[1]["x8_overlap"] is None  # X8 has no list: not counted
    assert planned.overlap["A1_X8"] == {"2016": [pytest.approx(1 / 6)] * 2}
    year = planned.coverage["2016"]
    assert (year["delisted"], year["delisted_missing"], year["valued"]) == (9, 6, 9)
    assert planned.rows[0]["net_issue"] == -0.03 and planned.rows[0]["g"] == 1.0


def test_x8s_list_is_explore_researchs_own_once_per_segment(monkeypatch):
    seen = []

    def buyback(base, spec, first, last, out):
        seen.append((spec["top"], first, last, type(out).__name__))
        out.picks = {first: [1]}
        return out

    monkeypatch.setattr(ex, "_plan_buyback", buyback)
    ctx = SimpleNamespace(base=None, x8={}, seconds=Counter())
    assert tool.x8_names(ctx, 3, 9) == {3: [1]}
    assert tool.x8_names(ctx, 3, 9) == {3: [1]}
    assert seen == [(20, 3, 9, "Plan")] and "x8_order" in ctx.seconds


def test_the_event_account_sells_at_the_next_event_days_close():
    """「K2 的賣出時點」(A1, A2): T′'s close, the new list at T′+1; fewer
    than 20 cash; T′ suspended or locked: sold at the next open, its cash in
    that day's buys; the population and the reference 1/n of the cash."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              reference={1: [3], 4: [3]}, dues={1: 3, 4: 8})  # fmt: skip
    for name in ("A1", "A2"):
        mine, population, reference = tool.engines(
            SimpleNamespace(quote=quote_of(prices)), name, planned, 1, 7
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

        mine = tool.engines(SimpleNamespace(quote=on), "A1", planned, 1, 7)[0]
        first, second = mine.positions
        assert (first.sold, first.how) == (4, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)


@pytest.mark.parametrize("name", ["A1", "A2"])
def test_invested_shares_and_the_excess_over_the_reference_by_hand(monkeypatch, name):
    """A1 第 8、9 點, A2 第 7、8 點: one account; the reference on the same
    rule and event days; each rebalance's invested share at its T+1 close."""

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
    monkeypatch.setattr(tool, f"plan_{name.lower()}", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), name, "exploration")
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


# --- A2: sales_growth_36 ----------------------------------------------------------


def month_of(index: int) -> date:
    """2013-01 is 0."""

    return date(2013 + index // 12, index % 12 + 1, 1)


def revenue_item(values: dict[int, float | None], announced=None) -> lib.Series:
    """Monthly revenues by month index, each announced on the next month's 10th."""

    item = make_item([10.0])
    rows = []
    for index, revenue in sorted(values.items()):
        month = month_of(index)
        due = (announced or {}).get(index) or month_of(index + 1).replace(day=10)
        rows.append((due, month, revenue, None))
    item.revenues = sorted(rows, key=lambda row: (row[0], row[1]))
    return item


T2 = date(2017, 3, 10)  # m = 2017-02 = index 49; R1 38..49, R0 2..13
M = 49


def growth_values(recent=150.0, base=100.0, other=999.0) -> dict[int, float]:
    values = {}
    for index in range(0, M + 1):
        if M - 11 <= index <= M:
            values[index] = recent
        elif M - 47 <= index <= M - 36:
            values[index] = base
        else:
            values[index] = other
    return values


def test_sales_growth_36_by_hand():
    """A2 第 2 點: R1 = m − 11 .. m, R0 = m − 47 .. m − 36, the 12-month sums:
    (12 × 150) ÷ (12 × 100) − 1 = 0.5; the months between and before are not
    read."""

    assert (month_of(M), month_of(M - 11), month_of(M - 36), month_of(M - 47)) == (
        date(2017, 2, 1), date(2016, 3, 1), date(2014, 2, 1), date(2013, 3, 1),
    )  # fmt: skip
    got = tool.sales_growth_36(revenue_item(growth_values()), T2)
    assert (got.value, got.reason, got.month) == (pytest.approx(0.5), None, "2017-02")
    assert (got.r1, got.r0) == (1800.0, 1200.0)
    for index in (M - 12, M - 35, M - 48, 0):
        values = growth_values()
        values[index] = 5.0
        assert tool.sales_growth_36(revenue_item(values), T2).value == pytest.approx(
            0.5
        )
    values = growth_values()
    values[M] = 270.0  # R1 = 11 × 150 + 270
    assert tool.sales_growth_36(revenue_item(values), T2).value == pytest.approx(
        1920 / 1200 - 1
    )
    values = growth_values()
    values[M - 47] = 220.0  # R0 = 11 × 100 + 220
    assert tool.sales_growth_36(revenue_item(values), T2).value == pytest.approx(
        1800 / 1320 - 1
    )
    # R1 = R0: exactly 0, ranked by its value
    got = tool.sales_growth_36(revenue_item(growth_values(recent=100.0)), T2)
    assert (got.value, got.reason) == (0.0, None)


def test_sales_growth_36_is_missing_stale_a_month_or_r0():
    values = growth_values()
    del values[M]  # the latest known month is 2017-01
    assert tool.sales_growth_36(revenue_item(values), T2).reason == "stale"
    late = revenue_item(growth_values(), announced={M: date(2017, 3, 11)})
    assert tool.sales_growth_36(late, T2).reason == "stale"  # m not known on T
    assert tool.sales_growth_36(late, date(2017, 3, 13)).value == pytest.approx(0.5)
    assert tool.sales_growth_36(revenue_item({}), T2).reason == "stale"
    for index in (M - 11, M - 5, M - 36, M - 47):
        values = growth_values()
        del values[index]
        assert tool.sales_growth_36(revenue_item(values), T2).reason == "months", index
        values = growth_values()
        values[index] = None  # a null revenue is no revenue
        assert tool.sales_growth_36(revenue_item(values), T2).reason == "months", index
    for base in (0.0, -10.0):
        got = tool.sales_growth_36(revenue_item(growth_values(base=base)), T2)
        assert got.reason == "base", base
    # a later month known (T in April) moves m
    assert (
        tool.sales_growth_36(revenue_item(growth_values()), date(2017, 4, 10)).reason
        == "stale"
    )


def test_months_missing_is_point_3s_month_case_with_the_month_before_t():
    assert not tool.months_missing(revenue_item(growth_values()), T2)
    assert not tool.months_missing(
        revenue_item(growth_values(base=0.0)), T2
    )  # R0 ≤ 0 not
    values = growth_values()
    del values[M]
    assert tool.months_missing(revenue_item(values), T2)  # m itself is needed
    values = growth_values()
    del values[M - 40]
    assert tool.months_missing(revenue_item(values), T2)
    values = growth_values()
    del values[M - 20]  # not one of the 24
    assert not tool.months_missing(revenue_item(values), T2)
    assert tool.months_missing(revenue_item({}), T2)


def test_the_monthly_event_days_roll_to_the_next_session():
    """A2's event days are X7's: the 10th, a holiday or weekend rolled to the
    next session; the validation's first is 2020-01-10."""

    sessions = weekdays(date(2016, 8, 1), 60)
    days = [sessions[at] for at in ex.event_days(sessions)]
    assert days == [
        date(2016, 8, 10),
        date(2016, 9, 12),
        date(2016, 10, 10),
    ]  # 09-10 Saturday
    holiday = [d for d in sessions if d != date(2016, 10, 10)]
    assert [holiday[at] for at in ex.event_days(holiday)][2] == date(2016, 10, 11)


def test_a2_ranks_small_first_with_its_reference_x7_x4_and_revenue_yoy(monkeypatch):
    sessions = weekdays(date(2017, 1, 2), 80)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 7)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    statuses = {1: "active", 2: "transferred", 3: "delisted", 4: "delisted", 5: "active",
                6: "active"}  # fmt: skip
    gone = {1, 3, 4}
    monkeypatch.setattr(
        tool, "months_missing", lambda item, day: item.instrument_id in gone
    )
    values = {1: None, 2: 0.2, 3: None, 4: 0.5, 5: -0.4, 6: 0.0}
    monkeypatch.setattr(tool, "sales_growth_36", lambda item, day: tool.Growth(
        values[item.instrument_id], None if values[item.instrument_id] is not None else "months"))  # fmt: skip
    monkeypatch.setattr(tool, "x7_names", lambda ctx, day, members: {5, 4})
    monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: set())
    yoy = {1: 0.1, 2: 0.3, 3: None, 4: 0.2, 5: -0.1, 6: None}
    monkeypatch.setitem(
        ex.FEATURES, "revenue_yoy", lambda c, item, at: yoy[item.instrument_id]
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses, base=None)  # fmt: skip
    s = [sessions.index(d) + 1 for d in (date(2017, 1, 10), date(2017, 2, 10), date(2017, 3, 10),
                                          date(2017, 4, 10))]  # fmt: skip
    first, last = s[0], sessions.index(date(2017, 3, 31))
    planned = tool.plan_a2(ctx, tool.HYPOTHESES["A2"], first, last)
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    tail = sorted((1, 3), key=lambda i: pr.tie_break(date(2017, 1, 10), i))
    assert planned.picks[s[0]] == [5, 6, 2, 4, *tail]
    assert planned.reference[s[0]] == [
        1,
        2,
        5,
        6,
    ]  # 3 and 4 (delisted, a month missing) out
    event = planned.rebalances[0]
    assert (event["delisted"], event["delisted_missing"], event["valued"]) == (3, 2, 4)
    assert event["x7_overlap"] == pytest.approx(2 / 6) and event["x4_overlap"] is None
    assert event["revenue_yoy"] == pytest.approx(
        statistics.fmean([0.1, 0.3, 0.2, -0.1])
    )
    assert planned.overlap["A2_X4"] == {}
    assert planned.means["2017"][0] == pytest.approx(0.125)
    assert (
        planned.rows[0]["sales_growth_36"] == -0.4
        and planned.rows[0]["revenue_yoy"] == -0.1
    )


def test_x7_and_x4_names_are_explore_researchs_on_the_same_t(monkeypatch):
    day = date(2017, 3, 10)
    rows = [(i, {}, "") for i in range(30, 0, -1)]
    calls = []
    monkeypatch.setattr(
        ex, "_rank", lambda base, spec, d, m: calls.append((spec, d)) or (rows, {})
    )
    ctx = SimpleNamespace(seconds=Counter(), base=None)
    assert tool.x7_names(ctx, day, []) == set(range(30, 10, -1))
    assert calls == [(ex.HYPOTHESES["X7"], day)] and "x7_order" in ctx.seconds
    monkeypatch.setattr(r14, "x4_names", lambda *a: {2})
    assert tool.x4_names(None, day, []) == {2}


# --- A3: vov_240 ------------------------------------------------------------------


def closes_of(returns: list[float], start: float = 10.0) -> list[float]:
    out = [start]
    for r in returns:
        out.append(out[-1] * (1 + r))
    return out


def vov(closes, at=None, suspended=()):
    item = make_item(closes, suspended=suspended)
    at = len(closes) - 1 if at is None else at
    return tool.vov_240(context_for(), item, at)


def wiggle(k: int) -> float:
    return 0.01 * math.sin(k * 1.7) + 0.004 * (k % 13 - 6) / 6 * (1 + k // 20)


def test_vov_240_by_hand():
    """A3 第 1、2 點: 240 returns in 12 parts of 20 from the oldest; s_j with
    19 degrees of freedom; their sample standard deviation (11) over their
    mean."""

    returns = [wiggle(k) for k in range(240)]
    closes = closes_of(returns)
    actual = [closes[k + 1] / closes[k] - 1 for k in range(240)]
    s = [statistics.stdev(actual[20 * j : 20 * j + 20]) for j in range(12)]
    expected = statistics.stdev(s) / statistics.fmean(s)
    got = vov(closes)
    assert got.reason is None and got.value == pytest.approx(expected, rel=1e-12)
    assert len(set(round(v, 12) for v in s)) == 12  # the parts differ
    # bars before at − 240 are not read
    assert vov([99.0, 1.0, *closes]).value == pytest.approx(expected, rel=1e-12)
    # the order of the parts does not matter, a part's own returns do
    swapped = actual[20:40] + actual[:20] + actual[40:]
    assert vov(closes_of(swapped)).value == pytest.approx(expected, rel=1e-9)
    # the ddof: 11 for the s_j, not 12
    population = statistics.pstdev(s) / statistics.fmean(s)
    assert got.value == pytest.approx(population * math.sqrt(12 / 11), rel=1e-12)


def test_vov_240_is_0_when_the_parts_are_equal_and_missing_otherwise():
    flat = [10.0] * 241
    assert vov(flat).reason == "zero"  # every s_j 0: the mean is 0
    pattern = [100.0, 101.0] * 120 + [100.0]  # every part the same 20 returns
    got = vov(pattern)
    assert (got.value, got.reason) == (0.0, None)
    assert vov(pattern[:240]).reason == "short"  # 240 closes
    assert vov(pattern, at=239).reason == "short"
    for bar in (0, 120, 240):
        assert vov(pattern, suspended=(bar,)).reason == "suspended", bar
    assert vov([100.0, *pattern], suspended=(0,)).value == 0.0  # before at − 240
    for bar in (0, 240):
        for bad in (0.0, -1.0, NAN):
            closes = list(pattern)
            closes[bar] = bad
            assert vov(closes).reason == "price", (bar, bad)
    # one flat part among moving ones: its s_j is 0, the mean is not
    returns = [wiggle(k) for k in range(240)]
    returns[100:120] = [0.0] * 20
    assert vov(closes_of(returns)).value > 0


def test_the_part_deviations_are_each_bars_own_20_returns():
    returns = [wiggle(k) for k in range(60)]
    closes = closes_of(returns)
    closes[30] = 0.0
    parts = tool.part_deviations(make_item(closes))
    assert all(math.isnan(parts[k]) for k in range(20))
    actual = [closes[k + 1] / closes[k] - 1 for k in range(20)]
    assert parts[20] == pytest.approx(statistics.stdev(actual), rel=1e-12)
    assert all(math.isnan(parts[k]) for k in range(30, 51))  # close 30 in k − 20 .. k
    assert not math.isnan(parts[51])


def test_a3_rotates_20_accounts_and_the_population_too(monkeypatch):
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    monkeypatch.setattr(pr, "simulate", simulate)
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]})
    _m, _p, reference = tool.engines(SimpleNamespace(quote=None), "A3", planned, 1, 5)
    assert calls == [({1: [1]}, 20, 20), ({1: [1, 2]}, 20, None)] and reference is None


def test_a3_k20_accounts_by_hand():
    prices = {(i, s): (10.0, 10.0) for i in (1, 2) for s in range(1, 30)}
    mine, population, _ = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "A3",
        SimpleNamespace(picks={1: [1], 2: [2]}, population={1: [1, 2], 2: [1, 2]}), 1, 29,
    )  # fmt: skip
    first, second = mine.positions[:2]
    assert (first.bought, first.due, second.bought, second.due) == (1, 20, 2, 21)
    assert first.cost == pytest.approx(1 / 20 / 20) == second.cost
    assert first.account != second.account
    assert population.positions[0].cost == pytest.approx(1 / 20 / 2)


def test_a3_plan_ranks_small_first_overlaps_v1_y2_and_lists_vol_60(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 30)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 26)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    values = {i: (None if i <= 3 else float(i % 5)) for i in items}
    monkeypatch.setattr(tool, "vov_240", lambda ctx, item, at: tool.Vov(
        values[item.instrument_id], None if values[item.instrument_id] is not None else "short"))  # fmt: skip
    monkeypatch.setattr(tool, "v1_names", lambda ctx, day, members: {5, 10, 1})
    monkeypatch.setattr(tool, "y2_names", lambda ctx, day, members: set())
    vols = {i: (None if i == 5 else i / 100) for i in items}
    monkeypatch.setattr(r5, "vol_60", lambda ctx, item, at: vols[item.instrument_id])
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          v1=None)  # fmt: skip
    planned = tool.plan_a3(ctx, tool.HYPOTHESES["A3"], 1, 2)
    day = sessions[0]
    order = sorted(
        items, key=lambda i: (values[i] is None, values[i] or 0, pr.tie_break(day, i))
    )
    assert planned.picks[1] == order[:20]
    assert {1, 2, 3} & set(order[:20]) == set()
    chosen = order[:20]
    assert planned.overlap["A3_V1"]["2016"][0] == pytest.approx(
        len({5, 10} & set(chosen)) / 20
    )
    assert planned.overlap["A3_Y2"] == {}
    expected = statistics.fmean(vols[i] for i in chosen if vols[i] is not None)
    assert planned.means["2016"][0] == pytest.approx(expected)
    year = planned.coverage["2016"]
    assert (year["valued"], year["missing"]["vov_240"], year["missing"]["short"]) == (
        44,
        6,
        6,
    )
    assert (
        planned.rows[0]["vov_240"] == 0.0
        and planned.rows[0]["vol_60"] == vols[order[0]]
    )


def test_v1_and_y2_names_are_the_other_tools_own(monkeypatch):
    day = date(2016, 3, 1)
    rows = [(i, {}, "") for i in range(30, 0, -1)]
    calls = []

    def ranked(name):
        def rank(ctx, spec, d, members):
            calls.append((name, spec, d))
            return SimpleNamespace(rows=rows)

        return rank

    monkeypatch.setattr(r5, "rank", ranked("V1"))
    monkeypatch.setattr(r7, "rank", ranked("Y2"))
    ctx = SimpleNamespace(seconds=Counter(), v1=None, y2=None)
    top = set(range(30, 10, -1))
    assert tool.v1_names(ctx, day, []) == top == tool.y2_names(ctx, day, [])
    assert calls == [("V1", r5.HYPOTHESES["V1"], day), ("Y2", r7.HYPOTHESES["Y2"], day)]
    assert set(ctx.seconds) == {"v1_order", "y2_order"}


def test_the_starts_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2007, 11, 26), 4800)  # to 2026
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["A3"])
    assert sessions[first - 1] == weekdays(OTC, 241)[-1]
    first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["A1"])
    assert sessions[first - 1] == date(2014, 5, 15)
    first, last = tool.segment_window(sessions, "exploration", tool.HYPOTHESES["A2"])
    assert sessions[first - 1] == date(2017, 1, 10) and sessions[last] == date(
        2019, 12, 31
    )
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["A1"])
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["A2"])
    assert sessions[first - 1] == date(2020, 1, 10)
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["A3"])
    assert sessions[first] == date(2020, 1, 2)


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
        (3.346, "前瞻觀察"),  # round 16's threshold is not this round's
        (3.358, "前瞻觀察"),
        (3.359, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_359(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 700
STOCKS = range(1, 25)
# the last bar's index (26 in the exploration, 25 in the validation); 25 EPS
# only and no revenue after 2015, 26 every field and month
DELISTED = {25: 570, 26: 450}
TRANSFERRED = 27  # EPS only, no revenue
INDEX_ID = 90
BANK = 9  # report_format bank: never a net_issue
SMALL_EPS = 13  # cumulative EPS 0.1 a quarter: below the floor in Q1
GAP = 11  # no revenue for 2014-06
DIVIDEND = (2, date(2016, 9, 1), 0.1)  # a stock dividend: g 1.1 on 2017-05-15
NULL_ROW = (4, date(2016, 9, 1))  # a cash-only row: a null ratio
BUYBACKS = ((1, date(2017, 5, 15)), (3, date(2016, 8, 15)))  # X8 on A1's event days


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


def shares_of(i: int, year: int) -> float:
    """i < 12 buys back (shares fall each year), i > 12 issues."""

    return 1_000_000.0 * (1 + (i - 12) * 0.01) ** (year - 2012)


def fundamental_rows() -> list[dict]:
    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        for year in range(2012, 2019):
            for q, (end, due) in enumerate(zip(ENDS(year), DUES(year)), 1):
                eps = (0.1 if i == SMALL_EPS else 1.0) * q
                net = eps * shares_of(i, year) / 1000
                data: dict = {}
                if i not in (25, TRANSFERRED):  # the XBRL rows: EPS only
                    data = {"report_format": "general", tool.NET: f"{net:,.3f}",
                            tool.EPS: f"{eps:.2f}"}  # fmt: skip
                    if i == BANK:
                        data = {"report_format": "bank", "本期淨利（淨損）": f"{net:,.3f}",
                                tool.EPS: f"{eps:.2f}"}  # fmt: skip
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": due, "eps": eps, "data_json": data,
                             "source": "test"})  # fmt: skip
    return rows


def revenue_rows() -> list[dict]:
    """2013-01 .. 2018-08, 1,000 + i·t (t the month index): the growth rises with i."""

    rows = []
    for i in (*STOCKS, *DELISTED):
        for t in range(0, 68):
            month = month_of(t)
            if (i == GAP and month == date(2014, 6, 1)) or (
                i == 25 and month.year > 2015
            ):
                continue
            rows.append({"instrument_id": i, "revenue_month": month, "revenue": 1000.0 + i * t,
                         "prior_year_revenue": 1000.0 + i * (t - 12), "source": "test",
                         "announcement_date": month_of(t + 1).replace(day=10),
                         "raw_payload_id": 1, "data_as_of": "test"})  # fmt: skip
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
            level = 9000.0 + 5 * t
            bars.append(
                {"instrument_id": INDEX_ID, "trading_date": day, "open": level,
                 "high": level, "low": level, "close": level, "adj_close": level,
                 "volume": 0, "turnover": 0.0, "turnover_status": "unknown",
                 "source": "twse_index", "is_suspended": False}
            )  # fmt: skip
        db.execute(insert(MarketBar), bars)
        db.execute(insert(FundamentalSnapshot), fundamental_rows())
        db.execute(insert(MonthlyRevenue), revenue_rows())
        db.execute(
            insert(CorporateAction),
            [
                {"instrument_id": DIVIDEND[0], "action_date": DIVIDEND[1],
                 "action_type": "stock_dividend", "stock_dividend_ratio": DIVIDEND[2],
                 "source": "test"},
                {"instrument_id": NULL_ROW[0], "action_date": NULL_ROW[1],
                 "action_type": "cash_dividend", "cash_dividend": 1.0,
                 "stock_dividend_ratio": None, "source": "test"},
            ],
        )  # fmt: skip
        db.execute(
            insert(Event),
            [
                {"instrument_id": i, "event_date": day, "event_type": "material_information",
                 "title": "本公司董事會決議買回庫藏股", "source": "mops_material_information"}
                for i, day in BUYBACKS
            ],
        )  # fmt: skip
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round17") / "stock.db")


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


def test_one_panel_serves_the_statements_the_dividends_and_the_overlaps(loaded):
    for part in (loaded.v1, loaded.y2):
        assert part.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "statements", "dividends"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    row = loaded.statements[1][0]
    assert row.net == pytest.approx(shares_of(1, 2012) / 1000) and row.eps == 1.0
    assert loaded.statements[25][0].net is None  # EPS only
    assert loaded.statements[BANK][0].net is None  # bank's net is under another name
    assert loaded.dividends[DIVIDEND[0]] == [(DIVIDEND[1], DIVIDEND[2])]
    assert loaded.dividends[NULL_ROW[0]] == [(NULL_ROW[1], None)]
    assert len(loaded.base.announcements) == len(BUYBACKS)
    end = trading_days()[499]
    assert all(d <= end for item in loaded.panel.series.values() for d in item.dates)
    assert all(r.announced <= end for rows in loaded.statements.values() for r in rows)


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    at = days.index(DAY)
    series = loaded.panel.series
    for i in (1, 5, 20):
        got = tool.net_issue(loaded, series[i], DAY, Q)
        assert got.value == pytest.approx(math.log(1 + (i - 12) * 0.01), abs=1e-5), i
    got = tool.net_issue(loaded, series[DIVIDEND[0]], DAY, Q)
    assert got.g == pytest.approx(1.1)
    assert got.value == pytest.approx(math.log(0.9 / 1.1), abs=1e-5)
    assert tool.net_issue(loaded, series[NULL_ROW[0]], DAY, Q).null_dividends == 1
    assert tool.net_issue(loaded, series[BANK], DAY, Q).reason == "format"
    assert tool.net_issue(loaded, series[SMALL_EPS], DAY, Q).reason == "eps"
    assert tool.net_issue(loaded, series[25], DAY, Q).reason == "fields"
    assert tool.fields_missing(loaded, series[25], DAY, Q)
    assert not tool.fields_missing(loaded, series[26], DAY, Q)
    july = date(2017, 7, 10)  # m = 2017-06: R0 = 2013-07 .. 2014-06
    got = tool.sales_growth_36(series[1], july)
    r1 = sum(1000.0 + t for t in range(42, 54))
    r0 = sum(1000.0 + t for t in range(6, 18))
    assert got.value == pytest.approx(r1 / r0 - 1)
    assert tool.sales_growth_36(series[GAP], july).reason == "months"
    assert tool.sales_growth_36(series[25], july).reason == "stale"
    assert tool.months_missing(series[25], july) and not tool.months_missing(
        series[26], july
    )
    assert tool.vov_240(loaded, series[1], 240).value is not None
    assert tool.vov_240(loaded, series[1], 239).reason == "short"
    assert at > 240


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[479]),
            # A1's 2017-11-14 event, A2's 2017-11-10 .. 2018-03-12
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


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "A1,A2,A3"
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
    argv = [
        "--db",
        str(db),
        "--out",
        str(out),
        "--segment",
        "validation",
        "--min-free-gb",
        "0",
    ]
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
        "round17_research", "1008", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (17, 3, 64)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.359)
    assert report["read_until"] == days[479].isoformat()
    hyp = report["hypotheses"]
    assert [hyp[n]["engine"] for n in NAMES] == ["events", "events", "portfolio"]
    assert hyp["A1"]["reference_excess"]["days"] > 0
    assert hyp["A1"]["overlap_x8"] == {"days": 2, "mean": pytest.approx(0.05)}
    assert hyp["A1"]["names"] == 20
    assert hyp["A2"]["reference_excess"]["days"] > 0
    assert "overlap_x7" in hyp["A2"] and "overlap_x4" in hyp["A2"]
    assert hyp["A2"]["revenue_yoy"]["days"] > 0
    for key in ("overlap_v1", "overlap_y2", "vol_60"):
        assert hyp["A3"][key]["days"] > 0, key
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 64 個" in text and "驗證段 t ≥ 3.359" in text
    for key in ("A1_survivor", "A2_survivor", "A2_summary_only", "A3_summary_only"):
        assert tool.OVERLAP_NOTE[key] in text, key
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round17_research", 17, "exploration", 1) for name in NAMES]
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
    a1 = (out / "A1" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert a1[2] == tool.OVERLAP_NOTE["A1_survivor"]  # the report's start
    a1 = "\n".join(a1)
    assert (
        "超額（對對照基準，只列出）" in a1 and tool.OVERLAP_NOTE["A1_reference"] in a1
    )
    assert tool.OVERLAP_NOTE["A1_X8"] in a1 and "## 每次調倉（A1 第 9 點" in a1
    a2 = (out / "A2" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert a2[2] == tool.OVERLAP_NOTE["A2_survivor"]
    assert a2[4] == "- " + tool.OVERLAP_NOTE["A2_summary_only"]
    a2 = "\n".join(a2)
    assert tool.OVERLAP_NOTE["A2_reference"] in a2 and "## 每次調倉（A2 第 8 點" in a2
    for key in ("A2_X7", "A2_X4"):
        assert tool.OVERLAP_NOTE[key] in a2
    assert "## 名單的平均 `revenue_yoy`" in a2
    a3 = (out / "A3" / "summary.md").read_text(encoding="utf-8").splitlines()
    assert a3[2] == "- " + tool.OVERLAP_NOTE["A3_summary_only"]
    a3 = "\n".join(a3)
    assert tool.OVERLAP_NOTE["A3_V1"] in a3 and "## 名單的平均 `vol_60`" in a3
    picks = (out / "A1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        picks[0]
        == "signal_date,rank,exchange,symbol,quarter,net_issue,shares_q,shares_q4,g,tie"
    )
    on = [line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")]
    assert on[:3] == ["S2", "S1", "S3"]  # S2's dividend puts it first: ln(0.9 / 1.1)
    a2_picks = (out / "A2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert a2_picks[0] == (
        "signal_date,rank,exchange,symbol,month,sales_growth_36,r1,r0,revenue_yoy,tie"
    )
    on = [line.split(",")[3] for line in a2_picks[1:] if line.startswith("2017-07-10")]
    assert on[:3] == ["S1", "S2", "S3"]  # the growth rises with i


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="A2") == 2
    assert any("A2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="A1,N2") == 2
    assert any("N2 not registered" in line for line in refused(capsys))


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
    data["design"] = "994"
    data["hypotheses"]["A2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_359(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "A1", "A2")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("A1", "round17_research", "finished"),
                       ("A2", "round17_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["A1", "A2"]
    assert validation["min_t"] == 3.359
    for name in ("A1", "A2"):
        tables = read_json(tmp_path / "validation" / name / "tables.json")
        assert tables["reason"] is None, (
            name,
            tables["reason"],
            tables["prerequisites"],
        )
        assert tables["min_t"] == 3.359
        assert validation["hypotheses"][name]["reference_excess"]["days"] > 0
    days = trading_days()
    assert validation["read_until"] == days[580].isoformat()
    a1 = read_json(tmp_path / "validation" / "A1" / "tables.json")
    assert a1["window"]["first_signal"] == "2017-11-14"
    a2 = read_json(tmp_path / "validation" / "A2" / "tables.json")
    assert [e["signal_date"] for e in a2["rebalances"]] == [
        "2017-11-10", "2017-12-11", "2018-01-10", "2018-02-12", "2018-03-12",
    ]  # fmt: skip
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.359（沒有 t 下限）" in text
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
    report = passed_report(out, tmp_path, "A3")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[580]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["A3"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["A3"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "A3" / "used" / file).is_file(), file


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
    may = next(e for row in hyp["A1"]["coverage"].values() for e in row["events"]
               if e["signal_date"] == "2017-05-15")  # fmt: skip
    assert (may["format"], may["eps"], may["fields"], may["stale"]) == (1, 1, 2, 0)
    assert may["valued"] == may["members"] - 4
    assert (may["delisted"], may["delisted_missing"]) == (3, 2)  # 25, 26, 27; 26 kept
    assert (may["g_not_1"], may["null_dividends"], may["tenfold"]) == (1, 1, 0)
    july = next(e for row in hyp["A2"]["coverage"].values() for e in row["events"]
                if e["signal_date"] == "2017-07-10")  # fmt: skip
    assert (july["stale"], july["months"], july["base"]) == (2, 1, 0)  # 25, 27; GAP
    assert (july["delisted"], july["delisted_missing"]) == (3, 2)
    a3 = hyp["A3"]["coverage"]
    assert sum(row.get("valued", 0) for row in a3.values()) > 0
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["A1"] == {"plan", "net_issue", "reference", "x8_order"}
    assert seconds["A2"] == {
        "plan",
        "sales_growth_36",
        "reference",
        "x7_order",
        "x4_order",
    }
    assert seconds["A3"] == {"plan", "vov_240", "v1_order", "y2_order"}
    columns = body["columns_2013"]
    assert sorted(columns) == ["2013-03-31", "2013-06-30", "2013-09-30", "2013-12-31"]
    general = columns["2013-03-31"]["general"]
    assert general["fields"][tool.NET] == general["rows"] == 23 + 1  # 26 too
    assert columns["2013-03-31"]["bank"]["fields"] == {tool.NET: 0, tool.EPS: 1}
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "statements", "dividends"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "## A1：2013 年各季的欄名" in md
    assert "最新一季不是對應的那一季" in md and "最新已知月份不是上個月" in md
    assert "有 `vov_240` 的檔次" in md and "g ≠ 1" in md
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "A1"])  # fmt: skip


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
    assert explore(copied, tmp_path / "out", hypotheses="A3") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "A3")
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
        assert explore(copied, out, hypotheses="A3") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "A3")
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
