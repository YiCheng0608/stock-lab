"""Date-scoped MOPS material-information list (``t05st02``), Issue #464.

The OpenAPI feeds ``t187ap04_L``／``mopsfin_t187ap04_O`` are snapshots of the
latest announcements; they cannot say that a session had no announcement, so
event coverage stayed ``unsupported``.  MOPS ``t05st02`` answers one calendar
date for the whole market:

- one POST with the ROC date returns every announcement of that date up to the
  time of the query, plus the previous date's announcements made after 17:30;
- each row carries 發言日期, 發言時間, 公司代號, 公司名稱, 主旨 and the market
  (``marketKind``: ``sii`` listed, ``otc`` OTC, ``rotc`` emerging, ``pub``
  public); only ``sii``／``otc`` are kept (the instrument universe);
- the list has no 說明 text (that needs one ``t05st02_detail`` request per row,
  which this module does not make), so the events it writes have no
  description.

Coverage of the query date is evidence, not inference: a successful, readable
response verifies the date (``verified_dates`` when it has ``sii``／``otc`` rows
of that date, ``empty_dates`` when it has none).  Any failure — transport,
``code`` other than 200, a missing table, a row dated outside the query date
and the day before — records the date as ``partial``; it is never presumed
empty.  The coverage keeps the query time (``fetched_at``): rows announced on
the date after the query reach the store through the next date's list.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import IngestionRun, Instrument
from worker.sources import (
    EventRecord,
    FetchedPayload,
    OfficialDataError,
    _call_fetcher,
    _disambiguate_event_titles,
    capture_payload,
    fetch_json,
    parse_roc_date,
)

MOPS_EVENT_LIST_ENDPOINT = "https://mops.twse.com.tw/mops/api/t05st02"
MOPS_EVENT_LIST_SOURCE = "MOPS t05st02 date-scoped material-information list"
RAW_SOURCE = "mops"
EVENT_SOURCE = "mops_material_information"
MARKET_EXCHANGES = {"sii": "TWSE", "otc": "TPEx"}
EXPECTED_TITLES = ("發言日期", "發言時間", "公司代號", "公司名稱", "主旨")
DENOMINATOR = "date_scoped_event_queries"
# The warning prefix is non-core (pipeline.NONCORE_WARNING_PATTERN): a missing
# event list never makes a collect partial; the date is recorded as partial.
WARNING_PREFIX = "MOPS event list unavailable"
RUN_TYPE = "event_backfill"
# One run covers at most this many calendar dates (60 sessions are about 90).
BACKFILL_MAX_DAYS = 120
# Failed dates in a row that stop an event backfill run.
ABORT_AFTER_FAILURES = 5
TAIPEI = timezone(timedelta(hours=8))

# Per-date coverage states, strongest evidence first.  ``unsupported`` is the
# snapshot feeds' state: an observation, not a date-scoped answer.
STATE_RANK = {"verified": 3, "empty": 3, "partial": 2, "unsupported": 1}


def request_body(day: date) -> dict[str, str]:
    return {
        "year": str(day.year - 1911),
        "month": f"{day.month:02d}",
        "day": f"{day.day:02d}",
    }


def _clock(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) not in {5, 6}:
        return ""
    digits = digits.zfill(6)
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"


def parse_event_list(
    payload: Any, query_date: date, *, payload_sha256: str | None = None
) -> list[EventRecord]:
    """Normalize one ``t05st02`` response; raise when it cannot be trusted."""

    if not isinstance(payload, dict) or payload.get("code") != 200:
        message = payload.get("message") if isinstance(payload, dict) else None
        raise OfficialDataError(
            f"MOPS t05st02 {query_date.isoformat()} returned "
            f"code={payload.get('code') if isinstance(payload, dict) else None!r} "
            f"message={message!r}"
        )
    result = payload.get("result")
    rows = result.get("data") if isinstance(result, dict) else None
    titles = result.get("titles") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not isinstance(titles, list):
        raise OfficialDataError(
            f"MOPS t05st02 {query_date.isoformat()} has no result table"
        )
    names = tuple(
        str(item.get("main")) if isinstance(item, dict) else "" for item in titles
    )
    if names[: len(EXPECTED_TITLES)] != EXPECTED_TITLES:
        raise OfficialDataError(
            f"MOPS t05st02 {query_date.isoformat()} columns changed: {names!r}"
        )
    allowed_dates = {query_date, query_date - timedelta(days=1)}
    records: list[EventRecord] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6 or not isinstance(row[5], dict):
            raise OfficialDataError(
                f"MOPS t05st02 {query_date.isoformat()} has a malformed row"
            )
        parameters = row[5].get("parameters")
        market = parameters.get("marketKind") if isinstance(parameters, dict) else None
        if market is None:
            raise OfficialDataError(
                f"MOPS t05st02 {query_date.isoformat()} row has no marketKind"
            )
        event_date = parse_roc_date(row[0])
        if event_date not in allowed_dates:
            raise OfficialDataError(
                f"MOPS t05st02 {query_date.isoformat()} reported 發言日期 {row[0]!r}"
            )
        exchange = MARKET_EXCHANGES.get(str(market))
        symbol = str(row[2] or "").strip()
        title = str(row[4] or "")
        if exchange is None:
            continue
        if not symbol or not title.strip():
            raise OfficialDataError(
                f"MOPS t05st02 {query_date.isoformat()} row has no code or subject"
            )
        records.append(
            EventRecord(
                symbol=symbol,
                event_date=event_date,
                event_type="material_information",
                title=title,
                description=None,
                details={
                    "發言日期": row[0],
                    "發言時間": _clock(row[1]) or row[1],
                    "公司代號": symbol,
                    "公司名稱": row[3],
                    "主旨": title,
                    "marketKind": market,
                    "serialNumber": parameters.get("serialNumber"),
                    "enterDate": parameters.get("enterDate"),
                    "query_date": query_date.isoformat(),
                },
                endpoint=MOPS_EVENT_LIST_ENDPOINT,
                exchange=exchange,
                source=EVENT_SOURCE,
                payload_sha256=payload_sha256,
            )
        )
    return _disambiguate_event_titles(records)


def date_coverage(
    query_date: date,
    events: Iterable[EventRecord] | None,
    *,
    fetched_at: datetime | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Coverage of one query date: verified, verified-empty or partial."""

    day = query_date.isoformat()
    observed = sorted({item.event_date.isoformat() for item in events or []})
    base = {
        "denominator": DENOMINATOR,
        "query_date": day,
        "markets": sorted(MARKET_EXCHANGES),
        "source": MOPS_EVENT_LIST_SOURCE,
        "endpoint": MOPS_EVENT_LIST_ENDPOINT,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "verified_dates": [],
        "empty_dates": [],
        "unsupported_dates": [],
        "partial_dates": [],
        "observed_event_dates": observed,
    }
    if error is not None:
        return {**base, "status": "partial", "partial_dates": [day], "reason": error}
    if day in observed:
        return {**base, "status": "complete", "verified_dates": [day], "reason": None}
    return {
        **base,
        "status": "verified_empty",
        "empty_dates": [day],
        "reason": "MOPS answered the date with no listed/OTC announcement",
    }


