"""Scheduled daily job with an auditable run log.

Every ``worker.cli daily`` invocation writes one ``schedule_runs`` row and one
``schedule_run_steps`` row per step (catchup -> collect -> trading_calendar ->
analyze -> evaluate -> candidates -> indicators -> theme_suggestions ->
plan_tracking -> strategy_levels -> candidate_notes).  catchup
first collects recent official
sessions that have no successful collect yet (the machine was off, or every
trigger of that day failed); its outcome never blocks the target date.
analyze, evaluate and candidates run only after a
successful collect; evaluate and candidates only after a successful analyze
(candidates read the trading date's signals, not the tracking that evaluate
updates); indicators depend on stored bars alone, so they run after every
successful collect, and so does theme_suggestions, which only regroups stored
news LLM results, and plan_tracking, which tracks the user plans' own copy of
their levels on the stored bars.  A failure keeps its error text and the
dependent steps are recorded as skipped.  strategy_levels (the observation
price levels of the day's signals) runs after a successful analyze, and
candidate_notes (LLM explanations of the day's candidates) last after a
successful candidates step; whatever their status, they only stay on their
step rows and never change the run status.  So does trading_calendar, which
refreshes the official holiday schedule after a successful collect and before
analyze (the signals' earliest execution date reads it); when it fails,
analyze uses the calendar already stored.

A first "no session" answer for today's target is recorded as
``non_trading_unconfirmed``, which is not complete: the next trigger (21:30)
asks again and only a repeated answer becomes ``non_trading_day``.

Re-running the same target date is safe: when a run for that date already
finished as ``success`` or ``non_trading_day``, the new invocation records a
``skipped`` row (reason ``already_complete``) without touching market data,
unless ``force`` is set.  Data idempotency itself is owned by the steps:
collect reuses a successful run for the same request and never rewrites a
stored value.

Every row records what ran in ``summary_json["runtime"]`` (#336): the image tag
(``STOCK_IMAGE_TAG``), the checkout's HEAD (``STOCK_GIT_HEAD``, else
``git rev-parse HEAD``) and, when the scheduled job (worker.job) holds its
daily lock, that lock's path.  A ``running`` row started under the lock the
current run holds now has lost its process, whatever host or PID it names: a
restarted container has a new hostname and may hand out the same PIDs again.
"""

from __future__ import annotations

import functools
import importlib
import os
import socket
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import desc, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.migration_revisions import REVISIONS
from app.models import IngestionRun, ScheduleRun, ScheduleRunStep
from worker import pipeline, theme_suggestions
from worker.sources import OfficialMarketDataAdapter

