"""Research-only strategy ablations (#318): a registered strategy minus one condition.

An ablation is a :class:`Strategy` named ``<strategy>_ablate_<condition>``
whose configuration is the canonical one without that condition's
threshold keys; its rule is the strategy's evaluator given that
configuration, so the removed comparison is skipped and every other check,
the required inputs included, is unchanged.  Ablations never enter
``REGISTRY``: only a research backtest on an isolated database
(``worker.pipeline.backtest(registry=...)``) evaluates them, and that run
writes their StrategyVersion rows.
"""

from __future__ import annotations

import copy
import functools
from typing import Any

from . import REGISTRY, registry_problems
from .base import Strategy

# Condition -> the config keys (paths) that hold its threshold.
ABLATIONS: dict[str, dict[str, tuple[tuple[str, ...], ...]]] = {
    "breakout_v1": {
        "breakout": (("price",),),
        "volume": (("volume",),),
        "group": (("confirmations", "group_relative_strength"),),
        "institutional": (("confirmations", "institutional_flow"),),
        "margin": (("confirmations", "margin_financing"),),
    },
    "pullback_v1": {
        "trend": (("trend", "ma_alignment"), ("trend", "close_must_be_at_or_above")),
        "support": (("support_zone",),),
        "volume": (("volume",),),
        "group": (("confirmations", "group_relative_strength"),),
        "institutional": (("confirmations", "institutional_flow"),),
        "margin": (("confirmations", "margin_financing"),),
    },
}


def ablated_strategy(strategy_key: str, condition: str) -> Strategy:
    """``REGISTRY[strategy_key]`` without ``condition``, under its own name and kind.

    The kind is distinct as well, so one backtest can evaluate the canonical
    strategies and their ablations side by side (each kind keys its own
    state in ``rule_evidence_json``).
    """

    base = REGISTRY[strategy_key]
    paths = ABLATIONS[strategy_key][condition]
    config: dict[str, Any] = copy.deepcopy(dict(base.config))
    for path in paths:
        parent = config
        for part in path[:-1]:
            parent = parent[part]
        del parent[path[-1]]
    config["name"] = f"{strategy_key}_ablate_{condition}"
    config["kind"] = f"{base.kind}_ablate_{condition}"
    config["ablation"] = {
        "base_strategy": strategy_key,
        "base_version": base.version,
        "removed_condition": condition,
        "removed_keys": [".".join(path) for path in paths],
    }
    strategy = copy.copy(base)
    strategy.config = config
    strategy.rule = functools.partial(type(base).rule, config=config)
    return strategy


def research_registry(
    ablations: list[tuple[str, str]], *, canonical: bool = True
) -> dict[str, Strategy]:
    """The registry a research backtest evaluates: canonical strategies, then ablations."""

    registry: dict[str, Strategy] = dict(REGISTRY) if canonical else {}
    for strategy_key, condition in ablations:
        strategy = ablated_strategy(strategy_key, condition)
        registry[strategy.key] = strategy
    problems = registry_problems(registry)
    if problems or not registry:
        raise ValueError("; ".join(problems) or "empty research registry")
    return registry


def all_ablations() -> list[tuple[str, str]]:
    return [
        (strategy_key, condition)
        for strategy_key, conditions in ABLATIONS.items()
        for condition in conditions
    ]
