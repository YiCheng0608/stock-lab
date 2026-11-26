"""tools/research/candidate_pool_score.py: the pool's sources against the population (#1069).

A small file copy: pool day T is Tuesday 2026-12-01, D Wednesday 2026-12-02
and 20 weekday sessions from D.  The returns and the population are checked
against the functions the AI's scores use (``app.premarket_score.open_hold``,
``worker.premarket_score.population``) on the same bars; the grouping and the
verdicts on made-up day results (docs/spec/candidate_pool.md 對答案).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import premarket_score as score
from app.db import Base
from app.models import (
    CandidatePoolItem,
    CandidatePoolRun,
    Instrument,
    MarketBar,
    PremarketAiReading,
    PremarketAiStock,
)
from worker import pipeline
from worker import premarket_score as scoring

ROOT = Path(__file__).resolve().parents[2]
T = date(2026, 12, 1)


def _tool(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cps = _tool("candidate_pool_score")


def weekdays_from(start: date, count: int) -> list[date]:
    days, cursor = [], start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


SESSIONS = weekdays_from(T + timedelta(days=1), 20)
# 20 weekday sessions up to T (T included): the liquidity window
HISTORY = [day for day in weekdays_from(T - timedelta(days=40), 40) if day < T][-19:]


def instrument(db, symbol, kind="stock"):
    row = Instrument(
        exchange="TWSE", symbol=symbol, name=f"名{symbol}", instrument_type=kind
    )
    db.add(row)
    db.flush()
    return row


def bars(db, row, prices, *, volume=2_000_000):
    """The history at T's close, T's close, then (open, close) on each
    session; None leaves a session out."""

    days = [*HISTORY, T, *SESSIONS]
    prices = [prices[0]] * len(HISTORY) + list(prices)
    for day, price in zip(days, prices, strict=False):
        if price is None:
            continue
        o, c = price if isinstance(price, tuple) else (price, price)
        db.add(
            MarketBar(
                instrument_id=row.id,
                trading_date=day,
                open=o,
                high=max(o, c),
                low=min(o, c),
                close=c,
                adj_close=c,
                volume=volume,
                turnover=c * volume,
                source="fixture",
            )
        )


def source(name):
    return {"source": name, "value": {}, "data_date": T.isoformat(), "source_ids": []}


def pool_item(db, run, row, sources, *, tier, selected=True, reject=None, rank=None):
    item = CandidatePoolItem(
        run_id=run.id,
        trading_date=T,
        version="candidate_pool_v1",
        phase=run.phase,
        instrument_id=row.id,
        rank=rank,
        tier=tier,
        selected=selected,
        reject_reason=reject,
        source_count=len(sources),
        sources_json=[source(name) for name in sources],
    )
    db.add(item)
    db.flush()
    return item


@pytest.fixture
def copy(tmp_path):
    """The copy on disk (the tool opens it read only) and its stocks."""

    path = tmp_path / "copy.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        taiex = instrument(db, "TAIEX", "index")
        bars(db, taiex, [20000] * 21)
        stocks = {name: instrument(db, name) for name in ("A", "B", "C", "E", "P")}
        bars(db, stocks["A"], [100, (101, 103), *[105] * 19])
        bars(db, stocks["B"], [50, (50, 49), *[47] * 19])
        bars(db, stocks["C"], [30, (30, 31), *[33] * 19])
        # E has no bar on session 3: incomparable at T+5 and T+20.
        bars(db, stocks["E"], [20, (20, 20), 20, None, *[21] * 17])
        # P trades 500 lots a day: in the population, not liquid
        bars(db, stocks["P"], [40, (40, 40), *[40] * 19], volume=500_000)
        run = CandidatePoolRun(
            trading_date=T,
            version="candidate_pool_v1",
            phase="evening",
            status="computed",
            cap=40,
            config_json={"liquidity_days": 20, "min_average_lots": 1000.0},
            computed_at=datetime(2026, 12, 1, 13, 40),
        )
        db.add(run)
        db.flush()
        items = {
            "A": pool_item(
                db, run, stocks["A"], ["rule_signal", "news"], tier=2, rank=1
            ),
            "B": pool_item(db, run, stocks["B"], ["volume"], tier=5, rank=2),
            "E": pool_item(db, run, stocks["E"], ["volume"], tier=5, rank=3),
            "C": pool_item(
                db, run, stocks["C"], ["chips"], tier=5, selected=False, reject="cap"
            ),
        }
        db.commit()
        ids = {name: row.id for name, row in stocks.items()}
        item_ids = {name: row.id for name, row in items.items()}
    engine.dispose()
    return {"path": path, "ids": ids, "items": item_ids}


def built(copy) -> dict:
    return cps.build(copy["path"], None)


def test_the_returns_and_the_population_are_the_ai_scores_own(copy):
    result = built(copy)
    engine = create_engine(f"sqlite:///{copy['path']}")
    with Session(engine) as db:
        for horizon, length in cps.HORIZONS.items():
            population = scoring.population(db, T, SESSIONS, length)
            [got] = result["horizons"][horizon]["population"]
            got = {key: value for key, value in got.items() if key != "liquid"}
            assert got == {
                "t": T.isoformat(),
                "d": SESSIONS[0].isoformat(),
                **population,
            }
            for name in ("A", "B"):
                tracked = pipeline._tracking_inputs(
                    db, copy["ids"][name], T, evaluation_cutoff=SESSIONS[-1]
                )[1]
                hold = score.open_hold(tracked, SESSIONS, length)
                [day] = result["horizons"][horizon]["groups"][
                    cps.source_key("rule_signal" if name == "A" else "volume")
                ]["daily"]
                assert hold["status"] == "comparable"
                assert day["mean"] == pytest.approx(hold["return"])
                assert day["excess"] == pytest.approx(
                    hold["return"] - population["mean"]
                )
    engine.dispose()


def test_a_stock_counts_once_in_each_of_its_sources(copy):
    groups = built(copy)["horizons"]["5"]["groups"]
    a = groups[cps.source_key("rule_signal")]["daily"][0]["mean"]
    assert groups[cps.source_key("news")]["daily"][0]["mean"] == a
    assert groups[cps.source_key("rule_signal")]["stocks"] == 1
    # B and E are volume; E has no bar on session 3, so only B is comparable.
    assert groups[cps.source_key("volume")]["stocks"] == 1
    assert built(copy)["only_source"] == {"volume": 2}


def test_a_source_without_stocks_that_day_has_no_day(copy):
    groups = built(copy)["horizons"]["5"]["groups"]
    assert groups[cps.source_key("hot_theme")]["days"] == 0
    assert groups[cps.source_key("hot_theme")]["verdict"] == "樣本不足"


def test_the_capped_group_is_the_left_out_only(copy):
    result = built(copy)
    groups = result["horizons"]["5"]["groups"]
    assert groups[cps.REJECTED]["stocks"] == 1
    # C is chips but left out: no chips day.
    assert groups[cps.source_key("chips")]["days"] == 0
    assert groups[cps.POOL]["stocks"] == 2
    assert result["rejected"] == {"cap": 1}


def add_reading(db, copy, role, version, calls):
    now = datetime(2026, 12, 2, 0, 25)
    reading = PremarketAiReading(
        session_date=SESSIONS[0],
        list_date=T,
        role=role,
        sequence=1,
        trigger="scheduler",
        prompt_version=version,
        prompt_sha256="0" * 64,
        schema_sha256="0" * 64,
        model_alias="sonnet",
        pool_phase="evening",
        cutoff_at=now,
        input_hash="0" * 64,
        input_json={"pool": {"today_list_count": 0}},
        output_json={"market": {"stance": "neutral", "confidence": "low"}},
        status="done",
        attempts=1,
        duration_ms=0,
        started_at=now,
        finished_at=now,
    )
    db.add(reading)
    db.flush()
    for position, (name, action) in enumerate(calls, start=1):
        db.add(
            PremarketAiStock(
                reading_id=reading.id,
                session_date=SESSIONS[0],
                prompt_version=version,
                role=role,
                instrument_id=copy["ids"][name],
                symbol=name,
                position=position,
                on_today_list=False,
                pool_item_id=copy["items"][name],
                action=action,
            )
        )
    db.flush()
    return reading


def scored(copy, readings) -> None:
    """The readings, scored by the daily's own step through the last session."""

    engine = create_engine(f"sqlite:///{copy['path']}")
    with Session(engine) as db:
        for role, version, calls in readings:
            add_reading(db, copy, role, version, calls)
        db.add_all(scoring.score_readings(db, SESSIONS[-1]))
        db.commit()
    engine.dispose()


