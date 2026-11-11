"""Shared reading and arithmetic of the evidence tools, read only.

``feature_evidence.py`` and ``candidate_scorecard.py`` answer one question each
about the same panel: the daily bars of every ``stock``／``ipo`` instrument
(``research_report.benchmark_universe``: by ``instrument_type``, not ``status``,
so an instrument delisted since is in the panel on the days it traded), the
chips and the monthly revenues, all read through ``mode=ro`` + ``query_only``.

Prices are put on one basis per instrument: a bar before a corporate action is
multiplied by that action's price factor (``worker.pipeline.
_corporate_action_factor``, the product's own), so a return across an
ex-dividend or split day is the holder's, not the raw gap.  Volumes are raw.

A forward return buys at the open of T+1 with the tracking's 5 bps buy
slippage and values at the close of T+N.  It is comparable only when the
instrument has a bar on each of the market's N sessions after T and none of
them is suspended, the rule of ``research_report.benchmark_return``.  Costs are
not in it: ``net`` takes the round trip off (``DEFAULT_COST_BPS``, the two
0.1425 % fees and the 0.3 % sell tax, undiscounted), and an excess return over
the same day's universe does not depend on it.

The segments are ``app.strategies.index_conditions``'s, fixed before any result
of these tools was read (a test keeps the two equal).
"""

from __future__ import annotations

import importlib.util
import math
import sqlite3
import statistics
import sys
from array import array
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HORIZONS = (5, 20)
BUY_SLIPPAGE = 5.0 / 10_000.0
DEFAULT_COST_BPS = 58.5
SHARES_PER_LOT = 1000
DEFAULT_MIN_LOTS = 1000.0
LIQUIDITY_WINDOW = 20
NAN = float("nan")
# (key, label, first day, last day or None): index_conditions.SEGMENTS.
SEGMENTS = (
    ("exploration", "探索段", date(2024, 9, 30), date(2025, 12, 31)),
    ("validation", "驗證段", date(2026, 1, 1), None),
)
CHIP_FIELDS = (
    "foreign_buy",
    "trust_buy",
    "dealer_buy",
    "margin_balance",
    "short_balance",
    "borrowed_sell",
    "day_trade_ratio",
)
# A revenue month older than this many calendar days at T is not "the latest".
REVENUE_STALE_DAYS = 80


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools" / "research" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


def research_report():
    return _load("research_report")


def production_problem(db: Path, environ: dict[str, str]) -> str | None:
    """Why ``db`` may not be read (it is the production database), or None."""

    return _load("backtest_research").production_problem(db, environ)


# --- the panel ------------------------------------------------------------


@dataclass
class Series:
    """One instrument's bars in date order, prices on its latest basis."""

    instrument_id: int
    dates: list[date] = field(default_factory=list)
    session: array = field(default_factory=lambda: array("i"))
    open: array = field(default_factory=lambda: array("d"))
    high: array = field(default_factory=lambda: array("d"))
    low: array = field(default_factory=lambda: array("d"))
    close: array = field(default_factory=lambda: array("d"))
    volume: array = field(default_factory=lambda: array("d"))
    # suspended[k] counts the suspended bars before position k.
    suspended: array = field(default_factory=lambda: array("i"))
    position: dict[date, int] = field(default_factory=dict)
    chips: dict[str, array] = field(default_factory=dict)
    # (announcement_date, revenue_month, revenue, prior_year_revenue), by announcement.
    revenues: list[tuple[date, date, float | None, float | None]] = field(
        default_factory=list
    )

    def is_suspended(self, at: int) -> bool:
        return self.suspended[at + 1] != self.suspended[at]


@dataclass
class Panel:
    sessions: list[date]
    series: dict[int, Series]
    listed: dict[date, list[int]]
    index_close: dict[date, float]
    symbols: dict[int, tuple[str, str, str]]  # id -> exchange, symbol, name


