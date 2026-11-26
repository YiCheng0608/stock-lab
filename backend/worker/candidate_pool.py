"""Write the 候選池 of a day (Issue #1020): the evening and the morning run.

- **Evening**: the daily's ``candidate_pool`` step (last, after
  ``theme_discovery``, whose clusters it reads) calls ``run_candidate_pool``.
  A failure is a warning: one ``warning:`` line on stderr and a ``failed``
  result the daily keeps on the step row only
  (``schedule_runs.NON_BLOCKING_STEPS``); the today list, the run's status
  and the exit code do not change.  A failed computation writes nothing.
- **Morning**: the 08:20 ``preopen`` job calls ``run_morning_pool`` after its
  own check, so the news of the 08:00 run is in; its outcome is one line of
  the preopen log and never changes preopen's result or exit code.
- **Written once**: a stored run of the date and phase is reported
  ``already_stored`` and not touched (``app.candidate_pool``).

``worker.cli candidate-pool --date [--phase] [--dry-run]`` runs either by hand;
``--dry-run`` computes and prints the summary without writing.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from typing import Any, Callable

from app.candidate_pool import (
    CANDIDATE_POOL_VERSION,
    EVENING,
    MORNING,
    compute_evening,
    compute_morning,
)
from worker import pipeline


def _result(run: Any, written: bool, day: date, phase: str) -> dict[str, Any]:
    if run is None:
        return {
            "status": "skipped",
            "reason": "no_evening_run",
            "date": day.isoformat(),
            "phase": phase,
            "version": CANDIDATE_POOL_VERSION,
        }
    summary = run.summary_json or {}
    return {
        "status": "success",
        "date": day.isoformat(),
        "phase": phase,
        "version": CANDIDATE_POOL_VERSION,
        "written": written,
        "reason": None if written or run.id is None else "already_stored",
        "run_id": run.id,
        "pool_status": run.status,
        "computed_at": run.computed_at.isoformat() if run.computed_at else None,
        "union": run.union_count,
        "records": run.selected_count,
        "cap": run.cap,
        "sources": run.source_counts_json,
        "selected_sources": summary.get("selected_sources"),
        "multi_source": summary.get("multi_source"),
        "rejected": summary.get("rejected"),
        "inputs": summary.get("inputs"),
    }


def _failed(day: date, phase: str, exc: Exception) -> dict[str, Any]:
    error = f"{type(exc).__name__}: {exc}"
    print(
        f"warning: {CANDIDATE_POOL_VERSION} {phase} {day.isoformat()} failed: {error}",
        file=sys.stderr,
        flush=True,
    )
    return {
        "status": "failed",
        "date": day.isoformat(),
        "phase": phase,
        "version": CANDIDATE_POOL_VERSION,
        "error": error,
    }


def run_candidate_pool(target: date, *, dry_run: bool = False) -> dict[str, Any]:
    """The evening run of ``target``; never raises."""

    try:
        with pipeline.SessionLocal() as db:
            run, written = compute_evening(db, target, write=not dry_run)
            result = _result(run, written, target, EVENING)
            if dry_run:
                result["dry_run"] = True
                result["selected"] = _entries(db, run)
            return result
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        return _failed(target, EVENING, exc)


def run_morning_pool(
    list_date: date,
    checked_at: datetime,
    *,
    dry_run: bool = False,
    session: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """The morning run of ``list_date`` (the evening's trading date) at
    ``checked_at`` (UTC-naive); never raises.  ``session`` is the caller's
    session factory (preopen's); ``pipeline.SessionLocal`` by default."""

    try:
        with (session or pipeline.SessionLocal)() as db:
            run, written = compute_morning(db, list_date, checked_at, write=not dry_run)
            result = _result(run, written, list_date, MORNING)
            if dry_run and run is not None:
                result["dry_run"] = True
                result["selected"] = _entries(db, run)
            return result
    except Exception as exc:  # noqa: BLE001 - logged, preopen goes on
        return _failed(list_date, MORNING, exc)


def _entries(db: Any, run: Any) -> list[dict[str, Any]]:
    """A dry run's selected stocks, ``exchange:symbol`` and sources."""

    from app.models import Instrument

    entries = getattr(run, "unsaved_entries", None)
    if entries is None:
        return []
    chosen = [entry for entry in entries if entry.selected]
    names = {
        row.id: f"{row.exchange}:{row.symbol} {row.name}"
        for row in db.query(Instrument).filter(
            Instrument.id.in_([entry.instrument_id for entry in chosen])
        )
    }
    return [
        {
            "rank": entry.rank,
            "tier": entry.tier,
            "instrument": names.get(entry.instrument_id, entry.instrument_id),
            "sources": sorted(entry.hits),
        }
        for entry in chosen
    ]
