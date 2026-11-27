"""Round 11 of the new-strategy exploration: L1～L4 (#953).

docs/spec/evidence.md 第十一輪：L1～L4 and 第十一輪實作釋義: the hypotheses
were registered (commit ``5353b141``, #950, decision 7073170913) before anyone
ran a tool on the backfilled history.  Nothing here is a command-line option:
a change of a definition is a new code.

They are not in ``explore_research.HYPOTHESES``, ``trade_research.HYPOTHESES``
nor ``round4_research`` .. ``round10_research``: their ``definitions_sha256``
hash the whole table, so adding them would make the validation refuse the
exploration reports already run.  L2, L3 and L4 trade on the portfolio engine
(``portfolio_research.simulate``) with the population, the loading
(``explore_research.load_context``), ``explore_judge``, the order
(``round5_research.order_key``), ``institutional_flow_20``
(``feature_evidence``'s, as X3 reads it), ``margin_flow_20`` and
``turnover_60`` (``round7_research``), the industries
(``mainstream_research.group_members``), the gate and the ledgers imported; L1
is judged trade by trade with ``trade_research``'s trades (``TradeBars``,
``settle``, ``baseline``, ``stats``, the occupancy of ``State``) and
``round9_research``'s exit without a stop or a target (``enter_next_open``,
``NO_STOP``, ``trade_context``).  L3's overlap with H2 is
``round10_research``'s (``x2_names``, ``overlap_share``,
``overlap_summary``).  New here are only ``limit_down_close``, L2's
composite order, ``price_raw``, ``ret_5``, L4's leaders and followers, and
the count of L4's industries.

Each signal date T (after its close, only T's data and before):

- L1: every member of the population (less the occupied ones) whose
  unadjusted close is at most T's limit-down price + 1e-9.  Bought at T+1's
  open (one session; not tradable or locked at limit up abandons it, locked
  at limit down fills), sold at the close of the 5th session counting the
  fill as the 1st.
- L2: the members with ``institutional_flow_20`` > 0 and ``margin_flow_20``
  < 0, ranked there on each (high first, small first); the mean of the two
  ranks small first.  Fewer than 20 leave cash.  N 20, K 20.
- L3: ``price_raw`` (T's unadjusted close) high first.  N 20, K 60.  Its
  daily list's overlap with X2 (H2) is listed only.
- L4: in each industry with ≥ 6 members in the population, the 3 with the
  largest ``turnover_60`` (both it and ``ret_5`` valued) lead; the others
  follow, ranked on the leaders' mean ``ret_5`` high first.  N 20, K 20.  The
  industries of the daily list are counted, listed only.

``explore_research.explore_judge`` judges with t ≥ 2 on the exploration and
the fixed Bonferroni t ≥ 3.261 (45 hypotheses) on the validation; L1 also
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
import mainstream_research as ms  # noqa: E402
import portfolio_research as pr  # noqa: E402
import round5_research as r5  # noqa: E402
import round7_research as r7  # noqa: E402
import round9_research as r9  # noqa: E402
import round10_research as r10  # noqa: E402
import trade_research as tr  # noqa: E402

VERSION = 1
DESIGN = "953"
TOOL = "round11_research"
REGISTRATION_COMMIT = "5353b141"
DECISION = "https://github.com/YiCheng0608/stock-lab/issues/950#issuecomment-7073170913"
EXPLORATION, VALIDATION, USED = ex.EXPLORATION, ex.VALIDATION, ex.USED
STAGES = ex.STAGES
SEGMENTS = dict(ex.SEGMENTS)
MIN_SEGMENT_DAYS = dict(ex.MIN_SEGMENT_DAYS)
MIN_T = ex.MIN_T  # the exploration's t ≥ 2
# docs 第十一輪 門檻: 1 − Φ(z) = 0.025 ÷ 45, z = 3.2608, 3.261 to the 3rd decimal;
# fixed, not computed when run.
VALIDATION_MIN_T = 3.261
ROUND = 11
ROUND_SIZE = 4
# X1～X8, S1～S3, R1～R2, M1～M2, C1～C4, V1～V3, W1～W4, Y1～Y4, Z1～Z4, B1～B3,
# F1～F4, L1～L4
CUMULATIVE = 45
MIN_DAYS = tr.MIN_DAYS  # L1: signal dates with a fill, per segment
OVERLAP = tr.OVERLAP
# Every segment reads the copy from its start, as round10_research: the
# windows here are short, but one rule for the three segments keeps the
# features of a later segment's first signal dates the exploration's.
LOAD_FROM = ex.LOAD_FROM
LOAD_RULE = "every segment from LOAD_FROM"
MIN_LOTS = lib.DEFAULT_MIN_LOTS
RAW_DIR_NAME = ex.RAW_DIR_NAME
POPULATION = pr.POPULATION
TAIEX = pr.TAIEX
PORTFOLIO, TRADE = "portfolio", "trade"
HIGH, LOW = r5.HIGH, r5.LOW

LIMIT_EPS = er.EPS  # L1: close ≤ limit down + 1e-9, as the engine's lock
FLOW_MIN = 0.0  # L2 (a): institutional_flow_20 > 0, strictly
MARGIN_MAX = 0.0  # L2 (b): margin_flow_20 < 0, strictly
RANK_WEIGHTS = (1, 1)  # L2: (r1 + r2) ÷ 2, the two ranks equally weighted
RET_WINDOW = 5  # L4: c[at] ÷ c[at − 5] − 1
LEADERS = 3  # L4: the leaders of an industry
MIN_MEMBERS = 6  # L4: members of the industry in T's population
# A member in several industries follows the one with the smallest group id
# (Y4's several_groups, PR #913 review); #953 決定 7073648898.
SEVERAL_GROUPS = "smallest group id"
# An industry's leaders are no followers: missing, last, not left out (#953
# 決定 7073649176).
LEADER_RULE = "missing, ranked last"
L1_START = date(2015, 6, 1)  # the first day of ±10%
L2_ANCHOR = date(2014, 12, 1)  # the OTC institutional table's first day
L4_START = date(2013, 2, 1)  # the member table's, as Y4
NO_STOP = r9.NO_STOP  # L1's exit has no stop and no target
OTC_ANCHOR = r5.OTC_ANCHOR

# The registration (docs 第十一輪：L1～L4), word for word.  ``start`` as
# ``explore_research``: ("session", anchor, n) is the n-th session counting the
# anchor (or the first session after it) as the first; ("date", d) the first
# session from d.  ``keys``: (feature, HIGH or LOW), a missing value last,
# ties by ``portfolio_research.tie_break``.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "L1": {
        "engine": TRADE,
        "kind": "event",  # trade_research._trade_row: hold counts from the fill
        "event": "limit_down_close",
        "direction": "事件：價格限制",
        "label": "T 日收盤等於跌停價（`limit_down_close`），全部符合的訊號；"
        "T+1 開盤成交（期限 1 日）、沒有停損與目標、持有 5 日",
        "market_filter": False,
        "entry_days": 1,
        "stop": None,
        "target": None,
        "hold": 5,
        "start": ("date", L1_START),
    },
    "L2": {
        "engine": PORTFOLIO,
        "direction": "籌碼：法人與散戶槓桿",
        "label": "`institutional_flow_20` > 0 且 `margin_flow_20` < 0，"
        "兩個名次的平均小者先",
        "rule": "daily",
        # (feature, ">" or "<", threshold), strictly; a missing value fails
        "conditions": (
            ("institutional_flow_20", ">", FLOW_MIN),
            ("margin_flow_20", "<", MARGIN_MAX),
        ),
        "ranks": (("institutional_flow_20", HIGH), ("margin_flow_20", LOW)),
        "score": LOW,  # the mean rank, small first
        "top": 20,
        "hold": 20,
        "start": ("session", L2_ANCHOR, 20),
    },
    "L3": {
        "engine": PORTFOLIO,
        "direction": "股價水準",
        "label": "`price_raw`（T 日未還原收盤）大者先",
        "rule": "daily",
        "keys": (("price_raw", HIGH),),
        "top": 20,
        "hold": 60,
        "start": ("session", OTC_ANCHOR, 20),
    },
    "L4": {
        "engine": PORTFOLIO,
        "direction": "產業內的資訊擴散",
        "label": "同產業龍頭 3 檔的 `lead_ret_5` 大者先選跟隨者",
        "rule": "daily",
        "leaders": (("turnover_60", HIGH),),  # LEADERS of them per industry
        "keys": (("lead_ret_5", HIGH),),
        "top": 20,
        "hold": 20,
        "start": ("date", L4_START),
    },
}
OTHER_COMPARISONS = ex.OTHER_COMPARISONS
REASONS = dict(tr.REASONS)  # explore_research's and too_few_trade_days
LIMITS = {
    "L1": "逐筆平均假設每個訊號都買得到、每筆等額，不是一個帳戶的資金曲線；"
    "急跌日的訊號多，各筆持有期間高度重疊",
    "L2": "融資減少也可能是散戶停損或現金償還；三大法人的買超也可能買自其他法人，"
    "DB 分不出交易的對手；不足 20 檔的日子留現金，平均投入比例可能偏低，是登記時事先定的規則",
    "L3": "盤中零股交易 2020-10-26 開放，在驗證段裡，之後散戶買高價股的限制變小，機制可能減弱；"
    "少數公司改過面額或分割，名目股價跟著跳；"
    "名目股價和公司規模、品質、近一年漲多少都相關，L3 可能沾到 X2（H2），看和 H2 名單的重疊比例",
    "L4": "上市的分類是現在（或下市前最後）的分類回填，上櫃是當時的分類，同 Y4；"
    "DB 沒有市值，龍頭用成交金額選；成員表到 2024-09，已用段一律用最後一份；"
    "不設每個產業的上限，前 20 名多半集中在 1～2 個產業",
}
# The degenerate cases as the code judges them (第十一輪實作釋義; PR #913
# review: the docs, coverage.md and summary.md say the same words, a test
# reads the docs' tool section for them).
DEGENERATE = {
    "L1": "T 或前一根停牌、收盤缺值或 ≤ 0，或算不出跌停價時不符合",
    "L2": "`institutional_flow_20` 或 `margin_flow_20` 任一個缺值時條件不符合；"
    "剛好等於 0 也不符合",
    "L3": "T 那一根的未還原收盤缺值或 ≤ 0 時 `price_raw` 缺值、排最後",
    "L4": "`ret_5` 任一端停牌、缺值或 ≤ 0 時缺值；"
    "湊不到 3 檔龍頭或母體成員 < 6 檔的產業，跟隨者缺值、排最後；"
    "龍頭本身與不屬於任何產業的檔缺值、排最後；"
    "同時屬於幾個產業的檔，以 `group_id` 最小的那個為所屬產業（每個產業的組成都算它）",
}
ABANDON_LABELS = r9.ABANDON_LABELS
FEATURE_LABELS = {
    "limit_down_close": "收盤等於跌停價",
    "institutional_flow_20": "三大法人 20 日淨買超 ÷ 均量",
    "margin_flow_20": "融資 20 根變化 ÷ 均量",
    "price_raw": "未還原收盤",
    "ret_5": "5 日報酬",
    "turnover_60": "60 日平均成交金額",
    "lead_ret_5": "同產業龍頭 3 檔的平均 5 日報酬",
}


def definitions() -> dict[str, Any]:
    return {
        "version": VERSION,
        "design": DESIGN,
        "hypotheses": HYPOTHESES,
        "features": {
            "limit_down_close": {
                "value": "T's unadjusted close <= the lower bound of "
                "portfolio_research.Market.limits + eps (exit_research.price_limits "
                "on T, tick_ceil)",
                "eps": LIMIT_EPS,
                "missing": "T or the bar before suspended; a close missing or <= 0; "
                "no limit: does not qualify",
            },
            "institutional_flow_20": {
                "function": "explore_research.FEATURES (feature_evidence._flow)",
                "institutions": list(features.INSTITUTIONS),
                "feature_evidence": features.SHARED_VERSION,
                "explore_research": [ex.VERSION, ex.DESIGN],
            },
            "margin_flow_20": {
                "function": "round7_research.margin_flow_20",
                "window": r7.MARGIN_WINDOW,
                "lot_shares": r7.LOT_SHARES,
                "round7_research": [r7.VERSION, r7.DESIGN],
            },
            "conditions": {
                "rule": "each strictly beyond its threshold (> or <); a missing "
                "value does not qualify",
                "flow_min": FLOW_MIN,
                "margin_max": MARGIN_MAX,
            },
            "composite": {
                "ranks": "1 .. among the members meeting the conditions by each "
                "key, ties by the hash",
                "weights": list(RANK_WEIGHTS),
                "score": "sum(weight * rank) / sum(weight), ties by the hash",
            },
            "price_raw": {
                "value": "market_bars.close of T's bar (unadjusted)",
                "missing": "missing or <= 0",
            },
            "ret_5": {
                "value": "c[at] / c[at-window] - 1 (adjusted closes)",
                "window": RET_WINDOW,
                "missing": "at < window; either end suspended, missing or <= 0",
            },
            "turnover_60": {
                "function": "round7_research.turnover_60 (explore_research.turnover_60)",
                "window": ex.TURNOVER_WINDOW,
                "available": ex.TURNOVER_AVAILABLE,
            },
            "lead_ret_5": {
                "groups": "mainstream_research.group_members (snapshot_date <= T)",
                "leaders": LEADERS,
                "leader_order": "the members of the group in T's population with "
                "turnover_60 and ret_5, by the hypothesis's leaders key, ties by "
                "the hash",
                "value": "the mean ret_5 of the leaders",
                "min_members": MIN_MEMBERS,
                "follower": "a member of T's population in a usable group, not "
                "one of its leaders; ret_5 of its own not needed",
                "several_groups": SEVERAL_GROUPS,
                "leader": LEADER_RULE,
                "missing": "no group; the group with fewer than min_members in "
                "the population or fewer than leaders valued; a leader",
            },
        },
        "members": ms.definitions()["members"],
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
    thresholds, the windows, the leaders and the industries' floor, the
    orders, the composite rule, the member table, the segments, the costs).
    A changed tool needs a new exploration report before a validation."""

    text = json.dumps(definitions(), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- reading ----------------------------------------------------------------------


@dataclass
class Context:
    """``explore_research``'s context (the market, the turnovers, the quotes),
    the trade context on the same market (L1) and the member snapshots
    (``mainstream_research``'s context on the same market, L4).  One panel."""

    base: ex.Context
    trade: tr.Context
    groups: ms.Context | None = None
    seconds: Counter = field(default_factory=Counter)
    load_seconds: dict[str, float] = field(default_factory=dict)

    @property
    def market(self) -> pr.Market:
        return self.base.market

    @property
    def panel(self) -> lib.Panel:
        return self.base.market.panel

    def quote(self, instrument_id: int, s: int) -> pr.Quote | None:
        return self.base.quote(instrument_id, s)


def load(db: Path, members: Path, start: date, end: date, raw_dir: Path) -> Context:
    """The panel, the turnovers, the trade context and the member snapshots
    to ``end``; nothing after ``end`` is read but the date of a delisted or
    transferred stock's last bar (no price)."""

    started = time.monotonic()
    base = ex.load_context(db, start, end, raw_dir)
    panel_seconds = time.monotonic() - started
    t0 = time.monotonic()
    trade = r9.trade_context(base.market, db, end)
    trade_seconds = time.monotonic() - t0
    t0 = time.monotonic()
    groups = ms.build_context(base.market, ms.read_members(members, end))
    return Context(
        base,
        trade,
        groups,
        load_seconds={
            "panel": panel_seconds,
            "trade": trade_seconds,
            "members": time.monotonic() - t0,
        },
    )


# --- features ---------------------------------------------------------------------


def limit_down_price(
    market: pr.Market, item: lib.Series, at: int
) -> tuple[float, float] | None:
    """(T's unadjusted close, T's limit-down price), or None (docs 第十一輪 L1
    第 1、2 點): T or the bar before suspended, a close missing or ≤ 0, no
    limit.  ``round9_research.limit_up_price`` with the other bound."""

    if at < 1 or item.is_suspended(at) or item.is_suspended(at - 1):
        return None
    raw_close = market.raw[item.instrument_id][2][at]
    if not raw_close > 0 or not item.close[at] > 0 or not item.close[at - 1] > 0:
        return None
    bounds = market.limits(item.instrument_id, at)  # the bar before is at − 1
    if bounds is None:
        return None
    return raw_close, bounds[0]


def limit_down_close(market: pr.Market, item: lib.Series, at: int) -> bool | None:
    """L1 第 1 點: None when it cannot be told (does not qualify)."""

    parts = limit_down_price(market, item, at)
    if parts is None:
        return None
    return parts[0] <= parts[1] + LIMIT_EPS


def institutional_flow_20(ctx: Context, item: lib.Series, at: int) -> float | None:
    """L2 第 1 點: ``feature_evidence``'s, as X3 and X6 read it."""

    return ex.FEATURES["institutional_flow_20"](ctx.base, item, at)


def margin_flow_20(ctx: Context, item: lib.Series, at: int) -> float | None:
    """L2 第 2 點: ``round7_research``'s (Y1's)."""

    return r7.margin_flow_20(ctx, item, at)


def price_raw(ctx: Context, item: lib.Series, at: int) -> float | None:
    """L3 第 1 點: T's ``market_bars.close``; missing or ≤ 0 is missing."""

    value = ctx.market.raw[item.instrument_id][2][at]
    return float(value) if value > 0 else None  # NaN fails too


def ret_5(item: lib.Series, at: int) -> float | None:
    """L4 第 2 點: c[at] ÷ c[at − 5] − 1 (adjusted); missing when either end
    is suspended, missing or ≤ 0."""

    back = at - RET_WINDOW
    if back < 0 or item.is_suspended(at) or item.is_suspended(back):
        return None
    a, b = item.close[back], item.close[at]
    if not (a > 0 and b > 0):
        return None
    return b / a - 1.0


def turnover_60(ctx: Context, item: lib.Series, at: int) -> float | None:
    """L4 第 2 點: ``round7_research``'s (``explore_research.turnover_60``)."""

    return r7.turnover_60(ctx, item, at)


# --- L4: the leaders and the followers --------------------------------------------


@dataclass
class Follow:
    value: float | None  # lead_ret_5 of its group, None when missing
    group: str | None  # its own group (the smallest id of its groups)
    reason: str | None  # no_group, unusable, leader; None with a value
    groups: int = 0  # how many groups it is in on T


@dataclass
class IndustryDay:
    follow: dict[int, Follow] = field(default_factory=dict)
    usable: dict[str, float] = field(default_factory=dict)  # group -> lead_ret_5
    leaders: dict[str, list[int]] = field(default_factory=dict)
    groups: int = 0  # groups with a member in T's population


def industry_day(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> IndustryDay:
    """L4 第 1～5 點 on T's population."""

    out = IndustryDay()
    at_of = {item.instrument_id: (item, at) for item, at in members}
    grouped: dict[str, set[int]] = {}
    if ctx.groups is not None:
        grouped = ms.group_members(ctx.groups, day)[0]
    t0 = time.perf_counter()
    ret: dict[int, float | None] = {}
    turnover: dict[int, float | None] = {}

    def values(instrument_id: int) -> tuple[float | None, float | None]:
        if instrument_id not in ret:
            item, at = at_of[instrument_id]
            ret[instrument_id] = ret_5(item, at)
            turnover[instrument_id] = turnover_60(ctx, item, at)
        return turnover[instrument_id], ret[instrument_id]

    groups_of: dict[int, list[str]] = defaultdict(list)
    keys = tuple(spec["leaders"])
    for group_id, ids in sorted(grouped.items()):
        inside = sorted(i for i in ids if i in at_of)
        if not inside:
            continue
        out.groups += 1
        for instrument_id in inside:
            groups_of[instrument_id].append(group_id)
        if len(inside) < MIN_MEMBERS:
            continue
        valued = []
        for instrument_id in inside:
            t, r = values(instrument_id)
            if t is not None and r is not None:
                tie = pr.tie_break(day, instrument_id)
                valued.append((instrument_id, {"turnover_60": t, "ret_5": r}, tie))
        if len(valued) < LEADERS:
            continue
        valued.sort(key=lambda row: order_key(row[1], keys, row[2]))
        top = valued[:LEADERS]
        out.usable[group_id] = statistics.fmean(row[1]["ret_5"] for row in top)
        out.leaders[group_id] = [row[0] for row in top]
    ctx.seconds["ret_5+turnover_60"] += time.perf_counter() - t0
    for instrument_id in at_of:
        groups = groups_of.get(instrument_id)
        if not groups:
            out.follow[instrument_id] = Follow(None, None, "no_group")
            continue
        group = min(groups)
        if group not in out.usable:
            reason, value = "unusable", None
        elif instrument_id in out.leaders[group]:
            reason, value = "leader", None
        else:
            reason, value = None, out.usable[group]
        out.follow[instrument_id] = Follow(value, group, reason, len(groups))
    return out


# --- L2, L3 and L4: the portfolio engine ------------------------------------------


order_key = r5.order_key
_window_facts = r5._window_facts


def segment_window(
    sessions: list[date], segment: str, spec: dict[str, Any]
) -> tuple[int, int] | None:
    """(first, last) index of the sessions with an equity value (or, for L1,
    the sessions after a signal date), or None (``round10_research``'s
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
    hits: int = 0  # L2: members meeting both conditions
    usable: int = 0  # L4: usable groups
    groups: int = 0  # L4: groups with a member in the population
    groups_of: dict[int, str] = field(default_factory=dict)  # L4: the followers'
    valued: int = 0  # L4: followers with a value
    filled: Counter = field(default_factory=Counter)  # L4: missing ones in the top


def meets(value: float | None, op: str, bound: float) -> bool:
    """L2 第 3 點: strictly beyond ``bound``; a missing value fails."""

    if value is None:
        return False
    return value > bound if op == ">" else value < bound


def rank_l2(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """L2 第 3、4 點: the members meeting both conditions, the two ranks among
    them, the mean rank small first."""

    out = Ranked([])
    kept = []
    for item, at in members:
        t0 = time.perf_counter()
        flow = institutional_flow_20(ctx, item, at)
        t1 = time.perf_counter()
        margin = margin_flow_20(ctx, item, at)
        ctx.seconds["institutional_flow_20"] += t1 - t0
        ctx.seconds["margin_flow_20"] += time.perf_counter() - t1
        values = {"institutional_flow_20": flow, "margin_flow_20": margin}
        for name, value in values.items():
            out.missing[name] += value is None
        if all(
            meets(values[name], op, bound) for name, op, bound in spec["conditions"]
        ):
            kept.append(
                (item.instrument_id, values, pr.tie_break(day, item.instrument_id))
            )
    t0 = time.perf_counter()
    out.hits = len(kept)
    ranks: dict[int, list[int]] = {row[0]: [] for row in kept}
    for name, direction in spec["ranks"]:
        ordered = sorted(
            kept, key=lambda row: order_key(row[1], ((name, direction),), row[2])
        )
        for place, row in enumerate(ordered, 1):
            ranks[row[0]].append(place)
    weight = sum(RANK_WEIGHTS)
    scored = []
    for instrument_id, values, tie in kept:
        mine = ranks[instrument_id]
        score = Fraction(sum(w * r for w, r in zip(RANK_WEIGHTS, mine)), weight)
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
    ctx.seconds["l2_order"] += time.perf_counter() - t0
    return out


def rank_l3(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """L3 第 1、2 點: the population, ``price_raw`` high first, missing last."""

    out = Ranked([])
    rows = []
    t0 = time.perf_counter()
    for item, at in members:
        value = price_raw(ctx, item, at)
        out.missing["price_raw"] += value is None
        rows.append(
            (
                item.instrument_id,
                {"price_raw": value},
                pr.tie_break(day, item.instrument_id),
            )
        )
    ctx.seconds["price_raw"] += time.perf_counter() - t0
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    return out


def rank_l4(
    ctx: Context, spec: dict[str, Any], day: date, members: list[tuple[lib.Series, int]]
) -> Ranked:
    """L4 第 3～5 點: the population, the followers by their group's
    ``lead_ret_5`` high first, everyone else missing and last."""

    out = Ranked([])
    t0 = time.perf_counter()
    industry = industry_day(ctx, spec, day, members)
    out.usable, out.groups = len(industry.usable), industry.groups
    rows = []
    for item, _at in members:
        follow = industry.follow[item.instrument_id]
        if follow.reason is not None:
            out.missing[follow.reason] += 1
        out.missing["lead_ret_5"] += follow.value is None
        out.missing["several_groups"] += follow.groups > 1
        if follow.value is not None:
            out.groups_of[item.instrument_id] = follow.group
        rows.append(
            (
                item.instrument_id,
                {"lead_ret_5": follow.value, "group": follow.group},
                pr.tie_break(day, item.instrument_id),
            )
        )
    keys = tuple(spec["keys"])
    rows.sort(key=lambda row: order_key(row[1], keys, row[2]))
    out.rows = rows
    out.valued = len(out.groups_of)
    # the missing ones the list takes in when fewer than N followers have a
    # value (#953 決定 7073649176): the leaders apart from the others
    for instrument_id, values, _tie in rows[: spec["top"]]:
        if values["lead_ret_5"] is None:
            reason = industry.follow[instrument_id].reason
            out.filled["leader" if reason == "leader" else "other"] += 1
    ctx.seconds["l4_order"] += time.perf_counter() - t0
    return out


def ranker(name: str) -> Callable[..., Ranked]:
    return {"L2": rank_l2, "L3": rank_l3, "L4": rank_l4}[name]


PICK_FIELDS = {
    "L2": ("institutional_flow_20", "margin_flow_20", "r1", "r2", "score"),
    "L3": ("price_raw",),
    "L4": ("lead_ret_5", "group"),
}


@dataclass
class Plan:
    picks: dict[int, list[int]] = field(default_factory=dict)
    population: dict[int, list[int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    signal_days: int = 0
    overlap: dict[str, list[float]] = field(default_factory=dict)  # L3, by year
    industries: dict[str, list[int]] = field(default_factory=dict)  # L4, by year


def _coverage_add(
    coverage: dict[str, Any], name: str, day: date, members: int, r: Ranked
) -> None:
    year = coverage.setdefault(str(day.year), {"days": 0, "members": 0, "missing": {}})
    year["days"] += 1
    year["members"] += members
    for key, count in r.missing.items():
        year["missing"][key] = year["missing"].get(key, 0) + count
    if name == "L2":
        year["hits"] = year.get("hits", 0) + r.hits
        year["hit_days"] = year.get("hit_days", 0) + (r.hits > 0)
        year["over_top_days"] = year.get("over_top_days", 0) + (
            r.hits > HYPOTHESES[name]["top"]
        )
        year["max_hits"] = max(year.get("max_hits", 0), r.hits)
    elif name == "L4":
        year["usable"] = year.get("usable", 0) + r.usable
        year["groups"] = year.get("groups", 0) + r.groups
        year["min_usable"] = min(year.get("min_usable", r.usable), r.usable)
        year["short_days"] = year.get("short_days", 0) + (
            r.valued < HYPOTHESES[name]["top"]
        )
        for key in ("leader", "other"):
            year[f"filled_{key}"] = year.get(f"filled_{key}", 0) + r.filled[key]


def industry_count(names: list[int], groups_of: dict[int, str]) -> int | None:
    """L4 第 7 點: the industries of the day's list (the followers'); None
    without a list."""

    if not names:
        return None
    return len({groups_of[i] for i in names if i in groups_of})


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
        _coverage_add(out.coverage, name, day, len(members), ranked)
        out.signal_days += 1
        if name == "L3":
            x2 = r10.x2_names(ctx, day, members)  # timed in the coverage too
            if keep_rows:
                share = r10.overlap_share([row[0] for row in ranked.rows[:top]], x2)
                if share is not None:
                    out.overlap.setdefault(str(day.year), []).append(share)
        if not keep_rows:
            continue
        if name == "L4":
            count = industry_count(
                [row[0] for row in ranked.rows[:top]], ranked.groups_of
            )
            if count is not None:
                out.industries.setdefault(str(day.year), []).append(count)
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


overlap_summary = r10.overlap_summary


def industries_summary(by_year: dict[str, list[int]]) -> dict[str, Any]:
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
    """L2, L3 or L4 on one segment: its numbers, verdict and private parts."""

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
    if name == "L3":
        result["overlap"] = overlap_summary(planned.overlap)
    if name == "L4":
        result["industries"] = industries_summary(planned.industries)
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


# --- L1: trade by trade -----------------------------------------------------------


enter_next_open = r9.enter_next_open


@dataclass
class EventState:
    """L1's run: ``trade_research.State`` (the trades, the occupancy) plus the
    signals by year and the fills on a T+1 locked at limit down."""

    state: tr.State
    years: dict[str, Counter] = field(default_factory=dict)
    locked_down_fills: int = 0


def _signals(
    ctx: Context, s: int, members: list[tuple[lib.Series, int]]
) -> list[tuple[lib.Series, int, dict[str, Any]]]:
    """L1's signals of signal date ``s`` among ``members`` (item, at, extra)."""

    out = []
    t0 = time.perf_counter()
    market = ctx.market
    for item, at in members:
        parts = limit_down_price(market, item, at)
        if parts is not None and parts[0] <= parts[1] + LIMIT_EPS:
            out.append((item, at, {"close_raw": parts[0], "limit_down": parts[1]}))
    ctx.seconds["limit_down_close"] += time.perf_counter() - t0
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
        # L1 第 3 點: a T+1 locked at limit down fills at its open, listed apart
        locked_down = entry.session is not None and bars[0].locked_down
        run.locked_down_fills += locked_down
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
    """L1 on one segment (docs 逐筆評估): its numbers, verdict and trades."""

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


# --- --coverage-only for L1 -------------------------------------------------------


def event_coverage(ctx: Context) -> dict[str, Any]:
    """L1: by year the signals (also by exchange) and the signal dates.  Every
    signal date counts, without the occupancy (nothing is traded)."""

    spec = HYPOTHESES["L1"]
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
            {"days": 0, "signal_days": 0, "signals": 0, "members": 0, "unknown": 0,
             "markets": {}},
        )  # fmt: skip
        year["days"] += 1
        members = lib.universe(panel, day, MIN_LOTS)
        year["members"] += len(members)
        signals = _signals(ctx, s, members)
        t0 = time.perf_counter()
        year["unknown"] += sum(
            1 for item, at in members if limit_down_price(ctx.market, item, at) is None
        )
        ctx.seconds["limit_down_close"] += time.perf_counter() - t0
        year["signal_days"] += bool(signals)
        year["signals"] += len(signals)
        for item, _at, _extra in signals:
            exchange = panel.symbols.get(item.instrument_id, ("", "", ""))[0]
            m = year["markets"].setdefault(exchange, Counter())
            m["signals"] += 1
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
EVENT_FIELDS = {"L1": ("close_raw", "limit_down", "t1_locked_down")}
EVENT_TRADE_TAIL = r10.EVENT_TRADE_TAIL


