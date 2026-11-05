"""Store a trading day's action tiers for the pages (Issue #476).

The daily's ``action_tiers`` step (after strategy_levels) and
``worker.cli action-tiers`` call ``run_action_tiers``: it writes
``action_tier_snapshots`` for the day through
``app.action_tier_store.write_action_tier_snapshot``.  Rerunning a date
rewrites its row.  The pages compute live whenever the row is missing or its
inputs changed since, so a failure here never changes what they show, only
how fast.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.action_tier_store import ACTION_TIER_STORE_VERSION, write_action_tier_snapshot
from app.decision import latest_official_as_of
from worker import pipeline


def run_action_tiers(target: date | None = None) -> dict[str, Any]:
    """Store ``target``'s tiers (default: the pages' latest official day)."""

    # pipeline.SessionLocal, like the other daily steps (and their test patches).
    with pipeline.SessionLocal() as db:
        day = target if target is not None else latest_official_as_of(db)[1]
        if day is None:
            return {
                "status": "no_data",
                "reason": "no_official_day",
                "date": None,
                "records": 0,
            }
        row = write_action_tier_snapshot(db, day)
        result = {
            "status": "success",
            "date": day.isoformat(),
            "store_version": ACTION_TIER_STORE_VERSION,
            "records": row.row_count,
            "fingerprint": row.fingerprint,
        }
        db.commit()
    return result
