"""tools/research/forward_watch.py: the frozen forward entry of round 10's F2
(#949; 前瞻觀察 on its validation, #944 7072993427, 決定 7073015041).

F2's definition is round10_research 第 1 版's (``definitions_sha256``
453f6512…f85dd9, the hash of #944's two reports); the entry adds only the
start (2026-11-22, the day its validation was written to the ledger), the 60
sessions before a verdict and the kind.  The engine is round10_research's
own: the copy read from ``LOAD_FROM`` (``vol_720`` needs 721 bars), its
``plan`` and ``portfolio_research.simulate``.  The synthetic copy here has
more than 721 sessions before the start and 80 after, so the entry runs as
frozen; its five output files are locked by ``F2_DIGESTS``.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import Base, ChipSnapshot, CorporateAction, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
pr = _tool("portfolio_research")
er = _tool("explore_research")
r10 = _tool("round10_research")
tool = _tool("forward_watch")

F2_SHA256 = "453f65124f86b5643ef1ce79dd079530a603e9434ed719a5f942090eeaf85dd9"
EXPLORE_SHA256 = "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
SINCE = date(2026, 11, 22)  # a Sunday: the first signal date is 2026-11-23
FIRST_SIGNAL = date(2026, 11, 23)


# --- the frozen entry -------------------------------------------------------------


def test_f2_is_the_frozen_entry():
    assert list(tool.WATCHES) == ["X4", "H2", "H2-product", "F2", "P2"]
    assert tool.WATCHES["F2"] == {
        "kind": "前瞻觀察",
        "source": "round10_research",
        "source_version": 1,
        "code": "F2",
        "definitions_sha256": F2_SHA256,
        "since": SINCE,
        "min_days": 60,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/944#issuecomment-7072993427"
        ),
    }
    # the definition #944's exploration and validation ran: imported, not copied
    assert tool.SOURCES["round10_research"] is r10
    assert tool.definition("F2") is r10.HYPOTHESES["F2"]
    assert r10.VERSION == 1 and r10.definitions_sha256() == F2_SHA256
    assert tool.source_problems("F2") == []
    assert tool.definition("F2") == {
        "engine": "portfolio",
        "direction": "多因子合成",
        "label": "保守公式：`vol_720` 較小的一半裡，`cash_yield_12m` 與 `mom_240_20` "
        "的平均名次小者先",
        "rule": "daily",
        "half": ("vol_720", "low"),
        "ranks": (("cash_yield_12m", "high"), ("mom_240_20", "high")),
        "score": "low",
        "top": 20,
        "hold": 60,
        "start": ("session", date(2007, 12, 3), 721),
    }
    assert r10.VOL_WINDOW == 720 and r10.LOAD_FROM == er.LOAD_FROM
    assert tool.display("F2") == "F2"


def test_the_other_entries_and_their_source_are_unchanged():
    """X4, H2 and H2-product still run explore_research 第 2 版 (AC-3)."""

    assert er.VERSION == 2 and er.definitions_sha256() == EXPLORE_SHA256
    for name in ("X4", "H2", "H2-product"):
        entry = tool.WATCHES[name]
        assert entry["source"] == "explore_research"
        assert entry["definitions_sha256"] == EXPLORE_SHA256
        assert tool.source_problems(name) == []
    assert tool.ENGINES["explore_research"] is tool.explore_daily


def test_the_command_takes_f2_and_no_parameter(tmp_path):
    choices = next(a for a in tool._parser()._actions if "--watch" in a.option_strings)
    assert "F2" in choices.choices
    base = ["--db", "x", "--out", str(tmp_path), "--watch", "F2"]
    for extra in (["--since", "2026-01-02"], ["--top", "5"], ["--hold", "20"]):
        with pytest.raises(SystemExit) as stopped:
            tool.main([*base, *extra])
        assert stopped.value.code == 2


# --- the synthetic copy -----------------------------------------------------------

STOCKS = range(1, 25)
INDEX_ID = 90
AFTER = 80  # sessions from the first signal date on


def trading_days() -> list[date]:
    out, day = [], date(2023, 9, 4)
    while True:
        if day.weekday() < 5:
            out.append(day)
            if day >= FIRST_SIGNAL and len(out) - out.index(FIRST_SIGNAL) == AFTER:
                return out
        day += timedelta(days=1)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int, count: int) -> list[float]:
    """Each stock its own volatility and drift; 13 … 24 are well above 1 … 12."""

    drift = (i - 12) * 0.00015
    width = 0.004 + 0.001 * i + (0.01 if i > 12 else 0.0)
    level, out = 40.0 + i, []
    for t in range(count):
        level *= 1.0 + drift + width * noise(i, t)
        out.append(round(level, 4))
    return out


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
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
                    "status": "active",
                }
                for i in STOCKS
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
        bars, chips = [], []
        for i in STOCKS:
            prices = closes(i, len(days))
            for t, day in enumerate(days):
                close = prices[t]
                open_ = (prices[t - 1] if t else close) * (1 + 0.004 * noise(i, t, "o"))
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": round(open_, 4),
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": 2_000_000 + 10_000 * i,
                        "turnover": close * (2_000_000 + 10_000 * i),
                        "turnover_status": "available",
                        "source": "test",
                        "is_suspended": False,
                    }
                )
                chips.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "margin_balance": 100_000.0,
                        "source": "test",
                    }
                )
        for t, day in enumerate(days):
            level = 22000.0 + 4 * t + 30 * noise(INDEX_ID, t)
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
        db.execute(insert(ChipSnapshot), chips)
        # a cash dividend each July for most stocks; one more on a session
        # after the start, so the yields (and the ranks) change forward
        actions = []
        for i in STOCKS:
            if i % 4 == 0:
                continue
            for year in (2024, 2025, 2026):
                actions.append(
                    {
                        "instrument_id": i,
                        "action_date": date(year, 7, 10 + i % 7),
                        "action_type": "cash_dividend",
                        "cash_dividend": round(0.3 + 0.17 * (i % 9), 2),
                        "stock_dividend_ratio": None,
                        "source": "test",
                    }
                )
        for i in (4, 8):
            actions.append(
                {
                    "instrument_id": i,
                    "action_date": days[days.index(FIRST_SIGNAL) + 30],
                    "action_type": "cash_dividend",
                    "cash_dividend": 3.0,
                    "stock_dividend_ratio": None,
                    "source": "test",
                }
            )
        db.execute(insert(CorporateAction), actions)
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def f2_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("f2") / "stock.db")


def no_window(monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


# research_report.load_actions points these at the copy for app.config; the
# command is one process per run, so each call here puts them back after it.
APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
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
    argv = ["--db", str(db), "--watch", "F2", "--out", str(out), "--min-free-gb", "0"]
    return one_process(lambda: tool.main([*argv, *extra]))


def edited(db: Path, tmp_path: Path, name: str, *statements: tuple) -> Path:
    path = tmp_path / name / "stock.db"
    path.parent.mkdir()
    shutil.copy(db, path)
    con = sqlite3.connect(path)
    try:
        for statement in statements:
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


# F2's forward outputs on ``f2_db`` (written by the commit that added the
# entry, #949): a change of the definition, the engine, the costs or the report
# fails here and is a new entry, not an edit.
F2_DIGESTS = {
    "summary.md": "c625a70378c47e7bc381582e3685c02ac504e9adb6fbce6c216a83c0a0e7123a",
    "tables.json": "956df2a4d9ffaf4790fad8696ccd141d85e99f7e98c3ed96255e05b4514a25d6",
    "equity.csv": "423cfe3463b238bfc14f3b9c8abb0cfed8d703f4d81fdb1e0cf3e140df140f06",
    "picks.csv": "f4d27f2582cb36b2d99973add2f5c2c8bcf61b5fa09c275847b53000cf5a92fc",
    "trades.csv": "fed8b9cc5f5e7ffb6e34de4afcf2fa31f271af6636bfd61add049d7eeba88b9d",
}


@pytest.fixture(scope="module")
def f2_run(f2_db, tmp_path_factory):
    """The command as frozen: no cutoff, the copy's last session."""

    out = tmp_path_factory.mktemp("frozen") / "out"
    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        assert watch(f2_db, out) == 0
    finally:
        patch.undo()
    return out


