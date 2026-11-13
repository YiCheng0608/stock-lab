"""Re-apply stored institutional captures with the later-capture rule (Issue #387).

Until #387, a collect kept the first stored institutional values and only
recorded a later, revised capture of the same official file as a value
conflict.  This replays the stored TWSE T86 and TPEx institutional captures of
a date range in capture order through the same chip upsert as collect, so each
row ends at the values of its latest capture.  Nothing is fetched and only
existing chip rows change.  With ``apply`` every replaced value is recorded,
with its old value and both raw ids, on one ``chip_revision`` ingestion run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.raw_paths import payload_file
from app.clock import utcnow
from app.models import ChipSnapshot, IngestionRun, Instrument, RawPayload
from worker import pipeline
from worker.sources import (
    TPEX_CHIP_ENDPOINT,
    TPEX_CHIP_HISTORY_ENDPOINT,
    TPEX_MARGIN_ENDPOINT,
    TPEX_MARGIN_HISTORY_ENDPOINT,
    TWSE_CHIP_ENDPOINT,
    TWSE_MARGIN_HISTORY_ENDPOINT,
    OfficialDataError,
    _require_reported_date,
    parse_tpex_institutional_rows,
    parse_tpex_margin_rows,
    parse_twse_institutional_rows,
    parse_twse_margin_rows,
)

RUN_TYPE = "chip_revision"
REVISION_VERSION = "chip_revision_v1"
# The TPEx OpenAPI table is the current session's file since Issue #579; the
# same parser reads both shapes.
PARSERS = {
    TWSE_CHIP_ENDPOINT: parse_twse_institutional_rows,
    TPEX_CHIP_HISTORY_ENDPOINT: parse_tpex_institutional_rows,
    TPEX_CHIP_ENDPOINT: parse_tpex_institutional_rows,
}


class RevisionError(Exception):
    """The stored evidence is inconsistent; nothing is written."""


def _captures(db: Session, start: date, end: date) -> list[RawPayload]:
    """The range's institutional captures, oldest capture first."""

    rows = db.scalars(
        select(RawPayload)
        .where(
            RawPayload.data_as_of >= start.isoformat(),
            RawPayload.data_as_of <= end.isoformat(),
        )
        .order_by(RawPayload.collected_at, RawPayload.id)
    ).all()
    return [row for row in rows if (row.endpoint or "").split("?", 1)[0] in PARSERS]


def _load(capture: RawPayload) -> Any:
    """The capture's payload; None when it reports another date (as
    ``chip_provenance._load``); RevisionError when the file is not that capture.

    A file of another session says nothing about its requested date: a TPEx
    OpenAPI table captured before it was updated (Issue #579) is kept as raw
    under the requested date while collect read the website report.
    """

    content = payload_file(capture.payload_path).read_bytes()
    if hashlib.sha256(content).hexdigest() != capture.sha256:
        raise RevisionError(
            f"raw payload {capture.id} does not match its SHA-256: {capture.payload_path}"
        )
    payload = json.loads(content.decode("utf-8"))
    try:
        _require_reported_date(
            payload,
            date.fromisoformat((capture.data_as_of or "")[:10]),
            capture.endpoint.split("?", 1)[0],
        )
    except OfficialDataError:
        return None
    return payload


