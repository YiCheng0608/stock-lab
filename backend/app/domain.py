from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any


# These dictionaries intentionally contain JSON primitives only.  They are the
# canonical definitions persisted by StrategyVersion.config_json once the
# worker is wired to the v1 evaluator.
MINIMUM_FIRST_TARGET_RISK_REWARD = 1.5

# Institutional-flow ratio formula identities.  v1 is the original canonical
# formula (net shares / TWD turnover); its numerator and denominator have
# different units, so it is retained here only as a traceable identity and is
# never evaluated.  v2 divides net shares by share volume, which makes the
# ratio dimensionless; the -0.003 ``gte`` threshold carries over unchanged.
INSTITUTIONAL_FLOW_FORMULA_V1 = "institutional-flow/v1-shares-per-twd-turnover"
INSTITUTIONAL_FLOW_FORMULA_V2 = "institutional-flow/v2-shares-per-share-volume"
INSTITUTIONAL_FLOW_FORMULA_VERSION = INSTITUTIONAL_FLOW_FORMULA_V2
INSTITUTIONAL_FLOW_FORMULAS: dict[str, dict[str, Any]] = {
    INSTITUTIONAL_FLOW_FORMULA_V1: {
        "status": "original_canonical_retained",
        "strategy_normalizer": "average_daily_turnover_20d",
        "hot_group_normalizer": "sum_turnover_20d",
        "numerator_unit": "shares",
        "denominator_unit": "twd",
        "dimensionless": False,
    },
    INSTITUTIONAL_FLOW_FORMULA_V2: {
        "status": "current",
        "strategy_normalizer": "average_daily_volume_20d",
        "hot_group_normalizer": "sum_volume_20d",
        "numerator_unit": "shares",
        "denominator_unit": "shares",
        "dimensionless": True,
    },
}

# ``Signal.confidence`` is a legacy compatibility field.  It is nullable and
# the v1 worker's fixed 0.75 was never a calibrated probability.  Keep the
# semantic marker in the existing JSON evidence so a new signal can be
# distinguished from historical rows without changing the canonical strategy
# version or migrating the table.
SIGNAL_CONFIDENCE_SEMANTICS_VERSION = "signal-confidence/v2"
LEGACY_SIGNAL_CONFIDENCE_SEMANTICS_VERSION = "signal-confidence/v1-fixed"
LEGACY_SIGNAL_CONFIDENCE_STRATEGIES = frozenset({"breakout_v1", "pullback_v1"})
LEGACY_SIGNAL_CONFIDENCE_STRATEGY_VERSION = "1.0.0"
SIGNAL_CONFIDENCE_SEMANTICS: dict[str, Any] = {
    "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    "kind": "not_calibrated",
    "is_calibrated": False,
    "is_probability": False,
    "display_label_zh": "未校準；非預測勝率",
}
LEGACY_SIGNAL_CONFIDENCE_SEMANTICS: dict[str, Any] = {
    "version": LEGACY_SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    "kind": "legacy_fixed_value",
    "is_calibrated": False,
    "is_probability": False,
    "display_label_zh": "舊版固定規則值（未經機率校準；非勝率）",
}
UNKNOWN_SIGNAL_CONFIDENCE_SEMANTICS: dict[str, Any] = {
    "version": SIGNAL_CONFIDENCE_SEMANTICS_VERSION,
    "kind": "unknown_numeric",
    "is_calibrated": False,
    "is_probability": False,
    "display_label_zh": "未校準；非預測勝率",
}


def signal_confidence_semantics(
    confidence: object,
    evidence: Mapping[str, object] | None = None,
    *,
    strategy_name: str | None = None,
    strategy_version: str | None = None,
) -> dict[str, Any]:
    """Return an explicit, non-probability interpretation for a signal value.

    Existing rows may have a numeric legacy value but no semantic marker.  A
    legacy fixed value is recognised only when the value, strategy allowlist,
    and canonical strategy version all match.  Marker contents are not
    trusted for public semantics because old evidence may be incomplete or
    malformed.
    """

    if isinstance(evidence, Mapping):
        if strategy_name is None and isinstance(evidence.get("strategy"), str):
            strategy_name = evidence["strategy"]
        if strategy_version is None and isinstance(
            evidence.get("strategy_version"), str
        ):
            strategy_version = evidence["strategy_version"]
    legacy_fixed = (
        isinstance(confidence, Real)
        and not isinstance(confidence, bool)
        and math.isfinite(float(confidence))
        and float(confidence) == 0.75
        and strategy_name in LEGACY_SIGNAL_CONFIDENCE_STRATEGIES
        and strategy_version == LEGACY_SIGNAL_CONFIDENCE_STRATEGY_VERSION
    )
    if legacy_fixed:
        return dict(LEGACY_SIGNAL_CONFIDENCE_SEMANTICS)
    return dict(
        SIGNAL_CONFIDENCE_SEMANTICS
        if confidence is None
        else UNKNOWN_SIGNAL_CONFIDENCE_SEMANTICS
    )


