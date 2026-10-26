"""``pullback_v1``: an uptrend's close back in the MA20 support zone."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.domain import RuleEvaluation

from .base import (
    COMMON_CONFIRMATIONS,
    COMMON_EXECUTION,
    COMMON_RISK_MANAGEMENT,
    COMMON_UNIVERSE,
    SignalLevels,
    Strategy,
    StrategyInputs,
    finite_number,
    required_finite,
    risk_levels,
    trailing_positive_history,
)

CONFIG: dict[str, Any] = {
    "name": "pullback_v1",
    "version": "1.0.0",
    "schema_version": "strategy-config/v1",
    "kind": "pullback",
    "universe": COMMON_UNIVERSE,
    "execution": COMMON_EXECUTION,
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
    "confirmations": COMMON_CONFIRMATIONS,
    "risk_management": COMMON_RISK_MANAGEMENT,
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
}


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

    config = CONFIG
    if not isinstance(bar_count, int) or isinstance(bar_count, bool):
        return RuleEvaluation(
            False, "data_incomplete", ("bar_count_missing_or_invalid",)
        )
    if bar_count < config["trend"]["minimum_history_trading_days"]:
        return RuleEvaluation(False, "data_incomplete", ("history_under_60_bars",))

    volumes, volume_errors = trailing_positive_history(
        prior_volumes, window=20, reason="prior_20_volumes_missing_or_invalid"
    )
    metrics, metric_errors = required_finite(
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


class PullbackV1(Strategy):
    config = CONFIG
    rule = staticmethod(evaluate_pullback_v1)
    entry_type = "pullback"
    label_zh = "回踩條件"
    research_label_zh = "回踩研究條件"
    requires_zh = (
        "60 日有效行情日數",
        "MA20",
        "MA60",
        "20 日前期成交量",
        "族群相對 TAIEX 的 20 日超額報酬",
        "5 日法人流向",
        "5 日融資餘額變化率",
    )
    candidate_reason = "pullback_ma20_support"

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        return dict(
            bar_count=inputs.bar_count,
            close=inputs.close,
            ma20=inputs.ma20,
            ma60=inputs.ma60,
            volume=inputs.volume,
            prior_volumes=inputs.prior_volumes,
            group_excess_return_20d=inputs.group_excess_return_20d,
            institutional_flow_to_turnover_ratio_5d=inputs.institutional_flow_ratio_5d,
            margin_balance_change_ratio_5d=inputs.margin_change_ratio_5d,
        )

    def actionable_levels(self, inputs: StrategyInputs) -> SignalLevels:
        close = inputs.close
        atr = inputs.atr14
        entry = round(close, 2)
        support = inputs.ma20 or close
        zone_width = max((atr or close * 0.01) * 0.5, close * 0.005)
        reference_entry, invalid_price, target_1, target_2 = risk_levels(entry, atr)
        return SignalLevels(
            reference_entry=reference_entry,
            pullback_low=round(max(0.01, support - zone_width), 2),
            pullback_high=round(support + zone_width, 2),
            invalid_price=invalid_price,
            target_1=target_1,
            target_2=target_2,
        )

    def candidate_distance(
        self, close: float, evidence_inputs: Mapping[str, Any]
    ) -> float | None:
        ma20 = finite_number(evidence_inputs.get("ma20"))
        if ma20 is not None and ma20 > 0:
            return abs(close / ma20 - 1)
        return None


PULLBACK_V1 = PullbackV1()
