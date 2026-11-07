"""Research-only market-regime filters (#546): a registered strategy plus one TAIEX condition.

A regime strategy is named ``<strategy>_regime_<filter>`` (kind
``<kind>_regime_<filter>``).  Its rule is the registered strategy's rule,
called exactly as a canonical run calls it, followed by one condition on
TAIEX's own closes through the signal date (``FILTERS``):

- the condition holds: the strategy's result, unchanged;
- it fails: a passed result becomes ``rejected`` with
  ``market_regime_<filter>_not_met``, a rejected one gains that reason, and
  the strategy's own ``data_incomplete`` stays as it is;
- TAIEX has no bar on the signal date, or fewer closes through it than the
  filter needs: ``data_incomplete`` (``taiex_bar_missing``／
  ``taiex_closes_insufficient``), never a failed condition.

Strategy inputs carry no date, so the closes come from a :class:`TaiexCloses`
the research run fills from ``market_bars`` and points at each score date
before that date's signals are written (``tools/research/backtest_research.py``);
a regime strategy evaluated with no score date set raises instead of guessing.
Like ablations (``app.strategies.ablation``), regime strategies never enter
``REGISTRY``: only a research backtest on a copy of the database or an
isolated one evaluates them, and that run writes their StrategyVersion rows.
"""

from __future__ import annotations

import bisect
import copy
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain import RuleEvaluation, _finite, moving_average

from . import REGISTRY, registry_problems
from .base import Strategy, StrategyInputs

BENCHMARK_ID = "TAIEX"
BAR_MISSING = "taiex_bar_missing"
CLOSES_INSUFFICIENT = "taiex_closes_insufficient"
CLOSE_NOT_FINITE = "taiex_close_missing_or_non_finite"


def _return_20d_positive(closes: Sequence[float]) -> bool:
    return closes[-1] / closes[-21] - 1.0 > 0.0


def _close_above_ma20(closes: Sequence[float]) -> bool:
    return closes[-1] > moving_average(closes, 20)


def _close_above_ma60(closes: Sequence[float]) -> bool:
    return closes[-1] > moving_average(closes, 60)


def _ma20_above_ma60_and_close_above_ma60(closes: Sequence[float]) -> bool:
    ma60 = moving_average(closes, 60)
    return moving_average(closes, 20) > ma60 and closes[-1] > ma60


def _ma20_rising_5d(closes: Sequence[float]) -> bool:
    return moving_average(closes, 20) > moving_average(closes[:-5], 20)


@dataclass(frozen=True)
class RegimeFilter:
    """One TAIEX condition: ``holds`` reads the last ``required_closes`` closes."""

    code: str
    definition: str
    required_closes: int
    holds: Callable[[Sequence[float]], bool]
    label_zh: str

    @property
    def reason(self) -> str:
        return f"market_regime_{self.code}_not_met"

    def snapshot(self) -> dict[str, Any]:
        return {
            "filter": self.code,
            "definition": self.definition,
            "benchmark_id": BENCHMARK_ID,
            "price_field": "market_bars.close",
            "window_basis": "inclusive_signal_day",
            "required_closes": self.required_closes,
            "missing_policy": "data_incomplete",
            "failed_reason": self.reason,
        }


# R1～R4 are the Issue's candidates; R5 is the engineer's (#546 範圍).  Moving
# averages are app.domain.moving_average of the closes through the signal day,
# as the stock MA20／MA60 of technical_features; the 20-session return is the
# close over the close 20 sessions earlier, as worker.pipeline._price_return.
FILTERS: dict[str, RegimeFilter] = {
    item.code: item
    for item in (
        RegimeFilter(
            "r1",
            "taiex_return_20d_gt_0",
            21,
            _return_20d_positive,
            "TAIEX 20 日報酬 > 0",
        ),
        RegimeFilter(
            "r2", "taiex_close_gt_ma20", 20, _close_above_ma20, "TAIEX 收盤 > MA20"
        ),
        RegimeFilter(
            "r3", "taiex_close_gt_ma60", 60, _close_above_ma60, "TAIEX 收盤 > MA60"
        ),
        RegimeFilter(
            "r4",
            "taiex_ma20_gt_ma60_and_close_gt_ma60",
            60,
            _ma20_above_ma60_and_close_above_ma60,
            "TAIEX MA20 > MA60 且收盤 > MA60",
        ),
        RegimeFilter(
            "r5",
            "taiex_ma20_gt_ma20_5_sessions_earlier",
            25,
            _ma20_rising_5d,
            "TAIEX MA20 高於 5 個交易日前的 MA20",
        ),
    )
}
LOOKBACK = max(item.required_closes for item in FILTERS.values())