ETF_CATEGORIES = frozenset(
    {
        "broad_market",
        "dividend",
        "sector",
        "thematic",
        "bond",
        "commodity",
        "leveraged",
        "inverse",
    }
)

# All recognised ETF categories remain eligible for collection, classification,
# and the separate hot-group ETF leaderboard.  The three non-equity profiles
# below are intentionally excluded only from the general stock-style signal
# strategies until dedicated strategy versions are approved.
ACTIONABLE_ETF_CATEGORIES = frozenset(
    {
        "broad_market",
        "dividend",
        "sector",
        "thematic",
        "commodity",
    }
)
NON_ACTIONABLE_ETF_CATEGORIES = frozenset({"bond", "leveraged", "inverse"})


GROUP_SCORE_WEIGHTS: dict[str, float] = {
    "relative_return": 0.35,
    "breadth": 0.25,
    "volume_strength": 0.15,
    "institutional_flow": 0.15,
    "catalyst": 0.10,
}


# 1.0.0 required every member (not every eligible member) to have a 5-day
# flow and treated a member absent from the day's official institutional file
# as missing.  1.1.0 changes only that coverage rule (V1_SPEC hot_group_v1);
# score rows it overwrites are archived first (group_daily_score_archive).
HOT_GROUP_LEGACY_VERSION = "1.0.0"
HOT_GROUP_VERSION = "1.1.0"
# Chip-row sources written by the official institutional parsers; a row
# without one of them carries only margin data.
OFFICIAL_INSTITUTIONAL_CHIP_SOURCES: dict[str, str] = {
    "TWSE": "twse_t86",
    "TPEx": "tpex_3insti",
}