def connect_read_only(db: Path) -> sqlite3.Connection:
    return research_report().connect_read_only(db)


def load_panel(db: Path, start: date, raw_dir: Path) -> Panel:
    """Every stock／ipo bar from ``start`` on, adjusted, with chips and revenues."""

    report = research_report()
    con = connect_read_only(db)
    try:
        instruments, listed = report.benchmark_universe(con, start)
        sessions = report.market_sessions(con, start)
        index_close = report.index_closes(con, start)
        factor_of = report.load_actions(db, instruments, start, raw_dir)
        session_index = {day: index for index, day in enumerate(sessions)}
        series = {
            instrument_id: _series(instrument_id, instrument, factor_of, session_index)
            for instrument_id, instrument in instruments.items()
        }
        _load_chips(con, series, start)
        _load_revenues(con, series)
        symbols = {
            row[0]: (row[1], row[2], row[3])
            for row in con.execute("select id, exchange, symbol, name from instruments")
            if row[0] in series
        }
    finally:
        con.close()
    return Panel(sessions, series, dict(listed), index_close, symbols)


def _series(instrument_id: int, instrument, factor_of, session_index) -> Series:
    out = Series(instrument_id)
    actions = sorted(instrument.actions, key=lambda action: action.action_date)
    own = [
        (action.action_date, factor_of([action], None, instrument))
        for action in actions
    ]
    # Walk the bars from the last one back; ``factor`` is the product of the
    # factors of every action after the bar's day.
    factors = [1.0] * len(instrument.bars)
    factor, pending = 1.0, len(own) - 1
    for at in range(len(instrument.bars) - 1, -1, -1):
        day = instrument.bars[at].trading_date
        while pending >= 0 and own[pending][0] > day:
            factor *= own[pending][1]
            pending -= 1
        factors[at] = factor
    out.suspended.append(0)
    for at, bar in enumerate(instrument.bars):
        if bar.trading_date not in session_index:
            continue
        scale = factors[at]
        out.position[bar.trading_date] = len(out.dates)
        out.dates.append(bar.trading_date)
        out.session.append(session_index[bar.trading_date])
        for name in ("open", "high", "low", "close"):
            value = getattr(bar, name)
            getattr(out, name).append(value * scale if value else NAN)
        out.volume.append(float(bar.volume or 0))
        out.suspended.append(out.suspended[-1] + (1 if bar.suspended else 0))
    return out


def _load_chips(
    con: sqlite3.Connection, series: dict[int, Series], start: date
) -> None:
    for item in series.values():
        item.chips = {name: array("d", [NAN]) * len(item.dates) for name in CHIP_FIELDS}
    rows = con.execute(
        f"select instrument_id, trading_date, {', '.join(CHIP_FIELDS)} "
        "from chip_snapshots where trading_date >= ?",
        (start.isoformat(),),
    )
    for instrument_id, day, *values in rows:
        item = series.get(instrument_id)
        if item is None:
            continue
        at = item.position.get(date.fromisoformat(day))
        if at is None:
            continue
        for name, value in zip(CHIP_FIELDS, values):
            if value is not None:
                item.chips[name][at] = float(value)


def _load_revenues(con: sqlite3.Connection, series: dict[int, Series]) -> None:
    rows = con.execute(
        "select instrument_id, announcement_date, revenue_month, revenue, "
        "prior_year_revenue from monthly_revenues order by announcement_date, revenue_month"
    )
    for instrument_id, announced, month, revenue, prior in rows:
        item = series.get(instrument_id)
        if item is not None:
            item.revenues.append(
                (
                    date.fromisoformat(announced),
                    date.fromisoformat(month),
                    revenue,
                    prior,
                )
            )


# --- returns and the universe ---------------------------------------------


