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
from app.strategies.index_conditions import (
    BASES,
    CONDITIONS,
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
