"""tools/research/round24_research.py: the registered AG2 (#1116).

The registered numbers (N, start, thresholds) are asserted as written in
docs/spec/evidence.md 第二十四輪：AG2.  The feature and the account are
checked on hand-made rows (the expected numbers worked out in the test); the
gate ("each once") and the reports run on a synthetic copy on a compressed
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
from collections import Counter
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import Session

from app.models import Base, IngestionRun, Instrument, MarketBar, RawPayload

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/1116#issuecomment-1"


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
r23 = _tool("round23_research")
tool = _tool("round24_research")
NAMES = ("AG2",)


# --- the registration, as written -------------------------------------------------


def test_the_hypothesis_is_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == list(NAMES)
    for name in ("mainstream_research", *(f"round{n}_research" for n in range(4, 24))):
        other = sys.modules.get(name) or _tool(name)
        assert not set(h) & set(other.HYPOTHESES), name
    tr = sys.modules.get("trade_research") or _tool("trade_research")
    for other in (ex, tr):
        assert not set(h) & set(other.HYPOTHESES)
    ag2 = h["AG2"]
    assert ag2["engine"] == "events"
    assert ag2["keys"] == (("cash_to_assets", "high"),)
    assert (ag2["top"], ag2["hold"], ag2["start"], ag2["rule"]) == (
        20, "next_event", ("date", date(2013, 5, 15)), "quarterly",
    )  # fmt: skip
    assert ag2["short"] == "cash, not filled"


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (
        1,
        24,
        1,
        75,
    )
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.403
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(75), 3) == 3.403
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "14906ed9" and tool.DESIGN == "1116"
    assert "14906ed96b81cd87fbbb05baabefd010c2be2cc1".startswith(
        tool.REGISTRATION_COMMIT
    )
    assert (tool.CASH, tool.ASSETS, tool.ASSETS_MIN) == ("cash", "total_assets", 0.0)
    assert (tool.STATEMENT_TABLE, tool.STATEMENT_SOURCE) == (
        "quarterly_statements", "mops_tifrs_zip",
    )  # fmt: skip
    assert tool.FINANCIAL_CODES == ("basi", "fh", "ins", "bd")
    assert tool.DELISTED_STATUSES == ("delisted", "transferred")
    # imported, not rewritten
    assert tool.overlap_share is r10.overlap_share
    assert tool.overlap_summary is r10.overlap_summary
    assert tool._known is r23._known is r15._known
    assert tool.load_valuations is r23.load_valuations
    assert tool.delisted_by_year is r23.delisted_by_year
    assert issubclass(tool.CashStatement, r23.QuarterStatement)
    assert "load_context" in tool.load.__code__.co_names
    assert {"load_statuses", "quarter_events"} <= set(tool.load.__code__.co_names)
    assert "quarter_events" in tool.plan_events.__code__.co_names
    assert "quarter_events" in tool.segment_window.__code__.co_names
    assert "simulate_events" in tool.engines.__code__.co_names
    source = inspect.getsource(tool.af_names)
    assert "r23.pb(" in source and "r23.accruals_4q(" in source
    assert "r5.order_key(" in source and "r23.HYPOTHESES[name]" in source
    assert "r5.order_key(" in inspect.getsource(tool.plan_events)
    assert "r23.foreign_late(" in inspect.getsource(tool.foreign_late)


def _swap(key: str, value):
    return {"AG2": {**tool.HYPOTHESES["AG2"], key: value}}


def _other(module, name: str, key: str, value):
    return {**module.HYPOTHESES, name: {**module.HYPOTHESES[name], key: value}}


def test_the_definitions_hash_holds_every_value_the_verdicts_depend_on(monkeypatch):
    """#1116 範圍第 1 項: each value that changes a verdict changes the hash."""

    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.403
    for module, name, value in (
        (tool, "VALIDATION_MIN_T", 3.399),
        # AG2: the fields, the table and source, q's values only, the latest
        # quarter, the missing cases and their order (financial codes,
        # total_assets ≤ 0), high first, N 20, the start
        (tool, "CASH", "current_assets"),
        (tool, "ASSETS", "equity_total"),
        (tool, "STATEMENT_TABLE", "fundamental_snapshots"),
        (tool, "STATEMENT_SOURCE", "mops_t163sb04"),
        (tool, "INDUSTRY_KEY", "report_format"),
        (tool, "FINANCIAL_CODES", ("basi", "fh", "ins")),
        (tool, "LATEST_RULE", "the latest quarter with every field"),
        (tool, "CASH_TO_ASSETS", "cash(q) / mean(total_assets(q), total_assets(q-4))"),
        (tool, "ASSETS_MIN", -1.0),
        (tool, "CASH_MISSING", "reasons in order: financial, stale, fields, assets"),
        (tool, "FOREIGN_KEY", "deadline"),
        (tool, "FOREIGN_RULE", "foreign"),
        (tool, "HYPOTHESES", _swap("keys", (("cash_to_assets", "low"),))),
        (tool, "HYPOTHESES", _swap("top", 19)),
        (tool, "HYPOTHESES", _swap("start", ("date", date(2014, 5, 15)))),
        # the event days, held to the next one, T+1's open, the hash
        (tool, "ORDER", "small first"),
        (tool, "SHORT_RULE", "filled by the hash"),
        (tool, "SALE", "at T'+1's open"),
        (tool, "HYPOTHESES", _swap("hold", 60)),
        (r14, "DEADLINES", ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 15, 9, 0))),
        (r14, "EVENT_DAY_RULE", "the first session on or after the deadline"),
        (r14, "VERSION", 2),  # quarter_events' tool
        (r14, "LATEST_RULE", "another reading"),  # in round14's own hash
        (ex, "VERSION", 3),  # simulate_events' tool
        (r15, "VERSION", 2),  # _known's tool
        (r15, "EVENT_DAY_RULE", "another rule"),  # in round15's own hash
        # round23_research: the reading of the latest quarter, AF1's and
        # AF2's lists, its own definitions
        (r23, "VERSION", 2),
        (r23, "LATEST_RULE", "another reading"),
        (r23, "FINANCIAL_CODES", ("basi",)),
        (r23, "OPERATING", "gross_profit_ytd"),
        (r23, "CFO", "capex_ytd"),
        (r23, "HYPOTHESES", _other(r23, "AF1", "top", 19)),
        (r23, "HYPOTHESES", _other(r23, "AF2", "keys", (("accruals_4q", "high"),))),
        (r23, "PB_SOURCES", {"TWSE": "twse_bwibbu_d", "TPEx": "twse_bwibbu_d"}),
        (r23, "ACCRUALS", "another formula"),
        # the listed parts
        (tool, "DELISTED_STATUSES", ("delisted",)),
        (r10, "VERSION", 2),
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
        (tool, "CUMULATIVE", 76),
        (pr, "SLIPPAGE", 0.001),
        (pr, "FEE", 0.001),
        (pr, "TAX", 0.0015),
    ):  # fmt: skip
        with monkeypatch.context() as m:
            m.setattr(module, name, value)
            assert tool.definitions_sha256() != before, (module.__name__, name)
    assert tool.definitions_sha256() == before


