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


# --- the lists (docs/spec/evidence.md 每月檢討) ---------------------------------


def forward_fact(code: str, kind: str, days: int, mean: float, t: float) -> dict:
    excess = {"days": days, "mean": mean, "t": t}
    return {
        "code": code,
        "kind": kind,
        "note": fw.KIND_NOTES.get(kind, "只當紀錄，不改 H1 成立與否"),
        # the verdict the entry itself writes (forward_judge, M = 60)
        "verdict": pr.forward_judge(excess, 60),
        "days": days,
        "min_days": 60,
        "excess": {"taiex": excess, "population": excess},
    }


def verdicts(features: dict | None = None, conditions: dict | None = None) -> dict:
    return {
        "version": fe.VERSION,
        "range": ["2024-09-30", "2026-11-30"],
        "verdicts": {
            "features": features or {},
            "conditions": conditions or {},
        },
    }


def made_review(**parts) -> dict:
    review = {
        "forward": {},
        "failed": [],
        "scorecard": {"range": [None, None], "candidates": 0, "horizons": {}},
        "features": verdicts(),
    }
    review.update(parts)
    return review


def names(items: list[dict], kind: str | None = None) -> list[str]:
    return [item["name"] for item in items if kind is None or item["kind"] == kind]


def test_a_forward_object_losing_is_listed_from_60_sessions_only():
    review = made_review(
        forward={
            "X4": forward_fact("X4", fw.WATCH, 59, -0.01, -3.0),
            "H2-product": forward_fact("H2", fw.PRODUCT, 60, -0.01, -3.0),
            "H2": forward_fact("H2", fw.PASSED, 80, -0.01, -1.5),
        }
    )
    assert review["forward"]["X4"]["verdict"] == "樣本不足"
    items = mr.worse(review, None)
    assert names(items, "forward") == ["H2-product"]
    (item,) = [i for i in items if i["kind"] == "forward"]
    assert item["action"] == fw.KIND_NOTES[fw.PRODUCT]
    assert "輸給基準" in item["text"]


def test_h1_losing_is_a_record_only():
    fact = forward_fact("H1", "H1 前瞻", 250, -0.01, -2.5)
    fact["note"] = "只當紀錄，不改 H1 成立與否"
    items = mr.worse(made_review(forward={"H1": fact}), None)
    assert names(items, "forward") == ["H1"]
    assert items[0]["action"].startswith("只當紀錄")


def test_a_forward_object_passing_is_listed_stronger_as_a_record():
    review = made_review(
        forward={
            "F2": forward_fact("F2", fw.WATCH, 60, 0.01, 2.5),
            "P2": forward_fact("P2", fw.WATCH, 59, 0.01, 2.5),
        }
    )
    items = mr.better(review, None, {})
    assert names(items, "forward") == ["F2"]
    assert items[0]["action"] == "只當紀錄；" + fw.KIND_NOTES[fw.WATCH]
    assert names(mr.worse(review, None), "forward") == []


def test_the_scorecard_losing_is_listed_from_60_days():
    daily = {"days": 59, "mean": -0.01, "t": -3.0}
    assert mr.scorecard_verdict(daily) == "樣本不足"
    assert mr.scorecard_verdict({**daily, "days": 60}) == "輸給基準"
    assert mr.scorecard_verdict({"days": 0, "mean": None, "t": None}) == "樣本不足"
    card = {
        "range": ["2026-10-01", "2026-11-30"],
        "candidates": 100,
        "horizons": {
            "5": {"verdict": "輸給基準", "mean": -0.01, "t": -3.0, "days": 60},
            "20": {"verdict": "樣本不足", "mean": -0.01, "t": -3.0, "days": 40},
        },
    }
    items = mr.worse(made_review(scorecard=card), None)
    assert names(items, "scorecard") == ["candidate_scorecard:T+5"]
    assert items[0]["action"] == mr.SCORECARD_NOTE


