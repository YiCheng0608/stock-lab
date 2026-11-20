"""Research index conditions (#567): each condition's three outcomes, markets, TX rolls, US dates."""

from __future__ import annotations

import importlib.util
import json
import random
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from test_strategy_regime import DRAWS, NOT_ACTIONABLE, _random_arguments, _rows

import worker.pipeline as pipeline
from app.db import enable_sqlite_foreign_keys
from app.domain import RuleEvaluation
from app.models import Instrument, MarketBar
from app.strategies import REGISTRY, StrategyInputs, canonical_config_snapshot
from app.strategies.breakout_v3 import BREAKOUT_V3
from app.strategies.pullback_v3 import PULLBACK_V3
from app.strategies.pullback_v4 import PULLBACK_V4
from app.strategies.index_conditions import (
    ALL_CONDITIONS,
    BASES,
    COMMON_COST,
    CONDITIONS,
    NEXT_SESSION_UNKNOWN,
    OVERNIGHT_BASES,
    OVERNIGHT_CONDITIONS,
    OVERNIGHT_MIN_REMOVED,
    OVERNIGHT_MIN_REMOVED_DAYS,
    OVERNIGHT_MIN_T20,
    OVERNIGHT_THRESHOLDS,
    TRACKING_COST,
    OvernightComparison,
    baselines_of,
    judge_edge,
    judge_improved,
    overnight_conditions,
    overnight_verdict,
    EXPLORATION,
    MARKET_INDEX_UNKNOWN,
    MIN_REMOVED,
    MIN_T20,
    SERIES,
    US_STALE_DAYS,
    VALIDATION,
    Comparison,
    IndexHistory,
    IndexView,
    all_conditions,
    combine,
    condition_strategy,
    evaluate_with_condition,
    judge_exploration,
    judge_validation,
    proposable,
    segment_of,
    with_conditions,
)
from worker.futures_bars import near_month, third_wednesday

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
report = _load("index_condition_report")

# Rows each condition needs of the series it reads (its longest window).
NEEDED = {
    "c1": 240,
    "c2": 60,
    "c3a": 1,
    "c3b": 20,
    "c4a": 60,
    "c4b": 60,
    "c5": 240,
    "c6": 60,
    "c7": 240,
}


def _weekdays(count: int, end: date = date(2026, 3, 2)) -> list[date]:
    days: list[date] = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days[::-1]


def _rows_of(days, closes, months=None):
    months = months or [None] * len(days)
    return {day: (close, month) for day, close, month in zip(days, closes, months)}


def _scenario(direction: str, length: int) -> tuple[IndexHistory, date]:
    """Every series ``length`` rows rising (``up``) or falling (``down``).

    Taiwan rows end on the session; US rows end the weekday before it.  TX is
    TAIEX + 50 when rising and − 50 when falling (C3's basis).
    """

    days = _weekdays(length + 1)
    session = days[-1]
    step = 10.0 if direction == "up" else -10.0
    closes = [5000.0 + step * n for n in range(length)]
    basis = 50.0 if direction == "up" else -50.0
    taiwan, us = days[1:], days[:-1]
    rows = {
        "TAIEX": _rows_of(taiwan, closes),
        "TPEX": _rows_of(taiwan, closes),
        "TX": _rows_of(
            taiwan,
            [close + basis for close in closes],
            [near_month(day) for day in taiwan],
        ),
        "SPX": _rows_of(us, closes),
        "SOX": _rows_of(us, closes),
    }
    return IndexHistory(rows), session


def _result(history: IndexHistory, session: date, code: str, exchange="TWSE"):
    return IndexView(history, session, exchange).result(code)


# ---- each condition: holds, fails, too few rows ----


def test_every_condition_is_listed_with_its_needed_rows():
    assert list(CONDITIONS) == list(NEEDED)
    assert {key for item in CONDITIONS.values() for key in item.series} == set(SERIES)


@pytest.mark.parametrize("exchange", ["TWSE", "TPEx"])
@pytest.mark.parametrize("code", list(CONDITIONS))
def test_a_condition_holds_on_rising_indexes(code, exchange):
    history, session = _scenario("up", NEEDED[code])
    assert _result(history, session, code, exchange) == RuleEvaluation(True, "passed")
    history, session = _scenario("up", 300)
    assert _result(history, session, code, exchange) == RuleEvaluation(True, "passed")


@pytest.mark.parametrize("exchange", ["TWSE", "TPEx"])
@pytest.mark.parametrize("code", list(CONDITIONS))
def test_a_condition_fails_on_falling_indexes(code, exchange):
    history, session = _scenario("down", 300)
    assert _result(history, session, code, exchange) == RuleEvaluation(
        False, "rejected", (f"index_condition_{code}_not_met",)
    )


@pytest.mark.parametrize("code", list(CONDITIONS))
def test_a_condition_without_enough_rows_is_data_incomplete(code):
    history, session = _scenario("up", NEEDED[code] - 1)
    result = _result(history, session, code)
    assert result.passed is False and result.state == "data_incomplete"
    (reason,) = result.reasons
    if code == "c3a":  # needs one row: none at all is a missing bar
        assert reason == "tx_bar_missing"
    else:
        assert reason.endswith("_closes_insufficient")
    # No row of a Taiwan series on the session itself: missing, not failed.
    history, session = _scenario("up", 300)
    later = session + timedelta(days=1)
    if CONDITIONS[code].series[0] not in ("SPX", "SOX"):
        result = _result(history, later, code)
        assert result.state == "data_incomplete"
        assert result.reasons[0].endswith("_bar_missing")


@pytest.mark.parametrize("code", list(CONDITIONS))
@pytest.mark.parametrize("bad", [None, float("nan"), 0.0])
def test_a_missing_close_inside_the_window_is_data_incomplete(code, bad):
    history, session = _scenario("up", 300)
    for key in CONDITIONS[code].series:
        dates, closes, _ = history.series(key)
        closes[len(closes) - NEEDED[code]] = bad
    result = _result(history, session, code)
    assert result.state == "data_incomplete"
    assert result.reasons[0].endswith("_close_missing_or_non_finite")
    # One older than the window is not read.
    history, session = _scenario("up", 300)
    for key in CONDITIONS[code].series:
        _, closes, _ = history.series(key)
        closes[len(closes) - NEEDED[code] - 1] = bad
    assert _result(history, session, code).passed


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        # MA240 84.98, MA60 99.92, 60-row high 100: above the year line only,
        # 5% off the high.
        ([80.0] * 240 + [100.0] * 59 + [95.0], {"c1": True, "c5": False, "c6": True}),
        # The same with an 11% fall from the high.
        ([80.0] * 240 + [100.0] * 59 + [89.0], {"c1": True, "c5": False, "c6": False}),
        # MA240 115.0, MA60 100.02: above MA60 (R3) but under the year line.
        (
            [120.0] * 240 + [100.0] * 59 + [101.0],
            {"c1": False, "c5": False, "c6": True},
        ),
        # Above both.
        ([80.0] * 240 + [100.0] * 59 + [101.0], {"c1": True, "c5": True, "c6": True}),
    ],
    ids=["year_line_only", "deep_fall", "ma60_only", "both"],
)
def test_the_taiex_conditions_read_their_own_windows(closes, expected):
    days = _weekdays(len(closes))
    history = IndexHistory({"TAIEX": _rows_of(days, closes)})
    view = IndexView(history, days[-1], "TWSE")
    assert {code: view.result(code).passed for code in expected} == expected


