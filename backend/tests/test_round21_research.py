"""tools/research/round21_research.py: the registered AD1 (#1067).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第二十一輪：AD1.  The subject rule, ``ann_date``,
``exp_date``, the condition and the window account are checked on hand-made
dates and series (the expected numbers worked out in the test); the gate
("each once") and the reports run on a synthetic copy on a compressed
calendar (``compressed``): the segments and the floors are moved into the
fixture's 700 sessions, everything else is the registered one.
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
    Event,
    FundamentalSnapshot,
    IngestionRun,
    Instrument,
    MarketBar,
    RawPayload,
)

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1067#issuecomment-1"


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
r5 = _tool("round5_research")
r10 = _tool("round10_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
r20 = _tool("round20_research")
tool = _tool("round21_research")
NAMES = ("AD1",)
REPORT = "本公司董事會通過105年第1季合併財務報告"


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 21))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    ad1 = h["AD1"]
    assert ad1["engine"] == "portfolio" and ad1["keys"] == ()
    assert (ad1["top"], ad1["hold"], ad1["start"], ad1["rule"]) == (
        20, 5, ("date", date(2014, 4, 15)), "window_daily",
    )  # fmt: skip
    assert ad1["condition"] == "expected_ahead"
    assert ad1["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        21,
        1,
        71,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.388
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(71), 3) == 3.388
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "3b686bd2" and tool.DESIGN == "1067"
    assert tool.SUBJECT_ALL == ("董事會",)
    assert tool.SUBJECT_ANY == (("通過", "決議"), ("財務報告", "財務報表", "財報"))
    assert tool.SUBJECT_NONE == (
        "更正",
        "補充",
        "子公司",
        "取消",
        "延期",
        "重編",
        "自結",
    )
    assert tool.DEADLINES == (
        (3, 31, 12, -1),
        (5, 15, 3, 0),
        (8, 14, 6, 0),
        (11, 14, 9, 0),
    )
    assert tool.WINDOW_STARTS == (
        (3, 1, 12, -1),
        (4, 15, 3, 0),
        (7, 15, 6, 0),
        (10, 15, 9, 0),
    )
    assert (tool.AHEAD_FIRST, tool.AHEAD_LAST) == (1, 5)
    assert (tool.NEWS_SOURCE, tool.NEWS_EVENT_TYPE) == (
        "mops_material_information", "material_information",
    )  # fmt: skip
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool._reference is r20._reference
    assert tool.REFERENCE_STATUSES is r20.REFERENCE_STATUSES
    assert tool.DEADLINES is r14.DEADLINES and tool.WINDOW_STARTS is r15.BUY_DAYS
    assert "load_context" in tool.load.__code__.co_names
    assert "load_statuses" in tool.load.__code__.co_names
    assert {"buy_events", "sale_days"} <= set(tool.windows.__code__.co_names)
    assert "r15.plan_p1(" in inspect.getsource(tool.p1_lists)
    assert "r10.overlap_share(" in inspect.getsource(tool.plan_ad1)
    assert "lib.universe(" in inspect.getsource(tool.plan_ad1)
    assert "pr.tie_break(" in inspect.getsource(tool.plan_ad1)
    assert "pr.simulate" in inspect.getsource(tool.engines)
    assert "announcements" in inspect.getsource(tool.announced)
    assert "explore_judge" in tool.run_portfolio.__code__.co_names


def _swap(key: str, value):
    return {**tool.HYPOTHESES, "AD1": {**tool.HYPOTHESES["AD1"], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1067 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.388
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.384),
        # the subject rule: the three groups and the 7 words left out
        (tool, "SUBJECT_ALL", ("董事會", "通過")),
        (tool, "SUBJECT_ANY", (("通過",), ("財務報告", "財務報表", "財報"))),
        (tool, "SUBJECT_ANY", (("通過", "決議"), ("財務報告", "財報"))),
        (tool, "SUBJECT_NONE", ("更正", "補充", "子公司", "取消", "延期", "重編")),
        (tool, "NEWS_SOURCE", "mops_other"),
        (tool, "NEWS_EVENT_TYPE", "treasury_stock"),
        # ann_date: the day after the quarter's end to the deadline, the
        # first, calendar days; the 4 deadlines and their quarters
        (tool, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (tool, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 14, 6, 0))),
        (tool, "ANN_RULE", "the last matching announcement"),
        (tool, "ANN_RULE", "the session the announcement is put off to"),
        # exp_date: d calendar days, the expected session
        (tool, "EXP_RULE", "d in sessions"),
        (tool, "EXPECTED_RULE", "the last session on or before exp_date"),
        # the condition: T+1 .. T+5, not announced on or before T
        (tool, "AHEAD_FIRST", 0),
        (tool, "AHEAD_LAST", 6),
        (tool, "ANNOUNCED_RULE", "announced before T, T itself not"),
        # the windows and their endpoints
        (tool, "WINDOW_STARTS", ((3, 1, 12, -1), (4, 16, 3, 0), (7, 15, 6, 0), (10, 15, 9, 0))),
        (r15, "EVENT_DAY_RULE", "the first session on or after the date"),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 15, 6, 0), (11, 14, 9, 0))),
        (tool, "WINDOW_RULE", "to the deadline session, not in"),
        # N 20 (the hash, not ranked), K 5, cash between the windows
        (tool, "HYPOTHESES", _swap("top", 19)),
        (tool, "HYPOTHESES", _swap("hold", 4)),
        (tool, "HYPOTHESES", _swap("keys", (("exp_date", "low"),))),
        (tool, "ORDER", "by exp_date, near first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "CASH_RULE", "the accounts rotate on the window days only"),
        # the reference, the hash, the start
        (tool, "REFERENCE_RULE", "less every delisted instrument"),
        (r20, "REFERENCE_STATUSES", ("delisted",)),
        (tool, "HYPOTHESES", _swap("start", ("date", date(2014, 3, 1)))),
        # the listed parts: P1's list, the actual date inside the holding
        (r15, "HYPOTHESES", {**r15.HYPOTHESES, "P1": {**r15.HYPOTHESES["P1"], "top": 19}}),
        (tool, "P1_RULE", "every window, before P1's start too"),
        (tool, "INSIDE_RULE", "T .. T+5"),
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
        (tool, "ROUND_SIZE", 2),
        (tool, "CUMULATIVE", 72),
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
        "-h", "--help", "--db", "--out", "--segment", "--min-free-gb", "--coverage-only",
        "--hypotheses", "--exploration-report", "--exploration-sha256", "--exploration-url",
    }  # fmt: skip


# AC-1: measured on master 3b686bd2 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash, its P2 row round15_research's and its
# A1 row round17_research's; AD1 reads round14 (the deadlines), round15 (the
# windows, P1), round18／round20 (the reference) and explore_research (the
# MOPS list).
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
    "round20_research": (1, "c0274f4166204624fe02a090adaf95d81688c869049bc362620cfca04436f854"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round10_research", "round14_research", "round15_research", "round17_research",
     "round18_research", "round20_research", None],
)  # fmt: skip
def test_the_tools_ad1_reads_are_the_ledgers(name):
    """AC-1: the hashes AD1 and forward_watch read are the ones in the public
    ledger (explore_research's entries have no ``tool``)."""

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
    assert (
        found
        == {module.definitions_sha256()}
        == {FROZEN[name or "explore_research"][1]}
    )


# AC-1: portfolio_research.ranking_key's source on master 3b686bd2
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
    section = text.split("**第二十一輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    assert tool.DEGENERATE["AD1"] in section
    assert any(tool.DEGENERATE["AD1"] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.388 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round21_research.py" in section
    assert "本輪 1 個、累計 71 個" in section
    assert "t < 3.388（沒有 t 下限）" in section
    # #1067 決定 7202868880: the coverage's numbers lead the limits
    assert tool.LIMITS["AD1"].startswith(tool.OVERLAP_NOTE["AD1_coverage"] + "；")
    for words in ("8%～19%", "448 天不足 20 檔、63 天沒有名單", "「名單接近母體」那一點在這份資料上不成立",
                  "董事會重要決議事項", "2013Q2"):  # fmt: skip
        assert words in tool.OVERLAP_NOTE["AD1_coverage"], words
    # the "前瞻觀察" line of the reports, word for word
    assert "t < 3.388（沒有 t 下限）" in tool._watch_line(tool.VALIDATION_MIN_T)


# --- hand-made dates and series ---------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes, instrument_id=1, dates=None):
    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2016, 1, 4), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        item.session.append(at)
        item.open.append(close)
        item.high.append(close)
        item.low.append(close)
        item.close.append(close)
        item.volume.append(2_000_000.0)
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1])
    return item


