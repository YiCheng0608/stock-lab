"""Research aggressive versions (#598): each relaxes only its declared place."""

from __future__ import annotations

import importlib.util
import json
import random
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from test_strategy_regime import NOT_ACTIONABLE, _rows

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import RuleEvaluation
from app.models import MarketBar
from app.strategies import REGISTRY, canonical_config_snapshot
from app.strategies import index_conditions
from app.strategies.aggressive import (
    BASES,
    EXPLORATION,
    MIN_ADDED,
    MIN_ADDED_T20,
    REMOVE,
    VALIDATION,
    VARIANTS,
    Comparison,
    aggressive_strategy,
    all_variants,
    judge_exploration,
    judge_validation,
    proposable,
    relaxed_config,
    with_variants,
)
from app.strategies.breakout_v3 import BREAKOUT_V3
from app.strategies.pullback_v4 import PULLBACK_V4

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "research" / "backtest_research.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


research = _load("backtest_research")
report = _load("aggressive_report")

# The keys each version changes, and its new value ("removed" for a deleted
# confirmation): the Issue's definitions, written out once more by hand.
DECLARED = {
    ("breakout_v3", "a1"): {"volume.minimum_signal_to_average_ratio": 1.00},
    ("breakout_v3", "a2"): {"confirmations.institutional_flow": "removed"},
    ("breakout_v3", "a3"): {"confirmations.margin_financing": "removed"},
    ("breakout_v3", "a4"): {"confirmations.group_relative_strength": "removed"},
    ("breakout_v3", "a7"): {
        "volume.minimum_signal_to_average_ratio": 1.00,
        "confirmations.institutional_flow": "removed",
        "confirmations.margin_financing": "removed",
    },
    ("pullback_v4", "a2"): {"confirmations.institutional_flow": "removed"},
    ("pullback_v4", "a3"): {"confirmations.margin_financing": "removed"},
    ("pullback_v4", "a4"): {"confirmations.group_relative_strength": "removed"},
    ("pullback_v4", "a5"): {"volume.maximum_signal_to_average_ratio": 1.50},
    ("pullback_v4", "a6"): {"support_zone.minimum_close_to_ma20_ratio": 0.95},
    ("pullback_v4", "a7"): {
        "volume.maximum_signal_to_average_ratio": 1.50,
        "confirmations.institutional_flow": "removed",
        "confirmations.margin_financing": "removed",
    },
}
# The reasons a relaxed key can stop reporting; every other reason stays.
RELAXED_REASONS = {
    "volume.minimum_signal_to_average_ratio": "volume_ratio_below_1_20",
    "confirmations.institutional_flow": "institutional_flow_materially_adverse",
    "confirmations.margin_financing": "margin_financing_increase_abnormal",
    "confirmations.group_relative_strength": "group_relative_strength_not_positive",
    "volume.maximum_signal_to_average_ratio": "pullback_volume_ratio_outside_range",
    "support_zone.minimum_close_to_ma20_ratio": "close_outside_ma20_support_zone",
}
DRAWS = 20000


def _flatten(value, prefix=""):
    if isinstance(value, dict):
        items = {}
        for key, item in value.items():
            items.update(_flatten(item, f"{prefix}{key}."))
        return items
    return {prefix[:-1]: value}


def _random_arguments(key: str, rng: random.Random) -> dict:
    """Inputs around the old and new thresholds, with missing and non-finite values."""

    def pick(*values):
        return rng.choice(values)

    confirmations = dict(
        group_excess_return_20d=pick(-0.01, 0.0, 0.01, None, float("nan")),
        institutional_flow_to_turnover_ratio_5d=pick(-0.004, -0.003, 0.0, None),
        margin_balance_change_ratio_5d=pick(0.04, 0.05, 0.06, None),
        margin_financing=pick("applicable", "not_applicable", "missing", None),
        margin_zero_base=pick(None, "zero_base_unchanged", "zero_base_increased"),
    )
    volumes = pick([1000.0] * 20, [1000.0] * 19, [1000.0] * 19 + [0.0], None)
    if key == "breakout_v3":
        return dict(
            close=pick(99.0, 100.0, 101.0, 0.0, None),
            prior_highs=pick([100.0] * 20, [100.0] * 19, None),
            volume=pick(950.0, 1000.0, 1100.0, 1200.0, 1300.0, 0.0, None),
            prior_volumes=volumes,
            **confirmations,
        )
    return dict(
        bar_count=pick(59, 60, 61, None, True),
        close=pick(94.0, 95.0, 96.0, 97.0, 100.0, 102.0, 103.0),
        ma20=pick(100.0, 0.0, None),
        ma60=pick(90.0, 100.0, 101.0),
        volume=pick(500.0, 600.0, 1000.0, 1200.0, 1400.0, 1500.0, 1600.0),
        prior_volumes=volumes,
        **confirmations,
    )