def event_trade_fields(name: str) -> tuple[str, ...]:
    return ("signal_date", "exchange", "symbol", *EVENT_FIELDS[name], *EVENT_TRADE_TAIL)


def _threshold_line(segment: str, min_t: float) -> str:
    return (
        f"- 門檻：超額日均 > 0 且 t ≥ {threshold(min_t)}，且絕對報酬日均 > 0；"
        f"段長下限 {MIN_SEGMENT_DAYS.get(segment, '—')} 日；研究 DB 要有段內已下市公司；"
        f"L1 另要有成交的訊號日至少 {MIN_DAYS} 日（逐筆評估）。"
        f"探索段 t ≥ {threshold(MIN_T)}，驗證段 t ≥ {threshold(VALIDATION_MIN_T)}"
        f"（Bonferroni，累計 {CUMULATIVE} 個：1 − Φ(z)＝0.025 ÷ {CUMULATIVE}，寫死不重算）"
    )


def portfolio_coverage_lines(name: str, coverage: dict[str, Any]) -> list[str]:
    """L2 第 8 點: the members meeting (a)(b) and the days with at least one;
    L3: ``price_raw``'s missing share; L4: the usable industries and the
    followers' missing share (分母是母體檔次)."""

    if name == "L2":
        head = [
            "年",
            "日數",
            "母體檔次",
            "符合 (a)(b) 的檔日",
            "至少一檔符合的訊號日",
            "一天最多",
            "超過 20 檔的天數",
            "`institutional_flow_20` 缺值",
            "`margin_flow_20` 缺值",
        ]
    elif name == "L3":
        head = ["年", "日數", "母體檔次", "`price_raw` 缺值"]
    else:
        head = [
            "年",
            "日數",
            "母體檔次",
            "可用產業（每日平均）",
            "可用產業（最少的一天）",
            "有母體成員的產業（每日平均）",
            "跟隨者缺值",
            "其中不屬於任何產業",
            "其中產業不可用",
            "其中是龍頭",
            "同時屬於幾個產業的檔次",
            "有值的跟隨者不足 20 檔的訊號日",
            "補進名單的龍頭檔次",
            "補進名單的其他缺值檔次",
        ]
    lines = [
        "| " + " | ".join(head) + " |",
        "| --- | " + " | ".join("---:" for _ in head[1:]) + " |",
    ]
    for year, row in sorted(coverage.items()):
        members, days = row["members"], row["days"]
        missing = row.get("missing", {})
        cells = [f"{days:,}", f"{members:,}"]
        if name == "L2":
            cells += [
                f"{row.get('hits', 0):,}",
                f"{row.get('hit_days', 0):,}",
                f"{row.get('max_hits', 0):,}",
                f"{row.get('over_top_days', 0):,}",
                _share(missing.get("institutional_flow_20", 0), members),
                _share(missing.get("margin_flow_20", 0), members),
            ]
        elif name == "L3":
            cells += [_share(missing.get("price_raw", 0), members)]
        else:
            cells += [
                lib.num(row.get("usable", 0) / days, 1) if days else "—",
                f"{row.get('min_usable', 0):,}",
                lib.num(row.get("groups", 0) / days, 1) if days else "—",
                _share(missing.get("lead_ret_5", 0), members),
                _share(missing.get("no_group", 0), members),
                _share(missing.get("unusable", 0), members),
                _share(missing.get("leader", 0), members),
                f"{missing.get('several_groups', 0):,}",
                f"{row.get('short_days', 0):,}",
                f"{row.get('filled_leader', 0):,}",
                f"{row.get('filled_other', 0):,}",
            ]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    return lines