def test_f2_output_is_frozen(f2_run):
    assert digests(f2_run) == F2_DIGESTS


def test_f2_reports_its_kind_and_round10s_picks(f2_run):
    tables = read_json(f2_run / "tables.json")
    days = trading_days()
    assert tables["days"] == AFTER - 1 >= 60
    assert tables["verdict"] in pr.FORWARD_VERDICTS and tables["verdict"] != "樣本不足"
    assert (tables["watch"], tables["kind"], tables["min_days"]) == (
        "F2",
        "前瞻觀察",
        60,
    )
    assert tables["entry"]["source"] == "round10_research"
    assert tables["definition"]["half"] == ["vol_720", "low"]
    assert set(tables["counts"]) == {"F2", "population"}
    assert set(tables["curves"]) == {"taiex", "F2", "population"}
    assert tables["counts"]["F2"]["bought"] > 0
    assert tables["excess"]["population"]["days"] == tables["days"]
    # the overlap with H2's list on every signal date (listed only)
    assert tables["overlap"]["days"] == tables["signal_days"] == AFTER - 1
    assert 0.0 <= tables["overlap"]["mean"] <= 1.0
    summary = (f2_run / "summary.md").read_text(encoding="utf-8").splitlines()
    assert summary[0] == "# F2 前瞻觀察的前瞻紀錄（forward_watch 第 1 版，#868）"
    first = [line for line in summary if line.startswith("- ")][:4]
    assert first[0].startswith("- 對加權指數超額（只列出）")
    assert (
        first[1].startswith("- 對母體超額") and f"累積 {tables['days']} 日" in first[1]
    )
    assert first[2].startswith("- 判定：") and "判到「輸給基準」也只記錄" in first[2]
    assert first[3].startswith("- 定義：round10_research 第 1 版的 F2")
    assert F2_SHA256 in first[3] and "issuecomment-7072993427" in first[3]
    text = "\n".join(summary)
    assert "## 和 H2 的重疊（只列出）" in text and r10.OVERLAP_NOTE in text
    assert "`vol_720` 缺值" in text and "低波動半平均檔數" in text
    assert read_csv(f2_run / "equity.csv")[0].keys() == {
        "date",
        "F2",
        "population",
        "taiex_close",
    }
    # the picks are F2's: in the low-volatility half, the mean rank small first
    lines = (f2_run / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == (
        "signal_date,rank,exchange,symbol,vol_720,cash_yield_12m,mom_240_20,"
        "r1,r2,score,tie"
    )
    picks = read_csv(f2_run / "picks.csv")
    by_day: dict[str, list[dict]] = {}
    for row in picks:
        by_day.setdefault(row["signal_date"], []).append(row)
    assert len(by_day) == AFTER - 1
    for rows in by_day.values():
        assert len(rows) == 12  # ⌈24 ÷ 2⌉, fewer than N 20
        assert all(row["vol_720"] for row in rows)
        scores = [float(row["score"]) for row in rows]
        assert scores == sorted(scores)
    # on the first signal date the low-volatility half is the twelve quietest
    # (``closes``)
    first = by_day[FIRST_SIGNAL.isoformat()]
    assert {row["symbol"] for row in first} == {f"S{i}" for i in range(1, 13)}
    assert days[-1].isoformat() == tables["cutoff"]


# --- causality and the start ------------------------------------------------------


def test_only_signal_dates_from_the_start_count(f2_run):
    days = trading_days()
    tables = read_json(f2_run / "tables.json")
    assert tables["since"] == SINCE.isoformat()
    assert tables["first_signal"] == FIRST_SIGNAL.isoformat()
    picks = read_csv(f2_run / "picks.csv")
    assert min(row["signal_date"] for row in picks) == FIRST_SIGNAL.isoformat()
    equity = read_csv(f2_run / "equity.csv")
    assert equity[0]["date"] == days[days.index(FIRST_SIGNAL) + 1].isoformat()
    trades = read_csv(f2_run / "trades.csv")
    assert min(row["bought"] for row in trades) > FIRST_SIGNAL.isoformat()


def test_vol_720_has_its_721_bars_on_the_first_signal_date(f2_db, tmp_path):
    """The copy is read from LOAD_FROM (round10_research's rule): with
    explore_research's 730 calendar days of warm-up the first signal date
    would have about 520 bars and no ``vol_720``, so no list (PR #939 review
    7059380651)."""

    days = trading_days()
    warmup = FIRST_SIGNAL - timedelta(days=tool.WARMUP_CALENDAR_DAYS)
    assert len([d for d in days if warmup <= d <= FIRST_SIGNAL]) < 721
    assert days.index(FIRST_SIGNAL) >= 720  # 721 bars counting T
    ctx = one_process(lambda: r10.load(f2_db, r10.LOAD_FROM, days[-1], tmp_path))
    at = days.index(FIRST_SIGNAL)
    values = [r10.vol_720(ctx, ctx.panel.series[i], at) for i in STOCKS]
    assert all(value is not None for value in values)


def test_more_days_at_the_end_change_no_earlier_number(f2_db, tmp_path, monkeypatch):
    """The copy cut at a session and the longer copy with that cutoff give the
    same files; without the cutoff, the earlier days' rows are the same."""

    no_window(monkeypatch)
    days = trading_days()
    cut = days[days.index(FIRST_SIGNAL) + 65]
    short = edited(
        f2_db,
        tmp_path,
        "short",
        ("delete from market_bars where trading_date > ?", (cut.isoformat(),)),
        ("delete from chip_snapshots where trading_date > ?", (cut.isoformat(),)),
        ("delete from corporate_actions where action_date > ?", (cut.isoformat(),)),
    )
    first, again, longer = tmp_path / "first", tmp_path / "again", tmp_path / "longer"
    assert watch(short, first) == 0
    assert watch(f2_db, again, "--cutoff", cut.isoformat()) == 0
    assert watch(f2_db, longer) == 0
    assert normalized(again, copy=False) == normalized(first, copy=False)
    base = read_json(first / "tables.json")
    assert base["days"] == 65 and base["verdict"] != "樣本不足"
    for name in ("equity.csv", "picks.csv"):
        rows, more = read_csv(first / name), read_csv(longer / name)
        assert len(more) > len(rows) and more[: len(rows)] == rows


def test_short_of_60_days_lists_numbers_and_no_verdict(f2_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    days = trading_days()
    cut = days[days.index(FIRST_SIGNAL) + 59]
    out = tmp_path / "out"
    assert watch(f2_db, out, "--cutoff", cut.isoformat()) == 0
    tables = read_json(out / "tables.json")
    assert (tables["days"], tables["min_days"], tables["verdict"]) == (
        59,
        60,
        "樣本不足",
    )
    assert tables["excess"]["population"]["mean"] is not None
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 59／60 日）" in summary and "數字不是判定" in summary


def test_before_any_session_after_the_start(f2_db, tmp_path, monkeypatch, capsys):
    """A copy that ends before the start: 0 days, no simulation, 樣本不足."""

    no_window(monkeypatch)
    days = trading_days()
    cut = days[days.index(FIRST_SIGNAL) - 1]
    out = tmp_path / "out"
    assert watch(f2_db, out, "--cutoff", cut.isoformat()) == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["verdict"], line["days"], line["watch"]) == ("樣本不足", 0, "F2")
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 0／60 日）" in summary and "前瞻起日 2026-11-22" in summary
    assert read_json(out / "tables.json")["overlap"]["days"] == 0
    assert (out / "equity.csv").read_text(encoding="utf-8").splitlines() == [
        "date,F2,population,taiex_close"
    ]


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [("VERSION", 2, "version 2"), ("HYPOTHESES", None, "definitions_sha256")],
)
def test_a_changed_source_is_refused(
    f2_db, tmp_path, monkeypatch, capsys, attribute, value, message
):
    no_window(monkeypatch)
    if value is None:
        changed = {**r10.HYPOTHESES, "F2": {**r10.HYPOTHESES["F2"], "top": 10}}
        monkeypatch.setattr(r10, "HYPOTHESES", changed)
    else:
        monkeypatch.setattr(r10, attribute, value)
    out = tmp_path / "out"
    assert watch(f2_db, out) == 2
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]
    assert any(message in problem for problem in refused)
    assert not out.exists()