DAILY_JOB = "daily"
DAILY_STEPS = (
    "catchup",
    "collect",
    "trading_calendar",
    "analyze",
    "evaluate",
    "candidates",
    "indicators",
    "theme_suggestions",
    "plan_tracking",
    "strategy_levels",
    "candidate_notes",
)
# Steps after collect and the earlier steps each needs to have succeeded.
STEP_REQUIRES = {
    "trading_calendar": (),
    "analyze": (),
    "evaluate": ("analyze",),
    "candidates": ("analyze",),
    "indicators": (),
    "theme_suggestions": (),
    "plan_tracking": (),
    "strategy_levels": ("analyze",),
    "candidate_notes": ("candidates",),
}
# Steps whose failure is kept on the step row only: the run stays success, so
# the run's success definition does not depend on them.  The LLM notes
# (timeout, claude missing, quota) and the observation price levels, which
# nothing else in the run reads.  A later daily does not retry them (it
# targets its own date); worker.cli candidate-notes / strategy-levels --date
# fill them.  The holiday schedule refresh (#294): analyze then reads the
# calendar already stored and records in its own details whether the day's
# signals got an earliest execution date (the watchdog checks that).
NON_BLOCKING_STEPS = frozenset(
    {"trading_calendar", "candidate_notes", "strategy_levels"}
)
# A run still marked running after this long has lost its process (killed,
# rebooted); the next invocation records it as abandoned instead of waiting.
# Equal to the scheduled task's execution limit and clearly shorter than the
# 3 hours between the 18:30 and 21:30 triggers.  On the same host a dead PID
# is detected immediately, without waiting for this limit.
STALE_RUNNING_AFTER = timedelta(hours=2, minutes=30)
COMPLETE_STATUSES = frozenset({"success", "non_trading_day"})
# Both markets reported no session, but only once for today's target; the
# next trigger confirms it.  Not complete, so that trigger runs again.
NON_TRADING_UNCONFIRMED = "non_trading_unconfirmed"
# Catch-up looks at this many recent official sessions before the target
# (weekdays a collect already reported as closed do not count), looking back
# at most CATCHUP_MAX_WEEKDAYS weekdays.
CATCHUP_SESSIONS = 5
CATCHUP_MAX_WEEKDAYS = 15
TAIPEI_UTC_OFFSET = timedelta(hours=8)
# Reasons the scheduled job (worker.job) may pass to record a run it declined to start.
PREFLIGHT_SKIP_REASONS = frozenset({"low_memory", "git_busy"})
# The job lock is held by another daily job: the same reason as a running row
# found by _start_run, pointing at that row when it is already written.
LOCK_SKIP_REASON = "already_running"
# The indicator batch (V1-G2).  A checkout without the module records the
# step as not_configured instead of failing the run.
INDICATOR_MODULE = "worker.indicator_batch"
INDICATOR_FUNCTION = "run_indicator_batch"
CANDIDATE_MODULE = "worker.candidates"
CANDIDATE_FUNCTION = "run_candidates"
CANDIDATE_NOTE_MODULE = "worker.candidate_notes"
CANDIDATE_NOTE_FUNCTION = "run_candidate_notes_batch"
PLAN_TRACKING_MODULE = "worker.plan_tracking"
PLAN_TRACKING_FUNCTION = "run_plan_tracking"
STRATEGY_LEVELS_MODULE = "worker.strategy_levels"
STRATEGY_LEVELS_FUNCTION = "run_strategy_levels"
TRADING_CALENDAR_MODULE = "worker.trading_calendar"
TRADING_CALENDAR_FUNCTION = "run_trading_calendar"
# Set by worker.job for the worker it starts while holding the job's lock (#336).
JOB_LOCK_ENV = "STOCK_JOB_LOCK"
IMAGE_TAG_ENV = "STOCK_IMAGE_TAG"
GIT_HEAD_ENV = "STOCK_GIT_HEAD"
ROOT = Path(__file__).resolve().parents[2]


def _utcnow() -> datetime:
    return datetime.utcnow()


