"""X4 名單「盈餘殖利率前 20」(Issue #1016): the frozen definition, daily step, API.

AC-1 is a golden comparison: one fixture database, every session of it, and
``tools/research/explore_research``'s X4 picks (``plan``) against
``app.x4_list`` (code and rank, ``eps_yield_raw`` and ``revenue_yoy``).  The
fixture holds each point of the AC: fewer than 20 passing, a revenue month
going stale at 80 days, a quarter going stale at 200 days, the first
quarter's own EPS (the cumulative figure), a quarter without the one before,
a quarter without last year's, a tie, a suspended T (the flag, and a
zero-volume bar with four equal prices), the 1,000-lot line, and a cash
dividend (the research's adjusted close against the product's raw one); and
a month without a revenue, one without last year's, an ``ipo`` and an ``etf``.
AC-2 is the daily step and AC-3 the API, ``missing`` and both kinds of
``zero``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

import app.api as api_module
import app.main as main_module
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs
from app import h2_list, strategy_lists, x4_list
from app.db import enable_sqlite_foreign_keys
from app.domain import CANDIDATE_SCORE_VERSION
from app.main import app
from app.migrations import upgrade_database
from app.models import (
    CandidateRun,
    CorporateAction,
    DailyCandidate,
    FundamentalSnapshot,
    Instrument,
    MarketBar,
    MonthlyRevenue,
    RawPayload,
    Signal,
    StrategyListItem,
    StrategyListRun,
)
from test_daily_schedule import Steps, runs
from worker.cli import DAILY_EXIT_CODES
from worker.x4_list import run_x4_list

ROOT = Path(__file__).resolve().parents[2]
REAL_X4_STEP = schedule_runs._x4_list_step


def _research(name: str):
    """A tools/research module, the one already loaded when there is one."""

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

N = 110


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def next_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


DAYS = weekdays(date(2025, 1, 6), N)  # 2025-01-06 .. 2025-06-06
T = DAYS[-1]
BASE = range(1, 51)  # ordinary stocks
(
    IPO,
    ETF,
    THIN,
    EDGE,
    TWIN,
    SUSPENDED,
    CASH,
    REV_STALE,
    Q_STALE,
    NO_PREV,
    NO_YEAR,
    REV_NULL,
    NO_PRIOR,
) = range(60, 73)
TWIN_OF = 3  # TWIN copies stock 3: bars, revenues and EPS, a tie
FLAG_AT, FLAT_AT = 60, 70  # SUSPENDED: is_suspended on 60, zero volume on 70
CASH_AT = 50  # a 3.0 cash dividend without a reference price
KINDS = {IPO: "ipo", ETF: "etf"}
VOLUMES = {THIN: 999_000, EDGE: 1_000_000}  # 999 and exactly 1,000 lots
# Months of revenue: 2024-09 .. 2025-05, announced the 10th of the next month.
MONTHS = [
    date(2024, 9, 1),
    date(2024, 10, 1),
    date(2024, 11, 1),
    date(2024, 12, 1),
    *(date(2025, m, 1) for m in range(1, 6)),
]
WEAK_MONTHS = {date(2024, 12, 1), date(2025, 1, 1)}  # most stocks fall
REV_STALE_LAST = date(2025, 2, 1)  # +80 days is 2025-04-22, a Tuesday
REV_NULL_MONTH = date(2025, 4, 1)
NO_PRIOR_MONTH = date(2025, 3, 1)
# (period end, statutory announcement): cumulative EPS of the year.
QUARTERS = [
    (date(2023, 3, 31), date(2023, 5, 15)),
    (date(2023, 6, 30), date(2023, 8, 14)),
    (date(2023, 9, 30), date(2023, 11, 14)),
    (date(2023, 12, 31), date(2024, 3, 31)),
    (date(2024, 3, 31), date(2024, 5, 15)),
    (date(2024, 6, 30), date(2024, 8, 14)),
    (date(2024, 9, 30), date(2024, 11, 14)),  # +200 days is 2025-04-18, a Friday
    (date(2024, 12, 31), date(2025, 3, 31)),
    (date(2025, 3, 31), date(2025, 5, 15)),
]


def noise(i: int, t, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def source_of(i: int) -> int:
    return TWIN_OF if i == TWIN else i


def prices(i: int) -> list[tuple[float, float, float, float]]:
    level, out = 20.0 + 2 * i, []
    for t in range(N):
        prior = level
        level *= 1.0 + 0.03 * noise(i, t)
        open_ = prior * (1 + 0.006 * noise(i, t, "o"))
        high = max(open_, level) * (1 + 0.01 * abs(noise(i, t, "h")))
        low = min(open_, level) * (1 - 0.01 * abs(noise(i, t, "l")))
        out.append((round(open_, 2), round(high, 2), round(low, 2), round(level, 2)))
    return out


def ids() -> list[int]:
    return [*BASE, *range(IPO, NO_PRIOR + 1)]


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
    source = prices(source_of(i))
    volume = VOLUMES.get(i, 2_000_000 + 10_000 * source_of(i))
    rows = []
    for t, day in enumerate(DAYS):
        o, h, low, c = source[t]
        if i == CASH and t >= CASH_AT:
            o, h, low, c = (round(v - 3.0, 2) for v in (o, h, low, c))
        if i == SUSPENDED and t == FLAT_AT:
            flat = source[t - 1][3]
            rows.append(_bar(i, day, flat, flat, flat, flat, 0))
            continue
        rows.append(_bar(i, day, o, h, low, c, volume, i == SUSPENDED and t == FLAG_AT))
    return rows


def actions() -> list[dict]:
    return [
        {
            # no reference price: the close of the bar before is the fallback
            "instrument_id": CASH,
            "action_date": DAYS[CASH_AT],
            "action_type": "cash_dividend",
            "cash_dividend": 3.0,
            "source": "test",
        }
    ]


def yoy_of(i: int, month: date) -> float:
    s = source_of(i)
    if s in (TWIN_OF, CASH):
        return 0.15  # always up
    shift = -0.35 if month in WEAK_MONTHS and s % 3 else 0.25
    return round(0.4 * noise(s, month, "y") + shift, 4)


def revenues_of(i: int) -> list[dict]:
    s, rows = source_of(i), []
    for month in MONTHS:
        if i == REV_STALE and month > REV_STALE_LAST:
            continue
        revenue = round(1000.0 + 37 * s + 50 * noise(s, month, "r"), 1)
        prior = round(revenue / (1.0 + yoy_of(i, month)), 1)
        if i == REV_NULL and month == REV_NULL_MONTH:
            revenue = None
        if i == NO_PRIOR and month == NO_PRIOR_MONTH:
            prior = None
        nxt = date(month.year + month.month // 12, month.month % 12 + 1, 10)
        rows.append(
            {
                "instrument_id": i,
                "revenue_month": month,
                "revenue": revenue,
                "prior_year_revenue": prior,
                "announcement_date": next_weekday(nxt),
                "source": "test",
                "raw_payload_id": 1,
                "data_as_of": "test",
            }
        )
    return rows


def own_eps(s: int, end: date) -> float:
    base = 0.2 + (s % 9) * 0.25 - 0.4
    trend = (-0.1 if s % 4 == 0 else 0.2) * (end.year - 2023)
    if s in (CASH, REV_STALE, Q_STALE):  # high yields: in the list
        base, trend = 3.0, 0.3 * (end.year - 2023)
    elif s == TWIN_OF:
        trend = 0.3 * (end.year - 2023)
    return round(base + trend + 0.1 * noise(s, end, "e"), 2)


def quarters_of(i: int) -> list[dict]:
    s, rows, total = source_of(i), [], {}
    for end, announced in QUARTERS:
        total[end.year] = (0.0 if end.month == 3 else total[end.year]) + own_eps(s, end)
        if i == Q_STALE and end > date(2024, 9, 30):
            continue
        if i == NO_PREV and end == date(2024, 9, 30):
            continue
        if i == NO_YEAR and end == date(2023, 12, 31):
            continue
        rows.append(
            {
                "instrument_id": i,
                "period_end": end,
                "fiscal_period": f"{end.year}Q{(end.month + 2) // 3}",
                "announcement_date": announced,
                "eps": round(total[end.year], 2),
                "source": "test",
            }
        )
    return rows


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
        db.add(RawPayload(id=1, source="test", endpoint="fixture"))
        db.flush()
        db.execute(insert(MonthlyRevenue), [r for i in ids() for r in revenues_of(i)])
        db.execute(
            insert(FundamentalSnapshot), [r for i in ids() for r in quarters_of(i)]
        )
        db.commit()
    engine.dispose()
    return path


@pytest.fixture(scope="module")
def golden_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("x4") / "golden.db")


def research_picks(db: Path, raw_dir: Path) -> dict[date, list[tuple]]:
    """explore_research's X4 rows of every session: (symbol, eps_yield_raw,
    revenue_yoy) by rank."""

    ctx = explore.load_context(db, explore.LOAD_FROM, DAYS[-1], raw_dir)
    sessions = ctx.market.panel.sessions
    planned = explore.plan(ctx, explore.HYPOTHESES["X4"], 1, len(sessions))
    out: dict[date, list[tuple]] = {}
    for row in planned.rows:
        day = date.fromisoformat(row["signal_date"])
        out.setdefault(day, []).append(
            (row["rank"], row["symbol"], row["eps_yield_raw"], row["revenue_yoy"])
        )
    return {day: [row[1:] for row in sorted(rows)] for day, rows in out.items()}


def product_picks(db, day: date) -> tuple[list[tuple], list[x4_list.Member]]:
    members = x4_list.universe(db, day)
    return [
        (f"S{m.instrument_id}", m.eps_yield_raw, m.revenue_yoy)
        for _rank, m in x4_list.rank_members(day, members)
    ], members


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
    if [row[0] for row in research_rows] != [row[0] for row in product_rows]:
        return False
    for a_row, b_row in zip(research_rows, product_rows):
        for a, b in zip(a_row[1:], b_row[1:]):
            if (a is None) != (b is None):
                return False
            if a is not None and a != pytest.approx(b, rel=1e-12, abs=1e-15):
                return False
    return True


def _members(universes, day_index) -> dict[int, x4_list.Member]:
    return {m.instrument_id: m for m in universes[DAYS[day_index]]}


def _index(day: date) -> int:
    return DAYS.index(day)


# --- AC-1: the definition and the golden comparison -------------------------


def test_the_definition_is_the_frozen_research_one():
    assert explore.VERSION == 2
    assert explore.definitions_sha256() == x4_list.DEFINITIONS_SHA256
    spec = explore.HYPOTHESES["X4"]
    assert (spec["rule"], spec["subset"]) == ("daily", None)
    assert spec["filters"] == (
        ("revenue_yoy", ">", 0.0),
        ("eps_growth_yield", ">", 0.0),
    )
    assert spec["keys"] == ("eps_yield_raw",)
    assert spec["top"] == x4_list.LIST_SIZE == 20
    assert explore.MIN_LOTS == x4_list.MIN_AVERAGE_LOTS
    lib = _research("evidence_lib")
    assert lib.REVENUE_STALE_DAYS == x4_list.REVENUE_STALE_DAYS == 80
    assert lib.QUARTER_STALE_DAYS == x4_list.QUARTER_STALE_DAYS == 200
    assert lib.LIQUIDITY_WINDOW == x4_list.LIQUIDITY_BARS == 20
    assert _research("research_report").BENCHMARK_TYPES == x4_list.INSTRUMENT_TYPES
    assert x4_list.X4_VERSION == "explore_research_v2_X4"
    assert strategy_lists.strategy("x4") is x4_list.X4


def test_every_session_is_the_research_list(compared):
    research, product, _ = compared
    days = [day for day in DAYS if product[day]]
    assert len(days) > 80  # every day with a universe (20 bars on)
    assert set(research) == set(days)
    different = [day for day in days if not _same(research[day], product[day])]
    assert different == []


def test_fewer_than_twenty_passing_is_a_shorter_list(compared):
    research, product, universes = compared
    short = [day for day in DAYS if 0 < len(product[day]) < 20]
    full = [day for day in DAYS if len(product[day]) == 20]
    assert short and full
    for day in short:
        members = universes[day]
        assert len(members) > 20  # the universe is larger: nothing fills the list
        assert len(product[day]) == sum(m.passes for m in members)
        assert len(research[day]) == len(product[day])
    for day in full:
        assert sum(m.passes for m in universes[day]) > 20


def test_a_revenue_month_is_stale_after_80_days(compared):
    _, _, universes = compared
    valid, stale = _index(date(2025, 4, 22)), _index(date(2025, 4, 23))
    assert (date(2025, 4, 22) - REV_STALE_LAST).days == 80
    kept = _members(universes, valid)[REV_STALE]
    assert kept.revenue and kept.revenue.month == REV_STALE_LAST
    assert kept.revenue_yoy is not None and kept.passes
    gone = _members(universes, stale)[REV_STALE]
    assert gone.revenue is None and not gone.passes


def test_a_quarter_is_stale_after_200_days(compared):
    research, product, universes = compared
    valid, stale = _index(date(2025, 4, 18)), _index(date(2025, 4, 21))
    assert (date(2025, 4, 18) - date(2024, 9, 30)).days == 200
    kept = _members(universes, valid)[Q_STALE]
    assert kept.quarter and kept.quarter.period_end == date(2024, 9, 30)
    assert kept.passes and f"S{Q_STALE}" in [row[0] for row in product[DAYS[valid]]]
    gone = _members(universes, stale)[Q_STALE]
    assert gone.quarter is None and gone.eps_yield_raw is None and not gone.passes
    for day_index in (valid, stale):
        assert _same(research[DAYS[day_index]], product[DAYS[day_index]])


def test_the_first_quarter_is_its_cumulative_figure(compared):
    _, _, universes = compared
    day = _index(date(2025, 5, 15))
    member = _members(universes, day)[1]
    end = date(2025, 3, 31)
    assert member.quarter.period_end == end
    assert member.quarter.eps == pytest.approx(own_eps(1, end))
    assert member.quarter.year_before == pytest.approx(own_eps(1, date(2024, 3, 31)))
    before = _members(universes, day - 1)[1]
    assert before.quarter.period_end == date(2024, 12, 31)
    assert x4_list.quarter_label(end) == "2025Q1"


def test_a_quarter_without_the_one_before_is_missing(compared):
    _, _, universes = compared
    day = _index(date(2025, 4, 1))  # Q4 2024 known, Q3 2024 never
    member = _members(universes, day)[NO_PREV]
    assert member.quarter is None and not member.passes
    later = _members(universes, _index(date(2025, 5, 15)))[NO_PREV]
    assert later.quarter is not None  # Q1 needs no quarter before


def test_a_quarter_without_last_years_fails_the_growth(compared):
    _, _, universes = compared
    member = _members(universes, _index(date(2025, 4, 1)))[NO_YEAR]
    assert member.quarter is not None and member.quarter.year_before is None
    assert member.eps_yield_raw is not None
    assert member.eps_growth_yield is None and not member.passes


def test_revenue_gaps(compared):
    _, _, universes = compared
    # A month without a revenue: the month before stays the latest.
    member = _members(universes, _index(date(2025, 5, 12)))[REV_NULL]
    assert member.revenue.month == date(2025, 3, 1)
    # Last year's revenue missing: no yoy, the stock fails.
    member = _members(universes, _index(date(2025, 4, 10)))[NO_PRIOR]
    assert member.revenue.month == NO_PRIOR_MONTH and member.revenue_yoy is None
    assert not member.passes


def test_ties_are_ordered_by_the_hash(compared):
    research, product, universes = compared
    together = 0
    for day in DAYS:
        values = {m.instrument_id: m for m in universes[day]}
        if TWIN_OF not in values:
            continue
        assert values[TWIN_OF].eps_yield_raw == values[TWIN].eps_yield_raw
        symbols = [row[0] for row in product[day]]
        if f"S{TWIN_OF}" not in symbols or f"S{TWIN}" not in symbols:
            continue
        together += 1
        first, second = sorted((TWIN_OF, TWIN), key=lambda i: h2_list.tie_key(day, i))
        assert symbols.index(f"S{first}") < symbols.index(f"S{second}")
        assert _same(research[day], product[day])
    assert together > 0


def test_a_suspended_t_is_out(compared):
    research, product, universes = compared
    assert SUSPENDED not in _members(universes, FLAG_AT)
    assert SUSPENDED not in _members(universes, FLAT_AT)
    assert SUSPENDED in _members(universes, FLAT_AT + 1)
    for day_index in (FLAG_AT, FLAT_AT, FLAT_AT + 1):
        assert _same(research[DAYS[day_index]], product[DAYS[day_index]])


def test_types_and_the_liquidity_line(compared):
    _, _, universes = compared
    seen = {m.instrument_id for day in DAYS for m in universes[day]}
    assert IPO in seen and EDGE in seen  # an ipo; exactly 1,000 lots
    assert ETF not in seen and THIN not in seen  # an etf; 999 lots


def test_a_dividend_uses_the_raw_close_and_keeps_the_research_list(compared):
    research, product, universes = compared
    listed = 0
    for day_index in range(CASH_AT - 5, N):
        member = _members(universes, day_index).get(CASH)
        if member is None:
            continue
        assert member.passes
        raw = prices(CASH)[day_index][3] - (3.0 if day_index >= CASH_AT else 0.0)
        assert member.close == pytest.approx(round(raw, 2))
        assert member.eps_yield_raw == pytest.approx(
            member.quarter.eps * 4.0 / member.close
        )
        day = DAYS[day_index]
        rows = {row[0]: row for row in research[day]}
        if f"S{CASH}" in rows:
            listed += 1
            assert rows[f"S{CASH}"][1] == pytest.approx(member.eps_yield_raw)
        assert _same(research[day], product[day])
    assert listed > 0


# --- AC-2: the daily step -------------------------------------------------


@pytest.fixture
def factory(golden_db, tmp_path, monkeypatch):
    path = tmp_path / "x4.db"
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


def _real_x4(monkeypatch, **results):
    steps = Steps(monkeypatch, **results)
    monkeypatch.setattr(schedule_runs, "_x4_list_step", REAL_X4_STEP)
    return steps


def _stored(make, day=T):
    with make() as db:
        run = db.scalar(
            select(StrategyListRun).where(
                StrategyListRun.trading_date == day, StrategyListRun.strategy == "x4"
            )
        )
        items = db.scalars(
            select(StrategyListItem)
            .where(StrategyListItem.run_id == run.id)
            .order_by(StrategyListItem.rank)
        ).all()
        return run, [
            (
                f"S{item.instrument_id}",
                item.values_json["eps_yield_raw"],
                item.values_json["revenue_yoy"],
            )
            for item in items
        ]


def test_the_daily_writes_the_day_after_h2(factory, monkeypatch, compared):
    research, _, _ = compared
    steps = _real_x4(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert result["x4_list"]["status"] == "success"
    assert steps.calls.index("h2_list") < steps.calls.index("plan_tracking")
    rows, by_run = runs(factory)
    logged = by_run[rows[0].id]
    step = logged["x4_list"]
    # theme_heat (#1017) is step 9, so x4_list is 11.
    assert (step.status, step.records, step.sequence) == ("success", 20, 11)
    assert logged["h2_list"].sequence < logged["period_backfill"].sequence
    assert logged["period_backfill"].sequence < step.sequence
    assert step.sequence < logged["plan_tracking"].sequence
    run, items = _stored(factory)
    assert (run.status, run.version, run.definitions_sha256) == (
        "computed",
        "explore_research_v2_X4",
        x4_list.DEFINITIONS_SHA256,
    )
    assert run.config_json == x4_list.X4_CONFIG
    assert (run.item_count, len(items)) == (20, 20)
    assert _same(research[T], items)


def test_the_list_reads_what_period_backfill_writes_on_t(factory, monkeypatch):
    """period_backfill runs before x4_list (#1016 review): a month it writes
    with announcement_date = T (its deadline ahead) is in T's stored list, as
    the research tool reading T later sees it."""

    with factory() as db:
        before = x4_list.compute_day(db, T)
    top = before.entries[0].instrument_id
    month = date(2025, 5, 1)  # announced 2025-06-10, after T, in the fixture
    steps = _real_x4(monkeypatch)

    def backfill(target):
        steps.calls.append("period_backfill")
        with factory() as db:
            db.execute(
                update(MonthlyRevenue)
                .where(
                    MonthlyRevenue.instrument_id == top,
                    MonthlyRevenue.revenue_month == month,
                )
                .values(
                    announcement_date=target,
                    prior_year_revenue=MonthlyRevenue.revenue * 2.0,
                )
            )
            db.commit()
        return {"status": "success", "records": 1}

    monkeypatch.setattr(schedule_runs, "_period_backfill_step", backfill)
    assert pipeline.run_daily(T)["status"] == "success"
    with factory() as db:
        after = x4_list.compute_day(db, T)
    assert top not in [entry.instrument_id for entry in after.entries]
    _, stored = _stored(factory)
    assert [row[0] for row in stored] == [
        f"S{entry.instrument_id}" for entry in after.entries
    ]
    rows, by_run = runs(factory)
    logged = by_run[rows[0].id]
    assert logged["period_backfill"].sequence < logged["x4_list"].sequence


def test_a_rerun_of_the_day_replaces_it(factory):
    assert run_x4_list(T)["records"] == 20
    _, first = _stored(factory)
    top = int(first[0][0][1:])
    with factory() as db:
        db.execute(
            update(MarketBar)
            .where(MarketBar.instrument_id == top, MarketBar.trading_date == T)
            .values(is_suspended=True)
        )
        db.commit()
    assert run_x4_list(T)["records"] == 20
    run, again = _stored(factory)
    assert f"S{top}" not in [row[0] for row in again]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StrategyListRun)) == 1
        assert {item.run_id for item in db.scalars(select(StrategyListItem))} == {
            run.id
        }


def test_a_failure_is_a_warning_and_keeps_the_run_and_the_previous_list(
    factory, monkeypatch, capsys
):
    assert run_x4_list(T)["records"] == 20

    def broken(db, day):
        raise RuntimeError("fixture x4 crash")

    monkeypatch.setattr("worker.x4_list.compute_x4", broken)
    _real_x4(monkeypatch)
    result = pipeline.run_daily(T)
    assert result["status"] == "success"
    assert DAILY_EXIT_CODES[result["status"]] == 0
    err = capsys.readouterr().err
    warnings = [line for line in err.splitlines() if "explore_research_v2_X4" in line]
    assert warnings == [
        f"warning: explore_research_v2_X4 {T.isoformat()} failed: "
        "RuntimeError: fixture x4 crash"
    ]
    rows, by_run = runs(factory)
    assert rows[0].status == "success" and rows[0].error is None
    step = by_run[rows[0].id]["x4_list"]
    assert step.status == "failed" and "fixture x4 crash" in (step.error or "")
    assert rows[0].summary_json["steps"]["x4_list"] == "failed"
    assert rows[0].summary_json["steps"]["h2_list"] == "success"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StrategyListItem)) == 20


def test_a_day_that_is_not_a_session_fails_without_writing(factory):
    result = run_x4_list(T + timedelta(days=1))  # a Saturday
    assert result["status"] == "failed" and "X4DataError" in result["error"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StrategyListRun)) == 0


# --- AC-3: the API --------------------------------------------------------

URL = "/api/strategy-lists/x4"


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


def _taiex(make, days):
    """TAIEX bars on ``days``: the calendar of the change and the sparkline."""
    with make() as db:
        taiex = Instrument(
            market="TW",
            exchange="TWSE",
            symbol="TAIEX",
            name="TAIEX",
            instrument_type="index",
            status="active",
        )
        db.add(taiex)
        db.flush()
        db.add_all(
            MarketBar(
                instrument_id=taiex.id,
                trading_date=day,
                open=20000.0,
                high=20000.0,
                low=20000.0,
                close=20000.0,
                adj_close=20000.0,
                volume=0,
                turnover=0,
                source="twse-fixture",
            )
            for day in days
        )
        db.commit()


def test_the_api_fields(factory, compared):
    _, _, universes = compared
    earlier = date(2025, 3, 24)  # before Q4 2024 is announced (03-31)
    run_x4_list(earlier)
    run_x4_list(T)
    _, items = _stored(factory)
    first, third = int(items[0][0][1:]), int(items[2][0][1:])
    _today_list(factory, T, {first: (4, "breakout"), third: (9, "pullback")})
    _taiex(factory, DAYS[-30:])
    client = TestClient(app)
    body = client.get(URL).json()
    assert body == client.get(f"{URL}?date={T.isoformat()}").json()
    assert set(body) == {
        "status",
        "zero_reason",
        "trading_date",
        "version",
        "definitions_sha256",
        "list_size",
        "computed_at",
        "universe_count",
        "item_count",
        "items",
    }
    assert (body["status"], body["zero_reason"], body["trading_date"]) == (
        "computed",
        None,
        T.isoformat(),
    )
    assert body["version"] == "explore_research_v2_X4"
    assert body["definitions_sha256"] == x4_list.DEFINITIONS_SHA256
    assert body["list_size"] == 20 and body["item_count"] == 20
    assert body["universe_count"] == len(universes[T])
    assert body["computed_at"].endswith("+00:00")
    rows = body["items"]
    assert [row["rank"] for row in rows] == list(range(1, 21))
    assert set(rows[0]) == {
        "rank",
        "instrument",
        "eps_yield_raw",
        "revenue_yoy",
        "revenue_month",
        "quarter_eps",
        "close",
        "market",
        "recent_closes",
        "today_list",
    }
    assert set(rows[0]["instrument"]) == {
        "id",
        "exchange",
        "symbol",
        "name",
        "instrument_type",
    }
    members = {m.instrument_id: m for m in universes[T]}
    for row in rows:
        member = members[row["instrument"]["id"]]
        assert row["instrument"]["symbol"] == f"S{member.instrument_id}"
        assert row["eps_yield_raw"] == pytest.approx(member.eps_yield_raw)
        assert row["revenue_yoy"] == pytest.approx(member.revenue_yoy)
        assert row["revenue_month"] == member.revenue.month.isoformat()[:7]
        assert row["quarter_eps"] == {
            "quarter": "2025Q1",
            "period_end": "2025-03-31",
            "eps": pytest.approx(member.quarter.eps),
            "year_before_eps": pytest.approx(member.quarter.year_before),
        }
        assert row["close"] == member.close
        market = row["market"]
        assert market["trading_date"] == T.isoformat()
        assert market["close"] == member.close
        assert row["recent_closes"]["dates"] == [d.isoformat() for d in DAYS[-30:]]
        assert row["recent_closes"]["closes"][-1] == pytest.approx(member.close)
        if member.instrument_id != SUSPENDED:
            before = bars_of(member.instrument_id)[N - 2]["close"]
            assert market["change_status"] == "known"
            assert market["change"] == pytest.approx(member.close - before)
    marks = [row["today_list"] for row in rows]
    assert marks[0] == {
        "rank": 4,
        "entry_type": "breakout",
        "score_version": CANDIDATE_SCORE_VERSION,
    }
    assert marks[2]["rank"] == 9 and marks[1] is None
    assert sum(mark is not None for mark in marks) == 2
    assert not {"entry_zone", "stop", "target", "levels"} & set(rows[0])
    older = client.get(f"{URL}?date={earlier.isoformat()}").json()
    assert older["trading_date"] == earlier.isoformat()
    assert [row["today_list"] for row in older["items"]] == [None] * len(older["items"])
    assert {row["quarter_eps"]["quarter"] for row in older["items"]} == {"2024Q3"}


def test_a_day_without_a_list_is_missing(factory):
    client = TestClient(app)
    assert client.get(URL).json() == {
        "status": "missing",
        "zero_reason": None,
        "trading_date": None,
        "version": "explore_research_v2_X4",
        "definitions_sha256": x4_list.DEFINITIONS_SHA256,
        "list_size": 20,
        "computed_at": None,
        "universe_count": None,
        "item_count": None,
        "items": [],
    }
    run_x4_list(T)
    body = client.get(f"{URL}?date={DAYS[-2].isoformat()}").json()
    assert (body["status"], body["trading_date"], body["items"]) == (
        "missing",
        DAYS[-2].isoformat(),
        [],
    )
    # H2 has no list on T: the two strategies do not mix.
    assert client.get("/api/strategy-lists/h2").json()["status"] == "missing"


def test_an_empty_universe_is_zero(factory):
    day = DAYS[10]  # no stock has 20 bars yet
    result = run_x4_list(day)
    assert (result["list_status"], result["universe"]) == ("zero", 0)
    body = TestClient(app).get(f"{URL}?date={day.isoformat()}").json()
    assert (body["status"], body["zero_reason"]) == ("zero", "universe_empty")
    assert (body["universe_count"], body["item_count"], body["items"]) == (0, 0, [])


def test_a_universe_without_a_passing_stock_is_zero(factory):
    with factory() as db:
        # Every month now fell from a year before: no revenue_yoy > 0.
        db.execute(
            update(MonthlyRevenue).values(
                prior_year_revenue=MonthlyRevenue.revenue * 2.0
            )
        )
        db.commit()
    result = run_x4_list(T)
    assert result["list_status"] == "zero" and result["universe"] > 20
    body = TestClient(app).get(URL).json()
    assert (body["status"], body["zero_reason"]) == ("zero", "none_passed")
    assert body["universe_count"] == result["universe"]
    assert (body["item_count"], body["items"]) == (0, [])
