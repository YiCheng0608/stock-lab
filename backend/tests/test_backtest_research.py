"""tools/research/backtest_research.py (#318): guards and one run on the verify fixture."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "research" / "backtest_research.py"

spec = importlib.util.spec_from_file_location("backtest_research", SCRIPT)
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def test_the_production_database_is_refused(tmp_path):
    production = tmp_path / "Stock-Lab-Data" / "stock.db"
    data_dir = tmp_path / "data"

    assert "stock-lab-data" in research.production_problem(production, {})
    assert "STOCK_DATA_DIR" in research.production_problem(
        data_dir / "stock.db", {"STOCK_DATA_DIR": str(data_dir)}
    )
    assert (
        research.production_problem(
            tmp_path / "copy" / "stock.db", {"STOCK_DATA_DIR": str(data_dir)}
        )
        is None
    )


@pytest.mark.parametrize(
    ("utc", "refused"),
    [
        ((10, 29), False),  # 18:29 Taipei
        ((10, 30), True),
        ((13, 29), True),
        ((13, 30), False),  # 21:30 Taipei
    ],
)
def test_the_daily_window_is_refused(utc, refused):
    now = datetime(2026, 10, 28, *utc, tzinfo=timezone.utc)
    assert (research.daily_window_problem(now) is not None) is refused


def test_a_hard_link_to_the_production_file_is_refused(tmp_path):
    # Stand-ins only: the real production file is never linked or opened.
    production = tmp_path / "prod" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"production")
    link = tmp_path / "other" / "hard.db"
    link.parent.mkdir()
    os.link(production, link)
    copy = tmp_path / "other" / "copy.db"
    copy.write_bytes(production.read_bytes())

    assert "same file" in research.production_problem(link, {}, [production])
    assert research.production_problem(copy, {}, [production]) is None
    # A missing production file (or --db) falls back to the path checks.
    missing = [tmp_path / "gone" / "stock.db"]
    assert research.production_problem(link, {}, missing) is None
    assert research.production_problem(tmp_path / "none.db", {}, [production]) is None
    assert research.production_files({"STOCK_DATA_DIR": "D:/data"})[1] == Path(
        "D:/data/stock.db"
    )


def test_the_window_check_follows_its_clock_and_a_pause_prints_the_rerun():
    times = iter(
        datetime(2026, 10, 28, 10, minute, tzinfo=timezone.utc) for minute in (29, 30)
    )
    check = research.window_check(lambda: next(times))

    assert check() is None and "18:30" in check()
    assert research.paused({"error": "BacktestPaused: Taipei time 18:30 ..."})
    assert not research.paused({"error": "RuntimeError: boom"})
    assert research.rerun_command(["--db", "x.db", "--force", "--ablate", "all"])[
        2:
    ] == ["--db", "x.db", "--ablate", "all"]


def test_a_refused_run_writes_nothing(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--db", str(production)]
        + ["--start", "2026-10-01", "--end", "2026-10-02", "--min-free-gb", "0"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 2
    assert "stock-lab-data" in json.loads(result.stdout)["refused"][0]
    assert production.read_bytes() == b""


def test_a_run_on_the_fixture_database_reports_each_strategy(tmp_path):
    built = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tools" / "verify" / "fixture_db.py")]
        + ["--dest", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert built.returncode == 0, built.stderr
    with closing(sqlite3.connect(tmp_path / "stock.db")) as connection:
        (end,) = connection.execute(
            "SELECT max(trading_date) FROM market_bars"
        ).fetchone()
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--db", str(tmp_path / "stock.db")]
        + ["--start", end, "--end", end, "--min-free-gb", "0"]
        + ["--ablate", "breakout_v1:volume", "pullback_v1:trend"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if research.daily_window_problem(datetime.now(timezone.utc)):
        assert result.returncode == 2 and "18:30" in result.stdout
        return
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["registry"] == [
        "breakout_v1",
        "pullback_v1",
        "breakout_v1_ablate_volume",
        "pullback_v1_ablate_trend",
    ]
    assert report["status"] == "success" and report["score_sessions"] == 1
    assert set(report["strategies"]) == set(report["registry"])
    assert len({item["signals"] for item in report["strategies"].values()}) == 1
    assert report["peak_working_set_gb"] > 0
    assert report["largest_wal_gb"] >= 0
