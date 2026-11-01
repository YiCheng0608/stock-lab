"""Backfill and check corporate actions against the official result tables (#386).

The daily feeds only describe the collection day: TWT48U lists that day and
announced future dates, tpex_exright_daily only that day.  A session that was
not collected therefore never got its ex-right/ex-dividend rows.  ``sync``
reads TWSE TWT49U (+ TWT49UDetail) and TPEx exDailyQ for a date range, writes
every event through ``pipeline._upsert_action`` (so the same factor check
applies) and reports what changed.  ``check`` compares every stored row with
the official 減除股利參考價 / 除權息前收盤價 ratio, without writing.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from datetime import date
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import utcnow
from app.db import SessionLocal
from app.models import (
    CorporateAction,
    GroupDailyScore,
    IngestionRun,
    Instrument,
)
from worker import pipeline
from worker.sources import (
    ActionRecord,
    FetchedPayload,
    OfficialDataError,
    TpexAdapter,
    TwseAdapter,
    fetch_json,
)

SYNC_VERSION = "corporate_action_sync_v1"
RUN_TYPE = "corporate_action_sync"
FINISHED = frozenset({"success", "partial"})
FIELDS = ("cash_dividend", "stock_dividend_ratio", "split_ratio", "reference_price")


def table_summary(db: Session) -> dict[str, Any]:
    earliest, latest, rows = db.execute(
        select(
            func.min(CorporateAction.action_date),
            func.max(CorporateAction.action_date),
            func.count(CorporateAction.id),
        )
    ).one()
    return {
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
        "rows": rows,
    }


def check_corporate_actions(
    db: Session, *, start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    """Every stored row whose fields disagree with the official price ratio."""
    query = select(CorporateAction, Instrument).join(
        Instrument, Instrument.id == CorporateAction.instrument_id
    )
    if start is not None:
        query = query.where(CorporateAction.action_date >= start)
    if end is not None:
        query = query.where(CorporateAction.action_date <= end)
    checked = unchecked = 0
    mismatches: list[dict[str, Any]] = []
    for action, instrument in db.execute(
        query.order_by(CorporateAction.action_date, CorporateAction.id)
    ).all():
        check = pipeline.action_factor_check(action)
        if check is None:
            unchecked += 1
            continue
        checked += 1
        if not check["passed"]:
            mismatches.append(
                {
                    "exchange": instrument.exchange,
                    "symbol": instrument.symbol,
                    "action_date": action.action_date.isoformat(),
                    "action_type": action.action_type,
                    **{name: getattr(action, name) for name in FIELDS},
                    **check,
                }
            )
    return {
        "status": "success",
        "version": SYNC_VERSION,
        "rows_checked": checked,
        "rows_without_official_prices": unchecked,
        "mismatches": mismatches,
    }


def _fetch(
    start: date, end: date, fetcher: Callable[..., Any]
) -> tuple[list[ActionRecord], list[FetchedPayload], list[str]]:
    records: list[ActionRecord] = []
    payloads: list[FetchedPayload] = []
    warnings: list[str] = []
    for adapter in (TwseAdapter(fetcher), TpexAdapter(fetcher)):
        try:
            found, captured, notes = adapter.fetch_action_history(start, end)
        except OfficialDataError:
            # Keep what was captured before the failure as evidence.
            payloads.extend(adapter.captured_payloads)
            raise
        records.extend(found)
        payloads.extend(captured)
        warnings.extend(notes)
    # One row per (exchange, symbol, date, type), the unique key of
    # corporate_actions; the session does not autoflush, so a second record
    # of a key would be a second INSERT.
    unique: dict[tuple[str, str, date, str], ActionRecord] = {}
    for record in records:
        key = (record.exchange, record.symbol, record.action_date, record.action_type)
        if key in unique and unique[key] != record:
            warnings.append(
                f"{record.exchange} {record.symbol} {record.action_date.isoformat()} "
                "published twice with different values; the later row is kept"
            )
        unique[key] = record
    return list(unique.values()), payloads, warnings


def _plan(
    db: Session,
    records: list[ActionRecord],
    instruments: dict[tuple[str, str], Instrument],
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    changes: list[dict[str, Any]] = []
    unknown: Counter[str] = Counter()
    rejected: list[dict[str, Any]] = []
    affected: dict[int, date] = {}
    for record in records:
        instrument = instruments.get((record.exchange, record.symbol))
        if instrument is None:
            unknown[record.exchange] += 1
            continue
        check = pipeline.action_factor_check(record)
        if check is not None and not check["passed"]:
            rejected.append(
                {
                    "exchange": record.exchange,
                    "symbol": record.symbol,
                    "action_date": record.action_date.isoformat(),
                    **check,
                }
            )
        row = db.scalar(
            select(CorporateAction).where(
                CorporateAction.instrument_id == instrument.id,
                CorporateAction.action_date == record.action_date,
                CorporateAction.action_type == record.action_type,
            )
        )
        if row is None:
            counts["new"] += 1
            _note(affected, instrument, record.action_date)
            continue
        before = {name: getattr(row, name) for name in FIELDS}
        after = {name: getattr(record, name) for name in FIELDS}
        if check is not None and not check["passed"]:
            after.update(
                cash_dividend=None, stock_dividend_ratio=None, split_ratio=None
            )
        if before == after:
            counts["same_fields"] += 1
            continue
        counts["changed"] += 1
        _note(affected, instrument, record.action_date)
        changes.append(
            {
                "exchange": record.exchange,
                "symbol": record.symbol,
                "action_date": record.action_date.isoformat(),
                "action_type": record.action_type,
                "before": before,
                "after": after,
            }
        )
    return {
        "events_fetched": len(records),
        "events_without_stored_instrument": dict(unknown),
        "new_rows": counts["new"],
        "changed_rows": counts["changed"],
        "unchanged_rows": counts["same_fields"],
        "changes": changes,
        "factor_mismatches": rejected,
        # instrument id -> earliest action date whose factor input changes;
        # ``rebuild`` recomputes these instruments from that date.
        "affected": {
            str(key): value.isoformat() for key, value in sorted(affected.items())
        },
    }


def _note(affected: dict[int, date], instrument: Instrument, day: date) -> None:
    if instrument.id not in affected or day < affected[instrument.id]:
        affected[instrument.id] = day


def sync_corporate_actions(
    db: Session,
    *,
    start: date,
    end: date,
    apply: bool = False,
    fetcher: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    """Plan, and with ``apply`` write, the backfill in the caller's transaction."""
    if start > end:
        raise ValueError("start must be on or before end")
    before = table_summary(db)
    records, payloads, warnings = _fetch(start, end, fetcher)
    instruments = {
        (item.exchange, item.symbol): item for item in db.scalars(select(Instrument))
    }
    plan = _plan(db, records, instruments)
    result: dict[str, Any] = {
        "status": "dry_run",
        "version": SYNC_VERSION,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "before": before,
        "warnings": warnings,
        "payloads": len(payloads),
        **plan,
    }
    if not apply:
        return result
    run = IngestionRun(
        run_type=RUN_TYPE,
        source="official",
        run_date=utcnow().date(),
        status="running",
        data_as_of=end.isoformat(),
        metadata_json={"version": SYNC_VERSION, "start": start.isoformat()},
    )
    db.add(run)
    db.flush()
    raw_ids = {
        payload.sha256: pipeline._upsert_raw_payload(db, run, payload).id
        for payload in payloads
    }
    for record in records:
        pipeline._upsert_action(
            db, record, instruments, raw_ids.get(record.payload_sha256)
        )
    db.flush()
    run.status = "partial" if warnings else "success"
    run.records = len(records)
    run.finished_at = utcnow()
    run.metadata_json = {
        **run.metadata_json,
        "warnings": warnings,
        "new_rows": plan["new_rows"],
        "changed_rows": plan["changed_rows"],
        "factor_mismatches": len(plan["factor_mismatches"]),
        "affected": plan["affected"],
    }
    result.update(status=run.status, run_id=run.id, after=table_summary(db))
    return result


