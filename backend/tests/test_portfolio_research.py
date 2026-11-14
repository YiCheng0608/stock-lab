"""tools/research/portfolio_research.py: the portfolio study, worked by hand (#682)."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sys
from array import array
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.domain import CANDIDATE_SCORE, weighted_available_mean
from app.models import Base, Instrument, MarketBar
from app.strategies import levels
from worker.pipeline import _percentile

ROOT = Path(__file__).resolve().parents[2]


def _tool(name: str):
    path = ROOT / "tools" / "research" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lib = _tool("evidence_lib")
tool = _tool("portfolio_research")

BUY = 1.0005 * 1.001425  # slippage and fee on the cash paid
SELL = 0.9995 * (1 - 0.001425 - 0.003)  # slippage, fee and tax off the sale
A, B, C, ETF = 1, 2, 3, 4


def quotes(table):
    """``quote`` over {(instrument, session): Quote}; missing is no bar."""

    return lambda instrument_id, s: table.get((instrument_id, s))


def q(o, c, **extra):
    return tool.Quote(o, c, True, **extra)


# --- fixed constants -------------------------------------------------------------


def test_the_grid_costs_and_rule_are_the_decisions():
    assert tool.TOPS == (5, 10, 20) and tool.HOLDS == (5, 10, 20)
    assert tool.SLIPPAGE * 10_000 == 5.0
    assert (2 * tool.FEE + tool.TAX) * 10_000 == pytest.approx(lib.DEFAULT_COST_BPS)
    assert (tool.MIN_DAYS, tool.MIN_T) == (60, 2.0)
    assert "去掉新聞與族群" in tool.SCORE_LABEL
    assert CANDIDATE_SCORE["name"] == "candidate_score_v7"
    assert set(tool.SCORED_COMPONENTS) <= set(CANDIDATE_SCORE["weights"])


# --- the engine --------------------------------------------------------------------


def test_k_accounts_take_turns_and_fewer_names_keep_cash():
    table = {
        (A, 1): q(100, 110),
        (A, 2): q(110, 121),
        (A, 3): q(121, 121),
        (A, 4): q(121, 121),
    }
    result = tool.simulate({1: [A], 2: [A]}, quotes(table), 1, 4, hold=2, top=2)
    # Account 0 buys on session 1 with half its 0.5 (1 name of top 2).
    u1 = 0.25 / (100 * BUY)
    # Account 1 buys on session 2; account 0's position is sold at session 2's close.
    u2 = 0.25 / (110 * BUY)
    p1 = u1 * 121 * SELL
    p2 = u2 * 121 * SELL
    assert result.equity == pytest.approx(
        [0.75 + u1 * 110, 0.5 + p1 + u2 * 121, 0.5 + p1 + p2, 0.5 + p1 + p2]
    )
    assert result.bought == pytest.approx([0.25, 0.25, 0.0, 0.0])
    assert result.invested[2] == 0.0
    assert [p.how for p in result.positions] == ["close", "close"]
    assert [(p.bought, p.due, p.sold) for p in result.positions] == [
        (1, 2, 2),
        (2, 3, 3),
    ]
    assert result.counts["bought"] == 2


def test_the_account_reinvests_what_it_got_back():
    table = {(A, s): q(100, 100) for s in range(1, 6)}
    table[(A, 2)] = q(100, 120)
    result = tool.simulate({1: [A], 3: [A]}, quotes(table), 1, 4, hold=2, top=1)
    back = 0.5 / (100 * BUY) * 120 * SELL
    # Session 3 is account 0's turn again: all of ``back`` goes in.
    assert result.bought == pytest.approx([0.5, 0.0, back, 0.0])


def test_all_names_share_equally_without_a_top():
    table = {(A, 1): q(100, 110), (B, 1): q(50, 45)}
    result = tool.simulate({1: [A, B]}, quotes(table), 1, 1, hold=1, top=None)
    expected = 0.5 / (100 * BUY) * 110 * SELL + 0.5 / (50 * BUY) * 45 * SELL
    assert result.equity == pytest.approx([expected])


def test_the_top_caps_the_names_and_their_share():
    table = {(i, 1): q(100, 100) for i in (A, B, C)}
    result = tool.simulate({1: [A, B, C]}, quotes(table), 1, 1, hold=1, top=2)
    assert result.counts["bought"] == 2
    assert result.bought == pytest.approx([1.0])


def test_a_session_locked_at_limit_up_is_not_bought():
    table = {(A, 1): q(110, 110, locked_up=True), (B, 1): q(100, 105)}
    result = tool.simulate({1: [A, B]}, quotes(table), 1, 1, hold=1, top=2)
    assert result.counts["limit_up"] == 1 and result.counts["bought"] == 1
    assert result.equity == pytest.approx([0.5 + 0.5 / (100 * BUY) * 105 * SELL])


def test_no_bar_or_a_suspension_is_not_bought():
    table = {(B, 1): tool.Quote(100, 100, False)}
    result = tool.simulate({1: [A, B]}, quotes(table), 1, 1, hold=1, top=2)
    assert result.counts["not_tradable"] == 2
    assert result.equity == [1.0]


def test_a_session_locked_at_limit_down_moves_the_sale_to_the_next_open():
    table = {(A, 1): q(100, 90, locked_down=True), (A, 2): q(85, 88)}
    result = tool.simulate({1: [A]}, quotes(table), 1, 2, hold=1, top=1)
    units = 1.0 / (100 * BUY)
    assert result.equity == pytest.approx([units * 90, units * 85 * SELL])
    assert result.counts["limit_down"] == 1
    assert result.positions[0].how == "delayed" and result.positions[0].sold == 2


def test_a_suspended_due_session_holds_at_the_last_close():
    table = {
        (A, 1): q(100, 104),
        (A, 2): tool.Quote(104, 104, False),
        (A, 4): q(95, 96),
    }
    result = tool.simulate({1: [A]}, quotes(table), 1, 4, hold=2, top=1)
    units = 0.5 / (100 * BUY)
    # Session 3 has no bar: still held at 104; session 4 sells at its open.
    assert result.equity == pytest.approx(
        [
            0.5 + units * 104,
            0.5 + units * 104,
            0.5 + units * 104,
            0.5 + units * 95 * SELL,
        ]
    )
    assert result.counts["sale_held"] == 1
    assert result.positions[0].how == "delayed"


def test_positions_open_at_the_end_are_valued_and_counted():
    table = {(A, s): q(100, 100 + s) for s in range(1, 4)}
    result = tool.simulate({1: [A]}, quotes(table), 1, 3, hold=5, top=1)
    assert result.counts["unsold"] == 1
    assert result.equity[-1] == pytest.approx(0.8 + 0.2 / (100 * BUY) * 103)


# --- metrics and the verdict ---------------------------------------------------------


def test_daily_returns_and_drawdown():
    returns = tool.daily_returns([1.1, 0.99, 1.089])
    assert returns == pytest.approx([0.1, -0.1, 0.1])
    assert tool.max_drawdown(returns) == pytest.approx(-0.1)


def test_curve_metrics_annualize_252_days():
    metrics = tool.curve_metrics([0.001] * 252, [0.5] * 252, [0.01] * 252)
    assert metrics["annual"] == pytest.approx(1.001**252 - 1)
    assert metrics["invested"] == 0.5
    assert metrics["turnover"] == pytest.approx(2.52)
    assert metrics["max_drawdown"] == 0.0


def test_excess_t_is_the_plain_daily_t():
    values = [0.001, 0.003, -0.001, 0.002]
    excess = tool.excess_metrics(values)
    mean = sum(values) / 4
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / 3)
    assert excess["t"] == pytest.approx(mean / (sd / 2))
    assert excess["annual"] == pytest.approx(mean * 252)


def seg(days, mean, t):
    return {"days": days, "mean": mean, "t": t}


@pytest.mark.parametrize(
    ("exploration", "validation", "verdict"),
    [
        (seg(59, 0.01, 5.0), seg(100, 0.01, 5.0), "無法判定"),
        (seg(100, 0.01, 5.0), seg(59, 0.01, 5.0), "無法判定"),
        (seg(100, 0.01, 2.0), seg(100, 0.01, 2.0), "贏過基準"),
        (seg(100, -0.01, -2.0), seg(100, -0.01, -2.5), "輸給基準"),
        (seg(100, 0.01, 1.99), seg(100, 0.01, 3.0), "沒有差異"),
        (seg(100, 0.01, None), seg(100, 0.01, 3.0), "沒有差異"),
        (seg(100, 0.01, 2.5), seg(100, -0.01, -0.5), "驗證段反轉"),
        (seg(100, -0.01, -2.5), seg(100, -0.01, -1.0), "方向一致但不顯著"),
        (seg(100, 0.01, 2.5), seg(100, 0.01, 1.0), "方向一致但不顯著"),
    ],
)
def test_judge_follows_the_table(exploration, validation, verdict):
    assert tool.judge(exploration, validation) == verdict


# --- a market by hand ------------------------------------------------------------------

DAY0 = date(2025, 3, 3)


def series(instrument_id, closes, *, highs=None, lows=None, volumes=None, flags=None):
    item = lib.Series(instrument_id)
    n = len(closes)
    highs = highs or closes
    lows = lows or closes
    volumes = volumes or [1_000_000.0] * n
    flags = flags or [False] * n
    item.suspended.append(0)
    for at in range(n):
        day = DAY0 + timedelta(days=at)
        item.position[day] = at
        item.dates.append(day)
        item.session.append(at)
        item.open.append(closes[at])
        item.high.append(highs[at])
        item.low.append(lows[at])
        item.close.append(closes[at])
        item.volume.append(volumes[at])
        item.suspended.append(item.suspended[-1] + (1 if flags[at] else 0))
    item.chips = {name: array("d", [math.nan]) * n for name in lib.CHIP_FIELDS}
    return item


def market(items, raws=None, kinds=None):
    n = max(len(item.dates) for item in items)
    sessions = [DAY0 + timedelta(days=at) for at in range(n)]
    listed = {
        day: [item.instrument_id for item in items if day in item.position]
        for day in sessions
    }
    raw = {}
    for item in items:
        given = (raws or {}).get(item.instrument_id)
        raw[item.instrument_id] = given or (
            list(item.low),
            list(item.high),
            list(item.close),
            [False] * len(item.dates),
        )
    symbols = {
        item.instrument_id: ("TWSE", f"S{item.instrument_id}", "") for item in items
    }
    panel = lib.Panel(
        sessions, {item.instrument_id: item for item in items}, listed, {}, symbols
    )
    return tool.Market(
        panel, raw, kinds or {item.instrument_id: "stock" for item in items}, levels
    )


def test_limits_are_the_previous_close_on_the_bars_basis():
    # A 2:1 split on bar 1: the panel halves bar 0 (100 -> 50), the raw bar 1 is 55.
    item = series(A, [50.0, 55.0], lows=[50.0, 55.0], highs=[50.0, 55.0])
    raw = ([100.0, 55.0], [100.0, 55.0], [100.0, 55.0], [False, False])
    m = market([item], {A: raw})
    assert m.limits(A, 1) == (45.0, 55.0)
    quote = m.quote(A, 1)
    assert quote.tradable and quote.locked_up and not quote.locked_down


def test_limits_round_to_the_tick_and_need_a_previous_close():
    item = series(
        A, [101.0, 99.0, 90.9], lows=[101.0, 99.0, 90.9], highs=[101.0, 99.0, 91.0]
    )
    m = market([item])
    assert m.limits(A, 0) is None
    # 101 * 1.1 = 111.1 -> 111.0 (tick 0.5 from 100); 101 * 0.9 = 90.9 (tick 0.1)
    assert m.limits(A, 1) == pytest.approx((90.9, 111.0))
    # 99 * 0.9 = 89.1 -> 89.1 (tick 0.1 below 100)
    assert m.limits(A, 2)[0] == pytest.approx(89.1)
    assert not m.quote(A, 2).locked_down
    assert m.quote(A, 0).tradable and not m.quote(A, 0).locked_up


def test_a_suspended_bar_is_not_tradable():
    item = series(A, [100.0, 100.0], flags=[False, True])
    assert not market([item]).quote(A, 1).tradable


def test_technical_inputs_are_v7s():
    volumes = [100.0] * 20 + [300.0]
    highs = [100.0] * 19 + [120.0, 126.0]
    item = series(A, [100.0] * 20 + [126.0], highs=highs, volumes=volumes)
    breakout = tool.technical_inputs(item, 20, "breakout_v3")
    assert breakout["volume_ratio"] == pytest.approx(3.0)
    assert breakout["distance"] == pytest.approx(126 / 120 - 1)
    pullback = tool.technical_inputs(item, 20, "pullback_v4")
    ma20 = (19 * 100 + 126) / 20
    assert pullback["distance"] == pytest.approx(abs(126 / ma20 - 1))
    assert tool.technical_inputs(item, 19, "breakout_v3") == {
        "volume_ratio": None,
        "distance": None,
    }


def test_chip_inputs_skip_suspended_bars_and_need_every_row():
    n = 22
    flags = [False] * n
    flags[5] = True
    item = series(A, [100.0] * n, volumes=[1000.0] * n)
    for at in range(n):
        item.chips["foreign_buy"][at] = 10.0
        item.chips["trust_buy"][at] = 5.0
        item.chips["dealer_buy"][at] = -5.0
        item.chips["margin_balance"][at] = 100.0
    item.chips["margin_balance"][21] = 110.0
    inputs = tool.chip_inputs(item, flags, 21)
    assert inputs["institutional_flow_5d"] == pytest.approx(50 / 1000)
    assert inputs["institutional_flow_20d"] == pytest.approx(200 / 1000)
    assert inputs["margin_change_5d"] == pytest.approx(0.1)
    # The window is bars 1..21 without 5: bar 1's missing dealer drops the 20-day flow.
    item.chips["dealer_buy"][1] = math.nan
    assert tool.chip_inputs(item, flags, 21)["institutional_flow_20d"] is None
    item.chips["dealer_buy"][1] = -5.0
    item.chips["dealer_buy"][0] = math.nan  # outside the window
    assert tool.chip_inputs(item, flags, 21)["institutional_flow_20d"] is not None
    assert tool.chip_inputs(item, [True] * n, 21) == tool.CHIP_EMPTY


def test_rank_day_orders_by_technical_and_keeps_one_row_per_stock():
    day = DAY0 + timedelta(days=20)
    flat = [100.0] * 20
    a = series(A, flat + [101.0], volumes=[1e6] * 20 + [2e6])
    b = series(B, flat + [105.0], volumes=[1e6] * 21)
    thin = series(C, flat + [101.0], volumes=[1e5] * 21)
    m = market([a, b, thin])
    signals = [
        {"signal_id": 1, "instrument_id": A, "strategy": "breakout_v3"},
        {"signal_id": 2, "instrument_id": A, "strategy": "pullback_v4"},
        {"signal_id": 3, "instrument_id": B, "strategy": "breakout_v3"},
        {"signal_id": 4, "instrument_id": C, "strategy": "breakout_v3"},
    ]
    ranked, counts = tool.rank_day(
        m, day, signals, CANDIDATE_SCORE, _percentile, weighted_available_mean
    )
    assert [(e.signal_id, e.strategy) for e in ranked] == [
        (1, "breakout_v3"),
        (3, "breakout_v3"),
    ]
    # A: higher volume ratio and smaller distance than B in the breakout pool.
    assert ranked[0].technical == 1.0 and ranked[1].technical == 0.0
    assert ranked[0].chips is None and ranked[0].total == 1.0
    assert counts["low_volume"] == 1 and counts["same_instrument"] == 1


def test_rank_day_leaves_etf_signals_out():
    """A run's actionable signals include ETFs; v7's pool is stock／ipo only."""

    day = DAY0 + timedelta(days=20)
    a = series(A, [100.0] * 21)
    m = market([a], kinds={A: "stock", ETF: "etf"})
    signals = [
        {"signal_id": 1, "instrument_id": A, "strategy": "breakout_v3"},
        {"signal_id": 2, "instrument_id": ETF, "strategy": "breakout_v3"},
    ]
    ranked, counts = tool.rank_day(
        m, day, signals, CANDIDATE_SCORE, _percentile, weighted_available_mean
    )
    assert [e.signal_id for e in ranked] == [1]
    assert counts["not_stock_or_ipo"] == 1 and counts["no_bar"] == 0


# --- the command on a copy -------------------------------------------------------------

SESSIONS = 70


def trading_days() -> list[date]:
    days, current = [], date(2025, 11, 3)
    while len(days) < SESSIONS:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


@pytest.fixture(scope="module")
def copy_db(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("copy") / "stock.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    with Session(engine) as db:
        for instrument_id, kind, symbol in (
            (A, "stock", "S1"),
            (B, "stock", "S2"),
            (9, "index", "TAIEX"),
            (ETF, "etf", "0050"),
        ):
            db.add(
                Instrument(
                    id=instrument_id,
                    exchange="TWSE",
                    symbol=symbol,
                    name=f"N{instrument_id}",
                    instrument_type=kind,
                )
            )
        for index, current in enumerate(days):
            for instrument_id, price in (
                (A, 100.0 + index),
                (B, 100.0),
                (9, 20000.0 + index),
            ):
                db.add(
                    MarketBar(
                        instrument_id=instrument_id,
                        trading_date=current,
                        open=price,
                        high=price + 1,
                        low=price - 1,
                        close=price,
                        adj_close=price,
                        volume=2_000_000,
                        source="test",
                        is_suspended=False,
                    )
                )
        db.commit()
    engine.dispose()
    return path


def write_signals(path: Path, rows) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "signal_id",
                "strategy",
                "instrument_id",
                "symbol",
                "signal_date",
                "E0_net",
            ]
        )
        writer.writerows(rows)
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_command_writes_reports_and_not_the_database(
    copy_db, tmp_path, monkeypatch, capsys
):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    monkeypatch.setenv("STOCK_DATA_DIR", str(tmp_path / "production"))
    days = trading_days()
    rows = [
        (n, "breakout_v3", A, "S1", days[at].isoformat(), "")
        for n, at in enumerate(range(25, 60), 1)
    ]
    rows.append((1, "breakout_v3", A, "S1", days[25].isoformat(), ""))  # a repeated row
    # An ETF's signal: its symbol is the copy's, so it is not a mismatch.
    rows.append((99, "breakout_v3", ETF, "0050", days[30].isoformat(), ""))
    signals = write_signals(tmp_path / "trades.csv", rows)
    before = digest(copy_db)
    out = tmp_path / "out"
    code = tool.main(
        [
            "--db", str(copy_db),
            "--signals", str(signals),
            "--signals-source", "test@sha:trades.csv",
            "--cutoff", days[60].isoformat(),
            "--out", str(out),
            "--min-free-gb", "0",
        ]
    )  # fmt: skip
    assert code == 0
    assert digest(copy_db) == before
    assert not list(copy_db.parent.glob("stock.db-*"))
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert (
        tables["signals"]["rows"] == 36
        and tables["signals"]["source"] == "test@sha:trades.csv"
    )
    assert tables["pool_counts"]["not_stock_or_ipo"] == 1
    assert tables["comparisons"] == 18 and tables["cutoff"] == days[60].isoformat()
    assert tables["first_session"] == days[26].isoformat()
    top = tables["variants"]["K5:top5"]
    assert top["verdicts"] == {"population": "無法判定", "taiex": "無法判定"}
    assert top["counts"]["bought"] > 0
    assert set(tables["variants"]) == {
        f"K{k}:{key}"
        for k in tool.HOLDS
        for key in ["top5", "top10", "top20", "pool", "population"]
    }
    assert (
        "verdicts" in tables["variants"]["K5:pool"]
        and not tables["variants"]["K5:pool"]["verdicts"]
    )
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert tool.SCORE_LABEL in summary and "候選池全部（參考線）" in summary
    equity = (out / "equity.csv").read_text(encoding="utf-8").splitlines()
    assert len(equity) == 1 + 35  # sessions 26..60
    assert (out / "picks.csv").read_text(encoding="utf-8").count("\n") == 1 + 35
    assert "population" not in (out / "trades.csv").read_text(encoding="utf-8")
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["out"]


def test_the_population_beats_nothing_on_flat_prices(copy_db, tmp_path, monkeypatch):
    """B never moves: the population (A and B) earns A's rise at half weight."""

    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    days = trading_days()
    rows = [
        (n, "breakout_v3", B, "S2", days[at].isoformat(), "")
        for n, at in enumerate(range(25, 60), 1)
    ]
    out = tmp_path / "out"
    assert tool.main(
        [
            "--db", str(copy_db),
            "--signals", str(write_signals(tmp_path / "t.csv", rows)),
            "--cutoff", days[60].isoformat(),
            "--out", str(out),
            "--min-free-gb", "0",
        ]
    ) == 0  # fmt: skip
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    flat = tables["variants"]["K5:top5"]["segments"]["all"]
    population = tables["variants"]["K5:population"]["segments"]["all"]
    # B at a flat 100 only loses the costs; A rises one a session.
    assert flat["curve"]["total"] < 0 < population["curve"]["total"]
    assert flat["excess_population"]["mean"] < 0


