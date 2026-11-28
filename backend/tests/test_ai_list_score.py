"""Scoring the AI list (#1147): ai_list_score_v1 worked by hand.

List date L is Tuesday 2026-12-01 and D Wednesday 2026-12-02 (session 1), as
test_premarket_score; the fixture has 20 weekday sessions from D.  Every
expected number is the arithmetic of the spec (docs/spec/ai_list.md 對答案):
a D-open hold buys +5 bps and sells -5 bps, 30 bps round trip; a tracking_v2
hold to the horizon close sells at the close without slippage.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from test_premarket_score import (
    D,
    L,
    SESSIONS,
    bar,
    cli_main,
    dividend,
    hold,
    instrument,
    levels,
    path,
    tracked,
)

from app import ai_list_score as score
from app import premarket_score as v1
from app.db import Base, enable_sqlite_foreign_keys
from app.models import (
    AiListPick,
    AiListReading,
    AiListScore,
    CandidateRun,
    DailyCandidate,
    Signal,
)
from worker import ai_list_score, ai_list_score_report, pipeline, schedule_runs


def approx(value):
    """The stored values are rounded to 8 decimals (app.premarket_score._round)."""

    return pytest.approx(value, abs=1e-8)


SPEC = Path(__file__).resolve().parents[2] / "docs" / "spec" / "ai_list.md"


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session


def display(kind, low, high, stop, target):
    return {
        "entry": {"type": kind, "low": low, "high": high},
        "stop": stop,
        "target_1": target,
        "target_2": None,
        "risk_reward": 1.5,
        "valid_sessions": 3,
        "valid_until": SESSIONS[2].isoformat(),
    }


@pytest.fixture
def world(db):
    """TAIEX and the stocks: the picks A B C E F and R, on the rule list only."""

    taiex = instrument(db, "TAIEX", "index")
    bar(db, taiex, L, 20000, 20000, 20000, 20000, source="twse_index_ohlcv")
    bar(db, taiex, D, 20000, 20250, 19950, 20200, source="twse_index_ohlcv")
    for day in SESSIONS[1:]:
        bar(db, taiex, day, 20500, 20500, 20500, 20500, source="twse_index_ohlcv")
    stocks = {}
    # A: AI breakout 100 (no chase 102) fills at the open 101; the rule's
    # breakout 101.5 fills at 101.5 (D's high 102).  Then 102 to the end.
    stocks["A"] = instrument(db, "A")
    path(db, stocks["A"], 99, (101, 102, 100, 101), 102)
    # B: AI breakout 50 (no chase 51) opens 52: not applicable today
    # (gap_above_entry_high), still tracked: fills at the open 52.
    stocks["B"] = instrument(db, "B")
    path(db, stocks["B"], 50, (52, 53, 51.5, 52.5), 52)
    # C: AI pullback 30-31 fills at the open 30.5, then 29 (stop 28 untouched);
    # on the rule list without rule levels.
    stocks["C"] = instrument(db, "C")
    path(db, stocks["C"], 31, (30.5, 31, 30, 30.5), 29)
    # E: its levels failed the check: a D-open hold only.
    stocks["E"] = instrument(db, "E")
    path(db, stocks["E"], 20, (20, 20.5, 19.5, 20), 21)
    # F: AI breakout 10 opens 9.4, under the stop 9.5: not applicable, never
    # fills (high 9.6, then 9.5).  Its facts flag a corporate action L..D.
    stocks["F"] = instrument(db, "F")
    path(db, stocks["F"], 10, (9.4, 9.6, 9.3, 9.5), 9.5)
    # R: on the rule list, not picked: breakout 40 fills at the open 40.
    stocks["R"] = instrument(db, "R")
    path(db, stocks["R"], 40, (40, 40.5, 39.5, 40), 40)
    db.flush()
    return stocks


RULE_A = levels("breakout", 101.5, 101.5, 95, 110)
RULE_R = levels("breakout", 40, 40, 38, 44)
PICKS = (
    # symbol, on rule list, setup, basis, confidence, display levels, rule levels
    (
        "A",
        True,
        "breakout",
        ["technical", "chips"],
        "medium",
        display("breakout", 100, 102, 95, 110),
        RULE_A,
    ),
    (
        "B",
        False,
        "breakout",
        ["news", "technical"],
        "high",
        display("breakout", 50, 51, 47, 56),
        None,
    ),
    (
        "C",
        True,
        "pullback_support",
        ["technical"],
        "medium",
        display("pullback", 30, 31, 28, 34),
        None,
    ),
    ("E", False, "news_catalyst", ["news"], "low", None, None),
    (
        "F",
        False,
        "breakout",
        ["sector", "technical"],
        "low",
        display("breakout", 10, 10.2, 9.5, 12),
        None,
    ),
)


def rule_list(db, stocks, members=(("A", RULE_A), ("C", None), ("R", RULE_R))):
    run = CandidateRun(trading_date=L, score_version="fixture")
    db.add(run)
    db.flush()
    for rank, (symbol, _levels) in enumerate(members, start=1):
        signal = Signal(
            signal_key=f"fixture-{symbol}",
            signal_date=L,
            instrument_id=stocks[symbol].id,
        )
        db.add(signal)
        db.flush()
        db.add(
            DailyCandidate(
                candidate_run_id=run.id,
                trading_date=L,
                instrument_id=stocks[symbol].id,
                signal_id=signal.id,
                strategy="fixture",
                score_version="fixture",
                total_score=80.0,
                weight_coverage=1.0,
                rank=rank,
                data_as_of=L,
            )
        )
    db.flush()
    return run, dict(members)


def reading(
    db,
    stocks,
    *,
    picks=PICKS,
    role="champion",
    version="ai_list_v1",
    stance="bullish",
    market_basis=("tx_night", "us"),
    with_rule_list=True,
    status="done",
    facts=None,
):
    now = datetime(2026, 12, 2, 0, 25)
    run, rule_levels = rule_list(db, stocks) if with_rule_list else (None, {})
    facts = facts or {"F": {"corporate_action_on_session": True}}
    candidates = []
    for symbol, listed, *_rest in picks:
        item = {"symbol": symbol, "on_today_list": listed}
        item["level_facts"] = {
            "corporate_action_on_session": False,
            **facts.get(symbol, {}),
        }
        if symbol in rule_levels:
            item["strategy_levels"] = rule_levels[symbol] or {"status": "no_levels"}
        candidates.append(item)
    if "R" in rule_levels:
        candidates.append(
            {"symbol": "R", "on_today_list": True, "strategy_levels": rule_levels["R"]}
        )
    row = AiListReading(
        session_date=D,
        list_date=L,
        role=role,
        sequence=db.scalar(select(func.count(AiListReading.id))) + 1,
        trigger="scheduler",
        prompt_version=version,
        prompt_sha256="0" * 64,
        schema_sha256="0" * 64,
        model_alias="sonnet",
        llm_model="claude-sonnet-5-5",
        pool_phase="morning",
        cutoff_at=now,
        input_hash="0" * 64,
        input_json={
            "pool": {"today_list_run_id": run.id if run else None},
            "candidates": candidates,
        },
        status=status,
        output_json={"market": {"stance": stance, "confidence": "medium"}}
        if status == "done"
        else None,
        market_method_json=list(market_basis) if status == "done" else None,
        checks_json={},
        attempts=1,
        attempts_json=[],
        duration_ms=1000,
        usage_json={},
        started_at=now,
        finished_at=now,
    )
    db.add(row)
    db.flush()
    if status != "done":
        return row
    for rank, (symbol, listed, setup, basis, confidence, shown, rule) in enumerate(
        picks, start=1
    ):
        db.add(
            AiListPick(
                reading_id=row.id,
                session_date=D,
                prompt_version=version,
                role=role,
                rank=rank,
                instrument_id=stocks[symbol].id,
                symbol=symbol,
                pool_sources_json=[],
                on_rule_list=listed,
                setup=setup,
                basis_json=basis,
                basis_primary=basis[0],
                confidence=confidence,
                levels_json={},
                levels_check_json={},
                display_levels_json=shown,
                risk_reward=1.5 if shown else None,
                valid_sessions=3,
                valid_until=SESSIONS[2],
                exit_conditions_json=[],
                reasons_json=[],
                rule_levels_json=rule,
            )
        )
    db.flush()
    return row


def written(db, reading_id=None):
    query = select(AiListScore)
    if reading_id is not None:
        query = query.where(AiListScore.reading_id == reading_id)
    return {
        (row.reading_id, row.scope, row.subject, row.horizon): row.outcome_json
        for row in db.scalars(query)
    }


def run(db, target):
    rows = ai_list_score.score_readings(db, target)
    db.add_all(rows)
    db.commit()
    return rows


# --- AC-1: the rules are pinned ------------------------------------------------------

# score_version -> (sha256 of RULES as JSON, sha256 of the spec section).  A
# change to either fails here: give it a new SCORE_VERSION and pin that one.
PINNED = {
    "ai_list_score_v1": (
        "cda5034953f74e33c3b07a651e19eac048c93beac4854b17ad628e2533bf52f1",
        "0fcbc4fbbd1501d255531d42a91d1124d5fc1d684289bfc909b1240d6d481737",
    ),
}


def spec_section() -> str:
    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^## 對答案\n(.*?)(?=^## )", text, re.S | re.M)
    assert match, "docs/spec/ai_list.md has no 對答案 section"
    return match.group(1)


def test_the_scoring_rules_and_their_spec_are_pinned_to_the_score_version():
    rules = hashlib.sha256(
        json.dumps(score.RULES, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    section = spec_section()
    spec = hashlib.sha256(section.encode()).hexdigest()
    assert score.RULES["score_version"] == score.SCORE_VERSION
    assert f"`{score.SCORE_VERSION}`" in section
    assert PINNED.get(score.SCORE_VERSION) == (rules, spec), (
        "ai_list_score rules or the spec's 對答案 section changed: "
        "new SCORE_VERSION, then pin it here",
        rules,
        spec,
    )


def test_the_constants_the_report_rests_on():
    assert score.MIN_GROUP_COMPARABLE == 20
    assert score.RULES["group_min_comparable"] == 20
    assert score.STOCK_HORIZONS == {"t5": 5, "t20": 20}
    assert score.MARKET_HORIZONS == {"d0": 1, "t5": 5}
    assert score.RULES["levels_window"] == 20
    assert score.RULES["open_check_conditions"] == [
        "open_at_or_below_stop",
        "open_at_or_above_target",
        "gap_above_entry_high",
    ]


# --- AC-2: worked by hand ------------------------------------------------------------


def test_each_pick_gets_its_hand_worked_results(db, world):
    row = reading(db, world)
    run(db, SESSIONS[4])
    scores = written(db, row.id)
    a = scores[(row.id, "stock", "A", "t5")]
    assert a["open_hold"]["return"] == approx(hold(101, 102))
    assert a["ai_levels"]["status"] == "comparable"
    assert a["ai_levels"]["execution_date"] == D.isoformat()
    assert a["ai_levels"]["return"] == approx(tracked(101, 102))
    assert a["rule_levels"]["return"] == approx(tracked(101.5, 102))
    assert a["open_check"]["applicable"] is True
    assert (a["setup"], a["basis_primary"], a["basis"]) == (
        "breakout",
        "technical",
        ["technical", "chips"],
    )
    # B: not applicable today, ai_levels still tracked; no rule levels.
    b = scores[(row.id, "stock", "B", "t5")]
    assert b["open_check"]["applicable"] is False
    assert b["open_check"]["reason"] == "gap_above_entry_high"
    assert b["open_check"]["open"] == 52
    assert b["ai_levels"]["return"] == approx(tracked(52, 52))
    assert b["rule_levels"] is None
    assert b["rule_levels_reason"] == "no_rule_levels"
    # C: on the rule list, its strategy_levels are no_levels.
    c = scores[(row.id, "stock", "C", "t5")]
    assert c["ai_levels"]["return"] == approx(tracked(30.5, 29))
    assert c["on_rule_list"] is True and c["rule_levels"] is None
    # E: levels failed: open_hold only, no open check.
    e = scores[(row.id, "stock", "E", "t5")]
    assert e["levels_passed"] is False
    assert (e["ai_levels"], e["ai_levels_reason"]) == (None, "levels_check_failed")
    assert e["open_check"] is None
    assert e["open_hold"]["return"] == approx(hold(20, 21))
    # F: opens under its stop, never fills; its corporate-action flag is kept.
    f = scores[(row.id, "stock", "F", "t5")]
    assert f["open_check"]["conditions"] == ["open_at_or_below_stop"]
    assert f["ai_levels"]["status"] == "incomparable"
    assert f["ai_levels"]["reason"] == "not_filled_by_horizon"
    assert f["ai_levels"]["execution_date"] is None
    assert f["corporate_action_on_session"] is True
    assert a["corporate_action_on_session"] is False
    # Each pick's excess is over the reading's population (all six stocks).
    population = statistics.fmean(
        [
            hold(101, 102),
            hold(52, 52),
            hold(30.5, 29),
            hold(20, 21),
            hold(9.4, 9.5),
            hold(40, 40),
        ]
    )
    assert a["open_hold"]["excess"] == approx(hold(101, 102) - population)
    assert (row.id, "stock", "R", "t5") not in scores


def test_the_overall_row_compares_with_the_population_and_the_rule_list(db, world):
    row = reading(db, world)
    run(db, SESSIONS[4])
    overall = written(db, row.id)[(row.id, "overall", "overall", "t5")]
    holds = {
        "A": hold(101, 102),
        "B": hold(52, 52),
        "C": hold(30.5, 29),
        "E": hold(20, 21),
        "F": hold(9.4, 9.5),
        "R": hold(40, 40),
    }
    population = statistics.fmean(holds.values())
    ai_mean = statistics.fmean(holds[s] for s in "ABCEF")
    rule_mean = statistics.fmean(holds[s] for s in "ACR")
    assert overall["population"]["mean"] == approx(population)
    assert overall["ai_list"]["open_hold"]["mean"] == approx(ai_mean)
    assert overall["ai_list"]["open_hold"]["excess"] == approx(ai_mean - population)
    levels = overall["ai_list"]["ai_levels"]
    assert (levels["n"], levels["comparable"], levels["filled"]) == (4, 3, 3)
    rule = overall["rule_list"]
    assert rule["status"] == "scored"
    assert rule["open_hold"]["mean"] == approx(rule_mean)
    assert rule["open_hold"]["excess"] == approx(rule_mean - population)
    # The rule list's tracking_v2: A on 101.5 and R on 40 (C has none).
    assert rule["levels"]["comparable"] == 2
    assert rule["levels"]["mean"] == approx(
        statistics.fmean([tracked(101.5, 102), tracked(40, 40)])
    )
    # AI levels against rule levels: only A has both.
    pair = overall["ai_vs_rule_levels"]
    assert pair["pairs"] == 1
    assert pair["value"] == approx(tracked(101, 102) - tracked(101.5, 102))
    assert overall["ai_vs_rule_picks"]["value"] == approx(ai_mean - rule_mean)
    assert overall["counts"] == {
        "picks": 5,
        "levels_check_failed": 1,
        "not_applicable": 2,
        "no_rule_levels": 4,
        "corporate_action_on_session": 1,
    }


def test_the_market_row_keeps_the_basis(db, world):
    row = reading(db, world, stance="neutral")
    run(db, SESSIONS[4])
    scores = written(db, row.id)
    d0 = scores[(row.id, "market", "market", "d0")]
    # 20000 -> 20200 is +1.0%: up, a neutral stance misses.
    assert (d0["realized"], d0["hit"]) == ("up", False)
    assert d0["return"] == approx(0.01)
    assert (d0["basis"], d0["basis_primary"]) == (["tx_night", "us"], "tx_night")
    t5 = scores[(row.id, "market", "market", "t5")]
    # 20000 -> 20500 is +2.5% > 1.5%.
    assert (t5["realized"], t5["hit"]) == ("up", False)


def test_without_a_rule_list_the_sides_are_empty(db, world):
    row = reading(db, world, with_rule_list=False)
    run(db, SESSIONS[4])
    overall = written(db, row.id)[(row.id, "overall", "overall", "t5")]
    assert overall["rule_list"]["status"] == "no_list"
    assert overall["ai_vs_rule_picks"] == {"value": None, "reason": "empty_side"}
    # A pick's rule levels are its own rule_levels_json, which A still has:
    # A is still paired.
    assert overall["ai_vs_rule_levels"]["pairs"] == 1


def test_an_empty_list_scores_the_market_and_an_empty_overall(db, world):
    row = reading(db, world, picks=())
    run(db, SESSIONS[4])
    scores = written(db, row.id)
    overall = scores[(row.id, "overall", "overall", "t5")]
    assert overall["ai_list"]["open_hold"]["n"] == 0
    assert overall["ai_list"]["open_hold"]["excess"] is None
    assert overall["ai_vs_rule_picks"]["reason"] == "empty_side"
    assert overall["ai_vs_rule_levels"] == {
        "pairs": 0,
        "ai_mean": None,
        "rule_mean": None,
        "value": None,
        "reason": "empty_side",
    }
    assert (row.id, "market", "market", "d0") in scores


def test_t20_records_the_first_trigger(db, world):
    """G: breakout 50 fills at the open 51, touches the target 56 on session 3."""

    g = instrument(db, "G")
    path(
        db, g, 50, (51, 52, 50.5, 51.5), lambda at: (55, 57, 54, 56) if at == 3 else 53
    )
    world["G"] = g
    picks = (
        (
            "G",
            False,
            "breakout",
            ["technical"],
            "high",
            display("breakout", 50, 52, 47, 56),
            None,
        ),
    )
    row = reading(db, world, picks=picks)
    run(db, SESSIONS[19])
    result = written(db, row.id)[(row.id, "stock", "G", "t20")]["ai_levels"]
    assert result["first_trigger"] == "target_1_hit"
    assert result["return"] == approx(tracked(51, 56, sell=True))


def test_open_check_rules():
    breakout = display("breakout", 100, 102, 95, 110)
    pullback = display("pullback", 30, 31, 28, 34)
    cases = [
        (breakout, 102, True, []),
        (breakout, 102.5, False, ["gap_above_entry_high"]),
        (breakout, 95, False, ["open_at_or_below_stop"]),
        (breakout, 110, False, ["open_at_or_above_target", "gap_above_entry_high"]),
        # A pullback opening over its zone may still come back: applicable.
        (pullback, 32, True, []),
        (pullback, 34, False, ["open_at_or_above_target"]),
        (pullback, 28, False, ["open_at_or_below_stop"]),
    ]
    for levels_, opened, applicable, conditions in cases:
        out = score.open_check(levels_, opened)
        assert (out["applicable"], out["conditions"]) == (applicable, conditions), (
            opened
        )
        assert out["reason"] == (conditions[0] if conditions else None)
    missing = score.open_check(breakout, None)
    assert (missing["status"], missing["reason"], missing["applicable"]) == (
        "no_data",
        "no_open",
        None,
    )


def test_ex_dividend_opens_are_checked_on_the_list_date_basis(db, world):
    """H goes ex-dividend on D (factor 0.9): the raw open 45.9 is 51 on L's basis."""

    h = instrument(db, "H")
    path(db, h, 50, (45.9, 47.7, 45.45, 46.8), 46.8)
    dividend(db, h, D, 0.9)
    world["H"] = h
    picks = (
        (
            "H",
            False,
            "breakout",
            ["technical"],
            "medium",
            display("breakout", 50, 51.5, 47, 56),
            None,
        ),
    )
    row = reading(
        db, world, picks=picks, facts={"H": {"corporate_action_on_session": True}}
    )
    run(db, SESSIONS[4])
    stock = written(db, row.id)[(row.id, "stock", "H", "t5")]
    # Raw 45.9 would be under the stop 47; on the basis it is 51, inside 50-51.5.
    assert stock["open_check"]["open"] == approx(51)
    assert stock["open_check"]["applicable"] is True
    assert stock["ai_levels"]["return"] == approx(tracked(51, 52))
    assert stock["open_hold"]["return"] == approx(hold(51, 52))
    assert stock["corporate_action_on_session"] is True


