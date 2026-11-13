"""Which exit is best for the live rules' signals? (#673, docs/spec/evidence.md 出場規則研究)

Read only (``mode=ro`` + ``query_only``); refuses the production database as
``backtest_research.py`` does, Taipei 21:30–23:30 (the daily job) and less
free memory than ``--min-free-gb``.  Reads the copy a ``backtest_research.py``
run wrote (``--run-id``, status ``success``) and writes ``summary.md``,
``tables.json`` and ``trades.csv`` to ``--out``.

The sample is the run's actionable signals (status not ``observation``,
``data_incomplete`` or ``invalid_levels``) with their stored levels.  Every
exit shares one entry (``enter``), so the exits are compared signal by signal:

- the fill and the entries not taken are ``tracking_v2``'s (app.tracking): a
  breakout fills at max(open, trigger), a pullback in its zone, plus 5 bps; a
  fill session that opens or fills at or beyond the first target or the
  invalid price is not entered.  The window is the first ``WINDOW`` sessions
  after the signal date.  A session locked at limit up (its low at or above
  the limit up price) cannot be bought: the next session is tried.
- an exit (``exit_trade``) of a stop or a target fills at the open when the
  session opens beyond it, else at the level, less 5 bps; a session touching
  both is taken as the stop first (counted); a session locked at limit down
  (its high at or below the limit down price) cannot be sold, so the exit
  moves to the next unlocked session's open.  A suspended session or a missing
  market session after the fill makes the trade not comparable; too few bars
  is "not matured".  Returns are net of ``COST_BPS`` (the evidence tools'
  round trip), on the signal date's price basis (the product's corporate-action
  factors).

``RULES`` are fixed before any result was read (#673 decision 6846697843).
Before any of them is measured, ``E0`` under the product's own conventions
(``app.tracking.track_path``／``settle``, the run's 20 bars) must give every
stored T+20 settlement of the run back: a mismatch stops the tool (exit 4)
with the mismatches in ``mismatches.json``, nothing else measured.

Per strategy, rule and segment (``evidence_lib.SEGMENTS``, by signal date):
the trades, the mean and median net return, the share above zero, the mean
holding sessions, the largest drawdown of the cumulative return of equal
trades in exit order, and the t of the daily mean (the mean of each signal
date's trades; the days counted as ``days / OVERLAP``, the floor of
evidence.md).  Each alternative is also paired with ``E0``: per signal the
difference of the two net returns where both are comparable, averaged per
signal date, judged by ``judge`` (fixed here).  ``E0`` under the research
conventions less ``E0`` under the product's (at the same cost) measures what
the conventions change.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence_lib as lib  # noqa: E402

VERSION = 1
# The product's tracking window (app.tracking.TRACKING_WINDOW_SESSIONS; a test
# keeps the two equal).  A time exit of N sessions from a fill on session 20
# needs up to WINDOW + 19 bars.
WINDOW = 20
MAX_SESSIONS = 40
SLIPPAGE = 5.0 / 10_000.0
COST_BPS = lib.DEFAULT_COST_BPS
PRODUCT_COST_BPS = 30.0
OVERLAP = 20
MIN_DAYS = 60
MIN_T = 2.0
# The R of risk_levels: target_1 = entry + 1.6R, invalid = entry - R.
R_SPAN = 2.6
LIMIT = Fraction(1, 10)
NOT_ACTIONABLE = ("observation", "data_incomplete", "invalid_levels")
RAW_DIR_NAME = ".raw-unused"
EPS = 1e-9


# --- the rules ---------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    key: str
    kind: str  # target, trail, hold
    label: str
    target: str | None = None  # target_1, target_2
    k: float | None = None  # trailing distance in R
    hold: int | None = None  # sessions from the fill, the fill's included


RULES: tuple[Rule, ...] = (
    Rule("E0", "target", "固定目標一（現行）", target="target_1"),
    Rule("E1", "target", "固定目標二（3R）", target="target_2"),
    Rule("T1", "trail", "移動停利 1.0R", k=1.0),
    Rule("T2", "trail", "移動停利 1.5R", k=1.5),
    Rule("T3", "trail", "移動停利 2.0R", k=2.0),
    Rule("H5", "hold", "時間出場 5 根", hold=5),
    Rule("H10", "hold", "時間出場 10 根", hold=10),
    Rule("H20", "hold", "時間出場 20 根", hold=20),
)
BASELINE = "E0"
ALTERNATIVES = tuple(rule.key for rule in RULES if rule.key != BASELINE)

VERDICTS = {
    "cannot_tell": "無法判定",
    "better": "勝過現行",
    "worse": "不如現行",
    "no_difference": "沒有差異",
    "reversed": "驗證段反轉",
    "weak": "方向一致但不顯著",
}


@dataclass(frozen=True)
class Levels:
    entry_type: str
    breakout_price: float | None
    pullback_low: float | None
    pullback_high: float | None
    invalid_price: float | None
    target_1: float | None
    target_2: float | None

    @property
    def risk(self) -> float | None:
        if self.target_1 is None or self.invalid_price is None:
            return None
        return (self.target_1 - self.invalid_price) / R_SPAN


@dataclass(frozen=True)
class Bar:
    """One session after the signal date, prices on the signal date's basis."""

    trading_date: date
    open: float
    high: float
    low: float
    close: float
    # Not tradable: suspended, a flat zero-volume bar, a suspension interval
    # hiding a session, or a missing price.
    suspended: bool = False
    # A market session without a bar between this bar and the one before.
    missing_before: bool = False
    limit_up: float | None = None
    limit_down: float | None = None

    @property
    def locked_up(self) -> bool:
        return self.limit_up is not None and self.low >= self.limit_up - EPS

    @property
    def locked_down(self) -> bool:
        return self.limit_down is not None and self.high <= self.limit_down + EPS


