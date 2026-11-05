"""Read-only database helper for tools/ops/watchdog.sh.

Git Bash on the scheduler host has no sqlite3, so the watchdog calls this
module for its database checks; every decision stays in the shell script.
The result goes to stdout without a trailing newline.

  news-llm-pending <db> <n>        how many of the last <n> news_llm batches are
                                   pending in a row, or "skip" without the table
  news-llm-failed <db> <n> <now>   how many of the last <n> news_llm runs started
                                   in the last 24 hours failed in a row (a run
                                   still running after 90 minutes counts as
                                   failed), or "skip"
  llm-auth <db> <now>              one line "<run_type> run_id=<id>" per LLM
                                   run type (news_llm, candidate_notes) whose
                                   latest run, started in the last 24 hours,
                                   had a batch fail authentication
                                   (not_logged_in: no login, or an expired or
                                   revoked CLAUDE_CODE_OAUTH_TOKEN), else
                                   nothing; "skip" without the table
  daily-result <db> <date> <now> [<minutes>]
                                   the outcome of the daily runs for target
                                   <date> (YYYY-MM-DD): success,
                                   non_trading_day, running, none, skip, a
                                   failing run status, skipped:<reason>, or
                                   catchup_incomplete; a run still running
                                   past <minutes> (default 150) is failed
  invariants <db> <today> [<now>]  one line per data invariant,
                                   "<name> ok|violation|skip key=value ...":
                                   future_trading_date (latest market_bars
                                   trading_date after <today>, YYYY-MM-DD),
                                   latest_bar_provenance (bars of the latest
                                   trading_date with an unknown or empty source
                                   or no data_as_of), llm_done_provenance
                                   (done news_llm_results without llm_model or
                                   prompt_version), instrument_status_sync,
                                   execution_calendar (analysis signals of the
                                   latest signal date written with the calendar
                                   but without earliest_execution_date),
                                   strategy_levels (the latest finished daily
                                   run's strategy_levels step did not succeed),
                                   candidate_notes (the latest candidate list
                                   of CANDIDATE_SCORE_VERSION has candidates,
                                   no done AI note and was computed over 30
                                   minutes before <now>; not judged while a
                                   daily or candidate_notes run is running or
                                   the latest candidate_notes run was refused
                                   for its login, skipped without <now>)
  deploy-image <deploy.json>       "deploy_image ok|violation|skip key=value ...":
                                   the image this process runs in
                                   (STOCK_IMAGE_TAG, STOCK_GIT_HEAD: the
                                   scheduler container's) against the image and
                                   HEAD tools/ops/deploy.sh recorded (#340);
                                   skip without a record
  monitor-beat <file> <now>        the event monitor's heartbeat (#316):
                                   "none" without the file (no monitor yet),
                                   "ok <age_s>", "stale <age_s> <written_at>"
                                   past MONITOR_STALE_SECONDS, "gh_failed <polls>
                                   <since> <error>" after MONITOR_GH_FAILED_POLLS
                                   polls in a row with a failed gh call, or
                                   "unreadable"
  maintenance <marker> <now>       the maintenance marker (#468, written by
                                   worker.cli maintenance on; format in
                                   backend/worker/job.py): "off" without the
                                   file, else "on <age_s> <since> <reason>",
                                   dated by the file's modification time and
                                   reason "unreadable" when it is not the JSON
                                   it writes
  maintenance-expired <log> <now>  the latest "expired" record of the last 24 hours in
                                   <data>/logs/maintenance.log (#468 AC-5: serve
                                   removed a marker whose command stopped beating):
                                   "<at> <owner> <pid> <minutes_without_beat>
                                   <reason>", or nothing
  data-check <db> <date> [--offline] [--all] [--scratch DIR]
                                   the daily data check of trading date
                                   <date> (tools/ops/data_check.py, #390):
                                   "data_check ok|violation|pending|skip
                                   key=value ...", then on a violation the
                                   Markdown details (the first 20 findings,
                                   all with --all); --offline requests no
                                   official result table; the temporary
                                   directory goes into DIR (default TEMP)

<now> is the watchdog clock in epoch seconds.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Same limits as the jobs: a daily run past the scheduled task's 2.5 hours
# (worker.schedule_runs.STALE_RUNNING_AFTER) or a news_llm run past the news
# task's 90 minutes (worker.news_llm.ABANDONED_AFTER) has lost its process.
DAILY_RUNNING_LIMIT = timedelta(hours=2, minutes=30)
NEWS_LLM_RUNNING_LIMIT = timedelta(minutes=90)
# news-llm-failed counts only runs started within this window.
RECENT_WINDOW = timedelta(hours=24)
COMPLETE = ("success", "non_trading_day")
# The LLM steps that call claude -p, and their reason for a failed
# authentication (worker.news_llm.AUTH_ERROR_TEXT).
LLM_RUN_TYPES = ("news_llm", "candidate_notes")
AUTH_REASON = "not_logged_in"
# A candidate list this old without one done AI note is reported (#517): the
# notes follow the list, in the daily or in worker.cli candidates.
CANDIDATE_NOTES_GRACE = timedelta(minutes=30)
# The score version worker.candidate_notes writes notes for
# (app.domain.CANDIDATE_SCORE_VERSION; backend/tests/test_watchdog.py keeps
# them equal).  Lists of other versions are never given notes, so they are
# not judged.
CANDIDATE_SCORE_VERSION = "candidate_score_v6"
# Skipped rows that only point at another run of the same date.
REFERENCE_SKIPS = ("already_complete", "already_running")

# The scheduler container's version (backend/Dockerfile; worker.schedule_runs).
IMAGE_TAG_ENV = "STOCK_IMAGE_TAG"
GIT_HEAD_ENV = "STOCK_GIT_HEAD"


def _connect(db: str) -> sqlite3.Connection:
    uri = Path(db).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def _json(raw: object) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _utc(now: str) -> datetime:
    # The jobs store naive UTC timestamps.
    return datetime.fromtimestamp(int(now), tz=timezone.utc).replace(tzinfo=None)


def _started(raw: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def news_llm_pending(db: str, limit: int) -> str:
    with _connect(db) as conn:
        if not _has_table(conn, "ingestion_runs"):
            return "skip"
        rows = conn.execute(
            "SELECT metadata_json FROM ingestion_runs WHERE run_type='news_llm' ORDER BY id DESC LIMIT 50"
        ).fetchall()
    statuses: list[str] = []
    for (raw,) in rows:
        batches = _json(raw).get("batches") or []
        statuses.extend(str(batch.get("status")) for batch in reversed(batches))
        if len(statuses) >= limit:
            break
    streak = 0
    for status in statuses[:limit]:
        if status != "pending":
            break
        streak += 1
    return str(streak)


def news_llm_failed(db: str, limit: int, now: str) -> str:
    current = _utc(now)
    with _connect(db) as conn:
        if not _has_table(conn, "ingestion_runs"):
            return "skip"
        rows = conn.execute(
            "SELECT status, started_at FROM ingestion_runs WHERE run_type='news_llm' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    streak = 0
    for status, started in rows:
        started_at = _started(started)
        abandoned = (
            status == "running"
            and started_at is not None
            and current - started_at > NEWS_LLM_RUNNING_LIMIT
        )
        # Old failures are not reported again every day once the job stopped.
        recent = started_at is not None and current - started_at <= RECENT_WINDOW
        if (status != "failed" and not abandoned) or not recent:
            break
        streak += 1
    return str(streak)


def llm_auth(db: str, now: str) -> str:
    current = _utc(now)
    lines = []
    with _connect(db) as conn:
        if not _has_table(conn, "ingestion_runs"):
            return "skip"
        for run_type in LLM_RUN_TYPES:
            run_id = _auth_refused(conn, run_type, current)
            if run_id is not None:
                lines.append(f"{run_type} run_id={run_id}")
    return "\n".join(lines)


def _auth_refused(
    conn: sqlite3.Connection, run_type: str, current: datetime
) -> int | None:
    """The id of the latest run of ``run_type`` when it started within
    RECENT_WINDOW and had a batch refused for its login, else None."""

    row = conn.execute(
        "SELECT id, started_at, metadata_json FROM ingestion_runs"
        " WHERE run_type=? ORDER BY id DESC LIMIT 1",
        (run_type,),
    ).fetchone()
    if row is None:
        return None
    run_id, started, raw = row
    started_at = _started(started)
    # A run of a step that stopped is not reported again every day.
    if started_at is None or current - started_at > RECENT_WINDOW:
        return None
    batches = _json(raw).get("batches") or []
    if any(
        isinstance(batch, dict) and batch.get("reason") == AUTH_REASON
        for batch in batches
    ):
        return int(run_id)
    return None


def daily_result(db: str, day: str, now: str, running_limit: str | None = None) -> str:
    current = _utc(now)
    # A scheduled run's own limit (minutes) when given: the day before is judged after
    # midnight, past the 80-minute limit and serve's 5-minute backstop (#466).
    limit = (
        timedelta(minutes=float(running_limit))
        if running_limit
        else DAILY_RUNNING_LIMIT
    )
    with _connect(db) as conn:
        if not _has_table(conn, "schedule_runs"):
            return "skip"
        rows = conn.execute(
            "SELECT status, started_at, summary_json FROM schedule_runs"
            " WHERE job='daily' AND target_date=? ORDER BY id DESC",
            (day,),
        ).fetchall()
    # A complete run settles the day, even if a later trigger was skipped
    # (for example low_memory at 23:00 after a successful 21:30).
    for status, _started_at, raw in rows:
        if status in COMPLETE:
            steps = _json(raw).get("steps") or {}
            if status == "success" and steps.get("catchup") not in (None, "success"):
                return "catchup_incomplete"
            return status
    for status, started, raw in rows:
        reason = _json(raw).get("reason")
        if status == "skipped" and reason in REFERENCE_SKIPS:
            continue
        if status == "running":
            started_at = _started(started)
            if started_at is not None and current - started_at > limit:
                return "failed"
            return "running"
        if status == "skipped":
            return f"skipped:{reason}"
        return str(status)
    return "none"


def _state(violations: int) -> str:
    return "violation" if violations else "ok"


def invariants(db: str, today: str, now: str | None = None) -> str:
    lines: list[str] = []
    with _connect(db) as conn:
        latest = None
        if _has_table(conn, "market_bars"):
            latest = conn.execute(
                "SELECT max(trading_date) FROM market_bars"
            ).fetchone()[0]
        if latest is None:
            lines.append("future_trading_date skip reason=no_market_bars")
            lines.append("latest_bar_provenance skip reason=no_market_bars")
        else:
            # Date columns are ISO text, so they compare with today as strings.
            latest = str(latest)[:10]
            lines.append(
                f"future_trading_date {_state(latest > today)}"
                f" max_trading_date={latest} today={today}"
            )
            bars, unknown, no_as_of = conn.execute(
                "SELECT count(*),"
                " coalesce(sum(source IS NULL OR source IN ('', 'unknown')), 0),"
                " coalesce(sum(data_as_of IS NULL), 0)"
                " FROM market_bars WHERE trading_date=("
                "SELECT max(trading_date) FROM market_bars)"
            ).fetchone()
            lines.append(
                f"latest_bar_provenance {_state(unknown + no_as_of)}"
                f" trading_date={latest} bars={bars}"
                f" unknown_source={unknown} null_data_as_of={no_as_of}"
            )
        if not _has_table(conn, "news_llm_results"):
            lines.append("llm_done_provenance skip reason=no_news_llm_results")
        else:
            done, no_model, no_prompt = conn.execute(
                "SELECT count(*),"
                " coalesce(sum(llm_model IS NULL OR llm_model=''), 0),"
                " coalesce(sum(prompt_version IS NULL OR prompt_version=''), 0)"
                " FROM news_llm_results WHERE llm_status='done'"
            ).fetchone()
            lines.append(
                f"llm_done_provenance {_state(no_model + no_prompt)}"
                f" done={done} missing_model={no_model}"
                f" empty_prompt_version={no_prompt}"
            )
        if not _has_table(conn, "data_quality"):
            lines.append("instrument_status_sync skip reason=no_data_quality")
        else:
            # The latest sync of each exchange (Issue #212); a skip leaves the
            # statuses stale until a later sync applies.
            rows = conn.execute(
                "SELECT entity_key, status, as_of_date, checks_json FROM data_quality d"
                " WHERE entity_type='instrument_status_sync' AND as_of_date=("
                "SELECT max(as_of_date) FROM data_quality e"
                " WHERE e.entity_type=d.entity_type AND e.entity_key=d.entity_key)"
                " ORDER BY entity_key"
            ).fetchall()
            skipped = [
                f"{key}@{str(day)[:10]}:absent={_json(checks).get('absent', '?')}"
                f",dormant={_json(checks).get('dormant', '?')}"
                for key, status, day, checks in rows
                if status == "skipped"
            ]
            lines.append(
                f"instrument_status_sync {_state(len(skipped))}"
                f" exchanges={len(rows)} skipped={','.join(skipped) or 'none'}"
            )
        lines.append(_execution_calendar(conn))
        lines.append(_strategy_levels(conn))
        lines.append(_candidate_notes(conn, now))
    return "\n".join(lines)


def _execution_calendar(conn: sqlite3.Connection) -> str:
    """Analysis signals of the latest signal date without an earliest execution
    date (Issue #294): the holiday schedule lacks the year or its step failed.

    Only signals written by the calendar-based analyze are judged (their
    evidence has ``execution.calendar``): the older ones stay empty for good
    (no backfill), so a database before the calendar migration, or one whose
    latest signals predate it, is skipped."""

    if not _has_table(conn, "trading_calendar_days"):
        return "execution_calendar skip reason=no_trading_calendar"
    day = conn.execute(
        "SELECT max(signal_date) FROM signals WHERE signal_key LIKE 'analysis-%'"
    ).fetchone()[0]
    if day is None:
        return "execution_calendar skip reason=no_analysis_signals"
    signals, judged, without = conn.execute(
        "SELECT count(*), coalesce(sum(calendar IS NOT NULL), 0),"
        " coalesce(sum(calendar IS NOT NULL AND earliest_execution_date IS NULL), 0)"
        " FROM (SELECT earliest_execution_date, CASE WHEN json_valid(rule_evidence_json)"
        " THEN json_extract(rule_evidence_json, '$.execution.calendar') END AS calendar"
        " FROM signals WHERE signal_key LIKE 'analysis-%' AND signal_date=?)",
        (day,),
    ).fetchone()
    day = str(day)[:10]
    if not judged:
        return (
            "execution_calendar skip reason=signals_before_calendar"
            f" signal_date={day} signals={signals}"
        )
    return (
        f"execution_calendar {_state(without)} signal_date={day}"
        f" signals={judged} without_date={without}"
    )


def _strategy_levels(conn: sqlite3.Connection) -> str:
    """The strategy_levels step of the latest finished daily run that has one
    (Issue #274, #293 review L2).

    The step is non-blocking: its failure leaves the run a success, so only
    this line reports it.  ``skipped`` (analyze did not succeed) is not judged:
    the run's own outcome reports that.  A database without the step (before
    0019, or a release without it) is skipped."""

    if not _has_table(conn, "schedule_run_steps"):
        return "strategy_levels skip reason=no_schedule_run_steps"
    row = conn.execute(
        "SELECT r.id, r.target_date, s.status FROM schedule_run_steps s"
        " JOIN schedule_runs r ON r.id = s.schedule_run_id"
        " WHERE r.job='daily' AND s.step='strategy_levels'"
        " AND r.finished_at IS NOT NULL ORDER BY r.id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return "strategy_levels skip reason=no_strategy_levels_step"
    run_id, target, status = row
    failed = status not in ("success", "no_data", "skipped")
    return (
        f"strategy_levels {_state(failed)} target_date={str(target)[:10]}"
        f" run_id={run_id} status={status}"
    )


def _running(conn: sqlite3.Connection, query: str, current: datetime) -> bool:
    """A row of ``query`` (its started_at) still running within the jobs' limit."""

    for (started,) in conn.execute(query).fetchall():
        started_at = _started(started)
        if started_at is not None and current - started_at <= DAILY_RUNNING_LIMIT:
            return True
    return False


def _candidate_notes(conn: sqlite3.Connection, now: str | None) -> str:
    """The latest candidate list has candidates but not one done AI note
    (Issue #517): a list recomputed by hand without its notes, or a notes step
    that wrote none (claude -p refused, the daily call limit).

    Only the latest trading date's list of CANDIDATE_SCORE_VERSION is judged:
    the one worker.candidate_notes writes notes for (its _candidate_run), so
    ``candidate-notes --date`` can always clear it.  A note of any prompt
    version counts: this only catches a list with none at all.  Not judged
    while a daily or a candidate_notes run is running (the notes are being
    written), nor within CANDIDATE_NOTES_GRACE of the list's computed_at, nor
    when the latest candidate_notes run was refused for its login (llm_auth
    reports that cause already).  Without the clock argument or the tables it
    is skipped."""

    if now is None:
        return "candidate_notes skip reason=no_clock"
    if not all(
        _has_table(conn, name)
        for name in ("candidate_runs", "daily_candidates", "candidate_llm_notes")
    ):
        return "candidate_notes skip reason=no_candidate_tables"
    current = _utc(now)
    if _has_table(conn, "schedule_runs") and _running(
        conn,
        "SELECT started_at FROM schedule_runs WHERE job='daily' AND status='running'",
        current,
    ):
        return "candidate_notes skip reason=daily_running"
    if _has_table(conn, "ingestion_runs") and _running(
        conn,
        "SELECT started_at FROM ingestion_runs"
        " WHERE run_type='candidate_notes' AND status='running'",
        current,
    ):
        return "candidate_notes skip reason=notes_running"
    row = conn.execute(
        "SELECT id, trading_date, computed_at FROM candidate_runs"
        " WHERE score_version=? ORDER BY trading_date DESC LIMIT 1",
        (CANDIDATE_SCORE_VERSION,),
    ).fetchone()
    if row is None:
        return "candidate_notes skip reason=no_candidate_run"
    run_id, trading_date, computed = row
    candidates = conn.execute(
        "SELECT count(*) FROM daily_candidates WHERE candidate_run_id=?", (run_id,)
    ).fetchone()[0]
    done = conn.execute(
        "SELECT count(*) FROM candidate_llm_notes"
        " WHERE candidate_run_id=? AND llm_status='done'",
        (run_id,),
    ).fetchone()[0]
    computed_at = _started(computed)
    minutes = (
        int((current - computed_at).total_seconds() // 60)
        if computed_at is not None
        else None
    )
    facts = (
        f" trading_date={str(trading_date)[:10]} candidate_run_id={run_id}"
        f" candidates={candidates} done={done} minutes={minutes}"
    )
    if not candidates or done:
        return "candidate_notes ok" + facts
    if computed_at is None or current - computed_at <= CANDIDATE_NOTES_GRACE:
        # The notes follow the list (the daily's last step, worker.cli candidates).
        return "candidate_notes skip reason=recent" + facts
    refused = (
        _auth_refused(conn, "candidate_notes", current)
        if _has_table(conn, "ingestion_runs")
        else None
    )
    if refused is not None:
        # One cause, one comment: the llm_auth check comments on the login.
        return f"candidate_notes skip reason=notes_auth notes_run_id={refused}" + facts
    return "candidate_notes violation" + facts


# The monitor polls every minute; ten minutes without a poll is a stop (#316 AC-3).
MONITOR_STALE_SECONDS = 600
# Ten polls in a row (ten minutes) with a failed gh call: the queue gets no PR or
# comment events, though the monitor still beats (#316 review S2).
MONITOR_GH_FAILED_POLLS = 10


def monitor_beat(path: str, now: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return "none"
    try:
        beat = json.loads(text)
        written = beat["written_at"]
        at = datetime.fromisoformat(written.replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError, AttributeError):
        return "unreadable"
    if at.tzinfo is not None:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    age = int((_utc(now) - at).total_seconds())
    if age > MONITOR_STALE_SECONDS:
        return f"stale {age} {written}"
    failed = beat.get("gh_failed_polls")
    if isinstance(failed, int) and failed >= MONITOR_GH_FAILED_POLLS:
        error = " ".join(str(beat.get("gh_error") or "?").replace("`", "'").split())
        return f"gh_failed {failed} {beat.get('gh_failed_since') or '?'} {error[:200]}"
    return f"ok {age}"


def maintenance(path: str, now: str) -> str:
    """The maintenance marker as worker.job.maintenance_state reads it (stdlib only)."""

    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        modified = os.stat(path).st_mtime
    except FileNotFoundError:
        return "off"
    try:
        marker = json.loads(text)
        since = float(marker["since_epoch"])
        reason = " ".join(str(marker.get("reason") or "-").split())
    except (ValueError, KeyError, TypeError):
        since, reason = modified, "unreadable"
    at = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = int(float(now) - since)
    return f"on {age} {at} {reason.replace('`', "'")[:200]}"


def maintenance_expired(path: str, now: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except FileNotFoundError:
        return ""
    current = _utc(now)
    for line in reversed(lines):
        try:
            record = json.loads(line)
            if record.get("event") != "expired":
                continue
            at = datetime.fromisoformat(record["at"])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        at_utc = at.astimezone(timezone.utc).replace(tzinfo=None)
        if not timedelta(0) <= current - at_utc <= RECENT_WINDOW:
            return ""
        words = [
            at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            str(record.get("owner") or "?").replace(" ", "_"),
            str(record.get("pid") or "?"),
            str(record.get("heartbeat_age_minutes") or "?"),
            " ".join(str(record.get("reason") or "-").split()).replace("`", "'")[:200],
        ]
        return " ".join(words)
    return ""


def deploy_image(path: str) -> str:
    """The image this process runs in against the one tools/ops/deploy.sh recorded."""

    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        return "deploy_image skip reason=no_deploy_record"
    try:
        record = json.loads(text)
        recorded, recorded_head, tag = record["image"], record["HEAD"], record["tag"]
    except (ValueError, KeyError, TypeError):
        return "deploy_image violation reason=unreadable_record"
    image = os.environ.get(IMAGE_TAG_ENV) or None
    head = os.environ.get(GIT_HEAD_ENV) or None
    return (
        f"deploy_image {_state(image != recorded or head != recorded_head)}"
        f" image={image or 'unknown'} recorded={recorded}"
        f" head={head or 'unknown'} recorded_head={recorded_head} tag={tag}"
    )


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    command, args = argv[0], argv[1:]
    if command == "news-llm-pending":
        out = news_llm_pending(args[0], int(args[1]))
    elif command == "news-llm-failed":
        out = news_llm_failed(args[0], int(args[1]), args[2])
    elif command == "llm-auth":
        out = llm_auth(args[0], args[1])
    elif command == "daily-result":
        out = daily_result(*args[:4])
    elif command == "invariants":
        out = invariants(*args[:3])
    elif command == "monitor-beat":
        out = monitor_beat(args[0], args[1])
    elif command == "deploy-image":
        out = deploy_image(args[0])
    elif command == "maintenance":
        out = maintenance(args[0], args[1])
    elif command == "maintenance-expired":
        out = maintenance_expired(args[0], args[1])
    elif command == "data-check":
        # Imported here: it loads the backend; the other checks stay stdlib only.
        from data_check import data_check

        options = args[2:]
        out = data_check(
            args[0],
            args[1],
            official="--offline" not in options,
            limit=None if "--all" in options else 20,
            scratch_parent=options[options.index("--scratch") + 1]
            if "--scratch" in options
            else None,
        )
    else:
        raise SystemExit(f"unknown command: {command}")
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, IndexError, sqlite3.Error) as exc:
        print(f"watchdog_helper: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
