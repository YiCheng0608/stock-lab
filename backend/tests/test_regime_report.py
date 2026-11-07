"""tools/research/regime_report.py (#546): its arithmetic, and one report on the verify fixture."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import shutil
import subprocess
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.models import MarketBar
from app.strategies import REGISTRY
from app.strategies.regime import TaiexCloses, with_regimes

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = _load("regime_report")
research = _load("backtest_research")


def test_max_drawdown_is_the_largest_fall_from_an_earlier_peak():
    days = [date(2026, 1, 1) + timedelta(days=n) for n in range(6)]
    closes = [100.0, 120.0, 90.0, 130.0, 95.0, 125.0]
    worst = report.max_drawdown(list(zip(days, closes)))
    assert worst["peak"] == days[3] and worst["trough"] == days[4]
    assert worst["return"] == pytest.approx(95.0 / 130.0 - 1.0)
    rising = report.max_drawdown(list(zip(days, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])))
    assert rising["return"] == 0.0
    assert report.max_drawdown([]) is None


def test_segments_are_runs_of_one_state():
    days = [date(2026, 1, 1) + timedelta(days=n) for n in range(5)]
    states = dict(zip(days, ["passed", "passed", "rejected", "passed", "passed"]))
    assert report.segments(states) == [
        {"state": "passed", "start": days[0], "end": days[1], "sessions": 2},
        {"state": "rejected", "start": days[2], "end": days[2], "sessions": 1},
        {"state": "passed", "start": days[3], "end": days[4], "sessions": 2},
    ]
    assert report.quarter(date(2024, 12, 31)) == "2024Q4"
    assert report.quarter(date(2025, 1, 2)) == "2025Q1"


def test_a_return_still_not_triggered_at_t_n_is_left_out():
    settled = {
        1: {5: (True, 0.02, "active"), 20: (True, -0.01, "invalidated")},
        2: {5: (True, 0.05, "not_triggered"), 20: (False, None, "incomparable")},
        3: {5: (True, -0.03, "invalidated")},
    }
    summary = report.summarize(
        [(1, "invalidated"), (2, "incomparable"), (3, "invalidated")], settled
    )
    assert summary["actionable"] == 3
    assert summary["statuses"] == {"invalidated": 2, "incomparable": 1}
    assert summary["invalidated_share"] == pytest.approx(2 / 3)
    assert summary["returns"]["t5"]["n"] == 2
    assert summary["returns"]["t5"]["p50"] == pytest.approx(-0.005)
    assert summary["returns"]["t20"]["n"] == 1
    assert summary["returns_excluded"] == {"t5": 1, "t20": 2}
    assert report.summarize([], settled)["invalidated_share"] is None


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    dest = tmp_path_factory.mktemp("regime-report")
    result = subprocess.run(
        [sys.executable, "-B", str(ROOT / "tools" / "verify" / "fixture_db.py")]
        + ["--dest", str(dest)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    return dest / "stock.db"


def test_a_report_of_a_regime_run_matches_its_baseline_where_the_filter_holds(
    fixture_db, tmp_path, monkeypatch
):
    path = tmp_path / "stock.db"
    shutil.copyfile(fixture_db, path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    start, end = days[-45], days[-1]
    # The fixture's own TAIEX closes, as the research CLI loads them.
    with closing(sqlite3.connect(path)) as connection:
        closes = TaiexCloses(report.taiex_closes(connection))
    registry = with_regimes(dict(REGISTRY), [(key, "r2") for key in REGISTRY], closes)
    with research.score_dates(closes, pipeline):
        run = pipeline.backtest(start, end, registry=registry)["run"]
    engine.dispose()

    result = report.build(path, run["id"])
    assert result["run"]["request_key"] == run["request_key"]
    assert result["run"]["registry"] == list(registry)
    assert list(result["filters"]) == ["r2"]
    market = result["market"]
    assert market["sessions"] == 45
    assert sum(market["filters"]["r2"]["days"].values()) == 45
    for base, data in result["strategies"].items():
        assert list(data["versions"]) == [base, f"{base}_regime_r2"]
        whole = data["versions"][base]["scopes"]["all"]
        quarters = [data["versions"][base]["scopes"][q] for q in result["quarters"]]
        assert whole["rows"] == sum(item["rows"] for item in quarters)
        assert whole["actionable"] == sum(item["actionable"] for item in quarters)
        parts = data["removed"][f"{base}_regime_r2"]
        assert whole["actionable"] == sum(
            parts[state]["all"]["actionable"] for state in report.STATES
        )
        check = data["consistency"][f"{base}_regime_r2"]
        assert check["baseline_on_passed_dates"] == check["regime_actionable"]
        assert check["only_in_baseline"] == check["only_in_regime"] == 0
        assert check["status_or_settlement_differs"] == 0
    out = tmp_path / "out"
    assert (
        report.main(["--db", str(path), "--run-id", str(run["id"]), "--out", str(out)])
        == 0
    )
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert run["request_key"] in summary and "TAIEX 市況" in summary
    assert (
        json.loads((out / "tables.json").read_text(encoding="utf-8"))["run"]["id"]
        == run["id"]
    )
    assert (out / "segments.csv").read_text(encoding="utf-8").startswith("filter,state")


def test_the_report_refuses_the_production_database(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    assert (
        report.main(
            ["--db", str(production), "--run-id", "1", "--out", str(tmp_path / "o")]
        )
        == 2
    )
    assert not (tmp_path / "o").exists()