def test_the_ai_group_is_the_champions_keep_and_reprice_and_equals_its_score(copy):
    scored(
        copy,
        [
            (
                "champion",
                "premarket_v1",
                [("A", "keep"), ("B", "defer"), ("E", "keep")],
            ),
            ("shadow", "premarket_v9", [("A", "defer"), ("B", "keep"), ("E", "keep")]),
        ],
    )
    result = built(copy)
    for horizon in cps.HORIZONS:
        part = result["horizons"][horizon]
        group = part["groups"][cps.AI_KEPT]
        # A only: B deferred, E incomparable, the shadow not read
        assert group["stocks"] == 1
        assert part["ai_check"] == {"compared": 1, "differ": []}
        assert (
            group["daily"][0]["mean"]
            == part["groups"][cps.source_key("rule_signal")]["daily"][0]["mean"]
        )


def test_the_ai_group_waits_for_the_score_rows(copy):
    groups = built(copy)["horizons"]
    assert groups["5"]["groups"][cps.AI_KEPT]["days"] == 0
    assert groups["5"]["ai_check"] == {"compared": 0, "differ": []}


def test_the_liquid_population_is_a_reference_on_the_evening_floor(copy):
    result = built(copy)
    [day] = result["horizons"]["5"]["population"]
    # A, B, C, E trade 2,000 lots a day; P 500: P is in the population only
    assert day["members"] == 5
    assert day["liquid"]["members"] == 4
    group = result["horizons"]["5"]["groups"][cps.source_key("rule_signal")]
    expected = group["daily"][0]["mean"] - day["liquid"]["mean"]
    assert group["liquid_reference"] == {"days": 1, "mean": pytest.approx(expected)}
    assert result["comparisons"] == 54