def test_the_entry_is_round10_researchs_own(f2_db, f2_run, monkeypatch):
    """round10_research's own run of F2 on a segment from the start gives the
    same daily equity, population and picks: the definition and the engine
    are the ones #944 ran, not a second copy."""

    days = trading_days()
    # a later segment's first signal is the session before its first day
    segment = (days[days.index(FIRST_SIGNAL) + 1], days[-1])
    monkeypatch.setattr(r10, "SEGMENTS", {**r10.SEGMENTS, "used": segment})
    ctx = one_process(
        lambda: r10.load(f2_db, r10.LOAD_FROM, days[-1], f2_run.parent / "raw")
    )
    result = r10.run_portfolio(ctx, f2_db, "F2", "used")
    mine, population = result["_equity"]
    equity = read_csv(f2_run / "equity.csv")
    assert [row["date"] for row in equity] == [d.isoformat() for d in result["_dates"]]
    assert [row["F2"] for row in equity] == [f"{v:.8f}" for v in mine]
    assert [row["population"] for row in equity] == [f"{v:.8f}" for v in population]
    picks = read_csv(f2_run / "picks.csv")
    assert [(row["signal_date"], row["symbol"]) for row in picks] == [
        (row["signal_date"], row["symbol"]) for row in result["_rows"]
    ]
    assert read_json(f2_run / "tables.json")["overlap"] == json.loads(
        json.dumps(result["overlap"])
    )
