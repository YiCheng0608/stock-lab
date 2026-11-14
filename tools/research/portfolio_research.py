"""Buy the list's top N every day and hold K sessions: does it beat TAIEX? (#682)

The portfolio study of docs/spec/evidence.md 組合層級回測, fixed in the #682
decision (comment 6870690506) before any result was read.  Read only
(``mode=ro`` + ``query_only``); refuses the production database, Taipei
21:30–23:30 and less free memory than ``--min-free-gb`` as
``exit_research.py`` does.

The signals are a ``backtest_research.py`` run's actionable signals as
``exit_research.py`` wrote them (``trades.csv``: ``signal_id``, ``strategy``,
``instrument_id``, ``symbol``, ``signal_date``); the prices, chips and
corporate actions come from ``--db``, a ``copy_db.py`` copy.  Every row's
symbol must be the copy's for its instrument id, else the tool stops (exit 4).

Per signal date T the pool is ``candidate_score_v7``'s (the liquidity floor of
the population, one row per instrument, highest total then breakout), ranked
by v7's technical and chips components alone, renormalized (news and group
are dropped: their history is not known on T).  ``SCORE_LABEL`` says so in
every table.  The pool's entries without a technical score are left out, as
v7 does.

``simulate`` splits the capital into K accounts; account i trades only on the
sessions i, i+K, i+2K… of the window: it buys the day's names at the open
(+5 bps slippage and the 0.1425 % fee), equal shares of its cash (each at most
1/N of it; with fewer names the rest stays cash), and sells them at the close
of the K-th session counting the buy session as the first (−5 bps, the fee and
the 0.3 % tax).  A session locked at limit up (low ≥ limit up) is not bought
(that share stays cash to the account's next turn); a sale on a session
locked at limit down (high ≤ limit down), suspended or without a bar moves to
the open of the next session that is none of these.  Positions are valued at
their last close.  Prices are on one adjusted basis (dividends are returns).

Variants per K in ``HOLDS``: the top N for N in ``TOPS``; ``pool`` (every
entry of the ranked pool, equal shares; a reference line, not judged) and
``population`` (every member of ``evidence_lib.universe`` that day, the
benchmark).  TAIEX (price index, no dividends, no costs) is the other
benchmark.  Each top N is judged against each benchmark by ``judge`` on the
daily excess return per segment (``evidence_lib.SEGMENTS``, by date).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402

VERSION = 1
TOPS = (5, 10, 20)
HOLDS = (5, 10, 20)
SLIPPAGE = 5.0 / 10_000.0
FEE = 0.001425
TAX = 0.003
TRADING_DAYS = 252
MIN_DAYS = 60
MIN_T = 2.0
HISTORY_DAYS = 150  # calendar days of bars before the first signal date
SCORE_LABEL = (
    "candidate_score_v7 去掉新聞與族群（technical＋chips 重新正規化），不是當晚實際名單"
)
SCORED_COMPONENTS = ("technical", "chips")
POOL = "pool"
POPULATION = "population"
TAIEX = "taiex"
RAW_DIR_NAME = "raw"
VERDICTS = (
    "無法判定",
    "贏過基準",
    "輸給基準",
    "沒有差異",
    "驗證段反轉",
    "方向一致但不顯著",
)


def top_key(n: int) -> str:
    return f"top{n}"


# --- the engine -------------------------------------------------------------


@dataclass(frozen=True)
class Quote:
    """One instrument on one market session, prices on its adjusted basis."""

    open: float
    close: float
    tradable: bool  # a bar, not suspended, open and close known
    locked_up: bool = False
    locked_down: bool = False


@dataclass
class Position:
    account: int
    instrument_id: int
    units: float
    bought: int  # session index
    due: int  # session index of the K-th session
    cost: float  # cash paid
    mark: float
    sold: int | None = None
    proceeds: float | None = None
    how: str | None = None  # close, delayed, unsold


@dataclass
class Simulation:
    equity: list[float]  # at each session's close, from ``first``
    invested: list[float]  # share of equity in positions at the close
    bought: list[float]  # cash paid for buys that session
    counts: Counter = field(default_factory=Counter)
    positions: list[Position] = field(default_factory=list)


def buy_units(cash: float, open_price: float) -> float:
    return cash / (open_price * (1.0 + SLIPPAGE) * (1.0 + FEE))


def sale_proceeds(units: float, price: float) -> float:
    return units * price * (1.0 - SLIPPAGE) * (1.0 - FEE - TAX)


def simulate(
    picks: dict[int, list[int]],
    quote: Callable[[int, int], Quote | None],
    first: int,
    last: int,
    hold: int,
    top: int | None,
) -> Simulation:
    """Run the K accounts over sessions ``first``..``last`` (indexes).

    ``picks[s]`` are the names bought at the open of session ``s`` in order;
    ``top`` caps them and sets each share to 1/``top`` of the account's cash,
    ``None`` buys them all in equal shares.  The equity starts at 1.
    """

    cash = [1.0 / hold] * hold
    held: list[Position] = []
    result = Simulation([], [], [])
    for s in range(first, last + 1):
        # Delayed sales go first, at the open: their cash is back for the buys.
        for position in held:
            if position.due < s and position.sold is None:
                q = quote(position.instrument_id, s)
                if q is not None and q.tradable and not q.locked_down:
                    _sell(position, s, q.open, "delayed", cash)
        account = (s - first) % hold
        names = picks.get(s, [])
        if top is not None:
            names = names[:top]
        bought = 0.0
        if names:
            share = cash[account] / (top if top is not None else len(names))
            for instrument_id in names:
                q = quote(instrument_id, s)
                if q is None or not q.tradable:
                    result.counts["not_tradable"] += 1
                    continue
                if q.locked_up:
                    result.counts["limit_up"] += 1
                    continue
                position = Position(
                    account,
                    instrument_id,
                    buy_units(share, q.open),
                    s,
                    s + hold - 1,
                    share,
                    q.open,
                )
                cash[account] -= share
                bought += share
                held.append(position)
                result.positions.append(position)
                result.counts["bought"] += 1
        value = 0.0
        for position in held:
            if position.sold is not None:
                continue
            q = quote(position.instrument_id, s)
            if q is not None and q.tradable:
                position.mark = q.close
            if position.due == s:
                if q is not None and q.tradable and not q.locked_down:
                    _sell(position, s, q.close, "close", cash)
                    continue
                result.counts["limit_down" if q and q.locked_down else "sale_held"] += 1
            value += position.units * position.mark
        held = [position for position in held if position.sold is None]
        equity = sum(cash) + value
        result.equity.append(equity)
        result.invested.append(value / equity if equity > 0 else 0.0)
        result.bought.append(bought)
    for position in held:
        position.how = "unsold"
        result.counts["unsold"] += 1
    return result


def _sell(position: Position, s: int, price: float, how: str, cash: list[float]):
    position.sold = s
    position.proceeds = sale_proceeds(position.units, price)
    position.how = how
    cash[position.account] += position.proceeds


def daily_returns(equity: list[float]) -> list[float]:
    previous, out = 1.0, []
    for value in equity:
        out.append(value / previous - 1.0 if previous > 0 else 0.0)
        previous = value
    return out


# --- metrics and the verdict ------------------------------------------------


def max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    level = peak = 1.0
    worst = 0.0
    for value in returns:
        level *= 1.0 + value
        peak = max(peak, level)
        worst = min(worst, level / peak - 1.0)
    return worst


def curve_metrics(
    returns: list[float], invested: list[float], turnover: list[float]
) -> dict[str, Any]:
    """Annualized return, volatility, drawdown, invested share and turnover."""

    days = len(returns)
    if not days:
        return {"days": 0}
    growth = math.prod(1.0 + value for value in returns)
    return {
        "days": days,
        "total": growth - 1.0,
        "annual": growth ** (TRADING_DAYS / days) - 1.0 if growth > 0 else -1.0,
        "volatility": statistics.stdev(returns) * math.sqrt(TRADING_DAYS)
        if days > 1
        else None,
        "max_drawdown": max_drawdown(returns),
        "invested": statistics.fmean(invested),
        "turnover": sum(turnover) * TRADING_DAYS / days,
    }


def excess_metrics(differences: list[float]) -> dict[str, Any]:
    if not differences:
        return {"days": 0, "mean": None, "annual": None, "t": None}
    mean = statistics.fmean(differences)
    return {
        "days": len(differences),
        "mean": mean,
        "annual": mean * TRADING_DAYS,
        "t": lib.t_stat(differences),
    }


def _sign(value: float | None) -> int:
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def judge(exploration: dict[str, Any], validation: dict[str, Any]) -> str:
    """The #682 decision's table, first matching row from the top."""

    if exploration["days"] < MIN_DAYS or validation["days"] < MIN_DAYS:
        return "無法判定"
    t_exp, t_val = exploration["t"], validation["t"]
    m_exp, m_val = exploration["mean"], validation["mean"]
    if (
        m_exp > 0
        and m_val > 0
        and t_exp is not None
        and t_val is not None
        and t_exp >= MIN_T
        and t_val >= MIN_T
    ):
        return "贏過基準"
    if (
        m_exp < 0
        and m_val < 0
        and t_exp is not None
        and t_val is not None
        and t_exp <= -MIN_T
        and t_val <= -MIN_T
    ):
        return "輸給基準"
    if t_exp is None or abs(t_exp) < MIN_T:
        return "沒有差異"
    if _sign(m_val) != _sign(m_exp):
        return "驗證段反轉"
    return "方向一致但不顯著"


