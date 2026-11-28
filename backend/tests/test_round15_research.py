"""tools/research/round15_research.py: the registered P1～P3 (#984).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第十五輪：P1～P3.  The features and the accounts are
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
from dataclasses import replace
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
URL = "https://github.com/YiCheng0608/stock-lab/issues/984#issuecomment-1"
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
r8 = _tool("round8_research")
r10 = _tool("round10_research")
r14 = _tool("round14_research")
tool = _tool("round15_research")
NAMES = ("P1", "P2", "P3")
OTC = date(2007, 12, 3)


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 15))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    p1, p2, p3 = (h[name] for name in NAMES)
    assert (p1["engine"], p2["engine"], p3["engine"]) == (
        "events",
        "events",
        "portfolio",
    )
    assert p1["keys"] == (("eps_season_3y", "high"),)
    assert (p1["top"], p1["hold"], p1["start"]) == (
        20,
        "deadline",
        ("date", date(2016, 4, 15)),
    )
    assert p2["conditions"] == (("margins_up", "is", True),) and "keys" not in p2
    assert p2["order"] == "the hash only"
    assert (p2["top"], p2["hold"], p2["start"]) == (
        20,
        "next_event",
        ("date", date(2014, 5, 15)),
    )
    assert p3["keys"] == (("nr_ratio_20_240", "high"),)
    assert (p3["top"], p3["hold"], p3["start"]) == (20, 20, ("session", OTC, 261))
    for spec in h.values():
        assert spec["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        15,
        3,
        58,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.332
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(58), 3) == 3.332
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "7612838a" and tool.DESIGN == "984"
    assert tool.BUY_DAYS == (
        (3, 1, 12, -1),
        (4, 15, 3, 0),
        (7, 15, 6, 0),
        (10, 15, 9, 0),
    )
    assert r14.DEADLINES == (
        (3, 31, 12, -1),
        (5, 15, 3, 0),
        (8, 14, 6, 0),
        (11, 14, 9, 0),
    )
    assert tool.SEASON_YEARS == 3
    assert (tool.REVENUE, tool.GROSS, tool.OPERATING, tool.NET) == (
        "營業收入",
        ("營業毛利（毛損）淨額", "營業毛利（毛損）"),
        "營業利益（損失）",
        "本期淨利（淨損）",
    )
    assert (tool.REPORT_FORMAT, tool.REVENUE_MIN, tool.LAGS) == ("general", 0.0, (1, 4))
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    assert (tool.RECENT, tool.BEFORE) == (20, 240)
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert "load_context" in tool.load.__code__.co_names
    assert {"build_context", "read_members"} <= set(tool.load.__code__.co_names)
    assert "_quarter_eps" in tool.single_quarter.__code__.co_names
    assert "quarter_events" in tool.sale_days.__code__.co_names
    assert "quarter_events" in tool.plan_p2.__code__.co_names
    assert {"simulate_events", "simulate"} <= set(tool.engines.__code__.co_names)
    assert "r14.eps_turn(" in inspect.getsource(tool.k2_names)
    assert "x4_names" in tool.x4_names.__code__.co_names
    assert "rank" in tool.z4_names.__code__.co_names
    assert "r8.overnight_20(" in inspect.getsource(tool.plan_p3)
    assert "group_members" in tool.industries_of.__code__.co_names
    assert "ranking_key" in inspect.getsource(tool.plan_p1)
    assert "ranking_key" in inspect.getsource(tool.plan_p3)


def _swap(spec_name: str, key: str, value):
    return {
        **tool.HYPOTHESES,
        spec_name: {**tool.HYPOTHESES[spec_name], key: value},
    }


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#984 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.332
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.317),
        # P1: the buy days and their quarters, the sale days, 3 years, the ranks
        (
            tool,
            "BUY_DAYS",
            ((3, 1, 12, -1), (4, 15, 3, 0), (7, 15, 6, 0), (10, 16, 9, 0)),
        ),
        (
            tool,
            "BUY_DAYS",
            ((3, 1, 9, -1), (4, 15, 3, 0), (7, 15, 6, 0), (10, 15, 9, 0)),
        ),
        (
            r14,
            "DEADLINES",
            ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0)),
        ),
        (tool, "SEASON_YEARS", 2),
        (tool, "RANK_RULE", "ties by the hash"),
        (tool, "EPS_DIGITS", 4),
        (tool, "SEASON_MISSING", "a missing quarter ranked 4"),
        (tool, "WINDOW_RULE", "held to the next buy day"),
        (tool, "WINDOW_DAYS", "the sessions from T"),
        (tool, "HYPOTHESES", _swap("P1", "top", 19)),
        (tool, "HYPOTHESES", _swap("P1", "hold", "next_event")),
        (tool, "HYPOTHESES", _swap("P1", "keys", (("eps_season_3y", "low"),))),
        (tool, "HYPOTHESES", _swap("P1", "start", ("date", date(2016, 7, 15)))),
        # P2: the fields, the format, the comparisons, the reference
        (tool, "REVENUE", "營業收入合計"),
        (tool, "GROSS", ("營業毛利（毛損）",)),
        (tool, "OPERATING", "營業利益"),
        (tool, "NET", "本期稅後淨利（淨損）"),
        (tool, "REPORT_FORMAT", "other"),
        (tool, "FIELDS", ("revenue", "operating", "gross", "net")),
        (tool, "REVENUE_MIN", -1.0),
        (tool, "LAGS", (4,)),
        (tool, "NUMBER_RULE", "float()"),
        (tool, "STATEMENT_RULE", "the latest with an EPS"),
        (tool, "SALE", "at T'+1's open"),
        (tool, "REFERENCE_RULE", "less every delisted instrument"),
        (tool, "REFERENCE_STATUSES", ("delisted",)),
        (tool, "HYPOTHESES", _swap("P2", "top", 19)),
        (tool, "HYPOTHESES", _swap("P2", "hold", 60)),
        (tool, "HYPOTHESES", _swap("P2", "conditions", ())),
        (tool, "HYPOTHESES", _swap("P2", "start", ("date", date(2014, 8, 14)))),
        # P3: the reversal, the windows, the missing rules, N and K
        (tool, "RECENT", 21),
        (tool, "BEFORE", 250),
        (tool, "REVERSAL", "open[i] >= close[i - 1]"),
        (tool, "NR_MISSING", "a suspended bar is skipped"),
        (tool, "HYPOTHESES", _swap("P3", "top", 19)),
        (tool, "HYPOTHESES", _swap("P3", "hold", 60)),
        (tool, "HYPOTHESES", _swap("P3", "keys", (("nr_ratio_20_240", "low"),))),
        (tool, "HYPOTHESES", _swap("P3", "start", ("session", OTC, 262))),
        # the three: the hash and the order, the event days, the single quarters
        (tool, "ORDER", "P2 ranked by margins"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "EVENT_DAY_RULE", "the first session on or after the date"),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        (tool, "SINGLE_QUARTER", "the cumulative figure"),
        (features, "SHARED_VERSION", features.SHARED_VERSION + 1),
        # the overlaps' lists
        (
            r14,
            "HYPOTHESES",
            {**r14.HYPOTHESES, "K2": {**r14.HYPOTHESES["K2"], "top": 19}},
        ),
        (r14, "EPS_MIN", 0.01),
        (ex, "HYPOTHESES", {**ex.HYPOTHESES, "X4": {**ex.HYPOTHESES["X4"], "top": 19}}),
        (r8, "HYPOTHESES", {**r8.HYPOTHESES, "Z4": {**r8.HYPOTHESES["Z4"], "top": 19}}),
        (r8, "OVERNIGHT_TERMS", 19),
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
        "--members",
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master 7612838a before this tool existed.  forward_watch's
# F2 row reads round10_research's hash; P2's overlaps read round14's (K2) and
# explore_research's (X4), P3's round8's (Z4).
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
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name", ["round14_research", "round10_research", "round8_research", None]
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


# AC-1: portfolio_research.ranking_key's source on master 7612838a
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
    section = text.split("**第十五輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.332 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round15_research.py" in section
    assert "本輪 3 個、累計 58 個" in section


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes, opens=None, suspended=(), instrument_id=1, dates=None):
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
        item.volume.append(2_000_000.0)
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


# --- the event days ---------------------------------------------------------------


def test_the_buy_days_are_3_1_4_15_7_15_10_15_or_the_next_session():
    """P1 第 1 點: 3/1 is the year before's Q4; a date that is no session or a
    Saturday make-up session moves to the next Monday～Friday session."""

    sessions = weekdays(date(2016, 1, 4), 600)  # 2016-01-04 .. 2018-04
    found = [(sessions[at], q) for at, q in tool.buy_events(sessions)]
    assert found[:6] == [
        (date(2016, 3, 1), date(2015, 12, 31)),
        (date(2016, 4, 15), date(2016, 3, 31)),
        (date(2016, 7, 15), date(2016, 6, 30)),
        (date(2016, 10, 17), date(2016, 9, 30)),  # the 15th is a Saturday
        (date(2017, 3, 1), date(2016, 12, 31)),
        (date(2017, 4, 17), date(2017, 3, 31)),  # the 15th is a Saturday
    ]
    holiday = {date(2018, 3, 1)}
    make_up = sorted([d for d in weekdays(date(2018, 2, 26), 200) if d not in holiday]
                     + [date(2018, 7, 14)])  # fmt: skip
    found = {make_up[at]: q for at, q in tool.buy_events(make_up)}
    assert found[date(2018, 3, 2)] == date(2017, 12, 31)  # 03-01 no session
    # 07-15 is a Sunday: 07-16; a Saturday make-up session before it changes nothing
    assert found[date(2018, 7, 16)] == date(2018, 6, 30)
    saturday = sorted([*weekdays(date(2018, 7, 9), 10), date(2018, 7, 14)])
    plain = sorted([*weekdays(date(2019, 7, 8), 10), date(2019, 7, 13)])
    assert [saturday[at] for at, _q in tool.buy_events(saturday)] == [date(2018, 7, 16)]
    assert [plain[at] for at, _q in tool.buy_events(plain)] == [date(2019, 7, 15)]
    on_saturday = sorted([*weekdays(date(2017, 7, 10), 10), date(2017, 7, 15)])
    assert [on_saturday[at] for at, _q in tool.buy_events(on_saturday)] == [
        date(2017, 7, 17)  # 2017-07-15 a Saturday make-up session: skipped
    ]


def test_the_sale_days_are_round14s_deadlines_on_the_same_quarter():
    sessions = weekdays(date(2016, 1, 4), 600)
    assert tool._event_days(sessions, r14.DEADLINES) == r14.quarter_events(sessions)
    sales = tool.sale_days(sessions)
    pairs = [
        (sessions[at], sessions[sales[q]]) for at, q in tool.buy_events(sessions)[:5]
    ]
    assert pairs[:5] == [
        (date(2016, 3, 1), date(2016, 3, 31)),
        (date(2016, 4, 15), date(2016, 5, 16)),  # 05-15 is a Sunday
        (date(2016, 7, 15), date(2016, 8, 15)),  # 08-14 is a Sunday
        (date(2016, 10, 17), date(2016, 11, 14)),
        (date(2017, 3, 1), date(2017, 3, 31)),
    ]


def test_the_starts_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2007, 11, 26), 4800)  # to 2026
    for name, rule in (
        ("P1", date(2016, 4, 15)),
        ("P2", date(2014, 5, 15)),
        ("P3", weekdays(OTC, 261)[-1]),
    ):
        first, _ = tool.segment_window(sessions, "exploration", tool.HYPOTHESES[name])
        assert sessions[first - 1] == rule, name
    # 第十五輪實作釋義: the validation's first P1 window is 2020-03-02 (03-01 a
    # Sunday), P2's first event 2020-03-31; the used segment's first window 2024-10-15
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["P1"])
    assert sessions[first - 1] == date(2020, 3, 2)
    first, _ = tool.segment_window(sessions, "validation", tool.HYPOTHESES["P2"])
    assert sessions[first - 1] == date(2020, 3, 31)
    first, _ = tool.segment_window(sessions, "used", tool.HYPOTHESES["P1"])
    assert sessions[first - 1] == date(2024, 10, 15)
    # the exploration's last window 2019-10-15 .. 2019-11-14, the validation's
    # 2024-07-15 .. 2024-08-14
    sales = tool.sale_days(sessions)
    for segment, last_window in (
        ("exploration", (date(2019, 10, 15), date(2019, 11, 14))),
        ("validation", (date(2024, 7, 15), date(2024, 8, 14))),
    ):
        first, last = tool.segment_window(sessions, segment, tool.HYPOTHESES["P1"])
        inside = [
            (at, q)
            for at, q in tool.buy_events(sessions)
            if first - 1 <= at <= last - 1
        ]
        at, q = inside[-1]
        assert (sessions[at], sessions[sales[q]]) == last_window, segment


# --- P1: eps_season_3y ------------------------------------------------------------


def cumulative(year: int, own: list[float], announced=None) -> list[tuple]:
    ends = [date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)]
    dues = announced or [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                         date(year + 1, 3, 31)]  # fmt: skip
    out, total = [], 0.0
    for end, due, value in zip(ends, dues, own):
        total += value
        out.append((due, end, total))
    return out


def eps_item(rows):
    item = make_item([10.0])
    item.quarters = sorted(rows)
    return item


def test_eps_season_3y_by_hand():
    """F = 2017 Q1 (the 4/15 buy day): 2016 [1, 3, 2, 4] Q1 is 1st; 2015 [2, 2,
    1, 3] Q1 ties Q2 at 2nd-3rd, 2.5; 2014 [5, 1, 2, 3] Q1 is 4th: (1 + 2.5 + 4) ÷ 3."""

    rows = [*cumulative(2016, [1, 3, 2, 4]), *cumulative(2015, [2, 2, 1, 3]),
            *cumulative(2014, [5, 1, 2, 3])]  # fmt: skip
    got = tool.eps_season_3y(eps_item(rows), date(2017, 4, 17), date(2017, 3, 31))
    assert got.ranks == (1.0, 2.5, 4.0)
    assert got.value == pytest.approx(2.5)
    # Q2 of the same years: 3 → 3rd, 2 → 2nd-3rd (2.5), 1 → 1st
    got = tool.eps_season_3y(eps_item(rows), date(2017, 7, 17), date(2017, 6, 30))
    assert got.ranks == (3.0, 2.5, 1.0)
    # the 3/1 buy day: F = 2016's Q4, the years 2015, 2014, 2013
    rows13 = [*rows, *cumulative(2013, [4, 4, 4, 4])]  # all equal: 2.5
    got = tool.eps_season_3y(eps_item(rows13), date(2017, 3, 1), date(2016, 12, 31))
    assert got.ranks == (4.0, 3.0, 2.5)  # 2015 Q4 3 → 4th, 2014 Q4 3 → 3rd
    # negative single quarters rank the same way (the smallest first)
    neg = [*cumulative(2016, [-1, -3, 0, 2]), *cumulative(2015, [2, 2, 1, 3]),
           *cumulative(2014, [5, 1, 2, 3])]  # fmt: skip
    got = tool.eps_season_3y(eps_item(neg), date(2017, 4, 17), date(2017, 3, 31))
    assert got.ranks == (2.0, 2.5, 4.0)


def test_eps_season_3y_ties_the_single_quarters_rounded_to_6_decimals():
    """#984 決定 7095896595: cumulative 0.30, 0.70, 1.00, 1.30 are the single
    quarters 0.3, 0.39999999999999997, 0.30000000000000004, 0.30000000000000004;
    rounded to 6 decimals they are 0.3, 0.4, 0.3, 0.3: ranks 2, 4, 2, 2."""

    cum = {date(2016, 3, 31): 0.30, date(2016, 6, 30): 0.70,
           date(2016, 9, 30): 1.00, date(2016, 12, 31): 1.30}  # fmt: skip
    raw = [tool.single_quarter(cum, end) for end in sorted(cum)]
    assert raw[1] != 0.4 and raw[2] != raw[0]  # the floats themselves differ
    rows = []
    for year in (2014, 2015, 2016):
        dues = [
            date(year, 5, 15),
            date(year, 8, 14),
            date(year, 11, 14),
            date(year + 1, 3, 31),
        ]
        ends = [
            date(year, 3, 31),
            date(year, 6, 30),
            date(year, 9, 30),
            date(year, 12, 31),
        ]
        rows += [
            (due, end, value)
            for due, end, value in zip(dues, ends, (0.30, 0.70, 1.00, 1.30))
        ]
    item = eps_item(rows)
    for buy, quarter, rank in (
        (date(2017, 4, 17), date(2017, 3, 31), 2.0),
        (date(2017, 7, 17), date(2017, 6, 30), 4.0),
        (date(2017, 10, 16), date(2017, 9, 30), 2.0),
    ):
        got = tool.eps_season_3y(item, buy, quarter)
        assert got.ranks == (rank,) * 3 and got.value == rank, quarter
    got = tool.eps_season_3y(eps_item([*rows, *cumulative(2013, [1, 1, 1, 1])]),
                             date(2017, 3, 1), date(2016, 12, 31))  # fmt: skip
    assert got.ranks == (2.0, 2.0, 2.5)  # Q4 of 2015, 2014; 2013's four equal: 2.5


def test_eps_season_3y_is_missing_without_any_of_the_12_or_before_its_announcement():
    full = [*cumulative(2016, [1, 3, 2, 4]), *cumulative(2015, [2, 2, 1, 3]),
            *cumulative(2014, [5, 1, 2, 3])]  # fmt: skip
    day, q = date(2017, 4, 17), date(2017, 3, 31)
    assert tool.eps_season_3y(eps_item(full), day, q).value is not None
    for gone in (date(2014, 3, 31), date(2015, 6, 30), date(2016, 12, 31)):
        rows = [r for r in full if r[1] != gone]  # the cumulative, or the one before
        assert tool.eps_season_3y(eps_item(rows), day, q).value is None, gone
    # 2016 Q4 announced after T: not known on T
    late = [r if r[1] != date(2016, 12, 31) else (date(2017, 4, 18), r[1], r[2])
            for r in full]  # fmt: skip
    assert tool.eps_season_3y(eps_item(late), day, q).value is None
    assert tool.eps_season_3y(eps_item(late), date(2017, 4, 18), q).value is not None
    # a fourth year before does not matter, a later year neither
    more = [*full, *cumulative(2017, [9])]
    assert tool.eps_season_3y(
        eps_item(more), date(2017, 5, 15), q
    ).value == pytest.approx(2.5)


def test_single_quarter_is_feature_evidences_difference():
    rows = cumulative(2016, [1.0, -2.0, 0.5, 3.0])
    item = eps_item(rows)
    cum = {end: eps for _a, end, eps in rows}
    for end, own in zip(sorted(cum), [1.0, -2.0, 0.5, 3.0]):
        assert tool.single_quarter(cum, end) == pytest.approx(own)
    item.dates = [date(2017, 3, 31)]
    assert features._quarter_eps(item, 0)[0] == pytest.approx(
        tool.single_quarter(cum, date(2016, 12, 31))
    )
    del cum[date(2016, 6, 30)]
    assert tool.single_quarter(cum, date(2016, 9, 30)) is None  # the one before missing
    assert tool.single_quarter(cum, date(2016, 3, 31)) == 1.0  # Q1 is the cumulative
    assert tool.single_quarter(cum, date(2015, 12, 31)) is None


# --- P1: the windows --------------------------------------------------------------


def test_p1_buys_at_t1_open_sells_at_the_deadlines_close_and_holds_cash_between():
    """P1 第 2 點 (X7's account): the window's sale day has no new list, so
    both sides hold cash until the next buy day's T+1 open."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 10)}
    planned = SimpleNamespace(picks={1: [1, 2], 6: [3]}, population={1: [1, 2, 3], 6: [1, 2, 3]},
                              dues={1: 3, 6: 8})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "P1", planned, 1, 9
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
    # sessions 3 .. 5 close in cash: the equity does not move on 4 and 5
    assert mine.equity[3 - 1] == pytest.approx(cash)
    assert mine.equity[4 - 1] == pytest.approx(cash) == mine.equity[5 - 1]
    assert mine.invested[4 - 1] == 0.0 and population.invested[4 - 1] == 0.0
    returns = pr.daily_returns(mine.equity)
    assert returns[4 - 1] == 0.0 and returns[5 - 1] == 0.0
    # the population: all of T's population, 1/3 each of the cash, sold the same day
    assert len(population.positions) == 6
    assert population.positions[0].cost == pytest.approx(1 / 3)
    assert {p.sold for p in population.positions[:3]} == {3}
    # the invested shares by hand at the buy day's close (11)
    units = pr.buy_units(0.05, 10.0)
    assert mine.invested[0] == pytest.approx(2 * units * 11 / (0.9 + 2 * units * 11))
    third = pr.buy_units(1 / 3, 10.0)
    assert population.invested[0] == pytest.approx(1.0)  # no cash left
    assert population.equity[0] == pytest.approx(3 * third * 11)


def test_p1_a_locked_or_suspended_sale_day_sells_at_the_next_open_and_waits():
    """「X7 的金額與順延」: the sale day locked at limit down or suspended sells
    at the first open after it; the cash waits for the next buy day."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 10)}
    planned = SimpleNamespace(picks={1: [1], 6: [3]}, population={1: [1], 6: [3]},
                              dues={1: 3, 6: 8})  # fmt: skip
    for case in ("locked", "suspended"):
        quote = quote_of(prices, locked={(1, 3)} if case == "locked" else ())

        def on(instrument_id, s, quote=quote, case=case):
            if case == "suspended" and (instrument_id, s) in ((1, 3), (1, 4)):
                return pr.Quote(10.0, 10.0 + s, False)
            return quote(instrument_id, s)

        mine = tool.engines(SimpleNamespace(quote=on), "P1", planned, 1, 9)[0]
        first, second = mine.positions
        sold = 4 if case == "locked" else 5
        assert (first.sold, first.how) == (sold, "delayed"), case
        assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
        cash = 1.0 - first.cost + first.proceeds
        assert mine.equity[5 - 1] == pytest.approx(cash)  # cash after the sale
        assert second.cost == pytest.approx(cash / 20)  # spent on the next buy day


def test_p1_window_days_and_the_window_only_excess_by_hand():
    windows = [{"first": 2, "last": 4}, {"first": 7, "last": 8}]
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
    got = tool.window_excess(windows, 1, differences)
    picked = [0.02, -0.01, 0.03, 0.04, -0.02]
    mean = sum(picked) / 5
    sd = math.sqrt(sum((v - mean) ** 2 for v in picked) / 4)
    assert got["days"] == 5
    assert got["mean"] == pytest.approx(0.012)
    assert got["t"] == pytest.approx(mean / (sd / math.sqrt(5)))


def test_p1_plan_takes_20_by_the_season_high_first_and_counts_the_windows(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 250)  # to 2016-12-16
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 31)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    values = {i: (None if i > 27 else float(i % 4)) for i in items}

    def season(item, day, quarter):
        value = values[item.instrument_id]
        return tool.Season(value, (value,) * 3 if value is not None else ())

    monkeypatch.setattr(tool, "eps_season_3y", season)
    monkeypatch.setattr(
        tool, "industries_of", lambda ctx, day, names: Counter({"x": len(names)})
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=Counter())  # fmt: skip
    first = sessions.index(date(2016, 3, 1)) + 1
    last = sessions.index(date(2016, 11, 1))  # inside the 10-17 window
    planned = tool.plan_p1(ctx, tool.HYPOTHESES["P1"], first, last)
    buys = [date(2016, 3, 1), date(2016, 4, 15), date(2016, 7, 15), date(2016, 10, 17)]
    sales = [date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15)]
    s = [sessions.index(d) + 1 for d in buys]
    assert planned.dues == {
        **{s[k]: sessions.index(sales[k]) for k in range(3)},
        s[3]: last + 1,  # the deadline after the segment: its last close
    }
    day = date(2016, 3, 1)
    order = sorted(items, key=lambda i: (values[i] is None, -(values[i] or 0),
                                         pr.tie_break(day, i)))  # fmt: skip
    assert planned.picks[s[0]] == order[:20]
    assert all(values[i] == 3.0 for i in order[:7])  # 3, 7, 11, .., 27 first
    assert len(planned.population[s[0]]) == 30
    windows = planned.coverage["windows"]
    # 03-02..03-31, 04-18..05-16, 07-18..08-15, 10-18..11-01 (counted by hand)
    assert [w["days"] for w in windows] == [22, 21, 21, 11]
    assert [w["valued"] for w in windows] == [27] * 4
    assert [w["missing"] for w in windows] == [3] * 4
    assert [w["names"] for w in windows] == [20] * 4
    assert windows[0]["sale_date"] == "2016-03-31"
    assert planned.industries == Counter({"x": 80}) and planned.industry_windows == 4
    assert planned.rows[0]["eps_season_3y"] == 3.0


def test_p1_industries_read_the_member_table_to_its_last_month(monkeypatch):
    member = ms.Member("TWSE", "24", "半導體業", "g24", "S1", False)
    groups = SimpleNamespace(snapshots={date(2016, 1, 4): [member]})
    ctx = SimpleNamespace(groups=groups, labels={}, seconds=Counter())

    def grouped(g, day):
        return {"g24": {1, 2}}, set(), set()

    monkeypatch.setattr(ms, "group_members", grouped)
    got = tool.industries_of(ctx, date(2016, 4, 15), [1, 2, 3])
    assert got == Counter({"半導體業": 2, "（不在成員表）": 1})
    assert tool.industries_of(ctx, date(2024, 10, 15), [1]) is None  # after 2024-09


# --- P2: margins_up ---------------------------------------------------------------


def statements(year, revenue, gross, operating, net, fmt="general", announced=None):
    """One year's rows from the single quarters (cumulative, as the source)."""

    ends = [date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)]
    dues = announced or [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                         date(year + 1, 3, 31)]  # fmt: skip
    rows, totals = [], [0.0, 0.0, 0.0, 0.0]
    for k, (end, due) in enumerate(zip(ends, dues)):
        if k >= len(revenue):
            break
        values = []
        for j, own in enumerate((revenue, gross, operating, net)):
            totals[j] = (
                None if totals[j] is None or own[k] is None else totals[j] + own[k]
            )
            values.append(totals[j])
        rows.append(tool.Statement(due, end, fmt, *values))
    return rows


