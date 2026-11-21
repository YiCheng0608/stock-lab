"""Round 10 of the new-strategy exploration: F1～F4 (#936).

docs/spec/evidence.md 第十輪：F1～F4 and 第十輪實作釋義: the hypotheses were
registered (commit ``e495fa70``, #932, decision 7057685033) before anyone ran a
tool on the backfilled history.  Nothing here is a command-line option: a
change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round9_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  F2 and F3 trade on the portfolio engine
(``portfolio_research.simulate``) with the population, the loading
(``explore_research.load_context``), ``explore_judge``, the order
(``round5_research.order_key``), ``cash_yield_12m``
(``round5_research.cash_yield_parts``), the gate and the ledgers imported; F1
and F4 are judged trade by trade with ``trade_research``'s trades
(``TradeBars``, ``settle``, ``baseline``, ``stats``, the occupancy of
``State``) and ``round9_research``'s exit without a stop or a target
(``enter_next_open``, ``NO_STOP``, ``trade_context``).  New here are only
``stock_div_ex``, ``vol_720``, ``mom_240_20``, F2's composite order,
``drawdown_60``, ``margin_drop_5``, ``margin_first`` and F2's overlap with H2.

Each signal date T (after its close, only T's data and before):

- F1: every member of the population (less the occupied ones) with a
  ``corporate_actions`` row on T (an ``action_date`` that is no session
  counts on the next one) whose ``stock_dividend_ratio`` ≥ 0.05 (the largest
  of the day's rows; null does not qualify).  Bought at T+1's open (one
  session; not tradable or locked at limit up abandons it), sold at the close
  of the 60th session counting the fill as the 1st.
- F2: the ⌈n ÷ 2⌉ members with the smallest ``vol_720`` (n: the members with
  one), ranked there on ``cash_yield_12m`` and ``mom_240_20`` (high first, a
  missing one ranks as the half's size); the mean of the two ranks small
  first.  N 20, K 60.  Its daily list's overlap with X2 (H2) is listed only.
- F3: ``drawdown_60`` ≤ −0.22 and ``margin_drop_5`` ≤ −0.10 (compared as
  fractions: exactly −0.22 qualifies), ``margin_drop_5`` small first; fewer
  than 20 leave cash.  N 20, K 20.
- F4: every member (less the occupied ones) first on its exchange's margin
  list on T (never on any earlier list of the exchange since the
  instrument's first bar) with ≥ 20 bars before T; without T's or the
  previous session's list the exchange makes no signal that day (counted).
  Held 20 sessions as F1.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.234 (41 hypotheses) on the validation; F1 and F4
also need 60 signal dates with a fill (``trade_research.MIN_DAYS``).  Before
the used segment is loaded the validation's panel is let go (PR #905 review).
``--coverage-only`` writes counts of dates, members and missing values per
year and the time of the features, no return at all.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import statistics
import sys
import time
from array import array
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round9_research as r9  # noqa: E402
import trade_research as tr  # noqa: E402

VERSION = 1
DESIGN = "936"
TOOL = "round10_research"
REGISTRATION_COMMIT = "e495fa70"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/932#issuecomment-7057685033"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十輪 門檻: 1 − Φ(z) = 0.025 ÷ 41, z = 3.2343, 3.234 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.234
ROUND = 10
ROUND_SIZE = 4
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3, F1～F4
CUMULATIVE = 41
MIN_DAYS = tr.MIN_DAYS  # F1, F4: signal dates with a fill, per segment
OVERLAP = tr.OVERLAP
# Every segment reads the copy from its start (as round6_research): F2's
# vol_720 needs 721 bars, more than the 730 calendar days of warm-up
# explore_research gives a later segment (PR #939 review 7059380651).
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO, TRADE = "portfolio", "trade"
HIGH, LOW = r5.HIGH, r5.LOW

STOCK_DIV_MIN = 0.05  # F1: stock_dividend_ratio ≥ 0.05 (50 shares per 1,000)
VOL_WINDOW = 720  # F2: returns, of 721 adjusted closes
VOL_DDOF = 1
LOW_VOL_SHARE = Fraction(1, 2)  # F2: the low-volatility half, ⌈n × 1/2⌉
RANK_WEIGHTS = (1, 1)  # F2: (r1 + r2) ÷ 2, the two ranks equally weighted
MOM_FAR, MOM_NEAR = 240, 20  # F2: c[at − 20] ÷ c[at − 240] − 1
DRAWDOWN_WINDOW = 60  # F3: c[at] ÷ max(c[at − 59] … c[at]) − 1
DRAWDOWN_MAX = -0.22
MARGIN_LAG = 5  # F3: m[at] ÷ m[at − 5] − 1
MARGIN_DROP_MAX = -0.10
MIN_BARS = 20  # F4: bars of the instrument before T
NEAR = 1e-9  # F3: a float this close to a threshold is compared as fractions
# F1 and F4's exit has no stop and no target (round9_research's B2 exit).
NO_STOP = r9.NO_STOP
OTC_ANCHOR = r5.OTC_ANCHOR
MARKETS = {"TWSE": "上市", "TPEx": "上櫃"}
X2 = "X2"  # F2 第 6 點: explore_research 第 2 版的 HYPOTHESES["X2"] (H2)

# The registration (docs 第十輪：F1～F4), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first.  ``keys``: (feature,
# HIGH or LOW), a missing value last, ties by ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "F1": {
        "engine": TRADE,
        "kind": "event",  # trade_research._trade_row: hold counts from the fill
        "event": "stock_div_ex",
        "direction": "事件：配股除權",
        "label": "T 日是除權交易日、配股率 `stock_dividend_ratio` ≥ 0.05（`stock_div_ex`），"
        "全部符合的訊號；T+1 開盤成交（期限 1 日）、沒有停損與目標、持有 60 日",
        "market_filter": False,
        "entry_days": 1,
        "stop": None,
        "target": None,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 20),
    },
    "F2": {
        "engine": PORTFOLIO,
        "direction": "多因子合成",
        "label": "保守公式：`vol_720` 較小的一半裡，`cash_yield_12m` 與 `mom_240_20` "
        "的平均名次小者先",
        "rule": "daily",
        "half": ("vol_720", LOW),
        "ranks": (("cash_yield_12m", HIGH), ("mom_240_20", HIGH)),
        "score": LOW,  # the mean rank, small first
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 721),
    },
    "F3": {
        "engine": PORTFOLIO,
        "direction": "散戶槓桿：斷頭賣壓",
        "label": "`drawdown_60` ≤ −0.22 且 `margin_drop_5` ≤ −0.10，依 `margin_drop_5` 小者先",
        "rule": "daily",
        "conditions": ("drawdown_60", "margin_drop_5"),  # each <= its threshold
        "keys": (("margin_drop_5", LOW),),
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 60),
    },
    "F4": {
        "engine": TRADE,
        "kind": "event",
        "event": "margin_first",
        "direction": "事件：第一次成為融資標的",
        "label": "第一次出現在融資融券名單上（`margin_first`），全部符合的訊號；"
        "T+1 開盤成交（期限 1 日）、沒有停損與目標、持有 20 日",
        "market_filter": False,
        "entry_days": 1,
        "stop": None,
        "target": None,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 20),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(tr.REASONS)  # explore_research's and too_few_trade_days
VOLATILE_KEYS = ex.VOLATILE_KEYS
LIMITS = {
    "F1": "2009 年員工分紅費用化、2012 年後配股的公司變少，訊號集中在探索段前半；"
    "驗證段有成交的訊號日若 < 60，照判定記「無法判定」，不改門檻；"
    "DB 沒有股利的董事會決議日，配股在除權日之前已公開好幾個月，T 用除權日，"
    "測的是除權之後的延續，不是宣告效果；除權集中在 7～9 月；"
    "逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線",
    "F2": "原文的「淨發放殖利率」含庫藏股買回並扣掉增資，DB 沒有歷史發行股數，只用現金股利；"
    "原文的母體是市值前 1,000 大，這裡沿用共同口徑母體，沒有市值；"
    "12-1 動能和 X2（H2）的 `high_gap_240` 相關，F2 的結果會沾到 H2，看和 H2 名單的重疊比例",
    "F3": "上櫃股融資成數 50% 時追繳線約在 −35%，主管機關也會調整個股成數，"
    "DB 沒有各股成數，一律用 −0.22；融資減少也可能是自願賣出或現金償還，"
    "DB 分不出是不是斷頭；條件不成立的日子留現金，平均投入比例偏低，是登記時事先定的規則",
    "F4": "成為融資標的的同時也開放融券，DB 分不出兩者各自的效果；"
    "方向依台股信用交易的使用者結構事先定為買進，不比較另一邊；"
    "逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線",
}
# The degenerate cases as the code judges them (第十輪實作釋義; PR #913 review:
# the docs, coverage.md and summary.md say the same words, a test reads the
# docs' tool section for them).
DEGENERATE = {
    "F1": "`stock_dividend_ratio` 是 null 的列視為不符合；同一檔同一天有多列時取配股率最大的那一列；"
    "`action_date` 不是交易日時，T 取之後第一個交易日",
    "F2": "`vol_720` 在 at − 720 … at 共 721 根中任一根停牌、收盤缺值或 ≤ 0，"
    "或不足 721 根時缺值，缺值不進低波動半；"
    "`cash_yield_12m` 或 `mom_240_20` 缺值時那一項名次是低波動半的檔數",
    "F3": "at < 5、at 或 at − 5 沒有籌碼列、`margin_balance` 是 null，或 m[at − 5] ≤ 0 時 "
    "`margin_drop_5` 缺值；不足 60 根，或 60 根中任一根收盤缺值或 ≤ 0 時 `drawdown_60` 缺值；"
    "任一個缺值，條件不符合",
    "F4": "T 或前一個交易日，這一檔交易所在 `margin_lists` 沒有那天的列時，"
    "那天這個交易所不產生訊號，天數另列",
}
ABANDON_LABELS = r9.ABANDON_LABELS
FEATURE_LABELS = {
    "stock_div_ex": "配股除權",
    "vol_720": "720 日報酬標準差",
    "mom_240_20": "12-1 月動能",
    "cash_yield_12m": "近 12 個月現金殖利率",
    "drawdown_60": "距 60 日最高收盤",
    "margin_drop_5": "融資 5 根變化",
    "margin_first": "第一次成為融資標的",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "stock_div_ex": {
                "value": "a corporate_actions row of the instrument on T (an "
                "action_date that is no market session counts on the next one) "
                "with stock_dividend_ratio >= STOCK_DIV_MIN",
                "min": STOCK_DIV_MIN,
                "rows": "the largest stock_dividend_ratio of the day's rows",
                "missing": "a null stock_dividend_ratio does not qualify",
            },
            "vol_720": {
                "value": "sample standard deviation of the VOL_WINDOW returns "
                "c[k] / c[k-1] - 1, k = at-VOL_WINDOW+1 .. at (adjusted closes)",
                "window": VOL_WINDOW,
                "ddof": VOL_DDOF,
                "missing": "fewer bars; a suspended bar, a close missing or <= 0 "
                "among at-VOL_WINDOW .. at",
            },
            "mom_240_20": {
                "value": "c[at-near] / c[at-far] - 1 (adjusted closes)",
                "far": MOM_FAR,
                "near": MOM_NEAR,
                "missing": "either end suspended, missing or <= 0",
            },
            "cash_yield_12m": {
                "value": "round5_research.cash_yield_parts",
                "calendar_days": r5.YIELD_CALENDAR_DAYS,
                "round5_research": [r5.VERSION, r5.DESIGN],
            },
            "composite": {
                "half": "the ceil(n * share) members with the smallest vol_720 "
                "(n: members with vol_720), ties by the hash",
                "share": str(LOW_VOL_SHARE),
                "ranks": "1 .. in the half by each key, ties by the hash; a missing "
                "value ranks as the half's size",
                "weights": list(RANK_WEIGHTS),
                "score": "sum(weight * rank) / sum(weight), ties by the hash",
            },
            "drawdown_60": {
                "value": "c[at] / max(c[at-window+1] .. c[at]) - 1 (adjusted closes)",
                "window": DRAWDOWN_WINDOW,
                "max": DRAWDOWN_MAX,
                "missing": "a close missing or <= 0 in the window, or fewer bars",
            },
            "margin_drop_5": {
                "value": "m[at] / m[at-lag] - 1, m the chip row's margin_balance",
                "lag": MARGIN_LAG,
                "max": MARGIN_DROP_MAX,
                "missing": "no chip row or a null margin_balance on at or at-lag; "
                "m[at-lag] <= 0",
            },
            "conditions": {
                "rule": "each <= its threshold; within near of it compared as "
                "the fractions of the two floats (exactly the threshold "
                "qualifies); a missing value does not qualify",
                "near": NEAR,
            },
            "margin_first": {
                "value": "on T's list of the instrument's exchange; its first run on "
                "that exchange's lists since its first bar starts on T, not on the "
                "exchange's first list; >= MIN_BARS bars before T",
                "min_bars": MIN_BARS,
                "missing": "no list of the exchange on T or on the session before: "
                "no signal of that exchange that day, the days listed",
            },
        },
        "markets": sorted(MARKETS),  # F4: the exchanges whose lists make signals
        "event_exit": {
            "entry": "T+1 open, one session; not tradable or locked at limit up "
            "abandons (round9_research.enter_next_open)",
            "stop": "none (settle with NO_STOP)",
            "no_stop": str(NO_STOP),
            "target": "none",
            "hold": "the hold-th market session counting the fill as the 1st; "
            "trade_research.settle's delays, delisting and segment end",
            "trade_research": [tr.VERSION, tr.DESIGN],
            "round9_research": [r9.VERSION, r9.DESIGN],
        },
        "limit": [
            str(er.LIMIT_BEFORE_WIDENING),
            str(er.LIMIT_WIDENED_ON),
            str(er.LIMIT),
        ],  # exit_research.daily_limit by the bar's date (#922)
        "order": "missing last; ties sha256(<T>:<instrument_id>)",
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "validation_min_t": VALIDATION_MIN_T,
        "min_days": MIN_DAYS,
        "overlap": OVERLAP,
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX, tr.SLIPPAGE, tr.COST_BPS],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
        "load": LOAD_RULE,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definitions, the
    thresholds, the windows, the exchanges, the orders, the composite rule,
    the segments, the costs).  A changed tool needs a new exploration report
    before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass
class MarginRuns:
    """The stored ``margin_lists`` from their first day to the window's end:
    which (exchange, day) have a list, each exchange's first list day, and
    for every (exchange, symbol) the runs of consecutive lists it is on
    (first and last list day of each run)."""

    present: set[tuple[str, date]] = field(default_factory=set)
    first_day: dict[str, date] = field(default_factory=dict)
    runs: dict[tuple[str, str], list[tuple[date, date]]] = field(default_factory=dict)

    def has(self, exchange: str, day: date | None) -> bool:
        return day is not None and (exchange, day) in self.present


def read_margin_runs(db: Path, end: date) -> MarginRuns:
    """Every list to ``end`` (from the first one: 第 1 點「從名單的第一天起」)."""

    out = MarginRuns()
    con = lib.connect_read_only(db)
    try:
        opened: dict[str, dict[str, date]] = defaultdict(dict)
        previous: dict[str, date] = {}
        for exchange, day, text in con.execute(
            "select exchange, trading_date, members_json from margin_lists "
            "where trading_date <= ? order by exchange, trading_date",
            (end.isoformat(),),
        ):
            day = date.fromisoformat(day)
            members = json.loads(text) if text else {}
            symbols = set(members or {})
            out.present.add((exchange, day))
            out.first_day.setdefault(exchange, day)
            mine = opened[exchange]
            for symbol in [s for s in mine if s not in symbols]:
                start = mine.pop(symbol)
                out.runs.setdefault((exchange, symbol), []).append(
                    (start, previous[exchange])
                )
            for symbol in symbols:
                mine.setdefault(symbol, day)
            previous[exchange] = day
        for exchange, mine in opened.items():
            for symbol, start in mine.items():
                out.runs.setdefault((exchange, symbol), []).append(
                    (start, previous[exchange])
                )
    finally:
        con.close()
    for runs in out.runs.values():
        runs.sort()
    return out


def first_bars(db: Path, ids) -> dict[int, date]:
    """Each instrument's first bar in the copy (a date only, no price): the
    lists before it belong to another company with the same symbol."""

    wanted = set(ids)
    con = lib.connect_read_only(db)
    try:
        return {
            instrument_id: date.fromisoformat(day)
            for instrument_id, day in con.execute(
                "select instrument_id, min(trading_date) from market_bars "
                "group by instrument_id"
            )
            if instrument_id in wanted
        }
    finally:
        con.close()


@dataclass
class Context:
    """``explore_research``'s context (the market, the quotes), the trade
    context on the same market (F1, F4), the actions (``round5_research``'s
    for ``cash_yield_12m``, F1's stock dividends by session), the margin list
    runs and each instrument's first bar.  One panel."""

    base: ex.Context
    trade: tr.Context
    yields: r5.Context
    # instrument -> session index of T -> the largest stock_dividend_ratio of
    # the day's rows (None: only null ratios)
    stock_div: dict[int, dict[int, float | None]] = field(default_factory=dict)
    lists: MarginRuns = field(default_factory=MarginRuns)
    life_start: dict[int, date] = field(default_factory=dict)
    # (instrument, session index) with a row whose three fields are all null
    # (the coverage lists them apart from the cash-only rows)
    blank: set[tuple[int, int]] = field(default_factory=set)
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # per instrument: prefix sums of the returns and their squares, and of the
    # bad closes (missing or <= 0), built when first asked
    prefix: dict[int, tuple[array, array, array]] = field(default_factory=dict)
    entries: dict[int, date | None] = field(default_factory=dict)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def stock_dividends(
    sessions: list[date], holders: dict[int, Any]
) -> dict[int, dict[int, float | None]]:
    out: dict[int, dict[int, float | None]] = {}
    for instrument_id, holder in holders.items():
        for action in holder.actions:
            s = bisect_left(sessions, action.action_date)  # not a session: the next
            if s >= len(sessions):
                continue
            days = out.setdefault(instrument_id, {})
            ratio = action.stock_dividend_ratio
            ratio = None if ratio is None else float(ratio)
            old = days.get(s)
            if s not in days or (ratio is not None and (old is None or ratio > old)):
                days[s] = ratio
    return out


def blank_actions(
    sessions: list[date], holders: dict[int, Any]
) -> set[tuple[int, int]]:
    """(instrument, T) of the rows with all three fields null
    (``round5_research.row_cash`` is None): listed by the coverage apart from
    the cash-only rows, whose ratio is null too.  Neither qualifies."""

    out = set()
    for instrument_id, holder in holders.items():
        for action in holder.actions:
            s = bisect_left(sessions, action.action_date)
            if s < len(sessions) and r5.row_cash(action) is None:
                out.add((instrument_id, s))
    return out


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the trade context, the actions and the margin lists to
    ``end``; nothing after ``end`` is read but the date of a delisted or
    transferred stock's last bar (no price)."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    trade = r9.trade_context(base.market, db, end)
    t0 = time.monotonic()
    report = lib.research_report()
    holders = {
        instrument_id: report.Instrument() for instrument_id in base.market.panel.series
    }
    report.load_actions(db, holders, start, raw_dir, end)
    yields = r5.Context(
        base,
        actions={
            instrument_id: r5.actions_of(holder.actions)
            for instrument_id, holder in holders.items()
            if holder.actions
        },
    )
    stock_div = stock_dividends(base.market.panel.sessions, holders)
    blank = blank_actions(base.market.panel.sessions, holders)
    del holders
    actions_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    lists = read_margin_runs(db, end)
    life_start = first_bars(db, base.market.panel.series)
    return Context(
        base,
        trade,
        yields,
        stock_div,
        lists,
        life_start,
        blank,
        load_seconds={
            "panel": panel_seconds,
            "actions": actions_seconds,
            "margin_lists": time.monotonic() - t0,
        },
    )


# --- features ---------------------------------------------------------------------


def stock_div_ex(ctx: Context, item: lib.Series, s: int) -> bool | None:
    """F1 第 1、2 點: a row on T with a ratio ≥ 0.05 (True), below (False);
    None when T's rows all have a null ratio (does not qualify); False
    without a row."""

    days = ctx.stock_div.get(item.instrument_id)
    if not days or s not in days:
        return False
    ratio = days[s]
    if ratio is None:
        return None
    return ratio >= STOCK_DIV_MIN


def _prefix(ctx: Context, item: lib.Series) -> tuple[array, array, array]:
    parts = ctx.prefix.get(item.instrument_id)
    if parts is None:
        closes = item.close
        s1, s2, bad = array("d", [0.0]), array("d", [0.0]), array("i", [0])
        a1 = a2 = 0.0
        nbad = 0
        for k, close in enumerate(closes):
            good = close > 0  # NaN fails too
            nbad += not good
            bad.append(nbad)
            r = 0.0
            if k and good and closes[k - 1] > 0:
                r = close / closes[k - 1] - 1.0
            a1 += r
            a2 += r * r
            s1.append(a1)
            s2.append(a2)
        parts = (s1, s2, bad)
        ctx.prefix[item.instrument_id] = parts
    return parts


def vol_720(ctx: Context, item: lib.Series, at: int) -> float | None:
    """F2 第 1 點: the sample standard deviation (ddof 1) of the 720 returns
    of the 721 adjusted closes at − 720 … at; missing with fewer bars, a
    suspended bar, a close missing or ≤ 0 among them (the 721 bars, as V1's
    ``vol_60``: a suspended bar's close would make a stale return)."""

    n = VOL_WINDOW
    first = at - n
    if first < 0:
        return None
    if item.suspended[at + 1] != item.suspended[first]:
        return None
    s1, s2, bad = _prefix(ctx, item)
    if bad[at + 1] != bad[first]:
        return None
    total = s1[at + 1] - s1[first + 1]  # the returns of first + 1 .. at
    squares = s2[at + 1] - s2[first + 1]
    variance = (squares - total * total / n) / (n - VOL_DDOF)
    return math.sqrt(max(variance, 0.0))


def mom_240_20(item: lib.Series, at: int) -> float | None:
    """F2 第 2 點: c[at − 20] ÷ c[at − 240] − 1; missing when either end is
    suspended, missing or ≤ 0."""

    far, near = at - MOM_FAR, at - MOM_NEAR
    if far < 0 or item.is_suspended(far) or item.is_suspended(near):
        return None
    a, b = item.close[far], item.close[near]
    if not (a > 0 and b > 0):
        return None
    return b / a - 1.0


def drawdown_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """F3 第 1 點: c[at] ÷ max(c[at − 59] … c[at]) − 1; missing with fewer
    bars or a close missing or ≤ 0 among the 60."""

    first = at - DRAWDOWN_WINDOW + 1
    if first < 0:
        return None
    _s1, _s2, bad = _prefix(ctx, item)
    if bad[at + 1] != bad[first]:
        return None
    return item.close[at] / max(item.close[first : at + 1]) - 1.0


def drawdown_parts(item: lib.Series, at: int) -> tuple[float, float]:
    first = at - DRAWDOWN_WINDOW + 1
    return item.close[at], max(item.close[first : at + 1])


def margin_parts(item: lib.Series, at: int) -> tuple[float, float] | None:
    margins = item.chips.get("margin_balance")
    if margins is None or at < MARGIN_LAG:
        return None
    now, before = margins[at], margins[at - MARGIN_LAG]
    if now != now or before != before or not before > 0:
        return None
    return now, before


def margin_drop_5(item: lib.Series, at: int) -> float | None:
    """F3 第 2 點: m[at] ÷ m[at − 5] − 1; missing without a chip row or with a
    null ``margin_balance`` on at or at − 5, or m[at − 5] ≤ 0."""

    parts = margin_parts(item, at)
    if parts is None:
        return None
    return parts[0] / parts[1] - 1.0


def at_most(value: float, num: float, den: float, bound: float) -> bool:
    """num ÷ den − 1 ≤ bound, exactly: the float when it is clearly apart,
    the fractions of the two floats when it is within ``NEAR``."""

    if value < bound - NEAR:
        return True
    if value > bound + NEAR:
        return False
    return Fraction(num) <= (1 + Fraction(str(bound))) * Fraction(den)


def f3_qualifies(
    ctx: Context, item: lib.Series, at: int
) -> tuple[bool, float | None, float | None]:
    """(qualifies, drawdown_60, margin_drop_5)."""

    dd = drawdown_60(ctx, item, at)
    md = margin_drop_5(item, at)
    if dd is None or md is None:
        return False, dd, md
    close, top = drawdown_parts(item, at)
    now, before = margin_parts(item, at)
    ok = at_most(dd, close, top, DRAWDOWN_MAX) and at_most(
        md, now, before, MARGIN_DROP_MAX
    )
    return ok, dd, md


def first_entry(ctx: Context, item: lib.Series) -> date | None:
    """The first list day of the instrument's first run on its exchange's
    lists since its first bar, or None (never on one, on the list before its
    first bar, or on the exchange's first list).  A run starting on the first
    bar counts, with 0 bars before it (no signal: fewer than ``MIN_BARS``)."""

    instrument_id = item.instrument_id
    if instrument_id in ctx.entries:
        return ctx.entries[instrument_id]
    exchange, symbol, _ = ctx.panel.symbols.get(instrument_id, ("", "", ""))
    life = ctx.life_start.get(instrument_id) or (item.dates[0] if item.dates else None)
    out = None
    if life is not None:
        for start, end in ctx.lists.runs.get((exchange, symbol), ()):
            if end < life:
                continue  # another company's, before this instrument's first bar
            if start >= life and start != ctx.lists.first_day.get(exchange):
                out = start
            break
    ctx.entries[instrument_id] = out
    return out


def margin_first(ctx: Context, item: lib.Series, s: int, at: int) -> bool | None:
    """F4 第 1、2 點: None without T's or the previous session's list of the
    instrument's exchange."""

    panel = ctx.panel
    exchange = panel.symbols.get(item.instrument_id, ("", "", ""))[0]
    day = panel.sessions[s]
    before = panel.sessions[s - 1] if s > 0 else None
    if not ctx.lists.has(exchange, day) or not ctx.lists.has(exchange, before):
        return None
    return first_entry(ctx, item) == day and at >= MIN_BARS


# --- F2 and F3: the portfolio engine ----------------------------------------------


order_key = r5.order_key
_window_facts = r5._window_facts


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value (or, for F1
    and F4, the sessions after a signal date), or None (``round9_research``'s
    ``segment_window`` on this tool's segments)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Ranked:
    rows: list[tuple[int, dict[str, float | None], str]]
    missing: Counter = field(default_factory=Counter)
    hits: int = 0  # F3: members meeting the conditions
    half: int = 0  # F2: the low-volatility half's size


def rank_f2(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """F2 第 4 點: the half, the two ranks in it, the mean rank."""

    out = Ranked([])
    half_name, half_direction = spec["half"]
    rows = []
    for item, at in members:
        t0 = time.perf_counter()
        vol = vol_720(ctx, item, at)
        t1 = time.perf_counter()
        cash = r5.cash_yield_parts(ctx.yields, item, at).value
        t2 = time.perf_counter()
        mom = mom_240_20(item, at)
        t3 = time.perf_counter()
        ctx.seconds["vol_720"] += t1 - t0
        ctx.seconds["cash_yield_12m"] += t2 - t1
        ctx.seconds["mom_240_20"] += t3 - t2
        values = {half_name: vol, "cash_yield_12m": cash, "mom_240_20": mom}
        for name, value in values.items():
            out.missing[name] += value is None
        rows.append((item.instrument_id, values, pr.tie_break(day, item.instrument_id)))
    t0 = time.perf_counter()
    kept = [row for row in rows if row[1][half_name] is not None]
    kept.sort(key=lambda row: order_key(row[1], ((half_name, half_direction),), row[2]))
    size = math.ceil(len(kept) * LOW_VOL_SHARE)
    half = kept[:size]
    out.half = size
    ranks: dict[int, list[int]] = {row[0]: [] for row in half}
    for name, direction in spec["ranks"]:
        ordered = sorted(
            half, key=lambda row: order_key(row[1], ((name, direction),), row[2])
        )
        for place, row in enumerate(ordered, 1):
            ranks[row[0]].append(size if row[1][name] is None else place)
    weight = sum(RANK_WEIGHTS)
    scored = []
    for instrument_id, values, tie in half:
        mine = ranks[instrument_id]
        total = sum(w * r for w, r in zip(RANK_WEIGHTS, mine))
        score = Fraction(total, weight)
        key = score if spec["score"] == LOW else -score
        scored.append(
            (
                key,
                tie,
                instrument_id,
                {**values, "r1": mine[0], "r2": mine[1], "score": float(score)},
            )
        )
    scored.sort(key=lambda row: (row[0], row[1]))
    out.rows = [
        (instrument_id, values, tie) for _k, tie, instrument_id, values in scored
    ]
    ctx.seconds["f2_order"] += time.perf_counter() - t0
    return out


def rank_f3(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """F3 第 3、4 點: the members meeting both conditions, small first."""

    out = Ranked([])
    rows = []
    t0 = time.perf_counter()
    for item, at in members:
        ok, dd, md = f3_qualifies(ctx, item, at)
        out.missing["drawdown_60"] += dd is None
        out.missing["margin_drop_5"] += md is None
        if ok:
            rows.append(
                (
                    item.instrument_id,
                    {"drawdown_60": dd, "margin_drop_5": md},
                    pr.tie_break(day, item.instrument_id),
                )
            )
    ctx.seconds["drawdown_60+margin_drop_5"] += time.perf_counter() - t0
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    out.hits = len(rows)
    return out


RANKERS = {"F2": rank_f2, "F3": rank_f3}
PICK_FIELDS = {
    "F2": ("vol_720", "cash_yield_12m", "mom_240_20", "r1", "r2", "score"),
    "F3": ("drawdown_60", "margin_drop_5"),
}


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    overlap: dict[str, list[float]] = field(default_factory=dict)  # F2, by year


def _coverage_add(
    coverage: dict[str, Any], name: str, day: date, members: int, r: Ranked
) -> None:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += members
    for key, count in r.missing.items():
        year["missing"][key] = year["missing"].get(key, 0) + count
    if name == "F3":
        year["hits"] = year.get("hits", 0) + r.hits
        year["hit_days"] = year.get("hit_days", 0) + (r.hits > 0)
        year["over_top_days"] = year.get("over_top_days", 0) + (
            r.hits > HYPOTHESES[name]["top"]
        )
        year["max_hits"] = max(year.get("max_hits", 0), r.hits)
    else:
        year["half"] = year.get("half", 0) + r.half


def x2_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """X2's list on ``day`` (``explore_research`` 第 2 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = ex.HYPOTHESES[X2]
    rows, _missing = ex._rank(ctx.base, spec, day, members)
    ctx.seconds["x2_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def overlap_share(mine: list[int], x2: set[int]) -> float | None:
    """F2 第 6 點: |F2 ∩ X2| ÷ F2's names; None when either has no list."""

    if not mine or not x2:
        return None
    return len(set(mine) & x2) / len(mine)


def plan(
    ctx: Context, spec: dict[str, Any], name: str, first: int, last: int, keep_rows=True
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    ranker = RANKERS[name]
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        ranked = ranker(ctx, spec, day, members)
        _coverage_add(out.coverage, name, day, len(members), ranked)
        out.signal_days += 1
        if name == "F2":
            x2 = x2_names(ctx, day, members)  # timed in the coverage too
            if keep_rows:
                share = overlap_share([row[0] for row in ranked.rows[:top]], x2)
                if share is not None:
                    out.overlap.setdefault(str(day.year), []).append(share)
        if not keep_rows:
            continue
        out.picks[at + 1] = [row[0] for row in ranked.rows]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (instrument_id, values, tie) in enumerate(ranked.rows[:top], 1):
            exchange, symbol, _ = panel.symbols.get(instrument_id, ("", "", ""))
            out.rows.append(
                {
                    "signal_date": day.isoformat(),
                    "rank": place,
                    "exchange": exchange,
                    "symbol": symbol,
                    **{key: values.get(key) for key in PICK_FIELDS[name]},
                    "tie": tie[:12],
                }
            )
    return out


def overlap_summary(by_year: dict[str, list[float]]) -> dict[str, Any]:
    every = [value for values in by_year.values() for value in values]
    return {
        "days": len(every),
        "mean": statistics.fmean(every) if every else None,
        "years": {
            year: {"days": len(values), "mean": statistics.fmean(values)}
            for year, values in sorted(by_year.items())
        },
    }


def _result(name: str, segment: str) -> dict[str, Any]:
    return {
        "hypothesis": name,
        "engine": HYPOTHESES[name]["engine"],
        "segment": segment,
        "verdict": None if segment == USED else ex.UNDECIDED,
        "reason": None,
        "window": {"days": 0},
        "prerequisites": None,
    }


def _prerequisites(
    db: Path, result: dict[str, Any], segment: str, sessions, first: int, last: int
) -> bool:
    """docs 段長下限、先決條件: False (not run) when they fail."""

    days = last - first + 1
    need = MIN_SEGMENT_DAYS[segment]
    delisted = ex.delisted_count(db, sessions[first], sessions[last])
    result["prerequisites"] = {
        "days": days,
        "min_days": need,
        "delisted": delisted,
        "ok": days >= need and delisted > 0,
    }
    if not result["prerequisites"]["ok"]:
        result["reason"] = "segment_too_short" if days < need else "no_delisted"
        return False
    return True


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """F2 or F3 on one segment: its numbers, verdict and private parts."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    days = last - first + 1
    result["window"] = _window_facts(sessions, window)
    if segment != USED and not coverage_only:
        if not _prerequisites(db, result, segment, sessions, first, last):
            return result
    ctx.seconds.clear()
    started = time.monotonic()
    planned = plan(ctx, spec, name, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["coverage"] = planned.coverage
    result["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    if coverage_only:
        return result
    if name == "F2":
        result["overlap"] = overlap_summary(planned.overlap)
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    taiex = ex._taiex(ctx.panel, first, last)
    excess = {
        POPULATION: pr.excess_metrics([a - b for a, b in zip(returns, others)]),
        TAIEX: pr.excess_metrics(
            [a - b for a, b in zip(returns, taiex) if b is not None]
        ),
    }
    absolute = statistics.fmean(returns) if returns else None
    result["excess"] = excess
    result["absolute"] = {"days": len(returns), "mean": absolute}
    result["curves"] = {
        name: pr.curve_metrics(returns, mine.invested, ex._turnover(mine)),
        POPULATION: pr.curve_metrics(
            others, population.invested, ex._turnover(population)
        ),
        TAIEX: pr.curve_metrics([v for v in taiex if v is not None], [1.0], [0.0]),
    }
    result["win"] = ex.win_rate(mine)
    result["counts"] = {name: dict(mine.counts), POPULATION: dict(population.counts)}
    if segment != USED:
        result["min_t"] = min_t
        result["verdict"] = ex.explore_judge(
            segment, days, True, excess[POPULATION], absolute, min_t
        )
    result["_dates"] = sessions[first : last + 1]
    result["_equity"] = (mine.equity, population.equity)
    result["_positions"] = mine.positions
    result["_rows"] = planned.rows
    return result


# --- F1 and F4: trade by trade ----------------------------------------------------


enter_next_open = r9.enter_next_open


@dataclass
class EventState:
    """F1 or F4's run: ``trade_research.State`` (the trades, the occupancy)
    plus the days without a list (F4) and the signals by year."""

    state: tr.State
    missing_days: Counter = field(default_factory=Counter)  # by exchange
    years: dict[str, Counter] = field(default_factory=dict)


def _signals(
    ctx: Context,
    name: str,
    s: int,
    members: list[tuple[lib.Series, int]],
    missing: Counter,
) -> list[tuple[lib.Series, int, dict[str, Any]]]:
    """The signals of signal date ``s`` among ``members`` (item, at, extra);
    ``missing`` counts F4's exchanges without the two lists."""

    out = []
    t0 = time.perf_counter()
    if name == "F1":
        for item, at in members:
            if stock_div_ex(ctx, item, s):
                ratio = ctx.stock_div[item.instrument_id][s]
                out.append((item, at, {"stock_dividend_ratio": ratio}))
        ctx.seconds["stock_div_ex"] += time.perf_counter() - t0
        return out
    panel = ctx.panel
    day = panel.sessions[s]
    before = panel.sessions[s - 1] if s > 0 else None
    open_ = {}
    for exchange in MARKETS:
        open_[exchange] = ctx.lists.has(exchange, day) and ctx.lists.has(
            exchange, before
        )
        missing[exchange] += not open_[exchange]
    for item, at in members:
        exchange = panel.symbols.get(item.instrument_id, ("", "", ""))[0]
        if not open_.get(exchange):
            continue
        if margin_first(ctx, item, s, at):
            out.append((item, at, {"bars_before": at}))
    ctx.seconds["margin_first"] += time.perf_counter() - t0
    return out


def event_day(ctx: Context, run: EventState, s: int, s_last: int) -> None:
    """The signals on signal date ``s``, each traded at once."""

    trade, state = ctx.trade, run.state
    members = [
        (item, at)
        for item, at in trade.universe(s)
        if state.busy.get(item.instrument_id, -1) < s
    ]
    day = ctx.panel.sessions[s]
    made = 0
    for item, at, extra in _signals(ctx, state.name, s, members, run.missing_days):
        bars = tr.TradeBars(trade, item, s, s_last)
        entry = enter_next_open(bars)
        row = tr._trade_row(
            trade, state, s, item, None, bars, entry, 0, NO_STOP, None, s_last, extra
        )
        row["stop"] = None  # no stop: NO_STOP is only settle's argument
        state.trades.append(row)
        year = run.years.setdefault(str(day.year), Counter())
        year[f"{row['exchange']}:signals"] += 1
        year["signals"] += 1
        made += 1
    state.signal_days += made > 0
    if made:
        run.years[str(day.year)]["signal_days"] += 1


def run_trades(
    ctx: Context, db: Path, name: str, segment: str, min_t: float = MIN_T
) -> dict[str, Any]:
    """F1 or F4 on one segment (docs 逐筆評估): its numbers, verdict and trades."""

    spec = HYPOTHESES[name]
    sessions = ctx.panel.sessions
    result = _result(name, segment)
    window = segment_window(sessions, segment, spec)
    if window is None:
        result["reason"] = "no_sessions"
        return result
    first, last = window
    result["window"] = _window_facts(sessions, window)
    if segment != USED:
        if not _prerequisites(db, result, segment, sessions, first, last):
            return result
    ctx.seconds.clear()
    started = time.monotonic()
    run = EventState(tr.State(name, spec))
    for s in range(first - 1, last):
        event_day(ctx, run, s, last)
    result["window"]["signal_days"] = last - first + 1
    numbers = tr.stats(run.state)
    result.update(numbers)
    result["listed"] = {
        "years": {year: dict(counts) for year, counts in sorted(run.years.items())},
    }
    if name == "F4":
        result["listed"]["missing_list_days"] = {
            exchange: run.missing_days[exchange] for exchange in MARKETS
        }
    result["seconds"] = {"run": time.monotonic() - started, **ctx.seconds}
    result["_trades"] = run.state.trades
    if segment == USED:
        return result
    result["min_t"] = min_t
    if numbers["trade_days"] < MIN_DAYS:
        result["reason"] = "too_few_trade_days"
        result["verdict"] = ex.UNDECIDED
    else:
        result["verdict"] = ex.explore_judge(
            segment,
            result["window"]["days"],
            True,
            numbers["excess"],
            numbers["absolute"]["mean"],
            min_t,
        )
    return result


def run_one(
    ctx: Context, db: Path, name: str, segment: str, min_t: float = MIN_T
) -> dict[str, Any]:
    if HYPOTHESES[name]["engine"] == TRADE:
        return run_trades(ctx, db, name, segment, min_t)
    return run_portfolio(ctx, db, name, segment, min_t=min_t)


# --- --coverage-only for F1 and F4 ------------------------------------------------


def _quartiles(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "q1": None, "median": None, "q3": None}
    if len(values) == 1:
        return {"count": 1, "q1": values[0], "median": values[0], "q3": values[0]}
    q1, median, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return {"count": len(values), "q1": q1, "median": median, "q3": q3}


def event_coverage(ctx: Context, name: str) -> dict[str, Any]:
    """F1: by year the signals and the signal dates; F4 第 5、6 點: by year
    and exchange the signals, the first entries' bars before them (median and
    quartiles), the most first entries in a day and the days without a list.
    Every signal date counts, without the occupancy (nothing is traded)."""

    spec = HYPOTHESES[name]
    panel = ctx.panel
    sessions = panel.sessions
    window = segment_window(sessions, EXPLORATION, spec)
    if window is None:
        return {"window": {"days": 0}, "years": {}}
    first, last = window
    ctx.seconds.clear()
    started = time.monotonic()
    years: dict[str, dict[str, Any]] = {}
    for s in range(first - 1, last):
        day = sessions[s]
        year = years.setdefault(
            str(day.year), {"days": 0, "signal_days": 0, "markets": {}}
        )
        year["days"] += 1
        members = lib.universe(panel, day, MIN_LOTS)
        missing = Counter()
        signals = _signals(ctx, name, s, members, missing)
        if name == "F4":
            for exchange in MARKETS:
                m = year["markets"].setdefault(exchange, Counter())
                m["missing_list_days"] += missing[exchange]
        else:
            nulls = sum(
                1 for item, _at in members if stock_div_ex(ctx, item, s) is None
            )
            year["null_ratio"] = year.get("null_ratio", 0) + nulls
            blank = sum(
                1 for item, _at in members if (item.instrument_id, s) in ctx.blank
            )
            year["blank_rows"] = year.get("blank_rows", 0) + blank
        year["signal_days"] += bool(signals)
        for item, _at, _extra in signals:
            exchange = panel.symbols.get(item.instrument_id, ("", "", ""))[0]
            m = year["markets"].setdefault(exchange, Counter())
            m["signals"] += 1
        year["signals"] = year.get("signals", 0) + len(signals)
    out: dict[str, Any] = {
        "window": _window_facts(sessions, window),
        "years": {},
    }
    entries: dict[str, dict[str, Any]] = {}
    if name == "F4":
        lo, hi = sessions[first - 1], sessions[last - 1]
        lags: dict[tuple[str, str], list[int]] = defaultdict(list)
        per_day: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for instrument_id, item in panel.series.items():
            exchange = panel.symbols.get(instrument_id, ("", "", ""))[0]
            if exchange not in MARKETS:
                continue
            entry = first_entry(ctx, item)
            if entry is None or not lo <= entry <= hi:
                continue
            key = (str(entry.year), exchange)
            lags[key].append(bisect_left(item.dates, entry))
            per_day[key][entry] += 1
        for (year, exchange), values in sorted(lags.items()):
            most_day, most = min(
                per_day[(year, exchange)].items(), key=lambda kv: (-kv[1], kv[0])
            )
            entries.setdefault(year, {})[exchange] = {
                **_quartiles(sorted(values)),
                "under_min_bars": sum(1 for value in values if value < MIN_BARS),
                "max_day": most_day.isoformat(),
                "max_day_entries": most,
            }
        out["first_list_day"] = {
            exchange: day.isoformat()
            for exchange, day in sorted(ctx.lists.first_day.items())
        }
    for key, row in sorted(years.items()):
        body = {
            "days": row["days"],
            "signal_days": row["signal_days"],
            "signals": row.get("signals", 0),
            "markets": {
                exchange: dict(counts) for exchange, counts in row["markets"].items()
            },
        }
        if name == "F1":
            body["null_ratio"] = row.get("null_ratio", 0)
            body["blank_rows"] = row.get("blank_rows", 0)
        else:
            body["entries"] = entries.get(key, {})
        out["years"][key] = body
    out["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    return out


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public
threshold = r5.threshold
_share = r5._share
PORTFOLIO_TRADE_FIELDS = r5.TRADE_FIELDS
EVENT_FIELDS = {"F1": ("stock_dividend_ratio",), "F4": ("bars_before",)}
EVENT_TRADE_TAIL = (
    "entry_reason",
    "limit_blocked",
    "abandoned_date",
    "fill_date",
    "fill_price",
    "exit_date",
    "exit_reason",
    "exit_price",
    "net",
    "holding",
    "limit_delayed",
    "suspension_delayed",
    "population",
    "population_members",
    "population_unbought",
    "excess",
    "taiex",
    "taiex_excess",
)


def event_trade_fields(name: str) -> tuple[str, ...]:
    return ("signal_date", "exchange", "symbol", *EVENT_FIELDS[name], *EVENT_TRADE_TAIL)


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司；"
        f"F1、F4 另要有成交的訊號日至少 {MIN_DAYS} 日（逐筆評估）。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def portfolio_coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """F2: each feature's missing share and the half's mean size; F3: the
    members meeting both conditions and the days with at least one (分母是母體檔次)."""

    if name == "F2":
        head = [
            "年",
            "日數",
            "母體檔次",
            "`vol_720` 缺值",
            "`mom_240_20` 缺值",
            "`cash_yield_12m` 缺值",
            "低波動半平均檔數",
        ]
    else:
        head = [
            "年",
            "日數",
            "母體檔次",
            "符合的檔日",
            "至少一檔符合的訊號日",
            "一天最多",
            "超過 20 檔的天數",
            "`drawdown_60` 缺值",
            "`margin_drop_5` 缺值",
        ]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        missing = row.get("missing", {})
        cells = [f"{days:,}", f"{members:,}"]
        if name == "F2":
            cells += [
                _share(missing.get("vol_720", 0), members),
                _share(missing.get("mom_240_20", 0), members),
                _share(missing.get("cash_yield_12m", 0), members),
                lib.num(row.get("half", 0) / days, 1) if days else "—",
            ]
        else:
            cells += [
                f"{row.get('hits', 0):,}",
                f"{row.get('hit_days', 0):,}",
                f"{row.get('max_hits', 0):,}",
                f"{row.get('over_top_days', 0):,}",
                _share(missing.get("drawdown_60", 0), members),
                _share(missing.get("margin_drop_5", 0), members),
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def event_coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    if name == "F1":
        lines = [
            "| 年 | 訊號日 | 有訊號的日數 | 訊號數 | 上市 | 上櫃 "
            "| 母體中 T 日的列配股率都是 null（不符合） | 其中有三欄都是 null 的列 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for year, row in coverage.get("years", {}).items():
            m = row["markets"]
            lines.append(
                f"| {year} | {row['days']:,} | {row['signal_days']:,} | {row['signals']:,} "
                f"| {m.get('TWSE', {}).get('signals', 0):,} "
                f"| {m.get('TPEx', {}).get('signals', 0):,} | {row.get('null_ratio', 0):,} "
                f"| {row.get('blank_rows', 0):,} |"
            )
        return lines
    head = ["年", "訊號日"]
    for label in MARKETS.values():
        head += [
            f"{label}訊號數",
            f"{label}名單缺列的天數",
            f"{label}第一次入名單的檔數",
            f"{label}入名單前的日線根數（中位數）",
            f"{label}四分位（Q1～Q3）",
            f"{label}其中不足 20 根",
            f"{label}一天新增最多（日期）",
        ]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in coverage.get("years", {}).items():
        cells = [f"{row['days']:,}"]
        for exchange in MARKETS:
            m = row["markets"].get(exchange, {})
            e = row.get("entries", {}).get(exchange, {})
            cells += [
                f"{m.get('signals', 0):,}",
                f"{m.get('missing_list_days', 0):,}",
                f"{e.get('count', 0):,}",
                lib.num(e.get("median"), 1) if e else "—",
                f"{lib.num(e.get('q1'), 1)}～{lib.num(e.get('q3'), 1)}" if e else "—",
                f"{e.get('under_min_bars', 0):,}",
                f"{e['max_day_entries']:,}（{e['max_day']}）" if e else "—",
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def _head_lines(
    result: dict[str, Any], header: dict[str, Any], spec: dict[str, Any]
) -> list[str]:
    name = result["hypothesis"]
    segment = SEGMENT_NAMES[result["segment"]]
    window = result["window"] or {}
    verdict = result["verdict"] or "只列出、不判定"
    sizes = (
        f"全部符合、持有 {spec['hold']} 日"
        if spec["engine"] == TRADE
        else f"N＝{spec['top']}、K＝{spec['hold']}"
    )
    lines = [
        f"# {name} {segment}（round10_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；{sizes}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，"
        + ("成交日" if spec["engine"] == TRADE else "有淨值的交易日")
        + f" {window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
        f"{window.get('days', 0)} 個交易日",
        f"- 退化：{DEGENERATE[name]}",
        f"- 限制：{LIMITS[name]}",
    ]
    prerequisites = result.get("prerequisites")
    if prerequisites:
        lines.append(
            f"- 先決條件：段長 {prerequisites['days']}／下限 {prerequisites['min_days']} 日；"
            f"段內已下市公司 {prerequisites['delisted']} 檔"
        )
    lines += [
        f"- 副本：最新交易日 {header['copy']['latest']}，alembic `{header['copy']['alembic']}`",
        f"- 重現：`{header['command']}`",
        "",
    ]
    return lines


OVERLAP_NOTE = (
    'F2 與 H2（X2，`explore_research` 第 2 版的 `HYPOTHESES["X2"]`）每日名單的重疊比例：'
    "|F2 的前 20 名 ∩ X2 的前 20 名| ÷ F2 當天的名單檔數；F2 或 X2 當天沒有名單的日子不計。"
    "只列出、不判定"
)


def portfolio_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    lines = _head_lines(result, header, spec)
    if "excess" in result:
        e, a = result["excess"], result["absolute"]
        lines += [
            "## 數字",
            "",
            "| 量 | 日數 | 日均 | 年化 | t |",
            "| --- | ---: | ---: | ---: | ---: |",
            f"| 超額（對加權指數，只列出） | {e[TAIEX]['days']} | {_pct(e[TAIEX]['mean'], 3)} "
            f"| {_pct(e[TAIEX]['annual'])} | {_t(e[TAIEX]['t'])} |",
            f"| 超額（對母體，判定） | {e[POPULATION]['days']} | {_pct(e[POPULATION]['mean'], 3)} "
            f"| {_pct(e[POPULATION]['annual'])} | {_t(e[POPULATION]['t'])} |",
            f"| 絕對報酬（扣成本，判定） | {a['days']} | {_pct(a['mean'], 3)} "
            f"| {_pct(None if a['mean'] is None else a['mean'] * pr.TRADING_DAYS)} | — |",
            "",
            f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}。",
            "",
            "## 只列出",
            "",
            "| 組合 | 日數 | 年化報酬 | 年化波動 | 最大回撤 | 平均投入 | 年化換手 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        labels = {name: name, POPULATION: "母體（基準）", TAIEX: "加權指數（價格指數）"}
        for key in (TAIEX, name, POPULATION):
            c = result["curves"][key]
            held = (
                "| — | — |"
                if key == TAIEX
                else f"| {_pct(c.get('invested'), 1)} | {lib.num(c.get('turnover'), 1)} |"
            )
            lines.append(
                f"| {labels[key]} | {c['days']} | {_pct(c.get('annual'))} "
                f"| {_pct(c.get('volatility'))} | {_pct(c.get('max_drawdown'))} " + held
            )
        w = result["win"]
        counts = result["counts"][name]
        lines += [
            "",
            f"勝率（買進的每一筆，期末未賣以最後收盤計）：{_pct(w['rate'], 1)}"
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if "overlap" in result:
        o = result["overlap"]
        lines += [
            "## 和 H2 的重疊（F2 第 6 點）",
            "",
            OVERLAP_NOTE + "。",
            "",
            f"全段平均：{_pct(o['mean'], 1)}（{o['days']:,} 個訊號日）。",
            "",
            "| 年 | 訊號日 | 平均重疊 |",
            "| --- | ---: | ---: |",
            *(
                f"| {year} | {row['days']:,} | {_pct(row['mean'], 1)} |"
                for year, row in o["years"].items()
            ),
            "",
        ]
    if result.get("coverage"):
        lines += [
            "## 資料覆蓋（不含報酬）",
            "",
            *portfolio_coverage_lines(name, result["coverage"]),
            "",
        ]
    return "\n".join(lines)


def event_markdown(result: dict[str, Any], header: dict[str, Any]) -> str:
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    lines = _head_lines(result, header, spec)
    if "excess" not in result:
        return "\n".join(lines)
    x, e, a = result["taiex_excess"], result["excess"], result["absolute"]
    lines += [
        "## 數字（訊號日序列：同一訊號日的各筆先平均）",
        "",
        "| 量 | 訊號日數 | 平均 | t |",
        "| --- | ---: | ---: | ---: |",
        f"| 超額（對加權指數，只列出） | {x['days']} | {_pct(x['mean'], 3)} | {_t(x['t'])} |",
        f"| 超額（對母體，判定） | {e['days']} | {_pct(e['mean'], 3)} | {_t(e['t'])} |",
        f"| 扣成本報酬（判定） | {a['days']} | {_pct(a['mean'], 3)} | — |",
        "",
        f"門檻：t ≥ {threshold(result.get('min_t', MIN_T))}（`t_stat(…, overlap={OVERLAP})`）；"
        f"有成交的訊號日至少 {MIN_DAYS} 日。",
        "",
        "## 只列出",
        "",
        "| 項目 | 值 |",
        "| --- | ---: |",
        f"| 訊號數 | {result['signals']:,} |",
        f"| 有訊號的日數 | {result['signal_days']:,} |",
        f"| 成交筆數 | {result['trades']:,} |",
        f"| 每筆平均（扣成本） | {_pct(result['net_mean'], 3)} |",
        f"| 每筆中位（扣成本） | {_pct(result['net_median'], 3)} |",
        f"| 勝率（> 0 ÷ 成交筆數） | {_pct(result['win_rate'], 1)} |",
        f"| 賺的筆數／平均 | {result['won']:,}／{_pct(result['won_mean'], 3)} |",
        f"| 賠的筆數／平均 | {result['lost']:,}／{_pct(result['lost_mean'], 3)} |",
        f"| 報酬剛好 0 的筆數 | {result['zero']:,} |",
        f"| 平均持有天數 | {lib.num(result['holding_mean'], 2)} |",
        f"| 放棄比例（放棄 ÷ 訊號） | {_pct(result['abandon_rate'], 1)}"
        f"（{result['abandoned']:,}） |",
    ]
    for reason, label in ABANDON_LABELS.items():
        lines.append(
            f"| 放棄：{label} | {result['abandon_reasons'].get(reason, 0):,} |"
        )
    for reason in tr.EXIT_REASONS:
        if reason in ("stop", "target"):
            continue  # neither
        lines.append(
            f"| 出場：{tr.EXIT_LABELS[reason]} | {_pct(result['exit_share'][reason], 1)}"
            f"（{result['exits'][reason]:,}） |"
        )
    listed = result.get("listed", {})
    lines += [
        f"| 跌停順延 | {result['limit_delayed']:,} |",
        f"| 停牌順延 | {result['suspension_delayed']:,} |",
        f"| 母體在 e 買不進的檔次 | {result['population_unbought']:,} |",
    ]
    if name == "F4":
        lines += [
            f"| {label}名單缺列的天數（T 或前一個交易日） | "
            f"{listed.get('missing_list_days', {}).get(exchange, 0):,} |"
            for exchange, label in MARKETS.items()
        ]
    lines += [
        "",
        "### 每年的訊號數",
        "",
        "| 年 | 訊號數 | 有訊號的日數 | 上市 | 上櫃 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for year, counts in listed.get("years", {}).items():
        lines.append(
            f"| {year} | {counts.get('signals', 0):,} | {counts.get('signal_days', 0):,} "
            f"| {counts.get('TWSE:signals', 0):,} | {counts.get('TPEx:signals', 0):,} |"
        )
    lines.append("")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    return tr._cell(value)


def write_hypothesis(out: Path, result: dict[str, Any], header: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    name = result["hypothesis"]
    spec = HYPOTHESES[name]
    body = {
        **{
            key: header[key]
            for key in ("tool", "version", "design", "definitions_sha256")
        },
        "label": spec["label"],
        "direction": spec["direction"],
        "parameters": {
            key: value
            for key, value in spec.items()
            if key not in ("label", "direction")
        },
        **public(result),
    }
    (out / "tables.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    trade = spec["engine"] == TRADE
    (out / "summary.md").write_text(
        event_markdown(result, header) if trade else portfolio_markdown(result, header),
        encoding="utf-8",
    )
    if trade and "_trades" in result:
        _write_trades(out, name, result["_trades"])
    elif "_dates" in result:
        _write_portfolio(out, result, header)


def _write_trades(out: Path, name: str, trades: list[dict[str, Any]]) -> None:
    fields = event_trade_fields(name)
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for trade in trades:
            writer.writerow([_cell(trade.get(key)) for key in fields])
    days: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        if trade["net"] is not None:
            days[trade["signal_date"]].append(trade)
    with (out / "days.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["signal_date", "trades", "net", "excess", "taiex_excess"])
        for day, rows in sorted(days.items()):
            cells = []
            for key in ("net", "excess", "taiex_excess"):
                values = [row[key] for row in rows if row[key] is not None]
                cells.append(_cell(statistics.fmean(values)) if values else "")
            writer.writerow([day.isoformat(), len(rows), *cells])


def _write_portfolio(out: Path, result: dict[str, Any], header: dict[str, Any]) -> None:
    name = result["hypothesis"]
    panel = header["_panel"]
    mine, population = result["_equity"]
    with (out / "equity.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", name, POPULATION, "taiex_close"])
        for at, day in enumerate(result["_dates"]):
            writer.writerow(
                [
                    day.isoformat(),
                    f"{mine[at]:.8f}",
                    f"{population[at]:.8f}",
                    panel.index_close.get(day),
                ]
            )
    fields = ["signal_date", "rank", "exchange", "symbol", *PICK_FIELDS[name], "tie"]
    with (out / "picks.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["_rows"])
    sessions = panel.sessions
    with (out / "trades.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PORTFOLIO_TRADE_FIELDS)
        for position in result["_positions"]:
            exchange, symbol, _ = panel.symbols.get(
                position.instrument_id, ("", "", "")
            )
            writer.writerow(
                [
                    position.account,
                    exchange,
                    symbol,
                    sessions[position.bought].isoformat(),
                    sessions[position.due].isoformat()
                    if position.due < len(sessions)
                    else "",
                    sessions[position.sold].isoformat()
                    if position.sold is not None
                    else "",
                    position.how,
                    f"{position.cost:.10f}",
                    "" if position.proceeds is None else f"{position.proceeds:.10f}",
                ]
            )


def _row(result: dict[str, Any]) -> dict[str, Any]:
    """The overview's row: the portfolio engine's excess, or the trades'."""

    if result["engine"] == TRADE:
        return {"engine": TRADE, **tr._row(result)}
    row = {"engine": PORTFOLIO, **r5._row(result)}
    if "overlap" in result:
        row["overlap_x2"] = {key: result["overlap"][key] for key in ("days", "mean")}
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round10_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十輪：F1～F4」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：F2、F3 是組合引擎（`portfolio_research.simulate`，日數是有淨值的交易日）；"
        "F1、F4 是逐筆評估（`trade_research`，日數是段內交易日，超額與 t 在訊號日序列上）",
        *(f"- {name} 的限制：{text}" for name, text in LIMITS.items()),
        f"- 副本：最新交易日 {report['copy']['latest']}，alembic `{report['copy']['alembic']}`",
        f"- 讀取的資料到 {report['read_until']}（之後的列不讀）",
        f"- 耗時 {report.get('elapsed_seconds', 0):.0f} 秒，峰值記憶體 "
        f"{lib.num(report.get('peak_memory_gb'), 2)} GB",
        f"- 重現：`{report['command']}`",
    ]
    if segment == EXPLORATION:
        lines.append("- 本次跑的假設：" + "、".join(report.get("selected") or []))
    if segment == VALIDATION:
        lines.append(
            f"- 前瞻觀察：超額 > 0 但 t < {threshold(report['min_t'])}，且絕對報酬 > 0；"
            "只當紀錄，不算通過、不進產品"
        )
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    head = (
        "| 代號 | 方向 | 引擎 | 日數 | 有成交的訊號日 | 對加權指數超額 | t | 對母體超額 | t "
        "| 絕對報酬 | 判定 |"
    )
    rule = "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines += ["", "## 判定", "", head, rule]
    for name, row in report["hypotheses"].items():
        lines.append(_overview_line(name, row, judged=True))
    overlap = report["hypotheses"].get("F2", {}).get("overlap_x2")
    if overlap:
        lines += [
            "",
            f"F2 和 H2 的重疊（只列出）：平均 {_pct(overlap['mean'], 1)}"
            f"（{overlap['days']:,} 個訊號日）。",
        ]
    if report.get("used"):
        lines += [
            "",
            "## 已用段（驗證通過的假設，只列出、不判定）",
            "",
            head,
            rule,
        ]
        for name, row in report["used"].items():
            lines.append(_overview_line(name, row, judged=False))
    lines += [
        "",
        "各假設的數字、只列出的指標與資料覆蓋見 `<代號>/summary.md`。",
        "",
    ]
    return "\n".join(lines)


def _overview_line(name: str, row: dict[str, Any], judged: bool) -> str:
    spec = HYPOTHESES[name]
    e = row.get("excess") or {}
    x = row.get("taiex_excess") or {}
    verdict = (row["verdict"] or "—") if judged else "只列出"
    if row.get("reason"):
        verdict += f"（{REASONS[row['reason']]}）"
    trade = row.get("engine") == TRADE
    return (
        f"| {name} | {spec['direction']} | {'逐筆' if trade else '組合'} | {row['days']} "
        f"| {(row.get('trade_days') or 0) if trade else '—'} "
        f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
        f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
        f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
    )


def seconds_lines(body: dict[str, Any]) -> list[str]:
    """The time of each hypothesis's signal dates and of its features."""

    lines = [
        "| 代號 | 訊號日 | 排序與覆蓋（秒） | 特徵計算（秒） | 每個訊號日（毫秒） |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for name, row in body["hypotheses"].items():
        seconds = row.get("seconds") or {}
        days = (row["window"] or {}).get("days", 0)
        parts = "、".join(
            f"`{key}` {value:.1f}" for key, value in seconds.items() if key != "plan"
        )
        per_day = lib.num(seconds.get("plan", 0.0) * 1000 / days, 1) if days else "—"
        lines.append(
            f"| {name} | {days:,} | {seconds.get('plan', 0.0):.1f} | {parts or '—'} "
            f"| {per_day} |"
        )
    return lines


COVERAGE_NOTES = (
    "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；每個訊號日都數，不扣占用（沒有模擬成交）",
    f"- F1：`stock_div_ex`：{DEGENERATE['F1']}。訊號數是母體中 `stock_div_ex` 成立的檔次；只有現金股利的列，配股率也是 null，"
    "同樣不符合，三欄都是 null 的列另列一欄",
    f"- F2：{DEGENERATE['F2']}。`x2_order` 是同一個 T 算 X2（H2）名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- F3：{DEGENERATE['F3']}。兩個條件以分數比較，剛好 −0.22、−0.10 符合",
    f"- F4：{DEGENERATE['F4']}。「第一次入名單」是這一檔從第一根日線起，"
    "在同一交易所名單上的第一天（第一根日線以前就在名單上的、交易所名單第一天就在的不算；"
    "第一根日線那天就在的算，前面 0 根，因不足 20 根不產生訊號）；"
    "「入名單前的日線根數」是那天以前這個 instrument 的日線根數（研究工具讀到的，排除清單的不算），"
    "不限母體；訊號數只數母體、另要 ≥ 20 根",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 F1～F4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round10_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、除權息 "
        f"{load_seconds.get('actions', 0):.0f} 秒、名單 {load_seconds.get('margin_lists', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根",
        *COVERAGE_NOTES,
        "",
        "## 耗時",
        "",
        *seconds_lines(body),
        "",
    ]
    for name, row in body["hypotheses"].items():
        window = row["window"] or {}
        lines += [
            f"## {name}（訊號日 {window.get('first_signal', '—')} 起，{window.get('days', 0)} 日）",
            "",
        ]
        if HYPOTHESES[name]["engine"] == TRADE:
            title = (
                "### F1：依年的訊號數與訊號日數"
                if name == "F1"
                else "### F4 第 5、6 點：依年、依交易所"
            )
            lines += [title, "", *event_coverage_lines(name, row["coverage"]), ""]
            if name == "F4":
                first = row["coverage"].get("first_list_day", {})
                lines += [
                    "名單的第一天："
                    + "、".join(
                        f"{MARKETS.get(exchange, exchange)} {day}"
                        for exchange, day in first.items()
                    )
                    + "。有明顯斷點（某年起中位數大幅改變，或某一天大量新增）時，"
                    "先在工具單提問、不跑 F4 的探索段。",
                    "",
                ]
        else:
            lines += [*portfolio_coverage_lines(name, row["coverage"]), ""]
    return "\n".join(lines)


# --- the runs ---------------------------------------------------------------------


def _header(db: Path, segment: str, command: str, read_until: date) -> dict[str, Any]:
    return {
        "tool": TOOL,
        "version": VERSION,
        "design": DESIGN,
        "registration_commit": REGISTRATION_COMMIT,
        "segment": segment,
        "round": ROUND,
        "round_size": ROUND_SIZE,
        "cumulative": CUMULATIVE,
        "validation_min_t": VALIDATION_MIN_T,
        "definitions_sha256": definitions_sha256(),
        "engines": {
            "portfolio_research": "simulate",
            "trade_research": tr.VERSION,
        },
        "tool_commit": ex.tool_commit(),
        "command": command,
        "copy": pr.copy_facts(db),
        "read_until": read_until.isoformat(),
    }


def _peak_memory_gb() -> float | None:
    return lib._load("backtest_research").peak_memory_gb()


def _finish(out: Path, report: dict[str, Any], started: float) -> str:
    report["elapsed_seconds"] = time.monotonic() - started
    report["peak_memory_gb"] = _peak_memory_gb()
    path = out / "explore.json"
    path.write_text(
        json.dumps(public(report), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    sha256 = ex.file_sha256(path)
    (out / "explore.md").write_text(overview_markdown(report, sha256), encoding="utf-8")
    return sha256


def run_coverage(
    db: Path,
    out: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``--coverage-only``: counts of the exploration, no return."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
    loaded = time.monotonic() - started
    header = _header(db, EXPLORATION, command, end)
    hypotheses = {}
    for name, spec in HYPOTHESES.items():
        if spec["engine"] == TRADE:
            coverage = event_coverage(ctx, name)
            row = {
                "window": coverage.pop("window"),
                "seconds": coverage.pop("seconds", {}),
                "coverage": coverage,
            }
        else:
            result = run_portfolio(ctx, db, name, EXPLORATION, coverage_only=True)
            row = {
                "window": result["window"],
                "coverage": result.get("coverage", {}),
                "seconds": result.get("seconds", {}),
            }
        hypotheses[name] = row
        progress(f"{name} coverage ({row['seconds'].get('plan', 0.0):.1f}s)")
    body = {
        **public(header),
        "coverage_only": True,
        "hypotheses": hypotheses,
        "load_seconds": loaded,
        "load_seconds_parts": ctx.load_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "peak_memory_gb": _peak_memory_gb(),
        "bars": sum(len(item.dates) for item in ctx.panel.series.values()),
    }
    (out / "coverage.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "coverage.md").write_text(coverage_markdown(body), encoding="utf-8")
    return {"out": str(out.resolve()), "coverage_only": True}


def run_exploration(
    db: Path,
    out: Path,
    names: list[str] | tuple[str, ...],
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
    header = _header(db, EXPLORATION, command, end)
    header["_panel"] = ctx.panel
    report = {**header, "min_t": MIN_T, "selected": list(names), "hypotheses": {}}
    for name in names:
        t0 = time.monotonic()
        result = run_one(ctx, db, name, EXPLORATION)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = {
            **_row(result),
            "coverage": result.get("coverage"),
        }
        progress(f"{name}: {result['verdict']} ({time.monotonic() - t0:.1f}s)")
    sha256 = _finish(out, report, started)
    # Only a finished run with its report written counts as the one run (#721).
    commit, finished = ex.tool_commit(), ex._now()
    mine = [
        {
            "hypothesis": name,
            "tool": TOOL,
            "round": ROUND,
            "segment": EXPLORATION,
            "version": VERSION,
            "status": "finished",
            "finished_at": finished,
            "report_sha256": sha256,
            "tool_commit": commit,
            "definitions_sha256": report["definitions_sha256"],
            "verdict": report["hypotheses"][name]["verdict"],
        }
        for name in names
    ]
    ledger = ex.ledger_path(db)
    ex.write_ledger(ledger, ex.read_ledger(ledger) + mine)
    ex.write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": EXPLORATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def run_validation(
    db: Path,
    out: Path,
    names: list[str],
    source: dict[str, str],
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the validation segment, once: the ledger first, then the data."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    commit = ex.tool_commit()
    ledger = ex.ledger_path(db)
    entries = ex.read_ledger(ledger)
    for name in names:
        entries.append(
            {
                "hypothesis": name,
                "tool": TOOL,
                "round": ROUND,
                "segment": VALIDATION,
                "version": VERSION,
                "status": "started",
                "started_at": ex._now(),
                "report_sha256": source["sha256"],
                "url": source["url"],
                "tool_commit": commit,
                "definitions_sha256": definitions_sha256(),
            }
        )
    ex.write_ledger(ledger, entries)  # before any validation data is read
    end = SEGMENTS[VALIDATION][1]
    ctx = load(db, LOAD_FROM, end, out / RAW_DIR_NAME)
    header = _header(db, VALIDATION, command, end)
    header["_panel"] = ctx.panel
    min_t = VALIDATION_MIN_T
    report = {**header, "min_t": min_t, "exploration": source, "hypotheses": {}}
    result: dict[str, Any] = {}
    for name in names:
        result = run_one(ctx, db, name, VALIDATION, min_t=min_t)
        write_hypothesis(out / name, result, header)
        report["hypotheses"][name] = _row(result)
        progress(f"{name}: {result['verdict']}")
    for entry in entries:
        if (
            entry.get("tool") == TOOL
            and entry["status"] == "started"
            and entry["hypothesis"] in report["hypotheses"]
        ):
            entry["status"] = "finished"
            entry["finished_at"] = ex._now()
            entry["verdict"] = report["hypotheses"][entry["hypothesis"]]["verdict"]
    ex.write_ledger(ledger, entries)
    passed = [
        name for name in names if report["hypotheses"][name]["verdict"] == ex.PASSED
    ]
    if passed:  # the used segment only for the passed ones
        # Let the validation's panel go before the used one is loaded, so only
        # one panel is held at a time (PR #905 review 7053124013).
        header.pop("_panel", None)
        report.pop("_panel", None)
        del ctx, result
        gc.collect()
        used_ctx = load(db, LOAD_FROM, SEGMENTS[USED][1], out / RAW_DIR_NAME)
        used_header = {**header, "_panel": used_ctx.panel}
        report["used"] = {}
        for name in passed:
            result = run_one(used_ctx, db, name, USED)
            write_hypothesis(out / name / USED, result, used_header)
            report["used"][name] = _row(result)
    sha256 = _finish(out, report, started)
    mine = [
        entry
        for entry in entries
        if entry.get("tool") == TOOL
        and entry["hypothesis"] in names
        and entry.get("segment") == VALIDATION
    ]
    ex.write_ledger(out / "ledger-entries.json", mine)
    return {
        "out": str(out.resolve()),
        "segment": VALIDATION,
        "sha256": sha256,
        "verdicts": {
            name: row["verdict"] for name, row in report["hypotheses"].items()
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="round10_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values per "
        "year (F4 also per exchange) and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): F1, F2, F3, F4 or "
        "some of them, comma separated; each runs once per tool version",
    )
    parser.add_argument(
        "--exploration-report", help="validation: the exploration explore.json"
    )
    parser.add_argument(
        "--exploration-sha256",
        help="validation: the sha256 quoted in the public comment",
    )
    parser.add_argument(
        "--exploration-url", help="validation: the public comment or pr-assets link"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _parser()
    args = parser.parse_args(argv)
    gate = (args.exploration_report, args.exploration_sha256, args.exploration_url)
    if args.segment == EXPLORATION and any(gate):
        parser.error("--exploration-* go with --segment validation only")
    if args.segment == VALIDATION and args.coverage_only:
        parser.error("--coverage-only goes with --segment exploration only")
    if args.hypotheses is not None and (
        args.segment == VALIDATION or args.coverage_only
    ):
        parser.error(
            "--hypotheses goes with --segment exploration only, not --coverage-only"
        )
    db = Path(args.db)
    problems = list(er.refusals(db, args.min_free_gb))
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round10_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        if args.coverage_only:
            line = run_coverage(db, Path(args.out), command, progress=progress)
        else:
            line = run_exploration(
                db, Path(args.out), names, command, progress=progress
            )
    else:
        problems, names, _report = ex.validation_problems(
            db, *gate, HYPOTHESES, DESIGN, definitions_sha256()
        )
        if problems:
            print(json.dumps({"refused": problems}, ensure_ascii=False))
            return 2
        line = run_validation(
            db,
            Path(args.out),
            names,
            {
                "sha256": args.exploration_sha256.strip().lower(),
                "url": args.exploration_url,
            },
            command,
            progress=progress,
        )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
