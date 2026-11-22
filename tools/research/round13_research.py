"""Round 13 of the new-strategy exploration: U1～U3 (#968).

docs/spec/evidence.md 第十三輪：U1～U3 and 第十三輪實作釋義: the hypotheses
were registered (commit ``7d2705c3``, #966, decision 7082551476, PR #967
decision 7082722147) before anyone ran a tool on the backfilled history.
Nothing here is a command-line option: a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round12_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  All three trade on the portfolio engine
(``portfolio_research.simulate``) with the population, the loading
(``explore_research.load_context``), ``explore_judge``, the order
(``round5_research.order_key``), ``feature_evidence._mean_volume``, the
industries (``mainstream_research.group_members``, M1's
``mainstream_research.signal_day``／``rank_groups``), the corporate actions
(``research_report.load_actions``), the gate and the ledgers imported.  The
overlaps with W1 and V3 take those lists from ``round6_research`` and
``round5_research`` (their first versions) and ``round10_research``'s
``overlap_share``／``overlap_summary``.  New here are only ``inst_quiet_60``,
``flow_i`` and ``ind_flow_20``, ``cash_paid_5y``, the two overlaps, U2's
share in M1's top groups and its industries per list.

Each signal date T (after its close, only T's data and before):

- U1: ``inst_quiet_60``, how many of the item's 60 bars to T had no
  institutional trading (no chip row, or each of the three columns null or
  0), high first.  N 20, K 60.
- U2: the industry's ``ind_flow_20`` = Σ ``flow_i`` ÷ Σ ``vol_i`` over its
  members in T's population with both (at least 5), the item's key its
  industry's (the smallest group id), high first.  N 20, K 20.
- U3: ``cash_paid_5y`` (a cash dividend > 0 in each of the 5 calendar years
  before T's), 20 by the hash, not ranked; fewer leave cash.  N 20, K 120.

A bar's market (TWSE or TPEx) without any institutional value that session
makes ``inst_quiet_60`` and ``flow_i`` missing.  ``explore_research.
explore_judge`` judges with t ≥ 2 on the exploration and the fixed
Bonferroni t ≥ 3.302 (52 hypotheses) on the validation.  Before the used
segment is loaded the validation's panel is let go (PR #905 review).
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
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_lib as lib  # noqa: E402
import exit_research as er  # noqa: E402
import explore_research as ex  # noqa: E402
import feature_evidence as features  # noqa: E402
import mainstream_research as ms  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round6_research as r6  # noqa: E402
import round10_research as r10  # noqa: E402

VERSION = 1
DESIGN = "968"
TOOL = "round13_research"
REGISTRATION_COMMIT = "7d2705c3"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/966#issuecomment-7082551476"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十三輪 門檻: 1 − Φ(z) = 0.025 ÷ 52, z = 3.3015, 3.302 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.302
ROUND = 13
ROUND_SIZE = 3
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4, J1～J4, U1～U3
CUMULATIVE = 52
# Every segment reads the copy from its start, as round10_research ..
# round12_research: U3 reads the dividends of the 5 years before T's.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO = "portfolio"
HIGH = r5.HIGH

INSTITUTIONS = features.INSTITUTIONS  # foreign_buy, trust_buy, dealer_buy
# 共同「沒有法人進出」: a bar (the item's own) without a chip row, or with each
# of the three columns null or 0 (null and 0 mixed too); one column not null
# and not 0 is trading (#966 決定 7082551476).
NO_TRADING = "no chip row, or each of the three columns null or 0"
# 共同「市場整天沒有法人資料」: a session on which no instrument of the bar's
# market (TWSE or TPEx) in the panel has one of the three columns not null;
# a window with such a bar is missing.
MARKET_GAP = (
    "a session on which no instrument of the bar's market in the panel has "
    "one of the three columns not null; a window with such a bar is missing"
)
QUIET_WINDOW = 60  # U1: at − 59 .. at
FLOW_WINDOW = 20  # U2: at − 19 .. at, institutional_flow_20's window
# U2 第 1 點: a bar without trading counts 0, and so does a null column of a
# bar (#966 決定 7082551476); not feature_evidence._flow's missing rule.
FLOW_NULL = "a null column counts 0; a bar without trading counts 0"
MIN_VALID = 5  # U2: valued members of an industry in T's population (M1's floor)
# U2 第 5 點: the member's own flow_i or vol_i missing is missing, not given
# the industry's value (#966 決定 7082551476).
OWN_MISSING = "own flow_i or vol_i missing: missing, not the industry's value"
# 第十三輪實作釋義 (L4's #953 決定 7073648898, Y4's several_groups): a member
# in several industries counts in each one's sums; its key is the smallest
# group id's, missing when that one is not ranked.
SEVERAL_GROUPS = (
    "counted in every group's sums and valued members; the key is the smallest "
    "group id's ind_flow_20, missing when that group is not ranked"
)
PAID_YEARS = 5  # U3: Y − 5 .. Y − 1
CASH_MIN = 0.0  # U3: cash_dividend > 0, strictly; null is not paid
PAID_RULE = (
    "each of the calendar years Y-5..Y-1 (Y is T's) has a row with action_date "
    "in the year and cash_dividend > 0; a null cash_dividend is not paid; "
    "only action_date < T read"
)
# U3 第 3 點: the qualified ones by the hash, fewer than 20 leave cash.
SHORT_RULE = "cash, not filled"
INST_ANCHOR = date(2014, 12, 1)  # the OTC institutional table's first day
U3_START = date(2013, 1, 2)  # 2013's first session
W1, V3 = "W1", "V3"  # the lists U1 and U3 overlap with (listed only)

# The registration (docs 第十三輪：U1～U3), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.  ``keys``: (feature, HIGH), a missing value last, ties by
# ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "U1": {
        "engine": PORTFOLIO,
        "direction": "法人關注",
        "label": "`inst_quiet_60`（近 60 根裡當天三大法人都沒有進出的根數）大者先",
        "rule": "daily",
        "keys": (("inst_quiet_60", HIGH),),
        "top": 20,
        "hold": 60,
        "start": ("session", INST_ANCHOR, 60),
    },
    "U2": {
        "engine": PORTFOLIO,
        "direction": "籌碼：產業資金流向",
        "label": "所屬產業的 `ind_flow_20`（產業的三大法人 20 日淨買超合計 ÷ "
        "成員的 20 日均量合計）大者先",
        "rule": "daily",
        "keys": (("ind_flow_20", HIGH),),
        "top": 20,
        "hold": 20,
        "start": ("session", INST_ANCHOR, 20),
    },
    "U3": {
        "engine": PORTFOLIO,
        "direction": "品質：連續配息",
        "label": "`cash_paid_5y`（T 所在年度之前的 5 個完整曆年每年都有現金股利除息）成立，"
        "以雜湊取 20 檔、不排序",
        "rule": "daily",
        "conditions": (("cash_paid_5y", "is", True),),
        "order": "the hash only",
        "short": SHORT_RULE,
        "top": 20,
        "hold": 120,
        "start": ("date", U3_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(ex.REASONS)
LIMITS = {
    "U1": "冷門和不流動、規模小有關，U1 可能沾到 W1，看和 W1 名單的重疊比例；"
    "U1 是第一次把「官方沒列」當訊號",
    "U2": "排序鍵是產業的值，名單通常集中在 1～2 個產業（第一名的產業母體內就有 20 檔以上時，"
    "20 檔都來自它），這是「買類別」的意思，不另設產業上限；法人常買近期漲的產業，"
    "U2 可能沾到產業動能，看落在 M1 前 5 族群的比例；成員表的上市分類回溯，限制同 M1",
    "U3": "K＝120 是前十二輪最長的 K（都 ≤ 60）：有 120 份子帳戶，每天動用約 1／120 的資金；"
    "各段期末還沒賣的部位以最後收盤計，期末未賣的比例比 K＝60 的假設高。母體也用同一個 K",
}
# The degenerate cases as the code judges them (第十三輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "U1": "60 根中任一根停牌，或任一根所在的交易日這一檔的市場（上市或上櫃）沒有任何一檔有法人值"
    "（三欄中有一欄非 null）時缺值、排最後；沒有籌碼列，或三欄每一欄都是 null 或 0 的根算「沒有法人進出」",
    "U2": "`flow_i` 在 20 根中任一根停牌、任一根所在的交易日這一檔的市場沒有任何一檔有法人值時缺值"
    "（沒有法人進出的根與 null 的欄算 0），`vol_i`（`feature_evidence._mean_volume`）沒有值時缺值；"
    "自己的 `flow_i` 或 `vol_i` 缺值、沒有產業，或所屬產業（`group_id` 字串最小的那個）"
    "有效成員不到 5 檔時排序鍵缺值、排最後",
    "U3": "5 個曆年中任一年沒有 `cash_dividend` > 0 的列（null 不算）時不符合；"
    "只讀 `action_date` < T 的列；符合的不足 20 檔時餘額留現金",
}
OVERLAP_NOTE = {
    "U1": 'U1 與 W1（`round6_research` 第 1 版的 `HYPOTHESES["W1"]`）每日名單的重疊比例：'
    "|U1 的前 20 名 ∩ W1 的前 20 名| ÷ U1 當天的名單檔數；U1 或 W1 當天沒有名單的日子不計。"
    "只列出、不判定",
    "U2": "U2 當天名單落在 M1 前 5 族群（`mainstream_research.signal_day` 的 `rank_groups`，"
    "同一個 T 算）的比例：名單中所屬產業（`group_id` 字串最小的那個）是 M1 當天選出的族群之一的檔數"
    " ÷ U2 當天的名單檔數；名單的產業數是名單中所屬產業的個數（沒有產業的不算）。"
    "U2 或 M1 當天沒有名單的日子不計。只列出、不判定",
    "U3": 'U3 與 V3（`round5_research` 第 1 版的 `HYPOTHESES["V3"]`）每日名單的重疊比例：'
    "|U3 的前 20 名 ∩ V3 的前 20 名| ÷ U3 當天的名單檔數；U3 或 V3 當天沒有名單的日子不計。"
    "只列出、不判定",
}
FEATURE_LABELS = {
    "inst_quiet_60": "近 60 根沒有法人進出的根數",
    "flow_i": "三大法人 20 根淨買超合計",
    "vol_i": "20 日均量",
    "ind_flow_20": "產業的法人 20 日淨買超 ÷ 均量",
    "cash_paid_5y": "前 5 個曆年每年都有配現金",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "no_trading": {
                "columns": list(INSTITUTIONS),
                "rule": NO_TRADING,
            },
            "market_gap": MARKET_GAP,
            "inst_quiet_60": {
                "value": "the bars without trading among the item's bars at-59..at",
                "window": QUIET_WINDOW,
                "missing": "a suspended bar; a bar on a market gap",
            },
            "flow_i": {
                "value": "sum of the three columns over the item's bars at-19..at",
                "window": FLOW_WINDOW,
                "null": FLOW_NULL,
                "missing": "a suspended bar; a bar on a market gap",
            },
            "vol_i": {
                "function": "feature_evidence._mean_volume (20 bars before T, > 0)",
                "feature_evidence": features.VERSION,
            },
            "ind_flow_20": {
                "groups": "mainstream_research.group_members (snapshot_date <= T)",
                "value": "sum flow_i / sum vol_i over the group's members in T's "
                "population with both",
                "min_valid": MIN_VALID,
                "own_missing": OWN_MISSING,
                "several_groups": SEVERAL_GROUPS,
                "missing": "own flow_i or vol_i missing; no group; the group "
                "with fewer than min_valid valued members",
            },
            "cash_paid_5y": {
                "years": PAID_YEARS,
                "cash_min": CASH_MIN,
                "rule": PAID_RULE,
                "short": SHORT_RULE,
            },
            "overlaps": {
                W1: [r6.HYPOTHESES[W1], r6.VERSION, r6.DESIGN],
                V3: [r5.HYPOTHESES[V3], r5.VERSION, r5.DESIGN],
                "M1": [ms.VERSION, ms.DESIGN, ms.GROUP_COUNT],
            },
        },
        "members": ms.definitions()["members"],
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
        "round": [ROUND, ROUND_SIZE, CUMULATIVE],
        "costs": [pr.SLIPPAGE, pr.FEE, pr.TAX],
        "min_lots": MIN_LOTS,
        "load_from": LOAD_FROM,
        "load": LOAD_RULE,
    }


def definitions_sha256() -> str:
    """Hash of every fixed number the verdicts depend on (the definitions, the
    windows 60 and 20, the 5 calendar years, N and K, the industries' floor,
    the orders, the rules of no trading, of a market gap, of a null column,
    of a member's own missing value and of several industries, U3's null and
    T rule, the member table, the segments, the costs).  A changed tool needs
    a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


