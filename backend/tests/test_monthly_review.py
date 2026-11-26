"""tools/research/monthly_review.py: the month's review in one command (#1062).

The entries run as their own commands (``subprocess_runner``); here they run
in this process (``in_process``, each tool's own ``main``) so the daily window
can be held off, on forward_watch's synthetic copy (``test_forward_watch.build``,
sessions from 2025-10-01 past the frozen starts).  The lists are fed made-up
``review.json`` parts: their rules are docs/spec/evidence.md 每月檢討.
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_forward_watch as fwt  # noqa: E402

lib = fwt.lib
pr = fwt.pr
fw = fwt.tool
mr = fwt._tool("monthly_review")
fe = sys.modules["feature_evidence"]

MONTH = "2026-12"
CUTOFF = date(2026, 12, 31)
APP_PATHS = fwt.APP_PATHS


def in_process(tool: str, argv: list[str]) -> tuple[int, str, str]:
    """The entry's own ``main`` here, with the environment put back after it
    (research_report.load_actions points app.config at the copy)."""

    saved = {key: os.environ.get(key) for key in APP_PATHS}
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = lib._load(tool).main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return code, out.getvalue(), err.getvalue()


def review_argv(db: Path, out: Path, *extra: str) -> list[str]:
    return [
        "--db",
        str(db),
        "--month",
        MONTH,
        "--out",
        str(out),
        "--min-free-gb",
        "0",
        *extra,
    ]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def copy_db(tmp_path_factory) -> Path:
    return fwt.build(tmp_path_factory.mktemp("review") / "stock.db")


@pytest.fixture(scope="module")
def review_run(copy_db, tmp_path_factory):
    out = tmp_path_factory.mktemp("run") / "out"
    patch = pytest.MonkeyPatch()
    fwt.no_window(patch)
    try:
        code = mr.main(review_argv(copy_db, out), runner=in_process)
    finally:
        patch.undo()
    return code, out


# --- one command, every entry --------------------------------------------------


def test_the_cutoff_is_the_months_last_session(copy_db):
    assert mr.month_cutoff(copy_db, MONTH) == CUTOFF
    assert mr.month_cutoff(copy_db, "2026-11") == date(2026, 11, 30)
    assert mr.month_cutoff(copy_db, "2020-01") is None


def test_every_entry_runs_in_order(copy_db, tmp_path):
    names = [step["name"] for step in mr.steps(copy_db, tmp_path, CUTOFF, 0)]
    assert names == [
        "H1",
        *fw.WATCHES,
        "candidate_scorecard",
        "feature_evidence",
        "premarket_score_report",
    ]


def test_the_review_runs_every_entry(review_run):
    code, out = review_run
    review = read_json(out / "review.json")
    assert review["failed"] == [], review["steps"]
    assert code == 0
    assert set(review["steps"]) == {
        "H1",
        *fw.WATCHES,
        "candidate_scorecard",
        "feature_evidence",
        "premarket_score_report",
    }
    for name in ("H1", *fw.WATCHES, "candidate_scorecard", "feature_evidence"):
        assert (out / name / "tables.json").is_file(), name
        assert (out / name / "summary.md").is_file(), name
    assert (out / "premarket_score_report" / "report.md").is_file()
    assert review["cutoff"] == CUTOFF.isoformat()
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith(f"# 每月檢討 {MONTH}")
    assert summary.index("## 變差") < summary.index("## 變強") < summary.index("## H1")


# what changes from one run to the next, whoever runs it
VOLATILE = ("command", "tool_commit", "elapsed_seconds", "peak_memory_gb")


def normalized(path: Path) -> dict:
    tables = read_json(path)
    for key in VOLATILE:
        tables.pop(key, None)
    if "copy" in tables:
        tables["copy"].pop("mtime", None)
    return tables


@pytest.mark.parametrize(
    "name", ["H1", *fw.WATCHES, "candidate_scorecard", "feature_evidence"]
)
def test_each_entrys_output_is_the_one_it_writes_alone(
    review_run, copy_db, tmp_path, monkeypatch, name
):
    _code, out = review_run
    step = next(s for s in mr.steps(copy_db, tmp_path, CUTOFF, 0) if s["name"] == name)
    fwt.no_window(monkeypatch)
    code, _stdout, stderr = in_process(step["tool"], step["argv"])
    assert code == 0, stderr
    assert normalized(tmp_path / name / "tables.json") == normalized(
        out / name / "tables.json"
    )


def test_the_premarket_report_is_the_clis_on_the_copy(review_run, copy_db, monkeypatch):
    _code, out = review_run
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from worker import pipeline, premarket_score_report

    engine = create_engine(f"sqlite:///{copy_db}")
    monkeypatch.setattr(pipeline, "SessionLocal", sessionmaker(bind=engine))
    try:
        alone = premarket_score_report.run(MONTH)
    finally:
        engine.dispose()
    assert (out / "premarket_score_report" / "report.md").read_text(
        encoding="utf-8"
    ) == alone + "\n"


def test_a_row_added_to_watches_runs(copy_db, tmp_path, monkeypatch):
    monkeypatch.setitem(fw.WATCHES, "X4-later", dict(fw.WATCHES["X4"]))
    ran = []

    def runner(tool, argv):
        ran.append((tool, argv[argv.index("--out") + 1]))
        return 1, json.dumps({"refused": ["test"]}), ""

    mr.run_review(
        copy_db,
        MONTH,
        tmp_path / "out",
        CUTOFF,
        runner=runner,
        premarket=lambda db, month: "",
    )
    assert ("forward_watch", str(tmp_path / "out" / "X4-later")) in ran


def test_one_failing_entry_leaves_the_others_running(copy_db, tmp_path, monkeypatch):
    fwt.no_window(monkeypatch)

    def runner(tool, argv):
        if "--watch" in argv and argv[argv.index("--watch") + 1] == "H2":
            return 2, json.dumps({"refused": ["H2 broke"]}), ""
        if tool == "feature_evidence":
            raise RuntimeError("feature crash")
        return in_process(tool, argv)

    out = tmp_path / "out"
    code = mr.main(review_argv(copy_db, out), runner=runner)
    assert code == 1
    review = read_json(out / "review.json")
    assert review["failed"] == ["H2", "feature_evidence"]
    assert review["steps"]["H2"]["reason"] == "拒絕：H2 broke"
    assert (
        "RuntimeError: feature crash" in review["steps"]["feature_evidence"]["reason"]
    )
    for name in review["steps"]:
        if name not in review["failed"]:
            assert review["steps"][name]["status"] == "ok", name
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "- **失敗**：拒絕：H2 broke" in summary


def test_a_failing_premarket_report_is_its_section_only(copy_db, tmp_path):
    def runner(tool, argv):
        return 1, json.dumps({"refused": ["off"]}), ""

    def broken(db, month):
        raise ValueError("no table")

    review = mr.run_review(
        copy_db, MONTH, tmp_path / "out", CUTOFF, runner=runner, premarket=broken
    )
    assert review["steps"]["premarket_score_report"]["reason"] == "ValueError: no table"


# --- refused before any entry runs -----------------------------------------------


def never(tool, argv):
    raise AssertionError("no entry runs when the review is refused")


def test_the_review_refuses_production(copy_db, tmp_path, monkeypatch, capsys):
    fwt.no_window(monkeypatch)
    monkeypatch.setenv("STOCK_DATA_DIR", str(copy_db.parent))
    out = tmp_path / "out"
    assert mr.main(review_argv(copy_db, out), runner=never) == 2
    assert "refused" in capsys.readouterr().out
    assert not out.exists()


def test_the_review_refuses_the_daily_window(copy_db, tmp_path, monkeypatch, capsys):
    research = lib._load("backtest_research")
    monkeypatch.setattr(
        research, "daily_window_problem", lambda now: "Taipei time 22:00 is inside"
    )
    out = tmp_path / "out"
    assert mr.main(review_argv(copy_db, out), runner=never) == 2
    assert "22:00" in capsys.readouterr().out
    assert not out.exists()


def test_the_review_refuses_too_little_memory(copy_db, tmp_path, monkeypatch, capsys):
    fwt.no_window(monkeypatch)
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "free_memory_gb", lambda *args: 0.5)
    out = tmp_path / "out"
    argv = review_argv(copy_db, out)
    argv[argv.index("--min-free-gb") + 1] = "2"
    assert mr.main(argv, runner=never) == 2
    assert "--min-free-gb 2" in capsys.readouterr().out
    assert not out.exists()


def test_the_review_refuses_a_month_the_copy_lacks(
    copy_db, tmp_path, monkeypatch, capsys
):
    fwt.no_window(monkeypatch)
    out = tmp_path / "out"
    argv = review_argv(copy_db, out)
    argv[argv.index("--month") + 1] = "2020-01"
    assert mr.main(argv, runner=never) == 2
    assert "2020-01" in capsys.readouterr().out


def test_the_review_refuses_a_previous_without_review_json(
    copy_db, tmp_path, monkeypatch, capsys
):
    fwt.no_window(monkeypatch)
    (tmp_path / "last").mkdir()
    argv = review_argv(copy_db, tmp_path / "out", "--previous", str(tmp_path / "last"))
    assert mr.main(argv, runner=never) == 2
    assert "review.json" in capsys.readouterr().out


def test_the_review_refuses_a_previous_of_another_format(
    copy_db, tmp_path, monkeypatch, capsys
):
    fwt.no_window(monkeypatch)
    (tmp_path / "last").mkdir()
    (tmp_path / "last" / "review.json").write_text(
        json.dumps({"format": 0, "month": "2026-11"}), encoding="utf-8"
    )
    argv = review_argv(copy_db, tmp_path / "out", "--previous", str(tmp_path / "last"))
    assert mr.main(argv, runner=never) == 2
    assert "格式版本" in capsys.readouterr().out
