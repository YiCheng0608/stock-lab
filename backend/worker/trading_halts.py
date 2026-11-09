"""Official capital-reduction stops of trading (Issue #582).

A capital reduction stops the old shares from trading for about a week: the
official quote tables (TWSE MI_INDEX, TPEx dailyQuotes) then have no row for
the security, and the day used to look like missing data.  TWSE
股票減資恢復買賣參考價格 (``TWTAUU``) and TPEx 減資恢復買賣 (``revivt``) list each
such stop by its resumption day, before it begins: TWSE with the last
trading day, TPEx with the first stopped day.  ``trading_halts`` keeps one row
per security and resumption; the stopped sessions run from ``halt_start`` up
to, not including, ``resume_date`` (``app.trading_halts`` reads them).

Each answer covers a range of resumption days and is complete for it, so the
exchange's stored rows resuming in that range are rebuilt from it: a row the
answer no longer lists is removed, one whose content changed points at the new
capture, an unchanged one keeps the capture that brought it.  A row whose own
dates disagree (sources' parsers) is left out with a warning; so is one whose
security has a stored bar inside the stop, except a TWSE row whose stated
last trading day is a session early (``_check_bars``).  A code without a
stored instrument is counted, not written.

collect asks for the resumptions from ten days before to sixty days after the
collect day (one request per exchange, non-core: a failure is a warning and
the collect stays ``success``); ``worker.cli trading-halts`` asks for any range
(one request per exchange).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import IngestionRun, Instrument, MarketBar, RawPayload, TradingHalt
from worker import pipeline
from worker.sources import (
    TRADING_HALT_DAYS_AFTER,
    FetchedPayload,
    TradingHaltRecord,
    TradingHaltWindow,
    _call_fetcher,
    capture_payload,
    fetch_json,
    fetch_reduction_window,
    parse_number,
    trading_halt_warning,
)

RUN_TYPE = "trading_halts"
EXCHANGES = ("TWSE", "TPEx")
_RAW_SOURCES = {"TWSE": "twse", "TPEx": "tpex"}


def _content(record: TradingHaltRecord) -> tuple[Any, ...]:
    return (
        record.halt_start,
        record.last_trade_date,
        record.reason,
        record.reason_detail,
        record.details,
    )


def _stored_content(row: TradingHalt) -> tuple[Any, ...]:
    return (
        row.halt_start,
        row.last_trade_date,
        row.reason,
        row.reason_detail,
        row.details_json,
    )


def _bars_inside(
    db: Session, instrument_id: int, record: TradingHaltRecord
) -> list[tuple[date, float | None]]:
    """The stored bars of the security inside the stop, oldest first."""

    return [
        (day, close)
        for day, close in db.execute(
            select(MarketBar.trading_date, MarketBar.close)
            .where(
                MarketBar.instrument_id == instrument_id,
                MarketBar.trading_date >= record.halt_start,
                MarketBar.trading_date < record.resume_date,
            )
            .order_by(MarketBar.trading_date)
        ).all()
    ]


def _check_bars(
    db: Session, instrument_id: int, record: TradingHaltRecord
) -> tuple[TradingHaltRecord | None, str | None]:
    """The record as the quote tables allow it, or None and why not.

    TWSE's 詳細資料 date is mostly the last trading day but sometimes the
    session before it (2025-09 2101 南港, 2026-10 4155 訊映: their 停止買賣前收盤
    is the close of the next session).  So a TWSE stop whose stated start has
    bars is moved past the last of them when that bar's close is the row's
    停止買賣前收盤價格 (or the row has no price yet); the stated date stays in
    ``details``.  Any other bar inside a stop, and every one inside a TPEx stop
    (TPEx states its 停止買賣日期), rejects the row: the bar is the evidence.
    """

    inside = _bars_inside(db, instrument_id, record)
    if not inside:
        return record, None
    last_day, last_close = inside[-1]
    stated = parse_number(record.details.get("停止買賣前收盤價格"))
    if record.exchange == "TWSE" and (
        stated is None
        or (last_close is not None and abs(float(last_close) - stated) < 1e-6)
    ):
        return (
            replace(
                record,
                last_trade_date=last_day,
                halt_start=last_day + timedelta(days=1),
                details={
                    **record.details,
                    "stated_last_trade_date": record.last_trade_date.isoformat()
                    if record.last_trade_date
                    else None,
                    "last_trade_date_basis": "last_bar_before_resumption",
                },
            ),
            None,
        )
    return None, (
        f"{record.symbol} has a bar on {inside[0][0]} inside its stop "
        f"{record.halt_start}..{record.resume_date}"
    )


def _apply_window(
    db: Session,
    window: TradingHaltWindow,
    records: list[TradingHaltRecord],
    instruments: dict[tuple[str, str], Instrument],
    raw_id: Callable[[str | None], int | None],
    warnings: list[str],
) -> dict[str, Any]:
    identifier = raw_id(window.payload_sha256)
    raw = db.get(RawPayload, identifier) if identifier is not None else None
    if raw is None:
        raise ValueError(
            f"no raw payload for the {window.exchange} capital reduction table"
        )
    stored = {
        (row.instrument_id, row.resume_date): row
        for row in db.scalars(
            select(TradingHalt).where(
                TradingHalt.source == window.source,
                TradingHalt.resume_date >= window.start,
                TradingHalt.resume_date <= window.end,
            )
        ).all()
    }
    outcome: dict[str, Any] = {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "removed": 0,
        "outside_universe": 0,
        "rejected": len(window.rejected),
    }
    incoming: dict[tuple[int, date], TradingHaltRecord] = {}
    conflicts: list[str] = []
    for record in records:
        # A stored security outside the collect universe (delisted since) keeps
        # its row: the answer still lists it.
        instrument = instruments.get((record.exchange, record.symbol)) or db.scalar(
            select(Instrument).where(
                Instrument.exchange == record.exchange,
                Instrument.symbol == record.symbol,
            )
        )
        if instrument is None:
            outcome["outside_universe"] += 1
            continue
        checked, conflict = _check_bars(db, instrument.id, record)
        if checked is None:
            conflicts.append(str(conflict))
            continue
        if checked is not record:
            outcome["moved_past_bars"] = outcome.get("moved_past_bars", 0) + 1
        incoming[(instrument.id, record.resume_date)] = checked
    for key, row in stored.items():
        if key not in incoming:
            db.delete(row)
            outcome["removed"] += 1
    for key, record in incoming.items():
        row = stored.get(key)
        if row is not None and _stored_content(row) == _content(record):
            outcome["unchanged"] += 1
            continue
        if row is None:
            row = TradingHalt(
                instrument_id=key[0],
                source=record.source,
                resume_date=record.resume_date,
            )
            db.add(row)
            outcome["inserted"] += 1
        else:
            outcome["updated"] += 1
        row.exchange = record.exchange
        row.halt_start = record.halt_start
        row.last_trade_date = record.last_trade_date
        row.reason = record.reason
        row.reason_detail = record.reason_detail
        row.endpoint = record.endpoint
        row.data_as_of = raw.data_as_of or window.end.isoformat()
        row.collected_at = raw.collected_at
        row.raw_payload_id = raw.id
        row.details_json = dict(record.details)
    db.flush()
    for text in conflicts:
        warnings.append(f"{window.exchange} trading halts rejected: {text}")
    outcome["conflicts"] = len(conflicts)
    outcome["raw_payload_id"] = raw.id
    return outcome


def store_trading_halts(
    db: Session,
    records: Iterable[TradingHaltRecord],
    windows: Iterable[TradingHaltWindow],
    instruments: dict[tuple[str, str], Instrument],
    raw_id: Callable[[str | None], int | None],
    warnings: list[str],
) -> dict[str, Any]:
    """Rebuild each answered range's rows; per exchange and range, by outcome.

    Each range is written in its own savepoint: a failure there becomes that
    exchange's non-core warning and changes none of its rows.
    """

    records = list(records)
    result: dict[str, Any] = {}
    for window in windows:
        for text in window.rejected:
            warnings.append(f"{window.exchange} trading halts rejected: {text}")
        mine = [
            record
            for record in records
            if record.exchange == window.exchange
            and window.start <= record.resume_date <= window.end
        ]
        try:
            with db.begin_nested():
                outcome = _apply_window(db, window, mine, instruments, raw_id, warnings)
        except Exception as exc:
            warnings.append(trading_halt_warning(window.exchange, exc))
            outcome = {"failed": len(mine), "error": f"{type(exc).__name__}: {exc}"}
        outcome["range"] = [window.start.isoformat(), window.end.isoformat()]
        result[window.exchange] = outcome
    return result


def run_trading_halts(
    start: date,
    end: date | None = None,
    *,
    fetcher: Callable[..., Any] = fetch_json,
    today: date | None = None,
) -> dict[str, Any]:
    """``worker.cli trading-halts``: one request per exchange for ``start``..``end``.

    ``end`` defaults to sixty days after today, as collect asks.  The run is a
    ``trading_halts`` ingestion run; every stored instrument (any status) can
    take a row, so a past stop of a since-delisted security is kept too.
    """

    day = today or date.today()
    end = end or day + timedelta(days=TRADING_HALT_DAYS_AFTER)
    if end < start:
        raise ValueError(f"--end {end} is before --start {start}")
    with pipeline.SessionLocal() as db:
        run = IngestionRun(
            run_type=RUN_TYPE,
            source="official",
            run_date=day,
            status="running",
            records=0,
            started_at=utcnow(),
            metadata_json={},
        )
        db.add(run)
        db.flush()
        raw_ids: dict[str, int] = {}

        def fetch(exchange: str) -> Callable[[str, str | None], FetchedPayload]:
            def call(endpoint: str, data_as_of: str | None) -> FetchedPayload:
                payload = _call_fetcher(fetcher, endpoint)
                captured = capture_payload(
                    _RAW_SOURCES[exchange], endpoint, payload, data_as_of
                )
                raw_ids[captured.sha256] = pipeline._upsert_raw_payload(
                    db, run, captured
                ).id
                return captured

            return call

        warnings: list[str] = []
        records: list[TradingHaltRecord] = []
        windows: list[TradingHaltWindow] = []
        failed: dict[str, str] = {}
        for exchange in EXCHANGES:
            try:
                found, window, _captured = fetch_reduction_window(
                    fetch(exchange), exchange, start, end, data_as_of=day.isoformat()
                )
            except Exception as exc:
                warnings.append(trading_halt_warning(exchange, exc))
                failed[exchange] = f"{type(exc).__name__}: {exc}"
                continue
            records.extend(found)
            windows.append(window)
        instruments = {
            (row.exchange, row.symbol): row
            for row in db.scalars(select(Instrument)).all()
        }
        result = store_trading_halts(
            db, records, windows, instruments, raw_ids.get, warnings
        )
        for exchange, error in failed.items():
            result[exchange] = {"failed": 0, "error": error}
        failures = [
            exchange for exchange, outcome in result.items() if "failed" in outcome
        ]
        status = (
            "failed"
            if len(failures) == len(EXCHANGES)
            else "partial"
            if warnings
            else "success"
        )
        written = sum(
            int(outcome.get(name, 0) or 0)
            for outcome in result.values()
            for name in ("inserted", "updated", "removed")
        )
        run.status = status
        run.records = written
        run.error = "; ".join(warnings) or None
        run.finished_at = utcnow()
        run.metadata_json = {
            "range": [start.isoformat(), end.isoformat()],
            "exchanges": result,
            "warnings": warnings,
        }
        db.commit()
        return {
            "status": status,
            "run_id": run.id,
            "range": [start.isoformat(), end.isoformat()],
            "exchanges": result,
            "warnings": warnings,
            "records": written,
        }