# --- the ranking (candidate_score_v7 without news and group) ---------------


@dataclass
class Market:
    """The panel plus what the limits and the chips inputs need."""

    panel: lib.Panel
    raw: dict[int, tuple[list[float], list[float], list[float], list[bool]]]
    kinds: dict[int, str]  # instrument_type
    levels: Any  # app.strategies.levels (tick_floor, tick_ceil)

    def limits(self, instrument_id: int, at: int) -> tuple[float, float] | None:
        """(limit down, limit up) of bar ``at`` on its raw basis; None if unknown.

        ``exit_research.price_limits`` around the previous bar's close put on
        bar ``at``'s raw basis (the adjusted close over the factor of ``at``).
        """

        item = self.panel.series[instrument_id]
        raw_close = self.raw[instrument_id][2]
        if not raw_close[at] or raw_close[at] <= 0 or not (item.close[at] > 0):
            return None
        scale = item.close[at] / raw_close[at]
        for back in range(at - 1, -1, -1):
            if item.close[back] > 0:
                reference = item.close[back] / scale
                break
        else:
            return None
        return lib._load("exit_research").price_limits(
            reference, self.kinds.get(instrument_id, "stock"), self.levels
        )

    def quote(self, instrument_id: int, s: int) -> Quote | None:
        item = self.panel.series.get(instrument_id)
        if item is None:
            return None
        at = item.position.get(self.panel.sessions[s])
        if at is None:
            return None
        o, c = item.open[at], item.close[at]
        if item.is_suspended(at) or not (o > 0 and c > 0):
            return Quote(o, c, False)
        bounds = self.limits(instrument_id, at)
        raw_low, raw_high, _, _ = self.raw[instrument_id]
        return Quote(
            o,
            c,
            True,
            locked_up=bounds is not None and raw_low[at] >= bounds[1] - 1e-9,
            locked_down=bounds is not None and raw_high[at] <= bounds[0] + 1e-9,
        )