def fetch_date(
    day: date, fetcher: Callable[..., Any] = fetch_json
) -> tuple[list[EventRecord], list[FetchedPayload], dict[str, Any], list[str]]:
    """Fetch and parse one date; a failure is a partial date, never an empty one."""

    try:
        payload = _call_fetcher(
            fetcher,
            MOPS_EVENT_LIST_ENDPOINT,
            method="POST",
            json_body=request_body(day),
        )
    except OfficialDataError as exc:
        error = f"{WARNING_PREFIX}: {day.isoformat()}: {exc}"
        return [], [], date_coverage(day, None, error=error), [error]
    captured = capture_payload(
        RAW_SOURCE, MOPS_EVENT_LIST_ENDPOINT, payload, day.isoformat()
    )
    try:
        events = parse_event_list(payload, day, payload_sha256=captured.sha256)
    except OfficialDataError as exc:
        error = f"{WARNING_PREFIX}: {day.isoformat()}: {exc}"
        return [], [captured], date_coverage(day, None, error=error), [error]
    return (
        events,
        [captured],
        date_coverage(day, events, fetched_at=captured.collected_at),
        [],
    )


# --- per-date coverage state ------------------------------------------------


def coverage_state(item: dict[str, Any] | None, day: date) -> str:
    """State of ``day`` in one coverage record (``unqueried`` when absent)."""

    if not item:
        return "unqueried"
    key = day.isoformat()
    queried = item.get("query_date")
    if queried and str(queried)[:10] != key:
        # A dated answer describes its own query date only; it is never read
        # as evidence for the date it happens to be stored under.
        return "unqueried"

    def dates(name: str) -> set[str]:
        return {str(value)[:10] for value in item.get(name, []) or []}

    if key in dates("empty_dates"):
        return "empty"
    if key in dates("verified_dates"):
        return "verified"
    if key in dates("partial_dates"):
        return "partial"
    if key in dates("unsupported_dates"):
        return "unsupported"
    status = str(item.get("status") or "")
    if status == "verified_empty":
        return "empty"
    if status == "complete":
        return "verified"
    if status == "partial":
        return "partial"
    return "unsupported"