def revise_institutional(
    db: Session, start: date, end: date, *, apply: bool = False
) -> dict[str, Any]:
    """Replay the range's captures; write and commit only with ``apply``.

    A capture whose file is missing or unreadable is skipped and listed (the
    result is ``partial``); one that reports another date is skipped and
    listed in ``other_session_captures`` without making it partial; a file
    that does not match its SHA-256 stops the whole run before anything is
    written.
    """

    captures = _captures(db, start, end)
    payloads: dict[int, Any] = {}
    unreadable: list[dict[str, Any]] = []
    other_session: list[int] = []
    for capture in captures:
        try:
            payload = _load(capture)
        except (OSError, ValueError, OfficialDataError) as exc:
            unreadable.append({"raw_payload_id": capture.id, "error": str(exc)})
            continue
        if payload is None:
            other_session.append(capture.id)
        else:
            payloads[capture.id] = payload
    instruments = {
        (row.exchange, row.symbol): row for row in db.scalars(select(Instrument))
    }
    revisions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    replayed: list[int] = []
    for capture in captures:
        if capture.id not in payloads:
            continue
        trading_date = date.fromisoformat((capture.data_as_of or "")[:10])
        records = PARSERS[capture.endpoint.split("?", 1)[0]](
            payloads[capture.id],
            trading_date=trading_date,
            data_as_of=trading_date.isoformat(),
            payload_sha256=capture.sha256,
        )
        for record in records:
            pipeline._upsert_official_chip(
                db,
                record,
                instruments,
                capture.id,
                overwrite=False,
                conflicts=conflicts,
                fills=fills,
                revisions=revisions,
                create=False,
            )
        db.flush()
        replayed.append(capture.id)
    result: dict[str, Any] = {
        "status": "partial" if unreadable else "success",
        "version": REVISION_VERSION,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "applied": apply,
        "captures_replayed": len(replayed),
        "unreadable_captures": unreadable,
        "other_session_captures": other_session,
        "revised_rows": len(revisions),
        "revised_dates": sorted({item["trading_date"] for item in revisions}),
        "value_conflicts": len(conflicts),
        "value_fills": len(fills),
    }
    if not apply:
        db.rollback()
        result["value_revision_rows"] = revisions
        return result
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=now.replace(tzinfo=timezone.utc).astimezone(pipeline.TAIPEI).date(),
        status=result["status"],
        records=len(revisions),
        data_as_of=end.isoformat(),
        metadata_json={
            **result,
            "raw_payload_ids": replayed,
            "value_revision_rows": revisions,
            "value_conflict_samples": conflicts[
                : pipeline.MAX_RECORDED_VALUE_CONFLICTS
            ],
            "value_fill_groups": pipeline._value_fill_groups(fills),
        },
        started_at=now,
        finished_at=now,
    )
    db.add(run)
    db.commit()
    result["run_id"] = run.id
    return result


def run_revise_institutional(
    start: date, end: date, *, apply: bool = False
) -> dict[str, Any]:
    with pipeline.SessionLocal() as db:
        try:
            return revise_institutional(db, start, end, apply=apply)
        except RevisionError as exc:
            db.rollback()
            return {"status": "failed", "error": str(exc), "applied": False}


SHORT_BALANCE_RUN_TYPE = "short_balance_fill"
SHORT_BALANCE_VERSION = "short_balance_fill_v1"
MARGIN_PARSERS = {
    TWSE_MARGIN_HISTORY_ENDPOINT: parse_twse_margin_rows,
    TPEX_MARGIN_HISTORY_ENDPOINT: parse_tpex_margin_rows,
    TPEX_MARGIN_ENDPOINT: parse_tpex_margin_rows,
}
MAX_SHORT_BALANCE_SAMPLES = 50


def _short_balance_rows(
    db: Session, raw_payload_id: int, start: date | None, end: date | None
) -> list[Any]:
    query = (
        select(
            ChipSnapshot.id,
            ChipSnapshot.trading_date,
            Instrument.symbol,
            ChipSnapshot.margin_balance,
            ChipSnapshot.margin_change,
        )
        .join(Instrument, Instrument.id == ChipSnapshot.instrument_id)
        .where(
            ChipSnapshot.margin_raw_payload_id == raw_payload_id,
            ChipSnapshot.short_balance.is_(None),
        )
    )
    if start is not None:
        query = query.where(ChipSnapshot.trading_date >= start)
    if end is not None:
        query = query.where(ChipSnapshot.trading_date <= end)
    return list(db.execute(query).all())


