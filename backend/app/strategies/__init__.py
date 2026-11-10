"""Strategy registry (docs/spec/README.md 策略版本識別).

``REGISTRY`` is the only place that declares which strategies exist.  analyze
writes one ``signals`` row per registered strategy for every instrument and
session; the decision summary, the API and the candidate list read the
registry for entry types, labels and level fields.  The candidate pool is
not derived from it: each ``candidate_score`` version lists its strategies,
so a new strategy enters the candidate list only with a new score version.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from app.domain import HOT_GROUP_CONFIG, INSTITUTIONAL_FLOW_FORMULA_VERSION

from .base import (
    ENTRY_LEVEL_FIELDS,
    ENTRY_REQUIRED_LEVELS,
    LEGACY_RISK_LEVELS_FORMULA,
    PULLBACK_ZONE_MIDPOINT_FORMULA,
    Condition,
    NextSessionInputs,
    ObservationLevels,
    SignalLevels,
    Strategy,
    StrategyInputs,
    finite_number,
    risk_levels,
)
from .breakout_v1 import BREAKOUT_V1, evaluate_breakout_v1
from .breakout_v2 import BREAKOUT_V2, evaluate_breakout_v2
from .breakout_v3 import BREAKOUT_V3, evaluate_breakout_v3
from .pullback_v1 import PULLBACK_V1, evaluate_pullback_v1
from .pullback_v2 import PULLBACK_V2, evaluate_pullback_v2
from .pullback_v3 import PULLBACK_V3, evaluate_pullback_v3
from .pullback_v4 import PULLBACK_V4

# Declaration order is the product order: the decision summary takes the
# first conditional strategy in this order, and every signal's rationale and
# evidence list the strategies in it.
REGISTRY: dict[str, Strategy] = {
    strategy.key: strategy for strategy in (BREAKOUT_V3, PULLBACK_V4)
}

# Strategies analyze no longer writes, kept so their stored signals still
# read (Issue #392, #404, #580).  Each strategy's config names the version it took
# the place of (``supersedes``), so the versions of one kind form a chain
# ending at a registered strategy: readers show, for each instrument-day,
# only the newest version that has a signal there, keyed by the registered
# strategy (``app.signal_versions``; the levels step applies the same rule).
SUPERSEDED: dict[str, Strategy] = {
    strategy.key: strategy
    for strategy in (BREAKOUT_V1, PULLBACK_V1, BREAKOUT_V2, PULLBACK_V2, PULLBACK_V3)
}


def _older_versions(strategy: Strategy) -> list[str]:
    """The superseded versions ``strategy`` replaced, newest first."""

    older: list[str] = []
    while "supersedes" in strategy.config:
        name = strategy.config["supersedes"]["name"]
        strategy = SUPERSEDED[name]
        older.append(name)
    return older


# Superseded version -> the registered strategy at the end of its chain.
SUCCESSOR: dict[str, str] = {
    name: key
    for key, strategy in REGISTRY.items()
    for name in _older_versions(strategy)
}
# Superseded version -> the versions of its chain newer than it, newest first
# (the registered strategy included): one of them on the same instrument-day
# hides it.
NEWER_VERSIONS: dict[str, tuple[str, ...]] = {
    name: (key, *_older_versions(strategy)[:position])
    for key, strategy in REGISTRY.items()
    for position, name in enumerate(_older_versions(strategy))
}


def newest_versions(names: Iterable[str]) -> set[str]:
    """Of the strategy names stored on one instrument-day, those that are read.

    A superseded version is read only without a newer version of its chain
    on that day.
    """

    present = set(names)
    return {
        name
        for name in present
        if not any(newer in present for newer in NEWER_VERSIONS.get(name, ()))
    }


def registry_key(name: str) -> str | None:
    """The registered strategy a stored signal of ``name`` is read as; None if none."""

    return name if name in REGISTRY else SUCCESSOR.get(name)


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


def risk_reward_basis(name: str | None) -> str | None:
    """What the stored entry of a ``name`` signal's RR is (#580); None if unknown."""

    strategy = (REGISTRY.get(name) or SUPERSEDED.get(name)) if name else None
    return strategy.risk_reward_basis if strategy is not None else None


def strategy_by_kind(kind: str) -> Strategy | None:
    return next(
        (strategy for strategy in REGISTRY.values() if strategy.kind == kind), None
    )


def current_strategy(name: str, version: str, formula_version: str) -> Strategy | None:
    """The strategy a StrategyVersion row is the current version of.

    A superseded strategy (``SUPERSEDED``) is its own last version: its rows
    read with its own conditions and defaults.  A row of another version or
    institutional-flow formula is history: its
    stored levels and conditions follow that version's rules, not today's
    defaults (#274 review L1).
    """

    strategy = REGISTRY.get(name) or SUPERSEDED.get(name)
    if (
        strategy is None
        or strategy.version != version
        or formula_version != INSTITUTIONAL_FLOW_FORMULA_VERSION
    ):
        return None
    return strategy


def strategy_configs(
    registry: Mapping[str, Strategy] | None = None,
) -> dict[str, Mapping[str, Any]]:
    registry = REGISTRY if registry is None else registry
    return {key: strategy.config for key, strategy in registry.items()}


def canonical_configs(
    registry: Mapping[str, Strategy] | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Every configuration persisted as a StrategyVersion row.

    ``registry`` replaces REGISTRY only for a research backtest
    (``app.strategies.ablation``).
    """

    return {**strategy_configs(registry), HOT_GROUP_CONFIG["name"]: HOT_GROUP_CONFIG}


def canonical_config_snapshot(
    registry: Mapping[str, Strategy] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return a JSON round-tripped copy suitable for database persistence."""

    return json.loads(json.dumps(canonical_configs(registry), sort_keys=True))


__all__ = [
    "ENTRY_LEVEL_FIELDS",
    "ENTRY_REQUIRED_LEVELS",
    "LEGACY_RISK_LEVELS_FORMULA",
    "PULLBACK_ZONE_MIDPOINT_FORMULA",
    "NEWER_VERSIONS",
    "Condition",
    "NextSessionInputs",
    "ObservationLevels",
    "REGISTRY",
    "RESERVED_KINDS",
    "SUCCESSOR",
    "SUPERSEDED",
    "SignalLevels",
    "Strategy",
    "StrategyInputs",
    "canonical_config_snapshot",
    "canonical_configs",
    "current_strategy",
    "evaluate_breakout_v1",
    "evaluate_breakout_v2",
    "evaluate_breakout_v3",
    "evaluate_pullback_v1",
    "evaluate_pullback_v2",
    "evaluate_pullback_v3",
    "finite_number",
    "registry_problems",
    "newest_versions",
    "registry_key",
    "risk_reward_basis",
    "risk_levels",
    "strategy_by_kind",
    "strategy_configs",
]
