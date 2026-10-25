"""Strategy registry (V1_SPEC 策略版本識別).

``REGISTRY`` is the only place that declares which strategies exist.  analyze
writes one ``signals`` row per registered strategy for every instrument and
session; the decision summary, the API and the candidate list read the
registry for entry types, labels and level fields.  The candidate pool is
not derived from it: each ``candidate_score`` version lists its strategies,
so a new strategy enters the candidate list only with a new score version.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from app.domain import HOT_GROUP_CONFIG

from .base import (
    ENTRY_LEVEL_FIELDS,
    ENTRY_REQUIRED_LEVELS,
    LEGACY_RISK_LEVELS_FORMULA,
    SignalLevels,
    Strategy,
    StrategyInputs,
    finite_number,
    risk_levels,
)
from .breakout_v1 import BREAKOUT_V1, evaluate_breakout_v1
from .pullback_v1 import PULLBACK_V1, evaluate_pullback_v1

# Declaration order is the product order: the decision summary takes the
# first conditional strategy in this order, and every signal's rationale and
# evidence list the strategies in it.
REGISTRY: dict[str, Strategy] = {
    strategy.key: strategy for strategy in (BREAKOUT_V1, PULLBACK_V1)
}


def strategy_by_kind(kind: str) -> Strategy | None:
    return next(
        (strategy for strategy in REGISTRY.values() if strategy.kind == kind), None
    )


def strategy_configs() -> dict[str, Mapping[str, Any]]:
    return {key: strategy.config for key, strategy in REGISTRY.items()}


def canonical_configs() -> dict[str, Mapping[str, Any]]:
    """Every configuration persisted as a StrategyVersion row."""

    return {**strategy_configs(), HOT_GROUP_CONFIG["name"]: HOT_GROUP_CONFIG}


def canonical_config_snapshot() -> dict[str, dict[str, Any]]:
    """Return a JSON round-tripped copy suitable for database persistence."""

    return json.loads(json.dumps(canonical_configs(), sort_keys=True))


__all__ = [
    "ENTRY_LEVEL_FIELDS",
    "ENTRY_REQUIRED_LEVELS",
    "LEGACY_RISK_LEVELS_FORMULA",
    "REGISTRY",
    "SignalLevels",
    "Strategy",
    "StrategyInputs",
    "canonical_config_snapshot",
    "canonical_configs",
    "evaluate_breakout_v1",
    "evaluate_pullback_v1",
    "finite_number",
    "risk_levels",
    "strategy_by_kind",
    "strategy_configs",
]