def fill_short_balance(
    db: Session,
    start: date | None = None,
    end: date | None = None,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Fill empty ``short_balance`` from each row's own margin capture (Issue #662).

    Until #662 collect read only the margin columns of the official margin
    file, though the same file has the short-sale balance.  For every chip row
    with an empty ``short_balance`` and a margin group, this parses the stored
    capture the row cites (``margin_raw_payload_id``) and writes its short-sale
    balance (融券今日餘額, 張).  Nothing is fetched and nothing else changes:
    a row whose stored margin values differ from that capture's, or whose
    capture has no short-sale value for it, is skipped and counted.  A capture
    that cannot be read or does not match its SHA-256 is skipped and listed,
    and the result is ``partial``; one that reports another date is listed in
    ``other_session_captures``.  With ``apply`` each capture is committed on its
    own and one ``short_balance_fill`` ingestion run is recorded; a rerun only
    reads rows that are still empty.
    """

    query = select(ChipSnapshot.margin_raw_payload_id).where(
        ChipSnapshot.short_balance.is_(None),
        ChipSnapshot.margin_raw_payload_id.is_not(None),
    )
    if start is not None:
        query = query.where(ChipSnapshot.trading_date >= start)
    if end is not None:
        query = query.where(ChipSnapshot.trading_date <= end)
    raw_ids = set(db.scalars(query.distinct()))
    captures = sorted(
        (db.get(RawPayload, raw_id) for raw_id in raw_ids),
        key=lambda capture: (capture.data_as_of or "", capture.id),
    )
    counts = {
        "rows_filled": 0,
        "rows_margin_mismatch": 0,
        "rows_no_short_value": 0,
        "rows_not_in_capture": 0,
        "rows_capture_skipped": 0,
    }
    unreadable: list[dict[str, Any]] = []
    other_session: list[int] = []
    other_endpoint: list[int] = []
    samples: list[dict[str, Any]] = []
    filled_dates: set[str] = set()
    started = utcnow()
    for capture in captures:
        rows = _short_balance_rows(db, capture.id, start, end)
        parser = MARGIN_PARSERS.get((capture.endpoint or "").split("?", 1)[0])
        payload = None
        if parser is None:
            other_endpoint.append(capture.id)
        else:
            try:
                payload = _load(capture)
            except (OSError, ValueError, OfficialDataError, RevisionError) as exc:
                unreadable.append(
                    {
                        "raw_payload_id": capture.id,
                        "data_as_of": capture.data_as_of,
                        "error": str(exc),
                    }
                )
            else:
                if payload is None:
                    other_session.append(capture.id)
        if parser is None or payload is None:
            counts["rows_capture_skipped"] += len(rows)
            continue
        trading_date = date.fromisoformat((capture.data_as_of or "")[:10])
        records = {
            record.symbol: record
            for record in parser(
                payload,
                trading_date=trading_date,
                data_as_of=trading_date.isoformat(),
                payload_sha256=capture.sha256,
            )
        }
        updates: list[dict[str, Any]] = []
        for row_id, row_date, symbol, margin_balance, margin_change in rows:
            record = records.get(symbol)
            short = (
                None if record is None else pipeline._safe_float(record.short_balance)
            )
            if record is None:
                reason = "rows_not_in_capture"
            elif (
                pipeline._safe_float(record.margin_balance) != margin_balance
                or pipeline._safe_float(record.margin_change) != margin_change
            ):
                reason = "rows_margin_mismatch"
            elif short is None:
                reason = "rows_no_short_value"
            else:
                updates.append({"id": row_id, "short_balance": short})
                continue
            counts[reason] += 1
            if len(samples) < MAX_SHORT_BALANCE_SAMPLES:
                samples.append(
                    {
                        "symbol": symbol,
                        "trading_date": row_date.isoformat(),
                        "raw_payload_id": capture.id,
                        "reason": reason,
                    }
                )
        if updates:
            db.execute(update(ChipSnapshot), updates)
            counts["rows_filled"] += len(updates)
            filled_dates.add(trading_date.isoformat())
        if apply:
            db.commit()
    result: dict[str, Any] = {
        "status": "partial"
        if unreadable or counts["rows_margin_mismatch"]
        else "success",
        "version": SHORT_BALANCE_VERSION,
        "start_date": start.isoformat() if start else None,
        "end_date": end.isoformat() if end else None,
        "applied": apply,
        "captures": len(captures),
        **counts,
        "rows_skipped": sum(counts.values()) - counts["rows_filled"],
        "filled_dates": len(filled_dates),
        "first_filled_date": min(filled_dates, default=None),
        "last_filled_date": max(filled_dates, default=None),
        "unreadable_captures": unreadable,
        "other_session_captures": other_session,
        "other_endpoint_captures": other_endpoint,
        "skipped_samples": samples,
    }
    if not apply:
        db.rollback()
        return result
    run = IngestionRun(
        run_type=SHORT_BALANCE_RUN_TYPE,
        source="official",
        run_date=started.replace(tzinfo=timezone.utc)
        .astimezone(pipeline.TAIPEI)
        .date(),
        status=result["status"],
        records=counts["rows_filled"],
        data_as_of=result["last_filled_date"],
        metadata_json={
            **result,
            "raw_payload_ids": [capture.id for capture in captures],
        },
        started_at=started,
        finished_at=utcnow(),
    )
    db.add(run)
    db.commit()
    result["run_id"] = run.id
    return result


def run_fill_short_balance(
    start: date | None = None, end: date | None = None, *, apply: bool = False
) -> dict[str, Any]:
    with pipeline.SessionLocal() as db:
        return fill_short_balance(db, start, end, apply=apply)
