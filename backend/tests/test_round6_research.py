"""tools/research/round6_research.py: the registered W1～W4 (#903).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第六輪：W1～W4.  The features and the order are checked
on hand-made series (the expected numbers worked out in the test); the gate
("each once") runs on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 330 sessions, everything else is the registered one.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import sys
import weakref
from array import array
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import Base, CorporateAction, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/903#issuecomment-1"
NAN = float("nan")


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
pr = _tool("portfolio_research")
ex = _tool("explore_research")
r5 = _tool("round5_research")
tool = _tool("round6_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == ["W1", "W2", "W3", "W4"]
    assert not set(h) & set(ex.HYPOTHESES) and not set(h) & set(r5.HYPOTHESES)
    rows = {
        name: (spec["subset"], spec["keys"], spec["top"], spec["hold"], spec["start"])
        for name, spec in h.items()
    }
    otc = date(2007, 12, 3)
    assert rows == {
        "W1": (None, (("amihud_60", "high"),), 20, 60, ("session", otc, 61)),
        "W2": (None, (("reversal_720_240", "low"),), 20, 60, ("session", otc, 721)),
        "W3": (None, (("expected_ex_28", "high"),), 20, 20, ("date", date(2010, 1, 4))),
        "W4": (None, (("season_5y", "high"),), 20, 20, ("date", date(2012, 12, 3))),
    }
    assert all(spec["rule"] == "daily" for spec in h.values())


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (1, 6, 4, 26)
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.102
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(26), 3) == 3.102
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert tool.REGISTRATION_COMMIT == "6f6142d4"
    assert (tool.EX_YEAR_DAYS, tool.EX_AHEAD_DAYS, tool.SEASON_STALE_DAYS) == (
        365,
        28,
        7,
    )


def test_the_definitions_hash_holds_the_validation_threshold(monkeypatch):
    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.102
    monkeypatch.setattr(tool, "VALIDATION_MIN_T", 3.052)
    assert tool.definitions_sha256() != before


def test_the_command_has_no_parameter_flags():
    flags = {
        option for action in tool._parser()._actions for option in action.option_strings
    }
    assert flags == {
        "-h",
        "--help",
        "--db",
        "--out",
        "--segment",
        "--min-free-gb",
        "--coverage-only",
        "--hypotheses",
        "--exploration-report",
        "--exploration-sha256",
        "--exploration-url",
    }


# AC-1: measured on master 6f6142d4 before this tool existed.
FROZEN = {
    "explore_research": (
        2,
        "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63",
    ),
    "trade_research": (
        1,
        "80329d4669123683783a2153a132931fe90eecfbbe8fbfa382cfed345d8cfbfb",
    ),
    "mainstream_research": (
        1,
        "5e776480b0fa7d023c9f217671c856ac81ea8d4115d7ff94aac7446a263371f2",
    ),
    "round4_research": (
        1,
        "2fa7f1826fc1b1b962eb63b45b6a238122d74fd4912e0a14c8eed0a0cf63aa56",
    ),
    "round5_research": (
        1,
        "a3409f1b9dd24a8e32c04148f5d1e36a5e8282e96df975bd0b36a21101993d75",
    ),
}


@pytest.mark.parametrize("name", sorted(FROZEN))
def test_the_other_tools_are_unchanged(name):
    module = sys.modules.get(name) or _tool(name)
    assert (module.VERSION, module.definitions_sha256()) == FROZEN[name]


# --- hand-made series -------------------------------------------------------------


def weekdays(first: date, count: int) -> list[date]:
    out, day = [], first
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def make_item(closes, suspended=(), dates=None, instrument_id=1):
    item = lib.Series(instrument_id)
    days = dates or weekdays(date(2014, 1, 1), len(closes))
    item.suspended.append(0)
    for at, close in enumerate(closes):
        item.position[days[at]] = at
        item.dates.append(days[at])
        for name in ("open", "high", "low", "close"):
            getattr(item, name).append(close)
        item.volume.append(1.0)
        item.suspended.append(item.suspended[-1] + (1 if at in suspended else 0))
    return item


def context_for(items, turnover=None, actions=None):
    series = {item.instrument_id: item for item in items}
    raw = {item.instrument_id: ([], [], list(item.close), []) for item in items}
    market = pr.Market(lib.Panel([], series, {}, {}, {}), raw, {}, None)
    base = ex.Context(market)
    for instrument_id, values in (turnover or {}).items():
        base.turnover[instrument_id] = array("d", values)
    ctx = tool.Context(base)
    for instrument_id, rows in (actions or {}).items():
        ctx.actions[instrument_id] = tool.actions_of(rows)
    return ctx


def sorted_ids(spec_name: str, values: dict[int, float | None], day: date) -> list[int]:
    keys = tool.HYPOTHESES[spec_name]["keys"]
    name = keys[0][0]
    rows = [(i, {name: v}, pr.tie_break(day, i)) for i, v in values.items()]
    rows.sort(key=lambda row: tool.order_key(row[1], keys, row[2]))
    return [row[0] for row in rows]


# --- W1 -------------------------------------------------------------------------


def zigzag(n: int) -> list[float]:
    """Closes moving +1 %, −1 % in turn: every |r| is 0.01."""

    out = [100.0]
    for k in range(1, n):
        out.append(out[-1] * (1.01 if k % 2 else 0.99))
    return out


def w1(closes, turnover, suspended=(), at=None):
    item = make_item(closes, suspended=suspended)
    ctx = context_for([item], turnover={1: turnover})
    return tool.amihud_60(ctx, item, len(closes) - 1 if at is None else at)


def test_amihud_60_is_the_mean_of_60_ratios_of_61_bars():
    closes = zigzag(61)
    # the 60 turnovers of bars 1..60: 30 of 1,000 then 30 of 2,000; bar 0's is not read
    turnover = [NAN] + [1000.0] * 30 + [2000.0] * 30
    # by hand: (30 × 0.01 / 1,000 + 30 × 0.01 / 2,000) / 60 = 7.5e-6
    assert w1(closes, turnover) == pytest.approx(7.5e-6, rel=1e-9)


def test_amihud_60_needs_61_bars():
    turnover = [1000.0] * 61
    assert w1(zigzag(61), turnover, at=59) is None  # 60 bars
    assert w1(zigzag(61), turnover, at=60) == pytest.approx(0.01 / 1000.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, NAN])
@pytest.mark.parametrize("where", [0, 30, 60])  # the first, a middle, T's bar
def test_amihud_60_is_missing_with_a_close_missing_or_not_positive(bad, where):
    closes = zigzag(61)
    closes[where] = bad
    assert w1(closes, [1000.0] * 61) is None


def test_amihud_60_is_missing_with_a_suspended_bar_in_the_61():
    closes, turnover = zigzag(62), [1000.0] * 62
    for where in (1, 30, 61):  # the first of the 61, a middle, T's bar
        assert w1(closes, turnover, suspended={where}) is None, where
    # just before the 61 bars: not in the window
    assert w1(closes, turnover, suspended={0}) is not None


@pytest.mark.parametrize("bad", [NAN, 0.0, -5.0])
@pytest.mark.parametrize("where", [1, 30, 60])  # the 60 bars i = at − 59 .. at
def test_amihud_60_is_missing_with_a_turnover_not_available_or_not_positive(bad, where):
    turnover = [1000.0] * 61
    turnover[where] = bad  # NaN is a turnover_status other than available
    assert w1(zigzag(61), turnover) is None


def test_amihud_60_reads_no_turnover_of_bar_at_minus_60():
    turnover = [NAN] + [1000.0] * 60
    assert w1(zigzag(61), turnover) == pytest.approx(0.01 / 1000.0)


def test_amihud_60_counts_the_stocks_own_bars():
    days = weekdays(date(2014, 1, 1), 122)[::2]
    item = make_item(zigzag(61), dates=days)
    ctx = context_for([item], turnover={1: [1000.0] * 61})
    assert tool.amihud_60(ctx, item, 60) == pytest.approx(0.01 / 1000.0)


def test_w1_is_high_first_with_a_missing_value_last():
    day = date(2014, 6, 2)
    ids = sorted_ids("W1", {1: 2e-6, 2: None, 3: 9e-6, 4: 5e-6}, day)
    assert ids == [3, 4, 1, 2]


# --- W2 -------------------------------------------------------------------------


def test_reversal_720_240_takes_bars_at_minus_240_and_at_minus_720():
    closes = [50.0] * 721
    closes[0], closes[480] = 10.0, 15.0  # at − 720 and at − 240 for at = 720
    closes[720] = 99.0  # T's own close is not read
    item = make_item(closes)
    assert tool.reversal_720_240(None, item, 720) == pytest.approx(0.5)


def test_reversal_720_240_counts_suspended_bars():
    closes = [50.0] * 721
    closes[0], closes[480] = 20.0, 15.0
    item = make_item(closes, suspended={0, 300, 480})
    assert tool.reversal_720_240(None, item, 720) == pytest.approx(-0.25)


def test_reversal_720_240_needs_721_bars():
    item = make_item([10.0] * 721)
    assert tool.reversal_720_240(None, item, 719) is None  # 720 bars
    assert tool.reversal_720_240(None, item, 720) == pytest.approx(0.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, NAN])
@pytest.mark.parametrize("where", [0, 480])
def test_reversal_720_240_is_missing_with_a_close_missing_or_not_positive(bad, where):
    closes = [10.0] * 721
    closes[where] = bad
    assert tool.reversal_720_240(None, make_item(closes), 720) is None


def test_w2_is_small_first_with_a_missing_value_last():
    day = date(2014, 6, 2)
    ids = sorted_ids("W2", {1: -0.1, 2: None, 3: -0.6, 4: 0.4}, day)
    assert ids == [3, 1, 4, 2]


# --- W3 -------------------------------------------------------------------------


def action(day, cash=None, stock=None, split=None):
    return SimpleNamespace(
        action_date=day,
        cash_dividend=cash,
        stock_dividend_ratio=stock,
        split_ratio=split,
    )


T = date(2015, 6, 30)


def w3(rows):
    item = make_item([50.0], dates=[T])
    return tool.expected_parts(context_for([item], actions={1: rows}), item, 0)


def test_w3_window_both_ends():
    year_ago = T - timedelta(days=365)
    assert w3([action(year_ago, cash=1.0)]).value == 0.0  # T − 365: out
    assert w3([action(year_ago + timedelta(days=1), cash=1.0)]).value == 1.0
    assert w3([action(year_ago + timedelta(days=28), cash=1.0)]).value == 1.0
    assert w3([action(year_ago + timedelta(days=29), cash=1.0)]).value == 0.0
    assert w3([action(T, cash=1.0)]).value == 0.0  # this year's: never read
    assert w3([]).value == 0.0
    item = make_item([50.0], dates=[T])
    assert tool.expected_ex_28(context_for([item]), item, 0) == 0.0  # no actions


def test_w3_null_zero_or_stock_only_is_zero_never_missing():
    inside = T - timedelta(days=350)
    assert w3([action(inside, cash=0.0)]) == tool.Expected(0.0, False)
    assert w3([action(inside, stock=0.1)]) == tool.Expected(0.0, True)
    assert w3([action(inside, split=2.0)]) == tool.Expected(0.0, True)
    assert w3([action(inside)]) == tool.Expected(0.0, True)  # all three null
    # a cash row beside them still makes it 1
    assert w3([action(inside), action(inside + timedelta(days=1), cash=0.5)]) == (
        tool.Expected(1.0, True)
    )


def test_w3_fills_the_20_by_the_hash_when_fewer_than_20_are_1():
    day = T
    items, acts, members = [], {}, []
    ones = {4, 9, 17, 22, 28}
    for i in range(1, 31):
        item = make_item([50.0], dates=[day], instrument_id=i)
        items.append(item)
        acts[i] = [action(day - timedelta(days=350), cash=1.0)] if i in ones else []
        members.append((item, 0))
    ctx = context_for(items, actions=acts)
    ranked = tool.rank(ctx, tool.HYPOTHESES["W3"], day, members)
    ids = [row[0] for row in ranked.rows]
    by_hash = lambda group: sorted(group, key=lambda i: pr.tie_break(day, i))  # noqa: E731
    assert ids[:5] == by_hash(ones)
    assert ids[5:20] == by_hash(set(range(1, 31)) - ones)[:15]
    assert ranked.ones == 5 and ranked.missing["expected_ex_28"] == 0


def test_w3_lists_the_picks_with_1_as_a_mean_by_year():
    """Two days of 2015 with 3 and 1 of the picks 1, one of 2016 with 25 (the
    20 picks all 1): 2 a day in 2015, 20 in 2016."""

    spec = tool.HYPOTHESES["W3"]
    coverage: dict = {}
    for day, count in (
        (date(2015, 6, 1), 3),
        (date(2015, 6, 2), 1),
        (date(2016, 6, 1), 25),
    ):
        items, acts, members = [], {}, []
        for i in range(1, 31):
            item = make_item([50.0], dates=[day], instrument_id=i)
            items.append(item)
            acts[i] = (
                [action(day - timedelta(days=350), cash=1.0)] if i <= count else []
            )
            members.append((item, 0))
        ranked = tool.rank(context_for(items, actions=acts), spec, day, members)
        tool._coverage_add(coverage, spec, day, len(members), ranked)
    assert (coverage["2015"]["picked_ones"], coverage["2015"]["days"]) == (4, 2)
    assert (coverage["2016"]["picked_ones"], coverage["2016"]["picked"]) == (20, 20)
    lines = tool.picked_lines(coverage)
    assert lines[2] == "| 2015 | 2 | 40 | 4 | 2.00 |"
    assert lines[3] == "| 2016 | 1 | 20 | 20 | 20.00 |"
    assert coverage["2015"]["ones"] == 4 and coverage["2016"]["ones"] == 25


# --- W4 -------------------------------------------------------------------------


def season_item(
    shift: dict[int, int] | None = None, close: dict[str, float] | None = None
):
    """Bars only on a_k and b_k (k = 1..5) and on T: P(a_k) = 100, P(b_k) =
    100 × (1 + k %), so r = 1..5 % and the mean is 3 %.  ``shift`` moves the
    bar of a_k by that many calendar days."""

    shift, close = shift or {}, close or {}
    bars: dict[date, float] = {T: 80.0}
    for k in range(1, 6):
        a = T - timedelta(days=365 * k)
        bars[a + timedelta(days=shift.get(k, 0))] = close.get(f"a{k}", 100.0)
        bars[a + timedelta(days=28)] = close.get(f"b{k}", 100.0 * (1 + k / 100))
    days = sorted(bars)
    return make_item([bars[d] for d in days], dates=days), days.index(T)


def test_season_5y_is_the_mean_of_five_four_week_returns():
    item, at = season_item()
    assert tool.season_5y(None, item, at) == pytest.approx(0.03)


def test_season_5y_takes_the_last_bar_up_to_7_calendar_days_before():
    item, at = season_item(shift={3: -7})  # 7 days before a_3: still P(a_3)
    assert tool.season_5y(None, item, at) == pytest.approx(0.03)
    item, at = season_item(shift={3: -8})  # 8 days before: missing
    assert tool.season_5y(None, item, at) is None
    item, at = season_item(shift={3: 1})  # the day after a_3 is not ≤ a_3
    assert tool.season_5y(None, item, at) is None


def test_price_on_reads_back_from_a_weekend():
    friday = date(2015, 6, 26)
    item = make_item([10.0, 12.0], dates=[friday, friday + timedelta(days=3)])
    assert tool.price_on(item, friday + timedelta(days=1)) == 10.0  # Saturday
    assert tool.price_on(item, friday + timedelta(days=3)) == 12.0
    assert tool.price_on(item, friday - timedelta(days=1)) is None  # no bar before


@pytest.mark.parametrize("which", ["a1", "b1", "a5", "b5", "b3"])
@pytest.mark.parametrize("bad", [0.0, -1.0, NAN])
def test_season_5y_is_missing_when_any_price_is(which, bad):
    item, at = season_item(close={which: bad})
    assert tool.season_5y(None, item, at) is None


def test_w4_is_high_first_with_a_missing_value_last():
    day = date(2014, 6, 2)
    ids = sorted_ids("W4", {1: 0.01, 2: None, 3: -0.02, 4: 0.05}, day)
    assert ids == [4, 1, 3, 2]


# --- the verdict ----------------------------------------------------------------


def judged(stage, t):
    excess = {"mean": 0.001, "t": t}
    return ex.explore_judge(
        stage,
        2000,
        True,
        excess,
        0.0005,
        tool.VALIDATION_MIN_T if stage == "validation" else tool.MIN_T,
    )


@pytest.mark.parametrize(
    "t, verdict",
    [
        (2.0, "前瞻觀察"),
        (2.5, "前瞻觀察"),
        (3.052, "前瞻觀察"),  # round 5's threshold is not this round's
        (3.101, "前瞻觀察"),
        (3.102, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_102(t, verdict):
    assert judged("validation", t) == verdict


def test_the_exploration_passes_from_2():
    assert judged("exploration", 2.0) == "探索通過"
    assert judged("exploration", 1.99) == "沒有通過（探索段）"


# --- the synthetic copy ---------------------------------------------------------

SESSIONS = 330
STOCKS = range(1, 25)
DELISTED = {25: 120, 27: 250}  # the last bar's index
TRANSFERRED = {26: 280}
INDEX_ID = 90
UNKNOWN_TURNOVER = (9, 100)  # (id, session): turnover_status "unknown"


def trading_days() -> list[date]:
    return weekdays(date(2013, 1, 1), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    import hashlib

    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)
        out.append(round(level, 4))
    return out


def volume(i: int) -> int:
    return 2_000_000 + 10_000 * i


def build(path: Path) -> Path:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    ends = {**DELISTED, **TRANSFERRED}
    ids = [*STOCKS, *ends]
    with Session(engine) as db:
        db.execute(
            insert(Instrument),
            [
                {
                    "id": i,
                    "exchange": "TWSE" if i % 2 else "TPEx",
                    "symbol": f"S{i}",
                    "name": f"N{i}",
                    "instrument_type": "stock",
                    "status": "delisted"
                    if i in DELISTED
                    else "transferred"
                    if i in TRANSFERRED
                    else "active",
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
        bars = []
        for i in ids:
            prices = closes(i)
            for t, day in enumerate(days):
                if t > ends.get(i, SESSIONS):
                    break
                close = prices[t]
                open_ = (prices[t - 1] if t else close) * (1 + 0.004 * noise(i, t, "o"))
                bars.append(
                    {
                        "instrument_id": i,
                        "trading_date": day,
                        "open": round(open_, 4),
                        "high": round(max(open_, close) * 1.004, 4),
                        "low": round(min(open_, close) * 0.996, 4),
                        "close": close,
                        "adj_close": close,
                        "volume": volume(i),
                        "turnover": close * volume(i),
                        "turnover_status": "unknown"
                        if (i, t) == UNKNOWN_TURNOVER
                        else "available",
                        "source": "test",
                        "is_suspended": False,
                    }
                )
        for t, day in enumerate(days):
            level = 8000.0 + 3 * t
            bars.append(
                {
                    "instrument_id": INDEX_ID,
                    "trading_date": day,
                    "open": level,
                    "high": level,
                    "low": level,
                    "close": level,
                    "adj_close": level,
                    "volume": 0,
                    "turnover": 0.0,
                    "turnover_status": "unknown",
                    "source": "twse_index",
                    "is_suspended": False,
                }
            )
        db.execute(insert(MarketBar), bars)
        db.execute(insert(CorporateAction), corporate_actions())
        db.commit()
    engine.dispose()
    return path


ACTIONS = (
    # (id, action date, cash, stock ratio); 2012 is a year before W3's T
    (3, date(2012, 5, 2), 1.5, None),  # 1 for T in 2013-04-04 .. 2013-05-01
    (5, date(2012, 5, 2), None, 0.1),  # stock only: 0, a null cash row
    (7, date(2012, 5, 2), None, None),  # all three null: 0, a null cash row
    (9, date(2012, 5, 2), 0.0, None),  # zero cash: 0
    (11, date(2012, 5, 10), 2.0, None),  # 1 for T in 2013-04-12 .. 2013-05-09
    (3, "session 50", 1.0, None),  # inside the bars: W1's adjusted closes move
)


def corporate_actions() -> list[dict]:
    days = trading_days()
    rows = []
    for i, day, cash, stock in ACTIONS:
        rows.append(
            {
                "instrument_id": i,
                "action_date": days[50] if day == "session 50" else day,
                "action_type": "corporate_action",
                "cash_dividend": cash,
                "stock_dividend_ratio": stock,
                "reference_price": None if cash is None and stock is None else 40.0,
                "source": "test",
            }
        )
    return rows


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("round6") / "stock.db")


APP_PATHS = ("STOCK_DB_PATH", "STOCK_DATA_DIR", "STOCK_RAW_DIR")


def one_process(run):
    """research_report.load_actions points these at the copy for app.config."""

    saved = {key: os.environ.get(key) for key in APP_PATHS}
    try:
        return run()
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def loaded(fixture_db, tmp_path_factory):
    days = trading_days()
    raw = tmp_path_factory.mktemp("raw")
    return one_process(lambda: tool.load(fixture_db, date(1990, 1, 1), days[-1], raw))


def test_w1_divides_the_adjusted_return_by_the_unadjusted_turnover(loaded):
    days = trading_days()
    item = loaded.panel.series[3]
    at = item.position[days[70]]
    assert item.scale[at - 30] != pytest.approx(1.0)  # adjusted before session 50
    assert item.scale[at] == pytest.approx(1.0)
    raw = closes(3)
    by_hand = (
        sum(
            abs(item.close[k] / item.close[k - 1] - 1) / (raw[k] * volume(3))
            for k in range(at - 59, at + 1)
        )
        / 60
    )
    assert tool.amihud_60(loaded, item, at) == pytest.approx(by_hand, rel=1e-9, abs=0)
    adjusted = (
        sum(
            abs(item.close[k] / item.close[k - 1] - 1)
            / (raw[k] * volume(3) * item.scale[k])
            for k in range(at - 59, at + 1)
        )
        / 60
    )
    assert tool.amihud_60(loaded, item, at) != pytest.approx(adjusted, rel=1e-9, abs=0)


def test_w1_a_turnover_status_not_available_is_missing_for_its_60_bars(loaded):
    days = trading_days()
    item = loaded.panel.series[9]
    assert tool.amihud_60(loaded, item, item.position[days[99]]) is not None
    assert tool.amihud_60(loaded, item, item.position[days[100]]) is None
    assert tool.amihud_60(loaded, item, item.position[days[159]]) is None
    assert tool.amihud_60(loaded, item, item.position[days[160]]) is not None


def test_w3_reads_the_cash_dividend_as_stored(loaded):
    day = date(2013, 4, 15)
    values = {
        i: tool.expected_parts(
            loaded, loaded.panel.series[i], loaded.panel.series[i].position[day]
        )
        for i in (3, 5, 7, 9, 11, 13)
    }
    assert values == {
        3: tool.Expected(1.0, False),
        5: tool.Expected(0.0, True),
        7: tool.Expected(0.0, True),
        9: tool.Expected(0.0, False),
        11: tool.Expected(1.0, False),
        13: tool.Expected(0.0, False),
    }


def compressed(monkeypatch, tmp_path: Path) -> None:
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
    floors = {"exploration": 100, "validation": 60}
    monkeypatch.setattr(tool, "MIN_SEGMENT_DAYS", floors)
    monkeypatch.setattr(ex, "MIN_SEGMENT_DAYS", floors)  # explore_judge's
    monkeypatch.setattr(
        tool,
        "HYPOTHESES",
        {
            name: {**spec, "start": ("session", days[0], 61)}
            for name, spec in REGISTERED.items()
        },
    )
    monkeypatch.setattr(ex, "REPO_LEDGER", tmp_path / "repo-ledger.json")
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def copy_of(db: Path, tmp_path: Path) -> Path:
    folder = tmp_path / "copy"
    folder.mkdir()
    (folder / "research-db.json").write_text(
        '{"purpose": "research_history", "issue": 692}\n', encoding="utf-8"
    )
    return Path(shutil.copy(db, folder / "stock.db"))


def explore(
    db: Path, out: Path, *extra: str, hypotheses: str | None = "W1,W2,W3,W4"
) -> int:
    chosen = [] if hypotheses is None else ["--hypotheses", hypotheses]
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
                *chosen,
                *extra,
            ]
        )  # fmt: skip
    )


def validate(db: Path, out: Path, report: Path | None, sha: str | None = None, url=URL):
    argv = ["--db", str(db), "--out", str(out), "--segment", "validation",
            "--min-free-gb", "0"]  # fmt: skip
    if report is not None:
        sha = sha if sha is not None else ex.file_sha256(report)
        argv += ["--exploration-report", str(report), "--exploration-sha256", sha]
        argv += ["--exploration-url", url]
    return one_process(lambda: tool.main(argv))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def refused(capsys) -> list[str]:
    return json.loads(capsys.readouterr().out)["refused"]


@pytest.fixture
def explored(fixture_db, tmp_path, monkeypatch):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    out = tmp_path / "exploration"
    assert explore(db, out) == 0
    return db, out


NAMES = ("W1", "W2", "W3", "W4")


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round6_research",
        "903",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (6, 4, 26)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.102)
    assert report["read_until"] == trading_days()[199].isoformat()
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 4 個、累計 26 個" in text and "驗證段 t ≥ 3.102" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"], e["version"])
        for e in entries
    ] == [(name, "round6_research", 6, "exploration", 1) for name in NAMES]
    for name in NAMES:
        for file in (
            "summary.md",
            "tables.json",
            "equity.csv",
            "picks.csv",
            "trades.csv",
        ):
            assert (out / name / file).is_file(), (name, file)


def test_w3_picks_the_expected_ex_dividends_first_then_the_hash(explored):
    _db, out = explored
    day = date(2013, 4, 15)
    lines = (out / "W3" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "signal_date,rank,exchange,symbol,expected_ex_28,tie"
    rows = [line.split(",") for line in lines[1:] if line.startswith(day.isoformat())]
    assert len(rows) == 20
    symbols = [row[3] for row in rows]
    assert symbols[:2] == [
        f"S{i}" for i in sorted((3, 11), key=lambda i: pr.tie_break(day, i))
    ]
    assert [row[4] for row in rows] == ["1.0", "1.0"] + ["0.0"] * 18
    rest = sorted(set(range(1, 28)) - {3, 11}, key=lambda i: pr.tie_break(day, i))
    assert symbols[2:] == [f"S{i}" for i in rest[:18]]
    summary = (out / "W3" / "summary.md").read_text(encoding="utf-8")
    assert "另列：每年選入的股票中鍵值是 1 的平均檔數" in summary
    # stock 3 is 1 on 20 sessions, stock 11 on 20 (the hand windows in ACTIONS)
    assert (
        read_json(out / "explore.json")["hypotheses"]["W3"]["coverage"]["2013"][
            "picked_ones"
        ]
        == 40
    )


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="W2") == 2
    assert any("W2 already in" in line for line in refused(capsys))
    assert not (out.parent / "again").exists()


def test_the_repository_ledger_refuses_the_exploration_too(
    fixture_db, tmp_path, monkeypatch, capsys
):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    ex.write_ledger(
        ex.REPO_LEDGER,
        [
            {
                "hypothesis": "W4",
                "tool": "round6_research",
                "segment": "exploration",
                "version": 1,
            }
        ],
    )
    capsys.readouterr()
    assert explore(db, tmp_path / "x", hypotheses="W4") == 2
    assert any("W4 already in" in line for line in refused(capsys))


def test_unregistered_or_v_codes_are_refused(fixture_db, tmp_path, monkeypatch, capsys):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    capsys.readouterr()
    assert explore(db, tmp_path / "x", hypotheses="W1,V1") == 2
    assert any("V1 not registered" in line for line in refused(capsys))


def test_the_validation_needs_a_published_exploration_report(
    explored, tmp_path, capsys
):
    db, out = explored
    capsys.readouterr()
    assert validate(db, tmp_path / "v1", None) == 2
    assert any("needs --exploration-report" in line for line in refused(capsys))
    report = out / "explore.json"
    assert validate(db, tmp_path / "v2", report, sha="0" * 64) == 2
    assert any("not the published one" in line for line in refused(capsys))
    assert validate(db, tmp_path / "v3", report, url="https://example.com/x") == 2
    assert any("--exploration-url" in line for line in refused(capsys))
    for name in ("v1", "v2", "v3"):
        assert not (tmp_path / name).exists()


def test_the_validation_refuses_round_5s_report(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    data["design"] = "889"
    data["hypotheses"]["W1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_102(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    for name in NAMES:
        data["hypotheses"][name]["verdict"] = ex.EXPLORATION_FAILED
    data["hypotheses"]["W1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("W1", "round6_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["W1"]
    assert validation["min_t"] == 3.102
    assert read_json(tmp_path / "validation" / "W1" / "tables.json")["min_t"] == 3.102
    assert validation["read_until"] == trading_days()[279].isoformat()
    capsys.readouterr()
    assert validate(db, tmp_path / "validation-2", report) == 2
    assert any("the validation runs once" in line for line in refused(capsys))
    assert not (tmp_path / "validation-2").exists()


def test_the_validation_needs_the_research_marker(explored, tmp_path, capsys):
    db, out = explored
    (db.parent / "research-db.json").unlink()
    capsys.readouterr()
    assert validate(db, tmp_path / "v", out / "explore.json") == 2
    assert any("research marker" in line for line in refused(capsys))


def test_every_segment_reads_the_copy_from_its_start(explored, tmp_path, monkeypatch):
    """W2's 721 bars and W4's five years are more than 730 calendar days."""

    db, out = explored
    starts = []
    real = tool.load

    def spy(db, start, end, raw_dir):
        starts.append(start)
        return real(db, start, end, raw_dir)

    monkeypatch.setattr(tool, "load", spy)
    data = read_json(out / "explore.json")
    data["hypotheses"]["W2"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert validate(db, tmp_path / "validation", report) == 0
    assert starts and set(starts) == {ex.LOAD_FROM}


def test_a_passed_validation_lets_its_panel_go_before_the_used_segment(
    explored, tmp_path, monkeypatch
):
    """Both segments read the copy from its start: the validation's panel is
    collected before the used segment is loaded (PR #905 review), and the used
    segment of the passed hypothesis is written."""

    db, out = explored
    real_judge, real_load = ex.explore_judge, tool.load

    def judge(stage, *args, **kwargs):
        verdict = real_judge(stage, *args, **kwargs)
        return ex.PASSED if stage == "validation" else verdict

    loads: list[tuple] = []  # (start, end, weakref to the panel, earlier ones alive)

    def spy(db, start, end, raw_dir):
        alive = [ref() is not None for _s, _e, ref, _a in loads]
        ctx = real_load(db, start, end, raw_dir)
        loads.append((start, end, weakref.ref(ctx.panel), alive))
        return ctx

    monkeypatch.setattr(ex, "explore_judge", judge)
    monkeypatch.setattr(tool, "load", spy)
    data = read_json(out / "explore.json")
    for name in NAMES:
        data["hypotheses"][name]["verdict"] = ex.EXPLORATION_FAILED
    data["hypotheses"]["W1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert validate(db, tmp_path / "validation", report) == 0
    days = trading_days()
    assert [(start, end) for start, end, _r, _a in loads] == [
        (ex.LOAD_FROM, days[279]),
        (ex.LOAD_FROM, days[329]),
    ]
    assert loads[1][3] == [False]  # the validation's panel was gone
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert validation["hypotheses"]["W1"]["verdict"] == ex.PASSED
    assert list(validation["used"]) == ["W1"]
    for file in ("summary.md", "tables.json", "equity.csv", "picks.csv", "trades.csv"):
        assert (tmp_path / "validation" / "W1" / "used" / file).is_file(), file
    assert "## 已用段" in (tmp_path / "validation" / "explore.md").read_text(
        encoding="utf-8"
    )


def test_coverage_only_computes_no_return(fixture_db, tmp_path, monkeypatch):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    out = tmp_path / "coverage"
    assert explore(db, out, "--coverage-only", hypotheses=None) == 0
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == [
        "coverage.json",
        "coverage.md",
    ]
    body = read_json(out / "coverage.json")
    text = json.dumps(body)
    for word in ("excess", "absolute", "verdict", "equity"):
        assert word not in text
    assert not ex.read_ledger(db.parent / ex.LEDGER_NAME)
    year = {name: body["hypotheses"][name]["coverage"]["2013"] for name in NAMES}
    # W1: stock 9's unknown turnover (session 100) on the 60 signal dates 100..159
    assert year["W1"]["missing"]["amihud_60"] == 60
    # W2 and W4 need 721 bars and five years: the 330 sessions have neither
    assert year["W2"]["missing"]["reversal_720_240"] == year["W2"]["members"]
    assert year["W4"]["missing"]["season_5y"] == year["W4"]["members"]
    # W3: 20 sessions each for 3 and 11 (1), and for 5 and 7 (a null cash row)
    assert (year["W3"]["ones"], year["W3"]["null_cash"]) == (40, 40)
    assert year["W3"]["missing"]["expected_ex_28"] == 0
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "母體中鍵值是 1 的平均檔數" in md and "cash_dividend 是 null" in md
    # W3 第 6 點's listed count in the coverage too (PR #905 review)
    w3 = md.split("## W3", 1)[1].split("## W4", 1)[0]
    assert "### W3 另列：每年選入的股票中鍵值是 1 的平均檔數" in w3
    picked = year["W3"]["picked_ones"]
    assert picked == 40  # every day of stock 3's and 11's windows they are the top 2
    assert (
        f"| 2013 | {year['W3']['days']} | {year['W3']['picked']:,} | {picked} "
        f"| {picked / year['W3']['days']:.2f} |"
    ) in w3


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "W1"]
        )  # fmt: skip


# --- the ledger must be writable (#899) -------------------------------------------

# A directory a non-root POSIX user cannot write, as the research volume
# mounted :ro is in the container; Windows and root ignore the mode (#899).
READ_ONLY = pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0,
    reason="a read-only directory needs a non-root POSIX user (CI's runner)",
)


def no_reads(monkeypatch) -> list:
    """Every sqlite3.connect from here on is recorded and fails."""

    opened: list = []

    def connect(*args, **kwargs):
        opened.append(args)
        raise AssertionError(f"the DB was opened: {args}")

    monkeypatch.setattr(sqlite3, "connect", connect)
    return opened


def unwritable(problems: list[str], db: Path) -> bool:
    # the only refusal: a run refused for another reason proves nothing here
    return len(problems) == 1 and all(
        str(db.parent / ex.LEDGER_NAME) in text
        and "not writable" in text
        and ":ro" in text
        and "第 2 步的工具" in text
        for text in problems
    )


@READ_ONLY
def test_a_read_only_ledger_folder_refuses_the_exploration_before_anything_is_read(
    fixture_db, tmp_path, monkeypatch, capsys
):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    opened = no_reads(monkeypatch)
    out = tmp_path / "out"
    db.parent.chmod(0o555)
    try:
        assert explore(db, out, hypotheses="W1") == 2
    finally:
        db.parent.chmod(0o755)
    assert unwritable(refused(capsys), db)
    assert opened == [] and not out.exists()


@READ_ONLY
def test_a_read_only_ledger_refuses_the_validation_before_anything_is_read(
    explored, tmp_path, monkeypatch, capsys
):
    db, out = explored
    data = read_json(out / "explore.json")
    data["hypotheses"]["W1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    ledger = db.parent / ex.LEDGER_NAME
    before = ledger.read_bytes()
    opened = no_reads(monkeypatch)
    capsys.readouterr()
    db.parent.chmod(0o555)
    ledger.chmod(0o444)
    try:
        assert validate(db, tmp_path / "v", report) == 2
    finally:
        ledger.chmod(0o644)
        db.parent.chmod(0o755)
    assert unwritable(refused(capsys), db)
    assert opened == [] and not (tmp_path / "v").exists()
    assert ledger.read_bytes() == before


@READ_ONLY
def test_coverage_only_runs_on_a_read_only_ledger_folder(
    fixture_db, tmp_path, monkeypatch
):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    out = tmp_path / "coverage"
    db.parent.chmod(0o555)
    try:
        assert explore(db, out, "--coverage-only", hypotheses=None) == 0
    finally:
        db.parent.chmod(0o755)
    assert (out / "coverage.json").is_file()