def context_for(items=(), sessions=None, statuses=None, news=()):
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
    symbols = {i: ("TWSE", f"S{i}", f"N{i}") for i in series}
    panel = lib.Panel(sessions or [], series, {}, {}, symbols)
    base = ex.Context(pr.Market(panel, raw_rows, {}, None))
    base.announcements.extend(news)
    return tool.Context(base, statuses=statuses or {})


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_down=(instrument_id, s) in locked
        )

    return quote


def news_on(*days: date, instrument_id: int = 1, title: str = REPORT):
    return [(0, instrument_id, title, day) for day in days]


# --- AD1 第 2 點: the subject rule ------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "本公司董事會通過105年第1季合併財務報告",
        "董事會決議通過合併財務報表",  # 財務報表 (decision 7201658574)
        "公告本公司董事會通過105年度財報",
        "董事會決議105年第2季財務報告",  # 決議 alone
    ],
)
def test_the_subject_rule_takes_the_three_groups(title):
    assert tool.is_financial_report(title)


@pytest.mark.parametrize(
    "title",
    [
        "本公司通過105年第1季合併財務報告",  # no 董事會
        "本公司董事會105年第1季合併財務報告",  # no 通過／決議
        "本公司董事會通過105年度盈餘分配案",  # no report word
        "董事會決議財務",  # neither 財務報告, 財務報表 nor 財報
    ],
)
def test_the_subject_rule_needs_each_group(title):
    assert not tool.is_financial_report(title)


@pytest.mark.parametrize(
    "word", ["更正", "補充", "子公司", "取消", "延期", "重編", "自結"]
)
def test_each_of_the_7_words_keeps_a_subject_out(word):
    assert tool.is_financial_report(REPORT)
    assert not tool.is_financial_report(REPORT + word)
    assert not tool.is_financial_report(word + REPORT)


# --- AD1 第 2、3 點: ann_date and exp_date ----------------------------------------


Q4_2015, Q1_2016 = date(2015, 12, 31), date(2016, 3, 31)


