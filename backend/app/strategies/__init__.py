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

# ``kind`` keys each strategy's state in every signal's rule_evidence_json
# and rationale, next to these fixed keys (worker.pipeline writes them; the
# rationale's ``group=`` and ``missing=`` parts are read by presentation).
# A kind equal to one of them, or to another strategy's kind, would silently
# overwrite that entry.
RESERVED_KINDS = frozenset(
    {
        "strategy",
        "strategy_version",
        "group_member_return_lookup",
        "confidence_semantics",
        "actionable",
        "inputs",
        "risk_validation",
        "execution",
        "group",
        "missing",
    }
)


def registry_problems(registry: Mapping[str, Strategy]) -> list[str]:
    """Kinds that are reused or reserved; empty for a usable registry."""

    problems = []
    seen: dict[str, str] = {}
    for key, strategy in registry.items():
        if strategy.kind in RESERVED_KINDS:
            problems.append(f"{key}: kind {strategy.kind!r} is a reserved key")
        if strategy.kind in seen:
            problems.append(
                f"{key}: kind {strategy.kind!r} is already used by {seen[strategy.kind]}"
            )
        seen.setdefault(strategy.kind, key)
    return problems


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
    "RESERVED_KINDS",
    "SignalLevels",
    "Strategy",
    "StrategyInputs",
    "canonical_config_snapshot",
    "canonical_configs",
    "evaluate_breakout_v1",
    "evaluate_pullback_v1",
    "finite_number",
    "registry_problems",
    "risk_levels",
    "strategy_by_kind",
    "strategy_configs",
]
