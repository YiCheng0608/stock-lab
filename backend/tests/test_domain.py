import json
import math

from app.domain import (
    CANONICAL_CONFIGS,
    HOT_GROUP_CONFIG,
    STRATEGY_CONFIGS,
    calculate_group_score,
    canonical_config_snapshot,
    evaluate_breakout_v1,
    evaluate_pullback_v1,
    group_score_quality,
    instrument_eligibility,
    validate_signal_levels,
    validate_signal_status_transition,
)


def test_canonical_v1_configs_are_json_serializable_and_numeric():
    encoded = json.dumps(CANONICAL_CONFIGS, sort_keys=True)
    assert json.loads(encoded) == canonical_config_snapshot()
    assert "rules" not in STRATEGY_CONFIGS["breakout_v1"]
    assert STRATEGY_CONFIGS["breakout_v1"]["version"] == "1.0.0"
    assert STRATEGY_CONFIGS["breakout_v1"]["price"]["prior_high_lookback_trading_days"] == 20
    assert STRATEGY_CONFIGS["breakout_v1"]["price"]["reference_excludes_signal_day"] is True
    assert STRATEGY_CONFIGS["breakout_v1"]["volume"]["minimum_signal_to_average_ratio"] == 1.2
    etf_policy = STRATEGY_CONFIGS["breakout_v1"]["universe"]["etf_policy"]
    assert "commodity" in etf_policy["actionable_signal_categories"]
    assert etf_policy["excluded_from_general_breakout_pullback"] == {
        "bond": "non_actionable_etf_category",
        "leveraged": "non_actionable_etf_category",
        "inverse": "non_actionable_etf_category",
    }
    assert HOT_GROUP_CONFIG["leaderboards"]["etf"]["collect_and_classify_all_categories"] is True
    assert HOT_GROUP_CONFIG["weights"] == {
        "relative_return": 0.35,
        "breadth": 0.25,
        "volume_strength": 0.15,
        "institutional_flow": 0.15,
        "catalyst": 0.10,
    }


def test_breakout_v1_uses_prior_twenty_day_high_and_1_2_volume_ratio():
    result = evaluate_breakout_v1(
        close=101,
        prior_highs=[100] * 20,
        volume=120,
        prior_volumes=[100] * 20,
        group_excess_return_20d=0.001,
        institutional_flow_to_turnover_ratio_5d=-0.003,
        margin_balance_change_ratio_5d=0.05,
    )
    assert result.passed is True
    assert result.state == "passed"


def test_breakout_v1_fails_closed_for_missing_confirmation_data():
    result = evaluate_breakout_v1(
        close=101,
        prior_highs=[100] * 20,
        volume=120,
        prior_volumes=[100] * 20,
        group_excess_return_20d=None,
        institutional_flow_to_turnover_ratio_5d=0,
        margin_balance_change_ratio_5d=0,
    )
    assert result.passed is False
    assert result.state == "data_incomplete"
    assert "group_excess_return_20d_missing_or_non_finite" in result.reasons


def test_breakout_v1_rejects_non_breakout_and_low_volume():
    result = evaluate_breakout_v1(
        close=100,
        prior_highs=[100] * 20,
        volume=119,
        prior_volumes=[100] * 20,
        group_excess_return_20d=0.01,
        institutional_flow_to_turnover_ratio_5d=0,
        margin_balance_change_ratio_5d=0,
    )
    assert result.state == "rejected"
    assert "close_not_above_prior_20_day_high" in result.reasons
    assert "volume_ratio_below_1_20" in result.reasons