def test_the_variants_are_the_issues_definitions():
    assert set(all_variants()) == set(DECLARED)
    assert list(VARIANTS) == ["a1", "a2", "a3", "a4", "a5", "a6", "a7"]
    for code, item in VARIANTS.items():
        for key, changes in item.changes.items():
            # A1～A6 change one place each; A7 is the three-place package.
            assert len(changes) == (3 if code == "a7" else 1), (key, code)


@pytest.mark.parametrize(("key", "code"), all_variants())
def test_a_version_config_differs_only_by_its_declared_keys(key, code):
    canonical = _flatten(json.loads(json.dumps(BASES[key].config)))
    config = json.loads(json.dumps(relaxed_config(key, code)))

    assert config.pop("name") == f"{key}_aggr_{code}"
    assert config.pop("kind") == f"{BASES[key].kind}_aggr_{code}"
    snapshot = config.pop("aggressive")
    assert snapshot["base_strategy"] == key
    assert snapshot["base_version"] == BASES[key].version
    assert snapshot["variant"] == code and snapshot["issue"] == 598
    declared = DECLARED[(key, code)]
    assert {item["key"]: item["to"] for item in snapshot["changes"]} == declared

    flat = _flatten(config)
    del canonical["name"], canonical["kind"]
    changed = {}
    for path, value in canonical.items():
        if path not in flat:
            changed[path] = "removed"
        elif flat[path] != value:
            changed[path] = flat[path]
    assert not set(flat) - set(canonical)
    # A removed confirmation removes every key under it.
    expected = {}
    for path, value in declared.items():
        if value == "removed":
            expected.update(
                {item: "removed" for item in canonical if item.startswith(path + ".")}
            )
        else:
            expected[path] = value
    assert changed == expected
    for item in snapshot["changes"]:
        if item["to"] != "removed":
            assert canonical[item["key"]] == item["from"]


@pytest.mark.parametrize(("key", "code"), all_variants())
def test_a_version_only_relaxes_its_declared_conditions(key, code):
    """On every draw: same data_incomplete, base passed ⇒ version passed, fewer reasons only."""

    base = BASES[key]
    strategy = aggressive_strategy(key, code)
    relaxed = {RELAXED_REASONS[path] for path in DECLARED[(key, code)]}
    rng = random.Random(598)
    gained = states = 0
    for _ in range(DRAWS):
        arguments = _random_arguments(key, rng)
        before = base.rule(**arguments)
        after = strategy.rule(**arguments)
        if before.state == "data_incomplete":
            assert after == before
            continue
        assert after.state != "data_incomplete"
        assert set(after.reasons) <= set(before.reasons)
        assert set(before.reasons) - set(after.reasons) <= relaxed
        if before.passed:
            assert after == before
        elif after.passed:
            gained += 1
        # Every reason the version still reports keeps the base's order.
        assert after.reasons == tuple(r for r in before.reasons if r in after.reasons)
        states += 1
    assert gained and states


@pytest.mark.parametrize(("key", "code"), all_variants())
def test_the_evaluator_with_the_base_config_is_the_base(key, code):
    # The version's rule is the base's evaluator; only the config differs.
    strategy = aggressive_strategy(key, code)
    assert strategy.rule.func is type(BASES[key]).rule
    assert strategy.rule.keywords == {"config": strategy.config}
    assert strategy.arguments.__func__ is type(BASES[key]).arguments


BREAKOUT_PASS = dict(
    close=101.0,
    prior_highs=[100.0] * 20,
    volume=1300.0,
    prior_volumes=[1000.0] * 20,
    group_excess_return_20d=0.01,
    institutional_flow_to_turnover_ratio_5d=0.0,
    margin_balance_change_ratio_5d=0.0,
    margin_financing="applicable",
    margin_zero_base=None,
)
PULLBACK_PASS = dict(
    bar_count=60,
    close=100.0,
    ma20=100.0,
    ma60=90.0,
    volume=1000.0,
    prior_volumes=[1000.0] * 20,
    group_excess_return_20d=0.01,
    institutional_flow_to_turnover_ratio_5d=0.0,
    margin_balance_change_ratio_5d=0.0,
    margin_financing="applicable",
    margin_zero_base=None,
)