def test_the_product_features_come_from_the_product_rows():
    assert mr.product_features() == {
        "high_gap_240": ["H2-product"],
        "revenue_yoy": ["X4-product"],
        "eps_growth_yield": ["X4-product"],
    }
    assert mr.product_unmatched() == {"X4-product": ["eps_yield_raw"]}


def test_the_rank_order():
    order = sorted(mr.RANKS, key=mr.RANKS.get, reverse=True)
    assert order == ["evidence", "weak", "not_selected", "reversed"]
    assert set(mr.RANKS) | {mr.UNRANKED} == set(fe.VERDICTS)


def test_a_downgrade_of_a_live_condition_or_a_product_feature_is_worse():
    previous = {
        "features": verdicts(
            features={
                "high_gap_240": {"5": "evidence", "20": "weak"},
                "momentum_20": {"5": "evidence", "20": "evidence"},
                "revenue_yoy": {"5": "cannot_tell", "20": "weak"},
            },
            conditions={
                "breakout_rule": {"5": "weak", "20": "weak"},
                "margin_ok": {"5": "weak", "20": "not_selected"},
            },
        )
    }
    current = verdicts(
        features={
            "high_gap_240": {"5": "weak", "20": "weak"},
            "momentum_20": {"5": "reversed", "20": "evidence"},
            "revenue_yoy": {"5": "not_selected", "20": "cannot_tell"},
        },
        conditions={
            "breakout_rule": {"5": "weak", "20": "reversed"},
            "margin_ok": {"5": "evidence", "20": "not_selected"},
        },
    )
    items = mr.worse(made_review(features=current), previous)
    # momentum_20 is no product feature: a downgrade there is not listed;
    # to or from 無法判定 is neither up nor down
    assert names(items) == ["breakout_rule:T+20", "high_gap_240:T+5"]
    assert "方向一致但不顯著 → 驗證段反轉" in items[0]["text"]
    assert "H2-product" in items[1]["text"]
    changes = mr.feature_changes(current, previous)
    unranked = [row for row in changes if row["direction"] == "不排序"]
    assert {(row["key"], row["horizon"]) for row in unranked} == {
        ("revenue_yoy", "5"),
        ("revenue_yoy", "20"),
    }


def test_an_upgraded_unused_feature_is_stronger():
    previous = {
        "features": verdicts(
            features={
                "short_change_5": {"5": "not_selected", "20": "weak"},
                "day_trade_ratio": {"5": "weak", "20": "reversed"},
                "trust_buy_days_5": {"5": "not_selected", "20": "not_selected"},
                "volume_ratio": {"5": "cannot_tell", "20": "not_selected"},
            }
        )
    }
    current = verdicts(
        features={
            "short_change_5": {"5": "weak", "20": "evidence"},
            # reversed → not_selected is up, but under 方向一致但不顯著
            "day_trade_ratio": {"5": "weak", "20": "not_selected"},
            # used by H1
            "trust_buy_days_5": {"5": "evidence", "20": "not_selected"},
            # from 無法判定: no rank
            "volume_ratio": {"5": "evidence", "20": "not_selected"},
        },
        # a condition is in the rules already: never stronger
        conditions={"margin_ok": {"5": "evidence"}},
    )
    used = {"trust_buy_days_5": ["portfolio_research:H1"]}
    items = mr.better(made_review(features=current), previous, used)
    assert names(items) == ["short_change_5:T+20", "short_change_5:T+5"]
    assert "沒有證據 → 方向一致但不顯著" in items[1]["text"]


def test_the_used_features_are_read_from_the_registered_definitions(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps({"entries": [{"hypothesis": "X1", "round": 1}]}), encoding="utf-8"
    )
    used = mr.registered_features(ledger)
    assert "explore_research:X1" in used["momentum_120"]
    assert "portfolio_research:H1" in used["trust_buy_days_5"]
    assert "forward_watch:H2" in used["high_gap_240"]
    real = mr.registered_features()
    assert "explore_research:X2" in real["high_gap_240"]


