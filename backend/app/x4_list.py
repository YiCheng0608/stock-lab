"""X4 名單「盈餘殖利率前 20」(Issue #1016): compute and read.

X4 is ``tools/research/explore_research`` version 2's ``HYPOTHESES["X4"]``
(前瞻觀察, docs/spec/evidence.md 前瞻監測與下架); the user put it on a page as
a list (#1 decisions 7106346106, 7114503228).  Its definition is frozen: this
module writes the research code again (the product cannot import
tools/research) and ``backend/tests/test_x4_list.py`` locks the two to the
same picks on one fixture.  Every point below is the research tool's.  It has
no price levels and changes nothing of the today list or the other lists.

- **Sessions and universe**: H2's (``app.h2_list``, ``evidence_lib.universe``):
  ``stock``／``ipo`` by ``instrument_type`` with a bar on T (a session: a day
  with a ``stock`` bar) that is not suspended (``is_suspended``, or volume 0
  with open = high = low = close), whose mean volume over its last 20 bars on
  sessions (T included) is ≥ 1,000 lots.
- **revenue_yoy** (``feature_evidence.revenue_yoy``): the ``monthly_revenues``
  rows with ``announcement_date`` ≤ T, by announcement date then month; a row
  with a revenue sets its month (a later one replaces it).  The latest month
  is the largest; more than 80 calendar days before T it is missing.  Its
  revenue over ``prior_year_revenue`` minus one; missing when that is null or
  not positive.
- **The quarter's EPS** (``feature_evidence._quarter_eps``): the
  ``fundamental_snapshots`` rows with ``announcement_date`` ≤ T and an EPS,
  by announcement date then period end; a later row of a period end replaces
  it.  EPS is the year's cumulative figure: a quarter's own is the difference
  from the quarter before (Q1's is the cumulative one); missing when that
  quarter is not known.  The latest quarter is the largest period end; more
  than 200 days before T, or without its own EPS, there is none.  The year
  before is the same quarter's own EPS a year earlier, or missing.
- **eps_yield_raw** (``explore_research.eps_yield_raw``): the quarter's own EPS
  × 4 over T's unadjusted close (``market_bars.close``); missing without a
  quarter or a close > 0.
- **eps_growth_yield** (``feature_evidence.eps_growth_yield``): the quarter's
  EPS less the year before's, over T's close; missing without either EPS.
  The research divides by the adjusted close; every corporate-action factor
  is positive (``worker.pipeline._corporate_action_factor``: a split ratio,
  a free-share ratio and a cash dividend under the reference price, each
  > 0), so its sign is that over the unadjusted close, and only its sign is
  used.  The test fixture has a dividend to show it.
- **Filter, then order**: only ``revenue_yoy`` > 0 and ``eps_growth_yield`` >
  0 (a missing value fails); then ``eps_yield_raw`` larger first (a missing
  one last, ``portfolio_research.ranking_key``), then
  ``sha256("<T>:<instrument_id>")``; the first 20.  With fewer than 20 passing
  the list is those (nothing fills it, unlike H2).

The daily writes it after ``period_backfill`` (``worker.x4_list``) into the common
strategy list tables as strategy ``x4`` (``app.strategy_lists``, #1014); a
rerun of the date replaces the run and its items.  An item's values are in
``values_json``; ``/api/strategy-lists/x4`` reads them with ``market``,
``recent_closes`` and ``today_list`` at request time, as H2 does.  A ``zero``
run tells why in ``zero_reason``: ``universe_empty`` (no member) or
``none_passed`` (members, none passing both filters).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .candidate_view import recent_closes, recent_sessions
from .h2_list import (
    DEFINITIONS_SHA256,
    INSTRUMENT_TYPES,
    LIQUIDITY_BARS,
    MIN_AVERAGE_LOTS,
    SESSION_TYPE,
    Bar,
    Sessions,
    _bars,
    average_lots,
    tie_key,
)
from .mainstream import _today_list
from .market_change import adjacent_change
from .models import (
    FundamentalSnapshot,
    Instrument,
    MarketBar,
    MonthlyRevenue,
    StrategyListItem,
    StrategyListRun,
)
from .strategy_lists import Computed, Entry, Strategy, read_list, write_list

X4_KEY = "x4"
X4_VERSION = "explore_research_v2_X4"
LIST_SIZE = 20
REVENUE_STALE_DAYS = 80
QUARTER_STALE_DAYS = 200
# Bars read per stock before the session filter; all of them only when the
# filter leaves fewer than LIQUIDITY_BARS and the stock has more.
FETCH_BARS = LIQUIDITY_BARS + 20
X4_CONFIG: dict[str, Any] = {
    "source": "explore_research",
    "source_version": 2,
    "code": "X4",
    "key": "eps_yield_raw",
    "filters": ["revenue_yoy > 0", "eps_growth_yield > 0"],
    "list_size": LIST_SIZE,
    "liquidity_bars": LIQUIDITY_BARS,
    "min_average_lots": MIN_AVERAGE_LOTS,
    "instrument_types": list(INSTRUMENT_TYPES),
    "revenue_stale_days": REVENUE_STALE_DAYS,
    "quarter_stale_days": QUARTER_STALE_DAYS,
    "suspended": "is_suspended or (volume == 0 and open == high == low == close)",
    "fewer": "the passing ones only",
    "tie_break": "sha256(<T>:<instrument_id>)",
}
UNIVERSE_EMPTY = "universe_empty"
NONE_PASSED = "none_passed"


class X4DataError(RuntimeError):
    """T is not a session (no stock bar on it)."""


@dataclass(frozen=True)
class Revenue:
    month: date
    yoy: float | None


@dataclass(frozen=True)
class Quarter:
    period_end: date
    eps: float
    year_before: float | None


@dataclass(frozen=True)
class Member:
    instrument_id: int
    close: float
    revenue: Revenue | None
    quarter: Quarter | None

    @property
    def revenue_yoy(self) -> float | None:
        return self.revenue.yoy if self.revenue else None

    @property
    def eps_yield_raw(self) -> float | None:
        if self.quarter is None or not self.close > 0:
            return None
        return self.quarter.eps * 4.0 / self.close

    @property
    def eps_growth_yield(self) -> float | None:
        quarter = self.quarter
        if quarter is None or quarter.year_before is None or not self.close > 0:
            return None
        return (quarter.eps - quarter.year_before) / self.close

    @property
    def passes(self) -> bool:
        yoy, growth = self.revenue_yoy, self.eps_growth_yield
        return yoy is not None and yoy > 0 and growth is not None and growth > 0


# --- the pure parts --------------------------------------------------------


def latest_revenue(
    rows: list[tuple[date, date, float | None, float | None]], day: date
) -> Revenue | None:
    """rows: (announced, month, revenue, prior year) by announcement, month."""

    known = bisect_right(rows, day, key=lambda row: row[0])
    months: dict[date, tuple[float, float | None]] = {}
    for _announced, month, revenue, prior in rows[:known]:
        if revenue is not None:
            months[month] = (revenue, prior)
    if not months:
        return None
    latest = max(months)
    if (day - latest).days > REVENUE_STALE_DAYS:
        return None
    revenue, prior = months[latest]
    return Revenue(latest, revenue / prior - 1.0 if prior and prior > 0 else None)


def _quarter_before(end: date) -> date:
    return date(end.year, end.month - 3, 31 if end.month == 6 else 30)


def latest_quarter(rows: list[tuple[date, date, float]], day: date) -> Quarter | None:
    """rows: (announced, period end, cumulative EPS) by announcement, end."""

    known = bisect_right(rows, day, key=lambda row: row[0])
    cumulative = {end: eps for _announced, end, eps in rows[:known]}
    if not cumulative:
        return None
    latest = max(cumulative)
    if (day - latest).days > QUARTER_STALE_DAYS:
        return None

    def own(end: date) -> float | None:
        if end not in cumulative:
            return None
        if end.month == 3:
            return cumulative[end]
        before = _quarter_before(end)
        return cumulative[end] - cumulative[before] if before in cumulative else None

    now = own(latest)
    if now is None:
        return None
    return Quarter(latest, now, own(date(latest.year - 1, latest.month, latest.day)))


def rank_members(day: date, members: list[Member]) -> list[tuple[int, Member]]:
    """The passing members, ``eps_yield_raw`` larger first, then the hash; 20."""

    def key(member: Member) -> tuple:
        value = member.eps_yield_raw
        return (
            value is None,
            -(value if value is not None else 0.0),
            tie_key(day, member.instrument_id),
        )

    ordered = sorted((m for m in members if m.passes), key=key)[:LIST_SIZE]
    return list(enumerate(ordered, start=1))


def quarter_label(end: date) -> str:
    return f"{end.year}Q{(end.month + 2) // 3}"


# --- reading the inputs ---------------------------------------------------


def member_bars(
    db: Session, sessions: Sessions, instrument_id: int, day: date
) -> list[Bar]:
    """The stock's bars on sessions up to ``day``: the last LIQUIDITY_BARS at
    least when it has them (all of them otherwise)."""

    limit: int | None = FETCH_BARS
    while True:
        bars = _bars(db, instrument_id, day, limit)
        if not bars:
            return []
        days = sessions.cover(bars[0].trading_date)
        kept = [bar for bar in bars if bar.trading_date in days]
        if len(kept) >= LIQUIDITY_BARS or limit is None or len(bars) < limit:
            return kept
        limit = None


def _revenues(db: Session, ids: list[int], day: date) -> dict[int, list]:
    out: dict[int, list] = {instrument_id: [] for instrument_id in ids}
    if not ids:
        return out
    rows = db.execute(
        select(
            MonthlyRevenue.instrument_id,
            MonthlyRevenue.announcement_date,
            MonthlyRevenue.revenue_month,
            MonthlyRevenue.revenue,
            MonthlyRevenue.prior_year_revenue,
        )
        .where(
            MonthlyRevenue.instrument_id.in_(ids),
            MonthlyRevenue.announcement_date <= day,
        )
        .order_by(MonthlyRevenue.announcement_date, MonthlyRevenue.revenue_month)
    )
    for instrument_id, announced, month, revenue, prior in rows:
        out[instrument_id].append((announced, month, revenue, prior))
    return out


def _quarters(db: Session, ids: list[int], day: date) -> dict[int, list]:
    out: dict[int, list] = {instrument_id: [] for instrument_id in ids}
    if not ids:
        return out
    rows = db.execute(
        select(
            FundamentalSnapshot.instrument_id,
            FundamentalSnapshot.announcement_date,
            FundamentalSnapshot.period_end,
            FundamentalSnapshot.eps,
        )
        .where(
            FundamentalSnapshot.instrument_id.in_(ids),
            FundamentalSnapshot.announcement_date.is_not(None),
            FundamentalSnapshot.eps.is_not(None),
            FundamentalSnapshot.announcement_date <= day,
        )
        .order_by(FundamentalSnapshot.announcement_date, FundamentalSnapshot.period_end)
    )
    for instrument_id, announced, period_end, eps in rows:
        out[instrument_id].append((announced, period_end, eps))
    return out


def universe(db: Session, day: date) -> list[Member]:
    """T's universe with each member's inputs (module docstring)."""

    sessions = Sessions(db, day)
    if day not in sessions.cover(day):
        raise X4DataError(f"no {SESSION_TYPE} bar on {day.isoformat()}")
    candidates = db.scalars(
        select(MarketBar.instrument_id)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            MarketBar.trading_date == day,
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
        )
        .order_by(MarketBar.instrument_id)
    ).all()
    closes: dict[int, float] = {}
    for instrument_id in candidates:
        bars = member_bars(db, sessions, instrument_id, day)
        if not bars or bars[-1].trading_date != day or bars[-1].suspended:
            continue
        lots = average_lots(bars)
        if lots is None or lots < MIN_AVERAGE_LOTS:
            continue
        closes[instrument_id] = bars[-1].close or 0.0
    ids = sorted(closes)
    revenues, quarters = _revenues(db, ids, day), _quarters(db, ids, day)
    return [
        Member(
            instrument_id,
            closes[instrument_id],
            latest_revenue(revenues[instrument_id], day),
            latest_quarter(quarters[instrument_id], day),
        )
        for instrument_id in ids
    ]


# --- writing --------------------------------------------------------------


def values_of(member: Member) -> dict[str, Any]:
    revenue, quarter = member.revenue, member.quarter
    return {
        "eps_yield_raw": member.eps_yield_raw,
        "revenue_yoy": member.revenue_yoy,
        "revenue_month": revenue.month.isoformat() if revenue else None,
        "quarter_end": quarter.period_end.isoformat() if quarter else None,
        "quarter_eps": quarter.eps if quarter else None,
        "quarter_eps_year_before": quarter.year_before if quarter else None,
    }


def compute_day(db: Session, day: date) -> Computed:
    """``day``'s universe size and ranked list (``app.strategy_lists``)."""

    members = universe(db, day)
    return Computed(
        universe_count=len(members),
        entries=[
            Entry(
                instrument_id=member.instrument_id,
                rank=rank,
                close=member.close,
                values=values_of(member),
            )
            for rank, member in rank_members(day, members)
        ],
    )


