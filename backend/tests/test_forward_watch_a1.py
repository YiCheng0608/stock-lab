"""tools/research/forward_watch.py: round 17's A1 (#1013), the sixth object.

A1's definition is round17_research 第 1 版's (#1011 ran its exploration and
validation, ``definitions_sha256`` 505666ec…4c95df); the entry adds only the
start (2026-11-24, the Taipei day of the validation's ``finished_at``), the 60
sessions before a verdict and the kind 前瞻觀察.  It trades on P2's event days
(``round14_research.quarter_events``) on X7's account, so the run uses its own
synthetic copy spanning the frozen start, with A1's two statement fields, a
transferred stock out of the reference and X8's announcements; its five
output files are locked by ``A1_DIGESTS``.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import Base, Event, FundamentalSnapshot, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = sys.modules.get("evidence_lib") or _tool("evidence_lib")
er = sys.modules.get("explore_research") or _tool("explore_research")
r14 = sys.modules.get("round14_research") or _tool("round14_research")
r17 = sys.modules.get("round17_research") or _tool("round17_research")
tool = _tool("forward_watch")

A1_SHA256 = "505666ec2537fdb6b77086ce6b633bd6b58b4a61de8b7aa5f6213ef18d4c95df"
A1_SINCE = date(2026, 11, 24)
# 2026Q3's deadline 2026-11-14 is a Saturday: its event day 2026-11-16 is
# before the start; 2026Q4's deadline 2027-03-31 is the first forward one.
A1_BEFORE = date(2026, 11, 16)
A1_FIRST = date(2027, 3, 31)
REGISTERED = (
    "https://github.com/YiCheng0608/stock-lab/issues/1011#issuecomment-7113410582"
)
# The tools' versions and definition hashes the six entries rest on (AC-1, AC-3)
SOURCE_HASHES = {
    "explore_research": (
        2,
        "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63",
    ),
    "round10_research": (
        1,
        "453f65124f86b5643ef1ce79dd079530a603e9434ed719a5f942090eeaf85dd9",
    ),
    "round14_research": (
        1,
        "3c8cf489dd99778e71d29215b1bd7e8b8d63607c902500c9e9ac122bbe0a0044",
    ),
    "round15_research": (
        1,
        "dbbeb3e2626bbd4642c7b8732da3f376c9905e50575bee8f2dbed60273ea824e",
    ),
    "round17_research": (1, A1_SHA256),
}


# --- the frozen entry -------------------------------------------------------------


def test_a1_is_round17s_a1_frozen_as_forward_watch():
    assert list(tool.WATCHES) == [
        "X4",
        "H2",
        "H2-product",
        "F2",
        "P2",
        "A1",
        "X4-product",
    ]
    entry = tool.WATCHES["A1"]
    assert entry == {
        "kind": "前瞻觀察",
        "source": "round17_research",
        "source_version": 1,
        "code": "A1",
        "definitions_sha256": A1_SHA256,
        "since": A1_SINCE,
        "min_days": 60,
        "registered": REGISTERED,
    }
    # the definition #1011's exploration and validation ran: imported, not copied
    assert tool.SOURCES["round17_research"] is r17
    assert tool.definition("A1") is r17.HYPOTHESES["A1"]
    assert tool.source_problems("A1") == []
    assert tool.ENGINES["round17_research"] is tool.round17_events
    assert tool.COVERAGE_LINES["round17_research"] is r17.coverage_lines
    assert tool.PICK_FIELDS["round17_research"]("A1", {}) == r17.PICK_FIELDS["A1"]
    assert tool.EVENT_OVERLAPS["A1"] == ("A1_X8",)
    assert tool.definition("A1") == {
        "engine": "events",
        "direction": "基本面：淨增發",
        "label": "每季法定期限的事件日，`net_issue`（季報推算的累計加權平均股數，本季對去年同季的對數變化，"
        "扣掉期間的配股）小者先取 20 檔",
        "rule": "quarterly",
        "keys": (("net_issue", "low"),),
        "short": "cash, not filled",
        "top": 20,
        "hold": "next_event",
        "start": ("date", date(2014, 5, 15)),
    }
    assert tool.display("A1") == "A1" and tool.KIND_NOTES[entry["kind"]]


def test_the_start_is_the_taipei_day_the_validation_was_written():
    """``since`` is the day of the ledger's A1 validation ``finished_at`` on
    the sessions' calendar (Asia/Taipei): 2026-11-23T20:39:54Z is 11-24."""

    ledger = json.loads(
        (ROOT / "tools" / "research" / "explore_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    rows = ledger if isinstance(ledger, list) else ledger["entries"]
    [row] = [
        r for r in rows if r["hypothesis"] == "A1" and r["segment"] == "validation"
    ]
    assert row["verdict"] == "前瞻觀察"
    finished = datetime.fromisoformat(row["finished_at"])
    assert finished.astimezone(ZoneInfo("Asia/Taipei")).date() == A1_SINCE
    # the earlier rows' days are the same on that calendar
    for name, code in (("X4", "X4"), ("H2", "X2"), ("F2", "F2"), ("P2", "P2")):
        [row] = [
            r for r in rows if r["hypothesis"] == code and r["segment"] == "validation"
        ]
        day = datetime.fromisoformat(row["finished_at"]).astimezone(
            ZoneInfo("Asia/Taipei")
        )
        assert day.date() == tool.WATCHES[name]["since"], name


@pytest.mark.parametrize("name", sorted(SOURCE_HASHES))
def test_the_source_tools_versions_and_hashes_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == SOURCE_HASHES[name]


def test_the_other_entries_are_unchanged():
    for name in ("X4", "H2", "H2-product", "F2", "P2"):
        assert tool.source_problems(name) == [], name
    assert tool.ENGINES["round15_research"] is tool.round15_events
    assert tool.EVENT_OVERLAPS["P2"] == ("P2_K2", "P2_X4")


def test_the_command_takes_a1_and_no_parameter(tmp_path):
    choices = next(a for a in tool._parser()._actions if "--watch" in a.option_strings)
    assert "A1" in choices.choices
    base = ["--db", "x", "--out", str(tmp_path), "--watch", "A1"]
    for extra in (["--since", "2026-11-14"], ["--top", "5"], ["--keys", "x"]):
        with pytest.raises(SystemExit) as stopped:
            tool.main([*base, *extra])
        assert stopped.value.code == 2


# --- the synthetic copy -----------------------------------------------------------

# 2025-01-02 .. 2027-09-30, statements 2023～2027Q2.
STOCKS = range(1, 31)
BANK = 25  # report_format bank: never a net_issue
TRANSFERRED = 31  # EPS only, transferred: out of the reference
DELISTED = 32  # every field, delisted, its last bar 2026-06-30
IDS = (*STOCKS, TRANSFERRED, DELISTED)
INDEX_ID = 90
END = date(2027, 9, 30)
BUYBACK = (3, A1_FIRST)  # X8 on A1's first forward event day


def days_of() -> list[date]:
    out, day = [], date(2025, 1, 2)
    while day <= END:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def shares_of(i: int, year: int) -> float:
    """i < 15 buys back (shares fall each year), i > 15 issues."""

    return 1_000_000.0 * (1 + (i - 15) * 0.01) ** (year - 2020)


def statements() -> list[dict]:
    rows = []
    deadlines = ((5, 15), (8, 14), (11, 14), (3, 31))
    for i in IDS:
        for year in range(2023, 2028):
            for q in range(4):
                if (year, q) > (2027, 1):  # 2027Q2 is the last announced
                    break
                end = date(year, 3 * (q + 1), 31 if q in (0, 3) else 30)
                month, day = deadlines[q]
                due = date(year + (1 if q == 3 else 0), month, day)
                eps = (1.0 + 0.05 * i) * (q + 1)
                net = eps * shares_of(i, year) / 1000
                data: dict = {}
                if i != TRANSFERRED:
                    data = {
                        "report_format": "bank" if i == BANK else "general",
                        r17.NET: f"{net:,.3f}",
                        r17.EPS: f"{eps:.2f}",
                    }
                rows.append(
                    {
                        "instrument_id": i,
                        "period_end": end,
                        "fiscal_period": f"Q{q + 1}",
                        "announcement_date": due,
                        "eps": eps,
                        "data_json": data,
                        "source": "test",
                    }
                )
    return rows


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = days_of()
    status = {TRANSFERRED: "transferred", DELISTED: "delisted"}
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": status.get(i, "active"),
                }
                for i in IDS
            ]
            + [
                {
                    "id": INDEX_ID,
                    "exchange": "TWSE",
                    "symbol": "TAIEX",
                    "name": "加權指數",
                    "instrument_type": "index",
                    "status": "active",
                }
            ],
        )
        bars = []
        for i in IDS:
            level = 50.0 + i
            for t, day in enumerate(days):
                if i == DELISTED and day > date(2026, 6, 30):
                    break
                previous = level
                level *= 1.0 + (15 - i) * 0.0001 + 0.02 * noise(i, t, "a1")
                close = round(level, 4)
                open_ = round(previous * (1 + 0.004 * noise(i, t, "a1o")), 4)
                volume = 2_000_000 + 10_000 * i
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": open_,
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": volume,
                        "turnover": close * volume,
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": False,
                    }
                )
        for t, day in enumerate(days):
            level = 22000.0 + 4 * t + 30 * noise(INDEX_ID, t, "a1")
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": level,
                    "high": level,
                    "low": level,
                    "close": level,
                    "adj_close": level,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(FundamentalSnapshot), statements())
        db.execute(
            insert(Event),
            [
                {
                    "instrument_id": BUYBACK[0],
                    "event_date": BUYBACK[1],
                    "event_type": "material_information",
                    "title": "本公司董事會決議買回庫藏股",
                    "source": "mops_material_information",
                }
            ],
        )
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def a1_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("a1") / "stock.db")


