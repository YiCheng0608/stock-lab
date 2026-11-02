"""Fetch and store TWSE's yearly official holiday schedule (Issue #294).

The daily ``trading_calendar`` step (after collect, before analyze; its
status never changes the run status) and ``worker.cli trading-calendar``.
Each requested year is one GET of the TWSE website schedule, which unlike the
OpenAPI feed can be asked for a given year: the target's year and the next,
so a signal on the last session of a year finds the first session of the
next once TWSE publishes it.

A payload whose SHA-256 equals the endpoint's latest stored capture is not
captured again.  A valid payload replaces the year's rows when its content
differs (``added``/``changed``/``removed`` in the run metadata); every row of
the year then points at that capture.  An empty payload (``total`` 0) means
the year is not published yet and writes nothing; an empty payload for a
year that already has rows keeps them and warns.  A payload that fails
validation writes nothing and warns.  analyze reads the rows through
``app.trading_calendar``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.models import IngestionRun, RawPayload, TradingCalendarDay
from app.trading_calendar import (
    CALENDAR_EXCHANGE,
    CALENDAR_SOURCE,
    classify,
    forget,
)
from worker import pipeline
from worker.sources import (
    FetchedPayload,
    OfficialDataError,
    _call_fetcher,
    _encode_payload,
    capture_payload,
    fetch_json,
)

RUN_TYPE = "trading_calendar"
TWSE_HOLIDAY_SCHEDULE_ENDPOINT = (
    "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
)
DATE_FIELD, NAME_FIELD, DESCRIPTION_FIELD = "日期", "名稱", "說明"


def year_endpoint(year: int) -> str:
    query = urlencode({"date": f"{year}0101", "response": "json"})
    return f"{TWSE_HOLIDAY_SCHEDULE_ENDPOINT}?{query}"


@dataclass(frozen=True)
class CalendarRow:
    calendar_date: date
    kind: str
    name: str
    description: str


def parse_schedule(payload: Any, year: int) -> list[CalendarRow]:
    """The year's rows; an empty list when the year is not published yet.

    Raises OfficialDataError when the payload is not that year's schedule.
    """

    if not isinstance(payload, dict) or str(payload.get("stat", "")).lower() != "ok":
        raise OfficialDataError(f"holiday schedule {year}: stat is not ok")
    if str(payload.get("queryYear")) != str(year):
        raise OfficialDataError(
            f"holiday schedule {year}: queryYear is {payload.get('queryYear')!r}"
        )
    data = payload.get("data")
    fields = payload.get("fields")
    if not isinstance(data, list):
        raise OfficialDataError(f"holiday schedule {year}: data is not a list")
    if not data:
        return []
    if not isinstance(fields, list) or not {
        DATE_FIELD,
        NAME_FIELD,
        DESCRIPTION_FIELD,
    } <= set(fields):
        raise OfficialDataError(f"holiday schedule {year}: fields are {fields!r}")
    rows: dict[date, CalendarRow] = {}
    for values in data:
        if not isinstance(values, list) or len(values) != len(fields):
            raise OfficialDataError(f"holiday schedule {year}: malformed row")
        row = dict(zip(fields, values))
        try:
            day = date.fromisoformat(str(row[DATE_FIELD]).strip())
        except ValueError as exc:
            raise OfficialDataError(
                f"holiday schedule {year}: invalid date {row[DATE_FIELD]!r}"
            ) from exc
        if day.year != year:
            raise OfficialDataError(
                f"holiday schedule {year}: {day.isoformat()} is outside the year"
            )
        if day in rows:
            raise OfficialDataError(
                f"holiday schedule {year}: {day.isoformat()} is listed twice"
            )
        name = str(row[NAME_FIELD] or "").strip()
        description = str(row[DESCRIPTION_FIELD] or "").strip()
        if not name:
            raise OfficialDataError(
                f"holiday schedule {year}: {day.isoformat()} has no name"
            )
        rows[day] = CalendarRow(day, classify(name, description), name, description)
    return [rows[day] for day in sorted(rows)]


def _raw_row(
    db: Session, run: IngestionRun, endpoint: str, payload: Any, year: int
) -> RawPayload:
    """The endpoint's latest capture when unchanged, else a new one."""

    digest = hashlib.sha256(_encode_payload(payload)).hexdigest()
    latest = db.scalar(
        select(RawPayload)
        .where(RawPayload.source == "twse", RawPayload.endpoint == endpoint)
        .order_by(desc(RawPayload.id))
        .limit(1)
    )
    if latest is not None and latest.sha256 == digest:
        return latest
    fetched: FetchedPayload = capture_payload(
        "twse", endpoint, payload, data_as_of=str(year)
    )
    return pipeline._upsert_raw_payload(db, run, fetched)


