"""The candidate run a page reads for a date (Issue #392, #407 review M3).

``candidate_score_v3`` replaced ``candidate_score_v2`` when the registered
strategies replaced the superseded ones; past runs are not recomputed.  A date shows
its run of the current version, or else its run of the previous one, so the
dates before the switch keep their candidates and one date never mixes two
versions.  The daily writer (worker.candidates) and the LLM notes only use
the current version.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import case, desc, select
from sqlalchemy.orm import Session

from .domain import CANDIDATE_SCORE_READ_VERSIONS
from .models import CandidateRun


def version_order() -> Any:
    """0 for the current version, 1 for the previous one."""

    return case(
        *(
            (CandidateRun.score_version == version, position)
            for position, version in enumerate(CANDIDATE_SCORE_READ_VERSIONS)
        ),
        else_=len(CANDIDATE_SCORE_READ_VERSIONS),
    )


def read_run(
    db: Session, trading_date: date | None, *, on_or_before: bool = False
) -> CandidateRun | None:
    """The run shown for ``trading_date`` (the latest date when None).

    ``on_or_before`` takes the latest date up to ``trading_date`` that has a
    readable run.
    """

    query = select(CandidateRun).where(
        CandidateRun.score_version.in_(CANDIDATE_SCORE_READ_VERSIONS)
    )
    if trading_date is not None:
        query = query.where(
            CandidateRun.trading_date <= trading_date
            if on_or_before
            else CandidateRun.trading_date == trading_date
        )
    return db.scalar(
        query.order_by(
            desc(CandidateRun.trading_date), version_order(), desc(CandidateRun.id)
        ).limit(1)
    )
