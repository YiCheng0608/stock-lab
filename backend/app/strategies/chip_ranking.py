"""Research-only chip rankings (#598): the candidate order with chips weighted up.

The signals do not change: a ranking orders the same day's candidate pool
``candidate_score_v7`` scores (``worker.candidates``), and the research tool
``tools/research/ranking_research.py`` compares each ranking's first
``TOP_N`` with v7's.  Nothing here is a score version: no ranking writes
``candidate_runs``／``daily_candidates`` rows or enters ``CANDIDATE_SCORE``.

- ``v7``: the stored rule (weights, coverage floor, required technical,
  one row per instrument, tie-break), recomputed on the research run's
  signals; the baseline.
- ``k1``: chips weight 0.30 → 0.50, the other three scaled by the same
  factor (0.50／0.70) so the weights still sum to 1; v7's component scores.
- ``k2``: k1's weights; the chips component is 0.5 × (sessions of the last
  five with a positive institutional net buy ÷ 5) + 0.5 × (1 when the
  five-session margin change is negative, else 0), on absolute scales.
  Either input missing makes the component null, as v7's missing chips do
  (the other weights renormalize and the 0.65 coverage floor applies).
- ``k3``: v7's scores, kept only for entries whose five-session
  institutional flow is positive and whose margin change is ≤ 0; an entry
  without either value is dropped (a non-margin security has no change).

The samples are #567's, and ``judge_exploration``／``judge_validation`` are
the rule a ranking passes in each to be proposed; both were fixed before any
result was read.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain import CANDIDATE_SCORE_V7, weighted_available_mean

from .index_conditions import EXPLORATION, SEGMENTS, VALIDATION, segment_of

ISSUE = 598
TOP_N = 10
# The ranking's pool is the one v7 scores; the baseline is v7 itself.
SCORE_CONFIG: Mapping[str, Any] = CANDIDATE_SCORE_V7
COMPONENTS = ("technical", "chips", "group", "news_sentiment")
V7_WEIGHTS: dict[str, float] = {
    key: float(SCORE_CONFIG["weights"][key]) for key in COMPONENTS
}
K_CHIPS_WEIGHT = 0.50


def _chips_weighted(weights: Mapping[str, float], chips: float) -> dict[str, float]:
    rest = sum(value for key, value in weights.items() if key != "chips")
    factor = (1.0 - chips) / rest
    return {
        key: chips if key == "chips" else value * factor
        for key, value in weights.items()
    }


K1_WEIGHTS = _chips_weighted(V7_WEIGHTS, K_CHIPS_WEIGHT)


@dataclass(frozen=True)
class Ranking:
    code: str
    label_zh: str
    weights: Mapping[str, float]
    chips: str  # "v7" or "k2"
    flow_and_margin_filter: bool = False


RANKINGS: dict[str, Ranking] = {
    item.code: item
    for item in (
        Ranking("v7", "baseline：candidate_score_v7 排序", V7_WEIGHTS, "v7"),
        Ranking("k1", "K1：籌碼權重 0.30 → 0.50，其餘等比例縮小", K1_WEIGHTS, "v7"),
        Ranking(
            "k2",
            "K2：籌碼分項改為法人買超天數與融資減少各半，權重同 K1",
            K1_WEIGHTS,
            "k2",
        ),
        Ranking(
            "k3",
            "K3：只在法人 5 日淨買超 > 0 且融資 5 日變化 ≤ 0 的候選裡排序",
            V7_WEIGHTS,
            "v7",
            flow_and_margin_filter=True,
        ),
    )
}


@dataclass
class Entry:
    """One pool signal with v7's component scores and the chip inputs a ranking reads."""

    signal_id: int
    instrument_id: int
    exchange: str
    symbol: str
    strategy: str
    scores: Mapping[str, float | None]  # v7 component scores by COMPONENTS
    institutional_flow_5d: float | None = None
    margin_change_5d: float | None = None
    positive_flow_sessions_5d: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def k2_chips(
    positive_flow_sessions_5d: int | None, margin_change_5d: float | None
) -> float | None:
    if positive_flow_sessions_5d is None or margin_change_5d is None:
        return None
    if not 0 <= positive_flow_sessions_5d <= 5:
        raise ValueError(f"positive sessions {positive_flow_sessions_5d} not in 0..5")
    return 0.5 * (positive_flow_sessions_5d / 5) + 0.5 * (
        1.0 if margin_change_5d < 0 else 0.0
    )


def passes_flow_and_margin(entry: Entry) -> bool:
    return (
        entry.institutional_flow_5d is not None
        and entry.margin_change_5d is not None
        and entry.institutional_flow_5d > 0
        and entry.margin_change_5d <= 0
    )


@dataclass(frozen=True)
class Ranked:
    entry: Entry
    total: float
    coverage: float
    scores: Mapping[str, float | None]


