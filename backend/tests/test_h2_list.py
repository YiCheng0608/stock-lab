"""H2 名單 (Issue #881): the frozen X2 definition, daily step, API, migration.

AC-2 is a golden comparison: one fixture database, every session of it, and
``tools/research/explore_research``'s X2 picks (``plan``) against
``app.h2_list`` (code and rank, and the value).  The fixture holds each point
of the AC-1 decision (#881 7045371555): ties, missing values that fill the
list when fewer than 20 have one, fewer than 240 bars, a suspended T (the
flag, and a zero-volume bar with four equal prices), such a bar inside the
window, days without a bar, a bar off the sessions, an ``ipo`` and an ``etf``,
the 1,000-lot line, a split and a cash dividend in the window (one without a
reference price), and a dividend after T.  AC-3 is the daily step, the API and
migration 0034 (up and down).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

import app.api as api_module
import app.main as main_module
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
from app import h2_list, migrations
from app.db import enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_VERSION
from app.main import app
from app.migration_revisions import REVISIONS
from app.migrations import upgrade_database
from app.models import (
    CandidateRun,
    CorporateAction,
    DailyCandidate,
    H2Item,
    H2Run,
    Instrument,
    MarketBar,
    Signal,
)
from test_daily_schedule import Steps, runs
from worker.cli import DAILY_EXIT_CODES
from worker.h2_list import run_h2_list

ROOT = Path(__file__).resolve().parents[2]
REAL_H2_STEP = schedule_runs._h2_list_step


def _research(name: str):
    """A tools/research module, the one already loaded when there is one
    (test_explore_research loads the same names)."""

    if name in sys.modules:
        return sys.modules[name]
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


explore = _research("explore_research")

# --- the fixture ----------------------------------------------------------

N = 300


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


DAYS = weekdays(date(2025, 1, 6), N)
T = DAYS[-1]
BASE = range(1, 7)  # ordinary stocks from the first session
LATE = range(7, 17)  # listed at session 40: 240 bars from session 279 on
LATE_FROM = 40
IPO, ETF, THIN, EDGE, TWIN, NO_HIGH, SUSPENDED, GAPS, SPLIT, CASH, AFTER = range(25, 36)
NO_HIGH_AT = 285  # a null high: missing from here on
FLAG_AT, FLAT_AT = 260, 270  # SUSPENDED: is_suspended on 260, zero volume on 270
GAP = range(100, 110)  # GAPS has no bar on these sessions
SPLIT_AT, CASH_AT = 250, 280
OFF_SESSION = DAYS[150] + timedelta(days=(5 - DAYS[150].weekday()) % 7)  # a Saturday
KINDS = {IPO: "ipo", ETF: "etf"}
VOLUMES = {THIN: 999_000, EDGE: 1_000_000}  # 999 and exactly 1,000 lots


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def prices(i: int) -> list[tuple[float, float, float, float]]:
    """(open, high, low, close) of every session: a drift by id and noise."""

    drift = ((i % 7) - 3) * 0.0008
    level, out = 50.0 + 3 * i, []
    for t in range(N):
        prior = level
        level *= 1.0 + drift + 0.03 * noise(i, t)
        open_ = prior * (1 + 0.006 * noise(i, t, "o"))
        high = max(open_, level) * (1 + 0.01 * abs(noise(i, t, "h")))
        low = min(open_, level) * (1 - 0.01 * abs(noise(i, t, "l")))
        out.append((round(open_, 2), round(high, 2), round(low, 2), round(level, 2)))
    return out


def ids() -> list[int]:
    return [*BASE, *LATE, *range(IPO, AFTER + 1)]


def _bar(i, day, o, h, low, c, volume, suspended=False):
    return {
        "instrument_id": i,
        "trading_date": day,
        "open": o,
        "high": h,
        "low": low,
        "close": c,
        "adj_close": c,
        "volume": volume,
        "turnover": (c or 0) * volume,
        "turnover_status": "available",
        "source": "test",
        "is_suspended": suspended,
    }


def bars_of(i: int) -> list[dict]:
    source = prices(3 if i == TWIN else i)  # TWIN copies stock 3: a tie
    volume = VOLUMES.get(i, 2_000_000 + 10_000 * i)
    rows = []
    for t, day in enumerate(DAYS):
        if i in LATE and t < LATE_FROM:
            continue
        if i == GAPS and t in GAP:
            continue
        o, h, low, c = source[t]
        if i == SPLIT and t >= SPLIT_AT:  # 2-for-1 from SPLIT_AT
            o, h, low, c = (round(v / 2, 2) for v in (o, h, low, c))
        if i == CASH and t >= CASH_AT:  # a 3.0 cash dividend from CASH_AT
            o, h, low, c = (round(v - 3.0, 2) for v in (o, h, low, c))
        if i == AFTER and t >= N - 1:
            o, h, low, c = (round(v - 2.0, 2) for v in (o, h, low, c))
        if i == NO_HIGH and t == NO_HIGH_AT:
            h = None
        if i == SUSPENDED and t == FLAT_AT:
            # zero volume, four equal prices, above every high around it
            flat = round(source[t - 1][3] * 1.3, 2)
            rows.append(_bar(i, day, flat, flat, flat, flat, 0))
            continue
        rows.append(_bar(i, day, o, h, low, c, volume, i == SUSPENDED and t == FLAG_AT))
        if i == IPO and day == DAYS[150]:
            # a bar off the sessions (no stock trades that day): never read
            rows.append(_bar(i, OFF_SESSION, c, c * 100, c, c, volume))
    return rows


def actions() -> list[dict]:
    split_day, cash_day, after_day = DAYS[SPLIT_AT], DAYS[CASH_AT], DAYS[N - 1]
    return [
        {
            "instrument_id": SPLIT,
            "action_date": split_day,
            "action_type": "split",
            "split_ratio": 2.0,
            "source": "test",
        },
        {
            # no reference price: the close of the bar before is the fallback
            "instrument_id": CASH,
            "action_date": cash_day,
            "action_type": "cash_dividend",
            "cash_dividend": 3.0,
            "source": "test",
        },
        {
            "instrument_id": AFTER,
            "action_date": after_day,
            "action_type": "cash_dividend",
            "cash_dividend": 2.0,
            "reference_price": 80.0,
            "source": "test",
        },
    ]


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    upgrade_database(engine)
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "market": "TW",
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": KINDS.get(i, "stock"),
                    "status": "active",
                }
                for i in ids()
            ],
        )
        db.execute(insert(MarketBar), [row for i in ids() for row in bars_of(i)])
        db.execute(insert(CorporateAction), actions())
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def golden_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("h2") / "golden.db")


def research_picks(db: Path, raw_dir: Path) -> dict[date, list[tuple]]:
    """explore_research's X2 rows of every session: (symbol, value) by rank."""

    ctx = explore.load_context(db, explore.LOAD_FROM, DAYS[-1], raw_dir)
    sessions = ctx.market.panel.sessions
    planned = explore.plan(ctx, explore.HYPOTHESES["X2"], 1, len(sessions))
    out: dict[date, list[tuple]] = {}
    for row in planned.rows:
        day = date.fromisoformat(row["signal_date"])
        out.setdefault(day, []).append(
            (row["rank"], row["symbol"], row["high_gap_240"])
        )
    return {day: [row[1:] for row in sorted(rows)] for day, rows in out.items()}


