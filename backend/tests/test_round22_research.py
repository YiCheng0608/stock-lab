"""tools/research/round22_research.py: the registered AE1 (#1080).

The registered numbers (the hold, the start, the thresholds) are asserted as
written in docs/spec/evidence.md 第二十二輪：AE1.  The announcement session
a, EAR, its population mean and the condition are checked on hand-made
dates and series (the expected numbers worked out in the test); the trades
(T+1's open, the 60th session, the locks, the delays, the occupancy) on a
synthetic copy whose paths are made for them; the gate ("each once") and the
reports run on the same copy on a compressed calendar (``compressed``): the
segments and the floors are moved into the fixture's 300 sessions,
everything else is the registered one.
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
from bisect import bisect_left
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
from app.strategies import levels

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1080#issuecomment-1"


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
tr = _tool("trade_research")
r5 = _tool("round5_research")
r9 = _tool("round9_research")
r10 = _tool("round10_research")
r14 = _tool("round14_research")
r15 = _tool("round15_research")
r20 = _tool("round20_research")
r21 = _tool("round21_research")
tool = _tool("round22_research")
NAMES = ("AE1",)
REPORT = "本公司董事會通過105年第1季合併財務報告"


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 22))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    ae1 = h["AE1"]
    assert (ae1["engine"], ae1["kind"], ae1["event"]) == (
        "trade",
        "event",
        "ear_positive",
    )
    assert (ae1["entry_days"], ae1["stop"], ae1["target"], ae1["hold"]) == (
        1,
        None,
        None,
        60,
    )
    assert ae1["start"] == ("date", date(2013, 4, 1))
    assert ae1["market_filter"] is False


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        22,
        1,
        72,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.392
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(72), 3) == 3.392
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "f43c86f2" and tool.DESIGN == "1080"
    assert (tool.EAR_BEFORE, tool.EAR_AFTER, tool.SIGNAL_AFTER, tool.EAR_MIN) == (
        2,
        1,
        1,
        0.0,
    )
    assert tool.MIN_DAYS == tr.MIN_DAYS == 60 and tool.OVERLAP == tr.OVERLAP == 20
    assert tool.REFERENCE_STATUSES == ("delisted", "transferred")
    # imported, not rewritten
    assert tool._reference is r21._reference is r20._reference
    assert tool.REFERENCE_STATUSES is r21.REFERENCE_STATUSES
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool.enter_next_open is r9.enter_next_open
    assert tool.NO_STOP is r9.NO_STOP
    assert "load_context" in tool.load.__code__.co_names
    assert "trade_context" in tool.load.__code__.co_names
    assert "r21.announced(" in inspect.getsource(tool.events)
    assert "r21.plan_ad1(" in inspect.getsource(tool.ad1_names)
    source = inspect.getsource(tool.trade_signal)
    for call in ("tr.TradeBars(", "enter_next_open(", "tr._trade_row(", "tr.baseline("):
        assert call in source, call
    source = inspect.getsource(tool.run_trades)
    assert "tr.State(" in source and "tr.stats(" in source
    assert "explore_judge" in tool.run_trades.__code__.co_names
    assert "self.ctx.trade.universe(" in inspect.getsource(tool.ReferenceView)


def _swap(key: str, value):
    return {**tool.HYPOTHESES, "AE1": {**tool.HYPOTHESES["AE1"], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1080 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.392
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.388),
        # a: the first session on or after ann_date
        (tool, "SESSION_RULE", "the last session on or before ann_date"),
        # EAR: a-2 .. a+1, the closes, the population's mean, missing
        (tool, "EAR_BEFORE", 3),
        (tool, "EAR_AFTER", 2),
        (tool, "CLOSE_RULE", "a suspended bar's close too"),
        (tool, "MEAN_RULE", "every member, a missing return as 0"),
        (tool, "MEAN_RULE", "T's population less the occupied members"),
        # the condition: EAR > 0, T = a+1, one per quarter, not ranked
        (tool, "EAR_MIN", -1e-9),
        (tool, "SIGNAL_AFTER", 2),
        (tool, "SIGNAL_RULE", "the 20 highest EAR"),
        (tool, "SAME_DAY_RULE", "the later quarter first"),
        # the entry, the 60-day hold, no stop and no target
        (tool, "HYPOTHESES", _swap("hold", 59)),
        (tool, "HYPOTHESES", _swap("entry_days", 2)),
        (tool, "HYPOTHESES", _swap("stop", 0.9)),
        (tool, "HYPOTHESES", _swap("target", 1.2)),
        (tool, "NO_STOP", 0.0),
        # the reference, the start
        (tool, "REFERENCE_RULE", "less every delisted member"),
        (tool, "REFERENCE_STATUSES", ("delisted",)),
        (r20, "REFERENCE_STATUSES", ("delisted",)),  # what _reference reads
        (tool, "AE1_START", date(2013, 1, 1)),
        (tool, "START_RULE", "the quarters before the start too"),
        (tool, "HYPOTHESES", _swap("start", ("date", date(2014, 4, 1)))),
        # ann_date and the subject rule: round21_research's, by its hash
        (r21, "SUBJECT_ALL", ("董事會", "通過")),
        (r21, "SUBJECT_NONE", ("更正",)),
        (r21, "ANN_RULE", "the last matching announcement"),
        (r21, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 15, 6, 0), (11, 14, 9, 0))),
        (r21, "NEWS_SOURCE", "mops_other"),
        (r21, "VERSION", 2),
        # the listed parts: AD1's list and the overlap
        (r21, "HYPOTHESES", {**r21.HYPOTHESES, "AD1": {**r21.HYPOTHESES["AD1"], "top": 19}}),
        (tool, "AD1_RULE", "every window, before AD1's start too"),
        # the trades: trade_research and round9_research
        (tr, "SLIPPAGE", 0.001),
        (tr, "COST_BPS", 50.0),
        (tool, "MIN_DAYS", 50),
        (tool, "OVERLAP", 60),
        (tr, "VERSION", 2),
        (r9, "VERSION", 2),
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
        (tool, "CUMULATIVE", 73),
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


# AC-1: measured on master f43c86f2 before this tool existed.  forward_watch's
# F2 row reads round10_research's hash, its P2 row round15_research's and its
# A1 row round17_research's; AE1 reads round21 (ann_date, the subject rule,
# AD1, the reference), trade_research (the trades), round9 (the exit without a
# stop or a target), round10 (the overlap) and explore_research (the MOPS
# list); round12's J3 is the same kind of trade.
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
    "round21_research": (1, "2c8d393563383ff5bc4376e0fdb7ebbc4df435074c4cf4c7b9fadf48a5984220"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round21_research", "trade_research", "round9_research", "round12_research",
     "round10_research", "round15_research", "round17_research", None],
)  # fmt: skip
def test_the_tools_ae1_reads_are_the_ledgers(name):
    """AC-1: the hashes AE1 and forward_watch read are the ones in the public
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


