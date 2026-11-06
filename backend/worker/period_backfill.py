"""daily's window backfill of the newest quarters and months (Issue #536).

The daily snapshots (``t187ap14``, ``t187ap05``) hold one period, and each
switches to the next period at some point; what a period gets after its
switch never reaches them.  Measured on the 2026-11-06 DB copy (#536 AC-1):
companies listed after the switch (2026Q2: 1; 2026-09: 7), late filings and
corrections.  Before the deadline the MOPS pages also list the companies that
have filed, days before the snapshot shows them.

So daily's ``period_backfill`` step runs the #529／#530 backfills for the
latest period and the one before it, but only on the days around the
statutory deadline (``quarter_window``, ``month_window``); outside both
windows it sends no request.  At most ``QUARTERS`` × 2 + ``MONTHS`` × 4 = 12
pages per daily, under one ``TIME_BUDGET_SECONDS`` budget.  Its outcome never
changes the daily run's status: a failure is a non-core warning in the run's
``summary_json`` (``noncore_warnings``, ``period_backfill``).
"""

from __future__ import annotations

import functools
import time
from datetime import date, timedelta
from typing import Any, Callable

from app.clock import utcnow
from worker import monthly_revenue, pipeline, quarterly_fundamentals
from worker.monthly_revenue import Month
from worker.quarterly_fundamentals import Quarter

STEP = "period_backfill"
TRIGGER = "daily"
# A quarter's window: from LEAD days before its earliest deadline (11/14 for
# Q3) to GRACE days after its latest (11/29, financial holding companies).
QUARTER_LEAD_DAYS = 14
QUARTER_GRACE_DAYS = 14
# A month's window: from the 1st of the next month to GRACE days after the
# deadline, the 10th (the 2026-09 table came out on 10/17, 5 days after the
# deadline rolled to 10/12).
MONTH_GRACE_DAYS = 10
# The latest period and the one before it.
QUARTERS = 2
MONTHS = 2
# No request starts after this many seconds of the step.
TIME_BUDGET_SECONDS = 300.0
# Per HTTP attempt; the manual backfills keep 60 s.
FETCH_TIMEOUT_SECONDS = 30.0
SUMMARY_KEYS = (
    "status",
    "run_id",
    "start_quarter",
    "end_quarter",
    "start_month",
    "end_month",
    "requests",
    "changed",
    "inserted",
    "updated",
    "dated",
    "unchanged",
    "outside_universe",
    "aborted",
    "error",
)


def quarter_window(quarter: Quarter) -> tuple[date, date]:
    deadlines = [
        quarterly_fundamentals.nominal_deadline(name, quarter)
        for name in quarterly_fundamentals.DEADLINES
    ]
    return (
        min(deadlines) - timedelta(days=QUARTER_LEAD_DAYS),
        max(deadlines) + timedelta(days=QUARTER_GRACE_DAYS),
    )


def month_window(month: Month) -> tuple[date, date]:
    return (
        month.next().first_day,
        monthly_revenue.nominal_deadline(month) + timedelta(days=MONTH_GRACE_DAYS),
    )


def _in(window: tuple[date, date], today: date) -> bool:
    return window[0] <= today <= window[1]


def due_quarters(today: date) -> list[Quarter]:
    """The quarters to backfill on ``today``, oldest first; empty outside every window.

    A quarter in its window comes with the one before it; a window can reach
    past the next quarter's end (Q4's runs to 4/14), so the latest two ended
    quarters are both checked.
    """

    latest = Quarter.latest_ended(today)
    due: set[Quarter] = set()
    for quarter in (latest.previous(), latest):
        if _in(quarter_window(quarter), today):
            due |= {quarter.previous(), quarter}
    return sorted(due)[-QUARTERS:]


def due_months(today: date) -> list[Month]:
    """The months to backfill on ``today``, oldest first; empty outside the window."""

    latest = Month.latest_ended(today)
    if not _in(month_window(latest), today):
        return []
    return sorted({latest.previous(), latest})[-MONTHS:]


def taipei_today() -> date:
    return monthly_revenue._taipei_day(utcnow())


def _part(result: dict[str, Any]) -> dict[str, Any]:
    kept = {key: result[key] for key in SUMMARY_KEYS if result.get(key) is not None}
    if result.get("warnings"):
        kept["warnings"] = list(result["warnings"])[:5]
    return kept


