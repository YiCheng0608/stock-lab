"""Strategy framework (V1_SPEC 策略版本識別): inputs, interface, shared levels.

Pure calculation: nothing here reads or writes the database.  The worker
builds one :class:`StrategyInputs` per instrument and session and hands it to
every registered strategy; the API, the decision summary and the candidate
list read labels and level-field mappings from the registry instead of naming
strategies.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain import (
    ACTIONABLE_ETF_CATEGORIES,
    ENTRY_LEVEL_FIELDS,
    ENTRY_REQUIRED_LEVELS,
    ETF_CATEGORIES,
    INSTITUTIONAL_FLOW_FORMULA_VERSION,
    MINIMUM_FIRST_TARGET_RISK_REWARD,
    RuleEvaluation,
    _finite,
    _positive,
)

# Building blocks shared by the canonical strategy configurations.  Their
# JSON is part of every strategy's canonical snapshot (StrategyVersion), so a
# change here is a change of every strategy and needs new versions.
COMMON_UNIVERSE = {
    "instrument_types": ["stock", "etf", "ipo"],
    "etf_categories": sorted(ETF_CATEGORIES),
    "etf_policy": {
        "collect_and_classify_categories": sorted(ETF_CATEGORIES),
        "hot_group_rank_categories": sorted(ETF_CATEGORIES),
        "actionable_signal_categories": sorted(ACTIONABLE_ETF_CATEGORIES),
        "excluded_from_general_breakout_pullback": {
            "bond": "non_actionable_etf_category",
            "leveraged": "non_actionable_etf_category",
            "inverse": "non_actionable_etf_category",
        },
    },
    "ipo_observation_minimum_bars": 20,
    "ipo_actionable_minimum_bars": 60,
}

COMMON_EXECUTION = {
    "signal_time": "T_close",
    "earliest_execution": "T+1",
    "execution_price_field": "next_session_open_or_better_documented_fill",
    "no_same_day_fill": True,
}

COMMON_CONFIRMATIONS = {
    "group_relative_strength": {
        "benchmark_id": "TAIEX",
        "return_window_trading_days": 20,
        "minimum_excess_return": 0.0,
        "operator": "gt",
    },
    "institutional_flow": {
        "formula_version": INSTITUTIONAL_FLOW_FORMULA_VERSION,
        "flow_window_trading_days": 5,
        "flow_unit": "shares",
        "normalizer": "average_daily_volume_20d",
        "normalizer_window_trading_days": 20,
        "normalizer_window_basis": "inclusive_signal_day",
        "normalizer_unit": "shares",
        # The key name predates the v2 formula and is kept for stored-contract
        # compatibility; the ratio is now net shares / average share volume.
        "minimum_net_flow_to_turnover_ratio": -0.003,
        "operator": "gte",
    },
    "margin_financing": {
        "change_window_trading_days": 5,
        "maximum_balance_change_ratio": 0.05,
        "operator": "lte",
    },
}

COMMON_RISK_MANAGEMENT = {
    "first_target_minimum_risk_reward": MINIMUM_FIRST_TARGET_RISK_REWARD,
    "invalid_price_must_be_below_entry": True,
    "target_1_must_exceed_entry": True,
    "target_2_must_exceed_target_1_when_present": True,
}

# Identity of the level arithmetic in :func:`risk_levels` (level_semantics).
LEGACY_RISK_LEVELS_FORMULA = "legacy-risk-levels/v1"


@dataclass(frozen=True)
class StrategyInputs:
    """Everything a strategy may read for one instrument on one session.

    Built once per instrument and session and shared by all strategies.
    Prices are in the session's raw basis (as technical_features); the prior
    windows are the up-to-20 sessions before it, exactly as stored in
    ``rule_evidence_json.inputs``.
    """

    bar_count: int
    close: float | None
    volume: float | None
    ma20: float | None
    ma60: float | None
    atr14: float | None
    prior_highs: list[float] | None
    prior_volumes: list[int] | None
    group_excess_return_20d: float | int | None
    institutional_flow_ratio_5d: float | None
    margin_change_ratio_5d: float | None


@dataclass(frozen=True)
class SignalLevels:
    """Price levels written to a ``signals`` row (null when not used)."""

    reference_entry: float | None = None
    breakout_price: float | None = None
    pullback_low: float | None = None
    pullback_high: float | None = None
    invalid_price: float | None = None
    target_1: float | None = None
    target_2: float | None = None


def risk_levels(entry: float, atr: float | None) -> tuple[float, float, float, float]:
    """Entry, invalidation and the 1.6R/3R targets (``legacy-risk-levels/v1``)."""

    risk = max((atr or entry * 0.02) * 1.0, entry * 0.01)
    invalid = max(0.01, entry - risk)
    target_1 = entry + risk * 1.6
    target_2 = entry + risk * 3.0
    return round(entry, 2), round(invalid, 2), round(target_1, 2), round(target_2, 2)


def finite_number(value: Any) -> float | None:
    """A finite float, or None for missing, boolean and non-numeric values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def trailing_positive_history(
    values: Iterable[float] | None,
    *,
    window: int,
    reason: str,
) -> tuple[list[float] | None, tuple[str, ...]]:
    if values is None:
        return None, (reason,)
    try:
        data = list(values)
    except TypeError:
        return None, (reason,)
    if len(data) < window:
        return None, (reason,)
    trailing = data[-window:]
    if not all(_positive(value) for value in trailing):
        return None, (reason,)
    return [float(value) for value in trailing], ()


