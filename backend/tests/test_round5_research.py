"""tools/research/round5_research.py: the registered V1～V3 (#889).

The registered numbers (N, K, start, thresholds) are asserted as written in
docs/spec/evidence.md 第五輪：V1～V3.  The features and the order are checked
on hand-made series (the expected numbers worked out in the test); the gate
("each once") runs on a synthetic copy on a compressed calendar
(``compressed``): the segments, floors and starts are moved into the
fixture's 330 sessions, everything else is the registered one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import statistics
import sys
from array import array
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.models import Base, CorporateAction, Instrument, MarketBar

ROOT = Path(__file__).resolve().parents[1].parent
URL = "https://github.com/YiCheng0608/stock-lab/issues/889#issuecomment-1"
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
tool = _tool("round5_research")
REGISTERED = {name: dict(spec) for name, spec in tool.HYPOTHESES.items()}


# --- the registration, as written -------------------------------------------------


def test_the_hypotheses_are_the_registration():
    h = tool.HYPOTHESES
    assert list(h) == ["V1", "V2", "V3"]
    assert "V1" not in ex.HYPOTHESES
    rows = {
        name: (spec["subset"], spec["keys"], spec["top"], spec["hold"], spec["start"])
        for name, spec in h.items()
    }
    assert rows == {
        "V1": (None, (("vol_60", "low"),), 20, 60, ("session", date(2007, 12, 3), 61)),
        "V2": (
            ("turnover_60", 150),
            (("momentum_20", "low"),),
            20,
            20,
            ("session", date(2007, 12, 3), 60),
        ),
        "V3": (
            None,
            (("cash_yield_12m", "high"),),
            20,
            60,
            ("date", date(2008, 12, 1)),
        ),
    }
    assert all(spec["rule"] == "daily" for spec in h.values())


def test_the_round_and_the_thresholds():
    assert (tool.VERSION, tool.ROUND, tool.ROUND_SIZE, tool.CUMULATIVE) == (1, 5, 3, 22)
    assert tool.MIN_T == 2.0
    assert tool.VALIDATION_MIN_T == 3.052
    # the registered algorithm, to the 3rd decimal (the tool does not compute it)
    assert round(ex.validation_min_t(22), 3) == 3.052
    assert tool.SEGMENTS == ex.SEGMENTS
    assert tool.MIN_SEGMENT_DAYS == ex.MIN_SEGMENT_DAYS
    assert (tool.VOL_WINDOW, tool.VOL_DDOF, tool.YIELD_CALENDAR_DAYS) == (60, 1, 365)


def test_the_definitions_hash_holds_the_validation_threshold(monkeypatch):
    before = tool.definitions_sha256()
    assert tool.definitions()["validation_min_t"] == 3.052
    monkeypatch.setattr(tool, "VALIDATION_MIN_T", 3.038)
    assert tool.definitions_sha256() != before


# AC-1: measured on master ec72e67d before this tool existed.
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


def context_for(items, raw_close=None, turnover=None, actions=None):
    series = {item.instrument_id: item for item in items}
    raw = {
        item.instrument_id: (
            [],
            [],
            (raw_close or {}).get(item.instrument_id, list(item.close)),
            [],
        )
        for item in items
    }
    market = pr.Market(lib.Panel([], series, {}, {}, {}), raw, {}, None)
    base = ex.Context(market)
    for instrument_id, values in (turnover or {}).items():
        base.turnover[instrument_id] = array("d", values)
    ctx = tool.Context(base)
    for instrument_id, rows in (actions or {}).items():
        ctx.actions[instrument_id] = tool.actions_of(rows)
    return ctx


def wave(n: int) -> list[float]:
    """Closes whose returns are +2 %, −1 %, +0.5 % in turn."""

    steps = (0.02, -0.01, 0.005)
    out = [100.0]
    for k in range(1, n):
        out.append(out[-1] * (1 + steps[k % 3]))
    return out


# --- V1 -------------------------------------------------------------------------


def test_vol_60_is_the_sample_deviation_of_60_returns_of_61_closes():
    closes = wave(70)
    item = make_item(closes)
    ctx = context_for([item])
    at = 65
    returns = [closes[k] / closes[k - 1] - 1 for k in range(at - 59, at + 1)]
    assert len(returns) == 60
    # by hand: 20 of each step; mean (0.02 − 0.01 + 0.005) / 3 = 0.005
    mean = 0.005
    by_hand = math.sqrt(
        20 * ((0.02 - mean) ** 2 + (-0.01 - mean) ** 2 + (0.005 - mean) ** 2) / 59
    )
    assert tool.vol_60(ctx, item, at) == pytest.approx(by_hand, rel=1e-9)
    assert tool.vol_60(ctx, item, at) == pytest.approx(statistics.stdev(returns))
    # ddof 1, not 0
    assert tool.vol_60(ctx, item, at) != pytest.approx(statistics.pstdev(returns))


def test_vol_60_needs_61_bars():
    item = make_item(wave(61))
    ctx = context_for([item])
    assert tool.vol_60(ctx, item, 59) is None  # 60 bars
    assert tool.vol_60(ctx, item, 60) is not None  # 61 bars


@pytest.mark.parametrize("bad", [0.0, -1.0, NAN])
@pytest.mark.parametrize("where", [0, 30, 60])  # the first, a middle, T's bar
def test_vol_60_is_missing_with_a_close_missing_or_not_positive(bad, where):
    closes = wave(61)
    closes[where] = bad
    item = make_item(closes)
    assert tool.vol_60(context_for([item]), item, 60) is None


def test_vol_60_is_missing_with_a_suspended_bar_in_the_window():
    closes = wave(62)
    for where in (1, 30, 61):
        item = make_item(closes, suspended={where})
        assert tool.vol_60(context_for([item]), item, 61) is None, where
    # just before the 61 bars: not in the window
    item = make_item(closes, suspended={0})
    assert tool.vol_60(context_for([item]), item, 61) is not None


def test_vol_60_counts_the_stocks_own_bars_not_the_market_sessions():
    # 61 own bars, one every other weekday: still 61 bars
    days = weekdays(date(2014, 1, 1), 122)[::2]
    item = make_item(wave(61), dates=days)
    assert tool.vol_60(context_for([item]), item, 60) is not None


def test_small_first_keeps_a_missing_value_last():
    keys = (("vol_60", "low"),)
    rows = [
        ("a", {"vol_60": 0.03}, "c"),
        ("b", {"vol_60": None}, "0"),  # the smallest tie-break: still last
        ("c", {"vol_60": 0.01}, "b"),
        ("d", {"vol_60": 0.02}, "a"),
    ]
    rows.sort(key=lambda row: tool.order_key(row[1], keys, row[2]))
    assert [row[0] for row in rows] == ["c", "d", "a", "b"]


def test_high_first_is_portfolio_researchs_ranking_key():
    for value in (None, 0.0, -1.5, 2.25):
        values = {"cash_yield_12m": value}
        assert tool.order_key(
            values, (("cash_yield_12m", "high"),), "t"
        ) == pr.ranking_key(values, ("cash_yield_12m",), "t")


# --- V2 -------------------------------------------------------------------------


def test_v2_takes_the_150_by_turnover_then_momentum_small_first():
    """160 members, turnover 1000 + i.  155 has no turnover: out, so 10 (the
    151st) comes in.  160 (the largest) has no momentum_20: it keeps its
    place in the 150, last.  Momentum −(i mod 7) %: ties go by the hash."""

    items, turnover, members = [], {}, []
    day = weekdays(date(2014, 1, 1), 70)[-1]
    for i in range(1, 161):
        closes = [10.0] * 70
        closes[-1] = 10.0 * (1 - (i % 7) / 100)
        if i == 160:
            closes[-21] = 0.0
        item = make_item(closes, instrument_id=i)
        items.append(item)
        turnover[i] = [NAN if i == 155 else 1000.0 + i] * 70
        members.append((item, 69))
    ctx = context_for(items, turnover=turnover)
    ranked = tool.rank(ctx, tool.HYPOTHESES["V2"], day, members)
    ids = [row[0] for row in ranked.rows]
    assert len(ids) == 150 and ranked.subset == 150
    assert set(ids) == set(range(10, 161)) - {155}
    assert ids[-1] == 160 and ranked.rows[-1][1]["momentum_20"] is None
    assert ranked.subset_missing["momentum_20"] == 1
    assert ranked.missing["turnover_60"] == 1
    # momentum −6 % first; inside a tie by sha256("<T>:<id>")
    first = [i for i in ids if i % 7 == 6 and i != 160]
    assert ids[: len(first)] == sorted(first, key=lambda i: pr.tie_break(day, i))
    assert ranked.rows[0][1]["momentum_20"] == pytest.approx(-0.06)
    values = [row[1]["momentum_20"] for row in ranked.rows[:-1]]
    assert values == sorted(values)


def test_momentum_20_is_feature_evidences():
    item = make_item([10.0] * 20 + [12.0])
    ctx = context_for([item])
    assert tool.momentum_20(ctx, item, 20) == pytest.approx(0.2)
    assert tool.momentum_20(ctx, item, 19) is None  # 20 bars


# --- V3 -------------------------------------------------------------------------


def action(day, cash=None, stock=None, split=None):
    return SimpleNamespace(
        action_date=day,
        cash_dividend=cash,
        stock_dividend_ratio=stock,
        split_ratio=split,
    )


T = date(2015, 6, 30)


def v3(actions, raw_close=50.0):
    item = make_item([50.0], dates=[T])
    ctx = context_for([item], raw_close={1: [raw_close]}, actions={1: actions})
    return tool.cash_yield_parts(ctx, item, 0)


def test_v3_window_is_365_calendar_days_left_open_right_closed():
    edge = T - timedelta(days=365)
    assert v3([action(edge, cash=9.0)]).value == 0.0  # T − 365: out
    assert v3([action(edge + timedelta(days=1), cash=2.0)]).value == pytest.approx(0.04)
    assert v3([action(T, cash=2.0)]).value == pytest.approx(0.04)  # T: in
    assert v3([action(T + timedelta(days=1), cash=9.0)]).value == 0.0  # after T


def test_v3_adds_two_payouts_in_a_year():
    rows = [action(date(2014, 8, 1), cash=1.5), action(date(2015, 3, 2), cash=1.0)]
    assert v3(rows).value == pytest.approx(2.5 / 50.0)


def test_v3_a_stock_only_row_is_zero_and_no_row_is_zero():
    assert v3([action(date(2015, 1, 5), stock=0.1)]).value == 0.0
    assert v3([action(date(2015, 1, 5), split=2.0)]).value == 0.0
    assert v3(
        [action(date(2015, 1, 5), stock=0.1), action(date(2015, 2, 5), cash=1.0)]
    ).value == (pytest.approx(0.02))
    assert v3([]).value == 0.0
    item = make_item([50.0], dates=[T])
    assert tool.cash_yield_12m(context_for([item]), item, 0) == 0.0  # no actions at all


def test_v3_all_three_null_makes_it_missing():
    parts = v3([action(date(2015, 1, 5)), action(date(2015, 2, 5), cash=1.0)])
    assert parts.value is None and parts.unknown_row and not parts.no_close
    # outside the window it does not count
    assert v3([action(date(2014, 1, 5)), action(date(2015, 2, 5), cash=1.0)]).value == (
        pytest.approx(0.02)
    )


@pytest.mark.parametrize("close", [0.0, -5.0, NAN])
def test_v3_unadjusted_close_not_positive_is_missing(close):
    parts = v3([action(date(2015, 2, 5), cash=1.0)], raw_close=close)
    assert parts.value is None and parts.no_close and not parts.unknown_row


def test_v3_divides_by_the_unadjusted_close():
    item = make_item([25.0], dates=[T])  # the adjusted close is not used
    ctx = context_for([item], raw_close={1: [50.0]}, actions={1: [action(T, cash=2.0)]})
    assert tool.cash_yield_12m(ctx, item, 0) == pytest.approx(0.04)


def test_v3_rank_counts_both_missing_reasons_apart():
    members, items, raw, acts = [], [], {}, {}
    for i, (rows, close) in enumerate(
        [
            ([action(date(2015, 1, 5), cash=3.0)], 50.0),  # 6 %
            ([action(date(2015, 1, 5))], 0.0),  # both reasons
            ([action(date(2015, 1, 5), cash=1.0)], 50.0),  # 2 %
            ([], 50.0),  # 0
        ],
        1,
    ):
        item = make_item([close or 1.0], dates=[T], instrument_id=i)
        items.append(item)
        raw[i] = [close]
        acts[i] = rows
        members.append((item, 0))
    ctx = context_for(items, raw_close=raw, actions=acts)
    ranked = tool.rank(ctx, tool.HYPOTHESES["V3"], T, members)
    assert [row[0] for row in ranked.rows] == [1, 3, 4, 2]
    assert (ranked.unknown_rows, ranked.no_close, ranked.missing["cash_yield_12m"]) == (
        1,
        1,
        1,
    )


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
        (3.051, "前瞻觀察"),
        (3.052, "通過"),
        (4.0, "通過"),
    ],
)
def test_the_validation_passes_from_3_052(t, verdict):
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


def trading_days() -> list[date]:
    return weekdays(date(2013, 1, 1), SESSIONS)


def noise(i: int, t: int, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}{i}:{t}".encode()).digest()
    return digest[0] / 255.0 - 0.5


def closes(i: int) -> list[float]:
    """A drift by id and a noise whose size grows with the id (V1 has an order)."""

    level, out = 50.0 + i, []
    for t in range(SESSIONS):
        level *= 1.0 + (i - 12) * 0.0002 + 0.002 * i * noise(i, t)
        out.append(round(level, 4))
    return out


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
                        "volume": 2_000_000 + 10_000 * i,
                        "turnover": close * (2_000_000 + 10_000 * i),
                        "turnover_status": "available",
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
    # (id, session, cash, stock ratio)
    (3, 50, 1.5, None),
    (3, 150, 1.0, None),
    (5, 100, None, 0.1),
    (7, 90, None, None),  # all three null
    (25, 60, 0.8, None),  # delisted, in 2013
)


def corporate_actions() -> list[dict]:
    days = trading_days()
    rows = []
    for i, t, cash, stock in ACTIONS:
        rows.append(
            {
                "instrument_id": i,
                "action_date": days[t],
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
    return build(tmp_path_factory.mktemp("round5") / "stock.db")


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


def test_the_loaded_actions_give_the_hand_yield(fixture_db, tmp_path):
    days = trading_days()
    ctx = one_process(
        lambda: tool.load(fixture_db, date(1990, 1, 1), days[-1], tmp_path)
    )
    raw = closes(3)
    item = ctx.panel.series[3]
    at = item.position[days[160]]
    assert tool.cash_yield_12m(ctx, item, at) == pytest.approx(2.5 / raw[160])
    item5, item7 = ctx.panel.series[5], ctx.panel.series[7]
    assert tool.cash_yield_12m(ctx, item5, item5.position[days[160]]) == 0.0
    assert tool.cash_yield_12m(ctx, item7, item7.position[days[160]]) is None
    assert ctx.statuses[25] == "delisted" and ctx.statuses[26] == "transferred"
    rows = tool.action_coverage(ctx, days[-1])
    assert rows["2013"] == {
        "delisted": 3,
        "delisted_acted": 1,
        "all": 27,
        "all_acted": 4,
    }
    assert rows["2014"]["delisted"] == 1  # 26 transferred in 2014, 25 and 27 gone


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
    db: Path, out: Path, *extra: str, hypotheses: str | None = "V1,V2,V3"
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
    argv = [
        "--db",
        str(db),
        "--out",
        str(out),
        "--segment",
        "validation",
        "--min-free-gb",
        "0",
    ]
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


def test_the_exploration_reports_the_round_and_records_the_ledger(explored):
    db, out = explored
    report = read_json(out / "explore.json")
    assert (report["tool"], report["design"], report["segment"]) == (
        "round5_research",
        "889",
        "exploration",
    )
    assert (report["round"], report["round_size"], report["cumulative"]) == (5, 3, 22)
    assert (report["min_t"], report["validation_min_t"]) == (2.0, 3.052)
    assert report["read_until"] == trading_days()[199].isoformat()
    text = (out / "explore.md").read_text(encoding="utf-8")
    assert "本輪 3 個、累計 22 個" in text and "驗證段 t ≥ 3.052" in text
    entries = ex.read_ledger(db.parent / ex.LEDGER_NAME)
    assert [
        (e["hypothesis"], e["tool"], e["round"], e["segment"]) for e in entries
    ] == [(name, "round5_research", 5, "exploration") for name in ("V1", "V2", "V3")]
    for name in ("V1", "V2", "V3"):
        for file in (
            "summary.md",
            "tables.json",
            "equity.csv",
            "picks.csv",
            "trades.csv",
        ):
            assert (out / name / file).is_file(), (name, file)


def test_v1_picks_the_quietest_first(explored):
    _db, out = explored
    lines = (out / "V1" / "picks.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "signal_date,rank,exchange,symbol,vol_60,tie"
    first_day = [line.split(",") for line in lines[1:21]]
    values = [float(row[4]) for row in first_day]
    assert values == sorted(values)
    assert first_day[0][3] == "S1"  # the smallest noise


def test_the_exploration_runs_once(explored, capsys):
    db, out = explored
    capsys.readouterr()
    assert explore(db, out.parent / "again", hypotheses="V2") == 2
    assert any("V2 already in" in line for line in refused(capsys))
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
                "hypothesis": "V3",
                "tool": "round5_research",
                "segment": "exploration",
                "version": 1,
            }
        ],
    )
    capsys.readouterr()
    assert explore(db, tmp_path / "x", hypotheses="V3") == 2
    assert any("V3 already in" in line for line in refused(capsys))


def test_unregistered_or_x_codes_are_refused(fixture_db, tmp_path, monkeypatch, capsys):
    db = copy_of(fixture_db, tmp_path)
    compressed(monkeypatch, tmp_path)
    capsys.readouterr()
    assert explore(db, tmp_path / "x", hypotheses="V1,X1") == 2
    assert any("X1 not registered" in line for line in refused(capsys))


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


def test_the_validation_refuses_another_tools_report(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    data["design"] = "703"
    data["hypotheses"]["V1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "other.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "v", report) == 2
    assert "the report is not an exploration report of this tool" in refused(capsys)


def test_the_validation_runs_once_with_3_052(explored, tmp_path, capsys):
    db, out = explored
    data = read_json(out / "explore.json")
    for name in ("V1", "V2", "V3"):
        data["hypotheses"][name]["verdict"] = ex.EXPLORATION_FAILED
    data["hypotheses"]["V1"]["verdict"] = ex.EXPLORATION_PASSED
    report = tmp_path / "passed.json"
    report.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    capsys.readouterr()
    assert validate(db, tmp_path / "validation", report) == 0
    entries = [
        (e["hypothesis"], e["tool"], e["status"])
        for e in ex.read_ledger(db.parent / ex.LEDGER_NAME)
        if e["segment"] == "validation"
    ]
    assert entries == [("V1", "round5_research", "finished")]
    validation = read_json(tmp_path / "validation" / "explore.json")
    assert list(validation["hypotheses"]) == ["V1"]
    assert validation["min_t"] == 3.052
    assert read_json(tmp_path / "validation" / "V1" / "tables.json")["min_t"] == 3.052
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
    v3 = body["hypotheses"]["V3"]["coverage"]
    # stock 7's all-null row (session 90) is in the window of every T of 2013 from it
    assert sum(row["unknown_rows"] for row in v3.values()) > 0
    assert all(
        row["missing"]["cash_yield_12m"] == row["unknown_rows"] for row in v3.values()
    )
    v2 = body["hypotheses"]["V2"]["coverage"]
    assert all(row["subset"] == row["members"] for row in v2.values())  # < 150 members
    assert body["actions"]["2013"]["delisted"] == 3
    md = (out / "coverage.md").read_text(encoding="utf-8")
    assert "各欄不互斥" in md and "2007-12" in md and "子集合內 20 日報酬 缺值" in md


def test_coverage_only_takes_no_hypotheses(tmp_path):
    with pytest.raises(SystemExit):
        tool.main(
            ["--db", str(tmp_path / "x.db"), "--out", str(tmp_path), "--segment",
             "exploration", "--coverage-only", "--hypotheses", "V1"]
        )  # fmt: skip
