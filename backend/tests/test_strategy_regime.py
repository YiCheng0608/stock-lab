"""Research regime filters (#546): each filter's three outcomes; a holding filter changes nothing."""

from __future__ import annotations

import importlib.util
import json
import random
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import RuleEvaluation
from app.models import MarketBar, Signal, SignalSettlement, StrategyVersion
from app.strategies import REGISTRY, StrategyInputs, canonical_config_snapshot
from app.strategies.regime import (
    BAR_MISSING,
    CLOSE_NOT_FINITE,
    CLOSES_INSUFFICIENT,
    FILTERS,
    LOOKBACK,
    TaiexCloses,
    all_regimes,
    evaluate_filter,
    evaluate_with_regime,
    regime_strategy,
    with_regimes,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "research" / "backtest_research.py"

spec = importlib.util.spec_from_file_location("backtest_research", SCRIPT)
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)

RISING = [100.0 + day for day in range(LOOKBACK)]
FALLING = [200.0 - day for day in range(LOOKBACK)]
FLAT = [100.0] * LOOKBACK
# Draws of v3 inputs per test: enough for pullback_v3 to pass at least once.
DRAWS = 30000


# ---- each filter: holds, fails, too few closes ----


@pytest.mark.parametrize("code", list(FILTERS))
def test_a_filter_holds_on_rising_closes(code):
    needed = FILTERS[code].required_closes
    assert evaluate_filter(code, RISING[-needed:]) == RuleEvaluation(True, "passed")
    assert evaluate_filter(code, RISING) == RuleEvaluation(True, "passed")


@pytest.mark.parametrize("code", list(FILTERS))
@pytest.mark.parametrize("closes", [FALLING, FLAT], ids=["falling", "flat"])
def test_a_filter_fails_on_falling_or_flat_closes(code, closes):
    # Every comparison is strict: a flat TAIEX is not above its averages.
    assert evaluate_filter(code, closes) == RuleEvaluation(
        False, "rejected", (f"market_regime_{code}_not_met",)
    )


@pytest.mark.parametrize("code", list(FILTERS))
def test_a_filter_without_enough_closes_is_data_incomplete(code):
    needed = FILTERS[code].required_closes
    assert evaluate_filter(code, RISING[-(needed - 1) :]) == RuleEvaluation(
        False, "data_incomplete", (CLOSES_INSUFFICIENT,)
    )
    assert evaluate_filter(code, []) == RuleEvaluation(
        False, "data_incomplete", (CLOSES_INSUFFICIENT,)
    )
    assert evaluate_filter(code, None) == RuleEvaluation(
        False, "data_incomplete", (BAR_MISSING,)
    )


@pytest.mark.parametrize("code", list(FILTERS))
@pytest.mark.parametrize("bad", [None, float("nan"), 0.0])
def test_a_missing_close_inside_the_window_is_data_incomplete(code, bad):
    needed = FILTERS[code].required_closes
    inside = list(RISING)
    inside[-needed] = bad
    assert evaluate_filter(code, inside) == RuleEvaluation(
        False, "data_incomplete", (CLOSE_NOT_FINITE,)
    )
    # One older than the window is not read.
    outside = [bad] + RISING[-needed:]
    assert evaluate_filter(code, outside).passed


def test_the_filters_read_their_own_windows():
    # 40 at 100, 19 at 120, then 110: below MA20 (119.5), above MA60 (106.5).
    closes = [100.0] * 40 + [120.0] * 19 + [110.0]
    results = {code: evaluate_filter(code, closes).passed for code in FILTERS}
    assert results == {"r1": True, "r2": False, "r3": True, "r4": True, "r5": True}
    # A spike 20 sessions ago (150), then 100s and 120: only R1 fails
    # (MA20 101 > MA60 94.67; MA20 five sessions earlier 100.5).
    closes = [90.0] * 39 + [150.0] + [100.0] * 19 + [120.0]
    results = {code: evaluate_filter(code, closes).passed for code in FILTERS}
    assert results == {"r1": False, "r2": True, "r3": True, "r4": True, "r5": True}
    # MA20 above MA60 but the close under MA60: R4 fails although MA20 > MA60.
    closes = [100.0] * 40 + [130.0] * 19 + [105.0]
    results = {code: evaluate_filter(code, closes).passed for code in FILTERS}
    assert results["r4"] is False and results["r3"] is False


