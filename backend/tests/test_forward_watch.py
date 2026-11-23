"""tools/research/forward_watch.py: the frozen forward entries of X4 (#868), H2
(#875), H2 in the product (key H2-product, kind 已進產品 from 2026-11-21,
#902; ``H2_PRODUCT_DIGESTS``) and round 15's P2 (#990, the event-day engine,
its own synthetic copy at the end; ``P2_DIGESTS``).

X4's and X2's definitions are explore_research's (#867 and #864 ran them,
``definitions_sha256`` 600dc942…ebec63); an entry adds only the start
(2026-11-20), the 60 sessions before a verdict and the kind (X4 前瞻觀察, H2
通過驗證).  The runs use a synthetic copy whose calendar spans the frozen start,
so the entries run as frozen, and their five output files are locked by
``X4_DIGESTS`` and ``H2_DIGESTS``: a change there is a new entry, not an edit.
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

from app.models import (
    Base,
    ChipSnapshot,
    FundamentalSnapshot,
    Instrument,
    MarketBar,
    MonthlyRevenue,
)

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
tool = _tool("forward_watch")

X4_SHA256 = "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
SINCE = date(2026, 11, 20)


# --- the frozen entry -------------------------------------------------------------


def test_x4_is_the_frozen_entry():
    # P2: #990, A1: #1013
    assert set(tool.WATCHES) == {"X4", "H2", "H2-product", "F2", "P2", "A1"}
    entry = tool.WATCHES["X4"]
    assert entry == {
        "kind": "前瞻觀察",
        "source": "explore_research",
        "source_version": 2,
        "code": "X4",
        "definitions_sha256": X4_SHA256,
        "since": SINCE,
        "min_days": 60,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/867#issuecomment-7033243199"
        ),
    }
    # the definition #867's exploration and validation ran: imported, not copied
    assert tool.definition("X4") is er.HYPOTHESES["X4"]
    assert er.VERSION == 2 and er.definitions_sha256() == X4_SHA256
    assert tool.source_problems("X4") == []
    assert tool.definition("X4") == {
        "direction": "籌碼＋基本面",
        "label": (
            "只取 `revenue_yoy` > 0 且 `eps_growth_yield` > 0，"
            "依最新一季 EPS × 4 ÷ T 日未還原收盤大者先"
        ),
        "rule": "daily",
        "subset": None,
        "filters": (("revenue_yoy", ">", 0.0), ("eps_growth_yield", ">", 0.0)),
        "keys": ("eps_yield_raw",),
        "top": 20,
        "hold": 60,
        "start": ("date", date(2014, 8, 14)),
    }
    assert tool.MIN_DAYS == pr.MIN_DAYS == 60
    assert tool.WARMUP_CALENDAR_DAYS == er.WARMUP_CALENDAR_DAYS == 730


def test_h2_is_x2_frozen_as_passed():
    """H2 is X2 as #864's exploration (7041131687) and validation (7043710015)
    ran it: the same definition hash as X4's (one explore_research version 2),
    the kind 通過驗證 and the start 2026-11-20 (#875 決定 7044311598)."""

    entry = tool.WATCHES["H2"]
    assert entry == {
        "kind": "通過驗證",
        "source": "explore_research",
        "source_version": 2,
        "code": "X2",
        "definitions_sha256": X4_SHA256,
        "since": SINCE,
        "min_days": 60,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/864#issuecomment-7043710015"
        ),
    }
    assert tool.definition("H2") is er.HYPOTHESES["X2"]
    assert tool.source_problems("H2") == []
    assert tool.definition("H2") == {
        "direction": "持有較久、低換手",
        "label": "`high_gap_240`（收盤 ÷ 240 日最高價 − 1）大者先",
        "rule": "daily",
        "subset": None,
        "filters": (),
        "keys": ("high_gap_240",),
        "top": 20,
        "hold": 60,
        "start": ("session", date(2007, 4, 23), 240),
    }
    # the two kinds before it are unchanged (X4's golden output holds its note)
    assert (tool.WATCH, tool.PRODUCT, tool.PASSED) == (
        "前瞻觀察",
        "已進產品",
        "通過驗證",
    )
    assert set(tool.KIND_NOTES) == {"前瞻觀察", "已進產品", "通過驗證"}
    assert "在 #1 的進產品提案補一則" in tool.KIND_NOTES["通過驗證"]
    assert "不是下架提案" in tool.KIND_NOTES["通過驗證"]


H2_PRODUCT_SINCE = date(2026, 11, 21)


def test_h2_product_is_x2_frozen_in_the_product():
    """H2 in the product (#1 7044998169, live on 2026-11-21 with v1.2.74, #1
    7050216934): X2's frozen definition again, a row of its own under the key
    H2-product, the kind 已進產品 and the start its deployment day; the reports
    name it H2 (#875 決定 7044311598 第 3 點, #902)."""

    entry = tool.WATCHES["H2-product"]
    assert entry == {
        "kind": "已進產品",
        "source": "explore_research",
        "source_version": 2,
        "code": "X2",
        "definitions_sha256": X4_SHA256,
        "since": H2_PRODUCT_SINCE,
        "min_days": 60,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7050216934"
        ),
    }
    # only the kind, the start and the registration differ from the H2 row
    old = tool.WATCHES["H2"]
    assert {key for key in entry if entry[key] != old[key]} == {
        "kind",
        "since",
        "registered",
    }
    assert tool.definition("H2-product") is er.HYPOTHESES["X2"]
    assert tool.source_problems("H2-product") == []
    assert [tool.display(name) for name in tool.WATCHES] == [
        "X4",
        "H2",
        "H2",
        "F2",
        "P2",
        "A1",
    ]
    # 已進產品 on 輸給基準: the coordinator proposes delisting in #1
    note = tool.KIND_NOTES["已進產品"]
    assert "判到「輸給基準」由統籌在 #1 提案下架" in note
    assert "滿 60 日起每月判一次" in note and "其餘判定只列出" in note