# --- writing ------------------------------------------------------------------------


def test_a_horizon_is_written_once_and_a_rerun_writes_nothing(db, world):
    row = reading(db, world)
    assert run(db, SESSIONS[3]) != []
    have = written(db, row.id)
    assert {key[3] for key in have} == {"d0"}
    run(db, SESSIONS[4])
    assert {key[3] for key in written(db, row.id)} == {"d0", "t5"}
    assert run(db, SESSIONS[4]) == []
    run(db, SESSIONS[19])
    assert run(db, SESSIONS[19]) == []
    keys = written(db, row.id)
    assert len(keys) == 2 + 2 * (5 + 1)


def test_failed_readings_and_premarket_rows_are_not_touched(db, world):
    reading(db, world, status="failed")
    assert ai_list_score.score_readings(db, SESSIONS[4]) == []
    from app.models import PremarketAiScore

    run(db, SESSIONS[4])
    assert db.scalar(select(func.count(PremarketAiScore.id))) == 0


def test_premarket_score_v1_is_unchanged():
    """premarket_score_v1's pin still holds: the version this module calls."""

    from test_premarket_score import (
        test_the_scoring_rules_and_their_spec_are_pinned_to_the_score_version as pin,
    )

    pin()
    assert v1.SCORE_VERSION == "premarket_score_v1"