def stored_event_manifest(db: Session) -> dict[str, dict[str, Any]]:
    """Best stored coverage record per date across collect/backfill runs.

    Runs are read oldest first; a record replaces the kept one unless it is
    weaker evidence (a later snapshot ``unsupported`` or a failed ``partial``
    never hides an earlier verified answer).
    """

    runs = db.scalars(
        select(IngestionRun)
        .where(
            IngestionRun.source == "official",
            IngestionRun.run_type.in_({"collect", "backfill", RUN_TYPE}),
        )
        .order_by(IngestionRun.id)
    ).all()
    manifest: dict[str, dict[str, Any]] = {}

    def keep(day: str, coverage: Any) -> None:
        if not isinstance(coverage, dict) or not coverage:
            return
        try:
            parsed = date.fromisoformat(day[:10])
        except ValueError:
            return
        new_rank = STATE_RANK.get(coverage_state(coverage, parsed), 0)
        old = manifest.get(parsed.isoformat())
        old_rank = STATE_RANK.get(coverage_state(old, parsed), 0) if old else -1
        if new_rank >= old_rank:
            manifest[parsed.isoformat()] = dict(coverage)

    def keyed(day: Any, coverage: Any) -> None:
        # A dated answer is keyed by its own query date, not by the run's
        # data_as_of (which can be an earlier session, e.g. months_back).
        if isinstance(coverage, dict) and coverage.get("query_date"):
            day = coverage["query_date"]
        if day:
            keep(str(day), coverage)

    for run in runs:
        metadata = run.metadata_json or {}
        if run.run_type in {"backfill", RUN_TYPE}:
            for day, item in (metadata.get("coverage_manifest") or {}).items():
                if isinstance(item, dict):
                    keyed(day, item.get("event_coverage"))
        else:
            keyed(run.data_as_of or run.run_date, metadata.get("event_coverage"))
            for day, coverage in (metadata.get("event_gap_coverage") or {}).items():
                keyed(day, coverage)
    return manifest


def event_coverage_states(db: Session, days: Iterable[date]) -> dict[date, str]:
    """Per date: ``verified``, ``empty``, ``partial`` or ``unqueried``.

    For the hot-group catalyst (#453): only ``verified`` and ``empty`` are
    date-scoped answers.  A snapshot-only date (``unsupported``) has no
    date-scoped query and is reported as ``unqueried``.

    Each call reads every collect/backfill run's metadata once; pass all the
    dates of a window in one call rather than calling it per date.
    """

    return states_from_manifest(stored_event_manifest(db), days)


def states_from_manifest(
    manifest: dict[str, dict[str, Any]], days: Iterable[date]
) -> dict[date, str]:
    result: dict[date, str] = {}
    for day in days:
        state = coverage_state(manifest.get(day.isoformat()), day)
        result[day] = "unqueried" if state == "unsupported" else state
    return result


# --- calendar dates the daily list did not answer ---------------------------