class RebuildError(Exception):
    pass


def rebuild_after_sync(
    db: Session,
    run_id: int,
    *,
    checkpoint: Callable[[str], None] | None = None,
    group_scores_from: date | None = None,
) -> dict[str, Any]:
    """Recompute what a sync run's corrected rows feed, in the caller's session.

    For the instruments the run changed: every technical_indicators row (any
    status with bars, as the indicators batch covers them) and, for active
    ones, every technical_features row; then the hot-group scores of every
    session from the earliest changed action date on that already has
    scores.  A session without scores is not filled in: that would backfill
    history with today's group definitions.  Signals are not
    regenerated: past signals are tracked, and whether to regenerate them is
    decided per correction.  ``checkpoint`` (the CLI commits and logs) is
    called with the step name after each step; each step recomputes from
    stored rows, so a rerun after a failure writes the same values.

    ``group_scores_from`` resumes a rebuild that stopped during the group
    scores: indicators and features (already committed) are skipped and only
    the sessions from that date on are rescored.  Each session is scored from
    stored rows alone, so the result equals one uninterrupted rebuild.
    """
    # Imported here: both modules import pipeline, as this one does.
    from worker.indicator_batch import compute_market_indicators
    from worker.industry_repair import rescore_dates

    def step(name: str) -> None:
        if checkpoint is not None:
            checkpoint(name)

    run = db.get(IngestionRun, run_id)
    if run is None or run.run_type != RUN_TYPE or run.status not in FINISHED:
        raise RebuildError(f"no finished {RUN_TYPE} run {run_id}")
    affected = {
        int(key): date.fromisoformat(value)
        for key, value in (run.metadata_json or {}).get("affected", {}).items()
    }
    result: dict[str, Any] = {
        "status": "success",
        "version": SYNC_VERSION,
        "run_id": run_id,
        "instruments": len(affected),
    }
    if not affected:
        return {**result, "status": "no_change"}
    ids = sorted(affected)
    started = time.perf_counter()
    since = min(affected.values())
    if group_scores_from is None:
        result["indicators"] = compute_market_indicators(
            db, rebuild=True, instrument_ids=ids
        )
        step("indicators")
        result["feature_instruments"] = _rebuild_features(db, ids, step)
    else:
        result["resumed_group_scores_from"] = group_scores_from.isoformat()
        since = max(since, group_scores_from)
    days = db.scalars(
        select(GroupDailyScore.trading_date)
        .where(GroupDailyScore.trading_date >= since)
        .distinct()
        .order_by(GroupDailyScore.trading_date)
    ).all()
    # One commit per session: hundreds of sessions in one transaction would
    # hold the SQLite write lock for the whole rescore.
    rescore_dates(db, days, after_each=lambda day: step(f"group_scores {day}"))
    rescored = [day.isoformat() for day in days]
    result["group_score_dates"] = {
        "since": since.isoformat(),
        "count": len(rescored),
        "first": rescored[0] if rescored else None,
        "last": rescored[-1] if rescored else None,
    }
    result["elapsed_seconds"] = round(time.perf_counter() - started, 1)
    return result