def up_rows(**changes):
    """2016: revenue 100 each, gross 20..23, operating 10, 10, 11, 11, net 5,
    5, 6, 6; 2017 Q1 revenue 100, gross 24, operating 12, net 7: each margin
    of q above q − 1 (2016 Q4) and q − 4 (2016 Q1)."""

    q1 = {"revenue": [100.0], "gross": [24.0], "operating": [12.0], "net": [7.0]}
    q1.update(changes)
    return [*statements(2016, [100.0] * 4, [20.0, 21.0, 22.0, 23.0], [10.0, 10.0, 11.0, 11.0],
                        [5.0, 5.0, 6.0, 6.0]),
            *statements(2017, q1["revenue"], q1["gross"], q1["operating"], q1["net"])]  # fmt: skip


DAY, Q = date(2017, 5, 15), date(2017, 3, 31)


def flat(rates) -> list[float]:
    return [value for rate in rates for value in rate]


def margins(rows, day=DAY, quarter=Q):
    ctx = context_for(statements={1: rows})
    return tool.margins_up(ctx, make_item([10.0]), day, quarter)


def test_margins_up_by_hand():
    got = margins(up_rows())
    assert got.qualifies and got.reason is None
    # single quarters, not the cumulative: 2016 Q4's own 23/100, 11/100, 6/100
    assert flat(got.rates) == pytest.approx(
        [0.24, 0.12, 0.07, 0.23, 0.11, 0.06, 0.20, 0.10, 0.05]
    )
    for change, reason in (
        ({"operating": [11.0]}, "lower"),  # equal to q − 1: not strictly higher
        ({"net": [5.0]}, "lower"),  # equal to q − 4
        ({"net": [5.5]}, "lower"),  # above q − 4, below q − 1
        ({"gross": [20.0]}, "lower"),
        ({"revenue": [0.0]}, "revenue"),
        ({"revenue": [-5.0]}, "revenue"),
    ):
        got = margins(up_rows(**change))
        assert (got.qualifies, got.reason) == (False, reason), change
    # a higher revenue with the same profits lowers every margin
    assert margins(up_rows(revenue=[200.0])).reason == "lower"