def technical_inputs(item: lib.Series, at: int, strategy: str) -> dict[str, Any]:
    """v7's volume ratio and distance on the bars to T (adjusted to T's basis)."""

    out: dict[str, float | None] = {"volume_ratio": None, "distance": None}
    if at < 20:
        return out
    average = sum(item.volume[at - 20 : at]) / 20
    if average > 0:
        out["volume_ratio"] = item.volume[at] / average
    close = item.close[at]
    if not close > 0:
        return out
    if strategy.startswith("breakout"):
        highs = item.high[at - 20 : at]
        if all(value > 0 for value in highs):
            out["distance"] = close / max(highs) - 1
    else:
        closes = item.close[at - 19 : at + 1]
        if all(value > 0 for value in closes):
            out["distance"] = abs(close / (sum(closes) / 20) - 1)
    return out


CHIP_EMPTY = {
    "institutional_flow_5d": None,
    "institutional_flow_20d": None,
    "margin_change_5d": None,
}


def chip_inputs(item: lib.Series, flags: list[bool], at: int) -> dict[str, Any]:
    """``worker.candidates._chip_inputs`` on the panel: the last 20 bars to T
    whose ``is_suspended`` is not set, the latest of them T itself."""

    if flags[at]:
        return dict(CHIP_EMPTY)
    window: list[int] = []
    for back in range(at, -1, -1):
        if not flags[back]:
            window.append(back)
            if len(window) == 20:
                break
    window.reverse()
    chips = item.chips

    def row(p: int) -> bool:
        return any(not math.isnan(chips[name][p]) for name in lib.CHIP_FIELDS)

    out = dict(CHIP_EMPTY)
    if len(window) >= 6:
        last6 = window[-6:]
        if all(row(p) for p in last6):
            first = chips["margin_balance"][last6[0]]
            last = chips["margin_balance"][last6[-1]]
            if not math.isnan(first) and first != 0 and not math.isnan(last):
                out["margin_change_5d"] = (last - first) / abs(first)
    volumes = [item.volume[p] for p in window]
    if len(window) != 20 or any(volume <= 0 for volume in volumes):
        return out
    average = sum(volumes) / 20

    def flow(days: list[int]) -> float | None:
        total = 0.0
        for p in days:
            if not row(p):
                return None
            parts = [
                chips[name][p] for name in ("foreign_buy", "trust_buy", "dealer_buy")
            ]
            if any(math.isnan(part) for part in parts):
                return None
            total += sum(parts)
        return total

    five = flow(window[-5:])
    if five is not None:
        out["institutional_flow_5d"] = five / average
    twenty = flow(window)
    if twenty is not None:
        out["institutional_flow_20d"] = twenty / average
    return out


