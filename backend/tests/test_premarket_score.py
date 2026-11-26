"""Scoring the pre-market AI readings (#1043): premarket_score_v1 worked by hand.

List date L is Tuesday 2026-12-01 and D Wednesday 2026-12-02 (session 1); the
fixture has 20 weekday sessions from D.  Every expected number is written out
as the arithmetic of the spec (docs/spec/premarket_ai.md 對答案): buy fills
+5 bps, sell fills -5 bps, 30 bps round trip; a tracking_v2 hold to the
horizon close sells at the close without slippage (app.tracking.settle).
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import premarket_score as score
from app.db import Base, enable_sqlite_foreign_keys
from app.models import (
    Instrument,
    MarketBar,
    PremarketAiReading,
    PremarketAiScore,
    PremarketAiStock,
)
from worker import pipeline, premarket_score, premarket_score_report

L = date(2026, 12, 1)
D = date(2026, 12, 2)
COST = 0.003
BUY = 1.0005
SELL = 0.9995
SPEC = Path(__file__).resolve().parents[2] / "docs" / "spec" / "premarket_ai.md"


def weekdays_from(start: date, count: int) -> list[date]:
    days, cursor = [], start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


SESSIONS = weekdays_from(D, 20)


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


def instrument(db, symbol, kind="stock"):
    row = Instrument(
        exchange="TWSE",
        symbol=symbol,
        name=f"名{symbol}",
        instrument_type=kind,
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def bar(db, row, day, o, h, low, c, *, source="fixture", volume=1_000_000, **extra):
    db.add(
        MarketBar(
            instrument_id=row.id,
            trading_date=day,
            open=o,
            high=h,
            low=low,
            close=c,
            adj_close=c,
            volume=volume,
            turnover=c * volume,
            source=source,
            **extra,
        )
    )


def path(db, row, previous_close, first, rest, *, skip=()):
    """L's close, D's OHLC, and sessions 2..20 given as (o, h, l, c) or a flat price."""

    bar(db, row, L, previous_close, previous_close, previous_close, previous_close)
    bar(db, row, SESSIONS[0], *first)
    for at, day in enumerate(SESSIONS[1:], start=2):
        if at in skip:
            continue
        value = rest(at) if callable(rest) else rest
        prices = value if isinstance(value, tuple) else (value,) * 4
        bar(db, row, day, *prices)


def levels(kind, low, high, invalid, target):
    return {
        "rank": 1,
        "strategy": "fixture",
        "entry_type": kind,
        "entry": low if kind == "breakout" else (low + high) / 2,
        "entry_zone": {"low": low, "high": high},
        "invalid_price": invalid,
        "target_1": target,
        "target_2": None,
        "risk_reward": None,
        "earliest_execution_date": D.isoformat(),
    }


@pytest.fixture
def world(db):
    """TAIEX, the pool stocks of the reading and the rest of the market."""

    taiex = instrument(db, "TAIEX", "index")
    bar(db, taiex, L, 20000, 20000, 20000, 20000, source="twse_index_ohlcv")
    bar(db, taiex, D, 20100, 20250, 20050, 20200, source="twse_index_ohlcv")
    for at, day in enumerate(SESSIONS[1:], start=2):
        close = 20500 if at == 5 else 20300
        bar(db, taiex, day, close, close, close, close, source="twse_index_ohlcv")
    stocks = {}
    # A keep, breakout 100: fills at D's open 101, then 102 to the end.
    stocks["A"] = instrument(db, "A")
    path(db, stocks["A"], 99, (101, 102, 100, 101), 102)
    # B reprice, breakout 52: the original fills at 52; re-priced at the open 51
    # (gap 2%, rr (56-51)/(51-47) = 1.25 >= 1.2).  Target 56 touched on day 2.
    stocks["B"] = instrument(db, "B")
    path(
        db,
        stocks["B"],
        50,
        (51, 53, 50.5, 52),
        lambda at: (52, 57, 52, 56) if at == 2 else 55,
    )
    # C defer, pullback 30-31: fills at the open 30.5, then 29 (invalid 28 untouched).
    stocks["C"] = instrument(db, "C")
    path(db, stocks["C"], 31, (30.5, 31, 30, 30.5), 29)
    # E keep, off the list: no levels, a D-open hold only.
    stocks["E"] = instrument(db, "E")
    path(db, stocks["E"], 20, (20, 20.5, 19.5, 20), 21)
    # F reprice, but the open 10.8 is 8% over the close 10 (> 5%): defer.
    stocks["F"] = instrument(db, "F")
    path(db, stocks["F"], 10, (10.8, 11, 10.5, 11), 11)
    # G keep, off the list, no bar on session 3.
    stocks["G"] = instrument(db, "G")
    path(db, stocks["G"], 70, (70, 71, 69, 70), 72, skip={3})
    # The rest of the market: P is in the population, the ETF and S (suspended
    # on D) are not.
    p = instrument(db, "P")
    path(db, p, 40, (40, 40.5, 39.5, 40), 40)
    etf = instrument(db, "ETF", "etf")
    path(db, etf, 50, (50, 50, 50, 50), 80)
    s = instrument(db, "S")
    bar(db, s, L, 60, 60, 60, 60)
    bar(db, s, D, 60, 60, 60, 60, volume=0, is_suspended=True)
    for day in SESSIONS[1:]:
        bar(db, s, day, 90, 90, 90, 90)
    db.flush()
    return stocks


POOL = (
    # symbol, on list, action, levels, reprice rule
    ("A", True, "keep", levels("breakout", 100, 100, 95, 110), None),
    (
        "B",
        True,
        "reprice",
        levels("breakout", 52, 52, 47, 56),
        {"max_gap_pct": 0.05, "max_gap_down_pct": 0.03, "min_risk_reward": 1.2},
    ),
    ("C", True, "defer", levels("pullback", 30, 31, 28, 34), None),
    ("E", False, "keep", None, None),
    (
        "F",
        True,
        "reprice",
        levels("breakout", 10, 10, 9, 12),
        {"max_gap_pct": 0.05, "max_gap_down_pct": 0.03, "min_risk_reward": 0.5},
    ),
    ("G", False, "keep", None, None),
)


def reading(db, stocks, *, role="champion", version="premarket_v1", stance="bullish"):
    now = datetime(2026, 12, 2, 0, 25)
    row = PremarketAiReading(
        session_date=D,
        list_date=L,
        role=role,
        sequence=1,
        trigger="scheduler",
        prompt_version=version,
        prompt_sha256="0" * 64,
        schema_sha256="0" * 64,
        model_alias="sonnet",
        llm_model="claude-sonnet-5-5",
        pool_phase="evening",
        cutoff_at=now,
        input_hash="0" * 64,
        input_json={"pool": {"today_list_count": 4}},
        status="done",
        output_json={"market": {"stance": stance, "confidence": "medium"}},
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
    for position, (symbol, listed, action, level, rule) in enumerate(POOL, start=1):
        db.add(
            PremarketAiStock(
                reading_id=row.id,
                session_date=D,
                prompt_version=version,
                role=role,
                instrument_id=stocks[symbol].id,
                symbol=symbol,
                position=position,
                on_today_list=listed,
                pool_sources_json=[],
                levels_json=level,
                action=action,
                reprice_rule_json=rule,
                reasons_json=[],
            )
        )
    db.flush()
    return row


def written(db, reading_id=None):
    query = select(PremarketAiScore)
    if reading_id is not None:
        query = query.where(PremarketAiScore.reading_id == reading_id)
    return {
        (row.reading_id, row.scope, row.subject, row.horizon): row.outcome_json
        for row in db.scalars(query)
    }


def run(db, target):
    rows = premarket_score.score_readings(db, target)
    db.add_all(rows)
    db.commit()
    return rows


def hold(entry, exit_):
    return exit_ * SELL / (entry * BUY) - 1 - COST


def tracked(entry_raw, exit_, *, sell=False):
    return (exit_ * SELL if sell else exit_) / (entry_raw * BUY) - 1 - COST


# --- AC-1: the rules are pinned ------------------------------------------------------

# score_version -> (sha256 of RULES as JSON, sha256 of the spec section).  A
# change to either fails here: give it a new SCORE_VERSION and pin that one.
PINNED = {
    "premarket_score_v1": (
        "30cb4aed987d1f69bb28c6795c5d9d2e2202c547f5fcbacdbf4bce845a681290",
        "30157c112a817fa7d526c0fc9ca9d9d77cf1ec9ff1df9ee106eb4d48b64f3c41",
    ),
}


def spec_section() -> str:
    text = SPEC.read_text(encoding="utf-8")
    match = re.search(r"^## 對答案\n(.*?)(?=^## )", text, re.S | re.M)
    assert match, "docs/spec/premarket_ai.md has no 對答案 section"
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
        "premarket_score rules or the spec's 對答案 section changed: "
        "new SCORE_VERSION, then pin it here",
        rules,
        spec,
    )


# --- AC-2: worked by hand ------------------------------------------------------------


def test_market_stance_scores_d0_and_t5_from_the_open(db, world):
    row = reading(db, world)
    run(db, SESSIONS[4])
    scores = written(db, row.id)
    d0 = scores[(row.id, "market", "market", "d0")]
    t5 = scores[(row.id, "market", "market", "t5")]
    # D: 20100 -> 20200 is +0.4975%, inside ±0.5%: flat, so bullish misses.
    assert d0["return"] == pytest.approx(20200 / 20100 - 1)
    assert (d0["realized"], d0["hit"]) == ("flat", False)
    # T+5: 20100 -> 20500 is +1.99%, over 1.5%: up, a hit.
    assert t5["return"] == pytest.approx(20500 / 20100 - 1)
    assert (t5["realized"], t5["hit"], t5["close_date"]) == (
        "up",
        True,
        SESSIONS[4].isoformat(),
    )


def test_a_close_only_taiex_open_is_no_data(db, world):
    taiex = db.scalar(select(Instrument).where(Instrument.symbol == "TAIEX"))
    first = db.scalar(
        select(MarketBar).where(
            MarketBar.instrument_id == taiex.id, MarketBar.trading_date == D
        )
    )
    first.source = "twse_index"
    row = reading(db, world)
    run(db, SESSIONS[0])
    d0 = written(db, row.id)[(row.id, "market", "market", "d0")]
    assert (d0["status"], d0["reason"], d0["hit"]) == ("no_data", "no_open", None)


def test_each_action_gets_its_hand_worked_results(db, world):
    row = reading(db, world)
    run(db, SESSIONS[4])
    scores = written(db, row.id)

    def stock(symbol):
        return scores[(row.id, "stock", symbol, "t5")]

    a, b, c, f, g = (stock(symbol) for symbol in "ABCFG")
    # keep: original levels, filled at the open 101, valued at the T+5 close 102.
    assert a["effective_action"] == "keep"
    assert a["levels"]["original"]["return"] == pytest.approx(tracked(101, 102))
    assert a["levels"]["repriced"] is None
    assert a["open_hold"]["return"] == pytest.approx(hold(101, 102))
    # reprice: both results.  Original fills at the breakout 52 (open 51 below
    # it), re-priced fills at the open 51; both sell at the target 56 on day 2.
    assert b["effective_action"] == "reprice"
    repriced = b["levels"]["repriced"]
    assert repriced["status"] == "repriced"
    assert repriced["gap"] == pytest.approx(51 / 50 - 1)
    assert repriced["risk_reward"] == pytest.approx((56 - 51) / (51 - 47))
    assert repriced["stop_distance"] == pytest.approx(4)
    assert b["levels"]["original"]["return"] == pytest.approx(
        tracked(52, 56, sell=True)
    )
    assert b["levels"]["original"]["first_trigger"] == "target_1_hit"
    assert b["levels"]["repriced_result"]["return"] == pytest.approx(
        tracked(51, 56, sell=True)
    )
    assert b["open_hold"]["return"] == pytest.approx(hold(51, 55))
    # defer: what it would have done on the original levels (pullback at the
    # open 30.5, valued at 29).
    assert c["effective_action"] == "defer"
    assert c["levels"]["original"]["return"] == pytest.approx(tracked(30.5, 29))
    assert c["open_hold"]["return"] == pytest.approx(hold(30.5, 29))
    # reprice deferred by its own rule: a gap of 8% over 5%.
    assert f["action"] == "reprice" and f["effective_action"] == "defer"
    assert f["levels"]["repriced"]["status"] == "reprice_deferred"
    assert f["levels"]["repriced"]["conditions"] == ["gap_up_over_max"]
    assert f["levels"]["repriced_result"] is None
    assert f["levels"]["original"]["return"] == pytest.approx(tracked(10.8, 11))
    # A missing session: no D-open hold.
    assert g["open_hold"] == {
        **g["open_hold"],
        "status": "incomparable",
        "reason": "missing_bar",
        "return": None,
    }
    assert g["levels"] is None


def test_the_overall_row_compares_versions_with_the_population_and_the_value(db, world):
    row = reading(db, world)
    run(db, SESSIONS[4])
    overall = written(db, row.id)[(row.id, "overall", "overall", "t5")]
    a, b, c, e, f = (
        hold(101, 102),
        hold(51, 55),
        hold(30.5, 29),
        hold(20, 21),
        hold(10.8, 11),
    )
    p = hold(40, 40)
    # Population: stock/ipo with a D bar not suspended (the ETF and S are
    # out); G is a member without a T+5 hold.
    population = statistics.fmean([a, b, c, e, f, p])
    assert overall["population"]["members"] == 7
    assert overall["population"]["comparable"] == 6
    assert overall["population"]["mean"] == pytest.approx(population)
    ai = statistics.fmean([a, b, e])
    rule = statistics.fmean([a, b, c, f])
    assert overall["ai_version"]["mean"] == pytest.approx(ai)
    assert overall["ai_version"]["excess"] == pytest.approx(ai - population)
    assert overall["rule_version"]["excess"] == pytest.approx(rule - population)
    assert overall["value_open_hold"]["value"] == pytest.approx(
        ai - statistics.fmean([c, f])
    )
    levels_ai = statistics.fmean([tracked(101, 102), tracked(51, 56, sell=True)])
    levels_defer = statistics.fmean([tracked(30.5, 29), tracked(10.8, 11)])
    assert overall["levels"]["value"] == pytest.approx(levels_ai - levels_defer)
    assert overall["today_list_count"] == 4


def test_a_day_without_today_list_records_no_list(db, world):
    row = reading(db, world)
    for stock in db.scalars(select(PremarketAiStock)):
        stock.on_today_list = False
        stock.levels_json = None
        stock.action = "keep" if stock.action == "reprice" else stock.action
        stock.reprice_rule_json = None
    run(db, SESSIONS[4])
    overall = written(db, row.id)[(row.id, "overall", "overall", "t5")]
    assert overall["rule_version"]["status"] == "no_list"
    assert overall["rule_version"]["mean"] is None
    assert overall["levels"]["value"] is None
    assert overall["levels"]["reason"] == "empty_side"


@pytest.mark.parametrize(
    ("open_price", "rule", "conditions"),
    [
        (46.5, {}, ["open_at_or_below_invalid"]),
        (56.5, {}, ["open_at_or_above_target", "risk_reward_under_min"]),
        (48.4, {"max_gap_down_pct": 0.03}, ["gap_down_over_max"]),
        (51, {"min_risk_reward": 1.3}, ["risk_reward_under_min"]),
        (51, {"min_risk_reward": 1.25}, []),
    ],
)
def test_reprice_keeps_the_stop_and_target_and_checks_each_condition(
    open_price, rule, conditions
):
    rule = {"max_gap_pct": 0.2, "min_risk_reward": 1.0, **rule}
    out = score.reprice(levels("breakout", 52, 52, 47, 56), rule, open_price, 50)
    assert out["conditions"] == conditions
    assert out["status"] == ("reprice_deferred" if conditions else "repriced")
    assert (out["invalid_price"], out["target_1"], out["entry"]) == (47, 56, open_price)


# --- AC-3: versions apart, once only -------------------------------------------------


def test_champion_and_shadow_are_scored_apart_and_a_rerun_writes_nothing(db, world):
    champion = reading(db, world)
    shadow = reading(db, world, role="shadow", version="premarket_v2", stance="neutral")
    first = run(db, SESSIONS[4])
    rows = written(db)
    # Market d0 and t5, six stocks and the overall row at T+5, each reading.
    assert len(first) == 2 * (2 + 6 + 1)
    for item in (champion, shadow):
        keys = {key[1:] for key in rows if key[0] == item.id}
        assert ("market", "market", "d0") in keys
        assert ("overall", "overall", "t5") in keys
        assert not any(key[2] == "t20" for key in keys)
    stored = {
        (row.reading_id, row.role, row.prompt_version)
        for row in db.scalars(select(PremarketAiScore))
    }
    assert stored == {
        (champion.id, "champion", "premarket_v1"),
        (shadow.id, "shadow", "premarket_v2"),
    }
    assert rows[(champion.id, "market", "market", "d0")]["stance"] == "bullish"
    assert rows[(shadow.id, "market", "market", "d0")]["hit"] is True

    # The same day again, and a later day before T+20: nothing new.
    assert run(db, SESSIONS[4]) == []
    assert run(db, SESSIONS[10]) == []
    count = db.scalar(select(func.count(PremarketAiScore.id)))
    # T+20: only the t20 rows are added.
    later = run(db, SESSIONS[19])
    assert {row.horizon for row in later} == {"t20"}
    assert len(later) == 2 * (6 + 1)
    assert db.scalar(select(func.count(PremarketAiScore.id))) == count + len(later)
    assert run(db, SESSIONS[19]) == []


def test_failed_readings_are_not_scored(db, world):
    row = reading(db, world)
    row.status = "failed"
    db.flush()
    assert run(db, SESSIONS[4]) == []


def test_the_step_dry_run_writes_nothing(engine, db, world, monkeypatch):
    reading(db, world)
    db.commit()
    monkeypatch.setattr(
        pipeline, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False)
    )
    dry = premarket_score.run_premarket_score(SESSIONS[4], dry_run=True)
    assert dry["records"] == 0 and dry["rows"] == {
        "market": 2,
        "stock": 6,
        "overall": 1,
    }
    assert db.scalar(select(func.count(PremarketAiScore.id))) == 0
    real = premarket_score.run_premarket_score(SESSIONS[4])
    assert real["status"] == "success" and real["records"] == 9
    again = premarket_score.run_premarket_score(SESSIONS[4])
    assert again["records"] == 0


# --- the monthly report --------------------------------------------------------------


def test_the_month_report_marks_a_short_sample_and_compares_a_shadow(db, world):
    reading(db, world)
    reading(db, world, role="shadow", version="premarket_v2", stance="neutral")
    run(db, SESSIONS[19])
    text = premarket_score_report.render(db, "2026-12")
    assert "`premarket_v1`／`champion`" in text
    assert "`premarket_v2`／`shadow`" in text
    assert text.count("**insufficient_sample**") == 3
    assert "換版條件：`premarket_v2`（shadow）對 `premarket_v1`（champion）" in text
    # Market d0: the champion missed (bullish on a flat day), the shadow hit.
    assert "| 大盤當日判對率不低於 | 0.0% | 100.0% | 是 |" in text
    assert premarket_score_report.month_problem("2026-13") is not None
    assert premarket_score_report.month_problem("2026-12") is None