def test_margins_up_needs_the_deadlines_quarter_the_general_format_and_every_field():
    rows = up_rows()
    late = [
        r if r.period_end != Q else replace(r, announced=date(2017, 5, 31))
        for r in rows
    ]
    assert margins(late).reason == "stale"  # 2017 Q1 not known on T
    assert margins(rows[:4]).reason == "stale"
    assert margins([]).reason == "stale"
    bank = [r if r.period_end != date(2016, 12, 31) else tool.Statement(
        r.announced, r.period_end, "bank", r.revenue, None, r.operating, r.net) for r in rows]  # fmt: skip
    assert margins(bank).reason == "format"
    no_net = [r if r.period_end != date(2016, 9, 30) else tool.Statement(
        r.announced, r.period_end, "general", r.revenue, r.gross, r.operating, None) for r in rows]  # fmt: skip
    assert margins(no_net).reason == "fields"  # the quarter before q − 1
    gone = [r for r in rows if r.period_end != date(2016, 9, 30)]
    assert margins(gone).reason == "fields"
    gone = [r for r in rows if r.period_end != date(2016, 3, 31)]  # q − 4
    assert margins(gone).reason == "fields"
    eps_only = [r if r.period_end != Q else tool.Statement(r.announced, Q, None, None, None, None, None)
                for r in rows]  # fmt: skip
    assert margins(eps_only).reason == "fields"  # a delisted company's XBRL row
    # a Q3 quarter needs Q2 and Q1 of the same year, Q2 and Q3 of the year before
    rows = [*statements(2016, [100.0] * 4, [20.0] * 4, [10.0] * 4, [5.0] * 4),
            *statements(2017, [100.0] * 3, [21.0, 22.0, 23.0], [11.0, 12.0, 13.0],
                        [6.0, 7.0, 8.0])]  # fmt: skip
    got = margins(rows, date(2017, 11, 14), date(2017, 9, 30))
    assert got.qualifies
    assert flat(got.rates) == pytest.approx(
        [0.23, 0.13, 0.08, 0.22, 0.12, 0.07, 0.20, 0.10, 0.05]
    )