def product_picks(db, day: date) -> tuple[list[tuple], list[h2_list.Member]]:
    members = h2_list.universe(db, day)
    symbols = dict(db.execute(select(Instrument.id, Instrument.symbol)).all())
    items = h2_list.rank_members(day, members)
    return [(symbols[item.instrument_id], item.high_gap_240) for item in items], members


@pytest.fixture(scope="module")
def compared(golden_db, tmp_path_factory):
    # research_report.load_actions sets these three: put them back.
    keys = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")
    saved = {key: os.environ.get(key) for key in keys}
    try:
        research = research_picks(golden_db, tmp_path_factory.mktemp("raw"))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    engine = create_engine(f"sqlite:///{golden_db.as_posix()}")
    product, universes = {}, {}
    with Session(engine) as db:
        for day in DAYS:
            product[day], universes[day] = product_picks(db, day)
    engine.dispose()
    return research, product, universes


def _same(research_rows, product_rows) -> bool:
    if [s for s, _ in research_rows] != [s for s, _ in product_rows]:
        return False
    for (_, a), (_, b) in zip(research_rows, product_rows):
        if (a is None) != (b is None):
            return False
        if a is not None and a != pytest.approx(b, rel=1e-12, abs=1e-15):
            return False
    return True


# --- AC-2: the definition and the golden comparison -------------------------