HOT_GROUP_CONFIG: dict[str, Any] = {
    "name": "hot_group_v1",
    "version": HOT_GROUP_VERSION,
    "schema_version": "hot-group-config/v1",
    "kind": "group_ranking",
    "score_scale": {"minimum": 0.0, "maximum": 100.0},
    "weights": GROUP_SCORE_WEIGHTS,
    "benchmark": {
        "id": "TAIEX",
        "price_field": "adj_close",
        "return_formula": "adj_close[t] / adj_close[t-window] - 1",
    },
    "windows_trading_days": {"one_day": 1, "five_day": 5, "twenty_day": 20},
    "membership": {
        "minimum_eligible_members": 3,
        "effective_on_score_date": "valid_from_lte_score_date_and_(valid_to_is_null_or_valid_to_gte_score_date)",
        "exclude_members_without_required_history": True,
    },
    "leaderboards": {
        "equity": {
            "instrument_types": ["stock", "ipo"],
            "benchmark_id": "TAIEX",
        },
        "etf": {
            "instrument_types": ["etf"],
            "benchmark_id": "TAIEX",
            "separate_from_equity": True,
            "partition_by": "etf_category",
            "collect_and_classify_all_categories": True,
            "included_categories": sorted(ETF_CATEGORIES),
        },
    },
    "components": {
        "relative_return": {
            "weight": 0.35,
            "value_range": [0.0, 1.0],
            "formula": {
                "operation": "cross_sectional_percentile_of_weighted_sum",
                "member_aggregation": "equal_weight_mean",
                "terms": [
                    {
                        "weight": 0.20,
                        "metric": "group_return_minus_benchmark_return",
                        "window_trading_days": 1,
                    },
                    {
                        "weight": 0.30,
                        "metric": "group_return_minus_benchmark_return",
                        "window_trading_days": 5,
                    },
                    {
                        "weight": 0.50,
                        "metric": "group_return_minus_benchmark_return",
                        "window_trading_days": 20,
                    },
                ],
            },
        },
        "breadth": {
            "weight": 0.25,
            "value_range": [0.0, 1.0],
            "formula": {
                "operation": "weighted_mean",
                "member_aggregation": "share_of_members_with_positive_excess_return",
                "terms": [
                    {"weight": 0.20, "window_trading_days": 1},
                    {"weight": 0.30, "window_trading_days": 5},
                    {"weight": 0.50, "window_trading_days": 20},
                ],
            },
        },
        "volume_strength": {
            "weight": 0.15,
            "value_range": [0.0, 1.0],
            "formula": {
                "operation": "cross_sectional_percentile_of_weighted_sum",
                "member_aggregation": "median",
                "terms": [
                    {
                        "weight": 0.50,
                        "metric": "volume_1d / mean(volume_prior_20d)",
                        "signal_window_trading_days": 1,
                        "baseline_window_trading_days": 20,
                    },
                    {
                        "weight": 0.50,
                        "metric": "mean(volume_5d) / mean(volume_prior_20d)",
                        "signal_window_trading_days": 5,
                        "baseline_window_trading_days": 20,
                    },
                ],
            },
        },
        "institutional_flow": {
            "weight": 0.15,
            "value_range": [0.0, 1.0],
            "formula": {
                "operation": "cross_sectional_percentile",
                "metric": "sum(foreign_buy + trust_buy + dealer_buy, 5d) / sum(volume, 20d)",
                "formula_version": INSTITUTIONAL_FLOW_FORMULA_VERSION,
                "flow_window_trading_days": 5,
                "flow_unit": "shares",
                "denominator_window_trading_days": 20,
                "denominator_window_basis": "inclusive_signal_day",
                "denominator_unit": "shares",
            },
            "coverage": {
                "member_base": "eligible_members",
                "required_ratio": 1.0,
                "member_aggregation": "sum_over_eligible_members",
                # A member with a positive-volume bar that is absent from that
                # day's received official file had no institutional trade.
                "absent_from_official_file": "net_zero_with_evidence",
                "official_file_evidence": (
                    "same_exchange_same_day_chip_row_from_official_institutional_source"
                    "_linked_to_raw_payload_of_that_endpoint_and_date"
                ),
                "official_sources": OFFICIAL_INSTITUTIONAL_CHIP_SOURCES,
                "official_file_missing": "member_flow_unavailable",
                "official_row_with_null_component": "member_flow_unavailable",
                "applies_to": "hot_group_only",
            },
        },
        "catalyst": {
            "weight": 0.10,
            "value_range": [0.0, 1.0],
            "formula": {
                "operation": "weighted_capped_distinct_verified_events",
                "terms": [
                    {"weight": 0.50, "window_trading_days": 1},
                    {"weight": 0.30, "window_trading_days": 5},
                    {"weight": 0.20, "window_trading_days": 20},
                ],
                "normalization": {"cap_distinct_events": 3},
                "accepted_source_types": [
                    "mops_material_information",
                    "twse_tpex_official_announcement",
                    "issuer_filing",
                ],
            },
            "missing_value": None,
            "missing_policy": "component_null_and_data_quality_partial",
        },
    },
    "missing_data": {
        "component_value": None,
        "score_policy": "renormalize_available_component_weights",
        "minimum_available_weight": 0.90,
        "quality_complete_only_if_all_components_present": True,
        "quality_when_catalyst_missing": "partial",
        "do_not_substitute_neutral_catalyst_score": True,
    },
}


