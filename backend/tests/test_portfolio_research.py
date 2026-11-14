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
