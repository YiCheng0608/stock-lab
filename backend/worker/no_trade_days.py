"""Official no-trade days from stored daily quote reports (Issue #454).

The daily quote report collect already stores for every session lists a
thinly traded security on a day it had no regular-session trade with every
price blank: TWSE MI_INDEX 每日收盤行情 (開盤價／最高價／最低價／收盤價 ``--``)
and TPEx 上櫃股票行情 (開盤／最高／最低／收盤 ``---``).  The bar parsers drop
that row, so the day used to look like missing data.  Here it becomes a
``no_trade_days`` row with its source, and coverage counts it apart from a
gap; no price is made up and no price reader sees it.

Nothing is fetched.  For each exchange and session the latest stored capture
that reports that date and has rows is the evidence; the session's rows of
that exchange are rebuilt from it, so a later capture replaces an earlier one
and a row whose security now has a bar or a price is removed.  A code with no
stored instrument is counted, not written.  A session with no such capture is
``missing`` and keeps its earlier rows.  collect runs this for the sessions it
stored; ``worker.cli no-trade-days`` backfills a date range.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from typing import Any, Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Instrument, MarketBar, NoTradeDay, RawPayload
from app.raw_paths import payload_file
from worker.sources import (
    TPEX_HISTORY_API,
    TWSE_DAILY_HISTORY_ENDPOINT,
    NoTradeRecord,
    OfficialDataError,
    _has_tabular_rows,
    _require_reported_date,
    is_quoted_security_code,
    parse_tpex_daily_rows,
    parse_tpex_no_trade_rows,
    parse_twse_all_daily_no_trade_payload,
    parse_twse_all_daily_payload,
)

RUN_TYPE = "no_trade_days"
MAX_SAMPLES = 50
# _load's answer for a capture without table rows (see there).
NO_ROWS = object()


# The parsers return None for a capture without a security quote table (no
# row the bar parser reads): it is not usable, and the day's stored rows stay.
def _parse_twse(payload: Any, trading_date: date) -> list[NoTradeRecord] | None:
    if not parse_twse_all_daily_payload(payload, requested_date=trading_date):
        return None
    return parse_twse_all_daily_no_trade_payload(
        payload, requested_date=trading_date, data_as_of=trading_date.isoformat()
    )


def _parse_tpex(payload: Any, trading_date: date) -> list[NoTradeRecord] | None:
    as_of = trading_date.isoformat()
    if not parse_tpex_daily_rows(payload, data_as_of=as_of):
        return None
    return parse_tpex_no_trade_rows(payload, data_as_of=as_of)


# exchange -> (raw_payloads.source, endpoint without the query, parser)
CAPTURES: dict[
    str, tuple[str, str, Callable[[Any, date], list[NoTradeRecord] | None]]
] = {
    "TWSE": ("twse", TWSE_DAILY_HISTORY_ENDPOINT, _parse_twse),
    "TPEx": ("tpex", TPEX_HISTORY_API, _parse_tpex),
}


class NoTradeDayError(Exception):
    """A stored file is unreadable, not JSON or not its SHA-256; that session
    is not written."""


def _load(capture: RawPayload, trading_date: date) -> Any:
    try:
        content = payload_file(capture.payload_path).read_bytes()
    except OSError as exc:
        raise NoTradeDayError(
            f"raw payload {capture.id} cannot be read: {capture.payload_path}: {exc}"
        ) from exc
    if hashlib.sha256(content).hexdigest() != capture.sha256:
        raise NoTradeDayError(
            f"raw payload {capture.id} does not match its SHA-256: "
            f"{capture.payload_path}"
        )
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NoTradeDayError(
            f"raw payload {capture.id} is not JSON: {capture.payload_path}: {exc}"
        ) from exc
    # A date-less no-match answer (a TWSE holiday) or an empty table (a TPEx
    # holiday) has no rows to read: no evidence, and not a missing report.
    if not isinstance(payload, dict) or not _has_tabular_rows(payload):
        return NO_ROWS
    try:
        _require_reported_date(payload, trading_date, capture.endpoint.split("?")[0])
    except OfficialDataError:
        return None
    return payload


def _captures(db: Session, exchange: str, trading_date: date) -> list[RawPayload]:
    source, endpoint, _parse = CAPTURES[exchange]
    rows = db.scalars(
        select(RawPayload)
        .where(
            RawPayload.source == source,
            RawPayload.endpoint.like(f"{endpoint}%"),
            RawPayload.data_as_of.like(f"{trading_date.isoformat()}%"),
        )
        .order_by(RawPayload.collected_at.desc(), RawPayload.id.desc())
    ).all()
    # ``like`` also matches a longer path; keep the endpoint itself.
    return [row for row in rows if row.endpoint.split("?")[0] == endpoint]


def _session_dates(db: Session, start: date | None, end: date | None) -> list[date]:
    """Sessions with a stored daily quote capture of either exchange, in order."""

    found: set[date] = set()
    for source, endpoint, _parse in CAPTURES.values():
        query = select(RawPayload.data_as_of).where(
            RawPayload.source == source, RawPayload.endpoint.like(f"{endpoint}%")
        )
        for (value,) in db.execute(query).all():
            try:
                day = date.fromisoformat((value or "")[:10])
            except ValueError:
                continue
            if (start is None or day >= start) and (end is None or day <= end):
                found.add(day)
    return sorted(found)


def store_no_trade_days(
    db: Session, exchange: str, trading_date: date
) -> dict[str, Any]:
    """Rebuild one exchange's no-trade rows of one session from stored raw.

    Returns ``outcome`` (``written``, ``unchanged``, ``no_data`` when every
    capture of the date is an empty answer such as a holiday's, or
    ``missing`` when none of the date is usable), ``rows`` (rows the session
    now has) and ``unmatched`` (blank-price share or ETF codes without a
    stored instrument).
    """

    _source, _endpoint, parse = CAPTURES[exchange]
    saw_no_rows = False
    for capture in _captures(db, exchange, trading_date):
        payload = _load(capture, trading_date)
        if payload is NO_ROWS:
            saw_no_rows = True
            continue
        if payload is None:
            continue
        parsed = parse(payload, trading_date)
        if parsed is None:
            continue
        records = {
            record.symbol: record
            for record in parsed
            if record.trading_date == trading_date
        }
        instruments = {
            symbol: instrument_id
            for symbol, instrument_id in db.execute(
                select(Instrument.symbol, Instrument.id).where(
                    Instrument.exchange == exchange,
                    Instrument.symbol.in_(records) if records else False,
                )
            )
        }
        priced = set(
            db.scalars(
                select(MarketBar.instrument_id).where(
                    MarketBar.trading_date == trading_date,
                    MarketBar.instrument_id.in_(instruments.values())
                    if instruments
                    else False,
                )
            )
        )
        wanted = {
            instrument_id
            for symbol, instrument_id in instruments.items()
            if instrument_id not in priced
        }
        stored = {
            row.instrument_id: row
            for row in db.scalars(
                select(NoTradeDay)
                .join(Instrument, Instrument.id == NoTradeDay.instrument_id)
                .where(
                    Instrument.exchange == exchange,
                    NoTradeDay.trading_date == trading_date,
                )
            )
        }
        # Warrants, bonds and other products of the same tables are not
        # instruments; only an unknown share or ETF code is worth counting.
        unmatched = sorted(
            symbol
            for symbol in set(records) - set(instruments)
            if is_quoted_security_code(symbol)
        )
        if set(stored) == wanted and all(
            row.raw_payload_id == capture.id for row in stored.values()
        ):
            return {"outcome": "unchanged", "rows": len(wanted), "unmatched": unmatched}
        stale = [row.id for key, row in stored.items() if key not in wanted]
        if stale:
            db.execute(delete(NoTradeDay).where(NoTradeDay.id.in_(stale)))
        for instrument_id in wanted:
            row = stored.get(instrument_id)
            if row is None:
                row = NoTradeDay(instrument_id=instrument_id, trading_date=trading_date)
                db.add(row)
            row.source = capture.source
            row.endpoint = capture.endpoint
            row.data_as_of = trading_date.isoformat()
            row.collected_at = capture.collected_at
            row.raw_payload_id = capture.id
        db.flush()
        return {"outcome": "written", "rows": len(wanted), "unmatched": unmatched}
    # Only empty answers (a holiday): no rows to read, not a missing report.
    outcome = "no_data" if saw_no_rows else "missing"
    return {"outcome": outcome, "rows": 0, "unmatched": []}


def sync_no_trade_days(
    db: Session,
    dates: Iterable[date] | None = None,
    *,
    start: date | None = None,
    end: date | None = None,
    commit_each: bool = False,
) -> dict[str, Any]:
    """Store both exchanges' no-trade rows of ``dates`` (default: every stored
    session).

    ``commit_each`` commits each session on its own (the backfill CLI);
    collect leaves the commit to its own transaction.  A file that cannot be
    read, is not JSON or does not match its SHA-256 stops the run at that
    session (earlier sessions stay written when committed) and the result is
    ``failed`` with ``failed_date``.  A session without a usable capture makes
    it ``partial``.
    """

    days = sorted(set(dates)) if dates is not None else _session_dates(db, start, end)
    counts = {"written": 0, "unchanged": 0, "no_data": 0, "missing": 0}
    rows = 0
    unmatched = 0
    missing: list[str] = []
    unmatched_samples: list[str] = []
    for day in days:
        try:
            for exchange in CAPTURES:
                result = store_no_trade_days(db, exchange, day)
                counts[result["outcome"]] += 1
                rows += result["rows"]
                unmatched += len(result["unmatched"])
                if result["outcome"] == "missing" and len(missing) < MAX_SAMPLES:
                    missing.append(f"{exchange}:{day.isoformat()}")
                for symbol in result["unmatched"]:
                    if len(unmatched_samples) < MAX_SAMPLES:
                        unmatched_samples.append(
                            f"{exchange}:{symbol}:{day.isoformat()}"
                        )
        except NoTradeDayError as exc:
            if commit_each:
                db.rollback()
            return {
                "status": "failed",
                "error": str(exc),
                "failed_date": day.isoformat(),
                "dates": len(days),
                **counts,
                "rows": rows,
                "missing_samples": missing,
            }
        if commit_each:
            db.commit()
    return {
        "status": "success" if counts["missing"] == 0 else "partial",
        "dates": len(days),
        "first_date": days[0].isoformat() if days else None,
        "last_date": days[-1].isoformat() if days else None,
        **counts,
        "rows": rows,
        "unmatched": unmatched,
        "missing_samples": missing,
        "unmatched_samples": unmatched_samples,
    }


def run_no_trade_days(
    start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    """``worker.cli no-trade-days``: backfill the rows from stored raw."""

    from worker import pipeline  # pipeline imports this module

    with pipeline.SessionLocal() as db:
        return sync_no_trade_days(db, start=start, end=end, commit_each=True)