def test_the_statement_reads_the_net_gross_first_and_the_plain_one_otherwise():
    parse = __import__("worker.sources", fromlist=["parse_number"]).parse_number
    both = {"report_format": "general", "營業收入": "1,000", "營業毛利（毛損）淨額": "300",
            "營業毛利（毛損）": "310", "營業利益（損失）": "(20)", "本期淨利（淨損）": "-5"}  # fmt: skip
    row = tool.statement_of("2017-05-15", "2017-03-31", both, parse)
    assert (row.revenue, row.gross, row.operating, row.net) == (
        1000.0,
        300.0,
        -20.0,
        -5.0,
    )
    assert not row.gross_fallback and row.report_format == "general"
    plain = {k: v for k, v in both.items() if k != "營業毛利（毛損）淨額"}
    row = tool.statement_of("2017-05-15", "2017-03-31", plain, parse)
    assert row.gross == 310.0 and row.gross_fallback
    row = tool.statement_of("2017-05-15", "2017-03-31", {}, parse)
    assert (row.report_format, row.revenue, row.gross, row.operating, row.net) == (
        None,
    ) * 5
    row = tool.statement_of(
        "2017-05-15", "2017-03-31", {**both, "營業收入": "--"}, parse
    )
    assert row.revenue is None


def test_the_reference_takes_out_only_delisted_or_transferred_missing_a_field(
    monkeypatch,
):
    """P2 第 7 點, 第十五輪實作釋義: a delisted or transferred instrument
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
    monkeypatch.setattr(tool, "margins_up", lambda ctx, item, day, q: tool.Margins(
        item.instrument_id in (2, 5), None if item.instrument_id in (2, 5) else "fields",
        ((0.2, 0.1, 0.05),) * 3))  # fmt: skip
    monkeypatch.setattr(tool, "k2_names", lambda ctx, day, members, q: {5})
    monkeypatch.setattr(tool, "x4_names", lambda ctx, day, members: {2, 6})
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter(),
                          statuses=statuses, statements={})  # fmt: skip
    first = sessions.index(date(2016, 3, 31)) + 1
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_p2(ctx, tool.HYPOTHESES["P2"], first, last)
    s = [
        sessions.index(d) + 1
        for d in (date(2016, 3, 31), date(2016, 5, 16), date(2016, 8, 15))
    ]
    assert planned.reference[s[0]] == [1, 2, 5, 6]
    assert planned.population[s[0]] == [1, 2, 3, 4, 5, 6]
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    names = sorted((2, 5), key=lambda i: pr.tie_break(date(2016, 3, 31), i))
    assert planned.picks[s[0]] == names
    event = planned.rebalances[0]
    assert (event["delisted"], event["delisted_missing"]) == (3, 2)
    assert (event["hits"], event["names"], event["fields"]) == (2, 2, 4)
    assert (event["k2_overlap"], event["x4_overlap"]) == (0.5, 0.5)
    assert planned.overlap == {
        "P2_K2": {"2016": [0.5] * 3},
        "P2_X4": {"2016": [0.5] * 3},
    }
    year = planned.coverage["2016"]
    assert (year["delisted"], year["delisted_missing"], year["hits"]) == (9, 6, 6)


def test_k2_names_are_round14s_k2_list_on_the_same_t(monkeypatch):
    """P2 第 8 點: ``k2_names`` is K2's list (``round14_research.plan_k2``'s
    picks) on the same T, not another selection."""

    sessions = weekdays(date(2017, 1, 2), 120)  # 2017-05-15 is an event day
    day, quarter = date(2017, 5, 15), date(2017, 3, 31)
    turn = [
        (date(2016, 5, 15), date(2016, 3, 31), -0.5),
        (date(2017, 5, 15), quarter, 0.4),
    ]
    flat = [
        (date(2016, 5, 15), date(2016, 3, 31), 0.5),
        (date(2017, 5, 15), quarter, 0.4),
    ]
    items = {}
    for i in range(1, 31):
        item = make_item([10.0], instrument_id=i, dates=[day])
        item.quarters = turn if i <= 25 else flat  # 25 turn: more than 20
        items[i] = item
    members = [(items[i], 0) for i in items]
    monkeypatch.setattr(lib, "universe", lambda panel, d, lots: members)
    monkeypatch.setattr(r14, "x4_names", lambda ctx, d, m: set())
    ctx = SimpleNamespace(
        panel=SimpleNamespace(sessions=sessions, symbols={}), seconds=Counter()
    )
    at = sessions.index(day)
    planned = r14.plan_k2(ctx, r14.HYPOTHESES["K2"], at + 1, at + 5)
    mine = tool.k2_names(ctx, day, members, quarter)
    assert mine == set(planned.picks[at + 1]) and len(mine) == 20


def test_fields_missing_is_point_3s_field_case_on_the_deadlines_quarter():
    rows = up_rows()
    ctx = context_for(statements={1: rows})
    item = make_item([10.0])
    assert not tool.fields_missing(ctx, item, DAY, Q)
    ctx = context_for(statements={1: up_rows(revenue=[0.0])})
    assert not tool.fields_missing(
        ctx, item, DAY, Q
    )  # revenue ≤ 0 is not a missing field
    ctx = context_for(statements={1: rows[:4]})  # q not known on T: its fields missing
    assert tool.fields_missing(ctx, item, DAY, Q)
    eps_only = [tool.Statement(r.announced, r.period_end, None, None, None, None, None)
                for r in rows]  # fmt: skip
    assert tool.fields_missing(context_for(statements={1: eps_only}), item, DAY, Q)
    assert tool.fields_missing(context_for(), item, DAY, Q)


def test_p2_x7_account_and_its_excess_over_the_reference_by_hand(monkeypatch):
    """P2 第 4、7 點: one account; the reference on the same rule and event
    days; the excess over it is the daily returns' difference."""

    sessions = weekdays(date(2016, 3, 28), 6)
    prices = {(1, s): (10.0, (11.0, 12.0, 12.0)[s - 1]) for s in (1, 2, 3)}
    prices.update({(2, s): (10.0, 10.0) for s in (1, 2, 3)})
    first, last = 1, 3
    plan = tool.Plan(picks={1: [1]}, population={1: [1, 2]}, reference={1: [2]}, dues={1: 4},
                     rebalances=[{"signal_date": sessions[0].isoformat(), "names": 1,
                                  "k2_overlap": None, "x4_overlap": None}])  # fmt: skip
    monkeypatch.setattr(tool, "segment_window", lambda s, seg, spec: (first, last))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_p2", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "P2", "exploration")
    units1 = pr.buy_units(0.05, 10.0)
    mine = [0.95 + units1 * c for c in (11.0, 12.0, 12.0)]
    units2 = pr.buy_units(1.0, 10.0)
    ref = [units2 * 10.0] * 3
    differences = [a - b for a, b in zip(pr.daily_returns(mine), pr.daily_returns(ref))]
    got = result["excess"]["reference"]
    assert got["days"] == 3
    assert got["mean"] == pytest.approx(statistics.fmean(differences))
    assert got["t"] == pytest.approx(lib.t_stat(differences))
    assert result["rebalances"][0]["invested"] == pytest.approx(units1 * 11 / mine[0])
    assert result["unsold_share"] == 1.0  # due after the segment: its last close