def test_the_command_has_no_parameter_flags():
    flags = {
        option for action in tool._parser()._actions for option in action.option_strings
    }
    assert flags == {
        "-h", "--help", "--db", "--out", "--segment", "--min-free-gb", "--coverage-only",
        "--hypotheses", "--exploration-report", "--exploration-sha256", "--exploration-url",
    }  # fmt: skip


# AC-1: the values #1107 AC-1 listed (measured on master c4437d55), and
# round23_research's when PR #1112 was merged into master (6fc1bb19).
# forward_watch's F2 row reads round10_research's hash, its P2 row
# round15_research's and its A1 row round17_research's; AG2 reads
# explore_research (simulate_events), round14 (quarter_events), round15
# (_known), round23 (the reading, AF1, AF2) and round10.
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
    "round22_research": (1, "c678bfcb6acb7f1b72470ffeea3f14afe9b254359db508357346180d0fdfdb47"),
    "round23_research": (1, "0aa26f8290aded954b67122053228285d0b8cb9ea5ebb321211d44caadf835c2"),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


@pytest.mark.parametrize(
    "name",
    ["round10_research", "round14_research", "round15_research", "round17_research",
     "round22_research", None],
)  # fmt: skip
def test_the_tools_ag2_reads_are_the_ledgers(name):
    """AC-1: the hashes AG2 and forward_watch read are the ones in the public
    ledger (explore_research's entries have no ``tool``).  round23_research
    has no entry yet: its value is FROZEN's, PR #1112's."""

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


# AC-1: portfolio_research.ranking_key's source on master
RANKING_KEY_SHA256 = "65054614e007a2baa499baa6253d01e411b9b6f7b24d2acc0d50107d000291e0"


def test_the_ranking_key_is_unchanged():
    import ast

    path = ROOT / "tools" / "research" / "portfolio_research.py"
    source_text = path.read_text(encoding="utf-8")
    node = next(
        n
        for n in ast.parse(source_text).body
        if isinstance(n, ast.FunctionDef) and n.name == "ranking_key"
    )
    source = ast.get_source_segment(source_text, node)
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == RANKING_KEY_SHA256


def test_the_docs_tool_section_says_what_the_code_judges():
    """The degenerate cases, notes and limits in the tool section are the
    code's own strings, and coverage.md／summary.md print the same (PR #913
    review)."""

    doc = (ROOT / "docs" / "spec" / "evidence.md").read_text(encoding="utf-8")
    section = doc.split("**第二十四輪的假設**", 1)[1].split("#### 實作釋義", 1)[0]
    for name in NAMES:
        assert tool.DEGENERATE[name] in section, name
        assert tool.LIMITS[name] in section, name
        assert any(tool.DEGENERATE[name] in line for line in tool.COVERAGE_NOTES)
    for name, note in tool.OVERLAP_NOTE.items():
        assert note in section, name
    assert f"`VALIDATION_MIN_T`＝{tool.threshold(tool.VALIDATION_MIN_T)}" in section
    assert "t < 3.403 判「前瞻觀察」，沒有 t 下限" in section
    assert "tools/research/round24_research.py" in section
    assert "本輪 1 個、累計 75 個" in section