# ---- C2／C7: the stock's own market ----


@pytest.mark.parametrize("code", ["c2", "c7"])
def test_listed_and_otc_stocks_read_their_own_market_index(code):
    days = _weekdays(300)
    session = days[-1]
    up = [1000.0 + n for n in range(300)]
    down = [2000.0 - n for n in range(300)]
    history = IndexHistory({"TAIEX": _rows_of(days, up), "TPEX": _rows_of(days, down)})
    assert _result(history, session, code, "TWSE").passed
    assert _result(history, session, code, "TPEx").state == "rejected"
    history = IndexHistory({"TAIEX": _rows_of(days, down), "TPEX": _rows_of(days, up)})
    assert _result(history, session, code, "TWSE").state == "rejected"
    assert _result(history, session, code, "TPEx").passed
    # A TPEx stock with no TPEX rows is data_incomplete even when TAIEX holds.
    history = IndexHistory({"TAIEX": _rows_of(days, up)})
    assert _result(history, session, code, "TPEx") == RuleEvaluation(
        False, "data_incomplete", ("tpex_bar_missing",)
    )
    for exchange in (None, "US", "TAIFEX"):
        assert _result(history, session, code, exchange) == RuleEvaluation(
            False, "data_incomplete", (MARKET_INDEX_UNKNOWN,)
        )
    # The other conditions read the same TAIEX for both markets.
    history = IndexHistory({"TAIEX": _rows_of(days, up), "TPEX": _rows_of(days, down)})
    assert _result(history, session, "c1", "TPEx").passed


# ---- C3: the near-month TX series and its rolls ----


def test_c3_compares_the_same_days_near_month_across_a_roll():
    roll = third_wednesday(2026, 3)  # 2026-03-18: the April contract from today
    assert (
        near_month(roll) == "202604"
        and near_month(roll - timedelta(days=1)) == "202603"
    )
    days = _weekdays(40, roll + timedelta(days=14))
    at = days.index(roll)
    taiex = [20000.0] * len(days)
    # The March contract trades 50 under TAIEX, the April one 100 over it.
    tx = [19950.0] * at + [20100.0] * (len(days) - at)
    # One roll in the window (the February one is before it in the stored rows).
    months = ["202603"] * at + ["202604"] * (len(days) - at)
    history = IndexHistory(
        {"TAIEX": _rows_of(days, taiex), "TX": _rows_of(days, tx, months)}
    )
    assert _result(history, days[at - 1], "c3a").state == "rejected"
    assert _result(history, roll, "c3a").passed
    # MA20 over the stored closes as they are: a window with 19 March rows and
    # the roll day's April close is above its average (19957.5).  Adjusted
    # for the 150-point roll gap it would be flat and fail.
    assert _result(history, days[at - 1], "c3b").state == "rejected"  # flat
    assert _result(history, roll, "c3b").passed
    (item,) = history.rolls()
    assert item["last_day"] == days[at - 1] and item["first_day"] == roll
    assert (item["last_month"], item["first_month"]) == ("202603", "202604")
    assert item["last_basis"] == -50.0 and item["first_basis"] == 100.0
    assert item["basis_jump"] == 150.0
    # Without a TAIEX row on the session the basis is data_incomplete.
    history = IndexHistory({"TX": _rows_of(days, tx, months)})
    assert _result(history, roll, "c3a") == RuleEvaluation(
        False, "data_incomplete", ("taiex_bar_missing",)
    )


# ---- C4: the US row before the signal date ----


def _us(rows: dict[date, float]) -> IndexHistory:
    return IndexHistory(
        {
            "SOX": {day: (close, None) for day, close in rows.items()},
            "SPX": {day: (close, None) for day, close in rows.items()},
        }
    )


@pytest.mark.parametrize("code", ["c4a", "c4b"])
def test_c4_reads_the_newest_us_row_before_the_signal_date(code):
    # Taipei Tuesday 2026-01-20; US Monday 2026-01-19 (MLK Day) has no row,
    # so Friday 01-16 is the row read.
    session = date(2026, 1, 20)
    friday = date(2026, 1, 16)
    us_days = _weekdays(80, friday)
    rising = {day: 1000.0 + n for n, day in enumerate(us_days)}
    # A same-day row and later rows that would fail the condition are not read.
    later = {session: 1.0, date(2026, 1, 21): 1.0, date(2026, 1, 22): 1.0}
    assert _result(_us(rising | later), session, code).passed
    # The Friday row decides: low on Friday, the condition fails.
    low_friday = dict(rising) | {friday: 500.0}
    assert _result(_us(low_friday | later), session, code).state == "rejected"
    # A row dated the signal date alone is never read: nothing before is missing.
    assert (
        _result(_us({session: 1000.0}), session, code)
        .reasons[0]
        .endswith("_bar_missing")
    )
    # 59 rows before the signal date: too few.
    short = {day: close for day, close in list(rising.items())[-59:]}
    assert (
        _result(_us(short | later), session, code)
        .reasons[0]
        .endswith("_closes_insufficient")
    )


@pytest.mark.parametrize("code", ["c4a", "c4b"])
def test_c4_refuses_a_stale_us_row(code):
    session = date(2026, 1, 20)
    for gap, state in (
        (US_STALE_DAYS, "passed"),
        (US_STALE_DAYS + 1, "data_incomplete"),
    ):
        last = session - timedelta(days=gap)
        rows = {day: 1000.0 + n for n, day in enumerate(_weekdays(80, last))}
        result = _result(_us(rows), session, code)
        assert result.state == state
        if state == "data_incomplete":
            assert result.reasons[0].endswith("_bar_stale")


def test_us_rows_never_reach_the_taiwan_conditions():
    history, session = _scenario("up", 300)
    for key in ("SPX", "SOX"):
        _, closes, _ = history.series(key)
        closes[:] = [None] * len(closes)
    for code in ("c1", "c2", "c3a", "c3b", "c5", "c6", "c7"):
        assert _result(history, session, code).passed