def test_the_command_has_no_parameter_flags(tmp_path):
    options = {
        option for action in tool._parser()._actions for option in action.option_strings
    }
    assert options == {
        "-h",
        "--help",
        "--db",
        "--watch",
        "--out",
        "--cutoff",
        "--min-free-gb",
    }
    base = ["--db", "x", "--out", str(tmp_path), "--watch", "X4"]
    for extra in (["--since", "2026-01-02"], ["--top", "5"], ["--min-days", "1"]):
        with pytest.raises(SystemExit) as stopped:
            tool.main([*base, *extra])
        assert stopped.value.code == 2
    with pytest.raises(SystemExit):
        tool.main(["--db", "x", "--out", str(tmp_path), "--watch", "X5"])


@pytest.mark.parametrize(
    ("name", "attribute", "value", "message"),
    [
        ("X4", "VERSION", 3, "version 3"),
        ("X4", "HYPOTHESES", None, "definitions_sha256"),
        ("H2", "VERSION", 3, "version 3"),
        ("H2", "HYPOTHESES", None, "definitions_sha256"),
        ("H2-product", "VERSION", 3, "version 3"),
        ("H2-product", "HYPOTHESES", None, "definitions_sha256"),
    ],
)
def test_a_changed_source_is_refused(
    x4_db, tmp_path, monkeypatch, capsys, name, attribute, value, message
):
    no_window(monkeypatch)
    if value is None:
        code = tool.WATCHES[name]["code"]
        changed = {**er.HYPOTHESES, code: {**er.HYPOTHESES[code], "top": 10}}
        monkeypatch.setattr(er, "HYPOTHESES", changed)
    else:
        monkeypatch.setattr(er, attribute, value)
    out = tmp_path / "out"
    assert watch(x4_db, out, name=name) == 2
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]
    assert any(message in problem for problem in refused)
    assert not out.exists()


# --- the synthetic copy -----------------------------------------------------------

SESSIONS = 390
STOCKS = range(1, 25)
INDEX_ID = 90


def trading_days() -> list[date]:
    out, day = [], date(2025, 10, 1)
    while len(out) < SESSIONS:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    drift = (i - 8) * 0.0003
    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + drift + 0.016 * noise(i, t)
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
            prices = closes(i)
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
                        "foreign_buy": 1000.0 * noise(i, t, "f"),
                        "trust_buy": 0.0,
                        "dealer_buy": 0.0,
                        "margin_balance": 100_000.0,
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
        revenues, quarters = [], []
        for i in STOCKS:
            history: list[float] = []
            for m in range(36):  # 2024-04 .. 2027-03, announced the 10th after
                month = date(2024 + (3 + m) // 12, (3 + m) % 12 + 1, 1)
                announced = date(
                    month.year + month.month // 12, month.month % 12 + 1, 10
                )
                trend = -0.004 if i % 4 == 0 else 0.002 * (i % 5)
                # the trends turn after the start: the picks change forward
                if month >= date(2026, 10, 1) and i % 3 == 0:
                    trend = -trend - 0.003
                revenue = 1000.0 * (1 + trend * m) + 40.0 * ((m * (i + 3)) % 7)
                prior = history[m - 12] if m >= 12 else revenue * 0.95
                history.append(revenue)
                revenues.append(
                    {
                        "instrument_id": i,
                        "revenue_month": month,
                        "revenue": round(revenue, 2),
                        "prior_year_revenue": round(prior, 2),
                        "announcement_date": announced,
                        "source": "test",
                        "raw_payload_id": 1,
                        "data_as_of": "test",
                    }
                )
            for year in (2024, 2025, 2026):
                cumulative = 0.0
                for quarter, (end, due) in enumerate(
                    [
                        (date(year, 3, 31), date(year, 5, 15)),
                        (date(year, 6, 30), date(year, 8, 14)),
                        (date(year, 9, 30), date(year, 11, 14)),
                        (date(year, 12, 31), date(year + 1, 3, 31)),
                    ]
                ):
                    k = (year - 2024) * 4 + quarter
                    own = (1.0 - 0.05 * k) if i % 5 == 0 else (0.5 + 0.03 * (i % 6) * k)
                    cumulative += own
                    quarters.append(
                        {
                            "instrument_id": i,
                            "period_end": end,
                            "fiscal_period": f"{year}Q{quarter + 1}",
                            "announcement_date": due,
                            "eps": round(cumulative, 4),
                            "source": "test",
                        }
                    )
        db.execute(insert(MonthlyRevenue), revenues)
        db.execute(insert(FundamentalSnapshot), quarters)
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def x4_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("x4") / "stock.db")