def test_p2_sells_at_the_next_event_days_close_and_buys_at_its_next_open():
    """「K2 的賣出時點」: T′'s close, the new list at T′+1; fewer than 20 cash."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3) for s in range(1, 8)}
    planned = SimpleNamespace(picks={1: [1], 4: [2]}, population={1: [1, 3], 4: [2, 3]},
                              reference={1: [3], 4: [3]}, dues={1: 3, 4: 8})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "P2", planned, 1, 7
    )
    first, second = mine.positions
    assert (first.sold, first.how, second.bought) == (3, "close", 4)
    assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)
    assert [p.instrument_id for p in reference.positions] == [3, 3]
    assert reference.positions[0].cost == pytest.approx(1.0)  # 1/n of the cash, n = 1
    # T′ suspended: sold at T′+1's open, its cash in that day's buys (X7)
    quote = quote_of(prices)

    def on(instrument_id, s):
        if (instrument_id, s) == (1, 3):
            return pr.Quote(10.0, 13.0, False)
        return quote(instrument_id, s)

    mine = tool.engines(SimpleNamespace(quote=on), "P2", planned, 1, 7)[0]
    first, second = mine.positions
    assert (first.sold, first.how) == (4, "delayed")
    assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 10.0))
    assert second.cost == pytest.approx((1.0 - first.cost + first.proceeds) / 20)


# --- P3: nr_ratio_20_240 ----------------------------------------------------------


def reversal_bars(at_recent=(241, 250, 260), at_before=tuple(1 + 20 * k for k in range(12)),
                  n=261, flat=()):  # fmt: skip
    """Open = close = 10, a reversal bar opens 11 and closes 10.5 (overnight up,
    intraday down); the bar after a reversal opens 10 < 10.5, no reversal."""

    opens, closes = [10.0] * n, [10.0] * n
    for i in (*at_recent, *at_before):
        opens[i], closes[i] = 11.0, 10.5
    for i in flat:
        opens[i], closes[i] = 11.0, 11.0
    return opens, closes


def ratio(opens, closes, at=None, suspended=()):
    item = make_item(closes, opens=opens, suspended=suspended)
    return tool.nr_ratio_20_240(
        context_for([item]), item, len(closes) - 1 if at is None else at
    )


def test_nr_ratio_20_240_by_hand():
    got = ratio(*reversal_bars())
    assert (got.f20, got.f240) == (3 / 20, 12 / 240)
    assert got.value == pytest.approx(3.0)
    # the windows' edge: at − 19 is in f20, at − 20 in f240
    got = ratio(*reversal_bars(at_recent=(240, 250, 260)))
    assert (got.f20, got.f240) == (2 / 20, 13 / 240)
    got = ratio(*reversal_bars(at_recent=(241, 250, 260), at_before=(1, 21)))
    assert got.value == pytest.approx((3 / 20) / (2 / 240))
    # bar at − 260 (0) has no bar before it in the window: its open is not read
    opens, closes = reversal_bars()
    opens[0] = 11.0
    assert ratio(opens, closes).value == pytest.approx(3.0)


def test_a_reversal_needs_both_signs_strictly():
    opens, closes = reversal_bars()
    opens[250], closes[250] = 10.0, 9.0  # open = the close before: no overnight rise
    assert ratio(opens, closes).f20 == 2 / 20
    opens, closes = reversal_bars(flat=(250,))  # locked: open = close
    assert ratio(opens, closes).f20 == 2 / 20
    opens, closes = reversal_bars()
    opens[250], closes[250] = 11.0, 12.0  # up and up
    assert ratio(opens, closes).f20 == 2 / 20
    opens, closes = reversal_bars()
    closes[249], opens[250], closes[250] = 9.0, 9.5, 9.2  # a gap up from a low close
    assert ratio(opens, closes).f20 == 3 / 20


def test_nr_ratio_20_240_is_missing_short_suspended_without_prices_or_f240_zero():
    assert ratio(*reversal_bars(n=260, at_recent=(250,)), at=259).reason == "short"
    assert ratio(*reversal_bars(), suspended=(0,)).reason == "suspended"
    assert ratio(*reversal_bars(), suspended=(260,)).reason == "suspended"
    opens, closes = reversal_bars(n=262, at_recent=(242, 251, 261),
                                  at_before=tuple(2 + 20 * k for k in range(12)))  # fmt: skip
    assert ratio(opens, closes, suspended=(0,)).value == pytest.approx(3.0)  # at − 261
    for which, i in (("open", 1), ("open", 260), ("close", 0), ("close", 260)):
        for bad in (0.0, NAN, -1.0):
            opens, closes = reversal_bars()
            (opens if which == "open" else closes)[i] = bad
            assert ratio(opens, closes).reason == "price", (which, i, bad)
    got = ratio(*reversal_bars(at_before=()))
    assert (got.value, got.reason, got.f20) == (None, "f240_zero", 3 / 20)


def test_p3_rotates_20_accounts_and_the_population_too(monkeypatch):
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    monkeypatch.setattr(pr, "simulate", simulate)
    planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]})
    tool.engines(SimpleNamespace(quote=None), "P3", planned, 1, 5)
    assert calls == [({1: [1]}, 20, 20), ({1: [1, 2]}, 20, None)]


def test_p3_plan_ranks_high_first_overlaps_z4_and_lists_the_overnight_mean(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 30)
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 26)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    values = {i: (None if i <= 2 else float(i % 5)) for i in items}
    monkeypatch.setattr(tool, "nr_ratio_20_240", lambda ctx, item, at: tool.Ratio(
        values[item.instrument_id], None if values[item.instrument_id] is not None else "short"))  # fmt: skip
    monkeypatch.setattr(tool, "z4_names", lambda ctx, day, members: {4, 9, 1})
    nights = {i: (None if i == 4 else i / 100) for i in items}
    monkeypatch.setattr(
        r8, "overnight_20", lambda ctx, item, at: nights[item.instrument_id]
    )
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, symbols={}),
                          seconds=Counter(), z4=None)  # fmt: skip
    planned = tool.plan_p3(ctx, tool.HYPOTHESES["P3"], 1, 2)
    day = sessions[0]
    order = sorted(
        items,
        key=lambda i: (values[i] is None, -(values[i] or 0), pr.tie_break(day, i)),
    )
    assert planned.picks[1] == order[:20]
    assert {1, 2} & set(order[:20]) == set()  # 23 valued: the missing last
    chosen = order[:20]
    assert planned.overlap["P3_Z4"]["2016"][0] == pytest.approx(
        len({4, 9} & set(chosen)) / 20
    )
    expected = statistics.fmean(nights[i] for i in chosen if nights[i] is not None)
    assert planned.overnight["2016"][0] == pytest.approx(expected)
    year = planned.coverage["2016"]
    assert (year["valued"], year["missing"]["nr_ratio_20_240"], year["missing"]["short"]) == (
        46, 4, 4,
    )  # fmt: skip


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
        (3.317, "前瞻觀察"),  # round 14's threshold is not this round's
        (3.331, "前瞻觀察"),
        (3.332, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_332(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 700
STOCKS = range(1, 25)
# the last bar's index (26 in the exploration, 25 in the validation); 25 EPS only,
# 26 every field
DELISTED = {25: 590, 26: 450}
TRANSFERRED = 27  # EPS only
INDEX_ID = 90
UP = range(1, 7)  # margins rising every quarter: margins_up on every deadline
FALLBACK = 3  # its gross under 營業毛利（毛損）
BANK = 9  # report_format bank: never margins_up
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
    """2012～2018: stock i's single-quarter EPS 1..4 rotate with i % 4; UP's
    margins rise every quarter, the others' stay 20%／10%／5%."""

    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        k = 0
        for year in range(2012, 2019):
            totals, eps = [0.0] * 4, 0.0
            ends = [
                date(year, 3, 31),
                date(year, 6, 30),
                date(year, 9, 30),
                date(year, 12, 31),
            ]
            dues = [date(year, 5, 15), date(year, 8, 14), date(year, 11, 14),
                    date(year + 1, 3, 31)]  # fmt: skip
            for q, (end, due) in enumerate(zip(ends, dues), 1):
                k += 1
                eps += 1.0 + ((q - 1 - i % 4) % 4)
                margin = 0.2 + (0.002 * k if i in UP else 0.0)
                own = (1000.0, 1000.0 * margin, 500.0 * margin, 250.0 * margin)
                totals = [a + b for a, b in zip(totals, own)]
                data: dict = {}
                if i not in (25, TRANSFERRED):  # the XBRL rows: EPS only
                    gross = (
                        "營業毛利（毛損）" if i == FALLBACK else "營業毛利（毛損）淨額"
                    )
                    data = {"report_format": "bank" if i == BANK else "general",
                            "營業收入": f"{totals[0]:,.0f}", gross: f"{totals[1]:.3f}",
                            "營業利益（損失）": f"{totals[2]:.3f}",
                            "本期淨利（淨損）": f"{totals[3]:.3f}"}  # fmt: skip
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
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("round15")
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