def test_the_deadlines_and_the_quarters_are_calendar_days():
    assert [tool.deadline_of(q) for q in (Q4_2015, Q1_2016, date(2016, 6, 30),
                                          date(2016, 9, 30))] == [
        date(2016, 3, 31), date(2016, 5, 15), date(2016, 8, 14), date(2016, 11, 14),
    ]  # fmt: skip
    assert tool.quarter_of(date(2016, 1, 1)) == Q4_2015
    assert tool.quarter_of(date(2016, 3, 31)) == Q4_2015  # the deadline in
    assert tool.quarter_of(date(2016, 4, 1)) == Q1_2016
    assert tool.quarter_of(date(2016, 5, 15)) == Q1_2016
    for day in (date(2016, 5, 16), date(2016, 6, 30), date(2016, 8, 15),
                date(2016, 9, 30), date(2016, 11, 15), date(2016, 12, 31)):  # fmt: skip
        assert tool.quarter_of(day) is None, day
    assert tool.quarter_of(date(2016, 7, 1)) == date(2016, 6, 30)
    assert tool.quarter_of(date(2016, 10, 1)) == date(2016, 9, 30)


def test_ann_date_is_the_first_from_the_day_after_the_quarters_end():
    """AD1 第 2 點, 第二十一輪實作釋義: (quarter end, deadline], the first;
    a weekend's listed date, not the next session."""

    news = (
        news_on(date(2015, 12, 31))  # the quarter's end: not this quarter's
        + news_on(date(2016, 3, 12))  # a Saturday: its own date
        + news_on(date(2016, 3, 20))  # the second: not taken
        + news_on(date(2016, 4, 1))  # after the deadline: not Q4's (Q1's window)
        + news_on(date(2016, 3, 1), title="董事會通過股利分派")  # not the rule
        + news_on(date(2016, 3, 2), instrument_id=2)
        + news_on(date(2016, 3, 31), instrument_id=3)  # the deadline itself
    )
    ctx = context_for(sessions=weekdays(date(2016, 3, 1), 30), news=news)
    assert tool.ann_date(ctx, 1, Q4_2015) == date(2016, 3, 12)
    assert tool.ann_date(ctx, 1, Q1_2016) == date(2016, 4, 1)
    assert tool.ann_date(ctx, 1, date(2014, 12, 31)) is None
    assert tool.ann_date(ctx, 1, date(2015, 9, 30)) is None  # 12-31 is not Q3's
    assert tool.ann_date(ctx, 2, Q4_2015) == date(2016, 3, 2)
    assert tool.ann_date(ctx, 3, Q4_2015) == date(2016, 3, 31)
    # the order of the list does not matter: the earliest is taken
    ctx = context_for(news=news_on(date(2016, 3, 20)) + news_on(date(2016, 3, 12)))
    assert tool.ann_date(ctx, 1, Q4_2015) == date(2016, 3, 12)


def last_year(exp: date, quarter: date = Q1_2016) -> date:
    """The year before's ann_date that puts exp_date on ``exp``."""

    return tool.deadline_of(tool.year_before(quarter)) - (
        tool.deadline_of(quarter) - exp
    )


def test_exp_date_by_hand():
    """AD1 第 3 點: d calendar days; d 0 is the deadline; no year before's
    announcement no exp_date; the expected session is the first session on
    or after exp_date."""

    sessions = weekdays(date(2016, 4, 25), 20)  # Mon 04-25 .. Fri 05-20
    news = (
        news_on(date(2015, 5, 5))  # d = 10
        + news_on(date(2015, 5, 15), instrument_id=2)  # d = 0
        + news_on(date(2015, 5, 9), instrument_id=4)  # d = 6, exp a Monday
    )
    ctx = context_for(sessions=sessions, news=news)
    assert tool.exp_date(ctx, 1, Q1_2016) == date(2016, 5, 5)
    assert sessions[tool.expected_session(sessions, date(2016, 5, 5))] == date(
        2016, 5, 5
    )
    # d 0: the year's deadline, a Sunday; the expected session is Monday's
    assert tool.exp_date(ctx, 2, Q1_2016) == date(2016, 5, 15)
    assert sessions[tool.expected_session(sessions, date(2016, 5, 15))] == date(
        2016, 5, 16
    )
    assert tool.exp_date(ctx, 4, Q1_2016) == date(2016, 5, 9)
    assert tool.exp_date(ctx, 3, Q1_2016) is None
    assert tool.expected_session(sessions, None) is None
    assert tool.expected_session(sessions, date(2016, 5, 21)) is None  # after the panel
    # the Q4 deadline: 2015-03-31 less 2015-03-21 is 10 days
    ctx = context_for(sessions=sessions, news=news_on(date(2015, 3, 21)))
    assert tool.exp_date(ctx, 1, Q4_2015) == date(2016, 3, 21)
    s = 3  # T is Thu 04-28
    got = tool.expected_ahead(context_for(sessions=sessions), 3, s, Q1_2016)
    assert (got.qualifies, got.reason) == (False, "no_exp")


SESSIONS = weekdays(date(2016, 4, 25), 20)  # Mon 04-25 .. Fri 05-20
S = 3  # T is Thu 04-28; T+1 Fri 04-29, T+5 Thu 05-05, T+6 Fri 05-06


def ahead(exp: date, announced=(), sessions=SESSIONS, s=S, item_bars=None):
    news = news_on(last_year(exp)) + list(announced)
    items = () if item_bars is None else (make_item([10.0] * len(item_bars),
                                                    dates=item_bars),)  # fmt: skip
    ctx = context_for(items=items, sessions=sessions, news=news)
    return tool.expected_ahead(ctx, 1, s, Q1_2016)