# --- AC-3: the groups and the threshold ---------------------------------------------


def outcome(setup="breakout", ret=0.01, *, excess=0.002, levels=True, trigger=None):
    ai = (
        {
            "status": "comparable",
            "reason": None,
            "return": ret,
            "execution_date": D.isoformat(),
            "first_trigger": trigger,
        }
        if levels
        else None
    )
    return {
        "setup": setup,
        "basis": ["technical", "news"],
        "basis_primary": "technical",
        "confidence": "medium",
        "levels_passed": levels,
        "open_check": {"applicable": True} if levels else None,
        "ai_levels": ai,
        "ai_levels_reason": None if levels else "levels_check_failed",
        "open_hold": {"status": "comparable", "return": ret, "excess": excess},
    }


def test_a_group_under_the_threshold_lists_counts_only():
    under = [{"t5": outcome(), "t20": outcome()} for _ in range(19)]
    part = score.group_stats(under)
    assert part["status"] == "insufficient_sample"
    assert (part["n"], part["comparable"], part["filled"]) == (19, 19, 19)
    assert part["win_rate"] is None and part["mean"] is None
    assert part["median"] is None
    assert set(part["first_trigger"].values()) == {None}
    assert part["open_hold_t5_excess"] is None
    rows = under + [
        {"t5": outcome(ret=-0.02), "t20": outcome(ret=-0.02, trigger="invalidated")}
    ]
    part = score.group_stats(rows)
    assert part["status"] == "sufficient"
    assert part["win_rate"] == approx(19 / 20)
    assert part["mean"] == approx((19 * 0.01 - 0.02) / 20)
    assert part["median"] == approx(0.01)
    assert part["first_trigger"] == {
        "target_1_hit": 0,
        "invalidated": 1,
        "None": 19,
    }
    assert part["open_hold_t20_excess"] == approx(0.002)
    assert part["fill_rate"] == 1.0


