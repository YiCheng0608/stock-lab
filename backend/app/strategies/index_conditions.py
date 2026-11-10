"""Research-only index conditions (#567): a registered strategy plus one condition on stored index bars.

An index-condition strategy is named ``<strategy>_index_<code>`` (kind
``<kind>_index_<code>``).  Its rule is the registered strategy's rule, called
exactly as a canonical run calls it, followed by one condition of
``CONDITIONS`` on the ``market_bars`` rows of the indexes in ``SERIES``:

- the condition holds: the strategy's result, unchanged;
- it fails: a passed result becomes ``rejected`` with
  ``index_condition_<code>_not_met``, a rejected one gains that reason, and
  the strategy's own ``data_incomplete`` stays as it is;
- an index it reads has no usable row, or fewer rows than it needs:
  ``data_incomplete`` (``<series>_bar_missing``／``<series>_closes_insufficient``
  …), never a failed condition.

Which rows a condition reads:

- Taiwan series (TAIEX, TPEX, TX): the rows through the signal date, the
  signal date's own row required (``IndexView.through``), as
  ``app.strategies.regime``'s TAIEX closes.
- US series (SPX, SOX): the newest row dated before the signal date and the
  rows through it (``IndexView.before``).  A US close of date D − 1 is
  published before the Taipei session D opens; a row of D itself or later is
  never read.  A US holiday has no row, so the row before it is taken; a row
  older than ``US_STALE_DAYS`` calendar days is ``us_<series>_bar_stale``.
- TX is the stored near-month series (``worker.futures_bars.near_month``: the
  next month from the third Wednesday on), not adjusted across a roll, the
  ``contract_roll`` 口徑 of ``app.market_overview._futures_row``.  C3's
  basis compares the same day's TX and TAIEX closes, so a roll day uses the
  new contract.  C3's MA20 averages the stored closes as they are; a window
  that spans a roll mixes two contracts (the research report lists the
  gap at every roll).
- C2／C7 read the index of the stock's own market: ``TWSE`` reads TAIEX,
  ``TPEx`` reads TPEX (``MARKET_INDEX``).  Strategy inputs carry neither a date
  nor the instrument, so the research run points an :class:`IndexHistory` at
  each score date and each instrument before that instrument's signals are
  written (``tools/research/backtest_research.py``); evaluating a strategy
  with either unset raises instead of guessing.

The samples are split before any result is read (``EXPLORATION``／
``VALIDATION``), and ``judge_exploration``／``judge_validation`` are the rule a
condition must pass in each to be proposed.  Like ablations and regime
filters, these strategies never enter ``REGISTRY``: only a research
backtest on a copy of the database or an isolated one evaluates them.  The US
series are display-only (#547); reading them here is research, not an input of
any registered strategy.

The base strategies are fixed (``BASES``: ``breakout_v3`` and ``pullback_v3``),
not whatever ``REGISTRY`` holds, so a newer registered version does not change
what run 2759 measured; a run of index conditions alone replays both bases
as its baselines (``tools/research/backtest_research.py``).
"""

from __future__ import annotations

import bisect
import copy
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain import RuleEvaluation, _finite, moving_average

from . import registry_problems
from .base import Strategy, StrategyInputs
from .breakout_v3 import BREAKOUT_V3
from .pullback_v3 import PULLBACK_V3

# The versions #567 measured (run 2759); see the module docstring.
BASES: dict[str, Strategy] = {
    strategy.key: strategy for strategy in (BREAKOUT_V3, PULLBACK_V3)
}

# Series key -> (instruments.exchange, instruments.symbol, instrument_type).
SERIES: dict[str, tuple[str, str, str]] = {
    "TAIEX": ("TWSE", "TAIEX", "index"),
    "TPEX": ("TPEx", "TPEX", "index"),
    "TX": ("TAIFEX", "TX", "futures"),
    "SPX": ("US", "SPX", "index"),
    "SOX": ("US", "SOX", "index"),
}
US_SERIES = frozenset({"SPX", "SOX"})
# The stock's own market index (C2／C7), by instruments.exchange.
MARKET_INDEX = {"TWSE": "TAIEX", "TPEx": "TPEX"}
MARKET_INDEX_UNKNOWN = "market_index_unknown"
# A US row older than this before the signal date is stale: the longest US
# closure next to a weekend is four days (a Friday holiday and a Monday
# signal date: Thursday), so a week only fires on missing collection.
US_STALE_DAYS = 7


