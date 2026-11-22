"""Round 14 of the new-strategy exploration: K1～K3 (#978).

docs/spec/evidence.md 第十四輪：K1～K3 and 第十四輪實作釋義: the hypotheses
were registered (commit ``50528962``, #972, decision 7084903074) before anyone
ran a tool on the backfilled history.  Nothing here is a command-line option:
a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round13_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  All three trade on the portfolio engines
with the population, the loading (``explore_research.load_context``),
``explore_judge``, the gate and the ledgers imported: K1 and K3 on
``portfolio_research.simulate`` (K accounts), K2 on X7's event-day account
(``explore_research.simulate_events``).  ``row_cash`` (``round5_research``),
``_quarter_eps`` (``feature_evidence``), the corporate actions
(``research_report.load_actions``), the market gaps and the window rule
(``round13_research``) are imported too.  The overlaps take J3, X4 and U1
from ``round12_research``, ``explore_research`` and ``round13_research``
(their current versions) on the same T, and ``round10_research``'s
``overlap_share``／``overlap_summary``.  New here are only ``div_initiation``
with K1's event lists, ``eps_turn`` with K2's quarterly event days,
``inst_sell_5q``, K1's floor of event days with a fill and the overlaps.

Each signal date T (after its close, only T's data and before):

- K1: ``div_initiation`` (a cash dividend going ex on T after 3 years
  without one, 3 years after the first bar); at most 20 by the hash, each
  1/n of T's account (K 240); the population bought by the same account on
  the same event days.
- K2: on the 4 statutory deadlines, ``eps_turn`` (the latest quarter's own
  EPS > 0, the same quarter's a year before < 0, the latest being the
  deadline's quarter), 20 by the hash, held to the next event day (X7).
- K3: ``inst_sell_5q`` (foreign + trust net buys < 0 in each of the 5 blocks
  of 60 bars to T), 20 by the hash, K 120.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.317 (55 hypotheses) on the validation; K1 also
needs 60 event days with a fill per segment.  Before the used segment is
loaded the validation's panel is let go (PR #905 review).
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
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round10_research as r10  # noqa: E402
import round12_research as r12  # noqa: E402
import round13_research as r13  # noqa: E402

VERSION = 1
DESIGN = "978"
TOOL = "round14_research"
REGISTRATION_COMMIT = "50528962"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/972#issuecomment-7084903074"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十四輪 門檻: 1 − Φ(z) = 0.025 ÷ 55, z = 3.3172, 3.317 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.317
ROUND = 14
ROUND_SIZE = 3
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3, K1～K3
CUMULATIVE = 55
# Every segment reads the copy from its start, as round10_research ..
# round13_research: K1 reads the dividends of the 3 years before T and the
# first bar, K3 300 bars.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO = "portfolio"
EVENTS = "events"

# 共同 排序與同分: not ranked; the first N by sha256("<T>:<instrument_id>")
# (portfolio_research.tie_break); a condition that cannot be told fails.
ORDER = "not ranked: the first N by sha256(<T>:<instrument_id>); missing fails"
SHORT_RULE = "cash, not filled"

# K1 (第 1～5 點, 統籌決定 7084903074)
GAP_DAYS = 1095  # ②: no cash in [d − 1,095 calendar days, d)
LISTED_DAYS = 1095  # ③: the first bar ≤ T − 1,095 calendar days
CASH_MIN = 0.0  # ① cash_dividend > 0 and ② row_cash > 0, strictly
SAME_DAY = (
    "rows going ex on T: action_date = T, or an action_date that is no session "
    "rolled to the next session; several take the largest cash_dividend, d its "
    "action_date (the earliest of equal ones)"
)
ROW_CASH = (
    "round5_research.row_cash: cash_dividend when not null; 0 when it is null "
    "and stock_dividend_ratio or split_ratio is not; unknown when the three are null"
)
NULL_RULE = "a row with the three fields null in [d - 1095, d): does not qualify"
WEIGHT = (
    "each of the n names taken (the first 20 by the hash, before buying) is "
    "1/n of T's account's cash; a name not bought leaves its share in cash; "
    "no event leaves the account in cash"
)
BENCHMARK = (
    "the population: the same account on the same event days buys T's whole "
    "population, 1/n each; a name not bought leaves its share in cash"
)
MIN_FILL_DAYS = 60  # K1 第 5 點: per segment, or 無法判定
FILL_RULE = "a signal date T on which the hypothesis bought at least one name"

# K2 (第 1～4 點): (month, day) of the deadline, the month its quarter ends and
# that quarter's year less the deadline's
DEADLINES = ((3, 31, 12, -1), (5, 15, 3, 0), (8, 14, 6, 0), (11, 14, 9, 0))
EPS_MIN = 0.0  # the latest > 0 and the year before's < 0, strictly
# #978 決定 7086393113: a deadline on a Saturday make-up session is put off to
# the next Monday～Friday session, as the copy's announcement_date is.
EVENT_DAY_RULE = (
    "the first Monday-to-Friday session on or after the deadline; a Saturday "
    "make-up session is skipped"
)
LATEST_RULE = (
    "the latest quarter known on T (announcement_date <= T, the largest period "
    "end) must be the deadline's quarter; feature_evidence._quarter_eps gives "
    "its own EPS and the same quarter's a year before, both needed"
)
SALE = (
    "one account (X7): bought at T+1's open, sold at the close of the next "
    "event day T' (explore_research.simulate_events), the new list bought at "
    "T'+1's open; the population on the same rule and event days"
)

# K3 (第 1～3 點)
BLOCK = 60
BLOCKS = 5  # at − 299 .. at, the item's own bars
FLOW_COLUMNS = ("foreign_buy", "trust_buy")  # no dealer_buy (統籌決定 7084903074)
SELL_MAX = 0.0  # each block's sum < 0, strictly
FLOW_NULL = "a null column counts 0; a bar without trading counts 0"
WINDOW_RULE = (
    "round13_research.window_of: fewer than 300 bars, a suspended one, or one "
    "on a session of the item's market gap is missing"
)
INST_ANCHOR = date(2014, 12, 1)  # the OTC institutional table's first day
K1_START = date(2010, 12, 2)
K2_START = date(2014, 5, 15)
J3, X4, U1 = "J3", "X4", "U1"  # the lists K1, K2 and K3 overlap with

# The registration (docs 第十四輪：K1～K3), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "K1": {
        "engine": PORTFOLIO,
        "direction": "事件：開始配息",
        "label": "T 日是現金股利除息交易日、之前 3 年沒有配現金、上市已滿 3 年"
        "（`div_initiation`），T 日那一份子帳戶等權買進當天的事件",
        "rule": "event_list",
        "conditions": (("div_initiation", "is", True),),
        "order": "the hash only",
        "short": SHORT_RULE,
        "weight": "1/n",
        "benchmark": "the population on the event days only",
        "top": 20,
        "hold": 240,
        "start": ("date", K1_START),
    },
    "K2": {
        "engine": EVENTS,
        "direction": "事件：由虧轉盈",
        "label": "每季法定期限的事件日，最新一季單季 EPS > 0、去年同季單季 EPS < 0"
        "（`eps_turn`），以雜湊取 20 檔、不排序；持有到下一個事件日",
        "rule": "quarterly",
        "conditions": (("eps_turn", "is", True),),
        "order": "the hash only",
        "short": SHORT_RULE,
        "top": 20,
        "hold": "next_event",
        "start": ("date", K2_START),
    },
    "K3": {
        "engine": PORTFOLIO,
        "direction": "籌碼：法人持續賣超",
        "label": "`inst_sell_5q`（外資＋投信最近 5 個 60 根區塊每一塊的淨買超合計都 < 0）"
        "成立，以雜湊取 20 檔、不排序",
        "rule": "daily",
        "conditions": (("inst_sell_5q", "is", True),),
        "order": "the hash only",
        "short": SHORT_RULE,
        "top": 20,
        "hold": 120,
        "start": ("session", INST_ANCHOR, BLOCK * BLOCKS),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = {
    **ex.REASONS,
    "too_few_event_days": f"有成交的事件日不足 {MIN_FILL_DAYS} 日",
}
LIMITS = {
    "K1": "持有 240 日（K＝240）是前十三輪最長的持有：各段最後約一年的事件持有不滿 240 日，"
    "部位以段末收盤計，每日報酬照實算；事件集中在除息旺季，n 常常很小，名單集中；"
    "轉板的標的（研究 DB 裡上市、上櫃是兩個標的）因為條件③，在轉板後 3 年內不符合；"
    "Boehme & Sorescu 指出這個漂移對方法敏感",
    "K2": "只看符號，不看 EPS 的大小與殖利率，名單可能和 X4 重疊，看和 X4 的重疊比例；"
    "金融業等法定期限不同的公司不會符合；下市與轉板標的共 76 個公司年缺 EPS",
    "K3": "方向和 X3、X6、L2、J2、U2 相反（它們買短期流入的一邊），由文獻事先定；"
    "被持續賣超的公司可能真的在變差、之後下市，研究 DB 含下市公司，照算",
}
# The degenerate cases as the code judges them (第十四輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "K1": "T 日沒有 `cash_dividend` > 0 的列（`action_date` 不是交易日的列算之後第一個交易日，"
    "同一天多列取最大，d 是那一列的 `action_date`）、窗口 [d − 1,095, d) 內有 `row_cash` > 0 的列、"
    "窗口內有三欄都是 null 的列，或第一根日線晚於 T − 1,095 個日曆日時，不符合；"
    "只看 T 日母體內的檔；事件超過 20 檔時以雜湊取前 20 名，沒有事件的日子那份子帳戶留現金",
    "K2": "最新一季（`announcement_date` ≤ T、期末最晚的一季）不是事件日對應的那一季，"
    "或兩季中任一季沒有單季值時，不符合；符合的不足 20 檔時餘額留現金",
    "K3": "300 根中任一根停牌、不足 300 根，或窗口內有市場整天沒有法人資料的日子時，不符合；"
    "5 塊中任一塊的合計（外資＋投信，沒有法人進出的根與 null 的欄算 0）≥ 0 時也不符合；"
    "符合的不足 20 檔時餘額留現金",
}
OVERLAP_NOTE = {
    "K1": "K1 與 J3（`round12_research` 第 1 版的 `cash_div_ex`，同一個 T 算）每個事件日的重疊檔數："
    "K1 當天名單（前 20 名）中 `cash_div_ex` 也成立的檔數；沒有事件的日子不計。只列出、不判定",
    "K2": 'K2 與 X4（`explore_research` 第 2 版的 `HYPOTHESES["X4"]`，同一個 T 算）每個事件日名單的重疊比例：'
    "|K2 的名單 ∩ X4 的前 20 名| ÷ K2 當天的名單檔數；K2 或 X4 當天沒有名單的事件日不計。"
    "只列出、不判定",
    "K3": 'K3 與 U1（`round13_research` 第 1 版的 `HYPOTHESES["U1"]`，同一個 T 算）每日名單的重疊比例：'
    "|K3 的名單 ∩ U1 的前 20 名| ÷ K3 當天的名單檔數；K3 或 U1 當天沒有名單的日子不計。"
    "只列出、不判定",
}
FEATURE_LABELS = {
    "div_initiation": "停發 3 年後開始配息",
    "eps_turn": "單季 EPS 由虧轉盈",
    "inst_sell_5q": "外資＋投信 5 個 60 根區塊都賣超",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "order": ORDER,
        "short": SHORT_RULE,
        "features": {
            "div_initiation": {
                "gap_days": GAP_DAYS,
                "listed_days": LISTED_DAYS,
                "cash_min": CASH_MIN,
                "same_day": SAME_DAY,
                "row_cash": [ROW_CASH, r5.VERSION, r5.DESIGN],
                "null": NULL_RULE,
                "weight": WEIGHT,
                "benchmark": BENCHMARK,
                "min_fill_days": MIN_FILL_DAYS,
                "fill": FILL_RULE,
            },
            "eps_turn": {
                "deadlines": DEADLINES,
                "event_day": EVENT_DAY_RULE,
                "eps_min": EPS_MIN,
                "latest": LATEST_RULE,
                "quarter_eps": "feature_evidence._quarter_eps",
                "feature_evidence": features.VERSION,
                "sale": SALE,
            },
            "inst_sell_5q": {
                "block": BLOCK,
                "blocks": BLOCKS,
                "columns": list(FLOW_COLUMNS),
                "sell_max": SELL_MAX,
                "null": FLOW_NULL,
                "no_trading": r13.NO_TRADING,
                "market_gap": [r13.MARKET_GAP, list(r13.INSTITUTIONS)],
                "window": WINDOW_RULE,
            },
            "overlaps": {
                J3: [r12.HYPOTHESES[J3], r12.VERSION, r12.DESIGN, r12.YIELD_MIN],
                X4: [ex.HYPOTHESES[X4], ex.VERSION],
                U1: [r13.HYPOTHESES[U1], r13.VERSION, r13.DESIGN],
            },
        },
        "limit": [
            str(er.LIMIT_BEFORE_WIDENING),
            str(er.LIMIT_WIDENED_ON),
            str(er.LIMIT),
        ],  # exit_research.daily_limit by the bar's date (#922)
        "segments": SEGMENTS,
        "min_segment_days": MIN_SEGMENT_DAYS,
        "min_t": MIN_T,
        "validation_min_t": VALIDATION_MIN_T,
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
        "load": LOAD_RULE,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definitions, the
    3-year windows, N and K, K1's weights, benchmark and floor of event days,
    row_cash's rule, K2's deadlines and quarter rule, K3's blocks, columns and
    missing rules, the order, the overlaps' lists, the segments, the costs).
    A changed tool needs a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


def first_cash(
    sessions: list[date], actions: dict[int, r5.Actions]
) -> dict[int, dict[int, tuple[float, date]]]:
    """K1 ①: by instrument and session (a date that is no session is the next
    one), the largest ``cash_dividend`` > 0 going ex there and its date
    (``row_cash`` is ``cash_dividend`` whenever that is not null)."""

    out: dict[int, dict[int, tuple[float, date]]] = {}
    for instrument_id, rows in actions.items():
        for day, cash in zip(rows.dates, rows.cash):
            if cash is None or not cash > CASH_MIN:
                continue
            s = bisect_left(sessions, day)
            if s >= len(sessions):
                continue
            days = out.setdefault(instrument_id, {})
            if s not in days or cash > days[s][0]:  # rows by date: the earliest kept
                days[s] = (cash, day)
    return out


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes,
    X4's features), the actions by ``row_cash`` (K1), the contexts
    ``round12_research`` and ``round13_research`` judge J3 and U1 with (the
    same base; the market gaps K3 uses are U1's).  One panel."""

    base: ex.Context
    actions: dict[int, r5.Actions] = field(default_factory=dict)
    j3: r12.Context | None = None
    u1: r13.Context | None = None
    cash: dict[int, dict[int, tuple[float, date]]] = field(default_factory=dict)
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # K3: per instrument, prefix sums of foreign_buy + trust_buy (a null 0;
    # shares are whole numbers, so the sums and their differences are exact)
    flows: dict[int, array] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.j3 is None:
            self.j3 = r12.Context(self.base)
        if self.u1 is None:
            self.u1 = r13.Context(self.base)
        if not self.cash:
            self.cash = first_cash(self.panel.sessions, self.actions)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the fundamentals and the corporate actions
    to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    gaps = r13.market_gaps(base.market.panel)
    gap_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    report = lib.research_report()
    holders = {
        instrument_id: report.Instrument() for instrument_id in base.market.panel.series
    }
    report.load_actions(db, holders, start, raw_dir, end)
    sessions = base.market.panel.sessions
    actions = {
        instrument_id: r5.actions_of(holder.actions)
        for instrument_id, holder in holders.items()
        if holder.actions
    }
    j3 = r12.Context(base, None, r12.cash_dividends(sessions, holders))
    del holders
    u1 = r13.Context(base, None, gaps)
    return Context(
        base,
        actions,
        j3,
        u1,
        load_seconds={
            "panel": panel_seconds,
            "market_gaps": gap_seconds,
            "actions": time.monotonic() - t0,
        },
    )