# ---- the condition on top of v3 ----


@pytest.mark.parametrize(("key", "code"), all_conditions())
def test_a_holding_condition_returns_the_v3_result_unchanged(key, code):
    rule = BASES[key].rule
    up, session = _scenario("up", 300)
    down, _ = _scenario("down", 300)
    short, _ = _scenario("up", NEEDED[code] - 1)
    views = {
        "up": IndexView(up, session, "TPEx"),
        "down": IndexView(down, session, "TPEx"),
        "short": IndexView(short, session, "TPEx"),
    }
    reason = CONDITIONS[code].reason
    rng = random.Random(567)
    seen = set()
    for _ in range(DRAWS):
        arguments = _random_arguments(key, rng)
        base = rule(**arguments)
        seen.add(base.state)
        held = evaluate_with_condition(rule, code, index_view=views["up"], **arguments)
        assert held == base
        failed = evaluate_with_condition(
            rule, code, index_view=views["down"], **arguments
        )
        if base.state == "data_incomplete":
            assert failed == base
        else:
            assert failed == RuleEvaluation(False, "rejected", (*base.reasons, reason))
        missing = evaluate_with_condition(
            rule, code, index_view=views["short"], **arguments
        )
        own = base.reasons if base.state == "data_incomplete" else ()
        assert missing.state == "data_incomplete"
        assert (
            missing.reasons[: len(own)] == own and len(missing.reasons) == len(own) + 1
        )
    assert seen == {"passed", "rejected", "data_incomplete"}


def test_combine_keeps_the_three_outcomes():
    passed = RuleEvaluation(True, "passed")
    rejected = RuleEvaluation(False, "rejected", ("x",))
    missing = RuleEvaluation(False, "data_incomplete", ("y",))
    failed = RuleEvaluation(False, "rejected", ("index_condition_c1_not_met",))
    short = RuleEvaluation(False, "data_incomplete", ("taiex_closes_insufficient",))
    for result in (passed, rejected, missing):
        assert combine(result, passed) == result
    assert combine(passed, failed) == RuleEvaluation(
        False, "rejected", ("index_condition_c1_not_met",)
    )
    assert combine(rejected, failed).reasons == ("x", "index_condition_c1_not_met")
    assert combine(missing, failed) == missing
    assert combine(passed, short) == short
    assert combine(rejected, short) == short
    assert combine(missing, short).reasons == ("y", "taiex_closes_insufficient")


# ---- strategies, the history and the registry ----


@pytest.mark.parametrize(("key", "code"), all_conditions())
def test_a_condition_config_differs_only_by_name_kind_and_its_condition(key, code):
    canonical = json.loads(json.dumps(BASES[key].config))
    strategy = condition_strategy(key, code, IndexHistory({}))
    config = json.loads(json.dumps(strategy.config))

    assert config.pop("name") == f"{key}_index_{code}" == strategy.key
    assert config.pop("kind") == f"{canonical['kind']}_index_{code}"
    snapshot = config.pop("index_condition")
    assert snapshot["base_strategy"] == key
    assert snapshot["base_version"] == BASES[key].version
    assert snapshot["condition"] == code and snapshot["issue"] == 567
    assert snapshot["missing_policy"] == "data_incomplete"
    assert snapshot["series"] == list(CONDITIONS[code].series)
    del canonical["name"], canonical["kind"]
    assert config == canonical


def test_the_bases_are_the_v3_modules_whatever_the_registry_holds():
    # Run 2759 measured these two; a newer registered version must not move
    # the research versions (or their baselines) onto itself.
    assert BASES == {"breakout_v3": BREAKOUT_V3, "pullback_v3": PULLBACK_V3}
    assert [key for key, _ in all_conditions()][:: len(CONDITIONS)] == list(BASES)
    assert research.condition_items(["pullback_v3:c1"]) == [("pullback_v3", "c1")]


def test_condition_strategies_leave_the_registry_and_canonical_snapshot_alone():
    before = canonical_config_snapshot()
    registered = dict(REGISTRY)
    registry = with_conditions(dict(BASES), all_conditions(), IndexHistory({}))

    assert REGISTRY == registered
    assert not any("_index_" in key for key in REGISTRY)
    assert canonical_config_snapshot() == before
    assert list(registry)[:2] == list(BASES)
    assert len(registry) == 2 + 2 * len(CONDITIONS)
    assert len({strategy.kind for strategy in registry.values()}) == len(registry)
    with pytest.raises(ValueError, match="already in the registry"):
        with_conditions(registry, [("breakout_v3", "c1")], IndexHistory({}))


def test_a_condition_strategy_needs_a_score_date_and_an_instrument():
    history, session = _scenario("up", 300)
    down, _ = _scenario("down", 300)
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
    for key in BASES:
        base = BASES[key].evaluate(inputs)
        held = condition_strategy(key, "c2", history)
        failed = condition_strategy(key, "c2", down)
        with pytest.raises(RuntimeError, match="without a score date"):
            held.evaluate(inputs)
        history.set_session(session)
        with pytest.raises(RuntimeError, match="without a score date"):
            held.evaluate(inputs)  # no instrument yet
        history.set_instrument("TPEx")
        down.set_session(session)
        down.set_instrument("TWSE")
        assert held.evaluate(inputs) == base
        assert failed.evaluate(inputs).reasons[-1] == "index_condition_c2_not_met"
        assert held.actionable_levels(inputs) == BASES[key].actionable_levels(inputs)
        history.set_instrument(None, active=False)
        history.set_session(None)
        down.set_session(None)
    assert BASES["breakout_v3"].evaluate(inputs).passed


def test_the_view_of_a_score_date_is_shared_by_one_market():
    history, session = _scenario("up", 300)
    history.set_session(session)
    history.set_instrument("TWSE")
    first = history.view()
    history.set_instrument("TPEx")
    assert history.view() is not first
    history.set_instrument("TWSE")
    assert history.view() is first
    history.set_session(session - timedelta(days=1))
    history.set_instrument("TWSE")
    assert history.view() is not first


# ---- the sample split and the proposal rule, fixed before any result ----


def test_the_split_is_the_issues():
    assert (EXPLORATION.start, EXPLORATION.end) == (
        date(2024, 9, 30),
        date(2025, 12, 31),
    )
    assert (VALIDATION.start, VALIDATION.end) == (date(2026, 1, 1), None)
    assert segment_of(date(2024, 9, 27)) is None
    assert segment_of(date(2024, 9, 30)) == "exploration"
    assert segment_of(date(2025, 12, 31)) == "exploration"
    assert segment_of(date(2026, 1, 2)) == "validation"
    assert segment_of(date(2026, 11, 6)) == "validation"
    assert [
        code for code, item in CONDITIONS.items() if not item.validation_independent
    ] == [
        "c2",
        "c5",
        "c6",
    ]


