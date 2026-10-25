"""``breakout_v1``: close above the prior 20-session high on 1.2x volume."""

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
    "name": "breakout_v1",
    "version": "1.0.0",
    "schema_version": "strategy-config/v1",
    "kind": "breakout",
    "universe": COMMON_UNIVERSE,
    "execution": COMMON_EXECUTION,
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
    "confirmations": COMMON_CONFIRMATIONS,
    "risk_management": COMMON_RISK_MANAGEMENT,
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
}


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

    highs, high_errors = trailing_positive_history(
        prior_highs, window=20, reason="prior_20_highs_missing_or_invalid"
    )
    volumes, volume_errors = trailing_positive_history(
        prior_volumes, window=20, reason="prior_20_volumes_missing_or_invalid"
    )
    metrics, metric_errors = required_finite(
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

    config = CONFIG
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


class BreakoutV1(Strategy):
    config = CONFIG
    rule = staticmethod(evaluate_breakout_v1)
    entry_type = "breakout"
    label_zh = "突破條件"
    research_label_zh = "突破研究條件"
    requires_zh = (
        "20 日前期高點",
        "20 日前期成交量",
        "族群相對 TAIEX 的 20 日超額報酬",
        "5 日法人流向",
        "5 日融資餘額變化率",
    )
    candidate_reason = "breakout_20d_high"

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        return dict(
            close=inputs.close,
            prior_highs=inputs.prior_highs,
            volume=inputs.volume,
            prior_volumes=inputs.prior_volumes,
            group_excess_return_20d=inputs.group_excess_return_20d,
            institutional_flow_to_turnover_ratio_5d=inputs.institutional_flow_ratio_5d,
            margin_balance_change_ratio_5d=inputs.margin_change_ratio_5d,
        )

    def actionable_levels(self, inputs: StrategyInputs) -> SignalLevels:
        close = inputs.close
        prior_highs = inputs.prior_highs
        prior_high = (
            max(prior_highs[-20:]) if prior_highs and len(prior_highs) >= 20 else close
        )
        entry, invalid_price, target_1, target_2 = risk_levels(
            max(close, float(prior_high)), inputs.atr14
        )
        return SignalLevels(
            breakout_price=entry,
            invalid_price=invalid_price,
            target_1=target_1,
            target_2=target_2,
        )

    def candidate_distance(
        self, close: float, evidence_inputs: Mapping[str, Any]
    ) -> float | None:
        highs = [
            finite_number(item) for item in evidence_inputs.get("prior_20_highs") or []
        ]
        if len(highs) == 20 and all(item is not None and item > 0 for item in highs):
            return close / max(highs) - 1
        return None


BREAKOUT_V1 = BreakoutV1()