_COMMON_UNIVERSE = {
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

_COMMON_EXECUTION = {
    "signal_time": "T_close",
    "earliest_execution": "T+1",
    "execution_price_field": "next_session_open_or_better_documented_fill",
    "no_same_day_fill": True,
}

_COMMON_CONFIRMATIONS = {
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

_COMMON_RISK_MANAGEMENT = {
    "first_target_minimum_risk_reward": MINIMUM_FIRST_TARGET_RISK_REWARD,
    "invalid_price_must_be_below_entry": True,
    "target_1_must_exceed_entry": True,
    "target_2_must_exceed_target_1_when_present": True,
}


STRATEGY_CONFIGS: dict[str, dict[str, Any]] = {
    "breakout_v1": {
        "name": "breakout_v1",
        "version": "1.0.0",
        "schema_version": "strategy-config/v1",
        "kind": "breakout",
        "universe": _COMMON_UNIVERSE,
        "execution": _COMMON_EXECUTION,
        "price": {
            "signal_price_field": "close",
            "reference_price_field": "high",
            "prior_high_lookback_trading_days": 20,
            "reference_excludes_signal_day": True,
            "breakout_operator": "gt",
        },
        "volume": {
            "signal_volume_field": "volume",
            "average_lookback_trading_days": 20,
            "average_excludes_signal_day": True,
            "minimum_signal_to_average_ratio": 1.20,
            "operator": "gte",
        },
        "confirmations": _COMMON_CONFIRMATIONS,
        "risk_management": _COMMON_RISK_MANAGEMENT,
        "data_policy": {
            "required_inputs": [
                "close",
                "prior_20_highs",
                "volume",
                "prior_20_volumes",
                "group_excess_return_20d",
                "institutional_flow_to_turnover_ratio_5d",
                "margin_balance_change_ratio_5d",
            ],
            "on_missing_required_input": "fail_closed_data_incomplete",
        },
    },
    "pullback_v1": {
        "name": "pullback_v1",
        "version": "1.0.0",
        "schema_version": "strategy-config/v1",
        "kind": "pullback",
        "universe": _COMMON_UNIVERSE,
        "execution": _COMMON_EXECUTION,
        "trend": {
            "minimum_history_trading_days": 60,
            "fast_ma_window_trading_days": 20,
            "slow_ma_window_trading_days": 60,
            "ma_alignment": "ma20_gt_ma60",
            "close_must_be_at_or_above": "ma60",
        },
        "support_zone": {
            "reference": "ma20",
            "minimum_close_to_ma20_ratio": 0.97,
            "maximum_close_to_ma20_ratio": 1.02,
            "bounds_inclusive": True,
        },
        "volume": {
            "signal_volume_field": "volume",
            "average_lookback_trading_days": 20,
            "average_excludes_signal_day": True,
            "minimum_signal_to_average_ratio": 0.60,
            "maximum_signal_to_average_ratio": 1.20,
            "bounds_inclusive": True,
        },
        "confirmations": _COMMON_CONFIRMATIONS,
        "risk_management": _COMMON_RISK_MANAGEMENT,
        "data_policy": {
            "required_inputs": [
                "bar_count_60d",
                "close",
                "ma20",
                "ma60",
                "volume",
                "prior_20_volumes",
                "group_excess_return_20d",
                "institutional_flow_to_turnover_ratio_5d",
                "margin_balance_change_ratio_5d",
            ],
            "on_missing_required_input": "fail_closed_data_incomplete",
        },
    },
}


CANONICAL_CONFIGS: dict[str, dict[str, Any]] = {
    **STRATEGY_CONFIGS,
    "hot_group_v1": HOT_GROUP_CONFIG,
}


# Daily candidate ranking (V1_SPEC candidate_score_v1).  The score only orders
# signals the strategies already judged conditional; it never changes a
# strategy decision and is not a win rate or expected return.  Any change to
# this dictionary requires a new version: stored candidates keep the version
# and a snapshot of the configuration they were scored with.  It is kept out
# of CANONICAL_CONFIGS, whose snapshot identifies strategy rows.
CANDIDATE_SCORE_VERSION = "candidate_score_v1"
# Prompt version of the candidate LLM notes (worker.candidate_notes); the
# API shows this version first.
CANDIDATE_NOTE_PROMPT_VERSION = "candidate_notes_v1"
CANDIDATE_SCORE_V1: dict[str, Any] = {
    "name": CANDIDATE_SCORE_VERSION,
    "schema_version": "candidate-score-config/v1",
    "purpose": "ranking_only_not_win_rate_or_expected_return",
    "percentile": "mid_rank_same_day:(less+(equal-1)/2)/(n-1);single_value=0.5",
    "pool": {
        "strategies": ["breakout_v1", "pullback_v1"],
        "signal_namespace": "analysis",
        # Judged actionable (conditional) by analyze on T.  evaluate later
        # moves the status (active, target_1_hit, ...) but never this flag, so
        # recomputing an old date sees the same pool.  Rows without the flag
        # fall back to the statuses only a conditional signal can reach.
        "actionable_on_signal_date": "rule_evidence_json.actionable_is_true",
        "legacy_actionable_statuses": [
            "conditional",
            "active",
            "target_1_hit",
            "target_2_hit",
            "invalidated",
            "incomparable",
        ],
        "instrument_types": ["stock", "ipo"],
        "require_valid_levels": True,
        "one_row_per_instrument": "highest_total_then_breakout",
    },
    "weights": {
        "technical": 0.35,
        "chips": 0.30,
        "group": 0.20,
        "news_sentiment": 0.15,
    },
    "components": {
        "technical": {
            "population": "same_day_same_strategy_pool",
            "items": {
                "volume_ratio": {
                    "weight": 0.5,
                    "formula": "volume[T]/mean(volume[T-20:T-1])",
                    "better": {"breakout_v1": "higher", "pullback_v1": "lower"},
                },
                "distance": {
                    "weight": 0.5,
                    "formula": {
                        "breakout_v1": "close[T]/max(high[T-20:T-1])-1",
                        "pullback_v1": "abs(close[T]/MA20[T]-1)",
                    },
                    "better": "lower",
                },
                # _risk_levels sets every target at 1.6R, so RR has no ranking
                # power today; it is reported but carries no weight.
                "risk_reward": {
                    "weight": 0.0,
                    "formula": "(target_1-entry)/(entry-invalid)",
                    "better": "higher",
                },
            },
        },
        "chips": {
            "population": "same_day_market_stock_and_ipo",
            "items": {
                "institutional_flow_5d": {
                    "weight": 0.4,
                    "formula": "sum(foreign+trust+dealer,5d)/mean(volume,20d)",
                    "better": "higher",
                },
                "institutional_flow_20d": {
                    "weight": 0.3,
                    "formula": "sum(foreign+trust+dealer,20d)/mean(volume,20d)",
                    "better": "higher",
                },
                "margin_change_5d": {
                    "weight": 0.3,
                    "formula": "(margin_balance[T]-margin_balance[T-5])/abs(margin_balance[T-5])",
                    "better": "lower",
                },
            },
        },
        "news_sentiment": {
            "population": "same_day_market_stock_and_ipo",
            "inference": True,
            "window_calendar_days": 3,
            "llm_prompt_version": "news_v1",
            "direction_values": {"positive": 1, "negative": -1, "mixed": 0},
            "ignored_directions": ["unknown"],
            "no_linked_news": "valid_zero_when_news_collection_succeeded_in_window",
            "better": "higher",
        },
        "group": {
            "population": "board_percentile_not_cross_stock",
            "boards": ["industry", "theme"],
            "formula": "max(1-(rank-1)/(ranked_groups_on_board-1));single_group=0.5",
            "qualification": "complete_quality_eligible_members_gte_3_ranked_on_T",
        },
    },
    "minimum_weight_coverage": 0.65,
    "required_components": ["technical"],
    "list_size": {"maximum": 20, "minimum_target": 10},
    "max_reasons": 4,
    "tie_break": [
        "total_desc",
        "technical_desc",
        "chips_desc",
        "exchange_asc",
        "symbol_asc",
    ],
}


def weighted_available_mean(
    values: Mapping[str, float | None],
    weights: Mapping[str, float],
) -> tuple[float | None, float]:
    """Weighted mean over the finite values only, and the weight they cover.

    Missing inputs are neither zero nor imputed: the remaining weights are
    renormalized and the covered weight is returned so callers can apply a
    floor.  Zero-weight items never contribute.
    """

    usable = {
        key: float(values[key])
        for key in weights
        if weights[key] > 0 and _finite(values.get(key))
    }
    coverage = sum(weights[key] for key in usable)
    if coverage <= 0:
        return None, 0.0
    return sum(usable[key] * weights[key] for key in usable) / coverage, coverage


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleEvaluation:
    """Outcome of a fail-closed pure strategy-rule evaluation."""

    passed: bool
    state: str
    reasons: tuple[str, ...] = ()


SIGNAL_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "observation": frozenset(
        {"conditional", "data_incomplete", "invalid_levels", "expired"}
    ),
    "conditional": frozenset(
        {"active", "data_incomplete", "invalid_levels", "expired"}
    ),
    "active": frozenset(
        {"target_1_hit", "target_2_hit", "invalidated", "expired", "incomparable"}
    ),
    "target_1_hit": frozenset(
        {"target_2_hit", "invalidated", "expired", "incomparable"}
    ),
    "target_2_hit": frozenset({"settled"}),
    "invalidated": frozenset({"settled"}),
    "expired": frozenset({"settled"}),
    "incomparable": frozenset({"settled"}),
    "data_incomplete": frozenset({"observation", "expired"}),
    "invalid_levels": frozenset({"observation", "expired"}),
    "settled": frozenset(),
}

VALID_ENTRY_TYPES = frozenset({"breakout", "pullback"})
VALID_INSTRUMENT_TYPES = frozenset({"stock", "etf", "ipo"})


def _finite(value: object) -> bool:
    """Return whether *value* is a real, non-boolean, finite number."""

    if type(value) is float:  # same answer, without the slower ABC check
        return math.isfinite(value)
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _positive(value: object) -> bool:
    return _finite(value) and float(value) > 0.0


def _trailing_positive_history(
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


def _required_finite(
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


def canonical_config_snapshot() -> dict[str, dict[str, Any]]:
    """Return a JSON round-tripped copy suitable for database persistence."""

    return json.loads(json.dumps(CANONICAL_CONFIGS, sort_keys=True))


def validate_signal_levels(
    *,
    entry_type: str,
    reference_entry: float | None,
    breakout_price: float | None,
    invalid_price: float | None,
    target_1: float | None,
    target_2: float | None,
    minimum_first_target_risk_reward: float = MINIMUM_FIRST_TARGET_RISK_REWARD,
) -> ValidationResult:
    """Validate price levels before a signal can enter the lifecycle.

    ``breakout`` uses ``breakout_price`` as the entry basis; ``pullback`` uses
    ``reference_entry``.  The first target must reward at least 1.5 units for
    every unit between entry and invalidation unless a versioned configuration
    supplies another positive finite threshold.
    """

    errors: list[str] = []
    if entry_type not in VALID_ENTRY_TYPES:
        errors.append("unsupported_entry_type")
        entry: float | None = None
    else:
        raw_entry = breakout_price if entry_type == "breakout" else reference_entry
        entry = float(raw_entry) if _positive(raw_entry) else None
        if entry is None:
            errors.append("entry_price_must_be_finite_and_positive")

    invalid = float(invalid_price) if _positive(invalid_price) else None
    if invalid is None:
        errors.append("invalid_price_must_be_finite_and_positive")
    elif entry is not None and invalid >= entry:
        errors.append("invalid_price_must_be_below_entry")

    first_target = float(target_1) if _positive(target_1) else None
    if first_target is None:
        errors.append("target_1_must_be_finite_and_positive")
    elif entry is not None and first_target <= entry:
        errors.append("target_1_must_exceed_entry")

    if target_2 is not None:
        second_target = float(target_2) if _positive(target_2) else None
        if second_target is None:
            errors.append("target_2_must_be_finite_and_positive_when_present")
        elif first_target is not None and second_target <= first_target:
            errors.append("target_2_must_exceed_target_1")

    if (
        not _finite(minimum_first_target_risk_reward)
        or float(minimum_first_target_risk_reward) <= 0
    ):
        errors.append("minimum_first_target_risk_reward_must_be_finite_and_positive")
    elif (
        entry is not None
        and invalid is not None
        and first_target is not None
        and invalid < entry < first_target
    ):
        risk_reward = (first_target - entry) / (entry - invalid)
        if risk_reward < float(minimum_first_target_risk_reward):
            errors.append("target_1_risk_reward_below_minimum")

    return ValidationResult(valid=not errors, errors=tuple(errors))


def validate_signal_status_transition(
    current_status: str, next_status: str
) -> ValidationResult:
    """Accept only declared, forward signal-lifecycle transitions.

    Idempotent transitions are accepted so a retry can safely persist a state
    already written by an earlier worker run.
    """

    if current_status not in SIGNAL_STATUS_TRANSITIONS:
        return ValidationResult(False, ("unsupported_current_status",))
    if next_status not in SIGNAL_STATUS_TRANSITIONS:
        return ValidationResult(False, ("unsupported_next_status",))
    if (
        current_status == next_status
        or next_status in SIGNAL_STATUS_TRANSITIONS[current_status]
    ):
        return ValidationResult(True)
    return ValidationResult(False, ("illegal_signal_status_transition",))


def clamp01(value: float | None, default: float | None = None) -> float | None:
    if not _finite(value):
        return default
    return max(0.0, min(1.0, float(value)))


def group_score_quality(values: Mapping[str, float | None]) -> str:
    """Classify a group score without pretending a missing catalyst is neutral."""

    available_weight = sum(
        GROUP_SCORE_WEIGHTS[key]
        for key in GROUP_SCORE_WEIGHTS
        if _finite(values.get(key))
    )
    minimum_available_weight = float(
        HOT_GROUP_CONFIG["missing_data"]["minimum_available_weight"]
    )
    if available_weight + 1e-12 < minimum_available_weight:
        return "insufficient_data"
    if available_weight < 1.0 - 1e-12:
        return "partial"
    return "complete"


def calculate_group_score(values: Mapping[str, float | None]) -> float | None:
    """Calculate a 0–100 hot-group score using only available, finite inputs.

    Scores with a missing catalyst are allowed at 90% available weight and are
    marked ``partial`` by :func:`group_score_quality`; no neutral catalyst is
    injected.  Below the configured available-weight floor, no score is
    returned.
    """

    usable = {
        key: clamp01(values.get(key))
        for key in GROUP_SCORE_WEIGHTS
        if _finite(values.get(key))
    }
    if group_score_quality(values) == "insufficient_data":
        return None
    weight_total = sum(GROUP_SCORE_WEIGHTS[key] for key in usable)
    return round(
        sum(usable[key] * GROUP_SCORE_WEIGHTS[key] for key in usable)
        / weight_total
        * 100,
        2,
    )


def instrument_eligibility(
    instrument_type: str,
    bar_count: int,
    etf_category: str | None = None,
) -> tuple[bool, str | None]:
    """Validate classification, ETF policy, and IPO 20/60-day guardrails.

    Every recognised ETF remains collectable and rankable in ``hot_group_v1``.
    ``bond``, ``leveraged``, and ``inverse`` are only excluded from actionable
    ``breakout_v1``/``pullback_v1`` signals.
    """

    if instrument_type not in VALID_INSTRUMENT_TYPES:
        return False, "unsupported_instrument_type"
    if not isinstance(bar_count, int) or isinstance(bar_count, bool) or bar_count < 0:
        return False, "bar_count_must_be_a_non_negative_integer"
    if instrument_type == "etf":
        if etf_category not in ETF_CATEGORIES:
            return False, "unsupported_or_missing_etf_category"
        if etf_category in NON_ACTIONABLE_ETF_CATEGORIES:
            return (
                False,
                f"etf_category_excluded_from_actionable_signals:{etf_category}",
            )
    if instrument_type != "etf" and etf_category is not None:
        return False, "etf_category_is_only_valid_for_etf"
    if instrument_type == "ipo":
        if bar_count < 20:
            return False, "ipo_history_under_20_bars"
        if bar_count < 60:
            return False, "ipo_observation_only_under_60_bars"
    return True, None


def evaluate_breakout_v1(
    *,
    close: float | None,
    prior_highs: Iterable[float] | None,
    volume: float | None,
    prior_volumes: Iterable[float] | None,
    group_excess_return_20d: float | None,
    institutional_flow_to_turnover_ratio_5d: float | None,
    margin_balance_change_ratio_5d: float | None,
) -> RuleEvaluation:
    """Evaluate ``breakout_v1`` using only the prior 20 trading sessions.

    Any missing, non-finite, or inadequate required input returns
    ``data_incomplete`` rather than an actionable pass.
    """

    highs, high_errors = _trailing_positive_history(
        prior_highs, window=20, reason="prior_20_highs_missing_or_invalid"
    )
    volumes, volume_errors = _trailing_positive_history(
        prior_volumes, window=20, reason="prior_20_volumes_missing_or_invalid"
    )
    metrics, metric_errors = _required_finite(
        {
            "close": close,
            "volume": volume,
            "group_excess_return_20d": group_excess_return_20d,
            "institutional_flow_to_turnover_ratio_5d": institutional_flow_to_turnover_ratio_5d,
            "margin_balance_change_ratio_5d": margin_balance_change_ratio_5d,
        }
    )
    missing = high_errors + volume_errors + metric_errors
    if missing:
        return RuleEvaluation(False, "data_incomplete", missing)
    if metrics["close"] <= 0 or metrics["volume"] <= 0:
        return RuleEvaluation(
            False, "data_incomplete", ("close_or_volume_must_be_positive",)
        )

    config = STRATEGY_CONFIGS["breakout_v1"]
    failures: list[str] = []
    if metrics["close"] <= max(highs):
        failures.append("close_not_above_prior_20_day_high")
    volume_ratio = metrics["volume"] / (sum(volumes) / len(volumes))
    if volume_ratio < config["volume"]["minimum_signal_to_average_ratio"]:
        failures.append("volume_ratio_below_1_20")
    if (
        metrics["group_excess_return_20d"]
        <= config["confirmations"]["group_relative_strength"]["minimum_excess_return"]
    ):
        failures.append("group_relative_strength_not_positive")
    if (
        metrics["institutional_flow_to_turnover_ratio_5d"]
        < config["confirmations"]["institutional_flow"][
            "minimum_net_flow_to_turnover_ratio"
        ]
    ):
        failures.append("institutional_flow_materially_adverse")
    if (
        metrics["margin_balance_change_ratio_5d"]
        > config["confirmations"]["margin_financing"]["maximum_balance_change_ratio"]
    ):
        failures.append("margin_financing_increase_abnormal")
    if failures:
        return RuleEvaluation(False, "rejected", tuple(failures))
    return RuleEvaluation(True, "passed")


def evaluate_pullback_v1(
    *,
    bar_count: int | None,
    close: float | None,
    ma20: float | None,
    ma60: float | None,
    volume: float | None,
    prior_volumes: Iterable[float] | None,
    group_excess_return_20d: float | None,
    institutional_flow_to_turnover_ratio_5d: float | None,
    margin_balance_change_ratio_5d: float | None,
) -> RuleEvaluation:
    """Evaluate ``pullback_v1`` with explicit trend, support, and data guards."""

    config = STRATEGY_CONFIGS["pullback_v1"]
    if not isinstance(bar_count, int) or isinstance(bar_count, bool):
        return RuleEvaluation(
            False, "data_incomplete", ("bar_count_missing_or_invalid",)
        )
    if bar_count < config["trend"]["minimum_history_trading_days"]:
        return RuleEvaluation(False, "data_incomplete", ("history_under_60_bars",))

    volumes, volume_errors = _trailing_positive_history(
        prior_volumes, window=20, reason="prior_20_volumes_missing_or_invalid"
    )
    metrics, metric_errors = _required_finite(
        {
            "close": close,
            "ma20": ma20,
            "ma60": ma60,
            "volume": volume,
            "group_excess_return_20d": group_excess_return_20d,
            "institutional_flow_to_turnover_ratio_5d": institutional_flow_to_turnover_ratio_5d,
            "margin_balance_change_ratio_5d": margin_balance_change_ratio_5d,
        }
    )
    missing = volume_errors + metric_errors
    if missing:
        return RuleEvaluation(False, "data_incomplete", missing)
    if any(metrics[key] <= 0 for key in ("close", "ma20", "ma60", "volume")):
        return RuleEvaluation(
            False, "data_incomplete", ("price_and_volume_inputs_must_be_positive",)
        )

    failures: list[str] = []
    if metrics["ma20"] <= metrics["ma60"]:
        failures.append("ma20_not_above_ma60")
    if metrics["close"] < metrics["ma60"]:
        failures.append("close_below_ma60")
    close_to_ma20 = metrics["close"] / metrics["ma20"]
    support_zone = config["support_zone"]
    if (
        not support_zone["minimum_close_to_ma20_ratio"]
        <= close_to_ma20
        <= support_zone["maximum_close_to_ma20_ratio"]
    ):
        failures.append("close_outside_ma20_support_zone")
    volume_ratio = metrics["volume"] / (sum(volumes) / len(volumes))
    volume_config = config["volume"]
    if (
        not volume_config["minimum_signal_to_average_ratio"]
        <= volume_ratio
        <= volume_config["maximum_signal_to_average_ratio"]
    ):
        failures.append("pullback_volume_ratio_outside_range")
    if (
        metrics["group_excess_return_20d"]
        <= config["confirmations"]["group_relative_strength"]["minimum_excess_return"]
    ):
        failures.append("group_relative_strength_not_positive")
    if (
        metrics["institutional_flow_to_turnover_ratio_5d"]
        < config["confirmations"]["institutional_flow"][
            "minimum_net_flow_to_turnover_ratio"
        ]
    ):
        failures.append("institutional_flow_materially_adverse")
    if (
        metrics["margin_balance_change_ratio_5d"]
        > config["confirmations"]["margin_financing"]["maximum_balance_change_ratio"]
    ):
        failures.append("margin_financing_increase_abnormal")
    if failures:
        return RuleEvaluation(False, "rejected", tuple(failures))
    return RuleEvaluation(True, "passed")


def moving_average(values: Iterable[float], window: int) -> float | None:
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        return None
    data = list(values)
    if len(data) < window or not all(_finite(value) for value in data[-window:]):
        return None
    return sum(float(value) for value in data[-window:]) / window
