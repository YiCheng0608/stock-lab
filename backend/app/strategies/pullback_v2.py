"""``pullback_v2``: ``pullback_v1`` whose margin condition can be not applicable.

Same single difference as ``breakout_v2`` (Issue #392); every other
condition, threshold and level is ``pullback_v1``'s, and v1 is not changed.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from app.domain import RuleEvaluation
from app.margin_lists import NOT_APPLICABLE
from app.margin_lists import RULE as MARGIN_ELIGIBILITY_RULE

from .base import StrategyInputs, finite_number
from .breakout_v2 import without_margin_confirmation
from .pullback_v1 import CONFIG as V1_CONFIG
from .pullback_v1 import PullbackV1, evaluate_pullback_v1

CONFIG: dict[str, Any] = copy.deepcopy(V1_CONFIG)
CONFIG["name"] = "pullback_v2"
CONFIG["version"] = "2.0.0"
CONFIG["supersedes"] = {"name": "pullback_v1", "version": "1.0.0"}
CONFIG["data_policy"]["margin_financing_eligibility"] = {
    "rule": MARGIN_ELIGIBILITY_RULE,
    "on_not_applicable": "skip_margin_financing_confirmation",
}


def evaluate_pullback_v2(
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
    margin_financing: str,
    config: Mapping[str, Any] = CONFIG,
) -> RuleEvaluation:
    """``evaluate_pullback_v1``, skipping margin for a non-margin security.

    See ``evaluate_breakout_v2``.
    """

    if margin_financing == NOT_APPLICABLE and (
        finite_number(margin_balance_change_ratio_5d) is None
    ):
        config = without_margin_confirmation(config)
        margin_balance_change_ratio_5d = 0.0
    return evaluate_pullback_v1(
        bar_count=bar_count,
        close=close,
        ma20=ma20,
        ma60=ma60,
        volume=volume,
        prior_volumes=prior_volumes,
        group_excess_return_20d=group_excess_return_20d,
        institutional_flow_to_turnover_ratio_5d=institutional_flow_to_turnover_ratio_5d,
        margin_balance_change_ratio_5d=margin_balance_change_ratio_5d,
        config=config,
    )


class PullbackV2(PullbackV1):
    config = CONFIG
    rule = staticmethod(evaluate_pullback_v2)
    requires_zh = (
        "60 日有效行情日數",
        "MA20",
        "MA60",
        "20 日前期成交量",
        "族群相對 TAIEX 的 20 日超額報酬",
        "5 日法人流向",
        "5 日融資餘額變化率（融資標的）",
    )

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        return {
            **super().arguments(inputs),
            "margin_financing": inputs.margin_financing,
        }


PULLBACK_V2 = PullbackV2()
