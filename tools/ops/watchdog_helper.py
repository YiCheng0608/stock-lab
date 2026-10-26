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
  daily-result <db> <date> <now>   the outcome of the daily runs for target
                                   <date> (YYYY-MM-DD): success,
                                   non_trading_day, running, none, skip, a
                                   failing run status, skipped:<reason>, or
                                   catchup_incomplete
  invariants <db> <today>          one line per data invariant,
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
                                   but without earliest_execution_date)

<now> is the watchdog clock in epoch seconds.
"""

from __future__ import annotations

import json
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
# Skipped rows that only point at another run of the same date.
REFERENCE_SKIPS = ("already_complete", "already_running")


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


def daily_result(db: str, day: str, now: str) -> str:
    current = _utc(now)
    with _connect(db) as conn:
        if not _has_table(conn, "schedule_runs"):
            return "skip"
        rows = conn.execute(
            "SELECT status, started_at, summary_json FROM schedule_runs"
            " WHERE job='daily' AND target_date=? ORDER BY id DESC",
            (day,),
        ).fetchall()
    # A complete run settles the day, even if a later trigger was skipped
    # (for example low_memory at 21:30 after a successful 18:30).
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
            if started_at is not None and current - started_at > DAILY_RUNNING_LIMIT:
                return "failed"
            return "running"
        if status == "skipped":
            return f"skipped:{reason}"
        return str(status)
    return "none"


def _state(violations: int) -> str:
    return "violation" if violations else "ok"


def invariants(db: str, today: str) -> str:
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


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    command, args = argv[0], argv[1:]
    if command == "news-llm-pending":
        out = news_llm_pending(args[0], int(args[1]))
    elif command == "news-llm-failed":
        out = news_llm_failed(args[0], int(args[1]), args[2])
    elif command == "daily-result":
        out = daily_result(args[0], args[1], args[2])
    elif command == "invariants":
        out = invariants(args[0], args[1])
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