@pytest.mark.parametrize(
    ("key", "code", "change", "base_reason", "version_passes"),
    [
        # A1: 1.00 ≤ ratio < 1.20 passes only the version; under 1.00 neither.
        ("breakout_v3", "a1", {"volume": 1100.0}, "volume_ratio_below_1_20", True),
        ("breakout_v3", "a1", {"volume": 1000.0}, "volume_ratio_below_1_20", True),
        ("breakout_v3", "a1", {"volume": 999.0}, "volume_ratio_below_1_20", False),
        # A5: 1.20 < ratio ≤ 1.50 passes only the version; above 1.50 neither.
        (
            "pullback_v4",
            "a5",
            {"volume": 1400.0},
            "pullback_volume_ratio_outside_range",
            True,
        ),
        (
            "pullback_v4",
            "a5",
            {"volume": 1500.0},
            "pullback_volume_ratio_outside_range",
            True,
        ),
        (
            "pullback_v4",
            "a5",
            {"volume": 1501.0},
            "pullback_volume_ratio_outside_range",
            False,
        ),
        # A5 leaves the 0.60 floor alone.
        (
            "pullback_v4",
            "a5",
            {"volume": 590.0},
            "pullback_volume_ratio_outside_range",
            False,
        ),
        # A6: 0.95 ≤ close/MA20 < 0.97 passes only the version; the 1.02 top stays.
        ("pullback_v4", "a6", {"close": 96.0}, "close_outside_ma20_support_zone", True),
        ("pullback_v4", "a6", {"close": 95.0}, "close_outside_ma20_support_zone", True),
        (
            "pullback_v4",
            "a6",
            {"close": 94.9},
            "close_outside_ma20_support_zone",
            False,
        ),
        (
            "pullback_v4",
            "a6",
            {"close": 102.5},
            "close_outside_ma20_support_zone",
            False,
        ),
        # A2～A4 and A7 on one failed confirmation each.
        (
            "breakout_v3",
            "a2",
            {"institutional_flow_to_turnover_ratio_5d": -0.01},
            "institutional_flow_materially_adverse",
            True,
        ),
        (
            "pullback_v4",
            "a3",
            {"margin_balance_change_ratio_5d": 0.2},
            "margin_financing_increase_abnormal",
            True,
        ),
        (
            "pullback_v4",
            "a3",
            {
                "margin_balance_change_ratio_5d": None,
                "margin_zero_base": "zero_base_increased",
            },
            "margin_financing_increase_abnormal",
            True,
        ),
        (
            "breakout_v3",
            "a4",
            {"group_excess_return_20d": 0.0},
            "group_relative_strength_not_positive",
            True,
        ),
        (
            "breakout_v3",
            "a7",
            {"volume": 1050.0, "margin_balance_change_ratio_5d": 0.2},
            None,
            True,
        ),
        (
            "breakout_v3",
            "a7",
            {"group_excess_return_20d": -0.01},
            "group_relative_strength_not_positive",
            False,
        ),
        (
            "pullback_v4",
            "a7",
            {"volume": 1450.0, "institutional_flow_to_turnover_ratio_5d": -0.5},
            None,
            True,
        ),
    ],
)
def test_the_relaxed_threshold_on_small_fixtures(
    key, code, change, base_reason, version_passes
):
    arguments = {**(BREAKOUT_PASS if key == "breakout_v3" else PULLBACK_PASS)}
    assert BASES[key].rule(**arguments) == RuleEvaluation(True, "passed")
    arguments.update(change)
    before = BASES[key].rule(**arguments)
    after = aggressive_strategy(key, code).rule(**arguments)
    assert before.state == "rejected"
    if base_reason is not None:
        assert base_reason in before.reasons
    assert after.passed is version_passes
    if not version_passes:
        assert after.state == "rejected"


def test_the_bases_are_fixed_whatever_the_registry_holds():
    assert BASES == {"breakout_v3": BREAKOUT_V3, "pullback_v4": PULLBACK_V4}
    assert research.aggressive_items(["pullback_v4:a5"]) == [("pullback_v4", "a5")]
    assert research.aggressive_items(["all"]) == all_variants()
    for name in (
        "breakout_v3:a5",
        "pullback_v4:a1",
        "pullback_v3:a2",
        "breakout_v3:a9",
    ):
        with pytest.raises(research.Refused, match="unknown aggressive"):
            research.aggressive_items([name])


