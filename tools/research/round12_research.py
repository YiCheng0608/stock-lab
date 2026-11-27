"""Round 12 of the new-strategy exploration: J1～J4 (#962).

docs/spec/evidence.md 第十二輪：J1～J4 and 第十二輪實作釋義: the hypotheses
were registered (commit ``24d700c3``, #956, decision 7078404124, correction
7078582727) before anyone ran a tool on the backfilled history.  Nothing here
is a command-line option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round11_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  J1, J2 and J4 trade on the portfolio engine
(``portfolio_research.simulate``) with the population, the loading
(``explore_research.load_context``), ``explore_judge``, the order
(``round5_research.order_key``), ``vol_60`` (``round5_research``),
``turnover_60`` (``explore_research``), ``feature_evidence._flow``, the gate
and the ledgers imported; J3 is judged trade by trade with
``trade_research``'s trades (``TradeBars``, ``settle``, ``baseline``,
``stats``, the occupancy of ``State``) and ``round9_research``'s exit without
a stop or a target (``enter_next_open``, ``NO_STOP``, ``trade_context``), the
corporate actions read by ``research_report.load_actions``.  The overlaps
with V1 and Z1 take those lists from ``round5_research`` and
``round8_research`` (their first versions) and ``round10_research``'s
``overlap_share``／``overlap_summary``.  New here are only ``margin_sent_60``
and J1's switch, ``trust_flow_20`` and J2's subset, ``cash_div_ex``,
``liq_shock_20``, J1's numbers by state and the two overlaps.

Each signal date T (after its close, only T's data and before):

- J1: the market's ``margin_sent_60`` (Σ margin_balance[at] ÷
  Σ margin_balance[at − 60] − 1 over T's population with both ends) > 0
  ranks ``vol_60`` small first, ≤ 0 high first; missing leaves cash.  N 20,
  K 20.
- J2: the population outside ``turnover_60``'s top 150 with
  ``trust_flow_20`` > 0, ``trust_flow_20`` high first; fewer than 20 leave
  cash.  N 20, K 20.
- J3: every member (less the occupied ones) with a cash dividend going ex on
  T of at least 3% of the bar before's unadjusted close.  Bought at T+1's
  open (one session; not tradable or locked at limit up abandons it, locked
  at limit down fills), sold at the close of the 20th session counting the
  fill as the 1st.
- J4: ``liq_shock_20`` = 1 − ``illiq_20`` ÷ ``illiq_base`` (Amihud's
  per-bar ratio over the latest 20 bars and the 240 before them) high
  first.  N 20, K 60.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.285 (49 hypotheses) on the validation; J3 also
needs 60 signal dates with a fill (``trade_research.MIN_DAYS``).  Before the
used segment is loaded the validation's panel is let go (PR #905 review).
``--coverage-only`` writes counts of dates, members and missing values per
year and the time of the features, no return at all.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
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
import feature_evidence as features  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round8_research as r8  # noqa: E402
import round9_research as r9  # noqa: E402
import round10_research as r10  # noqa: E402
import trade_research as tr  # noqa: E402

VERSION = 1
DESIGN = "962"
TOOL = "round12_research"
REGISTRATION_COMMIT = "24d700c3"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/956#issuecomment-7078404124"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十二輪 門檻: 1 − Φ(z) = 0.025 ÷ 49, z = 3.2848, 3.285 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.285
ROUND = 12
ROUND_SIZE = 4
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4
CUMULATIVE = 49
MIN_DAYS = tr.MIN_DAYS  # J3: signal dates with a fill, per segment
OVERLAP = tr.OVERLAP
# Every segment reads the copy from its start, as round10_research and
# round11_research: J4 needs 261 bars before a segment's first signal date.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO, TRADE = "portfolio", "trade"
HIGH, LOW = r5.HIGH, r5.LOW

SENT_WINDOW = 60  # J1: margin_balance[at] against margin_balance[at − 60]
SENT_MIN = 0.0  # J1: margin_sent_60 > 0 is the high state, ≤ 0 the low one
SENT_MEMBERS = "T's population, both ends valued, the same members in both sums"
# J1 第 6 點 (listed only): equity session e holds the lists of the signal
# dates W(e) = max(first − 1, e − hold) .. e − 1 (one per account); its excess
# goes to a state when every T in W(e) has it, else to "mixed" (PR #963
# review 7079570003).  A sale delayed past its due date is not counted.
STATE_OF_DAY = (
    "every signal date T in max(first - 1, e - hold) .. e - 1 in the state "
    "(high, low or missing), else mixed; sales delayed past the due date not counted"
)
LARGE_CAP = 150  # J2: turnover_60's top 150 (X6's) are left out
TRUST_COLUMNS = ("trust_buy",)  # J2: the investment trusts only
TRUST_WINDOW = 20  # J2: institutional_flow_20's window
TRUST_MIN = 0.0  # J2: trust_flow_20 > 0, strictly
# J2 第 4 點: fewer than 20 qualified leave the rest in cash, not filled up
# with a 0 or missing trust_flow_20 (as F3 and L2).
SHORT_RULE = "cash, not filled"
TRUST_FLOW_20 = features._flow(TRUST_COLUMNS, TRUST_WINDOW)
YIELD_MIN = 0.03  # J3: cash_dividend ÷ the bar before's unadjusted close ≥ 3%
# J3 第 1 點: several rows of one stock on one day take the largest cash
# dividend (as F1); a date that is no session is the next session's.
SAME_DAY = "the largest cash_dividend of the day's rows; a null row only if all are"
NEAR = 1e-9  # J3: a yield this close to 3% is compared as decimal fractions
ILLIQ_RECENT = 20  # J4: illiq_20, k = at − 19 .. at
ILLIQ_BASE = 240  # J4: illiq_base, k = at − 259 .. at − 20
NO_STOP = r9.NO_STOP  # J3's exit has no stop and no target
OTC_ANCHOR = r5.OTC_ANCHOR
J2_ANCHOR = date(2014, 12, 1)  # the OTC institutional table's first day
V1, Z1 = "V1", "Z1"  # the lists J1 and J4 overlap with (listed only)

# The registration (docs 第十二輪：J1～J4), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first.  ``keys``: (feature,
# HIGH or LOW), a missing value last, ties by ``portfolio_research.tie_break``;
# J1's by its state.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "J1": {
        "engine": PORTFOLIO,
        "direction": "散戶情緒",
        "label": "`margin_sent_60` > 0 時 `vol_60` 小者先，≤ 0 時 `vol_60` 大者先",
        "rule": "daily",
        "state": ("margin_sent_60", ">", SENT_MIN),  # high when true, else low
        "keys": {
            "high": (("vol_60", LOW),),
            "low": (("vol_60", HIGH),),
        },
        "missing_state": "empty list, cash",
        "top": 20,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 61),
    },
    "J2": {
        "engine": PORTFOLIO,
        "direction": "籌碼：投信",
        "label": "`turnover_60` 前 150 名以外、`trust_flow_20` > 0，"
        "依 `trust_flow_20` 大者先",
        "rule": "daily",
        # (feature, n): the n highest of the population (ties by the hash, a
        # missing value out) are left out, then the missing ones too
        "exclude": ("turnover_60", LARGE_CAP),
        "conditions": (("trust_flow_20", ">", TRUST_MIN),),
        "keys": (("trust_flow_20", HIGH),),
        "short": SHORT_RULE,
        "top": 20,
        "hold": 20,
        "start": ("session", J2_ANCHOR, 60),
    },
    "J3": {
        "engine": TRADE,
        "kind": "event",  # trade_research._trade_row: hold counts from the fill
        "event": "cash_div_ex",
        "direction": "事件：除息",
        "label": "T 日是除息交易日、現金殖利率 ≥ 3%（`cash_div_ex`），全部符合的訊號；"
        "T+1 開盤成交（期限 1 日）、沒有停損與目標、持有 20 日",
        "market_filter": False,
        "entry_days": 1,
        "stop": None,
        "target": None,
        "hold": 20,
        "start": ("session", OTC_ANCHOR, 20),
    },
    "J4": {
        "engine": PORTFOLIO,
        "direction": "流動性衝擊",
        "label": "`liq_shock_20`（近 20 根的 Amihud 相對之前 240 根降了多少）大者先",
        "rule": "daily",
        "keys": (("liq_shock_20", HIGH),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 261),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(tr.REASONS)  # explore_research's and too_few_trade_days
LIMITS = {
    "J1": "情緒狀態會持續好幾個月，切換次數少，等於只有少數幾段在比兩邊，t 高估獨立樣本數；"
    "情緒高的日子名單就是 V1 的名單",
    "J2": "三大法人的官方表只列當天有法人進出的證券，沒列的日子是缺值，名單會偏離法人很少進出的小型股；"
    "`feature_evidence` 的 `trust_flow_5`（投信 5 日）是 #619～#689 在已用段比較過的特徵之一，"
    "J2 依文獻提，沒有看那批結果；不足 20 檔的日子留現金，平均投入比例可能偏低，是登記時事先定的規則",
    "J3": "稅制在 2018 年改過（在探索段裡），二代健保補充保費 2013 年起；驗證段全在 2018 年以後；"
    "除息集中在 6～9 月；逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線；"
    "同一季的訊號持有期間高度重疊",
    "J4": "原文另外控制了其他變數，這裡沒有扣掉成交量的異常，成交量放大常伴隨流動性改善，"
    "J4 可能沾到 Z1，看和 Z1 名單的重疊比例",
}
# The degenerate cases as the code judges them (第十二輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "J1": "T 日母體中 `margin_balance` 在 at 與 at−60 都有值的檔才算進兩個加總；"
    "沒有任何一檔可用或分母 ≤ 0 時 `margin_sent_60` 缺值、名單為空、留現金；"
    "剛好等於 0 走「≤ 0」（`vol_60` 大者先）；`vol_60` 缺值排最後",
    "J2": "`turnover_60` 或 `trust_flow_20` 缺值時條件不符合；"
    "`trust_flow_20` 剛好等於 0 也不符合；符合的不足 20 檔時餘額留現金",
    "J3": "`cash_dividend` 是 null、≤ 0，或前一根停牌、未還原收盤缺值或 ≤ 0 時不符合；"
    "同一檔同一天多列取 `cash_dividend` 最大的",
    "J4": "261 根收盤中任一根停牌、缺值或 ≤ 0，或 260 個 turnover 中任一個不是 > 0"
    "（含 `turnover_status` 不是 `available`），或 `illiq_base` ≤ 0 時缺值、排最後",
}
OVERLAP_NOTE = {
    "J1": 'J1 與 V1（`round5_research` 第 1 版的 `HYPOTHESES["V1"]`）每日名單的重疊比例：'
    "|J1 的前 20 名 ∩ V1 的前 20 名| ÷ J1 當天的名單檔數；J1 或 V1 當天沒有名單的日子不計。"
    "只列出、不判定",
    "J4": 'J4 與 Z1（`round8_research` 第 1 版的 `HYPOTHESES["Z1"]`）每日名單的重疊比例：'
    "|J4 的前 20 名 ∩ Z1 的前 20 名| ÷ J4 當天的名單檔數；J4 或 Z1 當天沒有名單的日子不計。"
    "只列出、不判定",
}
ABANDON_LABELS = r9.ABANDON_LABELS
FEATURE_LABELS = {
    "margin_sent_60": "全市場融資 60 根變化",
    "vol_60": "近 60 日報酬標準差",
    "turnover_60": "60 日平均成交金額",
    "trust_flow_20": "投信 20 日淨買超 ÷ 均量",
    "cash_div_ex": "現金殖利率 ≥ 3% 的除息日",
    "liq_shock_20": "流動性衝擊（Amihud 20 根對 240 根）",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "margin_sent_60": {
                "value": "sum margin_balance[at] / sum margin_balance[at-window] - 1, "
                "lots, at each member's own bars",
                "window": SENT_WINDOW,
                "threshold": SENT_MIN,
                "members": SENT_MEMBERS,
                "missing": "no member with both ends; the denominator <= 0",
            },
            "vol_60": {
                "function": "round5_research.vol_60",
                "window": r5.VOL_WINDOW,
                "ddof": r5.VOL_DDOF,
                "round5_research": [r5.VERSION, r5.DESIGN],
            },
            "turnover_60": {
                "function": "explore_research.turnover_60",
                "window": ex.TURNOVER_WINDOW,
                "available": ex.TURNOVER_AVAILABLE,
                "explore_research": [ex.VERSION, ex.DESIGN],
            },
            "trust_flow_20": {
                "function": "feature_evidence._flow",
                "columns": list(TRUST_COLUMNS),
                "window": TRUST_WINDOW,
                "feature_evidence": features.SHARED_VERSION,
            },
            "subset": {
                "exclude": "the top LARGE_CAP of the population by turnover_60, high "
                "first, ties by the hash; a missing turnover_60 out too",
                "large_cap": LARGE_CAP,
                "conditions": "strictly beyond the threshold; a missing value fails",
                "trust_min": TRUST_MIN,
                "short": SHORT_RULE,
            },
            "cash_div_ex": {
                "value": "cash_dividend of a row with action_date T (the next "
                "session when not one) / the unadjusted close of the bar before T",
                "yield_min": YIELD_MIN,
                "near": NEAR,
                "same_day": SAME_DAY,
                "missing": "cash_dividend null or <= 0; the bar before suspended, "
                "missing or <= 0: does not qualify",
                "f1": "round10_research.stock_div_ex (listed only)",
                "round10_research": [r10.VERSION, r10.DESIGN],
            },
            "liq_shock_20": {
                "a": "|c[k] / c[k-1] - 1| / turnover[k], adjusted closes, official turnover",
                "recent": ILLIQ_RECENT,
                "base": ILLIQ_BASE,
                "value": "1 - illiq_20 / illiq_base",
                "missing": "a suspended bar, a close missing or <= 0 among at-260..at; "
                "a turnover not > 0 among at-259..at; illiq_base <= 0",
            },
            "states": {"of_day": STATE_OF_DAY},
            "overlaps": {
                V1: [r5.HYPOTHESES[V1], r5.VERSION, r5.DESIGN],
                Z1: [r8.HYPOTHESES[Z1], r8.VERSION, r8.DESIGN],
            },
        },
        "event_exit": {
            "entry": "T+1 open, one session; not tradable or locked at limit up "
            "abandons, locked at limit down fills (round9_research.enter_next_open)",
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
    windows, the thresholds, the large-cap line, the orders and J1's two
    directions, J2's cash rule, J3's hold and exit, the segments, the
    costs).  A changed tool needs a new exploration report before a
    validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes),
    the trade context on the same market (J3), the cash dividends and stock
    dividend ratios by session (J3), and the contexts ``round5_research`` and
    ``round8_research`` rank V1 and Z1 with (the same base).  One panel."""

    base: ex.Context
    trade: tr.Context | None = None
    # instrument -> session index of T -> the largest cash_dividend of the
    # day's rows (None: only null ones)
    cash_div: dict[int, dict[int, float | None]] = field(default_factory=dict)
    # round10_research.stock_dividends: F1's stock_div_ex on the same rows
    stock_div: dict[int, dict[int, float | None]] = field(default_factory=dict)
    v1: r5.Context | None = None
    z1: r8.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # J4: per instrument, prefix sums of a[k], of the positive a[k], of the
    # bad closes and of the bad turnovers
    liq: dict[int, tuple[Any, Any, Any, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.v1 is None:
            self.v1 = r5.Context(self.base)
        if self.z1 is None:
            self.z1 = r8.Context(self.base)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def cash_dividends(
    sessions: list[date], holders: dict[int, Any]
) -> dict[int, dict[int, float | None]]:
    """J3 第 1 點: by instrument and session (a date that is no session is the
    next one), the largest ``cash_dividend`` of the rows; None when all of
    the day's rows have a null one."""

    out: dict[int, dict[int, float | None]] = {}
    for instrument_id, holder in holders.items():
        for action in holder.actions:
            s = bisect_left(sessions, action.action_date)  # not a session: the next
            if s >= len(sessions):
                continue
            days = out.setdefault(instrument_id, {})
            cash = action.cash_dividend
            cash = None if cash is None else float(cash)
            old = days.get(s)
            if s not in days or (cash is not None and (old is None or cash > old)):
                days[s] = cash
    return out


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the trade context and the corporate actions
    to ``end``; nothing after ``end`` is read but the date of a delisted or
    transferred stock's last bar (no price)."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    trade = r9.trade_context(base.market, db, end)
    trade_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    report = lib.research_report()
    holders = {
        instrument_id: report.Instrument() for instrument_id in base.market.panel.series
    }
    report.load_actions(db, holders, start, raw_dir, end)
    sessions = base.market.panel.sessions
    cash_div = cash_dividends(sessions, holders)
    stock_div = r10.stock_dividends(sessions, holders)
    del holders
    return Context(
        base,
        trade,
        cash_div,
        stock_div,
        load_seconds={
            "panel": panel_seconds,
            "trade": trade_seconds,
            "actions": time.monotonic() - t0,
        },
    )


# --- features ---------------------------------------------------------------------


@dataclass(frozen=True)
class Sentiment:
    value: float | None  # margin_sent_60, None when missing
    high: bool | None  # > SENT_MIN; None when missing
    members: int  # members with both ends valued


def margin_sent_60(members: list[tuple[lib.Series, int]]) -> Sentiment:
    """J1 第 2、3 點: over T's population, the members whose ``margin_balance``
    is valued at at and at − 60 (their own bars), Σ now ÷ Σ then − 1; missing
    with no such member or a sum then ≤ 0.  The state is decided on the two
    sums, exactly (lots are whole numbers): equal sums are ≤ 0."""

    now = then = 0.0
    used = 0
    for item, at in members:
        back = at - SENT_WINDOW
        if back < 0:
            continue
        balance = item.chips.get("margin_balance")
        if balance is None:
            continue
        a, b = balance[at], balance[back]
        if a != a or b != b:  # no chip row, or a null balance
            continue
        now += a
        then += b
        used += 1
    if not used or not then > 0:
        return Sentiment(None, None, used)
    high = Fraction(now) > Fraction(then) * (1 + Fraction(str(SENT_MIN)))
    return Sentiment(now / then - 1.0, high, used)


def vol_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """J1 第 1 點: ``round5_research.vol_60`` (V1's)."""

    return r5.vol_60(ctx.v1, item, at)


def turnover_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """J2 第 1 點: ``explore_research.turnover_60`` (X6's subset, Y4's)."""

    return ex.turnover_60(ctx.base, item, at)


def trust_flow_20(item: lib.Series, at: int) -> float | None:
    """J2 第 2 點: ``feature_evidence._flow(("trust_buy",), 20)``; a missing
    trust on any of the 20 bars or a missing mean volume is missing."""

    if "trust_buy" not in item.chips:
        return None
    value = TRUST_FLOW_20(item, at)
    return None if value is None or value != value else float(value)


@dataclass(frozen=True)
class Dividend:
    qualifies: bool | None  # None: a row on T that cannot be told
    cash: float | None = None
    close: float | None = None  # the bar before's unadjusted close
    value: float | None = None  # cash ÷ close


def at_least(num: float, den: float, bound: float) -> bool:
    """num ÷ den ≥ bound, exactly: the float when it is clearly apart, the
    decimals of the two numbers (as stored) when it is within ``NEAR``."""

    value = num / den
    if value > bound + NEAR:
        return True
    if value < bound - NEAR:
        return False
    return Fraction(repr(num)) >= Fraction(str(bound)) * Fraction(repr(den))


def cash_div_parts(ctx: Context, item: lib.Series, s: int, at: int) -> Dividend:
    """J3 第 1、2 點 on session ``s`` (``at`` the item's bar there)."""

    days = ctx.cash_div.get(item.instrument_id)
    if not days or s not in days:
        return Dividend(False)
    cash = days[s]
    if cash is None:
        return Dividend(None)
    if not cash > 0:
        return Dividend(False, cash)
    if at < 1 or item.is_suspended(at - 1):
        return Dividend(None, cash)
    close = ctx.market.raw[item.instrument_id][2][at - 1]
    if not close > 0:  # NaN fails too
        return Dividend(None, cash)
    return Dividend(at_least(cash, close, YIELD_MIN), cash, close, cash / close)


def cash_div_ex(ctx: Context, item: lib.Series, s: int, at: int) -> bool | None:
    """J3 第 1 點: None when it cannot be told (does not qualify)."""

    return cash_div_parts(ctx, item, s, at).qualifies


def _liq_prefix(ctx: Context, item: lib.Series) -> tuple[Any, Any, Any, Any]:
    parts = ctx.liq.get(item.instrument_id)
    if parts is None:
        closes = item.close
        turnover = ctx.base.turnover.get(item.instrument_id)
        total, positive = array("d", [0.0]), array("i", [0])
        bad_close, bad_turnover = array("i", [0]), array("i", [0])
        s_total, n_positive, n_close, n_turnover = 0.0, 0, 0, 0
        for k, close in enumerate(closes):
            good = close > 0  # NaN fails too
            n_close += not good
            value = turnover[k] if turnover is not None else lib.NAN
            n_turnover += not (value > 0)
            a = 0.0
            if k and good and closes[k - 1] > 0 and value > 0:
                a = abs(close / closes[k - 1] - 1.0) / value
            s_total += a
            n_positive += a > 0
            total.append(s_total)
            positive.append(n_positive)
            bad_close.append(n_close)
            bad_turnover.append(n_turnover)
        parts = (total, positive, bad_close, bad_turnover)
        ctx.liq[item.instrument_id] = parts
    return parts


def liq_parts(ctx: Context, item: lib.Series, at: int) -> tuple[float, float] | None:
    """J4 第 1、2、4 點: (illiq_20, illiq_base), or None when missing."""

    first = at - ILLIQ_RECENT - ILLIQ_BASE  # the first of the 261 closes
    if first < 0:
        return None
    if item.suspended[at + 1] != item.suspended[first]:
        return None  # a suspended bar in first .. at
    total, positive, bad_close, bad_turnover = _liq_prefix(ctx, item)
    if bad_close[at + 1] != bad_close[first]:
        return None
    if bad_turnover[at + 1] != bad_turnover[first + 1]:
        return None  # the 260 turnovers of first + 1 .. at
    split = at + 1 - ILLIQ_RECENT  # the first of the recent bars
    if positive[split] == positive[first + 1]:
        return None  # every a of the base is 0: illiq_base is 0
    recent = (total[at + 1] - total[split]) / ILLIQ_RECENT
    base = (total[split] - total[first + 1]) / ILLIQ_BASE
    if not base > 0:
        return None
    return max(recent, 0.0), base


def liq_shock_20(ctx: Context, item: lib.Series, at: int) -> float | None:
    """J4 第 3 點: 1 − illiq_20 ÷ illiq_base."""

    parts = liq_parts(ctx, item, at)
    if parts is None:
        return None
    return 1.0 - parts[0] / parts[1]


# --- J1, J2 and J4: the portfolio engine ------------------------------------------


order_key = r5.order_key
_window_facts = r5._window_facts


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value (or, for J3,
    the sessions after a signal date), or None (``round11_research``'s
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
    rows: list[tuple[int, dict[str, Any], str]]
    missing: Counter = field(default_factory=Counter)
    sentiment: Sentiment | None = None  # J1
    excluded: int = 0  # J2: the large caps left out
    positive: int = 0  # J2: members with trust_flow_20 > 0
    hits: int = 0  # J2: members meeting the subset and the condition


def meets(value: float | None, op: str, bound: float) -> bool:
    """Strictly beyond ``bound``; a missing value fails."""

    if value is None:
        return False
    return value > bound if op == ">" else value < bound


def state_of(sentiment: Sentiment) -> str | None:
    if sentiment.high is None:
        return None
    return "high" if sentiment.high else "low"


def rank_j1(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """J1 第 1～4 點: the population by ``vol_60`` in the day's state's
    direction; none when ``margin_sent_60`` is missing."""

    t0 = time.perf_counter()
    sentiment = margin_sent_60(members)
    ctx.seconds["margin_sent_60"] += time.perf_counter() - t0
    out = Ranked([], sentiment=sentiment)
    rows = []
    t0 = time.perf_counter()
    for item, at in members:
        value = vol_60(ctx, item, at)
        out.missing["vol_60"] += value is None
        rows.append(
            (
                item.instrument_id,
                {"vol_60": value},
                pr.tie_break(day, item.instrument_id),
            )
        )
    ctx.seconds["vol_60"] += time.perf_counter() - t0
    state = state_of(sentiment)
    if state is None:
        return out  # 第 3 點: an empty list, the accounts keep the cash
    keys = tuple(spec["keys"][state])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    for _id, values, _tie in rows:
        values["state"] = state
        values["margin_sent_60"] = sentiment.value
    out.rows = rows
    return out


def rank_j2(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """J2 第 1～4 點: the population less ``turnover_60``'s top 150 (and the
    missing ones), with ``trust_flow_20`` > 0, high first."""

    out = Ranked([])
    rows = []
    for item, at in members:
        t0 = time.perf_counter()
        turnover = turnover_60(ctx, item, at)
        t1 = time.perf_counter()
        trust = trust_flow_20(item, at)
        ctx.seconds["turnover_60"] += t1 - t0
        ctx.seconds["trust_flow_20"] += time.perf_counter() - t1
        out.missing["turnover_60"] += turnover is None
        out.missing["trust_flow_20"] += trust is None
        out.positive += meets(trust, ">", TRUST_MIN)
        rows.append(
            (
                item.instrument_id,
                {"turnover_60": turnover, "trust_flow_20": trust},
                pr.tie_break(day, item.instrument_id),
            )
        )
    t0 = time.perf_counter()
    name, size = spec["exclude"]
    valued = [row for row in rows if row[1][name] is not None]
    valued.sort(key=lambda row: (-row[1][name], row[2]))
    large = {row[0] for row in valued[:size]}
    out.excluded = len(large)
    kept = [
        row
        for row in valued
        if row[0] not in large
        and all(meets(row[1][key], op, bound) for key, op, bound in spec["conditions"])
    ]
    keys = tuple(spec["keys"])
    kept.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.hits = len(kept)
    out.rows = kept  # 第 4 點: fewer than 20 leave cash, nothing filled up
    ctx.seconds["j2_order"] += time.perf_counter() - t0
    return out


def rank_j4(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """J4 第 5 點: the population, ``liq_shock_20`` high first, missing last."""

    out = Ranked([])
    rows = []
    t0 = time.perf_counter()
    for item, at in members:
        value = liq_shock_20(ctx, item, at)
        out.missing["liq_shock_20"] += value is None
        rows.append(
            (
                item.instrument_id,
                {"liq_shock_20": value},
                pr.tie_break(day, item.instrument_id),
            )
        )
    ctx.seconds["liq_shock_20"] += time.perf_counter() - t0
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    return out


def ranker(name: str) -> Callable[..., Ranked]:
    return {"J1": rank_j1, "J2": rank_j2, "J4": rank_j4}[name]


def v1_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """V1's list on ``day`` (``round5_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r5.HYPOTHESES[V1]
    rows = r5.rank(ctx.v1, spec, day, members).rows
    ctx.seconds["v1_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def z1_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """Z1's list on ``day`` (``round8_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r8.HYPOTHESES[Z1]
    rows = r8.rank(ctx.z1, spec, day, members).rows
    ctx.seconds["z1_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


overlap_with = {"J1": v1_names, "J4": z1_names}
PICK_FIELDS = {
    "J1": ("state", "margin_sent_60", "vol_60"),
    "J2": ("turnover_60", "trust_flow_20"),
    "J4": ("liq_shock_20",),
}


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    overlap: dict[str, list[float]] = field(default_factory=dict)  # J1, J4, by year
    states: dict[int, str | None] = field(default_factory=dict)  # J1, by T's index


def _coverage_add(
    coverage: dict[str, Any], name: str, day: date, members: int, r: Ranked
) -> None:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += members
    for key, count in r.missing.items():
        year["missing"][key] = year["missing"].get(key, 0) + count
    if name == "J1":
        state = "state_" + (state_of(r.sentiment) or "missing")
        year[state] = year.get(state, 0) + 1
        year["margin_members"] = year.get("margin_members", 0) + r.sentiment.members
    elif name == "J2":
        top = HYPOTHESES[name]["top"]
        year["positive"] = year.get("positive", 0) + r.positive
        year["min_positive"] = min(year.get("min_positive", r.positive), r.positive)
        year["max_positive"] = max(year.get("max_positive", 0), r.positive)
        year["hits"] = year.get("hits", 0) + r.hits
        year["max_hits"] = max(year.get("max_hits", 0), r.hits)
        year["short_days"] = year.get("short_days", 0) + (r.hits < top)
        year["zero_days"] = year.get("zero_days", 0) + (r.hits == 0)
        year["excluded"] = year.get("excluded", 0) + r.excluded


def switches(states: list[str | None]) -> int:
    """J1 第 6 點: how many times the state differs from the one of the
    signal date before with a state (a missing day is skipped)."""

    count, previous = 0, None
    for state in states:
        if state is None:
            continue
        if previous is not None and state != previous:
            count += 1
        previous = state
    return count


def plan(
    ctx: Context, spec: dict[str, Any], name: str, first: int, last: int, keep_rows=True
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    rank = ranker(name)
    previous: str | None = None
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        ranked = rank(ctx, spec, day, members)
        _coverage_add(out.coverage, name, day, len(members), ranked)
        out.signal_days += 1
        if name == "J1":
            state = state_of(ranked.sentiment)
            out.states[at] = state
            if state is not None:
                year = out.coverage[str(day.year)]
                year["switches"] = year.get("switches", 0) + (
                    previous is not None and state != previous
                )
                previous = state
        if name in overlap_with:
            other = overlap_with[name](ctx, day, members)  # timed in the coverage too
            if keep_rows:
                share = r10.overlap_share([row[0] for row in ranked.rows[:top]], other)
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


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary


def state_summary(
    states: dict[int, str | None], sessions: list[date]
) -> dict[str, Any]:
    """J1 第 6 點: the signal dates in each state, by year and in all, and the
    switches."""

    years: dict[str, Counter] = {}
    for at, state in sorted(states.items()):
        years.setdefault(str(sessions[at].year), Counter())[state or "missing"] += 1
    total = Counter()
    for counts in years.values():
        total.update(counts)
    days = sum(total.values())

    def shares(counts: Counter) -> dict[str, Any]:
        n = sum(counts.values())
        return {
            key: {"days": counts[key], "share": counts[key] / n if n else None}
            for key in ("high", "low", "missing")
        }

    return {
        "days": days,
        **shares(total),
        "switches": switches([state for _at, state in sorted(states.items())]),
        "years": {year: shares(counts) for year, counts in sorted(years.items())},
    }


def state_excess(
    differences: list[float], states: dict[int, str | None], first: int, hold: int
) -> dict[str, Any]:
    """J1 第 6 點 (listed only): the daily excess over the population of each
    equity session e = ``first + i`` by the states of the signal dates whose
    lists the accounts hold, W(e) = max(first − 1, e − hold) .. e − 1
    (``STATE_OF_DAY``): all high, all low or all missing goes there, any
    other mix to "mixed".  A sale delayed past its due date is not in W(e)."""

    groups: dict[str, list[float]] = {"high": [], "low": [], "missing": [], "mixed": []}
    for i, value in enumerate(differences):
        e = first + i
        seen = {states.get(t) for t in range(max(first - 1, e - hold), e)}
        key = (next(iter(seen)) or "missing") if len(seen) == 1 else "mixed"
        groups[key].append(value)
    return {key: pr.excess_metrics(values) for key, values in groups.items()}


def short_summary(coverage: dict[str, Any]) -> dict[str, Any]:
    """J2 第 6 點: the signal dates with fewer than 20 qualified and with none."""

    return {
        "short_days": sum(row.get("short_days", 0) for row in coverage.values()),
        "zero_days": sum(row.get("zero_days", 0) for row in coverage.values()),
        "years": {
            year: {key: row.get(key, 0) for key in ("days", "short_days", "zero_days")}
            for year, row in sorted(coverage.items())
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
    """J1, J2 or J4 on one segment: its numbers, verdict and private parts."""

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
    if name in overlap_with:
        result["overlap"] = overlap_summary(planned.overlap)
    if name == "J1":
        result["states"] = state_summary(planned.states, sessions)
    if name == "J2":
        result["short"] = short_summary(planned.coverage)
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], spec["top"])
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    returns = pr.daily_returns(mine.equity)
    others = pr.daily_returns(population.equity)
    taiex = ex._taiex(ctx.panel, first, last)
    differences = [a - b for a, b in zip(returns, others)]
    excess = {
        POPULATION: pr.excess_metrics(differences),
        TAIEX: pr.excess_metrics(
            [a - b for a, b in zip(returns, taiex) if b is not None]
        ),
    }
    if name == "J1":
        result["state_excess"] = state_excess(
            differences, planned.states, first, spec["hold"]
        )
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


# --- J3: trade by trade -----------------------------------------------------------


enter_next_open = r9.enter_next_open


@dataclass
class EventState:
    """J3's run: ``trade_research.State`` (the trades, the occupancy) plus the
    signals by year, the fills on a T+1 locked at limit down and the signals
    that are F1's on the same day."""

    state: tr.State
    years: dict[str, Counter] = field(default_factory=dict)
    locked_down_fills: int = 0
    f1_both: int = 0


def _signals(
    ctx: Context, s: int, members: list[tuple[lib.Series, int]]
) -> list[tuple[lib.Series, int, dict[str, Any]]]:
    """J3's signals of signal date ``s`` among ``members`` (item, at, extra)."""

    out = []
    t0 = time.perf_counter()
    for item, at in members:
        parts = cash_div_parts(ctx, item, s, at)
        if parts.qualifies:
            out.append(
                (
                    item,
                    at,
                    {
                        "cash_dividend": parts.cash,
                        "close_before_raw": parts.close,
                        "cash_yield": parts.value,
                        "stock_div_ex": bool(r10.stock_div_ex(ctx, item, s)),
                    },
                )
            )
    ctx.seconds["cash_div_ex"] += time.perf_counter() - t0
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
    for item, at, extra in _signals(ctx, s, members):
        bars = tr.TradeBars(trade, item, s, s_last)
        entry = enter_next_open(bars)
        # J3 第 4 點: a T+1 locked at limit down fills at its open, listed apart
        locked_down = entry.session is not None and bars[0].locked_down
        run.locked_down_fills += locked_down
        run.f1_both += extra["stock_div_ex"]
        row = tr._trade_row(
            trade,
            state,
            s,
            item,
            None,
            bars,
            entry,
            0,
            NO_STOP,
            None,
            s_last,
            {**extra, "t1_locked_down": locked_down},
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
    """J3 on one segment (docs 逐筆評估): its numbers, verdict and trades."""

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
        "t1_locked_down_fills": run.locked_down_fills,
        "f1_both": run.f1_both,
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


# --- --coverage-only for J3 -------------------------------------------------------


def event_coverage(ctx: Context) -> dict[str, Any]:
    """J3: by year the signals (also by exchange) and the signal dates, the
    rows that cannot be told and the signals that are F1's too.  Every
    signal date counts, without the occupancy (nothing is traded)."""

    spec = HYPOTHESES["J3"]
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
            str(day.year),
            {"days": 0, "signal_days": 0, "signals": 0, "members": 0, "rows": 0,
             "unknown": 0, "below": 0, "f1_both": 0, "markets": {}},
        )  # fmt: skip
        year["days"] += 1
        members = lib.universe(panel, day, MIN_LOTS)
        year["members"] += len(members)
        t0 = time.perf_counter()
        for item, at in members:
            parts = cash_div_parts(ctx, item, s, at)
            if parts.qualifies is False and parts.cash is None:
                continue  # no row on T
            year["rows"] += 1
            year["unknown"] += parts.qualifies is None
            year["below"] += parts.qualifies is False
        ctx.seconds["cash_div_ex"] += time.perf_counter() - t0
        signals = _signals(ctx, s, members)
        year["signal_days"] += bool(signals)
        year["signals"] += len(signals)
        for item, _at, extra in signals:
            exchange = panel.symbols.get(item.instrument_id, ("", "", ""))[0]
            m = year["markets"].setdefault(exchange, Counter())
            m["signals"] += 1
            year["f1_both"] += extra["stock_div_ex"]
    out: dict[str, Any] = {
        "window": _window_facts(sessions, window),
        "years": {
            key: {**row, "markets": {e: dict(c) for e, c in row["markets"].items()}}
            for key, row in sorted(years.items())
        },
    }
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
EVENT_FIELDS = {
    "J3": (
        "cash_dividend",
        "close_before_raw",
        "cash_yield",
        "stock_div_ex",
        "t1_locked_down",
    )
}
EVENT_TRADE_TAIL = r10.EVENT_TRADE_TAIL


def event_trade_fields(name: str) -> tuple[str, ...]:
    return ("signal_date", "exchange", "symbol", *EVENT_FIELDS[name], *EVENT_TRADE_TAIL)


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司；"
        f"J3 另要有成交的訊號日至少 {MIN_DAYS} 日（逐筆評估）。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def portfolio_coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """J1: the signal dates of each state, the switches and the days without
    ``margin_sent_60``; J2 第 6、8 點; J4: ``liq_shock_20``'s missing share
    (分母是母體檔次)."""

    if name == "J1":
        head = [
            "年",
            "日數",
            "母體檔次",
            "情緒高（`vol_60` 小者先）",
            "情緒低（`vol_60` 大者先）",
            "`margin_sent_60` 缺值的天數",
            "狀態切換",
            "兩端都有融資的檔次",
            "`vol_60` 缺值",
        ]
    elif name == "J2":
        head = [
            "年",
            "日數",
            "母體檔次",
            "排掉的前 150 名檔次",
            "`turnover_60` 缺值",
            "`trust_flow_20` 缺值",
            "`trust_flow_20` > 0 的檔數（每日平均）",
            "（最少的一天）",
            "（最多的一天）",
            "符合的檔日",
            "一天最多符合",
            "符合的不足 20 檔的訊號日",
            "沒有任何一檔符合的訊號日",
        ]
    else:
        head = ["年", "日數", "母體檔次", "`liq_shock_20` 缺值"]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        missing = row.get("missing", {})
        cells = [f"{days:,}", f"{members:,}"]
        if name == "J1":
            cells += [
                f"{row.get('state_high', 0):,}",
                f"{row.get('state_low', 0):,}",
                f"{row.get('state_missing', 0):,}",
                f"{row.get('switches', 0):,}",
                f"{row.get('margin_members', 0):,}",
                _share(missing.get("vol_60", 0), members),
            ]
        elif name == "J2":
            cells += [
                f"{row.get('excluded', 0):,}",
                _share(missing.get("turnover_60", 0), members),
                _share(missing.get("trust_flow_20", 0), members),
                lib.num(row.get("positive", 0) / days, 1) if days else "—",
                f"{row.get('min_positive', 0):,}",
                f"{row.get('max_positive', 0):,}",
                f"{row.get('hits', 0):,}",
                f"{row.get('max_hits', 0):,}",
                f"{row.get('short_days', 0):,}",
                f"{row.get('zero_days', 0):,}",
            ]
        else:
            cells += [_share(missing.get("liq_shock_20", 0), members)]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def event_coverage_lines(coverage: dict[str, Any]) -> list[str]:
    lines = [
        "| 年 | 訊號日 | 有訊號的日數 | 訊號數 | 上市 | 上櫃 | 母體檔次 | 母體中 T 有除權息列的檔次 "
        "| 其中 `cash_dividend` 是 null 或前一根不可用 | 其中殖利率 < 3% 或現金股利 ≤ 0 "
        "| 訊號中也符合 F1 `stock_div_ex` |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in coverage.get("years", {}).items():
        m = row["markets"]
        lines.append(
            f"| {year} | {row['days']:,} | {row['signal_days']:,} | {row['signals']:,} "
            f"| {m.get('TWSE', {}).get('signals', 0):,} "
            f"| {m.get('TPEx', {}).get('signals', 0):,} | {row['members']:,} "
            f"| {row['rows']:,} | {row['unknown']:,} | {row['below']:,} "
            f"| {row['f1_both']:,} |"
        )
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
        f"# {name} {segment}（round12_research 第 {VERSION} 版，#{DESIGN}）",
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


def _yearly_lines(title: str, note: str, summary: dict[str, Any], fmt) -> list[str]:
    return [
        title,
        "",
        note + "。",
        "",
        f"全段平均：{fmt(summary['mean'])}（{summary['days']:,} 個訊號日）。",
        "",
        "| 年 | 訊號日 | 平均 |",
        "| --- | ---: | ---: |",
        *(
            f"| {year} | {row['days']:,} | {fmt(row['mean'])} |"
            for year, row in summary["years"].items()
        ),
        "",
    ]


def state_lines(result: dict[str, Any]) -> list[str]:
    """J1 第 6 點: the states' shares, the switches and the excess by state."""

    states = result["states"]
    excess = result.get("state_excess") or {}
    labels = {
        "high": "情緒高（`vol_60` 小者先）",
        "low": "情緒低（`vol_60` 大者先）",
        "missing": "`margin_sent_60` 缺值（名單為空）",
        "mixed": "混合（持有的名單跨兩種狀態或含缺值）",
    }
    lines = [
        "## 兩種狀態（J1 第 6 點，只列出、不判定）",
        "",
        f"狀態切換 {states['switches']:,} 次（相鄰兩個有狀態的訊號日不同就算一次，缺值的日子跳過）。"
        "分狀態的超額：有淨值的交易日 e 持有訊號日 W(e)＝max(段首訊號日, e − 20)…e − 1 的名單，"
        "W(e) 裡每個訊號日都是同一個狀態（或都缺值）才歸那一類，其餘歸「混合」；"
        "持有到期後因跌停鎖死、停牌延後賣出的部位不算進 W(e)。",
        "",
        "| 狀態 | 訊號日 | 比例 | 對母體超額的日數 | 日均 | t |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for key, label in labels.items():
        e = excess.get(key) or {}
        days = f"{states[key]['days']:,}" if key in states else "—"
        share = _pct(states[key]["share"], 1) if key in states else "—"
        lines.append(
            f"| {label} | {days} | {share} "
            f"| {e.get('days', 0):,} | {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} |"
        )
    lines += [
        "",
        "| 年 | 情緒高 | 情緒低 | 缺值 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for year, row in states["years"].items():
        lines.append(
            f"| {year} | {row['high']['days']:,}（{_pct(row['high']['share'], 1)}） "
            f"| {row['low']['days']:,}（{_pct(row['low']['share'], 1)}） "
            f"| {row['missing']['days']:,} |"
        )
    lines.append("")
    return lines


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
    if "states" in result:
        lines += state_lines(result)
    if "short" in result:
        short = result["short"]
        lines += [
            "## 符合的檔數（J2 第 6 點，只列出、不判定）",
            "",
            f"符合的不足 20 檔的訊號日 {short['short_days']:,} 日、"
            f"沒有任何一檔符合的訊號日 {short['zero_days']:,} 日（不足的餘額留現金）。",
            "",
            "| 年 | 訊號日 | 不足 20 檔 | 沒有任何一檔 |",
            "| --- | ---: | ---: | ---: |",
            *(
                f"| {year} | {row['days']:,} | {row['short_days']:,} | {row['zero_days']:,} |"
                for year, row in short["years"].items()
            ),
            "",
        ]
    if "overlap" in result:
        other = "V1" if name == "J1" else "Z1"
        point = "J1 第 6 點" if name == "J1" else "J4 第 7 點"
        lines += _yearly_lines(
            f"## 和 {other} 的重疊（{point}）",
            OVERLAP_NOTE[name],
            result["overlap"],
            lambda value: _pct(value, 1),
        )
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
    listed = result.get("listed", {})
    lines += [
        f"| T+1 跌停鎖死、照常以開盤價成交 | {listed.get('t1_locked_down_fills', 0):,} |",
        f"| 同一天也符合 F1 `stock_div_ex` 的訊號 | {listed.get('f1_both', 0):,} |",
    ]
    for reason in tr.EXIT_REASONS:
        if reason in ("stop", "target"):
            continue  # neither
        lines.append(
            f"| 出場：{tr.EXIT_LABELS[reason]} | {_pct(result['exit_share'][reason], 1)}"
            f"（{result['exits'][reason]:,}） |"
        )
    lines += [
        f"| 跌停順延 | {result['limit_delayed']:,} |",
        f"| 停牌順延 | {result['suspension_delayed']:,} |",
        f"| 母體在 e 買不進的檔次 | {result['population_unbought']:,} |",
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
        row = {"engine": TRADE, **tr._row(result)}
        listed = result.get("listed") or {}
        for key in ("t1_locked_down_fills", "f1_both"):
            if key in listed:
                row[key] = listed[key]
        return row
    row = {"engine": PORTFOLIO, **r5._row(result)}
    if "overlap" in result:
        key = "overlap_v1" if result["hypothesis"] == "J1" else "overlap_z1"
        row[key] = {k: result["overlap"][k] for k in ("days", "mean")}
    if "states" in result:
        states = result["states"]
        row["states"] = {
            "high": states["high"],
            "low": states["low"],
            "missing": states["missing"],
            "switches": states["switches"],
        }
        row["state_excess"] = result.get("state_excess")
    if "short" in result:
        row["short"] = {k: result["short"][k] for k in ("short_days", "zero_days")}
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round12_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十二輪：J1～J4」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：J1、J2、J4 是組合引擎（`portfolio_research.simulate`，日數是有淨值的交易日）；"
        "J3 是逐筆評估（`trade_research`，日數是段內交易日，超額與 t 在訊號日序列上）",
        "- J1 的判定只看整體；分狀態的數字只列出",
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
    for name, key, other in (("J1", "overlap_v1", "V1"), ("J4", "overlap_z1", "Z1")):
        overlap = report["hypotheses"].get(name, {}).get(key)
        if overlap:
            lines += [
                "",
                f"{name} 和 {other} 的重疊（只列出）：平均 {_pct(overlap['mean'], 1)}"
                f"（{overlap['days']:,} 個訊號日）。",
            ]
    states = report["hypotheses"].get("J1", {}).get("states")
    if states:
        lines += [
            "",
            f"J1 的兩種狀態（只列出）：情緒高 {states['high']['days']:,} 日、"
            f"情緒低 {states['low']['days']:,} 日、缺值 {states['missing']['days']:,} 日，"
            f"切換 {states['switches']:,} 次。",
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


seconds_lines = r10.seconds_lines

COVERAGE_NOTES = (
    "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；每個訊號日都數，不扣占用（沒有模擬成交）",
    f"- J1：{DEGENERATE['J1']}。狀態切換是相鄰兩個有狀態的訊號日不同的次數（缺值的日子跳過，"
    "切換算在後一天的年份）；`v1_order` 是同一個 T 算 V1 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- J2：{DEGENERATE['J2']}。「`trust_flow_20` > 0 的檔數」在整個母體裡數；"
    "「符合」是排掉前 150 名之後 `trust_flow_20` > 0 的檔（J2 第 6、8 點）",
    f"- J3：{DEGENERATE['J3']}。訊號數是母體中 `cash_div_ex` 成立的檔次；"
    "「`cash_dividend` 是 null 或前一根不可用」是 T 有除權息列、但那天的 `cash_dividend` 全是 null，"
    "或前一根停牌、未還原收盤缺值或 ≤ 0 的檔次（都不符合）",
    f"- J4：{DEGENERATE['J4']}。`z1_order` 是同一個 T 算 Z1 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 J1～J4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round12_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、逐筆的標的狀態 "
        f"{load_seconds.get('trade', 0):.0f} 秒、除權息 {load_seconds.get('actions', 0):.0f} 秒），"
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
            lines += [
                "### J3：依年的訊號數與訊號日數",
                "",
                *event_coverage_lines(row["coverage"]),
                "",
            ]
        else:
            lines += [*portfolio_coverage_lines(name, row["coverage"]), ""]
            if name == "J1":
                lines += [
                    f"狀態切換（全段）：{row.get('switches', 0):,} 次。",
                    "",
                ]
    lines += [
        "有明顯斷點，或缺值比例有異常的年份或欄位時，先在工具單提問、不跑探索段。",
        "",
    ]
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
            coverage = event_coverage(ctx)
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
            if name == "J1":
                row["switches"] = sum(
                    year.get("switches", 0) for year in row["coverage"].values()
                )
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
    parser = argparse.ArgumentParser(prog="round12_research.py", description=__doc__)
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
        "year and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): J1, J2, J3, J4 or "
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
    command = "python tools/research/round12_research.py " + " ".join(argv)
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