# --- hand-made rows ---------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def item_of(instrument_id: int = 1) -> lib.Series:
    return lib.Series(instrument_id)


def ctx_of(**parts) -> tool.Context:
    panel = lib.Panel([], {}, {}, {}, {})
    base = ex.Context(pr.Market(panel, {}, {}, None))
    return tool.Context(base, **parts)


DAY = date(2016, 5, 16)  # the 5/15 deadline (a Sunday)
Q1_16, Q4_15 = date(2016, 3, 31), date(2015, 12, 31)


def statement(
    end, announced=None, industry="ci", cash=100.0, assets=1000.0, foreign=False
):
    due = {3: (5, 15), 6: (8, 14), 9: (11, 14), 12: (3, 31)}[end.month]
    year = end.year + (1 if end.month == 12 else 0)
    return tool.CashStatement(
        announced or date(year, *due), end, industry, 1.0, 1.0, assets, foreign, cash
    )


def cash_of(rows, day=DAY, quarter=Q1_16):
    return tool.cash_to_assets(ctx_of(statements={1: rows}), item_of(), day, quarter)


def test_cash_to_assets_by_hand():
    """AG2 第 2、3 點: q's cash over q's total assets, nothing else read."""

    rows = [statement(Q4_15, cash=900.0, assets=1000.0), statement(Q1_16, cash=250.0)]
    got = cash_of(rows)
    assert (got.value, got.reason, got.cash, got.assets) == (0.25, None, 250.0, 1000.0)
    # cash 0 is 0, by value, not missing; a negative cash by value too
    assert cash_of([statement(Q1_16, cash=0.0)]) == tool.CashToAssets(
        0.0, None, 0.0, 1000.0
    )
    assert cash_of([statement(Q1_16, cash=-10.0)]).value == pytest.approx(-0.01)
    # a later announced row of the same quarter is read once it is known
    corrected = [statement(Q1_16, cash=250.0),
                 statement(Q1_16, date(2016, 5, 16), cash=500.0)]  # fmt: skip
    assert cash_of(corrected).value == 0.5
    later = [statement(Q1_16, cash=250.0),
             statement(Q1_16, date(2016, 5, 17), cash=500.0)]  # fmt: skip
    assert cash_of(later).value == 0.25  # announced after T: not read


def test_cash_to_assets_is_missing_in_the_registered_order():
    """AG2 第 4 點 (decision 7229042011 第 3 點): stale, financial, rows,
    fields, assets; only the first one counts; only rows announced ≤ T."""

    assert cash_of([]).reason == "stale"
    assert cash_of([statement(Q4_15)]).reason == "stale"  # Q1 not out yet
    late = [statement(Q4_15), statement(Q1_16, date(2016, 5, 17))]
    assert cash_of(late).reason == "stale"  # q announced after T: not used
    newer = [statement(Q1_16), statement(date(2016, 6, 30), date(2016, 5, 10))]
    assert cash_of(newer).reason == "stale"  # the latest is not the deadline's
    # the foreign issuers' Q2: announced 8/31, so stale on 8/14 (8/15 here)
    q2 = date(2016, 6, 30)
    rows = [statement(Q1_16), statement(q2, date(2016, 8, 31), foreign=True)]
    ctx = ctx_of(statements={1: rows})
    aug = date(2016, 8, 15)
    assert tool.cash_to_assets(ctx, item_of(), aug, q2).reason == "stale"
    assert tool.foreign_late(ctx, item_of(), aug, q2)
    assert not tool.foreign_late(ctx, item_of(), date(2016, 9, 1), q2)
    assert tool.cash_to_assets(ctx, item_of(), date(2016, 9, 1), q2).reason is None
    for code in ("basi", "fh", "ins", "bd"):
        assert cash_of([statement(Q1_16, industry=code)]).reason == "financial", code
    # only q's code: a financial Q4 before it does not count
    assert cash_of([statement(Q4_15, industry="fh"), statement(Q1_16)]).reason is None
    assert cash_of([statement(Q1_16, cash=None)]) == tool.CashToAssets(
        None, "fields", None, 1000.0
    )
    assert cash_of([statement(Q1_16, assets=None)]).reason == "fields"
    for assets in (0.0, -5.0):
        assert cash_of([statement(Q1_16, assets=assets)]).reason == "assets"
    # two reasons at once: only the first is counted
    assert cash_of([statement(Q4_15, industry="basi", cash=None)]).reason == "stale"
    assert cash_of([statement(Q1_16, industry="ins", cash=None)]).reason == "financial"
    assert cash_of([statement(Q1_16, cash=None, assets=0.0)]).reason == "fields"