def test_the_definition_is_the_frozen_research_one():
    assert explore.VERSION == 2
    assert explore.definitions_sha256() == h2_list.DEFINITIONS_SHA256
    spec = explore.HYPOTHESES["X2"]
    assert (spec["rule"], spec["subset"], spec["filters"]) == ("daily", None, ())
    assert spec["keys"] == ("high_gap_240",)
    assert spec["top"] == h2_list.LIST_SIZE == 20
    assert spec["start"][2] == h2_list.WINDOW == 240
    assert explore.MIN_LOTS == h2_list.MIN_AVERAGE_LOTS
    research_report = _research("research_report")
    assert research_report.BENCHMARK_TYPES == h2_list.INSTRUMENT_TYPES
    assert explore.LOAD_FROM == h2_list.ACTIONS_AFTER
    assert h2_list.H2_VERSION == "explore_research_v2_X2"


def test_every_session_is_the_research_list(compared):
    research, product, _ = compared
    days = [day for day in DAYS if product[day]]
    assert len(days) > 250  # every day with a universe (20 bars on)
    assert set(research) == set(days)
    different = [day for day in days if not _same(research[day], product[day])]
    assert different == []


def test_fewer_than_twenty_values_fill_the_list_with_missing_ones(compared):
    research, product, universes = compared
    day = DAYS[245]
    valued = [m for m in universes[day] if m.high_gap_240 is not None]
    assert 0 < len(valued) < 20 and len(universes[day]) >= 20
    values = [value for _s, value in product[day]]
    assert len(values) == 20
    assert all(v is not None for v in values[: len(valued)])
    assert values[len(valued) :] == [None] * (20 - len(valued))
    assert _same(research[day], product[day])
    # From session 279 the late listings have 240 bars: no missing one is listed.
    last = DAYS[-1]
    assert all(value is not None for _s, value in product[last])
    assert any(m.high_gap_240 is None for m in universes[last])


def test_fewer_than_240_bars_and_a_null_high_are_missing(compared):
    _, _, universes = compared

    def value(day_index, instrument_id):
        found = [
            m.high_gap_240
            for m in universes[DAYS[day_index]]
            if m.instrument_id == instrument_id
        ]
        assert found, (day_index, instrument_id)
        return found[0]

    assert value(LATE_FROM + 238, 7) is None
    assert value(LATE_FROM + 239, 7) is not None
    assert value(NO_HIGH_AT - 1, NO_HIGH) is not None
    assert value(NO_HIGH_AT, NO_HIGH) is None
    assert value(N - 1, NO_HIGH) is None
    # GAPS has 10 days without a bar: its 240 bars end ten sessions later.
    assert value(248, GAPS) is None
    assert value(249, GAPS) is not None