# AC-1: portfolio_research.ranking_key's source on master f43c86f2
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
    section = text.split("**第二十二輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    assert tool.DEGENERATE["AE1"] in section
    assert any(tool.DEGENERATE["AE1"] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert tool.LIMITS["AE1"] in section
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.392 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round22_research.py" in section
    assert "本輪 1 個、累計 72 個" in section
    assert "t < 3.392（沒有 t 下限）" in section
    # the "前瞻觀察" line of the reports, word for word
    assert "t < 3.392（沒有 t 下限）" in tool._watch_line(tool.VALIDATION_MIN_T)
    for words in ("未讀全文", "工作論文", "對假設有利", "`overlap=20`", "保守的下限"):
        assert words in tool.LIMITS["AE1"] + tool.OVERLAP_NOTE["summary_only"], words


# --- hand-made dates and series ---------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes: dict[int, float], sessions, instrument_id=1, suspended=()):
    """Bars on the sessions in ``closes`` (session index -> close)."""

    item = lib.Series(instrument_id)
    item.suspended.append(0)
    for at, s in enumerate(sorted(closes)):
        day = sessions[s]
        item.position[day] = at
        item.dates.append(day)
        item.session.append(s)
        for column in (item.open, item.high, item.low, item.close):
            column.append(closes[s])
        item.volume.append(2_000_000.0)
        item.scale.append(1.0)
        item.suspended.append(item.suspended[-1] + int(s in suspended))
    return item


def context_for(items=(), sessions=(), statuses=None, news=(), members=None):
    """``members`` (session -> instrument ids) stands for T's population;
    by default every item with an unsuspended bar on the session."""

    sessions = list(sessions)
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
    panel = lib.Panel(sessions, series, {}, {}, symbols)
    market = pr.Market(panel, raw_rows, {}, None)
    base = ex.Context(market)
    base.announcements.extend(news)
    trade = tr.Context(market, Path("unused"), sessions[-1] if sessions else date.min)
    trade.statuses = dict(statuses or {})

    def universe(s):
        out = []
        for item in items:
            at = item.position.get(sessions[s])
            if at is None or item.is_suspended(at):
                continue
            if members is not None and item.instrument_id not in members.get(s, ()):
                continue
            out.append((item, at))
        return out

    trade.universe = universe
    return tool.Context(base, trade)


SESSIONS = weekdays(date(2016, 4, 25), 8)  # Mon 04-25 .. Wed 05-04
A, T = 4, 5  # a is Fri 04-29, T = a+1 Mon 05-02; a-2 is Wed 04-27


def hand_items(**extra):
    """1: 10 -> 11 (+10%), 2: 20 -> 21 (+5%), 3: 50 -> 45 (-10%), with a bar
    on every session; 4: no bar on a-2."""

    full = {s: 1.0 for s in range(len(SESSIONS))}
    one = make_item({**full, 2: 10.0, 3: 10.4, 4: 10.7, 5: 11.0}, SESSIONS, 1, **extra)
    two = make_item({**full, 2: 20.0, 5: 21.0}, SESSIONS, 2)
    three = make_item({**full, 2: 50.0, 5: 45.0}, SESSIONS, 3)
    four = make_item({s: 30.0 for s in range(len(SESSIONS)) if s != 2}, SESSIONS, 4)
    return [one, two, three, four]


def test_a_is_the_first_session_on_or_after_ann_date():
    days = weekdays(date(2016, 4, 18), 10)  # Mon 04-18 .. Fri 04-29
    holiday = [d for d in days if d != date(2016, 4, 20)]  # Wed 04-20 closed
    assert tool.announcement_session(days, date(2016, 4, 19)) == 1  # a session
    assert tool.announcement_session(days, date(2016, 4, 23)) == 5  # Sat -> Mon
    assert days[5] == date(2016, 4, 25)
    assert holiday[tool.announcement_session(holiday, date(2016, 4, 20))] == date(
        2016, 4, 21
    )  # the holiday -> the next session
    assert tool.announcement_session(days, date(2016, 5, 2)) is None  # after the panel


def test_the_events_are_t_a_plus_1_from_the_first_announcement_of_2013q1_on():
    days = weekdays(date(2013, 3, 25), 15)  # Mon 03-25 .. Fri 04-12
    title = "本公司董事會通過102年第1季合併財務報告"
    news = [
        (
            0,
            1,
            "本公司董事會通過101年度合併財務報告",
            date(2013, 3, 29),
        ),  # 2012Q4: before the start
        (0, 2, title, date(2013, 4, 6)),  # a Saturday: a is Mon 04-08
        (0, 3, title, date(2013, 4, 2)),
        (0, 3, title, date(2013, 4, 3)),  # the same quarter's second: not used
        (0, 4, title, date(2013, 4, 12)),  # a is the last session: T is after the panel
        (0, 5, "本公司董事會通過102年第1季合併財務報告更正", date(2013, 4, 2)),  # 更正
    ]
    ctx = context_for([], days, news=news)
    got = tool.events(ctx)
    q1 = date(2013, 3, 31)
    at = {d: k for k, d in enumerate(days)}
    assert got == {
        at[date(2013, 4, 9)]: [(2, q1, at[date(2013, 4, 8)])],
        at[date(2013, 4, 3)]: [(3, q1, at[date(2013, 4, 2)])],
    }
    assert set(ctx.seconds) == {"ann_date", "session"}


def test_ear_by_hand():
    ctx = context_for(hand_items(), SESSIONS)
    mean = (0.1 + 0.05 - 0.1) / 3  # 4 has no close on a-2: not in the mean
    assert tool.population_mean(ctx, T) == (pytest.approx(mean, abs=1e-15), 3)
    got = tool.ear(ctx, T, 1)
    assert got.reason is None and got.own == pytest.approx(0.1)
    assert got.value == pytest.approx(0.1 - mean, abs=1e-15)
    assert tool.ear(ctx, T, 2).value == pytest.approx(0.05 - mean, abs=1e-15)
    assert tool.ear(ctx, T, 3).reason == "not_positive"
    assert tool.ear(ctx, T, 4).reason == "missing"  # no close on a-2
    # the item's own close of a-1 and a (10.4, 10.7) is not read
    assert tool.window_return(ctx.panel.series[1], SESSIONS, A) == pytest.approx(0.1)


def test_a_suspension_between_a_minus_2_and_a_plus_1_changes_nothing():
    """a-2 and a+1 are market sessions: the item's bars between are not read."""

    plain = context_for(hand_items(), SESSIONS)
    halted = context_for(hand_items(suspended=(3, 4)), SESSIONS)
    assert halted.panel.series[1].is_suspended(
        halted.panel.series[1].position[SESSIONS[3]]
    )
    assert tool.ear(halted, T, 1).value == tool.ear(plain, T, 1).value


def test_a_missing_close_on_a_minus_2_or_t_and_the_population():
    items = hand_items()
    halted = make_item(
        {s: 10.0 for s in range(len(SESSIONS))}, SESSIONS, 5, suspended=(2,)
    )
    gone = make_item(
        {s: 10.0 for s in range(len(SESSIONS))}, SESSIONS, 6, suspended=(T,)
    )
    ctx = context_for([*items, halted, gone], SESSIONS, members={T: {1, 2, 3, 4, 5}})
    assert tool.ear(ctx, T, 5).reason == "missing"  # suspended on a-2
    assert tool.ear(ctx, T, 6).reason == "not_member"  # suspended on T = a+1
    assert tool.population_mean(ctx, T)[1] == 3  # 4, 5 left out of the mean
    outside = context_for(items, SESSIONS, members={T: {2, 3, 4}})
    assert tool.ear(outside, T, 1).reason == "not_member"  # not in T's population
    assert tool.population_mean(outside, T) == (pytest.approx(-0.025), 2)
    busy = tool.ear(ctx, T, 1, busy={1: T})
    assert busy.reason == "occupied"
    assert tool.ear(ctx, T, 1, busy={1: T - 1}).reason is None  # sold on T-1: free


def test_ear_exactly_0_does_not_qualify_and_no_mean_is_missing():
    full = {s: 1.0 for s in range(len(SESSIONS))}
    same = [make_item({**full, 2: 10.0, 5: 11.0}, SESSIONS, i) for i in (1, 2)]
    ctx = context_for(same, SESSIONS)
    got = tool.ear(ctx, T, 1)
    assert (got.reason, got.value) == ("not_positive", 0.0)
    lonely = make_item({s: 1.0 for s in range(len(SESSIONS)) if s != 2}, SESSIONS, 1)
    ctx = context_for([lonely], SESSIONS)
    assert tool.population_mean(ctx, T) == (None, 0)
    assert tool.ear(ctx, T, 1).reason == "missing"


def test_the_listed_counts_and_the_reference_by_hand():
    items = hand_items()
    statuses = {3: "delisted", 4: "transferred"}
    q = date(2016, 3, 31)
    ctx = context_for(items, SESSIONS, statuses=statuses)
    ctx.events = {T: [(1, q, A), (2, q, A), (3, q, A), (4, q, A), (9, q, A)]}
    ctx.ad1.announced = {1: {q: SESSIONS[A]}, 2: {q: SESSIONS[A]}, 4: {q: SESSIONS[A]}}
    listed = tool.Listed()
    signals = tool.count_day(ctx, listed, T)
    assert [row[0] for row in signals] == [1, 2]
    tool.reference_counts(ctx, listed, T, {q})
    tables = listed.tables()
    row = tables["years"]["2016"]
    assert row == {"with_ann": 4, "not_member": 1, "occupied": 0, "missing": 1,
                   "not_positive": 1, "signals": 2, "signal_days": 1,
                   "delisted": 2, "delisted_missing": 1}  # fmt: skip
    assert tables["quarters"] == {"2016Q1": row}
    # the reference leaves out 3 (delisted, no ann_date for q), keeps 4 (has one)
    view = tool.ReferenceView(ctx, q)
    assert [item.instrument_id for item, _at in view.universe(T)] == [1, 2, 4]


def test_one_items_two_quarters_on_one_t_trade_the_earlier_only():
    """第二十二輪實作釋義: the later quarter is occupied by the earlier one's
    trade, made before the later one is judged."""

    q4, q1 = date(2015, 12, 31), date(2016, 3, 31)
    ctx = context_for(hand_items(), SESSIONS)
    ctx.events = {T: [(1, q4, A), (1, q1, A), (2, q1, A)]}
    busy: dict[int, int] = {}
    made = []

    def traded(instrument_id, quarter, a, got):
        made.append((instrument_id, quarter))
        busy[instrument_id] = T + 60  # held: occupied from T

    listed = tool.Listed()
    signals = tool.count_day(ctx, listed, T, busy, traded)
    assert made == [(1, q4), (2, q1)] == [(row[0], row[1]) for row in signals]
    tables = listed.tables()
    assert tables["quarters"]["2016Q1"]["occupied"] == 1
    assert tables["quarters"]["2015Q4"]["signals"] == 1
    assert tables["years"]["2016"]["signal_days"] == 1


def test_the_overlap_with_ad1_by_hand():
    q1, q2, q3 = date(2016, 3, 31), date(2016, 6, 30), date(2016, 9, 30)
    trades = [
        {"quarter": q.isoformat(), "instrument_id": i, "signal_date": day}
        for q, i, day in (
            (q1, 1, date(2016, 4, 20)), (q1, 2, date(2016, 4, 21)),
            (q1, 3, date(2016, 4, 22)), (q2, 1, date(2016, 7, 20)),
            (q3, 5, date(2016, 10, 20)),
        )
    ]  # fmt: skip
    names = {q1: {1, 9}, q2: {1}}  # q3: AD1 has no list, not counted
    got = tool.ad1_overlap(trades, names)
    assert got["years"] == {"2016": {"days": 2, "mean": pytest.approx((1 / 3 + 1) / 2)}}
    assert (got["signals"], got["both"], got["share"]) == (4, 2, 0.5)


def test_ad1s_names_are_round21s_plan_from_ad1s_start(monkeypatch):
    days = weekdays(date(2014, 4, 1), 30)
    ctx = context_for([], days)
    seen = {}

    def plan(ctx_, spec, first, last, keep_rows=True):
        seen.update(ctx=ctx_, spec=spec, first=first, last=last)
        return SimpleNamespace(
            days=[{"signal_date": days[12].isoformat(), "quarter": "2014-03-31"},
                  {"signal_date": days[13].isoformat(), "quarter": "2014-03-31"}],
            picks={13: [1, 2], 14: [2, 3]},
        )  # fmt: skip

    monkeypatch.setattr(r21, "plan_ad1", plan)
    got = tool.ad1_names(ctx, 1, 29)
    assert got == {date(2014, 3, 31): {1, 2, 3}}
    assert seen["ctx"] is ctx.ad1 and seen["spec"] is r21.HYPOTHESES["AD1"]
    start = days.index(date(2014, 4, 15))  # AD1's start
    assert (seen["first"], seen["last"]) == (start + 1, 29)


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
        (3.388, "前瞻觀察"),  # round 21's threshold is not this round's
        (3.391, "前瞻觀察"),
        (3.392, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_392(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

DAYS = 300
BACKGROUND = range(1, 17)  # an announcement each quarter
DESIGNED = range(17, 25)  # only the announcements below
DELISTED = {25: 150, 26: 120, 28: 230}  # the last bar's index; 26 announces
TRANSFERRED = 27  # no announcement
INDEX_ID = 90
ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731


def trading_days() -> list[date]:
    return weekdays(date(2016, 1, 4), DAYS)


def at(day: date) -> int:
    return trading_days().index(day)


# (stock, listed date) of the designed announcements and what they test
ANNOUNCED = {
    (17, date(2016, 3, 10)): "held to the 60th session",
    (17, date(2016, 4, 20)): "occupied by the first",
    (18, date(2016, 4, 16)): "a Saturday; the 60th session locked at limit down",
    (19, date(2016, 4, 21)): "T+1 suspended",
    (20, date(2016, 4, 26)): "T+1 locked at limit up",
    (21, date(2016, 4, 27)): "EAR < 0",
    (22, date(2016, 5, 3)): "a-2 suspended",
    (23, date(2016, 5, 4)): "a-1 suspended; the 60th session suspended",
    (24, date(2016, 7, 20)): "EAR < 0, the quarter's first",
    (24, date(2016, 8, 1)): "the quarter's second: not used",
}


def designed_bars() -> dict[tuple[int, int], str]:
    """(stock, session) -> the bar's kind."""

    days = trading_days()
    a = {key: bisect_left(days, key[1]) for key in ANNOUNCED}  # the next session
    drops = {(21, date(2016, 4, 27)), (24, date(2016, 7, 20))}
    kinds = {
        (key[0], s + 1): "drop" if key in drops else "jump" for key, s in a.items()
    }
    s17 = a[(17, date(2016, 3, 10))]
    s18 = a[(18, date(2016, 4, 16))]
    s19 = a[(19, date(2016, 4, 21))]
    s20 = a[(20, date(2016, 4, 26))]
    s22 = a[(22, date(2016, 5, 3))]
    s23 = a[(23, date(2016, 5, 4))]
    kinds.update({
        (18, s18 + 2 + 59): "lock_down",  # the 60th session counting the fill
        (19, s19 + 2): "suspended",
        (20, s20 + 2): "lock_up",
        (22, s22 - 2): "suspended",
        (23, s23 - 1): "suspended",
        (23, s23 + 2 + 59): "suspended",
    })  # fmt: skip
    assert s17 + 2 + 59 > a[(17, date(2016, 4, 20))] + 1  # still held then
    return kinds


BARS = designed_bars()


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
    for t in range(DAYS):
        kind = BARS.get((i, t))
        if kind == "suspended":
            out.append((previous,) * 4)
            continue
        if kind in ("lock_up", "lock_down"):
            price = limit(previous, kind == "lock_up")
            out.append((price,) * 4)
            previous = price
            continue
        if kind in ("jump", "drop"):
            close = round(previous * (1.08 if kind == "jump" else 0.92), 2)
        else:
            close = round(
                previous * (1 + (i - 12) * 0.0001 + 0.001 * i * noise(i, t)), 2
            )
        open_ = (
            previous if kind else round(previous * (1 + 0.002 * noise(i, t, "o")), 2)
        )
        high = round(max(open_, close) * 1.002, 2)
        low = round(min(open_, close) * 0.998, 2)
        out.append((open_, high, low, close))
        previous = close
    return out


def days_ahead(i: int, year: int) -> int:
    """How many calendar days before the deadline i announces in ``year``."""

    return (i * 3 + year) % 23


def event_rows() -> list[dict]:
    rows = []
    last = trading_days()[-1]

    def row(i, listed, title):
        return {"instrument_id": i, "event_date": listed, "event_type": ex.MOPS_EVENT_TYPE,
                "title": title, "source": ex.MOPS_SOURCE}  # fmt: skip

    for i in (*BACKGROUND, 26):
        for year in (2015, 2016):
            for end in ENDS(year):
                listed = r21.deadline_of(end) - timedelta(days=days_ahead(i, year))
                if listed > last or (i == 26 and listed > trading_days()[DELISTED[26]]):
                    continue
                rows.append(
                    row(i, listed, f"本公司董事會通過{year - 1911}年合併財務報告")
                )
    for i, listed in ANNOUNCED:
        rows.append(row(i, listed, REPORT))
    # not the subject rule, not the MOPS list
    rows.append(row(17, date(2016, 7, 5), "本公司董事會決議通過105年股利分派"))
    rows.append({**row(18, date(2016, 7, 6), REPORT), "event_type": "treasury_stock",
                 "source": "other"})  # fmt: skip
    return rows


def fundamental_rows() -> list[dict]:
    rows = []
    for i in (*BACKGROUND, *DESIGNED, *DELISTED, TRANSFERRED):
        for year in range(2014, 2017):
            total = 0.0
            for q, end in enumerate(ENDS(year), 1):
                total += 1.0 + 0.1 * ((i + q) % 4)
                rows.append({"instrument_id": i, "period_end": end, "fiscal_period": f"Q{q}",
                             "announcement_date": r21.deadline_of(end),
                             "eps": round(total, 2), "data_json": {}, "source": "test"})  # fmt: skip
    return rows


def build(path_: Path) -> Path:
    engine = create_engine(f"sqlite:///{path_}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ids = [*BACKGROUND, *DESIGNED, *DELISTED, TRANSFERRED]
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
                halted = BARS.get((i, t)) == "suspended"
                volume = 0 if halted else 2_000_000 + 10_000 * i
                bars.append(
                    {"instrument_id": i, "trading_date": day, "open": open_, "high": high,
                     "low": low, "close": close, "adj_close": close, "volume": volume,
                     "turnover": close * volume, "turnover_status": "available",
                     "source": "test", "is_suspended": halted}
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
    return build(tmp_path_factory.mktemp("round22") / "stock.db")


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


def test_one_panel_serves_the_list_the_trades_and_ad1(loaded):
    assert loaded.ad1.base is loaded.base and loaded.trade.market is loaded.market
    assert loaded.ad1.statuses is loaded.trade.statuses
    assert set(loaded.load_seconds) == {"panel", "trade"}
    assert (
        loaded.statuses[25] == "delisted"
        and loaded.statuses[TRANSFERRED] == "transferred"
    )
    assert loaded.trade.last_bar[25] == trading_days()[DELISTED[25]]
    listed = {(i, day) for _at, i, _t, day in loaded.base.announcements}
    assert (18, date(2016, 4, 16)) in listed  # the Saturday's date, not Monday's
    assert (18, date(2016, 7, 6)) not in listed  # another source


def used_run(loaded, monkeypatch) -> dict:
    """AE1 on the signal dates 19 .. 298, the last session 299 (the used
    segment's rules: no floor, no delisted check; nothing else differs)."""

    days = trading_days()
    monkeypatch.setattr(
        tool, "SEGMENTS", {**tool.SEGMENTS, "used": (days[20], days[299])}
    )
    loaded.trade.baselines.clear()
    loaded.trade.universes.clear()
    return tool.run_trades(loaded, Path("unused"), "AE1", "used")


def net(sold: float, bought: float) -> float:
    return sold * (1 - 5e-4) / (bought * (1 + 5e-4)) - 1 - 58.5e-4


def test_ae1_trades_by_hand(loaded, monkeypatch):
    d = trading_days()
    result = used_run(loaded, monkeypatch)
    trades = {(t["signal_date"], t["symbol"]): t for t in result["_trades"]}
    designed = {key for key in trades if int(key[1][1:]) in DESIGNED}
    assert designed == {
        (d[49], "S17"),  # a Thu 03-10, T Fri 03-11; 04-20's T is occupied
        (d[76], "S18"),  # a Mon 04-18 (the Saturday's), T Tue 04-19
        (d[79], "S19"),
        (d[82], "S20"),
        (d[88], "S23"),
    }  # S21: EAR < 0; S22: a-2 suspended; S24: the quarter's first is EAR < 0
    s17 = loaded.panel.series[17]
    first = trades[(d[49], "S17")]
    assert (
        first["announcement_session"] == d[48].isoformat()
        and first["quarter"] == "2015-12-31"
    )
    assert (first["fill_date"], first["exit_date"], first["exit_reason"]) == (
        d[50], d[109], "time",  # the fill is day 1, the 60th session's close
    )  # fmt: skip
    assert first["holding"] == 60 and first["stop"] is None and first["target"] is None
    assert first["net"] == pytest.approx(
        net(s17.close[s17.position[d[109]]], s17.open[s17.position[d[50]]]), rel=1e-12
    )
    # EAR by hand on the copy: close(T) / close(a-2) - 1 less T's population mean
    members = lib.universe(loaded.panel, d[49], lib.DEFAULT_MIN_LOTS)
    returns = {
        item.instrument_id: item.close[item.position[d[49]]]
        / item.close[item.position[d[46]]]
        - 1
        for item, _at in members
        if d[46] in item.position and not item.is_suspended(item.position[d[46]])
    }
    assert first["window_return"] == pytest.approx(returns[17])
    assert first["population_window"] == pytest.approx(
        sum(returns.values()) / len(returns)
    )
    assert first["ear"] == pytest.approx(
        returns[17] - sum(returns.values()) / len(returns)
    )
    halted, locked = trades[(d[79], "S19")], trades[(d[82], "S20")]
    assert (halted["net"], halted["entry_reason"]) == (None, "not_tradable")
    assert (locked["net"], locked["entry_reason"]) == (None, "limit_up")
    down = trades[(d[76], "S18")]
    s18 = loaded.panel.series[18]
    assert down["announcement_session"] == d[75].isoformat()  # Mon 04-18
    assert (down["exit_date"], down["exit_reason"], down["limit_delayed"]) == (
        d[77 + 60], "time", True,
    )  # fmt: skip
    assert down["holding"] == 61
    assert down["net"] == pytest.approx(
        net(s18.open[s18.position[d[137]]], s18.open[s18.position[d[77]]]), rel=1e-12
    )
    held = trades[(d[88], "S23")]
    s23 = loaded.panel.series[23]
    assert (held["exit_date"], held["exit_reason"]) == (d[89 + 60], "time")
    assert held["suspension_delayed"] is True and held["holding"] == 61
    assert held["net"] == pytest.approx(
        net(s23.open[s23.position[d[149]]], s23.open[s23.position[d[89]]]), rel=1e-12
    )
    assert result["abandon_reasons"]["limit_up"] >= 1
    assert result["abandon_reasons"]["not_tradable"] >= 1
    assert result["exits"]["stop"] == result["exits"]["target"] == 0
    assert result["listed"]["years"]["2016"]["occupied"] >= 1  # S17's 2nd quarter
    # the excess is over T's population, the reference over it less 25 and 27
    expected = tr.baseline(loaded.trade, 49, 50, 109, 299)
    assert first["population"] == expected["mean"]
    assert first["excess"] == pytest.approx(first["net"] - expected["mean"])
    view = tool.ReferenceView(loaded, date(2015, 12, 31))
    kept = {item.instrument_id for item, _at in view.universe(49)}
    assert {25, 27}.isdisjoint(kept) and 26 in kept
    assert first["reference"] == tr.baseline(view, 49, 50, 109, 299)["mean"]
    assert first["reference_excess"] == pytest.approx(first["net"] - first["reference"])
    assert result["reference_excess"]["days"] == result["excess"]["days"]


def test_the_quarters_second_announcement_and_the_occupied_one_make_no_trade(
    loaded, monkeypatch
):
    d = trading_days()
    result = used_run(loaded, monkeypatch)
    symbols = {(t["signal_date"], t["symbol"]) for t in result["_trades"]}
    assert (d[151], "S24") not in symbols  # 08-01's T: the second of 2016Q2
    assert (d[78], "S17") not in symbols  # 04-20's T: occupied to 06-02
    assert (d[83], "S21") not in symbols and (d[87], "S22") not in symbols
    quarters = result["listed"]["quarters"]
    assert quarters["2016Q2"]["not_positive"] >= 1  # S24's first


# --- the gate and the reports --------------------------------------------------


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[199]),
            "validation": (days[200], days[259]),
            "used": (days[260], days[299]),
        },
    )
    floors = {"exploration": 30, "validation": 10}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(tool, "MIN_DAYS", 2)
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


def explore(db: Path, out: Path, *extra: str, hypotheses: str | None = "AE1") -> int:
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
    data["hypotheses"]["AE1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    days = trading_days()
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round22_research", "1080", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (22, 1, 72)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.392)
    assert report["read_until"] == days[199].isoformat()
    ae1 = report["hypotheses"]["AE1"]
    assert ae1["engine"] == "trade" and ae1["verdict"] is not None
    assert ae1["reason"] is None, ae1
    assert ae1["trade_days"] >= 2 and ae1["trades"] > 0
    assert ae1["reference_excess"]["days"] == ae1["excess"]["days"]
    assert "overlap_ad1" in ae1
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 1 個、累計 72 個" in text and "驗證段 t ≥ 3.392" in text
    lines = text.splitlines()
    assert lines[4] == "- " + tool.OVERLAP_NOTE["summary_only"]  # the report's start
    assert lines[5] == tool.OVERLAP_NOTE["AE1_survivor"]
    assert tool.LIMITS["AE1"] in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [("AE1", "round22_research", 22, "exploration", 1)]
    for file in ("summary.md", "tables.json", "trades.csv", "days.csv"):
        assert (out / "AE1" / file).is_file(), file
    summary = (out / "AE1" / "summary.md").read_text(encoding="utf-8")
    lines = summary.splitlines()
    assert lines[2] == "- " + tool.OVERLAP_NOTE["summary_only"]
    assert lines[3] == tool.OVERLAP_NOTE["AE1_survivor"]
    assert tool.DEGENERATE["AE1"] in summary and tool.LIMITS["AE1"] in summary
    assert "超額（對對照基準，只列出）" in summary
    for key in ("AE1_reference", "AE1_AD1", "AE1_listed"):
        assert tool.OVERLAP_NOTE[key] in summary, key
    head = (out / "AE1" / "trades.csv").read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith(
        "signal_date,exchange,symbol,quarter,ann_date,announcement_session,"
        "window_return,population_window,ear,t1_locked_down,entry_reason"
    )
    assert head.endswith(",reference,reference_excess")


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again") == 2
    assert any("AE1 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="AE1,AD1") == 2
    assert any("AD1 not registered" in line for line in refused(capsys))


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
    data["design"] = "1067"
    data["hypotheses"]["AE1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_392(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path)
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("AE1", "round22_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["AE1"] and validation["min_t"] == 3.392
    tables = read_json(tmp_path / "validation" / "AE1" / "tables.json")
    assert tables["reason"] is None, (tables["reason"], tables["prerequisites"])
    assert tables["min_t"] == 3.392
    assert tables["window"]["first_signal"] == trading_days()[199].isoformat()
    assert validation["read_until"] == trading_days()[259].isoformat()
    text = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.392（沒有 t 下限）" in text
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
        (tool.LOAD_FROM, days[259]),
        (tool.LOAD_FROM, days[299]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["AE1"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["AE1"]
    for file in ("summary.md", "tables.json", "trades.csv", "days.csv"):
        assert (tmp_path / "validation" / "AE1" / "used" / file).is_file(), file


def test_a_failed_validation_loads_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    real_load = tool.load
    loads = []
    monkeypatch.setattr(tool, "load", lambda *a: loads.append(a[2]) or real_load(*a))
    monkeypatch.setattr(ex, "explore_judge", lambda *a, **k: ex.FORWARD_WATCH)
    assert validate(db, tmp_path / "validation", passed_report(out, tmp_path)) == 0
    assert loads == [trading_days()[259]]
    assert "used" not in read_json(tmp_path / "validation" / "explore.json")


def test_too_few_trade_days_cannot_be_judged(copied, tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "MIN_DAYS", 10_000)
    out = tmp_path / "exploration"
    assert explore(copied, out) == 0
    row = read_json(out / "explore.json")["hypotheses"]["AE1"]
    assert (row["verdict"], row["reason"]) == (ex.UNDECIDED, "too_few_trade_days")


def test_coverage_only_computes_no_return(copied, tmp_path):
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity"):
        assert word not in text, word
    # EAR's sign is counted, its value not listed ("ear" is only a time's key)
    assert '"ear"' not in json.dumps(body["hypotheses"]["AE1"]["coverage"])
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    ae1 = body["hypotheses"]["AE1"]
    assert set(ae1["seconds"]) == {
        "plan", "ann_date", "session", "ear", "population_mean", "reference", "ad1_order",
    }  # fmt: skip
    coverage = ae1["coverage"]
    assert sorted(coverage["years"]) == ["2016"]
    row = coverage["years"]["2016"]
    assert row["with_ann"] == row["missing"] + row["not_positive"] + row["signals"]
    assert row["occupied"] == 0 and row["signals"] > 0
    assert 0 < row["signal_days"] <= row["signals"]
    assert row["missing"] >= 1  # S22's a-2
    assert 0 < row["delisted_missing"] <= row["delisted"]  # 25 and 27 out, 26 kept
    assert sum(q["with_ann"] for q in coverage["quarters"].values()) == row["with_ann"]
    quarters = coverage["quarters"]
    assert {"2015Q4", "2016Q1", "2016Q2"} <= set(quarters) <= {
        "2015Q1", "2015Q2", "2015Q3", "2015Q4", "2016Q1", "2016Q2",
    }  # fmt: skip
    for key in ("2015Q1", "2015Q2", "2015Q3"):  # a is the first session: T has no
        assert quarters.get(key, {}).get("with_ann", 0) == 0  # 20 bars yet
    estimate = coverage["estimate"]
    assert estimate["exploration"] == row["signal_days"] and estimate["min_days"] == 2
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "trade"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "依季（財報的季）" in md
    assert "有成交的訊號日的估計" in md
    assert tool.DEGENERATE["AE1"] in md


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "AE1"])  # fmt: skip


def test_the_validation_estimate_reads_no_validation_data():
    years = {"2013": {"signal_days": 50}, "2014": {"signal_days": 100},
             "2015": {"signal_days": 140}}  # fmt: skip
    got = tool.trade_days_estimate(years)
    length = ((date(2024, 9, 27) - date(2020, 1, 2)).days + 1) / 365.25
    assert (got["exploration"], got["full_years"], got["per_year"]) == (290, 2, 120)
    assert got["validation"] == pytest.approx(120 * length)


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