def test_one_panel_serves_the_statements_the_members_and_the_overlaps(loaded):
    assert loaded.groups.market is loaded.base.market
    assert loaded.z4.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "statements", "members"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    rows = loaded.statements[FALLBACK]
    assert all(r.gross_fallback for r in rows) and rows[0].gross == pytest.approx(202.0)
    assert rows[0].revenue == 1000.0 and rows[0].report_format == "general"
    assert loaded.statements[25][0].revenue is None  # EPS only


def test_the_features_on_the_copy(loaded):
    days = trading_days()
    at = days.index(date(2017, 5, 15))
    series = loaded.panel.series
    q = date(2017, 3, 31)
    for i in UP:
        assert tool.margins_up(loaded, series[i], days[at], q).qualifies, i
    assert (
        tool.margins_up(loaded, series[10], days[at], q).reason == "lower"
    )  # equal margins
    assert tool.margins_up(loaded, series[BANK], days[at], q).reason == "format"
    assert tool.margins_up(loaded, series[25], days[at], q).reason == "fields"
    assert tool.fields_missing(loaded, series[25], days[at], q)
    assert not tool.fields_missing(loaded, series[26], days[at], q)
    # 2016 Q4 (the 2017-03-01 buy day): Q4's own EPS is 1 + (3 − i % 4) % 4
    at = days.index(date(2017, 3, 1))
    for i, rank in ((3, 1.0), (2, 2.0), (1, 3.0), (4, 4.0)):
        got = tool.eps_season_3y(series[i], days[at], date(2016, 12, 31))
        assert got.value == rank, i
    item = series[1]
    assert tool.nr_ratio_20_240(loaded, item, 259).reason == "short"
    assert tool.nr_ratio_20_240(loaded, item, 260).reason in (None, "f240_zero")