def required_finite(
    values: Mapping[str, object],
) -> tuple[dict[str, float], tuple[str, ...]]:
    parsed: dict[str, float] = {}
    errors: list[str] = []
    for key, value in values.items():
        if not _finite(value):
            errors.append(f"{key}_missing_or_non_finite")
        else:
            parsed[key] = float(value)
    return parsed, tuple(errors)


class Strategy:
    """One rule strategy.  To add one, subclass this and add it to REGISTRY.

    ``config`` is the canonical configuration persisted as the strategy's
    StrategyVersion snapshot; ``name``, ``version`` and ``kind`` come from
    it.  ``kind`` keys the strategy's state in every signal's rationale and
    ``rule_evidence_json``.  ``entry_type`` picks the level columns
    (ENTRY_LEVEL_FIELDS).  ``rule`` is the pure evaluator and ``arguments``
    the keyword arguments it takes for one StrategyInputs.
    """

    config: Mapping[str, Any]
    rule: Callable[..., RuleEvaluation]
    entry_type: str
    label_zh: str
    research_label_zh: str
    requires_zh: tuple[str, ...]
    level_formula_version: str = LEGACY_RISK_LEVELS_FORMULA
    # REASON_TEMPLATES code (worker.candidates) for the technical reason.
    candidate_reason: str | None = None

    @property
    def key(self) -> str:
        return self.config["name"]

    @property
    def version(self) -> str:
        return self.config["version"]

    @property
    def kind(self) -> str:
        return self.config["kind"]

    @property
    def level_fields(self) -> dict[str, str]:
        return ENTRY_LEVEL_FIELDS[self.entry_type]

    @property
    def required_levels(self) -> tuple[str, ...]:
        return ENTRY_REQUIRED_LEVELS[self.entry_type]

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        raise NotImplementedError

    def evaluate(self, inputs: StrategyInputs) -> RuleEvaluation:
        return self.rule(**self.arguments(inputs))

    def actionable_levels(self, inputs: StrategyInputs) -> SignalLevels:
        """Levels of a passed evaluation; ``inputs.close`` is not None."""

        raise NotImplementedError

    def candidate_distance(
        self, close: float, evidence_inputs: Mapping[str, Any]
    ) -> float | None:
        """candidate_score technical ``distance`` from a stored signal."""

        return None