# --- features ---------------------------------------------------------------------


@dataclass(frozen=True)
class Initiation:
    qualifies: bool
    candidate: bool = False  # ① holds
    paid: bool = False  # ②: a row_cash > 0 in the window
    null: bool = False  # ②: a row with the three fields null in the window
    young: bool = False  # ③ fails
    cash: float | None = None
    day: date | None = None  # d


def div_initiation(ctx: Context, item: lib.Series, s: int, day: date) -> Initiation:
    """K1 第 1、2 點 on session ``s`` (``day`` is T)."""

    entry = ctx.cash.get(item.instrument_id, {}).get(s)
    if entry is None:
        return Initiation(False)
    cash, d = entry
    rows = ctx.actions[item.instrument_id]
    lo = bisect_left(rows.dates, d - timedelta(days=GAP_DAYS))
    hi = bisect_left(rows.dates, d)
    window = rows.cash[lo:hi]
    paid = any(value is not None and value > CASH_MIN for value in window)
    null = any(value is None for value in window)
    young = not item.dates or item.dates[0] > day - timedelta(days=LISTED_DAYS)
    return Initiation(not (paid or null or young), True, paid, null, young, cash, d)


@dataclass(frozen=True)
class Turn:
    qualifies: bool
    reason: str | None = None  # "stale" or "no_single"
    now: float | None = None
    before: float | None = None