def test_a_day_without_the_evening_floor_has_no_liquid_value(copy):
    con = sqlite3.connect(copy["path"])
    con.execute("update candidate_pool_runs set config_json = '{}'")
    con.commit()
    con.close()
    result = built(copy)
    assert result["horizons"]["5"]["population"][0]["liquid"] is None
    group = result["horizons"]["5"]["groups"][cps.source_key("rule_signal")]
    assert group["liquid_reference"] == {"days": 0, "mean": None}
    assert "| 無資料 |" in cps.markdown(result, "cmd")


def test_the_verdict_waits_for_sixty_days():
    short = {"days": 59, "mean": -0.01, "t": -5.0}
    assert cps.verdict(short) == "樣本不足"
    assert cps.verdict({**short, "days": 60}) == "輸給基準"
    assert cps.verdict({**short, "days": 60, "mean": 0.01, "t": 5.0}) == "通過"


def test_the_command_writes_the_tables_with_no_clock(copy, tmp_path, monkeypatch):
    monkeypatch.setattr(
        cps.lib._load("exit_research"), "refusals", lambda db, min_free_gb: []
    )
    first, second = tmp_path / "one", tmp_path / "two"
    for out in (first, second):
        assert cps.main(["--db", str(copy["path"]), "--out", str(out)]) == 0
    assert (first / "tables.json").read_text(encoding="utf-8") == (
        second / "tables.json"
    ).read_text(encoding="utf-8")
    assert (
        json.loads((first / "tables.json").read_text(encoding="utf-8"))["pool_days"]
        == 1
    )
    assert "候選池的對答案" in (first / "summary.md").read_text(encoding="utf-8")
