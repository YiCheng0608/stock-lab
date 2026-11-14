"""Backfill a research history month by month, newest first (Issue #692).

Runs inside a detached container on the research volume
(docs/ops/RESEARCH_DB.md), never in a session's background shell: each month
is one ``python -m worker.cli backfill --start-date <first> --end-date <last>
--scope market`` (a month is at most 23 weekdays, about ten minutes at three
seconds per host), so a stop loses at most the month in progress, and a rerun
of the same range skips the months the progress file records as done (the
backfill itself reuses its manifests too).

Before each month it checks the Taipei time: from ``PAUSE_FROM`` (21:00, a
month's length before the 21:15 no-request rule) to ``PAUSE_UNTIL`` (23:30) it
sleeps until 23:30, so no request is sent while the production daily runs.

It refuses a database that is the production one (the same check as the
research tools) and a run without ``STOCK_SESSION_BASIS_START`` set: a
backfill before 2024-09-30 belongs in a research database only.  Progress and
each month's exit code and summary go to ``<data>/logs/history-backfill.jsonl``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time as time_module
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable

TAIPEI = timezone(timedelta(hours=8))
PAUSE_FROM = time(21, 0)
PAUSE_UNTIL = time(23, 30)
PROGRESS_NAME = "history-backfill.jsonl"


def months_newest_first(first: date, last: date) -> list[tuple[date, date]]:
    """Calendar-month pieces of ``first``..``last``, the latest month first."""

    if first > last:
        raise ValueError(f"{first} is after {last}")
    pieces = []
    cursor = first
    while cursor <= last:
        month_end = date(
            cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1]
        )
        pieces.append((cursor, min(month_end, last)))
        cursor = month_end + timedelta(days=1)
    return pieces[::-1]


def pause_seconds(now: datetime) -> float:
    """Seconds to wait before a month may start at ``now`` (0 outside the pause)."""

    local = now.astimezone(TAIPEI)
    if not PAUSE_FROM <= local.time() < PAUSE_UNTIL:
        return 0.0
    resume = datetime.combine(local.date(), PAUSE_UNTIL, TAIPEI)
    return (resume - local).total_seconds()


def done_months(progress: Path) -> set[tuple[str, str]]:
    """Months a previous run finished with exit 0."""

    if not progress.is_file():
        return set()
    done = set()
    for line in progress.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("event") == "month" and entry.get("exit") == 0:
            done.add((entry["start"], entry["end"]))
    return done


def _refusal(environ: dict[str, str], db: Path) -> str | None:
    if not (environ.get("STOCK_SESSION_BASIS_START") or "").strip():
        return (
            "STOCK_SESSION_BASIS_START is not set: this is not a research database run"
        )
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backtest_research import production_problem

    return production_problem(db, environ)


def run(
    first: date,
    last: date,
    *,
    data_dir: Path,
    environ: dict[str, str],
    backfill: Callable[[date, date], tuple[int, str]],
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time_module.sleep,
) -> dict[str, int]:
    progress = data_dir / "logs" / PROGRESS_NAME
    progress.parent.mkdir(parents=True, exist_ok=True)
    finished = done_months(progress)
    counts = {"done_before": 0, "ok": 0, "failed": 0}

    def log(entry: dict) -> None:
        entry = {"at": now().isoformat(timespec="seconds"), **entry}
        with progress.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log({"event": "start", "first": first.isoformat(), "last": last.isoformat()})
    for start, end in months_newest_first(first, last):
        key = (start.isoformat(), end.isoformat())
        if key in finished:
            counts["done_before"] += 1
            continue
        wait = pause_seconds(now())
        if wait:
            log({"event": "pause", "seconds": round(wait)})
            sleep(wait)
        code, tail = backfill(start, end)
        log(
            {
                "event": "month",
                "start": key[0],
                "end": key[1],
                "exit": code,
                "tail": tail,
            }
        )
        counts["ok" if code == 0 else "failed"] += 1
    log({"event": "end", **counts})
    return counts


def _worker_backfill(start: date, end: date) -> tuple[int, str]:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "worker.cli",
            "backfill",
            "--start-date",
            start.isoformat(),
            "--end-date",
            end.isoformat(),
            "--scope",
            "market",
        ],
        capture_output=True,
        text=True,
    )
    summary = completed.stdout.strip()
    try:
        result = json.loads(summary)
        tail = json.dumps(
            {
                key: result.get(key)
                for key in ("status", "partial_dates", "failed_dates", "run_ids")
                if key in result
            },
            ensure_ascii=False,
        )
    except ValueError:
        tail = (summary or completed.stderr)[-500:]
    return completed.returncode, tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="history_backfill.py", description=__doc__)
    parser.add_argument("--from", dest="first", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="last", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    environ = dict(os.environ)
    data_dir = Path(environ.get("STOCK_DATA_DIR", "/data"))
    db = Path(environ.get("STOCK_DB_PATH", str(data_dir / "stock.db")))
    problem = _refusal(environ, db)
    if problem:
        print(json.dumps({"refused": [problem]}, ensure_ascii=False))
        return 2
    counts = run(
        args.first,
        args.last,
        data_dir=data_dir,
        environ=environ,
        backfill=_worker_backfill,
    )
    print(json.dumps(counts))
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
