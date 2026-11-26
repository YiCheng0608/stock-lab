"""Reading the stored pre-market AI readings (Issue #1041, docs/spec/premarket_ai.md).

``premarket_ai_readings`` keeps every run of a trading day, prompt version and
role as its own row (``sequence`` 1, 2, ...); a row is never changed.  The
day's reading of a version and role is its ``done`` row when there is one,
else the latest row.  Only ``worker.premarket_ai`` and the tests read this
module; the API and the 08:45 message read it through #1042.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .models import PremarketAiReading, PremarketAiStock

CHAMPION = "champion"
SHADOW = "shadow"
ROLES = (CHAMPION, SHADOW)
DONE = "done"
FAILED = "failed"
REJECTED = "rejected"
STATUSES = (DONE, FAILED, REJECTED)
# pool_phase: candidate_pool_v1's morning round (evening plus morning items),
# its evening round alone (no morning round yet at 08:21), or the stand-in pool.
POOL_PHASES = ("morning", "evening", "interim")


def readings(
    db: Session, session_date: date, prompt_version: str, role: str
) -> list[PremarketAiReading]:
    """The rows of one day, version and role, oldest first."""

    return list(
        db.scalars(
            select(PremarketAiReading)
            .where(
                PremarketAiReading.session_date == session_date,
                PremarketAiReading.prompt_version == prompt_version,
                PremarketAiReading.role == role,
            )
            .order_by(PremarketAiReading.sequence)
        )
    )


def done_reading(
    db: Session, session_date: date, prompt_version: str, role: str
) -> PremarketAiReading | None:
    return db.scalar(
        select(PremarketAiReading)
        .where(
            PremarketAiReading.session_date == session_date,
            PremarketAiReading.prompt_version == prompt_version,
            PremarketAiReading.role == role,
            PremarketAiReading.status == DONE,
        )
        .order_by(PremarketAiReading.sequence)
        .limit(1)
    )


def day_reading(
    db: Session, session_date: date, prompt_version: str, role: str = CHAMPION
) -> PremarketAiReading | None:
    """The day's reading: its done row, else its latest row, else None."""

    done = done_reading(db, session_date, prompt_version, role)
    if done is not None:
        return done
    return db.scalar(
        select(PremarketAiReading)
        .where(
            PremarketAiReading.session_date == session_date,
            PremarketAiReading.prompt_version == prompt_version,
            PremarketAiReading.role == role,
        )
        .order_by(desc(PremarketAiReading.sequence))
        .limit(1)
    )


def next_sequence(
    db: Session, session_date: date, prompt_version: str, role: str
) -> int:
    latest = db.scalar(
        select(func.max(PremarketAiReading.sequence)).where(
            PremarketAiReading.session_date == session_date,
            PremarketAiReading.prompt_version == prompt_version,
            PremarketAiReading.role == role,
        )
    )
    return (latest or 0) + 1


def stocks(db: Session, reading_id: int) -> list[PremarketAiStock]:
    return list(
        db.scalars(
            select(PremarketAiStock)
            .where(PremarketAiStock.reading_id == reading_id)
            .order_by(PremarketAiStock.position)
        )
    )