@dataclass
class Entry:
    signal_id: int
    instrument_id: int
    strategy: str
    exchange: str
    symbol: str
    technical: float | None = None
    chips: float | None = None
    total: float | None = None


def directed(
    percentile: Callable, value: float | None, peers: list[float | None], better: str
) -> float | None:
    if better == "lower":
        return percentile(
            None if value is None else -value,
            [None if peer is None else -peer for peer in peers],
        )
    return percentile(value, peers)


def rank_day(
    market: Market,
    day: date,
    signals: list[dict[str, Any]],
    config: dict[str, Any],
    percentile: Callable,
    weighted_mean: Callable,
    min_lots: float = lib.DEFAULT_MIN_LOTS,
) -> tuple[list[Entry], Counter]:
    """The day's ranked pool: v7's pool and order on technical and chips only."""

    panel = market.panel
    counts: Counter = Counter()
    pool: list[tuple[Entry, int]] = []
    for signal in signals:
        item = panel.series.get(signal["instrument_id"])
        at = None if item is None else item.position.get(day)
        if item is None or at is None or item.is_suspended(at):
            counts["no_bar"] += 1
            continue
        lots = lib.average_lots(item, at)
        if lots is None or lots < min_lots:
            counts["low_volume"] += 1
            continue
        exchange, symbol, _ = panel.symbols.get(item.instrument_id, ("", "", ""))
        pool.append(
            (
                Entry(
                    signal["signal_id"],
                    item.instrument_id,
                    signal["strategy"],
                    exchange,
                    symbol,
                ),
                at,
            )
        )
    weights = config["weights"]
    technical_spec = config["components"]["technical"]["items"]
    chip_spec = config["components"]["chips"]["items"]
    # technical: within the same strategy's pool of the day.
    raw_technical = {
        id(entry): technical_inputs(
            panel.series[entry.instrument_id], at, entry.strategy
        )
        for entry, at in pool
    }
    for strategy in {entry.strategy for entry, _ in pool}:
        peers = [entry for entry, _ in pool if entry.strategy == strategy]
        for entry in peers:
            values, item_weights = {}, {}
            for key in ("volume_ratio", "distance"):
                spec = technical_spec[key]
                better = (
                    spec["better"][strategy]
                    if isinstance(spec["better"], dict)
                    else spec["better"]
                )
                values[key] = directed(
                    percentile,
                    raw_technical[id(entry)][key],
                    [raw_technical[id(peer)][key] for peer in peers],
                    better,
                )
                item_weights[key] = float(spec["weight"])
            entry.technical, _ = weighted_mean(values, item_weights)
    # chips: across the day's stock／ipo market.
    market_chips = {
        instrument_id: chip_inputs(
            panel.series[instrument_id],
            market.raw[instrument_id][3],
            panel.series[instrument_id].position[day],
        )
        for instrument_id in panel.listed.get(day, ())
    }
    chip_peers = {key: [row[key] for row in market_chips.values()] for key in chip_spec}
    for entry, _ in pool:
        raw = market_chips.get(entry.instrument_id, CHIP_EMPTY)
        entry.chips, _ = weighted_mean(
            {
                key: directed(percentile, raw[key], chip_peers[key], spec["better"])
                for key, spec in chip_spec.items()
            },
            {key: float(spec["weight"]) for key, spec in chip_spec.items()},
        )
    eligible = []
    for entry, _ in pool:
        if entry.technical is None:
            counts["no_technical"] += 1
            continue
        entry.total, _ = weighted_mean(
            {"technical": entry.technical, "chips": entry.chips},
            {key: weights[key] for key in SCORED_COMPONENTS},
        )
        eligible.append(entry)
    order = config["pool"]["strategies"]
    best: dict[int, Entry] = {}
    for entry in sorted(
        eligible,
        key=lambda e: (
            -(e.total or 0.0),
            order.index(e.strategy) if e.strategy in order else 99,
        ),
    ):
        if entry.instrument_id in best:
            counts["same_instrument"] += 1
            continue
        best[entry.instrument_id] = entry
    ranked = sorted(
        best.values(),
        key=lambda e: (
            -(e.total or 0.0),
            -(e.technical or 0.0),
            e.chips is None,
            -(e.chips or 0.0),
            e.exchange,
            e.symbol,
        ),
    )
    counts["ranked"] += len(ranked)
    return ranked, counts


# --- reading ----------------------------------------------------------------