@dataclass(frozen=True)
class Entry:
    session: int | None  # 1-based; None when not filled
    price: float | None  # with the buy slippage
    reason: str  # filled, not_triggered, gap_above_target, gap_below_invalid
    limit_blocked: int = 0  # sessions locked at limit up that would have filled


@dataclass(frozen=True)
class Exit:
    comparable: bool
    reason: str  # stop, trail, target, time, window_end, suspended, not_matured
    session: int | None = None
    trading_date: date | None = None
    price: float | None = None  # with the sell slippage
    net: float | None = None
    holding: int | None = None
    both_touched: bool = False
    gapped: bool = False  # filled at the open beyond the level
    limit_delayed: bool = False


def enter(levels: Levels, bars: list[Bar]) -> Entry:
    """tracking_v2's fill within the window, skipping sessions locked at limit up."""

    blocked = 0
    for at, bar in enumerate(bars[:WINDOW]):
        if bar.suspended:
            continue
        fill: float | None = None
        if levels.entry_type == "breakout" and levels.breakout_price is not None:
            trigger = levels.breakout_price
            if bar.high >= trigger:
                fill = max(bar.open, trigger)
        elif (
            levels.entry_type == "pullback"
            and levels.pullback_low is not None
            and levels.pullback_high is not None
        ):
            low, high = levels.pullback_low, levels.pullback_high
            if bar.low <= high and bar.high >= low:
                fill = (
                    bar.open
                    if low <= bar.open <= high
                    else min(max(bar.open, low), high)
                )
        if fill is None:
            continue
        if bar.locked_up:
            blocked += 1
            continue
        if levels.target_1 is not None and max(bar.open, fill) >= levels.target_1:
            return Entry(None, None, "gap_above_target", blocked)
        if (
            levels.invalid_price is not None
            and min(bar.open, fill) <= levels.invalid_price
        ):
            return Entry(None, None, "gap_below_invalid", blocked)
        return Entry(at + 1, fill * (1.0 + SLIPPAGE), "filled", blocked)
    return Entry(None, None, "not_triggered", blocked)


def _closed(
    entry: Entry,
    bars: list[Bar],
    at: int,
    price: float,
    reason: str,
    cost_bps: float,
    **flags,
) -> Exit:
    sold = price * (1.0 - SLIPPAGE)
    return Exit(
        comparable=True,
        reason=reason,
        session=at + 1,
        trading_date=bars[at].trading_date,
        price=sold,
        net=sold / entry.price - 1.0 - cost_bps / 10_000.0,
        holding=at + 2 - entry.session,
        **flags,
    )


def exit_trade(
    levels: Levels,
    bars: list[Bar],
    entry: Entry,
    rule: Rule,
    cost_bps: float = COST_BPS,
) -> Exit:
    """The exit of ``rule`` after ``entry``, under the research conventions."""

    if entry.session is None or entry.price is None:
        raise ValueError("no entry")
    first = entry.session - 1
    invalid = levels.invalid_price
    target = getattr(levels, rule.target) if rule.target else None
    risk = levels.risk
    last = first + rule.hold - 1 if rule.kind == "hold" else WINDOW - 1
    highest: float | None = None
    pending: str | None = None
    for at in range(first, len(bars)):
        bar = bars[at]
        if at > first and (bar.suspended or bar.missing_before):
            return Exit(False, "suspended", at + 1, bar.trading_date)
        locked = at > first and bar.locked_down
        if pending is not None:
            if locked:
                continue
            return _closed(
                entry, bars, at, bar.open, pending, cost_bps, limit_delayed=True
            )
        stop = invalid
        if rule.kind == "trail" and highest is not None and risk is not None:
            stop = max(invalid, highest - rule.k * risk)
        hit_stop = stop is not None and bar.low <= stop
        hit_target = target is not None and bar.high >= target
        if hit_stop:
            reason = "trail" if stop > invalid + EPS else "stop"
            if locked:
                pending = reason
                continue
            gapped = at > first and bar.open < stop
            price = bar.open if gapped else stop
            return _closed(
                entry,
                bars,
                at,
                price,
                reason,
                cost_bps,
                both_touched=hit_target,
                gapped=gapped,
            )
        if hit_target:
            gapped = at > first and bar.open > target
            price = bar.open if gapped else target
            return _closed(entry, bars, at, price, "target", cost_bps, gapped=gapped)
        if at == last:
            reason = "time" if rule.kind == "hold" else "window_end"
            if locked:
                pending = reason
                continue
            return _closed(entry, bars, at, bar.close, reason, cost_bps)
        highest = bar.close if highest is None else max(highest, bar.close)
    return Exit(False, "not_matured")


