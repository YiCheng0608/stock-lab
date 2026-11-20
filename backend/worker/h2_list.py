"""Store a trading day's H2 list (Issue #881).

The daily's ``h2_list`` step (after ``mainstream``) calls ``run_h2_list``: it
computes and writes ``h2_runs`` / ``h2_items`` for the day through
``app.h2_list.compute_h2``.  Rerunning a date replaces its list.  A failure is
a warning: one ``warning:`` line on stderr, which ``worker.job`` writes into
the daily's log, and a ``failed`` result the daily keeps on the step row only
(``schedule_runs.NON_BLOCKING_STEPS``), so the today list, the run's status and
the exit code do not change.  A failed computation commits nothing: the
date's previous list, if any, stays.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from app.h2_list import H2_VERSION, compute_h2
from worker import pipeline


def run_h2_list(target: date) -> dict[str, Any]:
    """Compute and store ``target``'s list; never raises."""

    try:
        # pipeline.SessionLocal, like the other daily steps (and their test patches).
        with pipeline.SessionLocal() as db:
            run = compute_h2(db, target)
            return {
                "status": "success",
                "date": target.isoformat(),
                "version": H2_VERSION,
                "list_status": run.status,
                "universe": run.universe_count,
                "records": run.item_count,
            }
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        error = f"{type(exc).__name__}: {exc}"
        print(
            f"warning: {H2_VERSION} {target.isoformat()} failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        return {
            "status": "failed",
            "date": target.isoformat(),
            "version": H2_VERSION,
            "error": error,
        }