def compressed(monkeypatch, tmp_path: Path, db: Path) -> None:
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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "P1,P2,P3"
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
        "round15_research", "984", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (15, 3, 58)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.332)
    assert report["read_until"] == days[499].isoformat()
    hyp = report["hypotheses"]
    assert [hyp[n]["engine"] for n in NAMES] == ["events", "events", "portfolio"]
    # P1's windows from 2016-04-15 to the exploration's end (2017-11-30)
    assert hyp["P1"]["windows"] == 7 and hyp["P1"]["window_excess"]["days"] > 0
    assert hyp["P2"]["reference_excess"]["days"] > 0 and "overlap_k2" in hyp["P2"]
    assert "overlap_x4" in hyp["P2"] and "overlap_z4" in hyp["P3"]
    assert hyp["P3"]["overnight_20"]["days"] > 0
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 58 個" in text and "驗證段 t ≥ 3.332" in text
    assert tool.OVERLAP_NOTE["P2_survivor"] in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round15_research", 15, "exploration", 1) for name in NAMES]
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
    p1 = (out / "P1" / "summary.md").read_text(encoding="utf-8")
    assert "## 每個窗口（P1 第 8 點" in p1 and "## 名單的產業分布" in p1
    assert (
        "持有到法定期限收盤，窗口之間留現金" in p1
        and tool.OVERLAP_NOTE["P1_window"] in p1
    )
    assert f"| {im.GROUP_LABELS['TWSE']['24']} |" in p1  # the member table's label
    p2 = (out / "P2" / "summary.md").read_text(encoding="utf-8")
    assert p2.splitlines()[2] == tool.OVERLAP_NOTE["P2_survivor"]  # the report's start
    assert (
        "超額（對對照基準，只列出）" in p2 and tool.OVERLAP_NOTE["P2_reference"] in p2
    )
    for key in ("P2_K2", "P2_X4"):
        assert tool.OVERLAP_NOTE[key] in p2
    assert "## 每次調倉（P2 第 8 點" in p2
    assert tool.OVERLAP_NOTE["P3_Z4"] in (out / "P3" / "summary.md").read_text(
        encoding="utf-8"
    )
    picks = (out / "P2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        picks[0]
        == "signal_date,rank,exchange,symbol,quarter,gross_margin,operating_margin,net_margin,tie"
    )
    on = sorted(
        line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")
    )
    assert on == [f"S{i}" for i in sorted(UP, key=str)]  # every UP, incl. the fallback
    p1_picks = (out / "P1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert (
        p1_picks[0]
        == "signal_date,rank,exchange,symbol,quarter,eps_season_3y,ranks,tie"
    )
    first = [line.split(",") for line in p1_picks[1:] if line.startswith("2016-04-15")]
    assert len(first) == 20 and {row[5] for row in first[:7]} == {
        "4.0"
    }  # Q1 is 4th for i % 4 == 1


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="P2") == 2
    assert any("P2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="P1,K2") == 2
    assert any("K2 not registered" in line for line in refused(capsys))


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
    data["design"] = "978"
    data["hypotheses"]["P2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_332(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path, "P1", "P2")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("P1", "round15_research", "finished"),
                       ("P2", "round15_research", "finished")]  # fmt: skip
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["P1", "P2"]
    assert validation["min_t"] == 3.332
    for name in ("P1", "P2"):
        assert (
            read_json(tmp_path / "validation" / name / "tables.json")["min_t"] == 3.332
        )
    assert validation["read_until"] == trading_days()[599].isoformat()
    assert validation["hypotheses"]["P2"]["reference_excess"]["days"] > 0
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.332（沒有 t 下限）" in text
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
    report = passed_report(out, tmp_path, "P1")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[599]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["P1"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["P1"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "P1" / "used" / file).is_file(), file
    used = (tmp_path / "validation" / "P1" / "used" / "summary.md").read_text(
        encoding="utf-8"
    )
    assert (
        "成員表到 2024-09-30，本段的窗口在那之後，不列" not in used
    )  # 2018 here: listed
    assert "## 名單的產業分布" in used


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
    windows = hyp["P1"]["coverage"]["windows"]
    assert [w["signal_date"] for w in windows][:3] == [
        "2016-04-15",
        "2016-07-15",
        "2016-10-17",
    ]
    assert all(w["valued"] == w["members"] and w["missing"] == 0 for w in windows)
    may = next(e for row in hyp["P2"]["coverage"].values() for e in row["events"]
               if e["signal_date"] == "2017-05-15")  # fmt: skip
    assert may["hits"] == len(UP) and may["format"] == 1 and may["fallback"] == 1
    assert (may["delisted"], may["delisted_missing"]) == (3, 2)  # 25, 26, 27; 26 kept
    assert may["fields"] == 2  # 25 and 27 (EPS only)
    p3 = hyp["P3"]["coverage"]
    assert sum(row["valued"] for row in p3.values()) > 0
    seconds = {name: set(hyp[name]["seconds"]) for name in NAMES}
    assert seconds["P1"] == {"plan", "eps_season_3y"}
    assert seconds["P2"] == {"plan", "margins_up", "reference", "k2_order", "x4_order"}
    assert seconds["P3"] == {"plan", "nr_ratio_20_240", "z4_order"}
    columns = body["columns_2013"]
    assert sorted(columns) == ["2013-03-31", "2013-06-30", "2013-09-30", "2013-12-31"]
    general = columns["2013-03-31"]["general"]
    assert general["fields"]["營業收入"] == general["rows"] == 23 + 1  # 26 delisted too
    assert general["fields"]["營業毛利（毛損）"] == 1  # FALLBACK
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "statements", "members"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "## P2：2013 年各季的欄名" in md
    assert (
        "最新一季不是對應的那一季" in md
        and "因缺單季值而缺值" in md
        and "（f240＝0）" in md
    )
    for name in NAMES:
        assert tool.DEGENERATE[name] in md, name


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "P1"]
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
    assert explore(copied, tmp_path / "out", hypotheses="P3") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "P3")
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
        assert explore(copied, out, hypotheses="P3") == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path, "P3")
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
