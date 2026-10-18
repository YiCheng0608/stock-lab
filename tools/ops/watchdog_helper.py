"""Read-only database helper for tools/ops/watchdog.sh.

Git Bash on the scheduler host has no sqlite3, so the watchdog calls this
module for the one database check; every decision stays in the shell script.
The result goes to stdout without a trailing newline.

  news-llm-pending <db> <n>        how many of the last <n> news_llm batches are
                                   pending in a row, or "skip" without the table
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def news_llm_pending(db: str, limit: int) -> str:
    uri = Path(db).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ingestion_runs'"
        ).fetchone():
            return "skip"
        rows = conn.execute(
            "SELECT metadata_json FROM ingestion_runs WHERE run_type='news_llm' ORDER BY id DESC LIMIT 50"
        ).fetchall()
    statuses: list[str] = []
    for (raw,) in rows:
        try:
            metadata = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        batches = (metadata or {}).get("batches") or []
        statuses.extend(str(batch.get("status")) for batch in reversed(batches))
        if len(statuses) >= limit:
            break
    streak = 0
    for status in statuses[:limit]:
        if status != "pending":
            break
        streak += 1
    return str(streak)


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    command, args = argv[0], argv[1:]
    if command == "news-llm-pending":
        out = news_llm_pending(args[0], int(args[1]))
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