def test_picks_count_in_each_of_their_groups():
    picks = [
        {"t5": outcome("breakout"), "t20": outcome("breakout")},
        {"t5": outcome("pullback_support", levels=False), "t20": None},
    ]
    groups = score.grouped(picks)
    assert set(groups) == {
        "setup",
        "basis_primary",
        "basis",
        "confidence",
        "setup_confidence",
        "state",
    }
    assert groups["setup"]["breakout"]["n"] == 1
    assert groups["basis"]["news"]["n"] == 2 and groups["basis"]["technical"]["n"] == 2
    assert groups["setup_confidence"]["breakout×medium"]["n"] == 1
    assert set(groups["state"]) == {"applicable", "levels_check_failed"}
    failed = groups["state"]["levels_check_failed"]
    assert (failed["levels_n"], failed["comparable"]) == (0, 0)


def test_market_groups_need_twenty_scored_days():
    rows = [
        {"horizon": "d0", "basis_primary": "us", "status": "scored", "hit": day < 15}
        for day in range(20)
    ] + [
        {"horizon": "d0", "basis_primary": "news", "status": "scored", "hit": True}
        for _ in range(19)
    ]
    groups = score.market_groups(rows)
    assert groups["us"]["d0"]["hit_rate"] == approx(0.75)
    assert groups["news"]["d0"] == {
        "days": 19,
        "hits": None,
        "status": "insufficient_sample",
        "hit_rate": None,
    }