# The dated list of D carries D−1's announcements after 17:30, so a date's
# evening rows arrive with the next calendar date's query.  daily runs on
# weekdays only: Friday's (and a holiday eve's) evening rows sit in the
# Saturday (holiday) list.  collect therefore also queries the unanswered
# calendar dates between the last answered date and the score date.
GAP_LOOKBACK_DAYS = 14


def gap_dates(db: Session, score_date: date) -> list[date]:
    """Unanswered dates after the first answered one in the lookback window.

    Partial (failed) dates are retried.  With no answered date in the window
    there is no dated history to continue; ``events backfill`` owns that.
    """

    window = [
        score_date - timedelta(days=offset)
        for offset in range(GAP_LOOKBACK_DAYS, 0, -1)
    ]
    states = states_from_manifest(stored_event_manifest(db), window)
    answered = [day for day in window if states[day] in {"verified", "empty"}]
    if not answered:
        return []
    return [
        day
        for day in window
        if day > answered[0] and states[day] not in {"verified", "empty"}
    ]


def fill_gap_dates(
    db: Session,
    run: IngestionRun,
    score_date: date,
    fetcher: Callable[..., Any],
    instruments: dict[tuple[str, str], Instrument],
) -> dict[str, Any]:
    """Query ``gap_dates`` inside a collect run; raw payloads join that run.

    Requests are spaced by the MOPS host interval in ``fetch_json``.
    """

    from worker import pipeline

    coverage_by_date: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    written = 0
    for day in gap_dates(db, score_date):
        events, payloads, coverage, day_warnings = fetch_date(day, fetcher)
        raw_ids = {
            payload.sha256: pipeline._upsert_raw_payload(db, run, payload).id
            for payload in payloads
        }
        for event in events:
            if (event.exchange, event.symbol) in instruments:
                pipeline._upsert_event(
                    db, event, instruments, raw_ids.get(event.payload_sha256)
                )
                written += 1
        record_quality(db, day, coverage, events)
        coverage_by_date[day.isoformat()] = coverage
        warnings.extend(day_warnings)
        db.flush()
    return {
        "dates": sorted(coverage_by_date),
        "coverage": coverage_by_date,
        "events_written": written,
        "warnings": warnings,
    }


# --- event backfill run -----------------------------------------------------


def _taipei_day(value: datetime) -> date:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(TAIPEI).date()


