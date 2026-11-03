"""``pullback_v3``: ``pullback_v2`` whose margin condition reads a zero base.

Same single difference as ``breakout_v3`` (Issue #404); every other
condition, threshold and level is ``pullback_v2``'s, and v2 is not changed.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from app import margin_zero_base as zero_base
from app.domain import RuleEvaluation

from .base import StrategyInputs
from .breakout_v3 import judge_zero_base
from .pullback_v2 import CONFIG as V2_CONFIG
from .pullback_v2 import PullbackV2, evaluate_pullback_v2

CONFIG: dict[str, Any] = copy.deepcopy(V2_CONFIG)
CONFIG["name"] = "pullback_v3"
CONFIG["version"] = "3.0.0"
CONFIG["supersedes"] = {"name": "pullback_v2", "version": "2.0.0"}
CONFIG["data_policy"]["margin_zero_base"] = zero_base.RULE


def evaluate_pullback_v3(
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
    margin_zero_base: str | None,
    config: Mapping[str, Any] = CONFIG,
) -> RuleEvaluation:
    """``evaluate_pullback_v2``, judging a zero margin base (``judge_zero_base``)."""

    return judge_zero_base(
        evaluate_pullback_v2,
        bar_count=bar_count,
        close=close,
        ma20=ma20,
        ma60=ma60,
        volume=volume,
        prior_volumes=prior_volumes,
        group_excess_return_20d=group_excess_return_20d,
        institutional_flow_to_turnover_ratio_5d=institutional_flow_to_turnover_ratio_5d,
        margin_balance_change_ratio_5d=margin_balance_change_ratio_5d,
        margin_financing=margin_financing,
        margin_zero_base=margin_zero_base,
        config=config,
    )


class PullbackV3(PullbackV2):
    config = CONFIG
    rule = staticmethod(evaluate_pullback_v3)

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        return {
            **super().arguments(inputs),
            "margin_zero_base": inputs.margin_zero_base,
        }


PULLBACK_V3 = PullbackV3()
