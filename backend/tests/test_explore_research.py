"""tools/research/explore_research.py: the registered X1～X8 and explore_judge (#703).

The registered numbers (N, K, start, segments, thresholds) are asserted as
written in docs/spec/evidence.md.  The runs use a synthetic copy on a
compressed calendar: the segments, the segment floors and the anchors are
moved into the fixture's 330 sessions (``compressed``), everything else (the
definitions, N, K, the engine, the costs, the report) is the registered one,
and every output file of every hypothesis is locked by a golden file in
``backend/tests/fixtures/explore_research/`` (``EXPLORE_GOLDEN_UPDATE=1``
rewrites them; a diff there is a change of a hypothesis, not an edit).
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from array import array
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import (
    Base,
    ChipSnapshot,
    Event,
    FundamentalSnapshot,
    Instrument,
    MarketBar,
    MonthlyRevenue,
)

ROOT = Path(__file__).resolve().parents[1].parent
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "explore_research"
URL = "https://github.com/YiCheng0608/stock-lab/issues/703#issuecomment-1"


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
pr = _tool("portfolio_research")
tool = _tool("explore_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}

BUY = 1.0005 * 1.001425
SELL = 0.9995 * (1 - 0.001425 - 0.003)


# --- the registration, as written ------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == [f"X{n}" for n in range(1, 9)]
    rows = {
        name: (spec["rule"], spec["subset"], spec["filters"], spec["keys"])
        for name, spec in h.items()
    }
    assert rows == {
        "X1": ("daily", None, (), ("momentum_120",)),
        "X2": ("daily", None, (), ("high_gap_240",)),
        "X3": ("daily", None, (("revenue_yoy", ">", 0.0),), ("institutional_flow_20",)),
        "X4": (
            "daily",
            None,
            (("revenue_yoy", ">", 0.0), ("eps_growth_yield", ">", 0.0)),
            ("eps_yield_raw",),
        ),
        "X5": ("daily", ("turnover_60", 50), (), ()),
        "X6": ("daily", ("turnover_60", 150), (), ("institutional_flow_20",)),
        "X7": (
            "monthly",
            None,
            (("revenue_previous_month", "==", 1.0), ("revenue_high_12", "==", 1.0)),
            ("revenue_yoy",),
        ),
        "X8": ("buyback", None, (), ()),
    }
    assert {name: (spec["top"], spec["hold"]) for name, spec in h.items()} == {
        "X1": (20, 60),
        "X2": (20, 60),
        "X3": (10, 20),
        "X4": (20, 60),
        "X5": (50, 60),
        "X6": (10, 20),
        "X7": (20, "next_event"),
        "X8": (20, 20),
    }
    otc = date(2007, 4, 23)
    chips = date(2014, 12, 1)
    assert {name: spec["start"] for name, spec in h.items()} == {
        "X1": ("session", otc, 120),
        "X2": ("session", otc, 240),
        "X3": ("session", chips, 20),
        "X4": ("date", date(2014, 8, 14)),
        "X5": ("session", otc, 60),
        "X6": ("session", chips, 60),
        "X7": ("date", date(2014, 1, 10)),
        "X8": ("session", otc, 20),
    }


def test_the_segments_thresholds_and_counts_are_the_decision():
    assert tool.SEGMENTS == {
        "exploration": (None, date(2019, 12, 31)),
        "validation": (date(2020, 1, 2), date(2024, 9, 27)),
        "used": (date(2024, 9, 30), date(2026, 11, 13)),
    }
    assert tool.MIN_SEGMENT_DAYS == {"exploration": 500, "validation": 250}
    assert (tool.MIN_T, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (2.0, 1, 8, 8)
    assert tool.REGISTRATION_COMMIT == "0ba48e9"
    assert (tool.TURNOVER_WINDOW, tool.TURNOVER_AVAILABLE) == (60, "available")
    assert tool.BUYBACK_LOOKBACK == 20 and tool.EVENT_DAY == 10
    assert len(tool.BUYBACK_NONE) == 17
    assert (2 * pr.FEE + pr.TAX) * 10_000 == pytest.approx(58.5)


def test_the_exploration_threshold_is_2_and_bonferroni_after_20():
    assert tool.validation_min_t(8) == 2.0 and tool.validation_min_t(20) == 2.0
    assert tool.validation_min_t(21) == pytest.approx(3.0, abs=0.05)
    assert tool.validation_min_t(40) > tool.validation_min_t(21)


# --- the dates -------------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, current = [], first
    while len(out) < count:
        if current.weekday() < 5:
            out.append(current)
        current += timedelta(days=1)
    return out


def test_the_start_counts_the_anchor_as_the_first_session():
    sessions = weekdays(date(2007, 1, 1), 400)
    anchor = sessions.index(date(2007, 4, 23))
    assert (
        tool.start_index(sessions, ("session", date(2007, 4, 23), 120)) == anchor + 119
    )
    assert tool.start_index(sessions, ("session", date(2007, 4, 23), 1)) == anchor
    # an anchor that is not a session counts from the next one
    assert tool.start_index(sessions, ("session", date(2007, 4, 21), 1)) == anchor
    assert sessions[tool.start_index(sessions, ("date", date(2007, 4, 22)))] == date(
        2007, 4, 23
    )
    assert tool.start_index(sessions, ("session", date(2007, 4, 23), 10_000)) is None


def test_event_days_are_the_10th_or_the_next_session():
    sessions = weekdays(date(2014, 1, 1), 70)
    days = [sessions[at] for at in tool.event_days(sessions)]
    # 2014-01-10 Fri, 02-10 Mon, 03-10 Mon; 2014-05-10 is a Saturday
    assert days[:3] == [date(2014, 1, 10), date(2014, 2, 10), date(2014, 3, 10)]
    may = weekdays(date(2014, 5, 1), 20)
    assert [may[at] for at in tool.event_days(may)] == [date(2014, 5, 12)]


def test_the_segment_windows():
    sessions = [
        day for day in weekdays(date(2019, 12, 2), 60) if day != date(2020, 1, 1)
    ]
    spec = {"rule": "daily", "start": ("date", date(2019, 12, 2))}
    first, last = tool.segment_window(sessions, "validation", spec)
    # the first buy is on the segment's first day, signalled the session before
    assert sessions[first] == date(2020, 1, 2) and sessions[first - 1] == date(
        2019, 12, 31
    )
    assert sessions[last] == sessions[-1]
    first, last = tool.segment_window(sessions, "exploration", spec)
    assert (sessions[first], sessions[last]) == (date(2019, 12, 3), date(2019, 12, 31))
    monthly = {"rule": "monthly", "start": ("date", date(2019, 12, 2))}
    first, _ = tool.segment_window(sessions, "validation", monthly)
    # X7: the first event day of the segment is 2020-01-10, the equity from 01-13
    assert sessions[first - 1] == date(2020, 1, 10) and sessions[first] == date(
        2020, 1, 13
    )


# --- the definitions -------------------------------------------------------------


@pytest.mark.parametrize(
    "title, matched",
    [
        ("本公司董事會決議買回庫藏股", True),
        ("代子公司公告董事會決議買回庫藏股", False),
        ("董事會通過買回本公司股份", True),
        ("公告本公司董事會決議執行第3次買回股份", True),
        ("公告買回庫藏股執行情形", False),
        ("董事會決議註銷買回之庫藏股", False),
        ("董事會決議買回庫藏股之更正公告", False),
        ("董事會決議轉讓買回股份予員工", False),
        ("董事會決議", False),
        ("決議買回庫藏股", False),
        ("董事會決議買回", False),
    ],
)
def test_the_buyback_subject_rule(title, matched):
    assert tool.is_buyback(title) is matched


def item_with(closes, dates=None):
    item = lib.Series(1)
    days = dates or weekdays(date(2014, 1, 1), len(closes))
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        for name in ("open", "high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(1.0)
    return item


def context_for(item, turnover=None, raw_close=None):
    market = pr.Market(
        lib.Panel([], {1: item}, {}, {}, {}),
        {1: ([], [], raw_close or list(item.close), [])},
        {1: "stock"},
        None,
    )
    ctx = tool.Context(market)
    if turnover is not None:
        ctx.turnover[1] = array("d", turnover)
    return ctx


def test_turnover_60_needs_60_available_bars():
    item = item_with([10.0] * 70)
    values = [float(n) for n in range(70)]
    ctx = context_for(item, values)
    assert tool.turnover_60(ctx, item, 58) is None
    assert tool.turnover_60(ctx, item, 59) == pytest.approx(sum(range(60)) / 60)
    values[30] = float("nan")  # a bar whose turnover_status is not available
    ctx = context_for(item, values)
    assert tool.turnover_60(ctx, item, 69) is None
    assert tool.turnover_60(ctx, item, 59) is None


def test_eps_yield_raw_divides_by_the_unadjusted_close():
    item = item_with([50.0] * 5, weekdays(date(2014, 6, 2), 5))
    item.quarters = [(date(2014, 5, 15), date(2014, 3, 31), 1.5)]
    ctx = context_for(item, raw_close=[100.0] * 5)
    assert tool.eps_yield_raw(ctx, item, 4) == pytest.approx(1.5 * 4 / 100.0)
    assert pr.features.eps_yield(item, 4) == pytest.approx(1.5 * 4 / 50.0)


def test_revenue_previous_month():
    item = item_with([10.0] * 30, weekdays(date(2014, 3, 3), 30))
    item.revenues = [
        (date(2014, 2, 10), date(2014, 1, 1), 100.0, 90.0),
        (date(2014, 3, 10), date(2014, 2, 1), 110.0, 90.0),
    ]
    ctx = context_for(item)
    at = item.position[date(2014, 3, 7)]
    assert tool.revenue_previous_month(ctx, item, at) == 0.0  # January is the latest
    at = item.position[date(2014, 3, 10)]
    assert tool.revenue_previous_month(ctx, item, at) == 1.0
    assert (
        tool.revenue_previous_month(context_for(item_with([1.0])), item_with([1.0]), 0)
        is None
    )


# --- explore_judge, every row ----------------------------------------------------


def ex(mean, t):
    return {"days": 600, "mean": mean, "annual": None, "t": t}


@pytest.mark.parametrize(
    "stage, days, delisted, excess, absolute, verdict",
    [
        ("exploration", 499, True, ex(0.01, 5.0), 0.01, "無法判定"),
        ("validation", 249, True, ex(0.01, 5.0), 0.01, "無法判定"),
        ("exploration", 600, False, ex(0.01, 5.0), 0.01, "無法判定"),
        ("validation", 600, False, ex(0.01, 5.0), 0.01, "無法判定"),
        ("exploration", 500, True, ex(0.001, 2.0), 0.0001, "探索通過"),
        ("exploration", 500, True, ex(0.001, 1.99), 0.001, "沒有通過（探索段）"),
        ("exploration", 500, True, ex(0.001, 3.0), 0.0, "沒有通過（探索段）"),
        ("exploration", 500, True, ex(-0.001, -3.0), 0.001, "沒有通過（探索段）"),
        ("exploration", 500, True, ex(0.001, None), 0.001, "沒有通過（探索段）"),
        ("validation", 250, True, ex(0.001, 2.0), 0.0001, "通過"),
        ("validation", 250, True, ex(-0.0001, -0.5), 0.001, "驗證段反轉"),
        ("validation", 250, True, ex(-0.0001, -3.0), -0.001, "驗證段反轉"),
        ("validation", 250, True, ex(0.001, 1.5), 0.001, "沒有通過（驗證段）"),
        ("validation", 250, True, ex(0.001, 3.0), -0.0001, "沒有通過（驗證段）"),
        ("validation", 250, True, ex(0.0, None), 0.001, "沒有通過（驗證段）"),
    ],
)
def test_explore_judge_follows_the_table(
    stage, days, delisted, excess, absolute, verdict
):
    assert tool.explore_judge(stage, days, delisted, excess, absolute) == verdict


def test_explore_judge_takes_the_validation_threshold():
    assert tool.explore_judge("validation", 300, True, ex(0.001, 2.5), 0.001, 3.0) == (
        "沒有通過（驗證段）"
    )


# --- the event-day engine --------------------------------------------------------


def quotes(table):
    return lambda instrument_id, s: table.get((instrument_id, s))


def q(o, c, **extra):
    return pr.Quote(o, c, True, **extra)


def test_simulate_events_holds_one_account_to_the_next_event():
    table = {(1, s): q(10.0, 10.0) for s in range(10)}
    table.update({(2, s): q(20.0, 20.0) for s in range(10)})
    table[(1, 4)] = q(10.0, 11.0)
    picks = {1: [1, 2], 5: [2]}
    dues = {1: 4, 5: 12}
    sim = tool.simulate_events(picks, dues, quotes(table), 1, 8, 4)
    first, second, third = sim.positions
    # each 1/4 of the one account's cash, the rest stays cash
    assert first.cost == second.cost == pytest.approx(0.25)
    assert (first.sold, first.how) == (4, "close")
    assert first.proceeds == pytest.approx(0.25 / (10 * BUY) * 11 * SELL)
    cash_at_5 = 1.0 - 0.5 + first.proceeds + second.proceeds
    assert third.cost == pytest.approx(cash_at_5 / 4)
    assert third.how == "unsold" and sim.counts["unsold"] == 1
    assert sim.equity[0] == pytest.approx(0.5 + 0.25 / BUY * 2)


def test_simulate_events_delays_a_locked_sale_and_keeps_its_cash():
    table = {(1, s): q(10.0, 10.0) for s in range(10)}
    table[(1, 3)] = q(10.0, 10.0, locked_down=True)
    sim = tool.simulate_events({1: [1]}, {1: 3}, quotes(table), 1, 6, None)
    position = sim.positions[0]
    assert (position.sold, position.how) == (4, "delayed")
    assert sim.counts["limit_down"] == 1


# --- research_report's end -------------------------------------------------------


def test_the_loaders_read_nothing_after_end(explore_db):
    report = lib.research_report()
    end = trading_days()[100]
    con = lib.connect_read_only(explore_db)
    try:
        instruments, listed = report.benchmark_universe(con, date(2000, 1, 1), end)
        assert max(listed) == end
        assert all(
            bar.trading_date <= end for i in instruments.values() for bar in i.bars
        )
        assert max(report.market_sessions(con, date(2000, 1, 1), end)) == end
        assert max(report.index_closes(con, date(2000, 1, 1), end)) == end
        # without it, everything as before
        assert max(report.market_sessions(con, date(2000, 1, 1))) == trading_days()[-1]
        series = {7: lib.Series(7)}
        lib._load_revenues(con, series, end)
        lib._load_quarters(con, series, end)
        assert series[7].revenues and series[7].quarters
        assert all(row[0] <= end for row in series[7].revenues + series[7].quarters)
    finally:
        con.close()


# --- the synthetic copy ----------------------------------------------------------

SESSIONS = 330
STOCKS = range(1, 25)
DELISTED = {25: 120, 26: 240}  # the last bar's index
NO_TURNOVER = (3, 100)  # stock 3's turnover is not available before this index
INDEX_ID = 90


def trading_days() -> list[date]:
    return weekdays(date(2013, 1, 1), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    """A persistent drift by id (high ids rise faster) and a ±0.8 % noise."""

    drift = (i - 8) * 0.0003
    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + drift + 0.016 * noise(i, t)
        out.append(round(level, 4))
    return out


def saturday_after(day: date) -> date:
    return day + timedelta(days=(5 - day.weekday()) % 7 or 7)


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    with Session(engine) as db:
        ids = [*STOCKS, *DELISTED]
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": "delisted" if i in DELISTED else "active",
                }
                for i in ids
            ]
            + [
                {
                    "id": INDEX_ID,
                    "exchange": "TWSE",
                    "symbol": "TAIEX",
                    "name": "加權指數",
                    "instrument_type": "index",
                    "status": "active",
                }
            ],
        )
        bars, chips = [], []
        for i in ids:
            prices = closes(i)
            for t, day in enumerate(days):
                if t > DELISTED.get(i, SESSIONS):
                    break
                close = prices[t]
                open_ = (prices[t - 1] if t else close) * (1 + 0.004 * noise(i, t, "o"))
                unknown = i == NO_TURNOVER[0] and t < NO_TURNOVER[1]
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": round(open_, 4),
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": 2_000_000 + 10_000 * i,
                        "turnover": 0.0
                        if unknown
                        else close * (2_000_000 + 10_000 * i),
                        "turnover_status": "unknown" if unknown else "available",
                        "source": "test",
                        "is_suspended": False,
                    }
                )
                chips.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        # the flows favour the fast risers, then the slow ones
                        # (from the compressed validation on: X3 and X6 reverse)
                        "foreign_buy": (i - 12) * (2000.0 if t < 200 else -2000.0)
                        + 40_000 * noise(i, t, "f"),
                        "trust_buy": 1000.0 if noise(i, t, "t") > -0.1 else -1000.0,
                        "dealer_buy": 0.0,
                        "margin_balance": 100_000.0,
                    }
                )
        for t, day in enumerate(days):
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": 8000.0 + 3 * t,
                    "high": 8000.0 + 3 * t,
                    "low": 8000.0 + 3 * t,
                    "close": 8000.0 + 3 * t,
                    "adj_close": 8000.0 + 3 * t,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(ChipSnapshot), chips)
        revenues, quarters = [], []
        for i in ids:
            history: list[float] = []
            for m in range(36):  # 2011-12 .. 2014-11, announced the 10th after
                month = date(2011 + (11 + m) // 12, (11 + m) % 12 + 1, 1)
                announced = date(
                    month.year + month.month // 12, month.month % 12 + 1, 10
                )
                trend = -0.004 if i % 4 == 0 else 0.002 * (i % 5)
                revenue = 1000.0 * (1 + trend * m) + 40.0 * ((m * (i + 3)) % 7)
                prior = history[m - 12] if m >= 12 else revenue * 0.95
                history.append(revenue)
                revenues.append(
                    {
                        "instrument_id": i,
                        "revenue_month": month,
                        "revenue": round(revenue, 2),
                        "prior_year_revenue": round(prior, 2),
                        "announcement_date": announced,
                        "source": "test",
                        "raw_payload_id": 1,
                        "data_as_of": "test",
                    }
                )
            for year in (2012, 2013, 2014):
                cumulative = 0.0
                for quarter, (end, due) in enumerate(
                    [
                        (date(year, 3, 31), date(year, 5, 15)),
                        (date(year, 6, 30), date(year, 8, 14)),
                        (date(year, 9, 30), date(year, 11, 14)),
                        (date(year, 12, 31), date(year + 1, 3, 31)),
                    ]
                ):
                    k = (year - 2012) * 4 + quarter
                    own = (1.0 - 0.05 * k) if i % 5 == 0 else (0.5 + 0.03 * (i % 6) * k)
                    cumulative += own
                    quarters.append(
                        {
                            "instrument_id": i,
                            "period_end": end,
                            "fiscal_period": f"{year}Q{quarter + 1}",
                            "announcement_date": due,
                            "eps": round(cumulative, 4),
                            "source": "test",
                        }
                    )
        db.execute(insert(MonthlyRevenue), revenues)
        db.execute(insert(FundamentalSnapshot), quarters)
        db.execute(insert(Event), announcements())
        db.commit()
    engine.dispose()
    return path


BUYBACK = "本公司董事會決議買回庫藏股"


def announcements() -> list[dict]:
    days = trading_days()
    rows = []

    def add(i, day, title=BUYBACK):
        rows.append(
            {
                "instrument_id": i,
                "event_date": day,
                "event_type": "material_information",
                "title": title,
                "source": "mops_material_information",
            }
        )

    add(5, saturday_after(days[100]))  # a Saturday: T is the Monday after
    add(5, days[110])  # within 20 sessions of the first: skipped
    add(5, days[140])  # later: picked again
    add(7, days[120], "公告買回庫藏股執行情形")  # not a decision
    add(25, days[150])  # delisted at 120: not in the population
    for i in STOCKS[1:]:  # 23 the same day: 20 by the hash
        add(i, days[180])
    add(9, days[220])  # the validation segment
    add(11, days[240], "董事會通過買回本公司股份")
    return rows


@pytest.fixture(scope="module")
def explore_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("explore") / "stock.db")


def compressed(monkeypatch, tmp_path: Path) -> None:
    """The segments, floors and anchors moved into the fixture's 330 sessions."""

    days = trading_days()
    monkeypatch.setattr(
        tool,
        "SEGMENTS",
        {
            "exploration": (None, days[199]),
            "validation": (days[200], days[279]),
            "used": (days[280], days[329]),
        },
    )
    monkeypatch.setattr(
        tool, "MIN_SEGMENT_DAYS", {"exploration": 100, "validation": 60}
    )
    starts = {name: ("session", days[0], 61) for name in REGISTERED}
    starts["X7"] = ("date", date(2013, 4, 10))
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {name: {**spec, "start": starts[name]} for name, spec in REGISTERED.items()},
    )
    monkeypatch.setattr(tool, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    return Path(shutil.copy(db, folder / "stock.db"))


# research_report.load_actions points these at the copy for app.config; the
# command is one process per run, so each call here puts them back after it.
APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def explore(db: Path, out: Path, *extra: str) -> int:
    return one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "exploration",
                "--min-free-gb",
                "0",
                *extra,
            ]
        )  # fmt: skip
    )