def no_window(monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


# research_report.load_actions points these at the copy for app.config; the
# command is one process per run, so each call here puts them back after it.
APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def watch(db: Path, out: Path, *extra: str, name: str = "X4") -> int:
    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return tool.main(
            [
                "--db",
                str(db),
                "--watch",
                name,
                "--out",
                str(out),
                "--min-free-gb",
                "0",
                *extra,
            ]
        )
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
FILES = ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")


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


# X4's forward outputs on ``x4_db`` (written by the commit that added the
# entry, #868): a change of the definition, the engine, the costs or the report
# fails here and is a new entry, not an edit.
X4_DIGESTS = {
    "summary.md": "27718a529f3c35901860978a576ffbbb43bc77c6e3665161878e4838091c89fc",
    "tables.json": "6746b7855019bcd4134fe24bb7943c2d7ee7ef1f216bfc1dbb73cf3d9bf6be94",
    "equity.csv": "61bc84993909e0543ca8280b79b7331a4d95c151a2b2141b1b0d05324e0cacb6",
    "picks.csv": "c328cf53fb255292338d0b8f08182346d61273b9518e54c338cf18961d0b14a6",
    "trades.csv": "7f57b3c8b6526f7d530e1a0ffc9fc0b84f38a939ff5c3ca64370dfaf793dc230",
}


@pytest.fixture(scope="module")
def frozen_run(x4_db, tmp_path_factory):
    """The command as frozen: no cutoff, the copy's last session."""

    out = tmp_path_factory.mktemp("frozen") / "out"
    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        assert watch(x4_db, out) == 0
    finally:
        patch.undo()
    return out


def test_x4_output_is_frozen(frozen_run):
    assert digests(frozen_run) == X4_DIGESTS


def test_the_frozen_run_reports_the_object_first_taiex_then_the_population(frozen_run):
    tables = read_json(frozen_run / "tables.json")
    days = trading_days()
    after = [day for day in days if day >= SINCE]
    assert tables["days"] == len(after) - 1 >= 60
    assert tables["verdict"] in pr.FORWARD_VERDICTS and tables["verdict"] != "樣本不足"
    assert tables["kind"] == "前瞻觀察" and tables["min_days"] == 60
    assert tables["excess"]["population"]["days"] == tables["days"]
    summary = (frozen_run / "summary.md").read_text(encoding="utf-8").splitlines()
    first = [line for line in summary if line.startswith("- ")][:3]
    assert first[0].startswith("- 對加權指數超額（只列出）")
    assert (
        first[1].startswith("- 對母體超額") and f"累積 {tables['days']} 日" in first[1]
    )
    assert first[2].startswith("- 判定：") and "判到「輸給基準」也只記錄" in first[2]
    assert X4_SHA256 in "\n".join(summary)
    # the picks are X4's: both filters pass, the raw EPS yield high first
    picks = read_csv(frozen_run / "picks.csv")
    assert picks and len({row["symbol"] for row in picks}) > 3
    for row in picks:
        assert float(row["revenue_yoy"]) > 0 and float(row["eps_growth_yield"]) > 0
    by_day: dict[str, list[float]] = {}
    for row in picks:
        by_day.setdefault(row["signal_date"], []).append(float(row["eps_yield_raw"]))
    assert all(values == sorted(values, reverse=True) for values in by_day.values())
    assert max(int(row["rank"]) for row in picks) <= 20


# H2's forward outputs on ``x4_db`` (written by the commit that added the entry,
# #875): as X4_DIGESTS, a change is a new entry, not an edit.
H2_DIGESTS = {
    "summary.md": "06a07ec3cdd62c1ef2fe8c1a2005b8f3eb00cd39e90a00b4458b7b2424dffebd",
    "tables.json": "3dc58f4cbead94343cabbae6051e0d380646641eb4a8ea2846ff2e45ac4ff748",
    "equity.csv": "09b4045e9eb08c5de2cb3a46d2c1d0d265720d7bdc87c55258fc4e59d178cc4b",
    "picks.csv": "f193e9a073a4ccebe3174e14649bb87f6460a9e9216ee09bbe2284aac856e41f",
    "trades.csv": "2e364f898db203b495a957c7a09904359a89058d67dbdd105ebecb136c742b68",
}


@pytest.fixture(scope="module")
def h2_run(x4_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("h2") / "out"
    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        assert watch(x4_db, out, name="H2") == 0
    finally:
        patch.undo()
    return out


def test_h2_output_is_frozen(h2_run):
    assert digests(h2_run) == H2_DIGESTS


def test_h2_reports_its_kind_and_x2s_picks(h2_run):
    tables = read_json(h2_run / "tables.json")
    days = trading_days()
    assert tables["days"] == len([day for day in days if day >= SINCE]) - 1 >= 60
    assert (tables["watch"], tables["kind"], tables["min_days"]) == (
        "H2",
        "通過驗證",
        60,
    )
    assert tables["first_signal"] == next(d for d in days if d >= SINCE).isoformat()
    # the counts are the object's, under its name as its curve
    assert set(tables["counts"]) == {"H2", "population"}
    assert set(tables["curves"]) == {"taiex", "H2", "population"}
    assert tables["counts"]["H2"]["bought"] > 0
    summary = (h2_run / "summary.md").read_text(encoding="utf-8").splitlines()
    assert summary[0].startswith("# H2 通過驗證的前瞻紀錄")
    first = [line for line in summary if line.startswith("- ")][:4]
    assert first[0].startswith("- 對加權指數超額（只列出）")
    assert (
        first[1].startswith("- 對母體超額") and f"累積 {tables['days']} 日" in first[1]
    )
    assert first[2].startswith("- 判定：") and "在 #1 的進產品提案補一則" in first[2]
    assert first[3].startswith("- 定義：explore_research 第 2 版的 X2")
    assert X4_SHA256 in first[3] and "issuecomment-7043710015" in first[3]
    bought = tables["counts"]["H2"]["bought"]
    assert f"成交計數：買進 {bought:,}、" in "\n".join(summary)
    assert read_csv(h2_run / "equity.csv")[0].keys() == {
        "date",
        "H2",
        "population",
        "taiex_close",
    }
    # the picks are X2's: no filter, closest to the 240-session high first
    picks = read_csv(h2_run / "picks.csv")
    assert picks and set(picks[0]) == {
        "signal_date",
        "rank",
        "exchange",
        "symbol",
        "high_gap_240",
        "tie",
    }
    by_day: dict[str, list[float]] = {}
    for row in picks:
        by_day.setdefault(row["signal_date"], []).append(float(row["high_gap_240"]))
    assert all(len(values) == 20 for values in by_day.values())
    assert all(values == sorted(values, reverse=True) for values in by_day.values())
    assert len({row["symbol"] for row in picks}) > 20


# H2-product's forward outputs on ``x4_db`` (written by the commit that added
# the entry, #902): as X4_DIGESTS, a change is a new entry, not an edit.
H2_PRODUCT_DIGESTS = {
    "summary.md": "be74a536e5bc6a251a4169f2d000ceaf418b5fbc4c1ce2c548fc742d3d54844e",
    "tables.json": "ba951c050a809bc75133673bb8f42dcf43ae117674320f90c448617799701080",
    "equity.csv": "10092d02378c255e185ecbd77f69455d0ccf9f91d68feeb7bedcc6617884275a",
    "picks.csv": "c545b76c2de44529c574849638481eec85949f608ae8a390706dc11afce0dea1",
    "trades.csv": "3b5f43ced9b2cf3529e76db3e46e83151891da3dbab32c807b5423180767fabe",
}


@pytest.fixture(scope="module")
def h2_product_run(x4_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("h2-product") / "out"
    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        assert watch(x4_db, out, name="H2-product") == 0
    finally:
        patch.undo()
    return out


def test_h2_product_output_is_frozen(h2_product_run):
    assert digests(h2_product_run) == H2_PRODUCT_DIGESTS


def test_h2_product_reports_h2_in_the_product(h2_product_run, h2_run):
    tables = read_json(h2_product_run / "tables.json")
    days = trading_days()
    after = [day for day in days if day >= H2_PRODUCT_SINCE]
    assert tables["days"] == len(after) - 1 >= 60
    # the key is the entry run; every name in the report is the code H2
    assert (tables["watch"], tables["kind"], tables["min_days"]) == (
        "H2-product",
        "已進產品",
        60,
    )
    assert tables["since"] == "2026-11-21"
    # 2026-11-21 is a Saturday: the first signal is the next session
    assert tables["first_signal"] == after[0].isoformat() == "2026-11-23"
    assert set(tables["counts"]) == {"H2", "population"}
    assert set(tables["curves"]) == {"taiex", "H2", "population"}
    summary = (h2_product_run / "summary.md").read_text(encoding="utf-8").splitlines()
    assert summary[0] == "# H2 已進產品的前瞻紀錄（forward_watch 第 1 版，#868）"
    # the key is only in the command that reproduces the run
    named = [line for line in summary if "H2-product" in line]
    assert len(named) == 1 and named[0].startswith("- 重現：")
    first = [line for line in summary if line.startswith("- ")][:4]
    assert first[0].startswith("- 對加權指數超額（只列出）")
    assert (
        first[1].startswith("- 對母體超額") and f"累積 {tables['days']} 日" in first[1]
    )
    assert first[2].startswith("- 判定：")
    assert "判到「輸給基準」由統籌在 #1 提案下架" in first[2]
    assert first[3].startswith("- 定義：explore_research 第 2 版的 X2")
    assert X4_SHA256 in first[3] and "issuecomment-7050216934" in first[3]
    assert any(line.startswith("| H2 | ") for line in summary), (
        "the curve row is named H2"
    )
    assert read_csv(h2_product_run / "equity.csv")[0].keys() == {
        "date",
        "H2",
        "population",
        "taiex_close",
    }
    # the same X2 as the H2 row: its picks from the later start are the H2 row's
    old = read_csv(h2_run / "picks.csv")
    picks = read_csv(h2_product_run / "picks.csv")
    assert picks == [row for row in old if row["signal_date"] >= "2026-11-23"]


# --- causality and the start ------------------------------------------------------


def test_only_signal_dates_from_the_start_count(frozen_run):
    days = trading_days()
    first = next(day for day in days if day >= SINCE)
    tables = read_json(frozen_run / "tables.json")
    assert tables["since"] == SINCE.isoformat()
    assert tables["first_signal"] == first.isoformat()
    picks = read_csv(frozen_run / "picks.csv")
    assert min(row["signal_date"] for row in picks) == first.isoformat()
    equity = read_csv(frozen_run / "equity.csv")
    assert equity[0]["date"] == days[days.index(first) + 1].isoformat()
    trades = read_csv(frozen_run / "trades.csv")
    assert min(row["bought"] for row in trades) > first.isoformat()


def test_the_data_before_the_start_is_only_a_warmup(
    x4_db, frozen_run, tmp_path, monkeypatch
):
    """Other prices before the start change nothing: only T's close and the
    bars from the start on are read for the picks and the returns."""

    no_window(monkeypatch)
    scrambled = edited(
        x4_db,
        tmp_path,
        "scrambled",
        (
            "update market_bars set open = open * 1.7, high = high * 1.7, "
            "low = low * 1.7, close = close * 1.7, adj_close = adj_close * 1.7 "
            "where trading_date < ? and instrument_id != ?",
            (SINCE.isoformat(), INDEX_ID),
        ),
    )
    out = tmp_path / "out"
    assert watch(scrambled, out) == 0
    assert normalized(out, copy=False) == normalized(frozen_run, copy=False)


def test_more_days_at_the_end_change_no_earlier_number(x4_db, tmp_path, monkeypatch):
    """The copy cut at a session and the longer copy with that cutoff give the
    same files; without the cutoff, the earlier days' rows are the same."""

    no_window(monkeypatch)
    days = trading_days()
    cut = days[days.index(next(day for day in days if day >= SINCE)) + 65]
    short = edited(
        x4_db,
        tmp_path,
        "short",
        ("delete from market_bars where trading_date > ?", (cut.isoformat(),)),
        ("delete from chip_snapshots where trading_date > ?", (cut.isoformat(),)),
        (
            "delete from monthly_revenues where announcement_date > ?",
            (cut.isoformat(),),
        ),
        (
            "delete from fundamental_snapshots where announcement_date > ?",
            (cut.isoformat(),),
        ),
    )
    first, again, longer = tmp_path / "first", tmp_path / "again", tmp_path / "longer"
    assert watch(short, first) == 0
    assert watch(x4_db, again, "--cutoff", cut.isoformat()) == 0
    assert watch(x4_db, longer) == 0
    assert normalized(again, copy=False) == normalized(first, copy=False)
    base = read_json(first / "tables.json")
    assert base["days"] == 65 and base["verdict"] != "樣本不足"
    for name in ("equity.csv", "picks.csv"):
        rows, more = read_csv(first / name), read_csv(longer / name)
        assert len(more) > len(rows) and more[: len(rows)] == rows


def test_short_of_60_days_lists_numbers_and_no_verdict(x4_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    days = trading_days()
    cut = days[days.index(next(day for day in days if day >= SINCE)) + 59]
    out = tmp_path / "out"
    assert watch(x4_db, out, "--cutoff", cut.isoformat()) == 0
    tables = read_json(out / "tables.json")
    assert (tables["days"], tables["min_days"], tables["verdict"]) == (
        59,
        60,
        "樣本不足",
    )
    assert tables["excess"]["population"]["mean"] is not None
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 59／60 日）" in summary and "數字不是判定" in summary


def test_before_any_session_after_the_start(x4_db, tmp_path, monkeypatch, capsys):
    """A copy that ends before the start: 0 days, no simulation, 樣本不足."""

    no_window(monkeypatch)
    days = trading_days()
    cut = days[days.index(next(day for day in days if day >= SINCE)) - 1]
    out = tmp_path / "out"
    assert watch(x4_db, out, "--cutoff", cut.isoformat()) == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["verdict"], line["days"], line["watch"]) == ("樣本不足", 0, "X4")
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 0／60 日）" in summary and "前瞻起日 2026-11-20" in summary
    assert (out / "equity.csv").read_text(encoding="utf-8").splitlines() == [
        "date,X4,population,taiex_close"
    ]


def test_the_command_refuses_production(x4_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STOCK_DATA_DIR", str(x4_db.parent))
    out = tmp_path / "out"
    assert watch(x4_db, out) == 2
    assert "refused" in capsys.readouterr().out
    assert not out.exists()


@pytest.mark.parametrize(
    ("name", "run"),
    [("X4", "frozen_run"), ("H2", "h2_run"), ("H2-product", "h2_product_run")],
)
def test_the_entry_is_explore_researchs_own(x4_db, request, monkeypatch, name, run):
    """explore_research's own run of the code on a segment from the start gives
    the same daily equity, population and picks: the definition and the engine
    are the ones #867 (X4) and #864 (X2) ran, not a second copy."""

    frozen_run = request.getfixturevalue(run)
    code = tool.WATCHES[name]["code"]
    since = tool.WATCHES[name]["since"]
    days = trading_days()
    first = next(day for day in days if day >= since)
    # a later segment's first signal is the session before its first day
    segment = (days[days.index(first) + 1], days[-1])
    monkeypatch.setattr(er, "SEGMENTS", {**er.SEGMENTS, "used": segment})
    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        ctx = er.load_context(
            x4_db,
            since - timedelta(days=er.WARMUP_CALENDAR_DAYS),
            days[-1],
            frozen_run.parent / "raw",
        )
        result = er.run_one(ctx, x4_db, code, "used")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    mine, population = result["_equity"]
    equity = read_csv(frozen_run / "equity.csv")
    assert [row["date"] for row in equity] == [d.isoformat() for d in result["_dates"]]
    assert [row[tool.display(name)] for row in equity] == [f"{v:.8f}" for v in mine]
    assert [row["population"] for row in equity] == [f"{v:.8f}" for v in population]
    picks = read_csv(frozen_run / "picks.csv")
    assert [(row["signal_date"], row["symbol"]) for row in picks] == [
        (row["signal_date"], row["symbol"]) for row in result["_rows"]
    ]


# --- P2: round 15's event-day hypothesis (#990) ----------------------------------

r10 = sys.modules.get("round10_research") or _tool("round10_research")
r14 = sys.modules.get("round14_research") or _tool("round14_research")
r15 = sys.modules.get("round15_research") or _tool("round15_research")
ms = sys.modules.get("mainstream_research") or _tool("mainstream_research")
im = sys.modules.get("industry_members") or _tool("industry_members")

P2_SHA256 = "dbbeb3e2626bbd4642c7b8732da3f376c9905e50575bee8f2dbed60273ea824e"
P2_SINCE = date(2026, 11, 23)
# 2026Q3's deadline 2026-11-14 is a Saturday: its event day 2026-11-16 is
# before the start; 2026Q4's deadline 2027-03-31 is the first forward one.
P2_BEFORE = date(2026, 11, 16)
P2_FIRST = date(2027, 3, 31)
# The tools' versions and definition hashes the five entries rest on (AC-1, AC-3)
SOURCE_HASHES = {
    "explore_research": (2, X4_SHA256),
    "round10_research": (
        1,
        "453f65124f86b5643ef1ce79dd079530a603e9434ed719a5f942090eeaf85dd9",
    ),
    "round14_research": (
        1,
        "3c8cf489dd99778e71d29215b1bd7e8b8d63607c902500c9e9ac122bbe0a0044",
    ),
    "round15_research": (1, P2_SHA256),
}


def test_p2_is_round15s_p2_frozen_as_forward_watch():
    entry = tool.WATCHES["P2"]
    assert entry == {
        "kind": "前瞻觀察",
        "source": "round15_research",
        "source_version": 1,
        "code": "P2",
        "definitions_sha256": P2_SHA256,
        "since": P2_SINCE,
        "min_days": 60,
        "registered": (
            "https://github.com/YiCheng0608/stock-lab/issues/986#issuecomment-7097870215"
        ),
    }
    # the definition #986's exploration and validation ran: imported, not copied
    assert tool.SOURCES["round15_research"] is r15
    assert tool.definition("P2") is r15.HYPOTHESES["P2"]
    assert tool.source_problems("P2") == []
    assert tool.ENGINES["round15_research"] is tool.round15_events
    assert tool.COVERAGE_LINES["round15_research"] is r15.coverage_lines
    assert tool.PICK_FIELDS["round15_research"]("P2", {}) == r15.PICK_FIELDS["P2"]
    assert tool.definition("P2") == {
        "engine": "events",
        "direction": "基本面：三率三升",
        "label": "每季法定期限的事件日，`margins_up`（最新一季單季毛利率、營益率、淨利率都高於上一季，"
        "也都高於去年同季）成立，以雜湊取 20 檔、不排序；持有到下一個事件日",
        "rule": "quarterly",
        "conditions": (("margins_up", "is", True),),
        "order": "the hash only",
        "short": "cash, not filled",
        "top": 20,
        "hold": "next_event",
        "start": ("date", date(2014, 5, 15)),
    }
    assert tool.display("P2") == "P2" and tool.KIND_NOTES[entry["kind"]]


@pytest.mark.parametrize("name", sorted(SOURCE_HASHES))
def test_the_source_tools_versions_and_hashes_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == SOURCE_HASHES[name]


def test_the_command_takes_p2_and_no_parameter(tmp_path):
    choices = next(a for a in tool._parser()._actions if "--watch" in a.option_strings)
    assert "P2" in choices.choices
    base = ["--db", "x", "--out", str(tmp_path), "--watch", "P2"]
    for extra in (["--since", "2026-11-14"], ["--top", "5"], ["--members", "x"]):
        with pytest.raises(SystemExit) as stopped:
            tool.main([*base, *extra])
        assert stopped.value.code == 2


def test_the_next_deadline():
    sessions = [date(2026, 11, 20), date(2026, 11, 23), date(2026, 11, 24)]
    assert tool.next_deadline(sessions, P2_SINCE, 2) == P2_FIRST
    # a cutoff on the deadline: it is no signal yet, so it is still the next one
    sessions = [date(2027, 3, 30), date(2027, 3, 31)]
    assert tool.next_deadline(sessions, P2_SINCE, 1) == P2_FIRST
    sessions = [date(2027, 3, 31), date(2027, 4, 1)]
    assert tool.next_deadline(sessions, P2_SINCE, 1) == date(2027, 5, 15)
    assert tool.next_deadline(sessions, date(2026, 11, 10), 0) == date(2026, 11, 14)


# The synthetic copy: 2025-01-02 .. 2027-09-30, statements 2023～2027Q2.
P2_STOCKS = range(1, 31)
P2_UP = range(1, 25)  # margins rising every quarter: margins_up on every deadline
P2_BANK = 25  # report_format bank: never margins_up
P2_TRANSFERRED = 31  # EPS only, transferred: out of the reference
P2_DELISTED = 32  # every field, delisted, its last bar 2026-06-30
P2_IDS = (*P2_STOCKS, P2_TRANSFERRED, P2_DELISTED)
P2_END = date(2027, 9, 30)


def p2_days() -> list[date]:
    out, day = [], date(2025, 1, 2)
    while day <= P2_END:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def p2_statements() -> list[dict]:
    rows = []
    deadlines = ((5, 15), (8, 14), (11, 14), (3, 31))
    for i in P2_IDS:
        k = 0
        for year in range(2023, 2028):
            totals = [0.0] * 4
            eps = 0.0
            for q in range(4):
                if (year, q) > (2027, 1):  # 2027Q2 is the last announced
                    break
                k += 1
                end = date(year, 3 * (q + 1), 31 if q in (0, 3) else 30)
                month, day = deadlines[q]
                due = date(year + (1 if q == 3 else 0), month, day)
                margin = 0.2 + (0.002 * k + 0.0001 * i if i in P2_UP else 0.0)
                own = (1000.0 + 10 * i, 1000.0 * margin, 500.0 * margin, 250.0 * margin)
                totals = [a + b for a, b in zip(totals, own)]
                eps += 1.0 + 0.1 * i
                data: dict = {}
                if i != P2_TRANSFERRED:
                    data = {
                        "report_format": "bank" if i == P2_BANK else "general",
                        "營業收入": f"{totals[0]:,.0f}",
                        "營業毛利（毛損）淨額": f"{totals[1]:.3f}",
                        "營業利益（損失）": f"{totals[2]:.3f}",
                        "本期淨利（淨損）": f"{totals[3]:.3f}",
                    }
                rows.append(
                    {
                        "instrument_id": i,
                        "period_end": end,
                        "fiscal_period": f"Q{q + 1}",
                        "announcement_date": due,
                        "eps": round(eps, 4),
                        "data_json": data,
                        "source": "test",
                    }
                )
    return rows


def p2_build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = p2_days()
    status = {P2_TRANSFERRED: "transferred", P2_DELISTED: "delisted"}
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
                for i in P2_IDS
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
        for i in P2_IDS:
            level = 50.0 + i
            for t, day in enumerate(days):
                if i == P2_DELISTED and day > date(2026, 6, 30):
                    break
                previous = level
                level *= 1.0 + (i - 15) * 0.0001 + 0.02 * noise(i, t, "p2")
                close = round(level, 4)
                open_ = round(previous * (1 + 0.004 * noise(i, t, "p2o")), 4)
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
            level = 22000.0 + 4 * t + 30 * noise(INDEX_ID, t, "p2")
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
        db.execute(insert(FundamentalSnapshot), p2_statements())
        db.commit()
    engine.dispose()
    return path


def p2_write_members(folder: Path) -> Path:
    """A #779-shaped member table beside the copy, for ``round15_research.load``
    only (forward_watch does not read it)."""

    day = p2_days()[0].isoformat()
    label = im.GROUP_LABELS["TWSE"]["24"]
    rows = sorted(
        [day, "TWSE", "24", "", label, im.group_id(label), f"S{i}", f"N{i}",
         im.retroactive("TWSE", "24", day)]
        for i in range(1, 9)
    )  # fmt: skip
    target = folder.joinpath(*ms.MEMBERS_DIR, ms.MEMBERS_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(im.table_bytes(rows, "2025-01", "2025-01"))
    return target


@pytest.fixture(scope="module")
def p2_db(tmp_path_factory) -> Path:
    return p2_build(tmp_path_factory.mktemp("p2") / "stock.db")


def p2_watch(db: Path, out: Path, *extra: str) -> int:
    return watch(db, out, *extra, name="P2")


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


# P2's forward outputs on ``p2_db`` (written by the commit that added the
# entry, #990): a change of the definition, the engine or the report fails here.
P2_DIGESTS = {
    "summary.md": "ef0a4de0c6f9e2dcea0368cb2b06bffdfdec6dbf19cab91ba5e4e5f0ab40525d",
    "tables.json": "4474db0dd8d4f3068e137b6f9e6cee16043c614c60b71823a19851f70efe9557",
    "equity.csv": "873905911157d3a1ce0f19aa17fd68e159f0a3b337815d18beefe5b11245fe8b",
    "picks.csv": "40302fdd061454e913e78366ebdc198405767f797a82a182cd42ff1cf08d9280",
    "trades.csv": "80315bf58e644e2e0f6ca8e8a6887db196a5afc3520aa979436753667d2d7b8a",
}


@pytest.fixture(scope="module")
def p2_run(p2_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("p2_frozen") / "out"
    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        assert p2_watch(p2_db, out) == 0
    finally:
        patch.undo()
    return out


def test_p2_output_is_frozen(p2_run):
    assert digests(p2_run) == P2_DIGESTS


def test_p2_buys_only_event_days_from_the_start(p2_run):
    days = p2_days()
    tables = read_json(p2_run / "tables.json")
    assert (tables["since"], tables["first_signal"]) == (
        P2_SINCE.isoformat(),
        P2_FIRST.isoformat(),
    )
    # 2027-03-31, 2027-05-17 (5/15 a Saturday), 2027-08-16 (8/14 a Saturday)
    signals = ["2027-03-31", "2027-05-17", "2027-08-16"]
    assert tables["signal_days"] == 3
    assert [e["signal_date"] for e in tables["rebalances"]] == signals
    picks = read_csv(p2_run / "picks.csv")
    assert sorted({row["signal_date"] for row in picks}) == signals
    # 24 qualify, the hash takes 20 (the bank, the flat ones and the EPS-only never)
    assert [e["hits"] for e in tables["rebalances"]] == [24, 24, 24]
    assert {len([r for r in picks if r["signal_date"] == d]) for d in signals} == {20}
    assert not {row["symbol"] for row in picks} & {"S25", "S26", "S31", "S32"}
    equity = read_csv(p2_run / "equity.csv")
    assert equity[0]["date"] == days[days.index(P2_FIRST) + 1].isoformat()
    assert equity[-1]["date"] == P2_END.isoformat()
    trades = read_csv(p2_run / "trades.csv")
    assert min(row["bought"] for row in trades) == equity[0]["date"]
    assert tables["days"] == len(equity) >= 60 and tables["verdict"] != "樣本不足"
    # the reference (P2 第 7 點): listed, not judged
    assert tables["excess"]["reference"]["days"] == tables["days"]
    summary = (p2_run / "summary.md").read_text(encoding="utf-8")
    assert summary.splitlines()[0].startswith("# P2 前瞻觀察的前瞻紀錄")
    assert "| 超額（對對照基準，只列出） |" in summary
    assert "下一個法定期限 2027-11-14" in summary  # a Sunday: its event day 11-15
    assert tables["next_deadline"] == "2027-11-14"


def test_p2_an_event_day_before_the_start_is_not_bought(p2_db, p2_run, tmp_path):
    """The same copy from a start before 2026-11-16 buys that event day's
    list; the frozen start does not, nor puts it in front."""

    patch = pytest.MonkeyPatch()
    no_window(patch)
    try:
        earlier = in_one_process(
            lambda: tool.run_watch(
                p2_db, "P2", tmp_path / "earlier", since=date(2026, 11, 10)
            )
        )
    finally:
        patch.undo()
    assert earlier["days"] > read_json(p2_run / "tables.json")["days"]
    tables = read_json(tmp_path / "earlier" / "tables.json")
    assert tables["first_signal"] == P2_BEFORE.isoformat()
    before = [r for r in read_csv(tmp_path / "earlier" / "picks.csv")]
    assert {r["signal_date"] for r in before} >= {P2_BEFORE.isoformat()}
    frozen = read_csv(p2_run / "picks.csv")
    assert min(r["signal_date"] for r in frozen) == P2_FIRST.isoformat()
    assert min(r["bought"] for r in read_csv(p2_run / "trades.csv")) > (
        P2_FIRST.isoformat()
    )


def test_p2_more_days_at_the_end_change_no_earlier_number(p2_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    cut = date(2027, 6, 30)
    short = edited(
        p2_db,
        tmp_path,
        "short",
        ("delete from market_bars where trading_date > ?", (cut.isoformat(),)),
        (
            "delete from fundamental_snapshots where announcement_date > ?",
            (cut.isoformat(),),
        ),
    )
    first, again, longer = tmp_path / "first", tmp_path / "again", tmp_path / "longer"
    assert p2_watch(short, first) == 0
    assert p2_watch(p2_db, again, "--cutoff", cut.isoformat()) == 0
    assert p2_watch(p2_db, longer) == 0
    assert normalized(again, copy=False) == normalized(first, copy=False)
    base = read_json(first / "tables.json")
    assert base["signal_days"] == 2 and base["next_deadline"] == "2027-08-14"
    for name in ("equity.csv", "picks.csv"):
        rows, more = read_csv(first / name), read_csv(longer / name)
        assert len(more) > len(rows) and more[: len(rows)] == rows


@pytest.mark.parametrize("cut", [date(2026, 11, 24), P2_FIRST])
def test_p2_without_an_event_day_after_the_start(p2_db, tmp_path, monkeypatch, cut):
    """樣本不足 and the next event day; a cutoff on the event day is no signal
    yet (its T+1 is not in the copy)."""

    no_window(monkeypatch)
    out = tmp_path / "out"
    assert p2_watch(p2_db, out, "--cutoff", cut.isoformat()) == 0
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


def test_p2_short_of_60_days_lists_numbers_and_no_verdict(p2_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    days = p2_days()
    cut = days[days.index(P2_FIRST) + 30]
    out = tmp_path / "out"
    assert p2_watch(p2_db, out, "--cutoff", cut.isoformat()) == 0
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


def test_p2_a_changed_source_is_refused(p2_db, tmp_path, monkeypatch, capsys):
    no_window(monkeypatch)
    changed = {**r15.HYPOTHESES, "P2": {**r15.HYPOTHESES["P2"], "top": 10}}
    monkeypatch.setattr(r15, "HYPOTHESES", changed)
    out = tmp_path / "out"
    assert p2_watch(p2_db, out) == 2
    refused = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]
    assert any("definitions_sha256" in problem for problem in refused)
    assert not out.exists()


def test_p2_loads_as_round15s_load_and_runs_its_own_engine(p2_db, p2_run, tmp_path):
    """forward_watch's context (no member table, #990 決定 7098585515) and
    ``round15_research.load`` with the table give P2 the same event days,
    ``margins_up`` lists, reference and account; the frozen run's equity and
    picks are round15_research's own on that segment."""

    p2_write_members(p2_db.parent)
    members = ms.members_path(p2_db)
    days = p2_days()
    loaded = in_one_process(
        lambda: r15.load(p2_db, members, r15.LOAD_FROM, P2_END, tmp_path / "a")
    )
    built = in_one_process(lambda: tool.round15_context(p2_db, P2_END, tmp_path / "b"))
    assert loaded.groups is not None and built.groups is None
    assert built.panel.sessions == loaded.panel.sessions == days
    assert built.statements == loaded.statements and built.statuses == loaded.statuses
    events = r14.quarter_events(days)
    assert r14.quarter_events(built.panel.sessions) == events
    spec = r15.HYPOTHESES["P2"]
    first, last = days.index(P2_FIRST) + 1, len(days) - 1
    plans = [r15.plan_p2(ctx, spec, first, last) for ctx in (loaded, built)]
    for key in ("picks", "population", "reference", "dues", "rows", "rebalances"):
        assert getattr(plans[0], key) == getattr(plans[1], key), key
    assert plans[0].reference != plans[0].population  # S31 is out of it
    mine, population, reference = r15.engines(loaded, "P2", plans[0], first, last)
    equity = read_csv(p2_run / "equity.csv")
    assert [row["date"] for row in equity] == [
        d.isoformat() for d in days[first : last + 1]
    ]
    assert [row["P2"] for row in equity] == [f"{v:.8f}" for v in mine.equity]
    assert [row["population"] for row in equity] == [
        f"{v:.8f}" for v in population.equity
    ]
    picks = read_csv(p2_run / "picks.csv")
    assert [(r["signal_date"], r["symbol"]) for r in picks] == [
        (r["signal_date"], r["symbol"]) for r in plans[0].rows
    ]
