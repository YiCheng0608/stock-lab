"""H2 名單 (Issue #881): compute, store and read.

H2 is ``tools/research/explore_research`` version 2's X2, which passed both
research segments; the user put it in the product as a list only (#1 decision
7044998169).  Its definition is frozen: this module writes the research code
again (the product cannot import tools/research) and
``backend/tests/test_h2_list.py`` locks the two to the same picks on one
fixture.  Every point below is the research tool's; the AC-1 decision is #881
7045371555.  It has no price levels (no entry zone, stop or target) and
changes nothing of the today list or ``mainstream_v1``.

- **Sessions**: the days with a ``stock`` bar (``research_report.
  market_sessions``).  A stock's bars are its bars on sessions; "the last N
  bars" counts those, so a suspended day without a bar is skipped.
- **Universe** (``evidence_lib.universe``): ``stock``／``ipo`` by
  ``instrument_type`` (not ``status``) with a bar on T that is not suspended,
  whose mean volume over its last 20 bars (T included) is ≥ 1,000 lots.  A
  bar is suspended when ``is_suspended`` is set **or** its volume is 0 with
  open = high = low = close (``research_report.Bar.suspended``).  This is not
  ``mainstream_v1``'s universe, which reads ``is_suspended`` alone and needs
  241 bars.  ``bar_exclusions.json`` is not used: its code_reuse ranges apply
  only to a database holding the old companies' bars, which the production
  one (stock bars from 2024-09-30) does not, and its 2007 TPEx range is older
  than it; only a recompute of an old date on a longer history can differ.
- **Prices** (``evidence_lib._series``): each bar times the product of the
  factors of the corporate actions after its day (on or before T), each
  action's own ``worker.pipeline._corporate_action_factor``; an action
  without a reference price takes the close of the last bar before its day
  when > 0 (``research_report.load_actions``).  A price that is 0 or null is
  missing.  Not ``_action_factor_by_bar``, which guards the cumulative factor
  and looks the fallback up among the bars it was given.
- **high_gap_240** (``feature_evidence._high_gap(240)``): the adjusted close of
  T over the highest adjusted high of the last 240 bars (T included), minus
  one.  Missing with fewer than 240 bars, a missing high in the window, or a
  close of T that is not positive.
- **Order** (``portfolio_research.ranking_key``): a value before a missing
  one, the larger first, then ``sha256("<T>:<instrument_id>")``; the first 20.
  A missing value is not dropped: with fewer than 20 values the missing ones
  fill the list, stored with ``high_gap_240`` null.

The daily writes it after ``mainstream`` (``worker.h2_list``) into the common
strategy list tables as strategy ``h2`` (``app.strategy_lists``, #1014;
``high_gap_240`` in ``values_json``); a rerun of the date replaces the run and
its items.  ``/api/h2`` and ``/api/strategy-lists/h2`` answer the same.  ``today_list`` (the stock's rank and
entry type in the day's today list) is read at request time, not stored,
and so are the page's ``market`` (the close of T and its change) and
``recent_closes`` (the sparkline), as ``/api/mainstream`` reads them (#882).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .candidate_view import recent_closes, recent_sessions
from .mainstream import _today_list
from .market_change import adjacent_change
from .models import (
    CorporateAction,
    Instrument,
    MarketBar,
    StrategyListItem,
    StrategyListRun,
)
from .strategy_lists import Computed, Entry, Strategy, read_list, write_list

H2_VERSION = "explore_research_v2_X2"
# explore_research.definitions_sha256() of version 2 (forward_watch WATCHES["H2"]).
DEFINITIONS_SHA256 = "600dc942361847eb9591425b4eb97ce4178b477695ff34fc234e45a665ebec63"
WINDOW = 240
LIST_SIZE = 20
LIQUIDITY_BARS = 20
MIN_AVERAGE_LOTS = 1000.0
SHARES_PER_LOT = 1000
INSTRUMENT_TYPES = ("stock", "ipo")
SESSION_TYPE = "stock"
# explore_research.LOAD_FROM: the corporate actions read are after it.
ACTIONS_AFTER = date(1990, 1, 1)
# Bars read per stock before the session filter; more are read only when the
# filter leaves fewer than WINDOW and the stock has more.
FETCH_BARS = WINDOW + 40
H2_CONFIG: dict[str, Any] = {
    "source": "explore_research",
    "source_version": 2,
    "code": "X2",
    "key": "high_gap_240",
    "window": WINDOW,
    "list_size": LIST_SIZE,
    "liquidity_bars": LIQUIDITY_BARS,
    "min_average_lots": MIN_AVERAGE_LOTS,
    "instrument_types": list(INSTRUMENT_TYPES),
    "suspended": "is_suspended or (volume == 0 and open == high == low == close)",
    "missing": "last, kept",
    "tie_break": "sha256(<T>:<instrument_id>)",
}

NAN = float("nan")


class H2DataError(RuntimeError):
    """T is not a session (no stock bar on it)."""


@dataclass(frozen=True)
class Bar:
    trading_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int
    is_suspended: bool

    @property
    def suspended(self) -> bool:
        return bool(
            self.is_suspended
            or (self.volume == 0 and self.open == self.high == self.low == self.close)
        )


@dataclass(frozen=True)
class Member:
    instrument_id: int
    high_gap_240: float | None
    close: float


@dataclass(frozen=True)
class RankedItem:
    instrument_id: int
    rank: int
    high_gap_240: float | None
    close: float


# --- the pure parts --------------------------------------------------------


def tie_key(day: date, instrument_id: int) -> str:
    return hashlib.sha256(f"{day.isoformat()}:{instrument_id}".encode()).hexdigest()


def average_lots(bars: list[Bar]) -> float | None:
    """Mean volume in lots of the last 20 bars; None with fewer."""

    if len(bars) < LIQUIDITY_BARS:
        return None
    window = [float(bar.volume) for bar in bars[-LIQUIDITY_BARS:]]
    return sum(window) / LIQUIDITY_BARS / SHARES_PER_LOT


def scales(bars: list[Bar], own: list[tuple[date, float]]) -> list[float]:
    """Each bar's factor to T's basis: the factors of the actions after its
    day multiplied from the last action back (``evidence_lib._series``)."""

    out = [1.0] * len(bars)
    factor, pending = 1.0, len(own) - 1
    for at in range(len(bars) - 1, -1, -1):
        day = bars[at].trading_date
        while pending >= 0 and own[pending][0] > day:
            factor *= own[pending][1]
            pending -= 1
        out[at] = factor
    return out


def _adjusted(value: float | None, scale: float) -> float:
    return value * scale if value else NAN


def high_gap(bars: list[Bar], own: list[tuple[date, float]]) -> float | None:
    """``high_gap_240`` of the last bar (see the module docstring)."""

    if len(bars) < WINDOW:
        return None
    window = bars[-WINDOW:]
    factors = scales(window, own)
    highs = [_adjusted(bar.high, scale) for bar, scale in zip(window, factors)]
    top = max(highs, default=NAN)
    if top != top or any(value != value for value in highs):
        return None
    if not top > 0:
        return None
    now = _adjusted(window[-1].close, factors[-1])
    value = now / top - 1.0 if top and now > 0 else None
    return None if value is None or value != value else float(value)


def rank_members(day: date, members: list[Member]) -> list[RankedItem]:
    """A value before a missing one, the larger first, then the hash; 20."""

    def key(member: Member) -> tuple:
        value = member.high_gap_240
        return (
            value is None,
            -(value if value is not None else 0.0),
            tie_key(day, member.instrument_id),
        )

    ordered = sorted(members, key=key)[:LIST_SIZE]
    return [
        RankedItem(member.instrument_id, rank, member.high_gap_240, member.close)
        for rank, member in enumerate(ordered, start=1)
    ]


# --- reading the inputs ---------------------------------------------------


def _bars(db: Session, instrument_id: int, day: date, limit: int | None) -> list[Bar]:
    query = (
        select(
            MarketBar.trading_date,
            MarketBar.open,
            MarketBar.high,
            MarketBar.low,
            MarketBar.close,
            MarketBar.volume,
            MarketBar.is_suspended,
        )
        .where(MarketBar.instrument_id == instrument_id, MarketBar.trading_date <= day)
        .order_by(desc(MarketBar.trading_date))
    )
    if limit is not None:
        query = query.limit(limit)
    rows = db.execute(query).all()
    return [
        Bar(
            row.trading_date,
            row.open,
            row.high,
            row.low,
            row.close,
            row.volume or 0,
            bool(row.is_suspended),
        )
        for row in reversed(rows)
    ]


class Sessions:
    """The days with a stock bar up to T, read back as far as asked."""

    def __init__(self, db: Session, day: date):
        self.db = db
        self.day = day
        self.since: date | None = None
        self.days: set[date] = set()

    def cover(self, first: date) -> set[date]:
        if self.since is None or first < self.since:
            until = self.day if self.since is None else self.since
            self.days |= set(
                self.db.scalars(
                    select(MarketBar.trading_date)
                    .join(Instrument, Instrument.id == MarketBar.instrument_id)
                    .where(
                        Instrument.instrument_type == SESSION_TYPE,
                        MarketBar.trading_date >= first,
                        MarketBar.trading_date <= until,
                    )
                    .distinct()
                )
            )
            self.since = first
        return self.days


def session_bars(
    db: Session, sessions: Sessions, instrument_id: int, day: date
) -> list[Bar]:
    """The stock's bars on sessions up to ``day``: the last WINDOW at least
    when it has them (all of them otherwise)."""

    limit: int | None = FETCH_BARS
    while True:
        bars = _bars(db, instrument_id, day, limit)
        if not bars:
            return []
        days = sessions.cover(bars[0].trading_date)
        kept = [bar for bar in bars if bar.trading_date in days]
        if len(kept) >= WINDOW or limit is None or len(bars) < limit:
            return kept
        limit = None


def action_factors(
    db: Session, instrument_id: int, day: date
) -> list[tuple[date, float]]:
    """(action date, the action's own factor) of the actions on or before
    ``day``, by date (``research_report.load_actions``)."""

    # Imported here: worker.pipeline imports app modules at load time.
    from worker.pipeline import _corporate_action_factor

    actions = db.scalars(
        select(CorporateAction)
        .where(
            CorporateAction.instrument_id == instrument_id,
            CorporateAction.action_date > ACTIONS_AFTER,
            CorporateAction.action_date <= day,
        )
        .order_by(CorporateAction.action_date, CorporateAction.id)
    ).all()
    out = []
    for action in actions:
        references: dict[date, float] = {}
        if action.reference_price is None:
            previous = db.scalar(
                select(MarketBar.close)
                .where(
                    MarketBar.instrument_id == instrument_id,
                    MarketBar.trading_date < action.action_date,
                )
                .order_by(MarketBar.trading_date.desc())
                .limit(1)
            )
            if previous and previous > 0:
                references[action.action_date] = previous
        factor, _applied = _corporate_action_factor(
            [action], fallback_reference_prices=references
        )
        out.append((action.action_date, factor))
    return out


def universe(db: Session, day: date) -> list[Member]:
    """T's universe with each member's ``high_gap_240`` (module docstring)."""

    sessions = Sessions(db, day)
    if day not in sessions.cover(day):
        raise H2DataError(f"no {SESSION_TYPE} bar on {day.isoformat()}")
    candidates = db.scalars(
        select(MarketBar.instrument_id)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .where(
            MarketBar.trading_date == day,
            Instrument.instrument_type.in_(INSTRUMENT_TYPES),
        )
        .order_by(MarketBar.instrument_id)
    ).all()
    members = []
    for instrument_id in candidates:
        bars = session_bars(db, sessions, instrument_id, day)
        if not bars or bars[-1].trading_date != day or bars[-1].suspended:
            continue
        lots = average_lots(bars)
        if lots is None or lots < MIN_AVERAGE_LOTS:
            continue
        value = high_gap(bars, action_factors(db, instrument_id, day))
        members.append(Member(instrument_id, value, bars[-1].close))
    return members


# --- writing --------------------------------------------------------------


def compute_day(db: Session, day: date) -> Computed:
    """``day``'s universe size and ranked list (``app.strategy_lists``)."""

    members = universe(db, day)
    items = rank_members(day, members)
    return Computed(
        universe_count=len(members),
        entries=[
            Entry(
                instrument_id=item.instrument_id,
                rank=item.rank,
                close=item.close,
                values={"high_gap_240": item.high_gap_240},
            )
            for item in items
        ],
    )


def compute_h2(db: Session, day: date) -> StrategyListRun:
    """Compute ``day``'s list and replace any stored run of the date and version."""

    return write_list(db, H2, day)


# --- reading for /api/h2 --------------------------------------------------


def _empty(status: str, day: date | None) -> dict[str, Any]:
    return {
        "status": status,
        "trading_date": day.isoformat() if day else None,
        "version": H2_VERSION,
        "definitions_sha256": DEFINITIONS_SHA256,
        "window": WINDOW,
        "computed_at": None,
        "universe_count": None,
        "items": [],
    }


def present(
    db: Session,
    run: StrategyListRun | None,
    rows: list[StrategyListItem],
    trading_date: date | None,
) -> dict[str, Any]:
    """The response of a stored run (``app.strategy_lists``); missing without one."""

    if run is None:
        return _empty("missing", trading_date)
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
    # The page's close, change and sparkline (#882), read as /api/mainstream
    # reads them: the stored bar of T and the last sessions' raw closes.
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
        value = (row.values_json or {}).get("high_gap_240")
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
                "high_gap_240": value
                if value is not None and math.isfinite(value)
                else None,
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
    return {
        "status": run.status,
        "trading_date": run.trading_date.isoformat(),
        "version": run.version,
        "definitions_sha256": run.definitions_sha256,
        "window": WINDOW,
        # computed_at is UTC-naive; the instant carries its offset.
        "computed_at": run.computed_at.replace(tzinfo=timezone.utc).isoformat()
        if run.computed_at
        else None,
        "universe_count": run.universe_count,
        "items": items,
    }


H2 = Strategy(
    key="h2",
    version=H2_VERSION,
    definitions_sha256=DEFINITIONS_SHA256,
    config=H2_CONFIG,
    compute=compute_day,
    present=present,
)


def h2_list(db: Session, trading_date: date | None) -> dict[str, Any]:
    """The stored list of ``trading_date`` (the latest when None)."""

    return read_list(db, H2.key, trading_date)
