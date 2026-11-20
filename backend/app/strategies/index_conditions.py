"""Research-only index conditions (#567): a registered strategy plus one condition on stored index bars.

An index-condition strategy is named ``<strategy>_index_<code>`` (kind
``<kind>_index_<code>``).  Its rule is the registered strategy's rule, called
exactly as a canonical run calls it, followed by one condition of
``ALL_CONDITIONS`` (#567's ``CONDITIONS`` and #855's ``OVERNIGHT_CONDITIONS``)
on the ``market_bars`` rows of the indexes in ``SERIES``:

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

The overnight conditions (#855, ``OVERNIGHT_CONDITIONS`` o1～o6) ask whether
the list of score date T should be acted on at E, the next Taiwan session:
they read the US row that closed between the list and E's open
(``IndexView.overnight_row``: the newest row dated in [T, E), never one dated
E or later; none in [T, E) is a US holiday and the condition holds).  E comes
from the Taiwan sessions given to ``IndexHistory`` (``worker.pipeline.
taiwan_bar_dates``).  Their bases are ``OVERNIGHT_BASES`` (``breakout_v3`` and
``pullback_v4``, the 08:45 list's), and their judgement is
``judge_improved``／``judge_edge`` (both fixed before any result), not
#567's.
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
from .pullback_v4 import PULLBACK_V4

# The versions #567 measured (run 2759); see the module docstring.
BASES: dict[str, Strategy] = {
    strategy.key: strategy for strategy in (BREAKOUT_V3, PULLBACK_V3)
}
# The overnight conditions' bases (#855 decision 7018301183): the strategies
# of the list 08:45 shows (candidate_score_v7), not #567's fixed v3 pair.
OVERNIGHT_BASES: dict[str, Strategy] = {
    strategy.key: strategy for strategy in (BREAKOUT_V3, PULLBACK_V4)
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
# The overnight conditions (#855): read the US row of [T, E), not before T.
OVERNIGHT_ISSUE = 855
OVERNIGHT_WINDOW = "newest_us_row_dated_from_signal_date_to_before_next_taiwan_session"
NEXT_SESSION_UNKNOWN = "next_session_unknown"


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
    issue: int = 567

    @property
    def reason(self) -> str:
        return f"index_condition_{self.code}_not_met"

    def snapshot(self) -> dict[str, Any]:
        if self.issue == OVERNIGHT_ISSUE:
            return {
                "condition": self.code,
                "definition": self.definition,
                "reads": self.reads,
                "series": list(self.series),
                "per_market": False,
                "price_field": "market_bars.close",
                "us_window": OVERNIGHT_WINDOW,
                "overnight_return": "close_of_newest_row_over_previous_stored_close_minus_1",
                "us_market_closed": "condition_holds",
                "us_stale_days": US_STALE_DAYS,
                "next_session": "worker.pipeline.taiwan_bar_dates",
                "missing_policy": "data_incomplete",
                "failed_reason": self.reason,
            }
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

    def overnight_row(self, key: str) -> dict[str, Any]:
        """The US row of ``key`` that closed between the list and the next session's open.

        E is the first Taiwan session after the score date T
        (``IndexHistory.next_session``).  The row is the newest one dated in
        [T, E): a US close of date D is in Taipei D + 1 before 09:00, so every
        row dated before E is known at E's open, and a row dated T − 1 or
        earlier had closed before T's list (21:30).  A row dated E or later is
        never read.  ``return`` is its close over the stored row before it,
        minus 1; ``rows`` counts the rows in [T, E) (more than one across a
        Taiwan holiday, the newest decides).  No row in [T, E) while a later
        row is stored: the US market was closed, ``date`` and ``return`` are
        None.  No row in [T, E) and none later: not collected yet
        (``us_<key>_overnight_pending``).
        """

        entry = self.history.next_session(self.session)
        dates, closes, _ = self.history.series(key)
        name = key.lower()
        low = bisect.bisect_left(dates, self.session)
        high = bisect.bisect_left(dates, entry)
        if high == low:
            if high < len(dates):
                return {"entry": entry, "date": None, "return": None, "rows": 0}
            raise _Incomplete(f"us_{name}_overnight_pending")
        at = high - 1
        if at == 0:
            raise _Incomplete(f"us_{name}_closes_insufficient")
        if (dates[at] - dates[at - 1]).days > US_STALE_DAYS:
            raise _Incomplete(f"us_{name}_bar_stale")
        previous, close = closes[at - 1], closes[at]
        if not all(_finite(value) and float(value) > 0 for value in (previous, close)):
            raise _Incomplete(f"us_{name}_close_missing_or_non_finite")
        return {
            "entry": entry,
            "date": dates[at],
            "previous_date": dates[at - 1],
            "return": float(close) / float(previous) - 1.0,
            "rows": high - low,
        }

    def market_index(self) -> str:
        key = MARKET_INDEX.get(self.exchange or "")
        if key is None:
            raise _Incomplete(MARKET_INDEX_UNKNOWN)
        return key

    def result(self, code: str) -> RuleEvaluation:
        """``ALL_CONDITIONS[code]`` on this view (memoized: every stock of a market shares it)."""

        if code not in self._results:
            item = ALL_CONDITIONS[code]
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


# ---- the overnight conditions (#855) ----
#
# Fixed before any result was read (#855 提問 7018248685, decision
# 7018301183): the score date T's list is not acted on at E (the next Taiwan
# session) when the US close of the night before E moved past a threshold.
# r is ``IndexView.overnight_row``'s return; a US market closed through
# [T, E) has no overnight close and the condition holds.  The bounds are
# inclusive on the side that rejects (r ≤ −2 % rejects, r ≥ +1 % rejects).


def _overnight(key: str, threshold: float, rejects_at_or_below: bool):
    def holds(view: IndexView) -> bool:
        value = view.overnight_row(key)["return"]
        if value is None:
            return True
        return value > threshold if rejects_at_or_below else value < threshold

    return holds


def _overnight_condition(
    code: str, key: str, threshold: float, below: bool
) -> IndexCondition:
    side = "gt" if below else "lt"
    bound = f"{'m' if threshold < 0 else 'p'}{abs(threshold) * 100:g}pct"
    label = "−" if threshold < 0 else "+"
    held = (
        f"> {label}{abs(threshold) * 100:g}%"
        if below
        else f"< {label}{abs(threshold) * 100:g}%"
    )
    return IndexCondition(
        code,
        f"{key.lower()}_overnight_return_{side}_{bound}",
        f"隔夜 {key} 漲跌 {held}（不成立：T+1 不進場）",
        f"{key} newest row in [T, E) and the row before it",
        (key,),
        _overnight(key, threshold, below),
        note_zh="美股依 #547 只顯示；採用要使用者另外決定。",
        issue=OVERNIGHT_ISSUE,
    )


OVERNIGHT_THRESHOLDS: tuple[tuple[str, str, float, bool], ...] = (
    ("o1", "SOX", -0.02, True),
    ("o2", "SOX", -0.01, True),
    ("o3", "SOX", 0.01, False),
    ("o4", "SPX", -0.02, True),
    ("o5", "SPX", -0.01, True),
    ("o6", "SPX", 0.01, False),
)
OVERNIGHT_CONDITIONS: dict[str, IndexCondition] = {
    code: _overnight_condition(code, key, threshold, below)
    for code, key, threshold, below in OVERNIGHT_THRESHOLDS
}
ALL_CONDITIONS: dict[str, IndexCondition] = {**CONDITIONS, **OVERNIGHT_CONDITIONS}


def bases_of(code: str) -> dict[str, Strategy]:
    """The base strategies a condition is measured on (#567's or #855's)."""

    return OVERNIGHT_BASES if code in OVERNIGHT_CONDITIONS else BASES


class IndexHistory:
    """Stored rows of the ``SERIES`` indexes, plus the score date and instrument being written.

    ``rows[key]`` maps a date to ``(close, contract_month)``; a series missing
    from ``rows`` has no rows (every condition on it is data_incomplete).
    ``sessions`` are the Taiwan sessions (``worker.pipeline.taiwan_bar_dates``)
    that give an overnight condition its E (``next_session``); #567's
    conditions do not read them, and without them an overnight condition
    raises instead of guessing E.
    """

    def __init__(
        self,
        rows: Mapping[str, Mapping[date, tuple[float | None, str | None]]],
        sessions: Iterable[date] | None = None,
    ):
        # The Taiwan sessions (``worker.pipeline.taiwan_bar_dates``): E of the
        # overnight conditions.  None: an overnight condition raises.
        self.sessions = None if sessions is None else sorted(set(sessions))
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

    def next_session(self, day: date) -> date:
        """E: the first Taiwan session after ``day`` (``next_session_unknown`` after the last)."""

        if self.sessions is None:
            raise RuntimeError(
                "an overnight condition needs the Taiwan sessions "
                "(IndexHistory(rows, sessions=worker.pipeline.taiwan_bar_dates))"
            )
        at = bisect.bisect_right(self.sessions, day)
        if at == len(self.sessions):
            raise _Incomplete(NEXT_SESSION_UNKNOWN)
        return self.sessions[at]

    def overnight_rows(
        self, key: str, days: Iterable[date]
    ) -> dict[date, dict[str, Any]]:
        """``IndexView.overnight_row`` of each of ``days`` (the report); missing: its reason."""

        result = {}
        for day in days:
            try:
                result[day] = IndexView(self, day, None).overnight_row(key)
            except _Incomplete as missing:
                result[day] = {"missing": missing.reason}
        return result

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
    """``bases_of(code)[strategy_key]`` plus the condition ``code``, under its own name and kind."""

    base = bases_of(code)[strategy_key]
    item = ALL_CONDITIONS[code]
    config: dict[str, Any] = copy.deepcopy(dict(base.config))
    config["name"] = f"{strategy_key}_index_{code}"
    config["kind"] = f"{base.kind}_index_{code}"
    config["index_condition"] = {
        "base_strategy": strategy_key,
        "base_version": base.version,
        "issue": item.issue,
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


def overnight_conditions() -> list[tuple[str, str]]:
    """The 12 groups of #855: each overnight condition on each of its bases."""

    return [
        (strategy_key, code)
        for strategy_key in OVERNIGHT_BASES
        for code in OVERNIGHT_CONDITIONS
    ]


def baselines_of(items: Iterable[tuple[str, str]]) -> dict[str, Strategy]:
    """The bases a run of the condition strategies ``items`` replays.

    #567's conditions: ``BASES`` (both, as run 2759); #855's overnight ones:
    ``OVERNIGHT_BASES``.  A run takes one or the other: mixing them puts
    ``pullback_v3`` and ``pullback_v4`` (one kind) in one registry, which
    ``registry_problems`` refuses (exit 2), so this does not pick between
    them.
    """

    chosen = list(items)
    result: dict[str, Strategy] = {}
    if any(code in CONDITIONS for _, code in chosen):
        result |= BASES
    if any(code in OVERNIGHT_CONDITIONS for _, code in chosen):
        result |= OVERNIGHT_BASES
    return result


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


# ---- #855: the overnight conditions' two judgements (fixed before any result) ----
#
# 提問 7018248685 §4 and decision 7018301183 §3.  Per strategy × condition ×
# segment, the condition version against its baseline:
#
# (a) the mean T+20 simulated return of the run's tracking (net of its 30 bps
#     round trip, ``app.tracking``); (b) the mean of each signal's (a) less
#     the same signal date's population mean (evidence.md 共同口徑: T+1 open
#     with 5 bps to T+20 close, less the same 30 bps).
# - improved: judgeable, and the version's (a) and (b) both strictly above the
#   baseline's;
# - edge: improved, and the version's (a) at the 共同口徑 58.5 bps round trip
#   and its (b) both above 0.
# Both segments must pass.  Short of the sample floor a segment cannot judge
# (``insufficient``), which is not a pass.

OVERNIGHT_MIN_REMOVED = 30
OVERNIGHT_MIN_REMOVED_DAYS = 5
OVERNIGHT_MIN_T20 = 100
TRACKING_COST = 0.003
COMMON_COST = 0.00585
OVERNIGHT_RULE_ZH = (
    "改善：條件濾掉的 baseline 可行動訊號 ≥ 30 筆、分布在 ≥ 5 個訊號日，研究版本 T+20 可用報酬 ≥ 100 筆，"
    "且研究版本的 (a) 扣成本 T+20 模擬報酬平均與 (b) 對母體超額平均都嚴格高於 baseline。"
    "有優勢：先符合改善，且研究版本的 (a)（改扣共同口徑來回 58.5 bps）與 (b) 都 > 0。"
    "探索段與驗證段都要過；門檻不足記「無法判定」，不算通過。"
)


@dataclass(frozen=True)
class OvernightComparison:
    """One segment of #855: a condition version against its baseline."""

    removed: int  # baseline actionable signals the condition rejected
    removed_days: int  # their distinct signal dates
    t20_n: int  # usable T+20 returns of the condition version
    net_mean: float | None  # (a) of the version, tracking's 30 bps
    baseline_net_mean: float | None
    excess_mean: float | None  # (b) of the version
    baseline_excess_mean: float | None

    @property
    def common_net_mean(self) -> float | None:
        """(a) at the 共同口徑 round trip (58.5 bps) instead of tracking's 30 bps."""

        if self.net_mean is None:
            return None
        return self.net_mean + TRACKING_COST - COMMON_COST

    @property
    def judgeable(self) -> bool:
        return (
            self.removed >= OVERNIGHT_MIN_REMOVED
            and self.removed_days >= OVERNIGHT_MIN_REMOVED_DAYS
            and self.t20_n >= OVERNIGHT_MIN_T20
            and None
            not in (
                self.net_mean,
                self.baseline_net_mean,
                self.excess_mean,
                self.baseline_excess_mean,
            )
        )


def judge_improved(item: OvernightComparison) -> str:
    """``improved``, ``not_improved`` or ``insufficient``."""

    if not item.judgeable:
        return "insufficient"
    better = (
        item.net_mean > item.baseline_net_mean
        and item.excess_mean > item.baseline_excess_mean
    )
    return "improved" if better else "not_improved"


def judge_edge(item: OvernightComparison) -> str:
    """``edge``, ``no_edge`` or ``insufficient`` (improved, and (a) at 58.5 bps and (b) > 0)."""

    verdict = judge_improved(item)
    if verdict != "improved":
        return "insufficient" if verdict == "insufficient" else "no_edge"
    return "edge" if item.common_net_mean > 0 and item.excess_mean > 0 else "no_edge"


def overnight_verdict(
    exploration: OvernightComparison, validation: OvernightComparison
) -> dict[str, bool]:
    """Both segments: ``improved`` and ``edge``."""

    return {
        "improved": judge_improved(exploration) == "improved"
        and judge_improved(validation) == "improved",
        "edge": judge_edge(exploration) == "edge" and judge_edge(validation) == "edge",
    }
