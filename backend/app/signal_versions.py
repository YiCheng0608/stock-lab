"""Which stored analysis signals the pages read (Issue #392).

analyze writes the registered strategies only.  Signals of a superseded
strategy (``app.strategies.SUPERSEDED``) are still read, as their registered
successor, on the instrument-days that have no signal of a registered
strategy: the dates before the successor's first daily show the old version
and later dates the new one, and one instrument-day never shows both.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import aliased

from .models import Signal, StrategyVersion
from .strategies import REGISTRY, SUCCESSOR

ANALYSIS_PREFIX = "analysis-"


def readable_signal() -> Any:
    """Filter for a query joining ``Signal`` and its ``StrategyVersion``."""

    other = aliased(Signal)
    other_version = aliased(StrategyVersion)
    registered_same_day = exists(
        select(other.id)
        .join(other_version, other_version.id == other.strategy_version_id)
        .where(
            other.instrument_id == Signal.instrument_id,
            other.signal_date == Signal.signal_date,
            other.signal_key.like(f"{ANALYSIS_PREFIX}%"),
            other_version.name.in_(list(REGISTRY)),
        )
    )
    return or_(
        StrategyVersion.name.in_(list(REGISTRY)),
        and_(StrategyVersion.name.in_(list(SUCCESSOR)), ~registered_same_day),
    )
