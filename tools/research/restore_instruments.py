"""Restore the instrument types and statuses an old-date collect rewrote (Issue #838).

Until #838 a collect of an old session (the research backfill, a re-run)
classified today's official lists against that session and wrote the result
over every stored instrument: ``ipo`` for a company listed within 60 days
before the old session, and ``active`` for every code the lists (including a
``company/newlisting`` row of a company that has left the master) carried.
#702 batch 5 turned 8 delisted ``ipo`` instruments back to ``active`` and
flipped 23 others between ``stock`` and ``ipo``.  This tool puts back:

- **status**: the latest ``data_quality`` ``instrument_status`` row of the
  instrument (every status change and every instrument a backfill created
  writes one; the rewrite did not).  An instrument without such a row keeps
  its status.
- **type** (``stock``/``ipo`` only): what the fixed rule gives, i.e. the newest
  stored list captures classified against the day they were captured
  (``worker.instrument_repair._latest_lists``, as a daily collect of that day
  would).  An instrument the lists do not carry keeps its type.

Dry-run is the default; ``--apply`` writes every change in one transaction,
and with ``--expect-changes N`` only when there are exactly N (else it writes
nothing and exits 1).  A second run finds nothing to change.
``--reference <db>`` (a read-only copy of the production database, whose
daily collect applies the same rule to today's lists) adds what it holds for
each change and lists the instruments both databases have whose type or
status would still differ after the changes.  It refuses a
database without the research marker next to it (exit 2): the production
database is never repaired with this tool.  Run it in the backend image with
the research volume at ``/data`` (docs/ops/RESEARCH_DB.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

MARKER_NAME = "research-db.json"
MARKER_PURPOSE = "research_history"
TYPES = ("stock", "ipo")


def refusal(db: Path) -> str | None:
    """Why this database may not be repaired; None for a research database."""

    marker = db.parent / MARKER_NAME
    try:
        purpose = json.loads(marker.read_text(encoding="utf-8")).get("purpose")
    except (OSError, ValueError, AttributeError):
        purpose = None
    if purpose != MARKER_PURPOSE:
        return (
            f"{marker} is missing or not a research marker "
            f'(expected {{"purpose": "{MARKER_PURPOSE}"}}): not a research database'
        )
    if not db.is_file():
        return f"{db} does not exist"
    return None


def latest_statuses(session: Any) -> dict[str, str]:
    """``EXCHANGE:SYMBOL`` -> status of its latest ``instrument_status`` row."""

    from sqlalchemy import select

    from app.models import DataQuality

    latest: dict[str, str] = {}
    for key, status in session.execute(
        select(DataQuality.entity_key, DataQuality.status)
        .where(DataQuality.entity_type == "instrument_status")
        .order_by(DataQuality.as_of_date, DataQuality.id)
    ):
        latest[key] = status
    return latest


def plan(session: Any) -> dict[str, Any]:
    """The changes, and which list captures the types come from."""

    from sqlalchemy import select

    from app.models import Instrument
    from worker.instrument_repair import _latest_lists

    records, evidence, raw_ids = _latest_lists(session)
    listed = {(item.exchange, item.symbol): item.instrument_type for item in records}
    statuses = latest_statuses(session)
    changes = []
    for item in session.scalars(select(Instrument).order_by(Instrument.id)):
        key = f"{item.exchange}:{item.symbol}"
        new_type = item.instrument_type
        listed_type = listed.get((item.exchange, item.symbol))
        if item.instrument_type in TYPES and listed_type in TYPES:
            new_type = listed_type
        new_status = statuses.get(key, item.status)
        if (new_type, new_status) != (item.instrument_type, item.status):
            changes.append(
                {
                    "id": item.id,
                    "code": key,
                    "name": item.name,
                    "type": [item.instrument_type, new_type],
                    "status": [item.status, new_status],
                }
            )
    return {
        "lists": {
            exchange: {
                "observed_date": value["observed_date"].isoformat(),
                "raw_payload_ids": [c["raw_payload_id"] for c in value["captures"]],
            }
            for exchange, value in evidence.items()
        },
        "changes": changes,
    }


def held(path: Path) -> dict[str, list[str]]:
    """``EXCHANGE:SYMBOL`` -> [type, status] of a database, read-only."""

    import sqlite3

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            f"{exchange}:{symbol}": [kind, status]
            for exchange, symbol, kind, status in conn.execute(
                "SELECT exchange, symbol, instrument_type, status FROM instruments"
            )
        }
    finally:
        conn.close()


def compare(
    summary: dict[str, Any],
    reference: dict[str, list[str]],
    stored: dict[str, list[str]],
) -> dict[str, Any]:
    """``summary`` with the reference's values and what differs after it."""

    after = dict(stored)
    for change in summary["changes"]:
        change["reference"] = reference.get(change["code"])
        after[change["code"]] = [change["type"][1], change["status"][1]]
    return {
        **summary,
        "reference_common": sum(key in reference for key in after),
        "differs_from_reference_after": sorted(
            key for key, value in after.items() if reference.get(key, value) != value
        ),
    }


def run(
    db: Path, *, apply: bool, expect: int | None, reference: Path | None = None
) -> tuple[int, dict[str, Any]]:
    problem = refusal(db)
    if problem:
        return 2, {"refused": problem}

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import Instrument

    engine = create_engine(f"sqlite:///{db}")
    try:
        with Session(engine) as session:
            result = plan(session)
            changes = result["changes"]
            summary = {
                "db": str(db),
                **result,
                "count": len(changes),
                "mode": "apply" if apply else "dry_run",
            }
            if reference is not None:
                summary = compare(summary, held(reference), held(db))
            if expect is not None and len(changes) != expect:
                return 1, {**summary, "status": "unexpected", "expected": expect}
            if not apply:
                return 0, {**summary, "status": "planned"}
            for change in changes:
                item = session.get(Instrument, change["id"])
                item.instrument_type = change["type"][1]
                item.status = change["status"][1]
            session.commit()
            return 0, {**summary, "status": "applied"}
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("/data/stock.db"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-changes", type=int, default=None)
    parser.add_argument("--reference", type=Path, default=None)
    args = parser.parse_args(argv)
    code, summary = run(
        args.db,
        apply=args.apply,
        expect=args.expect_changes,
        reference=args.reference,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