def run_period_backfill(
    target: date | None = None,
    *,
    today: date | None = None,
    quarter_fetcher: Callable[[str, dict[str, str]], str] | None = None,
    month_fetcher: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    budget_seconds: float = TIME_BUDGET_SECONDS,
) -> dict[str, Any]:
    """daily's ``period_backfill`` step; ``target`` is the daily's target date.

    The windows are judged on the Taipei date the step runs (the pages answer
    what is filed now, whatever the target), ``today``.  Fundamentals run
    first, then revenue, with what is left of the budget.  ``skipped`` with
    reason ``outside_window`` sends nothing; otherwise ``success`` when every
    part succeeded, ``failed`` when none did and ``partial`` between.
    """

    today = today or taipei_today()
    quarters = due_quarters(today)
    months = due_months(today)
    base: dict[str, Any] = {
        "today": today.isoformat(),
        "target": target.isoformat() if target else None,
        "quarters": [quarter.label for quarter in quarters],
        "months": [month.label for month in months],
        "budget_seconds": budget_seconds,
    }
    if not quarters and not months:
        return {
            **base,
            "status": "skipped",
            "reason": "outside_window",
            "requests": 0,
            "records": 0,
        }
    started = clock()
    parts: dict[str, dict[str, Any]] = {}

    def remaining() -> float:
        return budget_seconds - (clock() - started)

    def run(name: str, action: Callable[[Any], dict[str, Any]]) -> None:
        with pipeline.SessionLocal() as db:
            try:
                parts[name] = _part(action(db))
            except Exception as exc:  # one part must not stop the other
                db.rollback()
                parts[name] = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }

    if quarters:
        run(
            "fundamentals",
            lambda db: quarterly_fundamentals.backfill_quarterly_fundamentals(
                db,
                quarters=len(quarters),
                end=quarters[-1],
                fetcher=quarter_fetcher
                or functools.partial(
                    quarterly_fundamentals.fetch_html,
                    timeout_seconds=FETCH_TIMEOUT_SECONDS,
                ),
                sleep=sleep,
                budget_seconds=max(remaining(), 0.0),
                clock=clock,
                trigger=TRIGGER,
            ),
        )
    if months:
        run(
            "revenue",
            lambda db: monthly_revenue.backfill_monthly_revenues(
                db,
                months=len(months),
                end=months[-1],
                fetcher=month_fetcher
                or functools.partial(
                    monthly_revenue.fetch_page, timeout_seconds=FETCH_TIMEOUT_SECONDS
                ),
                sleep=sleep,
                budget_seconds=max(remaining(), 0.0),
                clock=clock,
                trigger=TRIGGER,
            ),
        )
    statuses = [part.get("status") for part in parts.values()]
    if all(status == "success" for status in statuses):
        status = "success"
    elif all(status == "failed" for status in statuses):
        status = "failed"
    else:
        status = "partial"
    problems = [
        f"{name} {part.get('status')}: "
        + str(
            part.get("error")
            or part.get("aborted")
            or "; ".join(part.get("warnings") or [])
        )
        for name, part in parts.items()
        if part.get("status") != "success"
    ]
    return {
        **base,
        "status": status,
        "requests": sum(int(part.get("requests") or 0) for part in parts.values()),
        "records": sum(int(part.get("changed") or 0) for part in parts.values()),
        "seconds": round(clock() - started, 1),
        **parts,
        "error": "; ".join(problems)[:1000] or None,
    }


def summary(result: dict[str, Any]) -> dict[str, Any]:
    """What the daily run keeps in ``summary_json.period_backfill``."""

    kept = {
        key: result[key]
        for key in (
            "status",
            "reason",
            "today",
            "quarters",
            "months",
            "requests",
            "records",
            "seconds",
            "error",
        )
        if result.get(key) is not None
    }
    for name in ("fundamentals", "revenue"):
        part = result.get(name)
        if isinstance(part, dict):
            kept[name] = {
                key: part[key]
                for key in ("status", "run_id", "requests", "changed", "aborted")
                if part.get(key) is not None
            }
    return kept


def noncore_warning(result: dict[str, Any]) -> str | None:
    """The run's non-core warning for a backfill that did not succeed, else None."""

    status = result.get("status")
    if status in {"success", "skipped"}:
        return None
    detail = result.get("error") or result.get("reason") or status
    return f"MOPS period backfill {status}: {detail}"[:500]