def test_the_condition_is_t_plus_1_to_t_plus_5():
    """AD1 第 3 點: the expected session T+1 and T+5 qualify, T and T+6 do
    not; between sessions the next one counts."""

    assert SESSIONS[S] == date(2016, 4, 28)
    assert ahead(SESSIONS[S + 1]).qualifies
    assert ahead(SESSIONS[S + 5]).qualifies
    got = ahead(SESSIONS[S])
    assert (got.qualifies, got.reason, got.expected) == (False, "outside", S)
    got = ahead(SESSIONS[S + 6])
    assert (got.qualifies, got.reason, got.expected) == (False, "outside", S + 6)
    # a Saturday's exp_date: Monday's session (T+2) qualifies
    assert ahead(date(2016, 4, 30)).qualifies
    assert ahead(date(2016, 4, 30)).expected == S + 2
    # Sunday after T+5's week (05-08): Monday 05-09 is T+7
    assert not ahead(date(2016, 5, 8)).qualifies


def test_announced_on_or_before_t_does_not_qualify():
    """第二十一輪實作釋義「T 當天的公告」: T at any hour (after the close too)."""

    exp = SESSIONS[S + 2]
    assert ahead(exp, news_on(SESSIONS[S] + timedelta(days=1))).qualifies  # after T
    got = ahead(exp, news_on(SESSIONS[S]))
    assert (got.qualifies, got.reason) == (False, "announced")
    assert ahead(exp, news_on(date(2016, 4, 1))).reason == "announced"
    # an announcement of another quarter (before 03-31) does not count
    assert ahead(exp, news_on(date(2016, 3, 30))).qualifies
    # a title outside the rule does not count either
    assert ahead(exp, news_on(SESSIONS[S], title="董事會通過盈餘分配")).qualifies


def test_the_sessions_are_the_markets_not_the_items_bars():
    """第二十一輪實作釋義「日曆日與交易日」: a suspension (no bars) does not
    change the count; a market holiday does."""

    exp = SESSIONS[S + 5]
    few = [SESSIONS[0], SESSIONS[S], SESSIONS[S + 6]]  # the item's own bars
    assert ahead(exp, item_bars=few).qualifies == ahead(exp).qualifies is True
    holiday = [d for d in SESSIONS if d != SESSIONS[S + 2]]  # one session less
    assert not ahead(SESSIONS[S + 6]).qualifies  # Fri 05-06 is T+6
    got = ahead(SESSIONS[S + 6], sessions=holiday)
    assert (got.qualifies, got.expected) == (True, S + 5)  # with the holiday T+5
    assert not ahead(holiday[S + 6], sessions=holiday).qualifies


# --- AD1 第 4 點: the windows -----------------------------------------------------


def test_the_windows_are_p1s_buy_day_to_the_deadline_session():
    sessions = weekdays(date(2017, 1, 2), 260)
    found = [(sessions[a], sessions[b], q) for a, b, q in tool.windows(sessions)]
    assert found[:4] == [
        (date(2017, 3, 1), date(2017, 3, 31), date(2016, 12, 31)),
        (date(2017, 4, 17), date(2017, 5, 15), date(2017, 3, 31)),  # 04-15 a Saturday
        (date(2017, 7, 17), date(2017, 8, 14), date(2017, 6, 30)),  # 07-15 a Saturday
        (date(2017, 10, 16), date(2017, 11, 14), date(2017, 9, 30)),
    ]
    # a deadline on a weekend: its next session; a Saturday make-up session skipped
    saturday = date(2018, 3, 31)
    days = sorted({*weekdays(date(2018, 2, 26), 40), saturday})
    (start, end, quarter), *_ = tool.windows(days)
    assert (days[start], days[end], quarter) == (
        date(2018, 3, 1), date(2018, 4, 2), date(2017, 12, 31),
    )  # fmt: skip
    # a deadline after the panel: to its last session
    short = weekdays(date(2017, 3, 1), 10)
    assert [(short[a], short[b]) for a, b, _q in tool.windows(short)] == [
        (date(2017, 3, 1), date(2017, 3, 14))
    ]


def test_the_starts_and_the_first_windows_are_the_registered_ones():
    sessions = weekdays(date(2013, 1, 2), 3600)  # to 2026
    spec = tool.HYPOTHESES["AD1"]
    first, last = tool.segment_window(sessions, "exploration", spec)
    assert sessions[first - 1] == date(2014, 4, 15)
    assert sessions[last] == date(2019, 12, 31)
    first, last = tool.segment_window(sessions, "validation", spec)
    assert sessions[first - 1] == date(2020, 3, 2)  # 03-01 a Sunday
    assert sessions[last] == date(2024, 9, 27)
    first, _ = tool.segment_window(sessions, "used", spec)
    assert sessions[first - 1] == date(2024, 10, 15)


# --- AD1 第 5 點: the plan and the account ----------------------------------------

PLAN_SESSIONS = weekdays(date(2016, 2, 22), 40)  # Mon 02-22 .. Fri 04-15
WINDOW = (6, 28)  # Tue 03-01 .. Thu 03-31 (2015 Q4); 04-15 is session 39


def plan_context(monkeypatch, qualify, announced=None, statuses=None):
    items = {i: make_item([10.0], instrument_id=i) for i in range(1, 32)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )

    def expected_ahead(ctx, instrument_id, s, quarter):
        assert quarter == Q4_2015
        ok = instrument_id in qualify(s)
        return tool.Ahead(ok, None if ok else "outside", date(2016, 3, 31), s + 1)

    monkeypatch.setattr(tool, "expected_ahead", expected_ahead)
    ctx = context_for(
        items=items.values(), sessions=PLAN_SESSIONS, statuses=statuses or {}
    )
    ctx.announced = announced or {}
    return ctx