def _rebuild_features(db: Session, ids: list[int], step: Callable[[str], None]) -> int:
    features = 0
    instruments = db.scalars(
        select(Instrument).where(Instrument.id.in_(ids), Instrument.status == "active")
    ).all()
    for instrument in instruments:
        pipeline._calculate_features(db, instrument)
        features += 1
        if features % pipeline.ANALYZE_COMMIT_BATCH == 0:
            db.flush()
            step(f"features {features}/{len(instruments)}")
    db.flush()
    step(f"features {features}/{len(instruments)}")
    return features


def run_corporate_action_rebuild(
    run_id: int, *, group_scores_from: date | None = None
) -> dict[str, Any]:
    started = time.perf_counter()
    with SessionLocal() as db:

        def checkpoint(name: str) -> None:
            db.commit()
            elapsed = time.perf_counter() - started
            print(f"rebuild {name} committed at {elapsed:.0f}s", file=sys.stderr)

        try:
            result = rebuild_after_sync(
                db,
                run_id,
                checkpoint=checkpoint,
                group_scores_from=group_scores_from,
            )
        except RebuildError as exc:
            db.rollback()
            return {"status": "failed", "version": SYNC_VERSION, "error": str(exc)}
        db.commit()
        return result


def run_corporate_action_sync(
    start: date, end: date, *, apply: bool = False
) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            result = sync_corporate_actions(db, start=start, end=end, apply=apply)
        except OfficialDataError as exc:
            db.rollback()
            return {"status": "failed", "version": SYNC_VERSION, "error": str(exc)}
        if apply:
            db.commit()
        return result


def run_corporate_action_check(
    start: date | None = None, end: date | None = None
) -> dict[str, Any]:
    with SessionLocal() as db:
        return check_corporate_actions(db, start=start, end=end)