def forward_return(item: Series, at: int, horizon: int) -> float | None:
    """Open of T+1 (with buy slippage) to the close of T+``horizon``; before costs."""

    end = at + horizon
    if end >= len(item.dates):
        return None
    if item.session[end] - item.session[at] != horizon:
        return None  # a market session without a bar
    if item.suspended[end + 1] != item.suspended[at + 1]:
        return None  # a suspended session in T+1..T+N
    entry, exit_ = item.open[at + 1], item.close[end]
    if not (entry > 0 and exit_ > 0):
        return None
    return exit_ / (entry * (1.0 + BUY_SLIPPAGE)) - 1.0


def is_pending(panel: Panel, day: date, horizon: int) -> bool:
    """T+``horizon`` of ``day`` is after the panel's last session."""

    at = bisect_right(panel.sessions, day)
    return at + horizon > len(panel.sessions)


def average_lots(item: Series, at: int) -> float | None:
    """Mean volume in lots of the 20 bars to T inclusive; None with fewer bars."""

    if at + 1 < LIQUIDITY_WINDOW:
        return None
    window = item.volume[at + 1 - LIQUIDITY_WINDOW : at + 1]
    return sum(window) / LIQUIDITY_WINDOW / SHARES_PER_LOT


def universe(panel: Panel, day: date, min_lots: float) -> list[tuple[Series, int]]:
    """The instruments tradable on ``day``: a bar, not suspended, liquid enough."""

    members = []
    for instrument_id in panel.listed.get(day, ()):
        item = panel.series[instrument_id]
        at = item.position.get(day)
        if at is None or item.is_suspended(at):
            continue
        lots = average_lots(item, at)
        if lots is None or lots < min_lots:
            continue
        members.append((item, at))
    return members


def index_return(panel: Panel, day: date, horizon: int) -> float | None:
    """TAIEX close of T to its close ``horizon`` market sessions later."""

    at = bisect_right(panel.sessions, day)
    if (
        at == 0
        or panel.sessions[at - 1] != day
        or at - 1 + horizon >= len(panel.sessions)
    ):
        return None
    start = panel.index_close.get(day)
    end = panel.index_close.get(panel.sessions[at - 1 + horizon])
    if not (start and end and start > 0):
        return None
    return end / start - 1.0


def segment_of(day: date) -> str | None:
    for key, _label, first, last in SEGMENTS:
        if day >= first and (last is None or day <= last):
            return key
    return None


def quarter_of(day: date) -> str:
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


# --- statistics -----------------------------------------------------------


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks, ties sharing the mean of their ranks."""

    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    at = 0
    while at < len(order):
        end = at
        while end + 1 < len(order) and values[order[end + 1]] == values[order[at]]:
            end += 1
        shared = (at + end) / 2.0 + 1.0
        for k in range(at, end + 1):
            ranks[order[k]] = shared
        at = end + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation; None with fewer than 3 pairs or a constant side."""

    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sxx * syy)


def t_stat(values: Sequence[float], overlap: int = 1) -> float | None:
    """Mean over its standard error, the sample counted as ``len / overlap``.

    Daily values of an N-session forward return overlap N−1 sessions with the
    next day's, so ``overlap=N`` counts only the non-overlapping share of the
    days: a floor, not an estimate.
    """

    if len(values) < 2:
        return None
    spread = statistics.stdev(values)
    effective = len(values) / max(overlap, 1)
    if spread <= 0 or effective < 2:
        return None
    return statistics.fmean(values) / (spread / math.sqrt(effective))


def summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "positive": sum(1 for value in values if value > 0) / len(values),
    }


def by_segment(days: Sequence[date]) -> dict[str, list[int]]:
    """Positions of ``days`` per segment key, per quarter and for ``all``."""

    groups: dict[str, list[int]] = defaultdict(list)
    for at, day in enumerate(days):
        groups["all"].append(at)
        key = segment_of(day)
        if key:
            groups[key].append(at)
        groups[quarter_of(day)].append(at)
    return groups


def pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"