def no_window(monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


# research_report.load_actions points these at the copy for app.config; the
# command is one process per run, so each call here puts them back after it.
APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def in_one_process(run):
    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def watch(db: Path, out: Path, *extra: str) -> int:
    return in_one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--watch",
                "A1",
                "--out",
                str(out),
                "--min-free-gb",
                "0",
                *extra,
            ]
        )  # fmt: skip
    )


def edited(db: Path, tmp_path: Path, name: str, *statements_: tuple) -> Path:
    path = tmp_path / name / "stock.db"
    path.parent.mkdir()
    shutil.copy(db, path)
    con = sqlite3.connect(path)
    try:
        for statement in statements_:
            con.execute(*statement)
        con.commit()
    finally:
        con.close()
    return path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


VOLATILE_LINES = ("- 副本：", "- 耗時 ", "- 重現：")


def normalized(out: Path, copy: bool = True) -> dict[str, str]:
    """The five files without what changes from run to run (``copy`` False:
    also without the copy's facts, for two copies of different lengths)."""

    tables = read_json(out / "tables.json")
    for key in tool.VOLATILE_KEYS:
        tables.pop(key)
    tables["copy"].pop("mtime")
    if not copy:
        tables.pop("copy")
    summary = [
        line
        for line in (out / "summary.md").read_text(encoding="utf-8").splitlines()
        if not line.startswith(VOLATILE_LINES)
    ]
    texts = {
        "tables.json": json.dumps(tables, ensure_ascii=False, indent=2, default=str),
        "summary.md": "\n".join(summary),
    }
    for name in ("equity.csv", "picks.csv", "trades.csv"):
        texts[name] = (out / name).read_text(encoding="utf-8")
    return texts