def quarter_events(sessions: list[date]) -> list[tuple[int, date]]:
    """K2 第 1 點: (index of the first Monday～Friday session from each
    deadline, the end of the deadline's quarter), in date order; a Saturday
    make-up session is skipped (#978 決定 7086393113)."""

    if not sessions:
        return []
    out: list[tuple[int, date]] = []
    for year in range(sessions[0].year, sessions[-1].year + 1):
        for month, day, end_month, offset in DEADLINES:
            at = bisect_left(sessions, date(year, month, day))
            while at < len(sessions) and sessions[at].weekday() >= 5:
                at += 1
            if at >= len(sessions) or (out and out[-1][0] >= at):
                continue
            end_day = 31 if end_month in (3, 12) else 30
            out.append((at, date(year + offset, end_month, end_day)))
    return out


def eps_turn(item: lib.Series, at: int, quarter: date) -> Turn:
    """K2 第 2、3 點 on the item's bar ``at`` (T) for the deadline's ``quarter``."""

    day = item.dates[at]
    known = bisect_right(item.quarters, day, key=lambda row: row[0])
    ends = [end for _announced, end, _eps in item.quarters[:known]]
    if not ends or max(ends) != quarter:
        return Turn(False, "stale")
    parts = features._quarter_eps(item, at)
    if parts is None or parts[1] is None:
        return Turn(False, "no_single")
    now, before = parts
    return Turn(now > EPS_MIN and before < -EPS_MIN, None, now, before)


