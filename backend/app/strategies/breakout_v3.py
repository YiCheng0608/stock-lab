"""``breakout_v3``: ``breakout_v2`` whose margin condition reads a zero base.

The one difference (Issue #404): a margin security whose balance five
sessions ago was 0 has no five-day margin change ratio.  v2 records it as
``data_incomplete``; v3 judges it by the two balances
(``app.margin_zero_base``): 0 then 0 is no change and the condition holds,
0 then more than 0 is ``margin_financing_increase_abnormal``.  Every other
condition, threshold and level is ``breakout_v2``'s, and v2 is not changed:
its stored signals keep their results.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app import margin_zero_base as zero_base
from app.domain import RuleEvaluation
from app.margin_lists import NOT_APPLICABLE

from .base import StrategyInputs, finite_number
from .breakout_v2 import CONFIG as V2_CONFIG
from .breakout_v2 import BreakoutV2, evaluate_breakout_v2, without_margin_confirmation

CONFIG: dict[str, Any] = copy.deepcopy(V2_CONFIG)
CONFIG["name"] = "breakout_v3"
CONFIG["version"] = "3.0.0"
CONFIG["supersedes"] = {"name": "breakout_v2", "version": "2.0.0"}
CONFIG["data_policy"]["margin_zero_base"] = zero_base.RULE

INCREASE_ABNORMAL = "margin_financing_increase_abnormal"


def judge_zero_base(
    evaluate: Callable[..., RuleEvaluation],
    *,
    margin_balance_change_ratio_5d: float | None,
    margin_financing: str,
    margin_zero_base: str | None,
    config: Mapping[str, Any],
    **arguments: Any,
) -> RuleEvaluation:
    """``evaluate`` (a v2 evaluator) with a zero base judged by its balances.

    Only a security without a ratio whose margin condition is not
    ``not_applicable`` (#392 comes first) reads the zero-base state.  No
    change is the ratio 0.  An increase from 0 runs ``evaluate`` without the
    margin comparison (the mechanism research ablations use) and adds
    ``margin_financing_increase_abnormal`` to its result, at the place the
    margin comparison gives it; a result without data stays
    ``data_incomplete``.  A configuration without the margin confirmation
    (the margin ablation) never adds it.
    """

    ratio = margin_balance_change_ratio_5d
    increased = False
    judged_config = config
    if finite_number(ratio) is None and margin_financing != NOT_APPLICABLE:
        if margin_zero_base == zero_base.UNCHANGED:
            ratio = 0.0
        elif margin_zero_base == zero_base.INCREASED:
            increased = "margin_financing" in config["confirmations"]
            judged_config = without_margin_confirmation(config)
            ratio = 0.0
    result = evaluate(
        margin_balance_change_ratio_5d=ratio,
        margin_financing=margin_financing,
        config=judged_config,
        **arguments,
    )
    if not increased or result.state == "data_incomplete":
        return result
    return RuleEvaluation(False, "rejected", (*result.reasons, INCREASE_ABNORMAL))


def evaluate_breakout_v3(
    *,
    close: float | None,
    prior_highs: Iterable[float] | None,
    volume: float | None,
    prior_volumes: Iterable[float] | None,
    group_excess_return_20d: float | None,
    institutional_flow_to_turnover_ratio_5d: float | None,
    margin_balance_change_ratio_5d: float | None,
    margin_financing: str,
    margin_zero_base: str | None,
    config: Mapping[str, Any] = CONFIG,
) -> RuleEvaluation:
    """``evaluate_breakout_v2``, judging a zero margin base (``judge_zero_base``)."""

    return judge_zero_base(
        evaluate_breakout_v2,
        close=close,
        prior_highs=prior_highs,
        volume=volume,
        prior_volumes=prior_volumes,
        group_excess_return_20d=group_excess_return_20d,
        institutional_flow_to_turnover_ratio_5d=institutional_flow_to_turnover_ratio_5d,
        margin_balance_change_ratio_5d=margin_balance_change_ratio_5d,
        margin_financing=margin_financing,
        margin_zero_base=margin_zero_base,
        config=config,
    )


class BreakoutV3(BreakoutV2):
    config = CONFIG
    rule = staticmethod(evaluate_breakout_v3)

    def arguments(self, inputs: StrategyInputs) -> dict[str, Any]:
        return {
            **super().arguments(inputs),
            "margin_zero_base": inputs.margin_zero_base,
        }


BREAKOUT_V3 = BreakoutV3()