# ---- the filter on top of v3 ----


def _random_arguments(key: str, rng: random.Random) -> dict:
    """Inputs around every v3 threshold, with missing and non-finite values."""

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


@pytest.mark.parametrize(("key", "code"), all_regimes())
def test_a_holding_filter_returns_the_v3_result_unchanged(key, code):
    rule = REGISTRY[key].rule
    rng = random.Random(546)
    states = set()
    for _ in range(DRAWS):
        arguments = _random_arguments(key, rng)
        base = rule(**arguments)
        assert evaluate_with_regime(rule, code, taiex_closes=RISING, **arguments) == (
            base
        )
        states.add(base.state)
    assert states == {"passed", "rejected", "data_incomplete"}


@pytest.mark.parametrize(("key", "code"), all_regimes())
def test_a_failed_filter_rejects_and_keeps_v3_missing_data(key, code):
    rule = REGISTRY[key].rule
    reason = FILTERS[code].reason
    rng = random.Random(5460)
    seen = set()
    for _ in range(DRAWS):
        arguments = _random_arguments(key, rng)
        base = rule(**arguments)
        result = evaluate_with_regime(rule, code, taiex_closes=FALLING, **arguments)
        if base.state == "data_incomplete":
            assert result == base
        else:
            assert result == RuleEvaluation(False, "rejected", (*base.reasons, reason))
        seen.add(base.state)
    assert seen == {"passed", "rejected", "data_incomplete"}


@pytest.mark.parametrize(("key", "code"), all_regimes())
@pytest.mark.parametrize(
    ("closes", "missing"),
    [(None, BAR_MISSING), (RISING[:5], CLOSES_INSUFFICIENT)],
    ids=["no_bar", "too_few"],
)
def test_a_filter_without_enough_taiex_data_is_data_incomplete(
    key, code, closes, missing
):
    rule = REGISTRY[key].rule
    rng = random.Random(54600)
    seen = set()
    for _ in range(DRAWS):
        arguments = _random_arguments(key, rng)
        base = rule(**arguments)
        result = evaluate_with_regime(rule, code, taiex_closes=closes, **arguments)
        own = base.reasons if base.state == "data_incomplete" else ()
        assert result == RuleEvaluation(False, "data_incomplete", (*own, missing))
        seen.add(base.state)
    assert seen == {"passed", "rejected", "data_incomplete"}


# ---- strategies, closes and the registry ----


def _closes(days: list[date], values: list[float]) -> TaiexCloses:
    return TaiexCloses(dict(zip(days, values)))


def test_the_closes_window_never_reads_a_later_date():
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(80)]
    closes = _closes(days, [float(offset + 1) for offset in range(80)])
    with pytest.raises(RuntimeError, match="without a score date"):
        closes.window()
    closes.set_session(days[9])
    assert closes.window() == tuple(float(n) for n in range(1, 11))
    closes.set_session(days[79])
    assert closes.window() == tuple(float(n) for n in range(21, 81))
    closes.set_session(date(2025, 12, 31))  # before the first bar
    assert closes.window() is None
    sparse = TaiexCloses({days[0]: 1.0, days[2]: 2.0})
    sparse.set_session(days[1])  # TAIEX has no bar that day
    assert sparse.window() is None
    states = closes.states("r2", days[18:21])
    assert [item.state for item in states.values()] == [
        "data_incomplete",
        "passed",
        "passed",
    ]
    assert closes.session == date(2025, 12, 31)


@pytest.mark.parametrize(("key", "code"), all_regimes())
def test_a_regime_config_differs_only_by_name_kind_and_its_filter(key, code):
    canonical = json.loads(json.dumps(REGISTRY[key].config))
    strategy = regime_strategy(key, code, TaiexCloses({}))
    config = json.loads(json.dumps(strategy.config))

    assert config.pop("name") == f"{key}_regime_{code}" == strategy.key
    assert config.pop("kind") == f"{canonical['kind']}_regime_{code}"
    regime = config.pop("regime_filter")
    assert regime["base_strategy"] == key
    assert regime["base_version"] == REGISTRY[key].version
    assert regime["filter"] == code
    assert regime["required_closes"] == FILTERS[code].required_closes
    assert regime["missing_policy"] == "data_incomplete"
    del canonical["name"], canonical["kind"]
    assert config == canonical


