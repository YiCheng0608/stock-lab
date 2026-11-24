"""Store a trading day's X4 list (Issue #1016).

The daily's ``x4_list`` step (after ``period_backfill``, whose rows it reads) calls ``run_x4_list``: it
computes and writes the day's ``x4`` run and items of ``strategy_list_runs`` /
``strategy_list_items`` (#1014) through ``app.x4_list.compute_x4``.  Rerunning
a date replaces its list.  A failure is a warning: one ``warning:`` line on stderr, which ``worker.job`` writes into
the daily's log, and a ``failed`` result the daily keeps on the step row only
(``schedule_runs.NON_BLOCKING_STEPS``), so the today list, the run's status and
the exit code do not change.  A failed computation commits nothing: the
date's previous list, if any, stays.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from app.x4_list import X4_VERSION, compute_x4
from worker import pipeline


def run_x4_list(target: date) -> dict[str, Any]:
    """Compute and store ``target``'s list; never raises."""

    try:
        # pipeline.SessionLocal, like the other daily steps (and their test patches).
        with pipeline.SessionLocal() as db:
            run = compute_x4(db, target)
            return {
                "status": "success",
                "date": target.isoformat(),
                "version": X4_VERSION,
                "list_status": run.status,
                "universe": run.universe_count,
                "records": run.item_count,
            }
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        error = f"{type(exc).__name__}: {exc}"
        print(
            f"warning: {X4_VERSION} {target.isoformat()} failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        return {
            "status": "failed",
            "date": target.isoformat(),
            "version": X4_VERSION,
            "error": error,
        }
