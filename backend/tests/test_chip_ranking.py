"""Research chip rankings (#598): K1～K3 order a fixed pool as defined; the tool writes nothing."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE, CANDIDATE_SCORE_V7
from app.models import CandidateRun, DailyCandidate, MarketBar
from app.strategies import chip_ranking as cr
from app.strategies.aggressive import BASES
from worker import candidates

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load("ranking_research")


def test_the_weights_are_the_issues():
    assert (
        cr.SCORE_CONFIG is CANDIDATE_SCORE_V7 and CANDIDATE_SCORE is CANDIDATE_SCORE_V7
    )
    assert cr.V7_WEIGHTS == {
        "technical": 0.35,
        "chips": 0.30,
        "group": 0.20,
        "news_sentiment": 0.15,
    }
    k1 = cr.K1_WEIGHTS
    assert k1["chips"] == 0.50
    assert sum(k1.values()) == pytest.approx(1.0)
    # The other three shrink by one factor, 0.50／0.70.
    for key in ("technical", "group", "news_sentiment"):
        assert k1[key] == pytest.approx(cr.V7_WEIGHTS[key] * 0.5 / 0.7)
    assert k1["technical"] == pytest.approx(0.25)
    assert cr.RANKINGS["k2"].weights == k1
    assert cr.RANKINGS["k3"].weights == cr.V7_WEIGHTS
    assert list(cr.RANKINGS) == ["v7", "k1", "k2", "k3"]


@pytest.mark.parametrize(
    ("days", "margin", "expected"),
    [
        (5, -0.01, 1.0),
        (5, 0.0, 0.5),
        (0, -0.2, 0.5),
        (3, 0.1, 0.3),
        (2, -0.01, 0.7),
        (None, -0.01, None),
        (3, None, None),
    ],
)
def test_k2_chips_is_half_buy_sessions_half_margin_decrease(days, margin, expected):
    value = cr.k2_chips(days, margin)
    assert value == (None if expected is None else pytest.approx(expected))


def test_k2_refuses_more_than_five_sessions():
    with pytest.raises(ValueError):
        cr.k2_chips(6, 0.0)


def _entry(
    signal_id,
    *,
    technical,
    chips,
    group,
    news,
    flow=0.1,
    margin=-0.01,
    days=3,
    instrument=None,
    strategy="breakout_v3",
    symbol=None,
):
    return cr.Entry(
        signal_id=signal_id,
        instrument_id=instrument or signal_id,
        exchange="TWSE",
        symbol=symbol or f"{1000 + signal_id}",
        strategy=strategy,
        scores={
            "technical": technical,
            "chips": chips,
            "group": group,
            "news_sentiment": news,
        },
        institutional_flow_5d=flow,
        margin_change_5d=margin,
        positive_flow_sessions_5d=days,
    )


# One pool, built so each ranking puts it in a different order.
POOL = [
    # A: strong technical, weak chips.
    _entry(
        1,
        technical=0.95,
        chips=0.10,
        group=0.80,
        news=0.50,
        flow=-0.2,
        margin=0.03,
        days=1,
    ),
    # B: weak technical, strong chips; margin decreasing, buying every day.
    _entry(
        2,
        technical=0.40,
        chips=0.95,
        group=0.50,
        news=0.50,
        flow=0.3,
        margin=-0.05,
        days=5,
    ),
    # C: middle everywhere; flow positive but margin up.
    _entry(
        3,
        technical=0.70,
        chips=0.60,
        group=0.60,
        news=0.50,
        flow=0.1,
        margin=0.01,
        days=4,
    ),
    # D: good chips percentiles but no margin data (non-margin security).
    _entry(
        4,
        technical=0.60,
        chips=0.85,
        group=0.40,
        news=None,
        flow=0.2,
        margin=None,
        days=5,
    ),
    # E: no technical score: never eligible (required component).
    _entry(5, technical=None, chips=0.99, group=0.99, news=0.99),
    # F: only technical: under the 0.65 coverage floor.
    _entry(
        6, technical=0.99, chips=None, group=None, news=None, margin=None, days=None
    ),
]


def _order(code):
    return [item.entry.signal_id for item in cr.rank(POOL, code)]


def test_each_ranking_orders_one_pool_as_defined():
    # v7: D 0.6412 (renormalized without news), C 0.6200, B 0.6000, A 0.5975.
    assert _order("v7") == [4, 3, 2, 1]
    # K1 raises chips: D 0.7080, B 0.7000, C 0.6143, A 0.4554; B passes C.
    assert _order("k1") == [4, 2, 3, 1]
    # K2 replaces chips: B (5/5 days, margin down) 1.0, C 0.4, A 0.1.  D has no
    # margin change, so its chips are null; without news too, it covers
    # 0.39 of the weight, under the 0.65 floor, and drops out.
    assert _order("k2") == [2, 3, 1]
    # K3 keeps flow > 0 and margin ≤ 0 only: B alone (D has no margin data).
    assert _order("k3") == [2]


def test_the_totals_are_v7s_formula():
    totals = {item.entry.signal_id: item.total for item in cr.rank(POOL, "v7")}
    assert totals[1] == pytest.approx(
        0.35 * 0.95 + 0.30 * 0.10 + 0.20 * 0.80 + 0.15 * 0.50
    )
    assert totals[4] == pytest.approx((0.35 * 0.60 + 0.30 * 0.85 + 0.20 * 0.40) / 0.85)
    k2 = {item.entry.signal_id: item.scores["chips"] for item in cr.rank(POOL, "k2")}
    assert k2 == {1: pytest.approx(0.1), 2: 1.0, 3: pytest.approx(0.4)}
    k1 = {item.entry.signal_id: item.total for item in cr.rank(POOL, "k1")}
    w = cr.K1_WEIGHTS
    assert k1[2] == pytest.approx(
        w["technical"] * 0.40
        + w["chips"] * 0.95
        + w["group"] * 0.50
        + w["news_sentiment"] * 0.50
    )
    assert k1[2] == pytest.approx(0.70)


def test_one_row_per_instrument_and_the_tie_break():
    same = [
        _entry(
            10,
            technical=0.5,
            chips=0.5,
            group=0.5,
            news=0.5,
            instrument=7,
            strategy="pullback_v4",
        ),
        _entry(11, technical=0.5, chips=0.5, group=0.5, news=0.5, instrument=7),
        _entry(12, technical=0.6, chips=0.4, group=0.5, news=0.5, symbol="0050"),
        _entry(13, technical=0.6, chips=0.4, group=0.5, news=0.5, symbol="0040"),
    ]
    # Equal totals on one instrument: the pool's strategy order (breakout first).
    # Equal totals and technical: chips, then exchange and symbol.
    assert [item.entry.signal_id for item in cr.rank(same, "v7")] == [13, 12, 11]


def test_overlap_counts_the_first_slots_only():
    assert cr.overlap([1, 2, 3], [3, 4, 1], size=3) == pytest.approx(2 / 3)
    assert cr.overlap(list(range(12)), list(range(10)) + [20, 21]) == 1.0
    assert cr.overlap([], [1, 2]) == 0.0
    assert cr.overlap([], []) == 0.0


def test_overlap_divides_by_the_larger_short_top():
    # A day with fewer than TOP_N actionable stocks: v7 against itself is 100%.
    assert cr.overlap([1, 2, 3], [1, 2, 3]) == 1.0
    # A filtered ranking (K3) with a shorter top: shared ÷ v7's size.
    assert cr.overlap([2], [1, 2, 3]) == pytest.approx(1 / 3)
    assert cr.overlap([1, 2, 3, 4], [1, 2]) == pytest.approx(2 / 4)


def test_the_proposal_rule():
    def item(**changes):
        values = dict(
            replaced=cr.MIN_REPLACED,
            t20_n=cr.MIN_T20,
            t20_median=-0.01,
            baseline_t20_median=-0.02,
            invalidated_share=0.40,
            baseline_invalidated_share=0.45,
        )
        values.update(changes)
        return cr.Comparison(**values)

    assert cr.proposable(item(), item())
    tie = item(t20_median=-0.02)
    assert cr.judge_exploration(tie) == "not_selected"
    assert cr.judge_validation(tie) == "not_reversed"
    assert cr.judge_validation(item(invalidated_share=0.5)) == "reversed"
    for thin in (item(replaced=cr.MIN_REPLACED - 1), item(t20_n=cr.MIN_T20 - 1)):
        assert cr.judge_exploration(thin) == cr.judge_validation(thin) == "insufficient"


# ---- the tool on the verify fixture database ----


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    dest = tmp_path_factory.mktemp("chip-ranking")
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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_tools_v7_order_is_what_compute_daily_candidates_writes(
    fixture_db, tmp_path
):
    path = tmp_path / "stock.db"
    shutil.copyfile(fixture_db, path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        days = db.scalars(
            select(CandidateRun.trading_date).where(
                CandidateRun.score_version == "candidate_score_v7"
            )
        ).all()
        assert days
        # Recompute every v7 run with the function the pages read, under
        # another name so it writes a fresh run next to the fixture's.
        config = json.loads(json.dumps(CANDIDATE_SCORE_V7))
        config["name"] = "candidate_score_v7_check"
        written = {}
        for day in days:
            result = candidates.compute_daily_candidates(db, day, config=config)
            assert not result["already_complete"]
            written[day] = db.scalars(
                select(DailyCandidate.signal_id)
                .where(
                    DailyCandidate.trading_date == day,
                    DailyCandidate.score_version == config["name"],
                )
                .order_by(DailyCandidate.rank)
            ).all()
            stored = db.scalars(
                select(DailyCandidate.signal_id)
                .where(
                    DailyCandidate.trading_date == day,
                    DailyCandidate.score_version == "candidate_score_v7",
                )
                .order_by(DailyCandidate.rank)
            ).all()
            assert written[day] == stored
    engine.dispose()
    assert any(written.values())

    before = _digest(path)
    ro_engine, ro_factory = tool.read_only_session_factory(path)
    try:
        for day in days:
            with ro_factory() as db:
                entries, selected, info = tool.day_entries(db, day, "analysis")
                ranked = tool.rank_day(entries, selected, cr.TOP_N)
            assert selected == written[day]
            assert ranked["v7_matches_score_pool"]
            assert ranked["tops"]["v7"] == written[day][: cr.TOP_N]
            assert info["pool"] == len(entries) >= len(written[day])
            assert {entry.strategy for entry in entries} <= set(BASES)
            # K3 keeps only the entries with positive flow and no margin increase.
            kept = [e.signal_id for e in entries if cr.passes_flow_and_margin(e)]
            assert set(ranked["tops"]["k3"]) <= set(kept)
            assert len(entries) - len(kept) == ranked["k3_filtered"]
            with ro_factory() as db, pytest.raises(Exception, match="readonly"):
                db.execute(delete(CandidateRun))
                db.flush()
    finally:
        ro_engine.dispose()
    assert _digest(path) == before


def test_the_tool_ranks_a_research_run_and_writes_nothing(
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
    run = pipeline.backtest(days[-20], days[-1], registry=dict(BASES))["run"]
    assert run["status"] == "success"
    engine.dispose()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        candidate_rows = connection.execute(
            "select count(*) from daily_candidates"
        ).fetchone()

    before = _digest(path)
    out = tmp_path / "out"
    argv = ["--db", str(path), "--run-id", str(run["id"]), "--out", str(out)]
    assert tool.main(argv) == 0
    assert _digest(path) == before
    with closing(sqlite3.connect(path)) as connection:
        assert (
            connection.execute("select count(*) from daily_candidates").fetchone()
            == candidate_rows
        )
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["run"]["id"] == run["id"]
    assert tables["v7_mismatch_dates"] == []
    assert tables["ranked_dates"]["count"] == 20
    assert set(tables["rankings"]) == {"v7", "k1", "k2", "k3"}
    whole = tables["rankings"]["v7"]["scopes"]["all"]
    assert whole["slots"] == sum(
        tables["rankings"]["v7"]["scopes"][q]["slots"] for q in tables["quarters"]
    )
    assert tables["rankings"]["v7"]["scopes"]["all"]["replaced"] == 0
    v7_overlap = tables["rankings"]["v7"]["scopes"]["all"]["overlap"]
    if v7_overlap["days"]:
        # Short tops (fewer than TOP_N actionable) still overlap v7 fully.
        assert v7_overlap["mean"] == 1.0
        assert all(
            key.split("/")[0] == key.split("/")[1] for key in v7_overlap["histogram"]
        )
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert run["request_key"] in summary and "段別判定" in summary
    header = (out / "rankings.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("trading_date,ranking,rank,signal_id")
    assert date.fromisoformat(tables["ranked_dates"]["last"]) == days[-1]


def test_the_tool_refuses_the_production_database(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    argv = ["--db", str(production), "--run-id", "1", "--out", str(tmp_path / "o")]
    assert tool.main(argv) == 2
    assert not (tmp_path / "o").exists()