def test_symbols_that_differ_from_the_copy_stop_the_tool(
    copy_db, tmp_path, monkeypatch, capsys
):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    days = trading_days()
    rows = [(1, "breakout_v3", A, "9999", days[30].isoformat(), "")]
    out = tmp_path / "out"
    code = tool.main(
        [
            "--db", str(copy_db),
            "--signals", str(write_signals(tmp_path / "t.csv", rows)),
            "--out", str(out),
            "--min-free-gb", "0",
        ]
    )  # fmt: skip
    assert code == 4
    assert (
        json.loads((out / "mismatches.json").read_text(encoding="utf-8"))[0]["symbol"]
        == "9999"
    )
    assert not (out / "summary.md").exists()
    assert json.loads(capsys.readouterr().out)["stopped"]


def test_the_command_refuses_production(copy_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STOCK_DATA_DIR", str(copy_db.parent))
    code = tool.main(
        [
            "--db", str(copy_db),
            "--signals", str(tmp_path / "missing.csv"),
            "--out", str(tmp_path / "out"),
        ]
    )  # fmt: skip
    assert code == 2
    assert "refused" in json.loads(capsys.readouterr().out)
    assert not (tmp_path / "out").exists()


# --- the first version's output is unchanged (#689) -----------------------------

VOLATILE = ("elapsed_seconds", "peak_memory_gb", "command")
VOLATILE_LINES = ("- 副本：", "- 耗時 ", "- 重現：")
# Digests of the first version's outputs on the scenario below, written by the
# tool at f280528 (#682, before #689) in the backend image: a change that moves
# any byte of them fails here.
V1_DIGESTS = {
    "tables.json": "b48da88392a75720ec75fb6c69bf9513b50b8ef56d1ce9ce12369887a55e7808",
    "summary.md": "3be3812f10d8735bcc29b22437631fd7f200716d0a0fdbb69ed091f7e76a4232",
    "equity.csv": "8b894a37fd0bdfdd860e644acd5a4d1297b9131cafa91bc8b1a31b4d4523969c",
    "picks.csv": "842b7bb1b03ec7bbec032c7785b1979a73eaf6d01da667a588fa952c9243fb72",
    "trades.csv": "0a1c5fa9615d7c766bdc8418ae9bbb08ad261b937c393f3eacda8190e5ae46c1",
}


def v1_digests(out: Path) -> dict[str, str]:
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    for key in VOLATILE:
        tables.pop(key)
    tables["copy"].pop("mtime")
    summary = [
        line
        for line in (out / "summary.md").read_text(encoding="utf-8").splitlines()
        if not line.startswith(VOLATILE_LINES)
    ]
    texts = {
        "tables.json": json.dumps(tables, ensure_ascii=False, indent=2, default=str),
        "summary.md": "\n".join(summary),
    }
    digests = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in texts.items()
    }
    for name in ("equity.csv", "picks.csv", "trades.csv"):
        digests[name] = digest(out / name)
    return digests