def _flow_prefix(ctx: Context, item: lib.Series) -> array:
    parts = ctx.flows.get(item.instrument_id)
    if parts is None:
        parts = array("d", [0.0])
        total = 0.0
        columns = [item.chips.get(name) for name in FLOW_COLUMNS]
        for k in range(len(item.dates)):
            for column in columns:
                if column is not None:
                    value = column[k]
                    if value == value:  # a null column counts 0
                        total += value
            parts.append(total)
        ctx.flows[item.instrument_id] = parts
    return parts


@dataclass(frozen=True)
class Selling:
    qualifies: bool
    reason: str | None = None  # "short", "suspended", "market_gap" or None
    blocks: tuple[float, ...] = ()


def inst_sell_5q(ctx: Context, item: lib.Series, at: int) -> Selling:
    """K3 第 1～3 點: at − 299 .. at in 5 blocks of 60, each Σ foreign + trust < 0."""

    window = r13.window_of(ctx.u1, item, at, BLOCK * BLOCKS)
    if window.first is None:
        return Selling(False, window.reason)
    flows = _flow_prefix(ctx, item)
    blocks = tuple(
        flows[window.first + BLOCK * (j + 1)] - flows[window.first + BLOCK * j]
        for j in range(BLOCKS)
    )
    return Selling(all(value < SELL_MAX for value in blocks), None, blocks)


# --- the plans --------------------------------------------------------------------


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None.
    K2's equity starts the session after its first event day in the segment
    (as X7's)."""

    first_day, last_day = SEGMENTS[segment]
    last = bisect_left(sessions, last_day + timedelta(days=1)) - 1
    if first_day is None:
        base = ex.start_index(sessions, spec["start"])
        if base is None:
            return None
    else:
        base = max(bisect_left(sessions, first_day), 1) - 1
    if spec["rule"] == "quarterly":
        events = [at for at, _q in quarter_events(sessions) if at >= base]
        if not events:
            return None
        base = events[0]
    first = base + 1
    return (first, last) if first <= last else None


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    dues: dict[int, int] = field(default_factory=dict)  # K2
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    event_days: int = 0  # K1: signal dates with a list; K2: event days
    overlap: dict[str, list[float]] = field(default_factory=dict)
    events: dict[str, list[float]] = field(default_factory=dict)  # K1, by year
    hits: dict[str, list[float]] = field(default_factory=dict)  # K2, K3 by year
    rebalances: list[dict[str, Any]] = field(default_factory=list)  # K2
    flags: list[int] = field(default_factory=list)  # K1: a list on each signal date


def _year(coverage: dict[str, Any], day: date, members: int) -> dict[str, Any]:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0})
    year["days"] += 1
    year["members"] += members
    return year


def _add(row: dict[str, Any], key: str, value: int) -> None:
    row[key] = row.get(key, 0) + value


def _pick_row(ctx: Context, day: date, rank: int, instrument_id: int, values, tie):
    exchange, symbol, _ = ctx.panel.symbols.get(instrument_id, ("", "", ""))
    return {
        "signal_date": day.isoformat(),
        "rank": rank,
        "exchange": exchange,
        "symbol": symbol,
        **values,
        "tie": tie[:12],
    }


def j3_overlap(ctx: Context, s: int, chosen: list[tuple[lib.Series, int]]) -> int:
    """K1 第 8 點: how many of the day's list also have ``cash_div_ex`` (J3,
    ``round12_research`` 第 1 版) on the same T."""

    t0 = time.perf_counter()
    count = sum(bool(r12.cash_div_ex(ctx.j3, item, s, at)) for item, at in chosen)
    ctx.seconds["cash_div_ex"] += time.perf_counter() - t0
    return count


