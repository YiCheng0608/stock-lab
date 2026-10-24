"""Refreeze tools/verify/fixture_candidates.json from the current scorer (Issue #241).

    python tools/verify/freeze_candidates.py [--check] [--work <empty directory>]

Builds the fixture database without its three candidate tables' rows, runs
``worker.candidates.compute_daily_candidates`` for the fixture's trading date and
writes the run summary and ranked rows (without timestamps or elapsed time).
``--check`` compares instead of writing and exits 1 when the file is stale; run
it without ``--check`` after a change to the signals, groups or scorer.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "fixture_candidates.json"
COMMENT = (
    "Frozen output of worker.candidates.compute_daily_candidates on this fixture; "
    "regenerate with tools/verify/freeze_candidates.py."
)
CANDIDATE_TABLES = ("candidate_runs", "daily_candidates", "candidate_llm_notes")
ROW_FIELDS = (
    "instrument_id",
    "signal_id",
    "strategy",
    "total_score",
    "weight_coverage",
    "rank",
    "components_json",
    "reasons_json",
    "groups_json",
)


def rescore(work: Path) -> dict:
    sys.path.insert(0, str(HERE))
    import fixture_db

    fixture_db.build(work, skip=CANDIDATE_TABLES)
    from sqlalchemy import select

    import fixture_data
    from app.db import SessionLocal, engine
    from app.models import CandidateRun, DailyCandidate
    from worker.candidates import compute_daily_candidates

    with SessionLocal() as db:
        compute_daily_candidates(db, fixture_data.TRADING_DATE)
    with SessionLocal() as db:
        run = db.scalar(select(CandidateRun))
        summary = dict(run.summary_json)
        summary.pop("elapsed_seconds", None)
        rows = db.scalars(select(DailyCandidate).order_by(DailyCandidate.rank)).all()
        frozen = {
            "_comment": COMMENT,
            "run": {
                "evaluated_signals": run.evaluated_signals,
                "pool_count": run.pool_count,
                "candidate_count": run.candidate_count,
                "exclusions_json": run.exclusions_json,
                "summary_json": summary,
            },
            "rows": [
                {field: getattr(row, field) for field in ROW_FIELDS} for row in rows
            ],
        }
    engine.dispose()
    return frozen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    parser.add_argument("--work", type=Path, help="empty directory for the build")
    args = parser.parse_args()
    if args.work is None:
        with tempfile.TemporaryDirectory(prefix="fixture-") as work:
            frozen = rescore(Path(work))
    else:
        frozen = rescore(args.work.resolve())
    text = json.dumps(frozen, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if FROZEN.read_text(encoding="utf-8") != text:
            raise SystemExit(
                f"{FROZEN.name} is stale; run tools/verify/freeze_candidates.py"
            )
        print(f"{FROZEN.name} matches the current scorer")
        return
    FROZEN.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {FROZEN}")


if __name__ == "__main__":
    main()
