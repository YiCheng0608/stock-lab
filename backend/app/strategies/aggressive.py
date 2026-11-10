"""Research-only aggressive versions (#598): a current strategy with one threshold relaxed.

An aggressive version is named ``<strategy>_aggr_<code>`` (kind
``<kind>_aggr_<code>``).  Its configuration is the base strategy's with the
changes ``VARIANTS`` lists for that base, and its rule is the base's
evaluator given that configuration, the mechanism research ablations use
(``app.strategies.ablation``): a removed confirmation is not checked, a
changed threshold is compared instead of the old one, and every other check,
the required inputs included, is unchanged.  A1～A6 change one place each;
A7 is the A1／A5＋A2＋A3 package and changes exactly those three.

Each change only relaxes, so on every instrument-day a version passes
whenever its base passes (the tests check it); the signals only the version
passes are the ones the report calls 多出來的訊號.

Only the rule reads the changed configuration.  ``observation_levels`` and
``conditions`` (the next session's thresholds and the page's condition list)
read the base modules' own ``CONFIG``, and ``volume_ratio_below_1_20`` keeps
its name under A1's 1.00 threshold, as with ablations; the research report
reads signal states, tracking and settlements only.

The bases are fixed (``BASES``: ``breakout_v3`` and ``pullback_v4``), not
whatever ``REGISTRY`` holds, and never enter it: only a research backtest
on a copy of the database or an isolated one evaluates these versions
(``tools/research/backtest_research.py --aggressive``), and a run of
aggressive versions replays both bases as its baselines.

The samples are #567's (``index_conditions.EXPLORATION``／``VALIDATION``),
and ``judge_exploration``／``judge_validation`` are the rule a version passes
in each to be proposed; both were fixed before any result was read.
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import registry_problems
from .base import Strategy
from .breakout_v3 import BREAKOUT_V3
from .index_conditions import EXPLORATION, SEGMENTS, VALIDATION, segment_of
from .pullback_v4 import PULLBACK_V4

ISSUE = 598

# The versions #598 measures; see the module docstring.
BASES: dict[str, Strategy] = {
    strategy.key: strategy for strategy in (BREAKOUT_V3, PULLBACK_V4)
}

REMOVE = object()  # a change that deletes the key: the condition is not checked


@dataclass(frozen=True)
class Change:
    path: tuple[str, ...]
    value: Any  # REMOVE, or the new threshold

    def snapshot(self, config: Mapping[str, Any]) -> dict[str, Any]:
        parent: Any = config
        for part in self.path[:-1]:
            parent = parent[part]
        return {
            "key": ".".join(self.path),
            "from": copy.deepcopy(parent[self.path[-1]]),
            "to": "removed" if self.value is REMOVE else self.value,
        }


VOLUME_MIN = Change(("volume", "minimum_signal_to_average_ratio"), 1.00)
INSTITUTIONAL = Change(("confirmations", "institutional_flow"), REMOVE)
MARGIN = Change(("confirmations", "margin_financing"), REMOVE)
GROUP = Change(("confirmations", "group_relative_strength"), REMOVE)
PULLBACK_VOLUME_MAX = Change(("volume", "maximum_signal_to_average_ratio"), 1.50)
SUPPORT_MIN = Change(("support_zone", "minimum_close_to_ma20_ratio"), 0.95)


@dataclass(frozen=True)
class Variant:
    code: str
    label_zh: str
    changes: Mapping[str, tuple[Change, ...]]  # base strategy -> its changes


VARIANTS: dict[str, Variant] = {
    item.code: item
    for item in (
        Variant(
            "a1",
            "A1：突破量能門檻 1.20 倍 → 1.00 倍",
            {"breakout_v3": (VOLUME_MIN,)},
        ),
        Variant(
            "a2",
            "A2：拿掉法人 ≥ −0.003",
            {"breakout_v3": (INSTITUTIONAL,), "pullback_v4": (INSTITUTIONAL,)},
        ),
        Variant(
            "a3",
            "A3：拿掉融資 ≤ 0.05",
            {"breakout_v3": (MARGIN,), "pullback_v4": (MARGIN,)},
        ),
        Variant(
            "a4",
            "A4：拿掉族群 20 日 > 0",
            {"breakout_v3": (GROUP,), "pullback_v4": (GROUP,)},
        ),
        Variant(
            "a5",
            "A5：回踩量能上限 1.20 倍 → 1.50 倍",
            {"pullback_v4": (PULLBACK_VOLUME_MAX,)},
        ),
        Variant(
            "a6",
            "A6：回踩支撐區下緣 0.97 → 0.95",
            {"pullback_v4": (SUPPORT_MIN,)},
        ),
        Variant(
            "a7",
            "A7：組合放寬（突破 A1＋A2＋A3、回踩 A5＋A2＋A3）",
            {
                "breakout_v3": (VOLUME_MIN, INSTITUTIONAL, MARGIN),
                "pullback_v4": (PULLBACK_VOLUME_MAX, INSTITUTIONAL, MARGIN),
            },
        ),
    )
}


def relaxed_config(strategy_key: str, code: str) -> dict[str, Any]:
    """``BASES[strategy_key]``'s configuration with ``code``'s changes, under its own name."""

    base = BASES[strategy_key]
    changes = VARIANTS[code].changes[strategy_key]
    config: dict[str, Any] = copy.deepcopy(dict(base.config))
    snapshots = [change.snapshot(config) for change in changes]
    for change in changes:
        parent = config
        for part in change.path[:-1]:
            parent = parent[part]
        if change.value is REMOVE:
            del parent[change.path[-1]]
        else:
            parent[change.path[-1]] = change.value
    config["name"] = f"{strategy_key}_aggr_{code}"
    config["kind"] = f"{base.kind}_aggr_{code}"
    config["aggressive"] = {
        "base_strategy": strategy_key,
        "base_version": base.version,
        "issue": ISSUE,
        "variant": code,
        "label_zh": VARIANTS[code].label_zh,
        "changes": snapshots,
    }
    return config


def aggressive_strategy(strategy_key: str, code: str) -> Strategy:
    base = BASES[strategy_key]
    config = relaxed_config(strategy_key, code)
    strategy = copy.copy(base)
    strategy.config = config
    strategy.rule = functools.partial(type(base).rule, config=config)
    return strategy


def all_variants() -> list[tuple[str, str]]:
    return [
        (strategy_key, code)
        for strategy_key in BASES
        for code, item in VARIANTS.items()
        if strategy_key in item.changes
    ]


def with_variants(
    registry: Mapping[str, Strategy], items: Iterable[tuple[str, str]]
) -> dict[str, Strategy]:
    """``registry`` followed by the aggressive versions ``items`` names."""

    result = dict(registry)
    problems = []
    for strategy_key, code in items:
        if strategy_key not in VARIANTS[code].changes:
            problems.append(f"{code} does not apply to {strategy_key}")
            continue
        strategy = aggressive_strategy(strategy_key, code)
        if strategy.key in result:
            problems.append(f"{strategy.key} is already in the registry")
        result[strategy.key] = strategy
    problems += registry_problems(result)
    if problems or not result:
        raise ValueError("; ".join(problems) or "empty research registry")
    return result


# ---- the rule a version passes to be proposed (fixed before any result) ----

# A segment counts only when the version added at least MIN_ADDED actionable
# signals (the instrument-days its base did not pass) and at least MIN_ADDED_T20
# of them have a usable T+20 return; otherwise the segment cannot judge it.
MIN_ADDED = 30
MIN_ADDED_T20 = 30
SELECTION_RULE_ZH = (
    "探索段選出：多出來的可行動訊號 ≥ 30 筆、其中 T+20 可用報酬 ≥ 30 筆，"
    "且多出來那組的 T+20 中位數高於 baseline、invalidated 比例低於 baseline。"
    "驗證段沒有反轉：同樣的樣本門檻下，多出來那組的 T+20 中位數不低於 baseline、"
    "invalidated 比例不高於 baseline；門檻不足記「無法判定」，不算沒有反轉。"
    "提案只引用兩段都過的版本。"
)


@dataclass(frozen=True)
class Comparison:
    """One segment: the signals a version added against its baseline."""

    added: int  # actionable signals of the version its base did not pass
    added_t20_n: int  # usable T+20 returns among them
    added_t20_median: float | None
    baseline_t20_median: float | None
    added_invalidated_share: float | None
    baseline_invalidated_share: float | None

    @property
    def judgeable(self) -> bool:
        return (
            self.added >= MIN_ADDED
            and self.added_t20_n >= MIN_ADDED_T20
            and None
            not in (
                self.added_t20_median,
                self.baseline_t20_median,
                self.added_invalidated_share,
                self.baseline_invalidated_share,
            )
        )


def judge_exploration(item: Comparison) -> str:
    """``selected``, ``not_selected`` or ``insufficient``."""

    if not item.judgeable:
        return "insufficient"
    better = (
        item.added_t20_median > item.baseline_t20_median
        and item.added_invalidated_share < item.baseline_invalidated_share
    )
    return "selected" if better else "not_selected"


def judge_validation(item: Comparison) -> str:
    """``not_reversed``, ``reversed`` or ``insufficient``."""

    if not item.judgeable:
        return "insufficient"
    held = (
        item.added_t20_median >= item.baseline_t20_median
        and item.added_invalidated_share <= item.baseline_invalidated_share
    )
    return "not_reversed" if held else "reversed"


def proposable(exploration: Comparison, validation: Comparison) -> bool:
    return (
        judge_exploration(exploration) == "selected"
        and judge_validation(validation) == "not_reversed"
    )


__all__ = [
    "BASES",
    "EXPLORATION",
    "SEGMENTS",
    "VALIDATION",
    "VARIANTS",
    "Comparison",
    "aggressive_strategy",
    "all_variants",
    "judge_exploration",
    "judge_validation",
    "proposable",
    "relaxed_config",
    "segment_of",
    "with_variants",
]