def event_coverage_lines(coverage: dict[str, Any]) -> list[str]:
    lines = [
        "| 年 | 訊號日 | 有訊號的日數 | 訊號數 | 上市 | 上櫃 | 母體檔次 "
        "| 算不出跌停價（不符合） |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for year, row in coverage.get("years", {}).items():
        m = row["markets"]
        lines.append(
            f"| {year} | {row['days']:,} | {row['signal_days']:,} | {row['signals']:,} "
            f"| {m.get('TWSE', {}).get('signals', 0):,} "
            f"| {m.get('TPEx', {}).get('signals', 0):,} | {row['members']:,} "
            f"| {_share(row['unknown'], row['members'])} |"
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
        f"# {name} {segment}（round11_research 第 {VERSION} 版，#{DESIGN}）",
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
    'L3 與 H2（X2，`explore_research` 第 2 版的 `HYPOTHESES["X2"]`）每日名單的重疊比例：'
    "|L3 的前 20 名 ∩ X2 的前 20 名| ÷ L3 當天的名單檔數；L3 或 X2 當天沒有名單的日子不計。"
    "只列出、不判定"
)


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
    if "overlap" in result:
        lines += _yearly_lines(
            "## 和 H2 的重疊（L3 第 4 點）",
            OVERLAP_NOTE,
            result["overlap"],
            lambda value: _pct(value, 1),
        )
    if "industries" in result:
        lines += _yearly_lines(
            "## 名單涉及的產業數（L4 第 7 點）",
            "L4 每天名單涉及的產業數：每個訊號日 T 的前 20 名裡，有值的跟隨者所屬產業的個數；"
            "沒有名單的日子不計。只列出、不判定",
            result["industries"],
            lambda value: lib.num(value, 2),
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
    lines.append(
        f"| T+1 跌停鎖死、照常以開盤價成交 | {listed.get('t1_locked_down_fills', 0):,} |"
    )
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
        if "t1_locked_down_fills" in listed:
            row["t1_locked_down_fills"] = listed["t1_locked_down_fills"]
        return row
    row = {"engine": PORTFOLIO, **r5._row(result)}
    if "overlap" in result:
        row["overlap_x2"] = {key: result["overlap"][key] for key in ("days", "mean")}
    if "industries" in result:
        row["industries"] = {key: result["industries"][key] for key in ("days", "mean")}
    return row


def overview_markdown(report: dict[str, Any], sha256: str) -> str:
    segment = report["segment"]
    stage = SEGMENT_NAMES[segment]
    lines = [
        f"explore.json 的 sha256：`{sha256}`",
        "",
        f"# 新策略探索 第 {report['round']} 輪 {stage}（round11_research 第 {VERSION} 版，#{DESIGN}）",
        "",
        f"- 登記 commit `{REGISTRATION_COMMIT}`（docs/spec/evidence.md「第十一輪：L1～L4」）：{DECISION}",
        f"- 定義雜湊 `{report['definitions_sha256']}`",
        f"- 比較次數：本輪 {report['round_size']} 個、累計 {report['cumulative']} 個；另列："
        + "；".join(OTHER_COMPARISONS),
        _threshold_line(segment, report["min_t"]),
        "- 引擎：L2、L3、L4 是組合引擎（`portfolio_research.simulate`，日數是有淨值的交易日）；"
        "L1 是逐筆評估（`trade_research`，日數是段內交易日，超額與 t 在訊號日序列上）",
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
    overlap = report["hypotheses"].get("L3", {}).get("overlap_x2")
    if overlap:
        lines += [
            "",
            f"L3 和 H2 的重疊（只列出）：平均 {_pct(overlap['mean'], 1)}"
            f"（{overlap['days']:,} 個訊號日）。",
        ]
    industries = report["hypotheses"].get("L4", {}).get("industries")
    if industries:
        lines += [
            "",
            f"L4 名單涉及的產業數（只列出）：平均 {lib.num(industries['mean'], 2)}"
            f"（{industries['days']:,} 個訊號日）。",
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
    f"- L1：`limit_down_close`：{DEGENERATE['L1']}。訊號數是母體中 `limit_down_close` 成立的檔次；"
    "「算不出跌停價」是母體中因上述情況不符合的檔次",
    f"- L2：{DEGENERATE['L2']}。「符合 (a)(b) 的檔日」是兩個條件都成立的檔次（L2 第 8 點）",
    f"- L3：{DEGENERATE['L3']}。`x2_order` 是同一個 T 算 X2（H2）名單的時間，"
    "`--coverage-only` 不算重疊比例，各段的 `summary.md` 才列",
    f"- L4：{DEGENERATE['L4']}。「可用產業」是母體成員 ≥ 6 檔、湊得到 3 檔龍頭的產業；"
    "「跟隨者缺值」是母體中 `lead_ret_5` 缺值的檔次，另分三種原因；"
    "有值的跟隨者不足 20 檔的日子，名單依雜湊補進缺值的檔，補進的龍頭與其他缺值檔分開計",
    "- 各假設用自己的訊號日（起日寫在各段標題）",
)


def coverage_markdown(body: dict[str, Any]) -> str:
    load_seconds = body.get("load_seconds_parts", {})
    lines = [
        f"# 新策略探索 第 {body['round']} 輪 L1～L4 資料覆蓋（探索段，不含報酬）",
        "",
        f"- round11_research 第 {VERSION} 版；定義雜湊 `{body['definitions_sha256']}`",
        f"- 讀取的資料到 {body['read_until']}；副本最新交易日 {body['copy']['latest']}，"
        f"alembic `{body['copy']['alembic']}`",
        f"- 重現：`{body['command']}`",
        f"- 耗時 {body.get('elapsed_seconds', 0):.0f} 秒（載入 {body.get('load_seconds', 0):.0f} 秒，"
        f"其中 panel {load_seconds.get('panel', 0):.0f} 秒、逐筆的標的狀態 "
        f"{load_seconds.get('trade', 0):.0f} 秒、成員表 {load_seconds.get('members', 0):.0f} 秒），"
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
        ]
        if HYPOTHESES[name]["engine"] == TRADE:
            lines += [
                "### L1：依年的訊號數與訊號日數",
                "",
                *event_coverage_lines(row["coverage"]),
                "",
            ]
        else:
            lines += [*portfolio_coverage_lines(name, row["coverage"]), ""]
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
        "members_sha256": ms.MEMBERS_SHA256,
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
    parser = argparse.ArgumentParser(prog="round11_research.py", description=__doc__)
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
        help="exploration (required, not with --coverage-only): L1, L2, L3, L4 or "
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
    command = "python tools/research/round11_research.py " + " ".join(argv)
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
