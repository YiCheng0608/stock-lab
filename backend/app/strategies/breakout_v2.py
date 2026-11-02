"""``breakout_v2``: ``breakout_v1`` whose margin condition can be not applicable.

The one difference (Issue #392): a security that is not a margin-financing
security (``app.margin_lists``) has no five-day margin change ratio; v2 skips
that confirmation instead of failing closed as ``data_incomplete``.  Every
other condition, threshold and level is ``breakout_v1``'s, and v1 is not
changed: its stored signals keep their results.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from app.domain import RuleEvaluation
from app.margin_lists import NOT_APPLICABLE
from app.margin_lists import RULE as MARGIN_ELIGIBILITY_RULE

from .base import StrategyInputs, finite_number
from .breakout_v1 import CONFIG as V1_CONFIG
from .breakout_v1 import BreakoutV1, evaluate_breakout_v1

CONFIG: dict[str, Any] = copy.deepcopy(V1_CONFIG)
CONFIG["name"] = "breakout_v2"
CONFIG["version"] = "2.0.0"
CONFIG["supersedes"] = {"name": "breakout_v1", "version": "1.0.0"}
CONFIG["data_policy"]["margin_financing_eligibility"] = {
    "rule": MARGIN_ELIGIBILITY_RULE,
    "on_not_applicable": "skip_margin_financing_confirmation",
}


def without_margin_confirmation(config: Mapping[str, Any]) -> dict[str, Any]:
    """``config`` whose confirmations do not list margin financing."""

    result = dict(config)
    result["confirmations"] = {
        key: value
        for key, value in config["confirmations"].items()
        if key != "margin_financing"
    }
    return result


def evaluate_breakout_v2(
    *,
    close: float | None,
    prior_highs: Iterable[float] | None,
    volume: float | None,
    prior_volumes: Iterable[float] | None,
    group_excess_return_20d: float | None,
    institutional_flow_to_turnover_ratio_5d: float | None,
    margin_balance_change_ratio_5d: float | None,
    margin_financing: str,
    config: Mapping[str, Any] = CONFIG,
) -> RuleEvaluation:
    """``evaluate_breakout_v1``, skipping margin for a non-margin security.

    When the condition does not apply and there is no ratio, the v1
    evaluator runs on a configuration without the margin confirmation (the
    mechanism research ablations use), so that comparison is not made; the
    ratio it is handed then is never read.  A missing ratio of a security
    the condition applies to, or of unknown eligibility, stays
    ``data_incomplete``.
    """

    if margin_financing == NOT_APPLICABLE and (
        finite_number(margin_balance_change_ratio_5d) is None
    ):
        config = without_margin_confirmation(config)
        margin_balance_change_ratio_5d = 0.0
    return evaluate_breakout_v1(
        close=close,
        prior_highs=prior_highs,
        volume=volume,
        prior_volumes=prior_volumes,
        group_excess_return_20d=group_excess_return_20d,
        institutional_flow_to_turnover_ratio_5d=institutional_flow_to_turnover_ratio_5d,
        margin_balance_change_ratio_5d=margin_balance_change_ratio_5d,
        config=config,
    )


class BreakoutV2(BreakoutV1):
    config = CONFIG
    rule = staticmethod(evaluate_breakout_v2)
    requires_zh = (
        "20 日前期高點",
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


BREAKOUT_V2 = BreakoutV2()
