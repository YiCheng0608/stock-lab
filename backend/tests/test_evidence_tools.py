"""tools/research/feature_evidence.py and candidate_scorecard.py: read-only evidence tables."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base,
    CandidateRun,
    ChipSnapshot,
    CorporateAction,
    DailyCandidate,
    FundamentalSnapshot,
    Instrument,
    MarketBar,
    MonthlyRevenue,
)
from app.strategies import index_conditions

ROOT = Path(__file__).resolve().parents[2]


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
evidence = _tool("feature_evidence")
scorecard = _tool("candidate_scorecard")

BUY = 1.0005
STOCKS = 12
TAIEX, ETF, SPLIT, GAPPED, PAUSED, THIN = 100, 101, 102, 103, 104, 105
FIRST_ID = 1
# Sessions run across the exploration／validation boundary (2025-12-31).
SESSIONS = 200
START = date(2025, 9, 1)


def sessions(count: int = SESSIONS) -> list[date]:
    days, day = [], START
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def rate_of(stock: int) -> float:
    """Stock 1 grows slowest, stock 12 fastest."""

    return 0.0005 * stock


def closes(stock: int, count: int = SESSIONS) -> list[float]:
    """A noisy path around ``rate_of``: neighbours swap places on some days."""

    rng = random.Random(stock)
    values, value = [], 100.0
    for _ in range(count):
        value *= 1.0 + rate_of(stock) + rng.uniform(-0.001, 0.001)
        values.append(value)
    return values


def add_bars(db: Session, instrument_id: int, days, prices, **extra) -> None:
    skip = extra.pop("skip", ())
    suspended = extra.pop("suspended", ())
    volume = extra.pop("volume", 2_000_000)
    scale_from = extra.pop("halve_from", None)
    for index, day in enumerate(days):
        if index in skip:
            continue
        close = prices[index]
        open_ = prices[index - 1] if index else close
        if scale_from is not None and index >= scale_from:
            close, open_ = close / 2, open_ / 2
        db.add(
            MarketBar(
                instrument_id=instrument_id,
                trading_date=day,
                open=open_,
                high=max(open_, close),
                low=min(open_, close),
                close=close,
                adj_close=close,
                volume=volume + index,
                source="test",
                is_suspended=index in suspended,
            )
        )


@pytest.fixture(scope="module")
def copy_db(tmp_path_factory) -> Path:
    """Twelve stocks whose growth rate rises with their id, and five odd ones.

    Foreign buying falls as the id rises (a negative feature) in both
    segments.  Trust buying rises with the id in exploration and falls with it
    in validation (a feature that reverses).  SPLIT is stock 6's path with a
    2:1 split on session 30; GAPPED misses session 40; PAUSED is suspended on
    session 40; THIN trades 500 lots; ETF is not in the universe.
    """

    path = tmp_path_factory.mktemp("copy") / "stock.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = sessions()
    with Session(engine) as db:
        kinds = {stock: "stock" for stock in range(FIRST_ID, STOCKS + 1)}
        kinds |= {
            TAIEX: "index",
            ETF: "etf",
            SPLIT: "stock",
            GAPPED: "stock",
            PAUSED: "ipo",
            THIN: "stock",
        }
        for instrument_id, kind in kinds.items():
            db.add(
                Instrument(
                    id=instrument_id,
                    exchange="TWSE",
                    symbol="TAIEX" if kind == "index" else f"S{instrument_id}",
                    name=f"N{instrument_id}",
                    instrument_type=kind,
                    status="delisted" if instrument_id == GAPPED else "active",
                )
            )
        for stock in range(FIRST_ID, STOCKS + 1):
            add_bars(db, stock, days, closes(stock))
            for index, day in enumerate(days):
                exploring = day <= date(2025, 12, 31)
                db.add(
                    ChipSnapshot(
                        instrument_id=stock,
                        trading_date=day,
                        foreign_buy=float((STOCKS - stock) * 1000),
                        trust_buy=float((stock if exploring else -stock) * 1000),
                        dealer_buy=0.0,
                        margin_balance=1000.0 + index * stock,
                        source="test",
                    )
                )
        add_bars(db, TAIEX, days, closes(3))
        add_bars(db, ETF, days, closes(20))
        add_bars(db, SPLIT, days, closes(6), halve_from=30)
        db.add(
            CorporateAction(
                instrument_id=SPLIT,
                action_date=days[30],
                action_type="split",
                details_json={"price_factor": 0.5},
                source="test",
            )
        )
        add_bars(db, GAPPED, days, closes(6), skip=(40,))
        add_bars(db, PAUSED, days, closes(6), suspended=(40,))
        add_bars(db, THIN, days, closes(6), volume=500_000)
        # Stock 1's revenue of October is announced on session 50, November's on session 70.
        for month, announced, revenue, prior in (
            (date(2025, 10, 1), days[50], 120.0, 100.0),
            (date(2025, 11, 1), days[70], 150.0, 100.0),
        ):
            db.add(
                MonthlyRevenue(
                    instrument_id=1,
                    revenue_month=month,
                    revenue=revenue,
                    prior_year_revenue=prior,
                    announcement_date=announced,
                    source="test",
                    raw_payload_id=1,
                    data_as_of="x",
                )
            )
        # Stock 2's statements carry the year's cumulative EPS.  The third
        # quarter of 2025 counts from session 55; the others from before.
        for period_end, announced, eps in (
            (date(2024, 6, 30), date(2024, 8, 14), 2.0),
            (date(2024, 9, 30), date(2024, 11, 14), 3.0),
            (date(2025, 3, 31), date(2025, 5, 15), 1.2),
            (date(2025, 6, 30), date(2025, 8, 14), 2.6),
            (date(2025, 9, 30), days[55], 4.2),
        ):
            db.add(
                FundamentalSnapshot(
                    instrument_id=2,
                    period_end=period_end,
                    fiscal_period=f"Q{period_end.month // 3}",
                    announcement_date=announced,
                    eps=eps,
                    source="test",
                )
            )
        # Candidates of session 100: v7 ranks the fastest stocks first; the v6
        # run of the same day and the failed run of session 101 do not count.
        runs = (
            (1, days[100], "candidate_score_v7", "success"),
            (2, days[100], "candidate_score_v6", "success"),
            (3, days[101], "candidate_score_v7", "failed"),
            (4, days[-2], "candidate_score_v7", "success"),
        )
        for run_id, day, version, status in runs:
            db.add(
                CandidateRun(
                    id=run_id, trading_date=day, score_version=version, status=status
                )
            )
        picks = {1: (12, 10, 8, 6, 4, 2), 2: (1, 3), 3: (1,), 4: (12,)}
        for run_id, day, version, _status in runs:
            for rank, stock in enumerate(picks[run_id], 1):
                db.add(
                    DailyCandidate(
                        candidate_run_id=run_id,
                        trading_date=day,
                        instrument_id=stock,
                        signal_id=1,
                        strategy="breakout_v3" if rank <= 3 else "pullback_v4",
                        score_version=version,
                        total_score=1.0 - rank / 10,
                        weight_coverage=1.0,
                        rank=rank,
                        # chips ranks them backwards; group is missing.
                        components_json={
                            "technical": {"score": 1.0 - rank / 10},
                            "chips": {"score": rank / 10},
                            "group": {"score": None},
                        },
                        data_as_of=day,
                    )
                )
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def panel(copy_db, tmp_path_factory):
    return lib.load_panel(copy_db, START, tmp_path_factory.mktemp("raw"))


def hold(prices: list[float], at: int, horizon: int) -> float:
    """Open of T+1 (the close of T) to the close of T+horizon."""

    return prices[at + horizon] / (prices[at] * BUY) - 1.0


# --- evidence_lib ----------------------------------------------------------


def test_segments_are_the_index_condition_segments():
    assert [(key, first, last) for key, _label, first, last in lib.SEGMENTS] == [
        (segment.code, segment.start, segment.end)
        for segment in index_conditions.SEGMENTS
    ]


def test_forward_return_is_the_hold_from_next_open(panel):
    item, prices = panel.series[5], closes(5)
    for horizon in lib.HORIZONS:
        assert lib.forward_return(item, 60, horizon) == pytest.approx(
            hold(prices, 60, horizon)
        )
    assert lib.forward_return(item, SESSIONS - 5, 5) is None  # T+5 is not there yet


def test_a_split_does_not_change_the_return(panel):
    plain, split = closes(6), panel.series[SPLIT]
    # Session 28: bought before the split, valued after it.
    assert lib.forward_return(split, 28, 5) == pytest.approx(hold(plain, 28, 5))
    assert split.close[10] == pytest.approx(plain[10] / 2)  # the latest basis
    assert evidence.FEATURES[0][3](split, 40) == pytest.approx(
        plain[40] / plain[20] - 1.0
    )


def test_a_missing_or_suspended_session_is_not_comparable(panel):
    gapped, paused = panel.series[GAPPED], panel.series[PAUSED]
    assert lib.forward_return(gapped, 37, 5) is None  # session 40 has no bar
    assert lib.forward_return(gapped, 30, 5) is not None
    assert lib.forward_return(paused, 37, 5) is None  # session 40 is suspended
    assert lib.forward_return(paused, 40, 5) is not None  # T itself is not in T+1..T+N


def test_universe_is_liquid_trading_stocks(panel):
    days = sessions()
    members = {item.instrument_id for item, _at in lib.universe(panel, days[40], 1000)}
    assert members == {*range(FIRST_ID, STOCKS + 1), SPLIT}
    assert ETF not in panel.series and TAIEX not in panel.series
    # The delisted instrument is in the universe on a day it traded.
    assert GAPPED in {
        item.instrument_id for item, _at in lib.universe(panel, days[41 + 20], 1000)
    }
    assert lib.universe(panel, days[10], 1000) == []  # fewer than 20 bars
    assert THIN in {
        item.instrument_id for item, _at in lib.universe(panel, days[40], 400)
    }


def test_rank_statistics():
    assert lib.average_ranks([10.0, 30.0, 10.0, 20.0]) == [1.5, 4.0, 1.5, 3.0]
    assert lib.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert lib.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert lib.spearman([1, 1, 1], [1, 2, 3]) is None
    values = [0.1, 0.2, 0.3, 0.2, 0.1, 0.3, 0.2, 0.2, 0.1, 0.3]
    naive = lib.t_stat(values)
    assert naive == pytest.approx(
        statistics.fmean(values) / (statistics.stdev(values) / 10**0.5)
    )
    assert lib.t_stat(values, 5) == pytest.approx(naive / 5**0.5)
    assert lib.t_stat(values, 20) is None  # fewer than two non-overlapping days


def test_index_return_and_pending(panel):
    days, prices = sessions(), closes(3)
    assert lib.index_return(panel, days[50], 5) == pytest.approx(
        prices[55] / prices[50] - 1.0
    )
    assert lib.is_pending(panel, days[-3], 5) and not lib.is_pending(panel, days[-6], 5)


# --- features --------------------------------------------------------------


def feature(key: str):
    return next(function for name, *_rest, function in evidence.FEATURES if name == key)


def test_price_and_chip_features(panel):
    item, prices = panel.series[4], closes(4)
    assert feature("momentum_60")(item, 80) == pytest.approx(
        prices[80] / prices[20] - 1
    )
    assert feature("momentum_60")(item, 59) is None
    assert feature("high_gap_60")(item, 80) == pytest.approx(0.0)  # a new high
    mean_volume = statistics.fmean(2_000_000 + index for index in range(60, 80))
    assert feature("volume_ratio")(item, 80) == pytest.approx(
        (2_000_000 + 80) / mean_volume
    )
    # Session 80 is in exploration: foreign 8,000 and trust 4,000 a day.
    assert feature("institutional_flow_5")(item, 80) == pytest.approx(
        5 * 12_000 / mean_volume
    )
    assert feature("trust_flow_5")(item, 80) == pytest.approx(5 * 4_000 / mean_volume)
    assert feature("trust_buy_days_5")(item, 80) == 5.0
    assert feature("margin_change_5")(item, 80) == pytest.approx(
        (1000 + 80 * 4) / (1000 + 75 * 4) - 1
    )
    assert feature("short_change_5")(item, 80) is None  # no short balance stored


def test_revenue_counts_from_its_announcement(panel):
    item = panel.series[1]
    yoy = feature("revenue_yoy")
    assert yoy(item, 49) is None  # October's revenue is announced on session 50
    assert yoy(item, 50) == pytest.approx(0.20)
    assert yoy(item, 69) == pytest.approx(0.20)
    assert yoy(item, 70) == pytest.approx(0.50)
    assert feature("revenue_yoy_change")(item, 70) == pytest.approx(0.30)
    assert feature("revenue_high_12")(item, 70) is None  # fewer than 12 months known
    assert yoy(item, 130) is None  # November is stale by then
    assert yoy(panel.series[2], 70) is None


def test_quarterly_eps_is_the_quarters_own_and_counts_from_its_date(panel):
    item, prices = panel.series[2], closes(2)
    # Session 54: the second quarter is the latest known, 2.6 - 1.2 on its own;
    # a year before needs the first quarter of 2024, which is not stored.
    assert feature("eps_yield")(item, 54) == pytest.approx(1.4 * 4 / prices[54])
    assert feature("eps_growth_yield")(item, 54) is None
    # Session 55: the third quarter, 4.2 - 2.6, against 3.0 - 2.0 a year before.
    assert feature("eps_yield")(item, 55) == pytest.approx(1.6 * 4 / prices[55])
    assert feature("eps_growth_yield")(item, 55) == pytest.approx(0.6 / prices[55])
    assert feature("eps_yield")(item, 199) is None  # stale by then
    assert feature("eps_yield")(panel.series[3], 55) is None  # no statement


def test_the_rules_conditions(panel):
    item = panel.series[12]
    assert evidence.breakout_price(item, 80) is True  # a steady climb
    assert evidence.breakout_volume(item, 80) is False
    assert evidence.institutional_ok(item, 80) is True
    # (1000 + 80 * 12) / (1000 + 75 * 12) - 1 is 3.2 %, under the 5 % ceiling.
    assert evidence.margin_ok(item, 80) is True
    assert evidence.margin_ok(item, 4) is None
    assert evidence.breakout_rule(item, 80) is False
    assert evidence.breakout_price(item, 19) is None


def test_quintiles_follow_the_ranks():
    values = [float(value) for value in range(10)]
    excess = [value / 100 for value in values]
    assert evidence.quintile_means(values, excess) == pytest.approx(
        [0.005, 0.025, 0.045, 0.065, 0.085]
    )
    # Two values only: ties and gaps leave some fifths empty.
    tied = evidence.quintile_means([0.0] * 5 + [1.0] * 5, [0.0] * 5 + [0.1] * 5)
    assert tied[0] is None and tied[-1] is None
    assert [value for value in tied if value is not None] == pytest.approx([0.0, 0.1])


# --- feature_evidence ------------------------------------------------------


@pytest.fixture(scope="module")
def evidence_result(copy_db, tmp_path_factory):
    return evidence.build(
        copy_db, START, None, 1000.0, 6, tmp_path_factory.mktemp("raw")
    )


def test_evidence_of_a_feature_that_works(evidence_result):
    table = evidence_result["horizons"]["5"]["features"]["momentum_20"]
    for segment in ("exploration", "validation"):
        assert table[segment]["days"] >= evidence.MIN_DAYS
        assert table[segment]["ic"] > 0.9
        assert table[segment]["spread"] > 0
        quintiles = table[segment]["quintiles"]
        assert quintiles == sorted(quintiles)
    assert table["verdict"] == "evidence"
    assert table["exploration"]["t"] < table["exploration"]["t_naive"]


def test_a_negative_feature_is_evidence_too_and_a_reversal_is_not(evidence_result):
    features = evidence_result["horizons"]["5"]["features"]
    foreign = features["foreign_flow_5"]
    assert foreign["exploration"]["ic"] < -0.9 and foreign["validation"]["ic"] < -0.9
    assert foreign["exploration"]["spread"] < 0
    assert foreign["verdict"] == "evidence"
    trust = features["trust_flow_5"]
    assert trust["exploration"]["ic"] > 0.9 and trust["validation"]["ic"] < -0.9
    assert trust["verdict"] == "reversed"
    # No short balance anywhere: no day, so nothing to tell.
    assert features["short_change_5"]["verdict"] == "cannot_tell"
    assert features["short_change_5"]["exploration"] == {"days": 0}


def test_days_are_split_by_segment_and_quarter(evidence_result):
    tables = evidence_result["horizons"]["5"]
    counts = tables["days"]
    assert counts["exploration"] + counts["validation"] == counts["all"]
    assert counts["all"] == sum(
        count for key, count in counts.items() if key[:2] == "20"
    )
    # Sessions 19..194 have a 20-bar universe and a T+5.
    assert counts["all"] == SESSIONS - 19 - 5
    assert evidence_result["horizons"]["20"]["days"]["all"] == SESSIONS - 19 - 20


def test_conditions_are_measured_against_the_days_universe(evidence_result):
    conditions = evidence_result["horizons"]["5"]["conditions"]
    ok = conditions["institutional_ok"]["exploration"]
    # All twelve stocks with chips pass it every day of exploration.
    assert ok["n"] == STOCKS * ok["days"]
    assert ok["beat"] == pytest.approx(0.5, abs=0.1)
    assert conditions["breakout_price"]["exploration"]["n"] > 0
    assert conditions["breakout_rule"]["exploration"] == {"days": 0}  # no volume surge
    assert conditions["breakout_rule"]["verdict"] == "cannot_tell"


PASSING = {"days": 100, "ic": 0.05, "t": 3.0, "spread": 0.01}


# One case per row of evidence.md's verdict table, in its order (AC-1 of #643).
@pytest.mark.parametrize(
    ("row", "exploration", "validation", "verdict"),
    [
        ("探索段不足 60 日", {"days": 59}, {}, "cannot_tell"),
        ("探索段 |IC| < 0.02", {"ic": 0.019}, {}, "not_selected"),
        ("探索段 |t| < 2", {"t": 1.9}, {}, "not_selected"),
        ("探索段 t 缺值", {"t": None}, {}, "not_selected"),
        ("探索段五分位差缺值", {"spread": None}, {}, "cannot_tell"),
        ("探索段五分位差異號", {"spread": -0.01}, {}, "not_selected"),
        ("探索段五分位差為 0", {"spread": 0.0}, {}, "not_selected"),
        ("驗證段不足 60 日", {}, {"days": 59}, "cannot_tell"),
        ("驗證段 IC 異號", {}, {"ic": -0.01, "spread": -0.01}, "reversed"),
        ("驗證段 IC 為 0", {}, {"ic": 0.0}, "not_selected"),
        ("驗證段五分位差缺值", {}, {"spread": None}, "cannot_tell"),
        ("驗證段五分位差異號", {}, {"spread": -0.01}, "weak"),
        ("驗證段 |t| < 2", {}, {"t": 1.9}, "weak"),
        ("驗證段 t 缺值", {}, {"t": None}, "weak"),
        ("其餘", {}, {}, "evidence"),
    ],
)
def test_judge_follows_the_table(row, exploration, validation, verdict):
    assert (
        evidence.judge({**PASSING, **exploration}, {**PASSING, **validation}, "ic")
        == verdict
    ), row


def test_judge_signs_and_conditions():
    negative = {"days": 100, "ic": -0.05, "t": -3.0, "spread": -0.01}
    assert evidence.judge(negative, negative, "ic") == "evidence"
    assert evidence.judge(negative, {**negative, "spread": 0.01}, "ic") == "weak"
    # A condition has no spread: the spread rows do not apply.
    condition = {"days": 100, "mean": 0.004, "t": 2.5}
    assert evidence.judge(condition, condition, "mean") == "evidence"
    assert (
        evidence.judge(condition, {**condition, "mean": -0.001}, "mean") == "reversed"
    )
    assert evidence.judge(condition, {**condition, "t": 1.0}, "mean") == "weak"
    assert evidence.judge({**condition, "days": 10}, condition, "mean") == "cannot_tell"


# --- discrete features (#643) -------------------------------------------------


def discrete_day(monkeypatch, values: list[float], excess: list[float]):
    """``day_rows`` for one day where every feature has ``values``."""

    members = [(index, 0) for index in range(len(values))]
    monkeypatch.setattr(
        evidence.lib, "forward_return", lambda item, _at, _horizon: excess[item]
    )
    day = {key: list(values) for key, *_rest in evidence.FEATURES}
    day.update({key: [None] * len(values) for key, *_rest in evidence.CONDITIONS})
    return evidence.day_rows(members, day, 5, 30)


@pytest.mark.parametrize(
    ("values", "low", "high"),
    [
        # A 0～5 count, most names at 0 (trust_buy_days_5): 0 against 1～5.
        ([0.0] * 24 + [1.0] * 6 + [2.0] * 4 + [3.0] * 3 + [4.0] * 2 + [5.0], 24, 16),
        # A 0／1 flag (revenue_high_12).
        ([0.0] * 30 + [1.0] * 10, 30, 10),
    ],
)
def test_a_discrete_feature_has_a_spread(monkeypatch, values, low, high):
    # Higher values do better: excess is the value itself, in percent.
    excess = [value / 100 for value in values]
    mean = statistics.fmean(excess)
    excess = [value - mean for value in excess]
    row = discrete_day(monkeypatch, values, excess)
    day = row["features"]["trust_buy_days_5"]
    assert None in day["q"]  # ties leave a fifth empty
    table = evidence.feature_table([day] * 3, 5)
    expected = statistics.fmean(
        value / 100 for value in values[low:]
    ) - statistics.fmean(value / 100 for value in values[:low])
    assert len(values) - low == high
    assert table["spread"] == pytest.approx(expected)
    assert table["spread"] > 0
    assert table["two_group_days"] == 3


def test_two_groups_cut_between_values():
    # Sides nearest in size; equal values stay together; the lower cut on a tie.
    assert evidence.two_groups([0.0, 0.0, 1.0, 2.0], [0.0, 0.0, 0.1, 0.3]) == (
        pytest.approx([0.0, 0.2])
    )
    assert evidence.two_groups([0.0, 1.0, 2.0], [0.0, 0.3, 0.6]) == pytest.approx(
        [0.0, 0.45]
    )
    assert evidence.two_groups([1.0, 1.0], [0.1, 0.2]) is None


def test_an_empty_middle_fifth_keeps_the_five_groups():
    # A flow with most names at 0: the zeros fill the middle fifth only, so
    # the top and the bottom are there and the spread is version 1's.
    values = [-4.0, -3.0, -2.0, -1.0] + [0.0] * 32 + [1.0, 2.0, 3.0, 4.0]
    excess = [value / 100 for value in values]
    day = evidence.day_spread(values, excess)
    assert day["q"][1] is None and day["q"][3] is None
    assert day["groups"] == 5
    assert day["spread"] == pytest.approx(day["q"][-1] - day["q"][0])
    assert day["spread"] == pytest.approx(0.05)


def test_a_continuous_feature_keeps_its_five_groups(evidence_result):
    for horizon in ("5", "20"):
        for key in ("momentum_20", "foreign_flow_5"):
            for segment in ("exploration", "validation"):
                part = evidence_result["horizons"][horizon]["features"][key][segment]
                assert part["two_group_days"] == 0


def test_the_report_names_its_version(evidence_result):
    assert evidence.VERSION == 2 and evidence_result["version"] == 2
    title, _blank, version = evidence.markdown(evidence_result, "x").splitlines()[:3]
    assert title == "# 特徵證據（feature_evidence 第 2 版）"
    assert "看完第一輪（#619）結果後提出" in version


# --- candidate_scorecard ---------------------------------------------------


@pytest.fixture(scope="module")
def score_result(copy_db, tmp_path_factory):
    return scorecard.build(
        copy_db, None, None, 1000.0, 58.5, tmp_path_factory.mktemp("raw")
    )


def test_scorecard_reads_the_saved_list_of_the_highest_version(score_result):
    # Six of session 100 (v7, not v6's two) and one of the next-to-last session;
    # the failed run's is not read.
    assert score_result["candidates"] == 7 and score_result["days"] == 2
    everything = score_result["horizons"]["5"]["all"]
    assert everything["candidates"] == 7
    assert everything["pending"] == 1 and everything["comparable"] == 6
    assert set(score_result["horizons"]["5"]["score_version"]) == {"candidate_score_v7"}


def test_scorecard_returns_and_baselines(score_result):
    picks = (12, 10, 8, 6, 4, 2)
    everything = score_result["horizons"]["5"]["all"]
    gross = [hold(closes(stock), 100, 5) for stock in picks]
    assert everything["gross"]["mean"] == pytest.approx(statistics.fmean(gross))
    assert everything["net"]["mean"] == pytest.approx(statistics.fmean(gross) - 0.00585)
    # The day's universe: the twelve stocks and SPLIT, PAUSED, GAPPED (stock 6's path).
    universe = [hold(closes(stock), 100, 5) for stock in (*range(1, 13), 6, 6, 6)]
    base = statistics.fmean(universe)
    assert everything["excess_universe"]["mean"] == pytest.approx(
        statistics.fmean(gross) - base
    )
    assert everything["excess_universe"]["positive"] == pytest.approx(
        sum(1 for value in gross if value > base) / len(gross)
    )
    index = closes(3)[105] / closes(3)[100] - 1.0
    assert everything["excess_index"]["mean"] == pytest.approx(
        statistics.fmean(gross) - index
    )
    assert everything["daily_excess"]["days"] == 1
    assert everything["daily_excess"]["t"] is None  # one day says nothing


def test_scorecard_groups(score_result):
    tables = score_result["horizons"]["5"]
    assert tables["rank"]["第 1～5 名"]["comparable"] == 5
    assert tables["rank"]["第 6～10 名"]["comparable"] == 1
    assert tables["rank"]["第 11～20 名"]["candidates"] == 0
    assert tables["strategy"]["breakout_v3"]["candidates"] == 4
    assert tables["strategy"]["pullback_v4"]["comparable"] == 3
    top = tables["rank"]["第 1～5 名"]["gross"]["mean"]
    assert top > tables["rank"]["第 6～10 名"]["gross"]["mean"]


def test_scorecard_ranking(score_result):
    ranking = score_result["horizons"]["5"]["ranking"]
    assert ranking["total"]["days"] == 1
    assert ranking["total"]["ic"] == pytest.approx(1.0)
    assert ranking["technical"]["ic"] == pytest.approx(1.0)
    assert ranking["chips"]["ic"] == pytest.approx(-1.0)
    assert ranking["group"] == {"days": 0, "ic": None, "positive": None, "t": None}
    assert ranking["news_sentiment"]["days"] == 0


# --- the two commands --------------------------------------------------------


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("tool", [evidence, scorecard])
def test_commands_write_reports_and_not_the_database(
    tool, copy_db, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path / "production"))
    before = digest(copy_db)
    out = tmp_path / "out"
    extra = ["--min-names", "6"] if tool is evidence else []
    code = tool.main(["--db", str(copy_db), "--out", str(out), *extra])
    assert code == 0
    assert digest(copy_db) == before
    assert not list(copy_db.parent.glob("stock.db-*"))
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["command"].startswith(f"python tools/research/{tool.__name__}.py")
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "## T+5" in summary and "## 樣本限制" in summary
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["out"]


@pytest.mark.parametrize("tool", [evidence, scorecard])
def test_commands_refuse_the_production_database(
    tool, copy_db, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("STOCK_DATA_DIR", str(copy_db.parent))
    code = tool.main(["--db", str(copy_db), "--out", str(tmp_path / "out")])
    assert code == 2
    assert "refused" in json.loads(capsys.readouterr().out)
    assert not (tmp_path / "out").exists()


def test_scorecard_without_candidates(tmp_path):
    path = tmp_path / "copy" / "stock.db"
    path.parent.mkdir()
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    result = scorecard.build(path, None, None, 1000.0, 58.5, tmp_path / "raw")
    assert result["candidates"] == 0 and result["horizons"] == {}
    assert "0 檔次" in scorecard.markdown(result, "x")
