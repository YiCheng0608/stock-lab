"""Official stops of trading, read side (Issue #582).

``trading_halts`` rows (written by ``worker.trading_halts``) name an interval
from ``halt_start`` up to, not including, ``resume_date``.  A session in it
without a bar is a stopped session: coverage counts it apart from missing
data and the stock page says why the price stops.  It is never a price: the
indicators, strategies, tracking and the 20/60-session bar baselines keep
reading bars only, as for official no-trade days.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TradingHalt

HALT_REASON_LABELS = {"capital_reduction": "減資換發新股"}


def covers(row: TradingHalt, day: date) -> bool:
    return row.halt_start <= day < row.resume_date


def halted_sessions(
    rows: Iterable[TradingHalt], sessions: Iterable[date]
) -> dict[date, TradingHalt]:
    """Each session a stop covers, with the stop (the later start on overlap)."""

    ordered = sorted(rows, key=lambda row: (row.halt_start, row.resume_date))
    result: dict[date, TradingHalt] = {}
    for day in sessions:
        for row in ordered:
            if covers(row, day):
                result[day] = row
    return result


def load_halts(
    db: Session, instrument_ids: Iterable[int], start: date | None, end: date | None
) -> dict[int, list[TradingHalt]]:
    """The stops of the instruments that overlap ``start``..``end`` (both inclusive)."""

    ids = sorted(set(instrument_ids))
    result: dict[int, list[TradingHalt]] = defaultdict(list)
    if not ids:
        return result
    query = select(TradingHalt).where(TradingHalt.instrument_id.in_(ids))
    if end is not None:
        query = query.where(TradingHalt.halt_start <= end)
    if start is not None:
        query = query.where(TradingHalt.resume_date > start)
    for row in db.scalars(query.order_by(TradingHalt.halt_start)).all():
        result[row.instrument_id].append(row)
    return result


def halt_on(db: Session, instrument_id: int, day: date) -> TradingHalt | None:
    """The stop covering ``day``, if any (the latest-starting one)."""

    rows = load_halts(db, [instrument_id], day, day).get(instrument_id, [])
    covering = [row for row in rows if covers(row, day)]
    return max(covering, key=lambda row: row.halt_start, default=None)


def halt_dict(row: TradingHalt) -> dict[str, Any]:
    return {
        "reason": row.reason,
        "reason_label": HALT_REASON_LABELS.get(row.reason, row.reason),
        "reason_detail": row.reason_detail,
        "halt_start": row.halt_start.isoformat(),
        "resume_date": row.resume_date.isoformat(),
        "last_trade_date": row.last_trade_date.isoformat()
        if row.last_trade_date
        else None,
        "exchange": row.exchange,
        "source": row.source,
        "endpoint": row.endpoint,
        "data_as_of": row.data_as_of,
    }