def planning_ctx(sessions, statuses=None, statements=None):
    return SimpleNamespace(
        panel=SimpleNamespace(sessions=sessions, symbols={}),
        seconds=Counter(),
        statuses=statuses or {},
        statements=statements or {},
        valuations={},
    )


def test_ag2_ranks_high_first_missing_last_with_the_listed_counts(monkeypatch):
    """AG2 第 5、8 點: high first (0 by value), ties and the missing ones by
    the hash; each reason counted; AF1's and AF2's overlaps on the same T;
    the delisted members."""

    sessions = weekdays(date(2016, 1, 4), 250)
    items = {i: item_of(i) for i in range(1, 10)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    q1 = {1: statement(Q1_16, cash=300.0), 2: statement(Q1_16, cash=0.0),
          3: statement(Q1_16, cash=500.0), 4: statement(Q1_16, cash=150.0, assets=500.0),
          5: statement(Q1_16, industry="fh"), 6: statement(Q1_16, cash=None),
          7: statement(Q1_16, assets=None), 8: statement(Q1_16, assets=0.0)}  # fmt: skip
    statements = {i: [statement(Q4_15), *([q1[i]] if i in q1 else [])] for i in items}
    ctx = planning_ctx(sessions, {6: "delisted", 3: "transferred"}, statements)
    may, aug = date(2016, 5, 16), date(2016, 8, 15)
    calls = []

    def af(c, name, day, members, quarter):
        calls.append((name, day, quarter))
        if day != may:
            return set()
        return {3, 1} if name == "AF1" else {2}

    monkeypatch.setattr(tool, "af_names", af)
    s = [sessions.index(d) + 1 for d in (date(2016, 3, 31), may, aug)]
    last = sessions.index(date(2016, 8, 31))
    planned = tool.plan_events(ctx, "AG2", s[0], last)
    assert calls[2:4] == [("AF1", may, Q1_16), ("AF2", may, Q1_16)]
    ties = sorted((1, 4), key=lambda i: pr.tie_break(may, i))  # 0.3 and 0.3
    tail = sorted((5, 6, 7, 8, 9), key=lambda i: pr.tie_break(may, i))
    assert planned.picks[s[1]] == [3, *ties, 2, *tail]
    assert planned.dues == {s[0]: s[1] - 1, s[1]: s[2] - 1, s[2]: last + 1}
    event = planned.rebalances[1]
    counts = {k: event[k] for k in ("valued", "stale", "financial", "rows", "fields",
                                    "assets", "cash_null")}  # fmt: skip
    assert counts == {"valued": 4, "stale": 1, "financial": 1, "rows": 0, "fields": 2,
                      "assets": 1, "cash_null": 1}  # fmt: skip
    assert (event["names"], event["named_valued"]) == (9, 4)  # fewer than 20
    assert (event["delisted"], event["delisted_missing"]) == (2, 1)  # 6 missing
    assert event["overlap"] == {
        "AF1": pytest.approx(2 / 9),
        "AF2": pytest.approx(1 / 9),
    }
    assert planned.rebalances[0]["overlap"] == {"AF1": None, "AF2": None}  # no list
    assert planned.overlap == {"AG2_AF1": {"2016": [pytest.approx(2 / 9)]},
                               "AG2_AF2": {"2016": [pytest.approx(1 / 9)]}}  # fmt: skip
    rows = [r for r in planned.rows if r["signal_date"] == may.isoformat()]
    assert [r["cash_to_assets"] for r in rows][:4] == [0.5, 0.3, 0.3, 0.0]
    assert (rows[0]["quarter"], rows[0]["cash"], rows[0]["total_assets"]) == (
        "2016-03-31", 500.0, 1000.0,
    )  # fmt: skip
    # the Aug event: everyone stale (no Q2 row)
    assert planned.rebalances[2]["stale"] == 9
    by_year = tool.delisted_by_year(planned.coverage)["2016"]
    # 3/31: 9 has the Q4 row, every Q4 valued; 5/16: 5 missing; 8/15: 9 missing
    assert (by_year["events"], by_year["members"], by_year["missing"]) == (3, 27, 14)
    assert (by_year["delisted"], by_year["delisted_missing"]) == (6, 3)
    assert by_year["delisted_share"] == pytest.approx(3 / 6)
    assert by_year["others_share"] == pytest.approx(11 / 21)


def test_the_foreign_q2_is_counted_on_8_14(monkeypatch):
    sessions = weekdays(date(2016, 1, 4), 250)
    items = {i: item_of(i) for i in (1, 2)}
    monkeypatch.setattr(
        lib, "universe", lambda panel, day, lots: [(items[i], 0) for i in items]
    )
    q2 = date(2016, 6, 30)
    statements = {1: [statement(Q1_16), statement(q2, date(2016, 8, 31), foreign=True)],
                  2: [statement(Q1_16), statement(q2)]}  # fmt: skip
    monkeypatch.setattr(tool, "af_names", lambda *a: set())
    ctx = planning_ctx(sessions, {}, statements)
    aug = date(2016, 8, 15)
    s = sessions.index(aug) + 1
    planned = tool.plan_events(ctx, "AG2", s, sessions.index(date(2016, 9, 30)))
    event = planned.rebalances[0]
    assert (event["valued"], event["stale"], event["foreign_stale"]) == (1, 1, 1)
    assert planned.picks[s][0] == 2


def test_af1_and_af2_lists_are_round23s_own(monkeypatch):
    """實作釋義「重疊比例只列出」: ``round23_research``'s ``pb`` and
    ``accruals_4q`` small first, 20, on the same T; none before its first
    signal day."""

    sessions = weekdays(date(2013, 1, 1), 600)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions), seconds=Counter())
    members = [(item_of(i), 0) for i in range(1, 26)]
    monkeypatch.setattr(
        r23, "pb", lambda c, item, day: r23.Pb(float(item.instrument_id))
    )
    monkeypatch.setattr(
        r23,
        "accruals_4q",
        lambda c, item, day, q: r23.Accruals(
            None if item.instrument_id == 1 else -float(item.instrument_id)
        ),
    )
    may13, may14 = date(2013, 5, 15), date(2014, 5, 15)
    assert tool.af_names(ctx, "AF1", may13, members, date(2013, 3, 31)) == set(
        range(1, 21)
    )
    assert tool.af_names(ctx, "AF2", may13, members, date(2013, 3, 31)) == set()
    assert tool.af_names(ctx, "AF2", may14, members, date(2014, 3, 31)) == set(
        range(6, 26)
    )
    assert set(ctx.seconds) == {"af1_order", "af2_order"}