def test_regime_strategies_leave_the_registry_and_canonical_snapshot_alone():
    before = canonical_config_snapshot()
    registry = with_regimes(dict(REGISTRY), all_regimes(), TaiexCloses({}))

    assert list(REGISTRY) == ["breakout_v3", "pullback_v3"]
    assert canonical_config_snapshot() == before
    assert list(registry)[:2] == list(REGISTRY)
    assert len(registry) == 2 + 2 * len(FILTERS)
    assert len({strategy.kind for strategy in registry.values()}) == len(registry)
    with pytest.raises(ValueError, match="already in the registry"):
        with_regimes(registry, [("breakout_v3", "r1")], TaiexCloses({}))


def test_a_regime_strategy_evaluates_v3_inputs_with_the_score_dates_closes():
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(LOOKBACK)]
    rising, falling = _closes(days, RISING), _closes(days, FALLING)
    inputs = StrategyInputs(
        bar_count=60,
        close=101.0,
        volume=1300.0,
        ma20=100.0,
        ma60=90.0,
        atr14=2.0,
        prior_highs=[100.0] * 20,
        prior_volumes=[1000] * 20,
        group_excess_return_20d=0.01,
        institutional_flow_ratio_5d=0.0,
        margin_change_ratio_5d=0.0,
        margin_financing="applicable",
    )
    for key in REGISTRY:
        base = REGISTRY[key].evaluate(inputs)
        held = regime_strategy(key, "r4", rising)
        failed = regime_strategy(key, "r4", falling)
        with pytest.raises(RuntimeError):
            held.evaluate(inputs)
        rising.set_session(days[-1])
        falling.set_session(days[-1])
        assert held.evaluate(inputs) == base
        assert failed.evaluate(inputs).reasons[-1] == "market_regime_r4_not_met"
        assert held.actionable_levels(inputs) == REGISTRY[key].actionable_levels(inputs)
        rising.set_session(None)
        falling.set_session(None)
    assert REGISTRY["breakout_v3"].evaluate(inputs).passed


# ---- backtest on the verify fixture database ----


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    dest = tmp_path_factory.mktemp("regime")
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
    yield factory
    engine.dispose()


def _rows(factory, run_id: int) -> dict[tuple, dict]:
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
                "settlements": settlements,
            }
    return rows


NOT_ACTIONABLE = {"observation", "data_incomplete", "invalid_levels"}


def test_a_research_backtest_keeps_v3_where_the_filter_holds(backtest_db):
    with backtest_db() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    start, end = days[-45], days[-1]
    window = days[days.index(start) - 10 :]
    # Synthetic TAIEX: well above or below 100 by date, so R2 (close > MA20)
    # holds on some score dates and fails on others once it has 20 closes;
    # R3 needs 60 and is data_incomplete on every one.
    rng = random.Random(546)
    values = [rng.choice((60.0, 160.0)) for _ in window]
    closes = TaiexCloses(dict(zip(window, values)))
    items = [(key, code) for key in REGISTRY for code in ("r2", "r3")]
    registry = with_regimes(dict(REGISTRY), items, closes)
    with research.score_dates(closes, pipeline):
        result = pipeline.backtest(start, end, registry=registry)
    assert pipeline._generate_signals.__name__ == "_generate_signals"
    assert closes.session is None
    assert result["run"]["status"] == "success"
    assert result["run"]["request_key"].endswith(":research:" + ",".join(registry))

    rows = _rows(backtest_db, result["run"]["id"])
    r2_states = closes.states("r2", days[days.index(start) :])
    assert {state.state for state in r2_states.values()} == {
        "passed",
        "rejected",
        "data_incomplete",
    }
    compared = {"passed": 0, "rejected": 0, "data_incomplete": 0}
    for key in REGISTRY:
        base_kind = REGISTRY[key].kind
        for code in ("r2", "r3"):
            strategy = registry[f"{key}_regime_{code}"]
            for (name, instrument_id, day), row in rows.items():
                if name != strategy.key:
                    continue
                base = rows[(key, instrument_id, day)]
                filtered = closes.states(code, [day])[day]
                own = row["evidence"][strategy.kind]
                base_state = base["evidence"][base_kind]
                assert row["evidence"][base_kind] == base_state
                closes.set_session(day)
                expected = evaluate_with_regime(
                    lambda state=base_state: RuleEvaluation(
                        state["state"] == "passed",
                        state["state"],
                        tuple(state["reasons"]),
                    ),
                    code,
                    taiex_closes=closes.window(),
                )
                closes.set_session(None)
                assert own == {"state": expected.state, "reasons": [*expected.reasons]}
                if filtered.passed:
                    assert own == base_state
                    assert row["status"] == base["status"]
                    assert row["levels"] == base["levels"]
                    assert row["settlements"] == base["settlements"]
                else:
                    assert row["status"] in NOT_ACTIONABLE
                    assert not row["settlements"]
                    if filtered.state == "data_incomplete":
                        assert row["status"] == "data_incomplete"
                if base["status"] not in NOT_ACTIONABLE:
                    compared[filtered.state] += 1
    # Actionable v3 signals on dates the filter held, failed and lacked data.
    assert all(compared.values()), compared