@dataclass(frozen=True)
class Segment:
    code: str
    label_zh: str
    start: date
    end: date | None  # None: through the run's last score date

    def contains(self, day: date) -> bool:
        return day >= self.start and (self.end is None or day <= self.end)


# Fixed before any result was read (#567 範圍「事先切分樣本」).
EXPLORATION = Segment("exploration", "探索段", date(2024, 9, 30), date(2025, 12, 31))
VALIDATION = Segment("validation", "驗證段", date(2026, 1, 1), None)
SEGMENTS = (EXPLORATION, VALIDATION)


def segment_of(day: date) -> str | None:
    return next((item.code for item in SEGMENTS if item.contains(day)), None)


class _Incomplete(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IndexCondition:
    """One index condition: ``holds(view)`` reads the rows it needs."""

    code: str
    definition: str
    label_zh: str
    reads: str  # what it reads, for the snapshot and the report
    series: tuple[str, ...]  # the SERIES keys it reads
    holds: Callable[[IndexView], bool]
    # False: #546 has read this condition's validation segment (R3), or the
    # condition was written after reading #546's full-range report.
    validation_independent: bool = True
    note_zh: str = ""
    # True: reads the stock's own market index (MARKET_INDEX), so its state
    # depends on the instrument as well as the date.
    per_market: bool = False

    @property
    def reason(self) -> str:
        return f"index_condition_{self.code}_not_met"

    def snapshot(self) -> dict[str, Any]:
        return {
            "condition": self.code,
            "definition": self.definition,
            "reads": self.reads,
            "series": list(self.series),
            "per_market": self.per_market,
            "price_field": "market_bars.close",
            "taiwan_window": "rows_through_signal_date_signal_date_required",
            "us_window": "rows_through_newest_us_date_before_signal_date",
            "us_stale_days": US_STALE_DAYS,
            "tx_roll": "near_month_series_not_adjusted_across_rolls",
            "market_index": dict(MARKET_INDEX),
            "missing_policy": "data_incomplete",
            "failed_reason": self.reason,
        }


class IndexView:
    """The stored index rows as of one score date, for one instrument's market."""

    def __init__(self, history: IndexHistory, session: date, exchange: str | None):
        self.history = history
        self.session = session
        self.exchange = exchange
        self._results: dict[str, RuleEvaluation] = {}

    def through(self, key: str, count: int) -> list[float]:
        """The last ``count`` closes of ``key`` through the score date (its row required)."""

        dates, closes, _ = self.history.series(key)
        at = bisect.bisect_right(dates, self.session)
        if not at or dates[at - 1] != self.session:
            raise _Incomplete(f"{key.lower()}_bar_missing")
        return _window(key, closes, at, count)

    def before(self, key: str, count: int) -> list[float]:
        """The last ``count`` closes of ``key`` through its newest date before the score date."""

        dates, closes, _ = self.history.series(key)
        at = bisect.bisect_left(dates, self.session)
        if not at:
            raise _Incomplete(f"us_{key.lower()}_bar_missing")
        if (self.session - dates[at - 1]).days > US_STALE_DAYS:
            raise _Incomplete(f"us_{key.lower()}_bar_stale")
        return _window(f"us_{key}", closes, at, count)

    def market_index(self) -> str:
        key = MARKET_INDEX.get(self.exchange or "")
        if key is None:
            raise _Incomplete(MARKET_INDEX_UNKNOWN)
        return key

    def result(self, code: str) -> RuleEvaluation:
        """``CONDITIONS[code]`` on this view (memoized: every stock of a market shares it)."""

        if code not in self._results:
            item = CONDITIONS[code]
            try:
                held = item.holds(self)
            except _Incomplete as missing:
                outcome = RuleEvaluation(False, "data_incomplete", (missing.reason,))
            else:
                outcome = (
                    RuleEvaluation(True, "passed")
                    if held
                    else RuleEvaluation(False, "rejected", (item.reason,))
                )
            self._results[code] = outcome
        return self._results[code]


def _window(
    key: str, closes: Sequence[float | None], at: int, count: int
) -> list[float]:
    if at < count:
        raise _Incomplete(f"{key.lower()}_closes_insufficient")
    window = closes[at - count : at]
    if not all(_finite(value) and float(value) > 0 for value in window):
        raise _Incomplete(f"{key.lower()}_close_missing_or_non_finite")
    return [float(value) for value in window]


def _above_ma(closes: Sequence[float], window: int) -> bool:
    return closes[-1] > moving_average(closes, window)


def _c1(view: IndexView) -> bool:
    return _above_ma(view.through("TAIEX", 240), 240)


def _c2(view: IndexView) -> bool:
    return _above_ma(view.through(view.market_index(), 60), 60)


def _c3_basis(view: IndexView) -> bool:
    (tx,) = view.through("TX", 1)
    (taiex,) = view.through("TAIEX", 1)
    return tx - taiex >= 0.0


def _c3_ma20(view: IndexView) -> bool:
    return _above_ma(view.through("TX", 20), 20)


def _c4_sox(view: IndexView) -> bool:
    return _above_ma(view.before("SOX", 60), 60)


def _c4_spx(view: IndexView) -> bool:
    return _above_ma(view.before("SPX", 60), 60)


def _c5(view: IndexView) -> bool:
    closes = view.through("TAIEX", 240)
    return _above_ma(closes, 60) and _above_ma(closes, 240)


DRAWDOWN_LIMIT = 0.10


def _c6(view: IndexView) -> bool:
    closes = view.through("TAIEX", 60)
    return closes[-1] >= max(closes) * (1.0 - DRAWDOWN_LIMIT)


def _c7(view: IndexView) -> bool:
    return _above_ma(view.through(view.market_index(), 240), 240)


# C1～C5 are the Issue's candidates (C3／C4 each listed as two); C6／C7 are
# the engineer's (#567 範圍「工程師可再提最多兩種」).  Comparisons are strict
# except C3's basis (≥ 0) and C6's drawdown (≥ 90% of the high), as written.
CONDITIONS: dict[str, IndexCondition] = {
    item.code: item
    for item in (
        IndexCondition(
            "c1",
            "taiex_close_gt_ma240",
            "TAIEX 收盤 > MA240（年線）",
            "TAIEX 240",
            ("TAIEX",),
            _c1,
        ),
        IndexCondition(
            "c2",
            "own_market_index_close_gt_ma60",
            "所屬市場指數收盤 > MA60（上市看 TAIEX、上櫃看 TPEX）",
            "TAIEX or TPEX 60 (instruments.exchange)",
            ("TAIEX", "TPEX"),
            _c2,
            per_market=True,
            validation_independent=False,
            note_zh="上市股的 C2 就是 #546 的 R3（TAIEX > MA60），#546 看過全範圍。",
        ),
        IndexCondition(
            "c3a",
            "tx_near_month_close_minus_taiex_close_ge_0",
            "台指期近月收盤 − TAIEX 收盤 ≥ 0（正價差）",
            "TX 1, TAIEX 1",
            ("TX", "TAIEX"),
            _c3_basis,
        ),
        IndexCondition(
            "c3b",
            "tx_near_month_close_gt_tx_ma20",
            "台指期近月收盤 > 近月 MA20（跨換月不調整）",
            "TX 20",
            ("TX",),
            _c3_ma20,
        ),
        IndexCondition(
            "c4a",
            "sox_previous_us_close_gt_ma60",
            "前一美股交易日 SOX 收盤 > MA60",
            "SOX 60 (before the signal date)",
            ("SOX",),
            _c4_sox,
            note_zh="美股四檔依 #547 只顯示；採用要使用者另外推翻該規定。",
        ),
        IndexCondition(
            "c4b",
            "spx_previous_us_close_gt_ma60",
            "前一美股交易日 SPX 收盤 > MA60",
            "SPX 60 (before the signal date)",
            ("SPX",),
            _c4_spx,
            note_zh="美股四檔依 #547 只顯示；採用要使用者另外推翻該規定。",
        ),
        IndexCondition(
            "c5",
            "taiex_close_gt_ma60_and_gt_ma240",
            "TAIEX 收盤 > MA60 且 > MA240（R3＋C1）",
            "TAIEX 240",
            ("TAIEX",),
            _c5,
            validation_independent=False,
            note_zh="含 #546 的 R3，#546 看過全範圍。",
        ),
        IndexCondition(
            "c6",
            "taiex_close_ge_90pct_of_60_session_high",
            "TAIEX 收盤距近 60 日最高收盤回檔不超過 10%",
            "TAIEX 60",
            ("TAIEX",),
            _c6,
            validation_independent=False,
            note_zh="工程師提案：#546 的差距多半來自 2025Q1 大回檔，均線濾網落後，"
            "改看回檔深度。在讀過 #546 全範圍報告後提出，驗證段不算完全獨立。",
        ),
        IndexCondition(
            "c7",
            "own_market_index_close_gt_ma240",
            "所屬市場指數收盤 > MA240（上市看 TAIEX、上櫃看 TPEX）",
            "TAIEX or TPEX 240 (instruments.exchange)",
            ("TAIEX", "TPEX"),
            _c7,
            per_market=True,
            note_zh="工程師提案：把 C1 與 C2 的差別拆開，同樣看年線，只改成所屬市場的指數。",
        ),
    )
}


class IndexHistory:
    """Stored rows of the ``SERIES`` indexes, plus the score date and instrument being written.

    ``rows[key]`` maps a date to ``(close, contract_month)``; a series missing
    from ``rows`` has no rows (every condition on it is data_incomplete).
    """

    def __init__(
        self, rows: Mapping[str, Mapping[date, tuple[float | None, str | None]]]
    ):
        self._series: dict[
            str, tuple[list[date], list[float | None], list[str | None]]
        ] = {}
        for key in SERIES:
            by_day = rows.get(key) or {}
            dates = sorted(by_day)
            self._series[key] = (
                dates,
                [by_day[day][0] for day in dates],
                [by_day[day][1] for day in dates],
            )
        self.session: date | None = None
        self.exchange: str | None = None
        self.instrument_set = False
        self._views: dict[str | None, IndexView] = {}

    def series(
        self, key: str
    ) -> tuple[list[date], list[float | None], list[str | None]]:
        return self._series[key]

    def set_session(self, day: date | None) -> None:
        self.session = day
        self._views = {}

    def set_instrument(self, exchange: str | None, *, active: bool = True) -> None:
        self.exchange = exchange
        self.instrument_set = active

    def view(self) -> IndexView:
        if self.session is None or not self.instrument_set:
            raise RuntimeError(
                "index-condition strategy evaluated without a score date and "
                "instrument (IndexHistory.set_session／set_instrument); only a "
                "research backtest sets them"
            )
        return self.view_at(self.session, self.exchange)

    def view_at(self, day: date, exchange: str | None) -> IndexView:
        """The view of ``day`` and market ``exchange`` (memoized for the current score date)."""

        if day != self.session:
            return IndexView(self, day, exchange)
        if exchange not in self._views:
            self._views[exchange] = IndexView(self, day, exchange)
        return self._views[exchange]

    def states(
        self, code: str, days: Iterable[date], exchange: str | None = None
    ) -> dict[date, RuleEvaluation]:
        """The condition's result on each of ``days`` for market ``exchange`` (the report)."""

        return {day: IndexView(self, day, exchange).result(code) for day in days}

    def rolls(self) -> list[dict[str, Any]]:
        """Each TX roll: the last row of a contract and the next one's first, with TAIEX's closes."""

        dates, closes, months = self._series["TX"]
        taiex = dict(zip(self._series["TAIEX"][0], self._series["TAIEX"][1]))
        result = []
        for at in range(1, len(dates)):
            if months[at] and months[at - 1] and months[at] != months[at - 1]:
                before, after = dates[at - 1], dates[at]
                item = {
                    "last_day": before,
                    "last_month": months[at - 1],
                    "last_close": closes[at - 1],
                    "first_day": after,
                    "first_month": months[at],
                    "first_close": closes[at],
                }
                if (
                    _finite(taiex.get(before))
                    and _finite(taiex.get(after))
                    and _finite(closes[at - 1])
                    and _finite(closes[at])
                ):
                    old_basis = closes[at - 1] - taiex[before]
                    new_basis = closes[at] - taiex[after]
                    item |= {
                        "last_basis": old_basis,
                        "first_basis": new_basis,
                        "basis_jump": new_basis - old_basis,
                    }
                result.append(item)
        return result


def combine(result: RuleEvaluation, condition: RuleEvaluation) -> RuleEvaluation:
    """The strategy's ``result`` followed by an index condition's (module docstring)."""

    if condition.passed:
        return result
    if condition.state == "data_incomplete":
        own = result.reasons if result.state == "data_incomplete" else ()
        return RuleEvaluation(False, "data_incomplete", (*own, *condition.reasons))
    if result.state == "data_incomplete":
        return result
    return RuleEvaluation(False, "rejected", (*result.reasons, *condition.reasons))


def evaluate_with_condition(
    rule: Callable[..., RuleEvaluation],
    code: str,
    *,
    index_view: IndexView,
    **arguments: Any,
) -> RuleEvaluation:
    return combine(rule(**arguments), index_view.result(code))


def condition_strategy(strategy_key: str, code: str, history: IndexHistory) -> Strategy:
    """``BASES[strategy_key]`` plus the condition ``code``, under its own name and kind."""

    base = BASES[strategy_key]
    item = CONDITIONS[code]
    config: dict[str, Any] = copy.deepcopy(dict(base.config))
    config["name"] = f"{strategy_key}_index_{code}"
    config["kind"] = f"{base.kind}_index_{code}"
    config["index_condition"] = {
        "base_strategy": strategy_key,
        "base_version": base.version,
        "issue": 567,
        **item.snapshot(),
    }
    base_rule = base.rule

    def rule(**arguments: Any) -> RuleEvaluation:
        return evaluate_with_condition(base_rule, code, **arguments)

    def arguments(inputs: StrategyInputs) -> dict[str, Any]:
        return {**base.arguments(inputs), "index_view": history.view()}

    strategy = copy.copy(base)
    strategy.config = config
    strategy.rule = rule
    strategy.arguments = arguments
    return strategy


def with_conditions(
    registry: Mapping[str, Strategy],
    items: Iterable[tuple[str, str]],
    history: IndexHistory,
) -> dict[str, Strategy]:
    """``registry`` followed by the index-condition strategies ``items`` names."""

    result = dict(registry)
    problems = []
    for strategy_key, code in items:
        strategy = condition_strategy(strategy_key, code, history)
        if strategy.key in result:
            problems.append(f"{strategy.key} is already in the registry")
        result[strategy.key] = strategy
    problems += registry_problems(result)
    if problems or not result:
        raise ValueError("; ".join(problems) or "empty research registry")
    return result


def all_conditions() -> list[tuple[str, str]]:
    return [(strategy_key, code) for strategy_key in BASES for code in CONDITIONS]


# ---- the rule a condition passes to be proposed (fixed before any result) ----

# A segment's comparison of a condition version with its baseline counts only
# when the condition removed at least MIN_REMOVED actionable baseline signals
# (rejected on their signal date) and its version keeps at least MIN_T20
# usable T+20 returns; otherwise the segment cannot judge it.
MIN_REMOVED = 30
MIN_T20 = 100
SELECTION_RULE_ZH = (
    "探索段選出：條件濾掉的 baseline 可行動訊號 ≥ 30 筆、研究版本 T+20 可用報酬 ≥ 100 筆，"
    "且研究版本的 T+20 中位數高於 baseline、invalidated 比例低於 baseline。"
    "驗證段沒有反轉：同樣的樣本門檻下，T+20 中位數不低於 baseline、invalidated 比例不高於 baseline；"
    "門檻不足記「無法判定」，不算沒有反轉。提案只引用兩段都過的條件。"
)


@dataclass(frozen=True)
class Comparison:
    """One segment: a condition version against its baseline."""

    removed: int  # baseline actionable signals the condition rejected
    t20_n: int  # usable T+20 returns of the condition version
    t20_median: float | None
    baseline_t20_median: float | None
    invalidated_share: float | None
    baseline_invalidated_share: float | None

    @property
    def judgeable(self) -> bool:
        return (
            self.removed >= MIN_REMOVED
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
    """``selected``, ``not_selected`` or ``insufficient``."""

    if not item.judgeable:
        return "insufficient"
    better = (
        item.t20_median > item.baseline_t20_median
        and item.invalidated_share < item.baseline_invalidated_share
    )
    return "selected" if better else "not_selected"


def judge_validation(item: Comparison) -> str:
    """``not_reversed``, ``reversed`` or ``insufficient``."""

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