def test_versions_leave_the_registry_and_canonical_snapshot_alone():
    before = canonical_config_snapshot()
    registered = dict(REGISTRY)
    registry = with_variants(dict(BASES), all_variants())

    assert REGISTRY == registered
    assert not any("_aggr_" in key for key in REGISTRY)
    assert canonical_config_snapshot() == before
    assert BREAKOUT_V3.config["volume"]["minimum_signal_to_average_ratio"] == 1.20
    assert "institutional_flow" in PULLBACK_V4.config["confirmations"]
    assert list(registry)[:2] == list(BASES)
    assert len(registry) == 2 + len(DECLARED)
    assert len({strategy.kind for strategy in registry.values()}) == len(registry)
    with pytest.raises(ValueError, match="already in the registry"):
        with_variants(registry, [("breakout_v3", "a1")])
    with pytest.raises(ValueError, match="does not apply"):
        with_variants(dict(BASES), [("breakout_v3", "a5")])
    assert REMOVE is not None


def test_the_split_is_567s():
    assert (EXPLORATION, VALIDATION) == (
        index_conditions.EXPLORATION,
        index_conditions.VALIDATION,
    )
    assert EXPLORATION.start == date(2024, 9, 30)
    assert EXPLORATION.end == date(2025, 12, 31)
    assert VALIDATION.start == date(2026, 1, 1) and VALIDATION.end is None


def test_the_proposal_rule():
    def item(**changes):
        values = dict(
            added=MIN_ADDED,
            added_t20_n=MIN_ADDED_T20,
            added_t20_median=-0.01,
            baseline_t20_median=-0.02,
            added_invalidated_share=0.40,
            baseline_invalidated_share=0.45,
        )
        values.update(changes)
        return Comparison(**values)

    assert judge_exploration(item()) == "selected"
    assert judge_validation(item()) == "not_reversed"
    assert proposable(item(), item())
    # Exploration is strict; validation only asks for no reversal.
    tie = item(added_t20_median=-0.02, added_invalidated_share=0.45)
    assert judge_exploration(tie) == "not_selected"
    assert judge_validation(tie) == "not_reversed"
    worse = item(added_invalidated_share=0.46)
    assert judge_exploration(worse) == "not_selected"
    assert judge_validation(worse) == "reversed"
    assert not proposable(item(), worse)
    for thin in (item(added=MIN_ADDED - 1), item(added_t20_n=MIN_ADDED_T20 - 1)):
        assert judge_exploration(thin) == judge_validation(thin) == "insufficient"
        assert not proposable(thin, item())
    assert judge_validation(item(added_t20_median=None)) == "insufficient"