def _comparison(**changes) -> Comparison:
    values = dict(
        removed=MIN_REMOVED,
        t20_n=MIN_T20,
        t20_median=-0.01,
        baseline_t20_median=-0.012,
        invalidated_share=0.50,
        baseline_invalidated_share=0.52,
    )
    return Comparison(**(values | changes))


def test_the_proposal_rule():
    better = _comparison()
    assert judge_exploration(better) == "selected"
    assert judge_validation(better) == "not_reversed"
    tied = _comparison(t20_median=-0.012, invalidated_share=0.52)
    assert judge_exploration(tied) == "not_selected"  # strictly better to select
    assert judge_validation(tied) == "not_reversed"  # no worse to hold
    worse = _comparison(invalidated_share=0.53)
    assert judge_exploration(worse) == "not_selected"
    assert judge_validation(worse) == "reversed"
    for thin in (
        _comparison(removed=MIN_REMOVED - 1),
        _comparison(t20_n=MIN_T20 - 1),
        _comparison(t20_median=None),
    ):
        assert judge_exploration(thin) == judge_validation(thin) == "insufficient"
    assert proposable(better, better)
    assert not proposable(better, worse)
    assert not proposable(better, _comparison(removed=0))  # cannot judge: no
    assert not proposable(tied, better)


# ---- backtest on the verify fixture database ----


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory):
    dest = tmp_path_factory.mktemp("index-conditions")
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


def _synthetic(days: list[date]) -> IndexHistory:
    """TAIEX always rising; TPEX well above or below 100 by date (C2 per market)."""

    rng = random.Random(567)
    before = _weekdays(300, days[0] - timedelta(days=1))
    taiex = _rows_of(
        before + days, [1000.0 + n for n in range(len(before) + len(days))]
    )
    tpex = _rows_of(before, [100.0] * len(before)) | _rows_of(
        days, [rng.choice((60.0, 160.0)) for _ in days]
    )
    return IndexHistory({"TAIEX": taiex, "TPEX": tpex})


def test_a_research_backtest_keeps_v3_where_the_condition_holds(backtest_db):
    factory, _path = backtest_db
    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
        markets = dict(db.execute(select(Instrument.id, Instrument.exchange)).all())
    start, end = days[-45], days[-1]
    history = _synthetic(days[days.index(start) :])
    items = [(key, code) for key in BASES for code in ("c2", "c3a")]
    registry = with_conditions(dict(BASES), items, history)
    with (
        research.score_dates(research.SessionTargets(history), pipeline),
        research.instruments(history, pipeline),
    ):
        result = pipeline.backtest(start, end, registry=registry)
    assert pipeline._generate_signals.__name__ == "_generate_signals"
    assert pipeline._upsert_signal.__name__ == "_upsert_signal"
    assert history.session is None and not history.instrument_set
    assert result["run"]["status"] == "success"
    assert result["run"]["request_key"].endswith(":research:" + ",".join(registry))

    rows = _rows(factory, result["run"]["id"])
    compared = {"passed": 0, "rejected": 0, "data_incomplete": 0}
    by_market = {"TWSE": set(), "TPEx": set()}
    for key in BASES:
        base_kind = BASES[key].kind
        for code in ("c2", "c3a"):
            strategy = registry[f"{key}_index_{code}"]
            for (name, instrument_id, day), row in rows.items():
                if name != strategy.key:
                    continue
                base = rows[(key, instrument_id, day)]
                held = history.view_at(day, markets[instrument_id]).result(code)
                own = row["evidence"][strategy.kind]
                base_state = base["evidence"][base_kind]
                assert row["evidence"][base_kind] == base_state
                expected = combine(
                    RuleEvaluation(
                        base_state["state"] == "passed",
                        base_state["state"],
                        tuple(base_state["reasons"]),
                    ),
                    held,
                )
                assert own == {"state": expected.state, "reasons": [*expected.reasons]}
                if code == "c2":
                    by_market[markets[instrument_id]].add(held.state)
                else:  # no TX rows: always data_incomplete
                    assert held.reasons == ("tx_bar_missing",)
                if held.passed:
                    assert own == base_state
                    assert row["status"] == base["status"]
                    assert row["levels"] == base["levels"]
                    assert row["settlements"] == base["settlements"]
                else:
                    assert row["status"] in NOT_ACTIONABLE
                    assert not row["settlements"]
                    if held.state == "data_incomplete":
                        assert row["status"] == "data_incomplete"
                if base["status"] not in NOT_ACTIONABLE:
                    compared[held.state] += 1
    # Listed stocks read the rising TAIEX; OTC stocks the TPEX that flips.
    assert by_market == {"TWSE": {"passed"}, "TPEx": {"passed", "rejected"}}
    assert all(compared.values()), compared


def test_a_report_of_the_run_matches_its_baseline_where_the_condition_holds(
    backtest_db, tmp_path
):
    factory, path = backtest_db
    with factory() as db:
        days = db.scalars(
            select(MarketBar.trading_date).distinct().order_by(MarketBar.trading_date)
        ).all()
    start, end = days[-45], days[-1]
    # The fixture's own index rows, as the research CLI loads them.
    with closing(sqlite3.connect(path)) as connection:
        history = IndexHistory(report.series_rows(connection, SERIES))
    assert history.series("TAIEX")[0] and history.series("TPEX")[0]
    items = [(key, "c2") for key in BASES]
    registry = with_conditions(dict(BASES), items, history)
    with (
        research.score_dates(research.SessionTargets(history), pipeline),
        research.instruments(history, pipeline),
    ):
        run = pipeline.backtest(start, end, registry=registry)["run"]

    result = report.build(path, run["id"])
    assert result["run"]["request_key"] == run["request_key"]
    assert result["run"]["registry"] == list(registry)
    assert list(result["conditions"]) == ["c2"]
    assert set(result["market"]["condition_days"]) == {"c2:TWSE", "c2:TPEx"}
    for item in result["market"]["condition_days"].values():
        assert sum(item["all"]["days"].values()) == 45
    sessions = {key: item["score_sessions"] for key, item in result["split"].items()}
    assert sum(sessions.values()) == 45
    for base, data in result["strategies"].items():
        name = f"{base}_index_c2"
        assert list(data["versions"]) == [base, name]
        scopes = data["versions"][base]["scopes"]
        whole = scopes["all"]
        assert whole["rows"] == sum(scopes[q]["rows"] for q in result["quarters"])
        assert whole["actionable"] == sum(
            scopes[s]["actionable"] for s in ("exploration", "validation")
        )
        parts = data["removed"][name]
        assert whole["actionable"] == sum(
            parts[state]["all"]["actionable"] for state in report.STATES
        )
        check = data["consistency"][name]
        assert check["baseline_on_passed_dates"] == check["condition_actionable"]
        assert check["only_in_baseline"] == check["only_in_condition"] == 0
        assert check["status_or_settlement_differs"] == 0
        judged = data["judgement"][name]
        assert {judged["exploration"]["verdict"], judged["validation"]["verdict"]} <= {
            "selected",
            "not_selected",
            "not_reversed",
            "reversed",
            "insufficient",
        }
        assert judged["validation_independent"] is False
    out = tmp_path / "out"
    argv = ["--db", str(path), "--run-id", str(run["id"]), "--out", str(out)]
    assert report.main(argv) == 0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert run["request_key"] in summary and "事先切分" in summary
    assert "段別判定" in summary and "美股日期對齊" in summary
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["run"]["id"] == run["id"]
    assert tables["split"]["exploration"]["start"] == "2024-09-30"
    assert (
        (out / "segments.csv").read_text(encoding="utf-8").startswith("condition,state")
    )


