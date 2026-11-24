"""Store a trading day's H2 list (Issue #881).

The daily's ``h2_list`` step (after ``mainstream``) calls ``run_h2_list``: it
computes and writes the day's ``h2`` run and items of ``strategy_list_runs`` /
``strategy_list_items`` (#1014) through ``app.h2_list.compute_h2``.  Rerunning
a date replaces its list.  A failure is a warning: one ``warning:`` line on stderr, which ``worker.job`` writes into
the daily's log, and a ``failed`` result the daily keeps on the step row only
(``schedule_runs.NON_BLOCKING_STEPS``), so the today list, the run's status and
the exit code do not change.  A failed computation commits nothing: the
date's previous list, if any, stays.

``backfill_h2`` writes the lists of the last 60 sessions day by day for
the page's 「近 60 日入選過」 (#1021; ``worker.cli strategy-lists``): the days
already stored are kept unless forced, so a rerun writes only what is missing.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from app.h2_list import H2, H2_VERSION, compute_h2
from app.strategy_lists import RECENT_SESSIONS, backfill, latest_session
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


def backfill_h2(
    until: date | None = None, sessions: int = RECENT_SESSIONS, *, force: bool = False
) -> dict[str, Any]:
    """The last ``sessions`` sessions' lists to ``until`` (the latest session
    when None), old to new; ``app.strategy_lists.backfill``."""

    with pipeline.SessionLocal() as db:
        until = until or latest_session(db)
        if until is None:
            return {"status": "failed", "strategy": H2.key, "error": "no session"}
        return backfill(db, H2, until, sessions, force=force)