def validate(db: Path, out: Path, report: Path, sha: str | None = None, url=URL) -> int:
    sha = sha if sha is not None else tool.file_sha256(report)
    return one_process(lambda: _validate(db, out, report, sha, url))


def _validate(db: Path, out: Path, report: Path, sha: str, url: str) -> int:
    return tool.main(
        [
            "--db", str(db),
            "--out", str(out),
            "--segment", "validation",
            "--min-free-gb", "0",
            "--exploration-report", str(report),
            "--exploration-sha256", sha,
            "--exploration-url", url,
        ]
    )  # fmt: skip


@pytest.fixture
def explored(explore_db, tmp_path, monkeypatch):
    """A copy of the fixture (its own ledger) and its exploration report."""

    compressed(monkeypatch, tmp_path)
    db = copy_of(explore_db, tmp_path)
    out = tmp_path / "exploration"
    assert explore(db, out) == 0
    return db, out


# --- golden files ---------------------------------------------------------------

VOLATILE_LINES = (
    "explore.json 的 sha256",
    "- 耗時 ",
    "- 重現：",
    "- 副本：",
    "- 探索段報告：",
)
GOLDEN_FILES = ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv")


def normalized(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        for key in tool.VOLATILE_KEYS:
            data.pop(key, None)
        data.get("copy", {}).pop("mtime", None)
        data.get("exploration", {}).pop("sha256", None)
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.suffix == ".md":
        return (
            "\n".join(
                line
                for line in text.splitlines()
                if not line.startswith(VOLATILE_LINES)
            )
            + "\n"
        )
    return text


def outputs(out: Path) -> dict[str, str]:
    files = {}
    for path in sorted(out.rglob("*")):
        relative = path.relative_to(out).as_posix()
        if (
            path.is_file()
            and not relative.startswith("raw/")
            and path.name != "ledger-entries.json"
        ):
            files[relative] = normalized(path)
    return files


def check_golden(out: Path, name: str) -> None:
    folder = GOLDEN / name
    actual = outputs(out)
    if os.environ.get("EXPLORE_GOLDEN_UPDATE") == "1":
        shutil.rmtree(folder, ignore_errors=True)
        for relative, text in actual.items():
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    expected = {
        path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }
    assert sorted(actual) == sorted(expected)
    for relative in expected:
        assert actual[relative] == expected[relative], relative


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# --- the exploration ------------------------------------------------------------


def test_the_exploration_output_is_frozen(explored):
    _db, out = explored
    check_golden(out, "exploration")
    for name in REGISTERED:
        for file in GOLDEN_FILES:
            assert (out / name / file).is_file(), (name, file)


def test_the_exploration_runs_every_hypothesis_and_reports_the_round(explored):
    _db, out = explored
    report = read_json(out / "explore.json")
    assert report["segment"] == "exploration" and list(report["hypotheses"]) == list(
        REGISTERED
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (1, 8, 8)
    assert report["definitions_sha256"] == tool.definitions_sha256()
    verdicts = {row["verdict"] for row in report["hypotheses"].values()}
    assert "探索通過" in verdicts and "沒有通過（探索段）" in verdicts
    summary = (out / "explore.md").read_text(encoding="utf-8")
    assert summary.splitlines()[0] == (
        f"explore.json 的 sha256：`{tool.file_sha256(out / 'explore.json')}`"
    )
    assert "本輪 8 個、累計 8 個" in summary and "#689 評分改版：108 組" in summary
    x1 = read_json(out / "X1" / "tables.json")
    assert x1["window"]["first_signal"] == trading_days()[60].isoformat()
    assert x1["window"]["last_session"] == trading_days()[199].isoformat()
    assert x1["prerequisites"] == {
        "days": 139,
        "min_days": 100,
        "delisted": 1,
        "ok": True,
    }
    for key in ("win", "curves", "excess", "absolute", "counts", "coverage"):
        assert key in x1


def test_the_exploration_reads_nothing_after_2019_12_31(
    explore_db, tmp_path, monkeypatch
):
    """Rewriting every row after the exploration's end changes nothing in it."""

    compressed(monkeypatch, tmp_path)
    clean = copy_of(explore_db, tmp_path)
    assert explore(clean, tmp_path / "clean") == 0
    poisoned_dir = tmp_path / "poisoned"
    poisoned_dir.mkdir()
    poisoned = Path(shutil.copy(explore_db, poisoned_dir / "stock.db"))
    end = trading_days()[199].isoformat()
    con = sqlite3.connect(poisoned)
    with con:
        con.execute(
            "update market_bars set close = close * 3, open = open / 3 where trading_date > ?",
            (end,),
        )
        con.execute(
            "update chip_snapshots set trust_buy = -trust_buy where trading_date > ?",
            (end,),
        )
        con.execute(
            "update monthly_revenues set revenue = 1 where announcement_date > ?",
            (end,),
        )
        con.execute(
            "update fundamental_snapshots set eps = -9 where announcement_date > ?",
            (end,),
        )
        con.execute(
            "update events set title = '董事會決議買回庫藏股' where event_date > ?",
            (end,),
        )
    con.close()
    assert explore(poisoned, tmp_path / "dirty") == 0
    clean_out = outputs(tmp_path / "clean")
    dirty_out = outputs(tmp_path / "dirty")
    assert clean_out == dirty_out

    # and the read itself stops at the end
    seen = []
    original = tool.load_context

    def spy(db, start, end_, raw_dir):
        ctx = original(db, start, end_, raw_dir)
        seen.append((end_, max(ctx.market.panel.sessions)))
        return ctx

    monkeypatch.setattr(tool, "load_context", spy)
    assert explore(clean, tmp_path / "again") == 0
    assert seen == [(trading_days()[199], trading_days()[199])]


def test_x7_buys_after_each_event_day_and_sells_on_the_next(explored):
    _db, out = explored
    days = trading_days()
    events = [days[at] for at in tool.event_days(days)]
    trades = read_csv(out / "X7" / "trades.csv")
    assert trades
    for row in trades:
        bought = date.fromisoformat(row["bought"])
        before = days[days.index(bought) - 1]
        assert before in events
        due = events[events.index(before) + 1]
        assert row["due"] == (due.isoformat() if due <= days[199] else "")
        assert row["account"] == "0"
    picks = read_csv(out / "X7" / "picks.csv")
    assert {row["signal_date"] for row in picks} <= {d.isoformat() for d in events}
    assert {row["revenue_previous_month"] for row in picks} == {"1.0"}
    assert {row["revenue_high_12"] for row in picks} == {"1.0"}


def test_x8_rolls_the_date_skips_repeats_and_caps_at_20(explored):
    _db, out = explored
    days = trading_days()
    picks = read_csv(out / "X8" / "picks.csv")
    by_day: dict[str, list[str]] = {}
    for row in picks:
        by_day.setdefault(row["signal_date"], []).append(row["symbol"])
    # the Saturday after day 100 rolls to the next session
    monday = next(day for day in days if day > saturday_after(days[100]))
    assert by_day[monday.isoformat()] == ["S5"]
    assert days[110].isoformat() not in by_day  # S5 again within 20 sessions
    assert by_day[days[140].isoformat()] == ["S5"]
    assert days[120].isoformat() not in by_day  # 執行情形 is not a decision
    assert days[150].isoformat() not in by_day  # delisted: not in the population
    assert len(by_day[days[180].isoformat()]) == 20
    assert set(by_day) == {
        monday.isoformat(),
        days[140].isoformat(),
        days[180].isoformat(),
    }
    coverage = read_json(out / "X8" / "tables.json")["coverage"]
    assert coverage["2013"]["rolled"] == 1


def test_x5_leaves_a_missing_turnover_out_and_buys_its_whole_subset(explored):
    _db, out = explored
    days = trading_days()
    picks = read_csv(out / "X5" / "picks.csv")
    early = [
        row["symbol"] for row in picks if row["signal_date"] == days[61].isoformat()
    ]
    late = [
        row["symbol"] for row in picks if row["signal_date"] == days[180].isoformat()
    ]
    assert "S3" not in early and "S3" in late  # not available before day 100 (+60)
    assert len(late) == 25  # 24 stocks and S26 (delisted at 300), fewer than 50
    coverage = read_json(out / "X5" / "tables.json")["coverage"]
    assert coverage["2013"]["missing"]["turnover_60"] > 0


# --- AC-4: the prerequisites ----------------------------------------------------


def test_a_short_segment_is_undecided_and_not_run(explore_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path)
    monkeypatch.setattr(
        tool, "MIN_SEGMENT_DAYS", {"exploration": 200, "validation": 60}
    )
    ran = []
    monkeypatch.setattr(tool.pr, "simulate", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(tool, "simulate_events", lambda *a, **k: ran.append(a))
    out = tmp_path / "out"
    assert explore(copy_of(explore_db, tmp_path), out) == 0
    report = read_json(out / "explore.json")
    for name in REGISTERED:
        row = report["hypotheses"][name]
        assert (row["verdict"], row["reason"]) == ("無法判定", "segment_too_short"), (
            name
        )
        assert not (out / name / "equity.csv").exists()
    assert ran == []
    assert "段長不足" in (out / "explore.md").read_text(encoding="utf-8")


def test_no_delisted_company_is_undecided_and_not_run(
    explore_db, tmp_path, monkeypatch
):
    compressed(monkeypatch, tmp_path)
    db = copy_of(explore_db, tmp_path)
    con = sqlite3.connect(db)
    with con:
        con.execute(
            "update instruments set status = 'transferred' where status = 'delisted'"
        )
    con.close()
    ran = []
    monkeypatch.setattr(tool.pr, "simulate", lambda *a, **k: ran.append(a))
    out = tmp_path / "out"
    assert explore(db, out) == 0
    report = read_json(out / "explore.json")
    assert {row["reason"] for row in report["hypotheses"].values()} == {"no_delisted"}
    assert {row["verdict"] for row in report["hypotheses"].values()} == {"無法判定"}
    assert ran == []


def test_the_delisted_count_is_by_the_last_bar_in_the_window(explore_db):
    days = trading_days()
    assert tool.delisted_count(explore_db, days[0], days[329]) == 2
    assert tool.delisted_count(explore_db, days[121], days[240]) == 1
    assert tool.delisted_count(explore_db, days[241], days[329]) == 0


# --- coverage only --------------------------------------------------------------


def test_coverage_only_computes_no_return(explore_db, tmp_path, monkeypatch):
    compressed(monkeypatch, tmp_path)
    ran = []
    monkeypatch.setattr(tool.pr, "simulate", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(tool, "simulate_events", lambda *a, **k: ran.append(a))
    out = tmp_path / "out"
    assert explore(copy_of(explore_db, tmp_path), out, "--coverage-only") == 0
    assert ran == []
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    assert list(body["hypotheses"]) == list(REGISTERED)
    x5 = body["hypotheses"]["X5"]["coverage"]
    assert x5["2013"]["missing"]["turnover_60"] > 0
    assert "60 日平均成交金額 缺值" in (out / "coverage.md").read_text(encoding="utf-8")


def test_coverage_only_is_for_the_exploration(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        tool.main(
            [
                "--db",
                "x",
                "--out",
                str(tmp_path),
                "--segment",
                "validation",
                "--coverage-only",
            ]
        )
    assert stopped.value.code == 2


# --- AC-3: the validation gate --------------------------------------------------


def test_the_exploration_takes_no_report_arguments(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        tool.main(
            ["--db", "x", "--out", str(tmp_path), "--segment", "exploration",
             "--exploration-url", URL]
        )  # fmt: skip
    assert stopped.value.code == 2


def refused(capsys) -> list[str]:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])["refused"]


def assert_untouched(db: Path, out: Path) -> None:
    assert not (db.parent / tool.LEDGER_NAME).exists()
    assert not out.exists()


def test_the_validation_needs_all_three_arguments(explored, tmp_path, capsys):
    db, exploration = explored
    out = tmp_path / "v"
    code = one_process(
        lambda: tool.main(
            [
                "--db",
                str(db),
                "--out",
                str(out),
                "--segment",
                "validation",
                "--min-free-gb",
                "0",
                "--exploration-report",
                str(exploration / "explore.json"),
                "--exploration-url",
                URL,
            ]
        )  # fmt: skip
    )
    assert code == 2 and "needs --exploration-report" in refused(capsys)[0]
    assert_untouched(db, out)


def test_the_validation_refuses_a_report_that_is_not_the_published_one(
    explored, tmp_path, capsys
):
    db, exploration = explored
    out = tmp_path / "v"
    assert validate(db, out, exploration / "explore.json", sha="0" * 64) == 2
    assert any("not the published one" in text for text in refused(capsys))
    assert_untouched(db, out)


def test_the_validation_refuses_a_link_that_is_not_public(explored, tmp_path, capsys):
    db, exploration = explored
    out = tmp_path / "v"
    url = "https://example.com/report"
    assert validate(db, out, exploration / "explore.json", url=url) == 2
    assert any("--exploration-url" in text for text in refused(capsys))
    assert_untouched(db, out)


def test_the_validation_accepts_a_pr_assets_link(explored, tmp_path):
    db, exploration = explored
    url = (
        "https://github.com/YiCheng0608/stock-lab/blob/pr-assets/703/run-1/explore.json"
    )
    assert validate(db, tmp_path / "v", exploration / "explore.json", url=url) == 0


def test_the_validation_refuses_a_report_of_other_definitions(
    explored, tmp_path, monkeypatch, capsys
):
    db, exploration = explored
    monkeypatch.setattr(tool, "MIN_T", 1.5)  # the tool changed since the report
    out = tmp_path / "v"
    assert validate(db, out, exploration / "explore.json") == 2
    assert any("definitions_sha256" in text for text in refused(capsys))
    assert_untouched(db, out)


def test_the_validation_refuses_a_report_that_is_not_an_exploration(
    explored, tmp_path, capsys
):
    db, exploration = explored
    report = read_json(exploration / "explore.json")
    report["segment"] = "validation"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "v"
    assert validate(db, out, edited) == 2
    assert any("not an exploration report" in text for text in refused(capsys))
    assert_untouched(db, out)


def test_the_validation_refuses_when_nothing_passed_the_exploration(
    explored, tmp_path, capsys
):
    db, exploration = explored
    report = read_json(exploration / "explore.json")
    for row in report["hypotheses"].values():
        if row["verdict"] == "探索通過":
            row["verdict"] = "沒有通過（探索段）"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "v"
    assert validate(db, out, edited) == 2
    assert any("no hypothesis passed" in text for text in refused(capsys))
    assert_untouched(db, out)


def passed_names(exploration: Path) -> list[str]:
    report = read_json(exploration / "explore.json")
    return [
        n for n, row in report["hypotheses"].items() if row["verdict"] == "探索通過"
    ]


def test_the_validation_runs_only_the_passed_once_and_lists_the_used_segment(
    explored, tmp_path, capsys
):
    db, exploration = explored
    passed = passed_names(exploration)
    out = tmp_path / "v"
    assert validate(db, out, exploration / "explore.json") == 0
    report = read_json(out / "explore.json")
    assert list(report["hypotheses"]) == passed
    assert all((out / name).is_dir() for name in passed)
    assert not any((out / name).exists() for name in REGISTERED if name not in passed)
    assert report["exploration"]["url"] == URL
    verdicts = {name: row["verdict"] for name, row in report["hypotheses"].items()}
    assert "通過" in verdicts.values()
    # the used segment only for the passed ones
    used = [name for name, verdict in verdicts.items() if verdict == "通過"]
    assert sorted(report["used"]) == sorted(used)
    for name in passed:
        assert (out / name / "used").is_dir() is (name in used)
    x = read_json(out / used[0] / "used" / "tables.json")
    assert (
        x["verdict"] is None
        and x["window"]["first_session"] == trading_days()[280].isoformat()
    )
    # the ledger beside the DB: started, then finished with the verdict
    entries = tool.read_ledger(db.parent / tool.LEDGER_NAME)
    assert [entry["hypothesis"] for entry in entries] == passed
    assert {entry["status"] for entry in entries} == {"finished"}
    assert {entry["verdict"] for entry in entries} == set(verdicts.values())
    assert all(
        entry["report_sha256"] == tool.file_sha256(exploration / "explore.json")
        for entry in entries
    )
    assert tool.read_ledger(out / "ledger-entries.json") == entries
    check_golden(out, "validation")
    # once: the second run is refused before anything is read
    again = tmp_path / "again"
    assert validate(db, again, exploration / "explore.json") == 2
    assert any("the validation runs once" in text for text in refused(capsys))
    assert not again.exists()


def test_the_validation_reads_nothing_after_its_end(explored, tmp_path, monkeypatch):
    db, exploration = explored
    seen = []
    original = tool.load_context

    def spy(db_, start, end, raw_dir):
        ctx = original(db_, start, end, raw_dir)
        seen.append((end, max(ctx.market.panel.sessions)))
        return ctx

    monkeypatch.setattr(tool, "load_context", spy)
    assert validate(db, tmp_path / "v", exploration / "explore.json") == 0
    days = trading_days()
    assert seen[0] == (days[279], days[279])
    assert seen[1:] == [(days[329], days[329])]  # the used segment, for the passed


def test_the_repository_ledger_refuses_too(explored, tmp_path, capsys):
    db, exploration = explored
    passed = passed_names(exploration)
    tool.write_ledger(
        tool.REPO_LEDGER, [{"hypothesis": passed[0], "status": "finished"}]
    )
    out = tmp_path / "v"
    assert validate(db, out, exploration / "explore.json") == 2
    assert any("already in" in text and passed[0] in text for text in refused(capsys))
    assert_untouched(db, out)


def test_a_crash_after_the_start_still_counts_as_the_one_run(
    explored, tmp_path, monkeypatch, capsys
):
    db, exploration = explored

    def crash(*args, **kwargs):
        raise MemoryError("killed")

    monkeypatch.setattr(tool, "load_context", crash)
    with pytest.raises(MemoryError):
        validate(db, tmp_path / "v", exploration / "explore.json")
    entries = tool.read_ledger(db.parent / tool.LEDGER_NAME)
    assert entries and {entry["status"] for entry in entries} == {"started"}
    monkeypatch.undo()
    compressed(monkeypatch, tmp_path)
    assert validate(db, tmp_path / "again", exploration / "explore.json") == 2
    assert any("the validation runs once" in text for text in refused(capsys))


def test_the_repository_ledger_starts_empty():
    assert json.loads(tool.REPO_LEDGER.read_text(encoding="utf-8")) == {"entries": []}