def quote_of(prices: dict[tuple[int, int], tuple[float, float]], locked=()):
    def quote(instrument_id, s):
        found = prices.get((instrument_id, s))
        if found is None:
            return None
        return pr.Quote(
            found[0], found[1], True, locked_up=(instrument_id, s) in locked
        )

    return quote


def test_the_event_account_by_hand():
    """共同「選股與調倉」: T+1's open, 1/20 of the cash each; sold at the next
    event day's close, the new list at its T+1 open; one not bought (limit up
    or no bar) is skipped, not replaced; fewer than 20 leave cash."""

    prices = {(i, s): (10.0, 10.0 + s) for i in (1, 2, 3, 4) for s in range(1, 8)}
    del prices[(4, 1)]  # no bar on T+1
    planned = SimpleNamespace(picks={1: [1, 2, 4], 4: [3]}, population={1: [1, 2], 4: [3]},
                              dues={1: 3, 4: 8})  # fmt: skip
    mine, population = tool.engines(
        SimpleNamespace(quote=quote_of(prices, locked={(2, 1)})), "AG2", planned, 1, 7
    )
    first, second = mine.positions
    assert (first.instrument_id, first.bought, first.sold, first.how) == (
        1,
        1,
        3,
        "close",
    )
    assert first.cost == pytest.approx(0.05)  # 19/20 stays cash
    assert mine.counts["limit_up"] == 1 and mine.counts["not_tradable"] == 1
    assert (second.instrument_id, second.bought) == (3, 4)
    assert second.cost == pytest.approx((1.0 - 0.05 + first.proceeds) / 20)
    assert mine.equity[0] == pytest.approx(0.95 + pr.buy_units(0.05, 10.0) * 11.0)
    assert population.positions[0].cost == pytest.approx(0.5)  # 1/2 of the cash
    assert population.counts["limit_up"] == 1


def test_invested_and_the_overview_row_by_hand(monkeypatch):
    sessions = weekdays(date(2016, 3, 28), 6)
    prices = {(1, s): (10.0, (11.0, 12.0, 12.0, 13.0)[s - 1]) for s in (1, 2, 3, 4)}
    prices.update({(2, s): (10.0, 10.0) for s in (1, 2, 3, 4)})
    events = [{"signal_date": sessions[0].isoformat(), "names": 1},
              {"signal_date": sessions[2].isoformat(), "names": 2}]  # fmt: skip
    plan = tool.Plan(picks={1: [1], 3: [1]}, population={1: [1, 2], 3: [1, 2]},
                     dues={1: 2, 3: 5}, rebalances=events,
                     overlap={"AG2_AF1": {"2016": [0.5]}, "AG2_AF2": {}})  # fmt: skip
    monkeypatch.setattr(tool, "segment_window", lambda *a: (1, 4))
    monkeypatch.setattr(tool, "_prerequisites", lambda *a: True)
    monkeypatch.setattr(tool, "plan_events", lambda *a, **k: plan)
    ctx = SimpleNamespace(panel=SimpleNamespace(sessions=sessions, index_close={}, symbols={}),
                          seconds=Counter(), quote=quote_of(prices))  # fmt: skip
    result = tool.run_portfolio(ctx, Path("unused"), "AG2", "exploration")
    units1 = pr.buy_units(0.05, 10.0)
    eq1 = 0.95 + units1 * 11.0
    assert result["rebalances"][0]["invested"] == pytest.approx(units1 * 11 / eq1)
    assert result["unsold_share"] == 0.5  # the second due after the segment
    row = tool._row(result)
    assert row["names"] == 1.5
    assert row["overlap_af1"] == {"days": 1, "mean": 0.5}
    assert row["overlap_af2"] == {"days": 0, "mean": None}


