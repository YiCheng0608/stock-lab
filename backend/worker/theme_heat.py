"""Store the 題材熱度 of a day or a range of days (Issue #1017).

The daily's ``theme_heat`` step (after ``h2_list``) calls ``run_theme_heat``:
it computes and writes ``theme_heat_runs`` / ``theme_heat_scores`` for the day
through ``app.theme_heat``.  A failure is a warning: one ``warning:`` line on
stderr, which ``worker.job`` writes into the daily's log, and a ``failed``
result the daily keeps on the step row only (``schedule_runs.
NON_BLOCKING_STEPS``), so the today list, the run's status and the exit code
do not change.  A failed computation commits nothing for that day.

``worker.cli theme-heat`` (``run_theme_heat_range``) recomputes every session
of a range with the members valid on each day, and can report the weekly
ranking (the last session of each ISO week) to compare with #1003's trial.
"""

from __future__ import annotations

import sys
from datetime import date
from typing import Any

from sqlalchemy import select

from app.models import ThemeHeatRun, ThemeHeatScore
from app.theme_heat import (
    THEME_HEAT_VERSION,
    ThemeHeatDataError,
    compute_range,
    compute_theme_heat,
)
from worker import pipeline


def run_theme_heat(target: date) -> dict[str, Any]:
    """Compute and store ``target``'s heat; never raises."""

    try:
        # pipeline.SessionLocal, like the other daily steps (and their test patches).
        with pipeline.SessionLocal() as db:
            run = compute_theme_heat(db, target)
            return {
                "status": "success",
                "date": target.isoformat(),
                "version": THEME_HEAT_VERSION,
                "heat_status": run.status,
                "news_status": run.news_status,
                "themes": run.theme_count,
                "records": run.ranked_count,
            }
    except Exception as exc:  # noqa: BLE001 - a warning, the daily goes on
        error = f"{type(exc).__name__}: {exc}"
        print(
            f"warning: {THEME_HEAT_VERSION} {target.isoformat()} failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        return {
            "status": "failed",
            "date": target.isoformat(),
            "version": THEME_HEAT_VERSION,
            "error": error,
        }


def weekly_last_sessions(days: list[date]) -> list[date]:
    """The last of ``days`` in each ISO week, in order."""

    last: dict[tuple[int, int], date] = {}
    for day in sorted(days):
        year, week, _weekday = day.isocalendar()
        last[(year, week)] = day
    return sorted(last.values())


def weekly_ranking(db: Any, days: list[date]) -> list[dict[str, Any]]:
    """Each week's ranked group ids, read back from the stored scores."""

    rows = []
    for day in weekly_last_sessions(days):
        ranked = db.execute(
            select(ThemeHeatScore.group_id, ThemeHeatScore.heat)
            .join(ThemeHeatRun, ThemeHeatRun.id == ThemeHeatScore.run_id)
            .where(
                ThemeHeatRun.trading_date == day,
                ThemeHeatRun.version == THEME_HEAT_VERSION,
                ThemeHeatScore.rank.is_not(None),
            )
            .order_by(ThemeHeatScore.rank)
        ).all()
        rows.append(
            {
                "date": day.isoformat(),
                "ranking": [
                    {"theme_id": group_id, "heat": heat} for group_id, heat in ranked
                ],
            }
        )
    return rows


def run_theme_heat_range(
    since: date, until: date, *, weekly: bool = False
) -> dict[str, Any]:
    """Recompute and store every session from ``since`` to ``until``."""

    with pipeline.SessionLocal() as db:
        try:
            runs = compute_range(db, since, until)
        except ThemeHeatDataError as exc:
            return {
                "status": "failed",
                "version": THEME_HEAT_VERSION,
                "since": since.isoformat(),
                "until": until.isoformat(),
                "error": str(exc),
            }
        days = [run.trading_date for run in runs]
        result: dict[str, Any] = {
            "status": "success",
            "version": THEME_HEAT_VERSION,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "days": len(runs),
            "computed_days": sum(1 for run in runs if run.status == "computed"),
            "news_days": sum(1 for run in runs if run.news_status == "available"),
            "records": sum(run.ranked_count for run in runs),
        }
        if weekly:
            result["weekly"] = weekly_ranking(db, days)
        return result