def test_the_month_report_has_the_sections_and_marks_a_short_sample(db, world):
    reading(db, world)
    reading(db, world, status="failed", with_rule_list=False)
    run(db, SESSIONS[19])
    text = ai_list_score_report.render(db, "2026-12")
    assert "# AI 名單對答案月報 2026-12" in text
    assert "## `ai_list_v1`／`champion`" in text
    # The day has a done reading: it counts as done, as premarket_score_report.
    assert "判讀日 1 天：`done` 1、`failed` 0、`rejected` 0" in text
    assert "### 依判讀方式分組：累積" in text and "### 依判讀方式分組：當月" in text
    assert "**型態 `setup`**" in text and "樣本不足" in text
    assert "規則名單是對答案的基準：只記錄，不提案" in text
    assert "價位核對不過 1、今日不適用 2、沒有規則價位 4" in text
    assert ai_list_score_report.render(db, "2026-11").count("尚無判讀紀錄") == 1


# --- the daily step and the CLI -----------------------------------------------------

REAL_STEP = schedule_runs._ai_list_score_step


@pytest.fixture
def daily_db(tmp_path, monkeypatch):
    from app.migrations import upgrade_database
    from worker import sources

    engine = create_engine(f"sqlite:///{tmp_path / 'score.db'}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(sources, "RAW_DIR", tmp_path / "raw")
    yield factory
    engine.dispose()


@pytest.mark.parametrize("broken", [False, True])
def test_the_real_daily_step_runs_after_premarket_score_and_never_fails_the_run(
    daily_db, monkeypatch, capsys, broken
):
    from test_daily_schedule import DAY, Steps, runs

    steps = Steps(monkeypatch)
    monkeypatch.setattr(schedule_runs, "_ai_list_score_step", REAL_STEP)
    assert "ai_list_score" in schedule_runs.NON_BLOCKING_STEPS
    if broken:

        def crash(*_args, **_kwargs):
            raise RuntimeError("fixture score crash")

        monkeypatch.setattr(ai_list_score, "score_readings", crash)
    result = pipeline.run_daily(DAY)
    assert result["status"] == "success"
    assert steps.calls[-1] == "premarket_score"
    rows, by_run = runs(daily_db)
    step = by_run[rows[0].id]["ai_list_score"]
    assert by_run[rows[0].id]["premarket_score"].sequence < step.sequence
    assert rows[0].status == "success" and rows[0].error is None
    err = capsys.readouterr().err
    if broken:
        assert step.status == "failed" and "fixture score crash" in step.error
        assert "warning: ai_list_score_v1 2026-09-04 failed: RuntimeError" in err
    else:
        assert (step.status, step.records, step.sequence) == ("success", 0, 19)


def test_the_cli_scores_reports_and_refuses_a_bad_month(
    engine, db, world, monkeypatch, capsys, tmp_path
):
    reading(db, world)
    db.commit()
    monkeypatch.setattr(
        pipeline, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False)
    )
    day = SESSIONS[4].isoformat()
    assert cli_main(monkeypatch, "ai-list-score", "--date", day, "--dry-run") == 0
    dry = json.loads(capsys.readouterr().out)
    assert (dry["status"], dry["records"], dry["dry_run"]) == ("success", 0, True)
    assert db.scalar(select(func.count(AiListScore.id))) == 0
    assert cli_main(monkeypatch, "ai-list-score", "--date", day) == 0
    # market d0, t5; five picks and the overall at t5.
    assert json.loads(capsys.readouterr().out)["records"] == 8
    out = tmp_path / "report.md"
    assert (
        cli_main(
            monkeypatch, "ai-list-score-report", "--month", "2026-12", "--out", str(out)
        )
        == 0
    )
    assert "`ai_list_v1`／`champion`" in out.read_text(encoding="utf-8")
    assert cli_main(monkeypatch, "ai-list-score-report", "--month", "2026-13") == 2
    assert "YYYY-MM" in capsys.readouterr().err

    def crash(*_args, **_kwargs):
        raise RuntimeError("fixture score crash")

    monkeypatch.setattr(ai_list_score, "score_readings", crash)
    assert cli_main(monkeypatch, "ai-list-score", "--date", day) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


