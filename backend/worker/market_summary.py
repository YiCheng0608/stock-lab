"""Store official market summaries and rebuild TWSE ones from stored raw (Issue #275).

collect writes the rows of its batch (``store_market_summaries``).
``backfill_market_summaries`` (``worker.cli market-summary``) reads the TWSE
MI_INDEX payloads already in ``raw_payloads`` and sends no request; TPEx has
no history (the highlight feed is the latest session only), so dates before
collect fetched it have no TPEx row.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import MarketSummary, RawPayload

from .sources import (
    TWSE_DAILY_HISTORY_ENDPOINT,
    MarketSummaryRecord,
    OfficialDataError,
    _is_twse_mi_index_no_data,
    market_summary_warning,
    parse_twse_market_summary,
)

# Compared on a re-collect, written on insert; exchange and trading_date are the key.
VALUE_FIELDS = (
    "index_name",
    "index_close",
    "index_change",
    "index_change_pct",
    "change_pct_method",
    "turnover",
    "turnover_scope",
    "advancers",
    "decliners",
    "unchanged",
    "limit_up",
    "limit_down",
    "unmatched",
    "not_comparable",
    "breadth_scope",
    "source",
)


def upsert_market_summary(
    db: Session,
    record: MarketSummaryRecord,
    raw: RawPayload | None,
    *,
    overwrite: bool = False,
) -> str:
    """Write one summary like the official bars: the first capture owns the row.

    A later capture with the same values leaves the row as it is; one that
    has a value where the row is null fills it; a differing value is kept
    as stored (``conflict``) unless ``overwrite`` (``--force``), which writes
    the new non-null values and points the row at the new capture.  Returns
    inserted, unchanged, filled, conflict or overwritten.
    """

    row = db.scalar(
        select(MarketSummary).where(
            MarketSummary.exchange == record.exchange,
            MarketSummary.trading_date == record.trading_date,
        )
    )
    values = {name: getattr(record, name) for name in VALUE_FIELDS}
    provenance = {
        "data_as_of": record.data_as_of,
        "collected_at": raw.collected_at if raw else datetime.utcnow(),
        "raw_payload_id": raw.id if raw else None,
    }
    if row is None:
        db.add(
            MarketSummary(
                exchange=record.exchange,
                trading_date=record.trading_date,
                **values,
                **provenance,
            )
        )
        db.flush()
        return "inserted"
    differing = [
        name
        for name, value in values.items()
        if value is not None
        and getattr(row, name) is not None
        and getattr(row, name) != value
    ]
    missing = [
        name
        for name, value in values.items()
        if value is not None and getattr(row, name) is None
    ]
    if overwrite and (differing or missing):
        for name, value in values.items():
            if value is not None:
                setattr(row, name, value)
        for name, value in provenance.items():
            setattr(row, name, value)
        db.flush()
        return "overwritten"
    for name in missing:
        setattr(row, name, values[name])
    db.flush()
    if differing:
        return "conflict"
    return "filled" if missing else "unchanged"


def store_market_summaries(
    db: Session,
    records: list[MarketSummaryRecord],
    raw_id: Callable[[str | None], int | None],
    warnings: list[str],
    *,
    start: date,
    end: date,
    overwrite: bool = False,
) -> dict[str, int]:
    """collect's write step; a failed row becomes a non-core warning.

    Each row is written in its own savepoint, so neither a bad row nor the
    other exchange's row changes the rest of the collect.
    """

    counts: dict[str, int] = {}
    for record in records:
        if not start <= record.trading_date <= end:
            continue
        try:
            with db.begin_nested():
                identifier = raw_id(record.payload_sha256)
                raw = db.get(RawPayload, identifier) if identifier else None
                outcome = upsert_market_summary(db, record, raw, overwrite=overwrite)
        except Exception as exc:
            warnings.append(
                market_summary_warning(record.exchange, record.trading_date, exc)
            )
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def _report_date(endpoint: str) -> date | None:
    query = parse_qs(urlsplit(endpoint).query)
    values = query.get("date") or []
    try:
        return datetime.strptime(values[0], "%Y%m%d").date() if values else None
    except ValueError:
        return None


def _load(raw: RawPayload) -> Any:
    if not raw.payload_path or not raw.sha256:
        raise OfficialDataError(f"raw_payloads({raw.id}) has no payload path or sha256")
    encoded = Path(raw.payload_path).read_bytes()
    if hashlib.sha256(encoded).hexdigest() != raw.sha256:
        raise OfficialDataError(f"raw_payloads({raw.id}) does not match its sha256")
    return json.loads(encoded)


def backfill_market_summaries(
    start: date, end: date, *, force: bool = False, init_schema: bool = True
) -> dict[str, Any]:
    """Rebuild TWSE summaries for ``start``..``end`` from stored MI_INDEX raw.

    Per weekday the newest stored capture of the date-scoped report is read;
    a weekday without one is ``no_raw`` and the explicit holiday response is
    ``no_data``.  No network request is made.
    """

    if end < start:
        raise ValueError("--to must not be before --from")
    if init_schema:
        init_db()
    with SessionLocal() as db:
        latest: dict[date, RawPayload] = {}
        captures = db.scalars(
            select(RawPayload)
            .where(
                RawPayload.source == "twse",
                RawPayload.endpoint.like(f"{TWSE_DAILY_HISTORY_ENDPOINT}?%"),
            )
            .order_by(RawPayload.collected_at, RawPayload.id)
        )
        for raw in captures:
            day = _report_date(raw.endpoint)
            if day is not None and start <= day <= end:
                latest[day] = raw
        dates: list[dict[str, Any]] = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                dates.append(_backfill_day(db, day, latest.get(day), force=force))
            day += timedelta(days=1)
        db.commit()
    failed = {"unreadable", "rejected"}
    return {
        "status": "partial"
        if any(item["status"] in failed for item in dates)
        else "success",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "exchange": "TWSE",
        "written": sum(
            item["status"] in {"inserted", "filled", "overwritten"} for item in dates
        ),
        "dates": dates,
    }


def _backfill_day(
    db: Session, day: date, raw: RawPayload | None, *, force: bool
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "date": day.isoformat(),
        "raw_payload_id": raw.id if raw else None,
    }
    if raw is None:
        return {**item, "status": "no_raw"}
    try:
        payload = _load(raw)
    except (OSError, ValueError, OfficialDataError) as exc:
        return {**item, "status": "unreadable", "error": f"{type(exc).__name__}: {exc}"}
    if _is_twse_mi_index_no_data(payload, raw.endpoint):
        return {**item, "status": "no_data"}
    try:
        record = parse_twse_market_summary(
            payload,
            requested_date=day,
            data_as_of=raw.data_as_of or day.isoformat(),
            payload_sha256=raw.sha256,
        )
    except OfficialDataError as exc:
        return {**item, "status": "rejected", "error": str(exc)}
    return {**item, "status": upsert_market_summary(db, record, raw, overwrite=force)}
