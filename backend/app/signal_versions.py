"""Which stored analysis signals the pages read (Issue #392, #404).

analyze writes the registered strategies only.  Signals of a superseded
strategy (``app.strategies.SUPERSEDED``) are still read, as the registered
strategy at the end of their chain (``SUCCESSOR``), on the instrument-days
that have no signal of a newer version of that chain
(``NEWER_VERSIONS``): the dates before a version's first daily show the
version before it, and one instrument-day never shows two versions.

Technical backtest signals (``backtest-<run>-``) use the same strategy rows
but are a replay, not analysis: no page reads them except the backtest summary
(``product_signal``, #484).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import aliased

from .models import Signal, StrategyVersion
from .strategies import NEWER_VERSIONS, REGISTRY

ANALYSIS_PREFIX = "analysis-"
# worker.pipeline's namespace of a backtest run: f"{BACKTEST_PREFIX}{run id}-...".
BACKTEST_PREFIX = "backtest-"


def product_signal() -> Any:
    """Filter out the technical backtest signals (#484).

    A backtest run commits its signals as it goes, so they exist while it runs
    and after it fails, not only after it succeeds.  Two ranges on the unique
    ``signal_key`` index (``-`` is followed by ``.``) rather than NOT LIKE,
    which reads every row's key from the table: a year of backtest rows is
    over a million (#484 review).
    """

    return _outside_backtests(Signal)


def _outside_backtests(signal: Any) -> Any:
    return or_(
        signal.signal_key < BACKTEST_PREFIX,
        signal.signal_key >= f"{BACKTEST_PREFIX[:-1]}.",
    )


def product_signal_ids() -> Any:
    """The ids of ``product_signal()``, read from the signal_key index alone.

    For a filter whose query is driven by another index of ``signals`` (the
    status counts): there a condition on the key itself reads every row.
    """

    inner = aliased(Signal)
    return select(inner.id).where(_outside_backtests(inner))


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

    return and_(
        product_signal(),
        or_(
            StrategyVersion.name.in_(list(REGISTRY)),
            *(
                and_(StrategyVersion.name == name, ~_newer_same_day(newer))
                for name, newer in NEWER_VERSIONS.items()
            ),
        ),
    )