def read_signals(path: Path) -> list[dict[str, Any]]:
    seen: set[int] = set()
    out = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            signal_id = int(row["signal_id"])
            if signal_id in seen:
                continue
            seen.add(signal_id)
            out.append(
                {
                    "signal_id": signal_id,
                    "strategy": row["strategy"],
                    "instrument_id": int(row["instrument_id"]),
                    "symbol": row["symbol"],
                    "signal_date": date.fromisoformat(row["signal_date"]),
                }
            )
    return out


def load_market(db: Path, start: date, raw_dir: Path) -> Market:
    report = lib.research_report()
    con = lib.connect_read_only(db)
    try:
        instruments, listed = report.benchmark_universe(con, start)
        sessions = report.market_sessions(con, start)
        index_close = report.index_closes(con, start)
        factor_of = report.load_actions(db, instruments, start, raw_dir)
        session_index = {day: index for index, day in enumerate(sessions)}
        series = {
            instrument_id: lib._series(
                instrument_id, instrument, factor_of, session_index
            )
            for instrument_id, instrument in instruments.items()
        }
        raw = {}
        for instrument_id, instrument in instruments.items():
            kept = [bar for bar in instrument.bars if bar.trading_date in session_index]
            raw[instrument_id] = (
                [bar.low or 0.0 for bar in kept],
                [bar.high or 0.0 for bar in kept],
                [bar.close or 0.0 for bar in kept],
                [bool(bar.is_suspended) for bar in kept],
            )
        lib._load_chips(con, series, start)
        symbols, kinds = {}, {}
        for instrument_id, exchange, symbol, name, kind in con.execute(
            "select id, exchange, symbol, name, instrument_type from instruments"
        ):
            if instrument_id in series:
                symbols[instrument_id] = (exchange, symbol, name)
                kinds[instrument_id] = kind
    finally:
        con.close()
    from app.strategies import levels

    return Market(
        lib.Panel(sessions, series, dict(listed), index_close, symbols),
        raw,
        kinds,
        levels,
    )


def copy_facts(db: Path) -> dict[str, Any]:
    con = lib.connect_read_only(db)
    try:
        latest = con.execute("select max(trading_date) from market_bars").fetchone()[0]
        try:
            alembic = con.execute("select version_num from alembic_version").fetchone()[
                0
            ]
        except Exception:  # noqa: BLE001 - an isolated test database has none
            alembic = None
    finally:
        con.close()
    return {
        "latest": latest,
        "alembic": alembic,
        "mtime": datetime.fromtimestamp(db.stat().st_mtime, timezone.utc).isoformat(),
    }


# --- the study --------------------------------------------------------------


