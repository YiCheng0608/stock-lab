"""Fetch a completed session's institutional files once more (Issue #396).

The exchanges revise the day's institutional (三大法人) file after it is first
published.  When the 18:30 daily already finished as ``success``, the 21:30
trigger has nothing else to fetch, so it asks for the two institutional files
again, one TWSE T86 request and one TPEx daily-trade request, and applies them
through collect's chip upsert: a later capture replaces differing
institutional values of the stored rows (Issue #387), equal values stay as
they are, and the margin, OHLCV and event data are not requested.

Only existing chip rows change (``create=False``): the 18:30 collect decided
which instruments have a row.  Each target date is refetched at most once:
after a ``success`` refetch a later invocation reuses it without a request.
Every capture and every replaced value is kept on one ``institutional_refetch``
ingestion run, so ``chips revise`` can replay the capture later.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from sqlalchemy import select

from app.clock import utcnow
from app.models import IngestionRun, Instrument
from worker import pipeline
from worker.sources import (
    TPEX_CHIP_HISTORY_ENDPOINT,
    TWSE_CHIP_ENDPOINT,
    FetchedPayload,
    OfficialDataError,
    OfficialMarketDataAdapter,
    _require_reported_date,
    parse_tpex_institutional_rows,
    parse_twse_institutional_rows,
)

RUN_TYPE = "institutional_refetch"
# Per exchange: the file's endpoint (for the reported-date check) and parser.
FILES: dict[str, tuple[str, Callable[..., list[Any]]]] = {
    "TWSE": (TWSE_CHIP_ENDPOINT, parse_twse_institutional_rows),
    "TPEx": (TPEX_CHIP_HISTORY_ENDPOINT, parse_tpex_institutional_rows),
}


def request_key(target: date) -> str:
    return f"{RUN_TYPE}:{target.isoformat()}"


def _summary(run: IngestionRun, *, reused: bool) -> dict[str, Any]:
    metadata = dict(run.metadata_json or {})
    return {
        "status": run.status,
        "date": run.run_date.isoformat() if run.run_date else None,
        "run_id": run.id,
        "idempotent_reuse": reused,
        "requests": 0 if reused else int(metadata.get("requests", 0) or 0),
        "records": run.records,
        "revised_rows": int(metadata.get("revised_rows", 0) or 0),
        "unchanged_rows": int(metadata.get("unchanged_rows", 0) or 0),
        "value_fills": int(metadata.get("value_fills", 0) or 0),
        "exchanges": metadata.get("exchanges", {}),
        "error": run.error,
    }


def refetch_institutional(
    target: date, *, adapter: OfficialMarketDataAdapter | None = None
) -> dict[str, Any]:
    """Request both institutional files of ``target`` and revise the stored rows.

    ``success`` needs both files; one failed file is ``partial`` and both
    ``failed``.  A failed file's error stays on the run, the other file is
    still applied, and a later invocation tries the date again.
    """

    key = request_key(target)
    with pipeline.SessionLocal() as db:
        run = db.scalar(select(IngestionRun).where(IngestionRun.request_key == key))
        if run is not None and run.status == "success":
            return _summary(run, reused=True)
        now = utcnow()
        if run is None:
            run = IngestionRun(run_type=RUN_TYPE, request_key=key)
            db.add(run)
        run.source = "official"
        run.run_date = target
        run.status = "running"
        run.records = 0
        run.error = None
        run.data_as_of = target.isoformat()
        run.started_at = now
        run.finished_at = None
        db.commit()

        try:
            _apply(db, run, target, adapter or OfficialMarketDataAdapter())
        except Exception as exc:  # the run must not stay running
            db.rollback()
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"[:500]
            run.finished_at = utcnow()
            db.commit()
        return _summary(run, reused=False)


def _apply(
    db: Any, run: IngestionRun, target: date, active: OfficialMarketDataAdapter
) -> None:
    sides = {"TWSE": active.twse, "TPEx": active.tpex}
    captures: dict[str, tuple[FetchedPayload, int]] = {}
    exchanges: dict[str, dict[str, Any]] = {}
    requests = 0
    for exchange, side in sides.items():
        requests += 1
        try:
            payload = side.fetch_institutional_file(target)
        except OfficialDataError as exc:
            exchanges[exchange] = {"status": "failed", "error": str(exc)}
            continue
        raw = pipeline._upsert_raw_payload(db, run, payload)
        captures[exchange] = (payload, raw.id)
        exchanges[exchange] = {"status": "fetched", "raw_payload_id": raw.id}
    # Keep the captures even when parsing or an upsert fails below.
    db.commit()

    instruments = {
        (row.exchange, row.symbol): row for row in db.scalars(select(Instrument))
    }
    revisions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    matched = 0
    for exchange, (payload, raw_id) in captures.items():
        endpoint, parse = FILES[exchange]
        item = exchanges[exchange]
        try:
            _require_reported_date(payload.payload, target, endpoint)
            records = parse(
                payload.payload,
                trading_date=target,
                data_as_of=target.isoformat(),
                payload_sha256=payload.sha256,
            )
        except OfficialDataError as exc:
            item.update(status="failed", error=str(exc))
            continue
        if not records:
            item.update(status="failed", error="the file returned no rows")
            continue
        before = len(revisions)
        rows = 0
        for record in records:
            rows += int(
                pipeline._upsert_official_chip(
                    db,
                    record,
                    instruments,
                    raw_id,
                    overwrite=False,
                    conflicts=conflicts,
                    fills=fills,
                    revisions=revisions,
                    create=False,
                )
            )
        matched += rows
        item.update(
            status="success",
            file_rows=len(records),
            stored_rows=rows,
            revised_rows=len(revisions) - before,
        )
    failed = [name for name, item in exchanges.items() if item["status"] != "success"]
    if not failed:
        status = "success"
    elif len(failed) == len(exchanges):
        status = "failed"
    else:
        status = "partial"
    run.status = status
    run.records = len(revisions)
    run.error = (
        "; ".join(f"{name}: {exchanges[name].get('error')}" for name in failed) or None
    )
    run.finished_at = utcnow()
    run.metadata_json = {
        "requests": requests,
        "exchanges": exchanges,
        "raw_payload_ids": [raw_id for _payload, raw_id in captures.values()],
        "revised_rows": len(revisions),
        # A stored row is either revised, filled (a blank value) or unchanged.
        "unchanged_rows": matched - len(revisions) - len(fills),
        # Every replaced value with its old value and both raw ids, as
        # collect records them (Issue #387).
        "value_revision_rows": revisions,
        "value_conflicts": len(conflicts),
        "value_conflict_samples": conflicts[: pipeline.MAX_RECORDED_VALUE_CONFLICTS],
        "value_fills": len(fills),
        "value_fill_groups": pipeline._value_fill_groups(fills),
    }
    db.commit()