def rank(
    entries: Iterable[Entry],
    code: str,
    *,
    strategy_order: Sequence[str] | None = None,
) -> list[Ranked]:
    """``entries`` in ``code``'s order: v7's rule with the ranking's weights and chips.

    Same steps as ``worker.candidates._score_pool`` after the components:
    the weighted mean of the available components and the weight it covers,
    the coverage floor and the required components, the best strategy per
    instrument (highest total, then the pool's strategy order), and the
    tie-break (total, technical, chips, exchange, symbol), all descending
    except the last two.  No list cutoff: the caller takes the first
    ``TOP_N``.
    """

    ranking = RANKINGS[code]
    order = list(strategy_order or SCORE_CONFIG["pool"]["strategies"])
    minimum = float(SCORE_CONFIG["minimum_weight_coverage"])
    required = list(SCORE_CONFIG["required_components"])
    eligible: list[Ranked] = []
    for entry in entries:
        if ranking.flow_and_margin_filter and not passes_flow_and_margin(entry):
            continue
        scores = dict(entry.scores)
        if ranking.chips == "k2":
            scores["chips"] = k2_chips(
                entry.positive_flow_sessions_5d, entry.margin_change_5d
            )
        total, coverage = weighted_available_mean(scores, ranking.weights)
        if (
            total is None
            or any(scores.get(key) is None for key in required)
            or coverage + 1e-12 < minimum
        ):
            continue
        eligible.append(Ranked(entry, total, coverage, scores))

    best: dict[int, Ranked] = {}
    for item in sorted(
        eligible, key=lambda item: (-item.total, order.index(item.entry.strategy))
    ):
        best.setdefault(item.entry.instrument_id, item)

    def key(item: Ranked) -> tuple:
        technical = item.scores.get("technical")
        chips = item.scores.get("chips")
        return (
            -item.total,
            technical is None,
            -(technical or 0.0),
            chips is None,
            -(chips or 0.0),
            item.entry.exchange,
            item.entry.symbol,
        )

    return sorted(best.values(), key=key)


def overlap(first: Sequence[int], second: Sequence[int], size: int = TOP_N) -> float:
    """|first[:size] ∩ second[:size]| ÷ the larger of the two tops.

    A day whose pool holds fewer than ``size`` actionable stocks has short
    tops; dividing by ``size`` would score v7 against itself below 100%.
    Two empty tops count as 0.
    """

    a, b = set(first[:size]), set(second[:size])
    larger = max(len(a), len(b))
    return len(a & b) / larger if larger else 0.0


# ---- the rule a ranking passes to be proposed (fixed before any result) ----

# A segment counts only when the ranking's first TOP_N differ from v7's in at
# least MIN_REPLACED slots (signals in the ranking's top that are not in v7's
# on the same date) and its top keeps at least MIN_T20 usable T+20 returns.
MIN_REPLACED = 30
MIN_T20 = 100
SELECTION_RULE_ZH = (
    "探索段選出：與 baseline 每日前 10 檔不同的名額 ≥ 30、版本前 10 檔 T+20 可用報酬 ≥ 100 筆，"
    "且版本前 10 檔的 T+20 中位數高於 baseline 前 10 檔、invalidated 比例低於 baseline。"
    "驗證段沒有反轉：同樣的樣本門檻下，T+20 中位數不低於 baseline、invalidated 比例不高於 baseline；"
    "門檻不足記「無法判定」，不算沒有反轉。提案只引用兩段都過的排序。"
)


@dataclass(frozen=True)
class Comparison:
    """One segment: a ranking's first TOP_N against v7's."""

    replaced: int
    t20_n: int
    t20_median: float | None
    baseline_t20_median: float | None
    invalidated_share: float | None
    baseline_invalidated_share: float | None

    @property
    def judgeable(self) -> bool:
        return (
            self.replaced >= MIN_REPLACED
            and self.t20_n >= MIN_T20
            and None
            not in (
                self.t20_median,
                self.baseline_t20_median,
                self.invalidated_share,
                self.baseline_invalidated_share,
            )
        )


def judge_exploration(item: Comparison) -> str:
    if not item.judgeable:
        return "insufficient"
    better = (
        item.t20_median > item.baseline_t20_median
        and item.invalidated_share < item.baseline_invalidated_share
    )
    return "selected" if better else "not_selected"


def judge_validation(item: Comparison) -> str:
    if not item.judgeable:
        return "insufficient"
    held = (
        item.t20_median >= item.baseline_t20_median
        and item.invalidated_share <= item.baseline_invalidated_share
    )
    return "not_reversed" if held else "reversed"


def proposable(exploration: Comparison, validation: Comparison) -> bool:
    return (
        judge_exploration(exploration) == "selected"
        and judge_validation(validation) == "not_reversed"
    )


__all__ = [
    "EXPLORATION",
    "K1_WEIGHTS",
    "RANKINGS",
    "SEGMENTS",
    "TOP_N",
    "V7_WEIGHTS",
    "VALIDATION",
    "Comparison",
    "Entry",
    "judge_exploration",
    "judge_validation",
    "k2_chips",
    "overlap",
    "passes_flow_and_margin",
    "proposable",
    "rank",
    "segment_of",
]