def test_the_plan_takes_20_by_the_hash_in_the_window_only(monkeypatch):
    """AD1 第 5 點, 第二十一輪實作釋義: every window session T, the first 20
    by sha256(<T>:<id>) of the members that qualify, fewer than 20 what
    qualifies (the rest cash); the window's last session too; nothing after
    it before the next window; the population the same days."""

    def qualify(s):
        if s == WINDOW[0]:
            return set(range(1, 31))
        if s == WINDOW[1]:
            return {1, 2, 3}
        return {1}

    ctx = plan_context(monkeypatch, qualify)
    monkeypatch.setattr(tool, "p1_lists", lambda ctx, first, last: {})
    planned = tool.plan_ad1(ctx, tool.HYPOTHESES["AD1"], 1, 39)
    assert sorted(planned.picks) == list(range(WINDOW[0] + 1, WINDOW[1] + 2))
    assert sorted(planned.population) == sorted(planned.picks)
    day = PLAN_SESSIONS[WINDOW[0]]
    order = sorted(range(1, 31), key=lambda i: pr.tie_break(day, i))
    assert planned.picks[WINDOW[0] + 1] == order[:20]
    last = PLAN_SESSIONS[WINDOW[1]]
    assert planned.picks[WINDOW[1] + 1] == sorted(
        {1, 2, 3}, key=lambda i: pr.tie_break(last, i)
    )  # the window's last session: 3 names, the rest in cash
    assert planned.population[WINDOW[0] + 1] == list(range(1, 32))
    assert (planned.signal_days, planned.event_days) == (23, 1)
    days = {d["signal_date"]: d for d in planned.days}
    assert (days["2016-03-01"]["qualified"], days["2016-03-01"]["names"]) == (30, 20)
    assert (days["2016-03-31"]["qualified"], days["2016-03-31"]["names"]) == (3, 3)
    assert (days["2016-03-02"]["qualified"], days["2016-03-02"]["names"]) == (1, 1)
    year = planned.coverage["2016"]
    assert (year["days"], year["qualified"], year["names"]) == (
        23,
        30 + 3 + 21,
        20 + 3 + 21,
    )
    assert (year["short_days"], year["empty_days"]) == (22, 0)
    assert year["outside"] == 23 * 31 - (30 + 3 + 21)


def test_the_reference_leaves_out_the_delisted_without_exp_date(monkeypatch):
    """AD1 第 7 點: T's population less the delisted or transferred with no
    exp_date; a delisted one with an exp_date stays; listed only."""

    statuses = {29: "delisted", 30: "transferred", 31: "delisted", 5: "active"}
    announced = {29: {date(2014, 12, 31): date(2015, 3, 20)}}  # 29 has an exp_date
    ctx = plan_context(monkeypatch, lambda s: {1}, announced, statuses)
    monkeypatch.setattr(tool, "p1_lists", lambda ctx, first, last: {})
    planned = tool.plan_ad1(ctx, tool.HYPOTHESES["AD1"], 1, 39)
    for at, ids in planned.reference.items():
        assert ids == [i for i in range(1, 32) if i not in (30, 31)], at
    year = planned.coverage["2016"]
    assert (year["delisted"], year["delisted_missing"]) == (3 * 23, 2 * 23)
    window = planned.windows[0]
    assert (window["members"], window["with_exp"], window["with_ann"]) == (31, 1, 0)
    assert window["exp_share"] == pytest.approx(1 / 31)


def test_the_listed_numbers_by_hand(monkeypatch):
    """AD1 第 8 點: the actual ann_date inside T+1 .. T+5, by year; the
    overlap with P1's list of the same window; a day without either list
    is not counted."""

    actual = PLAN_SESSIONS[10]  # Mon 03-07
    announced = {1: {Q4_2015: actual}}
    ctx = plan_context(monkeypatch, lambda s: {1, 2} if s < 20 else set(), announced)
    monkeypatch.setattr(tool, "p1_lists", lambda ctx, first, last: {WINDOW[0]: {2, 7}})
    planned = tool.plan_ad1(ctx, tool.HYPOTHESES["AD1"], 1, 39)
    # names on 6 .. 19 (14 days, 2 each); 1's date is inside for T = 6 .. 9
    inside = [
        s
        for s in range(6, 20)
        if PLAN_SESSIONS[s + 1] <= actual <= PLAN_SESSIONS[s + 5]
    ]
    assert inside == [6, 7, 8, 9]
    assert planned.inside == {"2016": [28, 4]}
    summary = tool.inside_summary(planned.inside)
    assert summary["share"] == pytest.approx(4 / 28)
    assert summary["years"]["2016"] == {
        "names": 28,
        "inside": 4,
        "share": pytest.approx(4 / 28),
    }
    # the overlap: {1, 2} ∩ {2, 7} over 2 names; the empty days not counted
    assert planned.overlap["AD1_P1"] == {"2016": [0.5] * 14}
    window = planned.windows[0]
    assert (window["with_ann"], window["qualified"], window["names"]) == (1, 28, 28)
    # the picks list the dates
    first = planned.rows[0]
    assert (first["quarter"], first["exp_date"]) == ("2015-12-31", "2016-03-31")
    rows = {(r["signal_date"], r["symbol"]): r for r in planned.rows}
    assert rows[("2016-03-01", "S1")]["ann_date"] == "2016-03-07"
    assert rows[("2016-03-01", "S2")]["ann_date"] == ""