def test_the_research_cli_runs_index_conditions_on_the_fixture(fixture_db, tmp_path):
    shutil.copyfile(fixture_db, tmp_path / "stock.db")
    with closing(sqlite3.connect(tmp_path / "stock.db")) as connection:
        (end,) = connection.execute(
            "SELECT max(trading_date) FROM market_bars"
        ).fetchone()
    command = [sys.executable, "-B", str(SCRIPT), "--db", str(tmp_path / "stock.db")]
    command += ["--start", end, "--end", end, "--min-free-gb", "0"]
    result = subprocess.run(
        command + ["--index-condition", "breakout_v3:c2", "pullback_v3:c1"],
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
        "pullback_v3",
        "breakout_v3_index_c2",
        "pullback_v3_index_c1",
    ]
    assert output["status"] == "success" and output["score_sessions"] == 1
    assert output["index_series"]["TAIEX"]["last"] == end
    assert set(output["index_series"]) == set(SERIES)
    assert set(output["strategies"]) == set(output["registry"])
    assert len({item["signals"] for item in output["strategies"].values()}) == 1

    # A condition whose series has no rows at all is refused, not run blind.
    with closing(sqlite3.connect(tmp_path / "stock.db")) as connection:
        connection.execute(
            "DELETE FROM market_bars WHERE instrument_id IN "
            "(SELECT id FROM instruments WHERE exchange = 'US' AND symbol = 'SOX')"
        )
        connection.commit()
    refused = subprocess.run(
        command + ["--index-condition", "pullback_v3:c4a", "breakout_v3:c4b"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert refused.returncode == 2
    assert json.loads(refused.stdout) == {"refused": ["no market_bars rows for SOX"]}


def test_an_unknown_index_condition_strategy_is_refused():
    with pytest.raises(research.Refused, match="unknown index-condition"):
        research.condition_items(["breakout_v3:c9"])
    with pytest.raises(research.Refused, match="unknown index-condition"):
        research.condition_items(["breakout_v1:c1"])
    assert research.condition_items(["all"]) == all_conditions()


def test_the_report_refuses_the_production_database(tmp_path):
    production = tmp_path / "stock-lab-data" / "stock.db"
    production.parent.mkdir()
    production.write_bytes(b"")
    argv = ["--db", str(production), "--run-id", "1", "--out", str(tmp_path / "o")]
    assert report.main(argv) == 2
    assert not (tmp_path / "o").exists()


# ---- #855: the overnight conditions ----


def _overnight(us: dict[date, float], sessions: list[date], key: str = "SOX"):
    """SOX (or SPX) rows ``us`` and the Taiwan sessions ``sessions``."""

    return IndexHistory(
        {key: {day: (close, None) for day, close in us.items()}}, sessions
    )


def _us_run(last: date, count: int = 10, close: float = 1000.0) -> dict[date, float]:
    return {day: close for day in _weekdays(count, last)}


def _overnight_result(history: IndexHistory, session: date, code: str):
    return IndexView(history, session, "TWSE").result(code)


def test_the_overnight_conditions_are_the_decided_twelve():
    # 提問 7018248685 §1, decision 7018301183: SOX and SPX, three thresholds
    # each, on the strategies the 08:45 list uses; #567 is left as it was.
    assert list(OVERNIGHT_CONDITIONS) == ["o1", "o2", "o3", "o4", "o5", "o6"]
    assert [item.series for item in OVERNIGHT_CONDITIONS.values()] == [("SOX",)] * 3 + [
        ("SPX",)
    ] * 3
    assert OVERNIGHT_BASES == {"breakout_v3": BREAKOUT_V3, "pullback_v4": PULLBACK_V4}
    assert BASES == {"breakout_v3": BREAKOUT_V3, "pullback_v3": PULLBACK_V3}
    assert overnight_conditions() == [
        (key, code) for key in OVERNIGHT_BASES for code in OVERNIGHT_CONDITIONS
    ]
    assert len(overnight_conditions()) == 12
    # The decided thresholds, written out (decision 7018301183 §3).
    assert OVERNIGHT_THRESHOLDS == (
        ("o1", "SOX", -0.02, True),
        ("o2", "SOX", -0.01, True),
        ("o3", "SOX", 0.01, False),
        ("o4", "SPX", -0.02, True),
        ("o5", "SPX", -0.01, True),
        ("o6", "SPX", 0.01, False),
    )
    assert not set(OVERNIGHT_CONDITIONS) & set(CONDITIONS)
    assert ALL_CONDITIONS == {**CONDITIONS, **OVERNIGHT_CONDITIONS}
    assert all(code in CONDITIONS for _, code in all_conditions())
    assert research.condition_items(["overnight"]) == overnight_conditions()
    assert research.condition_items(["pullback_v4:o1"]) == [("pullback_v4", "o1")]
    with pytest.raises(research.Refused, match="unknown index-condition"):
        research.condition_items(["pullback_v3:o1"])
    with pytest.raises(research.Refused, match="unknown index-condition"):
        research.condition_items(["pullback_v4:c1"])
    assert baselines_of([("breakout_v3", "c1")]) == BASES
    assert baselines_of(overnight_conditions()) == OVERNIGHT_BASES


@pytest.mark.parametrize(
    ("code", "previous", "close", "state"),
    [
        ("o1", 100.0, 98.0, "rejected"),  # −2 % exactly rejects
        ("o1", 100.0, 98.01, "passed"),
        ("o2", 100.0, 99.0, "rejected"),  # −1 % exactly rejects
        ("o2", 100.0, 99.01, "passed"),
        ("o3", 100.0, 101.0, "rejected"),  # +1 % exactly rejects
        ("o3", 100.0, 100.99, "passed"),
        ("o3", 100.0, 90.0, "passed"),
        ("o1", 100.0, 120.0, "passed"),
        ("o4", 100.0, 98.0, "rejected"),  # −2 % exactly rejects
        ("o4", 100.0, 98.01, "passed"),
        ("o5", 100.0, 99.0, "rejected"),  # −1 % exactly rejects
        ("o5", 100.0, 99.01, "passed"),
        ("o6", 100.0, 101.0, "rejected"),  # +1 % exactly rejects
        ("o6", 100.0, 100.99, "passed"),
    ],
)
def test_an_overnight_condition_rejects_at_its_threshold(code, previous, close, state):
    # Taipei Tuesday 2026-03-03, E Wednesday 03-04: the US Tuesday row decides.
    session, entry = date(2026, 3, 3), date(2026, 3, 4)
    us = _us_run(date(2026, 3, 2), close=previous) | {session: close}
    key = OVERNIGHT_CONDITIONS[code].series[0]
    result = _overnight_result(_overnight(us, [session, entry], key), session, code)
    assert result.state == state
    if state == "rejected":
        assert result.reasons == (f"index_condition_{code}_not_met",)


def test_an_overnight_condition_never_reads_the_us_row_dated_the_entry_session():
    # The US close dated E (Taipei T+1) is in only after E's open (about
    # 05:00 on E + 1): a fall that day must not reject T's list.
    session, entry = date(2026, 3, 3), date(2026, 3, 4)
    flat = _us_run(session)
    for later in ({entry: 1.0}, {entry: 1.0, date(2026, 3, 5): 1.0}):
        history = _overnight(flat | later, [session, entry])
        assert _overnight_result(history, session, "o1").passed
        row = IndexView(history, session, None).overnight_row("SOX")
        assert row == {
            "entry": entry,
            "date": session,
            "previous_date": date(2026, 3, 2),
            "return": 0.0,
            "rows": 1,
        }
    # Only the row dated E exists after T − 1: the US market was closed on T,
    # and the E row is not read in its place.
    closed = _us_run(date(2026, 3, 2)) | {entry: 1.0}
    history = _overnight(closed, [session, entry])
    assert _overnight_result(history, session, "o1").passed
    assert IndexView(history, session, None).overnight_row("SOX")["rows"] == 0


def test_an_overnight_condition_does_not_read_the_row_before_the_score_date():
    # T − 1's close was in before T's 21:30 list; with no row in [T, E) the
    # night had no US close (US holiday), so a fall on T − 1 rejects nothing.
    # Thanksgiving: Taipei Thursday 2025-11-27 (no US row), E Friday 11-28.
    session, entry = date(2025, 11, 27), date(2025, 11, 28)
    us = _us_run(date(2025, 11, 25)) | {date(2025, 11, 26): 500.0, entry: 1000.0}
    history = _overnight(us, [session, entry])
    for code in ("o1", "o2", "o3"):
        assert _overnight_result(history, session, code).passed
    row = IndexView(history, session, None).overnight_row("SOX")
    assert row == {"entry": entry, "date": None, "return": None, "rows": 0}


def test_an_overnight_condition_reads_friday_over_a_weekend():
    friday, monday = date(2026, 3, 6), date(2026, 3, 9)
    us = _us_run(date(2026, 3, 5)) | {friday: 970.0}
    history = _overnight(us, [friday, monday])
    row = IndexView(history, friday, None).overnight_row("SOX")
    assert (row["date"], row["entry"], row["rows"]) == (friday, monday, 1)
    assert _overnight_result(history, friday, "o1").state == "rejected"


def test_a_taiwan_holiday_reads_the_newest_us_row_alone():
    # Lunar New Year 2026: T Wednesday 02-11, Taiwan closed 02-12..02-20,
    # E Monday 02-23.  The US rows 02-11..02-20 are all before E's open; the
    # newest (Friday 02-20) decides, over the row before it; the earlier
    # fall is not added up.
    session, entry = date(2026, 2, 11), date(2026, 2, 23)
    us = _us_run(date(2026, 2, 10)) | {
        date(2026, 2, 11): 900.0,  # −10 %: not the newest, not read
        date(2026, 2, 12): 900.0,
        date(2026, 2, 13): 900.0,
        # 02-16 is a US holiday: no row
        date(2026, 2, 17): 900.0,
        date(2026, 2, 18): 900.0,
        date(2026, 2, 19): 900.0,
        date(2026, 2, 20): 891.0,  # −1 %
    }
    history = _overnight(us, [session, entry])
    row = IndexView(history, session, None).overnight_row("SOX")
    assert (row["date"], row["previous_date"], row["rows"]) == (
        date(2026, 2, 20),
        date(2026, 2, 19),
        7,
    )
    assert row["return"] == pytest.approx(-0.01)
    assert _overnight_result(history, session, "o1").passed
    assert _overnight_result(history, session, "o2").state == "rejected"


TUE, WED = date(2026, 3, 3), date(2026, 3, 4)


@pytest.mark.parametrize(
    ("us", "sessions", "reason"),
    [
        # Rows end before T and none after: not collected yet, not a holiday.
        (_us_run(date(2026, 3, 2)), [TUE, WED], "us_sox_overnight_pending"),
        # The row before the overnight one is more than US_STALE_DAYS older.
        (
            {date(2026, 2, 20): 1000.0, TUE: 1000.0},
            [TUE, WED],
            "us_sox_bar_stale",
        ),
        # The only row: no previous close.
        ({TUE: 1000.0}, [TUE, WED], "us_sox_closes_insufficient"),
        # A missing or non-finite close in the pair.
        (
            {date(2026, 3, 2): None, TUE: 1000.0},
            [TUE, WED],
            "us_sox_close_missing_or_non_finite",
        ),
        (
            {date(2026, 3, 2): 1000.0, TUE: float("nan")},
            [TUE, WED],
            "us_sox_close_missing_or_non_finite",
        ),
        # No series at all.
        ({}, [TUE, WED], "us_sox_overnight_pending"),
        # T is the last Taiwan session: E is not known.
        (_us_run(TUE), [date(2026, 3, 2), TUE], NEXT_SESSION_UNKNOWN),
    ],
)
def test_missing_overnight_data_is_data_incomplete(us, sessions, reason):
    for code in ("o1", "o2", "o3"):
        result = _overnight_result(_overnight(us, sessions), TUE, code)
        assert (result.state, result.reasons) == ("data_incomplete", (reason,))


def test_the_stale_limit_of_the_previous_overnight_row():
    for gap, state in (
        (US_STALE_DAYS, "passed"),
        (US_STALE_DAYS + 1, "data_incomplete"),
    ):
        us = {TUE - timedelta(days=gap): 1000.0, TUE: 1000.0}
        assert _overnight_result(_overnight(us, [TUE, WED]), TUE, "o1").state == state


def test_the_entry_session_is_the_next_taiwan_session_not_the_next_weekday():
    # A Taiwan session list without 03-04 (a typhoon day): E is 03-05, so the
    # US rows of 03-03 and 03-04 are both before E, and 03-04 decides.
    us = _us_run(date(2026, 3, 2)) | {TUE: 1000.0, WED: 970.0}
    history = _overnight(us, [TUE, date(2026, 3, 5)])
    row = IndexView(history, TUE, None).overnight_row("SOX")
    assert (row["entry"], row["date"], row["rows"]) == (date(2026, 3, 5), WED, 2)
    assert _overnight_result(history, TUE, "o1").state == "rejected"
    # Without the Taiwan sessions an overnight condition refuses to guess.
    with pytest.raises(RuntimeError, match="Taiwan sessions"):
        _overnight_result(IndexHistory({"SOX": {}}), TUE, "o1")


def test_an_overnight_condition_on_pullback_v4_keeps_its_result_when_it_holds():
    history = _overnight(_us_run(TUE), [TUE, WED])
    strategy = condition_strategy("pullback_v4", "o2", history)
    snapshot = strategy.config["index_condition"]
    assert strategy.key == "pullback_v4_index_o2"
    assert snapshot["base_strategy"] == "pullback_v4"
    assert snapshot["base_version"] == PULLBACK_V4.version
    assert snapshot["issue"] == 855 and snapshot["series"] == ["SOX"]
    assert snapshot["us_market_closed"] == "condition_holds"
    assert type(strategy) is type(PULLBACK_V4)
    with pytest.raises(KeyError):
        condition_strategy("pullback_v3", "o2", history)
    # #567's snapshots keep their issue.
    c4a = condition_strategy("pullback_v3", "c4a", history)
    assert c4a.config["index_condition"]["issue"] == 567
    rng = random.Random(855)
    view = IndexView(history, TUE, "TWSE")
    for _ in range(DRAWS // 10):
        arguments = _random_arguments("pullback_v4", rng)
        assert strategy.rule(**arguments, index_view=view) == PULLBACK_V4.rule(
            **arguments
        )


def _overnight_comparison(**changes) -> OvernightComparison:
    values = {
        "removed": OVERNIGHT_MIN_REMOVED,
        "removed_days": OVERNIGHT_MIN_REMOVED_DAYS,
        "t20_n": OVERNIGHT_MIN_T20,
        "net_mean": 0.01,
        "baseline_net_mean": 0.005,
        "excess_mean": 0.004,
        "baseline_excess_mean": 0.001,
    }
    return OvernightComparison(**(values | changes))


def test_the_two_overnight_judgements():
    assert (TRACKING_COST, COMMON_COST) == (0.003, 0.00585)
    # The sample floor of the decision, written out: 30 removed, 5 days, 100 T+20.
    assert (OVERNIGHT_MIN_REMOVED, OVERNIGHT_MIN_REMOVED_DAYS, OVERNIGHT_MIN_T20) == (
        30,
        5,
        100,
    )
    for field, short, enough in (
        ("removed", 29, 30),
        ("removed_days", 4, 5),
        ("t20_n", 99, 100),
    ):
        assert judge_improved(_overnight_comparison(**{field: short})) == "insufficient"
        assert judge_improved(_overnight_comparison(**{field: enough})) == "improved"
    good = _overnight_comparison()
    assert judge_improved(good) == "improved" and judge_edge(good) == "edge"
    assert good.common_net_mean == pytest.approx(0.01 + 0.003 - 0.00585)
    # The sample floor: one short of each is insufficient, never a pass.
    for field, value in (
        ("removed", OVERNIGHT_MIN_REMOVED - 1),
        ("removed_days", OVERNIGHT_MIN_REMOVED_DAYS - 1),
        ("t20_n", OVERNIGHT_MIN_T20 - 1),
        ("net_mean", None),
        ("baseline_excess_mean", None),
    ):
        item = _overnight_comparison(**{field: value})
        assert judge_improved(item) == judge_edge(item) == "insufficient"
    # Improved needs both (a) and (b) strictly above the baseline.
    for changes in (
        {"net_mean": 0.005},
        {"excess_mean": 0.001},
        {"net_mean": 0.004},
        {"excess_mean": 0.0},
    ):
        item = _overnight_comparison(**changes)
        assert judge_improved(item) == "not_improved"
        assert judge_edge(item) == "no_edge"
    # Improved over a losing baseline is not an edge: (a) at 58.5 bps and (b) > 0.
    losing = _overnight_comparison(
        net_mean=-0.002,
        baseline_net_mean=-0.01,
        excess_mean=0.001,
        baseline_excess_mean=-0.002,
    )
    assert judge_improved(losing) == "improved" and judge_edge(losing) == "no_edge"
    # (a) 0.28 % at 30 bps is −0.005 % at 58.5 bps: no edge.
    thin = _overnight_comparison(net_mean=0.0028, baseline_net_mean=0.0)
    assert judge_improved(thin) == "improved" and judge_edge(thin) == "no_edge"
    # (a) positive but (b) not above 0: no edge.
    beta = _overnight_comparison(excess_mean=0.0, baseline_excess_mean=-0.003)
    assert judge_improved(beta) == "improved" and judge_edge(beta) == "no_edge"
    # Both segments must pass each level.
    assert overnight_verdict(good, good) == {"improved": True, "edge": True}
    assert overnight_verdict(good, losing) == {"improved": True, "edge": False}
    assert overnight_verdict(good, _overnight_comparison(removed=0)) == {
        "improved": False,
        "edge": False,
    }


def test_the_overnight_costs_are_their_sources():
    # (a) is tracking_v2's settlement (its round trip); (a′) is evidence.md's
    # 共同口徑, which evidence_lib's tools use.
    from app.tracking import ROUND_TRIP_TRANSACTION_COST_BPS

    lib = report._evidence_lib()
    assert TRACKING_COST == pytest.approx(ROUND_TRIP_TRANSACTION_COST_BPS / 10_000)
    assert COMMON_COST == pytest.approx(lib.DEFAULT_COST_BPS / 10_000)


def test_the_population_mean_is_the_t20_return_less_tracking_cost(monkeypatch):
    day = date(2025, 3, 3)
    calls = []

    def forward_return(item, at, horizon):
        calls.append((item, at, horizon))
        return {"x": 0.02, "y": -0.01, "z": None}[item]

    fake = type(
        "Lib",
        (),
        {
            "DEFAULT_MIN_LOTS": 7,
            "load_panel": staticmethod(lambda db, start, raw: "panel"),
            "universe": staticmethod(
                lambda panel, at, lots: [("x", 1), ("y", 1), ("z", 1)]
                if (panel, at, lots) == ("panel", day, 7)
                else []
            ),
            "forward_return": staticmethod(forward_return),
        },
    )
    monkeypatch.setattr(report, "_evidence_lib", lambda: fake)
    means = report.population_means(Path("/nowhere"), [day], Path("/raw"))
    # (0.02 − 0.01) / 2 less 30 bps; the one without a T+20 is left out.
    assert means == {day: pytest.approx(0.005 - 0.003)}
    assert {horizon for _, _, horizon in calls} == {20}


def test_the_overnight_numbers_of_a_hand_written_run():
    """(a), (b), the removed group and the fill days on numbers worked by hand."""

    import app.strategies.index_conditions as ic

    t1, e1 = date(2025, 3, 3), date(2025, 3, 4)  # exploration; E is Tuesday
    history = IndexHistory({}, [t1, e1, date(2025, 3, 5), date(2025, 3, 6)])
    a, b, c, d, e = ((n, t1) for n in range(1, 6))
    baseline = {
        a: (101, "x"),
        b: (102, "x"),
        c: (103, "x"),
        d: (104, "x"),
        e: (105, "x"),
    }
    own = {a: (201, "x"), b: (202, "x")}
    parts = {"rejected": [c, d, e], "data_incomplete": []}

    def t20(value):
        return {20: (True, value, "target_1_hit")}

    settled = {
        101: t20(0.02),
        102: t20(0.0),
        103: t20(-0.04),
        104: t20(0.01),
        201: t20(0.02),
        202: t20(0.0),
    }
    population = {t1: -0.01}
    # 103 filled at E, 104 the day after, 105 never.
    executed = {103: e1, 104: date(2025, 3, 5)}
    judged, fills = report.overnight_judgement(
        ic, own, baseline, parts, settled, population, executed, history
    )
    got = judged["exploration"]
    assert (got["removed"], got["removed_days"], got["t20_n"]) == (3, 1, 2)
    # (a): the settled T+20 as stored (already net of tracking's cost).
    assert got["net_mean"] == pytest.approx(0.01)
    assert got["baseline_net_mean"] == pytest.approx(-0.0025)
    assert got["common_net_mean"] == pytest.approx(0.01 + 0.003 - 0.00585)
    # (b): each (a) less its day's population mean.
    assert got["excess_mean"] == pytest.approx(0.02)
    assert got["baseline_excess_mean"] == pytest.approx(0.0075)
    assert got["improved"] == got["edge"] == "insufficient"
    removed = got["removed_group"]
    assert removed["t20_n"] == 2
    assert removed["net_mean"] == pytest.approx(-0.015)
    assert removed["excess_mean"] == pytest.approx(-0.005)
    # The fill day is compared with E, not with T.
    groups = fills["exploration"]
    assert {fill: groups[fill]["signals"] for fill in report.FILLS} == {
        "entry_day": 1,
        "later": 1,
        "not_filled": 1,
    }
    assert groups["entry_day"]["net_mean"] == pytest.approx(-0.04)
    assert groups["later"]["net_mean"] == pytest.approx(0.01)
    assert groups["not_filled"]["t20_n"] == 0
    assert judged["validation"]["removed"] == 0
    assert judged["verdict"] == {"improved": False, "edge": False}


def test_a_report_of_an_overnight_run_on_the_fixture(backtest_db, tmp_path):
    factory, path = backtest_db
    with factory() as db:
        days = pipeline.taiwan_bar_dates(db)
    start, end = days[-45], days[-1]
    with closing(sqlite3.connect(path)) as connection:
        rows = report.series_rows(connection, SERIES)
    assert rows.get("SOX") and rows.get("SPX")
    history = IndexHistory(rows, days)
    items = [(key, code) for key in OVERNIGHT_BASES for code in ("o2", "o6")]
    registry = with_conditions(baselines_of(items), items, history)
    with (
        research.score_dates(research.SessionTargets(history), pipeline),
        research.instruments(history, pipeline),
    ):
        run = pipeline.backtest(start, end, registry=registry)["run"]

    result = report.build(path, run["id"], raw_dir=tmp_path / "raw")
    assert result["overnight_codes"] == ["o2", "o6"]
    assert list(result["strategies"]) == ["breakout_v3", "pullback_v4"]
    alignment = result["market"]["overnight_rows"]
    assert set(alignment) == {"SOX", "SPX"}
    for entry in alignment.values():
        assert entry["read_on_or_after_entry"] == entry["read_before_score_date"] == 0
        assert sum(entry["all"].values()) == 45
        # The last score date has no next session in the copy.
        assert entry["missing_dates"][str(end)] == NEXT_SESSION_UNKNOWN
    for base, data in result["strategies"].items():
        assert not data["judgement"]
        for code in ("o2", "o6"):
            name = f"{base}_index_{code}"
            check = data["consistency"][name]
            assert check["only_in_baseline"] == check["only_in_condition"] == 0
            assert check["status_or_settlement_differs"] == 0
            judged = data["overnight"][name]
            for segment in ("exploration", "validation"):
                item = judged[segment]
                assert item["improved"] in {"improved", "not_improved", "insufficient"}
                assert item["edge"] in {"edge", "no_edge", "insufficient"}
                fills = data["fills"][name][segment]
                assert (
                    sum(cell["signals"] for cell in fills.values()) == item["removed"]
                )
            assert set(judged["verdict"]) == {"improved", "edge"}
    out = tmp_path / "out"
    argv = ["--db", str(path), "--run-id", str(run["id"]), "--out", str(out)]
    assert report.main(argv) == 0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert summary.startswith("# 隔夜美股條件研究（#855）")
    assert "隔夜條件判定" in summary and "隔夜美股讀哪一列" in summary
    assert "依成交日" in summary and "比較次數：隔夜條件 4 組" in summary
    # #567's TX rolls and C4 US dates are not this run's.
    assert "台指期換月" not in summary and "美股日期對齊" not in summary
    csv_text = (out / "overnight.csv").read_text(encoding="utf-8")
    assert csv_text.startswith("series,score_date,entry_session,us_date")