def test_pullback_v1_requires_trend_support_volume_and_complete_data():
    passed = evaluate_pullback_v1(
        bar_count=60,
        close=100,
        ma20=100,
        ma60=95,
        volume=100,
        prior_volumes=[100] * 20,
        group_excess_return_20d=0.01,
        institutional_flow_to_turnover_ratio_5d=0,
        margin_balance_change_ratio_5d=0.01,
    )
    assert passed.passed is True

    incomplete = evaluate_pullback_v1(
        bar_count=60,
        close=100,
        ma20=100,
        ma60=95,
        volume=100,
        prior_volumes=None,
        group_excess_return_20d=0.01,
        institutional_flow_to_turnover_ratio_5d=0,
        margin_balance_change_ratio_5d=0.01,
    )
    assert incomplete.state == "data_incomplete"

    rejected = evaluate_pullback_v1(
        bar_count=60,
        close=105,
        ma20=100,
        ma60=101,
        volume=150,
        prior_volumes=[100] * 20,
        group_excess_return_20d=0,
        institutional_flow_to_turnover_ratio_5d=-0.004,
        margin_balance_change_ratio_5d=0.06,
    )
    assert rejected.state == "rejected"
    assert "close_outside_ma20_support_zone" in rejected.reasons
    assert "pullback_volume_ratio_outside_range" in rejected.reasons
    assert "group_relative_strength_not_positive" in rejected.reasons


def test_signal_levels_require_legal_entry_type_and_first_target_risk_reward():
    invalid_entry_type = validate_signal_levels(
        entry_type="market",
        reference_entry=100,
        breakout_price=100,
        invalid_price=95,
        target_1=108,
        target_2=None,
    )
    assert invalid_entry_type.valid is False
    assert "unsupported_entry_type" in invalid_entry_type.errors

    weak_risk_reward = validate_signal_levels(
        entry_type="breakout",
        reference_entry=None,
        breakout_price=100,
        invalid_price=95,
        target_1=107,
        target_2=None,
    )
    assert weak_risk_reward.valid is False
    assert "target_1_risk_reward_below_minimum" in weak_risk_reward.errors

    valid = validate_signal_levels(
        entry_type="pullback",
        reference_entry=100,
        breakout_price=None,
        invalid_price=95,
        target_1=107.5,
        target_2=115,
    )
    assert valid.valid is True


def test_signal_levels_reject_infinity_and_non_finite_second_target():
    result = validate_signal_levels(
        entry_type="breakout",
        reference_entry=None,
        breakout_price=math.inf,
        invalid_price=95,
        target_1=110,
        target_2=math.inf,
    )
    assert result.valid is False
    assert "entry_price_must_be_finite_and_positive" in result.errors
    assert "target_2_must_be_finite_and_positive_when_present" in result.errors


def test_etf_categories_and_ipo_20_60_day_boundaries():
    for category in ("broad_market", "dividend", "sector", "thematic", "commodity"):
        assert instrument_eligibility("etf", 0, category) == (True, None)
    for category in ("bond", "leveraged", "inverse"):
        assert instrument_eligibility("etf", 0, category) == (
            False,
            f"etf_category_excluded_from_actionable_signals:{category}",
        )
    assert instrument_eligibility("etf", 0, None) == (
        False,
        "unsupported_or_missing_etf_category",
    )
    assert instrument_eligibility("stock", 60, "dividend") == (
        False,
        "etf_category_is_only_valid_for_etf",
    )
    assert instrument_eligibility("ipo", 19) == (False, "ipo_history_under_20_bars")
    assert instrument_eligibility("ipo", 20) == (False, "ipo_observation_only_under_60_bars")
    assert instrument_eligibility("ipo", 59) == (False, "ipo_observation_only_under_60_bars")
    assert instrument_eligibility("ipo", 60) == (True, None)


def test_signal_status_lifecycle_allows_only_declared_forward_transitions():
    assert validate_signal_status_transition("conditional", "active").valid is True
    assert validate_signal_status_transition("target_2_hit", "settled").valid is True
    assert validate_signal_status_transition("active", "conditional").errors == (
        "illegal_signal_status_transition",
    )
    assert validate_signal_status_transition("unknown", "conditional").errors == (
        "unsupported_current_status",
    )


def test_group_score_missing_catalyst_is_partial_not_neutral_or_complete():
    values = {
        "relative_return": 1.0,
        "breadth": 1.0,
        "volume_strength": 0.0,
        "institutional_flow": 0.0,
        "catalyst": None,
    }
    assert group_score_quality(values) == "partial"
    assert calculate_group_score(values) == round((0.35 + 0.25) / 0.9 * 100, 2)

    values["institutional_flow"] = math.inf
    assert group_score_quality(values) == "insufficient_data"
    assert calculate_group_score(values) is None