def market_gaps(panel: lib.Panel) -> dict[str, bytearray]:
    """共同「市場整天沒有法人資料」: by market, 1 on a session on which no
    instrument of the panel in that market has one of the three columns not
    null (sessions by index)."""

    size = len(panel.sessions)
    for item in panel.series.values():
        if len(item.session):
            size = max(size, item.session[-1] + 1)
    seen: dict[str, bytearray] = {}
    for instrument_id, item in panel.series.items():
        market = panel.symbols.get(instrument_id, ("", "", ""))[0]
        has = seen.setdefault(market, bytearray(size))
        for name in INSTITUTIONS:
            column = item.chips.get(name)
            if column is None:
                continue
            for k, value in enumerate(column):
                if value == value:  # not NaN
                    has[item.session[k]] = 1
    return {market: bytearray(1 - v for v in has) for market, has in seen.items()}


def paid_years(holders: dict[int, Any]) -> dict[int, frozenset[int]]:
    """U3 第 1、2 點: by instrument, the calendar years of a row with
    ``cash_dividend`` > 0 (a null one is not paid)."""

    out: dict[int, frozenset[int]] = {}
    for instrument_id, holder in holders.items():
        years = {
            action.action_date.year
            for action in holder.actions
            if action.cash_dividend is not None
            and float(action.cash_dividend) > CASH_MIN
        }
        if years:
            out[instrument_id] = frozenset(years)
    return out


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes),
    the market gaps (U1, U2), the member snapshots (U2, M1's groups), the
    years with a cash dividend (U3) and the contexts ``round6_research`` and
    ``round5_research`` rank W1 and V3 with (the same base).  One panel."""

    base: ex.Context
    groups: ms.Context | None = None
    gaps: dict[str, bytearray] | None = None
    paid: dict[int, frozenset[int]] = field(default_factory=dict)
    w1: r6.Context | None = None
    v3: r5.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)
    # per instrument: prefix sums of the bars without trading and of the bars
    # on a market gap
    inst: dict[int, tuple[Any, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gaps is None:
            self.gaps = market_gaps(self.panel)
        if self.w1 is None:
            self.w1 = r6.Context(self.base)
        if self.v3 is None:
            self.v3 = r5.Context(self.base)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the member snapshots and the corporate
    actions to ``end``; nothing after ``end`` is read."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    gaps = market_gaps(base.market.panel)
    gap_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    groups = ms.build_context(base.market, ms.read_members(members, end))
    member_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    report = lib.research_report()
    holders = {
        instrument_id: report.Instrument() for instrument_id in base.market.panel.series
    }
    report.load_actions(db, holders, start, raw_dir, end)
    paid = paid_years(holders)
    v3 = r5.Context(
        base,
        actions={
            instrument_id: r5.actions_of(holder.actions)
            for instrument_id, holder in holders.items()
            if holder.actions
        },
    )
    del holders
    return Context(
        base,
        groups,
        gaps,
        paid,
        v3=v3,
        load_seconds={
            "panel": panel_seconds,
            "market_gaps": gap_seconds,
            "members": member_seconds,
            "actions": time.monotonic() - t0,
        },
    )


# --- features ---------------------------------------------------------------------


def _value(item: lib.Series, name: str, k: int) -> float:
    column = item.chips.get(name)
    return lib.NAN if column is None else column[k]


def no_trading(item: lib.Series, k: int) -> bool:
    """共同「沒有法人進出」on the item's bar ``k``: each of the three columns
    null (NaN, also without a chip row) or 0."""

    for name in INSTITUTIONS:
        value = _value(item, name, k)
        if value == value and value != 0:
            return False
    return True


def _market(ctx: Context, item: lib.Series) -> str:
    return ctx.panel.symbols.get(item.instrument_id, ("", "", ""))[0]


def _inst_prefix(ctx: Context, item: lib.Series) -> tuple[Any, Any]:
    parts = ctx.inst.get(item.instrument_id)
    if parts is None:
        gap = ctx.gaps.get(_market(ctx, item))
        quiet, gaps = array("i", [0]), array("i", [0])
        n_quiet = n_gap = 0
        for k in range(len(item.dates)):
            n_quiet += no_trading(item, k)
            s = item.session[k]
            n_gap += 1 if gap is None or s >= len(gap) else gap[s]
            quiet.append(n_quiet)
            gaps.append(n_gap)
        parts = (quiet, gaps)
        ctx.inst[item.instrument_id] = parts
    return parts


@dataclass(frozen=True)
class Window:
    first: int | None  # the window's first bar, None when missing
    reason: str | None = None  # "short", "suspended" or "market_gap"


def window_of(ctx: Context, item: lib.Series, at: int, size: int) -> Window:
    """The item's ``size`` bars to ``at``: missing with fewer bars, a
    suspended one, or one on a session of its market's gap."""

    first = at - size + 1
    if first < 0:
        return Window(None, "short")
    if item.suspended[at + 1] != item.suspended[first]:
        return Window(None, "suspended")
    _quiet, gaps = _inst_prefix(ctx, item)
    if gaps[at + 1] != gaps[first]:
        return Window(None, "market_gap")
    return Window(first)


def inst_quiet_60(ctx: Context, item: lib.Series, at: int) -> int | None:
    """U1 第 1～3 點: the bars without trading among at − 59 .. at."""

    return quiet_count(ctx, item, at, window_of(ctx, item, at, QUIET_WINDOW))


def quiet_count(ctx: Context, item: lib.Series, at: int, window: Window) -> int | None:
    if window.first is None:
        return None
    quiet, _gaps = _inst_prefix(ctx, item)
    return quiet[at + 1] - quiet[window.first]


def flow_i(ctx: Context, item: lib.Series, at: int) -> float | None:
    """U2 第 1、3 點: the three columns summed over at − 19 .. at, a null
    column (or no chip row) 0."""

    window = window_of(ctx, item, at, FLOW_WINDOW)
    if window.first is None:
        return None
    total = 0.0
    for k in range(window.first, at + 1):
        for name in INSTITUTIONS:
            value = _value(item, name, k)
            if value == value:
                total += value
    return total


def vol_i(item: lib.Series, at: int) -> float | None:
    """U2 第 2 點: ``feature_evidence._mean_volume`` (the 20 bars before T)."""

    return features._mean_volume(item, at)


def cash_paid_5y(ctx: Context, item: lib.Series, day: date) -> bool:
    """U3 第 1、2、4 點: every year Y − 5 .. Y − 1 has a cash dividend > 0
    (Y is T's year, so only rows before T are read)."""

    paid = ctx.paid.get(item.instrument_id)
    if not paid:
        return False
    return all(year in paid for year in range(day.year - PAID_YEARS, day.year))


@dataclass(frozen=True)
class Key:
    value: float | None  # ind_flow_20 of the member's industry
    group: str | None  # the smallest group id, None without one
    reason: str | None  # "own", "no_group", "unranked" or None
    groups: int = 0  # how many groups it is in on T


@dataclass
class IndustryDay:
    keys: dict[int, Key] = field(default_factory=dict)
    ranked: dict[str, float] = field(default_factory=dict)  # group -> ind_flow_20
    valid: dict[str, int] = field(default_factory=dict)  # group -> valued members
    groups: int = 0  # groups with a member in T's population
    flow_missing: int = 0
    vol_missing: int = 0


def industry_day(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> IndustryDay:
    """U2 第 1～6 點 on T's population."""

    out = IndustryDay()
    values: dict[int, tuple[float | None, float | None]] = {}
    t0 = time.perf_counter()
    for item, at in members:
        f = flow_i(ctx, item, at)
        t1 = time.perf_counter()
        v = vol_i(item, at)
        ctx.seconds["flow_i"] += t1 - t0
        t0 = time.perf_counter()
        ctx.seconds["vol_i"] += t0 - t1
        values[item.instrument_id] = (f, v)
        out.flow_missing += f is None
        out.vol_missing += v is None
    t0 = time.perf_counter()
    grouped: dict[str, set[int]] = {}
    if ctx.groups is not None:
        grouped = ms.group_members(ctx.groups, day)[0]
    groups_of: dict[int, list[str]] = defaultdict(list)
    for group_id, ids in sorted(grouped.items()):
        inside = sorted(i for i in ids if i in values)
        if not inside:
            continue
        out.groups += 1
        flow = volume = 0.0
        valid = 0
        for instrument_id in inside:
            groups_of[instrument_id].append(group_id)
            f, v = values[instrument_id]
            if f is not None and v is not None:
                flow += f
                volume += v
                valid += 1
        out.valid[group_id] = valid
        if valid >= MIN_VALID:
            out.ranked[group_id] = flow / volume
    for instrument_id, (f, v) in values.items():
        groups = groups_of.get(instrument_id, [])
        group = min(groups) if groups else None
        if f is None or v is None:
            key = Key(None, group, "own", len(groups))
        elif group is None:
            key = Key(None, None, "no_group", 0)
        elif group not in out.ranked:
            key = Key(None, group, "unranked", len(groups))
        else:
            key = Key(out.ranked[group], group, None, len(groups))
        out.keys[instrument_id] = key
    ctx.seconds["ind_flow_20"] += time.perf_counter() - t0
    return out


# --- the portfolio engine ---------------------------------------------------------


order_key = r5.order_key
_window_facts = r5._window_facts


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value, or None
    (``round12_research``'s ``segment_window`` on this tool's segments)."""

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
    values: Counter = field(default_factory=Counter)  # U1: inst_quiet_60 -> members
    industry: IndustryDay | None = None  # U2
    hits: int = 0  # U3: members meeting cash_paid_5y


def rank_u1(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """U1 第 1～4 點: the population, ``inst_quiet_60`` high first, missing last."""

    out = Ranked([])
    rows = []
    t0 = time.perf_counter()
    for item, at in members:
        window = window_of(ctx, item, at, QUIET_WINDOW)
        value = quiet_count(ctx, item, at, window)
        if value is None:
            out.missing["inst_quiet_60"] += 1
            out.missing[window.reason] += 1
        else:
            out.values[value] += 1
        rows.append(
            (
                item.instrument_id,
                {"inst_quiet_60": value},
                pr.tie_break(day, item.instrument_id),
            )
        )
    ctx.seconds["inst_quiet_60"] += time.perf_counter() - t0
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    return out


def rank_u2(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """U2 第 4、5 點: the population by its industry's ``ind_flow_20`` high
    first, ties (in one industry) by the hash, the missing keys last."""

    industry = industry_day(ctx, day, members)
    out = Ranked([], industry=industry)
    out.missing["flow_i"] = industry.flow_missing
    out.missing["vol_i"] = industry.vol_missing
    t0 = time.perf_counter()
    rows = []
    for item, _at in members:
        key = industry.keys[item.instrument_id]
        out.missing["ind_flow_20"] += key.value is None
        if key.reason is not None:
            out.missing[key.reason] += 1
        out.missing["several_groups"] += key.groups > 1
        rows.append(
            (
                item.instrument_id,
                {"ind_flow_20": key.value, "group": key.group},
                pr.tie_break(day, item.instrument_id),
            )
        )
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    ctx.seconds["u2_order"] += time.perf_counter() - t0
    return out


def rank_u3(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """U3 第 3 點: the members with ``cash_paid_5y`` by the hash; fewer than
    20 leave cash, nothing filled up."""

    out = Ranked([])
    rows = []
    t0 = time.perf_counter()
    for item, _at in members:
        if cash_paid_5y(ctx, item, day):
            rows.append(
                (
                    item.instrument_id,
                    {"cash_paid_5y": True},
                    pr.tie_break(day, item.instrument_id),
                )
            )
    ctx.seconds["cash_paid_5y"] += time.perf_counter() - t0
    rows.sort(key=lambda row: row[2])
    out.hits = len(rows)
    out.rows = rows
    return out


def ranker(name: str) -> Callable[..., Ranked]:
    return {"U1": rank_u1, "U2": rank_u2, "U3": rank_u3}[name]


def w1_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """W1's list on ``day`` (``round6_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r6.HYPOTHESES[W1]
    rows = r6.rank(ctx.w1, spec, day, members).rows
    ctx.seconds["w1_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def v3_names(
    ctx: Context, day: date, members: list[tuple[lib.Series, int]]
) -> set[int]:
    """V3's list on ``day`` (``round5_research`` 第 1 版的定義, not rewritten)."""

    t0 = time.perf_counter()
    spec = r5.HYPOTHESES[V3]
    rows = r5.rank(ctx.v3, spec, day, members).rows
    ctx.seconds["v3_order"] += time.perf_counter() - t0
    return {row[0] for row in rows[: spec["top"]]}


def m1_groups(ctx: Context, at: int) -> set[str]:
    """M1's chosen groups on signal date ``at`` (``mainstream_research.
    signal_day``: ``rank_groups`` on the same T; none without TAIEX's
    return, the day M1 has no list)."""

    t0 = time.perf_counter()
    chosen: set[str] = set()
    if ctx.groups is not None:
        found = ms.signal_day(ctx.groups, at)
        if found.picks:
            chosen = {group.group_id for group in found.groups}
    ctx.seconds["m1_groups"] += time.perf_counter() - t0
    return chosen


def industry_share(
    rows: list[tuple[int, dict[str, Any], str]], chosen: set[str]
) -> tuple[int, float | None]:
    """U2 第 8 點 on a day's list: (its industries, the share of its names
    whose industry is one of M1's ``chosen``; None when either has no list)."""

    groups = [values.get("group") for _id, values, _tie in rows]
    industries = len({group for group in groups if group is not None})
    if not rows or not chosen:
        return industries, None
    return industries, sum(group in chosen for group in groups) / len(rows)


overlap_with = {"U1": w1_names, "U3": v3_names}
PICK_FIELDS = {
    "U1": ("inst_quiet_60",),
    "U2": ("ind_flow_20", "group"),
    "U3": ("cash_paid_5y",),
}


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    overlap: dict[str, list[float]] = field(default_factory=dict)  # U1, U3; U2's M1
    industries: dict[str, list[float]] = field(default_factory=dict)  # U2, by year
    hits: dict[str, list[float]] = field(default_factory=dict)  # U3, by year
    saturdays: int = 0  # U1: signal dates on a Saturday


def _coverage_add(
    ctx: Context, coverage: dict[str, Any], name: str, day: date, s: int,
    members: list[tuple[lib.Series, int]], r: Ranked,
) -> None:  # fmt: skip
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += len(members)
    for key, count in r.missing.items():
        year["missing"][key] = year["missing"].get(key, 0) + count
    if name == "U1":
        values = year.setdefault("values", {})
        for value, count in r.values.items():
            values[str(value)] = values.get(str(value), 0) + count
        year["saturdays"] = year.get("saturdays", 0) + (day.weekday() == 5)
        gaps = year.setdefault("market_gaps", {})
        for market, gap in sorted(ctx.gaps.items()):
            if market and s < len(gap):
                gaps[market] = gaps.get(market, 0) + gap[s]
    elif name == "U2":
        industry = r.industry
        ranked = len(industry.ranked)
        year["ranked"] = year.get("ranked", 0) + ranked
        year["min_ranked"] = min(year.get("min_ranked", ranked), ranked)
        year["max_ranked"] = max(year.get("max_ranked", 0), ranked)
        year["groups"] = year.get("groups", 0) + industry.groups
        year["no_ranked_days"] = year.get("no_ranked_days", 0) + (ranked == 0)
        top = HYPOTHESES[name]["top"]
        missing_in_list = sum(
            values["ind_flow_20"] is None for _i, values, _t in r.rows[:top]
        )
        year["list_missing"] = year.get("list_missing", 0) + missing_in_list
    elif name == "U3":
        top = HYPOTHESES[name]["top"]
        year["hits"] = year.get("hits", 0) + r.hits
        year["min_hits"] = min(year.get("min_hits", r.hits), r.hits)
        year["max_hits"] = max(year.get("max_hits", 0), r.hits)
        year["short_days"] = year.get("short_days", 0) + (r.hits < top)
        year["zero_days"] = year.get("zero_days", 0) + (r.hits == 0)


def plan(
    ctx: Context, spec: dict[str, Any], name: str, first: int, last: int, keep_rows=True
) -> Plan:
    """The picks, the population and the coverage on the signal dates
    ``first − 1`` .. ``last − 1`` (only T's data and before is read)."""

    panel = ctx.panel
    out = Plan()
    top = spec["top"]
    rank = ranker(name)
    for at in range(first - 1, last):
        day = panel.sessions[at]
        members = lib.universe(panel, day, MIN_LOTS)
        ranked = rank(ctx, spec, day, members)
        _coverage_add(ctx, out.coverage, name, day, at, members, ranked)
        out.signal_days += 1
        year = str(day.year)
        listed = ranked.rows[:top]
        if name in overlap_with:
            other = overlap_with[name](ctx, day, members)  # timed in the coverage too
            if keep_rows:
                share = r10.overlap_share([row[0] for row in listed], other)
                if share is not None:
                    out.overlap.setdefault(year, []).append(share)
        if name == "U1":
            out.saturdays += day.weekday() == 5
        if name == "U2":
            chosen = m1_groups(ctx, at)  # timed in the coverage too
            if keep_rows:
                industries, share = industry_share(listed, chosen)
                if listed:
                    out.industries.setdefault(year, []).append(industries)
                if share is not None:
                    out.overlap.setdefault(year, []).append(share)
        if name == "U3" and keep_rows:
            out.hits.setdefault(year, []).append(ranked.hits)
        if not keep_rows:
            continue
        out.picks[at + 1] = [row[0] for row in ranked.rows]
        out.population[at + 1] = [item.instrument_id for item, _ in members]
        for place, (instrument_id, values, tie) in enumerate(listed, 1):
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
    """U1, U2 or U3 on one segment: its numbers, verdict and private parts."""

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
    if name in overlap_with or name == "U2":
        result["overlap"] = overlap_summary(planned.overlap)
    if name == "U1":
        result["saturdays"] = planned.saturdays
    if name == "U2":
        result["industries"] = overlap_summary(planned.industries)
    if name == "U3":
        result["hits"] = overlap_summary(planned.hits)
        result["short"] = {
            key: sum(row.get(key, 0) for row in planned.coverage.values())
            for key in ("short_days", "zero_days")
        }
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


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def quiet_summary(values: dict[str, int]) -> dict[str, Any]:
    """U1: the valued members' ``inst_quiet_60`` (mean, 10th／50th／90th
    percentiles by the counts, the shares at 0 and at 60)."""

    counts = sorted((int(value), count) for value, count in values.items())
    n = sum(count for _v, count in counts)
    if not n:
        return {"n": 0, "mean": None, "p10": None, "p50": None, "p90": None,
                "zero": None, "full": None}  # fmt: skip

    def percentile(share: float) -> int:
        need, seen = share * n, 0
        for value, count in counts:
            seen += count
            if seen >= need:
                return value
        return counts[-1][0]

    total = sum(value * count for value, count in counts)
    get = dict(counts)
    return {
        "n": n,
        "mean": total / n,
        "p10": percentile(0.1),
        "p50": percentile(0.5),
        "p90": percentile(0.9),
        "zero": get.get(0, 0) / n,
        "full": get.get(QUIET_WINDOW, 0) / n,
    }


def coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """Per year: U1 ``inst_quiet_60``'s distribution, its missing share and
    the market gaps; U2 the ranked industries, the missing shares and the
    members in several industries; U3 the qualified members."""

    if name == "U1":
        head = ["年", "日數", "母體檔次", "`inst_quiet_60` 缺值", "（停牌）", "（市場整天沒有法人資料）",
                "平均", "p10", "p50", "p90", "＝0", "＝60", "上市整天沒有法人資料的訊號日",
                "上櫃整天沒有法人資料的訊號日", "週六補班日"]  # fmt: skip
    elif name == "U2":
        head = ["年", "日數", "母體檔次", "可排名產業（每日平均）", "（最少的一天）", "（最多的一天）",
                "母體內有成員的產業（每日平均）", "沒有可排名產業的訊號日", "`flow_i` 缺值",
                "`vol_i` 缺值", "排序鍵缺值", "（自己缺值）", "（沒有產業）", "（產業不排名）",
                "屬於多個產業的檔次", "名單中排序鍵缺值的檔次"]  # fmt: skip
    else:
        head = ["年", "日數", "母體檔次", "符合 `cash_paid_5y` 的檔數（每日平均）", "（最少的一天）",
                "（最多的一天）", "符合的不足 20 檔的訊號日", "沒有任何一檔符合的訊號日"]  # fmt: skip
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        missing = row.get("missing", {})
        cells = [f"{days:,}", f"{members:,}"]
        if name == "U1":
            q = quiet_summary(row.get("values", {}))
            gaps = row.get("market_gaps", {})
            cells += [
                _share(missing.get("inst_quiet_60", 0), members),
                _share(missing.get("suspended", 0), members),
                _share(missing.get("market_gap", 0), members),
                lib.num(q["mean"], 1),
                *(str(q[key]) if q[key] is not None else "—" for key in ("p10", "p50", "p90")),
                _pct(q["zero"], 1),
                _pct(q["full"], 1),
                f"{gaps.get('TWSE', 0):,}",
                f"{gaps.get('TPEx', 0):,}",
                f"{row.get('saturdays', 0):,}",
            ]  # fmt: skip
        elif name == "U2":
            cells += [
                lib.num(row.get("ranked", 0) / days, 1) if days else "—",
                f"{row.get('min_ranked', 0):,}",
                f"{row.get('max_ranked', 0):,}",
                lib.num(row.get("groups", 0) / days, 1) if days else "—",
                f"{row.get('no_ranked_days', 0):,}",
                _share(missing.get("flow_i", 0), members),
                _share(missing.get("vol_i", 0), members),
                _share(missing.get("ind_flow_20", 0), members),
                _share(missing.get("own", 0), members),
                _share(missing.get("no_group", 0), members),
                _share(missing.get("unranked", 0), members),
                f"{missing.get('several_groups', 0):,}",
                f"{row.get('list_missing', 0):,}",
            ]
        else:
            cells += [
                lib.num(row.get("hits", 0) / days, 1) if days else "—",
                f"{row.get('min_hits', 0):,}",
                f"{row.get('max_hits', 0):,}",
                f"{row.get('short_days', 0):,}",
                f"{row.get('zero_days', 0):,}",
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
        f"# {name} {segment}（round13_research 第 {VERSION} 版，#{DESIGN}）",
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
    if name == "U2":
        lines.append(ms._members_line())
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
    if "saturdays" in result:
        lines += [
            "## 週六補班日（U1 第 7 點，只列出、不判定）",
            "",
            f"本段的訊號日中有 {result['saturdays']:,} 天是 TWSE 週六補班日"
            "（照同一規則算「沒有法人進出」，不另處理）。",
            "",
        ]
    if "overlap" in result:
        title = {
            "U1": "## 和 W1 的重疊（U1 第 7 點）",
            "U2": "## 落在 M1 前 5 族群的比例（U2 第 8 點）",
            "U3": "## 和 V3 的重疊（U3 第 6 點）",
        }[name]
        lines += _yearly_lines(
            title, OVERLAP_NOTE[name], result["overlap"], lambda v: _pct(v, 1)
        )
    if "industries" in result:
        lines += _yearly_lines(
            "## 每天名單的產業數（U2 第 8 點，只列出、不判定）",
            "名單中所屬產業（`group_id` 字串最小的那個）的個數，沒有產業的不算；"
            "U2 當天沒有名單的日子不計",
            result["industries"],
            lambda v: lib.num(v, 2),
        )
    if "hits" in result:
        short = result["short"]
        lines += _yearly_lines(
            "## 每天符合 `cash_paid_5y` 的檔數（U3 第 6 點，只列出、不判定）",
            f"母體中 `cash_paid_5y` 成立的檔數；符合的不足 20 檔的訊號日 {short['short_days']:,} 日、"
            f"沒有任何一檔符合的訊號日 {short['zero_days']:,} 日（不足的餘額留現金）",
            result["hits"],
            lambda v: lib.num(v, 1),
        )
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
    """The overview's row: the portfolio engine's excess and the listed parts."""

    row = {"engine": PORTFOLIO, **r5._row(result)}
    name = result["hypothesis"]
    if "overlap" in result:
        key = {"U1": "overlap_w1", "U2": "m1_share", "U3": "overlap_v3"}[name]
        row[key] = {k: result["overlap"][k] for k in ("days", "mean")}
    if "saturdays" in result:
        row["saturdays"] = result["saturdays"]
    if "industries" in result:
        row["industries"] = {k: result["industries"][k] for k in ("days", "mean")}
    if "hits" in result:
        row["hits"] = {k: result["hits"][k] for k in ("days", "mean")}
        row["short"] = result["short"]
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round13_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十三輪：U1～U3」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：U1～U3 都是組合引擎（`portfolio_research.simulate`，日數是有淨值的交易日）",
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
        "| 代號 | 方向 | 日數 | 對加權指數超額 | t | 對母體超額 | t | 絕對報酬 | 判定 |"
    )
    rule = "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
    lines += ["", "## 判定", "", head, rule]
    for name, row in report["hypotheses"].items():
        lines.append(_overview_line(name, row, judged=True))
    listed = []
    for name, key, label, kind in (
        ("U1", "overlap_w1", "U1 和 W1 的重疊", "pct"),
        ("U2", "m1_share", "U2 落在 M1 前 5 族群的比例", "pct"),
        ("U2", "industries", "U2 每天名單的產業數", "num"),
        ("U3", "overlap_v3", "U3 和 V3 的重疊", "pct"),
        ("U3", "hits", "U3 每天符合 `cash_paid_5y` 的檔數", "num"),
    ):
        part = report["hypotheses"].get(name, {}).get(key)
        if part:
            value = _pct(part["mean"], 1) if kind == "pct" else lib.num(part["mean"], 1)
            listed.append(f"- {label}：平均 {value}（{part['days']:,} 個訊號日）")
    saturdays = report["hypotheses"].get("U1", {}).get("saturdays")
    if saturdays is not None:
        listed.append(f"- U1 段內的 TWSE 週六補班日：{saturdays:,} 天")
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


seconds_lines = r10.seconds_lines

COVERAGE_NOTES = (
    "- 缺值比例的分母是母體檔次（每個訊號日的母體加總）；每個訊號日都數",
    f"- U1：{DEGENERATE['U1']}。分布（平均、p10／p50／p90、＝0、＝60）只算有值的檔次；"
    "「整天沒有法人資料的訊號日」是那個市場在訊號日當天沒有任何一檔有法人值的天數；"
    "`w1_order` 是同一個 T 算 W1 名單的時間，`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- U2：{DEGENERATE['U2']}。「可排名產業」是有效成員至少 5 檔的產業；"
    "「屬於多個產業的檔次」是母體中當天屬於兩個以上產業的檔次（加總都算它，排序鍵取 `group_id` 最小的）；"
    "`m1_groups` 是同一個 T 算 M1 前 5 族群的時間，`--coverage-only` 不算比例",
    f"- U3：{DEGENERATE['U3']}。`v3_order` 是同一個 T 算 V3 名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 U1～U3 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round13_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、市場整天沒有法人資料的日子 "
        f"{load_seconds.get('market_gaps', 0):.0f} 秒、成員表 {load_seconds.get('members', 0):.0f} 秒、"
        f"除權息 {load_seconds.get('actions', 0):.0f} 秒），"
        f"峰值記憶體 {lib.num(body.get('peak_memory_gb'), 2)} GB，"
        f"日線 {body.get('bars', 0):,} 根",
        ms._members_line(),
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
            *coverage_lines(name, row["coverage"]),
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
        "engines": {"portfolio_research": "simulate"},
        "members_sha256": ms.MEMBERS_SHA256,
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
    members: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``--coverage-only``: counts of the exploration, no return."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, members, LOAD_FROM, end, out / RAW_DIR_NAME)
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
    members: Path,
    command: str = "",
    progress: Callable[[str], None] = lambda text: None,
) -> dict[str, Any]:
    """``names`` on the exploration segment; nothing after its end read."""

    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    end = SEGMENTS[EXPLORATION][1]
    ctx = load(db, members, LOAD_FROM, end, out / RAW_DIR_NAME)
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
    members: Path,
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
    ctx = load(db, members, LOAD_FROM, end, out / RAW_DIR_NAME)
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
        used_ctx = load(db, members, LOAD_FROM, SEGMENTS[USED][1], out / RAW_DIR_NAME)
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
    parser = argparse.ArgumentParser(prog="round13_research.py", description=__doc__)
    parser.add_argument(
        "--db", required=True, help="the research DB (/research/stock.db)"
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--segment", required=True, choices=STAGES)
    parser.add_argument("--min-free-gb", type=float, default=2.0)
    parser.add_argument(
        "--members",
        help="the #779 member table (default: research/industry_members/"
        f"{ms.MEMBERS_NAME} beside the DB); its sha256 must be MEMBERS_SHA256",
    )
    parser.add_argument(
        "--coverage-only",
        action="store_true",
        help="exploration only: counts of dates, members and missing values per "
        "year and the time of the features, no return",
    )
    parser.add_argument(
        "--hypotheses",
        help="exploration (required, not with --coverage-only): U1, U2, U3 or "
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
    members = Path(args.members) if args.members else ms.members_path(db)
    problems = [*er.refusals(db, args.min_free_gb), *ms.members_problems(members)]
    names: list[str] = []
    if args.segment == EXPLORATION and not args.coverage_only:
        chosen, names = ex.exploration_problems(
            db, args.hypotheses, HYPOTHESES, VERSION
        )
        problems = [*problems, *chosen]
    if problems:
        print(json.dumps({"refused": problems}, ensure_ascii=False))
        return 2
    command = "python tools/research/round13_research.py " + " ".join(argv)
    progress = lambda text: print(text, file=sys.stderr, flush=True)  # noqa: E731
    if args.segment == EXPLORATION:
        if args.coverage_only:
            line = run_coverage(db, Path(args.out), members, command, progress=progress)
        else:
            line = run_exploration(
                db, Path(args.out), names, members, command, progress=progress
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
            members,
            command,
            progress=progress,
        )
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