def test_ties_are_ordered_by_the_hash(compared):
    research, product, universes = compared
    listed_together = 0
    for day in DAYS[239:]:
        values = {m.instrument_id: m.high_gap_240 for m in universes[day]}
        assert values[3] == values[TWIN] is not None
        symbols = [s for s, _ in product[day]]
        if "S3" not in symbols or f"S{TWIN}" not in symbols:
            continue
        listed_together += 1
        first, second = sorted((3, TWIN), key=lambda i: h2_list.tie_key(day, i))
        assert symbols.index(f"S{first}") < symbols.index(f"S{second}")
        assert _same(research[day], product[day])
    assert listed_together > 0
    tied_missing = [s for s, v in product[DAYS[245]] if v is None]
    assert len(tied_missing) > 1  # the missing ones are ordered by the hash alone
    assert _same(research[DAYS[245]], product[DAYS[245]])


def test_a_suspended_t_is_out_and_a_flat_bar_in_the_window_counts(compared):
    research, product, universes = compared

    def members(day_index):
        return {m.instrument_id: m for m in universes[DAYS[day_index]]}

    assert SUSPENDED not in members(FLAG_AT)  # is_suspended
    assert SUSPENDED not in members(FLAT_AT)  # zero volume, four equal prices
    assert SUSPENDED in members(FLAT_AT + 1)
    # The flat bar is the window's high: T's close over it, on the next day.
    after = members(FLAT_AT + 1)[SUSPENDED].high_gap_240
    flat = round(prices(SUSPENDED)[FLAT_AT - 1][3] * 1.3, 2)
    close = prices(SUSPENDED)[FLAT_AT + 1][3]
    assert after == pytest.approx(close / flat - 1.0)
    for day_index in (FLAG_AT, FLAT_AT, FLAT_AT + 1, N - 1):
        assert _same(research[DAYS[day_index]], product[DAYS[day_index]])


def test_types_and_the_liquidity_line(compared):
    _, _, universes = compared
    seen = {m.instrument_id for day in DAYS for m in universes[day]}
    assert IPO in seen and EDGE in seen  # an ipo; exactly 1,000 lots
    assert ETF not in seen and THIN not in seen  # an etf; 999 lots


def test_the_off_session_bar_is_not_read(compared):
    _, _, universes = compared
    value = {m.instrument_id: m.high_gap_240 for m in universes[DAYS[-1]]}[IPO]
    assert value is not None and value > -0.9  # its high of 100× is not the peak


def test_a_split_and_a_dividend_in_the_window_are_adjusted(compared):
    research, product, universes = compared
    for instrument_id, at in ((SPLIT, SPLIT_AT), (CASH, CASH_AT)):
        for day_index in (at, at + 5, N - 1):
            value = {
                m.instrument_id: m.high_gap_240 for m in universes[DAYS[day_index]]
            }[instrument_id]
            assert value is not None and value > -0.3, (instrument_id, day_index)
            assert _same(research[DAYS[day_index]], product[DAYS[day_index]])


def test_a_dividend_after_t_changes_nothing(compared, golden_db):
    research, product, universes = compared
    day = DAYS[N - 2]  # AFTER's dividend is on the next session
    engine = create_engine(f"sqlite:///{golden_db.as_posix()}")
    with Session(engine) as db:
        assert db.scalar(
            select(func.count())
            .select_from(CorporateAction)
            .where(
                CorporateAction.instrument_id == AFTER,
                CorporateAction.action_date > day,
            )
        )
        assert h2_list.action_factors(db, AFTER, day) == []
    engine.dispose()
    assert AFTER in {m.instrument_id for m in universes[day]}
    assert _same(research[day], product[day])


# --- AC-3: the daily step -------------------------------------------------


