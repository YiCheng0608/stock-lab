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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.raw_paths import payload_file
from app.clock import utcnow
from app.models import IngestionRun, Instrument, RawPayload
from worker import pipeline
from worker.sources import (
    TPEX_CHIP_HISTORY_ENDPOINT,
    TWSE_CHIP_ENDPOINT,
    OfficialDataError,
    _require_reported_date,
    parse_tpex_institutional_rows,
    parse_twse_institutional_rows,
)

RUN_TYPE = "chip_revision"
REVISION_VERSION = "chip_revision_v1"
PARSERS = {
    TWSE_CHIP_ENDPOINT: parse_twse_institutional_rows,
    TPEX_CHIP_HISTORY_ENDPOINT: parse_tpex_institutional_rows,
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
    """The capture's payload; RevisionError when the file is not that capture."""

    content = payload_file(capture.payload_path).read_bytes()
    if hashlib.sha256(content).hexdigest() != capture.sha256:
        raise RevisionError(
            f"raw payload {capture.id} does not match its SHA-256: {capture.payload_path}"
        )
    payload = json.loads(content.decode("utf-8"))
    _require_reported_date(
        payload,
        date.fromisoformat((capture.data_as_of or "")[:10]),
        capture.endpoint.split("?", 1)[0],
    )
    return payload


def revise_institutional(
    db: Session, start: date, end: date, *, apply: bool = False
) -> dict[str, Any]:
    """Replay the range's captures; write and commit only with ``apply``.

    A capture whose file is missing or unreadable is skipped and listed (the
    result is ``partial``); a file that does not match its SHA-256 stops the
    whole run before anything is written.
    """

    captures = _captures(db, start, end)
    payloads: dict[int, Any] = {}
    unreadable: list[dict[str, Any]] = []
    for capture in captures:
        try:
            payloads[capture.id] = _load(capture)
        except (OSError, ValueError, OfficialDataError) as exc:
            unreadable.append({"raw_payload_id": capture.id, "error": str(exc)})
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
