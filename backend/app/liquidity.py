"""Twenty-session average volume in lots (Issue #490, docs/spec/candidate_score.md).

The liquidity floor of the candidate pool reads the average daily volume of
a stock's last 20 sessions ending on the trading date, in lots (張, 1,000
shares).  ``market_bars.volume`` is in shares.

The sessions are the verified TAIEX sessions (``app.coverage``), so a session
the stock has no data for is seen instead of silently skipped:

* a bar marked suspended is not counted; the walk goes one session further
  back, so the window still holds 20 counted sessions;
* a session with a bar counts its volume (0 is a real day without trades);
* a session without a bar but with an official no-trade day row
  (``no_trade_days``, #454) counts 0 lots: the official quote table lists the
  security with no trade that day;
* a session with neither, or a bar whose volume is null, negative or not
  finite, is missing data.  It is never read as 0: the average is null and
  the state says why.

A stock listed fewer than 20 counted sessions before the date, or a date that
is not a verified session, has no average either.  Pure helpers first; the
database read is ``average_volumes`` at the end.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .coverage import verified_taiex_sessions
from .models import Instrument, MarketBar, NoTradeDay

SHARES_PER_LOT = 1000
LIQUIDITY_WINDOW_SESSIONS = 20
# Sessions read back from the date: room for 20 counted sessions plus a long
# suspension.  A stock suspended longer than that has no average.
LIQUIDITY_LOOKBACK_SESSIONS = 120

STATE_OK = "ok"
# The date is not a verified TAIEX session (or no session is stored).
STATE_SESSION_BASELINE_MISSING = "session_baseline_missing"
# A counted session has no bar and no no-trade row, or its volume is invalid.
STATE_MISSING_BARS = "missing_bars"
# Fewer than 20 counted sessions since listing or within the lookback.
STATE_INSUFFICIENT_SESSIONS = "insufficient_sessions"


@dataclass(frozen=True)
class SessionVolume:
    """One stored session of a stock: its volume in shares and suspension."""

    volume: float | None
    suspended: bool = False


@dataclass(frozen=True)
class AverageVolume:
    """The 20-session average volume of one stock on one date."""

    state: str
    average_lots: float | None
    # The counted sessions, oldest first (20 when the state is ok).
    sessions: tuple[date, ...] = ()
    # Counted sessions that read 0 lots from an official no-trade day row.
    no_trade_sessions: tuple[date, ...] = ()
    # Counted sessions without usable volume data (state missing_bars).
    missing_sessions: tuple[date, ...] = ()
    # Suspended sessions the walk skipped.
    suspended_sessions: tuple[date, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {
            "state": self.state,
            "average_volume_lots_20d": (
                None if self.average_lots is None else round(self.average_lots, 3)
            ),
            "window_start": self.sessions[0].isoformat() if self.sessions else None,
            "window_end": self.sessions[-1].isoformat() if self.sessions else None,
            "counted_sessions": len(self.sessions),
            "no_trade_sessions": [day.isoformat() for day in self.no_trade_sessions],
            "missing_sessions": [day.isoformat() for day in self.missing_sessions],
            "suspended_sessions": [day.isoformat() for day in self.suspended_sessions],
        }


def _volume(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def average_volume_lots(
    trading_date: date,
    sessions: Sequence[date],
    bars: Mapping[date, SessionVolume],
    no_trade_days: Iterable[date] = (),
    *,
    listing_date: date | None = None,
    window: int = LIQUIDITY_WINDOW_SESSIONS,
) -> AverageVolume:
    """Average volume in lots of the last ``window`` counted sessions to ``trading_date``.

    ``sessions`` are the verified market sessions (any order); ``bars`` the
    stock's stored bars by date; ``no_trade_days`` its official no-trade days.
    """

    ordered = sorted({day for day in sessions if day <= trading_date})
    if not ordered or ordered[-1] != trading_date:
        return AverageVolume(STATE_SESSION_BASELINE_MISSING, None)
    no_trade = set(no_trade_days)
    counted: list[date] = []
    zero_days: list[date] = []
    missing: list[date] = []
    suspended: list[date] = []
    total = 0.0
    for day in reversed(ordered):
        if len(counted) == window:
            break
        if listing_date is not None and day < listing_date:
            break
        bar = bars.get(day)
        if bar is not None and bar.suspended:
            suspended.append(day)
            continue
        counted.append(day)
        if bar is None:
            if day in no_trade:
                zero_days.append(day)
            else:
                missing.append(day)
            continue
        volume = _volume(bar.volume)
        if volume is None:
            missing.append(day)
            continue
        total += volume
    result = {
        "sessions": tuple(reversed(counted)),
        "no_trade_sessions": tuple(sorted(zero_days)),
        "missing_sessions": tuple(sorted(missing)),
        "suspended_sessions": tuple(sorted(suspended)),
    }
    if missing:
        return AverageVolume(STATE_MISSING_BARS, None, **result)
    if len(counted) < window:
        return AverageVolume(STATE_INSUFFICIENT_SESSIONS, None, **result)
    return AverageVolume(STATE_OK, total / window / SHARES_PER_LOT, **result)


def passes_volume_floor(average: AverageVolume, minimum_lots: float) -> bool | None:
    """True at or above the floor, False below it, None without an average."""

    if average.average_lots is None:
        return None
    return average.average_lots >= minimum_lots


def liquidity_sessions(db: Session, trading_date: date) -> list[date]:
    """The verified TAIEX sessions the walk may read, oldest first.

    Same call and per-session cache as the decision coverage
    (``app.decision._instrument_coverage``), so a page that builds both reads
    the sessions once.
    """

    cache = db.info.setdefault("_decision_taiex_dates", {})
    key = trading_date.isoformat()
    if key not in cache:
        cache[key] = verified_taiex_sessions(
            db,
            end_date=trading_date,
            require_provenance=True,
            limit=LIQUIDITY_LOOKBACK_SESSIONS,
        )
    return list(cache[key])


def average_volumes(
    db: Session,
    instruments: Iterable[Instrument],
    trading_date: date,
    *,
    sessions: Sequence[date] | None = None,
) -> dict[int, AverageVolume]:
    """``average_volume_lots`` of each instrument on ``trading_date``, by instrument id."""

    instruments = list(instruments)
    if not instruments:
        return {}
    if sessions is None:
        sessions = liquidity_sessions(db, trading_date)
    window = sorted(day for day in sessions if day <= trading_date)
    ids = [instrument.id for instrument in instruments]
    bars: dict[int, dict[date, SessionVolume]] = {item: {} for item in ids}
    no_trade: dict[int, set[date]] = {item: set() for item in ids}
    if window:
        start = window[0]
        for chunk_start in range(0, len(ids), 500):
            chunk = ids[chunk_start : chunk_start + 500]
            for instrument_id, day, volume, is_suspended in db.execute(
                select(
                    MarketBar.instrument_id,
                    MarketBar.trading_date,
                    MarketBar.volume,
                    MarketBar.is_suspended,
                ).where(
                    MarketBar.instrument_id.in_(chunk),
                    MarketBar.trading_date >= start,
                    MarketBar.trading_date <= trading_date,
                )
            ).all():
                bars[instrument_id][day] = SessionVolume(volume, bool(is_suspended))
            for instrument_id, day in db.execute(
                select(NoTradeDay.instrument_id, NoTradeDay.trading_date).where(
                    NoTradeDay.instrument_id.in_(chunk),
                    NoTradeDay.trading_date >= start,
                    NoTradeDay.trading_date <= trading_date,
                )
            ).all():
                no_trade[instrument_id].add(day)
    return {
        instrument.id: average_volume_lots(
            trading_date,
            window,
            bars[instrument.id],
            no_trade[instrument.id],
            listing_date=instrument.listing_date,
        )
        for instrument in instruments
    }
