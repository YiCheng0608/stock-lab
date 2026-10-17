"""Scheduled daily job with an auditable run log.

Every ``worker.cli daily`` invocation writes one ``schedule_runs`` row and one
``schedule_run_steps`` row per step (collect -> analyze -> evaluate ->
indicators).  A step only runs when the previous one succeeded; a failure
keeps its error text and the later steps are recorded as skipped.

Re-running the same target date is safe: when a run for that date already
finished as ``success`` or ``non_trading_day``, the new invocation records a
``skipped`` row (reason ``already_complete``) without touching market data,
unless ``force`` is set.  Data idempotency itself is owned by the steps:
collect reuses a successful run for the same request and never rewrites a
stored value.
"""

from __future__ import annotations

import importlib
import traceback
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import desc, select

from app.models import ScheduleRun, ScheduleRunStep
from worker import pipeline

DAILY_JOB = "daily"
DAILY_STEPS = ("collect", "analyze", "evaluate", "indicators")
# A run still marked running after this long has lost its process (killed,
# rebooted); the next invocation records it as abandoned instead of waiting.
STALE_RUNNING_AFTER = timedelta(hours=6)
COMPLETE_STATUSES = frozenset({"success", "non_trading_day"})
# The indicator batch is delivered separately (V1-G2); until that module
# exists the step is recorded as not_configured and does not fail the run.
INDICATOR_MODULE = "worker.indicator_batch"
INDICATOR_FUNCTION = "run_indicator_batch"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    """Keep a step result small enough to store with every run."""

    details = dict(result)
    observations = details.pop("industry_membership_observations", None)
    if isinstance(observations, dict):
        details["industry_membership_observations"] = {
            key: value for key, value in observations.items() if not isinstance(value, (list, dict))
        }
    coverage = details.pop("event_coverage", None)
    if isinstance(coverage, dict):
        details["event_coverage_status"] = coverage.get("status")
    return details


def _step_records(step: str, result: dict[str, Any]) -> int | None:
    if step == "collect":
        return int(result.get("records", 0) or 0)
    if step == "analyze":
        return int(result.get("signals_upserted", 0) or 0)
    if step == "evaluate":
        return int(result.get("evaluations_written", 0) or 0) + int(result.get("settlements_written", 0) or 0)
    for key in ("records", "written", "rows_written"):
        if isinstance(result.get(key), int):
            return int(result[key])
    return None