def v1_rows() -> list[tuple]:
    days = trading_days()
    rows = [
        (n, "breakout_v3", A, "S1", days[at].isoformat(), "")
        for n, at in enumerate(range(25, 60), 1)
    ]
    rows += [
        (100 + n, "pullback_v4", B, "S2", days[at].isoformat(), "")
        for n, at in enumerate(range(25, 60, 3), 1)
    ]
    rows.append((99, "breakout_v3", ETF, "0050", days[30].isoformat(), ""))
    return rows


def run_v1(copy_db: Path, tmp_path: Path, extra: list[str]) -> Path:
    days = trading_days()
    out = tmp_path / "out"
    code = tool.main(
        [
            "--db", str(copy_db),
            "--signals", str(write_signals(tmp_path / "trades.csv", v1_rows())),
            "--signals-source", "test@sha:trades.csv",
            "--cutoff", days[60].isoformat(),
            "--out", str(out),
            "--min-free-gb", "0",
            *extra,
        ]
    )  # fmt: skip
    assert code == 0
    return out


def test_the_first_version_is_byte_for_byte_unchanged(copy_db, tmp_path, monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    assert v1_digests(run_v1(copy_db, tmp_path, [])) == V1_DIGESTS


# --- the rankings of evidence (#689) ---------------------------------------------


def with_trust(item, days):
    """Put a trust buy (+1) on the given bars and a sale (−1) on the others."""

    item.chips["trust_buy"] = array(
        "d", [1.0 if at in days else -1.0 for at in range(len(item.dates))]
    )
    return item


def test_the_rankings_are_the_decision():
    assert tool.RANKINGS_DESIGN == "689"
    assert [(key, keys) for key, _, keys in tool.RANKINGS] == [
        ("trust", ()),
        ("trust_rev", ("revenue_high_12",)),
        ("trust_eps", ("eps_yield",)),
    ]
    assert tool.PRIMARY == "trust_buy_days_5"
    assert [key for key, _ in tool.UNIVERSES] == ["pool", "all"]
    # By name: other tests load feature_evidence again as a new module object.
    assert {
        key: (function.__module__, function.__name__)
        for key, function in tool.FEATURE_FUNCTIONS.items()
    } == {
        "trust_buy_days_5": ("feature_evidence", "trust_buy_days"),
        "revenue_high_12": ("feature_evidence", "revenue_high_12"),
        "eps_yield": ("feature_evidence", "eps_yield"),
    }


def test_the_tie_break_is_a_neutral_hash():
    day = date(2025, 3, 7)
    assert tool.tie_break(day, 42) == hashlib.sha256(b"2025-03-07:42").hexdigest()
    assert tool.tie_break(day, 42) != tool.tie_break(day + timedelta(days=1), 42)


def test_ranking_keys_go_high_first_missing_last_then_the_hash():
    values = {
        1: {"trust_buy_days_5": 3.0, "eps_yield": 0.01},
        2: {"trust_buy_days_5": 5.0, "eps_yield": None},
        3: {"trust_buy_days_5": None, "eps_yield": 0.50},
        4: {"trust_buy_days_5": 5.0, "eps_yield": 0.02},
        5: {"trust_buy_days_5": 5.0, "eps_yield": -0.03},
    }
    ties = {1: "c", 2: "a", 3: "a", 4: "b", 5: "z"}

    def order(keys):
        return sorted(values, key=lambda i: tool.ranking_key(values[i], keys, ties[i]))

    # The primary key alone: the three 5s by the hash, 3 next, the missing last.
    assert order(("trust_buy_days_5",)) == [2, 4, 5, 1, 3]
    # The second key splits the 5s: high first, a negative before a missing one.
    assert order(("trust_buy_days_5", "eps_yield")) == [4, 5, 2, 1, 3]


def test_rank_by_features_keeps_every_name_and_reads_the_bar_of_t():
    n = 25
    day = DAY0 + timedelta(days=n - 1)
    a = with_trust(series(A, [100.0] * n), {n - 1, n - 2})  # 2 days
    b = with_trust(series(B, [100.0] * n), set(range(n - 5, n)))  # 5 days
    c = series(C, [100.0] * n)  # no trust rows: missing
    m = market([a, b, c])
    cache = {}
    rows = tool.rank_by_features(m.panel, day, [A, C, B], ("trust_buy_days_5",), cache)
    assert [row[0] for row in rows] == [B, A, C]
    assert [row[1]["trust_buy_days_5"] for row in rows] == [5.0, 2.0, None]
    assert rows[0][2] == tool.tie_break(day, B)
    assert set(cache) == {(day, A), (day, B), (day, C)}


def test_the_rankings_leave_the_first_version_as_it_was(copy_db, tmp_path, monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    out = run_v1(copy_db, tmp_path, ["--rankings", "689"])
    assert v1_digests(out) == V1_DIGESTS
    names = [f"{key}-{u}" for u, _ in tool.UNIVERSES for key, _, _ in tool.RANKINGS]
    for name in names:
        tables = json.loads((out / name / "tables.json").read_text(encoding="utf-8"))
        assert tables["comparisons"] == 18 and tables["comparisons_total"] == 108
        keys = {variant.split(":")[1] for variant in tables["variants"]}
        assert keys == {"top5", "top10", "top20", "population"} | (
            {"pool"} if name.endswith("-pool") else set()
        )
        assert all(
            set(v["verdicts"]) == {"population", "taiex"}
            for v in tables["variants"].values()
            if v["key"].startswith("top")
        )
        summary = (out / name / "summary.md").read_text(encoding="utf-8")
        assert tables["label"] in summary and "108" in summary
        trades = (out / name / "trades.csv").read_text(encoding="utf-8")
        assert ":pool" not in trades and ":population" not in trades
    v1 = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    pool = json.loads((out / "trust-pool" / "tables.json").read_text(encoding="utf-8"))
    # (a) reuses the first version's pool and population, untouched.
    for key in ("K5:pool", "K5:population"):
        assert pool["variants"][key] == v1["variants"][key]

    def names_by_day(path):
        days = {}
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                days.setdefault(row["signal_date"], set()).add(row["symbol"])
        return days

    # (a) is the same pool reordered: the same names every day.
    assert names_by_day(out / "trust-pool" / "picks.csv") == names_by_day(
        out / "picks.csv"
    )
    # (b) ranks the population: both stocks every day, the ETF never.
    population = names_by_day(out / "trust-all" / "picks.csv")
    assert set(map(frozenset, population.values())) == {frozenset({"S1", "S2"})}
    combined = json.loads((out / "rankings.json").read_text(encoding="utf-8"))
    assert combined["comparisons"] == 108 and set(combined["verdicts"]) == set(names)
    assert 0.05 < combined["chance"]["any"] < 0.06
    report = (out / "rankings.md").read_text(encoding="utf-8")
    assert "第 1 版 v7" in report and "`trust_eps`" in report


# The rankings' outputs on the scenario above, written by the tool at 93cba6d
# (#689, before #691) in the backend image: #691 must not move a byte of them.
RANKINGS_DIGESTS = {
    "trust-all": {
        "tables.json": "98a8b7a84bda8b9e33b888a23d09604cd4d36a0644248a483eeeaf3b95f01a8c",
        "summary.md": "27aa0411378a3fbef0a8608656b2b91a6ddaca7dd89a566a9f69dc8e45dc70e0",
        "equity.csv": "3f0e19ebb226a92e5ee722b56f4b81b5f31ffa350374d22f29f0ac597897ce96",
        "picks.csv": "d50b2440f9d2d44fb67c4d2767478f76e23634b7a5643b0354fc3552256286c8",
        "trades.csv": "e6ca6d152af129fab0b711823666bcac25936b5521b99edfbe16d4fbfe177238",
    },
    "trust-pool": {
        "tables.json": "32424192d5fbf48e6b1630de167f50ebf1dea4449b4605dcfc8946893d349b99",
        "summary.md": "679487b0458ab3f25997714ebb32d6b5ba603dd7f613f4d918f0844b90953dfb",
        "equity.csv": "8b894a37fd0bdfdd860e644acd5a4d1297b9131cafa91bc8b1a31b4d4523969c",
        "picks.csv": "923b56a5363f1ef1b363a46016f4663e8f0d90ed2a2f87579387eb05aa392170",
        "trades.csv": "e8538d085a67dc5b886bde45f2bcc6315546412b4ac3844c94cb9a651ab2b8ca",
    },
    "trust_eps-all": {
        "tables.json": "94fa9c535d87c041c230332ae9ef319db5db071195d49b11f7c5beb055fc6e79",
        "summary.md": "8fd129209f87a43d0f12c7645cd15639bd4dbc5991420e5894e2154a140ed69e",
        "equity.csv": "3f0e19ebb226a92e5ee722b56f4b81b5f31ffa350374d22f29f0ac597897ce96",
        "picks.csv": "d50b2440f9d2d44fb67c4d2767478f76e23634b7a5643b0354fc3552256286c8",
        "trades.csv": "e6ca6d152af129fab0b711823666bcac25936b5521b99edfbe16d4fbfe177238",
    },
    "trust_eps-pool": {
        "tables.json": "950855c1d56f17316e9157cf50be65d572afd6ddc8156632e1957305968b2512",
        "summary.md": "4902d1a8ecb1c1cc0a20c253d1b0e25b606f0581560a158d75f5a2c4f6be201f",
        "equity.csv": "8b894a37fd0bdfdd860e644acd5a4d1297b9131cafa91bc8b1a31b4d4523969c",
        "picks.csv": "923b56a5363f1ef1b363a46016f4663e8f0d90ed2a2f87579387eb05aa392170",
        "trades.csv": "e8538d085a67dc5b886bde45f2bcc6315546412b4ac3844c94cb9a651ab2b8ca",
    },
    "trust_rev-all": {
        "tables.json": "2e1164b9c5e1943428c786ae3f23c2842fd4cc8d798dca1066aa86aef902d76c",
        "summary.md": "276899a74b526ba3e1ae2ab68753fa6dd4e5347cdcd2a0b301f4b74bc260bf63",
        "equity.csv": "3f0e19ebb226a92e5ee722b56f4b81b5f31ffa350374d22f29f0ac597897ce96",
        "picks.csv": "d50b2440f9d2d44fb67c4d2767478f76e23634b7a5643b0354fc3552256286c8",
        "trades.csv": "e6ca6d152af129fab0b711823666bcac25936b5521b99edfbe16d4fbfe177238",
    },
    "trust_rev-pool": {
        "tables.json": "f1bc36e054a3ff833a360b0eaa3edf5d02f2fa20f48f1044b015c151a1a65820",
        "summary.md": "58113eccd1dce82caac639cb57e1095951460bc77d54f329658d8433462ac57a",
        "equity.csv": "8b894a37fd0bdfdd860e644acd5a4d1297b9131cafa91bc8b1a31b4d4523969c",
        "picks.csv": "923b56a5363f1ef1b363a46016f4663e8f0d90ed2a2f87579387eb05aa392170",
        "trades.csv": "e8538d085a67dc5b886bde45f2bcc6315546412b4ac3844c94cb9a651ab2b8ca",
    },
    "rankings.json": "e9cd74614d5fa8fa3f470ef0a4e58685dd8b14c99bd6a3cba00bc69776683988",
    "rankings.md": "d0505b889fc3a76cfec78a35fead9bb507fc360f20fe947ec2892288f56a89b4",
}


def rankings_digests(out: Path) -> dict:
    result = {
        sub.name: v1_digests(sub)
        for sub in sorted(p for p in out.iterdir() if p.is_dir() and p.name != "raw")
    }
    result["rankings.json"] = digest(out / "rankings.json")
    result["rankings.md"] = digest(out / "rankings.md")
    return result


def test_the_rankings_are_byte_for_byte_unchanged(copy_db, tmp_path, monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)
    out = run_v1(copy_db, tmp_path, ["--rankings", "689"])
    assert v1_digests(out) == V1_DIGESTS
    assert rankings_digests(out) == RANKINGS_DIGESTS


# --- the frozen hypothesis H1 (#691) ----------------------------------------------


def test_h1_is_the_decision():
    h1 = tool.HYPOTHESES["H1"]
    assert set(tool.HYPOTHESES) == {"H1"}
    assert h1["keys"] == ("trust_buy_days_5", "revenue_high_12")
    secondary = {key: keys for key, _, keys in tool.RANKINGS}[h1["ranking"]]
    assert h1["keys"] == (tool.PRIMARY, *secondary)
    assert (h1["ranking"], h1["universe"], h1["top"], h1["hold"]) == (
        "trust_rev",
        "all",
        5,
        20,
    )
    assert h1["since"] == date(2026, 11, 14) and h1["min_days"] == 250
    assert h1["historical_until"] == date(2024, 9, 27)
    assert h1["top"] in tool.TOPS and h1["hold"] in tool.HOLDS
    assert tool.WINDOWS == ("forward", "historical")


def ex(days, mean, t):
    return {"days": days, "mean": mean, "t": t}


@pytest.mark.parametrize(
    ("excess", "verdict"),
    [
        (ex(249, 0.01, 9.0), "樣本不足"),
        (ex(250, 0.01, 2.0), "通過"),
        (ex(250, -0.01, -2.0), "輸給基準"),
        (ex(250, 0.01, 1.99), "方向一致但不顯著"),
        (ex(250, 0.01, None), "方向一致但不顯著"),
        (ex(250, -0.01, -1.99), "沒有優勢"),
        (ex(250, 0.0, 0.0), "沒有優勢"),
    ],
)
def test_forward_judge_follows_the_table(excess, verdict):
    assert tool.forward_judge(excess, 250) == verdict
    assert verdict in tool.FORWARD_VERDICTS


@pytest.mark.parametrize(
    "extra",
    [["--signals", "x.csv"], ["--signals-source", "x"], ["--rankings", "689"]],
)
def test_the_hypothesis_takes_no_signals_or_other_study(tmp_path, extra):
    argv = ["--db", "x", "--out", str(tmp_path), "--hypothesis", "H1", *extra]
    with pytest.raises(SystemExit) as stopped:
        tool.main(argv)
    assert stopped.value.code == 2


def test_without_the_hypothesis_signals_are_required(tmp_path):
    for argv in (
        ["--db", "x", "--out", str(tmp_path)],
        ["--db", "x", "--out", str(tmp_path), "--window", "forward"],
    ):
        with pytest.raises(SystemExit) as stopped:
            tool.main(argv)
        assert stopped.value.code == 2


def h1_price(instrument_id: int, index: int) -> float:
    return (
        100.0 + ((index * (instrument_id + 2)) % 11) - 5 + instrument_id * index * 0.05
    )


@pytest.fixture(scope="module")
def h1_db(tmp_path_factory) -> Path:
    """Six stocks with trust buys and monthly revenues, TAIEX and an ETF."""

    from app.models import ChipSnapshot, MonthlyRevenue

    path = tmp_path_factory.mktemp("h1") / "stock.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    days = trading_days()
    stocks = range(1, 7)
    with Session(engine) as db:
        listing = [(i, "stock", f"S{i}") for i in stocks]
        listing += [(9, "index", "TAIEX"), (40, "etf", "0050")]
        for instrument_id, kind, symbol in listing:
            db.add(
                Instrument(
                    id=instrument_id,
                    exchange="TWSE",
                    symbol=symbol,
                    name=f"N{instrument_id}",
                    instrument_type=kind,
                )
            )
        for index, current in enumerate(days):
            bars = [(i, h1_price(i, index)) for i in stocks]
            bars += [(9, 20000.0 + 10 * index), (40, 150.0)]
            for instrument_id, price in bars:
                db.add(
                    MarketBar(
                        instrument_id=instrument_id,
                        trading_date=current,
                        open=price - 0.5,
                        high=price + 1,
                        low=price - 1,
                        close=price,
                        adj_close=price,
                        volume=2_000_000,
                        source="test",
                        is_suspended=False,
                    )
                )
            for i in stocks:
                if i == 6 and index < 40:
                    continue  # no chips for a while: a missing primary key
                db.add(
                    ChipSnapshot(
                        instrument_id=i,
                        trading_date=current,
                        foreign_buy=10.0,
                        trust_buy=1.0 if (index + i) % (i + 1) else -1.0,
                        dealer_buy=0.0,
                        margin_balance=100.0,
                    )
                )
        for i in (1, 2, 3, 4):
            for m in range(15):  # 2024-10 .. 2025-12, announced the 10th after
                month = date(2024 + (9 + m) // 12, (9 + m) % 12 + 1, 1)
                announced = date(
                    month.year + month.month // 12, month.month % 12 + 1, 10
                )
                revenue = 1000.0 + ((m * (i + 3)) % 7) * 10 + (50 * m if i == 1 else 0)
                db.add(
                    MonthlyRevenue(
                        instrument_id=i,
                        revenue_month=month,
                        revenue=revenue,
                        prior_year_revenue=900.0,
                        announcement_date=announced,
                        source="test",
                        raw_payload_id=1,
                        data_as_of="test",
                    )
                )
        db.commit()
    engine.dispose()
    return path


def no_window(monkeypatch):
    research = lib._load("backtest_research")
    monkeypatch.setattr(research, "daily_window_problem", lambda now: None)


def h1_run(db: Path, out: Path, **kwargs) -> dict:
    days = trading_days()
    kwargs.setdefault("cutoff", days[60])
    kwargs.setdefault("since", days[25])
    return tool.run_hypothesis(db, "H1", tool.FORWARD, out, **kwargs)


def test_h1_is_689s_trust_rev_all_top5_k20(h1_db, tmp_path, monkeypatch):
    """Started on #689's first signal date, H1 is that very group: the same
    K20:top5 curve, the same daily top 20 and the same trades, to the byte."""

    no_window(monkeypatch)
    days = trading_days()
    rows = [
        (n, "breakout_v3", 1, "S1", days[at].isoformat(), "")
        for n, at in enumerate(range(25, 60), 1)
    ]
    rankings = tmp_path / "689"
    assert tool.main(
        [
            "--db", str(h1_db),
            "--signals", str(write_signals(tmp_path / "t.csv", rows)),
            "--cutoff", days[60].isoformat(),
            "--out", str(rankings),
            "--min-free-gb", "0",
            "--rankings", "689",
        ]
    ) == 0  # fmt: skip
    h1 = tmp_path / "h1"
    h1_run(h1_db, h1)

    def column(path, name):
        with path.open(encoding="utf-8", newline="") as handle:
            return [(row["date"], row[name]) for row in csv.DictReader(handle)]

    def trades(path):
        with path.open(encoding="utf-8", newline="") as handle:
            return [
                row for row in csv.DictReader(handle) if row["variant"] == "K20:top5"
            ]

    reference = rankings / "trust_rev-all"
    for name in ("K20:top5", "K20:population", "taiex_close"):
        assert column(h1 / "equity.csv", name) == column(reference / "equity.csv", name)
    assert digest(h1 / "picks.csv") == digest(reference / "picks.csv")
    assert trades(h1 / "trades.csv") == trades(reference / "trades.csv")
    assert trades(h1 / "trades.csv")
    # Not the hash alone: trust days and revenue highs both vary here.
    with (h1 / "picks.csv").open(encoding="utf-8") as handle:
        picks = list(csv.DictReader(handle))
    assert len({row["trust_buy_days_5"] for row in picks}) > 2
    assert {"0.0", "1.0", ""} <= {row["revenue_high_12"] for row in picks}


H1_VOLATILE_LINES = ("- 副本：", "- 耗時 ", "- 重現：")
# H1's outputs on ``h1_db`` (written by the commit that froze H1, #691): a
# change of the engine, the features, the costs or the report fails here and is
# a new hypothesis, not an edit.
H1_DIGESTS = {
    "tables.json": "af5863f535c96544e03448336c3d2813ad29d888c92c56d0db6a5ee1b25ac81d",
    "summary.md": "10648205b726ed77c0009f65fb0ba21fc297b9ea3b182332c4b203882598ca94",
    "equity.csv": "e2686880710b5fb8f3cb0920fe592e3b5f65ad1d2829c0bf29584fb698f885f7",
    "picks.csv": "0eefb0a9c14ca0e057c248e3e75381cead4f0d3cce766d2417d39dc104e1684e",
    "trades.csv": "b197172d99f2f9248fdfee0fc7ac609be72915865d2b8cada331f29c47da095e",
}


def h1_digests(out: Path) -> dict[str, str]:
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    for key in VOLATILE:
        tables.pop(key)
    tables["copy"].pop("mtime")
    summary = [
        line
        for line in (out / "summary.md").read_text(encoding="utf-8").splitlines()
        if not line.startswith(H1_VOLATILE_LINES)
    ]
    texts = {
        "tables.json": json.dumps(tables, ensure_ascii=False, indent=2, default=str),
        "summary.md": "\n".join(summary),
    }
    digests = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in texts.items()
    }
    for name in ("equity.csv", "picks.csv", "trades.csv"):
        digests[name] = digest(out / name)
    return digests


def test_h1_output_is_frozen(h1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    out = tmp_path / "out"
    h1_run(h1_db, out)
    assert h1_digests(out) == H1_DIGESTS


def test_h1_short_of_250_days_is_not_a_verdict(h1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    out = tmp_path / "out"
    line = h1_run(h1_db, out)
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert line["verdict"] == tables["verdict"] == "樣本不足"
    assert (tables["days"], tables["min_days"], tables["judged_days"]) == (35, 250, 35)
    assert tables["excess"]["extension"]["population"]["days"] == 0
    assert tables["comparisons"] == 1 and tables["parameters"]["top"] == 5
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 35／250 日）" in summary and "不是判定" in summary
    assert "population" not in (out / "trades.csv").read_text(encoding="utf-8")


def test_h1_judges_once_on_the_first_m_days(h1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    spec = {**tool.HYPOTHESES["H1"], "min_days": 20}
    monkeypatch.setitem(tool.HYPOTHESES, "H1", spec)
    out = tmp_path / "out"
    h1_run(h1_db, out)
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    assert tables["verdict"] != "樣本不足" and tables["judged_days"] == 20
    assert tables["excess"]["judged"]["population"]["days"] == 20
    assert tables["excess"]["extension"]["population"]["days"] == 15
    assert "延伸紀錄" in (out / "summary.md").read_text(encoding="utf-8")
    # More data later does not move the verdict: the first 20 days are the same.
    later = tmp_path / "later"
    h1_run(h1_db, later, cutoff=trading_days()[69])
    again = json.loads((later / "tables.json").read_text(encoding="utf-8"))
    assert again["excess"]["judged"] == tables["excess"]["judged"]
    assert again["verdict"] == tables["verdict"]


def test_h1_forward_before_any_new_session(h1_db, tmp_path, monkeypatch, capsys):
    """The frozen since (2026-11-14) is after the fixture: 0 days, no simulation."""

    no_window(monkeypatch)
    out = tmp_path / "out"
    code = tool.main(
        [
            "--db", str(h1_db),
            "--hypothesis", "H1",
            "--out", str(out),
            "--min-free-gb", "0",
        ]
    )  # fmt: skip
    assert code == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert (line["verdict"], line["days"], line["window"]) == ("樣本不足", 0, "forward")
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "樣本不足（累積 0／250 日）" in summary and "訊號日 2026-11-14 起" in summary
    equity = (out / "equity.csv").read_text(encoding="utf-8").splitlines()
    assert equity == ["date,taiex_close"]


def test_h1_historical_window_ends_at_its_until(h1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    days = trading_days()
    spec = {**tool.HYPOTHESES["H1"], "historical_until": days[50]}
    monkeypatch.setitem(tool.HYPOTHESES, "H1", spec)
    out = tmp_path / "out"
    line = tool.run_hypothesis(h1_db, "H1", tool.HISTORICAL, out)
    tables = json.loads((out / "tables.json").read_text(encoding="utf-8"))
    # The population needs 20 bars (the liquidity window): day 19 is the first.
    assert tables["start"] == days[19].isoformat()
    assert tables["cutoff"] == tables["last_session"] == days[50].isoformat()
    assert (tables["days"], tables["judged_days"], tables["min_days"]) == (31, 31, 60)
    assert line["verdict"] == "樣本不足"
    assert "歷史樣本外" in (out / "summary.md").read_text(encoding="utf-8")


def test_h1_historical_without_sessions_stops(h1_db, tmp_path, monkeypatch):
    no_window(monkeypatch)
    with pytest.raises(SystemExit):
        tool.run_hypothesis(h1_db, "H1", tool.HISTORICAL, tmp_path / "out")
