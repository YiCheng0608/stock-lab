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


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    command, args = argv[0], argv[1:]
    if command == "news-llm-pending":
        out = news_llm_pending(args[0], int(args[1]))
    elif command == "news-llm-failed":
        out = news_llm_failed(args[0], int(args[1]), args[2])
    elif command == "daily-result":
        out = daily_result(args[0], args[1], args[2])
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
