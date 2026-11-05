"""Plain-language entry plan of a candidate (``entry_plan``, #491).

A candidate is a signal judged actionable on its date T.  Its entry plan is
that signal's ``strategy_levels`` row (docs/spec/strategy_levels.md): the
close and volume the next session (T+1) needs for the strategy to pass again,
with the reference stop and targets computed from it, and the full condition
list.  It is display only: candidate scoring, the decision summary and the
tracking plans do not read it, the candidate's own ``levels`` (the signal's)
are unchanged, and nothing is computed at request time.  A signal without a
row of the current levels version (a date before the table, or a failed
step) has no plan (None); the page says so instead of guessing a price.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import STRATEGY_LEVELS_VERSION
from .models import Signal, StrategyLevel, StrategyVersion
from .presentation import display_reason
from .strategies import current_strategy
from .strategies import levels as level_rules


def level_fields(row: StrategyLevel) -> dict[str, Any]:
    """The stored levels of one row, shared by the strategy board and the entry plan."""

    return {
        "availability": row.availability,
        "next_session_date": row.next_session_date.isoformat()
        if row.next_session_date
        else None,
        "trigger_price": row.trigger_price,
        "zone_low": row.zone_low,
        "zone_high": row.zone_high,
        "min_volume": row.min_volume,
        "max_volume": row.max_volume,
        "reference_entry": row.reference_entry,
        "entry_low": row.entry_low,
        "entry_high": row.entry_high,
        "invalid_price": row.invalid_price,
        "target_1": row.target_1,
        "target_2": row.target_2,
        "risk_reward": row.risk_reward,
        "reachable_next_session": row.reachable_next_session,
        "price_basis": row.price_basis,
        "missing_inputs": list(row.missing_inputs_json or []),
        "missing_labels": list(
            dict.fromkeys(
                display_reason(item) for item in row.missing_inputs_json or []
            )
        ),
    }


def entry_plan(db: Session, signal: Signal | None) -> dict[str, Any] | None:
    if signal is None:
        return None
    row = db.scalar(
        select(StrategyLevel).where(
            StrategyLevel.signal_id == signal.id,
            StrategyLevel.levels_version == STRATEGY_LEVELS_VERSION,
        )
    )
    if row is None:
        return None
    version = db.get(StrategyVersion, signal.strategy_version_id)
    strategy = (
        current_strategy(version.name, version.version, version.formula_version)
        if version is not None
        else None
    )
    return {
        "levels_version": row.levels_version,
        "entry_type": signal.entry_type,
        **level_fields(row),
        # Another version's row is history: its conditions follow that
        # version's defaults, so they are not expanded with today's.
        "conditions": level_rules.expand_conditions(strategy, row.conditions_json)
        if strategy is not None
        else [],
    }