# --- the migration ------------------------------------------------------------------


def test_the_migration_adds_only_the_scores_table_and_goes_down_and_up(tmp_path):
    pytest.importorskip("alembic")
    from alembic import command
    from test_premarket_ai import _alembic_config, _schema

    from app.migration_revisions import REVISIONS

    revision = "0053_ai_list_scores"
    previous = REVISIONS[REVISIONS.index(revision) - 1]
    assert previous == "0051_ai_list"
    indexes = {"ix_ai_list_scores_reading_id", "ix_ai_list_scores_session_date"}
    engine = create_engine(f"sqlite:///{(tmp_path / 'down.db').as_posix()}")
    enable_sqlite_foreign_keys(engine)
    config = _alembic_config(engine)
    try:
        command.upgrade(config, revision)
        names, found, version, fk = _schema(engine)
        assert "ai_list_scores" in names and indexes <= found
        assert version == [(revision,)] and fk == []
        command.downgrade(config, previous)
        down, down_indexes, version, fk = _schema(engine)
        assert "ai_list_scores" not in down and not indexes & down_indexes
        assert version == [(previous,)] and fk == []
        # Up again: the one table and its indexes, nothing else.
        command.upgrade(config, revision)
        names, found, version, fk = _schema(engine)
        named = {
            name for name in found - down_indexes if not name.startswith("sqlite_")
        }
        assert names - down == {"ai_list_scores"} and named == indexes
        assert version == [(revision,)] and fk == []
    finally:
        engine.dispose()