@pytest.fixture
def factory(golden_db, tmp_path, monkeypatch):
    path = tmp_path / "h2.db"
    shutil.copy(golden_db, path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with make() as db:
            yield db

    monkeypatch.setattr(pipeline, "SessionLocal", make)
    monkeypatch.setattr(pipeline, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "check_database_readiness", lambda: None)
    app.dependency_overrides[api_module.get_db] = override_get_db
    yield make
    app.dependency_overrides.pop(api_module.get_db, None)
    engine.dispose()


def _real_h2(monkeypatch, **results):
    steps = Steps(monkeypatch, **results)
    monkeypatch.setattr(schedule_runs, "_h2_list_step", REAL_H2_STEP)
    return steps


def _stored(make, day=T):
    with make() as db:
        run = db.scalar(select(H2Run).where(H2Run.trading_date == day))
        items = db.scalars(
            select(H2Item).where(H2Item.h2_run_id == run.id).order_by(H2Item.rank)
        ).all()
        symbols = dict(db.execute(select(Instrument.id, Instrument.symbol)).all())
        return run, [(symbols[item.instrument_id], item.high_gap_240) for item in items]


def test_the_daily_writes_the_day_after_mainstream(factory, monkeypatch, compared):
    research, _, _ = compared
    steps = _real_h2(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert result["h2_list"]["status"] == "success"
    assert steps.calls.index("mainstream") < steps.calls.index("plan_tracking")
    rows, by_run = runs(factory)
    logged = by_run[rows[0].id]
    step = logged["h2_list"]
    assert (step.status, step.records, step.sequence) == ("success", 20, 8)
    assert logged["mainstream"].sequence < step.sequence
    run, items = _stored(factory)
    assert (run.status, run.version, run.definitions_sha256) == (
        "computed",
        "explore_research_v2_X2",
        h2_list.DEFINITIONS_SHA256,
    )
    assert run.config_json == h2_list.H2_CONFIG
    assert (run.item_count, len(items)) == (20, 20)
    assert _same(research[T], items)


def test_a_rerun_of_the_day_replaces_it(factory):
    day = DAYS[245]
    assert run_h2_list(day)["records"] == 20
    first_run, first = _stored(factory, day)
    with factory() as db:
        # S1 is suspended on the day before the rerun: it must leave the list.
        db.execute(
            MarketBar.__table__.update()
            .where(MarketBar.instrument_id == 1, MarketBar.trading_date == day)
            .values(is_suspended=True)
        )
        db.commit()
    assert "S1" in [s for s, _ in first]
    assert run_h2_list(day)["records"] == 20
    run, again = _stored(factory, day)
    assert "S1" not in [s for s, _ in again]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(H2Run)) == 1
        assert db.scalar(select(func.count()).select_from(H2Item)) == 20
        assert {item.h2_run_id for item in db.scalars(select(H2Item))} == {run.id}


def test_a_failure_is_a_warning_and_keeps_the_run_and_the_previous_list(
    factory, monkeypatch, capsys
):
    assert run_h2_list(T)["records"] == 20

    def broken(db, day):
        raise RuntimeError("fixture h2 crash")

    monkeypatch.setattr("worker.h2_list.compute_h2", broken)
    _real_h2(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert DAILY_EXIT_CODES[result["status"]] == 0
    assert "warning: explore_research_v2_X2" in capsys.readouterr().err
    rows, by_run = runs(factory)
    assert rows[0].status == "success" and rows[0].error is None
    assert by_run[rows[0].id]["h2_list"].status == "failed"
    assert rows[0].summary_json["steps"]["h2_list"] == "failed"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(H2Item)) == 20


def test_a_day_that_is_not_a_session_fails_without_writing(factory):
    result = run_h2_list(T + timedelta(days=1))  # a Saturday
    assert result["status"] == "failed" and "H2DataError" in result["error"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(H2Run)) == 0


# --- AC-3: the API --------------------------------------------------------


def _today_list(make, day, ranks):
    with make() as db:
        run = CandidateRun(trading_date=day, score_version=CANDIDATE_SCORE_VERSION)
        db.add(run)
        db.flush()
        for instrument_id, (rank, entry_type) in ranks.items():
            signal = Signal(
                signal_key=f"fixture-{instrument_id}",
                signal_date=day,
                instrument_id=instrument_id,
                status="conditional",
                entry_type=entry_type,
            )
            db.add(signal)
            db.flush()
            db.add(
                DailyCandidate(
                    candidate_run_id=run.id,
                    trading_date=day,
                    instrument_id=instrument_id,
                    signal_id=signal.id,
                    strategy="breakout_v3",
                    score_version=CANDIDATE_SCORE_VERSION,
                    total_score=80.0,
                    weight_coverage=1.0,
                    rank=rank,
                    data_as_of=day,
                )
            )
        db.commit()


def test_the_api_returns_the_latest_and_a_date_with_the_today_list(factory):
    earlier = DAYS[245]
    run_h2_list(earlier)
    run_h2_list(T)
    _, items = _stored(factory)
    with factory() as db:
        by_symbol = dict(db.execute(select(Instrument.symbol, Instrument.id)).all())
    first, third = by_symbol[items[0][0]], by_symbol[items[2][0]]
    _today_list(factory, T, {first: (4, "breakout"), third: (9, "pullback")})
    client = TestClient(app)
    body = client.get("/api/h2").json()
    assert body == client.get(f"/api/h2?date={T.isoformat()}").json()
    assert (body["status"], body["trading_date"], body["version"]) == (
        "computed",
        T.isoformat(),
        "explore_research_v2_X2",
    )
    assert body["definitions_sha256"] == h2_list.DEFINITIONS_SHA256
    assert body["window"] == 240 and body["universe_count"] > 20
    assert body["computed_at"].endswith("+00:00")
    rows = body["items"]
    assert [row["rank"] for row in rows] == list(range(1, 21))
    assert [(row["instrument"]["symbol"], row["high_gap_240"]) for row in rows] == [
        (symbol, pytest.approx(value)) for symbol, value in items
    ]
    top = rows[0]
    assert set(top) == {"rank", "instrument", "high_gap_240", "close", "today_list"}
    assert set(top["instrument"]) == {
        "id",
        "exchange",
        "symbol",
        "name",
        "instrument_type",
    }
    with factory() as db:
        close = db.scalar(
            select(MarketBar.close).where(
                MarketBar.instrument_id == first, MarketBar.trading_date == T
            )
        )
    assert top["close"] == close
    marks = [row["today_list"] for row in rows]
    assert marks[0] == {
        "rank": 4,
        "entry_type": "breakout",
        "score_version": CANDIDATE_SCORE_VERSION,
    }
    assert marks[2]["rank"] == 9 and marks[1] is None
    assert sum(mark is not None for mark in marks) == 2
    # No price levels: the list is not a signal.
    assert not {"entry_zone", "stop", "target", "levels"} & set(top)
    older = client.get(f"/api/h2?date={earlier.isoformat()}").json()
    assert older["trading_date"] == earlier.isoformat()
    assert [row["today_list"] for row in older["items"]] == [None] * 20
    assert older["items"][-1]["high_gap_240"] is None  # a missing value, as null


def test_a_day_without_a_list_is_missing(factory):
    client = TestClient(app)
    assert client.get("/api/h2").json() == {
        "status": "missing",
        "trading_date": None,
        "version": "explore_research_v2_X2",
        "definitions_sha256": h2_list.DEFINITIONS_SHA256,
        "window": 240,
        "computed_at": None,
        "universe_count": None,
        "items": [],
    }
    run_h2_list(T)
    body = client.get(f"/api/h2?date={DAYS[-2].isoformat()}").json()
    assert (body["status"], body["trading_date"], body["items"]) == (
        "missing",
        DAYS[-2].isoformat(),
        [],
    )


def test_a_day_with_an_empty_universe_is_zero(factory):
    day = DAYS[10]  # no stock has 20 bars yet
    assert run_h2_list(day)["list_status"] == "zero"
    body = TestClient(app).get(f"/api/h2?date={day.isoformat()}").json()
    assert (body["status"], body["universe_count"], body["items"]) == ("zero", 0, [])


# --- migration 0034 -------------------------------------------------------


def _shape(path: Path) -> dict:
    with closing(sqlite3.connect(path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        out = {"tables": tables & {"h2_runs", "h2_items", "mainstream_runs"}}
        for table in ("h2_runs", "h2_items"):
            if table not in tables:
                continue
            out[table] = {
                "indexes": {
                    row[1]: [
                        info[2]
                        for info in connection.execute(f"PRAGMA index_info('{row[1]}')")
                    ]
                    for row in connection.execute(f"PRAGMA index_list('{table}')")
                },
                "foreign": {
                    row[3]: row[2]
                    for row in connection.execute(f"PRAGMA foreign_key_list('{table}')")
                },
                "not_null": {
                    row[1]: bool(row[3])
                    for row in connection.execute(f"PRAGMA table_info('{table}')")
                },
            }
        if "alembic_version" in tables:
            out["alembic"] = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
        if "schema_migrations" in tables:
            out["fallback"] = connection.execute(
                "SELECT version FROM schema_migrations WHERE version = '0034_h2_lists'"
            ).fetchall()
    return out


def _check_head(shape: dict) -> None:
    assert shape["tables"] == {"h2_runs", "h2_items", "mainstream_runs"}
    runs_shape, items_shape = shape["h2_runs"], shape["h2_items"]
    assert runs_shape["indexes"]["ix_h2_runs_trading_date"] == ["trading_date"]
    assert ["trading_date", "version"] in runs_shape["indexes"].values()
    for column in ("h2_run_id", "trading_date", "instrument_id"):
        assert items_shape["indexes"][f"ix_h2_items_{column}"] == [column]
    assert ["trading_date", "instrument_id", "version"] in items_shape[
        "indexes"
    ].values()
    assert runs_shape["foreign"] == {}
    assert items_shape["foreign"] == {
        "h2_run_id": "h2_runs",
        "instrument_id": "instruments",
    }
    assert set(runs_shape["not_null"]) == {c.name for c in H2Run.__table__.columns}
    assert all(runs_shape["not_null"].values())
    assert set(items_shape["not_null"]) == {c.name for c in H2Item.__table__.columns}
    assert {k for k, v in items_shape["not_null"].items() if not v} == {"high_gap_240"}


def _alembic_config(engine):
    from alembic.config import Config

    config = Config(str(migrations.ALEMBIC_CONFIG_PATH))
    config.set_main_option(
        "script_location", str(Path(migrations.ALEMBIC_CONFIG_PATH).parent / "alembic")
    )
    config.attributes["connection"] = engine
    return config


@pytest.mark.parametrize("entry", ["alembic", "fallback"])
def test_the_upgrade_adds_the_two_tables(tmp_path, monkeypatch, entry):
    if entry == "alembic":
        pytest.importorskip("alembic")
    path = tmp_path / f"{entry}.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    if entry == "fallback":
        monkeypatch.setattr(migrations, "ALEMBIC_CONFIG_PATH", tmp_path / "absent.ini")
    try:
        upgrade_database(engine)
    finally:
        engine.dispose()
    shape = _shape(path)
    _check_head(shape)
    if entry == "alembic":
        # Later revisions move the head: 0034 is in the chain below it.
        assert "0034_h2_lists" in REVISIONS
        assert shape["alembic"] == [(REVISIONS[-1],)]
    else:
        assert shape["fallback"] == [("0034_h2_lists",)]


def test_the_downgrade_drops_the_two_tables_and_the_upgrade_makes_them_again(
    tmp_path,
):
    pytest.importorskip("alembic")
    from alembic import command

    path = tmp_path / "down.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    enable_sqlite_foreign_keys(engine)
    # To 0034 itself, not the head: a later forward-only revision cannot go down.
    config = _alembic_config(engine)
    try:
        command.upgrade(config, "0034_h2_lists")
        command.downgrade(config, "0033_mainstream_lists")
        down = _shape(path)
        assert down["tables"] == {"mainstream_runs"}
        assert down["alembic"] == [("0033_mainstream_lists",)]
        with closing(sqlite3.connect(path)) as connection:
            assert not connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'ix_h2_%'"
            ).fetchall()
        command.upgrade(config, "0034_h2_lists")
    finally:
        engine.dispose()
    again = _shape(path)
    _check_head(again)
    assert again["alembic"] == [("0034_h2_lists",)]