def backfill_events(
    db: Session,
    *,
    start: date,
    end: date,
    fetcher: Callable[..., Any] = fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 3.0,
) -> dict[str, Any]:
    """Query every calendar date in ``[start, end]`` and store events + coverage.

    One ``event_backfill`` ingestion run; ``coverage_manifest`` holds each
    date's coverage (read by ``backfill.coverage_report``).  Re-running is
    idempotent: events upsert on their unique key and the strongest coverage
    per date wins.  Dates after today (Taipei) and ranges longer than
    ``BACKFILL_MAX_DAYS`` are refused; ``ABORT_AFTER_FAILURES`` failed dates
    in a row stop the run (the source is likely blocking).  Each date is
    committed, so an interrupted run keeps the dates it finished.
    """

    from worker import pipeline

    if start > end:
        raise ValueError("start must be on or before end")
    today = _taipei_day(utcnow())
    if end > today:
        raise ValueError(f"end {end.isoformat()} is after today {today.isoformat()}")
    if (end - start).days + 1 > BACKFILL_MAX_DAYS:
        raise ValueError(
            f"{(end - start).days + 1} calendar dates exceed the "
            f"{BACKFILL_MAX_DAYS}-date limit; split the range"
        )
    now = utcnow()
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=now.date(),
        status="running",
        started_at=now,
        data_as_of=end.isoformat(),
        metadata_json={"start": start.isoformat(), "end": end.isoformat()},
    )
    db.add(run)
    db.flush()
    instruments = {
        (item.exchange, item.symbol): item for item in db.scalars(select(Instrument))
    }
    db.commit()
    manifest: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    stored = skipped = failures_in_a_row = 0
    aborted: str | None = None

    def summarize(status: str) -> None:
        states = {
            key: coverage_state(item["event_coverage"], date.fromisoformat(key))
            for key, item in manifest.items()
        }
        run.status = status
        run.records = stored
        run.metadata_json = {
            **run.metadata_json,
            "coverage_manifest": manifest,
            "warnings": warnings,
            "aborted": aborted,
            "events_written": stored,
            "events_outside_universe": skipped,
            "verified_dates": sorted(k for k, v in states.items() if v == "verified"),
            "empty_dates": sorted(k for k, v in states.items() if v == "empty"),
            "partial_dates": sorted(k for k, v in states.items() if v == "partial"),
        }

    day = start
    try:
        while day <= end:
            if day != start:
                sleep(interval_seconds)
            events, payloads, coverage, day_warnings = fetch_date(day, fetcher)
            raw_ids = {
                payload.sha256: pipeline._upsert_raw_payload(db, run, payload).id
                for payload in payloads
            }
            for event in events:
                if (event.exchange, event.symbol) not in instruments:
                    skipped += 1
                    continue
                pipeline._upsert_event(
                    db, event, instruments, raw_ids.get(event.payload_sha256)
                )
                stored += 1
            manifest[day.isoformat()] = {"event_coverage": coverage}
            warnings.extend(day_warnings)
            record_quality(db, day, coverage, events)
            failures_in_a_row = failures_in_a_row + 1 if day_warnings else 0
            summarize("running")
            db.commit()
            if failures_in_a_row >= ABORT_AFTER_FAILURES:
                aborted = (
                    f"stopped after {failures_in_a_row} failed dates in a row "
                    f"at {day.isoformat()}"
                )
                break
            day += timedelta(days=1)
    except Exception as exc:
        db.rollback()
        # The failing date's writes were rolled back; so is its coverage.
        manifest.pop(day.isoformat(), None)
        aborted = f"error at {day.isoformat()}: {exc}"
        summarize("failed")
        run.error = aborted
        run.finished_at = utcnow()
        db.commit()
        raise
    summarize("partial" if warnings or aborted else "success")
    run.error = aborted
    run.finished_at = utcnow()
    return {
        "status": run.status,
        "run_id": run.id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "queried_dates": len(manifest),
        "verified_dates": len(run.metadata_json["verified_dates"]),
        "empty_dates": len(run.metadata_json["empty_dates"]),
        "partial_dates": run.metadata_json["partial_dates"],
        "aborted": aborted,
        "events_written": stored,
        "events_outside_universe": skipped,
        "warnings": warnings,
    }


def record_quality(
    db: Session, day: date, coverage: dict[str, Any], events: list[EventRecord]
) -> None:
    """``mops_events`` quality per exchange, never downgrading a verified date."""

    from app.models import DataQuality
    from worker import pipeline

    state = coverage_state(coverage, day)
    for exchange in ("TWSE", "TPEx"):
        existing = db.scalar(
            select(DataQuality).where(
                DataQuality.entity_type == "mops_events",
                DataQuality.entity_key == exchange,
                DataQuality.as_of_date == day,
            )
        )
        if (
            existing is not None
            and existing.status == "complete"
            and state not in {"verified", "empty"}
        ):
            continue
        complete = state in {"verified", "empty"}
        pipeline._upsert_quality(
            db,
            "mops_events",
            exchange,
            day,
            "complete" if complete else "partial",
            [] if complete else ["events"],
            {
                # Rows of the dated list only: a collect batch also carries
                # the snapshot feed's copy of the same announcements.
                "records": sum(
                    item.exchange == exchange
                    and item.event_date == day
                    and item.endpoint == MOPS_EVENT_LIST_ENDPOINT
                    for item in events
                ),
                "endpoint": MOPS_EVENT_LIST_ENDPOINT,
                "coverage": coverage,
            },
            source=exchange.lower(),
        )


def run_event_backfill(start: date, end: date) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            result = backfill_events(db, start=start, end=end)
        except ValueError as exc:
            # Refused before any request (range, future date).
            db.rollback()
            return {"status": "failed", "error": str(exc)}
        db.commit()
        return result