def digests(out: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in normalized(out).items()
    }


# A1's forward outputs on ``a1_db`` (written by the commit that added the
# entry, #1013): a change of the definition, the engine or the report fails here.
A1_DIGESTS = {
    "summary.md": "b36aee88482e453a7529cbc2c8f0004b40779962fd249f02800924dd04420cd8",
    "tables.json": "d6df0dcf3e489f3eda2da9c981757f425e9ddbc2882003b7ac950a6ace7fb120",
    "equity.csv": "39d84c2dce620095224b01830c67754459f1cd7de58c34489010e06feb88931c",
    "picks.csv": "682811f9e366786ecb9b1c3c508a90aea3ce7e02c8fe98a1e7d00518183ae166",
    "trades.csv": "16f8f7a09c985498dc579583376643a3d67c04f2079eae1903bad879df4f831c",
}


@pytest.fixture(scope="module")
def a1_run(a1_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("a1_frozen") / "out"
    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        assert watch(a1_db, out) == 0
    finally:
        patch.undo()
    return out


def test_a1_output_is_frozen(a1_run):
    assert digests(a1_run) == A1_DIGESTS


SIGNALS = ["2027-03-31", "2027-05-17", "2027-08-16"]  # 5/15, 8/14 Saturdays


def test_a1_buys_only_event_days_from_the_start(a1_run):
    days = days_of()
    tables = read_json(a1_run / "tables.json")
    assert (tables["since"], tables["first_signal"]) == (
        A1_SINCE.isoformat(),
        A1_FIRST.isoformat(),
    )
    assert tables["signal_days"] == 3
    assert [e["signal_date"] for e in tables["rebalances"]] == SIGNALS
    assert [e["quarter"] for e in tables["rebalances"]] == [
        "2026-12-31",
        "2027-03-31",
        "2027-06-30",
    ]
    picks = read_csv(a1_run / "picks.csv")
    assert sorted({row["signal_date"] for row in picks}) == SIGNALS
    # net_issue small first: the buybacks (S1..S14) lead, 20 a day; the bank
    # and the EPS-only one never have a value, the delisted one has no bar
    for day in SIGNALS:
        listed = [r for r in picks if r["signal_date"] == day]
        assert [r["symbol"] for r in listed] == [f"S{i}" for i in range(1, 21)]
        assert all(r["quarter"] for r in listed)
    first = [r for r in picks if r["signal_date"] == SIGNALS[0]][0]
    assert math.isclose(float(first["net_issue"]), math.log(0.86), abs_tol=1e-4)
    assert [e["valued"] for e in tables["rebalances"]] == [29, 29, 29]
    equity = read_csv(a1_run / "equity.csv")
    assert equity[0]["date"] == days[days.index(A1_FIRST) + 1].isoformat()
    assert equity[-1]["date"] == END.isoformat()
    trades = read_csv(a1_run / "trades.csv")
    assert min(row["bought"] for row in trades) == equity[0]["date"]
    assert tables["days"] == len(equity) >= 60 and tables["verdict"] != "樣本不足"
    # the reference (A1 第 8 點): listed, not judged
    assert tables["excess"]["reference"]["days"] == tables["days"]
    # X8 (A1 第 7 點): listed only, S3 on the first event day
    assert tables["rebalances"][0]["x8_overlap"] == pytest.approx(1 / 20)
    assert tables["overlaps"]["A1_X8"]["days"] == 1
    summary = (a1_run / "summary.md").read_text(encoding="utf-8")
    assert summary.splitlines()[0].startswith("# A1 前瞻觀察的前瞻紀錄")
    assert "| 超額（對對照基準，只列出） |" in summary
    assert r17.OVERLAP_NOTE["A1_reference"] in summary
    assert r17.OVERLAP_NOTE["A1_X8"] in summary and "P2" not in summary
    assert "round17_research 第 1 版的 A1" in summary
    assert "下一個法定期限 2027-11-14" in summary
    assert tables["next_deadline"] == "2027-11-14"


def test_a1_an_event_day_before_the_start_is_not_bought(a1_db, a1_run, tmp_path):
    """The same copy from a start before 2026-11-16 buys that event day's
    list; the frozen start does not, nor puts it in front."""

    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        earlier = in_one_process(
            lambda: tool.run_watch(
                a1_db, "A1", tmp_path / "earlier", since=date(2026, 11, 10)
            )
        )
    finally:
        patch.undo()
    assert earlier["days"] > read_json(a1_run / "tables.json")["days"]
    tables = read_json(tmp_path / "earlier" / "tables.json")
    assert tables["first_signal"] == A1_BEFORE.isoformat()
    before = read_csv(tmp_path / "earlier" / "picks.csv")
    assert {r["signal_date"] for r in before} >= {A1_BEFORE.isoformat()}
    frozen = read_csv(a1_run / "picks.csv")
    assert min(r["signal_date"] for r in frozen) == A1_FIRST.isoformat()
    assert min(r["bought"] for r in read_csv(a1_run / "trades.csv")) > (
        A1_FIRST.isoformat()
    )


def test_a1_more_days_at_the_end_change_no_earlier_number(a1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    cut = date(2027, 6, 30)
    short = edited(
        a1_db,
        tmp_path,
        "short",
        ("delete from market_bars where trading_date > ?", (cut.isoformat(),)),
        (
            "delete from fundamental_snapshots where announcement_date > ?",
            (cut.isoformat(),),
        ),
        ("delete from events where event_date > ?", (cut.isoformat(),)),
    )
    first, again, longer = tmp_path / "first", tmp_path / "again", tmp_path / "longer"
    assert watch(short, first) == 0
    assert watch(a1_db, again, "--cutoff", cut.isoformat()) == 0
    assert watch(a1_db, longer) == 0
    assert normalized(again, copy=False) == normalized(first, copy=False)
    base = read_json(first / "tables.json")
    assert base["signal_days"] == 2 and base["next_deadline"] == "2027-08-14"
    for name in ("equity.csv", "picks.csv"):
        rows, more = read_csv(first / name), read_csv(longer / name)
        assert len(more) > len(rows) and more[: len(rows)] == rows


@pytest.mark.parametrize("cut", [date(2026, 11, 24), date(2027, 3, 30), A1_FIRST])
def test_a1_without_an_event_day_after_the_start(a1_db, tmp_path, monkeypatch, cut):
    """樣本不足 and the next event day; a cutoff on the event day is no signal
    yet (its T+1 is not in the copy)."""

    no_window(monkeypatch)
    out = tmp_path / "out"
    assert watch(a1_db, out, "--cutoff", cut.isoformat()) == 0
    tables = read_json(out / "tables.json")
    assert (tables["days"], tables["signal_days"], tables["verdict"]) == (
        0,
        0,
        "樣本不足",
    )
    assert tables["first_signal"] is None and tables["next_deadline"] == "2027-03-31"
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（起日後還沒有事件日）" in summary
    assert "下一個事件日 2027-03-31" in summary
    assert read_csv(out / "picks.csv") == [] and read_csv(out / "trades.csv") == []


def test_a1_short_of_60_days_lists_numbers_and_no_verdict(a1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    days = days_of()
    cut = days[days.index(A1_FIRST) + 30]
    out = tmp_path / "out"
    assert watch(a1_db, out, "--cutoff", cut.isoformat()) == 0
    tables = read_json(out / "tables.json")
    assert (tables["days"], tables["signal_days"], tables["verdict"]) == (
        30,
        1,
        "樣本不足",
    )
    assert tables["excess"]["population"]["mean"] is not None
    assert tables["excess"]["reference"]["mean"] is not None
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 30／60 日）" in summary and "數字不是判定" in summary
    assert "起日後還沒有事件日" not in summary


def test_a1_a_changed_source_is_refused(a1_db, tmp_path, monkeypatch, capsys):
    no_window(monkeypatch)
    changed = {**r17.HYPOTHESES, "A1": {**r17.HYPOTHESES["A1"], "top": 10}}
    monkeypatch.setattr(r17, "HYPOTHESES", changed)
    out = tmp_path / "out"
    assert watch(a1_db, out) == 2
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]
    assert any("definitions_sha256" in problem for problem in refused)
    assert not out.exists()


def test_a1_runs_round17s_own_load_plan_and_engine(a1_db, a1_run, tmp_path):
    """The frozen run's equity, picks and reference are round17_research's
    own (``load`` from ``LOAD_FROM``, ``plan_a1``, ``engines``) on that
    segment."""

    days = days_of()
    ctx = in_one_process(lambda: r17.load(a1_db, r17.LOAD_FROM, END, tmp_path / "raw"))
    assert ctx.panel.sessions == days
    spec = r17.HYPOTHESES["A1"]
    first, last = days.index(A1_FIRST) + 1, len(days) - 1
    planned = r17.plan_a1(ctx, spec, first, last)
    assert planned.reference != planned.population  # S31 is out of it
    mine, population, reference = r17.engines(ctx, "A1", planned, first, last)
    equity = read_csv(a1_run / "equity.csv")
    assert [row["date"] for row in equity] == [
        d.isoformat() for d in days[first : last + 1]
    ]
    assert [row["A1"] for row in equity] == [f"{v:.8f}" for v in mine.equity]
    assert [row["population"] for row in equity] == [
        f"{v:.8f}" for v in population.equity
    ]
    picks = read_csv(a1_run / "picks.csv")
    assert [(r["signal_date"], r["symbol"]) for r in picks] == [
        (r["signal_date"], r["symbol"]) for r in planned.rows
    ]
    tables = read_json(a1_run / "tables.json")
    excess = tool.pr.excess_metrics(
        [
            a - b
            for a, b in zip(
                tool.pr.daily_returns(mine.equity),
                tool.pr.daily_returns(reference.equity),
            )
        ]
    )
    assert tables["excess"]["reference"] == json.loads(json.dumps(excess))