def plan_k1(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """K1 第 1～4 點 on the signal dates ``first − 1`` .. ``last − 1``: the
    events of T's population, at most 20 by the hash; the population bought
    on those dates only."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        found = []
        for item, k in members:
            parts = div_initiation(ctx, item, at, day)
            if not parts.candidate:
                continue
            _add(year, "candidates", 1)
            _add(year, "paid", parts.paid)
            _add(year, "null", parts.null)
            _add(year, "null_only", parts.null and not parts.paid and not parts.young)
            _add(year, "young", parts.young)
            if parts.qualifies:
                found.append((pr.tie_break(day, item.instrument_id), item, k, parts))
        ctx.seconds["div_initiation"] += time.perf_counter() - t0
        found.sort(key=lambda row: row[0])
        chosen = found[:top]
        _add(year, "events", len(found))
        _add(year, "event_days", bool(found))
        _add(year, "capped_days", len(found) > top)
        year["max_events"] = max(year.get("max_events", 0), len(found))
        out.flags.append(1 if chosen else 0)
        if not chosen:
            continue
        out.event_days += 1
        overlap = j3_overlap(ctx, at, [(item, k) for _t, item, k, _p in chosen])
        if not keep_rows:
            continue
        key = str(day.year)
        out.events.setdefault(key, []).append(len(found))
        out.overlap.setdefault(key, []).append(overlap)
        out.picks[at + 1] = [item.instrument_id for _t, item, _k, _p in chosen]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (tie, item, _k, parts) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"cash_dividend": parts.cash, "action_date": parts.day.isoformat(),
                     "events": len(found)},
                    tie,
                )
            )  # fmt: skip
    _invested_estimate(out, spec["hold"], panel.sessions, first)
    return out


def _invested_estimate(out: Plan, hold: int, sessions: list[date], first: int) -> None:
    """K1's coverage (no price read): on each session, the signal dates with a
    list among the ``hold`` before it ÷ ``hold``, by year."""

    total = 0
    for i, flag in enumerate(out.flags):
        total += flag
        if i >= hold:
            total -= out.flags[i - hold]
        year = out.coverage.get(str(sessions[first + i].year))
        if year is None:  # the session after the last signal date's year
            year = out.coverage.setdefault(
                str(sessions[first + i].year), {"days": 0, "members": 0}
            )
        year["invested_sum"] = year.get("invested_sum", 0.0) + total / hold
        year["invested_days"] = year.get("invested_days", 0) + 1


def x4_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """X4's list on ``day`` (``explore_research`` 第 2 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = ex.HYPOTHESES[X4]
    rows, _missing = ex._rank(ctx.base, spec, day, members)
    ctx.seconds["x4_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def plan_k2(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """K2 第 1～4 點: the event days of the segment, ``eps_turn`` in T's
    population, 20 by the hash, held to the next event day (X7)."""

    panel = ctx.panel
    sessions = panel.sessions
    out = Plan()
    top = spec["top"]
    every = quarter_events(sessions)
    following = {at: nxt for (at, _q), (nxt, _n) in zip(every, every[1:])}
    for at, quarter in every:
        if not first - 1 <= at <= last - 1:
            continue
        day = sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        out.event_days += 1
        t0 = time.perf_counter()
        found, reasons = [], Counter()
        for item, k in members:
            turn = eps_turn(item, k, quarter)
            reasons[turn.reason] += 1
            if turn.qualifies:
                found.append((pr.tie_break(day, item.instrument_id), item, turn))
        ctx.seconds["eps_turn"] += time.perf_counter() - t0
        found.sort(key=lambda row: row[0])
        chosen = found[:top]
        for key in ("stale", "no_single"):
            _add(year, key, reasons[key])
        _add(year, "hits", len(found))
        event = {
            "signal_date": day.isoformat(),
            "quarter": quarter.isoformat(),
            "members": len(members),
            "hits": len(found),
            "stale": reasons["stale"],
            "no_single": reasons["no_single"],
            "names": len(chosen),
        }
        year.setdefault("events", []).append(event)
        other = x4_names(ctx, day, members)  # timed in the coverage too
        if not keep_rows:
            continue
        share = r10.overlap_share(
            [item.instrument_id for _t, item, _r in chosen], other
        )
        if share is not None:
            out.overlap.setdefault(str(day.year), []).append(share)
        out.hits.setdefault(str(day.year), []).append(len(chosen))
        out.rebalances.append({**event, "x4_overlap": share})
        out.picks[at + 1] = [item.instrument_id for _t, item, _r in chosen]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        due = following.get(at)
        out.dues[at + 1] = due if due is not None and due <= last else last + 1
        for place, (tie, item, turn) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"eps_now": turn.now, "eps_year_before": turn.before},
                    tie,
                )
            )  # fmt: skip
    return out


def u1_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """U1's list on ``day`` (``round13_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r13.HYPOTHESES[U1]
    rows = r13.rank_u1(ctx.u1, spec, day, members).rows
    ctx.seconds["u1_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def plan_k3(
    ctx: Context, spec: dict[str, Any], first: int, last: int, keep_rows=True
) -> Plan:
    """K3 第 1～5 點 on the signal dates ``first − 1`` .. ``last − 1``."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        year = _year(out.coverage, day, len(members))
        out.signal_days += 1
        t0 = time.perf_counter()
        found, missing = [], Counter()
        for item, k in members:
            selling = inst_sell_5q(ctx, item, k)
            if selling.reason is not None:
                missing["inst_sell_5q"] += 1
                missing[selling.reason] += 1
            if selling.qualifies:
                found.append((pr.tie_break(day, item.instrument_id), item, selling))
        ctx.seconds["inst_sell_5q"] += time.perf_counter() - t0
        found.sort(key=lambda row: row[0])
        chosen = found[:top]
        missing_year = year.setdefault("missing", {})
        for key, count in missing.items():
            missing_year[key] = missing_year.get(key, 0) + count
        hits = len(found)
        _add(year, "hits", hits)
        year["min_hits"] = min(year.get("min_hits", hits), hits)
        year["max_hits"] = max(year.get("max_hits", 0), hits)
        _add(year, "short_days", hits < top)
        _add(year, "zero_days", hits == 0)
        other = u1_names(ctx, day, members)  # timed in the coverage too
        if not keep_rows:
            continue
        out.hits.setdefault(str(day.year), []).append(hits)
        share = r10.overlap_share(
            [item.instrument_id for _t, item, _s in chosen], other
        )
        if share is not None:
            out.overlap.setdefault(str(day.year), []).append(share)
        out.picks[at + 1] = [item.instrument_id for _t, item, _s in chosen]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (tie, item, selling) in enumerate(chosen, 1):
            out.rows.append(
                _pick_row(
                    ctx, day, place, item.instrument_id,
                    {"blocks": ";".join(f"{v:.0f}" for v in selling.blocks)},
                    tie,
                )
            )  # fmt: skip
    return out


def planner(name: str) -> Callable[..., Plan]:
    return {"K1": plan_k1, "K2": plan_k2, "K3": plan_k3}[name]


overlap_share = r10.overlap_share
overlap_summary = r10.overlap_summary
_window_facts = r5._window_facts
PICK_FIELDS = {
    "K1": ("cash_dividend", "action_date", "events"),
    "K2": ("eps_now", "eps_year_before"),
    "K3": ("blocks",),
}


# --- one hypothesis on one segment ------------------------------------------------


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


def fill_days(simulation: pr.Simulation) -> int:
    """K1 第 5 點: the signal dates on which at least one name was bought."""

    return len({position.bought for position in simulation.positions})


def engines(
    ctx: Context, name: str, planned: Plan, first: int, last: int
) -> tuple[pr.Simulation, pr.Simulation]:
    """(the hypothesis, the population): K1 1/n of the account on its event
    days, the population on the same days; K2 X7's account; K3 K accounts."""

    spec = HYPOTHESES[name]
    if name == "K2":
        mine = ex.simulate_events(
            planned.picks, planned.dues, ctx.quote, first, last, spec["top"]
        )
        population = ex.simulate_events(
            planned.population, planned.dues, ctx.quote, first, last, None
        )
        return mine, population
    # K1: the picks are at most 20 already, each 1/n (top None)
    top = None if name == "K1" else spec["top"]
    mine = pr.simulate(planned.picks, ctx.quote, first, last, spec["hold"], top)
    population = pr.simulate(
        planned.population, ctx.quote, first, last, spec["hold"], None
    )
    return mine, population


def run_portfolio(
    ctx: Context,
    db: Path,
    name: str,
    segment: str,
    coverage_only: bool = False,
    min_t: float = MIN_T,
) -> dict[str, Any]:
    """K1, K2 or K3 on one segment: its numbers, verdict and private parts."""

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
    planned = planner(name)(ctx, spec, first, last, keep_rows=not coverage_only)
    result["window"]["signal_days"] = planned.signal_days
    result["window"]["event_days"] = planned.event_days
    result["coverage"] = planned.coverage
    result["seconds"] = {"plan": time.monotonic() - started, **ctx.seconds}
    if coverage_only:
        return result
    result["overlap"] = overlap_summary(planned.overlap)
    if name == "K1":
        result["events"] = overlap_summary(planned.events)
    if name == "K2":
        result["rebalances"] = planned.rebalances
    if name in ("K2", "K3"):
        result["hits"] = overlap_summary(planned.hits)
    mine, population = engines(ctx, name, planned, first, last)
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
    bought = len(mine.positions)
    result["unsold_share"] = mine.counts.get("unsold", 0) / bought if bought else None
    if name == "K2":
        for event in planned.rebalances:
            s = sessions.index(date.fromisoformat(event["signal_date"])) + 1
            event["invested"] = mine.invested[s - first] if s <= last else None
    if name == "K1":
        filled = fill_days(mine)
        result["fill_days"] = {"days": filled, "min_days": MIN_FILL_DAYS}
    if segment != USED:
        result["min_t"] = min_t
        result["verdict"] = ex.explore_judge(
            segment, days, True, excess[POPULATION], absolute, min_t
        )
        if name == "K1" and result["fill_days"]["days"] < MIN_FILL_DAYS:
            result["verdict"] = ex.UNDECIDED
            result["reason"] = "too_few_event_days"
    result["_dates"] = sessions[first : last + 1]
    result["_equity"] = (mine.equity, population.equity)
    result["_positions"] = mine.positions
    result["_rows"] = planned.rows
    return result


def run_one(
    ctx: Context, db: Path, name: str, segment: str, min_t: float = MIN_T
) -> dict[str, Any]:
    return run_portfolio(ctx, db, name, segment, min_t=min_t)


# --- output -----------------------------------------------------------------------


SEGMENT_NAMES = ex.SEGMENT_NAMES
_pct = ex._pct
_t = ex._t
public = ex.public
threshold = r5.threshold
_share = r5._share
PORTFOLIO_TRADE_FIELDS = r5.TRADE_FIELDS
seconds_lines = r10.seconds_lines


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司；"
        f"K1 另要有成交的事件日至少 {MIN_FILL_DAYS} 日。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def _watch_line(min_t: float) -> str:
    return (
        f"- 前瞻觀察：超額 > 0 但 t < {threshold(min_t)}（沒有 t 下限），且絕對報酬 > 0；"
        "只當紀錄，不算通過、不進產品"
    )


def k1_estimate(coverage: dict[str, Any]) -> dict[str, Any]:
    """K1 (``--coverage-only``, no price read): the exploration's signal dates
    with a list (an event day with a fill is one of them) and the validation's
    estimate (the full years' mean × the validation's years)."""

    years = {year: row for year, row in coverage.items() if row.get("days")}
    full = [row.get("event_days", 0) for row in years.values() if row["days"] >= 200]
    first, last = SEGMENTS[VALIDATION]
    length = ((last - first).days + 1) / 365.25
    mean = statistics.fmean(full) if full else None
    return {
        "exploration": sum(row.get("event_days", 0) for row in years.values()),
        "full_years": len(full),
        "per_year": mean,
        "validation_years": length,
        "validation": None if mean is None else mean * length,
        "min_days": MIN_FILL_DAYS,
    }


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """Per year: K1 the candidates, the events and the reasons, the estimated
    invested share; K2 each event day's hits and reasons; K3 the hits and the
    missing shares."""

    if name == "K1":
        head = ["年", "日數", "母體檔次", "條件①成立的檔次", "符合 `div_initiation` 的檔次（事件數）",
                "事件日數", "超過 20 檔的事件日", "最多的一天", "窗口內有配現金", "窗口內有三欄都是 null 的列",
                "（只因 null 不符合）", "上市未滿 3 年", "平均投入比例（估計）"]  # fmt: skip
    elif name == "K2":
        head = ["事件日", "對應的季", "母體檔次", "符合 `eps_turn` 的檔數", "名單檔數",
                "最新一季不是對應的那一季", "（比例）", "任一季沒有單季值", "（比例）"]  # fmt: skip
    else:
        head = ["年", "日數", "母體檔次", "符合 `inst_sell_5q` 的檔數（每日平均）", "（最少的一天）",
                "（最多的一天）", "符合的不足 20 檔的訊號日", "沒有任何一檔符合的訊號日",
                "`inst_sell_5q` 缺值", "（不足 300 根）", "（停牌）", "（市場整天沒有法人資料）"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    if name == "K2":
        for _year_, row in sorted(coverage.items()):
            for event in row.get("events", []):
                members = event["members"]
                lines.append(
                    f"| {event['signal_date']} | {event['quarter']} | {members:,} "
                    f"| {event['hits']:,} | {event['names']:,} | {event['stale']:,} "
                    f"| {_share(event['stale'], members)} | {event['no_single']:,} "
                    f"| {_share(event['no_single'], members)} |"
                )
        return lines
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        cells = [f"{days:,}", f"{members:,}"]
        if name == "K1":
            invested = row.get("invested_days", 0)
            cells += [
                f"{row.get('candidates', 0):,}",
                f"{row.get('events', 0):,}",
                f"{row.get('event_days', 0):,}",
                f"{row.get('capped_days', 0):,}",
                f"{row.get('max_events', 0):,}",
                f"{row.get('paid', 0):,}",
                f"{row.get('null', 0):,}",
                f"{row.get('null_only', 0):,}",
                f"{row.get('young', 0):,}",
                _pct(row["invested_sum"] / invested, 1) if invested else "—",
            ]
        else:
            missing = row.get("missing", {})
            cells += [
                lib.num(row.get("hits", 0) / days, 1) if days else "—",
                f"{row.get('min_hits', 0):,}",
                f"{row.get('max_hits', 0):,}",
                f"{row.get('short_days', 0):,}",
                f"{row.get('zero_days', 0):,}",
                _share(missing.get("inst_sell_5q", 0), members),
                _share(missing.get("short", 0), members),
                _share(missing.get("suspended", 0), members),
                _share(missing.get("market_gap", 0), members),
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
    lines = [
        f"# {name} {segment}（round14_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 判定：**{verdict}**"
        + (f"（{REASONS[result['reason']]}）" if result["reason"] else ""),
        f"- 假設：{spec['direction']}；{spec['label']}；N＝{spec['top']}、K＝{spec['hold']}",
        f"- 登記 commit `{REGISTRATION_COMMIT}`；{DECISION}；"
        f"定義雜湊 `{header['definitions_sha256'][:16]}…`",
        f"- 期間：訊號日 {window.get('first_signal', '—')} 起，有淨值的交易日"
        f" {window.get('first_session', '—')}～{window.get('last_session', '—')}，共 "
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
    filled = result.get("fill_days")
    if filled:
        lines.append(
            f"- 有成交的事件日：{filled['days']:,}／下限 {filled['min_days']} 日"
            f"（{FILL_RULE}）"
        )
    if result["segment"] == VALIDATION:
        lines.append(_watch_line(result.get("min_t", VALIDATION_MIN_T)))
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
            f"（{w['won']:,}／{w['bought']:,}，期末未賣 {w['unsold']:,}，"
            f"期末未賣的比例 {_pct(result.get('unsold_share'), 1)}）。",
            f"成交計數：買進 {counts.get('bought', 0):,}、漲停買不到 "
            f"{counts.get('limit_up', 0):,}、不可交易 {counts.get('not_tradable', 0):,}、"
            f"跌停順延 {counts.get('limit_down', 0):,}、停牌／缺日線順延 "
            f"{counts.get('sale_held', 0):,}、期末未賣 {counts.get('unsold', 0):,}。",
            "",
        ]
    if "events" in result:
        lines += _yearly_lines(
            "## 每天的事件數（K1 第 8 點，只列出、不判定）",
            "母體中 `div_initiation` 成立的檔數（取前 20 名之前），只算有事件的訊號日",
            result["events"],
            lambda v: lib.num(v, 2),
        )
    if "overlap" in result:
        title, fmt = {
            "K1": ("## 和 J3 的重疊檔數（K1 第 8 點）", lambda v: lib.num(v, 2)),
            "K2": ("## 和 X4 的重疊（K2 第 7 點）", lambda v: _pct(v, 1)),
            "K3": ("## 和 U1 的重疊（K3 第 7 點）", lambda v: _pct(v, 1)),
        }[name]
        lines += _yearly_lines(title, OVERLAP_NOTE[name], result["overlap"], fmt)
    if name == "K3" and "hits" in result:
        lines += _yearly_lines(
            "## 每天符合 `inst_sell_5q` 的檔數（K3 第 7 點，只列出、不判定）",
            "母體中 `inst_sell_5q` 成立的檔數（取前 20 名之前）",
            result["hits"],
            lambda v: lib.num(v, 1),
        )
    if result.get("rebalances"):
        lines += [
            "## 每次調倉（K2 第 7 點，只列出、不判定）",
            "",
            "名單檔數是取前 20 名之後；投入比例是買進那天收盤時，部位占淨值的比例。",
            "",
            "| 事件日 | 對應的季 | 母體檔次 | 符合 `eps_turn` | 名單檔數 | 投入比例 | 和 X4 的重疊 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
            *(
                f"| {e['signal_date']} | {e['quarter']} | {e['members']:,} | {e['hits']:,} "
                f"| {e['names']:,} | {_pct(e.get('invested'), 1)} | {_pct(e['x4_overlap'], 1)} |"
                for e in result["rebalances"]
            ),
            "",
        ]
    if result.get("coverage"):
        lines += [
            "## 資料覆蓋（不含報酬）",
            "",
            *coverage_lines(name, result["coverage"]),
            "",
        ]
    return "\n".join(lines)


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
    (out / "summary.md").write_text(
        portfolio_markdown(result, header), encoding="utf-8"
    )
    if "_dates" in result:
        _write_portfolio(out, result, header)


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
    """The overview's row: the engine's excess and the listed parts."""

    row = {"engine": result["engine"], **r5._row(result)}
    name = result["hypothesis"]
    if "overlap" in result:
        key = {"K1": "overlap_j3", "K2": "overlap_x4", "K3": "overlap_u1"}[name]
        row[key] = {k: result["overlap"][k] for k in ("days", "mean")}
    for key in ("events", "hits"):
        if key in result:
            row[key] = {k: result[key][k] for k in ("days", "mean")}
    if "curves" in result:
        row["invested"] = result["curves"][name].get("invested")
        row["unsold_share"] = result.get("unsold_share")
    if "fill_days" in result:
        row["fill_days"] = result["fill_days"]
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round14_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十四輪：K1～K3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：K1、K3 是組合引擎（`portfolio_research.simulate`，K1 每天最多 20 檔、各 1／n，"
        "母體只在事件日買），K2 是 X7 的事件日帳戶（`explore_research.simulate_events`）；"
        "日數是有淨值的交易日",
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
        lines.append(_watch_line(report["min_t"]))
        source = report["exploration"]
        lines.append(f"- 探索段報告：{source['url']}（sha256 `{source['sha256']}`）")
    head = (
        "| 代號 | 方向 | 日數 | 對加權指數超額 | t | 對母體超額 | t | 絕對報酬 | 判定 |"
    )
    rule = "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines += ["", "## 判定", "", head, rule]
    for name, row in report["hypotheses"].items():
        lines.append(_overview_line(name, row, judged=True))
    listed = []
    for name, key, label, kind in (
        ("K1", "events", "K1 每個事件日的事件數", "num"),
        ("K1", "overlap_j3", "K1 和 J3 的重疊檔數", "num"),
        ("K2", "hits", "K2 每次調倉的名單檔數", "num"),
        ("K2", "overlap_x4", "K2 和 X4 的重疊", "pct"),
        ("K3", "hits", "K3 每天符合 `inst_sell_5q` 的檔數", "num"),
        ("K3", "overlap_u1", "K3 和 U1 的重疊", "pct"),
    ):
        part = report["hypotheses"].get(name, {}).get(key)
        if part:
            value = _pct(part["mean"], 1) if kind == "pct" else lib.num(part["mean"], 1)
            listed.append(f"- {label}：平均 {value}（{part['days']:,} 個訊號日）")
    for name, row in report["hypotheses"].items():
        if row.get("invested") is not None:
            listed.append(
                f"- {name} 的平均投入比例 {_pct(row['invested'], 1)}、期末未賣的比例 "
                f"{_pct(row.get('unsold_share'), 1)}"
            )
        if row.get("fill_days"):
            listed.append(
                f"- {name} 有成交的事件日：{row['fill_days']['days']:,}"
                f"（下限 {row['fill_days']['min_days']}）"
            )
    if listed:
        lines += ["", "只列出、不判定：", "", *listed]
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
    return (
        f"| {name} | {spec['direction']} | {row['days']} "
        f"| {_pct(x.get('mean'), 3)} | {_t(x.get('t'))} "
        f"| {_pct(e.get('mean'), 3)} | {_t(e.get('t'))} "
        f"| {_pct(row.get('absolute_mean'), 3)} | {verdict} |"
    )


COVERAGE_NOTES = (
    "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；每個訊號日都數；不跑模擬，不讀價格與報酬",
    f"- K1：{DEGENERATE['K1']}。「條件①成立的檔次」是母體中 T 日有 `cash_dividend` > 0 的列的檔次，"
    "後三欄是其中各條不符合的檔次（可重複）；「只因 null 不符合」是窗口內沒有配現金、上市已滿 3 年，"
    "只因窗口內有三欄都是 null 的列而不符合的檔次。平均投入比例（估計）是每個有淨值的交易日，"
    "前 240 個訊號日中有名單的天數 ÷ 240 的平均（買不到的不扣，不讀價格）；"
    "`cash_div_ex` 是同一個 T 算 J3 名單（`round12_research.cash_div_ex`）的時間，`--coverage-only` 不算重疊，各段的 `summary.md` 才列",
    f"- K2：{DEGENERATE['K2']}。每個事件日一列；`x4_order` 是同一個 T 算 X4 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- K3：{DEGENERATE['K3']}。`u1_order` 是同一個 T 算 U1 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    estimate = body.get("k1_event_days") or {}
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 K1～K3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round14_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、市場整天沒有法人資料的日子 "
        f"{load_seconds.get('market_gaps', 0):.0f} 秒、除權息 {load_seconds.get('actions', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根",
        *COVERAGE_NOTES,
        "",
        "## 耗時",
        "",
        *seconds_lines(body),
        "",
    ]
    if estimate:
        lines += [
            "## K1 的事件日（第 5 點的下限）",
            "",
            f"- 探索段有名單的訊號日 {estimate['exploration']:,} 日（有成交的事件日不會多於這個數）；"
            f"下限 {estimate['min_days']} 日",
            f"- 驗證段估計 {lib.num(estimate['validation'], 0)} 日：探索段 {estimate['full_years']} 個"
            f"完整年（至少 200 個訊號日）平均每年 {lib.num(estimate['per_year'], 1)} 日 × 驗證段 "
            f"{lib.num(estimate['validation_years'], 2)} 年（不讀驗證段的資料）",
            "",
        ]
    for name, row in body["hypotheses"].items():
        window = row["window"] or {}
        lines += [
            f"## {name}（訊號日 {window.get('first_signal', '—')} 起，{window.get('days', 0)} 日）",
            "",
            *coverage_lines(name, row["coverage"]),
            "",
        ]
    lines += [
        "有明顯斷點，或缺值比例有異常的年份或欄位，或 K1 任一段估得出的事件日少於 "
        f"{MIN_FILL_DAYS} 日時，先在工具單提問、不跑探索段。",
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
            "explore_research": "simulate_events",
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
    progress(f"loaded ({loaded:.1f}s)")
    header = _header(db, EXPLORATION, command, end)
    hypotheses = {}
    for name in HYPOTHESES:
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
        "k1_event_days": k1_estimate(hypotheses["K1"]["coverage"]),
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
    parser = argparse.ArgumentParser(prog="round14_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): K1, K2, K3 or "
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
    command = "python tools/research/round14_research.py " + " ".join(argv)
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
