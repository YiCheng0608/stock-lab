"""Research ablations (#318): each removes exactly one condition; no override changes nothing."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.models import (
    IngestionRun,
    Signal,
    SignalEvaluation,
    SignalSettlement,
    StrategyVersion,
)
from app.strategies import REGISTRY, canonical_config_snapshot
from app.strategies.ablation import (
    ABLATIONS,
    ablated_strategy,
    all_ablations,
    research_registry,
)
from app.strategies.breakout_v1 import CONFIG as BREAKOUT_CONFIG
from app.strategies.pullback_v1 import CONFIG as PULLBACK_CONFIG

ROOT = Path(__file__).resolve().parents[2]

# What each ablation must stop reporting; every other reason stays.
REMOVED_REASONS = {
    ("breakout_v1", "breakout"): {"close_not_above_prior_20_day_high"},
    ("breakout_v1", "volume"): {"volume_ratio_below_1_20"},
    ("pullback_v1", "trend"): {"ma20_not_above_ma60", "close_below_ma60"},
    ("pullback_v1", "support"): {"close_outside_ma20_support_zone"},
    ("pullback_v1", "volume"): {"pullback_volume_ratio_outside_range"},
    **{
        (key, condition): {reason}
        for key in ("breakout_v1", "pullback_v1")
        for condition, reason in (
            ("group", "group_relative_strength_not_positive"),
            ("institutional", "institutional_flow_materially_adverse"),
            ("margin", "margin_financing_increase_abnormal"),
        )
    },
}

# Inputs on which every condition of both strategies fails.
ALL_FAIL = {
    "breakout_v1": dict(
        close=90.0,
        prior_highs=[100.0] * 20,
        volume=500.0,
        prior_volumes=[1000.0] * 20,
        group_excess_return_20d=-0.1,
        institutional_flow_to_turnover_ratio_5d=-0.5,
        margin_balance_change_ratio_5d=0.5,
    ),
    "pullback_v1": dict(
        bar_count=60,
        close=80.0,
        ma20=100.0,
        ma60=110.0,
        volume=5000.0,
        prior_volumes=[1000.0] * 20,
        group_excess_return_20d=-0.1,
        institutional_flow_to_turnover_ratio_5d=-0.5,
        margin_balance_change_ratio_5d=0.5,
    ),
}


def _random_arguments(key: str, rng: random.Random) -> dict:
    """Inputs around every threshold, with missing and non-finite values."""

    def pick(*values):
        return rng.choice(values)

    confirmations = dict(
        group_excess_return_20d=pick(-0.01, 0.0, 0.01, None, float("nan")),
        institutional_flow_to_turnover_ratio_5d=pick(-0.004, -0.003, 0.0, None),
        margin_balance_change_ratio_5d=pick(0.04, 0.05, 0.06, None),
    )
    volumes = pick([1000.0] * 20, [1000.0] * 19, [1000.0] * 19 + [0.0], None)
    if key == "breakout_v1":
        return dict(
            close=pick(99.0, 100.0, 101.0, 0.0, None),
            prior_highs=pick([100.0] * 20, [100.0] * 19, None),
            volume=pick(1100.0, 1200.0, 1300.0, 0.0, None),
            prior_volumes=volumes,
            **confirmations,
        )
    return dict(
        bar_count=pick(59, 60, 61, None, True),
        close=pick(96.0, 97.0, 100.0, 102.0, 103.0, 89.0),
        ma20=pick(100.0, 0.0, None),
        ma60=pick(90.0, 100.0, 101.0),
        volume=pick(500.0, 600.0, 1000.0, 1200.0, 1300.0),
        prior_volumes=volumes,
        **confirmations,
    )


@pytest.mark.parametrize(
    ("key", "config"),
    [("breakout_v1", BREAKOUT_CONFIG), ("pullback_v1", PULLBACK_CONFIG)],
)
def test_an_evaluator_without_config_is_the_evaluator_with_the_canonical_config(
    key, config
):
    rule = type(REGISTRY[key]).rule
    rng = random.Random(318)
    states = set()
    for _ in range(30000):
        arguments = _random_arguments(key, rng)
        default = rule(**arguments)
        assert rule(**arguments, config=config) == default
        states.add(default.state)
    assert states == {"passed", "rejected", "data_incomplete"}


@pytest.mark.parametrize(("key", "condition"), all_ablations())
def test_an_ablation_drops_only_its_condition_reasons(key, condition):
    base = REGISTRY[key]
    ablated = ablated_strategy(key, condition)
    arguments = ALL_FAIL[key]
    canonical = base.rule(**arguments)
    result = ablated.rule(**arguments)
    removed = REMOVED_REASONS[(key, condition)]

    assert canonical.state == result.state == "rejected"
    assert removed <= set(canonical.reasons)
    assert result.reasons == tuple(r for r in canonical.reasons if r not in removed)


@pytest.mark.parametrize(("key", "condition"), all_ablations())
def test_an_ablated_config_differs_only_by_its_removed_keys(key, condition):
    canonical = json.loads(json.dumps(REGISTRY[key].config))
    ablated = json.loads(json.dumps(ablated_strategy(key, condition).config))

    assert ablated.pop("name") == f"{key}_ablate_{condition}"
    assert ablated.pop("kind") == f"{canonical['kind']}_ablate_{condition}"
    assert ablated.pop("ablation")["removed_keys"] == [
        ".".join(path) for path in ABLATIONS[key][condition]
    ]
    for path in ABLATIONS[key][condition]:
        parent = canonical
        for part in path[:-1]:
            parent = parent[part]
        del parent[path[-1]]
    del canonical["name"], canonical["kind"]
    assert ablated == canonical
    # Required inputs are kept: an ablation drops a comparison, not a data check.
    assert ablated["data_policy"] == REGISTRY[key].config["data_policy"]


def test_ablations_leave_the_registry_and_canonical_snapshot_alone():
    before = canonical_config_snapshot()
    registry = research_registry(all_ablations())

    assert list(REGISTRY) == ["breakout_v1", "pullback_v1"]
    assert canonical_config_snapshot() == before
    assert list(registry)[:2] == list(REGISTRY)
    assert len(registry) == 2 + sum(len(item) for item in ABLATIONS.values())
    assert len({strategy.kind for strategy in registry.values()}) == len(registry)
    assert len(set(registry)) == len(registry)
    assert set(REMOVED_REASONS) == set(all_ablations())


# ---- backtest on the verify fixture database ----


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    dest = tmp_path_factory.mktemp("ablation")
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


@pytest.fixture
def use_copy(fixture_db, tmp_path, monkeypatch):
    """Point the pipeline at a fresh copy of the fixture; returns its session factory."""

    engines = []

    def use(name: str = "stock.db"):
        path = tmp_path / name
        shutil.copyfile(fixture_db, path)
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        enable_sqlite_foreign_keys(engine)
        engines.append(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        monkeypatch.setattr(pipeline, "SessionLocal", factory)
        return factory

    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield use
    for engine in engines:
        engine.dispose()


@pytest.fixture
def backtest_db(use_copy):
    return use_copy()


@pytest.fixture
def varied_inputs(monkeypatch):
    """Vary flow, margin and MA60 by instrument and date.

    The fixture's chips and prices never fail the institutional, margin or
    trend conditions; both runs of a test see the same varied inputs.
    """

    original = pipeline._signal_context

    def varied(db, *, instrument, signal_date, capture=None):
        context = original(
            db, instrument=instrument, signal_date=signal_date, capture=capture
        )
        if context is None:
            return None
        seed = instrument.id * 7 + signal_date.toordinal()
        inputs = context.inputs
        ma60 = inputs.ma60
        return dataclasses.replace(
            context,
            inputs=dataclasses.replace(
                inputs,
                institutional_flow_ratio_5d=(0.01, -0.01, 0.0)[seed % 3],
                margin_change_ratio_5d=(0.0, 0.02, 0.1)[seed // 3 % 3],
                ma60=ma60 * (1.0, 1.0, 1.5)[seed // 9 % 3] if ma60 else ma60,
            ),
        )

    monkeypatch.setattr(pipeline, "_signal_context", varied)


def _window(factory, sessions: int = 45) -> tuple:
    from app.models import MarketBar

    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    return days[-sessions], days[-1]


def _columns(item) -> tuple:
    return tuple(
        (column.name, json.dumps(getattr(item, column.name), default=str))
        for column in item.__table__.columns
        if column.name not in {"id", "signal_id", "created_at", "updated_at"}
    )


def _rows(factory, run_id: int) -> dict[tuple, dict]:
    """Each signal of a run by (strategy, instrument, date), with its settlements."""

    prefix = f"backtest-{run_id}-"
    with factory() as db:
        names = {row.id: row.name for row in db.scalars(select(StrategyVersion))}
        rows = {}
        for signal in db.scalars(
            select(Signal).where(Signal.signal_key.like(prefix + "%"))
        ):
            settlements = sorted(
                (s.horizon, s.final_status, s.return_or_risk, s.comparable)
                for s in db.scalars(
                    select(SignalSettlement).where(
                        SignalSettlement.signal_id == signal.id
                    )
                )
            )
            evaluations = sorted(
                _columns(item)
                for item in db.scalars(
                    select(SignalEvaluation).where(
                        SignalEvaluation.signal_id == signal.id
                    )
                )
            )
            rows[
                (
                    names[signal.strategy_version_id],
                    signal.instrument_id,
                    signal.signal_date,
                )
            ] = {
                "status": signal.status,
                "levels": (
                    signal.reference_entry,
                    signal.breakout_price,
                    signal.pullback_low,
                    signal.pullback_high,
                    signal.invalid_price,
                    signal.target_1,
                    signal.target_2,
                ),
                "evidence": signal.rule_evidence_json,
                "rationale": signal.rationale,
                "settlements": settlements,
                "evaluations": evaluations,
            }
    return rows


def _canonical_view(row: dict) -> dict:
    """A row without the states of strategies outside REGISTRY."""

    research_kinds = {ablated_strategy(*item).kind for item in all_ablations()}
    return {
        **row,
        "evidence": {
            key: value
            for key, value in row["evidence"].items()
            if key not in research_kinds
        },
        "rationale": "; ".join(
            part
            for part in row["rationale"].split("; ")
            if part.split("=", 1)[0] not in research_kinds
        ),
    }


def test_a_research_backtest_matches_the_default_one_and_removes_one_condition_per_ablation(
    backtest_db, varied_inputs
):
    start, end = _window(backtest_db)
    default = pipeline.backtest(start, end)
    registry = research_registry(all_ablations())
    research = pipeline.backtest(start, end, registry=registry)

    assert default["run"]["status"] == research["run"]["status"] == "success"
    assert research["run"]["id"] != default["run"]["id"]
    assert research["run"]["request_key"] == (
        f"{default['run']['request_key']}:research:{','.join(registry)}"
    )
    default_rows = _rows(backtest_db, default["run"]["id"])
    research_rows = _rows(backtest_db, research["run"]["id"])
    assert any(row["settlements"] for row in default_rows.values())

    # The canonical strategies of the research run are the default run's rows.
    canonical_keys = {key for key in research_rows if key[0] in REGISTRY}
    assert canonical_keys == set(default_rows)
    for key in canonical_keys:
        assert _canonical_view(research_rows[key]) == default_rows[key]

    # Each ablation row is its strategy's row minus that condition's reasons.
    for strategy_key, condition in all_ablations():
        ablated = ablated_strategy(strategy_key, condition)
        removed = REMOVED_REASONS[(strategy_key, condition)]
        base_kind = REGISTRY[strategy_key].kind
        compared = 0
        for (name, instrument_id, day), row in research_rows.items():
            if name != ablated.key:
                continue
            base = research_rows[(strategy_key, instrument_id, day)]
            expected = base["evidence"][base_kind]
            actual = row["evidence"][ablated.kind]
            assert actual["reasons"] == [
                reason for reason in expected["reasons"] if reason not in removed
            ]
            if expected["state"] == "rejected" and set(expected["reasons"]) <= removed:
                assert actual["state"] == "passed"
            else:
                assert actual["state"] == expected["state"]
            compared += set(expected["reasons"]) & removed != set()
        assert compared, f"{ablated.key}: no fixture row fails {removed}"


def test_a_research_backtest_writes_its_versions_and_no_canonical_row(backtest_db):
    start, end = _window(backtest_db)
    registry = research_registry([("breakout_v1", "group")], canonical=False)
    result = pipeline.backtest(start, end, registry=registry)

    assert result["run"]["status"] == "success"
    with backtest_db() as db:
        run = db.get(IngestionRun, result["run"]["id"])
        assert run.metadata_json["research_registry"] == ["breakout_v1_ablate_group"]
        version = db.scalar(
            select(StrategyVersion).where(
                StrategyVersion.name == "breakout_v1_ablate_group"
            )
        )
        assert version.kind == "breakout_ablate_group"
        assert version.config_json == version.canonical_config_snapshot
        assert "group_relative_strength" not in version.config_json["confirmations"]
        names = {
            db.get(StrategyVersion, signal.strategy_version_id).name
            for signal in db.scalars(
                select(Signal).where(Signal.signal_key.like(f"backtest-{run.id}-%"))
            )
        }
    assert names == {"breakout_v1_ablate_group"}
    # A second research run of the same registry reuses the run.
    assert pipeline.backtest(start, end, registry=registry)["run"]["id"] == run.id


# ---- research runs commit as they go ----


class _Boom(RuntimeError):
    pass


def _fail_once(monkeypatch, name: str, *, after: int):
    """Make ``pipeline.<name>`` raise on its ``after``-th call, once."""

    original = getattr(pipeline, name)
    calls = {"n": 0}

    def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == after:
            raise _Boom(f"{name} fails on call {after}")
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline, name, wrapper)


def _research_result(factory, registry, start, end, **kwargs):
    result = pipeline.backtest(start, end, registry=registry, **kwargs)
    assert result["run"]["status"] == "success", result.get("error")
    with factory() as db:
        expected = pipeline.summarize_backtest(db, result["run"]["id"])
    # The SQL summary is summarize_backtest's.
    assert {
        key: value for key, value in result.items() if key != "idempotent_reuse"
    } == expected
    return _rows(factory, result["run"]["id"]), result["groups"]


@pytest.mark.parametrize(
    ("failing", "after"),
    [("_generate_signals", 20), ("_evaluate_signal_tracking", 30)],
)
def test_a_failed_research_run_rerun_matches_one_uninterrupted_run(
    use_copy, monkeypatch, failing, after
):
    monkeypatch.setattr(pipeline, "RESEARCH_TRACKING_BATCH", 37)
    registry = research_registry([("pullback_v1", "volume")])
    whole = use_copy("whole.db")
    start, end = _window(whole, 25)
    expected_rows, expected_groups = _research_result(whole, registry, start, end)

    factory = use_copy("failed.db")
    _fail_once(monkeypatch, failing, after=after)
    failed = pipeline.backtest(start, end, registry=registry)
    assert failed["run"]["status"] == "failed" and "_Boom" in failed["error"]
    # What the failed run committed stays (V1_SPEC 3).
    assert _rows(factory, failed["run"]["id"])

    rows, groups = _research_result(factory, registry, start, end)
    assert rows == expected_rows and groups == expected_groups
    forced_rows, forced_groups = _research_result(
        factory, registry, start, end, force=True
    )
    assert forced_rows == expected_rows and forced_groups == expected_groups


def test_a_research_run_commits_each_score_date(use_copy, monkeypatch):
    factory = use_copy()
    start, end = _window(factory)
    registry = research_registry([("breakout_v1", "margin")], canonical=False)
    committed = []
    original = pipeline._generate_signals

    def spy(db, score_date, strategies, **kwargs):
        with factory() as probe:  # another connection sees only committed rows
            committed.append(
                probe.scalar(
                    select(func.count(Signal.id)).where(
                        Signal.signal_key.like("backtest-%")
                    )
                )
            )
        return original(db, score_date, strategies, **kwargs)

    monkeypatch.setattr(pipeline, "_generate_signals", spy)
    pipeline.backtest(start, end, registry=registry)
    per_day = committed[1] - committed[0]
    assert per_day > 0
    assert committed == [committed[0] + per_day * day for day in range(len(committed))]


def test_a_research_run_stops_at_the_daily_window_and_a_rerun_completes_it(
    use_copy, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "backtest_research", ROOT / "tools" / "research" / "backtest_research.py"
    )
    research = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(research)
    monkeypatch.setattr(pipeline, "RESEARCH_TRACKING_BATCH", 37)
    registry = research_registry([("breakout_v1", "volume")], canonical=False)
    whole = use_copy("whole.db")
    start, end = _window(whole, 25)
    expected_rows, expected_groups = _research_result(whole, registry, start, end)

    # A fake clock one minute per check from 18:20 Taipei: the 11th check is 18:30.
    minutes = iter(range(20, 90))
    clock = research.window_check(
        lambda: datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc)
        + timedelta(minutes=next(minutes))
    )
    factory = use_copy("paused.db")
    stopped = pipeline.backtest(start, end, registry=registry, should_stop=clock)

    assert research.paused(stopped) and "18:30" in stopped["error"]
    assert stopped["run"]["status"] == "failed"
    with factory() as db:
        committed_days = db.scalar(
            select(func.count(func.distinct(Signal.signal_date))).where(
                Signal.signal_key.like(f"backtest-{stopped['run']['id']}-%")
            )
        )
    assert committed_days == 11  # stopped after the 11th score date's commit
    rows, groups = _research_result(factory, registry, start, end)
    assert rows == expected_rows and groups == expected_groups
