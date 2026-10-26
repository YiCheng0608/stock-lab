"""``pullback_v1``: an uptrend's close back in the MA20 support zone."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.domain import RuleEvaluation

from . import levels
from .base import (
    COMMON_CONFIRMATIONS,
    COMMON_EXECUTION,
    COMMON_RISK_MANAGEMENT,
    COMMON_UNIVERSE,
    Condition,
    NextSessionInputs,
    ObservationLevels,
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

    def observation_levels(self, inputs: NextSessionInputs) -> ObservationLevels:
        """The next close range [L, U] that passes trend and support, and its volume.

        With S19/S59 the last 19/59 closes through T, the next close c makes
        MA20 = (S19 + c)/20 and MA60 = (S59 + c)/60, so every price condition
        is linear in c: MA20 > MA60 <=> c > (S59 - 3*S19)/2; close >= MA60
        <=> c >= S59/59; 0.97 <= c/MA20 <= 1.02 <=> 0.97*S19/19.03 <= c <=
        1.02*S19/18.98.  L is the highest lower bound rounded up to a legal
        price, U the upper bound rounded down; L > U means the trend cannot
        pass next session (``trend_unreachable``, no price levels).
        """

        unavailable = levels.unavailable(inputs)
        if unavailable is not None:
            return unavailable
        minimum_bars = CONFIG["trend"]["minimum_history_trading_days"]
        closes = levels.positive_window(inputs.closes, minimum_bars - 1)
        average = levels.average_volume(inputs.volumes)
        missing = [
            *(
                ["history_under_60_bars"]
                if inputs.bar_count + 1 < minimum_bars
                else []
                if closes is not None
                else ["ma60_missing_or_non_finite"]
            ),
            *([] if average is not None else ["prior_20_volumes_missing_or_invalid"]),
            *(
                []
                if inputs.close and inputs.close > 0
                else ["close_missing_or_non_finite"]
            ),
            *levels.missing_confirmations(inputs),
        ]
        if missing:
            return ObservationLevels("data_incomplete", tuple(missing))
        kind = inputs.instrument_type
        s19 = sum(closes[-19:])
        s59 = sum(closes[-59:])
        zone = CONFIG["support_zone"]
        low_ratio = zone["minimum_close_to_ma20_ratio"]
        high_ratio = zone["maximum_close_to_ma20_ratio"]
        trend_low = levels.tick_ceil((s59 - 3 * s19) / 2, kind, strict=True)
        ma60_low = levels.tick_ceil(s59 / 59, kind)
        zone_low = levels.tick_ceil(low_ratio * s19 / (20 - low_ratio), kind)
        zone_high = levels.tick_floor(high_ratio * s19 / (20 - high_ratio), kind)
        low = max(trend_low, ma60_low, zone_low)
        volume = CONFIG["volume"]
        min_volume = levels.volume_at_least(
            volume["minimum_signal_to_average_ratio"], average
        )
        max_volume = levels.volume_at_most(
            volume["maximum_signal_to_average_ratio"], average
        )
        close = inputs.close
        position = (
            "below" if close < low else "above" if close > zone_high else "inside"
        )
        next_session = {
            "pullback_trend": {"min_close": trend_low},
            "pullback_above_ma60": {"min_close": ma60_low},
            "pullback_support_zone": {
                "min_close": low,
                "max_close": zone_high,
                "position": position,
                "gap": 0.0
                if position == "inside"
                else levels.gap(low if position == "below" else zone_high, close),
            },
            "pullback_volume": {"min_volume": min_volume, "max_volume": max_volume},
        }
        if low > zone_high:
            next_session["pullback_support_zone"] = {
                "min_close": zone_low,
                "max_close": zone_high,
            }
            return ObservationLevels(
                "trend_unreachable",
                ("trend_cannot_pass_within_support_zone",),
                next_session=next_session,
            )
        entry = min(max(close, low), zone_high)
        reference = levels.reference_levels(entry, inputs.atr14)
        # The actionable entry zone (actionable_levels) around the MA20 that
        # this close would make.
        ma20 = (s19 + entry) / 20
        width = max((inputs.atr14 or entry * 0.01) * 0.5, entry * 0.005)
        limits = levels.price_limits(inputs)
        return ObservationLevels(
            "levels",
            zone_low=low,
            zone_high=zone_high,
            min_volume=min_volume,
            max_volume=max_volume,
            entry_low=round(max(0.01, ma20 - width), 2),
            entry_high=round(ma20 + width, 2),
            **reference,
            reachable_next_session=None
            if limits is None
            else low <= limits[1] and zone_high >= limits[0],
            next_session=next_session,
        )

    def conditions(
        self,
        inputs: StrategyInputs,
        evaluation: RuleEvaluation,
        observation: ObservationLevels,
    ) -> list[Condition]:
        minimum_bars = CONFIG["trend"]["minimum_history_trading_days"]
        ma20 = finite_number(inputs.ma20)
        ma60 = finite_number(inputs.ma60)
        close = finite_number(inputs.close)
        volume = finite_number(inputs.volume)
        average = levels.average_volume(inputs.prior_volumes)
        zone = CONFIG["support_zone"]
        volume_config = CONFIG["volume"]
        next_session = observation.next_session
        return [
            Condition(
                "pullback_history",
                "data",
                inputs.bar_count >= minimum_bars,
                actual=inputs.bar_count,
                threshold=minimum_bars,
                operator="gte",
                next_session={"bar_count": inputs.bar_count + 1},
            ),
            Condition(
                "pullback_trend",
                "trend",
                levels.satisfied(evaluation, ("ma20_not_above_ma60",)),
                actual=ma20,
                threshold=ma60,
                operator="gt",
                next_session=next_session.get("pullback_trend"),
            ),
            Condition(
                "pullback_above_ma60",
                "trend",
                levels.satisfied(evaluation, ("close_below_ma60",)),
                actual=close,
                threshold=ma60,
                operator="gte",
                next_session=next_session.get("pullback_above_ma60"),
            ),
            Condition(
                "pullback_support_zone",
                "price",
                levels.satisfied(evaluation, ("close_outside_ma20_support_zone",)),
                actual=close,
                threshold=round(ma20 * zone["minimum_close_to_ma20_ratio"], 6)
                if ma20
                else None,
                threshold_high=round(ma20 * zone["maximum_close_to_ma20_ratio"], 6)
                if ma20
                else None,
                operator="between",
                next_session=next_session.get("pullback_support_zone"),
            ),
            Condition(
                "pullback_volume",
                "volume",
                levels.satisfied(evaluation, ("pullback_volume_ratio_outside_range",)),
                actual=round(volume / float(average), 6)
                if volume is not None and average
                else None,
                threshold=volume_config["minimum_signal_to_average_ratio"],
                threshold_high=volume_config["maximum_signal_to_average_ratio"],
                operator="between",
                next_session=next_session.get("pullback_volume"),
            ),
            *levels.confirmation_conditions(inputs, evaluation),
        ]


PULLBACK_V1 = PullbackV1()