def test_the_start_and_the_first_events_are_the_registered_ones():
    sessions = weekdays(date(2012, 1, 2), 4000)  # to 2027
    spec = tool.HYPOTHESES["AG2"]
    first, last = tool.segment_window(sessions, "exploration", spec)
    assert sessions[first - 1] == date(2013, 5, 15) and sessions[last] == date(
        2019, 12, 31
    )
    first, _ = tool.segment_window(sessions, "validation", spec)
    assert sessions[first - 1] == date(2020, 3, 31)  # 2019's annual report
    first, _ = tool.segment_window(sessions, "used", spec)
    assert sessions[first - 1] == date(2024, 11, 14)


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
        (3.399, "前瞻觀察"),  # round 23's threshold is not this round's
        (3.402, "前瞻觀察"),
        (3.403, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_403(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 700
STOCKS = range(1, 25)
DELISTED = {25: 570, 26: 450}  # the last bar's index
TRANSFERRED = 27
INDEX_ID = 90
BANK = 9  # industry code basi
NULL_CASH = 13  # cash NULL
ZERO_ASSETS = 11  # total_assets 0
FOREIGN = 15  # Q2 announced on 8/31


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


ENDS = lambda y: [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]  # noqa: E731
DUES = lambda y: [date(y, 5, 15), date(y, 8, 14), date(y, 11, 14), date(y + 1, 3, 31)]  # noqa: E731


def statement_rows() -> list[dict]:
    """2014～2018: cash 100·i over 10,000 (the ratio rises with i); AF2's op
    YTD 100·q·i, cfo YTD 100·q·12."""

    rows = []
    for i in (*STOCKS, *DELISTED, TRANSFERRED):
        for year in range(2014, 2019):
            for q, (end, due) in enumerate(zip(ENDS(year), DUES(year)), 1):
                if i == FOREIGN and q == 2:
                    due = date(year, 8, 31)
                data = {"industry_code": "basi" if i == BANK else "ci"}
                if i == FOREIGN and q == 2:
                    data["deadline_rule"] = "foreign_issuer_q2_two_months"
                rows.append(
                    {"instrument_id": i, "period_end": end.isoformat(),
                     "fiscal_period": f"Q{q}", "announcement_date": due.isoformat(),
                     "total_assets": 0.0 if i == ZERO_ASSETS else 10_000.0,
                     "cash": None if i == NULL_CASH else 100.0 * i,
                     "cfo_ytd": 1200.0 * q, "operating_income_ytd": 100.0 * q * i,
                     "source": "mops_tifrs_zip", "raw_payload_id": 1,
                     "data_as_of": end.isoformat(), "collected_at": "2026-11-28 00:00:00",
                     "data_json": json.dumps(data)}
                )  # fmt: skip
    return rows


def build(path_: Path) -> Path:
    engine = create_engine(f"sqlite:///{path_}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ids = [*STOCKS, *DELISTED, TRANSFERRED]
    status = {**{i: "delisted" for i in DELISTED}, TRANSFERRED: "transferred"}
    events = {days[at] for at, _q in r14.quarter_events(days)}
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
        bars, valuations = [], []
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
                if day in events:
                    source = (
                        "twse_bwibbu_d"
                        if exchange_of(i) == "TWSE"
                        else "tpex_pe_qry_date"
                    )
                    valuations.append(
                        {"instrument_id": i, "trading_date": day.isoformat(),
                         "pb_ratio": round(0.5 + 0.1 * i, 2), "source": source,
                         "data_as_of": day.isoformat(), "raw_payload_id": 1,
                         "collected_at": "2026-11-28 00:00:00"}
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
        db.execute(
            text(
                "insert into valuation_daily (instrument_id, trading_date, pb_ratio, "
                "source, data_as_of, raw_payload_id, collected_at) values (:instrument_id, "
                ":trading_date, :pb_ratio, :source, :data_as_of, :raw_payload_id, "
                ":collected_at)"
            ),
            valuations,
        )
        db.execute(
            text(
                "insert into quarterly_statements (instrument_id, period_end, fiscal_period, "
                "announcement_date, total_assets, cash, cfo_ytd, operating_income_ytd, "
                "source, raw_payload_id, data_as_of, collected_at, data_json) values "
                "(:instrument_id, :period_end, :fiscal_period, :announcement_date, "
                ":total_assets, :cash, :cfo_ytd, :operating_income_ytd, :source, "
                ":raw_payload_id, :data_as_of, :collected_at, :data_json)"
            ),
            statement_rows(),
        )
        db.commit()
    engine.dispose()
    return path_


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round24") / "stock.db")


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


def test_one_panel_serves_ag2_af1_and_af2(loaded):
    days = trading_days()
    end = days[499]
    assert set(loaded.load_seconds) == {"panel", "valuations", "statements"}
    assert loaded.tables == {"valuation_daily": True, "quarterly_statements": True}
    assert all(r.announced <= end for rows in loaded.statements.values() for r in rows)
    first = loaded.statements[5][0]
    assert (first.cash, first.assets, first.operating, first.cfo) == (
        500.0, 10_000.0, 500.0, 1200.0,
    )  # fmt: skip
    assert loaded.statements[NULL_CASH][0].cash is None
    assert loaded.statements[BANK][0].industry == "basi"
    assert any(r.foreign for r in loaded.statements[FOREIGN])
    assert loaded.valuations[3][date(2017, 5, 15)] == pytest.approx(0.8)
    assert loaded.statuses[25] == "delisted"
    assert loaded.statuses[TRANSFERRED] == "transferred"


def test_the_features_and_the_lists_on_the_copy(loaded):
    series = loaded.panel.series
    may, q1 = date(2017, 5, 15), date(2017, 3, 31)
    assert tool.cash_to_assets(loaded, series[5], may, q1).value == pytest.approx(0.05)
    assert tool.cash_to_assets(loaded, series[BANK], may, q1).reason == "financial"
    assert tool.cash_to_assets(loaded, series[NULL_CASH], may, q1).reason == "fields"
    assert tool.cash_to_assets(loaded, series[ZERO_ASSETS], may, q1).reason == "assets"
    aug, q2 = date(2017, 8, 14), date(2017, 6, 30)
    assert tool.cash_to_assets(loaded, series[FOREIGN], aug, q2).reason == "stale"
    # AF1's and AF2's lists are round23_research.plan_events's own picks
    sessions = loaded.panel.sessions
    at = sessions.index(may)
    members = lib.universe(loaded.panel, may, tool.MIN_LOTS)
    for name in ("AF1", "AF2"):
        mine = tool.af_names(loaded, name, may, members, q1)
        theirs = r23.plan_events(
            SimpleNamespace(
                panel=loaded.panel, seconds=Counter(), statuses=loaded.statuses,
                valuations=loaded.valuations, statements=loaded.statements,
                formats={}, ab1=SimpleNamespace(statements={}),
                base=loaded.base, market=loaded.market,
            ),
            name, at + 1, at + 1,
        ).picks[at + 1]  # fmt: skip
        assert mine == set(theirs) and len(mine) == 20, name


def compressed(monkeypatch, tmp_path: Path) -> None:
    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[479]),
            "validation": (days[480], days[580]),  # the 2017-11-14 .. 2018-03-31 events
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


def explore(db: Path, out: Path, *extra: str, hypotheses: str | None = "AG2") -> int:
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
    data["hypotheses"]["AG2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return report


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    days = trading_days()
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round24_research", "1116", "exploration",
    )  # fmt: skip
    assert (report["round"], report["round_size"], report["cumulative"]) == (24, 1, 75)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.403)
    assert report["read_until"] == days[479].isoformat()
    row = report["hypotheses"]["AG2"]
    assert row["engine"] == "events" and row["names"] == 20
    assert row["overlap_af1"]["days"] > 0 and row["overlap_af2"]["days"] > 0
    text_ = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 1 個、累計 75 個" in text_ and "驗證段 t ≥ 3.403" in text_
    for key in ("summary_only", "AG2_survivor"):
        assert tool.OVERLAP_NOTE[key] in text_, key
    assert tool.LIMITS["AG2"] in text_
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [("AG2", "round24_research", 24, "exploration", 1)]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (out / "AG2" / file).is_file(), file
    summary = (out / "AG2" / "summary.md").read_text(encoding="utf-8")
    lines = summary.splitlines()
    assert lines[2] == "- " + tool.OVERLAP_NOTE["summary_only"]  # the report's start
    assert lines[3] == tool.OVERLAP_NOTE["AG2_survivor"]
    assert tool.DEGENERATE["AG2"] in summary and tool.LIMITS["AG2"] in summary
    for key in ("AG2_AF1", "AG2_AF2", "delisted", "listed"):
        assert tool.OVERLAP_NOTE[key] in summary, key
    assert "## 依年的下市、轉板股" in summary
    picks = (out / "AG2" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert picks[0] == (
        "signal_date,rank,exchange,symbol,quarter,cash_to_assets,cash,total_assets,tie"
    )
    on = [line.split(",")[3] for line in picks[1:] if line.startswith("2017-05-15")]
    assert on[:3] == ["S27", "S26", "S25"]  # the ratio rises with i
    assert len(on) == 20  # 24 valued of 27: the missing ones are not reached
    assert not {f"S{i}" for i in (BANK, NULL_CASH, ZERO_ASSETS)} & set(on)


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again") == 2
    assert any("AG2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_unregistered_or_other_codes_are_refused(copied, tmp_path, capsys):
    capsys.readouterr()
    assert explore(copied, tmp_path / "x", hypotheses="AG2,AF2") == 2
    assert any("AF2 not registered" in line for line in refused(capsys))


def test_the_exploration_needs_the_tables(copied, tmp_path, capsys):
    con = sqlite3.connect(copied)
    con.execute("drop table quarterly_statements")
    con.commit()
    con.close()
    capsys.readouterr()
    assert explore(copied, tmp_path / "x") == 2
    assert any("no quarterly_statements table" in line for line in refused(capsys))
    assert not (tmp_path / "x").exists()
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)


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
    data["design"] = "1107"
    data["hypotheses"]["AG2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_403(explored, tmp_path, capsys):
    db, out = explored
    report = passed_report(out, tmp_path)
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("AG2", "round24_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["AG2"]
    assert validation["min_t"] == 3.403
    tables = read_json(tmp_path / "validation" / "AG2" / "tables.json")
    assert tables["reason"] is None, (tables["reason"], tables["prerequisites"])
    assert tables["min_t"] == 3.403
    assert tables["window"]["first_signal"] == "2017-11-14"
    assert validation["read_until"] == trading_days()[580].isoformat()
    text_ = (tmp_path / "validation" / "explore.md").read_text(encoding="utf-8")
    assert "t < 3.403（沒有 t 下限）" in text_
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
    report = passed_report(out, tmp_path)
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (tool.LOAD_FROM, days[580]),
        (tool.LOAD_FROM, days[699]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["AG2"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["AG2"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "AG2" / "used" / file).is_file(), file


def test_a_validation_not_passed_loads_no_used_segment(explored, tmp_path, monkeypatch):
    db, out = explored
    real_load = tool.load
    ends = []

    def spy(db, start, end, raw_dir):
        ends.append(end)
        return real_load(db, start, end, raw_dir)

    monkeypatch.setattr(ex, "explore_judge", lambda stage, *a, **k: ex.FORWARD_WATCH)
    monkeypatch.setattr(tool, "load", spy)
    assert validate(db, tmp_path / "validation", passed_report(out, tmp_path)) == 0
    assert ends == [trading_days()[580]]
    assert "used" not in read_json(tmp_path / "validation" / "explore.json")


def test_coverage_only_computes_no_return(copied, tmp_path):
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    dumped = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity", "overlap", '"invested"'):
        assert word not in dumped, word
    assert not ex.read_ledger(copied.parent / ex.LEDGER_NAME)
    assert body["tables"] == {"valuation_daily": True, "quarterly_statements": True}
    row = body["hypotheses"]["AG2"]
    events = [e for year in row["coverage"].values() for e in year["events"]]
    may = next(e for e in events if e["signal_date"] == "2017-05-15")
    assert (may["stale"], may["financial"], may["rows"], may["fields"], may["assets"]) == (
        0, 1, 0, 1, 1,
    )  # fmt: skip
    assert may["cash_null"] == 1 and may["valued"] == may["members"] - 3
    assert (may["delisted"], may["delisted_missing"]) == (3, 0)
    aug = next(e for e in events if e["signal_date"] == "2017-08-14")
    assert (aug["stale"], aug["foreign_stale"]) == (1, 1)
    assert set(row["delisted"]) == {"2016", "2017"}
    assert set(row["seconds"]) == {"plan", "cash_to_assets", "foreign", "af1_order",
                                   "af2_order"}  # fmt: skip
    assert body["elapsed_seconds"] >= body["load_seconds"] > 0
    assert set(body["load_seconds_parts"]) == {"panel", "valuations", "statements"}
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "## 耗時" in md and "峰值記憶體" in md and "外國發行人 Q2（8/14）" in md
    assert "（其中 `cash` 是 NULL）" in md and "q 沒有列" in md
    assert "依年的下市、轉板股" in md and "其他檔次的缺值比例" in md
    assert tool.DEGENERATE["AG2"] in md


def test_coverage_only_lists_a_missing_table(copied, tmp_path):
    con = sqlite3.connect(copied)
    con.execute("drop table quarterly_statements")
    con.commit()
    con.close()
    out = tmp_path / "coverage"
    assert explore(copied, out, "--coverage-only", hypotheses=None) == 0
    body = read_json(out / "coverage.json")
    assert body["tables"] == {"valuation_daily": True, "quarterly_statements": False}
    events = [e for row in body["hypotheses"]["AG2"]["coverage"].values()
              for e in row["events"]]  # fmt: skip
    assert all(e["valued"] == 0 and e["stale"] == e["members"] for e in events)
    assert "`quarterly_statements` 沒有（全部缺值）" in (out / "coverage.md").read_text(
        encoding="utf-8"
    )


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
                   "exploration", "--coverage-only", "--hypotheses", "AG2"])  # fmt: skip


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
        str(db.parent / ex.LEDGER_NAME) in line
        and "not writable" in line
        and ":ro" in line
        and "第 2 步的工具" in line
        for line in problems
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