def study(
    market: Market,
    signals: list[dict[str, Any]],
    cutoff: date,
    config: dict[str, Any],
    percentile: Callable,
    weighted_mean: Callable,
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    panel = market.panel
    sessions = panel.sessions
    by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_date[signal["signal_date"]].append(signal)
    first_signal = min(by_date)
    position = {day: index for index, day in enumerate(sessions)}
    signal_days = [day for day in sessions if first_signal <= day < cutoff]
    if not signal_days or cutoff not in position:
        raise SystemExit(f"cutoff {cutoff} is not a market session after the signals")
    first = position[signal_days[0]] + 1
    last = position[cutoff]
    ranked: dict[int, list[int]] = {}
    population: dict[int, list[int]] = {}
    picks_rows: list[dict[str, Any]] = []
    counts: Counter = Counter()
    for number, day in enumerate(signal_days):
        s = position[day] + 1
        if by_date.get(day):
            entries, day_counts = rank_day(
                market, day, by_date[day], config, percentile, weighted_mean
            )
            counts.update(day_counts)
            ranked[s] = [entry.instrument_id for entry in entries]
            for rank, entry in enumerate(entries, 1):
                picks_rows.append(
                    {
                        "signal_date": day.isoformat(),
                        "rank": rank,
                        "exchange": entry.exchange,
                        "symbol": entry.symbol,
                        "strategy": entry.strategy,
                        "signal_id": entry.signal_id,
                        "total": entry.total,
                        "technical": entry.technical,
                        "chips": entry.chips,
                    }
                )
        population[s] = [
            item.instrument_id
            for item, _ in lib.universe(panel, day, lib.DEFAULT_MIN_LOTS)
        ]
        if number % 50 == 0:
            progress(f"ranked {day} ({number + 1}/{len(signal_days)})")
    dates = sessions[first : last + 1]
    taiex = []
    for s in range(first, last + 1):
        now, before = (
            panel.index_close.get(sessions[s]),
            panel.index_close.get(sessions[s - 1]),
        )
        taiex.append(now / before - 1.0 if now and before and before > 0 else None)
    variants: dict[str, dict[str, Any]] = {}
    simulations: dict[tuple[int, str], Simulation] = {}
    for hold in HOLDS:
        plans = [(top_key(n), ranked, n) for n in TOPS]
        plans += [(POOL, ranked, None), (POPULATION, population, None)]
        for key, picks, top in plans:
            started = time.monotonic()
            simulation = simulate(picks, market.quote, first, last, hold, top)
            simulations[(hold, key)] = simulation
            progress(f"K={hold} {key}: {time.monotonic() - started:.1f}s")
    for hold in HOLDS:
        returns = {
            key: daily_returns(simulations[(hold, key)].equity)
            for key in [top_key(n) for n in TOPS] + [POOL, POPULATION]
        }
        for key, series in returns.items():
            simulation = simulations[(hold, key)]
            previous = [1.0] + simulation.equity[:-1]
            turnover = [
                b / p if p > 0 else 0.0 for b, p in zip(simulation.bought, previous)
            ]
            segments = {}
            for name, rows in _segment_rows(dates).items():
                block = {
                    "curve": curve_metrics(
                        [series[i] for i in rows],
                        [simulation.invested[i] for i in rows],
                        [turnover[i] for i in rows],
                    ),
                    "trades": _trade_counts(simulation, rows, first),
                }
                for benchmark in (POPULATION, TAIEX, POOL):
                    if benchmark == key or (key == POPULATION and benchmark == POOL):
                        continue
                    other = taiex if benchmark == TAIEX else returns[benchmark]
                    block[f"excess_{benchmark}"] = excess_metrics(
                        [series[i] - other[i] for i in rows if other[i] is not None]
                    )
                segments[name] = block
            verdicts = {}
            if key.startswith("top"):
                for benchmark in (POPULATION, TAIEX):
                    verdicts[benchmark] = judge(
                        segments["exploration"][f"excess_{benchmark}"],
                        segments["validation"][f"excess_{benchmark}"],
                    )
            variants[f"K{hold}:{key}"] = {
                "hold": hold,
                "key": key,
                "segments": segments,
                "verdicts": verdicts,
                "counts": dict(simulation.counts),
            }
    taiex_segments = {
        name: curve_metrics(
            [taiex[i] for i in rows if taiex[i] is not None], [1.0], [0.0]
        )
        for name, rows in _segment_rows(dates).items()
    }
    return {
        "first_session": sessions[first].isoformat(),
        "last_session": sessions[last].isoformat(),
        "signal_days": len(signal_days),
        "days_with_signals": sum(1 for day in signal_days if by_date.get(day)),
        "pool_counts": dict(counts),
        "variants": variants,
        "taiex": taiex_segments,
        "taiex_missing_days": sum(1 for value in taiex if value is None),
        "comparisons": len(TOPS) * len(HOLDS) * 2,
        "_dates": dates,
        "_simulations": simulations,
        "_picks": picks_rows,
        "_first": first,
    }


def _segment_rows(dates: list[date]) -> dict[str, list[int]]:
    rows: dict[str, list[int]] = {"exploration": [], "validation": [], "all": []}
    for at, day in enumerate(dates):
        rows["all"].append(at)
        key = lib.segment_of(day)
        if key:
            rows[key].append(at)
    return rows


def _trade_counts(
    simulation: Simulation, rows: list[int], first: int
) -> dict[str, int]:
    wanted = {first + i for i in rows}
    counts: Counter = Counter()
    for position in simulation.positions:
        if position.bought in wanted:
            counts["bought"] += 1
            counts[position.how or "open"] += 1
    return dict(counts)


# --- output -----------------------------------------------------------------


def _pct(value: float | None, digits: int = 2) -> str:
    return lib.pct(value, digits)


def _t(value: float | None) -> str:
    return lib.num(value, 2)


NAMES = {POOL: "候選池全部（參考線）", POPULATION: "母體（基準）"}
SEGMENT_NAMES = {"exploration": "探索", "validation": "驗證", "all": "全部"}


def variant_name(key: str) -> str:
    return NAMES.get(key, f"前 {key[3:]} 名")


def markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# 組合層級回測（portfolio_research 第 {result['version']} 版）",
        "",
        f"- 排序：{SCORE_LABEL}",
        f"- 訊號：`{result['signals']['source']}`（sha256 `{result['signals']['sha256'][:16]}…`），"
        f"{result['signals']['rows']:,} 筆可行動訊號，訊號日 {result['signals']['first']}～{result['signals']['last']}",
        f"- 副本：最新交易日 {result['copy']['latest']}，alembic `{result['copy']['alembic']}`，"
        f"檔案時間 {result['copy']['mtime']}",
        f"- 期間：{result['first_session']}～{result['last_session']}（cutoff {result['cutoff']}），"
        f"{result['signal_days']} 個訊號日，其中 {result['days_with_signals']} 日有可行動訊號",
        "- 進出：T+1 開盤買（+5 bps 滑價、手續費 0.1425%），成交那根算第 1 根、第 K 根收盤賣"
        "（−5 bps、手續費、證交稅 0.3%）；K 份子帳戶輪替；不足 N 檔留現金",
        "- 漲停一字鎖不買（留現金）；跌停一字鎖、停牌或缺日線順延到下一根可賣的開盤；還原價計報酬",
        "- 加權指數是價格指數、不含股利、不扣成本：對它的超額偏高約一年股利率",
        "- 超額＝每日組合報酬 − 每日基準報酬；t＝日均 ÷（標準差 ÷ √日數）",
        f"- 判定：同時比較 {result['comparisons']} 組（{len(TOPS)} 個 N × {len(HOLDS)} 個 K × 2 個基準）；"
        "只有「贏過基準」算照名單做贏；候選池全部是參考線，不判定",
        f"- 候選池計數：{json.dumps(result['pool_counts'], ensure_ascii=False)}",
        f"- 耗時 {result.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(result.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{result['command']}`",
        "",
        "## 判定",
        "",
        f"排序：{SCORE_LABEL}",
        "",
        "| K | N | 對母體 | 對加權指數 |",
        "| ---: | ---: | --- | --- |",
    ]
    for hold in HOLDS:
        for n in TOPS:
            verdicts = result["variants"][f"K{hold}:{top_key(n)}"]["verdicts"]
            lines.append(
                f"| {hold} | {n} | {verdicts[POPULATION]} | {verdicts[TAIEX]} |"
            )
    lines += [
        "",
        "## 資金曲線",
        "",
        f"排序：{SCORE_LABEL}",
        "",
        "| K | 組合 | 段 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 | 買進筆數 |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for hold in HOLDS:
        for key in [top_key(n) for n in TOPS] + [POOL, POPULATION]:
            variant = result["variants"][f"K{hold}:{key}"]
            for segment in ("exploration", "validation", "all"):
                curve = variant["segments"][segment]["curve"]
                trades = variant["segments"][segment]["trades"]
                lines.append(
                    f"| {hold} | {variant_name(key)} | {SEGMENT_NAMES[segment]} | {curve['days']} "
                    f"| {_pct(curve.get('annual'))} | {_pct(curve.get('volatility'))} "
                    f"| {_pct(curve.get('max_drawdown'))} | {_pct(curve.get('invested'), 1)} "
                    f"| {lib.num(curve.get('turnover'), 1)} | {trades.get('bought', 0):,} |"
                )
    lines += [
        "",
        "加權指數（價格指數）：",
        "",
        "| 段 | 日數 | 年化報酬 | 年化波動 | 最大回撤 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for segment in ("exploration", "validation", "all"):
        curve = result["taiex"][segment]
        lines.append(
            f"| {SEGMENT_NAMES[segment]} | {curve['days']} | {_pct(curve.get('annual'))} "
            f"| {_pct(curve.get('volatility'))} | {_pct(curve.get('max_drawdown'))} |"
        )
    lines += [
        "",
        "## 超額報酬",
        "",
        f"排序：{SCORE_LABEL}。日均與年化（日均 × 252）；候選池全部那幾列只列出、不判定。",
        "",
        "| K | 組合 | 對 | 段 | 日數 | 日均 | 年化 | t |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    against = {POPULATION: "母體", TAIEX: "加權指數", POOL: "候選池全部"}
    for hold in HOLDS:
        for key in [top_key(n) for n in TOPS] + [POOL]:
            variant = result["variants"][f"K{hold}:{key}"]
            for benchmark in (POPULATION, TAIEX, POOL):
                if f"excess_{benchmark}" not in variant["segments"]["all"]:
                    continue
                for segment in ("exploration", "validation", "all"):
                    excess = variant["segments"][segment][f"excess_{benchmark}"]
                    lines.append(
                        f"| {hold} | {variant_name(key)} | {against[benchmark]} "
                        f"| {SEGMENT_NAMES[segment]} | {excess['days']} "
                        f"| {_pct(excess['mean'], 3)} | {_pct(excess['annual'])} | {_t(excess['t'])} |"
                    )
    lines += [
        "",
        "## 成交計數（全期）",
        "",
        "| K | 組合 | 買進 | 漲停買不到 | 不可交易 | 跌停順延 | 停牌／缺日線順延 | 期末未賣 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for hold in HOLDS:
        for key in [top_key(n) for n in TOPS] + [POOL, POPULATION]:
            counts = result["variants"][f"K{hold}:{key}"]["counts"]
            lines.append(
                f"| {hold} | {variant_name(key)} | {counts.get('bought', 0):,} "
                f"| {counts.get('limit_up', 0):,} | {counts.get('not_tradable', 0):,} "
                f"| {counts.get('limit_down', 0):,} | {counts.get('sale_held', 0):,} "
                f"| {counts.get('unsold', 0):,} |"
            )
    return "\n".join(lines) + "\n"


def write_outputs(out: Path, result: dict[str, Any], market: Market) -> None:
    dates = result.pop("_dates")
    simulations = result.pop("_simulations")
    picks = result.pop("_picks")
    result.pop("_first")
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result), encoding="utf-8")
    keys = sorted(simulations)
    with (out / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["date", *[f"K{hold}:{key}" for hold, key in keys], "taiex_close"]
        )
        for at, day in enumerate(dates):
            writer.writerow(
                [
                    day.isoformat(),
                    *[f"{simulations[k].equity[at]:.8f}" for k in keys],
                    market.panel.index_close.get(day),
                ]
            )
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "signal_date",
            "rank",
            "exchange",
            "symbol",
            "strategy",
            "signal_id",
            "total",
            "technical",
            "chips",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(picks)
    sessions = market.panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "variant",
                "account",
                "exchange",
                "symbol",
                "bought",
                "due",
                "sold",
                "how",
                "cost",
                "proceeds",
            ]
        )
        for hold, key in keys:
            if key == POPULATION:
                continue  # about a million rows; its counts are in tables.json
            for position in simulations[(hold, key)].positions:
                exchange, symbol, _ = market.panel.symbols.get(
                    position.instrument_id, ("", "", "")
                )
                writer.writerow(
                    [
                        f"K{hold}:{key}",
                        position.account,
                        exchange,
                        symbol,
                        sessions[position.bought].isoformat(),
                        sessions[position.due].isoformat()
                        if position.due < len(sessions)
                        else "",
                        sessions[position.sold].isoformat()
                        if position.sold is not None
                        else "",
                        position.how,
                        f"{position.cost:.10f}",
                        ""
                        if position.proceeds is None
                        else f"{position.proceeds:.10f}",
                    ]
                )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="portfolio_research.py", description=__doc__)
    parser.add_argument("--db", required=True, help="a copy_db.py copy of stock.db")
    parser.add_argument("--signals", required=True, help="exit_research.py trades.csv")
    parser.add_argument(
        "--signals-source",
        default=None,
        help="where the CSV came from, e.g. pr-assets/673@<sha>:run-20261114/trades.csv",
    )
    parser.add_argument(
        "--cutoff",
        type=date.fromisoformat,
        default=None,
        help="last session valued (default: the latest signal date)",
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problems = lib._load("exit_research").refusals(db, args.min_free_gb)
    if problems:
        print(json.dumps({"refused": problems}))
        return 2
    started = time.monotonic()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = Path(args.signals)
    signals = read_signals(path)
    if not signals:
        print(json.dumps({"refused": [f"{path} has no signals"]}))
        return 2
    first = min(signal["signal_date"] for signal in signals)
    cutoff = args.cutoff or max(signal["signal_date"] for signal in signals)
    market = load_market(db, first - timedelta(days=HISTORY_DAYS), out / RAW_DIR_NAME)
    mismatched = [
        signal
        for signal in signals
        if market.panel.symbols.get(signal["instrument_id"], (None, None))[1]
        != signal["symbol"]
    ]
    if mismatched:
        (out / "mismatches.json").write_text(
            json.dumps(mismatched, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {"stopped": "symbols differ from the copy", "rows": len(mismatched)}
            )
        )
        return 4
    from app.domain import CANDIDATE_SCORE, weighted_available_mean
    from worker.pipeline import _percentile

    result = study(
        market,
        signals,
        cutoff,
        CANDIDATE_SCORE,
        _percentile,
        weighted_available_mean,
        lambda text: print(text, file=sys.stderr, flush=True),
    )
    result = {
        "version": VERSION,
        "command": "python tools/research/portfolio_research.py " + " ".join(argv),
        "score": {"label": SCORE_LABEL, "config": CANDIDATE_SCORE["name"]},
        "signals": {
            "source": args.signals_source or str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(signals),
            "first": first.isoformat(),
            "last": max(signal["signal_date"] for signal in signals).isoformat(),
        },
        "cutoff": cutoff.isoformat(),
        "copy": copy_facts(db),
        "rule": {
            "tops": TOPS,
            "holds": HOLDS,
            "slippage_bps": SLIPPAGE * 10_000,
            "fee": FEE,
            "tax": TAX,
            "min_days": MIN_DAYS,
            "min_t": MIN_T,
        },
        **result,
    }
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    write_outputs(out, result, market)
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                "elapsed_seconds": round(result["elapsed_seconds"], 1),
                "verdicts": {
                    key: value["verdicts"]
                    for key, value in result["variants"].items()
                    if value["verdicts"]
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
