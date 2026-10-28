"""The official trading calendar: the next session after a date (Issue #294).

``worker.trading_calendar`` stores TWSE's yearly holiday schedule in
``trading_calendar_days``.  The schedule lists the closed dates and a few
trading-day notices; a weekday it does not list as closed is a session.  Both
exchanges use the TWSE calendar (DATA_SOURCES, TAIEX session baseline).

Only the stored schedule is read, never ``market_bars``, so the answer for a
date is the same whether or not later bars are stored.  A closure the
schedule does not list (a typhoon) is not known on the night of the signal
and is not applied, then or later (V1_SPEC).  When a year the walk needs is
not published, or a row cannot be classified, there is no answer: callers
leave the date empty instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import TradingCalendarDay

CALENDAR_EXCHANGE = "TWSE"
CALENDAR_SOURCE = "twse_holiday_schedule"
# A row is a trading-day notice when its name says so (國曆新年開始交易日,
# 農曆春節前最後交易日), closed when its name or description has a closed
# marker (放假, 補假 for a make-up holiday, 市場無交易, ...), otherwise unknown.
TRADING_NOTICE_MARKERS = ("開始交易", "最後交易")
CLOSED_MARKERS = ("放假", "補假", "休市", "無交易", "不交易")
# The longest closure (Lunar New Year with the settlement-only days) is about
# nine days; a walk this long without a session means a broken calendar.
MAX_LOOKAHEAD_DAYS = 31
_CACHE_KEY = "trading_calendar_next_session"


def classify(name: str | None, description: str | None) -> str:
    """closed, trading or unknown; the one rule for every schedule reader."""

    name = name or ""
    if any(marker in name for marker in TRADING_NOTICE_MARKERS):
        return "trading"
    text = f"{name} {description or ''}"
    if any(marker in text for marker in CLOSED_MARKERS):
        return "closed"
    return "unknown"


@dataclass(frozen=True)
class NextSession:
    date: date | None
    # Why there is no date: calendar_year_missing, calendar_row_unknown or
    # no_session_within_lookahead; None when there is one.
    reason: str | None
    # The captures (raw_payloads.id) of the calendar years the walk read.
    raw_payload_ids: tuple[int, ...]
    missing_year: int | None = None

    def evidence(self) -> dict[str, object]:
        return {
            "source": CALENDAR_SOURCE,
            "raw_payload_ids": list(self.raw_payload_ids),
            "missing_reason": self.reason,
        }


def forget(db: Session) -> None:
    """Drop the session's cached answers after the calendar is written."""

    db.info.pop(_CACHE_KEY, None)


def next_session(db: Session, day: date) -> NextSession:
    """The first session after ``day`` by the stored official schedule."""

    cache = db.info.setdefault(_CACHE_KEY, {})
    if day not in cache:
        cache[day] = _next_session(db, day)
    return cache[day]


def _next_session(db: Session, day: date) -> NextSession:
    last = day + timedelta(days=MAX_LOOKAHEAD_DAYS)
    years = dict(
        db.execute(
            select(TradingCalendarDay.year, func.max(TradingCalendarDay.raw_payload_id))
            .where(
                TradingCalendarDay.exchange == CALENDAR_EXCHANGE,
                TradingCalendarDay.year.in_(range(day.year, last.year + 1)),
            )
            .group_by(TradingCalendarDay.year)
        ).all()
    )
    kinds = dict(
        db.execute(
            select(TradingCalendarDay.calendar_date, TradingCalendarDay.kind).where(
                TradingCalendarDay.exchange == CALENDAR_EXCHANGE,
                TradingCalendarDay.calendar_date > day,
                TradingCalendarDay.calendar_date <= last,
            )
        ).all()
    )
    read: list[int] = []
    cursor = day
    while cursor < last:
        cursor += timedelta(days=1)
        if cursor.year not in years:
            return NextSession(
                None,
                "calendar_year_missing",
                tuple(read),
                missing_year=cursor.year,
            )
        if years[cursor.year] not in read:
            read.append(years[cursor.year])
        if cursor.weekday() >= 5:
            continue
        kind = kinds.get(cursor)
        if kind == "closed":
            continue
        if kind == "unknown":
            return NextSession(None, "calendar_row_unknown", tuple(read))
        return NextSession(cursor, None, tuple(read))
    return NextSession(None, "no_session_within_lookahead", tuple(read))