def compute_x4(db: Session, day: date) -> StrategyListRun:
    """Compute ``day``'s list and replace any stored run of the date and version."""

    return write_list(db, X4, day)


# --- reading for /api/strategy-lists/x4 -----------------------------------


def _finite(value: Any) -> float | None:
    return value if isinstance(value, int | float) and math.isfinite(value) else None


def _empty(day: date | None) -> dict[str, Any]:
    return {
        "status": "missing",
        "zero_reason": None,
        "trading_date": day.isoformat() if day else None,
        "version": X4_VERSION,
        "definitions_sha256": DEFINITIONS_SHA256,
        "list_size": LIST_SIZE,
        "computed_at": None,
        "universe_count": None,
        "item_count": None,
        "items": [],
    }


def _month(value: str | None) -> str | None:
    return value[:7] if value else None


def _quarter(values: dict[str, Any]) -> dict[str, Any] | None:
    end = values.get("quarter_end")
    if not end:
        return None
    return {
        "quarter": quarter_label(date.fromisoformat(end)),
        "period_end": end,
        "eps": _finite(values.get("quarter_eps")),
        "year_before_eps": _finite(values.get("quarter_eps_year_before")),
    }


def present(
    db: Session,
    run: StrategyListRun | None,
    rows: list[StrategyListItem],
    trading_date: date | None,
) -> dict[str, Any]:
    """The response of a stored run (``app.strategy_lists``); missing without one."""

    if run is None:
        return _empty(trading_date)
    ids = [row.instrument_id for row in rows]
    instruments = {
        row.id: row
        for row in db.execute(
            select(
                Instrument.id,
                Instrument.exchange,
                Instrument.symbol,
                Instrument.name,
                Instrument.instrument_type,
                Instrument.listing_date,
            ).where(Instrument.id.in_(ids))
        )
    }
    bars = {
        bar.instrument_id: bar
        for bar in db.scalars(
            select(MarketBar).where(
                MarketBar.instrument_id.in_(ids),
                MarketBar.trading_date == run.trading_date,
            )
        )
    }
    days = recent_sessions(db, run.trading_date)
    closes = recent_closes(db, ids, days)
    sessions: dict[date, list[date]] = {run.trading_date: days[-2:]}
    today = _today_list(db, run.trading_date, ids)
    items = []
    for row in rows:
        instrument = instruments[row.instrument_id]
        values = row.values_json or {}
        items.append(
            {
                "rank": row.rank,
                "instrument": {
                    "id": instrument.id,
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "name": instrument.name,
                    "instrument_type": instrument.instrument_type,
                },
                "eps_yield_raw": _finite(values.get("eps_yield_raw")),
                "revenue_yoy": _finite(values.get("revenue_yoy")),
                "revenue_month": _month(values.get("revenue_month")),
                "quarter_eps": _quarter(values),
                "close": row.close,
                "market": adjacent_change(
                    db,
                    row.instrument_id,
                    run.trading_date,
                    bars.get(row.instrument_id),
                    sessions,
                    listing_date=instrument.listing_date,
                ),
                "recent_closes": closes[row.instrument_id],
                "today_list": today.get(row.instrument_id),
            }
        )
    zero_reason = None
    if run.status == "zero":
        zero_reason = UNIVERSE_EMPTY if not run.universe_count else NONE_PASSED
    return {
        "status": run.status,
        "zero_reason": zero_reason,
        "trading_date": run.trading_date.isoformat(),
        "version": run.version,
        "definitions_sha256": run.definitions_sha256,
        "list_size": LIST_SIZE,
        # computed_at is UTC-naive; the instant carries its offset.
        "computed_at": run.computed_at.replace(tzinfo=timezone.utc).isoformat()
        if run.computed_at
        else None,
        "universe_count": run.universe_count,
        "item_count": run.item_count,
        "items": items,
    }


X4 = Strategy(
    key=X4_KEY,
    version=X4_VERSION,
    definitions_sha256=DEFINITIONS_SHA256,
    config=X4_CONFIG,
    compute=compute_day,
    present=present,
)


def x4_list(db: Session, trading_date: date | None) -> dict[str, Any]:
    """The stored list of ``trading_date`` (the latest when None)."""

    return read_list(db, X4.key, trading_date)