def test_the_research_cli_runs_regime_strategies_on_the_fixture(fixture_db, tmp_path):
    from datetime import datetime, timezone

    shutil.copyfile(fixture_db, tmp_path / "stock.db")
    with __import__("sqlite3").connect(tmp_path / "stock.db") as connection:
        (end,) = connection.execute(
            "SELECT max(trading_date) FROM market_bars"
        ).fetchone()
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--db", str(tmp_path / "stock.db")]
        + ["--start", end, "--end", end, "--min-free-gb", "0"]
        + ["--regime", "breakout_v3:r2", "pullback_v3:r5"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    if research.daily_window_problem(datetime.now(timezone.utc)):
        assert result.returncode == 2 and "21:30-23:30" in result.stdout
        return
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["registry"] == [
        "breakout_v3",
        "pullback_v3",
        "breakout_v3_regime_r2",
        "pullback_v3_regime_r5",
    ]
    assert report["status"] == "success" and report["score_sessions"] == 1
    assert report["taiex_last"] == end and report["taiex_closes"] > 20
    assert set(report["strategies"]) == set(report["registry"])
    assert len({item["signals"] for item in report["strategies"].values()}) == 1


def test_an_unknown_regime_strategy_is_refused(tmp_path):
    with pytest.raises(research.Refused, match="unknown regime"):
        research.regime_items(["breakout_v3:r9"])
    with pytest.raises(research.Refused, match="unknown regime"):
        research.regime_items(["breakout_v1:r1"])
    assert research.regime_items(["all"]) == all_regimes()


def test_a_slim_run_keeps_every_number_of_a_full_run(fixture_db, tmp_path, monkeypatch):
    """--slim cuts non-actionable rows down; status, levels and tracking stay."""

    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    results = {}
    for slim in (False, True):
        path = tmp_path / f"slim-{slim}.db"
        shutil.copyfile(fixture_db, path)
        engine = create_engine(f"sqlite:///{path.as_posix()}")
        enable_sqlite_foreign_keys(engine)
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        monkeypatch.setattr(pipeline, "SessionLocal", factory)
        with factory() as db:
            days = db.scalars(
                select(MarketBar.trading_date)
                .distinct()
                .order_by(MarketBar.trading_date)
            ).all()
        start = days[-30]
        closes = TaiexCloses(
            dict(zip(days, [160.0 if n % 3 else 60.0 for n in range(len(days))]))
        )
        registry = with_regimes(
            dict(REGISTRY), [(key, "r2") for key in REGISTRY], closes
        )
        with research.score_dates(closes, pipeline, slim=slim):
            run = pipeline.backtest(start, days[-1], registry=registry)["run"]
        assert run["status"] == "success"
        results[slim] = (_rows(factory, run["id"]), run)
        engine.dispose()

    (full, full_run), (slim, slim_run) = results[False], results[True]
    assert full_run["request_key"] == slim_run["request_key"]
    assert set(full) == set(slim)
    shrunk = 0
    for key, row in full.items():
        cut = slim[key]
        assert (cut["status"], cut["levels"], cut["settlements"]) == (
            row["status"],
            row["levels"],
            row["settlements"],
        )
        kind = registry[key[0]].kind
        if row["status"] in NOT_ACTIONABLE:
            assert cut["evidence"] == {
                "strategy": row["evidence"]["strategy"],
                "strategy_version": row["evidence"]["strategy_version"],
                "actionable": False,
                "research_slim": research.SLIM_MARK,
                kind: row["evidence"][kind],
            }
            shrunk += 1
        else:
            assert cut["evidence"] == row["evidence"]
    assert shrunk and shrunk < len(full)
