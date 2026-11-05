"""Read-only helpers for verified official market-session coverage.

The product has two different coverage baselines:

* a bounded backfill manifest, which is an explicit audit of requested
  sessions; and
* an official snapshot, which may be the only evidence available before a
  backfill has ever been run.

This module keeps the latter conservative.  A session is inferred from a
persisted TAIEX bar with valid official provenance, or from a persisted
date-scoped TWSE MI_INDEX payload linked to a successful/partial official run.
An arbitrary weekday, a stock bar by itself, or a wrong-date payload never
becomes a verified TAIEX session.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from .models import IngestionRun, Instrument, MarketBar, RawPayload, ScheduleRun
from .raw_paths import payload_file
from .decision_market_reads import read_market_date, read_market_source
from worker.sources import parse_twse_taiex_from_all_daily_payload


DAILY_JOB = "daily"
TAIPEI_UTC_OFFSET = timedelta(hours=8)


def collect_states(db: Session, start_date: date, end_date: date) -> dict[date, str]:
    """complete, non_trading (confirmed official no-data) or missing per weekday.

    The one rule for a confirmed closure, read by the daily catch-up, the
    bounded backfill's target and /api/coverage (Issue #479).  A no-data
    answer counts as closed only when it is confirmed: a daily run recorded
    ``non_trading_day`` for that date, or the answer was obtained after that
    Taipei day ended (a later catch-up or backfill).  A single same-day answer
    (``non_trading_unconfirmed`` whose 23:00 check never ran) stays missing,
    so a wrong "no session" is fetched again.  The holiday schedule is not
    read: a typhoon closure is not in it, while the official no-data answer
    covers both.
    """

    rows_by_day: dict[date, list[IngestionRun]] = defaultdict(list)
    for row in db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == "collect",
            IngestionRun.run_date >= start_date,
            IngestionRun.run_date <= end_date,
        )
    ).all():
        rows_by_day[row.run_date].append(row)
    confirmed_days = set(
        db.scalars(
            select(ScheduleRun.target_date).where(
                ScheduleRun.job == DAILY_JOB,
                ScheduleRun.target_date >= start_date,
                ScheduleRun.target_date <= end_date,
                ScheduleRun.status == "non_trading_day",
            )
        ).all()
    )
    states: dict[date, str] = {}
    day = start_date
    while day <= end_date:
        if day.weekday() < 5:
            states[day] = _collect_state(
                day, rows_by_day.get(day, []), day in confirmed_days
            )
        day += timedelta(days=1)
    return states


def _collect_state(day: date, rows: list[IngestionRun], daily_confirmed: bool) -> str:
    # Same test as collect's idempotency shortcut: a success with a TAIEX row.
    if any(
        row.status == "success"
        and int((row.metadata_json or {}).get("taiex_records", 0) or 0) > 0
        for row in rows
    ):
        return "complete"
    skipped = [row for row in rows if row.status == "skipped"]
    if not skipped:
        return "missing"
    # The end of the Taipei day in naive UTC, like the stored timestamps.
    day_end = (
        datetime(day.year, day.month, day.day) + timedelta(days=1) - TAIPEI_UTC_OFFSET
    )
    if daily_confirmed or any(
        (row.finished_at or row.started_at or datetime.min) >= day_end
        for row in skipped
    ):
        return "non_trading"
    return "missing"


def confirmed_non_trading_dates(
    db: Session, start_date: date, end_date: date
) -> set[date]:
    """The weekdays of the range that are confirmed closures (``collect_states``)."""

    return {
        day
        for day, state in collect_states(db, start_date, end_date).items()
        if state == "non_trading"
    }


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def has_backfill_manifest(db: Session) -> bool:
    """Return whether an official bounded-backfill audit exists.

    A failed/partial run still counts as an audit record: its coverage is
    allowed to be incomplete, but it must not be confused with the absence of
    any bounded baseline.
    """

    return (
        db.scalar(
            select(IngestionRun.id)
            .where(
                IngestionRun.source == "official",
                IngestionRun.run_type == "backfill",
            )
            .limit(1)
        )
        is not None
    )


def _official_run_ids(db: Session) -> set[int]:
    rows = db.scalars(
        select(IngestionRun.id).where(
            IngestionRun.source == "official",
            IngestionRun.status.in_({"success", "partial", "skipped"}),
            IngestionRun.run_type.in_({"collect", "backfill"}),
        )
    ).all()
    return {int(item) for item in rows}


def _raw_is_date_verified(
    raw: RawPayload,
    *,
    run_ids: set[int],
    trading_date: date,
) -> bool:
    """Check provenance/date metadata before reading a raw payload."""

    if raw.ingestion_run_id not in run_ids:
        return False
    if _as_date(raw.data_as_of) != trading_date:
        return False
    source = (raw.source or "").casefold()
    endpoint = (raw.endpoint or "").casefold()
    if source != "twse":
        return False
    # MI_INDEX is the date-scoped TWSE report that contains the benchmark
    # summary table.  Other TWSE feeds must not be promoted to a TAIEX basis.
    return "mi_index" in endpoint or "taiex" in endpoint


def _fixture_bar_is_explicit_test_data(row: MarketBar) -> bool:
    """Keep existing isolated synthetic fixtures usable without weakening production.

    Unit/integration fixtures deliberately use names such as ``twse_fixture``
    and have no raw file.  They are not accepted by the official snapshot
    path unless their source explicitly advertises that test-only nature.
    """

    return "fixture" in (row.source or "").casefold()


def verified_taiex_sessions(
    db: Session,
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    require_provenance: bool = True,
    limit: int | None = None,
) -> list[date]:
    """Return sorted TAIEX sessions that are safe to use as denominators.

    ``require_provenance=False`` is used by the backfill worker's historical
    fixture-compatible report.  The API and product decision path use the
    conservative default, which accepts only official raw-linked rows (plus
    explicitly named test fixtures) and a date-validated persisted MI_INDEX
    payload when the index row was not normalized into ``market_bars``.
    """

    if start_date and end_date and start_date > end_date:
        return []
    run_ids = _official_run_ids(db) if require_provenance else set()
    query = (
        # Untyped necessary columns avoid unrelated MarketBar DateTime/price
        # processors. RawPayload and its official file gate remain unchanged.
        select(
            literal_column("market_bars.trading_date"),
            literal_column("market_bars.source"),
            RawPayload,
        )
        .select_from(MarketBar)
        .join(Instrument, Instrument.id == MarketBar.instrument_id)
        .outerjoin(RawPayload, RawPayload.id == MarketBar.raw_payload_id)
        .where(
            Instrument.status == "active",
            Instrument.instrument_type == "index",
            Instrument.exchange == "TWSE",
            Instrument.symbol.in_({"TAIEX", "TWII"}),
        )
    )
    if start_date:
        query = query.where(MarketBar.trading_date >= start_date)
    if end_date:
        query = query.where(MarketBar.trading_date <= end_date)
    rows = db.execute(query).all()
    sessions: set[date] = set()
    for stored_date, stored_source, raw in rows:
        trading_date = read_market_date(stored_date)
        if trading_date is None:
            continue
        if not require_provenance:
            sessions.add(trading_date)
            continue
        source = read_market_source(stored_source)
        if source is not None and "fixture" in source.casefold():
            sessions.add(trading_date)
        elif raw is not None and _raw_is_date_verified(
            raw,
            run_ids=run_ids,
            trading_date=trading_date,
        ):
            sessions.add(trading_date)

    # A prior official collect may have captured MI_INDEX but omitted the
    # TAIEX normalization (as happened for the existing one-day DB).  The raw
    # payload is still safe evidence when its run/source/data date all agree.
    if require_provenance and run_ids:
        raw_query = select(RawPayload).where(
            RawPayload.ingestion_run_id.in_(run_ids),
            RawPayload.source == "twse",
        )
        for raw in db.scalars(raw_query).all():
            candidate = _as_date(raw.data_as_of)
            if candidate is None:
                continue
            # Most official databases already persist a date-validated TAIEX
            # MarketBar linked to this raw payload.  Do not re-read and parse
            # the large MI_INDEX file for a date we have already verified;
            # retain the raw-only fallback only for missing normalized rows.
            if candidate in sessions:
                continue
            if start_date and candidate < start_date:
                continue
            if end_date and candidate > end_date:
                continue
            if not _raw_is_date_verified(
                raw,
                run_ids=run_ids,
                trading_date=candidate,
            ):
                continue
            if not raw.payload_path:
                continue
            try:
                payload = json.loads(
                    payload_file(raw.payload_path).read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, TypeError, ValueError):
                continue
            try:
                parsed = parse_twse_taiex_from_all_daily_payload(
                    payload,
                    requested_date=candidate,
                    data_as_of=raw.data_as_of,
                    payload_sha256=raw.sha256,
                )
            except (TypeError, ValueError, KeyError):
                parsed = []
            if any(item.trading_date == candidate for item in parsed):
                sessions.add(candidate)

    result = sorted(sessions)
    if limit is not None and limit >= 0:
        result = result[-limit:]
    return result


def official_snapshot_status(
    db: Session,
    sessions: Iterable[date],
    *,
    has_manifest: bool,
) -> dict[str, object]:
    """Describe the baseline without collapsing unknown into partial."""

    verified = sorted(set(sessions))
    if not verified:
        return {
            "status": "unknown",
            "kind": "none",
            "source": "none",
            "message": "尚未建立可核實的官方交易日基準",
            "has_backfill_manifest": has_manifest,
        }
    if has_manifest:
        return {
            "status": "manifest",
            "kind": "backfill_manifest",
            "source": "official_taiex_or_manifest",
            "message": "以官方回補稽核基準計算",
            "has_backfill_manifest": True,
        }
    return {
        "status": "snapshot",
        "kind": "official_snapshot",
        "source": "official_taiex_raw_provenance",
        "message": "目前僅有官方快照，尚無回補稽核基準",
        "has_backfill_manifest": False,
    }