def _apply(
    db: Session, year: int, rows: list[CalendarRow], raw: RawPayload
) -> dict[str, Any]:
    stored = {
        row.calendar_date: row
        for row in db.scalars(
            select(TradingCalendarDay).where(
                TradingCalendarDay.exchange == CALENDAR_EXCHANGE,
                TradingCalendarDay.year == year,
            )
        ).all()
    }
    if not rows:
        if stored:
            return {
                "status": "kept",
                "warning": f"holiday schedule {year} came back empty; "
                f"the {len(stored)} stored rows are kept",
            }
        return {"status": "unpublished"}
    incoming = {row.calendar_date: row for row in rows}
    added = sorted(set(incoming) - set(stored))
    removed = sorted(set(stored) - set(incoming))
    changed = sorted(
        day
        for day in set(incoming) & set(stored)
        if (stored[day].kind, stored[day].name, stored[day].description)
        != (incoming[day].kind, incoming[day].name, incoming[day].description)
    )
    if not (added or removed or changed):
        # Same content: the rows keep pointing at the capture that brought it.
        return {
            "status": "unchanged",
            "raw_payload_id": next(iter(stored.values())).raw_payload_id,
        }
    for day in removed:
        db.delete(stored[day])
    for day, row in incoming.items():
        target = stored.get(day)
        if target is None:
            target = TradingCalendarDay(
                exchange=CALENDAR_EXCHANGE, calendar_date=day, year=year
            )
            db.add(target)
        target.kind = row.kind
        target.name = row.name
        target.description = row.description
        target.source = CALENDAR_SOURCE
        target.collected_at = raw.collected_at
        target.raw_payload_id = raw.id
    db.flush()
    return {
        "status": "updated" if stored else "inserted",
        "raw_payload_id": raw.id,
        "added": [day.isoformat() for day in added],
        "changed": [day.isoformat() for day in changed],
        "removed": [day.isoformat() for day in removed],
        # A changed year rewrites every row (they all move to this capture).
        "rows_written": len(incoming) + len(removed),
        "unknown": [
            row.calendar_date.isoformat() for row in rows if row.kind == "unknown"
        ],
    }


def store_trading_calendar(
    db: Session,
    years: Iterable[int],
    *,
    run_date: date,
    fetcher: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=run_date,
        status="running",
        records=0,
        started_at=now,
        metadata_json={},
    )
    db.add(run)
    db.flush()
    results: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for year in dict.fromkeys(years):
        endpoint = year_endpoint(year)
        try:
            payload = _call_fetcher(fetcher, endpoint)
            raw = _raw_row(db, run, endpoint, payload, year)
            rows = parse_schedule(payload, year)
        except OfficialDataError as exc:
            results[str(year)] = {"status": "failed", "error": str(exc)}
            warnings.append(f"holiday schedule {year} unavailable: {exc}")
            continue
        outcome = _apply(db, year, rows, raw)
        outcome.setdefault("raw_payload_id", raw.id)
        if "warning" in outcome:
            warnings.append(outcome.pop("warning"))
        for day in outcome.get("unknown", []):
            warnings.append(
                f"holiday schedule {year}: {day} is neither closed nor a trading notice"
            )
        results[str(year)] = outcome
    forget(db)
    failed = [year for year, result in results.items() if result["status"] == "failed"]
    status = (
        "failed"
        if failed and len(failed) == len(results)
        else "partial"
        if warnings
        else "success"
    )
    records = sum(
        int(result.get("rows_written", 0) or 0) for result in results.values()
    )
    run.status = status
    run.records = records
    run.error = "; ".join(warnings) or None
    run.finished_at = utcnow()
    run.metadata_json = {
        "source": CALENDAR_SOURCE,
        "years": results,
        "warnings": warnings,
    }
    db.flush()
    return {
        "status": status,
        "run_id": run.id,
        # The daily step row keeps this as its error (schedule_runs._run_step).
        "error": run.error,
        "years": results,
        "warnings": warnings,
        "records": records,
    }


def run_trading_calendar(
    target: date | None = None,
    *,
    years: Iterable[int] | None = None,
    fetcher: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    """Store the schedules of ``years`` (default: the target's year and the next)."""

    day = target or date.today()
    wanted = list(years) if years else [day.year, day.year + 1]
    # pipeline.SessionLocal, like the other daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        result = store_trading_calendar(db, wanted, run_date=day, fetcher=fetcher)
        db.commit()
    return result