# ---- backtest on the verify fixture database ----


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    dest = tmp_path_factory.mktemp("aggressive")
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
def backtest_db(fixture_db, tmp_path, monkeypatch):
    path = tmp_path / "stock.db"
    shutil.copyfile(fixture_db, path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    yield factory, path
    engine.dispose()


def test_a_research_backtest_keeps_every_base_signal_and_only_adds(backtest_db):
    factory, _path = backtest_db
    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    start, end = days[-45], days[-1]
    registry = with_variants(dict(BASES), all_variants())
    result = pipeline.backtest(start, end, registry=registry)
    assert result["run"]["status"] == "success"
    assert result["run"]["request_key"].endswith(":research:" + ",".join(registry))

    rows = _rows(factory, result["run"]["id"])
    added = {}
    for key, code in all_variants():
        strategy = registry[f"{key}_aggr_{code}"]
        base_kind = BASES[key].kind
        added[(key, code)] = 0
        for (name, instrument_id, day), row in rows.items():
            if name != strategy.key:
                continue
            base = rows[(key, instrument_id, day)]
            own = row["evidence"][strategy.kind]
            base_state = base["evidence"][base_kind]
            # Each row records the base's state unchanged next to its own.
            assert row["evidence"][base_kind] == base_state
            if base_state["state"] == "data_incomplete":
                assert own == base_state
            if base_state["state"] == "passed":
                assert own == base_state
            if base["status"] not in NOT_ACTIONABLE:
                # A base signal stays, with the same status, levels and settlements.
                assert row["status"] == base["status"]
                assert row["levels"] == base["levels"]
                assert row["settlements"] == base["settlements"]
            elif row["status"] not in NOT_ACTIONABLE:
                added[(key, code)] += 1
    # The fixture is small; the confirmation removals must add signals there.
    assert added[("breakout_v3", "a7")] or added[("pullback_v4", "a7")], added


def test_a_report_of_the_run_finds_every_base_signal_and_the_added_ones(
    backtest_db, tmp_path
):
    factory, path = backtest_db
    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    start, end = days[-45], days[-1]
    items = [("breakout_v3", "a1"), ("breakout_v3", "a7"), ("pullback_v4", "a7")]
    registry = with_variants(dict(BASES), items)
    run = pipeline.backtest(start, end, registry=registry)["run"]
    rows = _rows(factory, run["id"])

    result = report.build(path, run["id"])
    assert result["run"]["request_key"] == run["request_key"]
    assert result["run"]["registry"] == list(registry)
    assert sum(item["score_sessions"] for item in result["split"].values()) == 45
    for base, data in result["strategies"].items():
        names = [
            key
            for key in registry
            if registry[key].config.get("aggressive", {}).get("base_strategy") == base
        ]
        assert list(data["versions"]) == [base, *names]
        for name in names:
            check = data["consistency"][name]
            assert check["baseline_not_in_version"] == 0 and check["dropped"] == []
            assert check["status_or_settlement_differs"] == 0
            whole = data["versions"][name]["scopes"]["all"]["actionable"]
            assert whole == check["baseline_actionable"] + check["added"]
            expected_added = sum(
                1
                for (row_name, instrument_id, day), row in rows.items()
                if row_name == name
                and row["status"] not in NOT_ACTIONABLE
                and rows[(base, instrument_id, day)]["status"] in NOT_ACTIONABLE
            )
            assert (
                data["added"][name]["all"]["actionable"]
                == check["added"]
                == expected_added
            )
            assert data["added"][name]["all"]["actionable"] == sum(
                data["added"][name][q]["actionable"] for q in result["quarters"]
            )
            judged = data["judgement"][name]
            for segment in ("exploration", "validation"):
                assert judged[segment]["verdict"] in report.VERDICT_ZH
                assert judged[segment]["version_verdict"] in report.VERDICT_ZH
    out = tmp_path / "out"
    argv = ["--db", str(path), "--run-id", str(run["id"]), "--out", str(out)]
    assert report.main(argv) == 0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert run["request_key"] in summary and "多出來的訊號" in summary
    assert "段別判定" in summary and "整個版本的判定" in summary
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["split"]["exploration"]["start"] == "2024-09-30"


def test_the_report_names_a_dropped_base_signal(backtest_db, tmp_path):
    """A version row that lost a base signal is listed with its status and reasons."""

    factory, path = backtest_db
    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    registry = with_variants(dict(BASES), [("breakout_v3", "a2")])
    run = pipeline.backtest(days[-30], days[-1], registry=registry)["run"]
    rows = _rows(factory, run["id"])
    victim = next(
        key
        for key, row in rows.items()
        if key[0] == "breakout_v3" and row["status"] not in NOT_ACTIONABLE
    )
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update signals set status = 'observation' where id = ("
            "select s.id from signals s join strategy_versions v "
            "on v.id = s.strategy_version_id where v.name = ? "
            "and s.instrument_id = ? and s.signal_date = ? and s.signal_key like ?)",
            (
                "breakout_v3_aggr_a2",
                victim[1],
                victim[2].isoformat(),
                f"backtest-{run['id']}-%",
            ),
        )
        connection.commit()
    check = report.build(path, run["id"])["strategies"]["breakout_v3"]["consistency"][
        "breakout_v3_aggr_a2"
    ]
    assert check["baseline_not_in_version"] == 1
    assert check["dropped"][0]["status"] == "observation"
    assert check["dropped"][0]["signal_date"] == victim[2]


def test_the_report_refuses_the_production_database(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    argv = ["--db", str(production), "--run-id", "1", "--out", str(tmp_path / "o")]
    assert report.main(argv) == 2
    assert not (tmp_path / "o").exists()


def test_the_research_cli_runs_aggressive_versions_on_the_fixture(fixture_db, tmp_path):
    shutil.copyfile(fixture_db, tmp_path / "stock.db")
    with closing(sqlite3.connect(tmp_path / "stock.db")) as connection:
        (end,) = connection.execute(
            "SELECT max(trading_date) FROM market_bars"
        ).fetchone()
    command = [sys.executable, "-B", str(SCRIPT), "--db", str(tmp_path / "stock.db")]
    command += ["--start", end, "--end", end, "--min-free-gb", "0"]
    result = subprocess.run(
        command + ["--aggressive", "breakout_v3:a1", "pullback_v4:a5"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if research.daily_window_problem(datetime.now(timezone.utc)):
        assert result.returncode == 2 and "21:30-23:30" in result.stdout
        return
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["registry"] == [
        "breakout_v3",
        "pullback_v4",
        "breakout_v3_aggr_a1",
        "pullback_v4_aggr_a5",
    ]
    assert output["status"] == "success" and output["score_sessions"] == 1
    assert set(output["strategies"]) == set(output["registry"])

    mixed = subprocess.run(
        command + ["--aggressive", "all", "--ablate", "breakout_v3:group"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert mixed.returncode == 2
    assert "cannot be combined" in json.loads(mixed.stdout)["refused"][0]