def test_inside_holding_counts_calendar_days_to_the_segments_end():
    days = SESSIONS
    assert tool.inside_holding(days, 3, days[4]) and tool.inside_holding(
        days, 3, days[8]
    )
    assert tool.inside_holding(days, 3, date(2016, 4, 30))  # a Saturday inside
    assert not tool.inside_holding(days, 3, days[3])  # T itself
    assert not tool.inside_holding(days, 3, days[9])
    assert not tool.inside_holding(days, 3, None)
    assert tool.inside_holding(days, len(days) - 3, days[-1])  # T+5 after the end
    assert not tool.inside_holding(days, len(days) - 1, days[-1])


def test_p1s_list_is_round15s_plan_from_p1s_start(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 120)
    calls = []

    def plan_p1(ctx, spec, first, last):
        calls.append((ctx, spec, first, last))
        return SimpleNamespace(picks={first: [1, 2]})

    monkeypatch.setattr(r15, "plan_p1", plan_p1)
    ctx = context_for(sessions=sessions)
    start = sessions.index(date(2016, 4, 15))
    assert tool.p1_lists(ctx, 3, 100) == {start: {1, 2}}
    assert calls == [(ctx.p1, r15.HYPOTHESES["P1"], start + 1, 100)]
    assert ctx.p1.base is ctx.base
    assert tool.p1_lists(ctx, start + 30, 100) == {start + 29: {1, 2}}


def test_the_engine_is_simulate_k5_on_the_window_days():
    calls = []

    def simulate(picks, quote, first, last, hold, top):
        calls.append((picks, hold, top))
        return pr.Simulation([], [], [])

    real = pr.simulate
    pr.simulate = simulate
    try:
        planned = SimpleNamespace(picks={1: [1]}, population={1: [1, 2]},
                                  reference={1: [2]})  # fmt: skip
        tool.engines(SimpleNamespace(quote=None), "AD1", planned, 1, 5)
    finally:
        pr.simulate = real
    assert calls == [({1: [1]}, 5, 20), ({1: [1, 2]}, 5, None), ({1: [2]}, 5, None)]


def test_the_k5_accounts_hold_cash_between_the_windows_by_hand():
    """AD1 第 5 點 (#979 review): 5 accounts rotate every session; a name is
    1/20 of its account's cash; no list outside the windows is cash; a
    suspended sale day puts the sale off to the next open; the population
    1/n; the invested share by hand."""

    prices = {(i, s): (10.0, 10.0) for i in (1, 2) for s in range(1, 13)}
    prices[(1, 2)] = (10.0, 12.0)
    del prices[(1, 5)]  # 1's sale day (T+5 = session 5) has no bar
    prices[(1, 6)] = (11.0, 11.0)
    # window days 1 and 2 (lists bought at 1, 2), then cash to 12
    planned = SimpleNamespace(picks={1: [1], 2: [2]}, population={1: [1, 2], 2: [1, 2]},
                              reference={1: [2], 2: [2]})  # fmt: skip
    mine, population, reference = tool.engines(
        SimpleNamespace(quote=quote_of(prices)), "AD1", planned, 1, 12
    )
    first, second = mine.positions
    assert (first.account, second.account) == (0, 1)
    assert (first.bought, first.due, second.bought, second.due) == (1, 5, 2, 6)
    assert first.cost == pytest.approx(0.2 / 20) == second.cost
    assert (first.sold, first.how) == (6, "delayed")
    assert first.proceeds == pytest.approx(pr.sale_proceeds(first.units, 11.0))
    assert (second.sold, second.how) == (6, "close")
    units = pr.buy_units(0.01, 10.0)
    assert mine.invested[1] == pytest.approx(
        (units * 12.0 + units * 10.0) / (0.98 + units * 22.0)
    )
    # after both are sold every account is cash: the equity stays flat
    assert mine.equity[6:] == [pytest.approx(mine.equity[5])] * 6
    assert mine.invested[6:] == [0.0] * 6
    assert population.positions[0].cost == pytest.approx(0.2 / 2)
    assert [p.instrument_id for p in reference.positions] == [2, 2]


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
        (3.384, "前瞻觀察"),  # round 20's threshold is not this round's
        (3.387, "前瞻觀察"),
        (3.388, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_388(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

DAYS = 700
STOCKS = range(1, 25)
DELISTED = {25: 570, 26: 450}  # the last bar's index; 25 no announcement
TRANSFERRED = 27  # no announcement
INDEX_ID = 90
ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), DAYS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def path(i: int) -> list[tuple[float, float, float, float]]:
    out, previous = [], 50.0 + i
    for t in range(DAYS):
        close = round(previous * (1 + (i - 12) * 0.0002 + 0.004 * i * noise(i, t)), 2)
        open_ = round(previous * (1 + 0.004 * noise(i, t, "o")), 2)
        out.append((open_, max(open_, close), min(open_, close), close))
        previous = close
    return out


def days_ahead(i: int, year: int) -> int:
    """How many calendar days before the deadline i announces in ``year``."""

    return (i * 3 + year) % 23


def event_rows() -> list[dict]:
    rows = []
    last = trading_days()[-1]
    for i in (*STOCKS, 26):
        for year in range(2014, 2019):
            for end in ENDS(year):
                listed = tool.deadline_of(end) - timedelta(days=days_ahead(i, year))
                if listed > last or (i == 26 and listed > trading_days()[DELISTED[26]]):
                    continue
                rows.append({"instrument_id": i, "event_date": listed,
                             "event_type": ex.MOPS_EVENT_TYPE,
                             "title": f"本公司董事會通過{year - 1911}年合併財務報告",
                             "source": ex.MOPS_SOURCE})  # fmt: skip
    extra = [
        (1, date(2016, 3, 5), "N1董事會決議通過105年股利分派"),  # near miss
        (2, date(2016, 3, 6), "N2董事會決議通過104年度盈餘分配"),  # near miss
        (3, date(2016, 3, 7), "更正本公司董事會通過財務報告"),  # 更正
        (4, date(2016, 3, 8), "董事會通過子公司財務報告延期"),  # 子公司, 延期
        (5, date(2017, 5, 13), "本公司董事會通過合併財務報表"),  # a Saturday
    ]
    for i, listed, title in extra:
        rows.append({"instrument_id": i, "event_date": listed,
                     "event_type": ex.MOPS_EVENT_TYPE, "title": title,
                     "source": ex.MOPS_SOURCE})  # fmt: skip
    rows.append({"instrument_id": 6, "event_date": date(2016, 3, 9),
                 "event_type": "treasury_stock", "title": REPORT, "source": "other"})  # fmt: skip
    return rows


def fundamental_rows() -> list[dict]:
    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        for year in range(2012, 2019):
            total = 0.0
            for q, end in enumerate(ENDS(year), 1):
                total += 1.0 + 0.1 * ((i + q) % 4)
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": tool.deadline_of(end),
                             "eps": round(total, 2), "data_json": {}, "source": "test"})  # fmt: skip
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
                {"id": i, "exchange": "TWSE" if i % 2 else "TPEx", "symbol": f"S{i}",
                 "name": f"N{i}", "instrument_type": "stock",
                 "status": status.get(i, "active")}
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
                volume = 2_000_000 + 10_000 * i
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
        db.execute(insert(Event), event_rows())
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round21") / "stock.db")


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


