"""Which stored analysis signals the pages read (Issue #392, #404).

analyze writes the registered strategies only.  Signals of a superseded
strategy (``app.strategies.SUPERSEDED``) are still read, as the registered
strategy at the end of their chain (``SUCCESSOR``), on the instrument-days
that have no signal of a newer version of that chain
(``NEWER_VERSIONS``): the dates before a version's first daily show the
version before it, and one instrument-day never shows two versions.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import aliased

from .models import Signal, StrategyVersion
from .strategies import NEWER_VERSIONS, REGISTRY

ANALYSIS_PREFIX = "analysis-"


def _newer_same_day(names: tuple[str, ...]) -> Any:
    other = aliased(Signal)
    other_version = aliased(StrategyVersion)
    return exists(
        select(other.id)
        .join(other_version, other_version.id == other.strategy_version_id)
        .where(
            other.instrument_id == Signal.instrument_id,
            other.signal_date == Signal.signal_date,
            other.signal_key.like(f"{ANALYSIS_PREFIX}%"),
            other_version.name.in_(list(names)),
        )
    )


def readable_signal() -> Any:
    """Filter for a query joining ``Signal`` and its ``StrategyVersion``."""

    return or_(
        StrategyVersion.name.in_(list(REGISTRY)),
        *(
            and_(StrategyVersion.name == name, ~_newer_same_day(newer))
            for name, newer in NEWER_VERSIONS.items()
        ),
    )