def test_without_a_previous_month_no_feature_is_compared():
    current = verdicts(features={"short_change_5": {"5": "evidence"}})
    review = made_review(
        features=current, forward={"X4": forward_fact("X4", fw.WATCH, 60, -0.01, -3)}
    )
    worse, better = mr.worse(review, None), mr.better(review, None, {})
    assert names(worse) == ["X4", "feature_evidence"]
    assert names(better) == ["feature_evidence"]
    assert "沒有上個月可比（沒有 --previous），不列" in worse[-1]["text"]
    assert "沒有上個月可比" in better[-1]["text"]
    assert mr.feature_changes(current, None) == []


def test_a_key_last_month_lacked_is_not_compared():
    previous = {"features": verdicts(features={"short_change_5": {"5": "weak"}})}
    current = verdicts(
        features={"short_change_5": {"5": "weak", "20": "evidence"}},
        conditions={"breakout_rule": {"5": "reversed"}},
    )
    review = made_review(features=current)
    assert mr.better(review, previous, {}) == []
    assert mr.worse(review, previous) == []


def test_another_feature_evidence_version_is_not_compared():
    previous = {"features": {**verdicts(), "version": fe.VERSION - 1}}
    items = mr.worse(made_review(), previous)
    assert names(items) == ["feature_evidence"]
    assert "判定規則改版" in items[0]["text"]
    previous = {"features": None}
    assert (
        "上個月 feature_evidence 失敗" in mr.worse(made_review(), previous)[0]["text"]
    )


def test_a_failed_entry_is_listed_as_not_judged():
    review = made_review(failed=["H2", "candidate_scorecard"], scorecard=None)
    items = mr.worse(review, None)
    assert names(items, "failed") == ["H2", "candidate_scorecard"]
    assert items[0]["text"] == "H2 失敗，未判"


def test_the_previous_review_feeds_the_next_month(
    review_run, copy_db, tmp_path, monkeypatch
):
    _code, last = review_run
    previous = read_json(last / "review.json")
    assert previous["format"] == mr.REVIEW_FORMAT
    fwt.no_window(monkeypatch)

    def runner(tool, argv):
        if tool == "feature_evidence":
            target = Path(argv[argv.index("--out") + 1])
            target.mkdir(parents=True)
            tables = read_json(last / "feature_evidence" / "tables.json")
            part = tables["horizons"]["20"]["conditions"]["breakout_rule"]
            part["verdict"] = (
                "reversed" if part["verdict"] != "reversed" else "evidence"
            )
            (target / "tables.json").write_text(json.dumps(tables), encoding="utf-8")
            return 0, "", ""
        return 1, json.dumps({"refused": ["skipped here"]}), ""

    previous["month"] = "2026-11"
    folder = tmp_path / "last"
    folder.mkdir()
    (folder / "review.json").write_text(json.dumps(previous), encoding="utf-8")
    out = tmp_path / "out"
    argv = review_argv(copy_db, out, "--previous", str(folder))
    assert mr.main(argv, runner=runner, premarket=lambda db, month: "") == 1
    review = read_json(out / "review.json")
    assert review["previous"]["month"] == "2026-11"
    assert [row["key"] for row in review["feature_changes"]] == ["breakout_rule"]
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "### 判定有變（和上個月比）" in summary


def test_a_copy_without_the_premarket_tables_says_so(copy_db, tmp_path):
    import sqlite3
    import shutil

    older = tmp_path / "older.db"
    shutil.copy(copy_db, older)
    con = sqlite3.connect(older)
    con.execute("drop table premarket_ai_readings")
    con.commit()
    con.close()
    status = mr.run_premarket(older, MONTH, tmp_path / "out", mr.premarket_text)
    assert status["status"] == "failed"
    assert status["reason"].startswith("副本沒有 `premarket_ai_readings` 表")