def _today() -> date:
    # Local date, like pipeline.latest_weekday's default target.
    return date.today()


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    """Keep a step result small and JSON-safe enough to store with every run."""

    details = _json_value(dict(result))
    observations = details.pop("industry_membership_observations", None)
    if isinstance(observations, dict):
        details["industry_membership_observations"] = {
            key: value
            for key, value in observations.items()
            if not isinstance(value, (list, dict))
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
        return int(result.get("evaluations_written", 0) or 0) + int(
            result.get("settlements_written", 0) or 0
        )
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
        return {
            "status": "not_configured",
            "reason": f"{INDICATOR_MODULE} is not installed",
        }
    runner = getattr(module, INDICATOR_FUNCTION, None)
    if runner is None:
        return {
            "status": "not_configured",
            "reason": f"{INDICATOR_MODULE}.{INDICATOR_FUNCTION} is missing",
        }
    return runner(target)


def _candidate_step(target: date) -> dict[str, Any]:
    module = importlib.import_module(CANDIDATE_MODULE)
    return getattr(module, CANDIDATE_FUNCTION)(target)


def _candidate_note_step(target: date) -> dict[str, Any]:
    module = importlib.import_module(CANDIDATE_NOTE_MODULE)
    return getattr(module, CANDIDATE_NOTE_FUNCTION)(target)


def _plan_tracking_step(target: date) -> dict[str, Any]:
    module = importlib.import_module(PLAN_TRACKING_MODULE)
    return getattr(module, PLAN_TRACKING_FUNCTION)(target)


def _strategy_levels_step(target: date) -> dict[str, Any]:
    module = importlib.import_module(STRATEGY_LEVELS_MODULE)
    return getattr(module, STRATEGY_LEVELS_FUNCTION)(target)


def _trading_calendar_step(target: date) -> dict[str, Any]:
    module = importlib.import_module(TRADING_CALENDAR_MODULE)
    return getattr(module, TRADING_CALENDAR_FUNCTION)(target)


def _theme_suggestion_step() -> dict[str, Any]:
    return theme_suggestions.run_theme_suggestions(pipeline.SessionLocal)


def _catchup_adapter() -> OfficialMarketDataAdapter:
    # The backfill's historical adapter: date-scoped feeds only, no snapshot
    # of today's classification, MOPS or ex-rights lists.
    return OfficialMarketDataAdapter(snapshot_feeds=False)


def _collect_state(db: Any, day: date) -> str:
    """complete, non_trading (confirmed official no-data) or missing.

    A no-data answer counts as closed only when it is confirmed: a daily run
    recorded ``non_trading_day`` for that date, or the answer was obtained
    after that Taipei day ended (a later catch-up or backfill).  A single
    same-day answer (``non_trading_unconfirmed`` whose 21:30 check never ran)
    stays missing, so a wrong "no session" is fetched again.
    """

    rows = db.scalars(
        select(IngestionRun).where(
            IngestionRun.run_type == "collect", IngestionRun.run_date == day
        )
    ).all()
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
    if any(
        (row.finished_at or row.started_at or datetime.min) >= day_end
        for row in skipped
    ):
        return "non_trading"
    confirmed = db.scalar(
        select(ScheduleRun.id)
        .where(
            ScheduleRun.job == DAILY_JOB,
            ScheduleRun.target_date == day,
            ScheduleRun.status == "non_trading_day",
        )
        .limit(1)
    )
    return "non_trading" if confirmed is not None else "missing"


def catchup_dates(
    target: date, sessions: int = CATCHUP_SESSIONS
) -> tuple[list[date], list[date]]:
    """Return (checked, missing) recent sessions before ``target``, oldest first."""

    checked: list[date] = []
    missing: list[date] = []
    day = target
    with pipeline.SessionLocal() as db:
        for _ in range(CATCHUP_MAX_WEEKDAYS):
            if len(checked) >= sessions:
                break
            day = pipeline.latest_weekday(day - timedelta(days=1))
            state = _collect_state(db, day)
            if state == "non_trading":
                continue
            checked.append(day)
            if state == "missing":
                missing.append(day)
    return sorted(checked), sorted(missing)


def _catchup_step(target: date, sessions: int) -> dict[str, Any]:
    """Collect the missing recent sessions through the backfill's one-day path."""

    checked, missing = catchup_dates(target, sessions)
    dates: dict[str, dict[str, Any]] = {}
    adapter = _catchup_adapter() if missing else None
    for day in missing:
        try:
            result = pipeline.collect(day, adapter=adapter, init_schema=False)
        except Exception as exc:  # one date must not stop the others or the target
            result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        dates[day.isoformat()] = {
            key: result[key]
            for key in ("status", "run_id", "records", "error")
            if result.get(key) is not None
        }
    incomplete = [
        day
        for day, item in dates.items()
        if item.get("status") not in {"success", "skipped"}
    ]
    if not incomplete:
        status = "success"
    elif len(incomplete) == len(dates):
        status = "failed"
    else:
        status = "partial"
    return {
        "status": status,
        "checked_dates": [day.isoformat() for day in checked],
        "missing_dates": [day.isoformat() for day in missing],
        "dates": dates,
        "incomplete_dates": incomplete,
        "records": sum(int(item.get("records", 0) or 0) for item in dates.values()),
        "error": (
            "catch-up incomplete: "
            + ", ".join(f"{day} {dates[day].get('status')}" for day in incomplete)
        )
        if incomplete
        else None,
    }


def _no_session_confirmed(run_id: int, target: date) -> bool:
    """Whether a "no session" answer for ``target`` is final.

    A past date's answer is final at once; for today's target an earlier run
    must already have received the same answer.
    """

    if target < _today():
        return True
    with pipeline.SessionLocal() as db:
        return (
            db.scalar(
                select(ScheduleRun.id)
                .where(
                    ScheduleRun.job == DAILY_JOB,
                    ScheduleRun.target_date == target,
                    ScheduleRun.id != run_id,
                    ScheduleRun.status.in_(
                        (NON_TRADING_UNCONFIRMED, "non_trading_day")
                    ),
                )
                .limit(1)
            )
            is not None
        )


def _ensure_schema() -> str:
    """Migrate only when the DB is not already at the code head.

    ``init_db`` always runs the whole-database migration integrity check,
    which takes minutes on a multi-year market DB even when no revision is
    pending, so an up-to-date DB skips it.
    """

    if _schema_revisions() == [REVISIONS[-1]]:
        return "current"
    pipeline.init_db()
    return "upgraded"


def _schema_revisions() -> list[str] | None:
    with pipeline.SessionLocal() as db:
        if not inspect(db.get_bind()).has_table("alembic_version"):
            return None
        return list(
            db.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )


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
    error = result.get("error") or (
        result.get("reason") if status in {"failed", "partial", "skipped"} else None
    )
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


def _finish(
    run_id: int,
    status: str,
    *,
    records: int,
    error: str | None,
    summary: dict[str, Any],
) -> None:
    with pipeline.SessionLocal() as db:
        run = db.get(ScheduleRun, run_id)
        run.status = status
        run.records = records
        run.error = error
        run.finished_at = _utcnow()
        # Keeps the runtime written when the run started.
        run.summary_json = {**(run.summary_json or {}), **summary}
        db.commit()


def checkout_fields(git_head: str | None, git_tag: str | None) -> dict[str, Any]:
    """The deployed version the scheduled job ran (#314); None when not known."""

    return {"git_tag": git_tag, "HEAD": git_head}


def _pid_alive(pid: int) -> bool:
    """Whether a process with this id exists on this host."""

    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@functools.lru_cache(maxsize=1)
def _git_head() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    head = completed.stdout.strip()
    return head if completed.returncode == 0 and head else None


def runtime() -> dict[str, str | None]:
    """What this run is: the image tag and HEAD, and the job lock it holds."""

    result: dict[str, str | None] = {
        "image": os.environ.get(IMAGE_TAG_ENV) or None,
        "head": os.environ.get(GIT_HEAD_ENV) or _git_head(),
    }
    if os.environ.get(JOB_LOCK_ENV):
        result["job_lock"] = os.environ[JOB_LOCK_ENV]
    return result


def _abandoned_reason(
    row: ScheduleRun, now: datetime, host: str, job_lock: str | None = None
) -> str | None:
    held = ((row.summary_json or {}).get("runtime") or {}).get("job_lock")
    if job_lock and held == job_lock:
        # The lock is ours, so the job that held it for this row has ended, and
        # its worker with it (worker.job); the host and PID may be a restarted
        # container's.
        return f"abandoned: process {row.pid} on {row.host} no longer holds {job_lock}"
    if row.host == host and row.pid is not None and not _pid_alive(row.pid):
        return f"abandoned: process {row.pid} on {host} is no longer running"
    if row.started_at and now - row.started_at > STALE_RUNNING_AFTER:
        return "abandoned: no finish was recorded within " + str(STALE_RUNNING_AFTER)
    return None


def _start_run(
    target: date, trigger: str, force: bool, checkout: dict[str, Any]
) -> tuple[int, dict[str, Any] | None]:
    """Create the run row; return a finished result when nothing should run."""

    now = _utcnow()
    host = socket.gethostname()
    current = runtime()
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
            abandoned = _abandoned_reason(row, now, host, current.get("job_lock"))
            if abandoned:
                row.status = "failed"
                row.error = abandoned
                row.finished_at = now
            elif active is None:
                active = row
        complete = next(
            (row for row in previous if row.status in COMPLETE_STATUSES), None
        )
        run = ScheduleRun(
            job=DAILY_JOB,
            target_date=target,
            trigger=trigger,
            status="running",
            started_at=now,
            host=host,
            pid=os.getpid(),
            summary_json={"runtime": current},
        )
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
            run.summary_json = {
                "runtime": current,
                "reason": skip_reason,
                "related_run_id": related,
                **checkout,
            }
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


def record_preflight_skip(
    end_date: date | None,
    *,
    reason: str,
    trigger: str = "scheduler",
    git_head: str | None = None,
    git_tag: str | None = None,
) -> dict[str, Any]:
    """Log a run the scheduled job declined to start; no step runs.

    For ``already_running`` the job lock is held by a daily that may be
    migrating this database at that moment. The migration reads for minutes
    inside one transaction before it writes, and any row another connection
    commits in between makes that write fail ("database is locked", found on
    a DB copy in #313 AC-7). So the schema is left alone, no row is written
    unless the database is already at the code head, and a row that cannot be
    written is reported in the result instead of raised; the job's log keeps
    the skip either way.
    """

    if reason not in PREFLIGHT_SKIP_REASONS | {LOCK_SKIP_REASON}:
        raise ValueError(f"unknown preflight skip reason: {reason}")
    target = pipeline.latest_weekday(end_date)
    checkout = checkout_fields(git_head, git_tag)
    if reason != LOCK_SKIP_REASON:
        _ensure_schema()
        return _insert_skip(target, reason, trigger, checkout)
    unwritten = {
        "status": "skipped",
        "reason": reason,
        "schedule_run_id": None,
        "date": target.isoformat(),
    }
    try:
        revisions = _schema_revisions()
        if revisions != [REVISIONS[-1]]:
            return {
                **unwritten,
                "error": f"skip row not written: database at {revisions}, code head"
                f" {REVISIONS[-1]}; the daily holding the lock migrates it",
            }
        return _insert_skip(target, reason, trigger, checkout)
    except SQLAlchemyError as exc:
        return {
            **unwritten,
            "error": f"skip row not written: {type(exc).__name__}: {exc}"[:500],
        }


def _insert_skip(
    target: date, reason: str, trigger: str, checkout: dict[str, Any]
) -> dict[str, Any]:
    now = _utcnow()
    with pipeline.SessionLocal() as db:
        summary: dict[str, Any] = {"reason": reason}
        if reason == LOCK_SKIP_REASON:
            summary["related_run_id"] = db.scalar(
                select(ScheduleRun.id)
                .where(
                    ScheduleRun.job == DAILY_JOB,
                    ScheduleRun.target_date == target,
                    ScheduleRun.status == "running",
                )
                .order_by(desc(ScheduleRun.id))
                .limit(1)
            )
        run = ScheduleRun(
            job=DAILY_JOB,
            target_date=target,
            trigger=trigger,
            status="skipped",
            started_at=now,
            finished_at=now,
            summary_json={"runtime": runtime(), **summary, **checkout},
        )
        db.add(run)
        db.commit()
        return {
            "status": "skipped",
            **summary,
            "schedule_run_id": run.id,
            "date": target.isoformat(),
        }


def run_daily_job(
    end_date: date | None = None,
    *,
    months_back: int = 0,
    trigger: str = "manual",
    force: bool = False,
    catchup_sessions: int = CATCHUP_SESSIONS,
    git_head: str | None = None,
    git_tag: str | None = None,
) -> dict[str, Any]:
    _ensure_schema()
    target = pipeline.latest_weekday(end_date)
    checkout = checkout_fields(git_head, git_tag)
    run_id, finished = _start_run(target, trigger, force, checkout)
    if finished is not None:
        return finished

    output: dict[str, Any] = {
        "schedule_run_id": run_id,
        "date": target.isoformat(),
        "trigger": trigger,
    }
    summary_steps: dict[str, str] = {}
    if catchup_sessions > 0:
        # Its outcome never blocks the target date; an incomplete catch-up is
        # kept in the step and the run summary, where the watchdog reads it.
        caught = _run_step(
            run_id, "catchup", 0, lambda: _catchup_step(target, catchup_sessions)
        )
        output["catchup"] = caught
        summary_steps["catchup"] = str(caught.get("status"))
    collected = _run_step(
        run_id,
        "collect",
        1,
        lambda: pipeline.collect(target, months_back=months_back, init_schema=False),
    )
    output["collect"] = collected
    collect_status = str(collected.get("status"))
    summary_steps["collect"] = collect_status
    later: list[tuple[str, int, Callable[[], dict[str, Any]]]] = [
        ("trading_calendar", 2, lambda: _trading_calendar_step(target)),
        (
            "analyze",
            3,
            lambda: pipeline.analyze(
                init_schema=False, collect_run_id=collected.get("run_id")
            ),
        ),
        ("evaluate", 4, lambda: pipeline.evaluate(init_schema=False)),
        ("candidates", 5, lambda: _candidate_step(target)),
        ("indicators", 6, lambda: _indicator_step(target)),
        ("theme_suggestions", 7, _theme_suggestion_step),
        # Before the LLM notes, which can take long; the sequence only orders
        # the step rows (rows are found by step name).
        ("plan_tracking", 8, lambda: _plan_tracking_step(target)),
        ("strategy_levels", 9, lambda: _strategy_levels_step(target)),
        ("candidate_notes", 10, lambda: _candidate_note_step(target)),
    ]
    if collect_status != "success":
        if collect_status == "skipped" and _no_session_confirmed(run_id, target):
            # The official sources explicitly reported no session for the
            # target weekday (holiday/typhoon closure).
            status, reason = "non_trading_day", "official_no_session"
        elif collect_status == "skipped":
            status, reason = NON_TRADING_UNCONFIRMED, "official_no_session_unconfirmed"
        else:
            status, reason = (
                ("partial" if collect_status == "partial" else "failed"),
                "official_collection_incomplete",
            )
        for step, sequence, _action in later:
            _record_step(run_id, step, sequence, status="skipped", error=reason)
            output[step] = {"status": "skipped", "reason": reason}
        no_session = status in {"non_trading_day", NON_TRADING_UNCONFIRMED}
        error = None if no_session else str(collected.get("error") or reason)
        if status == "partial":
            warnings = (
                collected.get("core_warnings", collected.get("warnings", [])) or []
            )
            error = "collect partial: " + "; ".join(str(item) for item in warnings[:5])
        _finish(
            run_id,
            status,
            records=int(collected.get("records", 0) or 0),
            error=error,
            summary=_summary(summary_steps, collected, checkout, reason=reason),
        )
        output["status"] = status
        return output

    statuses = summary_steps
    errors: list[str] = []
    failed: list[str] = []
    for step, sequence, action in later:
        # evaluate and candidates need a successful analyze; indicators only
        # need the bars collect just stored, so an analyze failure does not
        # block them; theme_suggestions and plan_tracking need neither.  An
        # analyze failure also skips strategy_levels, and a candidates failure
        # candidate_notes; their own results never fail the run.
        blocked_by = next((name for name in failed if name in STEP_REQUIRES[step]), "")
        if blocked_by:
            reason = f"{blocked_by}_not_successful"
            _record_step(run_id, step, sequence, status="skipped", error=reason)
            output[step] = {"status": "skipped", "reason": reason}
            statuses[step] = "skipped"
            failed.append(step)
            continue
        result = _run_step(run_id, step, sequence, action)
        output[step] = result
        statuses[step] = str(result.get("status"))
        acceptable = {"success", "no_data"} | (
            {"not_configured"} if step == "indicators" else set()
        )
        if statuses[step] not in acceptable and step not in NON_BLOCKING_STEPS:
            failed.append(step)
            errors.append(
                f"{step}: {result.get('error') or result.get('reason') or statuses[step]}"
            )
    status = "failed" if errors else "success"
    error = "; ".join(errors) or None
    _finish(
        run_id,
        status,
        records=int(collected.get("records", 0) or 0),
        error=error,
        summary=_summary(statuses, collected, checkout),
    )
    output["status"] = status
    return output


def _summary(
    steps: dict[str, str],
    collected: dict[str, Any],
    checkout: dict[str, Any],
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {"steps": steps, **checkout}
    if reason:
        summary["reason"] = reason
    # Non-core source warnings do not change the status; keep them visible.
    if collected.get("noncore_warnings"):
        summary["noncore_warnings"] = list(collected["noncore_warnings"])[:20]
    return summary


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
                "finished_at": step.finished_at.isoformat()
                if step.finished_at
                else None,
                "records": step.records,
                "error": step.error,
                "ingestion_run_id": step.ingestion_run_id,
            }
            for step in sorted(steps, key=lambda item: item.sequence)
        ],
    }


def list_schedule_runs(
    limit: int = 20, target_date: date | None = None
) -> list[dict[str, Any]]:
    with pipeline.SessionLocal() as db:
        query = select(ScheduleRun).order_by(desc(ScheduleRun.id)).limit(limit)
        if target_date is not None:
            query = query.where(ScheduleRun.target_date == target_date)
        runs = db.scalars(query).all()
        result = []
        for run in runs:
            steps = db.scalars(
                select(ScheduleRunStep).where(ScheduleRunStep.schedule_run_id == run.id)
            ).all()
            result.append(schedule_run_dict(run, list(steps)))
        return result
