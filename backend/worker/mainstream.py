"""Store a trading day's 主流族群前 20 list (Issue #768).

The daily's ``mainstream`` step (after the today list) calls
``run_mainstream``: it computes and writes ``mainstream_runs`` /
``mainstream_items`` for the day through ``app.mainstream.compute_mainstream``.
Rerunning a date replaces its list.  A failure is a warning: one ``warning:``
line on stderr, which ``worker.job`` writes into the daily's log, and a
``failed`` result the daily keeps on the step row only
(``schedule_runs.NON_BLOCKING_STEPS``), so the today list, the run's status and
the exit code do not change.  A failed computation commits nothing: the
date's previous list, if any, stays.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from app.mainstream import MAINSTREAM_VERSION, compute_mainstream
from worker import pipeline


def run_mainstream(target: date) -> dict[str, Any]:
    """Compute and store ``target``'s list; never raises."""

    try:
        # pipeline.SessionLocal, like the other daily steps (and their test patches).
        with pipeline.SessionLocal() as db:
            run = compute_mainstream(db, target)
            return {
                "status": "success",
                "date": target.isoformat(),
                "version": MAINSTREAM_VERSION,
                "list_status": run.status,
                "groups": [group["group_id"] for group in run.groups_json],
                "records": run.item_count,
            }
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        error = f"{type(exc).__name__}: {exc}"
        print(
            f"warning: {MAINSTREAM_VERSION} {target.isoformat()} failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        return {
            "status": "failed",
            "date": target.isoformat(),
            "version": MAINSTREAM_VERSION,
            "error": error,
        }