def evaluate_filter(code: str, closes: Sequence[float | None] | None) -> RuleEvaluation:
    """``FILTERS[code]`` on TAIEX's closes through the signal day (oldest first).

    ``closes`` is None when TAIEX has no bar on the signal day.  Only the last
    ``required_closes`` are read; a missing or non-finite one among them is
    ``data_incomplete`` as a short history is.
    """

    item = FILTERS[code]
    if closes is None:
        return RuleEvaluation(False, "data_incomplete", (BAR_MISSING,))
    if len(closes) < item.required_closes:
        return RuleEvaluation(False, "data_incomplete", (CLOSES_INSUFFICIENT,))
    window = list(closes[-item.required_closes :])
    if not all(_finite(value) and float(value) > 0 for value in window):
        return RuleEvaluation(False, "data_incomplete", (CLOSE_NOT_FINITE,))
    window = [float(value) for value in window]
    if item.holds(window):
        return RuleEvaluation(True, "passed")
    return RuleEvaluation(False, "rejected", (item.reason,))


def evaluate_with_regime(
    rule: Callable[..., RuleEvaluation],
    code: str,
    *,
    taiex_closes: Sequence[float | None] | None,
    **arguments: Any,
) -> RuleEvaluation:
    """``rule(**arguments)`` followed by the filter ``code`` (module docstring)."""

    result = rule(**arguments)
    regime = evaluate_filter(code, taiex_closes)
    if regime.passed:
        return result
    if regime.state == "data_incomplete":
        own = result.reasons if result.state == "data_incomplete" else ()
        return RuleEvaluation(False, "data_incomplete", (*own, *regime.reasons))
    if result.state == "data_incomplete":
        return result
    return RuleEvaluation(False, "rejected", (*result.reasons, *regime.reasons))


class TaiexCloses:
    """TAIEX closes by date, and the score date the research run is writing.

    ``window()`` is the last ``LOOKBACK`` closes through the score date, or
    None when TAIEX has no bar on it; only dates up to the score date are
    read, so a filter never sees a later close.
    """

    def __init__(self, closes: Mapping[date, float | None]) -> None:
        self.dates = sorted(closes)
        self.closes = [closes[day] for day in self.dates]
        self.session: date | None = None
        self._window: tuple[float | None, ...] | None = None

    def set_session(self, day: date | None) -> None:
        self.session = day
        self._window = None
        if day is None:
            return
        at = bisect.bisect_right(self.dates, day)
        if at and self.dates[at - 1] == day:
            self._window = tuple(self.closes[max(0, at - LOOKBACK) : at])

    def window(self) -> tuple[float | None, ...] | None:
        if self.session is None:
            raise RuntimeError(
                "regime strategy evaluated without a score date "
                "(TaiexCloses.set_session); only a research backtest sets it"
            )
        return self._window

    def states(self, code: str, days: Iterable[date]) -> dict[date, RuleEvaluation]:
        """The filter's result on each of ``days`` (for the research report)."""

        result = {}
        previous = self.session
        try:
            for day in days:
                self.set_session(day)
                result[day] = evaluate_filter(code, self._window)
        finally:
            self.set_session(previous)
        return result


def regime_strategy(strategy_key: str, code: str, closes: TaiexCloses) -> Strategy:
    """``REGISTRY[strategy_key]`` plus the filter ``code``, under its own name and kind."""

    base = REGISTRY[strategy_key]
    item = FILTERS[code]
    config: dict[str, Any] = copy.deepcopy(dict(base.config))
    config["name"] = f"{strategy_key}_regime_{code}"
    config["kind"] = f"{base.kind}_regime_{code}"
    config["regime_filter"] = {
        "base_strategy": strategy_key,
        "base_version": base.version,
        **item.snapshot(),
    }
    base_rule = base.rule

    def rule(**arguments: Any) -> RuleEvaluation:
        return evaluate_with_regime(base_rule, code, **arguments)

    def arguments(inputs: StrategyInputs) -> dict[str, Any]:
        return {**base.arguments(inputs), "taiex_closes": closes.window()}

    strategy = copy.copy(base)
    strategy.config = config
    strategy.rule = rule
    strategy.arguments = arguments
    return strategy


def with_regimes(
    registry: Mapping[str, Strategy],
    items: Iterable[tuple[str, str]],
    closes: TaiexCloses,
) -> dict[str, Strategy]:
    """``registry`` followed by the regime strategies ``items`` names."""

    result = dict(registry)
    problems = []
    for strategy_key, code in items:
        strategy = regime_strategy(strategy_key, code, closes)
        if strategy.key in result:
            problems.append(f"{strategy.key} is already in the registry")
        result[strategy.key] = strategy
    problems += registry_problems(result)
    if problems or not result:
        raise ValueError("; ".join(problems) or "empty research registry")
    return result


def all_regimes() -> list[tuple[str, str]]:
    return [(strategy_key, code) for strategy_key in REGISTRY for code in FILTERS]