def test_one_panel_serves_the_list_the_statuses_and_p1(loaded):
    assert loaded.p1.base is loaded.base
    assert set(loaded.load_seconds) == {"panel", "statuses"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    end = trading_days()[499]
    listed = {(i, day) for _at, i, _t, day in loaded.base.announcements}
    assert (5, date(2017, 5, 13)) in listed  # the Saturday's date, not Monday's
    assert all(i != 6 or day != date(2016, 3, 9) for i, day in listed)  # another source
    assert all(day <= end for _i, day in listed)
    # the year before's announcements (2015, before the first session) are read
    assert tool.ann_date(loaded, 1, date(2015, 3, 31)) == date(2015, 5, 15) - timedelta(
        days=days_ahead(1, 2015)
    )
    got = tool.exp_date(loaded, 1, date(2016, 3, 31))
    assert got == date(2016, 5, 15) - timedelta(days=days_ahead(1, 2015))
    assert tool.exp_date(loaded, 25, date(2016, 3, 31)) is None
    # the Saturday report is 2017 Q1's first only if it is the earliest
    first = date(2017, 5, 15) - timedelta(days=days_ahead(5, 2017))
    assert tool.ann_date(loaded, 5, date(2017, 3, 31)) == min(first, date(2017, 5, 13))


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[479]),
            "validation": (days[480], days[620]),
            "used": (days[621], days[699]),
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


def explore(db: Path, out: Path, *extra: str, hypotheses: str | None = "AD1") -> int:
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