# --- the statistics ------------------------------------------------------------


def max_drawdown(trades: list[tuple[date, int, float]]) -> float | None:
    """Largest fall of the running sum of returns, trades in (exit date, id) order."""

    if not trades:
        return None
    total = peak = worst = 0.0
    for _day, _id, value in sorted(trades):
        total += value
        peak = max(peak, total)
        worst = max(worst, peak - total)
    return worst


def daily_means(rows: list[tuple[date, float]]) -> list[float]:
    by_day: dict[date, list[float]] = defaultdict(list)
    for day, value in rows:
        by_day[day].append(value)
    return [statistics.fmean(by_day[day]) for day in sorted(by_day)]


def rule_table(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics of one rule over the comparable trades given."""

    if not trades:
        return {"n": 0, "days": 0}
    values = [trade["net"] for trade in trades]
    days = daily_means([(trade["signal_date"], trade["net"]) for trade in trades])
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "win": sum(1 for value in values if value > 0) / len(values),
        "holding": statistics.fmean(trade["holding"] for trade in trades),
        "max_drawdown": max_drawdown(
            [(trade["exit_date"], trade["signal_id"], trade["net"]) for trade in trades]
        ),
        "days": len(days),
        "daily_mean": statistics.fmean(days),
        "t": lib.t_stat(days, OVERLAP),
    }


def paired_table(pairs: list[tuple[date, float]]) -> dict[str, Any]:
    if not pairs:
        return {"n": 0, "days": 0, "mean": None, "t": None}
    days = daily_means(pairs)
    return {
        "n": len(pairs),
        "days": len(days),
        "mean": statistics.fmean(days),
        "t": lib.t_stat(days, OVERLAP),
    }


def _sign(value: float | None) -> int:
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def judge(exploration: dict[str, Any], validation: dict[str, Any]) -> str:
    """The verdict of one alternative against E0, first matching row first."""

    if exploration.get("days", 0) < MIN_DAYS or validation.get("days", 0) < MIN_DAYS:
        return "cannot_tell"
    e_mean, v_mean = exploration.get("mean"), validation.get("mean")
    e_t, v_t = exploration.get("t"), validation.get("t")
    if (
        _sign(e_mean) > 0
        and _sign(v_mean) > 0
        and e_t is not None
        and v_t is not None
        and e_t >= MIN_T
        and v_t >= MIN_T
    ):
        return "better"
    if (
        _sign(e_mean) < 0
        and _sign(v_mean) < 0
        and e_t is not None
        and v_t is not None
        and e_t <= -MIN_T
        and v_t <= -MIN_T
    ):
        return "worse"
    if e_t is None or abs(e_t) < MIN_T:
        return "no_difference"
    if _sign(v_mean) != _sign(e_mean):
        return "reversed"
    return "weak"


# --- reading the copy ------------------------------------------------------------


@dataclass
class Signal:
    id: int
    strategy: str
    instrument_id: int
    signal_date: date
    status: str
    levels: Levels


@dataclass
class Copy:
    run: dict[str, Any]
    cutoff: date
    signals: list[Signal]
    settlements: dict[int, tuple[bool, float | None, str]]  # T+20 of each signal
    instrument_types: dict[int, str]
    symbols: dict[int, tuple[str, str]]
    bars: dict[
        int, list[tuple]
    ]  # instrument -> (date, o, h, l, c, adj, vol, suspended)
    events: dict[int, list[tuple[date, dict]]]
    sessions: list[date]
    latest: date | None
    alembic: str | None


def run_cutoff(request_key: str) -> date:
    """The end date of ``technical-backtest:<version>:<start>:<end>[:research:...]``."""

    parts = request_key.split(":")
    if len(parts) < 4 or parts[0] != "technical-backtest":
        raise ValueError(f"not a backtest request key: {request_key}")
    return date.fromisoformat(parts[3])


def load_copy(db: Path, run_id: int) -> Copy:
    con = lib.connect_read_only(db)
    try:
        row = con.execute(
            "select id, status, request_key, started_at, finished_at from ingestion_runs "
            "where id = ? and run_type = 'backtest'",
            (run_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"run {run_id} is not a backtest run")
        run = dict(
            zip(("id", "status", "request_key", "started_at", "finished_at"), row)
        )
        cutoff = run_cutoff(run["request_key"])
        prefix = f"backtest-{run_id}-%"
        marks = ",".join("?" * len(NOT_ACTIONABLE))
        signals = [
            Signal(
                id=sid,
                strategy=name,
                instrument_id=instrument_id,
                signal_date=date.fromisoformat(day),
                status=status,
                levels=Levels(entry_type, breakout, low, high, invalid, t1, t2),
            )
            for (
                sid,
                name,
                instrument_id,
                day,
                status,
                entry_type,
                breakout,
                low,
                high,
                invalid,
                t1,
                t2,
            ) in con.execute(
                "select s.id, sv.name, s.instrument_id, s.signal_date, s.status, "
                "s.entry_type, s.breakout_price, s.pullback_low, s.pullback_high, "
                "s.invalid_price, s.target_1, s.target_2 "
                "from signals s join strategy_versions sv on sv.id = s.strategy_version_id "
                f"where s.signal_key like ? and s.status not in ({marks}) order by s.id",
                (prefix, *NOT_ACTIONABLE),
            )
        ]
        settlements = {
            sid: (bool(comparable), value, status)
            for sid, comparable, value, status in con.execute(
                "select st.signal_id, st.comparable, st.return_or_risk, st.final_status "
                "from signal_settlements st cross join signals s on s.id = st.signal_id "
                "where s.signal_key like ? and st.horizon = 20",
                (prefix,),
            )
        }
        wanted = sorted({signal.instrument_id for signal in signals})
        instrument_types, symbols = {}, {}
        for instrument_id, kind, exchange, symbol in con.execute(
            "select id, instrument_type, exchange, symbol from instruments"
        ):
            instrument_types[instrument_id] = kind
            symbols[instrument_id] = (exchange, symbol)
        first = min((signal.signal_date for signal in signals), default=cutoff)
        bars: dict[int, list[tuple]] = defaultdict(list)
        for chunk in range(0, len(wanted), 500):
            ids = wanted[chunk : chunk + 500]
            for instrument_id, day, *rest in con.execute(
                "select instrument_id, trading_date, open, high, low, close, adj_close, "
                "volume, is_suspended from market_bars "
                f"where instrument_id in ({','.join('?' * len(ids))}) "
                "and trading_date >= ? and trading_date <= ? "
                "order by instrument_id, trading_date",
                (*ids, first.isoformat(), cutoff.isoformat()),
            ):
                bars[instrument_id].append((date.fromisoformat(day), *rest))
        events: dict[int, list[tuple[date, dict]]] = defaultdict(list)
        for instrument_id, day, details in con.execute(
            "select instrument_id, event_date, details_json from events "
            "where event_type = 'suspension' and instrument_id is not null"
        ):
            try:
                parsed = json.loads(details) if details else {}
            except ValueError:
                parsed = {}
            events[instrument_id].append((date.fromisoformat(day[:10]), parsed or {}))
        sessions = lib.research_report().market_sessions(con, first)
        latest = con.execute("select max(trading_date) from market_bars").fetchone()[0]
        try:
            alembic = con.execute("select version_num from alembic_version").fetchone()[
                0
            ]
        except Exception:  # noqa: BLE001 - an isolated test database has none
            alembic = None
    finally:
        con.close()
    return Copy(
        run,
        cutoff,
        signals,
        settlements,
        instrument_types,
        symbols,
        dict(bars),
        dict(events),
        sessions,
        date.fromisoformat(latest) if latest else None,
        alembic,
    )


def suspension_gap(
    events: list[tuple[date, dict]], previous: date, current: date
) -> bool:
    """worker.pipeline._suspension_gap_between on preloaded events."""

    if current <= previous:
        return False
    for start, details in events:
        if start > current:
            continue
        end_text = details.get("resumed_date") or details.get("interval_end")
        try:
            end = date.fromisoformat(str(end_text)[:10]) if end_text else current
        except ValueError:
            end = current
        if start > previous and start <= current and end >= start:
            return True
        if start <= previous < end and end >= current:
            return True
    return False


def price_limits(reference: float | None, instrument_type: str, levels_module):
    """(limit down, limit up) around ``reference`` on its own basis; None for an ETF."""

    if instrument_type == "etf" or not reference or reference <= 0:
        return None
    base = Fraction(str(round(reference, 6)))
    return (
        levels_module.tick_ceil(float(base * (1 - LIMIT)), instrument_type),
        levels_module.tick_floor(float(base * (1 + LIMIT)), instrument_type),
    )


@dataclass
class Prepared:
    bars: list[Bar]  # research bars, up to MAX_SESSIONS
    track_bars: list[Any]  # app.tracking.TrackBar, the product's first WINDOW


def prepare(copy: Copy, signal: Signal, factor_of, actions, modules) -> Prepared:
    """The sessions after the signal date, as the research and the product see them."""

    tracking, levels_module = modules
    rows = copy.bars.get(signal.instrument_id, [])
    dates = [row[0] for row in rows]
    at = bisect.bisect_right(dates, signal.signal_date)
    signal_row = rows[at - 1] if at and dates[at - 1] == signal.signal_date else None
    after = rows[at : at + MAX_SESSIONS]
    own_actions = [
        action
        for action in actions.get(signal.instrument_id, [])
        if action.action_date > signal.signal_date
    ]
    events = copy.events.get(signal.instrument_id, [])
    kind = copy.instrument_types.get(signal.instrument_id, "stock")
    research: list[Bar] = []
    product: list[Any] = []
    previous_date = signal.signal_date
    previous_close = signal_row[4] if signal_row else None  # raw, factor 1
    previous_factor = 1.0
    for day, o, h, low, c, adj, volume, suspended in after:
        applied = [action for action in own_actions if action.action_date <= day]
        factor = factor_of(applied, signal.signal_date, None) if applied else 1.0
        gap = suspension_gap(events, previous_date, day)
        if len(product) < WINDOW:
            product.append(
                tracking.TrackBar(
                    trading_date=day,
                    open=o,
                    high=h,
                    low=low,
                    close=c,
                    adj_close=adj,
                    volume=volume,
                    is_suspended=bool(suspended),
                    source=None,
                    data_time=None,
                    factor=factor,
                    action_applied=bool(applied),
                    suspension_gap=gap,
                )
            )
        missing_price = any(value is None or value <= 0 for value in (o, h, low, c))
        flat = volume == 0 and o == h == low == c
        limits = None
        if previous_close and not missing_price:
            limits = price_limits(
                previous_close * factor / previous_factor, kind, levels_module
            )
        start = bisect.bisect_right(copy.sessions, previous_date)
        stop = bisect.bisect_left(copy.sessions, day)
        research.append(
            Bar(
                trading_date=day,
                open=(o or 0.0) / factor,
                high=(h or 0.0) / factor,
                low=(low or 0.0) / factor,
                close=(c or 0.0) / factor,
                suspended=bool(suspended or flat or gap or missing_price),
                missing_before=stop > start,
                limit_up=limits[1] / factor if limits else None,
                limit_down=limits[0] / factor if limits else None,
            )
        )
        previous_date = day
        if c and c > 0:
            previous_close, previous_factor = c, factor
    return Prepared(research, product)


def product_settlement(
    prepared: Prepared, signal: Signal, tracking
) -> tuple[bool, float | None, str]:
    """E0 under the product's conventions: the run's own T+20 settlement."""

    if not prepared.track_bars:
        return False, None, "incomparable"
    levels = signal.levels
    path = tracking.track_path(
        tracking.TrackLevels(
            entry_type=levels.entry_type,
            breakout_price=levels.breakout_price,
            pullback_low=levels.pullback_low,
            pullback_high=levels.pullback_high,
            invalid_price=levels.invalid_price,
            target_1=levels.target_1,
        ),
        prepared.track_bars,
        rules=tracking.TRACKING_RULES,
    )
    result = tracking.settle(path, WINDOW)
    return bool(result["comparable"]), result["return_or_risk"], result["final_status"]


def mismatch(stored, computed) -> bool:
    if stored is None:
        return True
    s_comparable, s_value, s_status = stored
    c_comparable, c_value, c_status = computed
    if s_comparable != c_comparable or s_status != c_status:
        return True
    if s_comparable and (
        s_value is None or c_value is None or abs(s_value - c_value) > EPS
    ):
        return True
    return False


# --- the run ---------------------------------------------------------------------


def _modules(db: Path, copy: Copy, raw_dir: Path):
    report = lib.research_report()
    instruments = {instrument_id: report.Instrument() for instrument_id in copy.bars}
    first = min((signal.signal_date for signal in copy.signals), default=copy.cutoff)
    factor_of = report.load_actions(db, instruments, first, raw_dir)
    from app import tracking
    from app.strategies import levels as levels_module

    actions = {key: value.actions for key, value in instruments.items()}
    return factor_of, actions, (tracking, levels_module)


def measure(
    copy: Copy, factor_of, actions, modules, progress=lambda text: None
) -> dict[str, Any]:
    tracking, _levels = modules
    mismatches: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    prepared_all: list[tuple[Signal, Prepared, tuple]] = []
    for count, signal in enumerate(copy.signals, start=1):
        prepared = prepare(copy, signal, factor_of, actions, modules)
        computed = product_settlement(prepared, signal, tracking)
        stored = copy.settlements.get(signal.id)
        if mismatch(stored, computed):
            mismatches.append(
                {
                    "signal_id": signal.id,
                    "strategy": signal.strategy,
                    "signal_date": signal.signal_date.isoformat(),
                    "stored": stored,
                    "computed": computed,
                }
            )
        prepared_all.append((signal, prepared, computed))
        if count % 2000 == 0:
            progress(f"{count}/{len(copy.signals)} signals checked")
    result: dict[str, Any] = {
        "signals": len(copy.signals),
        "reproduction": {"checked": len(copy.signals), "mismatches": len(mismatches)},
    }
    if mismatches:
        result["mismatches"] = mismatches
        return result
    entries: Counter = Counter()
    for signal, prepared, computed in prepared_all:
        entry = enter(signal.levels, prepared.bars)
        entries[(signal.strategy, entry.reason)] += 1
        trade: dict[str, Any] = {
            "signal_id": signal.id,
            "strategy": signal.strategy,
            "instrument_id": signal.instrument_id,
            "symbol": copy.symbols.get(signal.instrument_id, ("", ""))[1],
            "signal_date": signal.signal_date,
            "segment": lib.segment_of(signal.signal_date),
            "entry_reason": entry.reason,
            "entry_session": entry.session,
            "entry_price": entry.price,
            "limit_blocked": entry.limit_blocked,
            "product_comparable": computed[0],
            "product_net": (
                computed[1] + PRODUCT_COST_BPS / 10_000.0 - COST_BPS / 10_000.0
                if computed[0] and computed[1] is not None
                else None
            ),
            "product_status": computed[2],
            "exits": {},
        }
        if entry.session is not None:
            for rule in RULES:
                trade["exits"][rule.key] = exit_trade(
                    signal.levels, prepared.bars, entry, rule
                )
        trades.append(trade)
    result["entries"] = {
        f"{name}:{reason}": n for (name, reason), n in sorted(entries.items())
    }
    result["trades"] = trades
    return result


def tables(trades: list[dict[str, Any]]) -> dict[str, Any]:
    strategies = sorted({trade["strategy"] for trade in trades})
    groups = ("exploration", "validation", "all")
    out: dict[str, Any] = {}
    for strategy in strategies:
        own = [trade for trade in trades if trade["strategy"] == strategy]
        filled = [trade for trade in own if trade["entry_session"] is not None]
        part: dict[str, Any] = {
            "signals": len(own),
            "filled": len(filled),
            "rules": {},
            "paired": {},
            "conventions": {},
        }
        for rule in RULES:
            per = {}
            reasons = {}
            for group in groups:
                chosen = [
                    _flat(trade, rule.key)
                    for trade in filled
                    if (group == "all" or trade["segment"] == group)
                    and trade["exits"][rule.key].comparable
                ]
                per[group] = rule_table(chosen)
                reasons[group] = dict(
                    Counter(
                        trade["exits"][rule.key].reason
                        for trade in filled
                        if group == "all" or trade["segment"] == group
                    )
                )
            per["reasons"] = reasons
            per["both_touched"] = sum(
                1 for trade in filled if trade["exits"][rule.key].both_touched
            )
            per["gapped"] = sum(
                1 for trade in filled if trade["exits"][rule.key].gapped
            )
            per["limit_delayed"] = sum(
                1 for trade in filled if trade["exits"][rule.key].limit_delayed
            )
            part["rules"][rule.key] = per
        for key in ALTERNATIVES:
            per = {}
            for group in groups:
                pairs = [
                    (
                        trade["signal_date"],
                        trade["exits"][key].net - trade["exits"][BASELINE].net,
                    )
                    for trade in filled
                    if (group == "all" or trade["segment"] == group)
                    and trade["exits"][key].comparable
                    and trade["exits"][BASELINE].comparable
                ]
                per[group] = paired_table(pairs)
            per["verdict"] = judge(per["exploration"], per["validation"])
            part["paired"][key] = per
        for group in groups:
            chosen = [
                trade for trade in own if group == "all" or trade["segment"] == group
            ]
            pairs = [
                (
                    trade["signal_date"],
                    trade["exits"][BASELINE].net - trade["product_net"],
                )
                for trade in chosen
                if trade["entry_session"] is not None
                and trade["exits"][BASELINE].comparable
                and trade["product_net"] is not None
            ]
            table = paired_table(pairs)
            table["research_only"] = sum(
                1
                for trade in chosen
                if trade["entry_session"] is not None
                and trade["exits"][BASELINE].comparable
                and trade["product_net"] is None
            )
            table["product_only"] = sum(
                1
                for trade in chosen
                if trade["product_net"] is not None
                and not (
                    trade["entry_session"] is not None
                    and trade["exits"][BASELINE].comparable
                )
            )
            table["both_touched"] = sum(
                1
                for trade in chosen
                if trade["entry_session"] is not None
                and trade["exits"][BASELINE].both_touched
            )
            table["gapped_stop"] = sum(
                1
                for trade in chosen
                if trade["entry_session"] is not None
                and trade["exits"][BASELINE].gapped
                and trade["exits"][BASELINE].reason == "stop"
            )
            table["gapped_target"] = sum(
                1
                for trade in chosen
                if trade["entry_session"] is not None
                and trade["exits"][BASELINE].gapped
                and trade["exits"][BASELINE].reason == "target"
            )
            table["limit_blocked_entries"] = sum(
                1 for trade in chosen if trade["limit_blocked"]
            )
            table["limit_delayed_exits"] = sum(
                1
                for trade in chosen
                if trade["entry_session"] is not None
                and trade["exits"][BASELINE].limit_delayed
            )
            part["conventions"][group] = table
        out[strategy] = part
    return out


def _flat(trade: dict[str, Any], key: str) -> dict[str, Any]:
    exit_ = trade["exits"][key]
    return {
        "signal_id": trade["signal_id"],
        "signal_date": trade["signal_date"],
        "exit_date": exit_.trading_date,
        "net": exit_.net,
        "holding": exit_.holding,
    }


# --- the report ------------------------------------------------------------------


def _pct(value):
    return lib.pct(value)


def _t(value):
    return lib.num(value, 2)


def markdown(result: dict[str, Any]) -> str:
    labels = {rule.key: rule.label for rule in RULES}
    lines = [
        f"# 出場規則研究（exit_research 第 {result['version']} 版）",
        "",
        f"- run：`{result['run']['id']}`，request key `{result['run']['request_key']}`，"
        f"cutoff {result['cutoff']}",
        f"- 副本：最新交易日 {result['copy']['latest']}，alembic `{result['copy']['alembic']}`，"
        f"檔案時間 {result['copy']['mtime']}",
        f"- 樣本：run 的可行動訊號 {result['signals']:,} 筆；"
        f"重現檢查（E0 產品慣例對 run 的 T+20 settlement）不一致 "
        f"{result['reproduction']['mismatches']} 筆",
        f"- 成本：來回 {COST_BPS:g} bps，買賣各 5 bps 滑價；報酬在訊號日的價格基準",
        f"- t 值：同一訊號日先平均，天數以「日數 ÷ {OVERLAP}」計（保守下限）",
        f"- 判定（寫死在 `exit_research.judge`）：兩段配對差日均都 > 0 且 t ≥ {MIN_T:g} 才算"
        f"「勝過現行」；任一段不足 {MIN_DAYS} 個訊號日為「無法判定」",
        f"- 同時比較了 {result['comparisons']} 組（{len(ALTERNATIVES)} 條替代規則 × "
        f"{len(result['strategies'])} 條策略）：其中幾組碰巧通過並不意外",
        f"- 耗時 {result['elapsed_seconds']:.0f} 秒，峰值記憶體 {lib.num(result.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{result['command']}`",
        "",
    ]
    for strategy, part in result["strategies"].items():
        lines += [
            f"## {strategy}",
            "",
            f"可行動訊號 {part['signals']:,} 筆，成交 {part['filled']:,} 筆。",
            "",
            "### 各出場規則",
            "",
            "| 規則 | 段 | 筆數 | 平均 | 中位 | 勝率 | 平均持有 | 最大回撤 | 訊號日 | 日均 | t |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for rule in RULES:
            for group, label in (
                ("exploration", "探索"),
                ("validation", "驗證"),
                ("all", "全部"),
            ):
                row = part["rules"][rule.key][group]
                if not row.get("n"):
                    lines.append(
                        f"| {rule.key} {labels[rule.key]} | {label} | 0 | — | — | — | — | — | 0 | — | — |"
                    )
                    continue
                lines.append(
                    f"| {rule.key} {labels[rule.key]} | {label} | {row['n']:,} | {_pct(row['mean'])} | "
                    f"{_pct(row['median'])} | {lib.pct(row['win'], 1)} | {row['holding']:.1f} | "
                    f"{_pct(row['max_drawdown'])} | {row['days']} | {_pct(row['daily_mean'])} | {_t(row['t'])} |"
                )
        lines += [
            "",
            "### 對現行（E0）的配對差與判定",
            "",
            "| 規則 | 探索段日數 | 差值日均 | t | 驗證段日數 | 差值日均 | t | 判定 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for key in ALTERNATIVES:
            row = part["paired"][key]
            e, v = row["exploration"], row["validation"]
            lines.append(
                f"| {key} {labels[key]} | {e['days']} | {_pct(e['mean'])} | {_t(e['t'])} | "
                f"{v['days']} | {_pct(v['mean'])} | {_t(v['t'])} | {VERDICTS[row['verdict']]} |"
            )
        lines += [
            "",
            "### E0 研究慣例 − E0 產品慣例（同為 58.5 bps）",
            "",
            "| 段 | 配對筆數 | 訊號日 | 差值日均 | t | 只有研究可比較 | 只有產品可比較 | 同根都碰到 | 跳空停損 | 跳空目標 | 漲停順延進場 | 跌停順延出場 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for group, label in (
            ("exploration", "探索"),
            ("validation", "驗證"),
            ("all", "全部"),
        ):
            row = part["conventions"][group]
            lines.append(
                f"| {label} | {row['n']:,} | {row['days']} | {_pct(row['mean'])} | {_t(row['t'])} | "
                f"{row['research_only']} | {row['product_only']} | {row['both_touched']} | "
                f"{row['gapped_stop']} | {row['gapped_target']} | {row['limit_blocked_entries']} | "
                f"{row['limit_delayed_exits']} |"
            )
        lines += ["", "### 出場原因（全部）", ""]
        for rule in RULES:
            reasons = part["rules"][rule.key]["reasons"]["all"]
            text = "、".join(f"{reason} {n:,}" for reason, n in sorted(reasons.items()))
            lines.append(f"- {rule.key}：{text}")
        lines.append("")
    lines += [
        "## 樣本限制",
        "",
        "- 只有 2024-09-30 起的一段歷史，驗證段只有一段；結論可能只適用這段市況。",
        "- 日線只知道開高低收，不知道盤中先後：同一根停損與目標都碰到時保守當成停損先。",
        "- 每筆等額、不限同時持有檔數，不是組合層級的資金曲線（階段二第 2 項另開單）。",
        "- 漲跌停只看一字鎖住的日子；成交量限制與流動性不在內。",
        "",
    ]
    return "\n".join(lines)


def _csv_rows(trades: list[dict[str, Any]]):
    header = [
        "signal_id",
        "strategy",
        "instrument_id",
        "symbol",
        "signal_date",
        "segment",
        "entry_reason",
        "entry_session",
        "entry_price",
        "limit_blocked",
        "product_comparable",
        "product_status",
        "product_net",
    ]
    for rule in RULES:
        header += [
            f"{rule.key}_reason",
            f"{rule.key}_net",
            f"{rule.key}_holding",
            f"{rule.key}_exit_date",
        ]
    yield header
    for trade in trades:
        row = [trade[name] for name in header[:13]]
        for rule in RULES:
            exit_ = trade["exits"].get(rule.key)
            row += (
                [exit_.reason, exit_.net, exit_.holding, exit_.trading_date]
                if exit_ is not None
                else ["", "", "", ""]
            )
        yield row


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exit_research.py", description=__doc__)
    parser.add_argument("--db", required=True, help="the copy the research run wrote")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    return parser


def refusals(db: Path, min_free_gb: float, now: datetime | None = None) -> list[str]:
    research = lib._load("backtest_research")
    problems = []
    problem = lib.production_problem(db, dict(os.environ))
    if problem:
        problems.append(problem)
    elif not db.is_file():
        problems.append(f"{db} does not exist")
    window = research.daily_window_problem(now or datetime.now(timezone.utc))
    if window:
        problems.append(window)
    free = research.free_memory_gb()
    if free is not None and free < min_free_gb:
        problems.append(
            f"free memory {free:.1f} GB is under --min-free-gb {min_free_gb:g}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = _parser().parse_args(argv)
    db = Path(args.db)
    problems = refusals(db, args.min_free_gb)
    if problems:
        print(json.dumps({"refused": problems}))
        return 2
    started = time.monotonic()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    copy = load_copy(db, args.run_id)
    if copy.run["status"] != "success":
        print(
            json.dumps(
                {"refused": [f"run {args.run_id} is {copy.run['status']}, not success"]}
            )
        )
        return 2
    factor_of, actions, modules = _modules(db, copy, out / RAW_DIR_NAME)
    measured = measure(
        copy,
        factor_of,
        actions,
        modules,
        lambda text: print(text, file=sys.stderr, flush=True),
    )
    command = "python tools/research/exit_research.py " + " ".join(argv)
    result: dict[str, Any] = {
        "version": VERSION,
        "command": command,
        "run": copy.run,
        "cutoff": copy.cutoff.isoformat(),
        "copy": {
            "latest": copy.latest.isoformat() if copy.latest else None,
            "alembic": copy.alembic,
            "mtime": datetime.fromtimestamp(
                db.stat().st_mtime, timezone.utc
            ).isoformat(),
        },
        "signals": measured["signals"],
        "reproduction": measured["reproduction"],
        "rules": [rule.__dict__ for rule in RULES],
        "rule": {
            "min_days": MIN_DAYS,
            "min_t": MIN_T,
            "overlap": OVERLAP,
            "cost_bps": COST_BPS,
        },
        "comparisons": 0,
    }
    if measured["reproduction"]["mismatches"]:
        (out / "mismatches.json").write_text(
            json.dumps(
                measured["mismatches"], ensure_ascii=False, indent=2, default=str
            ),
            encoding="utf-8",
        )
        result["elapsed_seconds"] = time.monotonic() - started
        (out / "tables.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "stopped": "reproduction mismatches",
                    **measured["reproduction"],
                    "out": str(out.resolve()),
                }
            )
        )
        return 4
    result["entries"] = measured["entries"]
    result["strategies"] = tables(measured["trades"])
    result["comparisons"] = len(ALTERNATIVES) * len(result["strategies"])
    result["elapsed_seconds"] = time.monotonic() - started
    result["peak_memory_gb"] = lib._load("backtest_research").peak_memory_gb()
    (out / "tables.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.md").write_text(markdown(result), encoding="utf-8")
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(_csv_rows(measured["trades"]))
    print(
        json.dumps(
            {
                "out": str(out.resolve()),
                "signals": result["signals"],
                "elapsed_seconds": round(result["elapsed_seconds"], 1),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
