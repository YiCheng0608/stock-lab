"""The worker child of the job in test_worker_job's fixture-database test (#313 AC-4).

``python job_daily_child.py daily ...`` is ``python -m worker.cli daily ...`` with
the steps that reach outside faked: no socket may connect, collect hands over the
fixture's own collect run of the target date instead of fetching, catch-up reports
success, the trading calendar is not downloaded and candidate_notes never starts
claude. Everything else (schedule_runs, analyze,
evaluate, candidates, ...) runs for real on the database the job points it at.
"""

from __future__ import annotations

import socket
import sys

from sqlalchemy import desc, select

from app.models import IngestionRun
import worker.cli as cli
import worker.pipeline as pipeline
import worker.schedule_runs as schedule_runs


def _forbidden(*_args, **_kwargs):
    raise AssertionError("network forbidden in the job's fixture-database test")


def _collect(target, **_kwargs):
    """The fixture's own successful official collect of TARGET, fetched before."""

    with pipeline.SessionLocal() as db:
        run_id = db.scalar(
            select(IngestionRun.id)
            .where(
                IngestionRun.run_type == "collect",
                IngestionRun.source == "official",
                IngestionRun.status == "success",
                IngestionRun.data_as_of.like(f"{target.isoformat()}%"),
            )
            .order_by(desc(IngestionRun.id))
            .limit(1)
        )
    return {"status": "success", "records": 0, "run_id": run_id}


socket.socket.connect = _forbidden
socket.socket.connect_ex = _forbidden
pipeline.collect = _collect
schedule_runs._catchup_step = lambda *_args: {"status": "success", "records": 0}
schedule_runs._trading_calendar_step = lambda *_args: {
    "status": "success",
    "records": 0,
}
schedule_runs._candidate_note_step = lambda *_args: {
    "status": "skipped",
    "reason": "faked by the test",
}

sys.argv = ["worker.cli", *sys.argv[1:]]
cli.main()