def passed_report(out: Path, tmp_path: Path) -> Path:
    data = read_json(out / "explore.json")
    data["hypotheses"]["AD1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    days = trading_days()
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round21_research", "1067", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (21, 1, 71)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.388)
    assert report["read_until"] == days[479].isoformat()
    ad1 = report["hypotheses"]["AD1"]
    assert ad1["engine"] == "portfolio" and ad1["verdict"] is not None
    assert ad1["reference_excess"]["days"] == ad1["days"] > 0
    assert 0 < ad1["names"] <= 20 and ad1["qualified"] >= ad1["names"]
    assert 0 < ad1["exp_share"] < 1  # 25, 27 never; 2015's first window has all
    assert ad1["inside"]["names"] > 0
    assert ad1["overlap_p1"]["days"] > 0
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 1 個、累計 71 個" in text and "驗證段 t ≥ 3.388" in text
    lines = text.splitlines()
    assert lines[4] == "- " + tool.OVERLAP_NOTE["summary_only"]  # the report's start
    assert lines[5] == tool.OVERLAP_NOTE["AD1_survivor"]
    assert tool.LIMITS["AD1"] in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [("AD1", "round21_research", 21, "exploration", 1)]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (out / "AD1" / file).is_file(), file
    summary = (out / "AD1" / "summary.md").read_text(encoding="utf-8")
    lines = summary.splitlines()
    assert lines[2] == "- " + tool.OVERLAP_NOTE["summary_only"]
    assert lines[3] == tool.OVERLAP_NOTE["AD1_survivor"]
    assert tool.DEGENERATE["AD1"] in summary and tool.LIMITS["AD1"] in summary
    assert "超額（對對照基準，只列出）" in summary
    for key in ("AD1_reference", "AD1_P1", "AD1_listed", "AD1_windows", "AD1_inside"):
        assert tool.OVERLAP_NOTE[key] in summary, key
    picks = (out / "AD1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == (
        "signal_date,rank,exchange,symbol,quarter,exp_date,expected_session,ann_date,tie"
    )
    # nothing is bought outside the windows
    tables = read_json(out / "AD1" / "tables.json")
    signals = {row.split(",")[0] for row in picks[1:]}
    spans = [(w["first_signal"], w["last_signal"]) for w in tables["windows"]]
    assert all(any(a <= s <= b for a, b in spans) for s in signals)
    assert tables["windows"][0]["first_signal"] == "2016-03-01"
    trades = (out / "AD1" / "trades.csv").read_text(encoding="utf-8").splitlines()
    assert len(trades) > 1


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again") == 2
    assert any("AD1 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="AD1,AB1") == 2
    assert any("AB1 not registered" in line for line in refused(capsys))


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
    data["design"] = "1057"
    data["hypotheses"]["AD1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_388(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path)
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("AD1", "round21_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["AD1"] and validation["min_t"] == 3.388
    tables = read_json(tmp_path / "validation" / "AD1" / "tables.json")
    assert tables["reason"] is None, (tables["reason"], tables["prerequisites"])
    assert tables["min_t"] == 3.388
    assert tables["window"]["first_signal"] == "2018-03-01"  # the first window in it
    assert validation["hypotheses"]["AD1"]["reference_excess"]["days"] > 0
    assert validation["read_until"] == trading_days()[620].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.388（沒有 t 下限）" in text
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
    assert validate(db, tmp_path / "validation", passed_report(out, tmp_path)) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[620]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["AD1"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["AD1"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "AD1" / "used" / file).is_file(), file


def test_a_failed_validation_loads_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    real_load = tool.load
    loads = []
    monkeypatch.setattr(tool, "load", lambda *a: loads.append(a[2]) or real_load(*a))
    monkeypatch.setattr(ex, "explore_judge", lambda *a, **k: ex.FORWARD_WATCH)
    assert validate(db, tmp_path / "validation", passed_report(out, tmp_path)) == 0
    assert loads == [trading_days()[620]]
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
    ad1 = body["hypotheses"]["AD1"]
    assert set(ad1["seconds"]) == {
        "plan",
        "ann_date",
        "condition",
        "reference",
        "p1_order",
    }
    years = ad1["coverage"]
    assert sorted(years) == ["2016", "2017"]
    row = years["2016"]
    assert (
        row["members"]
        == row["no_exp"] + row["announced"] + row["outside"] + row["qualified"]
    )
    assert row["qualified"] > 0 and row["names"] <= 20 * row["days"]
    # 25 (delisted, never announced) and 27 (transferred) have no exp_date
    assert row["delisted_missing"] == 2 * row["days"]
    assert row["delisted"] == 3 * row["days"]  # 26 kept: it has one
    windows = ad1["windows"]
    assert (
        windows[0]["quarter"] == "2015-12-31"
        and windows[0]["first_signal"] == "2016-03-01"
    )
    assert all(w["with_exp"] == w["members"] - 2 for w in windows[:5])
    assert windows[0]["with_ann"] == windows[0]["members"] - 2
    subjects = body["subjects"]
    assert subjects["years"]["2016"]["companies"] == 25  # 1..24 and 26
    assert subjects["near_miss"] == {"2016": 2}
    assert [text for text, _n in subjects["near_miss_subjects"]] == [
        "〈公司〉董事會決議通過#年股利分派", "〈公司〉董事會決議通過#年度盈餘分配",
    ]  # fmt: skip
    assert subjects["blocked"] == {"更正": 1, "補充": 0, "子公司": 1, "取消": 0,
                                   "延期": 1, "重編": 0, "自結": 0}  # fmt: skip
    assert sum(r["rows"] for r in subjects["quarters"].values()) == sum(
        r["rows"] for r in subjects["years"].values()
    )
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "statuses"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "每個窗口" in md
    assert "## AD1：符合主旨規則的重大訊息" in md and "不含的 7 個詞各擋掉的則數" in md
    assert tool.DEGENERATE["AD1"] in md


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "AD1"])  # fmt: skip


def test_the_subject_counts_by_hand():
    news = [
        (0, 1, "N1董事會通過財報", date(2016, 3, 5)),
        (0, 1, "N1董事會通過財報", date(2016, 5, 5)),
        (0, 2, "董事會決議財務報表", date(2016, 5, 6)),
        (0, 2, "S2董事會決議１０５年第１季股利", date(2016, 5, 7)),
        (0, 3, "董事會通過財報更正補充", date(2017, 1, 3)),
        (0, 3, "公告重大訊息", date(2017, 1, 4)),
    ]
    items = [make_item([1.0], instrument_id=i) for i in (1, 2, 3)]
    got = tool.subject_counts(context_for(items=items, news=news))
    assert got["quarters"] == {"2016Q1": {"rows": 1, "companies": 1},
                               "2016Q2": {"rows": 2, "companies": 2}}  # fmt: skip
    assert got["years"] == {"2016": {"rows": 3, "companies": 2}}
    assert got["near_miss"] == {"2016": 1}
    assert got["near_miss_subjects"] == [("〈公司〉董事會決議#年第#季股利", 1)]
    assert (got["blocked"]["更正"], got["blocked"]["補充"], got["blocked"]["自結"]) == (
        1,
        1,
        0,
    )


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
    assert explore(copied, tmp_path / "out") == 2
    assert refused(capsys) == [problem]
    assert opened == [] and not (tmp_path / "out").exists()


def test_an_unwritable_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path)
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
        assert explore(copied, out) == 2
    finally:
        copied.parent.chmod(0o755)
    assert unwritable(refused(capsys), copied)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    report = passed_report(out, tmp_path)
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