def _indicator_step(target: date) -> dict[str, Any]:
    try:
        module = importlib.import_module(INDICATOR_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != INDICATOR_MODULE:
            raise
        return {"status": "not_configured", "reason": f"{INDICATOR_MODULE} is not installed"}
    runner = getattr(module, INDICATOR_FUNCTION, None)
    if runner is None:
        return {"status": "not_configured", "reason": f"{INDICATOR_MODULE}.{INDICATOR_FUNCTION} is missing"}
    return runner(target)


def _record_step(
    run_id: int,
    step: str,
    sequence: int,
    *,
    status: str,
    started_at: datetime | None = None,
    records: int | None = None,
    error: str | None = None,
    ingestion_run_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    with pipeline.SessionLocal() as db:
        row = db.scalar(
            select(ScheduleRunStep).where(
                ScheduleRunStep.schedule_run_id == run_id,
                ScheduleRunStep.step == step,
            )
        )
        if row is None:
            row = ScheduleRunStep(schedule_run_id=run_id, step=step, sequence=sequence)
            db.add(row)
        row.status = status
        row.started_at = started_at
        row.finished_at = _utcnow() if status != "running" else None
        row.records = records
        row.error = error
        row.ingestion_run_id = ingestion_run_id
        row.details_json = details or {}
        db.commit()


def _run_step(
    run_id: int,
    step: str,
    sequence: int,
    action: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    started = _utcnow()
    _record_step(run_id, step, sequence, status="running", started_at=started)
    try:
        result = action()
    except Exception as exc:  # the run log must survive any step failure
        result = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
    status = str(result.get("status") or "failed")
    error = result.get("error") or (result.get("reason") if status in {"failed", "partial", "skipped"} else None)
    _record_step(
        run_id,
        step,
        sequence,
        status=status,
        started_at=started,
        records=_step_records(step, result),
        error=str(error) if error else None,
        ingestion_run_id=result.get("run_id") if step == "collect" else None,
        details=_compact(result),
    )
    return result


def _finish(run_id: int, status: str, *, records: int, error: str | None, summary: dict[str, Any]) -> None:
    with pipeline.SessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        run.status = status
        run.records = records
        run.error = error
        run.finished_at = _utcnow()
        run.summary_json = summary
        db.commit()


def _start_run(target: date, trigger: str, force: bool) -> tuple[int, dict[str, Any] | None]:
    """Create the run row; return a finished result when nothing should run."""

    now = _utcnow()
    with pipeline.SessionLocal() as db:
        previous = db.scalars(
            select(ScheduleRun)
            .where(ScheduleRun.job == DAILY_JOB, ScheduleRun.target_date == target)
            .order_by(desc(ScheduleRun.id))
        ).all()
        active = None
        for row in previous:
            if row.status != "running":
                continue
            if row.started_at and now - row.started_at > STALE_RUNNING_AFTER:
                row.status = "failed"
                row.error = "abandoned: no finish was recorded within " + str(STALE_RUNNING_AFTER)
                row.finished_at = now
            elif active is None:
                active = row
        complete = next((row for row in previous if row.status in COMPLETE_STATUSES), None)
        run = ScheduleRun(job=DAILY_JOB, target_date=target, trigger=trigger, status="running", started_at=now)
        db.add(run)
        db.flush()
        skip_reason = None
        related = None
        if active is not None:
            skip_reason, related = "already_running", active.id
        elif complete is not None and not force:
            skip_reason, related = "already_complete", complete.id
        if skip_reason:
            run.status = "skipped"
            run.finished_at = _utcnow()
            run.summary_json = {"reason": skip_reason, "related_run_id": related}
        db.commit()
        if skip_reason:
            return run.id, {
                "status": "skipped",
                "reason": skip_reason,
                "related_run_id": related,
                "schedule_run_id": run.id,
                "date": target.isoformat(),
            }
        return run.id, None


def run_daily_job(
    end_date: date | None = None,
    *,
    months_back: int = 0,
    trigger: str = "manual",
    force: bool = False,
) -> dict[str, Any]:
    pipeline.init_db()
    target = pipeline.latest_weekday(end_date)
    run_id, finished = _start_run(target, trigger, force)
    if finished is not None:
        return finished

    output: dict[str, Any] = {"schedule_run_id": run_id, "date": target.isoformat(), "trigger": trigger}
    collected = _run_step(
        run_id,
        "collect",
        1,
        lambda: pipeline.collect(target, months_back=months_back, init_schema=False),
    )
    output["collect"] = collected
    collect_status = str(collected.get("status"))
    later: list[tuple[str, int, Callable[[], dict[str, Any]]]] = [
        ("analyze", 2, lambda: pipeline.analyze(init_schema=False, collect_run_id=collected.get("run_id"))),
        ("evaluate", 3, lambda: pipeline.evaluate(init_schema=False)),
        ("indicators", 4, lambda: _indicator_step(target)),
    ]
    if collect_status != "success":
        if collect_status == "skipped":
            # The official sources explicitly reported no session for the
            # target weekday (holiday/typhoon closure).
            status, reason = "non_trading_day", "official_no_session"
        else:
            status, reason = ("partial" if collect_status == "partial" else "failed"), "official_collection_incomplete"
        for step, sequence, _action in later:
            _record_step(run_id, step, sequence, status="skipped", error=reason)
            output[step] = {"status": "skipped", "reason": reason}
        error = None if status == "non_trading_day" else str(collected.get("error") or reason)
        if status == "partial":
            error = "collect partial: " + "; ".join(str(item) for item in collected.get("warnings", [])[:5])
        _finish(run_id, status, records=int(collected.get("records", 0) or 0), error=error,
                summary={"steps": {"collect": collect_status}, "reason": reason})
        output["status"] = status
        return output

    statuses = {"collect": collect_status}
    status, error, failed_step = "success", None, ""
    for step, sequence, action in later:
        if status != "success":
            reason = f"{failed_step}_not_successful"
            _record_step(run_id, step, sequence, status="skipped", error=reason)
            output[step] = {"status": "skipped", "reason": reason}
            statuses[step] = "skipped"
            continue
        result = _run_step(run_id, step, sequence, action)
        output[step] = result
        statuses[step] = str(result.get("status"))
        acceptable = {"success", "no_data"} | ({"not_configured"} if step == "indicators" else set())
        if statuses[step] not in acceptable:
            status = "failed"
            failed_step = step
            error = f"{step}: {result.get('error') or result.get('reason') or statuses[step]}"
    _finish(run_id, status, records=int(collected.get("records", 0) or 0), error=error,
            summary={"steps": statuses})
    output["status"] = status
    return output


def schedule_run_dict(run: ScheduleRun, steps: list[ScheduleRunStep]) -> dict[str, Any]:
    return {
        "id": run.id,
        "job": run.job,
        "target_date": run.target_date.isoformat(),
        "trigger": run.trigger,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "records": run.records,
        "error": run.error,
        "summary": run.summary_json or {},
        "steps": [
            {
                "step": step.step,
                "status": step.status,
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "finished_at": step.finished_at.isoformat() if step.finished_at else None,
                "records": step.records,
                "error": step.error,
                "ingestion_run_id": step.ingestion_run_id,
            }
            for step in sorted(steps, key=lambda item: item.sequence)
        ],
    }


def list_schedule_runs(limit: int = 20, target_date: date | None = None) -> list[dict[str, Any]]:
    with pipeline.SessionLocal() as db:
        query = select(ScheduleRun).order_by(desc(ScheduleRun.id)).limit(limit)
        if target_date is not None:
            query = query.where(ScheduleRun.target_date == target_date)
        runs = db.scalars(query).all()
        result = []
        for run in runs:
            steps = db.scalars(select(ScheduleRunStep).where(ScheduleRunStep.schedule_run_id == run.id)).all()
            result.append(schedule_run_dict(run, list(steps)))
        return result
